import json,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
import desktop,facebook_accounts as accounts,approval_followup
from store import Store

class AccountTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.data=Path(self.tmp.name);self.s=Store(self.data/'manager.sqlite3')
  self.raw=json.dumps({'browser':'chrome','user_data_dir':str(self.data/'chrome-profile'),'profile_directory':None,'facebook_account':'Original'})
  (self.data/'browser-profile.json').write_text(self.raw,encoding='utf-8');accounts.bootstrap(self.s,self.data)
  self.g=self.s.add_group('facebook.com/groups/account-test',link_policy='allow');self.s.enable_group(self.g,True)
 def tearDown(self):self.tmp.cleanup()
 def plan(self,text):
  cid=self.s.content(text);self.s.targets(cid,'selected',[self.g]);return self.s.plan(cid,60)[0]
 def job(self,jid):return self.s.rows('select * from jobs where id=?',(jid,))[0]
 def test_new_assignment_does_not_change_old_post_author(self):
  old=self.plan('First full caption')
  with self.s.db() as c:c.execute("update jobs set state='pending',post_attempted=1 where id=?",(old,))
  aid=accounts.create(self.s,self.data,'Second','Second Actor');accounts.assign(self.s,self.g,aid)
  new=self.plan('Completely different second caption')
  self.assertEqual(self.job(old)['browser_profile_json'],self.raw)
  self.assertEqual(self.job(old)['account_id'],'main');self.assertEqual(self.job(new)['account_id'],aid)
  token=desktop._BROWSER_PROFILE.set(json.loads(self.job(new)['browser_profile_json']))
  try:
   root,_=desktop.browser_profile(self.data)
   self.assertEqual(root,(self.data/'facebook-profiles'/aid).resolve())
   self.assertTrue(desktop.profile_matches(['chrome.exe','--user-data-dir='+str(root)],self.data))
   self.assertFalse(desktop.profile_matches(['chrome.exe','--user-data-dir='+str(self.data/'chrome-profile')],self.data))
  finally:desktop._BROWSER_PROFILE.reset(token)
  self.assertEqual(desktop.browser_profile(self.data)[0],(self.data/'chrome-profile').resolve())
 def test_bootstrap_keeps_legacy_approval_hash(self):
  jid=self.plan('An existing pending post');old_revision=approval_followup.profile_revision(self.data)
  self.assertEqual(old_revision,approval_followup.profile_revision(self.data,self.job(jid)))
  accounts.bootstrap(self.s,self.data)
  self.assertEqual(len(accounts.catalog(self.s)),1)
 def test_invalid_account_cannot_be_assigned(self):
  with self.assertRaises(ValueError):accounts.assign(self.s,self.g,'missing')
 def test_private_content_cannot_be_scheduled_to_another_account(self):
  aid=accounts.create(self.s,self.data,'Second');cid=self.s.content('Only the second account can post this caption')
  self.s.content_account(cid,aid)
  with self.s.db() as c:
   post=c.execute('select * from contents where id=?',(cid,)).fetchone();group=c.execute('select * from groups where id=?',(self.g,)).fetchone()
   self.assertFalse(self.s._eligible(c,post,group))
  accounts.assign(self.s,self.g,aid)
  jid=self.s.plan(cid,60)[0]
  self.assertEqual(self.job(jid)['account_id'],aid)
 def test_shared_content_uses_account_of_selected_group(self):
  aid=accounts.create(self.s,self.data,'Second');accounts.assign(self.s,self.g,aid)
  jid=self.plan('Shared caption for groups of either account')
  self.assertEqual(self.job(jid)['account_id'],aid)
 def test_approval_check_uses_frozen_account_even_when_default_changes(self):
  aid=accounts.create(self.s,self.data,'Second');accounts.assign(self.s,self.g,aid);jid=self.plan('An exact pending caption')
  with self.s.db() as c:c.execute("update jobs set state='pending',post_attempted=1 where id=?",(jid,))
  approval_followup.enqueue(self.s,jid,{'state':'pending'},self.data)
  (self.data/'browser-profile.json').write_text('{}')
  with self.s.db() as c:c.execute('update approval_checks set due=0')
  self.s.set('approval_monitor_enabled',True)
  job=approval_followup.claim(self.s,self.data)
  self.assertEqual(job['account_id'],aid)
  self.assertEqual(json.loads(job['browser_profile_json'])['display_name'],'Second')
