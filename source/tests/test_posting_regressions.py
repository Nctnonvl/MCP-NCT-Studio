import unittest,sys,types,tempfile
from pathlib import Path
from unittest.mock import patch,AsyncMock
from receipts import read_post_receipt
from post_context import own_post_context
from post_comments import open_observed_post,finish_post
from desktop import valid_pending_receipt
G='https://www.facebook.com/groups/test/'
P=G+'posts/123/'
BODY='The exact full caption identifying this published post'
class Node:
 IsOffscreen=False;IsEnabled=True;AriaRole=''
 BoundingRectangle=types.SimpleNamespace(left=10,top=10,right=120,bottom=60)
 def __init__(self,name='',role='GroupControl',children=(),url=''):
  self.Name=name;self.ControlTypeName=role;self.children=children;self.url=url;self.reads=0
 def GetChildren(self):
  self.reads+=1
  if self.reads>1:raise AssertionError('Duplicate remote tree traversal')
  return self.children
 def GetLegacyIAccessiblePattern(self):return types.SimpleNamespace(Value=self.url)
 def GetValuePattern(self):return types.SimpleNamespace(Value='')
def tree():
 header=Node(children=[Node(BODY,'TextControl'),Node('Just now','HyperlinkControl',url=P),Node('Actions for this post by My Name','ButtonControl')])
 return Node(children=[header,Node('Write a comment','EditControl')])
def modules(root):
 com=types.ModuleType('comtypes');com.CoInitialize=lambda:None;com.CoUninitialize=lambda:None
 uia=types.ModuleType('windows_mcp.uia');uia.ControlFromHandle=lambda _:root
 pkg=types.ModuleType('windows_mcp');pkg.__path__=[];pkg.uia=uia
 return {'comtypes':com,'windows_mcp':pkg,'windows_mcp.uia':uia}
class ReaderRegressionTests(unittest.TestCase):
 def test_context_reuses_one_remote_traversal_across_parent_scopes(self):
  root=tree()
  with patch.dict(sys.modules,modules(root)):ctx=own_post_context(1,BODY)
  self.assertTrue(ctx['caption_seen']);self.assertEqual(len(ctx['editors']),1)
 def test_receipt_reuses_one_remote_traversal(self):
  root=tree()
  with patch.dict(sys.modules,modules(root)):result=read_post_receipt(1,BODY,G)
  self.assertEqual(result['post_url'],P)
 def test_partial_tree_never_proves_success(self):
  from uia_snapshot import capture
  entries,complete=capture(tree(),limit=1)
  self.assertFalse(complete)
 def test_pending_counts_are_not_individual_submission_receipts(self):
  for notice in ('2 bài viết của bạn đang chờ duyệt','Your posts are pending approval','Các bài viết của bạn đang chờ duyệt'):
   self.assertFalse(valid_pending_receipt(notice,'',BODY))
  self.assertTrue(valid_pending_receipt('Bài viết ẩn danh của bạn đang chờ duyệt','',BODY))
  self.assertFalse(valid_pending_receipt('Bài viết ẩn danh của bạn đang chờ duyệt','Bài viết ẩn danh của bạn đang chờ duyệt',BODY))
