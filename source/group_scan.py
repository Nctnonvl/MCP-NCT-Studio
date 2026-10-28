"""Import joined-group cards through the configured Edge window and Windows MCP.

Only the joins page is read. No model, cookies, private Facebook API or joining.
"""
import asyncio,json,os,re,sys,threading,time,unicodedata,subprocess
from pathlib import Path
from urllib.parse import urlsplit
from store import group_url

PAGE='https://www.facebook.com/groups/joins/'
VIEW={'view group','xem nhóm','afficher le groupe','voir le groupe'}
PENDING=('demande d’adhésion envoyée',"demande d'adhésion envoyée",'request sent','membership pending','đã gửi yêu cầu','đang chờ phê duyệt')

def clean(value):return ' '.join(unicodedata.normalize('NFC',str(value)).casefold().split())

def game_from_name(name):
    name=clean(name)
    for category,pattern in [('Valorant',r'\bvalorant\b'),('Delta Force',r'\bdelta\s*force\b'),('PUBG',r'\bpubg\b'),('LOL',r'\blol\b|liên minh|league of legends'),('The isle',r'\bthe\s+isle\b'),('CS2',r'\bcs\s*2\b|\bcs\s*:?\s*go\b')]:
        if re.search(pattern,name):return category
    return ''

def joined_cards(cards):
    found={}
    for card in cards:
        names=[clean(x.get('name','')) for x in card['links']]
        if not any(n in VIEW for n in names) or any(x in clean(card['text']) for x in PENDING):continue
        links=[]
        for link in card['links']:
            try:url=group_url(link['url'])
            except (ValueError,TypeError,KeyError):continue
            links.append((url,str(link.get('name','')).strip()))
        urls={u.casefold() for u,n in links}
        if len(urls)!=1:continue
        named=[(u,n) for u,n in links if n and clean(n) not in VIEW]
        if named:
            url,name=max(named,key=lambda x:len(x[1]))
            found[url.casefold()]={'url':url,'name':name[:160],'category':game_from_name(name)}
    return list(found.values())

def import_found(store,rows,account_id="main"):
    added=[];duplicates=0;seen=set();review=[]
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE')
        existing={group_url(g['url']).casefold():g['id'] for g in c.execute('SELECT id,url FROM groups')}
        existing.update({r['alias'].casefold():r['group_id'] for r in c.execute('SELECT a.* FROM group_aliases a JOIN groups g ON g.id=a.group_id')})
        for row in rows:
            url=group_url(row['url']);key=url.casefold()
            if key in seen:continue
            seen.add(key)
            if row.get('review_only'):review.append({'name':row['name'],'url':url});continue
            if key in existing:
                duplicates+=1;gid=existing[key]
                for alias in row.get('aliases',[]):
                    alias=group_url(alias).casefold()
                    if alias not in existing or existing[alias]==gid:
                        c.execute('INSERT OR IGNORE INTO group_aliases VALUES(?,?)',(alias,gid));existing[alias]=gid
                continue
            category=game_from_name(row['name'])
            gid=c.execute("INSERT INTO groups(url,name,rules,category,enabled,link_policy,account_id) VALUES(?,?,?, ?,0,'unknown',?)",(url,str(row['name'])[:160],'',category,account_id)).lastrowid
            if category:c.execute('INSERT OR IGNORE INTO group_media_pools VALUES(?,?)',(gid,category))
            added.append(gid);existing[key]=gid
            for alias in row.get('aliases',[]):c.execute('INSERT OR IGNORE INTO group_aliases VALUES(?,?)',(group_url(alias).casefold(),gid))
    return {'added':len(added),'duplicates':duplicates,'found':len(seen),'group_ids':added,'needs_review':review}

def read_header_identity(root):
    """Only an observed members URL identifies a vanity URL; never infer by name."""
    import comtypes,windows_mcp.uia as uia
    comtypes.CoInitialize()
    try:
        ids=set();deadline=time.monotonic()+8;budget=[8000]
        def walk(node):
            if budget[0]<=0 or time.monotonic()>deadline:return
            budget[0]-=1
            if node.ControlTypeName=='HyperlinkControl':
                try:
                    p=node.GetLegacyIAccessiblePattern();url=urlsplit(p.Value if p else '')
                    m=re.fullmatch(r'/groups/(\d+)/members/?',url.path)
                    if url.hostname in {'www.facebook.com','facebook.com'} and m:ids.add(m[1])
                except Exception:pass
            try:children=node.GetChildren()
            except Exception:return
            for child in children:walk(child)
        walk(uia.ControlFromHandle(root))
        return next(iter(ids)) if len(ids)==1 else ''
    finally:comtypes.CoUninitialize()

