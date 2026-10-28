"""Storage tests only. No Facebook actions or Telegram messages."""
import tempfile,time,unittest
from pathlib import Path
from store import Store

class BulkToggleTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.store=Store(Path(self.tmp.name)/'state.sqlite3')
  self.a=self.store.add_group('facebook.com/groups/bulk_a','A',link_policy='allow',category='Game')
  self.b=self.store.add_group('facebook.com/groups/bulk_b','B',link_policy='unknown',category='Game')
  self.c=self.store.add_group('facebook.com/groups/bulk_c','C',link_policy='allow',category='Game')
 def tearDown(self):self.tmp.cleanup()
 def job(self,gid,state):
  with self.store.db() as c:
   return c.execute('INSERT INTO jobs(group_id,group_name,url,body,media,due,state,created,updated) VALUES(?,?,?,?,?,?,?,?,?)',(gid,'test','https://www.facebook.com/groups/bulk_a/','test','',time.time(),state,time.time(),time.time())).lastrowid
 def test_enable_skips_unknown_policy_without_changing_it(self):
  result=self.store.toggle_groups([self.a,self.b],True)
  self.assertEqual(result['changed_ids'],[self.a]);self.assertEqual(result['skipped'][0]['id'],self.b)
  self.assertEqual(self.store.rows('SELECT enabled FROM groups WHERE id=?',(self.b,))[0]['enabled'],0)
 def test_disable_cancels_only_target_pending_jobs(self):
  self.store.toggle_groups([self.a,self.c],True)
  target=self.job(self.a,'queued');other=self.job(self.c,'queued');done=self.job(self.a,'submitted')
  self.store.toggle_groups([self.a],False)
  states={r['id']:r['state'] for r in self.store.rows('SELECT id,state FROM jobs')}
  self.assertEqual(states[target],'cancelled');self.assertEqual(states[other],'queued');self.assertEqual(states[done],'submitted')
 def test_working_group_is_skipped(self):
  self.store.toggle_groups([self.a],True);self.job(self.a,'working')
  result=self.store.toggle_groups([self.a],False)
  self.assertEqual(result['changed'],0);self.assertEqual(result['skipped'][0]['id'],self.a)
  self.assertEqual(self.store.rows('SELECT enabled FROM groups WHERE id=?',(self.a,))[0]['enabled'],1)
 def test_invalid_or_deleted_group_leaves_everything_unchanged(self):
  with self.assertRaises(ValueError):self.store.toggle_groups([self.a,9999],True)
  self.assertEqual(self.store.rows('SELECT enabled FROM groups WHERE id=?',(self.a,))[0]['enabled'],0)
  for ids in [[],['1'],[True],[-1]]:
   with self.assertRaises(ValueError):self.store.toggle_groups(ids,True)
 def test_deduplicates_and_counts_only_real_changes(self):
  self.assertEqual(self.store.toggle_groups([self.a,self.a],True)['changed'],1)
  self.assertEqual(self.store.toggle_groups([self.a],True)['changed'],0)
