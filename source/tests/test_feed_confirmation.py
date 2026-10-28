import unittest,time
from unittest.mock import AsyncMock,patch
from feed_confirmation import verify_feed
G='https://www.facebook.com/groups/test/'
P=G+'posts/123/'
class FeedTests(unittest.IsolatedAsyncioTestCase):
 def setUp(self):
  receipt=patch('receipts.read_post_receipt',return_value={});receipt.start();self.addCleanup(receipt.stop)
 async def run_case(self,context=None,snapshot='',before='',old=None,current=G):
  job={'url':G,'body':'Exact unique full caption used for verification','submitted_at':time.time(),'preexisting_post_urls':old or []}
  tool=AsyncMock();observe=AsyncMock(return_value=snapshot)
  complete={'state':'submitted','post_url':P,'receipt_verified':True,'verification_source':'post_permalink','comment_status':'sent'}
  cards=[{'key':'matching-card','text':job['body'],'url':P}] if context else []
  with patch('desktop.foreground',return_value=[0,0,800,600]),patch('feed_confirmation.feed_posts',return_value=cards),patch('feed_confirmation.asyncio.sleep',new=AsyncMock()),patch('feed_confirmation.own_post_context',return_value=context or {}),patch('post_link_check.verify',new=AsyncMock(return_value=complete)) as finish:
   result=await verify_feed(tool,observe,AsyncMock(return_value=current),1,job,before,lambda _:None)
  return result,tool,finish
 async def test_reload_then_comment_at_verified_post_no_management(self):
  ctx={'caption_seen':True,'timestamp':{'name':'vừa xong','url':P}}
  result,tool,finish=await self.run_case(ctx)
  self.assertEqual(result['state'],'submitted');self.assertTrue(result['feed_reloaded'])
  finish.assert_awaited_once();self.assertEqual(finish.call_args.args[5],P)
 async def test_old_pending_notice_does_not_mark_new_post_pending(self):
  notice='Bài viết của bạn đang chờ quản trị viên phê duyệt'
  result,tool,finish=await self.run_case(snapshot=notice,before=notice)
  self.assertEqual(result['state'],'uncertain');finish.assert_not_awaited()
  self.assertEqual(sum(c.args[0]=='Scroll' for c in tool.await_args_list),9)
 async def test_new_pending_receipt_is_distinguished_from_old_notice(self):
  result,tool,finish=await self.run_case(snapshot='Bài viết của bạn đang chờ quản trị viên phê duyệt')
  self.assertEqual(result['state'],'pending');finish.assert_not_awaited()
 async def test_older_identical_post_is_not_commented(self):
  ctx={'caption_seen':True,'timestamp':{'name':'vừa xong','url':P}}
  result,tool,finish=await self.run_case(ctx,old=[P])
  self.assertEqual(result['state'],'uncertain');finish.assert_not_awaited()
 async def test_author_preview_never_overrides_fresh_pending_submission_receipt(self):
  ctx={'caption_seen':True,'timestamp':{'name':'1 phút trước','url':P}}
  result,tool,finish=await self.run_case(ctx,snapshot='Bài viết của bạn đang chờ quản trị viên phê duyệt')
  self.assertEqual(result['state'],'pending');finish.assert_not_awaited()
 async def test_wrong_group_is_not_reloaded_or_commented(self):
  result,tool,finish=await self.run_case(current='https://www.facebook.com/groups/other/')
  self.assertEqual(result['state'],'uncertain');tool.assert_not_awaited();finish.assert_not_awaited()
 async def test_caption_in_feed_without_permalink_never_comments(self):
  context={'caption_seen':True,'timestamp':{'name':'vừa xong','url':G}}
  result,tool,finish=await self.run_case(context)
  self.assertEqual(result['state'],'uncertain');finish.assert_not_awaited()

 async def test_sixth_post_is_not_accepted_even_when_caption_matches(self):
  body='Exact unique full caption used for verification'
  cards=[{'key':str(i),'text':body if i==6 else 'other','url':P if i==6 else G+'posts/'+str(i)+'/'} for i in range(1,7)]
  context={'caption_seen':True,'timestamp':{'name':'vừa xong','url':P}}
  job={'url':G,'body':body,'submitted_at':time.time()}
  tool=AsyncMock();observe=AsyncMock(return_value='')
  with patch('desktop.foreground',return_value=[0,0,800,600]),patch('feed_confirmation.feed_posts',return_value=cards),patch('feed_confirmation.asyncio.sleep',new=AsyncMock()),patch('feed_confirmation.own_post_context',side_effect=[{},context]),patch('feed_confirmation.finish_post',new=AsyncMock()) as finish:
   result=await verify_feed(tool,observe,AsyncMock(return_value=G),1,job,'',lambda _:None)
  self.assertEqual(result['state'],'uncertain');self.assertEqual(result['feed_posts_checked'],5)
  finish.assert_not_awaited()
  self.assertFalse(any(c.args[0]=='Scroll' for c in tool.await_args_list))

 async def test_overlapping_cards_are_counted_once_and_stop_at_five(self):
  card=lambda i:{'key':str(i),'text':'other','url':G+'posts/'+str(i)+'/'}
  pages=[[card(1),card(2)],[card(2),card(3)],[card(3),card(4),card(5)]]
  job={'url':G,'body':'Exact unique full caption used for verification','submitted_at':time.time()}
  tool=AsyncMock();observe=AsyncMock(return_value='')
  with patch('desktop.foreground',return_value=[0,0,800,600]),patch('feed_confirmation.feed_posts',side_effect=pages),patch('feed_confirmation.asyncio.sleep',new=AsyncMock()),patch('feed_confirmation.own_post_context',return_value={}),patch('feed_confirmation.finish_post',new=AsyncMock()) as finish:
   result=await verify_feed(tool,observe,AsyncMock(return_value=G),1,job,'',lambda _:None)
  self.assertEqual(result['feed_posts_checked'],5);finish.assert_not_awaited()
  self.assertEqual(sum(c.args[0]=='Scroll' for c in tool.await_args_list),2)

 async def test_unreadable_cards_cannot_verify_an_unranked_caption(self):
  job={'url':G,'body':'Exact unique full caption used for verification','submitted_at':time.time()}
  context={'caption_seen':True,'timestamp':{'name':'vừa xong','url':P}}
  calls=[{}]+[context]*10
  with patch('desktop.foreground',return_value=[0,0,800,600]),patch('feed_confirmation.feed_posts',return_value=[]),patch('feed_confirmation.asyncio.sleep',new=AsyncMock()),patch('feed_confirmation.own_post_context',side_effect=calls),patch('feed_confirmation.finish_post',new=AsyncMock()) as finish:
   result=await verify_feed(AsyncMock(),AsyncMock(return_value=''),AsyncMock(return_value=G),1,job,'',lambda _:None)
  self.assertEqual(result['state'],'uncertain');finish.assert_not_awaited()


