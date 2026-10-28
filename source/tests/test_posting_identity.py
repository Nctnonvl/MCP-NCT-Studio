"""Identity evidence and frozen group policy; mocked UI only, no Facebook publishing."""
import sys,tempfile,unittest
from unittest.mock import patch,AsyncMock
from types import SimpleNamespace
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from posting_identity import decision,validate
from store import Store

def target(name,role='checkbox',**kw):return {'id':0,'name':name,'role':role,**kw}

class IdentityTests(unittest.TestCase):
 def test_anonymous_requires_checked_state_in_composer(self):
  for t in [target('post anonymously'),target('post anonymously',checked=False),target('post anonymously',checked=True)]:
   self.assertFalse(decision('anonymous','',[t])['verified'])
  self.assertTrue(decision('anonymous','',[target('post anonymously',checked=True,composer_scope=True)])['verified'])
 def test_vi_en_fr_explicit_unchecked_switch_selected_once(self):
  for name in ['đăng ẩn danh','post anonymously','publier anonymement']:
   t=target(name,checked=False,composer_scope=True)
   self.assertEqual(decision('anonymous','',[t]),{'verified':False,'target':0})
 def test_caption_does_not_authorize_anonymous_button_as_publish(self):
  targets=[target('post anonymously','button'),target('create post','edit')]
  self.assertNotIn('target',decision('anonymous','',targets))
 def test_unknown_and_feed_labels_never_count_as_identity(self):
  self.assertFalse(decision('anonymous','',[target('anonymous member','button')])['verified'])
  self.assertFalse(decision('nickname','Player One',[target('player one','button')])['verified'])
 def test_nickname_exact_scoped_author_or_selected_option_only(self):
  self.assertTrue(decision('nickname','Player One',[target('player one','button',composer_scope=True)])['verified'])
  self.assertFalse(decision('nickname','Player One',[target('player one','radiobutton',composer_scope=True,selected=False)])['verified'])
  self.assertFalse(decision('nickname','Player One',[target('player one extra','button',composer_scope=True)])['verified'])
 def test_profile_fallback_needs_consent_and_is_forbidden_after_submit(self):
  from posting_identity import profile_fallback_decision
  editor=target('create post','edit',composer_scope=True)
  self.assertFalse(profile_fallback_decision('auto',[editor])['verified'])
  self.assertFalse(profile_fallback_decision('auto',[editor],True,True)['verified'])
  self.assertTrue(profile_fallback_decision('auto',[editor],True,False)['verified'])
  self.assertFalse(profile_fallback_decision('nickname',[editor],True,False)['verified'])
 def test_profile_fallback_turns_off_anonymous_and_rechecks_editor(self):
  from posting_identity import profile_fallback_decision
  on=target('post anonymously',checked=True,composer_scope=True)
  self.assertEqual(profile_fallback_decision('anonymous',[on],True),{'verified':False,'target':0})
  off={**on,'checked':False};editor={**target('create post','edit',composer_scope=True),'id':1}
  self.assertFalse(profile_fallback_decision('anonymous',[off],True)['verified'])
  self.assertTrue(profile_fallback_decision('anonymous',[off,editor],True)['verified'])
  self.assertFalse(profile_fallback_decision('anonymous',[off,{**editor,'anonymous_composer_scope':True}],True)['verified'])
 def test_profile_fallback_rejects_feed_and_ambiguous_controls(self):
  from posting_identity import profile_fallback_decision
  self.assertFalse(profile_fallback_decision('auto',[target('create post','edit')],True)['verified'])
  off=target('post anonymously',checked=False,composer_scope=True)
  editor=target('create post','edit',composer_scope=True)
  self.assertFalse(profile_fallback_decision('auto',[off,{**off,'id':1},editor],True)['verified'])

 def test_auto_prioritizes_checked_anonymous_but_does_not_guess(self):
  self.assertTrue(decision('auto','',[target('post anonymously',checked=True,composer_scope=True)])['verified'])
  self.assertFalse(decision('auto','',[])['verified'])
 def test_auto_falls_back_only_to_confirmed_regular_composer(self):
  from posting_identity import default_allowed
  regular=target('create post','edit')
  self.assertTrue(default_allowed([regular]))
  self.assertFalse(default_allowed([regular],seen=True))
  disabled=target('post anonymously','switch',composer_scope=True,checked=False,identity_enabled=False)
  self.assertTrue(default_allowed([regular,disabled],seen=True))
  self.assertNotIn('target',decision('auto','',[regular,disabled]))
  self.assertFalse(default_allowed([regular,{**disabled,'identity_enabled':True}]))
  self.assertFalse(default_allowed([target('gửi bài viết ẩn danh...','edit')]))
 def test_nickname_requires_explicit_name(self):
  with self.assertRaises(ValueError):validate('nickname','')
  with self.assertRaises(ValueError):validate('madeup')
 def test_generic_submit_only_with_live_composer_scope(self):
  from desktop import is_post_button
  t={**target('submit','button'),'text':'button "Submit"'}
  self.assertFalse(is_post_button(t))
  self.assertFalse(is_post_button({**t,'anonymous_submit':True}))
  self.assertTrue(is_post_button({**t,'anonymous_submit':True,'composer_scope':True}))
 def test_actual_mcp_switch_uia_button_mapping_requires_toggle_pattern(self):
  from posting_identity import live_role_matches
  class Pattern:ToggleState=0
  class Button:
   ControlTypeName='ButtonControl'
   def GetTogglePattern(self):return Pattern()
  class PlainButton:
   ControlTypeName='ButtonControl'
   def GetTogglePattern(self):return None
  self.assertTrue(live_role_matches(Button(),'switch'))
  self.assertFalse(live_role_matches(PlainButton(),'switch'))
  self.assertFalse(live_role_matches(Button(),'link'))
 def test_ok_only_in_anonymous_consent_not_generic_dialog(self):
  self.assertNotIn('target',decision('anonymous','',[target('ok','button')]))
  self.assertEqual(decision('anonymous','',[target('ok','button',identity_scope=True)])['target'],0)
  self.assertNotIn('target',decision('anonymous','',[target('ok','button',identity_scope=True),target('create post','edit')]))
 def test_anonymous_dialog_requires_real_caption_editor_scope(self):
  self.assertTrue(decision('anonymous','',[target('tạo bài viết công khai...','edit',anonymous_composer_scope=True)])['verified'])
  self.assertFalse(decision('anonymous','',[target('bài viết ẩn danh','group')])['verified'])
 def test_actual_vietnamese_anonymous_editor_uses_bounded_typing(self):
  from desktop import known_composer_action
  t={**target('gửi bài viết ẩn danh...','edit'),'text':'edit "Gửi bài viết ẩn danh..."'}
  self.assertEqual(known_composer_action([t],False,False,False,False)['action'],'type_caption')
 def test_window_lookup_requires_same_point_role_and_unique_match(self):
  from posting_identity import find_in_window
  class Node:
   ControlTypeName='ButtonControl'
   def __init__(self,name,children=(),left=0):
    self.Name=name;self.children=children;self.BoundingRectangle=SimpleNamespace(left=left,top=0,right=100,bottom=100)
   def GetChildren(self):return self.children
  t={**target('ok','button'),'loc':[50,50]};child=Node('OK')
  with patch('windows_mcp.uia.ControlFromHandle',return_value=Node('root',[child])):
   self.assertIs(find_in_window(t,123),child)
  with patch('windows_mcp.uia.ControlFromHandle',return_value=Node('root',[child,Node('OK')])):
   self.assertIsNone(find_in_window(t,123))
  with patch('windows_mcp.uia.ControlFromHandle',return_value=Node('root',[Node('OK',left=60)])):
   self.assertIsNone(find_in_window(t,123))

