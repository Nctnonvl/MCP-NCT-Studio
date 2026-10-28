"""Your content verification uses fake navigation and never posts or comments."""
import sys,unittest
from pathlib import Path
from unittest.mock import AsyncMock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import own_content
from final_report import render

GROUP='https://www.facebook.com/groups/test/'

class ContentTests(unittest.TestCase):
 def test_group_menu_excludes_post_body_more_buttons(self):
  share={'role':'button','name':'chia sẻ nhóm','loc':[500,300]}
  more={'role':'button','name':'xem thêm','loc':[700,340]}
  post_more={'role':'button','name':'xem thêm','loc':[400,600]}
  self.assertIs(own_content.group_menu([share,more,post_more]),more)
  self.assertIsNone(own_content.group_menu([share,more,{**more,'loc':[710,350]}]))
 def test_status_requires_correct_group_and_actual_filter_route(self):
  self.assertEqual(own_content.page_status(GROUP+'my_pending_content/',GROUP),'pending')
  self.assertEqual(own_content.page_status(GROUP+'my_posted_content',GROUP),'submitted')
  for url in ['https://evil.example/groups/test/my_posted_content/',GROUP.replace('test','other')+'my_posted_content/',GROUP]:self.assertEqual(own_content.page_status(url,GROUP),'')
 def test_view_in_group_link_uses_observed_single_post_id(self):
  self.assertEqual(own_content.card_post_url(GROUP+'?multi_permalinks=123&tracking=ignored',GROUP),GROUP+'posts/123/')
  for suffix in ['?multi_permalinks=123,456','?multi_permalinks=123&multi_permalinks=456','?multi_permalinks=bad']:
   self.assertEqual(own_content.card_post_url(GROUP+suffix,GROUP),'')
 def test_old_or_ambiguous_cards_do_not_prove_new_post(self):
  a={'state':'pending','recent':True};b={'state':'submitted','recent':True,'post_url':GROUP+'posts/1/'}
  self.assertIsNone(own_content.choose_match([a,b]))
  self.assertIsNone(own_content.choose_match([{**b,'recent':False}]))
  self.assertEqual(own_content.choose_match([a,b],b['post_url']),b)
 def test_telegram_uses_actual_identity_instead_of_composer_selection(self):
  job={'id':1,'group_name':'Test','url':GROUP}
  text=render(job,{'state':'submitted','posting_identity_effective':'anonymous','identity_verified':True,'post_identity_verified':True,'post_identity':'named','post_actor':'Test Name','verification_source':'your_content'})
  self.assertIn('Test Name',text);self.assertNotIn('Danh tính: ẩn danh',text)
  text=render(job,{'state':'pending','post_identity_verified':False})
  self.assertIn('Chờ duyệt',text);self.assertIn('chưa xác minh',text)

