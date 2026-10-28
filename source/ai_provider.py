"""Control-model transport. Cloud secrets remain in the local encrypted store."""
import ai_sources
import base64
import datetime as dt
import json
import os
import re
import time
from pathlib import Path
from net import request_json
from store import Store

XKIRO='https://api.xkiro.com/v1'
DEFAULT_MODEL='qwen/qwen3.8-max:free'

def config(store,secret=False):
    raw=store.get('control_ai',{})
    result={'provider':raw.get('provider','ollama'),'model':raw.get('model',DEFAULT_MODEL),'key_saved':bool(raw.get('api_key')),'base_url':XKIRO}
    if ai_sources.custom(result['provider']):
        source=ai_sources.get(store,result['provider'],secret)
        result.update(model=source['model'],base_url=source['base_url'],key_saved=source['key_saved'],name=source['name'])
        if secret:result['api_key']=source['api_key']
        return result
    if secret:
        key=raw.get('api_key','')
        if key.startswith('dpapi:'):
            import win32crypt
            key=win32crypt.CryptUnprotectData(base64.b64decode(key[6:]),None,None,None,0)[1].decode()
        result['api_key']=key
    return result

def save_config(store,obj):
    provider=obj.get('provider','ollama');model=str(obj.get('model') or DEFAULT_MODEL).strip()
    if ai_sources.custom(provider):
        ai_sources.idle(store);source=ai_sources.get(store,provider)
        if not source['model'] or not source['key_saved']:raise ValueError('Lưu key và chọn model trong Quản lý nguồn AI trước.')
        store.set('control_ai',{**store.get('control_ai',{}),'provider':provider,'model':source['model']})
        store.set('running',False);store.set('control_revision',store.get('control_revision',0)+1)
        return
    if provider not in {'ollama','xkiro'}:raise ValueError('Chọn Ollama hoặc xKiro.')
    if not re.fullmatch(r'[A-Za-z0-9_.:/-]{1,160}',model) or not model.endswith(':free'):
        raise ValueError('Bản thử chỉ dùng model xKiro có hậu tố :free; ví dụ '+DEFAULT_MODEL)
    if store.rows("SELECT id FROM jobs WHERE state='working' LIMIT 1"):raise ValueError('Tạm dừng và chờ lượt hiện tại kết thúc trước khi đổi AI.')
    old=store.get('control_ai',{});protected=old.get('api_key','')
    key=str(obj.get('api_key') or '').strip()
    if key:
        if len(key)>500 or any(ord(c)<33 or ord(c)>126 for c in key):raise ValueError('API key không hợp lệ.')
        protected=key
        if os.name=='nt':
            import win32crypt
            protected='dpapi:'+base64.b64encode(win32crypt.CryptProtectData(key.encode(),'NCT xKiro',None,None,None,0)).decode()
    if provider=='xkiro' and not protected:raise ValueError('Nhập API key xKiro trên PC trước.')
    store.set('control_ai',{'provider':provider,'model':model,'api_key':protected})
    store.set('running',False);store.set('control_revision',store.get('control_revision',0)+1)

def remote(store,path,payload=None,timeout=100):
    provider=config(store)['provider']
    if ai_sources.custom(provider):return ai_sources.remote(store,provider,path,payload,timeout)
    key=config(store,True).get('api_key')
    if not key:raise ValueError('Chưa lưu API key xKiro trong Cài đặt.')
    try:return request_json(XKIRO+path,payload,timeout,headers={'Authorization':'Bearer '+key})
    except Exception as exc:
        text=str(exc).replace(key,'[API_KEY]')
        if '429' in text:text='Hết hạn mức hoặc bị giới hạn tốc độ xKiro (429). Đã dừng, không tự chuyển sang model trả phí. '+text
        if '401' in text:text='API key xKiro chưa hợp lệ hoặc đã bị thu hồi (401). '+text
        raise RuntimeError(text[:900]) from None

