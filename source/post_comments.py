"""Deterministic comments on one verified new post. No model chooses editors."""
import asyncio,json,time
from pathlib import Path
from receipts import post_url
from store import group_url
from facebook_labels import RECENT
from post_context import own_post_context,clean
from facebook_labels import LINK_REJECTED
import comment_identity
from comment_feedback import has_error,read_error

def recent_context(context):
 name=context.get('timestamp',{}).get('name','')
 return name in RECENT

def same_group_page(url,group):
 try:return group_url(url)==group_url(group)
 except (ValueError,TypeError,AttributeError):return False

def page_matches(url,job,context,link,feed):
 if context.get('caption_seen') is not True:return False
 current=post_url(url,job['url'])
 if current:return bool(link) and current==link
 if not feed or not same_group_page(url,job['url']) or context.get('caption_seen') is not True:return False
 raw=context.get('timestamp',{}).get('url','');target=post_url(raw,job['url'])
 return target==link if link else (same_group_page(raw,job['url']) if raw else recent_context(context))

async def open_observed_post(tool,observe,target,group):
 """Navigate only to an observed, group-validated post URL; time labels may change."""
 link=post_url(target.get('url',''),group)
 if not link:return False
 import pyperclip
 old=pyperclip.paste()
 try:
  pyperclip.copy(link)
  await tool('Shortcut',{'shortcut':'ctrl+l'})
  await tool('Shortcut',{'shortcut':'ctrl+v'})
  await tool('Shortcut',{'shortcut':'enter'})
 finally:pyperclip.copy(old)
 await asyncio.sleep(2)
 await observe(True)
 return True


