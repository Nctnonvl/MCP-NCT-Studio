"""User-managed OpenAI-compatible sources; credentials never enter public config."""
import re,secrets
from urllib.parse import urlsplit

def custom(provider):return str(provider).startswith('src_')

def local_http(parsed):
    return parsed.scheme=='http' and (parsed.hostname or '').lower() in {'localhost','127.0.0.1','::1'}

def get(store,provider,secret=False):
    rows=store.get('ai_sources',{})
    if provider not in rows:raise ValueError('Nguồn AI không còn tồn tại. Chọn lại nguồn trong Cài đặt.')
    row={**rows[provider],'id':provider}
    key=row.pop('key','');row['key_saved']=bool(key)
    if secret:
        from content_ai import unprotect
        row['api_key']=unprotect(key)
    return row

def catalog(store):return [get(store,p) for p in store.get('ai_sources',{})]

def idle(store):
    if store.get('ai_busy') or store.get('studio_task',{}).get('status')=='running' or store.rows("SELECT id FROM jobs WHERE state='working' LIMIT 1") or store.rows("SELECT id FROM link_refresh WHERE state IN ('queued','working') LIMIT 1"):
        raise ValueError('Đang có tác vụ AI/Facebook. Dừng và chờ tác vụ kết thúc trước khi sửa nguồn.')

def save(store,obj):
    idle(store)
    provider=str(obj.get('id') or 'src_'+secrets.token_hex(8))
    rows=store.get('ai_sources',{})
    if not re.fullmatch(r'src_[a-f0-9]{16}',provider) or (obj.get('id') and provider not in rows):raise ValueError('Nguồn không hợp lệ.')
    name=str(obj.get('name','')).strip();base=str(obj.get('base_url','')).strip().rstrip('/');model=str(obj.get('model','')).strip()
    parsed=urlsplit(base)
    if not 1<=len(name)<=80 or any(ord(c)<32 for c in name):raise ValueError('Tên nguồn từ 1–80 ký tự.')
    try: parsed.port
    except ValueError: raise ValueError('Cổng API không hợp lệ.') from None
    if (parsed.scheme!='https' and not local_http(parsed)) or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or re.search(r'\s',base):raise ValueError('Dùng HTTPS hoặc HTTP localhost (localhost, 127.0.0.1, ::1); không chứa key, query hoặc thông tin đăng nhập.')
    if model and not re.fullmatch(r'[\w./:-]{1,160}',model):raise ValueError('Nhập đúng ID model của dịch vụ.')
    old=rows.get(provider,{});key=old.get('key','');value=str(obj.get('api_key','')).strip()
    if old.get('base_url') and old['base_url']!=base and not value:raise ValueError('Đổi địa chỉ API cần nhập lại key cho địa chỉ mới; không chuyển key cũ sang máy chủ khác.')
    if value:
        if len(value)>1000 or any(ord(c)<33 or ord(c)>126 for c in value):raise ValueError('API key không hợp lệ.')
        from content_ai import protect
        key=protect(value)
    rows[provider]={'name':name,'base_url':base,'model':model,'key':key}
    store.set('ai_sources',rows)
    return get(store,provider)

def delete(store,provider):
    idle(store)
    if store.get('content_ai',{}).get('writer_provider')==provider or store.get('control_ai',{}).get('provider')==provider:raise ValueError('Nguồn đang được dùng. Chọn và lưu nguồn khác cho viết bài/điều khiển trước khi xóa.')
    rows=store.get('ai_sources',{})
    if provider not in rows:raise ValueError('Không tìm thấy nguồn tùy chỉnh.')
    del rows[provider];store.set('ai_sources',rows)

def remote(store,provider,path,payload=None,timeout=100):
    from net import request_json
    source=get(store,provider,True);key=source['api_key']
    if not key:raise ValueError('Chưa nhập key cho nguồn '+source['name'])
    try:
        options={'headers':{'Authorization':'Bearer '+key}}
        if local_http(urlsplit(source['base_url'])):options['local_only']=True
        return request_json(source['base_url']+path,payload,timeout,**options)
    except Exception as exc:raise RuntimeError(str(exc).replace(key,'[API_KEY]')[:650]) from None

def check(store,provider):
    data=remote(store,provider,'/models',timeout=20)
    models=[r['id'] for r in data.get('data',[]) if isinstance(r,dict) and isinstance(r.get('id'),str)]
    selected=get(store,provider)['model']
    return {'connected':True,'models':models,'selected_model_listed':selected in models,'note':'Chỉ đọc danh sách model, chưa gọi tạo nội dung. Hạn mức còn lại xem tại dịch vụ.'}