def check_connection(store):
    if ai_sources.custom(config(store)['provider']):return ai_sources.check(store,config(store)['provider'])
    data=remote(store,'/usage',timeout=15)
    free=data.get('free_tokens',{})
    if not isinstance(free,dict) or not all(k in free for k in ('used_today','limit_per_day','remaining')):raise RuntimeError('xKiro chưa trả dữ liệu hạn mức đầy đủ; chưa xác nhận kết nối.')
    result={'used_today':free.get('used_today'),'limit_per_day':free.get('limit_per_day'),'remaining':free.get('remaining'),'checked_at':time.time()}
    store.set('xkiro_quota',result)
    return result

def record(store,job_id,model,usage):
    known=isinstance(usage,dict) and 'prompt_tokens' in usage and 'completion_tokens' in usage
    usage=usage if isinstance(usage,dict) else {}
    def number(key):
        value=usage.get(key,0)
        return max(0,int(value)) if isinstance(value,(int,float)) else 0
    prompt=number('prompt_tokens');output=number('completion_tokens');total=max(number('total_tokens'),prompt+output)
    with store.db() as c:c.execute('INSERT INTO ai_usage(at,job_id,model,input_tokens,output_tokens,total_tokens,known) VALUES(?,?,?,?,?,?,?)',(time.time(),job_id,model,prompt,output,total,int(known)))

def usage_summary(store):
    zone=dt.timezone(dt.timedelta(hours=7));now=dt.datetime.now(zone);start=now.replace(hour=0,minute=0,second=0,microsecond=0).timestamp()
    totals=store.rows('SELECT COUNT(*) calls,COALESCE(SUM(input_tokens),0) input_tokens,COALESCE(SUM(output_tokens),0) output_tokens,COALESCE(SUM(total_tokens),0) total_tokens,COALESCE(SUM(1-known),0) unknown_calls FROM ai_usage WHERE at>=?',(start,))[0]
    totals['per_job']=store.rows('SELECT job_id,COUNT(*) calls,SUM(total_tokens) total_tokens FROM ai_usage GROUP BY job_id ORDER BY job_id DESC LIMIT 100')
    return totals

def control_chat(payload,job=None):
    from net import request_json
    # Existing installations keep the Ollama path unless xKiro was selected explicitly.
    selected=(job or {}).get('control_ai',{'provider':'ollama'})
    if selected.get('provider')=='ollama':return request_json('http://127.0.0.1:11434/api/chat',payload,120)
    store=Store(Path(job['data_dir'])/'manager.sqlite3');model=selected['model']
    if not ai_sources.custom(selected['provider']) and not model.endswith(':free'):raise ValueError('Chặn model không có hậu tố :free. Không tự dùng gói trả phí.')
    messages=[]
    for message in payload['messages']:
        content=message['content']
        if message['role']=='user':
            try:
                obj=json.loads(content)
                if isinstance(obj,dict) and 'page' in obj:
                    obj['page']=obj['page'][-6000:]
                    content=json.dumps(obj,ensure_ascii=False)
            except (ValueError,TypeError):pass
        messages.append({'role':message['role'],'content':content})
    body={'model':model,'messages':messages,'stream':False,'temperature':0,'max_tokens':768,'reasoning_effort':'low','response_format':{'type':'json_object'}}
    if ai_sources.custom(selected['provider']):body.pop('reasoning_effort',None)
    response=ai_sources.remote(store,selected['provider'],'/chat/completions',body) if ai_sources.custom(selected['provider']) else remote(store,'/chat/completions',body)
    record(store,job['id'],model,response.get('usage'))
    try:
        choice=response['choices'][0]
        if choice.get('finish_reason')=='length':raise RuntimeError('xKiro trả lời bị cắt ở giới hạn token. Đã dừng trước thao tác; không tự tăng ngân sách.')
        content=choice['message']['content']
        if not isinstance(content,str):raise ValueError()
        return {'message':{'content':content}}
    except (KeyError,IndexError,TypeError,ValueError):raise RuntimeError('xKiro chưa trả nội dung đúng định dạng; đã dừng.') from None
