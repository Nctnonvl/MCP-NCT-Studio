"""Bounded read-only navigation to the group's Your content receipts."""
from post_context import clean
import re
from urllib.parse import urlsplit,parse_qs
import time,asyncio
from receipts import post_url
from facebook_labels import POST_MENUS,EXPAND,RECENT
from comment_identity import ANONYMOUS

YOUR_CONTENT={'nội dung của bạn','your content','votre contenu','vos contenus'}
GROUP_SHARE={'chia sẻ nhóm','share group','partager le groupe'}
GROUP_MORE={'xem thêm','more','more options','khác','plus','autres options'}
FILTERS={'pending':('đang chờ','pending','en attente'),'submitted':('đã đăng','published','publié','publiées'),'declined':('bị từ chối','declined','refusé','refusées'),'removed':('đã gỡ','removed','supprimé','supprimées')}

def age_matches(name,job):
    name=clean(name)
    if name in RECENT:low,high=0,2
    else:
        match=re.fullmatch(r'(?:il y a )?(?:khoảng |about |environ )?(\d+)\s*(phút|minutes?|min|giờ|hours?|heures?|h|ngày|days?|jours?)(?: trước| ago)?',name)
        if not match:return False
        unit=match[2];scale=1440 if unit in {'ngày','day','days','jour','jours'} else 60 if unit in {'giờ','hour','hours','heure','heures','h'} else 1
        low=int(match[1])*scale;high=low+scale
    sent=job.get('submitted_at') or job.get('attempted_at') or time.time()
    elapsed=max(0,(time.time()-sent)/60)
    return low<=elapsed+5 and high>=max(0,elapsed-15) and low<=7*1440

def card_post_url(value,group):
    direct=post_url(value,group)
    if direct:return direct
    try:
        p=urlsplit(value);g=urlsplit(group);ids=parse_qs(p.query).get('multi_permalinks',[])
        if p.scheme!='https' or p.hostname not in {'www.facebook.com','facebook.com','m.facebook.com'} or p.username or p.password or p.port not in {None,443}:return ''
        if p.path.rstrip('/')!=g.path.rstrip('/') or len(ids)!=1 or not re.fullmatch(r'[0-9]+',ids[0]):return ''
        return 'https://www.facebook.com'+g.path.rstrip('/')+'/posts/'+ids[0]+'/'
    except (ValueError,TypeError):return ''

def page_status(url,group):
    try:
        p=urlsplit(url);g=urlsplit(group)
        if p.scheme!='https' or p.hostname not in {'www.facebook.com','facebook.com','m.facebook.com'} or p.username or p.password or p.port not in {None,443}:return ''
        slug=g.path.strip('/').split('/')[1]
        m=re.fullmatch(r'/groups/([^/]+)/(my_pending_content|my_posted_content|my_declined_content|my_removed_content)/?',p.path)
        if not m or m[1]!=slug:return ''
        return {'my_pending_content':'pending','my_posted_content':'submitted','my_declined_content':'declined','my_removed_content':'removed'}[m[2]]
    except (ValueError,IndexError,TypeError):return ''

def filter_target(targets,status):
    labels=FILTERS[status]
    found=[t for t in targets if t.get('role')=='link' and any(t.get('name','')==s or t.get('name','').startswith(s+' ') for s in labels)]
    return found[0] if len(found)==1 else None

def observed_content_group(url,targets,job):
    """A numeric destination reached through this group's Your content menu.

    Require the same group's visible back link as well; never accept an
    arbitrary numeric group merely because its page has moderation filters.
    """
    try:
        p=urlsplit(url)
        match=re.fullmatch(r'/groups/([0-9]+)/(?:my_pending_content|my_posted_content|my_declined_content|my_removed_content)/?',p.path)
        if not match:return ''
        group='https://www.facebook.com/groups/'+match[1]+'/'
        if not page_status(url,group):return ''
        name=clean(job.get('group_name',''))
        if not name:return ''
        filters=[filter_target(targets,state) for state in FILTERS]
        top=min((t['loc'][1] for t in filters if t and len(t.get('loc',[]))==2),default=-1)
        # The same name also occurs in the author's post card. Only the
        # breadcrumb above the moderation sidebar is the group's back link.
        back=[t for t in targets if t.get('role')=='link' and t.get('name')==name and len(t.get('loc',[]))==2 and t['loc'][1]<top]
        return group if len(back)==1 else ''
    except (ValueError,TypeError):return ''

