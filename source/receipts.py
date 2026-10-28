"""Read-only receipt extraction from Edge accessibility; never infer a permalink."""
import re,time
from urllib.parse import urlsplit
from facebook_labels import POST_MENUS

def post_url(value, group):
    try:
        p=urlsplit(value);g=urlsplit(group)
        if p.scheme!='https' or p.hostname not in {'www.facebook.com','facebook.com','m.facebook.com'} or p.port not in {None,443} or p.username or p.password:return ''
        match=re.fullmatch(r'/groups/([^/]+)/(?:posts|permalink)/(\d+)/?',p.path)
        if not match or match[1]!=g.path.strip('/').split('/')[1]:return ''
        return 'https://www.facebook.com/groups/'+match[1]+'/posts/'+match[2]+'/'
    except (ValueError,IndexError,TypeError):return ''

def read_post_receipt(root, caption, group):
    import comtypes
    import windows_mcp.uia as uia
    from desktop import normalized
    comtypes.CoInitialize()
    try:
        from uia_snapshot import capture,subtree
        entries,complete=capture(uia.ControlFromHandle(root),15000,10)
        if not complete:return {}
        scopes=[]
        caption_text=normalized(caption)
        prefix=normalized(caption.splitlines()[0])[:55]
        if not prefix:return {}
        for node,path in entries:
            try:
                if node.ControlTypeName!='TextControl' or prefix not in normalized(node.Name):continue
                if any(getattr(p,'ControlTypeName','')=='EditControl' for p in path):continue
                for parent in reversed(path):
                    if parent not in scopes:scopes.append(parent)
            except Exception:continue
        found=set()
        for scope in scopes:
            nodes=list(subtree(entries,scope))
            names=[];links=[];menus=0
            for node,path in nodes:
                try:
                    if any(getattr(p,'ControlTypeName','')=='EditControl' for p in path):continue
                    role=node.ControlTypeName;name=normalized(node.Name)
                    if role in {'TextControl','HyperlinkControl'}:names.append(name)
                    if role=='ButtonControl' and any(x in name for x in POST_MENUS):menus+=1
                    if role=='HyperlinkControl':
                        pattern=node.GetLegacyIAccessiblePattern()
                        url=post_url(pattern.Value if pattern else '',group)
                        if url:links.append(url)
                except Exception:continue
            article=getattr(scope,'AriaRole','')=='article'
            if (article or menus==1) and (caption_text in names or caption_text in normalized(' '.join(names))):
                if len(set(links))==1:found.update(links)
        if len(found)==1:return {'post_url':found.pop(),'evidence':caption}
        return {}
    finally:comtypes.CoUninitialize()


def has_verified_post(result, group):
    """Only a deterministic full-caption receipt can bypass fallback navigation."""
    if result.get('state')!='submitted' or result.get('receipt_verified') is not True:return False
    source=result.get('verification_source')
    link=result.get('post_url','')
    if link and not post_url(link,group):return False
    return source=='group_feed' or bool(link and source in {'post_permalink','post_receipt','your_content'})
