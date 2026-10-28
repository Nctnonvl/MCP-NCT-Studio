"""Separate local browser profiles; queued jobs retain their original account."""
import json,secrets,time
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
