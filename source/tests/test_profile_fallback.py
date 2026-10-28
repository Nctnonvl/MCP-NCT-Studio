import tempfile,unittest
from pathlib import Path
from store import Store
from final_report import render

class ProfileFallbackTests(unittest.TestCase):
 def test_effective_profile_is_saved_for_approval_and_comments(self):
  with tempfile.TemporaryDirectory() as tmp:
   store=Store(Path(tmp)/'db');gid=store.add_group('facebook.com/groups/test',link_policy='allow',category='Valorant');store.enable_group(gid,True);store.set_posting_identity(gid,'auto')
   cid=store.content('Bài',category='Valorant');jid=store.plan(cid,30)[0];job=store.rows('SELECT * FROM jobs WHERE id=?',(jid,))[0]
   store.record_result(job,{'state':'pending','profile_fallback_used':True,'identity_verified':True,'posting_identity_effective':'default'})
   self.assertEqual(store.rows('SELECT posting_identity FROM jobs WHERE id=?',(jid,))[0]['posting_identity'],'default')
   self.assertEqual(store.rows('SELECT posting_identity FROM groups WHERE id=?',(gid,))[0]['posting_identity'],'auto')
 def test_report_names_effective_identity_and_reason(self):
  text=render({'id':1,'content_id':2,'group_name':'Group','url':'https://facebook.com/groups/test/'},{'state':'submitted','identity_verified':True,'posting_identity_effective':'default','profile_fallback_used':True})
  self.assertIn('Danh tính: hồ sơ chính',text);self.assertIn('đã chuyển sang hồ sơ chính',text)
if __name__=='__main__':unittest.main()
