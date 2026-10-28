import tempfile,unittest
from pathlib import Path
from store import Store

class BulkDeleteTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.s=Store(self.root/'db')
  self.file=self.root/'photo.png';self.file.write_bytes(b'original')
  self.g=self.s.add_group('facebook.com/groups/bulk','Bulk',category='Valorant',link_policy='allow');self.s.enable_group(self.g,True)
  self.a=self.s.content('Keep frozen caption',str(self.file),category='Valorant')
  self.b=self.s.content('Other caption',category='Valorant')
  self.s.targets(self.a,'selected',[self.g]);self.jobs=self.s.plan(self.a,30)
 def tearDown(self):self.tmp.cleanup()
 def test_delete_selected_only_preserves_frozen_jobs_and_files(self):
  before=self.s.rows('SELECT * FROM jobs')
  self.assertEqual(self.s.delete_contents([self.a,self.a,999999]),1)
  self.assertEqual(self.s.rows('SELECT id FROM contents'),[{'id':self.b}])
  self.assertEqual(self.s.rows('SELECT * FROM content_targets'),[])
  self.assertEqual(self.s.rows('SELECT * FROM jobs'),before)
  self.assertEqual(self.file.read_bytes(),b'original')
 def test_invalid_selection_is_atomic(self):
  for ids in ([],None,'1,2',[self.a,'bad'],[True],[-1],list(range(1,502))):
   with self.assertRaises(ValueError):self.s.delete_contents(ids)
   self.assertEqual(len(self.s.rows('SELECT * FROM contents')),2)
 def test_deleting_everything_does_not_reuse_old_ids_or_attach_new_content_to_jobs(self):
  self.assertEqual(self.s.delete_contents([self.a,self.b]),2)
  new=self.s.content('New unrelated post',category='CS2')
  self.assertGreater(new,self.b)
  self.assertNotEqual(self.s.rows('SELECT content_id FROM jobs')[0]['content_id'],new)
  self.assertEqual(self.s.delete_contents([self.a,self.b]),0)

if __name__=='__main__':unittest.main()