def group_menu(targets):
    searches=[t for t in targets if t.get('role')=='button' and t.get('name') in {'tìm kiếm trong nhóm này','search this group','rechercher dans ce groupe'}]
    if len(searches)==1:
        x,y=searches[0]['loc']
        choices=[t for t in targets if t.get('role')=='button' and t.get('name') in GROUP_MORE and t['loc'][0]>x+25 and abs(t['loc'][1]-y)<45]
        if len(choices)==1:return choices[0]
    shares=[t for t in targets if t.get('role')=='button' and t.get('name') in GROUP_SHARE]
    if len(shares)!=1:return None
    x,y=shares[0]['loc']
    candidates=[t for t in targets if t.get('role')=='button' and t.get('name') in GROUP_MORE and t['loc'][0]>x+30 and abs(t['loc'][1]-y)<140]
    return candidates[0] if len(candidates)==1 else None

def content_menu(targets):
    choices=[t for t in targets if t.get('role') in {'button','menu item','menuitem','link'} and t.get('name') in YOUR_CONTENT]
    return choices[0] if len(choices)==1 else None

def read_matches(root,job,status):
    """Find complete caption only inside a single post card, never from global tab counts."""
    import comtypes,windows_mcp.uia as uia
    comtypes.CoInitialize()
    try:
        budget=[14000];deadline=time.monotonic()+8
        def walk(node,path=()):
            if budget[0]<=0 or time.monotonic()>deadline:return
            budget[0]-=1;yield node,path
            try:children=node.GetChildren()
            except Exception:return
            for child in children:yield from walk(child,path+(node,))
        caption=clean(job['body']);prefix=clean(job['body'].splitlines()[0])[:55]
        if len(prefix)<15:return []
        matches=[]
        for node,path in list(walk(uia.ControlFromHandle(root))):
            try:
                if node.ControlTypeName!='TextControl' or prefix not in clean(node.Name):continue
                if getattr(node,'IsOffscreen',False) or any(getattr(p,'IsOffscreen',False) for p in path if p.ControlTypeName=='DocumentControl'):continue
                if any(p.ControlTypeName=='EditControl' for p in path):continue
                for parent in reversed(path):
                    if parent.ControlTypeName in {'DocumentControl','WindowControl'}:break
                    if getattr(parent,'IsOffscreen',False):continue
                    entries=list(walk(parent));names=[];links=set();menus=[];actors=[];recent=False;expand=[];views=[];times=[];header_end=None
                    for item,ancestry in entries:
                        if any(p.ControlTypeName=='EditControl' for p in ancestry):continue
                        name=clean(item.Name);role=item.ControlTypeName
                        if role in {'TextControl','HyperlinkControl'}:names.append(name)
                        if role in {'TextControl','HyperlinkControl'} and (name in RECENT or re.fullmatch(r'(?:il y a )?(?:khoảng |about |environ )?\d+\s*(?:phút|minutes?|min|giờ|hours?|heures?|h|ngày|days?|jours?)(?: trước| ago)?',name)):times.append(name)
                        if role=='ButtonControl' and any(s in name for s in POST_MENUS):
                            menus.append(item)
                            if header_end is None:header_end=len(times)
                        if role=='ButtonControl' and name in ANONYMOUS:actors.append(name)
                        if role=='TextControl':
                            author=re.match(r'(.+?) (?:đã đăng lên|posted to|a publié dans) ',name)
                            if author:actors.append(author[1])
                        if role=='HyperlinkControl':
                            try:href=item.GetLegacyIAccessiblePattern().Value
                            except Exception:href=''
                            url=next((card_post_url(href,g) for g in job.get('verification_groups',[job['url']]) if card_post_url(href,g)),'')
                            if url and 'comment_id' not in href:
                                links.add(url)
                                if name in {'xem trong nhóm','view in group','voir dans le groupe'}:
                                    vr=item.BoundingRectangle
                                    views.append({'url':href,'role':'link','name':name,'text':'link \"'+item.Name+'\"','loc':[(vr.left+vr.right)//2,(vr.top+vr.bottom)//2]})
                        if role=='ButtonControl' and name in EXPAND and not item.IsOffscreen:
                            r=item.BoundingRectangle;expand.append({'name':name,'role':'button','loc':[(r.left+r.right)//2,(r.top+r.bottom)//2],'text':'button "'+item.Name+'"'})
                    header=list(dict.fromkeys(times[:header_end] if header_end is not None else times))
                    recent=len(header)==1 and age_matches(header[0],job)
                    if len(menus)!=1 and getattr(parent,'AriaRole','')!='article':continue
                    if caption not in clean(' '.join(names)):
                        if len(expand)==1:return [{'expand':expand[0]}]
                        continue
                    r=parent.BoundingRectangle;actor=next(iter(set(actors))) if len(set(actors))==1 else ''
                    identity='anonymous' if actor in ANONYMOUS else 'nickname' if actor and actor==clean(job.get('posting_nickname','')) else 'named' if actor else ''
                    menu=None
                    if len(menus)==1:
                        mr=menus[0].BoundingRectangle
                        menu={'id':0,'loc':[(mr.left+mr.right)//2,(mr.top+mr.bottom)//2],'role':'button','name':clean(menus[0].Name),'text':menus[0].Name}
                    matches.append({'view_target':views[0] if len(views)==1 else None, 'post_menu':menu,'state':status,'post_url':next(iter(links)) if len(links)==1 else '', 'post_identity':identity,'post_actor':actor,'post_identity_verified':bool(identity),'recent':recent,'key':[r.left,r.top,r.right,r.bottom]})
                    break
            except Exception:continue
        return list({(m.get('post_url') or tuple(m.get('key',[])),m.get('state')):m for m in matches}.values())
    finally:comtypes.CoUninitialize()

def choose_match(matches,expected_url=''):
    cards=[m for m in matches if 'expand' not in m]
    if expected_url:cards=[m for m in cards if m.get('post_url')==expected_url]
    else:cards=[m for m in cards if m.get('recent')]
    return cards[0] if len(cards)==1 else None

async def verify(tool,observe,current_url,navigate_group,root,job,result,report):
    from desktop import parse_targets,verify_live_target
    found=[]
    display_status='pending' if result.get('state')=='pending' or job.get('state')=='pending' else ''
    async def finish(receipt,status):
        # Scanning the other filters must not leave their empty view in a
        # pending receipt. If restoration fails, omit the misleading photo.
        receipt['receipt_photo_allowed']=False
        if not status:return receipt
        try:
            if status_of(await current_url())!=status:
                target=filter_target(parse_targets(await observe(True)),status)
                if not target:return receipt
                verify_live_target(target,root)
                await tool('Click',{'loc':target['loc']})
                await asyncio.sleep(1)
            await observe(True)
            if status_of(await current_url())==status:
                receipt.update(receipt_photo_allowed=True,receipt_filter=status)
        except Exception:pass
        return receipt
    try:
        groups=[job['url']]
        if job.get('data_dir') and job.get('group_id'):
            import sqlite3
            from pathlib import Path
            database=Path(job['data_dir'])/'manager.sqlite3'
            if database.exists():
                with sqlite3.connect(database.as_uri()+'?mode=ro',uri=True) as connection:
                    groups.extend(r[0] for r in connection.execute('SELECT alias FROM group_aliases WHERE group_id=?',(job['group_id'],)))
        job={**job,'verification_groups':groups}
        def status_of(url):return next((page_status(url,g) for g in groups if page_status(url,g)),'')
        report('Mở menu nhóm → Nội dung của bạn để đối chiếu trạng thái bài')
        await navigate_group()
        targets=parse_targets(await observe(True));target=group_menu(targets)
        manage=[t for t in targets if t.get('role')=='link' and t.get('name') in {'quản lý bài viết','manage posts','gérer les publications'}]
        if len(manage)==1:
            verify_live_target(manage[0],root);await tool('Click',{'loc':manage[0]['loc']});await asyncio.sleep(2)
            target=None
        else:
            if not target:return await finish({'your_content_checked':False,'your_content_detail':'Chưa xác định được menu nhóm duy nhất.'},display_status)
            verify_live_target(target,root);await tool('Click',{'loc':target['loc']})
            target=content_menu(parse_targets(await observe(True)))
            if not target:return await finish({'your_content_checked':False,'your_content_detail':'Facebook chưa hiện mục Nội dung của bạn.'},display_status)
            verify_live_target(target,root);await tool('Click',{'loc':target['loc']});await asyncio.sleep(2)
        # Facebook can replace the group's public slug with its numeric ID
        # only after opening Your content. Bind that observed destination to
        # this navigation, rather than treating all numeric groups as aliases.
        destination=await current_url()
        if not status_of(destination):
            canonical=observed_content_group(destination,parse_targets(await observe(True)),job)
            if canonical and canonical not in groups:groups.append(canonical)
        for status in ('pending','submitted','declined','removed'):
            snapshot=await observe(True);targets=parse_targets(snapshot)
            if status_of(await current_url())!=status:
                target=filter_target(targets,status)
                if not target:continue
                verify_live_target(target,root);await tool('Click',{'loc':target['loc']});await asyncio.sleep(2)
            if status_of(await current_url())!=status:continue
            rows=read_matches(root,job,status)
            if len(rows)==1 and rows[0].get('expand'):
                target=rows[0]['expand'];verify_live_target(target,root);await tool('Click',{'loc':target['loc']});await observe(True)
                rows=read_matches(root,job,status)
            found.extend(m for m in rows if 'expand' not in m)
        expected=next((post_url(result.get('post_url',''),g) for g in groups if post_url(result.get('post_url',''),g)),'')
        match=choose_match(found,expected)
        if not match:return await finish({'your_content_checked':True,'your_content_detail':'Chưa tìm được duy nhất bài mới khớp đầy đủ nội dung trong Nội dung của bạn.'},display_status)
        status=match['state'];details={'pending':'Đã đối chiếu đúng bài trong Nội dung của bạn → Đang chờ duyệt.','submitted':'Đã đối chiếu đúng bài trong Nội dung của bạn → Đã đăng.','declined':'Facebook hiển thị đúng bài trong Nội dung của bạn → Bị từ chối.','removed':'Cảnh báo: Facebook hiển thị đúng bài trong Nội dung của bạn → Đã gỡ. Không bình luận hoặc tự đăng lại.'}
        receipt={k:v for k,v in match.items() if k not in {'key','recent','state','post_url','post_menu','view_url','view_target'}}
        receipt.update(state='error' if status in {'declined','removed'} else status,detail=details[status],verification_source='your_content',your_content_checked=True,moderation_checked=True,moderation_status=status)
        if match.get('post_url'):receipt['post_url']=match['post_url']
        if status!='submitted' and result.get('comment_status') not in {'sent','fallback_sent','uncertain'}:receipt.update(comment_status='skipped',comment_detail='Không bình luận khi bài chưa được đăng.')
        return await finish(receipt,status)
    except Exception as exc:
        return await finish({'your_content_checked':False,'your_content_detail':'Chưa hoàn tất kiểm tra Nội dung của bạn: '+str(exc)[:180]},display_status)
