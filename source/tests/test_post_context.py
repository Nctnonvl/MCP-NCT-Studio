import sys,types,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from post_context import own_post_context
class ContextTests(unittest.TestCase):
 def test_modal_footer_is_included_and_comment_time_is_not_post_time(self):
  caption='This is the exact caption identifying our own newly published post'
  class Node:
   def __init__(self,name='',role='group',control='GroupControl',children=(),href=''):
    self.Name=name;self.AriaRole=role;self.ControlTypeName=control;self.children=children;self.href=href;self.IsOffscreen=False;self.BoundingRectangle=types.SimpleNamespace(left=10,top=20,right=110,bottom=40)
   def GetChildren(self):return self.children
   def GetLegacyIAccessiblePattern(self):return types.SimpleNamespace(Value=self.href)
  header=Node(children=[Node(caption,'description','TextControl'),Node('Vừa xong','link','HyperlinkControl',href='https://www.facebook.com/groups/test/posts/1/'),Node('Hành động đối với bài viết này','button','ButtonControl')])
  footer=Node(children=[Node('Viết bình luận công khai…','textbox','EditControl')])
  # Facebook may leave comment timestamps as group placeholders too.
  comment=Node(children=[Node('1 phút','link','HyperlinkControl',href='https://www.facebook.com/groups/test/?placeholder'),Node('https://example.com','link','HyperlinkControl')])
  root=Node('Bài viết của người dùng',children=[header,comment,footer])
  com=types.ModuleType('comtypes');com.CoInitialize=lambda:None;com.CoUninitialize=lambda:None
  uia=types.ModuleType('windows_mcp.uia');uia.ControlFromHandle=lambda h:root
  package=types.ModuleType('windows_mcp');package.__path__=[];package.uia=uia
  with patch.dict(sys.modules,{'windows_mcp':package,'windows_mcp.uia':uia,'comtypes':com}):
   ctx=own_post_context(1,caption)
   self.assertEqual(len(ctx['editors']),1);self.assertEqual(ctx['timestamp']['name'],'vừa xong');self.assertIn('https://example.com',ctx['outside_texts'])
   self.assertEqual(own_post_context(1,'A different caption which is not the current post'),{})
if __name__=='__main__':unittest.main()

class FeedContextTests(unittest.TestCase):
 def test_same_opening_selects_only_the_complete_matching_caption(self):
  prefix='This is a long opening shared by two different posts in this group. '
  caption=prefix+'The second post has the correct complete content.'
  class Node:
   IsOffscreen=False;IsEnabled=True;AriaRole='group'
   BoundingRectangle=types.SimpleNamespace(left=10,top=20,right=110,bottom=40)
   def __init__(self,name='',control='GroupControl',children=(),href=''):
    self.Name=name;self.ControlTypeName=control;self.children=children;self.href=href
   def GetChildren(self):return self.children
   def GetLegacyIAccessiblePattern(self):return types.SimpleNamespace(Value=self.href)
  def article(body,url):return Node(children=[Node(body,'TextControl'),Node('Vừa xong','HyperlinkControl',href=url),Node('Hành động đối với bài viết này','ButtonControl'),Node('Viết bình luận công khai…','EditControl')])
  root=Node(children=[article(prefix+'Different ending.','https://www.facebook.com/groups/test/posts/1/'),article(caption,'https://www.facebook.com/groups/test/posts/2/')])
  com=types.ModuleType('comtypes');com.CoInitialize=lambda:None;com.CoUninitialize=lambda:None
  uia=types.ModuleType('windows_mcp.uia');uia.ControlFromHandle=lambda h:root
  package=types.ModuleType('windows_mcp');package.__path__=[];package.uia=uia
  with patch.dict(sys.modules,{'windows_mcp':package,'windows_mcp.uia':uia,'comtypes':com}):
   ctx=own_post_context(1,caption)
   from post_context import feed_posts
   cards=feed_posts(1,'https://www.facebook.com/groups/test/')
   self.assertEqual([card['url'] for card in cards],['https://www.facebook.com/groups/test/posts/1/','https://www.facebook.com/groups/test/posts/2/'])
   self.assertIn(caption.casefold(),cards[1]['text'])
  self.assertTrue(ctx['caption_seen']);self.assertTrue(ctx['timestamp']['url'].endswith('/2/'))