async def finish_post(tool,observe,current_url,root,job,result,submitted):
 from desktop import foreground,verify_live_target
 if not submitted:return result
 if job.get('data_dir') and not job.get('comment_profile_name'):
  config=Path(job['data_dir'])/'browser-profile.json'
  if config.is_file():
   from desktop import selected_browser_config
   selected=selected_browser_config(job['data_dir'])
   if selected.get('facebook_account'):job={**job,'comment_profile_name':selected['facebook_account']}
 foreground(root)
 context=await asyncio.to_thread(own_post_context,root,job['body'])
 if not context:return result
 profile_actor=context.get('current_profile_actor','')
 if context.get('caption_seen') is False:
  expand=context.get('expand',[])
  target=expand[0] if len(expand)==1 else None
  if target is None:
   # A collapsed feed can hide the footer. Open only the observed timestamp
   # belonging to the unique candidate, then require the FULL caption below.
   timestamp=context.get('timestamp',{})
   if post_url(timestamp.get('url',''),job['url']):target=timestamp
  if target is None:return result
  if not await open_observed_post(tool,observe,target,job['url']):
   verify_live_target(target,root);await tool('Click',{'loc':target['loc']});await observe(True)
  context=await asyncio.to_thread(own_post_context,root,job['body'])
  if not context or context.get('caption_seen') is not True:return result
 location=await current_url()
 # Prefer commenting directly in the verified feed. Large media can place
 # the editor below the viewport; do not click a stale timestamp to find it.
 if same_group_page(location,job['url']) and context.get('caption_seen') is True:
  for _ in range(3):
   if context.get('editors'):break
   bounds=foreground(root)
   await tool('Scroll',{'loc':[(bounds[0]+bounds[2])//2,(bounds[1]+bounds[3])//2],'direction':'down','wheel_times':3})
   await asyncio.sleep(.7);await observe(True)
   context=await asyncio.to_thread(own_post_context,root,job['body'])
   if context.get('caption_seen') is not True or not same_group_page(await current_url(),job['url']):return result
 link=post_url(location,job['url'])
 raw_href=context.get('timestamp',{}).get('url','');href=post_url(raw_href,job['url'])
 feed=not link and same_group_page(location,job['url']) and context.get('caption_seen') is True and len(context.get('editors',[]))==1 and bool(href or (raw_href and same_group_page(raw_href,job['url'])) or (not raw_href and recent_context(context)))
 if feed:link=href
 if not link and not feed:
  target=context['timestamp']
  if target['loc'][0]<=0 or target['loc'][1]<=0:return result
  if not await open_observed_post(tool,observe,target,job['url']):
   verify_live_target(target,root)
   await tool('Click',{'loc':target['loc']})
   await asyncio.sleep(3)
   await observe(True)
  link=post_url(await current_url(),job['url'])
 if not link and not feed:return result
 # Check caption again after permalink navigation; never trust URL alone.
 context=await asyncio.to_thread(own_post_context,root,job['body'])
 if not context:return result
 if context.get('caption_seen') is not True:return result
 result.update(state='submitted',detail='Đã xác nhận đúng nội dung bài vừa gửi trên Facebook.',comment_surface='group_feed' if feed else 'permalink',verification_source='group_feed' if feed else 'post_permalink',receipt_verified=True)
 if link:result['post_url']=link
 if context.get('post_actor'):
  actor=clean(context['post_actor'])
  identity='anonymous' if actor in comment_identity.ANONYMOUS else 'nickname' if actor==clean(job.get('posting_nickname','')) else 'named'
  result.update(post_actor=context['post_actor'],post_identity=identity,post_identity_verified=True)
  job={**job,'comment_expected_actor':context['post_actor']}
 text=job.get('comment_text','')
 if not text:
  result.update(comment_status='skipped',comment_detail='Không gửi bình luận: quy định nhóm không cho phép hoặc bài chưa bật bình luận link.')
  return result
 if job.get('comment_policy')!='allowed':
  result.update(comment_status='skipped',comment_detail='Không gửi bình luận vì chưa được phép theo quy định nhóm.')
  return result
 ledger=Path(job['data_dir'])/'work'/f"comment-{job['id']}.json"
 attempted=False
 profile_name=''
 attempt_meta={}
 last_error=None
 if ledger.exists():
  previous=json.loads(ledger.read_text(encoding='utf-8'))
  if not (previous.get('status')=='failed' and previous.get('attempted') is False):
   content=clean(previous.get('content',''))
   if previous.get('attempted') and previous.get('status')=='uncertain' and content and page_matches(await current_url(),job,context,link,feed) and context.get('outside_texts',[]).count(content)>previous.get('baseline',0):
    detail='Đã kiểm tra lại đúng bài và thấy bình luận đã gửi; không gửi thêm.'
    previous.update(status='sent',detail=detail)
    ledger.write_text(json.dumps(previous,ensure_ascii=False),encoding='utf-8')
    result.update(comment_status='sent',comment_detail=detail)
    return result
   if previous.get('attempted') and previous.get('status')=='uncertain' and page_matches(await current_url(),job,context,link,feed):
    previous.setdefault('initial_detail',previous.get('detail',''))
    previous['detail']='Đã mở lại đúng bài đã đăng; chưa thấy bình luận đã thử gửi. Giữ để kiểm tra, không tự gửi thêm.'
    ledger.write_text(json.dumps(previous,ensure_ascii=False),encoding='utf-8')
   resumable=previous.get('status')=='uncertain' and previous.get('attempted') and clean(previous.get('content',''))==clean(text) and isinstance(previous.get('baseline'),int)
   events=previous.get('attempts') or ([previous] if previous.get('attempted') else [])
   if len(events)>=3 and previous.get('status')=='uncertain':
    previous.update(status='failed',retry_exhausted=True,detail='Bình luận chưa được gửi thành công sau 3 lần thử: chưa thấy trên đúng bài. Đã dừng thử.')
    ledger.write_text(json.dumps(previous,ensure_ascii=False),encoding='utf-8')
    resumable=False
   if resumable and len(events)<3:
    attempt_meta={**previous,'attempts':events};attempted=True
   else:
    result.update(comment_status=previous.get('status','uncertain'),comment_detail=previous.get('detail','Đã có lần gửi bình luận; không tự gửi lại.'),comment_attempts=len(events),comment_retry_exhausted=previous.get('retry_exhausted',False))
    return result
 async def send_once(content,kind):
  nonlocal attempted,profile_name,profile_actor,attempt_meta,last_error
  location=await current_url()
  await observe(True)
  ctx=await asyncio.to_thread(own_post_context,root,job['body'])
  if not page_matches(location,job,ctx,link,feed):raise RuntimeError('Đã rời bài đích hoặc không còn đối chiếu được bài trong nhóm; không bình luận.')
  prior=[e for e in attempt_meta.get('attempts',[]) if clean(e.get('content',''))==clean(content)]
  baseline=prior[0].get('baseline',0) if prior else ctx.get('outside_texts',[]).count(clean(content))
  if prior and ctx.get('outside_texts',[]).count(clean(content))>baseline:return 'sent',''
  editors=ctx.get('editors',[])
  def identity_editors(items):
   account=ctx.get('current_profile_actor') or profile_actor
   return [{**editor,'profile_actor':account,'profile_verified':True} if account and not comment_identity.actor(editor) and clean(editor.get('name','')) in comment_identity.PUBLIC_EDITORS else editor for editor in items]
  editors=identity_editors(editors)
  # A photo/video post may place its editor below the viewport. Scroll only
  # while the exact post and full caption are still independently verified.
  for _ in range(3):
   if editors:break
   if not page_matches(await current_url(),job,ctx,link,feed):break
   bounds=foreground(root)
   await tool('Scroll',{'loc':[(bounds[0]+bounds[2])//2,(bounds[1]+bounds[3])//2],'direction':'down','wheel_times':3})
   await asyncio.sleep(.7);await observe(True)
   ctx=await asyncio.to_thread(own_post_context,root,job['body'])
   if not page_matches(await current_url(),job,ctx,link,feed):raise RuntimeError('Không còn xác minh được đúng bài khi tìm ô bình luận.')
   editors=identity_editors(ctx.get('editors',[]))
  if len(editors)!=1:raise RuntimeError('Không có duy nhất ô bình luận của bài vừa đăng.')
  if editors[0].get('enabled') is False:raise RuntimeError('Facebook đang khóa ô bình luận hoặc còn hộp báo lỗi; chưa thể gửi bình luận.')
  if not comment_identity.verified(job,editors[0],profile_name):
   trigger=comment_identity.selector(ctx)
   if not trigger:raise RuntimeError('Chưa xác minh được danh tính bình luận đã chọn; Facebook chưa hiện nút đổi danh tính trong ô bình luận.')
   verify_live_target(trigger,root)
   await tool('Click',{'loc':trigger['loc']});await asyncio.sleep(1)
   await observe(True)
   options=comment_identity.menu(root);option=comment_identity.option(job,options)
   if not option:raise RuntimeError('Facebook không có duy nhất lựa chọn danh tính bình luận yêu cầu. Chưa gửi bình luận.')
   verify_live_target(option,root)
   await tool('Click',{'loc':option['loc']});await asyncio.sleep(1)
   selected_mode,selected_actor=comment_identity.desired(job)
   if selected_mode=='profile' or (selected_mode=='actor' and clean(option.get('profile_name',''))==selected_actor and selected_actor not in comment_identity.ANONYMOUS):
    profile_name=option.get('profile_name',option['name'])
    # Freshly selected, named profile in Facebook's scoped identity dialog.
    # This proof may enrich a generic public editor after the dialog closes.
    profile_actor=profile_name
   await observe(True)
   ctx=await asyncio.to_thread(own_post_context,root,job['body']);editors=identity_editors(ctx.get('editors',[]))
   if len(editors)!=1 or not page_matches(await current_url(),job,ctx,link,feed) or not comment_identity.verified(job,editors[0],profile_name):raise RuntimeError('Bài hoặc danh tính ở ô bình luận chưa khớp lựa chọn. Chưa gửi bình luận.')
  target=editors[0]
  for validation in range(2):
   try:
    verify_live_target(target,root)
    break
   except RuntimeError:
    if validation:raise
    # No input was sent. Reobserve after layout/scroll movement and require
    # the same full post, identity and single editor before the one send.
    await observe(True)
    ctx=await asyncio.to_thread(own_post_context,root,job['body'])
    if not page_matches(await current_url(),job,ctx,link,feed):raise
    fresh=identity_editors(ctx.get('editors',[]))
    if len(fresh)!=1 or not comment_identity.verified(job,fresh[0],profile_name):raise
    target=fresh[0]
  if len(attempt_meta.get('attempts',[]))>=3:raise RuntimeError('Đã đủ 3 lượt gửi bình luận.')
  result['comment_identity_effective']=comment_identity.actor(target) or target.get('profile_actor') or 'mặc định Facebook'
  event={'kind':kind,'content':content,'baseline':baseline,'at':time.time()}
  attempt_meta={**event,'attempts':attempt_meta.get('attempts',[])+[event]}
  ledger.write_text(json.dumps({**attempt_meta,'attempted':True,'status':'uncertain','detail':'Đã bắt đầu gửi bình luận; không tự lặp.'},ensure_ascii=False),encoding='utf-8')
  attempted=True
  await tool('Type',{'loc':target['loc'],'text':content,'clear':True,'press_enter':True})
  await asyncio.sleep(4)
  snap=await observe(True)
  retained=False
  for check in range(3):
   ctx=await asyncio.to_thread(own_post_context,root,job['body'])
   if page_matches(await current_url(),job,ctx,link,feed) and ctx.get('outside_texts',[]).count(clean(content))>baseline:return 'sent',snap
   if any(v in clean(snap) for v in LINK_REJECTED):return 'rejected',snap
   if has_error(snap):
    feedback=read_error(root)
    last_error=feedback or {'kind':'temporary','message':'Facebook báo lỗi khi hoàn tất yêu cầu bình luận.'}
    retained=retained or any(clean(e.get('draft_text',''))==clean(content) for e in ctx.get('editors',[]))
    if feedback and feedback.get('dismiss'):
     target=feedback['dismiss'];verify_live_target(target,root)
     await tool('Click',{'loc':target['loc']})
    if last_error['kind']=='blocked':break
   if check<2:
    await asyncio.sleep(3)
    location=await current_url()
    actual=post_url(location,job['url'])
    if (actual and actual!=link) or (not actual and not same_group_page(location,job['url'])):
     raise RuntimeError('Đã rời bài đích khi kiểm tra kết quả bình luận.')
    snap=await observe(True)
  if last_error and last_error['kind']=='not_sent' and retained:return 'retryable',snap
  if last_error:return 'server_error',snap
  return 'uncertain',snap
 try:
  content=text;kind='link';status='uncertain'
  previous_count=len(attempt_meta.get('attempts',[]))
  for turn in range(max(0,3-previous_count)):
   if turn or previous_count:
    # Refresh the exact post and check for a late success before typing again.
    location=await current_url()
    if not page_matches(location,job,await asyncio.to_thread(own_post_context,root,job['body']),link,feed):
     raise RuntimeError('Không còn xác minh được đúng bài trước lượt thử bình luận tiếp theo.')
    await asyncio.sleep(6)
    await tool('Shortcut',{'shortcut':'ctrl+r'})
    await asyncio.sleep(3);await observe(True);last_error=None
   status,_=await send_once(content,kind)
   if status=='sent' or (last_error and last_error.get('kind')=='blocked'):break
   if status=='rejected':
    if job.get('comment_fallback') and kind=='link':content=job['comment_fallback'];kind='tiktok'
    else:break
  count=len(attempt_meta.get('attempts',[]));result['comment_attempts']=count
  if status=='sent':
   result.update(comment_status='fallback_sent' if kind=='tiktok' else 'sent',comment_detail='Đã thấy bình luận trên đúng bài viết; dừng gửi.')
  elif count>=3:
   result.update(comment_status='failed',comment_retry_exhausted=True,comment_unconfirmed=True,comment_detail='Bình luận chưa được gửi thành công sau 3 lần thử: chưa thấy bình luận trên đúng bài. Đã dừng thử.')
  else:
   result.update(comment_status='failed' if status=='rejected' else 'uncertain',comment_detail='Bình luận chưa được gửi thành công; chưa xác nhận xuất hiện trên đúng bài.')
   if last_error:result['comment_detail']='Facebook báo lỗi: '+last_error['message'][:180]+'. Chưa xác nhận bình luận thành công.'

 except Exception as exc:
  result.update(comment_status='uncertain' if attempted else 'failed',comment_detail='Không xác nhận gửi bình luận: '+str(exc)[:200])
 try:
  ledger.write_text(json.dumps({**attempt_meta,'retry_exhausted':result.get('comment_retry_exhausted',False),'status':result['comment_status'],'detail':result['comment_detail'],'attempted':attempted},ensure_ascii=False),encoding='utf-8')
 except OSError:
  result['comment_ledger_error']='Không lưu được biên nhận bình luận cuối; không tự gửi lại.'
 # When UIA omitted the permalink, collect it only AFTER commenting in the feed.
 if feed and not link and result['comment_status'] in {'sent','fallback_sent'}:
  ctx=await asyncio.to_thread(own_post_context,root,job['body'])
  if ctx.get('caption_seen') is True and recent_context(ctx):
   try:
    target=ctx['timestamp']
    if not await open_observed_post(tool,observe,target,job['url']):
     verify_live_target(target,root)
     await tool('Click',{'loc':target['loc']});await observe(True)
    permalink=post_url(await current_url(),job['url'])
    if permalink:result['post_url']=permalink
   except Exception:pass
 if result.get('state')=='submitted' and not result.get('post_url'):
  from receipts import read_post_receipt
  receipt=await asyncio.to_thread(read_post_receipt,root,job['body'],job['url'])
  if receipt.get('post_url'):result['post_url']=receipt['post_url']
 return result
