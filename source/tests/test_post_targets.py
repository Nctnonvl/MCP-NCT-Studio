import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from store import Store
class TargetPoolTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.s=Store(Path(self.tmp.name)/'state.db');self.groups=[]
        for name,cat,policy in [('delta-a','Delta','allow'),('delta-b','Delta','deny'),('other','Other','allow')]:
            gid=self.s.add_group('facebook.com/groups/'+name,name,category=cat,link_policy=policy);self.s.enable_group(gid,True);self.groups.append(gid)
        self.a,self.b,self.other=self.groups
        self.p=self.s.content('First https://example.com',body_no_link='First without link',category='Delta')
        self.q=self.s.content('Second',category='Delta');self.r=self.s.content('Different game',category='Other')
    def tearDown(self):self.tmp.cleanup()
    def test_routing_shuffle_and_spacing(self):
        self.s.targets(self.p,'selected',[self.a,self.b]);self.s.targets(self.q,'selected',[self.a]);self.s.targets(self.r,'selected',[self.other])
        self.assertTrue(self.s.cycle_pool([self.p,self.q,self.r],[self.a,self.b],30,1,1,8))
        a=self.s.rows('SELECT * FROM jobs WHERE group_id=? ORDER BY due',(self.a,));b=self.s.rows('SELECT * FROM jobs WHERE group_id=? ORDER BY due',(self.b,))
        self.assertEqual({j['content_id'] for j in a},{self.p,self.q})
        self.assertTrue(all(x['content_id']!=y['content_id'] for x,y in zip(a,a[1:])))
        self.assertTrue(all(j['content_id']==self.p and j['body']=='First without link' for j in b))
        self.assertFalse(self.s.rows('SELECT * FROM jobs WHERE group_id=?',(self.other,)))
        self.assertTrue(all(y['due']-x['due']>=86400 for rows in (a,b) for x,y in zip(rows,rows[1:])))
    def test_empty_targets_never_fall_back(self):
        self.s.targets(self.p,'selected',[])
        self.assertEqual(self.s.cycle_pool([self.p],None,30,1,1,4),[]);self.assertEqual(self.s.plan(self.p,30),[])
        with self.assertRaises(ValueError):self.s.cycle_pool([self.p],[],30)
    def test_cross_game_target_rejected_atomically(self):
        self.s.targets(self.p,'selected',[self.a])
        with self.assertRaises(ValueError):self.s.targets(self.p,'selected',[self.other])
        self.assertEqual(self.s.rows('SELECT group_id FROM content_targets WHERE content_id=?',(self.p,)),[{'group_id':self.a}])
    def test_change_cancels_only_source_pending_and_blocks_working(self):
        self.s.targets(self.p,'selected',[self.a]);self.s.targets(self.q,'selected',[self.b]);self.s.cycle_pool([self.p,self.q],None,30,1,1,3)
        count=len(self.s.rows('SELECT id FROM jobs WHERE content_id=?',(self.p,)))
        self.assertEqual(self.s.targets(self.p,'selected',[self.b]),count)
        self.assertTrue(all(j['state']=='cancelled' for j in self.s.rows('SELECT state FROM jobs WHERE content_id=?',(self.p,))))
        self.assertTrue(all(j['state']=='draft' for j in self.s.rows('SELECT state FROM jobs WHERE content_id=?',(self.q,))))
        with self.s.db() as c:c.execute("UPDATE jobs SET state='working' WHERE content_id=?",(self.q,))
        with self.assertRaises(ValueError):self.s.targets(self.q,'selected',[self.a])
    def test_missing_no_link_variant_skips_deny_group(self):
        cid=self.s.content('https://example.com',category='Delta');self.s.cycle_pool([cid],None,30,1,1,3)
        self.assertEqual({j['group_id'] for j in self.s.rows('SELECT group_id FROM jobs')},{self.a})
if __name__=='__main__':unittest.main()
