"""Bounded controls belonging to the exact newly submitted post; no input here."""
import re,time,unicodedata
from facebook_labels import POST_MENUS, COMMENTS, REPLIES, EXPAND, RECENT

def clean(text):
 from desktop import normalized
 return normalized(''.join(c for c in str(text) if c!='\u034f'))

def feed_posts(root,group):
 """Read visible post cards in visual order; no navigation or input."""
 import comtypes,windows_mcp.uia as uia,hashlib
 from uia_snapshot import capture,subtree
 from receipts import post_url
 comtypes.CoInitialize()
 try:
  entries,complete=capture(uia.ControlFromHandle(root),10000,10)
  if not complete:return []
  cards=[]
  for menu,path in entries:
   try:
    if menu.ControlTypeName!='ButtonControl' or menu.IsOffscreen or not any(s in clean(menu.Name) for s in POST_MENUS):continue
    candidate=None
    for parent in reversed(path):
     nodes=list(subtree(entries,parent));menus=[];timestamps=[];texts=[];has_editor=False;header_end=None
     for node,ancestors in nodes:
      role=node.ControlTypeName;name=clean(node.Name)
      if role=='EditControl' and any(s in name for s in COMMENTS):has_editor=True
      if role=='ButtonControl' and any(s in name for s in POST_MENUS):
       menus.append(node)
       if header_end is None:header_end=len(timestamps)
      if role=='HyperlinkControl' and (name in RECENT or re.search(r'\b(?:phút|giờ|minutes?|hours?|heures?)\b',name) or re.fullmatch(r'\d+\s*(?:min|h)',name)):
       pattern=node.GetLegacyIAccessiblePattern();value=pattern.Value if pattern else ''
       if 'comment_id' not in value:timestamps.append((name,post_url(value,group)))
      if role in {'TextControl','HyperlinkControl'} and name and not any(a.ControlTypeName=='EditControl' or getattr(a,'AriaRole','')=='textbox' for a in ancestors):texts.append(name)
     if header_end is not None:timestamps=timestamps[:header_end]
     if len(menus)>1:break
     if len(menus)==1 and len(timestamps)==1:
      names=[t for t in texts if t!=timestamps[0][0]]
      if not names:continue
      body=' '.join(names)
      key=timestamps[0][1] or hashlib.sha256((clean(menu.Name)+'|'+body).encode()).hexdigest()
      candidate={'key':key,'url':timestamps[0][1],'text':body,'top':menu.BoundingRectangle.top}
      if has_editor:break
    if candidate:cards.append(candidate)
   except Exception:continue
  unique={}
  for card in sorted(cards,key=lambda c:c['top']):unique.setdefault(card['key'],card)
  return list(unique.values())
 finally:comtypes.CoUninitialize()

