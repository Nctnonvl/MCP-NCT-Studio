import io,json,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import content_ai,media_library,media
from store import Store
from studio import Studio

class ContentMediaTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.directory=self.root/'media';self.s=Store(self.root/'db.sqlite3');media_library.initialize(self.s,self.directory)
  content_ai.save_config(self.s,{'writer_key':'writer-test-key','vision_key':'vision-test-key'})
 def tearDown(self):self.tmp.cleanup()
 def image(self,name='one.png',pool='Valorant'):
  self.directory.joinpath(name).write_bytes(b'\x89PNG\r\n\x1a\n'+b'fake-image-data')
  media_library.register(self.s,self.directory,{'id':name,'kind':'image'},pool);return name
 def free_model(self,**changes):
  return {'id':content_ai.DEFAULT_VISION,'name':'Vision free','is_free':True,'status':'active','type':'chat','input_types':['text','image'],'is_pro':False,**changes}
 def answer(self,game='Valorant',flag=False):return {'game':game,'confidence':.95,'summary':'Ảnh màn hình game','visible_text':'','contains_url_or_qr':flag}
 def group(self,name='one'):
  gid=self.s.add_group('facebook.com/groups/'+name,name,link_policy='allow',category='')
  media_library.group_pools(self.s,gid,['Valorant']);return gid
 def test_existing_exact_category_seeds_once_user_can_clear(self):
  gid=self.s.add_group('facebook.com/groups/seed','Seed',category='The Isle')
  media_library.initialize(self.s,self.directory)
  self.assertEqual(self.s.rows('SELECT pool FROM group_media_pools WHERE group_id=?',(gid,)),[{'pool':'The isle'}])
  media_library.group_pools(self.s,gid,[]);media_library.initialize(self.s,self.directory)
  self.assertEqual(self.s.rows('SELECT pool FROM group_media_pools WHERE group_id=?',(gid,)),[])
 def test_public_configuration_never_returns_keys_and_blank_preserves(self):
  old=content_ai.config(self.s,True);content_ai.save_config(self.s,{'writer_key':'','vision_key':''})
  self.assertEqual(content_ai.config(self.s,True),old)
  self.assertNotIn('test-key',json.dumps(content_ai.config(self.s)))
  with self.assertRaises(ValueError):content_ai.save_config(self.s,{'writer_model':'paid-model'})
 def test_missing_key_never_sends_request(self):
  self.s.set('content_ai',{})
  with patch('content_ai.request_json') as http:
   with self.assertRaises(ValueError):content_ai.check_vision(self.s)
   http.assert_not_called()
 def test_endpoints_and_vision_payload_remain_separate(self):
  name=self.image();response={'choices':[{'message':{'content':json.dumps(self.answer())}}]}
  with patch('content_ai.request_json',side_effect=[{'data':[self.free_model()]},response]) as http:
   content_ai.completion(self.s,'kira','vision',[{'role':'user','content':[{'type':'image_url','image_url':{'url':'data:image/png;base64,fake'}}]}])
   call=http.call_args;self.assertTrue(call.args[0].startswith(content_ai.KIRA));self.assertIn('image_url',json.dumps(call.args[1]));self.assertEqual(call.kwargs['headers']['Authorization'],'Bearer vision-test-key')
  with patch('content_ai.request_json',return_value={'choices':[{'message':{'content':'{"body":"hello"}'}}]}) as http:
   content_ai.writer_json(self.s,'write',{'brief':'facts'})
   call=http.call_args;self.assertIn('api.xkiro.com',call.args[0]);self.assertNotIn('image_url',json.dumps(call.args[1]));self.assertEqual(call.kwargs['headers']['Authorization'],'Bearer writer-test-key')
 def test_error_redacts_key_no_retry_or_failover(self):
  with patch('content_ai.request_json',side_effect=RuntimeError('vision-test-key')) as http:
   with self.assertRaises(RuntimeError) as err:content_ai.completion(self.s,'kira','vision',[])
   self.assertNotIn('vision-test-key',str(err.exception));self.assertEqual(http.call_count,1)
 def test_call_cap_counts_failed_calls_per_provider(self):
  content_ai.save_config(self.s,{'daily_calls':1})
  content_ai.reserve(self.s,'kira','vision','test')
  with self.assertRaises(ValueError):content_ai.reserve(self.s,'kira','vision','test')
  content_ai.reserve(self.s,'xkiro','write','test')
 def test_free_vision_metadata_requires_vision_free_active_nonpro_and_unexpired(self):
  self.assertTrue(content_ai.free_vision_model(self.free_model()))
  for change in [{'is_free':False},{'status':'disabled'},{'input_types':['text']},{'is_pro':True},{'promo_end_at':'2020-01-01T00:00:00Z'},{'promo_end_at':'invalid'},{'input_types':None}]:
   self.assertFalse(content_ai.free_vision_model(self.free_model(**change)))
 def test_free_only_guard_never_posts_when_pricing_or_vision_is_unknown(self):
  with patch('content_ai.request_json',return_value={'data':[self.free_model(is_free=False)]}) as http:
   with self.assertRaisesRegex(RuntimeError,'miễn phí'):content_ai.completion(self.s,'kira','vision',[])
   self.assertEqual(http.call_count,1);self.assertEqual(http.call_args.args[0],content_ai.KIRA+'/models');self.assertIsNone(http.call_args.args[1]);self.assertEqual(self.s.rows('SELECT * FROM content_ai_calls'),[])
 def test_price_is_rechecked_for_each_scan_and_never_falls_back(self):
  responses=[{'data':[self.free_model()]},{'choices':[{'message':{'content':'{}'}}]},{'data':[self.free_model(is_free=False)]}]
  with patch('content_ai.request_json',side_effect=responses) as http:
   content_ai.completion(self.s,'kira','vision',[])
   with self.assertRaises(RuntimeError):content_ai.completion(self.s,'kira','vision',[])
   self.assertEqual(http.call_count,3)
   self.assertNotIn('headers',http.call_args_list[0].kwargs)
 def test_non_kira_prefix_free_vision_model_can_be_saved(self):
  content_ai.save_config(self.s,{'vision_model':'longcat-2.5-preview-free'})
  self.assertEqual(content_ai.config(self.s)['vision_model'],'longcat-2.5-preview-free')
 def test_archive_excludes_random_preserves_original_and_saved_post_then_restores(self):
  name=self.image();gid=self.group()
  files=media.resolve([name],self.directory);cid=self.s.content('Saved',files)
  media_library.archive(self.s,[name]);media_library.initialize(self.s,self.directory)
  self.assertTrue((self.directory/name).is_file());self.assertEqual(self.s.rows('SELECT media FROM contents WHERE id=?',(cid,))[0]['media'],files)
  with self.assertRaises(ValueError):media_library.choose(self.s,self.directory,gid)
  with patch('content_ai.completion') as ai:
   with self.assertRaises(ValueError):media_library.scan(self.s,self.directory,name)
   ai.assert_not_called()
  media_library.archive(self.s,[name],restore=True)
  self.assertEqual(media_library.choose(self.s,self.directory,gid)[0][0]['id'],name)
 def test_archive_invalid_batch_is_atomic(self):
  name=self.image()
  with self.assertRaises(ValueError):media_library.archive(self.s,[name,'missing.png'])
  self.assertEqual(media_library.catalog(self.s)[0]['archived'],0)
  with self.assertRaises(ValueError):media_library.archive(self.s,['../one.png'])
 def test_archive_deduplicates_and_keeps_other_pool_images(self):
  one=self.image();two=self.image('two.png','PUBG')
  self.assertEqual(media_library.archive(self.s,[one,one]),1)
  rows={m['id']:m for m in media_library.catalog(self.s)}
  self.assertEqual(rows[one]['archived'],1);self.assertEqual(rows[two]['archived'],0)
 def test_scan_removed_and_changed_valid_file_still_eligible(self):
  name=self.image();gid=self.group()
  with patch('content_ai.completion') as ai:
   with self.assertRaisesRegex(ValueError,'Đã bỏ quét'):media_library.scan(self.s,self.directory,name)
   self.assertEqual(media_library.choose(self.s,self.directory,gid)[0][0]['id'],name)
   self.directory.joinpath(name).write_bytes(b'\x89PNG\r\n\x1a\nchanged')
   self.assertEqual(media_library.choose(self.s,self.directory,gid)[0][0]['id'],name)
   ai.assert_not_called()
 def test_only_user_pool_controls_selection_not_old_analysis(self):
  name=self.image();gid=self.group()
  with self.s.db() as c:c.execute('UPDATE media_catalog SET analysis=?',(json.dumps(self.answer('PUBG',flag=True)),))
  self.assertEqual(media_library.choose(self.s,self.directory,gid)[0][0]['id'],name)
  media_library.assign(self.s,self.directory,[name],'PUBG')
  with self.assertRaises(ValueError):media_library.choose(self.s,self.directory,gid)
 def test_group_without_mapping_does_not_use_any_pool(self):
  gid=self.group();media_library.group_pools(self.s,gid,[])
  with self.assertRaisesRegex(ValueError,'chưa được gán'):media_library.choose(self.s,self.directory,gid)
 def test_assign_does_not_move_originals_and_rejects_traversal(self):
  name=self.image();media_library.assign(self.s,self.directory,[name],'CS2');self.assertTrue((self.directory/name).is_file())
  with self.assertRaises(ValueError):media_library.assign(self.s,self.directory,['../one.png'],'CS2')
 def wait_task(self,studio):
  limit=time.monotonic()+5
  while studio.lock.locked() and time.monotonic()<limit:time.sleep(.01)
  self.assertFalse(studio.lock.locked());return self.s.get('studio_task')
 def test_group_drafts_are_bound_to_single_group_and_never_scheduled(self):
  name=self.image();gid=self.group();other=self.group('two')
  self.s.group_category(gid,'Valorant')
  studio=Studio(self.s,lambda:{'model':'fake','mode':'publish'},self.directory)
  with patch('content_ai.writer_json',return_value={'title':'Test','body':'Bài game','body_no_link':'Bài game'}) as writer:
   studio.draft_groups({'ids':[gid],'brief':'Giao lưu game','media_count':1});task=self.wait_task(studio)
  self.assertEqual(task['status'],'done');self.assertEqual(len(self.s.rows('SELECT * FROM contents')),1)
  self.assertEqual(self.s.rows('SELECT group_id FROM content_targets'),[{'group_id':gid}]);self.assertEqual(self.s.rows('SELECT * FROM jobs'),[])
  self.assertNotIn('data:image',json.dumps(writer.call_args.args[1:],ensure_ascii=False));self.assertEqual(self.s.rows('SELECT target_mode FROM contents')[0]['target_mode'],'selected')
 def test_hallucinated_url_does_not_create_draft(self):
  name=self.image();gid=self.group()
  studio=Studio(self.s,lambda:{'model':'fake'},self.directory)
  with patch('content_ai.writer_json',return_value={'body':'https://invented.example/x','body_no_link':'Bài'}):
   studio.draft_groups({'ids':[gid],'brief':'Facts'});task=self.wait_task(studio)
  self.assertEqual(task['status'],'error');self.assertEqual(self.s.rows('SELECT * FROM contents'),[])
 def test_daily_group_cap_and_vietnam_date_rollover(self):
  ids=[]
  for i in range(2):
   gid=self.group('cap'+str(i));self.s.group_category(gid,'Chung');self.s.enable_group(gid,True);ids.append(gid)
  cid=self.s.content('Test');jobs=self.s.plan(cid,'30');self.s.approve(jobs);self.s.set('running',True);self.s.set('daily_group_limit',1)
  with self.s.db() as c:c.execute('UPDATE jobs SET due=?',(time.time()-10,))
  first=self.s.claim();self.assertIsNotNone(first);self.s.finish(first['id'],'error','No post')
  self.assertIsNone(self.s.claim())
  # Reflow keeps the delayed slot explicit instead of leaving it overdue.
  self.assertGreater(self.s.rows("SELECT due FROM jobs WHERE state='queued'")[0]['due'],time.time())
  with patch('store.time.time',return_value=time.time()+86400):self.assertIsNotNone(self.s.claim())

if __name__=='__main__':unittest.main()
