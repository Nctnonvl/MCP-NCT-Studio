import unittest
from unittest.mock import AsyncMock,patch
from post_comments import finish_post
G='https://www.facebook.com/groups/test/'
P=G+'posts/123/'
class ReceiptConfirmationTests(unittest.IsolatedAsyncioTestCase):
 async def run_case(self,target_url=P,full_caption=True):
  partial={'caption_seen':False,'expand':[],'timestamp':{'url':target_url,'loc':[50,60]}}
  full={'caption_seen':full_caption,'timestamp':{'url':P,'loc':[50,60]},'post_actor':'Người tham gia ẩn danh','editors':[]}
  tool=AsyncMock();observe=AsyncMock();current=AsyncMock(return_value=P)
  with patch('desktop.foreground'),patch('desktop.verify_live_target'),patch('post_comments.own_post_context',side_effect=[partial,full,full]),patch('post_comments.open_observed_post',new=AsyncMock(return_value=True)):
   result=await finish_post(tool,observe,current,1,{'id':1,'url':G,'body':'Exact approved full caption','comment_text':''},{},True)
  return result,tool
 async def test_collapsed_feed_opens_observed_link_and_verifies_identity(self):
  result,tool=await self.run_case()
  self.assertEqual(result['state'],'submitted');self.assertEqual(result['post_url'],P)
  self.assertTrue(result['post_identity_verified']);self.assertEqual(result['post_identity'],'anonymous')
  tool.assert_not_awaited()
 async def test_wrong_group_link_is_never_opened(self):
  result,tool=await self.run_case('https://www.facebook.com/groups/other/posts/123/')
  self.assertEqual(result,{});tool.assert_not_awaited()
 async def test_prefix_alone_never_proves_success(self):
  result,tool=await self.run_case(full_caption=False)
  self.assertEqual(result,{});tool.assert_not_awaited()


class VerifiedPostGateTests(unittest.TestCase):
 def test_model_success_alone_never_skips_management(self):
  from receipts import has_verified_post
  self.assertFalse(has_verified_post({'state':'submitted','post_url':P},G))
 def test_full_caption_permalink_receipt_skips_management(self):
  from receipts import has_verified_post
  r={'state':'submitted','post_url':P,'receipt_verified':True,'verification_source':'post_permalink'}
  self.assertTrue(has_verified_post(r,G))
  self.assertFalse(has_verified_post({**r,'post_url':P.replace('/test/','/other/')},G))
  self.assertFalse(has_verified_post({**r,'state':'pending'},G))
 def test_verified_feed_allows_commenting_in_place_without_permalink(self):
  from receipts import has_verified_post
  self.assertTrue(has_verified_post({'state':'submitted','receipt_verified':True,'verification_source':'group_feed'},G))
