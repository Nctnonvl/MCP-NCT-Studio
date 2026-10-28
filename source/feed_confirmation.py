"""Reload and verify one submitted post in the group feed; never repost."""
import asyncio,re,time
from pathlib import Path
from receipts import has_verified_post,post_url
from post_context import own_post_context,clean,feed_posts
from post_comments import finish_post,same_group_page,open_observed_post

def new_pending_banner(snapshot,before):
 """A newly appearing group banner is provisional evidence, not publication."""
 labels=('đang chờ quản trị viên phê duyệt','pending admin approval','en attente d’approbation')
 def present(text):
  return any(any(label in clean(line) for label in labels) and ('text "' in line or 'heading "' in line or clean(line) in labels) for line in text.splitlines())
 return present(snapshot) and not present(before)


def recent_post(context,job):
 name=clean(context.get('timestamp',{}).get('name',''))
 if name in {'vừa xong','just now',"à l'instant",'à l’instant'}:return True
 age=re.fullmatch(r'(?:il y a )?(?:khoảng |about |environ )?(\d+)\s*(?:phút(?: trước)?|minutes?(?: ago)?|min)',name)
 limit=max(3,min(20,int((time.time()-job.get('submitted_at',time.time()))/60)+2))
 return bool(age and int(age[1])<=limit)

async def resolve_timestamp(tool,observe,current_url,root,job):
 """Facebook time links can expose only a group placeholder until clicked."""
 from desktop import foreground,verify_live_target
 if job.get('preexisting_caption_visible'):return ''
 context=await asyncio.to_thread(own_post_context,root,job['body'])
 if context.get('caption_seen') is not True or not recent_post(context,job):return ''
 target=context.get('timestamp',{});bounds=foreground(root)
 loc=target.get('loc',[])
 if target.get('role')!='link' or len(loc)!=2 or not (bounds[0]<=loc[0]<bounds[2] and bounds[1]<=loc[1]<bounds[3]):return ''
 verify_live_target(target,root)
 await tool('Click',{'loc':loc})
 await asyncio.sleep(2)
 await observe(True)
 # Only the actual address opened by Facebook can authorize the next step.
 return post_url(await current_url(),job['url'])


