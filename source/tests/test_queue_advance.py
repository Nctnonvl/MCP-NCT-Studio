"""Compact later approved work while retaining an uncertain post for review."""
import datetime as dt,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from store import Store
from queue_recovery import should_pause,VN,day

class AdvanceTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.s=Store(Path(self.tmp.name)/'db')
  self.now=dt.datetime(2026,10,25,10,tzinfo=VN).timestamp();self.groups=[]
  for i in range(3):
   gid=self.s.add_group('facebook.com/groups/test'+str(i),link_policy='allow');self.s.enable_group(gid,True);self.groups.append(gid)
  self.cid=self.s.content('Exact frozen approved caption')
  with patch('store.sample_gap',return_value=4800):self.ids=self.s.plan(self.cid,'40-80',start=self.now+7200)
  self.s.approve(self.ids);self.s.set('running',True)
 def tearDown(self):self.tmp.cleanup()
 def finish_review(self,attempted):
  with self.s.db() as c:c.execute('UPDATE jobs SET attempted_at=? WHERE id=?',(self.now,self.ids[0]))
  self.s.finish(self.ids[0],'uncertain','Needs review',post_attempted=attempted)
  return self.s.advance_after_review(self.ids[0])
 def test_uncertain_stays_separate_and_next_jobs_move_up_with_minimum_gap(self):
  before=self.s.rows('SELECT id,group_id,body FROM jobs ORDER BY id')
  original=self.s.rows('SELECT due,gap_seconds FROM jobs ORDER BY id')
  with patch('store.time.time',return_value=self.now):self.assertEqual(self.finish_review(True),0)
  jobs=self.s.rows('SELECT * FROM jobs ORDER BY id')
  self.assertEqual(jobs[0]['state'],'uncertain')
  self.assertEqual(original,self.s.rows('SELECT due,gap_seconds FROM jobs ORDER BY id'))
  self.assertTrue(should_pause({'state':'uncertain','post_attempted':True}))
  self.assertEqual(before,self.s.rows('SELECT id,group_id,body FROM jobs ORDER BY id'))
 def test_explicit_no_submit_does_not_reserve_a_posting_cooldown(self):
  with patch('store.time.time',return_value=self.now):
   self.finish_review(False);job=self.s.claim()
  self.assertEqual(job['id'],self.ids[1]);self.assertEqual(self.s.get('next_allowed'),0)
 def test_daily_limit_and_future_day_are_kept(self):
  self.s.set('daily_group_limit',1)
  with patch('store.time.time',return_value=self.now):
   self.finish_review(True);self.s.reflow_queue()
  jobs=self.s.rows('SELECT due FROM jobs WHERE state=\'queued\' ORDER BY due')
  self.assertTrue(all(day(j['due'])>day(self.now) for j in jobs))
 def test_compaction_does_not_enable_paused_queue(self):
  self.s.set('running',False);self.s.set('paused_by_user',True)
  with patch('store.time.time',return_value=self.now):self.finish_review(True)
  self.assertFalse(self.s.get('running'));self.assertTrue(self.s.get('paused_by_user'))
 def test_only_local_uncertainty_continues(self):
  self.assertTrue(should_pause({'state':'uncertain','detail':'Không xác minh được bằng chứng sau khi gửi bài.'}))
  self.assertFalse(should_pause({'state':'error','post_attempted':False,'detail':'Nhóm không có ô soạn phù hợp.'}))
  for result in [{'state':'prepared'},{'state':'error','detail':'Không kết nối được dịch vụ.'},{'state':'uncertain','detail':'Gặp cảnh báo hoặc yêu cầu xác minh: captcha'},{'state':'uncertain','detail':'Người dùng yêu cầu dừng.'}]:
   self.assertTrue(should_pause(result))
 def test_local_error_advances_without_retrying_the_failed_post(self):
  with patch('store.time.time',return_value=self.now):
   self.s.finish(self.ids[0],'error','No composer for this group',post_attempted=False)
   self.s.advance_after_review(self.ids[0]);job=self.s.claim()
  self.assertEqual(job['id'],self.ids[1])
  self.assertEqual(self.s.rows('SELECT state FROM jobs WHERE id=?',(self.ids[0],))[0]['state'],'error')

if __name__=='__main__':unittest.main()