class VerifyTests(unittest.IsolatedAsyncioTestCase):
 async def run_case(self,cards,pending_hint=False,fail_restore=False,canonical=''):
  current=[GROUP]
  raw='''UI Tree:
(500,300) button "Chia sẻ nhóm" [action: click]
(700,340) button "Xem thêm" [action: click]
(700,380) menu item "Nội dung của bạn" [action: click]
(30,100) link "Đang chờ" [action: click]
(30,130) link "Đã đăng Chỉ báo nội dung mới 1 bài viết" [action: click]
(30,160) link "Bị từ chối" [action: click]
(30,190) link "Đã gỡ" [action: click]'''
  if canonical:raw+='\n(100,90) link "Test" [action: click]'
  calls=[]
  async def tool(name,args):
   calls.append((name,args));loc=args['loc']
   route={ (700,380):'my_pending_content/',(30,100):'my_pending_content/',(30,130):'my_posted_content/',(30,160):'my_declined_content/',(30,190):'my_removed_content/' }.get(tuple(loc))
   if fail_restore and tuple(loc)==(30,100):route=None
   if route:current[0]=(canonical or GROUP)+route
  async def navigate():current[0]=GROUP
  async def location():return current[0]
  job={'url':GROUP,'group_name':'Test','body':'Exact caption to verify','posting_nickname':''}
  def read(root,job,status):
   self.read_groups=job.get('verification_groups',[])
   return cards.get(status,[])
  with patch('desktop.verify_live_target'),patch('own_content.read_matches',side_effect=read),patch('own_content.asyncio.sleep',new=AsyncMock()):
   result=await own_content.verify(tool,AsyncMock(return_value=raw),location,navigate,42,job,{'state':'pending'} if pending_hint else {},lambda s:None)
  self.assertTrue(all(name=='Click' for name,args in calls))
  self.final_url=current[0]
  return result
 async def test_pending_card_is_not_reported_as_published(self):
  result=await self.run_case({'pending':[{'state':'pending','recent':True,'post_identity':'anonymous','post_identity_verified':True,'post_actor':'người tham gia ẩn danh'}]})
  self.assertEqual(result['state'],'pending');self.assertEqual(result['comment_status'],'skipped')
 async def test_posted_card_proves_status_and_identity(self):
  result=await self.run_case({'submitted':[{'state':'submitted','recent':True,'post_url':GROUP+'posts/123/','post_identity':'anonymous','post_identity_verified':True}]})
  self.assertEqual(result['state'],'submitted');self.assertEqual(result['verification_source'],'your_content')
 async def test_removed_exact_card_reports_warning_not_pending(self):
  result=await self.run_case({'removed':[{'state':'removed','recent':True,'post_identity':'anonymous','post_identity_verified':True}]})
  self.assertEqual(result['state'],'error');self.assertEqual(result['moderation_status'],'removed')
  self.assertTrue(result['moderation_checked']);self.assertEqual(result['comment_status'],'skipped')
  text=render({'id':177,'content_id':117,'group_name':'Test','url':GROUP},result)
  self.assertIn('Bài đã bị gỡ',text);self.assertNotIn('Chờ duyệt',text)
 async def test_unknown_is_not_a_publishing_success(self):
  result=await self.run_case({})
  self.assertNotIn('state',result);self.assertTrue(result['your_content_checked'])
 async def test_unmatched_pending_receipt_restores_pending_filter_before_photo(self):
  result=await self.run_case({},pending_hint=True)
  self.assertNotIn('state',result)
  self.assertEqual(result['receipt_filter'],'pending');self.assertTrue(result['receipt_photo_allowed'])
  self.assertEqual(own_content.page_status(self.final_url,GROUP),'pending')
 async def test_failed_pending_filter_restoration_disallows_wrong_removed_photo(self):
  result=await self.run_case({},pending_hint=True,fail_restore=True)
  self.assertFalse(result['receipt_photo_allowed']);self.assertNotIn('receipt_filter',result)
 async def test_slug_redirect_to_observed_numeric_group_restores_pending_photo(self):
  canonical='https://www.facebook.com/groups/2481112905526616/'
  result=await self.run_case({'pending':[{'state':'pending','recent':True}]},pending_hint=True,canonical=canonical)
  self.assertEqual(result['state'],'pending');self.assertTrue(result['receipt_photo_allowed'])
  self.assertIn(canonical,self.read_groups)
  self.assertEqual(own_content.page_status(self.final_url,canonical),'pending')

if __name__=='__main__':unittest.main()

class ShiftedGroupMenuTests(unittest.TestCase):
 def test_pending_banner_moves_group_menu_below_share_row(self):
  from own_content import group_menu
  more={'role':'button','name':'xem thêm','loc':[911,446]}
  targets=[{'role':'button','name':'chia sẻ nhóm','loc':[673,294]},{'role':'button','name':'tìm kiếm trong nhóm này','loc':[855,446]},more,{'role':'button','name':'xem thêm','loc':[599,446]}]
  self.assertEqual(group_menu(targets),more)

class AgeTests(unittest.TestCase):
 def test_numeric_destination_requires_matching_group_back_link(self):
  url='https://www.facebook.com/groups/2481112905526616/my_pending_content'
  job={'group_name':'MUA BÁN ACC LIÊN MINH HUYỀN THOẠI 🇻🇳'}
  target={'role':'link','name':own_content.clean(job['group_name']),'loc':[100,90]}
  nav={'role':'link','name':'đang chờ','loc':[30,200]}
  self.assertEqual(own_content.observed_content_group(url,[target,nav,{**target,'loc':[500,450]}],job),'https://www.facebook.com/groups/2481112905526616/')
  for bad in (url.replace('www.facebook.com','evil.example'),url.replace('https:','http:')):
   self.assertEqual(own_content.observed_content_group(bad,[target,nav],job),'')
  self.assertEqual(own_content.observed_content_group(url,[],job),'')
  self.assertEqual(own_content.observed_content_group(url,[target,target,nav],job),'')
 def test_age_matches_attempt_time_not_generic_recent(self):
  import time
  job={'attempted_at':time.time()-3600}
  self.assertTrue(own_content.age_matches('1 giờ',job))
  self.assertFalse(own_content.age_matches('Vừa xong',job))
  self.assertFalse(own_content.age_matches('2 ngày',job))
 def test_removed_requires_exact_group_route(self):
  self.assertEqual(own_content.page_status(GROUP+'my_removed_content',GROUP),'removed')
  self.assertEqual(own_content.page_status(GROUP.replace('test','wrong')+'my_removed_content',GROUP),'')