class NavigationRegressionTests(unittest.IsolatedAsyncioTestCase):
 async def test_time_label_can_change_without_coordinate_click(self):
  clipboard=['original'];clip=types.SimpleNamespace(paste=lambda:clipboard[0],copy=lambda v:clipboard.__setitem__(0,v))
  tool=AsyncMock()
  with patch.dict(sys.modules,{'pyperclip':clip}),patch('post_comments.asyncio.sleep',new=AsyncMock()):
   ok=await open_observed_post(tool,AsyncMock(),{'name':'about a minute ago','url':P,'loc':[10,20]},G)
  self.assertTrue(ok);self.assertEqual(clipboard[0],'original')
  self.assertEqual([c.args[0] for c in tool.await_args_list],['Shortcut']*3)
 async def test_wrong_group_link_never_navigates(self):
  tool=AsyncMock();self.assertFalse(await open_observed_post(tool,AsyncMock(),{'url':P.replace('/test/','/other/')},G));tool.assert_not_awaited()
 async def test_final_ledger_failure_does_not_turn_published_post_into_error(self):
  with tempfile.TemporaryDirectory() as d:
   Path(d,'work').mkdir()
   job={'id':99,'data_dir':d,'url':G,'body':BODY,'comment_text':'A test comment','comment_policy':'allowed'}
   editor={'name':'write a comment','role':'edit','loc':[40,40]}
   base={'caption_seen':True,'timestamp':{'url':P},'editors':[editor],'outside_texts':[]}
   after={**base,'outside_texts':['a test comment']};tool=AsyncMock();original=Path.write_text;writes=[0]
   def write(path,*a,**kw):
    if path.name=='comment-99.json':
     writes[0]+=1
     if writes[0]==2:raise OSError('disk full')
    return original(path,*a,**kw)
   with patch('desktop.foreground'),patch('desktop.verify_live_target'),patch('post_comments.own_post_context',side_effect=[base,base,base,after]),patch('post_comments.asyncio.sleep',new=AsyncMock()),patch.object(Path,'write_text',write):
    result=await finish_post(tool,AsyncMock(return_value=''),AsyncMock(return_value=P),1,job,{},True)
   self.assertEqual(result['state'],'submitted');self.assertEqual(result['comment_status'],'sent');self.assertIn('comment_ledger_error',result)

 async def test_editor_below_photo_is_scrolled_into_view_before_comment(self):
  with tempfile.TemporaryDirectory() as d:
   Path(d,'work').mkdir()
   job={'id':98,'data_dir':d,'url':G,'body':BODY,'comment_text':'A test comment','comment_policy':'allowed'}
   base={'caption_seen':True,'timestamp':{'url':P},'editors':[],'outside_texts':[]}
   editor={'name':'write a comment','role':'edit','loc':[40,40]}
   ready={**base,'editors':[editor]};after={**ready,'outside_texts':['a test comment']};tool=AsyncMock()
   with patch('desktop.foreground',return_value=[0,0,800,600]),patch('desktop.verify_live_target'),patch('post_comments.own_post_context',side_effect=[base,base,base,ready,after]),patch('post_comments.asyncio.sleep',new=AsyncMock()):
    result=await finish_post(tool,AsyncMock(return_value=''),AsyncMock(return_value=P),1,job,{},True)
   self.assertEqual(result['state'],'submitted');self.assertEqual(result['comment_status'],'sent')
   self.assertEqual([c.args[0] for c in tool.await_args_list],['Scroll','Type'])

 async def test_layout_change_reobserves_editor_then_sends_exactly_once(self):
  with tempfile.TemporaryDirectory() as d:
   Path(d,'work').mkdir()
   job={'id':97,'data_dir':d,'url':G,'body':BODY,'comment_text':'A test comment','comment_policy':'allowed'}
   old={'name':'write a comment','role':'edit','loc':[40,40]}
   new={**old,'loc':[70,70]}
   base={'caption_seen':True,'timestamp':{'url':P},'editors':[old],'outside_texts':[]}
   fresh={**base,'editors':[new]};after={**fresh,'outside_texts':['a test comment']};tool=AsyncMock()
   with patch('desktop.foreground'),patch('desktop.verify_live_target',side_effect=[RuntimeError('layout changed'),None]),patch('post_comments.own_post_context',side_effect=[base,base,base,fresh,after]),patch('post_comments.asyncio.sleep',new=AsyncMock()):
    result=await finish_post(tool,AsyncMock(return_value=''),AsyncMock(return_value=P),1,job,{},True)
   self.assertEqual(result['state'],'submitted');self.assertEqual(result['comment_status'],'sent')
   tool.assert_awaited_once_with('Type',{'loc':[70,70],'text':'A test comment','clear':True,'press_enter':True})
