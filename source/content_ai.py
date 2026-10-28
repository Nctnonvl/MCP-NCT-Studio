"""Separate xKiro writing and KiraAI vision. Public config never exposes keys."""
import base64,json,os,re,time,datetime
import ai_provider
import ai_sources
from net import request_json
KIRA='https://kiraai.vn/api/v1'
DEFAULT_VISION='ornith-ornith-1.5-122b-free'

def unprotect(value):
    if value.startswith('dpapi:'):
        import win32crypt
        return win32crypt.CryptUnprotectData(base64.b64decode(value[6:]),None,None,None,0)[1].decode()
    return value

def protect(value):
    if not value:return ''
    if os.name=='nt':
        import win32crypt
        return 'dpapi:'+base64.b64encode(win32crypt.CryptProtectData(value.encode(),'NCT content AI',None,None,None,0)).decode()
    return value

def config(store,secret=False):
    raw=store.get('content_ai',{});old=store.get('control_ai',{})
    result={'writer_provider':raw.get('writer_provider','ollama'),'writer_model':raw.get('writer_model',ai_provider.DEFAULT_MODEL),
            'vision_model':raw.get('vision_model',DEFAULT_VISION),'vision_base_url':KIRA,
            'writer_key_saved':bool(raw.get('writer_key') or old.get('api_key')),'vision_key_saved':bool(raw.get('vision_key')),
            'daily_calls':raw.get('daily_calls',100)}
    if ai_sources.custom(result['writer_provider']):
        source=ai_sources.get(store,result['writer_provider'],secret)
        result.update(writer_model=source['model'],writer_key_saved=source['key_saved'],writer_name=source['name'])
    if secret:
        result['writer_key']=unprotect(raw.get('writer_key') or old.get('api_key',''))
        result['vision_key']=unprotect(raw.get('vision_key',''))
        if ai_sources.custom(result['writer_provider']):result['writer_key']=source['api_key']
    return result

def save_config(store,obj):
    provider=obj.get('writer_provider','xkiro');model=str(obj.get('writer_model') or ai_provider.DEFAULT_MODEL).strip()
    vision=str(obj.get('vision_model') or DEFAULT_VISION).strip();limit=int(obj.get('daily_calls',100))
    if ai_sources.custom(provider):
        source=ai_sources.get(store,provider);ai_sources.idle(store)
        if not source['model'] or not source['key_saved']:raise ValueError('Lưu key và chọn model trong Quản lý nguồn AI trước.')
    if provider not in {'xkiro','ollama'} and not ai_sources.custom(provider):raise ValueError('Nguồn viết bài không hợp lệ.')
    if not ai_sources.custom(provider) and (not re.fullmatch(r'[\w./:-]{1,160}',model) or not model.endswith(':free')):raise ValueError('Model xKiro viết bài phải có hậu tố :free.')
    if not re.fullmatch(r'[\w./:-]{1,160}',vision):raise ValueError('Mã model KiraAI không hợp lệ.')
    if not 1<=limit<=1000:raise ValueError('Giới hạn lượt AI/ngày từ 1 đến 1000 cho mỗi dịch vụ.')
    raw=store.get('content_ai',{})
    for field in ('writer_key','vision_key'):
        value=str(obj.get(field,'')).strip()
        if field=='writer_key' and ai_sources.custom(provider) and value:raise ValueError('Nhập key tại mục Quản lý nguồn AI cho nguồn tùy chỉnh.')
        if value:
            if len(value)>500 or any(ord(c)<33 or ord(c)>126 for c in value):raise ValueError('API key không hợp lệ.')
            raw[field]=protect(value)
    raw.update(writer_provider=provider,writer_model=model,vision_model=vision,daily_calls=limit)
    store.set('content_ai',raw)

def reserve(store,provider,purpose,model):
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE')
        used=c.execute("SELECT COUNT(*) FROM content_ai_calls WHERE provider=? AND date(at,'unixepoch','+7 hours')=date(?,'unixepoch','+7 hours')",(provider,time.time())).fetchone()[0]
        if used>=config(store)['daily_calls']:raise ValueError('Đã đạt giới hạn lượt AI trong ngày của '+provider+'.')
        return c.execute('INSERT INTO content_ai_calls(at,provider,purpose,model) VALUES(?,?,?,?)',(time.time(),provider,purpose,model)).lastrowid

