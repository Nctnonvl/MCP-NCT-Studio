import datetime as dt,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from store import Store
from queue_recovery import VN


class GroupCalendarTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.s=Store(Path(self.tmp.name)/'test.db')
        self.now=dt.datetime(2026,10,26,10,tzinfo=VN).timestamp()
        self.g=self.s.add_group('facebook.com/groups/calendar-a',link_policy='allow')
        self.other=self.s.add_group('facebook.com/groups/calendar-b',link_policy='allow')
        self.s.enable_group(self.g,True);self.s.enable_group(self.other,True)
        self.cid=self.s.content('An exact approved caption')
        self.s.targets(self.cid,'selected',[self.g])
        self.jid=self.s.plan(self.cid,60,start=self.now)[0]
    def tearDown(self):self.tmp.cleanup()
    def info(self,gid=None):
        with patch('store.time.time',return_value=self.now):return self.s.group_calendars()[gid or self.g]
    def unknown(self):
        with self.s.db() as c:c.execute("update jobs set state='uncertain',attempted_at=?,updated=?,post_attempted=1,post_url='https://facebook.com/receipt',photo='keep.png' where id=?",(self.now,self.now,self.jid))
        with self.s.db() as c:c.execute('update groups set next_post_after=? where id=?',(self.now+86400,self.g))
    def reset(self,revision=None,confirm=True):
        rev=revision or self.info()['revision']
        with patch('store.time.time',return_value=self.now):return self.s.reset_group_calendar(self.g,rev,confirm)
    def test_reports_24_hour_deadline_last_attempt_and_reserved_slot(self):
        self.unknown();info=self.info()
        self.assertEqual(info['available_at'],self.now+86400)
        self.assertEqual(info['last_attempt_at'],self.now)
        self.assertEqual(info['last_job_id'],self.jid)
        self.assertEqual(info['last_state'],'uncertain')
        self.assertEqual(info['reservations'],[])
    def test_global_break_and_future_schedule_are_visible(self):
        self.s.set('next_allowed',self.now+1200)
        with self.s.db() as c:c.execute('update jobs set due=? where id=?',(self.now+7200,self.jid))
        info=self.info();self.assertEqual(info['available_at'],self.now+7200)
        self.assertEqual(info['reservation_at'],self.now+7200)
        self.assertEqual(info['reservations'][0]['id'],self.jid)
    def test_reset_requires_confirmation_and_rejects_stale_observation(self):
        self.unknown();rev=self.info()['revision']
        with self.assertRaises(ValueError):self.reset(rev,False)
        with self.s.db() as c:c.execute('update jobs set updated=updated+1 where id=?',(self.jid,))
        with self.assertRaisesRegex(ValueError,'thay đổi'):self.reset(rev)
        self.assertEqual(self.s.rows('select * from calendar_releases'),[])
        self.assertEqual(self.s.rows('select calendar_released from jobs')[0]['calendar_released'],0)
    def test_reset_preserves_evidence_and_allows_fresh_calendar(self):
        self.unknown();before=self.s.rows('select * from jobs where id=?',(self.jid,))[0]
        result=self.reset();self.assertEqual(result['released'],1)
        after=self.s.rows('select * from jobs where id=?',(self.jid,))[0]
        for key in ('state','attempted_at','updated','post_url','photo','body'):self.assertEqual(before[key],after[key])
        self.assertEqual(after['calendar_released'],1)
        audit=json.loads(self.s.rows('select before_json from calendar_releases')[0]['before_json'])
        self.assertEqual(audit['jobs'][0],before)
        self.assertEqual(self.info()['available_at'],0)
        with patch('store.time.time',return_value=self.now):
            ids=self.s.plan(self.cid,60,start=self.now)
            self.assertEqual(len(ids),1);self.s.approve(ids);self.s.set('running',True)
            self.assertEqual(self.s.claim()['id'],ids[0])
    def test_reset_cancels_waiting_reservations_without_touching_other_groups(self):
        other_post=self.s.content('Other caption');self.s.targets(other_post,'selected',[self.other])
        other_job=self.s.plan(other_post,60,start=self.now)[0]
        self.s.finish(other_job,'submitted','Keep',post_attempted=True)
        before=self.s.rows('select * from groups where id=?',(self.other,))[0]
        other_before=self.s.rows('select * from jobs where id=?',(other_job,))[0]
        self.assertEqual(self.reset()['cancelled'],1)
        self.assertEqual(self.s.rows('select * from groups where id=?',(self.other,))[0],before)
        self.assertEqual(self.s.rows('select * from jobs where id=?',(other_job,))[0],other_before)
        self.assertEqual(self.s.rows('select state from jobs where id=?',(self.jid,))[0]['state'],'cancelled')
    def test_active_worker_rejects_entire_reset(self):
        with self.s.db() as c:c.execute("update jobs set state='working' where id=?",(self.jid,))
        with self.assertRaisesRegex(ValueError,'đang thao tác'):self.reset()
        self.assertEqual(self.s.rows('select * from calendar_releases'),[])
    def test_reset_does_not_clear_failure_cooldown(self):
        self.unknown();self.s.set('failure_cooldown_until',self.now+4800)
        self.reset();self.assertEqual(self.info()['available_at'],self.now+4800)
        self.assertEqual(self.s.get('failure_cooldown_until'),self.now+4800)
    def test_released_attempt_does_not_consume_daily_cap(self):
        self.unknown();self.s.set('daily_group_limit',1)
        self.assertGreater(self.info(self.other)['available_at'],self.now)
        self.reset();self.assertEqual(self.info(self.other)['available_at'],0)
    def test_release_survives_restart_and_is_not_automatically_reversed(self):
        self.unknown();self.reset()
        with patch('store.time.time',return_value=self.now):self.s.recover()
        self.assertEqual(self.info()['available_at'],0)
        self.assertEqual(self.s.rows('select calendar_released from jobs')[0]['calendar_released'],1)

if __name__=='__main__':unittest.main()
