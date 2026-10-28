"""Durable local data. Job text is frozen when queued; later edits cannot alter approval."""
import contextlib
import json
import re
import random
import secrets
import sqlite3
import time
import hashlib
import heapq
from pathlib import Path
from urllib.parse import urlsplit


def interval_bounds(value):
    """Accept fixed minutes (60) or a closed range (30-60)."""
    parts = str(value).strip().split('-')
    if len(parts) not in (1, 2) or not all(p.strip().isdigit() for p in parts):
        raise ValueError('Nhập số phút hoặc khoảng, ví dụ 60 hoặc 30-60.')
    minimum = int(parts[0])
    maximum = int(parts[-1])
    if not 1 <= minimum <= maximum <= 10080:
        raise ValueError('Cần 1 ≤ phút tối thiểu ≤ phút tối đa ≤ 10080.')
    return minimum, maximum


def sample_gap(bounds):
    return random.SystemRandom().randint(bounds[0]*60, bounds[1]*60)


def has_link(text):
    return bool(re.search(r'https?\s*:\s*//|www\s*\.|(?:[\w-]+\.)+[a-z]{2,}(?:\b|/)|t\.me/|discord\.gg/', text, re.I))


URL_PATTERN=re.compile(r'https?\s*:\s*//\s*[^\s<>"\u201c\u201d]+',re.I)


def urls(text):
    return [re.sub(r'^(https?)\s*:\s*//\s*',lambda m:m[1].lower()+'://',match.group(0).rstrip('.,;!)]}'),flags=re.I) for match in URL_PATTERN.finditer(text)]


def replace_link(text,old,new):
    def rewrite(match):
        token=match.group(0);url=token.rstrip('.,;!)]}')
        canonical=re.sub(r'^(https?)\s*:\s*//\s*',lambda m:m[1].lower()+'://',url,flags=re.I)
        if canonical!=old:return token
        # Keep the supplied footer's formatting and accompanying instructions.
        # The new comment uses the separately validated, standard new_url.
        separator=re.match(r'^https?(\s*:\s*//\s*)',url,re.I)[1]
        scheme,rest=new.split('://',1)
        return scheme+separator+rest+token[len(url):]
    return URL_PATTERN.sub(rewrite,text)


def validate_link(value):
    value=str(value).strip()
    parsed=urlsplit(value)
    if len(value)>2048 or parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username or parsed.password or re.search(r'\s',value):
        raise ValueError('Nhập link http:// hoặc https:// hợp lệ, không có khoảng trắng hay thông tin đăng nhập.')
    return value


def post_variant(post, policy, group_category=''):
    if policy == 'allow':
        body=post['body']
        if str(group_category).strip().upper()=='ALL':
            # Only ALL groups use direct Discord URLs; keep shared source prose intact.
            body=re.sub(r'(https?)\s*:\s*//\s*(discord\.gg/[^\s<>()]+)(?:[ \t]*\(\s*bỏ dấu cách[^)]*\))?',lambda m:m[1].lower()+'://'+m[2],body,flags=re.I)
        return body, post['media']
    if policy != 'deny':
        raise ValueError('Chưa chọn quy định link cho nhóm.')
    text = post['body_no_link'] or (post['body'] if not has_link(post['body']) else '')
    if not text or has_link(text):
        raise ValueError('Thiếu bản nội dung không link hợp lệ.')
    # No-link groups get only an image explicitly attached to the no-link version.
    return text, post['media_no_link']


def group_url(value):
    value = value.strip()
    if not value.startswith(('https://', 'http://')):
        value = 'https://' + value
    p = urlsplit(value)
    if p.hostname not in {'facebook.com', 'www.facebook.com', 'm.facebook.com'} or p.username or p.password:
        raise ValueError('Chỉ nhận link facebook.com/groups/...')
    if p.port not in (None, 443, 80):
        raise ValueError('Cổng trong link không hợp lệ.')
    m = re.fullmatch(r'/groups/([A-Za-z0-9._-]+)/?', p.path)
    if not m or m[1].lower() in {'feed', 'discover', 'joins', 'create'}:
        raise ValueError('Dùng link trang chính của nhóm, không dùng link bài viết hoặc link chia sẻ.')
    return 'https://www.facebook.com/groups/' + m[1] + '/'


