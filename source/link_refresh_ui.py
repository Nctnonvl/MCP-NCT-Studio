"""Edit only a fully matched own post, then send one separately journaled comment."""
import asyncio
import time
from pathlib import Path
from post_context import clean

EDIT = {'chỉnh sửa bài viết','edit post','modifier la publication'}
SAVE = {'lưu','save','enregistrer'}
EDIT_DIALOG = {'chỉnh sửa bài viết','edit post','modifier la publication'}


def edit_controls(root):
    import comtypes, windows_mcp.uia as uia
    comtypes.CoInitialize()
    try:
        deadline=time.monotonic()+6;budget=[8000]
        def walk(node):
            if budget[0]<=0 or time.monotonic()>deadline:return
            budget[0]-=1;yield node
            try:children=node.GetChildren()
            except Exception:return
            for ch in children:yield from walk(ch)
        dialogs=[]
        for n in walk(uia.ControlFromHandle(root)):
            try:
                if (getattr(n,'AriaRole','')=='dialog' or n.ControlTypeName in {'PaneControl','GroupControl'}) and clean(n.Name) in EDIT_DIALOG:dialogs.append(n)
            except Exception:pass
        found=[]
        for dialog in dialogs:
            editors=[];saves=[]
            for n in walk(dialog):
                try:
                    r=n.BoundingRectangle
                    if n.IsOffscreen or not n.IsEnabled or r.right<=r.left or r.bottom<=r.top:continue
                    target={'id':0,'loc':[(r.left+r.right)//2,(r.top+r.bottom)//2],'role':'edit' if n.ControlTypeName=='EditControl' else 'button','name':clean(n.Name),'text':n.Name}
                    if n.ControlTypeName=='EditControl' and not any(x in clean(n.Name) for x in ('bình luận','comment','commentaire','tìm kiếm','search','rechercher')):
                        try:target['value']=n.GetValuePattern().Value
                        except Exception:
                            try:target['value']=n.GetTextPattern().DocumentRange.GetText(-1)
                            except Exception:continue
                        editors.append(target)
                    if n.ControlTypeName=='ButtonControl' and clean(n.Name) in SAVE:saves.append(target)
                except Exception:continue
            if len(editors)==1 and len(saves)==1:found.append({'editor':editors[0],'save':saves[0]})
        unique={tuple(f['editor']['loc']):f for f in found}
        return next(iter(unique.values())) if len(unique)==1 else {}
    finally:comtypes.CoUninitialize()


async def execute(tool,observe,current_url,navigate_group,root,job,report):
    from desktop import parse_targets,verify_live_target
    from store import Store
    from link_refresh import checkpoint
    from receipts import post_url
    from post_context import own_post_context
    from own_content import ANONYMOUS
    store=Store(Path(job['data_dir'])/'manager.sqlite3');rid=job['refresh_id']
    groups=[job['url'],*[r['alias'] for r in store.rows('SELECT alias FROM group_aliases WHERE group_id=?',(job.get('group_id',0),))]]
    expected=next((post_url(job['post_url'],g) for g in groups if post_url(job['post_url'],g)), '')
    if not expected:raise RuntimeError('Không có link bài hợp lệ trong nhóm đã chọn.')
    result={'state':'skipped','post_url':expected,'comment_status':'skipped','detail':'Chưa cập nhật Facebook.'}
    async def click(t):
        verify_live_target(t,root);await tool('Click',{'loc':t['loc']})
    async def location_matches():
        current=await current_url()
        return any(post_url(current,g)==expected for g in groups)
    async def navigate_post():
        import own_content
        location=await current_url()
        if any(own_content.page_status(location,g)=='submitted' for g in groups):
            cards=own_content.read_matches(root,{**job,'verification_groups':groups},'submitted')
            match=own_content.choose_match(cards,expected)
            view=match.get('view_target') if match else None
            if view and any(own_content.card_post_url(view.get('url',''),g)==expected for g in groups):
                report('Bấm Xem trong nhóm của đúng bài đã đối chiếu')
                await click(view);await asyncio.sleep(3)
        report('Mở thẳng link bài đã đăng; không lướt hoặc tìm trong nhóm')
        if not await location_matches():
            import pyperclip
            previous=pyperclip.paste()
            try:
                pyperclip.copy(expected)
                await tool('Shortcut',{'shortcut':'ctrl+l'})
                await tool('Shortcut',{'shortcut':'ctrl+v'})
                await tool('Shortcut',{'shortcut':'enter'})
            finally:pyperclip.copy(previous)
            await asyncio.sleep(4)
        if not await location_matches():raise RuntimeError('Không mở được đúng link bài đã đăng; bỏ qua bài này.')
    async def context_for(caption):
        await observe(True)
        if not await location_matches():return {}
        ctx=await asyncio.to_thread(own_post_context,root,caption)
        if ctx.get('caption_seen') is False and len(ctx.get('expand',[]))==1:
            await click(ctx['expand'][0]);await observe(True)
            ctx=await asyncio.to_thread(own_post_context,root,caption)
        return ctx if ctx.get('caption_seen') is True else {}
    await navigate_post()
    context=await context_for(job['body'])
    if not context:
        return {**result,'detail':'Không đọc được đúng bài đã đăng tại link đã lưu. Bỏ qua, không lướt tìm.'}
    actor=context.get('post_actor','')
    result.update(post_actor=actor,post_identity='anonymous' if clean(actor) in ANONYMOUS else 'named' if actor else '',post_identity_verified=bool(actor))
    if job['body_after']!=job['body']:
        target=context.get('post_menu')
        if not target:return {**result,'detail':'Không có menu riêng của đúng bài. Bỏ qua, không lướt tìm.'}
        await click(target)
        choices=[t for t in parse_targets(await observe(True)) if t['role'] in {'button','menu item','menuitem'} and t['name'] in EDIT]
        if len(choices)!=1:
            checkpoint(store,rid,edit_state='unavailable')
            return {**result,'detail':'Facebook không hiện Chỉnh sửa bài viết cho bài này. Bỏ qua để xử lý bài tiếp theo.'}
        await click(choices[0]);await observe(True)
        controls=await asyncio.to_thread(edit_controls,root)
        if not controls or clean(controls['editor']['value'])!=clean(job['body']):raise RuntimeError('Nội dung ô chỉnh sửa không khớp đầy đủ bài nguồn; chưa nhập hoặc lưu.')
        if job.get('mode')=='prepare':
            return {**result,'state':'prepared','detail':'Đã mở đúng Chỉnh sửa bài viết và đối chiếu đầy đủ nội dung. Chưa nhập, lưu hoặc bình luận.'}
        target=controls['editor'];verify_live_target(target,root)
        await tool('Type',{'loc':target['loc'],'text':job['body_after'],'clear':True,'press_enter':False})
        await observe(True)
        controls=await asyncio.to_thread(edit_controls,root)
        if not controls or clean(controls['editor']['value'])!=clean(job['body_after']):raise RuntimeError('Chưa xác nhận nội dung mới trong ô sửa; không bấm Lưu.')
        checkpoint(store,rid,edit_state='uncertain')
        await click(controls['save']);await asyncio.sleep(4)
        context=await context_for(job['body_after'])
        if not context:
            return {**result,'state':'uncertain','detail':'Đã bấm Lưu nhưng chưa xác nhận nội dung mới; không tự sửa hoặc bình luận lại. Chuyển bài tiếp theo.'}
        checkpoint(store,rid,edit_state='saved')
    else:
        checkpoint(store,rid,edit_state='unchanged')
        if job.get('mode')=='prepare':return {**result,'state':'prepared','detail':'Đã đối chiếu bài. Nội dung không chứa link cũ; chưa bình luận.'}
    if job.get('comment_links')=='deny':
        checkpoint(store,rid,comment_state='skipped')
        return {**result,'state':'updated','detail':'Đã xử lý nội dung bài; bỏ bình luận vì nhóm được cấu hình cấm link bình luận.'}
    if len(context.get('editors',[]))!=1:
        checkpoint(store,rid,comment_state='failed')
        return {**result,'state':'updated','comment_status':'failed','detail':'Đã xử lý nội dung bài nhưng không có duy nhất ô bình luận. Chuyển bài tiếp theo, không lướt tìm.'}
    report('Gửi một bình luận link mới trên đúng bài đang mở')
    checkpoint(store,rid,comment_state='uncertain')
    comment_job={**job,'body':job['body_after'],'comment_text':job['new_url'],'comment_fallback':'','comment_policy':'allowed','comment_identity':'follow'}
    from post_comments import finish_post
    result=await finish_post(tool,observe,current_url,root,comment_job,result,True)
    checkpoint(store,rid,comment_state=result.get('comment_status','uncertain'))
    result.update(state='updated',detail='Đã đối chiếu cập nhật link trong bài. '+result.get('comment_detail','Chưa gửi bình luận.'))
    return result
