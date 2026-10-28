"""Window ownership journal lets the supervisor clean up even after a killed worker."""
import json,os,time
from pathlib import Path
import subprocess

def leave_button(root):
    """Only Edge's native before-unload dialog; never inspect webpage documents."""
    titles={'leave site?','rời khỏi trang web?','quitter le site ?','quitter la page ?'}
    labels={'leave','rời khỏi','quitter','quitter le site'}
    pending=[(root,False)];found=[];budget=500;deadline=time.monotonic()+3
    while pending and budget>0 and time.monotonic()<deadline:
        node,scope=pending.pop();budget-=1
        try:
            if node.ControlTypeName=='DocumentControl':continue
            name=' '.join(node.Name.casefold().split())
            scope=scope or (node.ControlTypeName=='WindowControl' and name in titles)
            if scope and node.ControlTypeName=='ButtonControl' and name in labels and node.IsEnabled:found.append(node)
            pending.extend((child,scope) for child in node.GetChildren())
        except Exception:continue
    return found[0] if len(found)==1 and not pending else None

def dismiss_leave(root,identity):
    from desktop import window_identity
    if window_identity(root)!=identity:return False
    import comtypes,windows_mcp.uia as uia
    comtypes.CoInitialize()
    try:
        button=leave_button(uia.ControlFromHandle(root))
        if button is None or window_identity(root)!=identity:return False
        button.GetInvokePattern().Invoke()
        return True
    finally:comtypes.CoUninitialize()

def stop_worker(process):
    """Stop the worker and its MCP server; Edge windows are closed by ownership, never a process-tree kill."""
    import psutil
    try:
        for child in psutil.Process(process.pid).children(recursive=True):
            try:
                if child.name().lower() in {'python.exe','pythonw.exe','python'} and 'windows_mcp' in child.cmdline():child.terminate()
            except psutil.Error:pass
    except psutil.Error:pass
    if process.poll() is None:
        process.terminate()
        try:process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill();process.wait(timeout=5)

def register(path,root,previous,identity,profile=None):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    value={'browser_profile':profile,'worker_pid':os.getpid(),'root':root,'previous':list(previous),'identity':list(identity),'closed':False,'created':time.time()}
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(value),encoding='utf-8');tmp.replace(path)

def finish(root,data,previous,identity,path=None):
    from desktop import close_operation_window
    closed=close_operation_window(root,data,previous,identity)
    if closed and path and Path(path).exists():
        p=Path(path);value=json.loads(p.read_text(encoding='utf-8'));value['closed']=True
        p.write_text(json.dumps(value),encoding='utf-8')
    return closed

def recover(path,data,worker_pid):
    if not path or not Path(path).exists():return False
    value=json.loads(Path(path).read_text(encoding='utf-8'))
    if value.get('worker_pid')!=worker_pid:return False
    if value.get('closed'):return True
    from desktop import _BROWSER_PROFILE
    token=_BROWSER_PROFILE.set(value.get('browser_profile'))
    try:return finish(value['root'],data,value['previous'],tuple(value['identity']),path)
    finally:_BROWSER_PROFILE.reset(token)
