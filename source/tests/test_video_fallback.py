"""Synthetic upload and MCP decision tests; never post to Facebook."""
import io,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import media,video_fallback as vf,media_library
from store import Store

class VideoFallbackTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.d=self.root/'media';self.d.mkdir();self.s=Store(self.root/'db.sqlite3')
  self.image=self.d/'image.png';self.image.write_bytes(b'\x89PNG\r\n\x1a\n'+b'fake')
  self.video=self.d/'clip.mp4';self.video.write_bytes(b'\x00\x00\x00\x18ftypmp42'+b'fake')
  self.targets=[{'id':0,'role':'edit','name':'create a public post','loc':[1,1]},{'id':1,'role':'button','name':'remove video','loc':[2,2]}]
  self.caption='Caption approved';self.snapshot=self.caption+' Could not upload your video'
 def tearDown(self):self.tmp.cleanup()
 def test_upper_bound_rejected_before_any_read_and_images_remain_100mb(self):
  for name,size in [('clip.mp4',500*1024*1024+1),('photo.png',100*1024*1024+1)]:
   class NoRead:
    def read(self,size):raise AssertionError('oversize must be rejected before reading')
   with self.assertRaises(ValueError):media.receive(NoRead(),size,name,self.d)
  self.assertEqual(media.MAX_UPLOAD,500*1024*1024)
 def test_500mb_stream_is_accepted_using_bounded_chunks(self):
  class Stream:
   def __init__(self):self.first=True;self.largest=0
   def read(self,size):
    self.largest=max(self.largest,size);out=b'\x00'*size
    if self.first:out=b'\x00\x00\x00\x18ftypmp42'+out[12:];self.first=False
    return out
  stream=Stream();item=media.receive(stream,500*1024*1024,'large.mp4',self.d)
  self.assertEqual(item['bytes'],500*1024*1024);self.assertEqual((self.d/item['id']).stat().st_size,500*1024*1024);self.assertLessEqual(stream.largest,1024*1024)
 def test_only_explicit_pre_submit_video_rejection_allows_removal(self):
  args=dict(submitted=False,attached=True,has_video=True,used=False)
  self.assertEqual(vf.removal_target(self.snapshot,self.targets,self.caption,**args)['id'],1)
  for k,v in [('submitted',True),('attached',False),('has_video',False),('used',True)]:
   self.assertIsNone(vf.removal_target(self.snapshot,self.targets,self.caption,**{**args,k:v}))
  self.assertIsNone(vf.removal_target(self.caption+' still uploading',self.targets,self.caption,**args))
  self.assertIsNone(vf.removal_target(self.snapshot,self.targets+[self.targets[1]],self.caption,**args))
  self.assertIsNone(vf.removal_target(self.snapshot,self.targets[1:],self.caption,**args))
 def test_caption_is_not_treated_as_a_facebook_rejection(self):
  self.assertEqual(vf.rejection(self.snapshot,self.snapshot),'')
 def test_removal_requires_clean_editor_caption_and_no_remove_button(self):
  self.assertTrue(vf.removal_confirmed(self.caption,self.targets[:1],self.caption))
  self.assertFalse(vf.removal_confirmed(self.snapshot,self.targets[:1],self.caption))
  self.assertFalse(vf.removal_confirmed(self.caption,self.targets,self.caption))
  self.assertFalse(vf.removal_confirmed('Other caption',self.targets[:1],self.caption))
 def test_fallback_paths_are_images_inside_media_only(self):
  self.assertEqual(vf.photo_paths(str(self.image),self.d),[str(self.image.resolve())])
  for value in ['',str(self.video),str(self.root/'outside.png')]:
   with self.assertRaises(ValueError):vf.photo_paths(value,self.d)
 def test_new_jobs_freeze_same_group_photos_and_saved_job_is_unchanged(self):
  media_library.initialize(self.s,self.d)
  gid=self.s.add_group('facebook.com/groups/video','Video',link_policy='allow',category='Valorant');self.s.enable_group(gid,True)
  media_library.group_pools(self.s,gid,['Valorant'])
  self.s.set('content_ai',{'vision_model':'mock-vision'})
  media_library.assign(self.s,self.d,['image.png'],'Valorant')
  a={'game':'Valorant','confidence':.99,'summary':'game','contains_url_or_qr':False}
  with self.s.db() as c:c.execute('UPDATE media_catalog SET scan_hash=?,scan_model=?,analysis=? WHERE id=?',(media_library.fingerprint(self.image),'mock-vision',json.dumps(a),'image.png'))
  cid=self.s.content('Caption',str(self.video),category='Valorant');ids=self.s.plan(cid,30)
  before=self.s.rows('SELECT video_fallback_media FROM jobs WHERE id=?',(ids[0],))[0]['video_fallback_media'];self.assertEqual(before,str(self.image.resolve()))
  media_library.archive(self.s,['image.png'])
  self.assertEqual(self.s.rows('SELECT video_fallback_media FROM jobs WHERE id=?',(ids[0],))[0]['video_fallback_media'],before)
  self.assertEqual(self.s.rows('SELECT media FROM jobs WHERE id=?',(ids[0],))[0]['media'],str(self.video))
 def test_video_without_scanned_group_photo_has_no_fallback(self):
  gid=self.s.add_group('facebook.com/groups/no-photo','No photo',link_policy='allow');self.s.enable_group(gid,True)
  cid=self.s.content('Caption',str(self.video));ids=self.s.plan(cid,30)
  self.assertEqual(self.s.rows('SELECT video_fallback_media FROM jobs WHERE id=?',(ids[0],))[0]['video_fallback_media'],'')

if __name__=='__main__':unittest.main()
