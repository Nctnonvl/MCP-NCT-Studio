import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from store import Store
import deployment,facebook_accounts

class DeploymentTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.old=self.root/'old data';self.old.mkdir();self.s=Store(self.old/'manager.sqlite3');deployment.prepare(self.s,self.old);facebook_accounts.bootstrap(self.s,self.old)
  g=self.s.add_group('facebook.com/groups/portable-test',link_policy='allow');self.s.enable_group(g,True)
  (self.old/'media').mkdir();self.file=self.old/'media'/'test.png';self.file.write_bytes(b'picture')
  self.caption='Keep this exact text including C:/old/data and https://discord.gg/test'
  cid=self.s.content(self.caption,str(self.file));self.s.targets(cid,'selected',[g]);self.jid=self.s.plan(cid,60)[0]
  with self.s.db() as c:c.execute("update jobs set state='queued' where id=?",(self.jid,))
  self.s.set('config',{'token':'secret-do-not-export','mode':'publish'});self.s.set('running',True)
  (self.old/'work').mkdir();(self.old/'work/receipt.png').write_bytes(b'history photo')
  with self.s.db() as c:c.execute('update jobs set photo=? where id=?',(str(self.old/'work/receipt.png'),self.jid))
 def tearDown(self):self.tmp.cleanup()
 def test_import_relocates_only_paths_and_requires_reapproval(self):
  new=self.root/'new machine';deployment.import_data(self.old,new);s=Store(new/'manager.sqlite3')
  job=s.rows('select * from jobs')[0]
  self.assertEqual(job['body'],self.caption);self.assertEqual(job['media'],str(new/'media/test.png'));self.assertEqual(job['state'],'draft')
  self.assertTrue((new/'media/test.png').exists());self.assertFalse((new/'chrome-profile').exists())
  self.assertEqual((new/'work/receipt.png').read_bytes(),b'history photo')
  self.assertFalse(s.get('running'));self.assertEqual(s.get('config')['token'],'')
  self.assertEqual(self.s.get('config')['token'],'secret-do-not-export')
  self.assertEqual(self.s.rows('select state from jobs')[0]['state'],'queued')
  profile=json.loads(job['browser_profile_json']);self.assertEqual(profile['user_data_dir'],str(new/'chrome-profile'))
 def test_existing_destination_is_never_overwritten(self):
  new=self.root/'existing';new.mkdir();(new/'keep').write_text('keep')
  with self.assertRaises(ValueError):deployment.import_data(self.old,new)
  self.assertEqual((new/'keep').read_text(),'keep')
 def test_relocate_json_media_without_touching_prose(self):
  original=json.dumps([r'D:\old\data\media\a.png',r'D:\old\data-other\keep.png'])
  result=json.loads(deployment.relocate(original,r'D:\old\data',self.root))
  self.assertEqual(result[0],str(self.root/'media/a.png'));self.assertEqual(result[1],r'D:\old\data-other\keep.png')
  self.assertEqual(deployment.relocate('prose D:/old/data/media/x',r'D:\old\data',self.root),'prose D:/old/data/media/x')
 def test_foreign_windows_key_is_cleared_and_schedule_paused(self):
  self.s.set('config',{'token':'dpapi:foreign'});self.s.set('running',True)
  with patch('content_ai.unprotect',side_effect=ValueError('different Windows')):deployment.prepare(self.s,self.old)
  self.assertEqual(self.s.get('config')['token'],'');self.assertFalse(self.s.get('running'))
 def test_fresh_machine_gets_separate_chrome_account(self):
  data=self.root/'fresh';s=Store(data/'manager.sqlite3');deployment.prepare(s,data);facebook_accounts.bootstrap(s,data)
  self.assertEqual(len(facebook_accounts.catalog(s)),1)
  self.assertEqual(json.loads((data/'browser-profile.json').read_text())['browser'],'chrome')
