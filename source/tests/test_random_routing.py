import sys,tempfile,unittest,random,time
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from store import Store
class RandomRoutingTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.s=Store(Path(self.tmp.name)/'db');self.gs=[]
  for i,cat in enumerate(('Valorant', 'Valorant', 'CS2')):
   gid=self.s.add_group(f'facebook.com/groups/random{i}',category=cat,link_policy='allow');self.s.enable_group(gid,True);self.gs.append(gid)
  self.ps=[self.s.content('Frozen A',media='image-a.png',category='Valorant'),self.s.content('Frozen B',media='image-b.png',category='Valorant'),self.s.content('Frozen CS2',category='CS2')]
 def tearDown(self):self.tmp.cleanup()
 def test_random_shuffles_groups_and_posts_only_within_their_game(self):
  with patch('store.random.SystemRandom',return_value=random.Random(4)):
   ids=self.s.cycle_pool(self.ps,self.gs,30,1,1,4,routing_mode='random')
  rows=self.s.rows('SELECT * FROM jobs ORDER BY due,id');self.assertTrue(ids)
  self.assertEqual({j['group_id'] for j in rows},set(self.gs))
  self.assertNotEqual([j['group_id'] for j in rows[:3]],self.gs)
  expected={self.ps[0]:('Frozen A','image-a.png'),self.ps[1]:('Frozen B','image-b.png'),self.ps[2]:('Frozen CS2','')}
  for j in rows:
   self.assertEqual((j['body'],j['media']),expected[j['content_id']]);self.assertEqual(j['routing_mode'],'random')
   self.assertEqual(j['content_id']==self.ps[2],j['group_id']==self.gs[2])
  for gid in self.gs:
   jobs=[j for j in rows if j['group_id']==gid]
   self.assertTrue(all(b['due']-a['due']>=86400 for a,b in zip(jobs,jobs[1:])))
   if gid!=self.gs[2]:self.assertTrue(all(a['content_id']!=b['content_id'] for a,b in zip(jobs,jobs[1:])))
 def test_category_mode_still_rejects_mismatched_groups(self):
  self.assertEqual(self.s.cycle_pool([self.ps[2]],self.gs[:2],30,1,1,3),[])
  self.assertEqual(self.s.cycle_pool([self.ps[2]],self.gs[:2],30,1,1,3,routing_mode='random'),[])
 def test_explicit_random_target_cannot_cross_games(self):
  with self.assertRaises(ValueError):self.s.targets(self.ps[2],'selected',[self.gs[0]],routing_mode='random')
 def test_claim_blocks_legacy_cross_game_random_job(self):
  ids=self.s.cycle_pool([self.ps[0]],[self.gs[0]],30,1,1,1,routing_mode='random')
  with self.s.db() as c:c.execute('UPDATE jobs SET content_id=? WHERE id=?',(self.ps[2],ids[0]))
  self.s.approve(ids);self.s.set('running',True)
  self.assertIsNone(self.s.claim())
  self.assertEqual(self.s.rows('SELECT state FROM jobs')[0]['state'],'error')
 def test_random_job_survives_claim_category_check(self):
  ids=self.s.cycle_pool(self.ps,self.gs,30,1,1,3,routing_mode='random');self.s.approve(ids);self.s.set('running',True)
  job=self.s.claim();self.assertIsNotNone(job);self.assertEqual(job['routing_mode'],'random')
 def test_explicit_empty_post_targets_are_respected(self):
  self.s.targets(self.ps[0],'selected',[])
  self.assertEqual(self.s.cycle_pool([self.ps[0]],self.gs,30,1,1,3,routing_mode='random'),[])
 def test_unknown_link_policy_still_blocks_random(self):
  for gid in self.gs:self.s.set_link_policy(gid,'unknown')
  self.assertEqual(self.s.cycle_pool(self.ps,self.gs,30,1,1,3,routing_mode='random'),[])
if __name__=='__main__':unittest.main()
