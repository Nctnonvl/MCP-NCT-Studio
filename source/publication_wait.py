"""Wait for Facebook media and submit feedback; never click or submit here."""
import asyncio,re,time
from pathlib import Path
from facebook_labels import EDITORS,caption_editor_allowed,POST

BUSY=('đang tải lên','đang tải video','đang xử lý','đang được xử lý','đang đăng','đang gửi bài',
      'uploading','processing video','processing your video','publishing',
      'importation en cours','traitement de la vidéo','publication en cours')

def busy_text(text,caption=''):
    from desktop import normalized
    body=normalized(caption)
    return any(term in normalized(line) and term not in body
               for line in text.splitlines() for term in BUSY)

def read_surface(root):
    """Visible UIA feedback includes toasts omitted by MCP's DOM snapshot."""
    import comtypes,windows_mcp.uia as uia
    from desktop import normalized,foreground
    from posting_identity import SUBMIT
    from uia_snapshot import capture,subtree
    foreground(root);comtypes.CoInitialize()
    try:
        entries,complete=capture(uia.ControlFromHandle(root),10000,8)
        visible=[];dialogs=[]
        for node,path in entries:
            try:
                if node.IsOffscreen:continue
                role=node.ControlTypeName;name=str(node.Name or '')
                if role=='TextControl' or getattr(node,'AriaRole','') in {'alert','status'}:
                    visible.append(name)
                if role=='EditControl' and caption_editor_allowed('edit',normalized(name)) and any(normalized(name).startswith(x) for x in EDITORS):
                    scope=next((p for p in reversed(path) if getattr(p,'AriaRole','')=='dialog' or p.ControlTypeName=='WindowControl'),None)
                    if scope is not None:dialogs.append(scope)
            except Exception:continue
        enabled=False;progress=False;composer_text=[]
        for dialog in dialogs:
            for node,path in subtree(entries,dialog):
                try:
                    if node.IsOffscreen:continue
                    name=normalized(node.Name);role=node.ControlTypeName
                    if role=='TextControl':composer_text.append(str(node.Name))
                    if role=='ProgressBarControl':progress=True
                    if role=='ButtonControl' and name in set(POST)|set(SUBMIT):enabled=bool(node.IsEnabled)
                except Exception:continue
        return {'complete':complete,'composer':bool(dialogs),'enabled':enabled,
                'busy':progress or busy_text('\n'.join(composer_text)),
                'notices':'\n'.join(dict.fromkeys(visible))}
    finally:comtypes.CoUninitialize()

async def wait_video_ready(observe,root,job,report,timeout=480):
    start=time.monotonic();stable=0
    while time.monotonic()-start<timeout:
        snapshot=await observe(True)
        surface=await asyncio.to_thread(read_surface,root)
        from video_fallback import rejection
        failure=rejection(snapshot+'\n'+surface['notices'],job['body'])
        if failure:raise RuntimeError('Facebook từ chối video trước khi gửi: '+failure)
        ready=surface['complete'] and surface['composer'] and surface['enabled'] and not surface['busy'] and not busy_text(snapshot,job['body'])
        stable=stable+1 if ready else 0
        if stable>=2:return
        report('Chờ video tải và xử lý xong; chưa bấm Đăng · '+str(int(time.monotonic()-start))+' giây')
        await asyncio.sleep(3)
    raise RuntimeError('Video chưa tải/xử lý xong trong 8 phút; chưa bấm Đăng.')

async def wait_submission(observe,root,job,before,report,video=False,timeout=180):
    from desktop import valid_pending_receipt
    start=time.monotonic();quiet=0;collected=[]
    while time.monotonic()-start<timeout:
        snapshot=await observe(True)
        surface=await asyncio.to_thread(read_surface,root)
        combined=snapshot+'\n'+surface['notices']
        collected.append(combined)
        if job.get('data_dir') and job.get('id'):
            (Path(job['data_dir'])/'work'/f"submit-feedback-{job['id']}.txt").write_text('\n\n'.join(collected),encoding='utf-8')
        pending=next((line.strip() for line in combined.splitlines() if valid_pending_receipt(line,before,job['body'])),None)
        if pending:
            job['submit_pending_receipt']=pending
            report('Facebook báo bài vừa gửi đang chờ duyệt; chưa bình luận')
            return
        busy=busy_text(combined,job['body'])
        quiet=quiet+1 if surface['complete'] and not surface['composer'] and not busy else 0
        if quiet>=2 and time.monotonic()-start >= (10 if video else 3):return
        report('Chờ Facebook xử lý video/bài vừa gửi; giữ nguyên trang để đọc thông báo')
        await asyncio.sleep(3)
    # Never refresh away from an unfinished send/processing surface.
    raise RuntimeError('Đã bấm Đăng một lần nhưng Facebook chưa hoàn tất xử lý sau 3 phút; cần kiểm tra, không gửi lại.')
