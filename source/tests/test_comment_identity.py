"""Comment identity policy and switching with fake UI; no real comments sent."""
import sys,tempfile,unittest
from pathlib import Path
from unittest.mock import AsyncMock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import comment_identity,post_comments
from store import Store

def editor(who):return {'role':'edit','name':'bình luận dưới tên '+who,'loc':[100,200],'text':'edit "Bình luận dưới tên '+who+'"'}

class CommentIdentityTests(unittest.TestCase):
 def test_follow_hidden_and_nickname_require_exact_actor(self):
  job={'posting_identity':'anonymous'}
  self.assertTrue(comment_identity.verified(job,editor('người tham gia ẩn danh')))
  self.assertFalse(comment_identity.verified(job,editor('my name')))
  job={'comment_identity':'hidden','comment_nickname':'Player One'}
  self.assertTrue(comment_identity.verified(job,editor('player one')))
  self.assertFalse(comment_identity.verified(job,editor('player one extra')))
 def test_explicit_profile_needs_selected_main_profile_name(self):
  job={'comment_identity':'profile'}
  self.assertFalse(comment_identity.verified(job,editor('my name')))
  self.assertTrue(comment_identity.verified(job,editor('my name'),'My Name'))
  self.assertFalse(comment_identity.verified(job,editor('người tham gia ẩn danh'),'my name'))
 def test_follow_checks_observed_post_author_when_available(self):
  job={'comment_identity':'follow','comment_expected_actor':'My Name'}
  self.assertTrue(comment_identity.verified(job,editor('my name')))
  self.assertFalse(comment_identity.verified(job,editor('người tham gia ẩn danh')))
 def test_only_scoped_menu_options_are_used(self):
  option={'role':'button','name':'my name','description':'my name your main profile'}
  self.assertIsNone(comment_identity.option({'comment_identity':'profile'},[option]))
  self.assertIsNotNone(comment_identity.option({'comment_identity':'profile'},[{**option,'identity_menu':True}]))
 def test_repeated_avatar_at_same_point_is_one_selector(self):
  avatar={'role':'button','name':'ảnh đại diện','loc':[60,200]}
  ctx={'editors':[editor('người tham gia ẩn danh')],'identity_controls':[avatar,avatar]}
  self.assertEqual(comment_identity.selector(ctx),avatar)
 def test_current_facebook_profile_switch_label_is_scoped_to_editor(self):
  switch={'role':'button','name':'chuyển sang trang hoặc trang cá nhân khác','loc':[60,200]}
  ctx={'editors':[{'role':'edit','name':'viết bình luận công khai…','loc':[300,200]}],'identity_controls':[switch]}
  self.assertEqual(comment_identity.selector(ctx),switch)
 def test_account_dialog_requires_exact_configured_profile(self):
  option={'role':'button','name':'nguyễn vũ, 8 thông báo, đang chọn','profile_name':'nguyễn vũ','identity_menu':True,'description':'nguyễn vũ, 8 thông báo, đang chọn'}
  job={'comment_identity':'profile','comment_profile_name':'Nguyễn Vũ'}
  self.assertEqual(comment_identity.option(job,[option]),option)
  self.assertIsNone(comment_identity.option({'comment_identity':'profile'},[option]))
  self.assertIsNone(comment_identity.option({**job,'comment_profile_name':'Another Account'},[option]))
  self.assertIsNone(comment_identity.option({**job,'comment_profile_name':'Another Account'},[{**option,'description':'your main profile'}]))
 def test_follow_named_post_matches_profile_without_notification_suffix(self):
  option={'role':'button','name':'nguyễn vũ, 8 thông báo, đang chọn','profile_name':'nguyễn vũ','identity_menu':True}
  job={'comment_identity':'follow','comment_expected_actor':'Nguyễn Vũ'}
  self.assertEqual(comment_identity.option(job,[option]),option)
  self.assertIsNone(comment_identity.option({**job,'comment_expected_actor':'Another Account'},[option]))
  self.assertIsNone(comment_identity.option(job,[option,dict(option)]))
 def test_setting_is_frozen_into_new_jobs(self):
  with tempfile.TemporaryDirectory() as data:
   store=Store(Path(data)/'db');gid=store.add_group('facebook.com/groups/test',category='Valorant',link_policy='allow');store.enable_group(gid,True)
   cid=store.content('Test',category='Valorant')
   store.set_comment_settings(cid,'always','https://example.com',identity='hidden',nickname='Player One')
   jid=store.plan(cid,30)[0];job=store.rows('SELECT * FROM jobs WHERE id=?',(jid,))[0]
   self.assertEqual((job['comment_identity'],job['comment_nickname']),('hidden','Player One'))

class CommentSwitchTests(unittest.IsolatedAsyncioTestCase):
 async def test_profile_choice_is_rechecked_before_send(self):
  with tempfile.TemporaryDirectory() as data:
   Path(data,'work').mkdir()
   job={'id':1,'data_dir':data,'body':'Exact caption','url':'https://www.facebook.com/groups/test/','comment_text':'https://example.com','comment_policy':'allowed','posting_identity':'anonymous','comment_identity':'profile'}
   avatar={'role':'button','name':'ảnh đại diện','loc':[60,200],'text':'button "Ảnh đại diện"'}
   base={'caption_seen':True,'editors':[editor('người tham gia ẩn danh')],'outside_texts':[],'identity_controls':[avatar]}
   chosen={'caption_seen':True,'editors':[editor('my name')],'outside_texts':[]}
   after={**chosen,'outside_texts':[job['comment_text']]}
   option={'role':'button','name':'my name','description':'your main profile','identity_menu':True,'loc':[70,150],'text':'button "My Name"'}
   tool=AsyncMock();observe=AsyncMock(return_value='')
   with patch('desktop.foreground'),patch('desktop.verify_live_target'),patch('post_comments.own_post_context',side_effect=[base,base,base,chosen,after]),patch('comment_identity.menu',return_value=[option]),patch('post_comments.asyncio.sleep',new=AsyncMock()):
    result=await post_comments.finish_post(tool,observe,AsyncMock(return_value='https://www.facebook.com/groups/test/posts/123/'),42,job,{},True)
   self.assertEqual(result['comment_status'],'sent')
   self.assertEqual([c.args[0] for c in tool.await_args_list],['Click','Click','Type'])
   self.assertEqual(result['comment_identity_effective'],'my name')

if __name__=='__main__':unittest.main()


class PublicEditorIdentityTests(unittest.TestCase):
 def test_public_editor_needs_fresh_profile_proof(self):
  import comment_identity as identity
  job={'comment_identity':'follow','comment_expected_actor':'ismo samake'}
  editor={'name':'viết bình luận công khai…'}
  self.assertFalse(identity.verified(job,editor))
  proof={**editor,'profile_verified':True,'profile_actor':'ismo samake'}
  self.assertTrue(identity.verified(job,proof))
  self.assertTrue(identity.verified({'comment_identity':'profile'},proof))
  self.assertFalse(identity.verified({'comment_identity':'hidden'},proof))
 def test_public_profile_proof_never_overrides_explicit_anonymous_label(self):
  import comment_identity as identity
  editor={'name':'bình luận dưới tên người tham gia ẩn danh','profile_verified':True,'profile_actor':'ismo samake'}
  self.assertFalse(identity.verified({'comment_identity':'profile'},editor))
