"""Bounded identity selection. No inference from feed text or unselected options."""
import unicodedata
import time

def clean(value):return ' '.join(unicodedata.normalize('NFC',str(value)).casefold().split())
ANON=('post anonymously','đăng ẩn danh','publier anonymement','publier de manière anonyme')
CONFIRM=('create anonymous post','tạo bài viết ẩn danh','créer une publication anonyme')
EDITORS=CONFIRM+('anonymous post','bài viết ẩn danh','publication anonyme')
CHOOSERS=('choose how to participate','chọn cách tham gia','choisir comment participer',
          'anonymous member','anonymous participant','thành viên ẩn danh','người tham gia ẩn danh',
          'membre anonyme','participant anonyme','participante anonyme')
SUBMIT=('submit','gửi','envoyer','soumettre')
CONSENT=('ok','đồng ý','got it','compris',"d’accord","d'accord")

def live_role_matches(node,role):
    actual=clean(node.ControlTypeName).removesuffix('control').replace(' ','')
    if actual==role.replace(' ',''):return True
    if role.replace(' ','') in {'menuitemradiobutton','menuitemradio'}:
        return actual in {'menuitem','radiobutton'}
    # MCP 0.8.8 exposes the ARIA switch; Windows UIA exposes Button + TogglePattern.
    if role=='switch' and actual=='button':
        try:return int(node.GetTogglePattern().ToggleState) in {0,1,2}
        except Exception:return False
    return False

def find_in_window(target,root):
    """Read the verified Edge's UIA subtree when MCP's input shield wins hit testing."""
    import windows_mcp.uia as uia
    pending=[(uia.ControlFromHandle(root),0)];found=[];budget=1200;deadline=time.monotonic()+4
    x,y=target['loc']
    while pending and budget>0 and time.monotonic()<deadline:
        node,depth=pending.pop();budget-=1
        try:
            r=node.BoundingRectangle
            if r.right>r.left and r.bottom>r.top and not (r.left<=x<r.right and r.top<=y<r.bottom):continue
            if clean(node.Name)==target['name'] and live_role_matches(node,target['role']) and r.left<=x<r.right and r.top<=y<r.bottom:
                found.append(node)
                if len(found)>1:return None
            if depth<45:pending.extend((child,depth+1) for child in node.GetChildren())
        except Exception:continue
    # Exhaust the bounded matching path; ambiguity or incomplete traversal fails closed.
    return found[0] if len(found)==1 and not pending else None

def validate(mode,nickname=''):
    if mode not in {'default','auto','anonymous','nickname'}:raise ValueError('Chọn Mặc định, Tự chọn, Ẩn danh hoặc Biệt danh.')
    nickname=str(nickname).strip()
    if mode=='nickname' and (not 1<=len(nickname)<=80 or any(ord(c)<32 for c in nickname)):
        raise ValueError('Nhập chính xác biệt danh đã thiết lập trên Facebook cho nhóm (1–80 ký tự).')
    return mode,nickname if mode=='nickname' else ''

def default_allowed(targets,seen=False,steps=0):
    """Auto may use a regular composer when anonymous posting is absent or explicitly disabled."""
    from facebook_labels import EDITORS as CAPTION_NAMES
    regular=any(t.get('role') in {'edit','textbox','text box'} and any(t.get('name','').startswith(n) for n in CAPTION_NAMES) and not any(s in t.get('name','') for s in ('ẩn danh','anonym')) for t in targets)
    if not regular:return False
    controls=[t for t in targets if t.get('name') in ANON+CONFIRM]
    if not controls:return not seen and steps==0
    return len(controls)==1 and controls[0].get('composer_scope') is True and controls[0].get('checked') is False and controls[0].get('identity_enabled') is False

def profile_fallback_decision(mode,targets,allowed=False,submitted=False):
    """Only switch before submission, with explicit evidence in this composer."""
    if not allowed or submitted or mode not in {'auto','anonymous'}:return {'verified':False}
    from facebook_labels import EDITORS as CAPTION_NAMES
    regular=[t for t in targets if t.get('role') in {'edit','textbox','text box'} and t.get('composer_scope') is True and not t.get('anonymous_composer_scope') and any(t.get('name','').startswith(n) for n in CAPTION_NAMES)]
    switches=[t for t in targets if t.get('name') in ANON and t.get('composer_scope') is True and type(t.get('checked')) is bool]
    if len(switches)==1:
        if switches[0]['checked'] is True:return {'verified':False,'target':switches[0]['id']}
        return {'verified':len(regular)==1}
    if switches or any(t.get('anonymous_composer_scope') or (t.get('composer_scope') and t.get('name') in CHOOSERS) for t in targets):return {'verified':False}
    return {'verified':len(regular)==1 and default_allowed(targets)}


