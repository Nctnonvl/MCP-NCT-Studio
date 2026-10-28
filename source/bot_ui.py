"""Telegram control cards and short guided workflows; no token handling here."""
import json,re,secrets,time
from pathlib import Path
import media_library
import group_metrics
import campaign_plan

STATUS={'draft':'Nháp · chưa duyệt','queued':'Đã duyệt · chờ chạy','working':'Đang xử lý','submitted':'Đã đăng','pending':'Chờ Facebook duyệt','uncertain':'Cần xác minh','error':'Chưa đăng / có lỗi','cancelled':'Đã hủy','prepared':'Đã soạn · chưa đăng'}
COMMENT={'none':'Không yêu cầu','off':'Đã tắt','blocked':'Nhóm không cho bình luận link','pending':'Đang chờ','not_requested':'Không yêu cầu','sent':'Đã gửi','submitted':'Đã gửi','fallback_sent':'Đã gửi dự phòng','failed':'Chưa gửi được','uncertain':'Chưa xác nhận','skipped':'Bỏ qua','':'Không yêu cầu'}
COMMANDS=[('menu','Mở bảng điều khiển'),('status','Trạng thái tool và AI'),('stats','Hiệu quả riêng từng nhóm'),('ai','Tạo chiến dịch AI từng bước'),('contents','Kho nội dung'),('groups','Danh sách nhóm'),('queue','Lịch đăng'),('reviews','Nhóm cần xem xét'),('history','Kết quả đăng gần đây'),('stopai','Dừng AI viết bài'),('pause','Tạm dừng và giữ lịch'),('run','Chạy lịch đã duyệt'),('help','Hướng dẫn sử dụng')]

def button(text,data=None,url=None):return {'text':text,**({'url':url} if url else {'callback_data':data})}
def back(screen='home'):return [button('‹ Quay lại','panel:'+screen+':0'),button('⌂ Menu','panel:home:0')]
def show(a,chat,title,body,rows,mid=None):return a.render_panel(chat,title+'\n━━━━━━━━━━━━━━━━\n'+body,{'inline_keyboard':rows},mid)
def pager(rows,screen,page,total,size=6):
 nav=[]
 if page:nav.append(button('‹ Trước',f'panel:{screen}:{page-1}'))
 if (page+1)*size<total:nav.append(button('Sau ›',f'panel:{screen}:{page+1}'))
 if nav:rows.append(nav)
 rows.append(back())
 return rows

def keyboard():
 return {'keyboard':[[{'text':'🏠 Menu'},{'text':'📊 Thống kê'}],[{'text':'📝 Nội dung'},{'text':'👥 Nhóm'}],[{'text':'📋 Lịch đăng'},{'text':'✨ Chiến dịch AI'}],[{'text':'⏸ Tạm dừng'},{'text':'▶ Chạy'}]],'resize_keyboard':True,'is_persistent':True,'input_field_placeholder':'Chọn chức năng hoặc gửi /menu'}

