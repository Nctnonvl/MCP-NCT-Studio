import tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from store import Store
from queue_recovery import hard_pause
from final_report import render


class FailureCooldownTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.s=Store(Path(self.tmp.name)/'test.db')
        self.now=1793000000
        self.g=self.s.add_group('facebook.com/groups/cooldown',link_policy='allow')
        self.s.enable_group(self.g,True)
        self.cid=self.s.content('Frozen approved content')
        self.jid=self.s.plan(self.cid,'1',start=self.now)[0]
        self.s.approve([self.jid]);self.s.set('running',True)
    def tearDown(self):self.tmp.cleanup()
    def outcome(self,jid,state='error',detail='No composer',**fields):
        with patch('store.time.time',return_value=self.now),patch('store.sample_gap',return_value=3900):
            return self.s.queue_outcome(jid,dict(state=state,detail=detail,**fields))
    def test_three_errors_persist_break_without_blocking_or_retrying_failed_jobs(self):
        self.assertEqual(self.outcome(1)['failure_streak'],1)
        self.assertEqual(self.outcome(2,'uncertain')['failure_streak'],2)
        r=self.outcome(3)
        self.assertEqual(r['queue_cooldown_until'],self.now+3900)
        self.assertEqual(r['failure_streak'],0)
        self.assertTrue(self.s.get('running'));self.assertFalse(r['hard_pause'])
        self.assertEqual(self.s.get('next_allowed'),self.now+3900)
        self.assertEqual(self.s.rows('select count(*) n from jobs')[0]['n'],1)
    def test_success_and_pending_reset_but_comment_failure_does_not_count_as_post_failure(self):
        for state in ('submitted','pending'):
            self.outcome(10 if state=='submitted' else 20)
            r=self.outcome(11 if state=='submitted' else 21,state,comment_status='failed')
            self.assertEqual(r['failure_streak'],0)
        self.assertEqual(self.s.get('failure_cooldown_until',0),0)
    def test_duplicate_outcome_is_not_counted_twice(self):
        self.outcome(1);self.outcome(1);self.assertEqual(self.outcome(2)['failure_streak'],2)
    def test_refresh_restart_and_claim_preserve_timer_then_resume(self):
        for jid in (10,11,12):self.outcome(jid)
        with patch('store.time.time',return_value=self.now+1):
            self.assertEqual(self.s.refresh_global_cooldown(),self.now+3900)
            self.s.set('resume_approved_on_start',True);self.s.recover()
            self.assertIsNone(self.s.claim())
        with patch('store.time.time',return_value=self.now+3901):
            self.assertEqual(self.s.claim()['id'],self.jid)
    def test_user_pause_during_timer_is_never_overridden(self):
        for jid in (10,11,12):self.outcome(jid)
        self.s.set('running',False);self.s.set('paused_by_user',True)
        self.s.set('resume_approved_on_start',True)
        with patch('store.time.time',return_value=self.now+5000):
            self.s.recover();self.assertIsNone(self.s.claim())
        self.assertFalse(self.s.get('running'))
    def test_security_and_operator_stops_remain_manual(self):
        for detail in ('captcha','Người dùng yêu cầu dừng.','Windows đang khóa','Gặp cảnh báo hoặc yêu cầu xác minh'):
            self.assertTrue(hard_pause({'state':'uncertain','detail':detail}))
        self.assertFalse(hard_pause({'state':'uncertain','post_attempted':True,'detail':'Không tìm được bài'}))
    def test_actual_random_break_range(self):
        self.outcome(1);self.outcome(2)
        with patch('store.time.time',return_value=self.now):r=self.s.queue_outcome(3,{'state':'error'})
        self.assertTrue(3000<=r['queue_cooldown_until']-self.now<=4800)
    def test_telegram_reports_resume_time(self):
        text=render({'id':1,'group_name':'Test','url':'https://facebook.com/groups/test'},dict(state='error',queue_cooldown_until=self.now+3900))
        self.assertIn('3 lỗi liên tiếp',text);self.assertIn('tiếp tục lịch',text)
    def test_preflight_errors_stop_claiming_at_third_failure(self):
        with self.s.db() as c:
            c.execute("UPDATE groups SET link_policy='unknown' WHERE id=?",(self.g,))
            row=dict(c.execute('select * from jobs where id=?',(self.jid,)).fetchone());row.pop('id')
            for _ in range(3):
                c.execute(f"insert into jobs({','.join(row)}) values({','.join('?' for _ in row)})",list(row.values()))
        with patch('store.time.time',return_value=self.now),patch('store.sample_gap',return_value=3900),patch('queue_recovery.reflow',return_value=0):
            self.assertIsNone(self.s.claim())
        self.assertEqual(self.s.rows("select count(*) n from jobs where state='error'")[0]['n'],3)
        self.assertEqual(self.s.rows("select count(*) n from jobs where state='queued'")[0]['n'],1)
        self.assertEqual(self.s.get('failure_cooldown_until'),self.now+3900)
    def test_restore_will_not_duplicate_a_later_confirmed_success(self):
        self.s.finish(self.jid,'uncertain','Unknown',post_attempted=True)
        new=self.s.restore_failed_contents([self.cid])[0]
        self.s.finish(new,'submitted','Confirmed',post_attempted=True)
        with self.assertRaises(ValueError):self.s.restore_failed_contents([self.cid])
    def test_claimed_restored_job_becomes_unknown_if_worker_dies(self):
        self.s.finish(self.jid,'error','Before sending',post_attempted=False)
        with patch('store.time.time',return_value=self.now):
            new=self.s.restore_failed_contents([self.cid])[0]
            self.assertEqual(self.s.claim()['id'],new)
            self.s.finish(new,'uncertain','Worker exited without result')
            self.assertGreater(self.s.refresh_global_cooldown(),self.now)
        self.assertEqual(self.s.rows('select post_attempted from jobs where id=?',(new,))[0]['post_attempted'],-1)
    def test_restore_preserves_evidence_and_is_idempotent(self):
        with self.s.db() as c:c.execute('update jobs set gap_seconds=120,gap_min_seconds=2400 where id=?',(self.jid,))
        self.s.finish(self.jid,'uncertain','Original evidence',post_attempted=True)
        before=self.s.rows('select * from jobs where id=?',(self.jid,))[0]
        with patch('store.time.time',return_value=self.now):
            new_id=self.s.restore_failed_contents([self.cid])[0]
            self.assertNotEqual(new_id,self.jid)
            self.assertEqual(self.s.restore_failed_contents([self.cid]),[new_id])
        self.assertEqual(before,self.s.rows('select * from jobs where id=?',(self.jid,))[0])
        new=self.s.rows('select * from jobs where id=?',(new_id,))[0]
        self.assertEqual(new['retry_of'],self.jid);self.assertEqual(new['state'],'queued')
        for key in ('body','group_id','media','posting_identity','comment_text'):
            self.assertEqual(new[key],before[key])
        self.assertEqual(new['attempted_at'],0);self.assertEqual(new['post_attempted'],0)
        self.assertEqual(new['gap_seconds'],2400)
    def test_restore_respects_group_cooldown_and_rolls_back_missing_content(self):
        self.s.finish(self.jid,'uncertain','Unknown',post_attempted=True)
        with self.assertRaises(ValueError):self.s.restore_failed_contents([self.cid,999])
        self.assertEqual(self.s.rows('select count(*) n from jobs')[0]['n'],1)
        jid=self.s.restore_failed_contents([self.cid])[0]
        new=self.s.rows('select due from jobs where id=?',(jid,))[0]
        self.assertGreaterEqual(new['due'],self.s.rows('select next_post_after from groups where id=?',(self.g,))[0]['next_post_after'])

if __name__=='__main__':unittest.main()
