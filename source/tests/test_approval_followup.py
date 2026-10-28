import tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from store import Store
import approval_followup as approval
class ApprovalTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.data=Path(self.tmp.name)
  self.s=Store(self.data/'manager.sqlite3');self.g=self.s.add_group('facebook.com/groups/approval',link_policy='allow');self.s.enable_group(self.g,True)
  self.cid=self.s.content('Exact frozen caption');self.jid=self.s.plan(self.cid,60)[0];self.s.finish(self.jid,'pending','Waiting',post_attempted=True)
  self.url='https://www.facebook.com/groups/approval/posts/123/'
  self.s.set('paused_by_user',False);self.s.set('running',False)
 def tearDown(self):self.tmp.cleanup()
 def track(self):
  self.assertTrue(approval.enqueue(self.s,self.jid,{'state':'pending','post_url':self.url},self.data))
  with self.s.db() as c:c.execute('UPDATE approval_checks SET due=0')
 def result(self,comment='sent'):
  return {'state':'submitted','post_url':self.url,'receipt_verified':True,'verification_source':'post_permalink','comment_status':comment,'detail':'Published'}
 def test_only_pending_with_same_group_permalink_can_be_tracked(self):
  self.assertFalse(approval.enqueue(self.s,self.jid,{'state':'uncertain','post_url':self.url},self.data))
  self.assertTrue(approval.enqueue(self.s,self.jid,{'state':'pending'},self.data))
  self.assertFalse(approval.enqueue(self.s,self.jid,{'state':'pending','post_url':'https://www.facebook.com/groups/wrong/posts/1/'},self.data))
  self.track();self.track();self.assertEqual(len(self.s.rows('SELECT * FROM approval_checks')),1)
 def test_pending_remains_pending_and_checks_are_quiet(self):
  self.track();job=approval.claim(self.s,self.data);self.assertEqual(job['task'],'approval_check')
  self.assertFalse(approval.complete(self.s,job,{'state':'pending','post_url':self.url,'comment_status':'waiting_approval'}))
  self.assertEqual(self.s.rows('SELECT state FROM jobs')[0]['state'],'pending')
  row=self.s.rows('SELECT * FROM approval_checks')[0];self.assertEqual(row['state'],'waiting')
  self.assertTrue(890<row['due']-time.time()<1810)
 def test_approved_becomes_submitted_without_a_new_attempt(self):
  self.track();original=self.s.rows('SELECT attempted_at,updated FROM jobs')[0]
  job=approval.claim(self.s,self.data);self.assertTrue(approval.complete(self.s,job,self.result()))
  self.assertEqual(self.s.rows('SELECT state,comment_status FROM jobs')[0],{'state':'submitted','comment_status':'sent'})
  self.assertEqual(self.s.rows('SELECT attempted_at,updated FROM jobs')[0],original)
  self.assertEqual(self.s.rows('SELECT state FROM approval_checks')[0]['state'],'done')
  self.assertIsNone(approval.claim(self.s,self.data));self.assertFalse(approval.complete(self.s,job,self.result()))
 def test_ambiguous_comment_stops_followups_without_reposting(self):
  self.track();job=approval.claim(self.s,self.data);approval.complete(self.s,job,self.result('uncertain'))
  self.assertEqual(self.s.rows('SELECT state FROM approval_checks')[0]['state'],'review')
  self.assertEqual(len(self.s.rows('SELECT * FROM jobs')),1)
 def test_user_pause_and_browser_profile_change_prevent_actions(self):
  self.track();self.s.set('paused_by_user',True);self.assertIsNone(approval.claim(self.s,self.data))
  self.s.set('paused_by_user',False);(self.data/'browser-profile.json').write_text('{}')
  self.assertIsNone(approval.claim(self.s,self.data));self.assertEqual(self.s.rows('SELECT state FROM approval_checks')[0]['state'],'review')
 def test_restart_keeps_original_pending_status_and_never_repeats_unknown_comment(self):
  self.track();approval.claim(self.s,self.data);self.s.recover()
  self.assertEqual(self.s.rows('SELECT state FROM jobs')[0]['state'],'pending')
  self.assertEqual(self.s.rows('SELECT state FROM approval_checks')[0]['state'],'review')
 def test_worker_serialization_and_calendar_reset(self):
  self.track();job=approval.claim(self.s,self.data)
  self.s.set('running',True);self.assertIsNone(self.s.claim())
  with self.assertRaises(ValueError):self.s.clear_jobs()
  with self.assertRaises(ValueError):self.s.reset_group_calendar(self.g,self.s.group_calendars()[self.g]['revision'],True)
  approval.complete(self.s,job,{'state':'pending'})
  self.s.reset_group_calendar(self.g,self.s.group_calendars()[self.g]['revision'],True)
  self.assertEqual(self.s.rows('SELECT state FROM approval_checks')[0]['state'],'cancelled')
 def test_clear_schedule_cancels_waiting_followup(self):
  self.track();self.s.clear_jobs()
  self.assertEqual(self.s.rows('SELECT state FROM approval_checks')[0]['state'],'cancelled')
 def test_monitor_only_does_not_resume_posting_queue(self):
  import app
  self.track();self.s.set('running',False);self.s.set('paused_by_user',True)
  with patch.object(app,'STORE',self.s),patch.object(app,'runtime_ready',return_value=True),patch.object(app,'load_config',return_value={'mode':'publish'}):
   app.control_approval_monitor('run')
   self.assertFalse(self.s.get('running'));self.assertTrue(self.s.get('paused_by_user'))
   self.assertTrue(approval.enabled(self.s));self.assertIsNone(self.s.claim())
   app.control_approval_monitor('pause')
   self.assertFalse(approval.enabled(self.s));self.assertIsNone(approval.claim(self.s,self.data))
 def test_disabled_posting_group_can_be_watched_without_enabling_new_posts(self):
  self.track();self.s.set('running',False);self.s.set('paused_by_user',True);self.s.set('approval_monitor_enabled',True)
  with self.s.db() as c:c.execute('UPDATE groups SET enabled=0 WHERE id=?',(self.g,))
  job=approval.claim(self.s,self.data)
  self.assertIsNotNone(job);self.assertEqual(job['task'],'approval_check')
  self.assertFalse(self.s.get('running'));self.assertIsNone(self.s.claim())
 def test_confirmed_decline_stops_checks_without_a_new_post_attempt(self):
  self.track();original=self.s.rows('SELECT attempted_at,updated FROM jobs')[0]
  job=approval.claim(self.s,self.data)
  self.assertTrue(approval.complete(self.s,job,{'state':'error','your_content_checked':True,'verification_source':'your_content','detail':'Đúng bài bị từ chối.','comment_status':'skipped'}))
  self.assertEqual(self.s.rows('SELECT state FROM jobs')[0]['state'],'error')
  self.assertEqual(self.s.rows('SELECT state FROM approval_checks')[0]['state'],'review')
  self.assertEqual(self.s.rows('SELECT attempted_at,updated FROM jobs')[0],original)
  self.assertIsNone(approval.claim(self.s,self.data))
 def test_status_distinguishes_monitoring_from_user_pause(self):
  import app
  self.track()
  with patch.object(app,'STORE',self.s):
   self.assertIn('theo dõi',app.queue_progress())
   self.s.set('paused_by_user',True);self.s.set('progress','Paused by user')
   self.assertEqual(app.queue_progress(),'Paused by user')

 def test_removed_without_permalink_is_persisted_and_not_retried(self):
  self.assertTrue(approval.enqueue(self.s,self.jid,{'state':'pending'},self.data))
  with self.s.db() as c:c.execute('UPDATE approval_checks SET due=0')
  job=approval.claim(self.s,self.data);self.assertEqual(job['post_url'],'')
  result={'state':'error','moderation_checked':True,'moderation_status':'removed','your_content_checked':True,'verification_source':'your_content','comment_status':'skipped','detail':'Đúng bài đã gỡ.'}
  self.assertTrue(approval.complete(self.s,job,result));self.assertFalse(approval.complete(self.s,job,result))
  self.assertEqual(self.s.rows('SELECT state,moderation_status FROM jobs')[0],{'state':'error','moderation_status':'removed'})
  self.assertEqual(Store(self.data/'manager.sqlite3').rows('SELECT moderation_status FROM jobs')[0]['moderation_status'],'removed')
  self.assertIsNone(approval.claim(self.s,self.data))
 def test_missing_link_requires_actual_frozen_attempt(self):
  with self.s.db() as c:c.execute('UPDATE jobs SET post_attempted=0')
  self.assertFalse(approval.enqueue(self.s,self.jid,{'state':'pending'},self.data))