def own_post_context(root,caption):
 import comtypes,windows_mcp.uia as uia
 comtypes.CoInitialize()
 try:
  from uia_snapshot import capture,subtree
  tree_entries,complete=capture(uia.ControlFromHandle(root),10000,10)
  if not complete:return {}
  def walk(node,path=()):return subtree(tree_entries,node)
  # Ordinary public comment editors omit the account name. Read it only
  # from the profile link beside the real new-post composer in this observation.
  from facebook_labels import COMPOSER
  composers=[];profiles=[]
  for item,ancestry in tree_entries:
   try:
    name=clean(item.Name);r=item.BoundingRectangle
    if item.ControlTypeName=='ButtonControl' and any(name.startswith(label) for label in COMPOSER):composers.append(((r.left+r.right)//2,(r.top+r.bottom)//2))
    if item.ControlTypeName=='HyperlinkControl' and name.startswith('trang cá nhân của '):profiles.append((name[len('trang cá nhân của '):],(r.left+r.right)//2,(r.top+r.bottom)//2))
   except Exception:pass
  account_names={name for name,x,y in profiles if any(abs(y-cy)<45 and 0<cx-x<500 for cx,cy in composers)}
  current_profile=next(iter(account_names)) if len(account_names)==1 else ''
  prefix=clean(caption.splitlines()[0])[:55]
  if len(prefix)<15:return {}
  matches=[]
  for node,path in tree_entries:
   try:
    if node.ControlTypeName=='TextControl' and prefix in clean(node.Name) and not any(p.ControlTypeName=='EditControl' or getattr(p,'AriaRole','')=='textbox' for p in path):matches.append((node,path))
   except Exception:pass
  contexts=[]
  for node,path in matches:
   candidate=None
   for parent in reversed(path):
    entries=list(walk(parent));times=[];editors=[];expand=[];menu=False;names=[];outside=[];buttons=[];actors=[];menus=[];header_end=None
    for item,ancestry in entries:
     try:
      name=item.Name;role=item.ControlTypeName;n=clean(name);names.append(n)
      if role in {'TextControl','HyperlinkControl'} and not any(a.ControlTypeName=='EditControl' or a.AriaRole=='textbox' for a in ancestry):outside.append(n)
      if role=='ButtonControl' and any(x in n for x in POST_MENUS):
       menu=True
       if header_end is None:header_end=len(times)
      if role=='ButtonControl':
       author=re.match(r'(?:hành động đối với bài viết(?: này)? của |actions for this post by |actions pour cette publication de )(.+)',n)
       if author:actors.append(author[1])
      r=item.BoundingRectangle
      visible=r.right>r.left and r.bottom>r.top and not item.IsOffscreen
      target={'id':0,'loc':[(r.left+r.right)//2,(r.top+r.bottom)//2],'role':{'HyperlinkControl':'link','EditControl':'edit','ButtonControl':'button'}.get(role,''),'name':__import__('desktop').normalized(name),'text':role.removesuffix('Control').lower()+' "'+name+'"'}
      if role=='EditControl':
       try:target['enabled']=bool(item.IsEnabled)
       except Exception:target['enabled']=False
       try:target['draft_text']=item.GetValuePattern().Value
       except Exception:
        try:target['draft_text']=item.GetTextPattern().DocumentRange.GetText(-1)
        except Exception:target['draft_text']=''
      if role=='HyperlinkControl' and (n in RECENT or re.search(r'\b(?:phút|giờ|minutes?|hours?|heures?)\b',n) or re.fullmatch(r'\d+\s*(?:min|h)',n)):
       pattern=item.GetLegacyIAccessiblePattern();href=pattern.Value if pattern else ''
       if 'comment_id' not in href:
        target['url']=href;times.append(target)
      if role=='EditControl' and visible and any(x in n for x in COMMENTS) and not any(x in n for x in REPLIES):editors.append(target)
      if role=='ButtonControl' and visible and n in EXPAND:expand.append(target)
      if role=='ButtonControl' and visible:buttons.append(target)
      if role=='ButtonControl' and any(x in n for x in POST_MENUS):
       menu=True
       if visible:menus.append(target)
     except Exception:continue
    if header_end is not None:times=times[:header_end]
    if menu and len(times)==1:
     identity_controls=[]
     if len(editors)==1:
      x,y=editors[0]['loc']
      identity_controls=[b for b in buttons if abs(b['loc'][1]-y)<65 and abs(b['loc'][0]-x)<500]
     full=clean(caption) in clean(' '.join(outside))
     candidate={'post_menu':menus[0] if len(menus)==1 else None,'timestamp':times[0],'editors':editors,'expand':expand,'caption_seen':full,'outside_texts':outside,'identity_controls':identity_controls,'post_actor':actors[0] if len(set(actors))==1 else '', 'current_profile_actor':current_profile}
     if len(editors)==1:break
   if candidate:contexts.append(candidate)
  # Duplicated copies of the same accessibility element are harmless; distinct
  # matching posts are ambiguous, so stop instead of commenting on another post.
  complete=[c for c in contexts if c['caption_seen']]
  unique={tuple(c['timestamp']['loc']):c for c in (complete or contexts)}
  return next(iter(unique.values())) if len(unique)==1 else {}
 finally:comtypes.CoUninitialize()