def panel(a,chat,screen='home',page=0,message_id=None):
 s=a.STORE;page=max(0,int(page));size=6
 if screen=='home':
  s.set('bot_wizard',None)
  counts={r['state']:r['n'] for r in s.rows('SELECT state,COUNT(*) n FROM jobs WHERE hidden=0 GROUP BY state')}
  groups=s.rows('SELECT COUNT(*) n,SUM(enabled) enabled FROM groups WHERE deleted=0')[0];task=s.get('studio_task',{});working=counts.get('working',0)
  body=('▶ Lịch đang chạy' if s.get('running') else '⏸ Lịch tạm dừng')+f"\nNhóm: {groups['enabled'] or 0}/{groups['n']} bật · Kho: {s.rows('SELECT COUNT(*) n FROM contents')[0]['n']} bài\nLịch chờ: {counts.get('queued',0)} · Nháp: {counts.get('draft',0)} · Đang xử lý: {working}\nChờ duyệt: {counts.get('pending',0)} · Cần xem: {counts.get('uncertain',0)+counts.get('error',0)}\n\nAI: "+('Đang tạo / viết lại bài' if task.get('status')=='running' else 'Đã dừng' if task.get('status')=='stopped' else 'Cần kiểm tra' if task.get('status')=='error' else 'Sẵn sàng')
  rows=[[button('✨ Chiến dịch AI','panel:ai:0'),button('📝 Bài viết','panel:posts:0')],[button('👥 Nhóm','panel:groups:0'),button('🗓 Lịch đăng','panel:queue:0')],[button('📊 Hiệu quả nhóm','panel:stats:0'),button('🔎 Cần xem xét','panel:reviews:0')],[button('📷 Kết quả','panel:history:0'),button('🔗 Thay link','tg:links:0')],[button('⏸ Tạm dừng','panel:pause:0'),button('▶ Chạy lịch','panel:run:0')],[button('Trạng thái','panel:status:0'),button('Hướng dẫn','panel:help:0')]]
  return show(a,chat,'NCT STUDIO · BẢNG ĐIỀU KHIỂN',body,rows,message_id)
 if screen in {'groups','posts','queue','drafts','pending','attention','history','reviews','stats','worst','statpending','watch'}:
  if screen in {'stats','worst','statpending'}:
   items=group_metrics.statistics(s)['30'];field='pending' if screen=='statpending' else 'success_rate';items.sort(key=lambda g:(g[field] is None, -(g[field] or 0) if screen!='worst' else (g[field] or 0),-g['total']));title='HIỆU QUẢ TỪNG NHÓM · 30 NGÀY'
  elif screen=='watch':items=s.group_watchlist();title='NHÓM VƯỢT 5 LƯỢT CẦN XEM'
  elif screen=='groups':items=s.rows('SELECT * FROM groups WHERE deleted=0 ORDER BY enabled DESC,id');title='NHÓM FACEBOOK'
  elif screen=='posts':items=s.rows('SELECT * FROM contents ORDER BY id DESC');title='KHO BÀI VIẾT'
  elif screen=='reviews':items=s.rows("SELECT r.* FROM group_reviews r LEFT JOIN jobs j ON j.id=r.job_id WHERE decision='' AND (r.state IN ('error','uncertain','pending') OR j.comment_status IN ('failed','uncertain')) ORDER BY r.updated DESC");title='KẾT QUẢ CẦN KIỂM TRA'
  else:
   conditions={'queue':"state IN ('queued','working')",'drafts':"state='draft'",'pending':"state='pending'",'attention':"state IN ('error','uncertain')",'history':"state NOT IN ('draft','queued')"}
   items=s.rows('SELECT * FROM jobs WHERE hidden=0 AND '+conditions[screen]+' ORDER BY '+('due,id' if screen in {'queue','drafts'} else 'updated DESC,id DESC'));title={'queue':'LỊCH ĐĂNG','drafts':'LỊCH NHÁP · CHƯA DUYỆT','pending':'BÀI CHỜ FACEBOOK DUYỆT','attention':'LƯỢT CẦN KIỂM TRA','history':'KẾT QUẢ GẦN ĐÂY'}[screen]
  total=len(items);page=min(page,max(0,(total-1)//size));part=items[page*size:(page+1)*size];rows=[];lines=[]
  for item in part:
   if screen in {'stats','worst','statpending'}:
    rate='Chưa có dữ liệu' if item['success_rate'] is None else str(item['success_rate'])+'%'
    lines.append(f"{item['name']}\n{rate} · {item['published']} đã đăng · {item['pending']} chờ · {item['failed']} lỗi · {item['removed']} gỡ · {item['declined']} từ chối · {item['uncertain']} chưa rõ" )
    rows.append([button(item['name'][:48],f"panel:group:{item['id']}")])
   elif screen=='watch':rows.append([button(f"{item['total']} lượt · {item['name']}"[:60],f"tg:watch:{item['group_id']}")])
   else:
    if screen=='groups':label=f"{'●' if item['enabled'] else '○'} {item['name']}";target='group';identifier=item['id']
    elif screen=='posts':label=f"#{item['id']} · {item['title'] or item['body'][:40]}";target='post';identifier=item['id']
    elif screen=='reviews':label=f"{STATUS.get(item['state'],item['state'])} · {item['group_name']}";target='review';identifier=item['id']
    else:label=f"#{item['id']} · {STATUS.get(item['state'],item['state'])} · {item['group_name']}";target='job';identifier=item['id']
    rows.append([button(label[:62],f'panel:{target}:{identifier}')])
  if screen=='groups':rows.insert(0,[button('Thêm nhóm','tg:newgroup:0'),button('Bật / tắt tất cả','tg:bulk:0')]);rows.insert(1,[button('Tìm nhóm','tg:searchgroup:0')])
  if screen=='posts':rows.insert(0,[button('Viết bài','panel:create:0'),button('AI viết nháp','tg:singleai:0')]);rows.insert(1,[button('Tìm bài','tg:searchpost:0')]);rows.append([button('Random từ kho','panel:random:0')])
  if screen in {'queue','drafts','pending','attention'}:
   rows.insert(0,[button('Đã duyệt','panel:queue:0'),button('Nháp','panel:drafts:0'),button('Chờ duyệt','panel:pending:0')]);rows.append([button('Cần kiểm tra','panel:attention:0'),button('Hủy lịch chờ','tg:cancelall:0')])
   if screen=='drafts' and items:rows.append([button('Duyệt các lịch nháp','tg:approveall:0')])
  if screen=='reviews':rows.insert(0,[button('Nhóm vượt ngưỡng','panel:watch:0')])
  if screen in {'stats','worst','statpending'}:rows.insert(0,[button('Cao nhất','panel:stats:0'),button('Thấp nhất','panel:worst:0'),button('Chờ nhiều','panel:statpending:0')])
  text=f'{total} mục · Trang {page+1}/{max(1,(total+size-1)//size)}\n\n'+ ('\n\n'.join(lines) if lines else 'Chọn một mục bên dưới để quản lý.' if part else 'Danh sách đang trống.')
  if screen in {'stats','worst','statpending'}:text+='\n\nTỷ lệ theo lịch sử đã lưu; dưới 5 lượt là mẫu ít.'
  return show(a,chat,title,text,pager(rows,screen,page,total),message_id)
 if screen=='group':
  rows=s.rows('SELECT * FROM groups WHERE id=? AND deleted=0',(page,))
  if not rows:raise ValueError('Nhóm không còn tồn tại.')
  g=rows[0];stat=next(x for x in group_metrics.statistics(s)['30'] if x['id']==page);calendar=s.group_calendars().get(page,{})
  body=f"#{page} · {g['name']}\n{'● Đang bật' if g['enabled'] else '○ Đang tắt'} · {g['category']}\nLink bài: { {'allow':'Cho phép','deny':'Không cho','unknown':'Chưa rõ'}.get(g['link_policy']) }\nDanh tính: { {'default':'Hồ sơ chính','auto':'Ưu tiên ẩn danh','anonymous':'Ẩn danh bắt buộc','nickname':'Biệt danh'}.get(g['posting_identity'],g['posting_identity']) }\n\n30 ngày: {stat['published']} đã đăng · {stat['pending']} chờ duyệt\n{stat['failed']} lỗi · {stat['removed']} bị gỡ · {stat['declined']} từ chối · {stat['uncertain']} chưa rõ\nLịch chờ: {stat['queued']}\nCó thể đăng từ: {a.timestamp(max(time.time(),g['next_post_after']))}"
  actions=[[button('Mở nhóm',url=g['url'])],[button('Tắt nhóm' if g['enabled'] else 'Bật nhóm',f"panel:{'disable' if g['enabled'] else 'enable'}:{page}"),button('Game / phân loại',f'tg:category:{page}')],[button('Quy định link',f'tg:policy:{page}'),button('Danh tính',f'tg:identity:{page}')],[button('Xóa nhóm',f'panel:deletegroup:{page}')],back('groups')]
  return show(a,chat,'CHI TIẾT NHÓM',body,actions,message_id)
 if screen=='post':
  r=s.rows('SELECT * FROM contents WHERE id=?',(page,))
  if not r:raise ValueError('Bài không còn trong kho.')
  p=r[0];body=f"#{page} · {p['title'] or 'Bài chưa đặt tên'}\n{p['category']} · {len(a.media_store.paths(p['media']))} tệp\n\n{p['body'][:2500]}"
  rows=[[button('Xem đầy đủ',f'panel:content:{page}'),button('Sửa bài',f'tg:editpost:{page}')],[button('Lên lịch',f'panel:plan:{page}'),button('Bình luận link',f'tg:postcomment:{page}')],[button('Xóa khỏi kho',f'panel:deletepost:{page}')],back('posts')]
  return show(a,chat,'BÀI VIẾT',body,rows,message_id)
 if screen=='job':
  r=s.rows('SELECT * FROM jobs WHERE id=?',(page,))
  if not r:raise ValueError('Không tìm thấy lượt đăng.')
  j=r[0];body=f"#{page} · {j['group_name']}\n{('Bị gỡ' if j['moderation_status']=='removed' else 'Bị từ chối' if j['moderation_status']=='declined' else STATUS.get(j['state'],j['state']))}\nDanh tính đã chọn: { {'default':'Hồ sơ chính','auto':'Ưu tiên ẩn danh','anonymous':'Ẩn danh','nickname':'Biệt danh'}.get(j['posting_identity'],j['posting_identity']) }\nGiờ dự kiến: {a.timestamp(j['due'])}\nBình luận: {COMMENT.get(j['comment_status'],j['comment_status'])}\n\n{j['body'][:2000]}\n\n{j['detail'][:600]}";rows=[]
  if j['post_url']:rows.append([button('Mở bài đã đăng',url=j['post_url'])])
  rows.append([button('Mở nhóm',url=j['url'])])
  if j['state']=='draft':rows.append([button('Duyệt lịch này',f'tg:approve:{page}')])
  if j['state'] in {'draft','queued'}:rows.append([button('Đổi giờ',f'tg:reschedule:{page}'),button('Hủy lượt',f'tg:cancel:{page}')])
  if j['state']=='error' and j['post_attempted']==0 and not j['post_url']:rows.append([button('Đặt lịch lại · chưa bấm Đăng',f'tg:retry:{page}')])
  if j['photo'] and Path(j['photo']).is_file():rows.append([button('Xem ảnh kết quả',f'tg:photo:{page}')])
  rows.append(back('queue'));return show(a,chat,'CHI TIẾT LƯỢT ĐĂNG',body,rows,message_id)
 if screen=='ai':
  t=s.get('studio_task',{});body=('Đang chạy' if t.get('status')=='running' else 'Đã dừng' if t.get('status')=='stopped' else 'Cần kiểm tra' if t.get('status')=='error' else 'Sẵn sàng')+'\n'+str(t.get('message',''))[:700]
  rows=[[button('Tạo chiến dịch từng bước','tg:aistart:0'),button('Viết một bản nháp','tg:singleai:0')],[button('Dừng AI','tg:stopai:0'),button('Cập nhật tiến trình','panel:ai:0')],back()]
  return show(a,chat,'AI VIẾT BÀI',body,rows,message_id)
 if screen=='status':return show(a,chat,'TRẠNG THÁI',a.status_text(),[[button('AI đang làm gì?','panel:ai:0')],back()],message_id)
 if screen=='help':
  body='1. Nhóm: thêm link, chọn game và bật nhóm.\n2. Bài viết: tự viết hoặc nhờ AI tạo nháp.\n3. Lịch đăng: xem nội dung, duyệt rồi bấm Chạy.\n4. Chiến dịch AI: chọn phạm vi → nhập ý chính → tính lịch → xác nhận.\n\nTạm dừng giữ nguyên lịch. Hủy lịch chỉ áp dụng lượt chưa chạy. Dừng AI ngắt việc tạo bài.\n\nBài chưa rõ đã gửi hay chưa không có nút đăng lại. Bình luận lỗi không làm bài đã đăng thành chưa đăng.\n\nĐổi API key, hồ sơ Facebook và kho tệp trên dashboard PC.'
  return show(a,chat,'HƯỚNG DẪN NHANH',body,[[button('Các lệnh nâng cao','tg:commands:0'),button('Token / nguồn AI','tg:usage:0')],back()],message_id)
 if screen=='random':
  return show(a,chat,'RANDOM BÀI TRONG KHO','Chọn ngẫu nhiên bài đã lưu, luôn đúng game của nhóm. Nhóm ALL nhận bài từ các game.\n\nTạo lịch nháp 7 ngày, nghỉ 30–60 phút. Xem và duyệt lịch trước khi chạy.',[[button('Tạo lịch nháp random','panel:randomcreate:0')],back('posts')],message_id)
 return a._legacy_panel(chat,screen,page,message_id)


def confirm(a,chat,operation,value,text,mid,extra=None):
 nonce=secrets.token_hex(8);a.STORE.set('tg_confirmation',{'nonce':nonce,'operation':operation,'value':value,'at':time.time(),'extra':extra or {}})
 rows=[[button('Xác nhận bắt đầu' if operation=='campaign' else 'Xác nhận',f'tg:confirm:0:{nonce}'),button('Quay lại','panel:home:0')]]
 if operation=='campaign':rows.insert(0,[button('Xem từng lịch','tg:planlist:0'),button('Nhóm chưa có lượt','tg:uncovered:0')])
 return show(a,chat,'XÁC NHẬN',text,rows,mid)


def callback(a,query):
 data=query.get('data','');mid=query['message']['message_id'];chat=a.STORE.get('owner_chat')
 old=re.fullmatch(r'panel:(job|history|status|help|ai|stats|worst|statpending|watch|drafts|pending|attention):(\d+)',data)
 if old:
  a.telegram('answerCallbackQuery',{'callback_query_id':query['id']});panel(a,chat,old[1],int(old[2]),mid);return True
 m=re.fullmatch(r'tg:([a-z]+):(\d+)(?::(.{1,40}))?',data)
 if not m:return False
 action,gid,arg=m[1],int(m[2]),m[3];s=a.STORE;a.telegram('answerCallbackQuery',{'callback_query_id':query['id']})
 if action=='confirm':
  pending=s.get('tg_confirmation')
  if not pending or pending['nonce']!=arg or time.time()-pending['at']>600:raise ValueError('Xác nhận đã hết hạn. Mở menu để thao tác lại.')
  s.set('tg_confirmation',None);op=pending['operation'];value=pending['value'];extra=pending['extra']
  if op=='cancel':n=s.cancel_jobs([value]);text=f'Đã hủy {n} lượt chưa chạy.'
  elif op=='cancelall':n=s.cancel_jobs(extra['ids']);text=f'Đã hủy {n} lượt đã chọn; lịch sử giữ nguyên.'
  elif op=='approveall':n=s.approve(extra['ids']);text=f'Đã duyệt {n} lượt. Bấm Chạy lịch khi sẵn sàng.'
  elif op=='retry':
   row=s.rows('SELECT * FROM jobs WHERE id=?',(value,))[0]
   if row['state']!='error' or row['post_attempted']!=0 or row['post_url']:raise ValueError('Không xác nhận được lượt này chưa gửi; không đặt lại.')
   ids=s.restore_failed_contents([row['content_id']]);s.reflow_queue();text='Đã đặt lại lịch: '+', '.join('#'+str(i) for i in ids)+'. Xem lịch để biết giờ mới.'
  elif op=='bulk':
   changed=s.toggle_groups(extra['ids'],bool(value))
   text=f"Đã {'bật' if value else 'tắt'} {changed['changed']} nhóm."
   if changed['skipped']:text+='\nBỏ qua '+str(len(changed['skipped']))+' nhóm: '+'; '.join(x['name']+' · '+x['reason'] for x in changed['skipped'][:5])
  elif op in {'watchkeep','watchdelete'}:s.decide_group_watch(value,'keep' if op=='watchkeep' else 'delete');text='Đã giữ nhóm và bắt đầu đếm mới.' if op=='watchkeep' else 'Đã xóa nhóm khỏi tool.'
  elif op=='links':
   p=extra['preview'];changed=a.apply_link_change(p['old_url'],p['new_url'],p['digest'],facebook=extra.get('facebook',False));text=f"Đã cập nhật link trong {changed['content_count']} bài lưu và {changed['job_count']} lịch chưa chạy. Hàng đợi tạm dừng; kiểm tra lịch trước khi chạy lại."
  elif op=='campaign':
   options=extra['options'];current=campaign_plan.preview(s,a.DATA/'media',options)
   if [(i['group_id'],round(i['due'])) for i in current['items']]!=[(i['group_id'],round(i['due'])) for i in extra['plan']['items']]:
    # Clock movement is expected; eligibility changes require a new preview.
    if [i['group_id'] for i in current['items']]!=[i['group_id'] for i in extra['plan']['items']]:raise ValueError('Nhóm hoặc lịch đã thay đổi. Tính lại dự kiến trước khi bắt đầu.')
   result=a.studio().draft_groups(options);return show(a,chat,'ĐÃ BẮT ĐẦU TẠO BÀI',result['message'],[[button('Theo dõi AI','panel:ai:0')],back()],mid)
  else:raise ValueError('Thao tác không hợp lệ.')
  return show(a,chat,'ĐÃ XỬ LÝ',text,[[button('Xem lịch','panel:queue:0'),button('Chạy lịch','panel:run:0')],back()],mid)
 if action in {'planlist','uncovered'}:
  pending=s.get('tg_confirmation')
  if not pending or pending['operation']!='campaign' or time.time()-pending['at']>600:raise ValueError('Dự kiến đã hết hạn, tạo lại từ mục AI.')
  plan=pending['extra']['plan'];items=plan['items'] if action=='planlist' else plan['uncovered_groups'];page=min(gid,max(0,(len(items)-1)//6));part=items[page*6:(page+1)*6]
  body='\n\n'.join((r.get('name','Nhóm #'+str(r.get('group_id',r.get('id','')))))+'\n'+(a.timestamp(r['due']) if action=='planlist' else r['reason']) for r in part) or 'Không có nhóm bị bỏ sót.'
  nav=[]
  if page:nav.append(button('‹ Trước',f'tg:{action}:{page-1}'))
  if (page+1)*6<len(items):nav.append(button('Sau ›',f'tg:{action}:{page+1}'))
  rows=([nav] if nav else [])+[[button('Xác nhận bắt đầu','tg:confirm:0:'+pending['nonce'])],back()]
  show(a,chat,('LỊCH DỰ KIẾN' if action=='planlist' else 'NHÓM CHƯA CÓ LƯỢT')+f' · {len(items)} mục',body,rows,mid);return True
 if action=='stopai':result=a.studio().stop();return show(a,chat,'DỪNG AI',result['message'],[[button('Cập nhật','panel:ai:0')],back()],mid) or True
 if action in {'approve','cancel','retry','reschedule','photo'}:
  jobs=s.rows('SELECT * FROM jobs WHERE id=?',(gid,))
  if not jobs:raise ValueError('Không tìm thấy lượt đăng.')
  j=jobs[0]
  if action=='approve':n=s.approve([gid]);show(a,chat,'ĐÃ DUYỆT',f'{n} lượt. Chưa chạy cho đến khi bật lịch.',[[button('Chạy lịch','panel:run:0')],back('drafts')],mid)
  elif action=='cancel':confirm(a,chat,'cancel',gid,f'Hủy lượt #{gid} của {j["group_name"]}?',mid)
  elif action=='retry':
   if j['state']!='error' or j['post_attempted']!=0 or j['post_url']:raise ValueError('Lượt chưa rõ kết quả không được tự gửi lại.')
   confirm(a,chat,'retry',gid,f'Đặt lại lượt #{gid}? Dữ liệu ghi nhận chưa bấm Đăng. Giữ nguyên nội dung và khoảng nghỉ.',mid)
  elif action=='reschedule':
   if j['state'] not in {'draft','queued'}:raise ValueError('Chỉ đổi giờ lượt chưa chạy.')
   s.set('bot_wizard',{'kind':'tg_reschedule','id':gid});a.send_text(chat,'Gửi giờ Việt Nam: YYYY-MM-DD HH:MM\nVí dụ 2026-10-29 09:30\n/cancelcreate để hủy.')
  else:
   if not j['photo'] or not Path(j['photo']).is_file():raise ValueError('Không còn ảnh kết quả.')
   a.send_photo(chat,j['photo'],f'Lượt #{gid} · {j["group_name"]} · {STATUS.get(j["state"],j["state"])}')
  return True
 if action in {'cancelall','approveall'}:
  ids=[r['id'] for r in s.rows("SELECT id FROM jobs WHERE hidden=0 AND state "+("IN ('draft','queued')" if action=='cancelall' else "='draft'"))]
  if not ids:raise ValueError('Không có lượt phù hợp.')
  confirm(a,chat,action,0,f"{'Hủy' if action=='cancelall' else 'Duyệt'} {len(ids)} lượt?",mid,{'ids':ids});return True
 if action=='bulk':show(a,chat,'BẬT / TẮT TẤT CẢ NHÓM','Chỉ áp dụng nhóm đang có trong tool. Tắt nhóm sẽ hủy lịch chưa chạy của nhóm đó.',[[button('Bật tất cả','tg:bulkset:1'),button('Tắt tất cả','tg:bulkset:0')],back('groups')],mid);return True
 if action=='bulkset':
  ids=[g['id'] for g in s.rows('SELECT id FROM groups WHERE deleted=0')];confirm(a,chat,'bulk',gid,f"{'Bật' if gid else 'Tắt'} {len(ids)} nhóm?",mid,{'ids':ids});return True
 if action in {'category','policy','identity'}:
  choices={'category':[(p,p) for p in (*media_library.POOLS,'ALL','Chung')],'policy':[('Cho phép link','allow'),('Không cho link','deny'),('Chưa rõ','unknown')],'identity':[('Hồ sơ chính','default'),('Ưu tiên ẩn danh','auto'),('Ẩn danh bắt buộc','anonymous'),('Biệt danh','nickname')]}
  show(a,chat,'THIẾT LẬP NHÓM','Chọn giá trị mới. Lịch chưa chạy có thể phải tạo lại để áp dụng.',[[button(label,f'tg:set{action}:{gid}:{v}')] for label,v in choices[action]]+[[button('‹ Nhóm',f'panel:group:{gid}')]],mid);return True
 if action in {'setcategory','setpolicy','setidentity'}:
  if action=='setcategory':
   if arg not in (*media_library.POOLS,'ALL','Chung'):raise ValueError('Phân loại không hợp lệ.')
   s.group_category(gid,arg);media_library.group_pools(s,gid,[arg] if arg!='Chung' else [])
  elif action=='setpolicy':s.set_link_policy(gid,arg)
  else:
   if arg=='nickname':s.set('bot_wizard',{'kind':'tg_nickname','id':gid});a.send_text(chat,'Gửi biệt danh đã thiết lập trên Facebook cho nhóm này. /cancelcreate để hủy.');return True
   s.set_posting_identity(gid,arg)
  panel(a,chat,'group',gid,mid);return True
 if action=='postcomment':s.set('bot_wizard',{'kind':'tg_postcomment','id':gid});a.send_text(chat,'Gửi link https://... để bình luận sau bài, hoặc dấu - để tắt. Thay đổi sẽ hủy lịch chưa chạy của bài để bạn lên lịch lại. /cancelcreate để hủy.');return True
 if action=='choosegame':
  w=s.get('bot_wizard',{})
  if w.get('kind') not in {'manual','ai','autopost'} or w.get('step')!='category' or arg not in (*media_library.POOLS,'ALL','Chung'):raise ValueError('Bước chọn game đã hết hạn.')
  a._legacy_bot_wizard({'chat':{'id':chat}},arg,chat);return True
 if action in {'searchgroup','searchpost'}:s.set('bot_wizard',{'kind':'tg_search','table':'groups' if action=='searchgroup' else 'contents'});a.send_text(chat,'Gửi tên, ID hoặc từ khóa cần tìm. /cancelcreate để hủy.');return True
 if action=='editpost':s.set('bot_wizard',{'kind':'tg_editpost','id':gid});a.send_text(chat,'Gửi nội dung mới cho bài #'+str(gid)+'. Lịch cũ giữ bản đã chốt.\n/cancelcreate để hủy.');return True
 if action=='newgroup':s.set('bot_wizard',{'kind':'tg_newgroup','step':'url'});a.send_text(chat,'THÊM NHÓM · 1/2\nGửi link chính của nhóm Facebook.\n/cancelcreate để hủy.');return True
 if action=='links':show(a,chat,'THAY LINK','Chọn phạm vi cần cập nhật. Luôn xem ảnh hưởng và xác nhận trước khi áp dụng.',[[button('Trong kho và lịch chờ','tg:linkscope:0')],[button('Kèm bài đã đăng 36 giờ gần nhất','tg:linkscope:1')],back()],mid);return True
 if action=='linkscope':s.set('bot_wizard',{'kind':'tg_links','step':'old','facebook':bool(gid)});a.send_text(chat,'THAY LINK · 1/2\nGửi link cũ ở dạng https://... /cancelcreate để hủy.');return True
 if action=='singleai':a.bot_wizard({'chat':{'id':chat}},'✨ AI tạo nháp',chat);return True
 if action=='aistart':
  s.set('bot_wizard',{'kind':'tg_campaign','step':'game'});show(a,chat,'CHIẾN DỊCH AI · 1/3','Chọn phạm vi nhóm đang bật. Mỗi nhóm một bài đúng game.',[[button('Tất cả nhóm đang bật','tg:campaigngame:0:any')]]+[[button(game,'tg:campaigngame:0:'+game)] for game in (*media_library.POOLS,'ALL')]+[back()],mid);return True
 if action=='campaigngame':
  if arg not in ('any',*media_library.POOLS,'ALL'):raise ValueError('Phạm vi game không hợp lệ.')
  w=s.get('bot_wizard',{})
  if w.get('kind')!='tg_campaign':raise ValueError('Tạo lại chiến dịch từ menu.')
  w.update(step='brief',scope=arg);s.set('bot_wizard',w);a.send_text(chat,'CHIẾN DỊCH AI · 2/3\nGửi ý chính / dữ kiện để AI viết. /cancelcreate để hủy.');return True
 if action=='campaignoptions':
  w=s.get('bot_wizard',{})
  if w.get('kind')!='tg_campaign' or 'brief' not in w:raise ValueError('Tạo lại chiến dịch từ menu.')
  w['step']='options';s.set('bot_wizard',w);a.send_text(chat,'Gửi: NHÓM_MỖI_NGÀY SỐ_NGÀY KHOẢNG_NGHỈ\nVí dụ: 15 5 40-80\nCho phép 1–30 nhóm/ngày, 1–7 ngày. /cancelcreate để hủy.');return True
 if action=='campaignpreview':
  w=s.get('bot_wizard',{})
  if w.get('kind')!='tg_campaign' or 'brief' not in w:raise ValueError('Bước tạo chiến dịch đã hết hạn.')
  per_day=w.get('per_day',15) if arg=='custom' else int(arg or 15)
  if not 1<=per_day<=30:raise ValueError('Mức nhóm/ngày không hợp lệ.')
  groups=[g['id'] for g in s.rows('SELECT id,category FROM groups WHERE enabled=1 AND deleted=0') if w.get('scope','any')=='any' or g['category'].casefold()==w['scope'].casefold()]
  options={'brief':w['brief'],'selection_mode':'manual','ids':groups,'coverage_once':True,'total_posts':min(90,max(1,len(groups))),'groups_per_day':per_day,'horizon':w.get('horizon',7),'minutes':w.get('minutes','40-80'),'media_count_mode':'random','media_count':1,'posts_per_group':1,'comment_mode':w.get('comment_mode','none'),'comment_link':w.get('comment_link',''),'identity_mode':'auto','autopost':True}
  plan=campaign_plan.preview(s,a.DATA/'media',options)
  text=f"Phủ dự kiến {plan['unique_groups']}/{plan['requested']} nhóm · {plan['estimated_posts']} bài\nTối đa {per_day} nhóm/ngày · {options['horizon']} ngày · nghỉ {options['minutes']} phút\nTối thiểu {plan['api_calls_min']} lượt gọi AI; viết lại đến khi đạt.\nBình luận: {'Có link' if options['comment_mode']=='always' else 'Không gửi'}\n\n"+'\n'.join(g['name']+' · '+g['reason'] for g in plan['uncovered_groups'][:5])
  if not plan['items']:raise ValueError('Không có nhóm đủ điều kiện. '+text)
  confirm(a,chat,'campaign',0,text+'\n\nXác nhận sẽ tạo bài, lên lịch và bật tự đăng.',mid,{'options':options,'plan':plan});return True
 if action=='campaigncomment':
  w=s.get('bot_wizard',{})
  if w.get('kind')!='tg_campaign':raise ValueError('Bước tạo chiến dịch đã hết hạn.')
  w['step']='comment';s.set('bot_wizard',w);a.send_text(chat,'Gửi link bình luận trực tiếp https://... hoặc dấu - để không gửi bình luận.');return True
 if action=='watch':
  row=next((r for r in s.group_watchlist() if r['group_id']==gid),None)
  if not row:raise ValueError('Nhóm không còn vượt ngưỡng cần xem xét.')
  show(a,chat,'XEM XÉT NHÓM',f"{row['name']}\n{row['total']} lượt · {row['failed']} lỗi · {row['pending']} chờ · {row['removed']} gỡ · {row['declined']} từ chối",[[button('Xem nhóm',url=row['url'])],[button('Giữ nhóm',f'tg:watchkeep:{gid}'),button('Xóa nhóm',f'tg:watchdelete:{gid}')],back('watch')],mid);return True
 if action in {'watchkeep','watchdelete'}:confirm(a,chat,action,gid,'Giữ nhóm và bắt đầu đếm lại?' if action=='watchkeep' else 'Xóa nhóm khỏi tool và hủy lịch chưa chạy?',mid);return True
 if action=='commands':a.send_text(chat,a.HELP);return True
 if action=='usage':
  import ai_provider
  u=ai_provider.usage_summary(s);show(a,chat,'LƯỢT GỌI AI',f"Hôm nay: {u['calls']} lượt · {u['total_tokens']} token đã biết\n{u['unknown_calls']} lượt không có dữ liệu token.\nHạn mức / số dư thực tế xem tại dịch vụ API.",[back()],mid);return True
 raise ValueError('Nút đã cũ. Gửi /menu để mở lại.')


def wizard(a,message,text,chat):
 aliases={'/groups':'groups','/contents':'posts','/queue':'queue','/status':'status','/panelgroups':'groups','/panelposts':'posts','/panelqueue':'queue','📊 Thống kê':'stats','✨ Chiến dịch AI':'ai','/ai':'ai','/stats':'stats','/history':'history','/help':'help','/reviews':'reviews'}
 if text in aliases:a.STORE.set('bot_wizard',None);panel(a,chat,aliases[text]);return True
 if text=='/stopai':a.send_text(chat,a.studio().stop()['message']);return True
 w=a.STORE.get('bot_wizard',{}) or {}
 if not w.get('kind','').startswith('tg_'):return False
 if text in {'/menu','/start','🏠 Menu','Menu','menu','/cancelcreate'}:
  a.STORE.set('bot_wizard',None);panel(a,chat);return True
 if text.startswith('/'):return False
 kind=w['kind'];s=a.STORE
 if kind=='tg_search':
  groups=w['table']=='groups';rows=s.rows('SELECT * FROM '+('groups WHERE deleted=0' if groups else 'contents WHERE 1=1')+' AND (CAST(id AS TEXT)=? OR '+('name' if groups else 'title')+' LIKE ?'+('' if groups else ' OR body LIKE ?')+') ORDER BY id DESC LIMIT 20',(text,'%'+text+'%') if groups else (text,'%'+text+'%','%'+text+'%'));s.set('bot_wizard',None)
  show(a,chat,'KẾT QUẢ TÌM KIẾM',str(len(rows))+' mục phù hợp (tối đa 20).',[[button(('#'+str(r['id'])+' · '+(r['name'] if groups else r['title'] or r['body'][:40]))[:62],f"panel:{'group' if groups else 'post'}:{r['id']}")] for r in rows]+[back('groups' if groups else 'posts')]);return True
 if kind=='tg_links':
  value=a.validate_link(text)
  if w['step']=='old':w.update(old=value,step='new');s.set('bot_wizard',w);a.send_text(chat,'THAY LINK · 2/2\nGửi link mới https://...');return True
  preview=s.preview_links(w['old'],value,facebook=w['facebook']);s.set('bot_wizard',None)
  confirm(a,chat,'links',0,f"Link cũ: {w['old']}\nLink mới: {value}\n\n{preview['content_count']} bài lưu · {preview['job_count']} lịch chưa chạy\n"+('Bao gồm bài đã đăng 36 giờ gần nhất. ' if w['facebook'] else 'Không sửa bài đã đăng. ')+'Hàng đợi sẽ tạm dừng khi áp dụng.',None,{'preview':preview,'facebook':w['facebook']});return True
 if kind=='tg_nickname':
  s.set_posting_identity(w['id'],'nickname',text);s.set('bot_wizard',None);panel(a,chat,'group',w['id']);return True
 if kind=='tg_postcomment':
  s.set_comment_settings(w['id'],'none' if text=='-' else 'always','' if text=='-' else a.validate_link(text));s.set('bot_wizard',None);panel(a,chat,'post',w['id']);return True
 if kind=='tg_editpost':
  old=s.rows('SELECT * FROM contents WHERE id=?',(w['id'],))
  if not old:raise ValueError('Bài đã bị xóa.')
  if not text.strip():raise ValueError('Gửi nội dung chữ mới.')
  p=old[0];s.update_content(p['id'],text,p['media'],p['body_no_link'],p['category'],p['title'],p['media_no_link']);s.set('bot_wizard',None);panel(a,chat,'post',p['id']);return True
 if kind=='tg_reschedule':
  due=a.parse_start(text)
  if due<=time.time():raise ValueError('Chọn thời gian trong tương lai theo giờ Việt Nam.')
  with s.db() as c:n=c.execute("UPDATE jobs SET due=?,state='draft',updated=? WHERE id=? AND state IN ('draft','queued')",(due,time.time(),w['id'])).rowcount
  if not n:raise ValueError('Lượt đã chuyển trạng thái; không đổi giờ.')
  s.set('bot_wizard',None);panel(a,chat,'job',w['id']);return True
 if kind=='tg_newgroup':
  if w['step']=='url':w.update(url=a.group_url(text),step='name');s.set('bot_wizard',w);a.send_text(chat,'THÊM NHÓM · 2/2\nGửi tên nhóm. Nhóm mới mặc định tắt; chọn game và quyền link trong thẻ nhóm sau khi thêm.');return True
  if not text.strip():raise ValueError('Nhập tên nhóm.')
  gid=s.add_group(w['url'],text);s.set('bot_wizard',None);panel(a,chat,'group',gid);return True
 if kind=='tg_campaign':
  if w['step']=='brief':
   if not 1<=len(text)<=6000:raise ValueError('Ý chính từ 1–6000 ký tự.')
   w.update(brief=text,step='settings');s.set('bot_wizard',w)
  elif w['step']=='options':
   parts=text.split()
   if len(parts)!=3:raise ValueError('Gửi đúng 3 mục, ví dụ: 15 5 40-80')
   per_day,days=int(parts[0]),int(parts[1]);a.interval_bounds(parts[2])
   if not 1<=per_day<=30 or not 1<=days<=7:raise ValueError('Chọn 1–30 nhóm/ngày và 1–7 ngày.')
   w.update(step='settings',per_day=per_day,horizon=days,minutes=parts[2]);s.set('bot_wizard',w)
  elif w['step']=='comment':
   w.update(step='settings',comment_mode='none' if text=='-' else 'always',comment_link='' if text=='-' else a.validate_link(text));s.set('bot_wizard',w)
  else:raise ValueError('Bấm một mức nhóm/ngày bên dưới để tính dự kiến, hoặc /cancelcreate để hủy.')
  show(a,chat,'CHIẾN DỊCH AI · 3/3','Mỗi nhóm một bài đúng game. Random 1 video hoặc 1–3 ảnh.\nChọn mức nhóm/ngày để tính lịch, chưa gọi AI.',[[button('10 nhóm/ngày','tg:campaignpreview:0:10'),button('15 nhóm/ngày','tg:campaignpreview:0:15'),button('20 nhóm/ngày','tg:campaignpreview:0:20')],[button('Tùy chỉnh nhịp','tg:campaignoptions:0'),button('Link bình luận','tg:campaigncomment:0')],[button('Xem dự kiến tùy chỉnh','tg:campaignpreview:0:custom')],back()]);return True
 return False
