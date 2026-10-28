"""Bounded group membership preflight and newest-first feed selection."""
SHARE={'chia sẻ nhóm','share group','partager le groupe'}
JOIN={'tham gia nhóm','join group','rejoindre le groupe'}
JOINED={'đã tham gia','joined','membre'}
REQUESTED={'hủy yêu cầu','cancel request','annuler la demande'}
NEWEST={'bài viết mới','bài viết mới nhất','mới nhất','new posts','most recent','nouvelles publications','publications récentes'}
SORT_PREFIX=('sắp xếp bảng feed nhóm theo ','sort group feed by ','trier le fil du groupe par ')

def membership(targets):
 shares=[t for t in targets if t.get('role')=='button' and t.get('name') in SHARE]
 if len(shares)!=1:return 'unknown'
 x,y=shares[0]['loc']
 candidates=[t for t in targets if t.get('role')=='button' and t.get('name') in JOIN|JOINED|REQUESTED and 0<x-t['loc'][0]<650 and abs(t['loc'][1]-y)<80]
 if len(candidates)!=1:return 'unknown'
 name=candidates[0]['name']
 return 'not_joined' if name in JOIN else 'requested' if name in REQUESTED else 'joined'

async def newest_first(tool,observe,snapshot,root,report):
 from desktop import parse_targets,verify_live_target
 controls=[t for t in parse_targets(snapshot) if t.get('role')=='button' and any(t.get('name','').startswith(p) for p in SORT_PREFIX)]
 if len(controls)!=1:return snapshot,False
 target=controls[0]
 if any(target['name'].endswith(name) for name in NEWEST):return snapshot,True
 verify_live_target(target,root)
 report('Đổi bảng tin nhóm sang Bài viết mới để tìm đúng bài vừa gửi')
 await tool('Click',{'loc':target['loc']})
 menu=await observe(True)
 choices=[t for t in parse_targets(menu) if t.get('role') in {'menuitem','menu item','radio button','radiobutton','menu item radio button','menuitemradio','button'} and (t.get('name') in NEWEST or t.get('role') in {'menuitem','menu item','radio button','radiobutton','menu item radio button','menuitemradio'} and any(t.get('name','').startswith(name+' ') for name in NEWEST))]
 if len(choices)!=1:
  await tool('Shortcut',{'shortcut':'esc'})
  return await observe(True),False
 verify_live_target(choices[0],root)
 await tool('Click',{'loc':choices[0]['loc']})
 return await observe(True),True
