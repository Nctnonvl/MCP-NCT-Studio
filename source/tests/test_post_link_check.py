import unittest
from unittest.mock import AsyncMock,patch
from post_link_check import verify
G='https://www.facebook.com/groups/linktest/';P=G+'posts/12/'
class LinkCheckTests(unittest.IsolatedAsyncioTestCase):
 async def run_case(self,context=None,location=P,link=P):
  tool=AsyncMock();observe=AsyncMock(return_value='')
  result={'state':'submitted','post_url':P,'receipt_verified':True,'verification_source':'post_permalink','comment_status':'sent'}
  with patch('post_link_check.asyncio.sleep',new=AsyncMock()),patch('post_link_check.own_post_context',return_value=context or {}),patch('post_link_check.finish_post',new=AsyncMock(return_value=result)) as finish,patch('post_link_check.open_observed_post',new=AsyncMock(return_value=True)) as open_post:
   value=await verify(tool,observe,AsyncMock(return_value=location),1,{'url':G,'body':'Full approved caption'},link,lambda _:None)
  return value,tool,finish,open_post
 async def test_reload_permalink_before_exact_caption_and_comment(self):
  value,tool,finish,_=await self.run_case({'caption_seen':True,'outside_texts':['Full approved caption']})
  self.assertEqual(value['state'],'submitted');finish.assert_awaited_once()
  tool.assert_awaited_once_with('Shortcut',{'shortcut':'ctrl+r'})
 async def test_pending_status_never_comments(self):
  value,_,finish,_=await self.run_case({'caption_seen':True,'outside_texts':['Full approved caption','Bài viết của bạn đang chờ quản trị viên phê duyệt']})
  self.assertEqual(value['state'],'pending');finish.assert_not_awaited()
 async def test_wrong_caption_never_comments(self):
  value,_,finish,_=await self.run_case({'caption_seen':False})
  self.assertEqual(value['state'],'uncertain');finish.assert_not_awaited()
 async def test_wrong_group_link_is_rejected_without_input(self):
  value,tool,finish,_=await self.run_case(link='https://www.facebook.com/groups/other/posts/12/')
  self.assertEqual(value['state'],'uncertain');tool.assert_not_awaited();finish.assert_not_awaited()
 async def test_deleted_or_redirected_link_never_comments(self):
  value,_,finish,_=await self.run_case({'caption_seen':True},location=G)
  self.assertEqual(value['state'],'uncertain');finish.assert_not_awaited()
