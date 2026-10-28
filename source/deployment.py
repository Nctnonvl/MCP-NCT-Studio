"""Relocatable desktop data, explicit imports, and machine-bound credentials."""
import base64,json,os,shutil,sqlite3,time
from contextlib import closing
from pathlib import Path,PureWindowsPath

def relocate(value,old,new):
    if isinstance(value,dict):return {k:relocate(v,old,new) for k,v in value.items()}
    if isinstance(value,list):return [relocate(v,old,new) for v in value]
    if not isinstance(value,str):return value
    if value.startswith(('[','{')):
        try:return json.dumps(relocate(json.loads(value),old,new),ensure_ascii=False)
        except ValueError:return value
    v=value.replace('\\','/');prefix=str(old).replace('\\','/').rstrip('/')
    if v.casefold()==prefix.casefold() or v.casefold().startswith(prefix.casefold()+'/'):
        return str(Path(new).joinpath(*v[len(prefix):].strip('/').split('/')))
    return value

def remap(store,old,new):
    """Only file-bearing columns/configs; captions and public links are untouched."""
    columns={'jobs':['media','video_fallback_media','photo','browser_profile_json'],
             'contents':['media','media_no_link'],'group_reviews':['photo'],
             'facebook_accounts':['profile'],'outbox':['photo']}
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE')
        for table,fields in columns.items():
            for row in c.execute('SELECT * FROM '+table).fetchall():
                for field in fields:
                    value=relocate(row[field],old,new)
                    if value!=row[field]:c.execute(f'UPDATE {table} SET {field}=? WHERE id=?',(value,row['id']))
        # Hashes identify the exact frozen browser profile; relocation is the same account.
        import hashlib
        for row in c.execute("SELECT id,browser_profile_json FROM jobs WHERE browser_profile_json<>''").fetchall():
            c.execute('UPDATE approval_checks SET profile_revision=? WHERE job_id=?',(hashlib.sha256(row['browser_profile_json'].encode()).hexdigest()[:20],row['id']))
    config=Path(new)/'browser-profile.json'
    if config.exists():config.write_text(json.dumps(relocate(json.loads(config.read_text(encoding='utf-8')),old,new),ensure_ascii=False,indent=2),encoding='utf-8')

def clear_secrets(store):
    changed=[]
    for setting,fields in [('config',['token']),('control_ai',['api_key']),('content_ai',['writer_key','vision_key'])]:
        value=store.get(setting,{})
        for field in fields:
            if value.get(field):value[field]='';changed.append(setting+'.'+field)
        store.set(setting,value)
    sources=store.get('ai_sources',{})
    for item in sources.values():item['key']=''
    store.set('ai_sources',sources)
    return changed

def unreadable_secrets(store):
    from content_ai import unprotect
    missing=[]
    for setting,fields in [('config',['token']),('control_ai',['api_key']),('content_ai',['writer_key','vision_key'])]:
        obj=store.get(setting,{})
        for field in fields:
            value=obj.get(field,'')
            if not value.startswith('dpapi:'):continue
            try:unprotect(value)
            except Exception:obj[field]='';missing.append(setting+'.'+field)
        store.set(setting,obj)
    sources=store.get('ai_sources',{})
    for key,obj in sources.items():
        try:unprotect(obj.get('key',''))
        except Exception:obj['key']='';missing.append(key)
    store.set('ai_sources',sources)
    return missing

def prepare(store,data):
    data=Path(data).resolve();marker=data/'location.json'
    old=json.loads(marker.read_text(encoding='utf-8')).get('data_dir') if marker.exists() else None
    if old and str(data)!=old:remap(store,old,data)
    config=data/'browser-profile.json'
    if not config.exists():
        config.write_text(json.dumps({'browser':'chrome','user_data_dir':str(data/'chrome-profile'),'profile_directory':None,'display_name':'NCT Facebook','facebook_account':''}),encoding='utf-8')
    missing=unreadable_secrets(store)
    if missing:
        for key,val in [('running',False),('paused_by_user',True),('approval_monitor_enabled',False)]:store.set(key,val)
        store.set('deployment_notice','Máy Windows này không đọc được key đã lưu. Nhập lại API key và token Telegram trong Cài đặt rồi đăng nhập Facebook trong từng hồ sơ.')
    marker.write_text(json.dumps({'data_dir':str(data),'version':1},ensure_ascii=False),encoding='utf-8')

