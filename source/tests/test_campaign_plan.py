"""Automatic rotation and finite campaigns with fake AI and temporary data."""
import sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from store import Store
from studio import Studio
import campaign_plan,media_library

class CampaignTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.media=self.root/'media';self.media.mkdir()
  self.s=Store(self.root/'state.db');(self.media/'test.png').write_bytes(b'\x89PNG\r\n\x1a\n'+b'fake')
  media_library.initialize(self.s,self.media);media_library.assign(self.s,self.media,['test.png'],'Valorant')
  self.ids=[]
  for n in range(40):
   gid=self.s.add_group('facebook.com/groups/test'+str(n),'Group '+str(n),link_policy='allow',category='Valorant')
   self.s.enable_group(gid,True);self.ids.append(gid)
  self.obj={'selection_mode':'auto','total_posts':35,'groups_per_day':20,'horizon':3,'minutes':'1','brief':'Dịch vụ game Valorant.','autopost':False}
  self.now=1792886400
 def tearDown(self):self.tmp.cleanup()
 def plan(self,**kw):return campaign_plan.preview(self.s,self.media,{**self.obj,**kw},now=self.now)
 def test_coverage_sixty_groups_no_duplicates(self):
  for n in range(40,60):
   gid=self.s.add_group('facebook.com/groups/test'+str(n),'Group '+str(n),link_policy='allow',category='Valorant')
   self.s.enable_group(gid,True);self.ids.append(gid)
  p=self.plan(coverage_once=True,total_posts=5,horizon=3,minutes='1')
  self.assertEqual(p['requested'],60);self.assertEqual(p['unique_groups'],60)
  self.assertEqual(len(p['items']),60);self.assertEqual(p['uncovered_groups'],[])
  self.assertEqual(len({i['group_id'] for i in p['items']}),60)
  self.assertTrue(all(sum(i['day']==d for i in p['items'])<=20 for d in {i['day'] for i in p['items']}))
 def test_coverage_lists_excluded_and_time_limited_groups(self):
  self.s.set_link_policy(self.ids[0],'unknown')
  p=self.plan(coverage_once=True,horizon=1,minutes='1')
  self.assertEqual(p['unique_groups'],20);self.assertEqual(len(p['uncovered_groups']),20)
  self.assertTrue(any(g['id']==self.ids[0] and g['reason']=='Chưa rõ quyền link' for g in p['uncovered_groups']))
  self.assertEqual(len({i['group_id'] for i in p['items']}),len(p['items']))

 def test_more_than_thirty_groups_rotate_without_repeating_first(self):
  p=self.plan();self.assertEqual(p['estimated_posts'],35);self.assertEqual(p['unique_groups'],35)
  dates={i['day'] for i in p['items']};self.assertEqual(len(dates),2)
  for d in dates:self.assertLessEqual(sum(i['day']==d for i in p['items']),20)
  self.assertEqual(p['items'],self.plan()['items']);self.assertEqual(self.s.rows('SELECT * FROM jobs'),[])
 def test_insufficient_capacity_and_manual_selection(self):
  p=self.plan(selection_mode='manual',ids=self.ids[:2],total_posts=10,horizon=2)
  self.assertEqual(p['estimated_posts'],4);self.assertEqual(p['unique_groups'],2)
  for gid in self.ids[:2]:
   due=[i['due'] for i in p['items'] if i['group_id']==gid];self.assertGreaterEqual(due[1]-due[0],86400)
 def test_history_prioritizes_groups_not_yet_used(self):
  gid=self.plan(total_posts=1)['items'][0]['group_id']
  with self.s.db() as c:c.execute("INSERT INTO jobs(group_id,group_name,url,body,media,due,created,updated,state,attempted_at) VALUES(?,?,?,?,'',?,?,?,'submitted',?)",(gid,'old','url','old',self.now-86400,self.now-86400,self.now-86400,self.now-86400))
  self.assertNotEqual(self.plan(total_posts=1)['items'][0]['group_id'],gid)
 def test_excludes_unknown_missing_media_but_not_old_uncertainty_forever(self):
  with self.s.db() as c:
   c.execute("UPDATE groups SET link_policy='unknown' WHERE id=?",(self.ids[0],))
   c.execute("UPDATE groups SET category='PUBG' WHERE id=?",(self.ids[1],))
   c.execute("INSERT INTO jobs(group_id,group_name,url,body,media,due,created,updated,state) VALUES(?,?,?,?,'',?,?,?,'uncertain')",(self.ids[2],'x','x','x',0,0,0))
  p=self.plan();self.assertEqual(p['eligible_groups'],38);self.assertEqual(len(p['excluded']),2)
 def test_respects_lower_settings_cap(self):
  self.s.set('daily_group_limit',3);p=self.plan(total_posts=8)
  self.assertEqual(p['groups_per_day'],3)
  for d in {i['day'] for i in p['items']}:self.assertLessEqual(sum(i['day']==d for i in p['items']),3)
 def test_ai_budget_limits_estimate_without_calling_provider(self):
  self.s.set('content_ai',{'writer_provider':'xkiro','daily_calls':2})
  p=self.plan(total_posts=10)
  self.assertEqual(p['estimated_posts'],2);self.assertEqual(p['ai_calls_remaining'],2)
  self.assertEqual(self.s.rows('SELECT * FROM content_ai_calls'),[])
 def test_new_collision_rolls_back_entire_schedule(self):
  p=self.plan(total_posts=2);results=[]
  for i,item in enumerate(p['items']):
   cid=self.s.content('Body',category='Valorant');self.s.targets(cid,'selected',[item['group_id']])
   results.append({'item':(item['group_id'],i),'result':cid})
  gid=p['items'][1]['group_id']
  with self.s.db() as c:c.execute("INSERT INTO jobs(group_id,group_name,url,body,media,due,created,updated,state) VALUES(?,?,?,?,'',?,?,?,'draft')",(gid,'other','url','body',0,0,0))
  with self.assertRaises(ValueError):campaign_plan.schedule(self.s,p,results)
  self.assertEqual(len(self.s.rows('SELECT * FROM jobs')),1)

 def test_cancelled_reservation_returns_group_to_ai_plan(self):
  gid=self.ids[0];cid=self.s.content('Waiting content',category='Valorant')
  self.s.targets(cid,'selected',[gid]);jobs=self.s.cycle_pool([cid],[gid],30,1,1,1,start=self.now)
  before=self.plan(selection_mode='manual',ids=[gid],total_posts=1)
  self.assertEqual(before['estimated_posts'],0)
  self.assertEqual(self.s.cancel_jobs(jobs),len(jobs))
  after=self.plan(selection_mode='manual',ids=[gid],total_posts=1)
  self.assertEqual(after['estimated_posts'],1)
  newcid=self.s.content('A fresh generated caption',category='Valorant');self.s.targets(newcid,'selected',[gid])
  newjobs=campaign_plan.schedule(self.s,after,[{'item':(gid,0),'result':newcid}])
  self.assertEqual(len(newjobs),1)
  self.assertEqual(self.s.rows('SELECT state FROM jobs WHERE id=?',(jobs[0],))[0]['state'],'cancelled')

 def test_old_unknown_result_allows_new_content_after_group_cooldown(self):
  gid=self.ids[0];deadline=self.now+86400
  with self.s.db() as c:
   c.execute("INSERT INTO jobs(group_id,group_name,url,body,media,due,created,updated,state,attempted_at,post_attempted) VALUES(?,?,?,?,'',?,?,?,'uncertain',?,1)",(gid,'old','url','Old unknown caption',self.now,self.now,self.now,self.now))
   c.execute('UPDATE groups SET next_post_after=? WHERE id=?',(deadline,gid))
  plan=self.plan(selection_mode='manual',ids=[gid],total_posts=1)
  self.assertEqual(plan['estimated_posts'],1);self.assertGreaterEqual(plan['items'][0]['due'],deadline)
  cid=self.s.content('Old unknown caption',category='Valorant');self.s.targets(cid,'selected',[gid])
  with self.assertRaisesRegex(ValueError,'chưa rõ'):campaign_plan.schedule(self.s,plan,[{'item':(gid,0),'result':cid}])
  fresh=self.s.content('New distinct caption',category='Valorant');self.s.targets(fresh,'selected',[gid])
  self.assertEqual(len(campaign_plan.schedule(self.s,plan,[{'item':(gid,0),'result':fresh}])),1)
 def test_exact_number_of_generated_posts_and_schedules(self):
  self.s.set('owner_id',123);runs=[]
  studio=Studio(self.s,lambda:{'mode':'publish','model':'fake'},self.media,on_run=lambda **kw:runs.append(kw))
  answer={'title':'Bài mới','body':'Ghé bên mình trao đổi các lựa chọn nhé.','body_no_link':'Mời anh em tìm hiểu thêm.'}
  with patch.object(studio,'chat_json',return_value=answer),patch('studio.copied',return_value=False):
   studio.draft_groups({**self.obj,'total_posts':4,'autopost':True})
   end=time.monotonic()+5
   while studio.lock.locked() and time.monotonic()<end:time.sleep(.01)
   self.assertFalse(studio.lock.locked())
  self.assertEqual(self.s.get('studio_task')['status'],'done',self.s.get('studio_task'))
  self.assertEqual(len(self.s.rows('SELECT * FROM contents')),4)
  jobs=self.s.rows('SELECT * FROM jobs');self.assertEqual(len(jobs),4)
  self.assertEqual({j['state'] for j in jobs},{'queued'});self.assertEqual(len(runs),1)
  self.assertEqual(len({j['content_id'] for j in jobs}),4)
  self.assertTrue(all(j['campaign_daily_limit']==20 for j in jobs))

if __name__=='__main__':unittest.main()
