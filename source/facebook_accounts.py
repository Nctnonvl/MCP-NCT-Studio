"""Separate local browser profiles; queued jobs retain their original account."""
import json,secrets,time,os,re
from pathlib import Path

def bootstrap(store,data):
    path=Path(data)/'browser-profile.json'
    raw=path.read_text(encoding='utf-8') if path.exists() else ''
    if not raw:return
    with store.db() as c:
        c.execute("INSERT OR IGNORE INTO facebook_accounts(id,name,profile,created) VALUES('main',?,?,?)",('Tài khoản hiện tại',raw,time.time()))
        c.execute("UPDATE jobs SET account_id='main',browser_profile_json=? WHERE browser_profile_json=''",(raw,))

def catalog(store):
    return [{'id':r['id'],'name':r['name'],'facebook_account':json.loads(r['profile']).get('facebook_account',''),'browser':json.loads(r['profile']).get('browser','edge')} for r in store.rows('SELECT * FROM facebook_accounts ORDER BY created,id')]

def create(store,data,name,facebook_account=''):
    name=str(name).strip();actor=str(facebook_account).strip()
    if not name or len(name)>80 or len(actor)>100:raise ValueError('Nhập tên tài khoản tối đa 80 ký tự.')
    aid='acc_'+secrets.token_hex(8)
    root=(Path(data)/'facebook-profiles'/aid).resolve()
    root.mkdir(parents=True,exist_ok=False)
    profile={'browser':'chrome','user_data_dir':str(root),'profile_directory':None,'display_name':name,'facebook_account':actor}
    with store.db() as c:c.execute('INSERT INTO facebook_accounts VALUES(?,?,?,?)',(aid,name,json.dumps(profile,ensure_ascii=False),time.time()))
    return aid

def chrome_profiles():
    root=Path(os.environ.get('LOCALAPPDATA',''))/'Google/Chrome/User Data'
    if not (root/'Local State').is_file():return []
    try:state=json.loads((root/'Local State').read_text(encoding='utf-8'))
    except (OSError,ValueError):return []
    if not isinstance(state,dict) or not isinstance(state.get('profile'),dict):return []
    cache=state['profile'].get('info_cache',{})
    if not isinstance(cache,dict):return []
    profiles=[]
    for directory,info in cache.items():
        if not isinstance(info,dict):continue
        if not re.fullmatch(r'Default|Profile [0-9]+',directory) or not (root/directory/'Preferences').is_file():continue
        name=str(info.get('name','')).strip()
        if name:profiles.append({'id':directory,'name':name})
    for item in profiles:item['usable']=sum(p['name'].casefold()==item['name'].casefold() for p in profiles)==1
    return sorted(profiles,key=lambda item:item['name'].casefold())

def chrome_profile_config(directory,name='',facebook_account=''):
    choices=[p for p in chrome_profiles() if p['id']==directory and p['usable']]
    if len(choices)!=1:raise ValueError('Không tìm thấy hồ sơ Chrome duy nhất. Tải lại danh sách và chọn lại.')
    name=str(name).strip() or choices[0]['name'];actor=str(facebook_account).strip()
    if not name or len(name)>80 or len(actor)>100:raise ValueError('Nhập tên tài khoản tối đa 80 ký tự.')
    root=(Path(os.environ['LOCALAPPDATA'])/'Google/Chrome/User Data').resolve()
    return {'browser':'chrome','user_data_dir':str(root),'profile_directory':directory,'display_name':name,'facebook_account':actor,'shared_profile_name':choices[0]['name']}

def use_chrome_profile(store,directory,name,facebook_account=''):
    profile=chrome_profile_config(directory,name,facebook_account)
    root=Path(profile['user_data_dir'])
    aid='acc_'+secrets.token_hex(8)
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE')
        for existing in c.execute('SELECT profile FROM facebook_accounts'):
            other=json.loads(existing['profile'])
            if other.get('browser')=='chrome' and os.path.normcase(str(other.get('user_data_dir','')))==os.path.normcase(str(root)) and other.get('profile_directory')==directory:raise ValueError('Hồ sơ Chrome này đã được thêm vào tool.')
        c.execute('INSERT INTO facebook_accounts VALUES(?,?,?,?)',(aid,profile['display_name'],json.dumps(profile,ensure_ascii=False),time.time()))
    return aid

def assign(store,gid,aid):
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE')
        if not c.execute('SELECT 1 FROM facebook_accounts WHERE id=?',(aid,)).fetchone():raise ValueError('Không tìm thấy tài khoản.')
        if not c.execute('UPDATE groups SET account_id=? WHERE id=? AND deleted=0',(aid,gid)).rowcount:raise ValueError('Không tìm thấy nhóm.')
    # Existing jobs are intentionally frozen to their author, including pending posts.

def freeze(c,jid,gid):
    group=c.execute('SELECT account_id FROM groups WHERE id=?',(gid,)).fetchone()
    aid=group['account_id'] if group else 'main'
    account=c.execute('SELECT * FROM facebook_accounts WHERE id=?',(aid,)).fetchone()
    if account:c.execute('UPDATE jobs SET account_id=?,browser_profile_json=? WHERE id=?',(aid,account['profile'],jid))
    elif aid!='main':raise ValueError('Tài khoản của nhóm không còn tồn tại; không tạo lịch.')