async def verify_feed(tool,observe,current_url,root,job,before,report):
 from desktop import foreground,valid_pending_receipt
 location=await current_url()
 if not same_group_page(location,job['url']) and not post_url(location,job['url']):
  return {'state':'uncertain','detail':'Đã rời nhóm đích sau khi gửi; không bình luận hoặc gửi lại.'}
 # Preserve a new submit receipt/toast before reload removes transient feedback.
 # Old approval notices were already captured before opening the composer.
 after_submit=await observe(True)
 if job.get('data_dir') and job.get('id'):
  (Path(job['data_dir'])/'work'/f"after-submit-{job['id']}.txt").write_text(after_submit,encoding='utf-8')
 pending=[line.strip() for line in after_submit.splitlines() if valid_pending_receipt(line,before,job['body'])]
 baseline=job.get('pending_banner_baseline',before)
 if new_pending_banner(after_submit,baseline):pending.append('Thông báo chờ quản trị viên phê duyệt mới xuất hiện sau gửi.')
 if job.get('submit_pending_receipt'):pending.append(job['submit_pending_receipt'])
 observed=await asyncio.to_thread(own_post_context,root,job['body'])
 hint=observed.get('timestamp',{}) if observed.get('caption_seen') is True and recent_post(observed,job) else {}
 if post_url(hint.get('url',''),job['url']) in job.get('preexisting_post_urls',[]):hint={}
 from receipts import read_post_receipt
 from post_link_check import verify as verify_link
 receipt=await asyncio.to_thread(read_post_receipt,root,job['body'],job['url'])
 candidate=post_url(location,job['url']) or post_url(hint.get('url',''),job['url']) or (post_url(receipt.get('post_url',''),job['url']) if observed.get('caption_seen') is True and recent_post(observed,job) else '')
 if pending:
  # A pending author's own permalink can display the complete post and even
  # a comment editor. That alone must never override a fresh pending receipt.
  candidate=candidate if observed.get('caption_seen') is True and candidate not in job.get('preexisting_post_urls',[]) else ''
  if not candidate and observed.get('caption_seen') is True and recent_post(observed,job):
   candidate=await resolve_timestamp(tool,observe,current_url,root,job)
  return {'state':'pending','post_url':candidate,'detail':'Facebook đã nhận bài để quản trị viên duyệt; đang đối chiếu trạng thái cuối.','comment_status':'waiting_approval','comment_detail':'Đợi xác nhận được duyệt trước khi bình luận.','verification_source':'submit_feedback'}
 if candidate and candidate not in job.get('preexisting_post_urls',[]):
  result=await verify_link(tool,observe,current_url,root,job,candidate,report)
  result['feed_reloaded']=True
  return result
 report('Tải lại trang nhóm để kiểm tra bài vừa gửi')
 await tool('Shortcut',{'shortcut':'ctrl+r'})
 await asyncio.sleep(3)
 seen=[]
 for step in range(10):
  location=await current_url()
  if not same_group_page(location,job['url']) and not post_url(location,job['url']):break
  snapshot=await observe(True)
  if step==0:
   from group_posting import newest_first
   snapshot,newest=await newest_first(tool,observe,snapshot,root,report)
  if job.get('data_dir') and job.get('id'):
   (Path(job['data_dir'])/'work'/f"feed-{job['id']}-{step+1}.txt").write_text(snapshot,encoding='utf-8')
  pending.extend(line.strip() for line in snapshot.splitlines() if valid_pending_receipt(line,before,job['body']))
  if new_pending_banner(snapshot,baseline):pending.append('Thông báo chờ quản trị viên phê duyệt mới xuất hiện sau tải lại.')
  cards=await asyncio.to_thread(feed_posts,root,job['url'])
  allowed=[]
  for card in cards:
   if card['key'] not in seen:
    if len(seen)>=5:break
    seen.append(card['key'])
   allowed.append(card)
  context=await asyncio.to_thread(own_post_context,root,job['body'])
  old=job.get('preexisting_post_urls',[])
  link=post_url(context.get('timestamp',{}).get('url',''),job['url'])
  if pending:
   candidate=link if context.get('caption_seen') is True and link not in old else ''
   return {'state':'pending','post_url':candidate,'comment_status':'waiting_approval','detail':'Facebook đã nhận bài để quản trị viên duyệt; đang đối chiếu trạng thái cuối.','verification_source':'submit_feedback'}
  # A long caption is collapsed before its footer. Expand only the unique
  # matching card among the bounded first five; then require the full body.
  prefix=clean(job['body'].splitlines()[0])[:55]
  partial_within=bool(prefix) and any(prefix in card['text'] for card in allowed)
  expand=context.get('expand',[]);expanded_within=False
  if context.get('caption_seen') is False and partial_within and recent_post(context,job) and len(expand)==1 and not job.get('preexisting_caption_visible'):
   from desktop import verify_live_target
   target=expand[0];bounds=foreground(root);loc=target.get('loc',[])
   if len(loc)==2 and bounds[0]<=loc[0]<bounds[2] and bounds[1]<=loc[1]<bounds[3]:
    verify_live_target(target,root)
    report('Mở Xem thêm của đúng bài vừa gửi để đối chiếu toàn bộ nội dung')
    await tool('Click',{'loc':loc});await observe(True)
    context=await asyncio.to_thread(own_post_context,root,job['body'])
    link=post_url(context.get('timestamp',{}).get('url',''),job['url'])
    # The same observed card is still within the first five after expansion.
    expanded_within=context.get('caption_seen') is True
  # An unreadable card list cannot establish that a matching caption is among
  # the first five. A separately observed permalink can still be verified below.
  within_limit=expanded_within or (bool(cards) and any(clean(job['body']) in card['text'] or (link and card.get('url')==link) for card in allowed))
  if context and within_limit and link not in old and recent_post(context,job):
   # The feed is used only to locate its permalink, never as the comment surface.
   if not link:
    receipt=await asyncio.to_thread(read_post_receipt,root,job['body'],job['url'])
    link=post_url(receipt.get('post_url',''),job['url'])
    if not link:
     report('Mở mốc thời gian của đúng bài vừa gửi để lấy link thật')
     link=await resolve_timestamp(tool,observe,current_url,root,job)
     if not same_group_page(await current_url(),job['url']) and not link:
      return {'state':'uncertain','detail':'Đã mở mốc thời gian nhưng chưa lấy được link đúng nhóm; không bình luận hoặc gửi lại.'}
   if link:
    report('Đã lấy link bài khớp; mở link để kiểm tra rồi mới bình luận')
    result=await verify_link(tool,observe,current_url,root,job,link,report)
    result['feed_reloaded']=True;result['feed_scan_steps']=step+1;result['feed_sorted_newest']=newest;result['feed_posts_checked']=len(seen)
    return result
  if hint:
   target=hint;hint={}
   report('Mở link bài đã quan sát trước khi tải lại; đối chiếu lại đầy đủ nội dung')
   if await open_observed_post(tool,observe,target,job['url']):
    result=await verify_link(tool,observe,current_url,root,job,target['url'],report)
    if has_verified_post(result,job['url']):
     result.update(feed_reloaded=True,feed_scan_steps=step+1)
     return result
    # Do not scroll a different surface and call it the group feed.
    return {**result,'feed_reloaded':True}
  if len(seen)>=5:break
  if step<9:
   bounds=foreground(root)
   point=[(bounds[0]+bounds[2])//2,(bounds[1]+bounds[3])//2]
   report(f'Tìm bài vừa gửi trong 5 bài gần nhất · đã đọc {len(seen)}/5')
   await tool('Scroll',{'loc':point,'direction':'down','wheel_times':2})
   await asyncio.sleep(1)
 if pending:return {'state':'pending','detail':'Facebook đã nhận bài để quản trị viên duyệt; chưa có xác nhận đã xuất bản.','comment_status':'waiting_approval','comment_detail':'Chưa lấy được link; cần gắn link bài để theo dõi duyệt.','feed_reloaded':True}
 return {'state':'uncertain','detail':'Đã tải lại; chưa xác minh được đúng bài trong tối đa 5 bài gần nhất. Cần kiểm tra, không tự đăng lại.','comment_status':'uncertain','comment_detail':'Chưa tìm được đúng bài để bình luận.','feed_reloaded':True,'feed_posts_checked':len(seen)}
