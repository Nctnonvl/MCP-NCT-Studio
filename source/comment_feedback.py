"""Read Facebook's comment error dialog, without inferring failure from feed text."""
import time
from post_context import clean

TITLES={'đã xảy ra lỗi','something went wrong','an error occurred','une erreur s’est produite',"une erreur s'est produite"}
NOT_SENT=('không thể đăng bình luận','không gửi được bình luận',"couldn't post comment",'comment could not be posted','commentaire n’a pas pu être publié',"commentaire n'a pas pu être publié")
TEMPORARY=('chúng tôi gặp sự cố khi hoàn tất yêu cầu','trouble completing your request','something went wrong','đã xảy ra lỗi','une erreur s’est produite')
BLOCKED=('tạm thời bị chặn','bạn không thể bình luận','temporarily blocked',"you can't comment",'vous ne pouvez pas commenter','captcha')

def has_error(snapshot):return any(s in clean(snapshot) for s in NOT_SENT+TEMPORARY+BLOCKED)

def read_error(root):
    import comtypes,windows_mcp.uia as uia
    comtypes.CoInitialize()
    try:
        pending=[(uia.ControlFromHandle(root),False)];texts=[];buttons=[];budget=1800;deadline=time.monotonic()+3
        while pending and budget>0 and time.monotonic()<deadline:
            node,scope=pending.pop();budget-=1
            try:
                name=clean(node.Name)
                scope=scope or (node.ControlTypeName=='WindowControl' and name in TITLES)
                if scope and not node.IsOffscreen:
                    if node.ControlTypeName=='TextControl':texts.append(name)
                    if node.ControlTypeName=='ButtonControl' and name in {'ok','d’accord',"d'accord"}:
                        r=node.BoundingRectangle
                        if r.right>r.left and r.bottom>r.top:buttons.append({'name':name,'role':'button','loc':[(r.left+r.right)//2,(r.top+r.bottom)//2],'text':'button "'+node.Name+'"'})
                pending.extend((ch,scope) for ch in node.GetChildren())
            except Exception:continue
        message=' '.join(dict.fromkeys(texts))
        if not message:return None
        kind='blocked' if any(s in message for s in BLOCKED) else 'not_sent' if any(s in message for s in NOT_SENT) else 'temporary'
        return {'kind':kind,'message':message[:400],'dismiss':buttons[0] if len(buttons)==1 else None}
    except Exception:return None
    finally:comtypes.CoUninitialize()