def completion(store,provider,purpose,messages,temperature=None):
    cfg=config(store,True);vision=provider=='kira';key=cfg['vision_key' if vision else 'writer_key'];model=cfg['vision_model' if vision else 'writer_model']
    if not key:raise ValueError('Chưa lưu key '+('KiraAI quét ảnh' if vision else 'xKiro viết bài')+' trong Cài đặt.')
    if not vision and not ai_sources.custom(provider) and not model.endswith(':free'):raise ValueError('Không tự chuyển sang model xKiro trả phí.')
    cid=None
    try:
        if vision:verify_free_vision(store,model)
        cid=reserve(store,provider,purpose,model)
        send=(lambda url,body,timeout,headers:ai_sources.remote(store,provider,'/chat/completions',body,timeout)) if ai_sources.custom(provider) else request_json
        response=send((KIRA if vision else ai_provider.XKIRO)+'/chat/completions',{'model':model,'messages':messages,'stream':False,'temperature':(0.2 if vision else 0.7) if temperature is None else temperature,'max_tokens':1200},100,headers={'Authorization':'Bearer '+key})
        usage=response.get('usage',{});tokens=usage.get('total_tokens',0)
        if not vision:ai_provider.record(store,0,model,usage)
        with store.db() as c:c.execute("UPDATE content_ai_calls SET state='received',tokens=? WHERE id=?",(int(tokens) if isinstance(tokens,(float,int)) else 0,cid))
        choice=response['choices'][0]
        if choice.get('finish_reason')=='length':raise ValueError('AI trả nội dung bị cắt; không dùng kết quả này.')
        content=choice['message']['content']
        if not isinstance(content,str):raise ValueError('AI chưa trả văn bản.')
        content=re.sub(r'^```(?:json)?\s*|\s*```$','',content.strip())
        result=json.loads(content)
        if not isinstance(result,dict):raise ValueError('AI chưa trả đối tượng JSON.')
        return result
    except Exception as exc:
        if cid is not None:
            with store.db() as c:c.execute("UPDATE content_ai_calls SET state='failed' WHERE id=?",(cid,))
        message=str(exc).replace(key,'[API_KEY]')
        raise RuntimeError(('Dịch vụ '+provider+' · '+message)[:650]) from None

def writer_json(store,system,user,temperature=None):
    return completion(store,config(store)['writer_provider'],'write_or_classify',[{'role':'system','content':system+' Chỉ trả một đối tượng JSON, không markdown.'},{'role':'user','content':json.dumps(user,ensure_ascii=False)}],temperature=temperature)

def check_vision(store):
    cfg=config(store,True);key=cfg['vision_key']
    if not key:raise ValueError('Nhập key KiraAI trên PC trước.')
    try:
        response=request_json(KIRA+'/models',None,20,headers={'Authorization':'Bearer '+key})
        models=response.get('data',response.get('models',[])) if isinstance(response,dict) else response
        if not isinstance(models,list):raise ValueError('Chưa đọc được danh sách model Kira.')
        ids=[m.get('id') for m in models if isinstance(m,dict) and isinstance(m.get('id'),str)]
        return {'connected':True,'models':ids[:100],'selected_model_listed':cfg['vision_model'] in ids,'note':'Chỉ đọc danh sách model, chưa phân tích ảnh.'}
    except Exception as exc:raise RuntimeError(str(exc).replace(key,'[API_KEY]')[:600]) from None


def free_vision_model(model,now=None):
    if model.get('is_free') is not True or model.get('status')!='active' or model.get('type')!='chat':return False
    inputs=model.get('input_types',[])
    if model.get('is_pro') or not isinstance(inputs,list) or 'image' not in inputs:return False
    until=model.get('promo_end_at')
    if until:
        try:
            end=datetime.datetime.fromisoformat(until.replace('Z','+00:00'))
            if end.tzinfo is None:return False
            if end.timestamp()<=(time.time() if now is None else now):return False
        except (ValueError,TypeError):return False
    return True

def refresh_vision_models(store):
    # Public vendor catalog: model metadata only, no API key or user images.
    response=request_json(KIRA+'/models',None,20)
    rows=response.get('data',[]) if isinstance(response,dict) else []
    if not isinstance(rows,list):raise ValueError('Không đọc được danh mục model KiraAI; chưa gửi ảnh.')
    eligible=[m for m in rows if isinstance(m,dict) and free_vision_model(m)]
    result={'checked_at':time.time(),'models':[{'id':m['id'],'name':m.get('name',m['id']),'free_until':m.get('promo_end_at') or ''} for m in eligible if isinstance(m.get('id'),str)]}
    store.set('kira_vision_catalog',result)
    return result

def verify_free_vision(store,model):
    catalog=refresh_vision_models(store)
    if not any(m['id']==model for m in catalog['models']):
        raise ValueError('Model KiraAI đã chọn chưa được xác nhận đang miễn phí và nhận ảnh (không yêu cầu Pro). Chọn lại model; không chuyển sang trả phí hoặc model khác.')
