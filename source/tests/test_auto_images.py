import json,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from store import Store
from studio import Studio
import media,media_library
class AutoImageTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.directory=self.root/'media';self.directory.mkdir();self.s=Store(self.root/'db.sqlite3');self.s.set('content_ai',{'vision_model':'fake-vision'})
  for i in range(3):self.add_image(f'val{i}.png','Valorant',i)
  self.add_image('pubg.png','PUBG',9)
  self.gid=self.s.add_group('facebook.com/groups/auto-images','Test',link_policy='allow',category='Valorant');self.s.enable_group(self.gid,True);media_library.group_pools(self.s,self.gid,['Valorant'])
  self.studio=Studio(self.s,lambda:{'model':'fake','mode':'publish'},self.directory)
 def tearDown(self):self.tmp.cleanup()
 def add_image(self,name,pool,marker,flag=False):
  path=self.directory/name;path.write_bytes(b'\x89PNG\r\n\x1a\n'+bytes([marker])*20)
  media_library.register(self.s,self.directory,{'id':name,'kind':'image'},pool)
  a={'game':pool,'confidence':.99,'summary':'Ảnh game '+pool,'contains_url_or_qr':flag}
  with self.s.db() as c:c.execute('UPDATE media_catalog SET scan_hash=?,scan_model=?,analysis=? WHERE id=?',(media_library.fingerprint(path),'fake-vision',json.dumps(a),name))
 def answer(self):return {'title':'Giao lưu','body':'Mỗi người có thể lựa chọn vai trò phù hợp và trao đổi cách phối hợp trong đội. Những chia sẻ thực tế sẽ giúp buổi chơi có thêm góc nhìn.','body_no_link':'Bạn thích trao đổi điều gì khi cùng chơi một trận đấu? Mời chia sẻ trải nghiệm phối hợp với đồng đội.'}
 def wait(self):
  end=time.monotonic()+5
  while self.studio.lock.locked() and time.monotonic()<end:time.sleep(.01)
  self.assertFalse(self.studio.lock.locked());return self.s.get('studio_task')
 def test_requested_random_counts_one_two_three_are_within_correct_pool(self):
  with patch('media_library.random.SystemRandom') as rng:
   rng.return_value.randint.side_effect=[1,2,3]
   for count in [1,2,3]:
    selected=media_library.choose_pool(self.s,self.directory,'Valorant',1,3)
    self.assertEqual(len(selected),count);self.assertTrue(all(r['pool']=='Valorant' for r,a in selected))
 def test_one_available_photo_still_works_and_empty_pool_is_explicit(self):
  selected=media_library.choose_pool(self.s,self.directory,'PUBG',1,3);self.assertEqual(len(selected),1)
  with self.assertRaises(ValueError):media_library.choose_pool(self.s,self.directory,'CS2',1,3)
  with self.assertRaises(ValueError):media_library.choose_pool(self.s,self.directory,'Game',1,3)
 def test_manual_classification_does_not_require_scan_or_qr_analysis(self):
  media_library.archive(self.s,['val0.png'])
  (self.directory/'val1.png').write_bytes(b'\x89PNG\r\n\x1a\nchanged')
  with self.s.db() as c:c.execute("UPDATE media_catalog SET scan_hash='' WHERE id='val2.png'")
  self.add_image('qr.png','Valorant',10,flag=True)
  selected=media_library.eligible_images(self.s,self.directory,{'Valorant'})
  self.assertEqual({r['id'] for r,a in selected},{'val1.png','val2.png','qr.png'})
  self.assertTrue(all(a=={'game':'Valorant','kind':'image','source':'user_assigned'} for r,a in selected))
 def test_identical_uploads_are_deduplicated_and_share_last_used(self):
  self.add_image('copy.png','Valorant',0)
  selected=media_library.choose_pool(self.s,self.directory,'Valorant',1,3)
  self.assertTrue(all(r['pool']=='Valorant' for r,a in selected))
  media_library.mark_used(self.s,['val0.png'])
  rows=self.s.rows("SELECT last_used FROM media_catalog WHERE id IN ('val0.png','copy.png')")
  self.assertTrue(all(r['last_used']>0 for r in rows));self.assertEqual(rows[0]['last_used'],rows[1]['last_used'])
 def test_less_recently_used_photos_are_prioritized(self):
  media_library.mark_used(self.s,['val0.png'])
  with patch('media_library.random.SystemRandom') as rng:
   rng.return_value.randint.return_value=1
   self.assertNotEqual(media_library.choose_pool(self.s,self.directory,'Valorant',1,3)[0][0]['id'],'val0.png')
 def test_single_ai_auto_mode_replaces_stale_selection_and_attaches_both_variants(self):
  with patch.object(self.studio,'chat_json',return_value=self.answer()) as ai,patch('media_library.random.SystemRandom') as rng:
   rng.return_value.randint.return_value=2
   self.studio.start({'brief':'Giao lưu game cùng đồng đội.','category':'Valorant','image_mode':'auto','media_ids':['stale-not-in-library.png']});task=self.wait()
  self.assertEqual(task['status'],'done');self.assertEqual(task['result']['automatic_image_count'],2)
  row=self.s.rows('SELECT * FROM contents')[0];self.assertEqual(len(media.paths(row['media'])),2);self.assertEqual(row['media'],row['media_no_link']);self.assertEqual(self.s.rows('SELECT * FROM jobs'),[])
  self.assertEqual(len(ai.call_args.args[1]['attachments']),2)
 def test_missing_auto_images_stop_before_any_ai_call(self):
  with patch.object(self.studio,'chat_json') as ai:
   self.studio.start({'brief':'Nội dung game','category':'CS2','image_mode':'auto'});task=self.wait()
   ai.assert_not_called()
  self.assertEqual(task['status'],'error');self.assertEqual(self.s.rows('SELECT * FROM contents'),[])
 def test_manual_video_and_text_only_are_preserved(self):
  video=self.directory/'video.mp4';video.write_bytes(b'\x00\x00\x00\x18ftypmp42')
  with patch.object(self.studio,'chat_json',return_value=self.answer()):
   self.studio.start({'brief':'Trao đổi về game','category':'Valorant','image_mode':'manual','media_ids':['video.mp4']});task=self.wait()
  self.assertEqual(task['status'],'done');self.assertEqual(task['result']['attachments'][0]['kind'],'video');self.assertEqual(task['result']['automatic_image_count'],0)
  files,alt,chosen=media_library.resolve_for_save(self.s,self.directory,{'image_mode':'manual'});self.assertEqual((files,alt,chosen),('','',[]))
 def test_save_autoselects_when_empty_but_keeps_existing_manual_attachments(self):
  with patch('media_library.random.SystemRandom') as rng:
   rng.return_value.randint.return_value=3
   files,alt,selected=media_library.resolve_for_save(self.s,self.directory,{'category':'Valorant','image_mode':'auto'})
  self.assertEqual(len(selected),3);self.assertEqual(len(media.paths(files)),3);self.assertEqual(files,alt)
  files,alt,selected=media_library.resolve_for_save(self.s,self.directory,{'category':'Valorant','image_mode':'auto','media_ids':['val0.png']})
  self.assertEqual(len(media.paths(files)),1);self.assertEqual(selected,[])
 def test_group_random_mode_chooses_available_range_without_fixed_count_failure(self):
  with patch.object(self.studio,'chat_json',return_value=self.answer()),patch('media_library.random.SystemRandom') as rng:
   rng.return_value.randint.return_value=2
   self.studio.draft_groups({'ids':[self.gid],'brief':'Giao lưu về game','media_count_mode':'random','media_count':10});task=self.wait()
  self.assertEqual(task['status'],'done');self.assertEqual(len(media.paths(self.s.rows('SELECT media FROM contents')[0]['media'])),2)
 def test_cross_game_override_is_rejected(self):
  with self.assertRaises(ValueError):self.studio.start({'brief':'Game','category':'Valorant','image_mode':'auto','image_pool':'PUBG'})
  with self.assertRaises(ValueError):media_library.resolve_for_save(self.s,self.directory,{'category':'Valorant','image_mode':'auto','image_pool':'PUBG'})
if __name__=='__main__':unittest.main()