class Store:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.db() as c:
            c.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY,v TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS facebook_accounts(id TEXT PRIMARY KEY,name TEXT NOT NULL,profile TEXT NOT NULL,created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS groups(id INTEGER PRIMARY KEY,url TEXT UNIQUE NOT NULL,
              name TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 0, rules TEXT NOT NULL DEFAULT '');
            CREATE TABLE IF NOT EXISTS contents(id INTEGER PRIMARY KEY,body TEXT NOT NULL,
              media TEXT NOT NULL DEFAULT '',created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS jobs(id INTEGER PRIMARY KEY,group_id INTEGER NOT NULL,
              group_name TEXT NOT NULL,url TEXT NOT NULL,body TEXT NOT NULL,media TEXT NOT NULL,
              due REAL NOT NULL,state TEXT NOT NULL DEFAULT 'draft',detail TEXT NOT NULL DEFAULT '',
              created REAL NOT NULL,updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS outbox(id INTEGER PRIMARY KEY,text TEXT NOT NULL,
              photo TEXT NOT NULL DEFAULT '',tries INTEGER NOT NULL DEFAULT 0,next REAL NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS ai_usage(id INTEGER PRIMARY KEY,at REAL NOT NULL,job_id INTEGER NOT NULL,model TEXT NOT NULL,input_tokens INTEGER NOT NULL,output_tokens INTEGER NOT NULL,total_tokens INTEGER NOT NULL,known INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS group_reviews(id INTEGER PRIMARY KEY,job_id INTEGER UNIQUE NOT NULL,
              group_id INTEGER NOT NULL,group_name TEXT NOT NULL,url TEXT NOT NULL,state TEXT NOT NULL,
              detail TEXT NOT NULL,post_url TEXT NOT NULL DEFAULT '',photo TEXT NOT NULL DEFAULT '',
              decision TEXT NOT NULL DEFAULT '',created REAL NOT NULL,updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS media_pools(name TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS media_catalog(id TEXT PRIMARY KEY,pool TEXT NOT NULL DEFAULT '',name TEXT NOT NULL,kind TEXT NOT NULL,
              scan_hash TEXT NOT NULL DEFAULT '',analysis TEXT NOT NULL DEFAULT '{}',scan_model TEXT NOT NULL DEFAULT '',scan_at REAL NOT NULL DEFAULT 0,last_used REAL NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS group_media_pools(group_id INTEGER NOT NULL,pool TEXT NOT NULL,PRIMARY KEY(group_id,pool));
            CREATE TABLE IF NOT EXISTS content_ai_calls(id INTEGER PRIMARY KEY,at REAL NOT NULL,provider TEXT NOT NULL,purpose TEXT NOT NULL,model TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'started',tokens INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,at REAL NOT NULL,text TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS link_refresh(id INTEGER PRIMARY KEY,batch_id INTEGER NOT NULL,job_id INTEGER NOT NULL,old_url TEXT NOT NULL,new_url TEXT NOT NULL,body_before TEXT NOT NULL,body_after TEXT NOT NULL,comment_before TEXT NOT NULL DEFAULT '',state TEXT NOT NULL DEFAULT 'queued',edit_state TEXT NOT NULL DEFAULT 'waiting',comment_state TEXT NOT NULL DEFAULT 'waiting',detail TEXT NOT NULL DEFAULT '',created REAL NOT NULL,updated REAL NOT NULL,operation_key TEXT UNIQUE NOT NULL);
            CREATE TABLE IF NOT EXISTS link_changes(id INTEGER PRIMARY KEY,at REAL NOT NULL,old_url TEXT NOT NULL,new_url TEXT NOT NULL,before_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS content_targets(content_id INTEGER NOT NULL,group_id INTEGER NOT NULL,PRIMARY KEY(content_id,group_id));
            CREATE TABLE IF NOT EXISTS group_aliases(alias TEXT PRIMARY KEY,group_id INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS queue_outcomes(job_id INTEGER PRIMARY KEY,state TEXT NOT NULL,at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS calendar_releases(id INTEGER PRIMARY KEY,group_id INTEGER NOT NULL,at REAL NOT NULL,before_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS approval_checks(job_id INTEGER PRIMARY KEY,post_url TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'waiting',due REAL NOT NULL,created REAL NOT NULL,updated REAL NOT NULL,profile_revision TEXT NOT NULL,checks INTEGER NOT NULL DEFAULT 0,detail TEXT NOT NULL DEFAULT '',previous_state TEXT NOT NULL DEFAULT 'pending');
            ''')
            if 'gap_seconds' not in {r[1] for r in c.execute('PRAGMA table_info(jobs)')}:
                c.execute('ALTER TABLE jobs ADD COLUMN gap_seconds INTEGER NOT NULL DEFAULT 0')
            if 'retry_of' not in {r[1] for r in c.execute('PRAGMA table_info(jobs)')}:
                c.execute('ALTER TABLE jobs ADD COLUMN retry_of INTEGER NOT NULL DEFAULT 0')
            if 'calendar_released' not in {r[1] for r in c.execute('PRAGMA table_info(jobs)')}:
                c.execute('ALTER TABLE jobs ADD COLUMN calendar_released INTEGER NOT NULL DEFAULT 0')
            if 'previous_state' not in {r[1] for r in c.execute('PRAGMA table_info(approval_checks)')}:
                c.execute("ALTER TABLE approval_checks ADD COLUMN previous_state TEXT NOT NULL DEFAULT 'pending'")
            additions = {'media_catalog': {'archived': 'INTEGER NOT NULL DEFAULT 0'}, 'groups': {'account_id': "TEXT NOT NULL DEFAULT 'main'", 'posting_identity': "TEXT NOT NULL DEFAULT 'default'", 'posting_nickname': "TEXT NOT NULL DEFAULT ''", 'comment_links': "TEXT NOT NULL DEFAULT 'unknown'", 'deleted': 'INTEGER NOT NULL DEFAULT 0', 'link_policy': "TEXT NOT NULL DEFAULT 'unknown'", 'next_post_after': 'REAL NOT NULL DEFAULT 0', 'category': "TEXT NOT NULL DEFAULT 'Chung'"},
                'contents': {'account_id': "TEXT NOT NULL DEFAULT ''", 'comment_identity': "TEXT NOT NULL DEFAULT 'follow'", 'comment_nickname': "TEXT NOT NULL DEFAULT ''", 'footer_text': "TEXT NOT NULL DEFAULT ''", 'comment_fallback_text': "TEXT NOT NULL DEFAULT ''", 'comment_mode': "TEXT NOT NULL DEFAULT 'none'", 'comment_link': "TEXT NOT NULL DEFAULT ''", 'tiktok_id': "TEXT NOT NULL DEFAULT ''", 'body_no_link': "TEXT NOT NULL DEFAULT ''", 'media_no_link': "TEXT NOT NULL DEFAULT ''", 'category': "TEXT NOT NULL DEFAULT 'Chung'", 'title': "TEXT NOT NULL DEFAULT ''", 'target_mode': "TEXT NOT NULL DEFAULT 'category'"},
                'outbox': {'reply_markup': "TEXT NOT NULL DEFAULT '{}'", 'photo_caption': "TEXT NOT NULL DEFAULT ''", 'text_sent':'INTEGER NOT NULL DEFAULT 0'},
                'jobs': {'account_id': "TEXT NOT NULL DEFAULT 'main'", 'browser_profile_json': "TEXT NOT NULL DEFAULT ''", 'moderation_status': "TEXT NOT NULL DEFAULT ''", 'gap_min_seconds': 'INTEGER NOT NULL DEFAULT 0', 'post_attempted': 'INTEGER NOT NULL DEFAULT -1', 'comment_identity': "TEXT NOT NULL DEFAULT 'follow'", 'comment_nickname': "TEXT NOT NULL DEFAULT ''", 'posting_identity': "TEXT NOT NULL DEFAULT 'default'", 'posting_nickname': "TEXT NOT NULL DEFAULT ''", 'campaign_daily_limit': 'INTEGER NOT NULL DEFAULT 0', 'original_due': 'REAL NOT NULL DEFAULT 0', 'schedule_note': "TEXT NOT NULL DEFAULT ''", 'safe_retries': 'INTEGER NOT NULL DEFAULT 0', 'variant_note': "TEXT NOT NULL DEFAULT ''", 'video_fallback_media': "TEXT NOT NULL DEFAULT ''", 'attempted_at': 'REAL NOT NULL DEFAULT 0', 'routing_mode': "TEXT NOT NULL DEFAULT 'category'", 'comment_text': "TEXT NOT NULL DEFAULT ''", 'comment_fallback': "TEXT NOT NULL DEFAULT ''", 'comment_policy': "TEXT NOT NULL DEFAULT ''", 'comment_status': "TEXT NOT NULL DEFAULT ''", 'post_url': "TEXT NOT NULL DEFAULT ''", 'photo': "TEXT NOT NULL DEFAULT ''", 'group_gap_seconds': 'INTEGER NOT NULL DEFAULT 86400', 'content_id':'INTEGER NOT NULL DEFAULT 0', 'hidden':'INTEGER NOT NULL DEFAULT 0', 'prepare_only':'INTEGER NOT NULL DEFAULT 0'}}
            for table, fields in additions.items():
                existing = {r[1] for r in c.execute(f'PRAGMA table_info({table})')}
                for name, declaration in fields.items():
                    if name not in existing:
                        c.execute(f'ALTER TABLE {table} ADD COLUMN {name} {declaration}')
        if self.get('pair_code') is None:
            self.set('pair_code', secrets.token_hex(4))
        if self.get('running') is None:
            self.set('running', False)

    def recover(self):
        """Resume only approved work; interrupted submissions require review."""
        from approval_followup import recover
        recover(self)
        self.release_cancelled_slots()
        with self.db() as c:
            interrupted=c.execute("SELECT id FROM jobs WHERE state='working'").fetchall()
            c.execute("UPDATE groups SET next_post_after=MAX(next_post_after,?) WHERE id IN (SELECT group_id FROM jobs WHERE state='working')", (time.time()+86400,))
            c.execute("UPDATE jobs SET state='uncertain',detail='Ứng dụng bị đóng giữa lượt. Kiểm tra Facebook trước khi lên lịch lại.',updated=? WHERE state='working'", (time.time(),))
        self.refresh_global_cooldown()
        moved=self.reflow_queue()
        resume=not interrupted and not self.get('paused_by_user',False) and self.get('resume_approved_on_start',False) and bool(self.rows("SELECT id FROM jobs WHERE state='queued' LIMIT 1"))
        self.set('running',bool(resume))
        if moved:self.set('progress',f'Đã dời {moved} lịch đã duyệt; giữ nguyên bài và thứ tự, không chạy dồn.')

    def reflow_queue(self,compact=False):
        from queue_recovery import reflow
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            return reflow(c,time.time(),self.get('next_allowed',0),max(1,min(30,int(self.get('daily_group_limit',20)))),compact)

    def advance_after_review(self,jid):
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT state,gap_seconds,gap_min_seconds,post_attempted FROM jobs WHERE id=?',(jid,)).fetchone()
            if not row or row['state'] not in {'error','uncertain'}:return 0
            if row['post_attempted']!=0:return 0  # Sent/unknown: preserve the normal gap and schedule.
            # Failed/review jobs have their own short handoff; the normal posting range is unchanged.
            gap=max(60,min(300,int(self.get('failure_gap_seconds',120))))
            if row['gap_seconds']>gap:
                c.execute('UPDATE jobs SET gap_seconds=? WHERE id=?',(gap,jid))
        self.refresh_global_cooldown()
        return self.reflow_queue(compact=True)

    def defer_safe_failure(self,jid,result):
        # Only explicit proof of no submit plus a transient window/MCP failure.
        if result.get('post_attempted') is not False or result.get('safe_to_retry') is not True:return False
        with self.db() as c:
            row=c.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone()
            if not row or row['state']!='working' or row['safe_retries']>=1:return False
            if not c.execute('SELECT id FROM groups WHERE id=? AND enabled=1 AND deleted=0',(row['group_id'],)).fetchone():return False
            c.execute("UPDATE jobs SET state='queued',safe_retries=safe_retries+1,due=?,original_due=CASE WHEN original_due>0 THEN original_due ELSE due END,schedule_note='Chưa bấm Đăng; lỗi cửa sổ tạm thời, tự thử lại một lần.',detail=?,updated=? WHERE id=?",(time.time()+max(120,row['gap_seconds']),result.get('detail','')[:1000],time.time(),jid))
        self.reflow_queue()
        return True

    @contextlib.contextmanager
    def db(self):
        c = sqlite3.connect(self.path, timeout=15)
        c.row_factory = sqlite3.Row
        try:
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()

    def get(self, key, default=None):
        with self.db() as c:
            r = c.execute('SELECT v FROM kv WHERE k=?', (key,)).fetchone()
            return json.loads(r[0]) if r else default

    def set(self, key, value):
        with self.db() as c:
            c.execute('INSERT INTO kv VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v', (key, json.dumps(value, ensure_ascii=False)))

    def rows(self, sql, params=()):
        with self.db() as c:
            return [dict(r) for r in c.execute(sql, params)]

    def clear_jobs(self):
        """Remove jobs from user lists while retaining posting history and cooldowns."""
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute("SELECT 1 FROM jobs WHERE state='working' LIMIT 1").fetchone():
                raise ValueError('Có lượt đang thao tác. Bấm Tạm dừng, chờ thông báo dừng rồi xóa danh sách.')
            from approval_followup import busy
            if busy(c):raise ValueError('Đang kiểm tra duyệt/bình luận; chờ worker kết thúc trước khi xóa lịch.')
            now=time.time()
            cancelled=self._cancel_jobs(c)
            hidden=c.execute('UPDATE jobs SET hidden=1 WHERE hidden=0').rowcount
            c.execute("UPDATE approval_checks SET state='cancelled' WHERE state IN ('waiting','review')")
            revision=c.execute("SELECT v FROM kv WHERE k='control_revision'").fetchone()
            for key,value in [('running',False),('control_revision',(json.loads(revision[0]) if revision else 0)+1),('progress','Đã xóa danh sách lịch. Chưa có tác vụ mới.')]:
                c.execute('INSERT INTO kv VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v',(key,json.dumps(value,ensure_ascii=False)))
            return {'hidden':hidden,'cancelled':cancelled}

    def _cancel_jobs(self,c,job_ids=None):
        where="state IN ('draft','queued')";params=[]
        if job_ids is not None:
            ids=list(dict.fromkeys(int(i) for i in job_ids))
            if not ids:return 0
            where+=' AND id IN ('+','.join('?' for _ in ids)+')';params=ids
        rows=c.execute('SELECT id,group_id FROM jobs WHERE '+where,params).fetchall()
        if not rows:return 0
        c.execute("UPDATE jobs SET state='cancelled',updated=? WHERE "+where,[time.time(),*params])
        self._release_unused_groups(c,{row['group_id'] for row in rows})
        return len(rows)

    @staticmethod
    def _release_unused_groups(c,group_ids):
        # A draft is a reservation, not a posting attempt. Only actual/possible
        # submissions may keep the group cooldown after its reservation is gone.
        for gid in group_ids:
            evidence=c.execute("SELECT 1 FROM jobs WHERE group_id=? AND calendar_released=0 AND (state IN ('working','submitted','pending','uncertain') OR (attempted_at>0 AND post_attempted<>0)) LIMIT 1",(gid,)).fetchone()
            if not evidence:c.execute('UPDATE groups SET next_post_after=0 WHERE id=?',(gid,))

    def cancel_jobs(self,job_ids=None):
        """Release only waiting reservations, preserving all publication evidence."""
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            return self._cancel_jobs(c,job_ids)

    def release_cancelled_slots(self):
        """Repair stale reservations left by earlier cancellation paths."""
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            groups={r['group_id'] for r in c.execute("SELECT DISTINCT group_id FROM jobs WHERE state='cancelled'")}
            self._release_unused_groups(c,groups)

    def group_calendars(self):
        from group_calendar import summaries
        with self.db() as c:return summaries(c,time.time())

    def reset_group_calendar(self,gid,expected_revision,confirmed_not_posted=False):
        from group_calendar import revision
        if confirmed_not_posted is not True:raise ValueError('Cần xác nhận đã kiểm tra nhóm và bài chưa được đăng.')
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            group=c.execute('SELECT * FROM groups WHERE id=? AND deleted=0',(gid,)).fetchone()
            if not group:raise ValueError('Không tìm thấy nhóm.')
            if c.execute("SELECT 1 FROM jobs WHERE state='working' LIMIT 1").fetchone():raise ValueError('Có lượt đang thao tác. Chờ hoàn tất trước khi trả lịch trống.')
            from approval_followup import busy
            if busy(c):raise ValueError('Đang kiểm tra duyệt/bình luận; chờ xong trước khi trả lịch trống.')
            jobs=c.execute('SELECT * FROM jobs WHERE group_id=? AND calendar_released=0 ORDER BY id',(gid,)).fetchall()
            if not expected_revision or expected_revision!=revision(group,jobs):raise ValueError('Lịch nhóm vừa thay đổi. Tải lại và kiểm tra trước khi xác nhận.')
            snapshot={'group_id':gid,'next_post_after':group['next_post_after'],'jobs':[dict(j) for j in jobs]}
            c.execute('INSERT INTO calendar_releases(group_id,at,before_json) VALUES(?,?,?)',(gid,time.time(),json.dumps(snapshot,ensure_ascii=False)))
            cancelled=c.execute("UPDATE jobs SET state='cancelled' WHERE group_id=? AND calendar_released=0 AND state IN ('draft','queued')",(gid,)).rowcount
            c.execute('UPDATE jobs SET calendar_released=1 WHERE group_id=? AND calendar_released=0',(gid,))
            c.execute('UPDATE groups SET next_post_after=0 WHERE id=?',(gid,))
            c.execute("UPDATE approval_checks SET state='cancelled' WHERE job_id IN (SELECT id FROM jobs WHERE group_id=?)",(gid,))
        self.refresh_global_cooldown()
        return {'released':len(jobs),'cancelled':cancelled}

    def reset_all_group_calendars(self,revisions,confirmed=False):
        from group_calendar import revision
        from approval_followup import busy
        if confirmed is not True:raise ValueError('Cần xác nhận trả lịch trống tất cả nhóm.')
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            if busy(c) or c.execute("SELECT 1 FROM jobs WHERE state='working'").fetchone():raise ValueError('Có lượt đang thao tác; chờ hoàn tất trước khi trả lịch trống.')
            groups=c.execute('SELECT * FROM groups WHERE deleted=0').fetchall()
            if not isinstance(revisions,dict) or set(revisions)!=set(str(g['id']) for g in groups):raise ValueError('Danh sách nhóm vừa thay đổi. Tải lại trước khi xác nhận.')
            snapshots=[]
            for group in groups:
                jobs=c.execute('SELECT * FROM jobs WHERE group_id=? AND calendar_released=0 ORDER BY id',(group['id'],)).fetchall()
                if revisions[str(group['id'])]!=revision(group,jobs):raise ValueError('Lịch vừa thay đổi. Tải lại trước khi xác nhận.')
                snapshots.append((group,jobs))
            cancelled=0
            for group,jobs in snapshots:
                gid=group['id']
                c.execute('INSERT INTO calendar_releases(group_id,at,before_json) VALUES(?,?,?)',(gid,time.time(),json.dumps({'group_id':gid,'next_post_after':group['next_post_after'],'jobs':[dict(j) for j in jobs]},ensure_ascii=False)))
                cancelled+=c.execute("UPDATE jobs SET state='cancelled' WHERE group_id=? AND calendar_released=0 AND state IN ('draft','queued')",(gid,)).rowcount
                c.execute('UPDATE jobs SET calendar_released=1 WHERE group_id=? AND calendar_released=0',(gid,))
                c.execute('UPDATE groups SET next_post_after=0 WHERE id=?',(gid,))
                c.execute("UPDATE approval_checks SET state='cancelled' WHERE job_id IN (SELECT id FROM jobs WHERE group_id=?)",(gid,))
        self.refresh_global_cooldown()
        return {'groups':len(groups),'cancelled':cancelled}

    def event(self, text):
        with self.db() as c:
            c.execute('INSERT INTO events(at,text) VALUES(?,?)', (time.time(), text[:3000]))

    def notify(self, text, photo='', reply_markup=None, photo_caption=''):
        with self.db() as c:
            c.execute('INSERT INTO outbox(text,photo,reply_markup,photo_caption) VALUES(?,?,?,?)', (text[:3900], photo, json.dumps(reply_markup or {},ensure_ascii=False),photo_caption[:900]))

    def set_comment_settings(self,cid,mode,link='',tiktok_id='',fallback_text='',identity='follow',nickname=''):
        from comment_identity import validate
        identity,nickname=validate(identity,nickname)
        if mode not in {'none','always','fallback'}:raise ValueError('Chế độ bình luận không hợp lệ.')
        link=str(link).strip();tiktok_id=str(tiktok_id).strip()
        if link:link=validate_link(link)
        if mode!='none' and not link:raise ValueError('Cần link bình luận cho chế độ đã chọn.')
        if tiktok_id and not re.fullmatch(r'@[A-Za-z0-9_.]{2,24}',tiktok_id):raise ValueError('ID TikTok cần dạng @ten_taikhoan (2–24 ký tự).')
        fallback_text=str(fallback_text).strip()
        if len(fallback_text)>500 or has_link(fallback_text):raise ValueError('Nội dung dự phòng tối đa 500 ký tự và không chứa link.')
        with self.db() as c:
            if not c.execute('UPDATE contents SET comment_mode=?,comment_link=?,tiktok_id=?,comment_fallback_text=?,comment_identity=?,comment_nickname=? WHERE id=?',(mode,link,tiktok_id,fallback_text,identity,nickname,cid)).rowcount:raise ValueError('Không tìm thấy bài.')
            c.execute("UPDATE jobs SET state='cancelled',updated=? WHERE content_id=? AND state IN ('draft','queued')",(time.time(),cid))

    def set_comment_policy(self,gid,policy):
        if policy not in {'unknown','allow','deny'}:raise ValueError('Quy định bình luận không hợp lệ.')
        with self.db() as c:
            if c.execute("SELECT 1 FROM jobs WHERE group_id=? AND state='working'",(gid,)).fetchone():raise ValueError('Dừng worker trước khi đổi quy định bình luận.')
            if not c.execute('UPDATE groups SET comment_links=? WHERE id=? AND deleted=0',(policy,gid)).rowcount:raise ValueError('Không tìm thấy nhóm.')
            c.execute("UPDATE jobs SET state='cancelled',updated=? WHERE group_id=? AND state IN ('draft','queued')",(time.time(),gid))

    def set_posting_identity(self,gid,mode,nickname=''):
        from posting_identity import validate
        mode,nickname=validate(mode,nickname)
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute("SELECT 1 FROM jobs WHERE group_id=? AND state='working'",(gid,)).fetchone():raise ValueError('Dừng worker và chờ lượt hiện tại kết thúc trước khi đổi danh tính.')
            if not c.execute('UPDATE groups SET posting_identity=?,posting_nickname=? WHERE id=? AND deleted=0',(mode,nickname,gid)).rowcount:raise ValueError('Không tìm thấy nhóm.')
            return c.execute("UPDATE jobs SET state='cancelled',updated=? WHERE group_id=? AND state IN ('draft','queued')",(time.time(),gid)).rowcount

    def _freeze_comments(self,c,jid,cid,gid,gap_min_seconds=0):
        from facebook_accounts import freeze
        freeze(c,jid,gid)
        post=c.execute('SELECT * FROM contents WHERE id=?',(cid,)).fetchone()
        group=c.execute('SELECT * FROM groups WHERE id=?',(gid,)).fetchone()
        if not post or not group:return
        if gap_min_seconds>0:c.execute('UPDATE jobs SET gap_min_seconds=? WHERE id=?',(gap_min_seconds,jid))
        c.execute('UPDATE jobs SET posting_identity=?,posting_nickname=? WHERE id=?',(group['posting_identity'],group['posting_nickname'],jid))
        note='Bản không link: nhóm không cho link trong bài.' if group['link_policy']=='deny' and has_link(post['body']) else 'Bản thường: giữ nguyên nội dung đã chốt.'
        if group['category'].strip().upper()=='ALL' and group['link_policy']=='allow':note='Nhóm ALL: dùng link Discord trực tiếp, bỏ hướng dẫn dấu cách.'
        c.execute('UPDATE jobs SET variant_note=? WHERE id=?',(note,jid))
        # Freeze a scanned same-game photo for new video jobs only; never rewrite existing queued jobs.
        from media import paths as attachment_paths,serialize
        job=c.execute('SELECT media FROM jobs WHERE id=?',(jid,)).fetchone()
        if job and any(Path(p).suffix.lower() in {'.mp4','.mov','.webm'} for p in attachment_paths(job['media'])):
            import media_library
            try:
                chosen=media_library.choose_pool(self,Path(self.path).parent/'media',post['category'],1,1) if post['category'] in media_library.POOLS else media_library.choose(self,Path(self.path).parent/'media',gid,1)
                fallback=serialize([str((Path(self.path).parent/'media'/chosen[0][0]['id']).resolve())])
                c.execute('UPDATE jobs SET video_fallback_media=? WHERE id=?',(fallback,jid))
            except (ValueError,OSError):pass
        allowed=group['comment_links']=='allow' or (group['comment_links']=='unknown' and group['link_policy']=='allow')
        requested=post['comment_mode']=='always' or (post['comment_mode']=='fallback' and group['link_policy']=='deny')
        fallback_link=''
        if not requested and group['link_policy']=='deny' and self.get('footer_comment_fallback',False):
            from content_links import supplied_urls
            links=supplied_urls(post['footer_text']) & supplied_urls(post['body'])
            if links:fallback_link='\n'.join(sorted(links));requested=True
        text=(post['comment_link'] or fallback_link) if requested and allowed else ''
        if group['link_policy']=='deny' and has_link(post['body']):
            note+=' Link gửi ở bình luận.' if text else ' Link chưa gửi: chưa bật hoặc chưa được phép bình luận link.'
            c.execute('UPDATE jobs SET variant_note=? WHERE id=?',(note,jid))
        c.execute('UPDATE jobs SET comment_identity=?,comment_nickname=? WHERE id=?',(post['comment_identity'],post['comment_nickname'],jid))
        policy='allowed' if requested and allowed else 'blocked' if requested else 'off'
        c.execute('UPDATE jobs SET comment_text=?,comment_fallback=?,comment_policy=? WHERE id=?',(text,(post['comment_fallback_text'] or ('Bạn có thể tìm mình trên TikTok với ID '+post['tiktok_id']+' để trao đổi thêm.' if post['tiktok_id'] else '')) if text else '',policy,jid))

    def group_watchlist(self):
        """Current unresolved outcomes, once per posting job; never approval poll counts."""
        result=[]
        for group in self.rows('SELECT * FROM groups WHERE deleted=0'):
            ignored=set(self.get('group_watch_ignored_'+str(group['id']),[]))
            counts={'failed':0,'pending':0,'removed':0,'declined':0};latest=0
            jobs=self.rows("SELECT j.*,a.previous_state AS approval_previous FROM jobs j LEFT JOIN approval_checks a ON a.job_id=j.id WHERE j.group_id=?",(group['id'],))
            for job in jobs:
                if job['id'] in ignored:continue
                state=job['approval_previous'] if job['state']=='working' and job['approval_previous'] else job['state']
                if state in {'submitted','cancelled','prepared','draft','queued','working'}:continue
                moderation=job['moderation_status']
                if moderation=='removed':kind='removed'
                elif moderation=='declined':kind='declined'
                elif state=='pending':kind='pending'
                elif state=='error':
                    if any(marker in job['detail'] for marker in ('CONTROL_PREEMPTED','Quyền thao tác đã chuyển','runtime revision','Mã nguồn đã thay đổi')):continue
                    kind='failed'
                else:continue
                counts[kind]+=1;latest=max(latest,job['id'])
            total=sum(counts.values())
            if total>5:result.append({'group_id':group['id'],'name':group['name'],'url':group['url'],'total':total,'latest_job':latest,**counts})
        return sorted(result,key=lambda row:row['total'],reverse=True)

    def decide_group_watch(self,gid,decision):
        if decision not in {'keep','delete'}:raise ValueError('Chọn giữ hoặc xóa nhóm.')
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            if not c.execute('SELECT 1 FROM groups WHERE id=? AND deleted=0',(gid,)).fetchone():raise ValueError('Không tìm thấy nhóm.')
            if decision=='delete':self._delete_group(c,gid)
            else:
                ignored=[row[0] for row in c.execute("SELECT id FROM jobs WHERE group_id=? AND state IN ('pending','error','uncertain')",(gid,))]
                c.execute('INSERT INTO kv VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v',('group_watch_ignored_'+str(gid),json.dumps(ignored)))
            c.execute("UPDATE group_reviews SET decision=?,updated=? WHERE group_id=? AND decision=''",(decision,time.time(),gid))
        return decision

    def record_result(self, job, result):
        now=time.time()
        with self.db() as c:
            c.execute('UPDATE jobs SET post_url=?,photo=?,comment_status=? WHERE id=?',
                      (result.get('post_url',''),result.get('photo',''),result.get('comment_status',''),job['id']))
            if result.get('profile_fallback_used') and result.get('identity_verified') and result.get('posting_identity_effective')=='default':
                c.execute("UPDATE jobs SET posting_identity='default' WHERE id=?",(job['id'],))
            if result.get('moderation_checked') and result.get('moderation_status') in {'pending','submitted','declined','removed'}:
                c.execute('UPDATE jobs SET moderation_status=? WHERE id=?',(result['moderation_status'],job['id']))
            c.execute("""INSERT INTO group_reviews(job_id,group_id,group_name,url,state,detail,post_url,photo,created,updated)
                VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(job_id) DO UPDATE SET
                state=excluded.state,detail=excluded.detail,post_url=excluded.post_url,photo=excluded.photo,updated=excluded.updated""",
                (job['id'],job['group_id'],job['group_name'],job['url'],result['state'],result.get('detail',''),
                 result.get('post_url',''),result.get('photo',''),now,now))
            return c.execute('SELECT id FROM group_reviews WHERE job_id=?',(job['id'],)).fetchone()[0]

    def _delete_group(self,c,gid):
        row=c.execute('SELECT * FROM groups WHERE id=?',(gid,)).fetchone()
        if not row:raise ValueError('Không tìm thấy nhóm.')
        if c.execute("SELECT 1 FROM jobs WHERE group_id=? AND state='working'",(gid,)).fetchone():
            raise ValueError('Nhóm đang chạy; /pause và chờ worker dừng trước khi xóa.')
        c.execute('UPDATE groups SET enabled=0,deleted=1 WHERE id=?',(gid,))
        cancelled=c.execute("UPDATE jobs SET state='cancelled',updated=? WHERE group_id=? AND state IN ('draft','queued')",(time.time(),gid)).rowcount
        c.execute("UPDATE group_reviews SET decision='delete',updated=? WHERE group_id=? AND decision=''",(time.time(),gid))
        return {'name':row['name'],'url':row['url'],'cancelled':cancelled}

    def delete_group(self,gid):
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            return self._delete_group(c,gid)

    def decide_review(self, rid, decision):
        if decision not in {'keep','delete'}:raise ValueError('Lựa chọn không hợp lệ.')
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT * FROM group_reviews WHERE id=?',(rid,)).fetchone()
            if not row:raise ValueError('Không tìm thấy mục xem xét.')
            if row['decision']:return row['decision']
            gid=row['group_id']
            if decision=='delete':
                self._delete_group(c,gid)
            c.execute("UPDATE group_reviews SET decision=?,updated=? WHERE group_id=? AND decision=''",(decision,time.time(),gid))
            return decision

    def add_group(self, url, name='', rules='', link_policy=None, category=None):
        url = group_url(url)
        name = (name.strip() or url.split('/')[-2])[:160]
        with self.db() as c:
            c.execute('INSERT INTO groups(url,name,rules) VALUES(?,?,?) ON CONFLICT(url) DO UPDATE SET name=excluded.name,rules=excluded.rules', (url, name, rules[:2000]))
            gid = c.execute('SELECT id FROM groups WHERE url=?', (url,)).fetchone()[0]
        if link_policy is not None:
            self.set_link_policy(gid, link_policy)
        if category is not None:
            self.group_category(gid, category)
        return gid

    def group_category(self, gid, category):
        category = str(category).strip()[:80]
        if category.upper()=='ALL':
            category='ALL'
            self.set_link_policy(gid,'allow')
        with self.db() as c:
            old = c.execute('SELECT category FROM groups WHERE id=?', (gid,)).fetchone()
            if not old:
                raise ValueError('Không tìm thấy nhóm.')
            if old['category'] != category:
                if c.execute("SELECT id FROM jobs WHERE group_id=? AND state='working'", (gid,)).fetchone():
                    raise ValueError('Nhóm đang thao tác. Tạm dừng trước khi đổi phân loại.')
                c.execute("UPDATE jobs SET state='cancelled',detail='Phân loại nhóm đã đổi; cần lên lịch lại.',updated=? WHERE group_id=? AND state IN ('draft','queued')", (time.time(), gid))
            c.execute('UPDATE groups SET category=? WHERE id=?', (category, gid))

    def post_category(self, cid, category):
        category = str(category).strip()[:80]
        if not category:
            raise ValueError('Chọn phân loại cho bài viết.')
        with self.db() as c:
            if not c.execute('UPDATE contents SET category=? WHERE id=?', (category, cid)).rowcount:
                raise ValueError('Không tìm thấy bài viết.')

    def targets(self,cid,mode,group_ids,routing_mode='category'):
        import media_library
        if mode not in {'category','selected'} or not isinstance(group_ids,list):
            raise ValueError('Chọn theo phân loại hoặc các nhóm cụ thể.')
        ids=list(dict.fromkeys(int(g) for g in group_ids))
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            post=c.execute('SELECT * FROM contents WHERE id=?',(cid,)).fetchone()
            if not post:raise ValueError('Không tìm thấy bài.')
            for gid in ids:
                g=c.execute('SELECT * FROM groups WHERE id=?',(gid,)).fetchone()
                if not g or not g['category'].strip() or (g['category'].strip().casefold()!=post['category'].strip().casefold() and not (g['category'].strip().upper()=='ALL' and post['category'] in media_library.POOLS)):
                    raise ValueError('Chỉ chọn nhóm có cùng phân loại với bài. Nhóm khác game không hợp lệ.')
            existing=[row[0] for row in c.execute('SELECT group_id FROM content_targets WHERE content_id=? ORDER BY group_id',(cid,))]
            if post['target_mode']==mode and (mode=='category' or existing==sorted(ids)):return 0
            affected="(content_id=? OR (content_id=0 AND body IN (?,?)))"
            params=(cid,post['body'],post['body_no_link'])
            if c.execute("SELECT id FROM jobs WHERE state='working' AND "+affected,params).fetchone():
                raise ValueError('Bài đang có lượt thao tác. /pause và chờ dừng trước khi đổi nhóm đích.')
            cancelled=c.execute("UPDATE jobs SET state='cancelled',detail='Nhóm đích của bài đã đổi. Tạo lịch mới để áp dụng.',updated=? WHERE state IN ('draft','queued') AND "+affected,(time.time(),)+params).rowcount
            c.execute('UPDATE contents SET target_mode=? WHERE id=?',(mode,cid))
            c.execute('DELETE FROM content_targets WHERE content_id=?',(cid,))
            if mode=='selected':c.executemany('INSERT INTO content_targets VALUES(?,?)',[(cid,gid) for gid in ids])
            return cancelled

    def content_account(self,cid,aid):
        with self.db() as c:
            if aid and aid!='main' and not c.execute('SELECT 1 FROM facebook_accounts WHERE id=?',(aid,)).fetchone():raise ValueError('Không tìm thấy tài khoản của bài.')
            if not c.execute('UPDATE contents SET account_id=? WHERE id=?',(aid,cid)).rowcount:raise ValueError('Không tìm thấy bài.')

    def _eligible(self,c,post,group,routing_mode='category'):
        if routing_mode not in {'category','random'}:return False
        if post['account_id'] and post['account_id']!=group['account_id']:return False
        # Random changes order/choice within a game's pool, never its audience.
        if not group['category'].strip():return False
        if post['category'].strip().casefold()!=group['category'].strip().casefold():
            import media_library
            if group['category'].strip().upper()!='ALL' or post['category'] not in media_library.POOLS:return False
        if post['target_mode']=='selected':
            return c.execute('SELECT 1 FROM content_targets WHERE content_id=? AND group_id=?',(post['id'],group['id'])).fetchone() is not None
        return True

    def link_inventory(self):
        result={}
        with self.db() as c:
            for row in c.execute('SELECT body FROM contents'):
                for url in set(urls(row['body'])):
                    result.setdefault(url,{'url':url,'contents':0,'jobs':0})['contents']+=1
            for row in c.execute("SELECT body FROM jobs WHERE state IN ('draft','queued')"):
                for url in set(urls(row['body'])):
                    result.setdefault(url,{'url':url,'contents':0,'jobs':0})['jobs']+=1
        return sorted(result.values(),key=lambda item:(-item['jobs'],-item['contents'],item['url']))[:100]

    def _link_preview(self,c,old,new,facebook=False):
        old,new=validate_link(old),validate_link(new)
        if old==new:raise ValueError('Link mới phải khác link cũ.')
        content=[dict(row) for row in c.execute('SELECT id,body,comment_link,footer_text FROM contents') if any(replace_link(row[k],old,new)!=row[k] for k in ('body','comment_link','footer_text'))]
        jobs=[dict(row) for row in c.execute("SELECT id,body,state,comment_text FROM jobs WHERE state IN ('draft','queued')") if any(replace_link(row[k],old,new)!=row[k] for k in ('body','comment_text'))]
        if any(len(replace_link(item['body'],old,new))>5000 for item in content+jobs):
            raise ValueError('Thay link làm một bài vượt 5000 ký tự. Rút ngắn bài đó trước khi áp dụng.')
        posted=[row['id'] for row in c.execute("SELECT id,body FROM jobs WHERE state IN ('submitted','pending','uncertain','prepared')") if old in urls(row['body'])]
        snapshot={'old_url':old,'new_url':new,'contents':content,'jobs':jobs}
        footer=c.execute("SELECT v FROM kv WHERE k='post_footer'").fetchone()
        if footer and replace_link(json.loads(footer[0]).get('text',''),old,new)!=json.loads(footer[0]).get('text',''):
            snapshot['footer']=json.loads(footer[0])
        if facebook:
            from link_refresh import candidates
            snapshot['facebook']=candidates(c,old,new)
        digest=hashlib.sha256(json.dumps(snapshot,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        return snapshot,{'old_url':old,'new_url':new,'content_count':len(content),'job_count':len(jobs),'historical_count':len(posted),'digest':digest,'footer_count':int('footer' in snapshot),'facebook_enabled':bool(facebook),'facebook_count':len(snapshot.get('facebook',[])),'facebook_posts':[{'id':j['id'],'group_name':j['group_name'],'post_url':j['post_url'],'edit_body':j['body']!=j['body_after'],'comment_allowed':j['comment_allowed']} for j in snapshot.get('facebook',[])],
            'samples':[{'kind':'content','id':p['id'],'before':p['body'],'after':replace_link(p['body'],old,new)} for p in content[:3]]+[{'kind':'job','id':p['id'],'before':p['body'],'after':replace_link(p['body'],old,new)} for p in jobs[:3]]}

    def preview_links(self,old,new,facebook=False):
        with self.db() as c:return self._link_preview(c,old,new,facebook)[1]

    def apply_links(self,old,new,digest,facebook=False):
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute("SELECT id FROM jobs WHERE state='working' LIMIT 1").fetchone():
                raise ValueError('Có lượt đang thao tác. Gửi /pause, chờ thông báo dừng rồi thay link.')
            from link_refresh import busy
            if busy(c):raise ValueError('Đợt cập nhật Facebook trước chưa xong. Dừng hoặc chờ hoàn tất trước khi thay link tiếp.')
            scan=c.execute("SELECT v FROM kv WHERE k='group_scan'").fetchone()
            if scan and json.loads(scan[0]).get('status')=='running':raise ValueError('Đang quét nhóm. Chờ quét xong trước khi thay link.')
            snapshot,preview=self._link_preview(c,old,new,facebook)
            if not digest or digest!=preview['digest']:
                raise ValueError('Kho nội dung hoặc lịch đã đổi. Bấm Xem ảnh hưởng lại trước khi áp dụng.')
            if not snapshot['contents'] and not snapshot['jobs'] and not snapshot.get('facebook') and not snapshot.get('footer'):
                raise ValueError('Không có bài hoặc lượt chưa chạy nào dùng đúng link cũ này.')
            change_id=c.execute('INSERT INTO link_changes(at,old_url,new_url,before_json) VALUES(?,?,?,?)',
                (time.time(),preview['old_url'],preview['new_url'],json.dumps(snapshot,ensure_ascii=False))).lastrowid
            if snapshot.get('facebook'):
                from link_refresh import enqueue
                enqueue(c,change_id,snapshot['facebook'],preview['old_url'],preview['new_url'])
            for post in snapshot['contents']:
                c.execute('UPDATE contents SET body=?,comment_link=?,footer_text=? WHERE id=?',(*(replace_link(post[k],preview['old_url'],preview['new_url']) for k in ('body','comment_link','footer_text')),post['id']))
            for job in snapshot['jobs']:
                c.execute('UPDATE jobs SET body=?,comment_text=?,updated=? WHERE id=?',(replace_link(job['body'],preview['old_url'],preview['new_url']),replace_link(job['comment_text'],preview['old_url'],preview['new_url']),time.time(),job['id']))
            if snapshot.get('footer'):
                footer={**snapshot['footer'],'text':replace_link(snapshot['footer']['text'],preview['old_url'],preview['new_url'])}
                c.execute("UPDATE kv SET v=? WHERE k='post_footer'",(json.dumps(footer,ensure_ascii=False),))
            task=c.execute("SELECT v FROM kv WHERE k='studio_task'").fetchone()
            if task:
                task=json.loads(task[0])
                if task.get('result') and task['result'].get('id') in {p['id'] for p in snapshot['contents']}:
                    task['result']['body']=replace_link(task['result']['body'],preview['old_url'],preview['new_url'])
                    c.execute("UPDATE kv SET v=? WHERE k='studio_task'",(json.dumps(task,ensure_ascii=False),))
            for key,value in [('running',False),('paused_by_user',True),('current_link',preview['new_url'])]:
                c.execute('INSERT INTO kv VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v',(key,json.dumps(value)))
            current=c.execute("SELECT v FROM kv WHERE k='control_revision'").fetchone()
            revision=(json.loads(current[0]) if current else 0)+1
            c.execute('INSERT INTO kv VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v',('control_revision',str(revision)))
            return {**preview,'change_id':change_id}

    def set_link_policy(self, gid, policy):
        if policy not in {'allow', 'deny', 'unknown'}:
            raise ValueError('Quy định link phải là allow, deny hoặc unknown.')
        with self.db() as c:
            if c.execute("SELECT id FROM jobs WHERE group_id=? AND state='working'", (gid,)).fetchone():
                raise ValueError('Nhóm đang có lượt thao tác; /pause rồi chờ dừng trước khi đổi quy định.')
            if not c.execute('UPDATE groups SET link_policy=? WHERE id=?', (policy, gid)).rowcount:
                raise ValueError('Không tìm thấy nhóm.')
            # Policy changes invalidate pending approvals; never silently rewrite approved text.
            c.execute("UPDATE jobs SET state='cancelled',detail='Quy định link đã đổi. Lên lịch lại để chọn đúng phiên bản.',updated=? WHERE group_id=? AND state IN ('draft','queued')", (time.time(), gid))

    def enable_group(self, gid, enabled):
        with self.db() as c:
            row = c.execute('SELECT link_policy FROM groups WHERE id=? AND deleted=0', (gid,)).fetchone()
            if enabled and row and row['link_policy'] == 'unknown':
                raise ValueError('Chọn quyền link của nhóm trước khi bật.')
            if not c.execute('UPDATE groups SET enabled=? WHERE id=? AND deleted=0', (int(enabled), gid)).rowcount:
                raise ValueError('Không tìm thấy nhóm.')
            if not enabled:
                c.execute("UPDATE jobs SET state='cancelled',updated=? WHERE group_id=? AND state IN ('draft','queued')", (time.time(), gid))

    def toggle_groups(self, ids, enabled):
        if not isinstance(ids,list) or not ids or len(ids)>1000 or any(type(i) is not int or i<=0 for i in ids):
            raise ValueError('Chọn ít nhất một nhóm hợp lệ.')
        ids=list(dict.fromkeys(ids));changed=[];skipped=[]
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            rows={r['id']:r for r in c.execute('SELECT id,name,enabled,link_policy FROM groups WHERE deleted=0')}
            if any(gid not in rows for gid in ids):raise ValueError('Danh sách nhóm đã đổi. Tải lại trước khi thao tác.')
            working={r[0] for r in c.execute("SELECT DISTINCT group_id FROM jobs WHERE state='working'")}
            for gid in ids:
                row=rows[gid]
                reason='Nhóm đang có lượt thao tác.' if gid in working else 'Chưa chọn quy định link.' if enabled and row['link_policy']=='unknown' else ''
                if reason:
                    skipped.append({'id':gid,'name':row['name'],'reason':reason});continue
                if bool(row['enabled'])!=bool(enabled):
                    c.execute('UPDATE groups SET enabled=? WHERE id=?',(int(enabled),gid));changed.append(gid)
                if not enabled:
                    c.execute("UPDATE jobs SET state='cancelled',updated=? WHERE group_id=? AND state IN ('draft','queued')",(time.time(),gid))
        return {'changed':len(changed),'changed_ids':changed,'skipped':skipped,'enabled':bool(enabled)}

    def content(self, body, media='', body_no_link='', category='Chung', title='', media_no_link='',footer_text=''):
        body = body.strip()
        if not body or len(body) > 5000:
            raise ValueError('Nội dung phải có 1–5000 ký tự.')
        if len(body_no_link) > 5000 or has_link(body_no_link):
            raise ValueError('Bản không link tối đa 5000 ký tự và không chứa địa chỉ web.')
        if not str(category).strip():
            raise ValueError('Bài viết cần phân loại để chọn đúng nhóm.')
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            highest=c.execute("SELECT MAX(n) FROM (SELECT COALESCE(MAX(id),0) n FROM contents UNION ALL SELECT COALESCE(MAX(content_id),0) FROM jobs UNION ALL SELECT COALESCE(CAST(v AS INTEGER),0) FROM kv WHERE k='content_id_high_water')").fetchone()[0] or 0
            return c.execute('INSERT INTO contents(id,body,media,created,body_no_link,category,title,media_no_link,footer_text) VALUES(?,?,?,?,?,?,?,?,?)', (highest+1,body, media, time.time(), body_no_link.strip(), str(category).strip()[:80], str(title).strip()[:160], media_no_link,footer_text)).lastrowid

    def delete_contents(self, ids):
        """Delete library records only; frozen jobs, original media and history survive."""
        if not isinstance(ids,list) or not 1<=len(ids)<=500 or any(type(i) is not int or i<=0 for i in ids):
            raise ValueError('Chọn 1–500 bài hợp lệ để xóa.')
        ids=list(dict.fromkeys(ids))
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            highest=c.execute('SELECT COALESCE(MAX(id),0) FROM contents').fetchone()[0]
            old=c.execute("SELECT v FROM kv WHERE k='content_id_high_water'").fetchone()
            highest=max(highest,int(old[0]) if old else 0)
            c.execute("INSERT INTO kv(k,v) VALUES('content_id_high_water',?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",(str(highest),))
            placeholders=','.join('?' for _ in ids)
            c.execute(f'DELETE FROM content_targets WHERE content_id IN ({placeholders})',ids)
            return c.execute(f'DELETE FROM contents WHERE id IN ({placeholders})',ids).rowcount

    def no_link_content(self, cid, body, media=''):
        if not body.strip() or len(body) > 5000 or has_link(body):
            raise ValueError('Bản không link phải có 1–5000 ký tự, không chứa URL/tên miền.')
        with self.db() as c:
            if not c.execute('UPDATE contents SET body_no_link=?,media_no_link=? WHERE id=?', (body.strip(), media, cid)).rowcount:
                raise ValueError('Không tìm thấy bài viết.')

    def update_content(self,cid,body,media='',body_no_link='',category='Chung',title='',media_no_link=''):
        if not body.strip() or len(body)>5000 or len(body_no_link)>5000 or has_link(body_no_link) or not str(category).strip():
            raise ValueError('Kiểm tra nội dung, bản không link và phân loại bài viết.')
        with self.db() as c:
            if not c.execute('UPDATE contents SET body=?,media=?,body_no_link=?,category=?,title=?,media_no_link=? WHERE id=?',
                (body.strip(),media,body_no_link.strip(),str(category).strip()[:80],str(title).strip()[:160],media_no_link,cid)).rowcount:
                raise ValueError('Không tìm thấy bài viết.')
        return cid

    def plan(self, cid, minutes, start=None):
        return self.plan_many([cid], minutes, start)

    def plan_many(self, content_ids, minutes, start=None):
        bounds = interval_bounds(minutes)
        start = float(start or time.time())
        with self.db() as c:
            posts = [c.execute('SELECT * FROM contents WHERE id=?', (int(cid),)).fetchone() for cid in content_ids]
            groups = c.execute('SELECT * FROM groups WHERE enabled=1 ORDER BY id').fetchall()
            if not posts or any(p is None for p in posts) or not groups:
                raise ValueError('Cần bài viết hợp lệ và ít nhất một nhóm đã bật.')
            ids = []
            due = start
            for i, g in enumerate(groups):
                valid = []
                for post in posts:
                    if not self._eligible(c,post,g):
                        continue
                    try:
                        body,media=post_variant(post,g['link_policy'],g['category']);valid.append((post['id'],body,media))
                    except ValueError:
                        pass
                if not valid:
                    c.execute('INSERT INTO outbox(text) VALUES(?)', (f"⏭ Bỏ qua nhóm {g['name']}: chưa có quy định link hoặc thiếu bản nội dung phù hợp.",))
                    continue
                content_id, body, media = random.SystemRandom().choice(valid)
                old = c.execute("SELECT id FROM jobs WHERE group_id=? AND body=? AND media=? AND calendar_released=0 AND state IN ('draft','queued','working','uncertain','submitted','pending')", (g['id'], body, media)).fetchone()
                if old:
                    continue
                now = time.time()
                gap = sample_gap(bounds)
                due = max(due, g['next_post_after'])
                ids.append(c.execute('INSERT INTO jobs(group_id,group_name,url,body,media,due,created,updated,gap_seconds,content_id) VALUES(?,?,?,?,?,?,?,?,?,?)',
                    (g['id'], g['name'], g['url'], body, media, due, now, now, gap,content_id)).lastrowid)
                self._freeze_comments(c,ids[-1],content_id,g['id'],bounds[0]*60)
                due += gap
            return ids

    def cycle(self, cid, interval, min_days=1, max_days=1, horizon=30, start=None):
        """Freeze a finite, reviewable recurring campaign; never regenerate text at runtime."""
        return self.cycle_pool([cid],None,interval,min_days,max_days,horizon,start)

    def cycle_pool(self,content_ids,group_ids,interval,min_days=1,max_days=1,horizon=30,start=None,routing_mode='category'):
        if routing_mode not in {'category','random'}:raise ValueError('Chọn ghép theo phân loại hoặc random.')
        rng=random.SystemRandom()
        bounds = interval_bounds(interval)
        min_days, max_days, horizon = int(min_days), int(max_days), int(horizon)
        if not 1 <= min_days <= max_days <= 30 or not 1 <= horizon <= 90:
            raise ValueError('Khoảng lặp phải từ 1–30 ngày; thời gian lên lịch từ 1–90 ngày.')
        start = float(start or time.time())
        end = start+horizon*86400
        with self.db() as c:
            content_ids=list(dict.fromkeys(int(cid) for cid in content_ids))
            if not content_ids:raise ValueError('Chọn ít nhất một bài để đưa vào lịch.')
            posts=[c.execute('SELECT * FROM contents WHERE id=?',(cid,)).fetchone() for cid in content_ids]
            if any(p is None for p in posts):raise ValueError('Có bài viết không tồn tại.')
            if group_ids is not None:
                group_ids=list(dict.fromkeys(int(g) for g in group_ids))
                if not group_ids:raise ValueError('Chọn ít nhất một nhóm đích.')
                if any(not c.execute('SELECT id FROM groups WHERE id=?',(gid,)).fetchone() for gid in group_ids):raise ValueError('Có nhóm đích không tồn tại.')
            groups = c.execute('SELECT * FROM groups WHERE enabled=1 ORDER BY id').fetchall()
            ids=[];pending=[];pools={};bags={};previous={}
            for g in groups:
                if group_ids is not None and g['id'] not in group_ids:continue
                valid=[]
                for post in posts:
                    if not self._eligible(c,post,g,routing_mode):continue
                    try:
                        body,media=post_variant(post,g['link_policy'],g['category'])
                        if c.execute("SELECT 1 FROM jobs WHERE group_id=? AND body=? AND media=? AND calendar_released=0 AND state='uncertain' LIMIT 1",(g['id'],body,media)).fetchone():continue
                        valid.append((post['id'],body,media))
                    except ValueError:pass
                if not valid:
                    c.execute('INSERT INTO outbox(text) VALUES(?)',(f"⏭ Nhóm {g['name']} không có bài hợp lệ trong các bài được chọn (phân loại, nhóm đích, quyền link).",))
                    continue
                if c.execute("SELECT id FROM jobs WHERE group_id=? AND state IN ('draft','queued','working') LIMIT 1",(g['id'],)).fetchone():
                    c.execute('INSERT INTO outbox(text) VALUES(?)',(f"⏭ Nhóm {g['name']} đang có lịch; không tạo lịch chồng.",))
                    continue
                pools[g['id']]=(g,valid);bags[g['id']]=[]
                heapq.heappush(pending,(max(start,g['next_post_after']),rng.random() if routing_mode=='random' else g['id'],g['id']))
            # Schedule chronologically: minutes separate different groups;
            # per-group day spacing is independent and never consumes that minute range.
            global_due=start
            while pending:
                proposed,_,gid=heapq.heappop(pending)
                due=max(proposed,global_due)
                if due>=end:break
                g,valid=pools[gid];bag=bags[gid]
                if not bag:
                    bag.extend(valid);rng.shuffle(bag)
                    if len(bag)>1 and bag[-1][0]==previous.get(gid):bag[0],bag[-1]=bag[-1],bag[0]
                content_id,body,media=bag.pop();previous[gid]=content_id
                gap=sample_gap(bounds)
                group_gap=rng.randint(min_days*86400,max_days*86400)
                now=time.time()
                ids.append(c.execute('INSERT INTO jobs(group_id,group_name,url,body,media,due,created,updated,gap_seconds,group_gap_seconds,content_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                    (gid,g['name'],g['url'],body,media,due,now,now,gap,group_gap,content_id)).lastrowid)
                c.execute('UPDATE jobs SET routing_mode=? WHERE id=?',(routing_mode,ids[-1]))
                self._freeze_comments(c,ids[-1],content_id,gid,bounds[0]*60)
                global_due=due+gap
                heapq.heappush(pending,(due+group_gap,rng.random() if routing_mode=='random' else gid,gid))
            return ids

    def retime(self, interval, start=None):
        bounds = interval_bounds(interval)
        due = max(float(start or time.time()), self.get('next_allowed', 0))
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute("SELECT id FROM jobs WHERE state='working' LIMIT 1").fetchone():
                raise ValueError('Có lượt đang thao tác. Gửi /pause, chờ thông báo dừng rồi đổi lịch.')
            c.execute('INSERT INTO kv VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v', ('running', 'false'))
            jobs = c.execute("SELECT * FROM jobs WHERE state IN ('draft','queued') ORDER BY due,id").fetchall()
            per_group = {r['id']: r['next_post_after'] for r in c.execute('SELECT id,next_post_after FROM groups')}
            for job in jobs:
                jid = job['id']
                due = max(due, per_group.get(job['group_id'], 0))
                gap = sample_gap(bounds)
                c.execute("UPDATE jobs SET due=?,gap_seconds=?,state='draft',updated=? WHERE id=?", (due, gap, time.time(), jid))
                per_group[job['group_id']] = due+max(86400,job['group_gap_seconds'])
                due += gap
            return len(jobs)

    def approve(self, job_ids):
        with self.db() as c:
            n = 0
            for jid in job_ids:
                n += c.execute("UPDATE jobs SET state='queued',updated=? WHERE id=? AND state='draft' AND group_id IN (SELECT id FROM groups WHERE enabled=1 AND account_id=jobs.account_id)", (time.time(), int(jid))).rowcount
            return n

    def prepare_test(self,cid,gid,interval='30-60'):
        bounds=interval_bounds(interval)
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            post=c.execute('SELECT * FROM contents WHERE id=?',(cid,)).fetchone()
            group=c.execute('SELECT * FROM groups WHERE id=?',(gid,)).fetchone()
            if not post or not group or not group['enabled'] or not self._eligible(c,post,group):
                raise ValueError('Chọn 1 bài và 1 nhóm đang bật, đúng phân loại và nhóm đích của bài.')
            if c.execute("SELECT 1 FROM jobs WHERE state IN ('working','queued') LIMIT 1").fetchone():
                raise ValueError('Có lượt đang chạy hoặc chờ chạy. Tạm dừng và hủy lịch chờ trước khi thử riêng 1 bài.')
            if c.execute("SELECT 1 FROM jobs WHERE group_id=? AND calendar_released=0 AND state IN ('draft','queued','uncertain') LIMIT 1",(gid,)).fetchone():
                raise ValueError('Nhóm đã có lịch hoặc lượt chưa rõ kết quả. Hủy lịch cũ hoặc kiểm tra kết quả trước khi thử.')
            body,media=post_variant(post,group['link_policy'],group['category']);now=time.time()
            jid=c.execute("INSERT INTO jobs(group_id,group_name,url,body,media,due,created,updated,gap_seconds,content_id,prepare_only,state) VALUES(?,?,?,?,?,?,?,?,?,?,1,'queued')",
                (gid,group['name'],group['url'],body,media,now,now,now,sample_gap(bounds),cid)).lastrowid
            self._freeze_comments(c,jid,cid,gid,bounds[0]*60)
            return jid

    def refresh_global_cooldown(self):
        # Old versions also set this after failures/dry runs. Only possible
        # submissions justify an inter-group posting cooldown.
        with self.db() as c:
            deadline=c.execute("SELECT MAX(updated+CASE WHEN gap_seconds>0 THEN gap_seconds ELSE 3600 END) FROM jobs WHERE calendar_released=0 AND (state IN ('submitted','pending') OR (state='uncertain' AND post_attempted<>0))").fetchone()[0] or 0
            row=c.execute("SELECT v FROM kv WHERE k='failure_cooldown_until'").fetchone()
            deadline=max(deadline,json.loads(row[0]) if row else 0)
            c.execute("INSERT INTO kv VALUES('next_allowed',?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",(json.dumps(deadline),))
        return deadline

    def queue_outcome(self,jid,result):
        """Count a terminal job once; persist a nonblocking 50–80 minute break."""
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            return self._queue_outcome(c,jid,result)

    def _queue_outcome(self,c,jid,result):
        from queue_recovery import hard_pause
        state=result.get('state','uncertain')
        def read(key,default):
            row=c.execute('SELECT v FROM kv WHERE k=?',(key,)).fetchone()
            return json.loads(row[0]) if row else default
        def write(key,value):
            c.execute('INSERT INTO kv VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v',(key,json.dumps(value)))
        streak=read('failure_streak',0)
        until=read('failure_cooldown_until',0)
        inserted=c.execute('INSERT OR IGNORE INTO queue_outcomes VALUES(?,?,?)',(jid,state,time.time())).rowcount
        if inserted:
            if state in {'submitted','pending'}:streak=0
            elif state in {'error','uncertain'}:
                streak+=1
                if streak>=3:
                    until=max(until,time.time()+sample_gap((50,80)))
                    write('failure_cooldown_until',until)
                    write('next_allowed',max(read('next_allowed',0),until))
                    streak=0
            write('failure_streak',streak)
        return {'hard_pause':hard_pause(result),'failure_streak':streak,'queue_cooldown_until':until if until>time.time() else 0}

    def _reject_candidate(self,c,job,detail):
        c.execute("UPDATE jobs SET state='error',detail=?,post_attempted=0,updated=? WHERE id=?",(detail,time.time(),job['id']))
        policy=self._queue_outcome(c,job['id'],{'state':'error','post_attempted':False,'detail':detail})
        from final_report import render
        text=render(dict(job),dict(state='error',detail=detail,**{k:v for k,v in policy.items() if k!='hard_pause'}))
        c.execute('INSERT INTO outbox(text) VALUES(?)',(text,))
        return bool(policy['queue_cooldown_until'])

    def restore_failed_contents(self,content_ids):
        """Explicit operator retry: preserve original evidence and frozen payloads."""
        ids=list(dict.fromkeys(int(i) for i in content_ids))
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute("SELECT 1 FROM jobs WHERE state='working' LIMIT 1").fetchone():
                raise ValueError('Chờ lượt đang chạy hoàn tất trước khi khôi phục.')
            restored=[]
            for cid in ids:
                active=c.execute("SELECT id FROM jobs WHERE content_id=? AND state IN ('queued','draft') ORDER BY id DESC LIMIT 1",(cid,)).fetchone()
                if active:
                    c.execute("UPDATE jobs SET state='queued' WHERE id=? AND state='draft'",(active['id'],))
                    restored.append(active['id']);continue
                latest=c.execute('SELECT state FROM jobs WHERE content_id=? ORDER BY id DESC LIMIT 1',(cid,)).fetchone()
                if latest and latest['state'] in {'submitted','pending'}:
                    raise ValueError(f'Bài #{cid} đã đăng hoặc chờ duyệt; không tạo lượt trùng.')
                row=c.execute("SELECT * FROM jobs WHERE content_id=? AND state IN ('error','uncertain','cancelled') ORDER BY id DESC LIMIT 1",(cid,)).fetchone()
                if not row:raise ValueError(f'Bài #{cid} không có lượt lỗi để khôi phục.')
                group=c.execute('SELECT * FROM groups WHERE id=?',(row['group_id'],)).fetchone()
                if not group or group['deleted'] or not group['enabled']:
                    raise ValueError(f'Nhóm của bài #{cid} đang tắt hoặc đã xóa.')
                job=dict(row);origin=job.pop('id');now=time.time()
                # Legacy failure compaction may have reduced gap_seconds to 120;
                # a fresh posting attempt must restore its approved minimum gap.
                job['gap_seconds']=max(60,job['gap_seconds'],job['gap_min_seconds'])
                job.update(moderation_status='',retry_of=origin,calendar_released=0,state='queued',detail='',created=now,updated=now,due=max(now,group['next_post_after']),original_due=0,attempted_at=0,post_attempted=0,post_url='',photo='',comment_status='',safe_retries=0,hidden=0,schedule_note=f'Khôi phục theo yêu cầu từ lượt #{origin}; giữ lịch sử cũ.')
                columns=','.join(job);marks=','.join('?' for _ in job)
                restored.append(c.execute(f'INSERT INTO jobs({columns}) VALUES({marks})',list(job.values())).lastrowid)
            return restored

    def claim(self):
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            from approval_followup import busy as approval_busy
            if approval_busy(c):return None
            from link_refresh import busy
            if busy(c):return None
            scan=c.execute("SELECT v FROM kv WHERE k='group_scan'").fetchone()
            if scan and json.loads(scan[0]).get('status')=='running':return None
            raw = c.execute("SELECT v FROM kv WHERE k='running'").fetchone()
            if not raw or not json.loads(raw[0]):
                return None
            from queue_recovery import reflow
            now=time.time()
            reflow(c,now,self.get('next_allowed',0),max(1,min(30,int(self.get('daily_group_limit',20)))))
            # Serialize overdue jobs after sleep/restart: never catch up in a burst.
            if time.time() < self.get('next_allowed', 0):
                return None
            cap=max(1,min(30,int(self.get('daily_group_limit',20))))
            used=c.execute("SELECT COUNT(DISTINCT group_id) FROM jobs WHERE calendar_released=0 AND date(CASE WHEN attempted_at>0 THEN attempted_at ELSE updated END,'unixepoch','+7 hours')=date(?,'unixepoch','+7 hours') AND (attempted_at>0 OR state IN ('working','submitted','pending','uncertain'))",(time.time(),)).fetchone()[0]
            if used>=cap:return None
            candidates = c.execute("SELECT j.*,g.link_policy FROM jobs j JOIN groups g ON g.id=j.group_id WHERE j.state='queued' AND j.account_id=g.account_id AND j.calendar_released=0 AND j.due<=? AND g.enabled=1 AND g.next_post_after<=? AND NOT EXISTS (SELECT 1 FROM jobs prev WHERE prev.group_id=j.group_id AND prev.calendar_released=0 AND (prev.state='working' OR (prev.state IN ('submitted','pending','uncertain') AND date(prev.updated,'unixepoch','+7 hours')=date(?,'unixepoch','+7 hours')))) ORDER BY j.due,j.id", (time.time(), time.time(), time.time())).fetchall()
            job = None
            for candidate in candidates:
                post=c.execute('SELECT * FROM contents WHERE id=?',(candidate['content_id'],)).fetchone() if candidate['content_id'] else None
                group=c.execute('SELECT * FROM groups WHERE id=?',(candidate['group_id'],)).fetchone()
                if post is not None and not self._eligible(c,post,group,candidate['routing_mode']):
                    if self._reject_candidate(c,candidate,'Bài không còn được gán vào nhóm này. Tạo lịch mới.'):return None
                    continue
                if candidate['link_policy'] == 'unknown' or (candidate['link_policy'] == 'deny' and has_link(candidate['body'])):
                    if self._reject_candidate(c,candidate,'Nội dung không phù hợp quy định link hiện tại.'):return None
                    continue
                job = candidate
                break
            if not job:
                return None
            # Once a worker starts, a crash means unknown, even for a restored job
            # that was previously known not to have submitted in its new attempt.
            c.execute("UPDATE jobs SET state='working',post_attempted=-1,updated=?,attempted_at=? WHERE id=?", (time.time(),time.time(), job['id']))
            return dict(job)

    def finish(self, jid, state, detail,post_attempted=None):
        if state not in {'submitted', 'pending', 'uncertain', 'error', 'cancelled', 'prepared'}:
            raise ValueError('Trạng thái không hợp lệ.')
        with self.db() as c:
            c.execute('UPDATE jobs SET state=?,detail=?,updated=? WHERE id=?', (state, detail[:2000], time.time(), jid))
            if type(post_attempted) is bool:c.execute('UPDATE jobs SET post_attempted=? WHERE id=?',(int(post_attempted),jid))
            if state in {'submitted', 'pending', 'uncertain'} and not (state=='uncertain' and post_attempted is False):
                job = c.execute('SELECT group_id,group_gap_seconds FROM jobs WHERE id=?', (jid,)).fetchone()
                if job:
                    c.execute('UPDATE groups SET next_post_after=MAX(next_post_after,?) WHERE id=?', (time.time()+max(86400,job['group_gap_seconds']), job['group_id']))