def import_data(source,destination):
    from store import Store
    source=Path(source).resolve();destination=Path(destination).resolve()
    if not (source/'manager.sqlite3').is_file():raise ValueError('Chọn thư mục data có manager.sqlite3.')
    if destination.exists():raise ValueError('Đích đã có dữ liệu; không ghi đè. Dùng thư mục đích mới.')
    stage=destination.with_name(destination.name+'.import-'+str(time.time_ns()))
    stage.mkdir(parents=True)
    try:
        with closing(sqlite3.connect((source/'manager.sqlite3').as_uri()+'?mode=ro',uri=True)) as src,closing(sqlite3.connect(stage/'manager.sqlite3')) as dst:src.backup(dst)
        if (source/'media').is_dir():
            (stage/'media').mkdir()
            for file in (source/'media').iterdir():
                if file.is_file() and not file.is_symlink() and file.suffix.lower() in {'.png','.jpg','.jpeg','.webp','.mp4','.mov','.webm'}:shutil.copy2(file,stage/'media'/file.name)
        cfg=source/'browser-profile.json'
        if cfg.is_file():shutil.copy2(cfg,stage/cfg.name)
        else:(stage/'browser-profile.json').write_text(json.dumps({'browser':'chrome','user_data_dir':str(destination/'chrome-profile'),'profile_directory':None,'display_name':'NCT Facebook'}),encoding='utf-8')
        store=Store(stage/'manager.sqlite3')
        # Preserve history thumbnails without importing worker payloads or browser sessions.
        photos=set()
        for table in ('jobs','group_reviews'):
            for row in store.rows('SELECT photo FROM '+table):
                if row['photo']:photos.add(PureWindowsPath(row['photo']).name)
        for name in photos:
            original=source/'work'/name
            if original.is_file() and not original.is_symlink() and original.suffix.lower() in {'.png','.jpg','.jpeg'}:
                (stage/'work').mkdir(exist_ok=True);shutil.copy2(original,stage/'work'/name)
        import facebook_accounts
        facebook_accounts.bootstrap(store,stage)
        # Map old media paths and every frozen author to new private Chrome roots.
        remap(store,source,destination)
        # A folder already copied onto a USB drive can still contain old drive paths.
        roots=set()
        for row in store.rows('SELECT media FROM contents'):
            from media import paths
            for value in paths(row['media']):
                normalized=value.replace('\\','/')
                if '/media/' in normalized:roots.add(normalized.rsplit('/media/',1)[0])
        for old in roots:
            if old.casefold()!=str(destination).replace('\\','/').casefold():remap(store,old,destination)
        profiles={}
        with store.db() as c:
            for row in c.execute('SELECT * FROM facebook_accounts').fetchall():
                import re
                aid=row['id'];profile=json.loads(row['profile'])
                if aid!='main' and not re.fullmatch(r'acc_[0-9a-f]{16}',aid):raise ValueError('ID tài khoản trong dữ liệu nhập không hợp lệ.')
                profile.update(browser='chrome',user_data_dir=str(destination/('chrome-profile' if aid=='main' else 'facebook-profiles/'+aid)),profile_directory=None)
                profiles[aid]=json.dumps(profile,ensure_ascii=False)
                c.execute('UPDATE facebook_accounts SET profile=? WHERE id=?',(profiles[aid],aid))
            for aid,raw in profiles.items():c.execute('UPDATE jobs SET browser_profile_json=? WHERE account_id=?',(raw,aid))
            import hashlib
            for row in c.execute("SELECT id,browser_profile_json FROM jobs WHERE browser_profile_json<>''").fetchall():c.execute('UPDATE approval_checks SET profile_revision=? WHERE job_id=?',(hashlib.sha256(row['browser_profile_json'].encode()).hexdigest()[:20],row['id']))
            c.execute("UPDATE jobs SET state='uncertain',detail='Lượt đang thao tác trên máy cũ; cần kiểm tra, không tự gửi lại.' WHERE state='working'")
            c.execute("UPDATE jobs SET state='draft',detail='Lịch nhập từ máy khác; cần duyệt lại trước khi chạy.' WHERE state='queued'")
            c.execute("UPDATE approval_checks SET state='waiting' WHERE state='working'")
            c.execute("UPDATE link_refresh SET state='uncertain' WHERE state IN ('working','queued')")
            c.execute('DELETE FROM outbox')
        if 'main' in profiles:(stage/'browser-profile.json').write_text(profiles['main'],encoding='utf-8')
        clear_secrets(store)
        for key,val in [('running',False),('paused_by_user',True),('approval_monitor_enabled',False),('ai_busy',False),('studio_task',{}),('group_scan',{})]:store.set(key,val)
        store.set('deployment_notice','Đã nhập kho, nhóm và lịch sử. Nhập lại API key/token Telegram, đăng nhập Facebook và duyệt lại lịch nháp trước khi chạy. Phiên trình duyệt cũ không được sao chép.')
        (stage/'location.json').write_text(json.dumps({'data_dir':str(destination),'version':1}),encoding='utf-8')
        # Close all SQLite handles before moving; source remains untouched.
        stage.rename(destination)
    except Exception:
        shutil.rmtree(stage,ignore_errors=True)
        raise

def replace_data(source,destination):
    source=Path(source).resolve();destination=Path(destination).resolve()
    if source==destination or source.is_relative_to(destination) or destination.is_relative_to(source):raise ValueError('Thư mục nguồn và đích phải tách biệt; không chọn dữ liệu đang sử dụng.')
    if not (source/'manager.sqlite3').is_file():raise ValueError('Chọn thư mục data có manager.sqlite3.')
    backup=None
    if destination.exists():
        backup=destination.with_name(destination.name+'.backup-'+str(time.time_ns()))
        destination.rename(backup)
    try:import_data(source,destination)
    except Exception:
        if backup and not destination.exists():backup.rename(destination)
        raise
    return str(backup) if backup else ''

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--import-data',required=True);p.add_argument('--destination',required=True);p.add_argument('--replace-existing',action='store_true');a=p.parse_args()
    if a.replace_existing:
        backup=replace_data(a.import_data,a.destination)
        if backup:print('Dữ liệu trước khi nhập được sao lưu tại: '+backup)
    else:import_data(a.import_data,a.destination)
    print('Đã nhập dữ liệu. Chưa bật lịch hoặc đăng bài.')