class DisabledAnonymousProofTests(unittest.TestCase):
 def proof(self,checked=1,scoped=True,complete=True,duplicate=False):
  from posting_identity import native_anonymous_proof
  button=SimpleNamespace(Name='Đăng ẩn danh',ControlTypeName='ButtonControl',IsEnabled=False,IsOffscreen=False,BoundingRectangle=SimpleNamespace(left=10,top=10,right=30,bottom=30),GetTogglePattern=lambda:SimpleNamespace(ToggleState=checked))
  parent=SimpleNamespace(Name='Tạo bài viết' if scoped else 'Bảng tin',ControlTypeName='GroupControl')
  rows=[(button,(parent,))]*(2 if duplicate else 1)
  with patch('windows_mcp.uia.ControlFromHandle'),patch('uia_snapshot.capture',return_value=(rows,complete)):
   return native_anonymous_proof(123)
 def test_checked_disabled_switch_proves_anonymous_without_click(self):
  proof=self.proof()
  self.assertTrue(proof['checked']);self.assertFalse(proof['identity_enabled'])
  self.assertTrue(decision('auto','',[proof])['verified'])
 def test_no_proof_from_unchecked_feed_ambiguous_or_partial_tree(self):
  for args in ({'checked':0},{'scoped':False},{'complete':False},{'duplicate':True}):
   self.assertIsNone(self.proof(**args))

class IdentityStoreTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.s=Store(Path(self.tmp.name)/'db.sqlite3')
  self.gid=self.s.add_group('facebook.com/groups/test','Test',link_policy='allow',category='Valorant');self.s.enable_group(self.gid,True)
  self.cid=self.s.content('Test',category='Valorant')
 def tearDown(self):self.tmp.cleanup()
 def test_new_jobs_freeze_required_identity_and_change_cancels_old(self):
  self.s.set_posting_identity(self.gid,'nickname','Player One')
  jid=self.s.plan(self.cid,60)[0]
  row=self.s.rows('SELECT * FROM jobs WHERE id=?',(jid,))[0]
  self.assertEqual(row['posting_identity'],'nickname');self.assertEqual(row['posting_nickname'],'Player One')
  self.assertEqual(self.s.set_posting_identity(self.gid,'anonymous'),1)
  self.assertEqual(self.s.rows('SELECT state FROM jobs WHERE id=?',(jid,))[0]['state'],'cancelled')
 def test_working_identity_cannot_change(self):
  jid=self.s.plan(self.cid,60)[0]
  with self.s.db() as c:c.execute("UPDATE jobs SET state='working' WHERE id=?",(jid,))
  with self.assertRaises(ValueError):self.s.set_posting_identity(self.gid,'anonymous')

class IdentityCommentTests(unittest.IsolatedAsyncioTestCase):
 async def test_anonymous_post_never_sends_comment_as_regular_profile(self):
  import post_comments
  tool=AsyncMock();observe=AsyncMock();url=AsyncMock(return_value='https://www.facebook.com/groups/1451891096876445/posts/123456789/')
  with tempfile.TemporaryDirectory() as data:
   Path(data,'work').mkdir()
   job={'id':1,'data_dir':data,'body':'Test','url':'https://www.facebook.com/groups/1451891096876445/','posting_identity':'anonymous','comment_text':'https://example.com','comment_policy':'allowed'}
   editor={'role':'edit','name':'bình luận dưới tên profile thường','loc':[10,10],'text':'edit "Bình luận dưới tên Profile thường"'}
   with patch('desktop.foreground'),patch('post_comments.own_post_context',return_value={'caption_seen':True,'editors':[editor]}):
    result=await post_comments.finish_post(tool,observe,url,42,job,{'state':'uncertain'},True)
   self.assertEqual(result['comment_status'],'failed');tool.assert_not_awaited()

if __name__=='__main__':unittest.main()
