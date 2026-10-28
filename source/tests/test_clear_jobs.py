import sys,tempfile,time,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from store import Store
class ClearJobTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'state.db';self.s=Store(self.path)
        self.g=self.s.add_group('facebook.com/groups/test-clear','Test',link_policy='allow');self.s.enable_group(self.g,True);self.p=self.s.content('Caption')
    def tearDown(self):self.tmp.cleanup()
    def test_clear_hides_all_cancels_waiting_and_preserves_content_and_history(self):
        self.s.cycle(self.p,30,1,1,4);jobs=self.s.rows('SELECT * FROM jobs');self.s.approve([j['id'] for j in jobs]);self.s.set('running',True)
        first=self.s.claim();self.s.finish(first['id'],'submitted','Visible')
        deadline=self.s.rows('SELECT next_post_after FROM groups')[0]['next_post_after'];revision=self.s.get('control_revision',0)
        result=self.s.clear_jobs();self.assertEqual(result,{'hidden':4,'cancelled':3});self.assertFalse(self.s.get('running'));self.assertEqual(self.s.get('control_revision'),revision+1)
        self.assertEqual(self.s.rows('SELECT * FROM jobs WHERE hidden=0'),[]);self.assertEqual(len(self.s.rows('SELECT * FROM contents')),1)
        self.assertEqual(self.s.rows('SELECT state FROM jobs WHERE id=?',(first['id'],))[0]['state'],'submitted');self.assertEqual(self.s.rows('SELECT next_post_after FROM groups')[0]['next_post_after'],deadline)
        # Clearing does not remove the calendar-day guard, even if cooldown data is absent.
        with self.s.db() as c:c.execute('UPDATE groups SET next_post_after=0')
        ids=self.s.plan(self.p,30);self.s.approve(ids);self.s.set('running',True);self.assertIsNone(self.s.claim())
        self.assertTrue(all(j['hidden']==1 for j in Store(self.path).rows('SELECT hidden FROM jobs WHERE id<=4')))
    def test_active_worker_rejects_without_partial_clear(self):
        ids=self.s.plan(self.p,30);self.s.approve(ids);self.s.set('running',True);self.assertIsNotNone(self.s.claim())
        with self.assertRaises(ValueError):self.s.clear_jobs()
        self.assertEqual(self.s.rows('SELECT hidden FROM jobs')[0]['hidden'],0);self.assertTrue(self.s.get('running'))
    def test_cancel_releases_unused_group_and_stale_reservation(self):
        ids=self.s.plan(self.p,30)
        with self.s.db() as c:c.execute('UPDATE groups SET next_post_after=?',(time.time()+86400,))
        self.assertEqual(self.s.cancel_jobs(ids),1)
        group=self.s.rows('SELECT * FROM groups')[0]
        self.assertEqual(group['next_post_after'],0);self.assertEqual(group['enabled'],1)
        self.assertEqual(len(self.s.cycle(self.p,30,1,1,1)),1)
    def test_cancel_does_not_release_real_uncertain_publication(self):
        ids=self.s.cycle(self.p,30,1,1,2);self.s.approve(ids);self.s.set('running',True)
        first=self.s.claim();self.s.finish(first['id'],'uncertain','Possible submission',post_attempted=True)
        deadline=self.s.rows('SELECT next_post_after FROM groups')[0]['next_post_after']
        self.s.cancel_jobs();self.s.release_cancelled_slots()
        self.assertEqual(self.s.rows('SELECT next_post_after FROM groups')[0]['next_post_after'],deadline)
        self.assertEqual(self.s.cycle(self.p,30,1,1,1),[])
        fresh=self.s.content('A completely new caption')
        self.assertEqual(len(self.s.cycle(fresh,30,1,1,2)),2)
    def test_cancelling_one_reservation_keeps_other_reservations_active(self):
        ids=self.s.cycle(self.p,30,1,1,2)
        self.s.cancel_jobs(ids[:1])
        self.assertEqual(self.s.rows('SELECT state FROM jobs WHERE id=?',(ids[1],))[0]['state'],'draft')
        self.assertEqual(self.s.cycle(self.p,30,1,1,1),[])
if __name__=='__main__':unittest.main()