def decision(mode,nickname,targets):
    """Return verified or one explicit identity click; never authorize publishing."""
    validate(mode,nickname)
    if mode=='default':return {'verified':True}
    nickname=clean(nickname)
    toggles=[t for t in targets if t.get('name') in ANON and (t.get('role') in {'checkbox','check box','switch','togglebutton','toggle button'} or (t.get('role')=='button' and type(t.get('checked')) is bool))]
    if mode in {'anonymous','auto'}:
        proof=[t for t in toggles if t.get('checked') is True and t.get('composer_scope')]
        if len(proof)==1:return {'verified':True}
        proof=[t for t in targets if t.get('role') in {'edit','textbox','text box'} and t.get('anonymous_composer_scope')]
        if len(proof)==1:return {'verified':True}
    else:
        proof=[t for t in targets if t.get('name')==nickname and t.get('composer_scope') and (t.get('role')=='button' or t.get('selected') is True)]
        if len(proof)==1:return {'verified':True}
        choices=[t for t in targets if t.get('name')==nickname and t.get('role') in {'radio button','radiobutton','menu item','menuitem'} and t.get('identity_scope')]
        if len(choices)==1 and choices[0].get('selected') is not True:return {'verified':False,'target':choices[0]['id']}
    switches=[t for t in toggles if t.get('checked') is False and t.get('composer_scope') and t.get('identity_enabled') is not False]
    if len(switches)==1:return {'verified':False,'target':switches[0]['id']}
    from facebook_labels import EDITORS as CAPTION_NAMES
    has_editor=any(t.get('role') in {'edit','textbox','text box'} and any(t.get('name','').startswith(n) for n in CAPTION_NAMES) for t in targets)
    buttons=[t for t in targets if not has_editor and t.get('role')=='button' and t.get('identity_enabled') is not False and t.get('name') in CONFIRM+ANON+CONSENT and (t.get('identity_scope') or t.get('composer_scope') or t.get('name') in ANON)]
    if len(buttons)==1:return {'verified':False,'target':buttons[0]['id']}
    if mode=='nickname':
        choosers=[t for t in targets if t.get('role')=='button' and t.get('name') in CHOOSERS and t.get('composer_scope')]
        if len(choosers)==1:return {'verified':False,'target':choosers[0]['id']}
    return {'verified':False}

def inspect(targets,nickname='',root=None):
    """Read UIA state and composer ancestry at fresh MCP coordinates; never click."""
    import comtypes
    import windows_mcp.uia as uia
    from facebook_labels import COMPOSER,EDITORS as CAPTION_NAMES
    comtypes.CoInitialize()
    try:
        for t in targets:
            if t.get('name') not in ANON+CONFIRM+CHOOSERS+SUBMIT+CONSENT+(clean(nickname),) and not (t.get('role') in {'edit','textbox','text box'} and any(t.get('name','').startswith(n) for n in CAPTION_NAMES)):continue
            try:
                node=uia.ControlFromPoint(*t['loc'])
                t['identity_live_role']=clean(node.ControlTypeName)
                if root and not (clean(node.Name)==t['name'] and live_role_matches(node,t['role'])):
                    node=find_in_window(t,root)
                    if node is None:continue
                # A text child is common inside author buttons.
                for _ in range(3):
                    if clean(node.Name)==t['name'] and live_role_matches(node,t['role']):break
                    if node.ControlTypeName not in {'TextControl','ImageControl'}:node=None;break
                    node=node.GetParentControl()
                if node is None:continue
                t['identity_enabled']=bool(node.IsEnabled)
                try:
                    state=int(node.GetTogglePattern().ToggleState)
                    t['checked']={0:False,1:True}.get(state)
                except Exception:pass
                try:t['selected']=bool(node.GetSelectionItemPattern().IsSelected)
                except Exception:pass
                parent=node.GetParentControl()
                for _ in range(14):
                    if parent is None:break
                    name=clean(parent.Name)
                    if name in EDITORS and parent.ControlTypeName=='WindowControl':t['anonymous_composer_scope']=True
                    if name in COMPOSER+EDITORS:
                        t['composer_scope']=True;t['identity_scope']=True;break
                    if name in CHOOSERS+('anonymous participation','participation anonyme','tham gia ẩn danh'):t['identity_scope']=True
                    if parent.ControlTypeName in {'WindowControl','DocumentControl'}:break
                    parent=parent.GetParentControl()
                if t.get('composer_scope') and t.get('role')=='button' and t.get('name') in SUBMIT:
                    t['anonymous_submit']=True
            except Exception as exc:
                t['identity_read_error']=type(exc).__name__
                continue
        # windows-mcp omits disabled interactive nodes. Facebook disables its
        # already-selected anonymous switch while loading a link preview.
        # Read its TogglePattern in the exact composer; never infer from color.
        has_editor=any(t.get('role') in {'edit','textbox','text box'} and any(t.get('name','').startswith(n) for n in CAPTION_NAMES) for t in targets)
        if root and has_editor and not any(t.get('name') in ANON and t.get('checked') is True and t.get('composer_scope') for t in targets):
            proof=native_anonymous_proof(root)
            if proof:targets.append({**proof,'id':len(targets)})
        return targets
    finally:comtypes.CoUninitialize()

def native_anonymous_proof(root):
    """Read a unique checked switch inside the bound new-post dialog only."""
    import windows_mcp.uia as uia
    from facebook_labels import COMPOSER
    from uia_snapshot import capture
    entries,complete=capture(uia.ControlFromHandle(root),10000,8)
    if not complete:return None
    found=[]
    for node,path in entries:
        try:
            if clean(node.Name) not in ANON or node.IsOffscreen:continue
            if node.ControlTypeName not in {'ButtonControl','CheckBoxControl'}:continue
            if int(node.GetTogglePattern().ToggleState)!=1:continue
            if not any(clean(p.Name) in COMPOSER+EDITORS and p.ControlTypeName not in {'DocumentControl','TextControl'} for p in path):continue
            r=node.BoundingRectangle
            if r.right<=r.left or r.bottom<=r.top:continue
            found.append({'name':clean(node.Name),'role':'button' if node.ControlTypeName=='ButtonControl' else 'checkbox','loc':[(r.left+r.right)//2,(r.top+r.bottom)//2],'text':'button "'+node.Name+'"','checked':True,'composer_scope':True,'identity_enabled':bool(node.IsEnabled),'identity_source':'native_toggle'})
        except Exception:continue
    return found[0] if len(found)==1 else None
