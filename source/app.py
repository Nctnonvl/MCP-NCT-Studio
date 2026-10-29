"""NCT Group Manager: local dashboard and Telegram controller; GUI worker is isolated."""
import base64
import datetime as dt
import json
import logging
import io
import mimetypes
import os
import re
import secrets
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from store import Store, group_url, interval_bounds, validate_link
from net import request_json
from telegram_transport import request_telegram
import media as media_store
import ai_provider
import content_ai
import media_library
import post_footer
import bot_ui
from studio import Studio

ROOT = Path(__file__).resolve().parent
from runtime_guard import code_revision
RUNTIME_REVISION = code_revision(ROOT)
DATA = Path(os.environ.get('NCT_DATA_DIR', str(ROOT / 'data'))).resolve()
DATA.mkdir(parents=True, exist_ok=True)
STORE = Store(DATA / 'manager.sqlite3')
__import__('deployment').prepare(STORE,DATA)
__import__('facebook_accounts').bootstrap(STORE,DATA)
SHUTDOWN = threading.Event()
STOP_WORK = threading.Event()
WEB_KEY = secrets.token_urlsafe(32)
PORT = int(os.environ.get('NCT_PORT','8765'))
LOCAL = f'http://127.0.0.1:{PORT}'
logging.basicConfig(filename=DATA / 'app.log', level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
CONFIG_LOCK = threading.Lock()
PROCESS_LOCK = threading.Lock()
ACTIVE_PROCESS = None
GROUP_SCANNER = None

def group_scanner():
    global GROUP_SCANNER
    if GROUP_SCANNER is None:
        from group_scan import GroupScanner
        GROUP_SCANNER=GroupScanner(STORE,DATA)
    return GROUP_SCANNER
STUDIO = None


def load_config():
    raw = STORE.get('config', {})
    token = raw.get('token', '')
    if token.startswith('dpapi:'):
        import win32crypt
        token = win32crypt.CryptUnprotectData(base64.b64decode(token[6:]), None, None, None, 0)[1].decode()
    return {**raw, 'token': token, 'model': raw.get('model', 'qwen3:8b'), 'mode': raw.get('mode', 'prepare')}


def studio():
    global STUDIO
    if STUDIO is None or STUDIO.store is not STORE:
        STUDIO=Studio(STORE,load_config,DATA/'media',on_run=run_queue)
    return STUDIO


def apply_link_change(old,new,digest,facebook=False):
    with CONFIG_LOCK:
        if studio().lock.locked() or STORE.get('ai_busy',False):
            raise ValueError('AI đang tạo bài hoặc phân loại. Chờ xong rồi xem ảnh hưởng và thay link.')
        result=STORE.apply_links(old,new,digest,facebook)
        if result.get('facebook_count'):STOP_WORK.clear()
        else:
            STOP_WORK.set();STORE.set('approval_monitor_enabled',False)
        STORE.notify(f"🔗 Đã đổi link trong {result['content_count']} bài lưu và {result['job_count']} lượt chưa chạy. Hàng đợi đang tạm dừng. Cập nhật Facebook: {result.get('facebook_count',0)} bài trong 36 giờ gần nhất. /queue để xem; /run để tiếp tục lịch đã duyệt.")
        return result


def save_config(obj):
    with CONFIG_LOCK:
        old = load_config()
        token = str(obj.get('token') or old.get('token', '')).strip()
        if not re.fullmatch(r'\d+:[A-Za-z0-9_-]{20,}', token):
            raise ValueError('Token Telegram không đúng định dạng.')
        me = telegram('getMe', token=token)
        if old.get('token') and old['token'] != token:
            raise ValueError('Để đổi bot, dừng ứng dụng và đổi tên thư mục data trước khi chạy lại.')
        mode = obj.get('mode', old['mode'])
        if mode not in {'prepare', 'publish'}:
            raise ValueError('Chế độ không hợp lệ.')
        model = str(obj.get('model', old['model'])).strip()
        if not re.fullmatch(r'[A-Za-z0-9_.:/-]{1,100}', model) or 'cloud' in model.casefold() or '/' in model:
            raise ValueError('Chọn tên mô hình Ollama local, ví dụ qwen3:8b.')
        protected = token
        if os.name == 'nt':
            import win32crypt
            protected = 'dpapi:' + base64.b64encode(win32crypt.CryptProtectData(token.encode(), 'NCT Telegram', None, None, None, 0)).decode()
        STORE.set('config', {'token': protected, 'model': model, 'mode': mode, 'username': me['username']})
        STORE.set('running', False)
        STORE.set('control_revision',STORE.get('control_revision',0)+1)
        STOP_WORK.set();STORE.set('approval_monitor_enabled',False)
        return me['username']


def telegram(method, payload=None, token=None, timeout=30):
    token = token or load_config().get('token')
    if not token:
        raise ValueError('Chưa nhập token trên PC.')
    return request_telegram(token,method,payload or {},timeout)


def safe_error(exc):
    msg = str(exc)[:1500]
    try:
        token = load_config().get('token', '')
        if token:
            msg = msg.replace(token, '[TOKEN]')
        key=ai_provider.config(STORE,True).get('api_key')
        if key:msg=msg.replace(key,'[API_KEY]')
        for field in ('writer_key','vision_key'):
            key=content_ai.config(STORE,True).get(field)
            if key:msg=msg.replace(key,'[API_KEY]')
    except Exception:
        pass
    return re.sub(r'\b\d{6,}:[A-Za-z0-9_-]{20,}', '[TOKEN]', msg)


def timestamp(value):
    return dt.datetime.fromtimestamp(value, dt.timezone(dt.timedelta(hours=7))).strftime('%d/%m %H:%M:%S')


def queue_text():
    jobs = STORE.rows('SELECT * FROM jobs WHERE hidden=0 ORDER BY id DESC LIMIT 20')
    return '\n'.join(f"#{j['id']} · {j['state']} · {timestamp(j['due'])} · {j['group_name']}" for j in jobs) or 'Chưa có lượt đăng.'


def queue_progress():
    if STORE.rows("SELECT id FROM jobs WHERE state='working' LIMIT 1"):
        return STORE.get('progress','Đang khởi động bộ thao tác trình duyệt')
    if not STORE.get('running'):
        checks=STORE.rows("SELECT due FROM approval_checks WHERE state='waiting' ORDER BY due LIMIT 1")
        if __import__('approval_followup').enabled(STORE) and checks:
            return 'Đang theo dõi bài chờ duyệt; kiểm tra link tiếp theo lúc '+timestamp(checks[0]['due'])
        return STORE.get('progress','Đang tạm dừng. Tạo và duyệt một lượt rồi bấm Chạy.')
    if STORE.get('failure_cooldown_until',0)>time.time():
        return 'Nghỉ sau 3 lỗi liên tiếp đến '+timestamp(STORE.get('failure_cooldown_until'))+'; sẽ tự tiếp tục lịch.'
    if STORE.get('next_allowed',0)>time.time():
        return 'Nghỉ trước khi sang nhóm khác, đến '+timestamp(STORE.get('next_allowed'))
    rows=STORE.rows("SELECT j.*,g.enabled,g.next_post_after FROM jobs j JOIN groups g ON g.id=j.group_id WHERE j.state='queued' ORDER BY j.due,j.id")
    enabled=[j for j in rows if j['enabled']]
    if not enabled:return 'Chưa có lượt được duyệt trong nhóm đang bật.'
    ready=[j for j in enabled if j['due']<=time.time() and j['next_post_after']<=time.time()]
    if not ready:
        job=min(enabled,key=lambda j:max(j['due'],j['next_post_after']))
        return f"Chờ lượt #{job['id']} · {job['group_name']} · "+timestamp(max(job['due'],job['next_post_after']))
    return 'Đang kiểm tra giới hạn 1 bài/nhóm/ngày; lượt đủ điều kiện sẽ được mở trong trình duyệt.'


def status_text():
    rows = STORE.rows("SELECT state,COUNT(*) n FROM jobs WHERE hidden=0 GROUP BY state")
    watching=__import__('approval_followup').enabled(STORE) and bool(STORE.rows("SELECT job_id FROM approval_checks WHERE state IN ('waiting','working') LIMIT 1"))
    return ('NCT Group Manager\n' + ('▶ Đang chạy' if STORE.get('running') else '⌛ Đang theo dõi duyệt' if watching else '⏸ Đang tạm dừng') +
        f"\nChế độ: {load_config()['mode']}\nAI viết: {content_ai.config(STORE)['writer_provider']} · {content_ai.config(STORE)['writer_model'] if content_ai.config(STORE)['writer_provider']!='ollama' else load_config()['model']}\nAI thao tác: {ai_provider.config(STORE)['provider']} · {ai_provider.config(STORE)['model'] if ai_provider.config(STORE)['provider']!='ollama' else load_config()['model']}\n" +
        '\n'.join(f"{r['state']}: {r['n']}" for r in rows) +
        f"\nTiến trình: {queue_progress()}\nTrần nhóm/ngày: {STORE.get('daily_group_limit',20)} (tính cả lượt thử/lỗi đã bắt đầu).\nGiờ hiển thị: Việt Nam (UTC+7).")


def pause(cancel=False, shutdown=False):
    with CONFIG_LOCK:
        STORE.set('control_revision',STORE.get('control_revision',0)+1)
        STORE.set('running', False)
        if not shutdown:
            STORE.set('paused_by_user',True)
            STORE.set('approval_monitor_enabled',False)
        STOP_WORK.set()
        from link_refresh import stop
        stop(STORE)
        if cancel:
            STORE.cancel_jobs()
            with STORE.db() as c:c.execute("UPDATE approval_checks SET state='cancelled' WHERE state IN ('waiting','review')")

def clear_job_list():
    if studio().lock.locked():
        raise ValueError('AI đang tạo bài/lịch. Chờ tác vụ hoàn tất rồi xóa danh sách.')
    result=STORE.clear_jobs()
    STOP_WORK.set()
    return f"Đã xóa {result['hidden']} lượt khỏi danh sách và hủy {result['cancelled']} lượt đang chờ. Bài trong kho giữ nguyên."


def runtime_ready():
    if code_revision(ROOT)==RUNTIME_REVISION:return True
    if STORE.get('approval_monitor_enabled',False):STORE.set('approval_monitor_enabled',False)
    message='Có bản sửa mã nguồn mới. Lịch đã tạm dừng; khởi động lại ứng dụng để nạp đầy đủ bản sửa.'
    if STORE.get('running') or STORE.get('progress')!=message:
        STORE.set('running',False);STORE.set('paused_by_user',True);STORE.set('approval_monitor_enabled',False);STORE.set('progress',message)
    return False


def run_queue(expected_revision=None):
    if not runtime_ready():raise ValueError('Có bản sửa mới; khởi động lại ứng dụng trước khi chạy lịch.')
    with CONFIG_LOCK:
        from link_refresh import busy
        with STORE.db() as c:
            if busy(c):raise ValueError('Đang cập nhật link Facebook. Chờ xong hoặc Dừng cập nhật trước khi chạy lịch.')
        if STORE.get('group_scan',{}).get('status')=='running':raise ValueError('Đang quét nhóm. Chờ xong hoặc bấm Dừng quét trước khi chạy lịch.')
        if expected_revision is not None and (expected_revision!=STORE.get('control_revision',0) or load_config()['mode']!='publish'):
            raise ValueError('Đã tạm dừng hoặc đổi chế độ trong lúc AI viết. Không bật tự đăng.')
        if not STORE.get('owner_id'):
            raise ValueError('Ghép tài khoản Telegram trước.')
        if not STORE.rows("SELECT id FROM jobs WHERE state='queued' LIMIT 1") and not STORE.rows("SELECT job_id FROM approval_checks WHERE state='waiting' LIMIT 1"):
            raise ValueError('Chưa có lượt được duyệt. Xem /queue rồi /approve ID.')
        if STORE.rows("SELECT id FROM jobs WHERE state='working' LIMIT 1"):
            raise ValueError('Lượt đang dừng; chờ thông báo hoàn tất rồi chạy lại.')
        STORE.refresh_global_cooldown()
        STORE.reflow_queue()
        STOP_WORK.clear()
        STORE.set('paused_by_user',False)
        STORE.set('approval_monitor_enabled',True)
        STORE.set('running', True)


def queue_action(jid,immediate=False):
    if not runtime_ready():raise ValueError('Khởi động lại ứng dụng để nạp bản mới.')
    with CONFIG_LOCK:
        if studio().lock.locked():raise ValueError('AI đang tạo lịch. Chờ hoàn tất rồi đổi lịch.')
        if immediate and (load_config()['mode']!='publish' or not load_config().get('token') or not STORE.get('owner_id')):raise ValueError('Ghép Telegram và chọn chế độ Tự đăng trước khi đăng ngay.')
        from queue_actions import move_now,restore
        result=(move_now if immediate else restore)(STORE,jid)
        if immediate:STOP_WORK.clear()
    return f"Đã {'đưa lên đầu và bật hàng đợi' if immediate else 'khôi phục lịch lỗi'}: lượt #{result['job_id']}, dự kiến {timestamp(result['due'])}. Giữ khoảng nghỉ và giới hạn đăng."


def control_approval_monitor(action):
    if action not in {'run','pause'}:raise ValueError('Thao tác theo dõi duyệt không hợp lệ.')
    if action=='pause':
        with CONFIG_LOCK:STORE.set('approval_monitor_enabled',False)
        return 'Đã dừng theo dõi duyệt; lịch đăng giữ nguyên trạng thái.'
    if not runtime_ready():raise ValueError('Khởi động lại ứng dụng để nạp bản sửa trước khi theo dõi duyệt.')
    with CONFIG_LOCK:
        if load_config()['mode']!='publish':raise ValueError('Chuyển sang chế độ đăng thật trước khi theo dõi duyệt.')
        if not STORE.rows("SELECT job_id FROM approval_checks WHERE state='waiting' LIMIT 1"):raise ValueError('Chưa có bài chờ duyệt có link để theo dõi.')
        if STORE.rows("SELECT id FROM jobs WHERE state='working' LIMIT 1") or STORE.get('group_scan',{}).get('status')=='running':raise ValueError('Đang thao tác trình duyệt; chờ tác vụ hoàn tất.')
        STOP_WORK.clear()
        STORE.set('approval_monitor_enabled',True)
        STORE.set('progress','Đang theo dõi bài chờ duyệt. Lịch đăng giữ nguyên trạng thái.')
    return 'Đã bật theo dõi duyệt; không khởi động các lịch đăng đang tạm dừng.'

def parse_start(value):
    if not value:
        return time.time()
    return dt.datetime.strptime(value, '%Y-%m-%d %H:%M').replace(tzinfo=dt.timezone(dt.timedelta(hours=7))).timestamp()


def create_plan(cid, minutes, start=None):
    ids = STORE.plan(cid, minutes, start)
    STORE.set('interval_minutes', interval_bounds(minutes)[0])
    return 'Đã tạo lịch nháp: ' + (', '.join(map(str, ids)) or '0 lượt mới; đã bỏ qua nội dung trùng.') + '\nDùng /queue và /job ID để xem. Dùng /approve ID hoặc /approve_all để duyệt; /run để bắt đầu.'


def ai_generate(brief):
    if not 1 <= len(brief) <= 6000:
        raise ValueError('Mô tả phải có 1–6000 ký tự.')
    result = request_json('http://127.0.0.1:11434/api/chat', {
        'model': load_config()['model'], 'stream': False, 'think': False,
        'messages': [
            {'role': 'system', 'content': 'Viết một bài Facebook tiếng Việt dài 2–4 câu theo dữ liệu người dùng. Chỉ trả nội dung bài, không tiêu đề giải thích. Không bịa giá, cam kết, ưu đãi, tính năng, chứng thực hoặc đường link. Không sửa đường link đã cung cấp. Không thêm hashtag khi không được yêu cầu. Nội dung phải phù hợp nhóm, không hướng dẫn né kiểm duyệt.'},
            {'role': 'user', 'content': brief}],
        'options': {'temperature': 0.65, 'num_predict': 400, 'num_ctx': 8192}}, timeout=180)
    body = result['message']['content'].strip()
    cid = STORE.content(body)
    return f'Đã lưu bài #{cid} (chưa tự đưa vào lịch):\n\n{body}\n\nSửa bằng /edit {cid} nội dung mới; lên lịch bằng /plan {cid} 60.'


HELP = '''NCT Group Manager — điều khiển trên PC của bạn
/status — trạng thái
/addgroup LINK | Tên nhóm | Quy định nội dung
/groups — danh sách nhóm
/enable ID — bật nhóm sau khi kiểm tra quyền và quy định
/reviews — nhóm cần xem xét, nút Giữ lại / Xóa nhóm\n/disable ID — tắt nhóm và hủy lượt chưa chạy
/deletegroup ID hoặc LINK — xóa nhóm khỏi danh sách sử dụng, có xác nhận
/links ID allow — nhóm cho phép link
/links ID deny — nhóm không cho phép link
/new Nội dung — lưu bài; gửi ảnh kèm caption để lưu bài có ảnh
/contents — danh sách bài
/content ID — xem bài đầy đủ
/edit ID Nội dung mới — sửa bài (lịch cũ giữ bản đã chốt)
/nolink ID Nội dung — lưu phiên bản không link; có thể gửi ảnh kèm caption lệnh này
/delete ID — xóa bài trong kho, không thay lịch cũ
/generate Mô tả — Ollama viết bài nháp
/variants ID SỐ — tạo 1–5 bản nháp ngắn từ bài có sẵn
/plan ID PHÚT [YYYY-MM-DD HH:MM] — lên lịch một vòng các nhóm bật, giờ Việt Nam
/plan ID 30-60 — nghỉ ngẫu nhiên 30–60 phút; lịch được chốt để bạn xem trước
/planmix PHÚT ID,ID,... — chọn từ các bài có sẵn cho mỗi nhóm; xem lịch rồi duyệt
/queue — xem lịch
/job ID — xem chi tiết lượt
/approve ID [ID...] — duyệt nội dung/lịch đã xem
/approve_all — duyệt tất cả lịch nháp hiện có
/cancel ID — hủy lượt chưa chạy
/clearjobs — xóa toàn bộ lịch khỏi danh sách và hủy các lượt chờ
/reschedule ID YYYY-MM-DD HH:MM — đổi giờ, cần duyệt lại
/interval PHÚT — giãn các lượt đang chờ, cần duyệt lại
/random MIN MAX — đổi lịch chờ sang khoảng nghỉ ngẫu nhiên, ví dụ /random 30 60
/cycle ID NGHỈ_PHÚT NGÀY_MIN NGÀY_MAX SỐ_NGÀY — ví dụ /cycle 1 30-60 1 3 30
/run — chạy lịch đã duyệt
/pause — tạm dừng, giữ lịch
/stop — dừng và hủy lượt chưa chạy
/browser — mở trình duyệt Facebook để bạn đăng nhập Facebook trên PC
/aiusage — token xKiro đã dùng bởi bot và hạn mức gần nhất
/check — kiểm tra Ollama và các thành phần local
/history — kết quả gần đây
/groupcategory ID Tên — phân loại nhóm
/postcategory ID Tên — phân loại bài
/targets ID NHÓM, NHÓM — ví dụ /targets 1 2,3; đặt đúng nhóm đích cho bài
/targetcategory ID — dùng tất cả nhóm cùng phân loại
/randompool BÀI_IDS NHÓM_IDS PHÚT MIN_NGÀY MAX_NGÀY SỐ_NGÀY — random bài trong kho cùng phân loại với nhóm; ví dụ /randompool 1,2,5 2,3 30-60 1 1 7
/pool BÀI_IDS NHÓM_IDS PHÚT MIN_NGÀY MAX_NGÀY SỐ_NGÀY — tạo lịch random, ví dụ /pool 1,2,3 2,3 30-60 1 3 7
/cancelcreate — hủy bước tạo bài qua nút bấm
/linkpreview LINK_CŨ LINK_MỚI — xem số bài/lượt chưa chạy cần đổi link
/linkapply — áp dụng lần thay link vừa xem, tạm dừng hàng đợi
Lịch không phải bảo đảm tránh spam. Tôn trọng quyền thành viên và quy định từng nhóm.'''


def menu():
    return {'keyboard': [[{'text':'🏠 Menu'}],[{'text':'➕ Tạo bài'},{'text':'✨ AI tạo nháp'}],[{'text':'🎲 Random bài & nhóm'},{'text':'🗓 Lên lịch bài'}],[{'text': '📊 Trạng thái'}, {'text': '📋 Lịch đăng'}], [{'text': '▶ Chạy'}, {'text': '⏸ Tạm dừng'}, {'text': '⛔ Dừng'}], [{'text': '📝 Nội dung'}, {'text': '👥 Nhóm'}], [{'text':'🔗 Thay link'},{'text': '📖 Hướng dẫn'}]], 'resize_keyboard': True, 'is_persistent':True}


def render_panel(chat,text,markup,message_id=None):
    if message_id is None:return send_text(chat,text,reply_markup=markup)
    try:return telegram('editMessageText',{'chat_id':chat,'message_id':message_id,'text':text[:4000],'reply_markup':markup})
    except RuntimeError as exc:
        if 'message is not modified' in str(exc).lower():return {'unchanged':True}
        raise


def panel(chat,screen='home',page=0,message_id=None):
    page=max(0,int(page));size=6
    back=[{'text':'🏠 Menu chính','callback_data':'panel:home:0'}]
    if screen=='home':
        running=bool(STORE.get('running'));groups=STORE.rows('SELECT COUNT(*) n FROM groups WHERE deleted=0')[0]['n']
        posts=STORE.rows('SELECT COUNT(*) n FROM contents')[0]['n']
        pending=STORE.rows("SELECT COUNT(*) n FROM jobs WHERE state='queued'")[0]['n']
        text=f"🏠 NCT · BẢNG ĐIỀU KHIỂN\n\n{'▶ Lịch đang chạy' if running else '⏸ Lịch đang tạm dừng'}\n👥 {groups} nhóm   ·   📝 {posts} bài   ·   🗓 {pending} lượt chờ\n\nChọn việc bạn muốn làm bên dưới."
        rows=[[{'text':'➕ Tạo bài','callback_data':'panel:create:0'},{'text':'📝 Kho bài','callback_data':'panel:posts:0'}],
              [{'text':'👥 Quản lý nhóm','callback_data':'panel:groups:0'},{'text':'🗓 Lịch đăng','callback_data':'panel:queue:0'}],
              [{'text':'🔎 Nhóm cần xem xét','callback_data':'panel:reviews:0'},{'text':'📸 Kết quả đăng','callback_data':'panel:history:0'}],
              [{'text':'⏸ Tạm dừng','callback_data':'panel:pause:0'},{'text':'▶ Chạy lịch đã duyệt','callback_data':'panel:run:0'}],
              [{'text':'🎲 Random bài & nhóm','callback_data':'panel:random:0'}],
              [{'text':'📊 Trạng thái','callback_data':'panel:status:0'},{'text':'📖 Hướng dẫn','callback_data':'panel:help:0'}]]
    elif screen in {'groups','posts','queue','reviews'}:
        queries={'groups':'SELECT * FROM groups WHERE deleted=0 ORDER BY id','posts':'SELECT * FROM contents ORDER BY id DESC','queue':"SELECT * FROM jobs WHERE hidden=0 ORDER BY id DESC",'reviews':"SELECT * FROM group_reviews WHERE decision='' ORDER BY updated DESC"}
        all_rows=STORE.rows(queries[screen]);page=min(page,max(0,(len(all_rows)-1)//size));items=all_rows[page*size:(page+1)*size]
        title={'groups':'👥 QUẢN LÝ NHÓM','posts':'📝 KHO BÀI','queue':'🗓 LỊCH ĐĂNG','reviews':'🔎 NHÓM CẦN XEM XÉT'}[screen]
        text=f"{title} · {len(all_rows)} mục\nTrang {page+1}/{max(1,(len(all_rows)+size-1)//size)}\n\nBấm vào một mục để xem và quản lý." if items else title+'\n\nDanh sách đang trống.'
        rows=[]
        for item in items:
            if screen=='groups':label=f"{'🟢' if item['enabled'] else '⚪'} #{item['id']} · {item['name']}";action='group'
            elif screen=='posts':label=f"#{item['id']} · {item['title'] or item['body'][:45]}";action='post'
            elif screen=='reviews':label=f"#{item['job_id']} · {item['state']} · {item['group_name']}";action='review'
            else:label=f"#{item['id']} · {item['state']} · {item['group_name']}";action='job'
            rows.append([{'text':label[:64],'callback_data':f"panel:{action}:{item['id']}"}])
        arrows=[]
        if page>0:arrows.append({'text':'⬅ Trang trước','callback_data':f'panel:{screen}:{page-1}'})
        if (page+1)*size<len(all_rows):arrows.append({'text':'Trang sau ➡','callback_data':f'panel:{screen}:{page+1}'})
        if arrows:rows.append(arrows)
        rows.append(back)
    elif screen=='random':
        posts=STORE.rows('SELECT id,title FROM contents ORDER BY id')
        groups=STORE.rows("SELECT id,name FROM groups WHERE enabled=1 AND deleted=0 AND link_policy!='unknown' ORDER BY id")
        text=f"🎲 RANDOM BÀI CÓ SẴN & NHÓM\n\nNguồn: {len(posts)} bài trong kho · {len(groups)} nhóm đã bật, đã rõ quyền link.\nKhông cần cùng phân loại. Bot không viết lại bài và không tạo bài mới bằng AI.\nMặc định: nghỉ 30–60 phút giữa các nhóm, mỗi nhóm tối đa 1 bài/ngày, lên lịch 7 ngày.\nChỉ tạo lịch nháp để bạn xem; chưa đăng ngay."
        rows=[[{'text':'🎲 Tạo lịch nháp random','callback_data':'panel:randomcreate:0'}],[{'text':'📝 Xem kho bài','callback_data':'panel:posts:0'},{'text':'👥 Xem nhóm','callback_data':'panel:groups:0'}],back]
    elif screen=='review':
        items=STORE.rows('SELECT * FROM group_reviews WHERE id=?',(page,))
        if not items:raise ValueError('Mục xem xét không còn tồn tại.')
        r=items[0]
        return render_panel(chat,f"🔎 {r['group_name']} · {r['state']}\n{r['url']}\n{r['post_url'] or 'Chưa có link bài'}\n{r['detail'][:1000]}",review_keyboard(r) if not r['decision'] else {'inline_keyboard':[back]},message_id)
    elif screen=='group':
        items=STORE.rows('SELECT * FROM groups WHERE id=? AND deleted=0',(page,))
        if not items:raise ValueError('Nhóm không còn trong danh sách. Mở Menu → Quản lý nhóm.')
        g=items[0];text=f"👥 #{g['id']} · {g['name']}\n{'🟢 Đang bật' if g['enabled'] else '⚪ Đang tắt'}\n{g['url']}\nPhân loại: {g['category']}\nQuy định: {g['rules'] or 'Chưa ghi'}"
        rows=[[{'text':'🔗 Mở nhóm Facebook','url':g['url']}],
              [{'text':'⏸ Tắt nhóm' if g['enabled'] else '▶ Bật nhóm','callback_data':f"panel:{'disable' if g['enabled'] else 'enable'}:{g['id']}"},
               {'text':'🗑 Xóa nhóm','callback_data':f"panel:deletegroup:{g['id']}"}],
              [{'text':'⬅ Danh sách nhóm','callback_data':'panel:groups:0'}],back]
    elif screen=='post':
        items=STORE.rows('SELECT * FROM contents WHERE id=?',(page,))
        if not items:raise ValueError('Không tìm thấy bài trong kho.')
        post=items[0];text=f"📝 Bài #{post['id']} · {post['title'] or 'Chưa đặt tên'}\nPhân loại: {post['category']}\n\n"+post['body'][:3200]
        rows=[[{'text':'📄 Xem đầy đủ','callback_data':f'panel:content:{page}'},{'text':'🗓 Lên lịch bài này','callback_data':f'panel:plan:{page}'}],
              [{'text':'🗑 Xóa bài trong kho','callback_data':f'panel:deletepost:{page}'}],
              [{'text':'⬅ Kho bài','callback_data':'panel:posts:0'}],back]
    else:raise ValueError('Mục menu không hợp lệ.')
    return render_panel(chat,text,{'inline_keyboard':rows},message_id)


def panel_callback(query):
    match=re.fullmatch(r'panel:([a-z]+):(\d+)',query.get('data',''))
    if not match:return False
    action,value=match[1],int(match[2]);chat=STORE.get('owner_chat');message_id=query['message']['message_id']
    telegram('answerCallbackQuery',{'callback_query_id':query['id']})
    if action in {'home','groups','posts','queue','group','post','reviews','review','random'}:panel(chat,action,value,message_id);return True
    if action=='randomcreate':
        cids=[p['id'] for p in STORE.rows('SELECT id FROM contents ORDER BY id')]
        gids=[g['id'] for g in STORE.rows("SELECT id FROM groups WHERE enabled=1 AND deleted=0 AND link_policy!='unknown' ORDER BY id")]
        ids=STORE.cycle_pool(cids,gids,'30-60',1,1,7,routing_mode='random')
        render_panel(chat,f"🎲 Đã tạo {len(ids)} lượt nháp từ bài có sẵn. Không gọi AI soạn bài.\nChưa đăng; xem lịch rồi duyệt và chạy.\nCác nhóm đang có lịch hoặc lượt chưa rõ được bỏ qua.",{'inline_keyboard':[[{'text':'🗓 Xem lịch nháp','callback_data':'panel:queue:0'},{'text':'🏠 Menu chính','callback_data':'panel:home:0'}]]},message_id)
        return True
    if action in {'enable','disable'}:
        STORE.enable_group(value,action=='enable');panel(chat,'group',value,message_id);return True
    if action in {'pause','run'}:
        pause() if action=='pause' else run_queue()
        panel(chat,message_id=message_id);return True
    if action=='status':
        render_panel(chat,status_text(),{'inline_keyboard':[[{'text':'🏠 Menu chính','callback_data':'panel:home:0'}]]},message_id);return True
    if action=='history':
        recent=STORE.rows("SELECT * FROM jobs WHERE hidden=0 AND state NOT IN ('draft','queued') ORDER BY updated DESC LIMIT 6")
        text='📸 KẾT QUẢ GẦN ĐÂY\n\n'+'\n\n'.join(f"#{j['id']} · {j['state']} · {j['group_name']}\n{j['post_url'] or j['url']}\n{j['detail'][:180]}\nBình luận: {j['comment_status'] or 'Không yêu cầu'}" for j in recent)
        render_panel(chat,text if recent else 'Chưa có kết quả đăng.',{'inline_keyboard':[[{'text':'🏠 Menu chính','callback_data':'panel:home:0'}]]},message_id);return True
    if action=='deletepost':
        post=STORE.rows('SELECT id,title FROM contents WHERE id=?',(value,))
        if not post:raise ValueError('Bài đã được xóa khỏi kho.')
        nonce=secrets.token_hex(8);STORE.set('pending_delete_post',{'id':value,'nonce':nonce,'at':time.time()})
        send_text(chat,f"🗑 Xóa bài #{value} khỏi kho?\nCác lượt đã lên lịch vẫn giữ nội dung đã chốt. Không xóa bài trên Facebook.",reply_markup={'inline_keyboard':[[{'text':'Xác nhận xóa','callback_data':f'postdelete:yes:{nonce}'},{'text':'Hủy','callback_data':f'postdelete:no:{nonce}'}]]});return True
    if action=='plan':
        STORE.set('bot_wizard',{'kind':'schedule','step':'body'})
        bot_wizard({'chat':{'id':chat}},str(value),chat);return True
    commands={'create':'➕ Tạo bài','reviews':'/reviews','history':'/history','pause':'/pause','run':'/run','status':'/status','help':'/help',
              'enable':f'/enable {value}','disable':f'/disable {value}','deletegroup':f'/deletegroup {value}','content':f'/content {value}','job':f'/job {value}'}
    if action not in commands:raise ValueError('Nút không còn được hỗ trợ. Mở /menu lại.')
    handle_message({'from':{'id':STORE.get('owner_id')},'chat':{'id':chat,'type':'private'},'text':commands[action]})
    return True


def send_text(chat, text, keyboard=False, reply_markup=None):
    payload = {'chat_id': chat, 'text': text[:4000]}
    if keyboard:
        payload['reply_markup'] = menu()
    if reply_markup:payload['reply_markup']=reply_markup
    return telegram('sendMessage', payload)


def download_photo(photo):
    if photo.get('file_size', 0) > 10 * 1024 * 1024:
        raise ValueError('Ảnh tối đa 10 MB.')
    info = telegram('getFile', {'file_id': photo['file_id']})
    path = str(info['file_path'])
    if '..' in path or not re.fullmatch(r'[A-Za-z0-9_./-]+', path):
        raise ValueError('Đường dẫn ảnh không hợp lệ.')
    media = DATA / 'media'
    media.mkdir(exist_ok=True)
    dest = media / (secrets.token_hex(10) + '.jpg')
    token = load_config()['token']
    try:
        with urllib.request.urlopen(f'https://api.telegram.org/file/bot{token}/{path}', timeout=30) as response:
            raw = response.read(10 * 1024 * 1024 + 1)
        if len(raw) > 10 * 1024 * 1024:
            raise ValueError('Ảnh quá lớn.')
        dest.write_bytes(raw)
    except (urllib.error.URLError, OSError):
        raise RuntimeError('Tải ảnh Telegram thất bại.') from None
    return str(dest)


def download_attachment(message):
    item=message.get('video') or message.get('document') or (message['photo'][-1] if message.get('photo') else None)
    if not item:return ''
    limit=20*1024*1024
    if item.get('file_size',0)>limit:raise ValueError('Tệp Telegram tối đa 20 MB để bot tải về. Tệp lớn hơn hãy thêm trên dashboard (ảnh 100 MB, video 500 MB/tệp).')
    info=telegram('getFile',{'file_id':item['file_id']})
    remote=str(info['file_path'])
    if '..' in remote or not re.fullmatch(r'[A-Za-z0-9_./-]+',remote):raise ValueError('Đường dẫn tệp không hợp lệ.')
    filename=item.get('file_name') or ('video.mp4' if message.get('video') else 'photo.jpg')
    try:
        with urllib.request.urlopen(f"https://api.telegram.org/file/bot{load_config()['token']}/{remote}",timeout=60) as response:raw=response.read(limit+1)
        if len(raw)>limit:raise ValueError('Tệp quá lớn; thêm tệp trên dashboard.')
        value=media_store.receive(io.BytesIO(raw),len(raw),filename,DATA/'media')
        return str(DATA/'media'/value['id'])
    except urllib.error.URLError:raise RuntimeError('Không tải được tệp từ Telegram.') from None


def bot_wizard(message,text,chat):
    starts={'➕ Tạo bài':'manual','✨ AI tạo nháp':'ai','🚀 AI gen & tự đăng':'autopost','🗓 Lên lịch bài':'schedule','🔗 Thay link':'links'}
    if text in starts:
        kind=starts[text]
        STORE.set('bot_wizard',{'kind':kind,'step':'body'})
        prompt='Gửi link cũ cần thay trong kho và lịch chưa chạy.' if kind=='links' else ('Gửi ID bài cần lên lịch (xem /contents).' if kind=='schedule' else ('Gửi thông tin thật để AI viết bài. Có thể kèm một ảnh/video. Ví dụ: chủ đề, thông tin sản phẩm, giá đúng và link nếu có.' if kind!='manual' else 'Gửi nội dung bài viết. Có thể gửi ảnh/video kèm caption. Nếu chỉ gửi tệp, hãy gửi nội dung ở tin nhắn tiếp theo.'))
        send_text(chat,'BƯỚC 1 · '+prompt+'\n/cancelcreate để hủy.');return True
    state=STORE.get('bot_wizard')
    if text=='/cancelcreate':STORE.set('bot_wizard',None);send_text(chat,'Đã hủy tạo bài.',True);return True
    if not state or text.startswith('/'):return False
    kind=state['kind'];step=state['step']
    if kind=='links':
        value=validate_link(text)
        if step=='body':
            state.update(old_url=value,step='new_url');STORE.set('bot_wizard',state)
            send_text(chat,'BƯỚC 2 · Gửi link mới thay thế.');return True
        preview=STORE.preview_links(state['old_url'],value)
        STORE.set('link_preview',preview);STORE.set('bot_wizard',None)
        send_text(chat,f"Sẽ đổi {preview['content_count']} bài trong kho và {preview['job_count']} lượt chưa chạy.\nCó {preview['historical_count']} lượt đã gửi/đã soạn ở trình duyệt/chưa rõ dùng link cũ, không sửa qua thao tác này.\nBản không link, ảnh/video giữ nguyên.\n/linkapply để áp dụng; /run sau khi kiểm tra lịch.",True);return True
    if kind=='schedule':
        cid=int(text);ids=STORE.cycle(cid,'30-60',1,1,7)
        STORE.set('bot_wizard',None)
        send_text(chat,f'Đã tạo {len(ids)} lượt nháp trong 7 ngày, đúng phân loại bài. Mỗi nhóm tối đa 1 bài/ngày; nghỉ 30–60 phút trước khi sang nhóm khác. Xem /queue rồi /approve_all và /run.',True);return True
    if step=='body':
        attachment=download_attachment(message)
        if attachment:state['media']=attachment
        if not text:STORE.set('bot_wizard',state);send_text(chat,'Đã nhận tệp. Gửi tiếp nội dung hoặc mô tả cho AI.');return True
        state.update(body=text,step='category');STORE.set('bot_wizard',state)
        send_text(chat,'BƯỚC 2 · Chọn game bên dưới hoặc gửi tên phân loại. Bài chỉ vào nhóm đúng game.'+('\nChế độ này sẽ tạo bài và tự đăng trong 7 ngày.' if kind=='autopost' else ''),reply_markup={'inline_keyboard':[[{'text':game,'callback_data':'tg:choosegame:0:'+game}] for game in (*media_library.POOLS,'ALL','Chung')]});return True
    if step=='category':
        state['category']=text.strip()[:80]
        if kind in {'ai','autopost'}:
            media_ids=[Path(p).name for p in media_store.paths(state.get('media',''))]
            result=studio().start({'brief':state['body'],'category':state['category'],'media_ids':media_ids,'autopost':kind=='autopost','horizon':7})
            STORE.set('bot_wizard',None);send_text(chat,result['message']+' Bot sẽ gửi hai phiên bản khi xong.',True);return True
        state['step']='nolink';STORE.set('bot_wizard',state)
        send_text(chat,'BƯỚC 3 · Gửi bản hoàn chỉnh không có link cho nhóm cấm link. Gửi dấu - nếu không dùng. Không tự dùng ảnh/video của bản thường cho bản không link.');return True
    if step=='nolink':
        alt='' if text=='-' else text
        cid=STORE.content(state['body'],state.get('media',''),alt,state['category'])
        STORE.set('bot_wizard',None)
        send_text(chat,f'✅ Đã lưu bài #{cid} · {state["category"]}.\n/content {cid} để xem. Bấm “🗓 Lên lịch bài” và gửi {cid} để tạo lịch.',True);return True
    return False


def handle_message(message):
    if message.get('chat', {}).get('type') != 'private' or message.get('from', {}).get('is_bot'):
        return
    uid = message['from']['id']
    chat = message['chat']['id']
    text = (message.get('text') or message.get('caption') or '').strip()
    owner = STORE.get('owner_id')
    if not owner:
        expected = '/pair ' + STORE.get('pair_code')
        if secrets.compare_digest(text, expected):
            STORE.set('owner_id', uid)
            STORE.set('owner_chat', chat)
            STORE.set('pair_code', secrets.token_hex(16))
            STORE.notify('✅ Đã ghép bot với tài khoản Telegram của bạn. Gửi /menu để mở điều khiển hoặc /help để xem hướng dẫn.')
        elif text in {'/start', '/menu'}:
            send_text(chat, 'Mở trang cài đặt trên PC và gửi lệnh /pair kèm mã đang hiển thị để ghép tài khoản.')
        return
    if uid != owner or chat != STORE.get('owner_chat'):
        return
    aliases = {'🎲 Random bài & nhóm':'/randompool','Menu':'/menu','menu':'/menu','🏠 Menu':'/menu','📊 Trạng thái': '/status', '📋 Lịch đăng': '/panelqueue', '▶ Chạy': '/run', '⏸ Tạm dừng': '/pause', '⛔ Dừng': '/stop', '📝 Nội dung': '/panelposts', '👥 Nhóm': '/panelgroups', '📖 Hướng dẫn': '/help'}
    text = aliases.get(text, text)
    if bot_wizard(message,text,chat):return
    if message.get('photo') or message.get('video') or message.get('document'):
        if text.startswith('/nolink '):
            _, cid, body = text.split(' ', 2)
            STORE.no_link_content(int(cid), body, download_attachment(message))
            STORE.notify(f'Đã lưu bản không link có ảnh cho bài #{cid}. Xem /content {cid}.')
            return
        body = text.removeprefix('/new').strip()
        if not body:
            raise ValueError('Gửi ảnh kèm caption là nội dung bài viết.')
        cid = STORE.content(body, download_attachment(message))
        STORE.notify(f'Đã lưu bài có tệp #{cid}. Xem /content {cid}.')
        return
    command, _, args = text.partition(' ')
    command = command.split('@')[0].lower()
    args = args.strip()
    if command in {'/start','/menu'}:
        STORE.set('bot_wizard',None)
        panel(chat)
        return
    if command=='/help':
        send_text(chat,HELP,True)
        return
    if command in {'/panelgroups','/panelposts','/panelqueue'}:
        panel(chat,command.removeprefix('/panel'))
        return
    if command == '/status':
        result = status_text()
    elif command == '/groups':
        result = '\n'.join(f"#{g['id']} {'BẬT' if g['enabled'] else 'TẮT'} · {g['name']} · link: {g['link_policy']}\n{g['url']}\nQuy định: {g['rules'] or 'chưa ghi'}" for g in STORE.rows('SELECT * FROM groups WHERE deleted=0 ORDER BY id')) or 'Chưa có nhóm. /addgroup LINK | Tên | Quy định'
    elif command in {'/deletegroup','/xoanhom'}:
        if not args:
            rows=STORE.rows('SELECT id,name,url FROM groups WHERE deleted=0 ORDER BY id')
            result='Xóa nhóm: /deletegroup ID hoặc LINK. Bot sẽ hỏi xác nhận.\nChỉ gỡ khỏi danh sách sử dụng và hủy lịch chưa chạy; giữ lịch sử, không rời/xóa nhóm Facebook.\n\n'+'\n'.join(f"#{g['id']} · {g['name']}" for g in rows)
        else:
            if args.isdecimal():rows=STORE.rows('SELECT * FROM groups WHERE id=? AND deleted=0',(int(args),))
            else:
                try:url=group_url(args)
                except ValueError:raise ValueError('Dùng /deletegroup ID hoặc link nhóm. Xem ID bằng /groups.') from None
                rows=STORE.rows('SELECT * FROM groups WHERE url=? AND deleted=0',(url,))
            if not rows:raise ValueError('Không tìm thấy nhóm đang sử dụng. Xem /groups.')
            g=rows[0];nonce=secrets.token_hex(8)
            STORE.set('pending_delete_group',{'id':g['id'],'nonce':nonce,'at':time.time()})
            send_text(chat,f"Xóa nhóm #{g['id']} · {g['name']}?\n{g['url']}\nSẽ tắt nhóm, gỡ khỏi danh sách sử dụng và hủy các lượt chưa chạy. Lịch sử được giữ lại.",reply_markup={'inline_keyboard':[[{'text':'Xác nhận xóa','callback_data':f'groupdelete:yes:{nonce}'},{'text':'Hủy','callback_data':f'groupdelete:no:{nonce}'}]]})
            return
    elif command == '/reviews':
        rows=STORE.rows("SELECT * FROM group_reviews WHERE decision='' ORDER BY updated DESC LIMIT 20")
        for row in rows:
            send_text(chat,f"Xem xét · {row['group_name']}\n{row['url']}\n{row['state']}\n"+(row['post_url'] or 'Chưa có link bài viết'),reply_markup=review_keyboard(row))
        if not rows:send_text(chat,'Không có nhóm đang chờ xem xét.')
        return
    elif command == '/addgroup':
        ids = []
        for line in args.splitlines():
            fields = [v.strip() for v in line.split('|', 2)]
            ids.append(STORE.add_group(*fields))
        result = f"Đã lưu nhóm {', '.join(map(str, ids))}. Nhóm mới đang TẮT. Sau khi kiểm tra quy định, dùng /enable ID."
    elif command in {'/enable', '/disable'}:
        STORE.enable_group(int(args), command == '/enable')
        result = 'Đã cập nhật nhóm. Bật nhóm nghĩa là bạn xác nhận có quyền đăng nội dung dự kiến theo quy định nhóm.'
    elif command == '/links':
        gid, policy = args.split()
        STORE.set_link_policy(int(gid), policy)
        result = 'Đã lưu quy định link. Lượt nháp/chờ cũ của nhóm đã hủy; lên lịch lại để chọn đúng phiên bản nội dung.'
    elif command in {'/groupcategory','/postcategory'}:
        ident,category=args.split(' ',1)
        (STORE.group_category if command=='/groupcategory' else STORE.post_category)(int(ident),category)
        result='Đã cập nhật phân loại. Lên lịch lại nếu cần áp dụng thay đổi.'
    elif command == '/targets':
        cid,values=args.split(' ',1)
        cancelled=STORE.targets(int(cid),'selected',[int(v.strip()) for v in values.split(',') if v.strip()])
        result=f'Đã gán nhóm đích cho bài #{cid}. Hủy {cancelled} lượt chưa chạy bị ảnh hưởng; tạo lại lịch để áp dụng.'
    elif command == '/targetcategory':
        cancelled=STORE.targets(int(args),'category',[])
        result=f'Bài nhận nhóm theo phân loại. Đã hủy {cancelled} lượt cũ; lên lịch lại.'
    elif command in {'/pool','/randompool'}:
        if command=='/randompool' and not args:
            panel(chat,'random');return
        cids,gids,interval,lo,hi,horizon=args.split()
        ids=STORE.cycle_pool([int(v) for v in cids.split(',')],[int(v) for v in gids.split(',')],interval,int(lo),int(hi),int(horizon),routing_mode='random' if command=='/randompool' else 'category')
        result=f'Đã tạo {len(ids)} lượt nháp, chọn ngẫu nhiên trong các bài hợp lệ cho từng nhóm. Xem /queue và /job ID rồi duyệt/chạy.'
    elif command == '/linkpreview':
        old,new=args.split()
        preview=STORE.preview_links(old,new);STORE.set('link_preview',preview)
        result=f"Ảnh hưởng: {preview['content_count']} bài lưu, {preview['job_count']} lượt chưa chạy.\n{preview['historical_count']} lượt đã gửi/đã soạn ở trình duyệt/chưa rõ sẽ giữ nguyên.\n/linkapply để áp dụng. Bản không link và tệp đính kèm giữ nguyên."
    elif command == '/linkapply':
        preview=STORE.get('link_preview')
        if not preview:raise ValueError('Dùng nút Thay link hoặc /linkpreview trước.')
        changed=apply_link_change(preview['old_url'],preview['new_url'],preview['digest'])
        STORE.set('link_preview',None)
        result=f"Đã đổi link: {changed['content_count']} bài lưu, {changed['job_count']} lượt chưa chạy. Hàng đợi tạm dừng. Xem /queue, rồi /run để tiếp tục lịch đã duyệt."
    elif command == '/new':
        result = f'Đã lưu bài #{STORE.content(args)}.'
    elif command == '/contents':
        result = '\n'.join(f"#{p['id']} {'[ảnh] ' if p['media'] else ''}{p['body'][:130]}" for p in STORE.rows('SELECT * FROM contents ORDER BY id DESC LIMIT 30')) or 'Chưa có bài. /new nội dung hoặc /generate mô tả'
    elif command == '/content':
        posts = STORE.rows('SELECT * FROM contents WHERE id=?', (int(args),))
        if not posts:
            raise ValueError('Không tìm thấy bài.')
        result = f"Bài #{args}\nBẢN THƯỜNG:\n{posts[0]['body']}\n{'Có ảnh đính kèm' if posts[0]['media'] else 'Chỉ văn bản'}\n\nBẢN KHÔNG LINK:\n{posts[0]['body_no_link'] or '(chưa thêm; chỉ dùng bản thường nếu không chứa link)'}\nẢnh riêng không link: {'có' if posts[0]['media_no_link'] else 'không'}"
    elif command == '/nolink':
        cid, body = args.split(' ', 1)
        STORE.no_link_content(int(cid), body)
        result = 'Đã lưu phiên bản không link. Lịch đã chốt không thay đổi; hãy hủy và lên lịch lại nếu cần.'
    elif command == '/edit':
        cid, body = args.split(' ', 1)
        if not body.strip() or len(body) > 5000:
            raise ValueError('Nội dung phải có 1–5000 ký tự.')
        with STORE.db() as c:
            if not c.execute('UPDATE contents SET body=? WHERE id=?', (body.strip(), int(cid))).rowcount:
                raise ValueError('Không tìm thấy bài.')
        result = 'Đã sửa bài. Lượt đã lên lịch giữ bản nội dung đã chốt; hủy và lên lịch lại nếu cần.'
    elif command == '/delete':
        STORE.delete_contents([int(args)])
        result = 'Đã xóa bài khỏi kho. Lượt đã lên lịch giữ nguyên.'
    elif command in {'/generate', '/variants'}:
        if STORE.get('ai_busy', False):
            raise ValueError('AI đang viết bài trước, chờ kết quả rồi gửi tiếp.')
        briefs = [args]
        if command == '/variants':
            cid, count = map(int, args.split())
            if not 1 <= count <= 5:
                raise ValueError('Tạo từ 1 đến 5 bản nháp mỗi lần.')
            posts = STORE.rows('SELECT * FROM contents WHERE id=?', (cid,))
            if not posts:
                raise ValueError('Không tìm thấy bài gốc.')
            briefs = [f'Viết bản nháp ngắn số {i+1}, thay đổi cách diễn đạt tự nhiên nhưng giữ đúng dữ kiện của bài gốc. Không tạo nội dung để né bộ lọc. Bài gốc:\n{posts[0]["body"]}' for i in range(count)]
        STORE.set('ai_busy', True)
        def generate():
            try:
                for brief in briefs:
                    STORE.notify(ai_generate(brief))
            except Exception as exc:
                STORE.notify('❌ AI: ' + safe_error(exc))
            finally:
                STORE.set('ai_busy', False)
        threading.Thread(target=generate, daemon=True).start()
        result = 'AI đang viết bài local. Bạn vẫn dùng /pause và các lệnh khác trong lúc chờ.'
    elif command == '/plan':
        fields = args.split(' ', 2)
        result = create_plan(int(fields[0]), fields[1], parse_start(fields[2]) if len(fields) > 2 else None)
    elif command == '/planmix':
        minutes, ids = args.split(' ', 1)
        content_ids = [int(x.strip()) for x in ids.split(',')]
        created = STORE.plan_many(content_ids, minutes)
        STORE.set('interval_minutes', interval_bounds(minutes)[0])
        result = 'Đã chốt bài cho từng nhóm ở các lượt nháp: '+(', '.join(map(str, created)) or '0 lượt mới')+'. Xem /queue và /job ID rồi duyệt. AI không đổi bài sau khi duyệt.'
    elif command == '/cycle':
        cid, interval, lo, hi, horizon = args.split()
        ids = STORE.cycle(int(cid), interval, int(lo), int(hi), int(horizon))
        result = f'Đã tạo {len(ids)} lượt nháp cho {horizon} ngày; mỗi nhóm nghỉ {lo}–{hi} ngày, tối đa 1 bài/ngày. Xem /queue và /job ID, rồi /approve_all và /run. Hết kỳ sẽ dừng, không tự tạo thêm bài.'
    elif command == '/queue':
        result = queue_text()
    elif command == '/job':
        jobs = STORE.rows('SELECT * FROM jobs WHERE id=?', (int(args),))
        if not jobs:
            raise ValueError('Không tìm thấy lượt.')
        j = jobs[0]
        result = f"Lượt #{j['id']} · {j['state']}\n{j['group_name']}\n{j['url']}\nGiờ Việt Nam dự kiến: {timestamp(j['due'])}\nNghỉ sau lượt: {j['gap_seconds']//60} phút {j['gap_seconds']%60} giây\n\n{j['body']}\n\nẢnh: {'có' if j['media'] else 'không'}\nKết quả: {j['detail']}"
    elif command in {'/approve', '/approve_all'}:
        ids = [r['id'] for r in STORE.rows("SELECT id FROM jobs WHERE state='draft'")] if command == '/approve_all' else [int(x) for x in args.split()]
        result = f'Đã duyệt {STORE.approve(ids)} lượt. /run để bắt đầu. Nội dung và nhóm đã chốt không tự đổi khi AI viết thêm bài.'
    elif command == '/clearjobs':
        result=clear_job_list()
    elif command == '/cancel':
        n = STORE.cancel_jobs([int(args)])
        result = f'Đã hủy {n} lượt; nhóm không còn lịch chờ có thể tạo lịch mới. Với lượt đang chạy, dùng /pause.'
    elif command == '/reschedule':
        jid, date = args.split(' ', 1)
        with STORE.db() as c:
            n = c.execute("UPDATE jobs SET due=?,state='draft',updated=? WHERE id=? AND state IN ('draft','queued')", (parse_start(date), time.time(), int(jid))).rowcount
        result = f'Đã đổi lịch {n} lượt. Xem /queue rồi duyệt lại.'
    elif command in {'/interval', '/random'}:
        interval = args
        if command == '/random':
            minimum, maximum = args.split()
            interval = minimum+'-'+maximum
        bounds = interval_bounds(interval)
        count = STORE.retime(interval)
        STORE.set('interval_minutes', bounds[0])
        result = f'Đã đặt khoảng nghỉ {interval} phút cho {count} lượt chờ. Lịch đã tạm dừng. Xem /queue rồi /approve_all và /run. Giờ thực tế có thể trễ nếu PC bận hoặc mất mạng.'
    elif command == '/run':
        run_queue()
        result = '▶ Đã chạy lịch được duyệt. Chỉ hoạt động khi PC bật, có mạng và phiên Windows mở khóa. /pause để dừng.'
    elif command in {'/pause', '/stop'}:
        pause(command == '/stop')
        result = '⏸ Đã yêu cầu dừng. Bot vẫn nhận lệnh; lượt đang thao tác sẽ được kiểm tra trạng thái trước khi kết thúc.'
    elif command == '/browser':
        from desktop import launch_browser
        launch_browser(DATA, 'https://www.facebook.com/')
        result = 'Đã mở trình duyệt Facebook trên PC. Đăng nhập Facebook trực tiếp tại đó; không gửi mật khẩu qua bot.'
    elif command == '/aiusage':
        usage=ai_provider.usage_summary(STORE);quota=STORE.get('xkiro_quota',{})
        result=f"xKiro hôm nay (giờ VN): {usage['calls']} lần gọi · {usage['total_tokens']:,} token API đã báo.\nKhông có số token đầy đủ: {usage['unknown_calls']} lần."
        if quota.get('checked_at'):result+='\nHạn mức tài khoản còn (lần kiểm tra gần nhất): '+str(quota.get('remaining'))+' token. Xem Cài đặt để cập nhật.'
    elif command == '/check':
        result = check_services()
    elif command == '/history':
        result = '\n'.join(f"#{j['id']} {j['state']} · {j['group_name']}\n{j['detail']}" for j in STORE.rows("SELECT * FROM jobs WHERE hidden=0 AND state NOT IN ('draft','queued') ORDER BY updated DESC LIMIT 12")) or 'Chưa có lịch sử.'
    else:
        result = 'Chưa hiểu lệnh. /help để xem hướng dẫn; /menu để mở nút bấm.'
    # Telegram caps message length; split full content rather than silently hiding approval text.
    for i in range(0, len(result), 3800):
        STORE.notify(result[i:i+3800])


def review_keyboard(row):
    return {'inline_keyboard':[[{'text':'Xem nhóm','url':row['url']}]]+(
        [[{'text':'Mở bài viết','url':row['post_url']}]] if row.get('post_url') else [])+[
        [{'text':'Giữ nhóm','callback_data':f"review:keep:{row['id']}"},
         {'text':'Xóa nhóm','callback_data':f"review:delete:{row['id']}"}]]}


def notify_approval_result(job,result):
    from final_report import render
    rows=STORE.rows('SELECT * FROM group_reviews WHERE job_id=?',(job['id'],))
    review=rows[0] if rows else None
    text=render(job,result)
    STORE.notify(text,result.get('photo',''),review_keyboard(review) if review else None,text)


def handle_callback(query):
    if query.get('from',{}).get('id')!=STORE.get('owner_id') or query.get('message',{}).get('chat',{}).get('id')!=STORE.get('owner_chat'):
        return
    if panel_callback(query):return
    post_deletion=re.fullmatch(r'postdelete:(yes|no):([a-f0-9]{16})',query.get('data',''))
    if post_deletion:
        pending=STORE.get('pending_delete_post')
        if not pending or pending.get('nonce')!=post_deletion[2] or time.time()-pending['at']>600:
            telegram('answerCallbackQuery',{'callback_query_id':query['id'],'text':'Yêu cầu đã hết hạn. Mở kho bài lại.','show_alert':True});return
        if post_deletion[1]=='yes':
            STORE.delete_contents([pending['id']])
            text=f"Đã xóa bài #{pending['id']} khỏi kho. Lịch cũ giữ bản đã chốt."
        else:text='Đã hủy xóa bài.'
        STORE.set('pending_delete_post',None)
        telegram('answerCallbackQuery',{'callback_query_id':query['id'],'text':text})
        telegram('editMessageText',{'chat_id':STORE.get('owner_chat'),'message_id':query['message']['message_id'],'text':text,'reply_markup':{'inline_keyboard':[[{'text':'📝 Kho bài','callback_data':'panel:posts:0'},{'text':'🏠 Menu chính','callback_data':'panel:home:0'}]]}})
        return
    deletion=re.fullmatch(r'groupdelete:(yes|no):([a-f0-9]{16})',query.get('data',''))
    if deletion:
        pending=STORE.get('pending_delete_group')
        if not pending or pending.get('nonce')!=deletion[2] or time.time()-pending['at']>600:
            telegram('answerCallbackQuery',{'callback_query_id':query['id'],'text':'Yêu cầu đã hết hạn hoặc đã xử lý. Gửi /deletegroup lại.','show_alert':True});return
        if deletion[1]=='yes':
            deleted=STORE.delete_group(pending['id'])
            text=f"Đã xóa nhóm #{pending['id']} · {deleted['name']} khỏi danh sách sử dụng. Hủy {deleted['cancelled']} lượt chưa chạy. Lịch sử vẫn được lưu."
        else:text='Đã hủy yêu cầu xóa nhóm.'
        STORE.set('pending_delete_group',None)
        telegram('answerCallbackQuery',{'callback_query_id':query['id'],'text':text[:190]})
        telegram('editMessageText',{'chat_id':STORE.get('owner_chat'),'message_id':query['message']['message_id'],'text':text,'reply_markup':{'inline_keyboard':[]}})
        return
    match=re.fullmatch(r'review:(keep|delete):(\d+)',query.get('data',''))
    if not match:return
    decision=STORE.decide_review(int(match[2]),match[1])
    text='Đã giữ lại nhóm.' if decision=='keep' else 'Đã xóa nhóm khỏi danh sách sử dụng, hủy lịch chưa chạy. Lịch sử vẫn được lưu.'
    telegram('answerCallbackQuery',{'callback_query_id':query['id'],'text':text[:190]})
    telegram('editMessageReplyMarkup',{'chat_id':STORE.get('owner_chat'),'message_id':query['message']['message_id'],'reply_markup':{'inline_keyboard':[]}})


def poll_loop():
    registered = ''
    while not SHUTDOWN.is_set():
        try:
            cfg = load_config()
            if not cfg.get('token'):
                SHUTDOWN.wait(2)
                continue
            if registered != cfg['token']:
                telegram('setMyCommands', {'commands':[{'command':n,'description':d} for n,d in bot_ui.COMMANDS]})
                telegram('setChatMenuButton',{'menu_button':{'type':'commands'},**({'chat_id':STORE.get('owner_chat')} if STORE.get('owner_chat') else {})})
                registered = cfg['token']
            updates = telegram('getUpdates', {'offset': STORE.get('offset', 0), 'timeout': 20, 'allowed_updates': ['message','callback_query']}, timeout=30)
            STORE.set('telegram_last_ok', time.time())
            STORE.set('telegram_error','')
            for update in updates:
                try:
                    if 'callback_query' in update:
                        handle_callback(update['callback_query'])
                    if 'message' in update:
                        handle_message(update['message'])
                except Exception as exc:
                    if update.get('callback_query',{}).get('from',{}).get('id')==STORE.get('owner_id'):
                        telegram('answerCallbackQuery',{'callback_query_id':update['callback_query']['id'],'text':safe_error(exc)[:190],'show_alert':True})
                    if update.get('message', {}).get('from', {}).get('id') == STORE.get('owner_id'):
                        STORE.notify('❌ ' + safe_error(exc) + '\n/help để xem cú pháp.')
                STORE.set('offset', update['update_id'] + 1)
        except Exception as exc:
            STORE.set('telegram_error', safe_error(exc))
            SHUTDOWN.wait(5)


def send_photo(chat, photo, caption, reply_markup=None):
    boundary = 'nct' + secrets.token_hex(16)
    raw = bytearray()
    for key, val in {'chat_id': str(chat), 'caption': caption[:900]}.items():
        raw.extend(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{val}\r\n'.encode())
    if reply_markup:
        raw.extend(f'--{boundary}\r\nContent-Disposition: form-data; name="reply_markup"\r\n\r\n{json.dumps(reply_markup,ensure_ascii=False)}\r\n'.encode())
    raw.extend(f'--{boundary}\r\nContent-Disposition: form-data; name="photo"; filename="receipt.png"\r\nContent-Type: image/png\r\n\r\n'.encode())
    raw.extend(Path(photo).read_bytes())
    raw.extend(f'\r\n--{boundary}--\r\n'.encode())
    req = urllib.request.Request(f"https://api.telegram.org/bot{load_config()['token']}/sendPhoto", data=bytes(raw), headers={'Content-Type': 'multipart/form-data; boundary='+boundary})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            result = json.load(r)
        if not result.get('ok'):
            raise RuntimeError('Gửi ảnh không thành công.')
    except (urllib.error.URLError, OSError):
        raise RuntimeError('Gửi ảnh Telegram không thành công.') from None


def deliver_outbox_item(chat,item):
    """One Telegram message: photo + final caption + buttons, or text only."""
    if item['text_sent']:return  # A pre-upgrade row already sent text; do not repeat it.
    markup=json.loads(item['reply_markup'])
    if item['photo'] and Path(item['photo']).is_file():
        caption=item['text'] if len(item['text'])<=900 else (item['photo_caption'] or item['text'][:900])
        send_photo(chat,item['photo'],caption,reply_markup=markup)
    else:
        send_text(chat,item['text'],reply_markup=markup)
    with STORE.db() as c:c.execute('UPDATE outbox SET text_sent=1 WHERE id=?',(item['id'],))


def outbox_loop():
    while not SHUTDOWN.is_set():
        try:
            chat = STORE.get('owner_chat')
            rows = STORE.rows('SELECT * FROM outbox WHERE next<=? ORDER BY id LIMIT 1', (time.time(),)) if chat else []
            if not rows:
                SHUTDOWN.wait(1)
                continue
            item = rows[0]
            try:
                deliver_outbox_item(chat,item)
                with STORE.db() as c:
                    c.execute('DELETE FROM outbox WHERE id=?', (item['id'],))
            except Exception:
                with STORE.db() as c:
                    c.execute('UPDATE outbox SET tries=tries+1,next=? WHERE id=?', (time.time()+min(300, 2**min(item['tries']+1, 8)), item['id']))
                SHUTDOWN.wait(2)
        except Exception as exc:
            logging.error('Outbox: %s', safe_error(exc))
            SHUTDOWN.wait(3)


def cleanup_worker_browser(p):
    lease=getattr(p,'nct_window_lease',None)
    if not isinstance(lease,(str,Path)):return
    try:
        from browser_cleanup import recover
        recover(lease,DATA,p.pid)
    except Exception as exc:logging.error('Browser cleanup: %s',safe_error(exc))


def terminate_worker(p):
    try:
        if p.poll() is None:
            from browser_cleanup import stop_worker
            stop_worker(p)
    finally:
        if p.poll() is not None:cleanup_worker_browser(p)


def run_link_refresh_once():
    global ACTIVE_PROCESS
    import link_refresh
    with CONFIG_LOCK:item=link_refresh.claim(STORE)
    if not item:return False
    rid=item['refresh_id'];p=None;reason=''
    try:
        work=DATA/'work';work.mkdir(exist_ok=True)
        result_path=work/f"result-refresh-{rid}.json"
        progress_path=work/f"progress-refresh-{rid}.json"
        job_path=work/f"job-refresh-{rid}.json"
        result_path.unlink(missing_ok=True);progress_path.unlink(missing_ok=True)
        item.update(data_dir=str(DATA),model=load_config()['model'],mode='publish',result=str(result_path),progress=str(progress_path),browser_lease=str(work/f"browser-refresh-{rid}.json"))
        job_path.write_text(json.dumps(item,ensure_ascii=False),encoding='utf-8')
        STORE.set('progress',f"Cập nhật link Facebook · bài lượt #{item.get('refresh_id')}")
        with open(DATA/'worker.log','ab') as log:
            p=subprocess.Popen([sys.executable,str(ROOT/'desktop.py'),str(job_path)],cwd=ROOT,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            p.nct_window_lease=item['browser_lease']
            with PROCESS_LOCK:ACTIVE_PROCESS=p
            started=time.monotonic()
            while p.poll() is None:
                if progress_path.exists():
                    try:STORE.set('progress','Cập nhật link: '+json.loads(progress_path.read_text(encoding='utf-8'))['text'])
                    except (ValueError,OSError):pass
                if STOP_WORK.is_set() or SHUTDOWN.is_set() or time.monotonic()-started>720:
                    reason='Đã dừng hoặc quá thời gian. Kiểm tra bài và bình luận; không tự lặp.'
                    terminate_worker(p);break
                SHUTDOWN.wait(.5)
        result=json.loads(result_path.read_text(encoding='utf-8')) if result_path.exists() and not reason else {'state':'uncertain','detail':reason or 'Tiến trình bị ngắt; cần kiểm tra Facebook.'}
        state=result.get('state','uncertain')
        if state not in {'updated','skipped','uncertain','error'}:state='uncertain'
        link_refresh.checkpoint(STORE,rid,state=state,detail=result.get('detail',''))
        actual=result.get('post_actor') if result.get('post_identity_verified') else 'chưa xác minh'
        text=f"🔗 Cập nhật link · {item['group_name']}\n{item['post_url']}\n{result.get('detail','Chưa xác minh.')}\nDanh tính bài: {actual}\nBình luận: {result.get('comment_status','chưa xác minh')}."
        STORE.notify(text,result.get('photo',''),photo_caption=text)
        STORE.set('progress',f"Cập nhật link #{rid}: "+result.get('detail',''))
        from queue_recovery import should_pause
        if should_pause(result):link_refresh.stop(STORE)
    except Exception as exc:
        link_refresh.checkpoint(STORE,rid,state='uncertain',detail=safe_error(exc))
        link_refresh.stop(STORE)
        STORE.notify('Cập nhật link cần kiểm tra: '+safe_error(exc))
    finally:
        if p is not None:
            if p.poll() is None:terminate_worker(p)
            cleanup_worker_browser(p)
        with PROCESS_LOCK:ACTIVE_PROCESS=None
    # Keep the browser controller serial and interruptible between posts.
    if not STOP_WORK.is_set():
        for _ in range(30):
            if STOP_WORK.is_set() or SHUTDOWN.is_set():break
            SHUTDOWN.wait(1)
    return True


def run_approval_once():
    """One approval check on the same serialized browser worker as posting."""
    global ACTIVE_PROCESS
    import approval_followup
    if load_config()['mode']!='publish':return False
    with CONFIG_LOCK:job=approval_followup.claim(STORE,DATA)
    if not job:return False
    process=None;result={};finalized=False
    try:
        if STOP_WORK.is_set() or not approval_followup.enabled(STORE):raise RuntimeError('Người dùng yêu cầu dừng kiểm tra duyệt.')
        work=DATA/'work';work.mkdir(exist_ok=True)
        result_path=work/f"approval-result-{job['id']}.json"
        progress_path=work/f"approval-progress-{job['id']}.json"
        job_path=work/f"approval-job-{job['id']}.json"
        result_path.unlink(missing_ok=True);progress_path.unlink(missing_ok=True)
        payload={**job,'media':'','data_dir':str(DATA),'model':load_config()['model'],'mode':'publish','result':str(result_path),'progress':str(progress_path),'browser_lease':str(work/f"approval-browser-{job['id']}.json")}
        job_path.write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8')
        STORE.set('progress',f"Kiểm tra duyệt qua link · lượt #{job['id']}")
        reason=''
        with open(DATA/'worker.log','ab') as log:
            process=subprocess.Popen([sys.executable,str(ROOT/'desktop.py'),str(job_path)],cwd=ROOT,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            process.nct_window_lease=payload['browser_lease']
            with PROCESS_LOCK:ACTIVE_PROCESS=process
            started=time.monotonic()
            while process.poll() is None:
                if STOP_WORK.is_set() or SHUTDOWN.is_set() or not approval_followup.enabled(STORE) or time.monotonic()-started>600:
                    reason='Kiểm tra duyệt bị dừng; cần kiểm tra trước khi gửi bình luận lại.'
                    terminate_worker(process);break
                if progress_path.exists():
                    try:STORE.set('progress',f"Duyệt #{job['id']}: "+json.loads(progress_path.read_text(encoding='utf-8'))['text'])
                    except (ValueError,OSError):pass
                SHUTDOWN.wait(.5)
        result=json.loads(result_path.read_text(encoding='utf-8')) if result_path.exists() and not reason else {'state':'uncertain','detail':reason or 'Worker kiểm tra duyệt bị đóng.','comment_status':'uncertain','comment_attempted':True}
        result['approval_rechecked']=True
        notify=approval_followup.complete(STORE,job,result)
        finalized=True
        from queue_recovery import hard_pause
        if hard_pause(result):
            STORE.set('running',False);STORE.set('paused_by_user',True);STORE.set('approval_monitor_enabled',False)
            with STORE.db() as c:c.execute("UPDATE approval_checks SET state='review' WHERE job_id=?",(job['id'],))
            notify=True
        if notify:
            notify_approval_result(job,result)
        STORE.set('progress',f"Đã kiểm tra duyệt lượt #{job['id']}: "+result.get('detail','')[:200])
    except Exception as exc:
        if not finalized:approval_followup.complete(STORE,job,{'state':'uncertain','comment_status':'uncertain','comment_attempted':True,'detail':safe_error(exc)})
        logging.error('Approval followup: %s',safe_error(exc))
    finally:
        if process is not None:
            if process.poll() is None:terminate_worker(process)
            cleanup_worker_browser(process)
        with PROCESS_LOCK:ACTIVE_PROCESS=None
    return True


def scheduler_loop():
    global ACTIVE_PROCESS
    while not SHUTDOWN.is_set():
        job = None
        worker_started=False
        worker_process=None
        finalized=False
        try:
            if not runtime_ready():
                SHUTDOWN.wait(1);continue
            if run_link_refresh_once():continue
            if run_approval_once():continue
            job = STORE.claim()
            if not job:
                if STORE.get('running') and not STORE.rows("SELECT id FROM jobs WHERE state IN ('queued','working') LIMIT 1"):
                    STORE.set('running', False)
                    waiting=STORE.rows("SELECT job_id FROM approval_checks WHERE state='waiting' LIMIT 1")
                    STORE.set('progress','Đã gửi xong các lượt; tiếp tục theo dõi bài chờ duyệt.' if waiting else 'Đã hoàn tất các lượt đã duyệt. Hàng đợi tạm dừng.')
                SHUTDOWN.wait(1)
                continue
            STORE.set('progress', f"Lượt #{job['id']}: khởi động trình duyệt và Windows MCP")
            workdir = DATA / 'work'
            workdir.mkdir(exist_ok=True)
            job_path = workdir / f"job-{job['id']}.json"
            result_path = workdir / f"result-{job['id']}.json"
            progress_path = workdir / f"progress-{job['id']}.json"
            result_path.unlink(missing_ok=True)
            progress_path.unlink(missing_ok=True)
            cfg = load_config()
            control_ai=ai_provider.config(STORE)
            if control_ai['provider']=='xkiro':
                quota=ai_provider.check_connection(STORE)
                if quota.get('remaining') is not None and quota['remaining']<=0:raise ValueError('Đã hết token miễn phí xKiro hôm nay. Không tự chuyển sang trả phí.')
            job_path.write_text(json.dumps({**job, 'identity_profile_fallback':STORE.get('identity_profile_fallback',False), 'control_ai': {'provider':control_ai['provider'],'model':control_ai['model']}, 'data_dir': str(DATA), 'model': cfg['model'], 'mode': 'prepare' if job.get('prepare_only') else cfg['mode'], 'result': str(result_path), 'progress': str(progress_path), 'bounded_composer':True,'browser_lease':str(workdir/f"browser-{job['id']}.json")}, ensure_ascii=False), encoding='utf-8')
            started = time.monotonic()
            with open(DATA / 'worker.log', 'ab') as log:
                p = subprocess.Popen([sys.executable, str(ROOT/'desktop.py'), str(job_path)], cwd=ROOT, stdout=log, stderr=log,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0)
                p.nct_window_lease=workdir/f"browser-{job['id']}.json"
                worker_process=p
                worker_started=True
                with PROCESS_LOCK:
                    ACTIVE_PROCESS = p
                reason = ''
                while p.poll() is None:
                    if progress_path.exists():
                        try:
                            progress = json.loads(progress_path.read_text(encoding='utf-8'))
                            STORE.set('progress', f"#{job['id']}: {progress['text']}")
                        except (ValueError, OSError):
                            pass
                    if STOP_WORK.is_set() or SHUTDOWN.is_set():
                        reason = 'Người dùng yêu cầu dừng. Kiểm tra Facebook trước khi tạo lại lượt.'
                        terminate_worker(p)
                        break
                    worker_timeout=1200 if any(Path(p).suffix.lower() in {'.mp4','.mov','.webm'} for p in __import__('media').paths(job.get('media',''))) else 720
                    if time.monotonic()-started > worker_timeout:
                        reason = f'Tác vụ quá {worker_timeout//60} phút; bộ giám sát đã dừng tiến trình. Kiểm tra bài đã gửi chưa.'
                        terminate_worker(p)
                        break
                    SHUTDOWN.wait(0.5)
            if result_path.exists() and not reason:
                result = json.loads(result_path.read_text(encoding='utf-8'))
            else:
                result = {'state': 'uncertain', 'detail': reason or 'Tiến trình thao tác bị đóng hoặc gặp lỗi bất thường. Kiểm tra Facebook; không tự đăng lại.'}
            state = result.get('state', 'uncertain')
            detail = result.get('detail', '')
            STORE.finish(job['id'], state, detail,post_attempted=result.get('post_attempted'))
            finalized=True
            policy=STORE.queue_outcome(job['id'],result)
            result.update({k:v for k,v in policy.items() if k!='hard_pause'})
            STORE.refresh_global_cooldown()
            pause_result=policy['hard_pause']
            if state in {'uncertain','error'} and not pause_result:
                result['queue_compacted']=STORE.advance_after_review(job['id'])
                following=STORE.rows("SELECT j.id,j.due FROM jobs j JOIN groups g ON g.id=j.group_id WHERE j.state='queued' AND g.enabled=1 AND g.deleted=0 ORDER BY j.due,j.id LIMIT 1")
                result['queue_continues']=bool(STORE.get('running') and following)
                if following:result.update(queue_next_id=following[0]['id'],queue_next_due=following[0]['due'])
            else:STORE.reflow_queue()
            STORE.set('progress', f"Lượt #{job['id']} · {state}: {detail[:220]}")
            if pause_result:
                STORE.set('running', False)
                STORE.set('paused_by_user',True)
                STORE.set('approval_monitor_enabled',False)
                result['queue_paused_for_review']=True
            rid=STORE.record_result(job,result) if state in {'submitted','pending','uncertain','error'} else None
            if state=='pending':
                from approval_followup import enqueue
                tracked=enqueue(STORE,job['id'],result,DATA)
                result['approval_requires_link']=not tracked and not result.get('post_url')
                result['approval_tracking']=tracked
            from final_report import render
            text=render(job,result)
            review=STORE.rows('SELECT * FROM group_reviews WHERE id=?',(rid,))[0] if rid else None
            STORE.notify(text,result.get('photo',''),review_keyboard(review) if review else None,text)


        except Exception as exc:
            if finalized:
                # A delivery/reporting error cannot undo a verified posting outcome.
                logging.error('Post-processing job %s: %s',job['id'],safe_error(exc))
                STORE.set('progress',f"Lượt #{job['id']}: đã lưu kết quả; lỗi xử lý thông báo: "+safe_error(exc)[:200])
            elif job:
                failure={'state':'uncertain' if worker_started else 'error','detail':safe_error(exc),'post_attempted':None if worker_started else False}
                STORE.finish(job['id'], failure['state'], failure['detail'],post_attempted=failure['post_attempted'])
                policy=STORE.queue_outcome(job['id'],failure)
                STORE.refresh_global_cooldown();STORE.reflow_queue()
                if policy['hard_pause']:
                    STORE.set('running',False);STORE.set('paused_by_user',True);STORE.set('approval_monitor_enabled',False)
                STORE.set('progress',f"Lượt #{job['id']}: "+safe_error(exc)[:300])
                from final_report import render
                failure.update({k:v for k,v in policy.items() if k!='hard_pause'})
                STORE.notify(render(job,failure))
            else:
                STORE.set('running',False)
                STORE.notify('❌ Bộ lập lịch đã dừng: ' + safe_error(exc))
            logging.error('Scheduler: %s', safe_error(exc))
            SHUTDOWN.wait(2)
        finally:
            if worker_process is not None:
                if worker_process.poll() is None:terminate_worker(worker_process)
                cleanup_worker_browser(worker_process)
            with PROCESS_LOCK:
                ACTIVE_PROCESS = None


def check_services():
    lines = []
    try:
        models = request_json('http://127.0.0.1:11434/api/tags', timeout=5)
        names = [m['name'] for m in models.get('models', [])]
        lines.append('Ollama: ' + (', '.join(names) or 'đã chạy nhưng chưa tải model'))
        configured = load_config()['model']
        if configured not in names and configured+':latest' not in names:
            lines.append('Chưa có model đang chọn: ' + configured)
    except Exception as exc:
        lines.append('Ollama: ' + safe_error(exc))
    try:
        import importlib.metadata
        lines.append('Windows MCP: ' + importlib.metadata.version('windows-mcp'))
    except Exception:
        lines.append('Windows MCP: chưa cài hoặc không chạy trên Windows')
    control=ai_provider.config(STORE)
    lines.append('AI điều khiển: '+control['provider']+(' · '+control['model']+' · '+('key đã lưu' if control['key_saved'] else 'chưa có key') if control['provider']=='xkiro' else ' · '+load_config()['model']))
    lines.append('Telegram: ' + ('đã ghép tài khoản' if STORE.get('owner_id') else 'chưa ghép /pair'))
    return '\n'.join(lines)


def web_state():
    cfg = load_config()
    calendars=STORE.group_calendars()
    pending_approval_jobs=STORE.rows("SELECT id,group_name,state,post_url FROM jobs WHERE state='pending' AND hidden=0 AND calendar_released=0 ORDER BY id DESC LIMIT 100")
    targets=STORE.rows('SELECT content_id,group_id FROM content_targets')
    return {'chrome_profiles':__import__('facebook_accounts').chrome_profiles(),'facebook_accounts':__import__('facebook_accounts').catalog(STORE),'approval_pending_jobs':pending_approval_jobs,'approval_checks':__import__('approval_followup').status(STORE),'approval_monitor_paused':not __import__('approval_followup').enabled(STORE),'browser':__import__('desktop').browser_status(DATA),'runtime':{'revision':RUNTIME_REVISION,'restart_required':code_revision(ROOT)!=RUNTIME_REVISION},'paired': bool(STORE.get('owner_id')), 'pair_command': '' if STORE.get('owner_id') else '/pair '+STORE.get('pair_code'),
        'online_update':__import__('online_update').status(STORE),'deployment_notice':STORE.get('deployment_notice',''),'desktop_app':bool(os.environ.get('NCT_DESKTOP')),'configured': bool(cfg.get('token')), 'username': cfg.get('username', ''), 'model': cfg['model'], 'mode': cfg['mode'],
        'status': status_text(), 'groups': [{**g,'calendar':calendars.get(g['id'],{}),'media_pools':[m['pool'] for m in STORE.rows('SELECT pool FROM group_media_pools WHERE group_id=?',(g['id'],))]} for g in STORE.rows('SELECT * FROM groups WHERE deleted=0 ORDER BY id')],
        'group_statistics_reset_at':STORE.get('group_metrics_reset',{}).get('at',0),'group_statistics':__import__('group_metrics').statistics(STORE),'group_watchlist':STORE.group_watchlist(),
        'reviews': STORE.rows("SELECT * FROM group_reviews WHERE decision='' ORDER BY updated DESC"),
        'contents': [{**p,'target_group_ids':[t['group_id'] for t in targets if t['content_id']==p['id']],'attachments':media_store.public(p['media']),'no_link_attachments':media_store.public(p['media_no_link'])} for p in STORE.rows('SELECT * FROM contents ORDER BY id DESC LIMIT 100')],
        'studio': STORE.get('studio_task',{}),'group_scan':STORE.get('group_scan',{}),'batch_options':STORE.get('batch_options',{}),'post_footer':post_footer.config(STORE),'single_image_options':STORE.get('single_image_options',{}),
        'content_ai':content_ai.config(STORE),'kira_vision_catalog':STORE.get('kira_vision_catalog',{}),'media_pools':(*media_library.POOLS,'ALL'),'media_catalog':media_library.catalog(STORE),'daily_group_limit':STORE.get('daily_group_limit',20),'resume_approved_on_start':STORE.get('resume_approved_on_start',False),'footer_comment_fallback':STORE.get('footer_comment_fallback',False),
        'ai_sources':__import__('ai_sources').catalog(STORE),'control_ai':ai_provider.config(STORE),'ai_usage':ai_provider.usage_summary(STORE),'xkiro_quota':STORE.get('xkiro_quota',{}),
        'link_refresh': __import__('link_refresh').status(STORE),'links': STORE.link_inventory(), 'current_link': STORE.get('current_link',''),
        'categories': sorted({'Chung','ALL',*media_library.POOLS} | {g['category'] for g in STORE.rows('SELECT category FROM groups') if g['category']} | {p['category'] for p in STORE.rows('SELECT category FROM contents') if p['category']}),
        'jobs': STORE.rows('SELECT * FROM jobs WHERE hidden=0 ORDER BY id DESC LIMIT 100'),
        'telegram_ok': STORE.get('telegram_last_ok'), 'telegram_error': STORE.get('telegram_error', '')}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, status, data, content_type='application/json; charset=utf-8'):
        raw = data if isinstance(data,bytes) else (data.encode() if isinstance(data,str) else json.dumps(data,ensure_ascii=False).encode())
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; img-src 'self' blob: data:; media-src 'self' blob:; frame-ancestors 'none'; base-uri 'none'")
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def authorized(self):
        if self.headers.get('Host') != f'127.0.0.1:{PORT}':
            return False
        origin = self.headers.get('Origin')
        if origin and origin != LOCAL:
            return False
        key = self.headers.get('X-NCT-Key') or parse_qs(urlsplit(self.path).query).get('key', [''])[0]
        return secrets.compare_digest(key, WEB_KEY)

    def do_GET(self):
        if not self.authorized():
            self.send(403, {'error': 'Mở trang bằng đường dẫn được in trong cửa sổ chương trình.'})
            return
        path = urlsplit(self.path).path
        if path == '/':
            self.send(200, (ROOT/'ui.html').read_text(encoding='utf-8').replace('__WEB_KEY__', WEB_KEY), 'text/html; charset=utf-8')
        elif path in {'/assets/inter-latin.woff2','/assets/inter-latin-ext.woff2','/assets/inter-vietnamese.woff2','/assets/instrument-serif-italic.woff2'}:
            self.send(200,(ROOT/path.lstrip('/')).read_bytes(),'font/woff2')
        elif path == '/brand-logo.png':
            self.send(200,(ROOT/'assets'/'brand-logo.png').read_bytes(),'image/png')
        elif path == '/api/review-photo':
            try:
                rid=int(parse_qs(urlsplit(self.path).query).get('id',['0'])[0])
                rows=STORE.rows('SELECT photo FROM group_reviews WHERE id=?',(rid,))
                photo=Path(rows[0]['photo']).resolve() if rows and rows[0]['photo'] else None
                if not photo or not photo.is_relative_to((DATA/'work').resolve()) or photo.suffix.lower()!='.png' or not photo.is_file():
                    self.send(404,{'error':'Không có ảnh bằng chứng.'});return
                self.send(200,photo.read_bytes(),'image/png')
            except (ValueError,OSError):self.send(404,{'error':'Không có ảnh bằng chứng.'})
        elif path == '/api/state':
            self.send(200, web_state())
        elif path.startswith('/api/media/'):
            name=path.rsplit('/',1)[-1]
            base=(DATA/'media').resolve();target=(base/name).resolve()
            if not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}',name) or not target.is_relative_to(base) or not target.is_file():
                self.send(404,{'error':'Không tìm thấy tệp.'});return
            size=target.stat().st_size;start=0;end=size-1
            header=self.headers.get('Range','')
            if header:
                match=re.fullmatch(r'bytes=(\d+)-(\d*)',header)
                if not match:self.send(416,{'error':'Range không hợp lệ.'});return
                start=int(match[1]);end=min(int(match[2]) if match[2] else end,end)
                if start>end:self.send(416,{'error':'Range không hợp lệ.'});return
            self.send_response(206 if header else 200)
            self.send_header('Content-Type',mimetypes.guess_type(name)[0] or 'application/octet-stream')
            self.send_header('Accept-Ranges','bytes');self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff');self.send_header('Content-Length',str(end-start+1))
            if header:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
            self.end_headers()
            with target.open('rb') as f:
                f.seek(start);left=end-start+1
                while left:
                    chunk=f.read(min(left,1024*1024));self.wfile.write(chunk);left-=len(chunk)
        else:
            self.send(404, {'error': 'Không tìm thấy.'})

    def do_POST(self):
        if not self.authorized():
            self.send(403, {'error': 'Không được phép.'})
            return
        try:
            size = int(self.headers.get('Content-Length', '0'))
            route = urlsplit(self.path).path
            if route=='/api/desktop-close' and os.environ.get('NCT_DESKTOP'):
                if STUDIO is not None:STUDIO.stop()
                self.send(200,{'message':'Đang dừng tác vụ và đóng ứng dụng.'})
                threading.Thread(target=self.server.shutdown,daemon=True).start()
                return
            if route=='/api/update-feed':
                STORE.set('update_feed',__import__('online_update').url(json.loads(self.rfile.read(size)).get('url','')))
                self.send(200,{'message':'Đã lưu nguồn cập nhật HTTPS.'});return
            if route=='/api/update-check':
                self.send(200,__import__('online_update').check(STORE,ROOT));return
            if route=='/api/update-download':
                if not os.environ.get('NCT_DESKTOP'):raise ValueError('Cài cập nhật từ ứng dụng EXE.')
                with STORE.db() as c:
                    if c.execute("SELECT 1 FROM jobs WHERE state='working'").fetchone() or c.execute("SELECT 1 FROM approval_checks WHERE state='working'").fetchone():raise ValueError('Đang thao tác Facebook; chờ lượt hiện tại xong rồi cập nhật.')
                self.send(200,__import__('online_update').download(STORE,ROOT,DATA));return
            if route=='/api/deployment-dismiss':
                STORE.set('deployment_notice','');self.send(200,{'message':'Đã ẩn thông báo.'});return
            if route=='/api/upload':
                query=parse_qs(urlsplit(self.path).query)
                filename=query.get('filename',[''])[0];pool=query.get('pool',[''])[0]
                if pool:media_library.pool(pool)
                self.connection.settimeout(300)
                uploaded=media_store.receive(self.rfile,size,filename,DATA/'media')
                media_library.register(STORE,DATA/'media',uploaded,pool)
                self.send(200,{'message':'Đã thêm tệp.','file':uploaded});return
            if not 0 < size <= 100000:
                raise ValueError('Yêu cầu quá lớn hoặc trống.')
            obj = json.loads(self.rfile.read(size))
            route = urlsplit(self.path).path
            if route == '/api/media-from-url':
                from remote_media import receive_image
                uploaded=receive_image(obj.get('url',''),DATA/'media')
                media_library.register(STORE,DATA/'media',uploaded,'')
                self.send(200,{'message':'Đã thêm ảnh.','file':uploaded});return
            if route == '/api/setup':
                result = 'Đã kết nối @' + save_config(obj) + '. Gửi lệnh ghép đang hiển thị vào bot.'
            elif route == '/api/group':
                gid = STORE.add_group(obj['url'], obj.get('name', ''), obj.get('rules', ''), obj.get('link_policy', 'unknown'), obj.get('category','Chung'))
                result = f'Đã lưu nhóm #{gid}. Nhóm mới đang tắt; bật sau khi kiểm tra quy định.'
            elif route == '/api/group-watch-decision':
                decision=STORE.decide_group_watch(int(obj['id']),obj.get('decision',''))
                result='Đã giữ nhóm; bắt đầu đếm lượt mới.' if decision=='keep' else 'Đã xóa nhóm khỏi tool.'
            elif route == '/api/facebook-account-existing-chrome':
                __import__('facebook_accounts').use_chrome_profile(STORE,str(obj.get('profile_id','')),obj.get('name',''),obj.get('facebook_account',''))
                result='Đã thêm hồ sơ Chrome. Chọn tài khoản này ở các nhóm cần dùng.'
            elif route == '/api/facebook-account-add':
                aid=__import__('facebook_accounts').create(STORE,DATA,obj.get('name',''),obj.get('facebook_account',''))
                result='Đã tạo hồ sơ riêng. Bấm Mở Facebook để tự đăng nhập, rồi gán tài khoản cho nhóm.'
            elif route == '/api/group-account':
                changed=__import__('facebook_accounts').assign(STORE,int(obj['id']),str(obj['account_id']))
                result=f"Đã chọn tài khoản; đồng bộ {changed['changed']} lịch chưa thao tác. {changed['blocked']} bài riêng khác tài khoản cần xem lại. Bài đã gửi giữ tài khoản gốc."
            elif route == '/api/facebook-account-rename':
                name=str(obj.get('name','')).strip()
                if not name or len(name)>80:raise ValueError('Tên cần 1–80 ký tự.')
                with STORE.db() as c:
                    if not c.execute('UPDATE facebook_accounts SET name=? WHERE id=?',(name,str(obj['id']))).rowcount:raise ValueError('Không tìm thấy tài khoản.')
                result='Đã đổi tên tài khoản.'
            elif route == '/api/group-toggle':
                STORE.enable_group(int(obj['id']), bool(obj['enabled']))
                result = 'Đã cập nhật nhóm.'
            elif route == '/api/group-calendar-reset-all':
                released=STORE.reset_all_group_calendars(obj.get('revisions'),obj.get('confirmed') is True)
                result=f"Đã trả lịch trống {released['groups']} nhóm; hủy {released['cancelled']} lịch chờ."
            elif route == '/api/group-calendar-reset':
                released=STORE.reset_group_calendar(int(obj['id']),obj.get('revision',''),obj.get('confirmed_not_posted') is True)
                result=f"Đã trả nhóm về lịch trống; hủy {released['cancelled']} lịch chờ. Có thể gen lịch mới. Lịch sử cũ vẫn được giữ."
            elif route == '/api/approval-monitor':
                result=control_approval_monitor(obj.get('action',''))
            elif route == '/api/approval-link':
                from receipts import post_url
                from approval_followup import enqueue,busy
                with STORE.db() as c:
                    c.execute('BEGIN IMMEDIATE')
                    if busy(c):raise ValueError('Đang kiểm tra duyệt; chờ lượt hiện tại hoàn tất.')
                    job=c.execute("SELECT * FROM jobs WHERE id=? AND state='pending' AND hidden=0 AND calendar_released=0",(int(obj['id']),)).fetchone()
                    if not job:raise ValueError('Chỉ gắn link cho lượt đang chờ duyệt còn trong lịch.')
                    link=post_url(str(obj.get('post_url','')),job['url'])
                    if not link:raise ValueError('Link bài phải thuộc đúng nhóm của lượt đang chờ duyệt.')
                    c.execute('UPDATE jobs SET post_url=? WHERE id=?',(link,job['id']))
                    c.execute('DELETE FROM approval_checks WHERE job_id=?',(job['id'],))
                enqueue(STORE,job['id'],{'state':'pending','post_url':link},DATA)
                result='Đã lưu link để kiểm tra duyệt. Chỉ bình luận sau khi đối chiếu đúng bài đã xuất bản; không đăng lại.'
            elif route == '/api/groups-toggle':
                changed=STORE.toggle_groups(obj.get('ids'),bool(obj.get('enabled')))
                self.send(200,{'message':f"Đã {'bật' if changed['enabled'] else 'tắt'} {changed['changed']} nhóm.",'changed':changed});return
            elif route == '/api/review':
                STORE.decide_review(int(obj['id']),obj['decision'])
                result='Đã ghi nhận lựa chọn xem xét nhóm.'
            elif route == '/api/group-comments':
                STORE.set_comment_policy(int(obj['id']),obj['policy']);result='Đã cập nhật quyền link trong bình luận.'
            elif route == '/api/group-identity':
                count=STORE.set_posting_identity(int(obj['id']),obj.get('mode','default'),obj.get('nickname',''))
                result=f'Đã lưu danh tính đăng. Hủy {count} lịch cũ chưa chạy; tạo lại lịch để áp dụng.'
            elif route == '/api/group-policy':
                STORE.set_link_policy(int(obj['id']), obj['link_policy'])
                result = 'Đã đổi quy định link. Lên lịch lại cho nhóm để áp dụng phiên bản phù hợp.'
            elif route == '/api/group-category':
                STORE.group_category(int(obj['id']),obj['category']);result='Đã cập nhật phân loại nhóm.'
            elif route == '/api/content-targets':
                cancelled=STORE.targets(int(obj['content_id']),obj['mode'],obj.get('group_ids',[]))
                result=f'Đã lưu nhóm đích. Hủy {cancelled} lượt cũ bị ảnh hưởng; tạo lại lịch để áp dụng.'
            elif route == '/api/classify':
                self.send(200,studio().classify(obj['ids'],obj['categories']));return
            elif route == '/api/link-preview':
                self.send(200,{'message':'Đã tính số bài và lượt bị ảnh hưởng.','preview':STORE.preview_links(obj['old_url'],obj['new_url'],bool(obj.get('facebook')))});return
            elif route == '/api/link-apply':
                changed=apply_link_change(obj['old_url'],obj['new_url'],obj.get('digest'),bool(obj.get('facebook')))
                self.send(200,{'message':f"Đã đổi link trong {changed['content_count']} bài và {changed['job_count']} lượt chưa chạy. Cập nhật Facebook: {changed.get('facebook_count',0)} bài trong 36 giờ gần nhất. Hàng đợi đăng mới vẫn tạm dừng.",'changed':changed});return
            elif route == '/api/stop-link-refresh':
                pause();result='Đã yêu cầu dừng cập nhật link. Lượt đã thao tác sẽ được giữ để kiểm tra, không tự gửi trùng.'
            elif route == '/api/generate':
                self.send(200,studio().start(obj));return
            elif route == '/api/stop-ai':
                self.send(200,studio().stop());return
            elif route == '/api/delete-contents':
                if studio().lock.locked():raise ValueError('AI đang tạo bài. Chờ hoàn tất rồi xóa bài trong kho.')
                count=STORE.delete_contents(obj.get('ids'))
                result=f'Đã xóa {count} bài khỏi kho. Các lịch đã tạo và tệp gốc được giữ nguyên.'
            elif route == '/api/content':
                owner=str(obj.get('account_id',''))
                if owner and not STORE.rows('SELECT id FROM facebook_accounts WHERE id=?',(owner,)):raise ValueError('Chọn tài khoản hợp lệ cho bài viết.')
                m,alt,automatic_images=media_library.resolve_for_save(STORE,DATA/'media',obj)
                if automatic_images:obj['category']=automatic_images[0][0]['pool']
                values=(obj['body'],m,obj.get('body_no_link',''),obj.get('category','Chung'),obj.get('title',''),alt)
                cid=STORE.update_content(int(obj['id']),*values) if obj.get('id') else STORE.content(*values)
                STORE.content_account(cid,owner)
                if 'comment_mode' in obj:STORE.set_comment_settings(cid,obj['comment_mode'],obj.get('comment_link',''),obj.get('tiktok_id',''),obj.get('comment_fallback_text',''),obj.get('comment_identity','follow'),obj.get('comment_nickname',''))
                if automatic_images:media_library.mark_used(STORE,[r['id'] for r,a in automatic_images])
                self.send(200,{'message':f'Đã lưu bài #{cid}.'+((' Tự gắn 1 video.' if automatic_images[0][0]['kind']=='video' else f' Tự gắn {len(automatic_images)} ảnh.') if automatic_images else ''),'content_id':cid,'category':obj['category'],'attachments':media_store.public(m),'no_link_attachments':media_store.public(alt)});return
            elif route == '/api/no-link':
                STORE.no_link_content(int(obj['id']), obj['body'])
                result = 'Đã lưu bản không link. Lịch cũ giữ nguyên; lên lịch lại nếu cần.'
            elif route == '/api/plan':
                result = create_plan(int(obj['content_id']), obj['minutes'], parse_start(obj.get('start', '')))
            elif route == '/api/test-one':
                if not STORE.get('owner_id'):raise ValueError('Ghép Telegram trước khi thử thao tác.')
                if studio().lock.locked():raise ValueError('AI đang bận; chờ tác vụ hoàn tất rồi thử.')
                jid=STORE.prepare_test(int(obj['content_id']),int(obj['group_id']),obj.get('minutes','30-60'))
                run_queue()
                result=f'Đã tạo lượt thử #{jid} cho 1 bài / 1 nhóm. Chỉ điền bài, luôn dừng trước nút Đăng. Xem trạng thái nếu đang chờ giới hạn đăng.'
            elif route == '/api/cycle':
                if obj.get('activate') and (not STORE.get('owner_id') or load_config()['mode']!='publish'):
                    raise ValueError('Ghép Telegram và chọn chế độ Tự đăng trong Cài đặt trước khi bật chiến dịch.')
                cids=obj.get('content_ids') if 'content_ids' in obj else [int(obj['content_id'])]
                ids = STORE.cycle_pool(cids,obj.get('group_ids'), obj['minutes'], int(obj['min_days']), int(obj['max_days']), int(obj['horizon']), parse_start(obj.get('start', '')),routing_mode=obj.get('routing_mode','category'))
                if obj.get('activate'):
                    if not ids:raise ValueError('Không có nhóm phù hợp hoặc nhóm đã có lịch. Chưa bật chiến dịch.')
                    STORE.approve(ids);run_queue()
                result = f'Đã tạo {len(ids)} lượt nháp. Mỗi nhóm tối đa 1 bài/ngày, khoảng nghỉ giữa hai lượt của cùng nhóm theo số ngày bạn chọn. Xem và duyệt lịch trước khi chạy.'
                if obj.get('activate'):result=f'Đã bật {len(ids)} lượt tự đăng trong phạm vi chiến dịch bạn chọn.'
            elif route == '/api/bot-menu':
                chat=STORE.get('owner_chat')
                if not chat:raise ValueError('Ghép tài khoản Telegram trước.')
                send_text(chat,'NCT Studio · Menu đã cập nhật. Chọn chức năng bên dưới.',True)
                panel(chat)
                result='Đã gửi menu mới vào Telegram của bạn.'
            elif route == '/api/job-restore':
                result=queue_action(int(obj['id']))
            elif route == '/api/job-now':
                result=queue_action(int(obj['id']),True)
            elif route == '/api/clear-jobs':
                result=clear_job_list()
            elif route == '/api/approve':
                ids = [j['id'] for j in STORE.rows("SELECT id FROM jobs WHERE state='draft'")] if obj.get('all') else [int(x) for x in obj['ids']]
                result = f"Đã duyệt {STORE.approve(ids)} lượt."
            elif route == '/api/control':
                if obj['action'] == 'run':
                    run_queue()
                elif obj['action'] in {'pause', 'stop'}:
                    pause(obj['action'] == 'stop')
                else:
                    raise ValueError('Lệnh không hợp lệ.')
                result = 'Đã cập nhật.'
            elif route == '/api/post-footer':
                if studio().lock.locked():raise ValueError('AI đang tạo bài. Chờ xong rồi sửa nội dung cố định để tránh nhầm phiên bản.')
                value=post_footer.save(STORE,obj)
                self.send(200,{'message':'Đã lưu nội dung cố định cuối bài. Áp dụng cho bài AI tạo sau; bài và lịch cũ giữ nguyên.','post_footer':value});return
            elif route == '/api/source-save':
                with CONFIG_LOCK:source=__import__('ai_sources').save(STORE,obj)
                self.send(200,{'message':'Đã lưu nguồn AI.','source':source});return
            elif route == '/api/source-delete':
                with CONFIG_LOCK:__import__('ai_sources').delete(STORE,obj['id'])
                result='Đã xóa nguồn và key đã lưu.'
            elif route == '/api/source-check':
                self.send(200,{'message':'Đã kiểm tra danh sách model.','check':__import__('ai_sources').check(STORE,obj['id'])});return
            elif route == '/api/content-ai':
                if studio().lock.locked() or STORE.rows("SELECT id FROM jobs WHERE state='working'"):raise ValueError('Đang xử lý tác vụ. Tạm dừng và chờ xong trước khi đổi AI.')
                
                with CONFIG_LOCK:content_ai.save_config(STORE,obj)
                pause()
                result='Đã lưu AI viết bài và quét ảnh. Key trống giữ nguyên. Lịch đang tạm dừng.'
            elif route == '/api/kira-models':
                self.send(200,{'message':'Đã cập nhật model đang miễn phí, nhận ảnh, không yêu cầu Pro.','result':content_ai.refresh_vision_models(STORE)});return
            elif route == '/api/check-kira':
                self.send(200,{'message':'Đã đọc danh sách model KiraAI; chưa gửi ảnh.','result':content_ai.check_vision(STORE)});return
            elif route == '/api/media-archive':
                if studio().lock.locked():raise ValueError('AI đang dùng kho ảnh. Chờ tác vụ hoàn tất rồi xóa/khôi phục.')
                restore=obj.get('restore') is True
                count=media_library.archive(STORE,obj.get('ids'),restore)
                result=f'Đã khôi phục {count} tệp vào kho.' if restore else f'Đã chuyển {count} tệp vào Thùng rác. Bài và lịch đã lưu vẫn giữ ảnh; có thể khôi phục.'
            elif route == '/api/media-pool':
                media_library.assign(STORE,DATA/'media',obj.get('ids'),obj.get('pool'));result='Đã gán tệp vào kho game.'
            elif route == '/api/group-media-pools':
                media_library.group_pools(STORE,int(obj['id']),obj.get('pools'));result='Đã gán kho ảnh cho nhóm; áp dụng cho bản nháp tạo sau.'
            elif route == '/api/scan-media':
                self.send(200,studio().media_task(obj));return
            elif route == '/api/group-drafts':
                self.send(200,studio().draft_groups(obj));return
            elif route == '/api/campaign-preview':
                import campaign_plan
                self.send(200,{'plan':campaign_plan.preview(STORE,DATA/'media',obj)});return
            elif route == '/api/schedule-recovery':
                STORE.set('resume_approved_on_start',obj.get('enabled') is True)
                if 'footer_comment_fallback' in obj:STORE.set('footer_comment_fallback',obj.get('footer_comment_fallback') is True)
                self.send(200,{'message':'Đã lưu: tự dời lịch quá giờ và tiếp tục các lượt đã duyệt khi mở ứng dụng.' if obj.get('enabled') else 'Đã tắt tự tiếp tục khi mở ứng dụng.'});return
            elif route == '/api/daily-limit':
                limit=int(obj['limit'])
                if not 1<=limit<=30:raise ValueError('Giới hạn từ 1 đến 30 nhóm/ngày.')
                STORE.set('daily_group_limit',limit);result='Đã lưu trần nhóm/ngày (giờ Việt Nam). Trần này không bảo đảm tránh hạn chế Facebook.'
            elif route == '/api/control-ai':
                
                with CONFIG_LOCK:ai_provider.save_config(STORE,obj)
                STOP_WORK.set()
                result='Đã lưu AI điều khiển và tạm dừng lịch. xKiro chỉ dùng model :free; AI viết bài cấu hình riêng ở mục bên dưới.'
            elif route == '/api/check-xkiro':
                quota=ai_provider.check_connection(STORE)
                self.send(200,{'message':'Đã kiểm tra nguồn đang chọn; chưa chạy suy luận hoặc thao tác Facebook.','quota':quota});return
            elif route == '/api/check':
                result = check_services()
            elif route == '/api/scan-joined-groups':
                with CONFIG_LOCK:
                    self.send(200,group_scanner().start(str(obj.get('account_id','main'))));return
            elif route == '/api/stop-group-scan':
                group_scanner().stop.set();result='Đang dừng quét sau bước hiện tại.'
            elif route == '/api/browser':
                from desktop import launch_browser
                from desktop import _BROWSER_PROFILE
                from approval_followup import busy
                selected_profile=None
                if obj.get('profile_id'):
                    selected_profile=__import__('facebook_accounts').chrome_profile_config(str(obj['profile_id']))
                with STORE.db() as c:
                    c.execute('BEGIN IMMEDIATE')
                    if busy(c) or c.execute("SELECT 1 FROM jobs WHERE state='working'").fetchone():raise ValueError('Tool đang thao tác Facebook. Chờ lượt hiện tại xong rồi mở hồ sơ đăng nhập.')
                    if STORE.get('group_scan',{}).get('status')=='running' or c.execute("SELECT 1 FROM link_refresh WHERE state IN ('queued','working')").fetchone():raise ValueError('Đang quét nhóm/cập nhật link; chờ xong rồi mở hồ sơ.')
                    account=c.execute('SELECT * FROM facebook_accounts WHERE id=?',(str(obj.get('account_id','main')),)).fetchone() if not selected_profile else None
                    if not selected_profile and not account:raise ValueError('Không tìm thấy tài khoản.')
                    for key in ('running','approval_monitor_enabled'):
                        c.execute("INSERT INTO kv(k,v) VALUES(?,'false') ON CONFLICT(k) DO UPDATE SET v=excluded.v",(key,))
                    c.execute("INSERT INTO kv(k,v) VALUES('paused_by_user','true') ON CONFLICT(k) DO UPDATE SET v=excluded.v")
                profile=selected_profile or json.loads(account['profile'])
                account_name=profile['display_name'] if selected_profile else account['name']
                token=_BROWSER_PROFILE.set(profile)
                try:launch_browser(DATA, 'https://www.facebook.com/')
                finally:_BROWSER_PROFILE.reset(token)
                result = 'Đã tạm dừng lịch và yêu cầu mở hồ sơ '+account_name+'. Kiểm tra tên profile trong cửa sổ Chrome; thêm hồ sơ vào tool trước khi gán nhóm.'
            else:
                raise ValueError('Không tìm thấy chức năng.')
            self.send(200, {'message': result})
        except Exception as exc:
            self.send(400, {'error': safe_error(exc)})


_legacy_panel=panel
_legacy_panel_callback=panel_callback
_legacy_bot_wizard=bot_wizard

def _bot_context():
    from types import SimpleNamespace
    return SimpleNamespace(**globals())

def menu():return bot_ui.keyboard()

def panel(chat,screen='home',page=0,message_id=None):
    return bot_ui.panel(_bot_context(),chat,screen,page,message_id)

def panel_callback(query):
    if bot_ui.callback(_bot_context(),query):return True
    return _legacy_panel_callback(query)

def bot_wizard(message,text,chat):
    if bot_ui.wizard(_bot_context(),message,text,chat):return True
    return _legacy_bot_wizard(message,text,chat)

def main():
    global PORT,LOCAL
    STORE.set('ai_busy', False)
    try:
        server = ThreadingHTTPServer(('127.0.0.1', PORT), Handler)
    except OSError:
        print('Port 8765 is in use. Close the previous NCT Group Manager window first.')
        return 1
    PORT=server.server_address[1];LOCAL=f'http://127.0.0.1:{PORT}'
    if os.environ.get('NCT_DESKTOP_PID'):
        def watch_host():
            import psutil
            parent=int(os.environ['NCT_DESKTOP_PID'])
            while not SHUTDOWN.wait(2):
                if not psutil.pid_exists(parent):server.shutdown();return
        threading.Thread(target=watch_host,daemon=True).start()
    __import__('facebook_accounts').sync_queued_accounts(STORE)
    STORE.recover()
    __import__('link_refresh').recover(STORE)
    scan=STORE.get('group_scan',{})
    if scan.get('status')=='running':STORE.set('group_scan',{**scan,'status':'error','message':'Lượt quét trước bị ngắt khi đóng ứng dụng. Bấm Quét nhóm để chạy lại; nhóm đã nhập được giữ nguyên.'})
    media_library.initialize(STORE,DATA/'media')
    for target in (poll_loop, outbox_loop, scheduler_loop):
        threading.Thread(target=target, daemon=True).start()
    url = LOCAL+'/?key='+WEB_KEY
    print('NCT Group Manager — keep this window open. Ctrl+C to stop.\n'+url, flush=True)
    if not os.environ.get('NCT_NO_BROWSER'):
        webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        pause(shutdown=True)
        SHUTDOWN.set()
        with PROCESS_LOCK:
            p = ACTIVE_PROCESS
        if p is not None:
            terminate_worker(p)
        server.server_close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
