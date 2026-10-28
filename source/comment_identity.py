"""Choose and verify comment identity independently of the post's identity."""
import re
from post_context import clean

ANONYMOUS=('người tham gia ẩn danh','thành viên ẩn danh','anonymous participant','anonymous member','participant anonyme','participante anonyme','membre anonyme')
PREFIXES=('bình luận dưới tên','comment as','commenter en tant que','écrire un commentaire en tant que')
PROFILE=('trang cá nhân chính','trang cá nhân của bạn','your main profile','main profile','your profile','profil principal','votre profil principal','votre profil')
CHOOSERS=('chọn danh tính','chọn cách tham gia','chọn cách bạn tương tác','tương tác với tư cách','chuyển sang trang hoặc trang cá nhân khác','choose how to participate','choose your profile','switch profile','commenting as','interact as','chọn trang cá nhân','choisir comment participer','choisir votre profil','changer de profil')
AVATAR=('ảnh đại diện','profile picture','photo de profil')
IDENTITY_MENUS=('trang & trang cá nhân của bạn','your pages and profiles')

def validate(mode,nickname=''):
    if mode not in {'follow','hidden','profile'}:raise ValueError('Chọn danh tính bình luận: theo bài, ẩn danh/biệt danh hoặc hồ sơ thường.')
    nickname=str(nickname).strip()
    if len(nickname)>80 or any(ord(c)<32 for c in nickname):raise ValueError('Biệt danh bình luận tối đa 80 ký tự, không xuống dòng.')
    return mode,nickname

def desired(job):
    mode,nickname=validate(job.get('comment_identity','follow'),job.get('comment_nickname',''))
    posting=job.get('posting_identity_effective',job.get('posting_identity','default'))
    if mode=='profile':return 'profile',''
    if mode=='hidden':return ('nickname',clean(nickname)) if nickname else ('anonymous','')
    if job.get('comment_expected_actor'):return 'actor',clean(job['comment_expected_actor'])
    if posting=='nickname':return 'nickname',clean(job.get('posting_nickname',''))
    if posting in {'anonymous','auto'}:return 'anonymous',''
    return 'current',''

def actor(editor):
    name=clean(editor.get('name',''))
    for prefix in PREFIXES:
        if name.startswith(prefix):return name[len(prefix):].strip(' .…:')
    return ''

PUBLIC_EDITORS={'viết bình luận công khai…','viết bình luận công khai...','write a public comment…','write a public comment...','write a comment','écrire un commentaire public…'}

def verified(job,editor,profile_name=''):
    mode,name=desired(job);who=actor(editor)
    # Set only from fresh composer/profile evidence by finish_post, never from
    # the post's author alone. Explicit anonymous/nickname editor labels win.
    if not who and editor.get('profile_verified') is True and clean(editor.get('name','')) in PUBLIC_EDITORS:
        who=clean(editor.get('profile_actor',''))
        if mode=='profile':profile_name=who
    if mode=='current':return True
    if not who:return False
    if mode=='anonymous':return who in ANONYMOUS
    if mode in {'nickname','actor'}:return bool(name) and who==name
    return bool(profile_name) and who==clean(profile_name) and who not in ANONYMOUS

def selector(context):
    editors=context.get('editors',[])
    if len(editors)!=1:return None
    who=actor(editors[0])
    x,y=editors[0]['loc']
    found=[t for t in context.get('identity_controls',[]) if t.get('role')=='button' and (any(s in t.get('name','') for s in CHOOSERS+PREFIXES) or (who and t.get('name')==who) or (t.get('name') in AVATAR and t['loc'][0]<x and abs(t['loc'][1]-y)<30))]
    found=list({(tuple(t['loc']),t['name']):t for t in found}.values())
    return found[0] if len(found)==1 else None

def option(job,targets):
    mode,nickname=desired(job)
    candidates=[]
    for t in targets:
        if t.get('role') not in {'button','radio button','radiobutton','menu item','menuitem'} or not t.get('identity_menu'):continue
        name=t.get('name','');description=t.get('description',name)
        if mode=='anonymous' and name in ANONYMOUS:candidates.append(t)
        elif mode in {'nickname','actor'} and (name==nickname or (mode=='actor' and clean(t.get('profile_name',''))==nickname)):candidates.append(t)
        elif mode=='profile' and (any(s in description for s in PROFILE) or (job.get('comment_profile_name') and clean(t.get('profile_name',''))==clean(job['comment_profile_name']))):candidates.append(t)
    if mode=='profile' and job.get('comment_profile_name'):
        candidates=[t for t in candidates if clean(t.get('profile_name',''))==clean(job['comment_profile_name'])]
    return candidates[0] if len(candidates)==1 else None

def menu(root):
    """Read only a visible identity-choice dialog/menu, never options in the feed."""
    import comtypes,time,windows_mcp.uia as uia
    comtypes.CoInitialize()
    try:
        stack=[(uia.ControlFromHandle(root),False)];found=[];deadline=time.monotonic()+5;budget=1500
        while stack and budget>0 and time.monotonic()<deadline:
            node,scope=stack.pop();budget-=1
            try:
                name=clean(node.Name);scope=scope or (node.ControlTypeName in {'WindowControl','GroupControl','MenuControl'} and len(name)<160 and any(name.startswith(s) for s in CHOOSERS+IDENTITY_MENUS))
                children=node.GetChildren();r=node.BoundingRectangle
                role={'ButtonControl':'button','RadioButtonControl':'radio button','MenuItemControl':'menu item'}.get(node.ControlTypeName)
                if scope and role and not node.IsOffscreen and r.right>r.left and r.bottom>r.top:
                    texts=[name]+[clean(ch.Name) for ch in children]
                    profile_name=name
                    for phrase in PROFILE:profile_name=profile_name.replace(phrase,'')
                    profile_name=re.split(r',\s*\d+\s*(?:thông báo|notifications?)(?:,|$)',profile_name)[0]
                    profile_name=re.sub(r',\s*(?:đang chọn|selected)$','',profile_name)
                    found.append({'id':len(found),'name':name,'profile_name':profile_name.strip(' .…:,-'),'role':role,'description':' '.join(texts),'identity_menu':True,'loc':[(r.left+r.right)//2,(r.top+r.bottom)//2],'text':role+' "'+node.Name+'"'})
                stack.extend((ch,scope) for ch in children)
            except Exception:continue
        return found
    finally:comtypes.CoUninitialize()