def read_cards(root):
    import comtypes,windows_mcp.uia as uia
    comtypes.CoInitialize()
    try:
        window=uia.ControlFromHandle(root);cards=[];point=None;budget=[20000];deadline=time.monotonic()+12
        viewport=window.BoundingRectangle
        def walk(node):
            if budget[0]<=0 or time.monotonic()>deadline:return
            budget[0]-=1;yield node
            try:children=node.GetChildren()
            except Exception:return
            for child in children:yield from walk(child)
        for node in walk(window):
            try:
                if getattr(node,'AriaRole','')=='main':
                    r=node.BoundingRectangle
                    left=max(r.left,viewport.left);right=min(r.right,viewport.right)
                    top=max(r.top,viewport.top);bottom=min(r.bottom,viewport.bottom)
                    if right>left and bottom>top:point=[int((left+right)/2),int((top+bottom)/2)]
                if node.ControlTypeName!='ListItemControl' and getattr(node,'AriaRole','')!='listitem':continue
                links=[]
                for item in walk(node):
                    if item.ControlTypeName!='HyperlinkControl':continue
                    pattern=item.GetLegacyIAccessiblePattern()
                    links.append({'name':item.Name,'url':pattern.Value if pattern else ''})
                cards.append({'text':node.Name,'links':links})
            except Exception:continue
        return cards,point
    finally:comtypes.CoUninitialize()

