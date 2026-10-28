import tempfile,unittest,sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from store import Store
from receipts import post_url
class ReviewTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.s=Store(Path(self.tmp.name)/'t.db');self.g=self.s.add_group('https://www.facebook.com/groups/1451891096876445/','Test',link_policy='allow');self.s.enable_group(self.g,True)
 def tearDown(self):self.tmp.cleanup()
 def record(self):
  job={'id':99,'group_id':self.g,'group_name':'Test','url':'https://www.facebook.com/groups/1451891096876445/'}
  return self.s.record_result(job,{'state':'submitted','detail':'Evidence','post_url':job['url']+'posts/123/','photo':'receipt.png'})
 def test_review_persists_and_recording_twice_does_not_duplicate(self):
  r=self.record();self.assertEqual(self.record(),r)
  row=self.s.rows('SELECT * FROM group_reviews')[0];self.assertTrue(row['post_url'].endswith('/posts/123/'));self.assertEqual(row['photo'],'receipt.png')
 def test_keep_retains_group_and_enabled_state(self):
  self.s.enable_group(self.g,False);r=self.record();self.s.decide_review(r,'keep')
  row=self.s.rows('SELECT * FROM groups')[0];self.assertEqual(row['enabled'],0);self.assertEqual(row['deleted'],0)
 def test_delete_keeps_history_and_cancels_only_future_jobs(self):
  cid=self.s.content('test');self.s.plan(cid,30)
  r=self.record();self.assertEqual(self.s.decide_review(r,'delete'),'delete');self.assertEqual(self.s.decide_review(r,'keep'),'delete')
  self.assertEqual(self.s.rows('SELECT deleted,enabled FROM groups')[0],{'deleted':1,'enabled':0})
  self.assertTrue(all(j['state']=='cancelled' for j in self.s.rows('SELECT * FROM jobs')))
  with self.assertRaises(ValueError):self.s.enable_group(self.g,True)
 def test_notify_retains_buttons_and_caption(self):
  self.s.notify('test','photo.png',{'inline_keyboard':[]},'Success');row=self.s.rows('SELECT * FROM outbox')[0];self.assertEqual(row['photo_caption'],'Success');self.assertEqual(row['text_sent'],0)
 def test_url_requires_same_group_and_real_post_id(self):
  g='https://www.facebook.com/groups/1451891096876445/'
  self.assertTrue(post_url(g+'permalink/123/?ref=share',g).endswith('/posts/123/'))
  for url in (g,'https://facebook.com.evil/groups/1451891096876445/posts/123/','https://www.facebook.com/groups/other/posts/123/','https://www.facebook.com@evil/groups/1451891096876445/posts/123/'):
   self.assertEqual(post_url(url,g),'')
class ReceiptTreeTests(unittest.TestCase):
 def test_group_post_with_split_footer_requires_exact_full_text_and_unique_link(self):
  import sys,types
  from receipts import read_post_receipt
  class Node:
   def __init__(self,name='',kind='TextControl',children=(),url=''):
    self.Name=name;self.AriaRole='';self.children=children;self.url=url;self.ControlTypeName=kind
   def GetChildren(self):return self.children
   def GetLegacyIAccessiblePattern(self):return types.SimpleNamespace(Value=self.url)
  group='https://www.facebook.com/groups/test/'
  caption='Full approved caption with a separate footer\n\nDiscord info'
  post=Node(kind='GroupControl',children=[Node('Full approved caption with a separate footer'),Node('Discord info'),Node('Actions for this post',kind='ButtonControl'),Node('Just now',kind='HyperlinkControl',url=group+'posts/12/')])
  editor=Node(kind='EditControl',children=[Node(caption)])
  root=Node(kind='WindowControl',children=[editor,post])
  fake=types.ModuleType('windows_mcp.uia');fake.ControlFromHandle=lambda _:root
  com=types.ModuleType('comtypes');com.CoInitialize=lambda:None;com.CoUninitialize=lambda:None
  with patch.dict(sys.modules,{'windows_mcp.uia':fake,'comtypes':com}),patch('windows_mcp.uia',fake,create=True):
   self.assertEqual(read_post_receipt(1,caption,group)['post_url'],group+'posts/12/')
   self.assertEqual(read_post_receipt(1,caption+' not visible',group),{})
   root.children=[editor]
   self.assertEqual(read_post_receipt(1,caption,group),{})
 def test_link_must_share_article_with_exact_caption(self):
  import sys,types
  from receipts import read_post_receipt
  class Node:
   def __init__(self,name='',role='',children=(),url=''):
    self.Name=name;self.AriaRole=role;self.children=children;self.url=url
    self.ControlTypeName='HyperlinkControl' if url else 'TextControl'
   def GetChildren(self):return self.children
   def GetLegacyIAccessiblePattern(self):return types.SimpleNamespace(Value=self.url)
  group='https://www.facebook.com/groups/test/'
  wrong=Node(role='article',children=[Node('Other post'),Node(url=group+'posts/1/')])
  right=Node(role='article',children=[Node('Exact caption'),Node(url=group+'posts/2/')])
  fake=types.ModuleType('windows_mcp.uia');fake.ControlFromHandle=lambda root:Node(children=[wrong,right])
  com=types.ModuleType('comtypes');com.CoInitialize=lambda:None;com.CoUninitialize=lambda:None
  with patch.dict(sys.modules,{'windows_mcp.uia':fake,'comtypes':com}),patch('windows_mcp.uia',fake,create=True):
   self.assertEqual(read_post_receipt(1,'Exact caption',group)['post_url'],group+'posts/2/')
   self.assertEqual(read_post_receipt(1,'Missing caption',group),{})

if __name__=='__main__':unittest.main()
