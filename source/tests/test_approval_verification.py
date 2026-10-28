import unittest
from unittest.mock import AsyncMock,patch
from approval_verification import verify_pending
from desktop import valid_pending_receipt

G='https://www.facebook.com/groups/1042378071398974/'
P=G+'posts/1429437552693022/'
TOAST='Cảm ơn bạn đã đăng bài. Hệ thống đã gửi bài viết cho quản trị viên nhóm phê duyệt.'

class ActualSubmitToastTests(unittest.TestCase):
 def test_actual_facebook_toast_is_new_specific_pending_evidence(self):
  self.assertTrue(valid_pending_receipt('list item "'+TOAST+'"','Đang chờ quản trị viên phê duyệt 1 bài viết','Bắn Delta Force mà khó thế này thì mệt thật!'))
 def test_old_toast_or_caption_quote_cannot_confirm_new_pending(self):
  self.assertFalse(valid_pending_receipt(TOAST,TOAST,'Different body'))
  self.assertFalse(valid_pending_receipt(TOAST,'',TOAST))
 def test_aggregate_pending_count_is_not_specific_evidence(self):
  self.assertFalse(valid_pending_receipt('Đang chờ quản trị viên phê duyệt 2 bài viết','Đang chờ quản trị viên phê duyệt 1 bài viết','Different body'))

class ApprovalGateTests(unittest.IsolatedAsyncioTestCase):
 async def run_status(self,status):
  job={'state':'pending','url':G,'post_url':P,'body':'Exact submitted caption'}
  published={'state':'submitted','post_url':P,'receipt_verified':True,'verification_source':'post_permalink','comment_status':'sent'}
  with patch('own_content.verify',new=AsyncMock(return_value=status)) as read,patch('post_link_check.verify',new=AsyncMock(return_value=published)) as finish:
   result=await verify_pending(AsyncMock(),AsyncMock(),AsyncMock(),AsyncMock(),1,job,lambda _:None)
  return result,finish
 async def test_pending_author_preview_never_sends_comment(self):
  result,finish=await self.run_status({'state':'pending','post_url':P})
  self.assertEqual(result['comment_status'],'waiting_approval');finish.assert_not_awaited()
 async def test_only_exact_post_in_published_filter_allows_permalink_check_and_comment(self):
  result,finish=await self.run_status({'state':'submitted','post_url':P})
  self.assertEqual(result['comment_status'],'sent');finish.assert_awaited_once()
 async def test_removed_never_authorizes_comment(self):
  result,finish=await self.run_status({'state':'error','moderation_checked':True,'moderation_status':'removed','your_content_checked':True,'verification_source':'your_content'})
  self.assertEqual(result['moderation_status'],'removed');self.assertEqual(result['comment_status'],'skipped');finish.assert_not_awaited()
 async def test_pending_without_link_still_checks_exact_content(self):
  with patch('own_content.verify',new=AsyncMock(return_value={'state':'error','moderation_status':'removed'})) as read,patch('post_link_check.verify',new=AsyncMock()) as finish:
   result=await verify_pending(AsyncMock(),AsyncMock(),AsyncMock(),AsyncMock(),1,{'url':G,'body':'Frozen exact caption'},lambda _:None)
  read.assert_awaited_once();finish.assert_not_awaited();self.assertEqual(result['moderation_status'],'removed')
 async def test_other_published_post_or_missing_status_cannot_authorize_comment(self):
  for status in ({'state':'submitted','post_url':G+'posts/999/'},{'your_content_checked':True}):
   result,finish=await self.run_status(status)
   self.assertEqual(result['comment_status'],'waiting_approval');finish.assert_not_awaited()

class ActiveFilterCardTests(unittest.TestCase):
 def match(self,hidden=False):
  import sys,types
  from own_content import read_matches
  class Node:
   IsOffscreen=False
   BoundingRectangle=types.SimpleNamespace(left=10,top=20,right=110,bottom=100)
   def __init__(self,name='',control='GroupControl',children=(),href='',role=''):
    self.Name=name;self.ControlTypeName=control;self.children=children;self.href=href;self.AriaRole=role
   def GetChildren(self):return self.children
   def GetLegacyIAccessiblePattern(self):return types.SimpleNamespace(Value=self.href)
  caption='Exact unique caption identifying the submitted Delta Force post'
  text=Node(caption,'TextControl');text.IsOffscreen=hidden
  article=Node(children=[text,Node('Vừa xong','HyperlinkControl',href=P),Node('Hành động đối với bài viết này','ButtonControl')],role='article')
  root=Node(control='DocumentControl',children=[article])
  com=types.ModuleType('comtypes');com.CoInitialize=lambda:None;com.CoUninitialize=lambda:None
  uia=types.ModuleType('windows_mcp.uia');uia.ControlFromHandle=lambda _:root
  package=types.ModuleType('windows_mcp');package.__path__=[];package.uia=uia
  with patch.dict(sys.modules,{'comtypes':com,'windows_mcp':package,'windows_mcp.uia':uia}):
   return read_matches(1,{'body':caption,'url':G},'submitted')
 def test_hidden_card_from_inactive_filter_cannot_prove_publication(self):
  self.assertEqual(self.match(hidden=True),[])
  self.assertEqual(self.match()[0]['post_url'],P)