class GroupScanner:
    def __init__(self,store,data):
        self.store=store;self.data=Path(data);self.stop=threading.Event()
        self.window=None;self.previous=[];self.identity=None
    def update(self,**values):
        state=self.store.get('group_scan',{});state.update(values,updated=time.time());self.store.set('group_scan',state)
    def start(self,account_id="main"):
        with self.store.db() as c:
            c.execute('BEGIN IMMEDIATE')
            if not c.execute('SELECT 1 FROM facebook_accounts WHERE id=?',(account_id,)).fetchone():raise ValueError('Tài khoản quét không tồn tại. Chọn lại tài khoản.')
            from link_refresh import busy
            if busy(c):raise ValueError('Đang cập nhật link Facebook. Chờ xong hoặc dừng cập nhật trước khi quét nhóm.')
            if self.store.get('group_scan',{}).get('status')=='running':raise ValueError('Đang quét nhóm; chờ hoàn tất hoặc bấm Dừng quét.')
            if c.execute("SELECT 1 FROM jobs WHERE state='working'").fetchone():raise ValueError('Worker đang thao tác Facebook. Tạm dừng và chờ worker kết thúc trước khi quét.')
            if self.store.get('studio_task',{}).get('status')=='running':raise ValueError('AI đang tạo bài. Chờ hoàn tất trước khi quét.')
            for key,value in [('running',False),('paused_by_user',True),('control_revision',self.store.get('control_revision',0)+1),('group_scan',{'status':'running','account_id':account_id,'message':'Đang mở danh sách nhóm đã tham gia…','found':0,'updated':time.time()})]:
                c.execute('INSERT INTO kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v',(key,json.dumps(value)))
        self.stop.clear()
        threading.Thread(target=self.monitor,daemon=True).start()
        return {'message':'Đang quét nhóm từ hồ sơ Facebook đã chọn. Để yên chuột/bàn phím; lịch đăng đã tạm dừng.'}
    def monitor(self):
        """A fresh process per scan prevents UIA COM state leaking across threads."""
        work=self.data/'work';work.mkdir(exist_ok=True)
        process=None
        try:
            with (work/'group-scan-worker.log').open('ab') as log:
                process=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--worker',str(self.data.resolve())],cwd=Path(__file__).resolve().parent,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
                deadline=time.monotonic()+600;stop_at=None
                while process.poll() is None:
                    if self.stop.is_set():
                        self.update(cancel_requested=True)
                        if stop_at is None:stop_at=time.monotonic()+12
                    if time.monotonic()>deadline or (stop_at is not None and time.monotonic()>stop_at):
                        from browser_cleanup import stop_worker
                        stop_worker(process)
                        self.update(status='stopped' if stop_at else 'error',message='Đã dừng quét. Nhóm đã nhập được giữ nguyên; có thể quét lại.')
                        return
                    time.sleep(.3)
            if self.store.get('group_scan',{}).get('status')=='running':self.update(status='error',message='Bộ quét đã kết thúc trước khi có kết quả. Có thể quét lại.')
        except Exception as exc:
            if process is not None and process.poll() is None:
                from browser_cleanup import stop_worker
                stop_worker(process)
            self.update(status='error',message=str(exc)[:300])
        finally:
            if process is not None:
                try:
                    if process.poll() is None:
                        from browser_cleanup import stop_worker
                        stop_worker(process)
                    from browser_cleanup import recover
                    closed=recover(self.data/'work/group-scan-browser.json',self.data,process.pid)
                    if closed:self.update(browser_closed=True)
                except Exception as exc:self.update(browser_close_detail=str(exc)[:200])
    def run(self):
        from desktop import _BROWSER_PROFILE
        token=None
        try:
            account_id=self.store.get('group_scan',{}).get('account_id','main')
            accounts=self.store.rows('SELECT profile FROM facebook_accounts WHERE id=?',(account_id,))
            if not accounts and account_id!='main':raise ValueError('Không tìm thấy tài khoản đã chọn để quét.')
            token=_BROWSER_PROFILE.set(json.loads(accounts[0]['profile']) if accounts else None)
            rows,complete=asyncio.run(self.scan())
            counts=import_found(self.store,rows,account_id)
            self.update(status='done' if complete else 'stopped',**counts,message=f"{'Quét xong' if complete else 'Đã dừng quét'}: {counts['added']} nhóm mới, {counts['duplicates']} nhóm đã có, {len(counts['needs_review'])} nhóm cần xem lại. Nhóm mới đang tắt; kiểm tra phân loại và quyền link trước khi bật.")
        except Exception as exc:self.update(status='error',message=str(exc)[:500])
        finally:
            try:
                from browser_cleanup import finish
                closed=finish(self.window,self.data,self.previous,self.identity,self.data/'work/group-scan-browser.json')
                self.update(browser_closed=closed)
            except Exception as exc:self.update(browser_closed=False,browser_close_detail=str(exc)[:200])
            if token is not None:_BROWSER_PROFILE.reset(token)
    async def scan(self):
        from desktop import (profile_windows,launch_browser,focus_profile,foreground,
                             wait_initial_control,mcp_text,active_window_tree)
        from mcp import ClientSession,StdioServerParameters
        from mcp.client.stdio import stdio_client
        previous=profile_windows(self.data);launch_browser(self.data,PAGE);await asyncio.sleep(5)
        root=await focus_profile(self.data,previous,lambda text:self.update(message=text))
        from desktop import window_identity
        self.window=root;self.previous=previous;self.identity=window_identity(root)
        from browser_cleanup import register
        from desktop import selected_browser_config
        register(self.data/'work/group-scan-browser.json',root,previous,self.identity,selected_browser_config(self.data))
        params=StdioServerParameters(command=sys.executable,args=['-m','windows_mcp','serve','--transport','stdio','--tools','Snapshot,Shortcut,Scroll'],env={**os.environ,'ANONYMIZED_TELEMETRY':'false'})
        found={};stale=0;complete=False;expected=None
        async with stdio_client(params) as (read,write):
            async with ClientSession(read,write) as session:
                await asyncio.wait_for(session.initialize(),timeout=60);await wait_initial_control(session,lambda text:self.update(message=text))
                async def tool(name,args):
                    foreground(root)
                    response=await asyncio.wait_for(session.call_tool(name,args),timeout=60)
                    if response.isError:raise RuntimeError('Windows MCP không thực hiện được bước '+name)
                    return mcp_text(response)
                for index in range(80):
                    if self.stop.is_set() or self.store.get('group_scan',{}).get('cancel_requested'):break
                    # Read the actual URL on every page before inspecting or scrolling.
                    import pyperclip
                    old=pyperclip.paste();marker='NCT-group-scan-'+str(time.monotonic_ns())
                    try:
                        pyperclip.copy(marker);await tool('Shortcut',{'shortcut':'ctrl+l'});await tool('Shortcut',{'shortcut':'ctrl+c'})
                        await asyncio.sleep(.2);current=pyperclip.paste().strip()
                    finally:
                        await tool('Shortcut',{'shortcut':'esc'});pyperclip.copy(old)
                    p=urlsplit(current)
                    if p.scheme!='https' or p.hostname not in {'www.facebook.com','facebook.com'} or p.path.rstrip('/')!='/groups/joins':
                        raise RuntimeError('Đã rời trang nhóm đã tham gia hoặc cần đăng nhập. Mở Facebook trong hồ sơ đã chọn rồi thử lại.')
                    snap=await tool('Snapshot',{'use_dom':True,'use_vision':False})
                    total=re.search(r'(?:tous les groupes dont vous êtes membre|all groups you.ve joined|all your groups|tất cả nhóm bạn đã tham gia)\s*\((\d+)\)',clean(snap))
                    if total:expected=int(total[1])
                    if index==0:
                        work=self.data/'work';work.mkdir(exist_ok=True)
                        (work/'group-scan-dom-true.txt').write_text(snap,encoding='utf-8')
                        raw=await tool('Snapshot',{'use_dom':False,'use_vision':False})
                        (work/'group-scan-dom-false.txt').write_text(raw,encoding='utf-8')
                    cards,point=await asyncio.to_thread(read_cards,root)
                    rows=joined_cards(cards);before=len(found)
                    found.update({r['url'].casefold():r for r in rows})
                    self.update(found=len(found),message=f'Đã đọc {len(found)} nhóm · trang cuộn {index+1}.')
                    stale=stale+1 if len(found)==before else 0
                    if expected is not None and len(found)>=expected:complete=True;break
                    if stale>=3:complete=expected is None;break
                    if not point:raise RuntimeError('Chưa xác định được vùng danh sách nhóm để cuộn; đã dừng.')
                    bounds=foreground(root)
                    if not bounds[0]<=point[0]<bounds[2] or not bounds[1]<=point[1]<bounds[3]:raise RuntimeError('Vùng danh sách nằm ngoài cửa sổ trình duyệt.')
                    await tool('Scroll',{'loc':point,'direction':'down','wheel_times':6});await asyncio.sleep(1.5)
                # Resolve same-name URL aliases while the same MCP session owns
                # the verified window. Different groups can share a display name.
                existing=self.store.rows('SELECT id,name,url FROM groups')
                known={r['url'].casefold() for r in existing}|{r['alias'].casefold() for r in self.store.rows('SELECT alias FROM group_aliases')}
                cache={}
                async def identity(url):
                    slug=group_url(url).rstrip('/').split('/')[-1]
                    if slug.isdigit():return slug
                    if url in cache:return cache[url]
                    import pyperclip
                    old=pyperclip.paste()
                    try:
                        pyperclip.copy(url);await tool('Shortcut',{'shortcut':'ctrl+l'});await tool('Shortcut',{'shortcut':'ctrl+v'});await tool('Shortcut',{'shortcut':'enter'})
                    finally:pyperclip.copy(old)
                    await asyncio.sleep(4)
                    # Verify page location from the actual browser address bar.
                    marker='NCT-alias-'+str(time.monotonic_ns());old=pyperclip.paste()
                    try:
                        pyperclip.copy(marker);await tool('Shortcut',{'shortcut':'ctrl+l'});await tool('Shortcut',{'shortcut':'ctrl+c'});await asyncio.sleep(.2)
                        actual=pyperclip.paste().strip()
                    finally:
                        await tool('Shortcut',{'shortcut':'esc'});pyperclip.copy(old)
                    try:valid=group_url(actual)==group_url(url)
                    except ValueError:valid=False
                    if not valid:return ''
                    cache[url]=await asyncio.to_thread(read_header_identity,root)
                    return cache[url]
                for row in found.values():
                    if self.stop.is_set() or self.store.get('group_scan',{}).get('cancel_requested'):complete=False;break
                    if row['url'].casefold() in known:continue
                    matches=[r for r in existing if clean(r['name'])==clean(row['name'])]
                    if not matches:continue
                    self.update(message='Đối chiếu link chữ/link số: '+row['name'])
                    own_id=await identity(row['url']);unresolved=not own_id;matched=False
                    for old in matches:
                        old_id=await identity(old['url'])
                        if not old_id:unresolved=True
                        if own_id and own_id==old_id:
                            row['aliases']=[row['url'],'https://www.facebook.com/groups/'+own_id+'/'];row['url']=old['url'];matched=True;break
                    if not matched and unresolved:row['review_only']=True
        if not found and complete:raise RuntimeError('Chưa đọc được nhóm đã tham gia. Kiểm tra Facebook đã tải xong và đúng tài khoản, rồi quét lại.')
        return list(found.values()),complete

if __name__=='__main__':
    if len(sys.argv)!=3 or sys.argv[1]!='--worker':raise SystemExit('Use the dashboard scan button.')
    from store import Store
    data=Path(sys.argv[2]).resolve()
    GroupScanner(Store(data/'manager.sqlite3'),data).run()
