"""Campaign integration with fake AI and a temporary database; no live posting."""
import json,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from store import Store
from studio import Studio
import media_library

class BatchAITests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.media=self.root/'media';self.media.mkdir();self.s=Store(self.root/'db.sqlite3')
  image=self.media/'image.png';image.write_bytes(b'\x89PNG\r\n\x1a\n'+b'fake')
  media_library.initialize(self.s,self.media);media_library.assign(self.s,self.media,['image.png'],'Valorant')
  self.s.set('content_ai',{'vision_model':'fake-vision'});self.s.set('owner_id',123)
  a={'game':'Valorant','confidence':.99,'summary':'Ảnh game','contains_url_or_qr':False}
  with self.s.db() as c:c.execute('UPDATE media_catalog SET scan_hash=?,scan_model=?,analysis=?',(media_library.fingerprint(image),'fake-vision',json.dumps(a)))
  self.ids=[]
  for name in ['alpha','beta']:
   gid=self.s.add_group('facebook.com/groups/'+name,name,link_policy='allow',category='Valorant');self.s.enable_group(gid,True);media_library.group_pools(self.s,gid,['Valorant']);self.ids.append(gid)
  self.runs=[]
  def run(**kwargs):self.runs.append(kwargs);self.s.set('running',True)
  self.studio=Studio(self.s,lambda:{'model':'fake','mode':'publish'},self.media,on_run=run)
  self.bodies=['Khi giao tiếp trong trận, mình thường báo vị trí trước khi đề nghị đổi hướng. Cách gọi ngắn giúp cả đội phối hợp và ra quyết định rõ ràng hơn.',
   'Một góc khác từ ảnh: giao diện hiển thị các mục cài đặt để người chơi theo dõi. Bạn quan tâm chi tiết nào khi xem màn hình này?',
   'Hôm nay cùng bàn về việc chọn vai trò phù hợp trong đội hình. Mỗi người có sở thích riêng, nên thống nhất từ đầu sẽ thuận tiện hơn khi chơi chung.',
   'Thử nhìn lại thói quen sau mỗi ván đấu: ghi ra một điều đã làm tốt và một điểm cần thay đổi. Những ghi chú ngắn có thể giúp buổi chơi tiếp theo có mục tiêu rõ hơn.',
   'Nếu có thời gian luyện tập, bạn thích dành riêng một buổi để làm quen bản đồ hay chơi cùng bạn bè ngay? Mình muốn nghe cách mọi người sắp xếp.',
   'Từ ảnh này có thể trao đổi về cách bố trí giao diện trên màn hình. Những lựa chọn nào giúp bạn đọc thông tin thuận tiện nhất trong lúc chơi?']
 def tearDown(self):self.tmp.cleanup()
 def answer(self,body):return {'title':'Bài AI','body':body,'body_no_link':body}
 def wait(self):
  end=time.monotonic()+8
  while self.studio.lock.locked() and time.monotonic()<end:time.sleep(.01)
  self.assertFalse(self.studio.lock.locked());return self.s.get('studio_task')
 def options(self,**extra):return {'ids':self.ids,'brief':'Giao lưu về chơi game và đọc giao diện, không hứa hẹn kết quả.','posts_per_group':2,'horizon':2,**extra}
 def test_batch_avoids_newest_history_and_remembers_direction_between_runs(self):
  for i in range(30):self.s.content('Archive marker '+str(i)+' old independent description',category='Valorant')
  contexts=[]
  def answer(system,context):
   contexts.append(dict(context));return self.answer(self.bodies[len(contexts)-1])
  with patch.object(self.studio,'chat_json',side_effect=answer):
   for _ in range(2):
    self.studio.draft_groups(self.options(ids=self.ids[:1],posts_per_group=1));self.wait()
  self.assertEqual(len(contexts),2)
  self.assertIn('Archive marker 29',contexts[0]['recent_posts_to_avoid'][-1])
  self.assertFalse(any('Archive marker 0 ' in x for x in contexts[0]['recent_posts_to_avoid']))
  self.assertNotEqual(contexts[0]['writing_direction'],contexts[1]['writing_direction'])
  self.assertIn('length_target',contexts[0])
 def test_batch_generation_appends_the_same_editable_footer_after_ai(self):
  import post_footer
  footer='https ://discord.gg/DzdDGgry (bỏ dấu cách trước dấu hai chấm)'
  post_footer.save(self.s,{'enabled':True,'text':footer})
  with patch.object(self.studio,'chat_json',side_effect=[self.answer(b) for b in self.bodies]):
   self.studio.draft_groups(self.options(posts_per_group=1));task=self.wait()
  self.assertEqual(task['status'],'done')
  for row in self.s.rows('SELECT body,body_no_link,footer_text FROM contents'):
   self.assertTrue(row['body'].endswith(footer));self.assertEqual(row['footer_text'],footer);self.assertNotIn('discord.gg',row['body_no_link'])
 def test_multiple_variations_are_bound_to_groups_and_draft_only(self):
  with patch.object(self.studio,'chat_json',side_effect=[self.answer(b) for b in self.bodies]) as ai:
   self.studio.draft_groups(self.options());task=self.wait()
  self.assertEqual(task['status'],'done');self.assertEqual(ai.call_count,4);self.assertEqual(len(self.s.rows('SELECT * FROM contents')),4)
  targets=self.s.rows('SELECT group_id FROM content_targets');self.assertEqual([t['group_id'] for t in targets].count(self.ids[0]),2)
  self.assertEqual(self.s.rows('SELECT * FROM jobs'),[]);self.assertEqual(self.runs,[])
  self.assertIn('recent_posts_to_avoid',ai.call_args.args[1])
 def test_autopost_creates_and_approves_only_new_campaign(self):
  old=self.s.content('Existing library draft',category='Other')
  with patch.object(self.studio,'chat_json',side_effect=[self.answer(b) for b in self.bodies]):
   self.studio.draft_groups(self.options(autopost=True));task=self.wait()
  self.assertEqual(task['status'],'done');jobs=self.s.rows('SELECT * FROM jobs');self.assertEqual(len(jobs),4)
  self.assertTrue(all(j['state']=='queued' and j['content_id']!=old and j['routing_mode']=='random' for j in jobs))
  for j in jobs:self.assertEqual(self.s.rows('SELECT group_id FROM content_targets WHERE content_id=?',(j['content_id'],))[0]['group_id'],j['group_id'])
  self.assertEqual(len(self.runs),1);self.assertIn('expected_revision',self.runs[0]);self.assertEqual(self.s.get('batch_options')['posts_per_group'],2)
 def test_duplicate_keeps_rewriting_until_provider_limit(self):
  body=self.answer(self.bodies[0])
  with patch.object(self.studio,'chat_json',side_effect=[body,body,body,RuntimeError('HTTP 429: limit')]) as ai:
   self.studio.draft_groups(self.options(ids=[self.ids[0]]));task=self.wait()
  self.assertEqual(task['status'],'error');self.assertEqual(ai.call_count,4);self.assertEqual(len(self.s.rows('SELECT * FROM contents')),1)
  self.assertTrue(self.s.get('ai_rewrite_drafts'))
 def test_group_rewrites_until_fourth_response_passes(self):
  old=self.answer(self.bodies[0]);clean=self.answer(self.bodies[1])
  self.s.content(old['body'],category='Valorant')
  with patch.object(self.studio,'chat_json',side_effect=[old,old,old,clean]) as ai:
   self.studio.draft_groups(self.options(ids=self.ids[:1],posts_per_group=1));task=self.wait()
  self.assertEqual(task['status'],'done');self.assertEqual(ai.call_count,4)
  self.assertEqual(len(self.s.rows('SELECT * FROM contents')),2)
  self.assertEqual(self.s.rows('SELECT * FROM jobs'),[])
  self.assertEqual(self.s.get('ai_rewrite_drafts')['group:'+str(self.ids[0])+':item:0']['status'],'accepted')

 def test_pause_during_generation_keeps_draft_and_never_activates(self):
  def ai(*args):self.s.set('control_revision',self.s.get('control_revision',0)+1);return self.answer(self.bodies[0])
  with patch.object(self.studio,'chat_json',side_effect=ai):
   self.studio.draft_groups(self.options(autopost=True));task=self.wait()
  self.assertEqual(task['status'],'error');self.assertEqual(self.s.rows('SELECT * FROM jobs'),[]);self.assertEqual(self.runs,[])
 def test_pause_after_approval_returns_new_jobs_to_draft(self):
  approve=self.s.approve
  def stop(ids):
   result=approve(ids);self.s.set('control_revision',self.s.get('control_revision',0)+1);return result
  with patch.object(self.studio,'chat_json',side_effect=[self.answer(b) for b in self.bodies]),patch.object(self.s,'approve',side_effect=stop):
   self.studio.draft_groups(self.options(autopost=True));task=self.wait()
  self.assertEqual(task['status'],'error');self.assertTrue(all(j['state']=='draft' for j in self.s.rows('SELECT state FROM jobs')));self.assertEqual(self.runs,[])
 def test_existing_queued_campaign_blocks_before_calling_ai(self):
  cid=self.s.content('Old campaign',category='Valorant');jobs=self.s.plan(cid,30);self.s.approve(jobs)
  with patch.object(self.studio,'chat_json') as ai:
   with self.assertRaises(ValueError):self.studio.draft_groups(self.options(autopost=True))
   ai.assert_not_called()
 def test_unpaired_disabled_or_excessive_batch_is_rejected(self):
  self.s.set('owner_id',None)
  with self.assertRaises(ValueError):self.studio.draft_groups(self.options(autopost=True))
  self.s.set('owner_id',123);self.s.enable_group(self.ids[0],False)
  with self.assertRaises(ValueError):self.studio.draft_groups(self.options(autopost=True))
  with self.assertRaises(ValueError):self.studio.draft_groups(self.options(posts_per_group=8))
 def test_comment_link_is_frozen_only_when_group_allows_it(self):
  self.s.set_link_policy(self.ids[1],'deny');self.s.set_comment_policy(self.ids[1],'deny')
  with patch.object(self.studio,'chat_json',side_effect=[self.answer(b) for b in self.bodies]):
   self.studio.draft_groups(self.options(autopost=True,posts_per_group=1,comment_mode='always',comment_link='https://discord.gg/qwwrrMcP'));task=self.wait()
  self.assertEqual(task['status'],'done')
  jobs=self.s.rows('SELECT group_id,comment_text FROM jobs')
  self.assertTrue(any(j['comment_text']=='https://discord.gg/qwwrrMcP' for j in jobs if j['group_id']==self.ids[0]));self.assertTrue(all(not j['comment_text'] for j in jobs if j['group_id']==self.ids[1]))

if __name__=='__main__':unittest.main()