class RecentTimeTests(unittest.TestCase):
 def test_approximate_minute_labels_remain_fresh(self):
  from feed_confirmation import recent_post
  for label in ('khoảng 1 phút trước','about 1 minute ago','il y a environ 1 min','vừa xong'):
   self.assertTrue(recent_post({'timestamp':{'name':label}},{'submitted_at':time.time()}),label)
 def test_old_or_unknown_time_is_not_accepted(self):
  from feed_confirmation import recent_post
  for label in ('1 giờ trước','2 ngày trước','khoảng 30 phút trước',''):
   self.assertFalse(recent_post({'timestamp':{'name':label}},{'submitted_at':time.time()}),label)

class PlaceholderTimestampTests(unittest.IsolatedAsyncioTestCase):
 async def resolve(self,location=P,old=False,loc=(100,100)):
  from feed_confirmation import resolve_timestamp
  job={'url':G,'body':'Unique full caption','submitted_at':time.time(),'preexisting_caption_visible':old}
  context={'caption_seen':True,'timestamp':{'name':'khoảng 1 phút trước','role':'link','loc':list(loc),'url':G+'?tracking#placeholder'}}
  tool=AsyncMock();observe=AsyncMock()
  with patch('feed_confirmation.own_post_context',return_value=context),patch('desktop.foreground',return_value=[0,0,800,600]),patch('desktop.verify_live_target'),patch('feed_confirmation.asyncio.sleep',new=AsyncMock()):
   result=await resolve_timestamp(tool,observe,AsyncMock(return_value=location),1,job)
  return result,tool
 async def test_exact_post_timestamp_placeholder_can_resolve_actual_permalink(self):
  result,tool=await self.resolve()
  self.assertEqual(result,P);tool.assert_awaited_once_with('Click',{'loc':[100,100]})
 async def test_wrong_group_after_click_cannot_authorize_comment(self):
  result,tool=await self.resolve(location='https://www.facebook.com/groups/other/posts/123/')
  self.assertEqual(result,'')
 async def test_old_identical_caption_or_offscreen_timestamp_never_clicked(self):
  for args in ({'old':True},{'loc':(100,-50)}):
   result,tool=await self.resolve(**args)
   self.assertEqual(result,'');tool.assert_not_awaited()

class CollapsedCaptionTests(unittest.IsolatedAsyncioTestCase):
 async def test_expand_only_matching_first_five_card_then_verify_full_body(self):
  body='This is a unique long caption opening identifying the submitted post. Full ending and footer.'
  job={'url':G,'body':body,'submitted_at':time.time()}
  partial={'caption_seen':False,'timestamp':{'name':'vừa xong','url':P},'expand':[{'role':'button','name':'xem thêm','loc':[100,100]}]}
  full={'caption_seen':True,'timestamp':{'name':'vừa xong','url':P}}
  cards=[{'key':'one','text':body[:65].lower(),'url':P}]
  tool=AsyncMock()
  receipt={'state':'submitted','post_url':P,'receipt_verified':True,'verification_source':'post_permalink','comment_status':'sent'}
  with patch('desktop.foreground',return_value=[0,0,800,600]),patch('desktop.verify_live_target'),patch('receipts.read_post_receipt',return_value={}),patch('feed_confirmation.feed_posts',return_value=cards),patch('feed_confirmation.own_post_context',side_effect=[{},partial,full]),patch('feed_confirmation.asyncio.sleep',new=AsyncMock()),patch('post_link_check.verify',new=AsyncMock(return_value=receipt)) as verify:
   result=await verify_feed(tool,AsyncMock(return_value=''),AsyncMock(return_value=G),1,job,'',lambda _:None)
  self.assertEqual(result['state'],'submitted');verify.assert_awaited_once()
  self.assertTrue(any(c.args==('Click',{'loc':[100,100]}) for c in tool.await_args_list))
