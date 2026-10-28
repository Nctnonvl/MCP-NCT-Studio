import sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from store import Store
from desktop import profile_matches
class DailySpacingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.s=Store(Path(self.tmp.name)/'state.db');self.groups=[]
        for i in range(4):
            g=self.s.add_group('facebook.com/groups/daily-'+str(i),link_policy='allow');self.s.enable_group(g,True);self.groups.append(g)
        self.p=self.s.content('Caption')
    def tearDown(self):self.tmp.cleanup()
    def test_chronological_global_gap_and_independent_daily_limits(self):
        start=time.time()
        with patch('store.sample_gap',return_value=3600):self.s.cycle_pool([self.p],None,'30-60',1,1,4,start)
        rows=self.s.rows('SELECT * FROM jobs ORDER BY due,id');self.assertEqual(len(rows),16)
        self.assertEqual([j['group_id'] for j in rows[:4]],self.groups)
        self.assertEqual([round(j['due']-start) for j in rows[:4]],[0,3600,7200,10800])
        self.assertTrue(all(y['due']-x['due']>=x['gap_seconds'] for x,y in zip(rows,rows[1:])))
        for g in self.groups:
            own=[j for j in rows if j['group_id']==g]
            self.assertEqual(len(own),4)
            self.assertTrue(all(y['due']-x['due']==86400 for x,y in zip(own,own[1:])))
    def test_group_collisions_are_spaced_when_many_groups_fill_multiple_days(self):
        with patch('store.sample_gap',return_value=12*3600):self.s.cycle_pool([self.p],None,'720',1,1,4)
        rows=self.s.rows('SELECT * FROM jobs ORDER BY due,id')
        self.assertTrue(all(y['due']-x['due']>=12*3600 for x,y in zip(rows,rows[1:])))
        for g in self.groups:
            own=[j for j in rows if j['group_id']==g]
            self.assertTrue(all(y['due']-x['due']>=86400 for x,y in zip(own,own[1:])))
    def test_no_post_failures_and_preparations_do_not_create_global_wait(self):
        ids=self.s.plan(self.p,30)
        for state,jid in zip(['error','prepared','cancelled','error'],ids):self.s.finish(jid,state,'No submission')
        self.s.set('next_allowed',time.time()+3600)
        self.assertEqual(self.s.refresh_global_cooldown(),0)
        self.s.finish(ids[0],'submitted','Visible')
        deadline=self.s.refresh_global_cooldown();self.assertGreater(deadline,time.time()+1700)
        self.s.finish(ids[1],'error','Focus failed');self.assertEqual(self.s.refresh_global_cooldown(),deadline)
        self.s.clear_jobs();self.assertEqual(self.s.refresh_global_cooldown(),deadline)
    def test_one_post_test_is_bounded_and_does_not_join_existing_queue(self):
        jid=self.s.prepare_test(self.p,self.groups[0]);job=self.s.rows('SELECT * FROM jobs WHERE id=?',(jid,))[0]
        self.assertEqual((job['state'],job['prepare_only'],job['group_id']),('queued',1,self.groups[0]))
        with self.assertRaises(ValueError):self.s.prepare_test(self.p,self.groups[1])
        self.assertEqual(len(self.s.rows('SELECT * FROM jobs')),1)
    def test_profile_matching_rejects_other_edge_sessions(self):
        data=Path(self.tmp.name)
        self.assertTrue(profile_matches(['msedge.exe','--user-data-dir='+str(data/'edge-profile')],data))
        self.assertTrue(profile_matches(['msedge.exe','--user-data-dir',str(data/'edge-profile')],data))
        self.assertFalse(profile_matches(['msedge.exe','--user-data-dir='+str(data/'edge-profile-other')],data))
        self.assertFalse(profile_matches(['msedge.exe'],data))
if __name__=='__main__':unittest.main()
