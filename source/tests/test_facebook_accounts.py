import json,tempfile,time,unittest,os,asyncio
from types import SimpleNamespace
from unittest.mock import Mock
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
 def test_assignment_updates_only_never_attempted_jobs(self):
  safe=self.plan('A shared caption for the new account')
  attempted=self.plan('Another attempted caption')
  with self.s.db() as c:c.execute("update jobs set state='queued',attempted_at=1,post_attempted=1 where id=?",(attempted,))
  aid=accounts.create(self.s,self.data,'Second')
  result=accounts.assign(self.s,self.g,aid)
  self.assertEqual(result['changed'],1)
  self.assertEqual(self.job(safe)['account_id'],aid)
  self.assertEqual(self.job(attempted)['account_id'],'main')
 def test_assignment_blocks_private_content_of_old_account(self):
  cid=self.s.content('Only my original account owns this caption');self.s.content_account(cid,'main')
  self.s.targets(cid,'selected',[self.g]);jid=self.s.plan(cid,60)[0]
  aid=accounts.create(self.s,self.data,'Second');result=accounts.assign(self.s,self.g,aid)
  self.assertEqual(result['blocked'],1);self.assertEqual(self.job(jid)['state'],'draft')
  self.s.approve([jid]);self.assertEqual(self.job(jid)['state'],'draft')
 def test_bootstrap_keeps_legacy_approval_hash(self):
  jid=self.plan('An existing pending post');old_revision=approval_followup.profile_revision(self.data)
  self.assertEqual(old_revision,approval_followup.profile_revision(self.data,self.job(jid)))
  accounts.bootstrap(self.s,self.data)
  self.assertEqual(len(accounts.catalog(self.s)),1)
 def test_invalid_account_cannot_be_assigned(self):
  with self.assertRaises(ValueError):accounts.assign(self.s,self.g,'missing')
 def test_existing_chrome_profile_is_selected_and_frozen_without_cookie_copy(self):
  root=self.data/'Google/Chrome/User Data';profile=root/'Profile 2';profile.mkdir(parents=True)
  (profile/'Preferences').write_text('{}');(root/'Local State').write_text(json.dumps({'profile':{'info_cache':{'Profile 2':{'name':'Test Chrome','user_name':'private@example.invalid'}}}}))
  with patch.dict(os.environ,{'LOCALAPPDATA':str(self.data)}):
   self.assertEqual(accounts.chrome_profiles(),[{'id':'Profile 2','name':'Test Chrome','usable':True}])
   selected=accounts.chrome_profile_config('Profile 2')
   self.assertEqual(selected['profile_directory'],'Profile 2')
   self.assertEqual(selected['display_name'],'Test Chrome')
   self.assertEqual(self.s.rows('SELECT count(*) AS n FROM facebook_accounts')[0]['n'],1)
   aid=accounts.use_chrome_profile(self.s,'Profile 2','Facebook test');accounts.assign(self.s,self.g,aid)
   jid=self.plan('Test frozen profile');saved=json.loads(self.job(jid)['browser_profile_json'])
   self.assertEqual(saved['profile_directory'],'Profile 2');self.assertEqual(saved['shared_profile_name'],'Test Chrome')
   token=desktop._BROWSER_PROFILE.set(saved)
   try:self.assertEqual(desktop.browser_profile(self.data),(root.resolve(),'Profile 2'))
   finally:desktop._BROWSER_PROFILE.reset(token)
   with self.assertRaises(ValueError):accounts.use_chrome_profile(self.s,'Profile 2','Duplicate')
   self.assertFalse((self.data/'facebook-profiles'/aid).exists())
   # A copied database on another machine cannot reuse a machine-specific Chrome profile.
   import deployment
   copied=self.data/'imported'
   deployment.import_data(self.data,copied)
   moved=Store(copied/'manager.sqlite3').rows('select profile from facebook_accounts where id=?',(aid,))[0]
   self.assertNotIn('shared_profile_name',json.loads(moved['profile']))
 def test_invalid_or_ambiguous_profile_is_rejected(self):
  root=self.data/'Google/Chrome/User Data';root.mkdir(parents=True)
  for name in ('Default','Profile 1'):
   (root/name).mkdir();(root/name/'Preferences').write_text('{}')
  (root/'Local State').write_text(json.dumps({'profile':{'info_cache':{'Default':{'name':'Same'},'Profile 1':{'name':'Same'}}}}))
  with patch.dict(os.environ,{'LOCALAPPDATA':str(self.data)}):
   self.assertTrue(all(not p['usable'] for p in accounts.chrome_profiles()))
   for invalid in ('Default','../Default','Profile 9'):
    with self.assertRaises(ValueError):accounts.use_chrome_profile(self.s,invalid,'Test')
 def test_profile_check_rejects_page_content_and_wrong_toolbar_badge(self):
  class Node:
   def __init__(self,role,name='',children=()):self.ControlTypeName=role;self.Name=name;self.children=children
   def GetChildren(self):return self.children
  import windows_mcp.uia as uia
  token=desktop._BROWSER_PROFILE.set({'shared_profile_name':'Test Chrome'})
  try:
   doc=Node('DocumentControl',children=[Node('ButtonControl','Test Chrome')])
   with patch.object(uia,'ControlFromHandle',return_value=Node('WindowControl',children=[doc,Node('ButtonControl','Other')])):
    with self.assertRaises(RuntimeError):desktop.verify_shared_profile(1,self.data)
   with patch.object(uia,'ControlFromHandle',return_value=Node('WindowControl',children=[doc,Node('ButtonControl','Test Chrome')])):
    desktop.verify_shared_profile(1,self.data)
   with patch.object(uia,'ControlFromHandle',return_value=Node('WindowControl',children=[Node('ButtonControl','Test Chrome'),Node('ButtonControl','Test Chrome')])):
    with self.assertRaises(RuntimeError):desktop.verify_shared_profile(1,self.data)
  finally:desktop._BROWSER_PROFILE.reset(token)
 def test_failed_profile_check_closes_new_window_without_clicking(self):
  user32=SimpleNamespace(ShowWindow=Mock(),SetForegroundWindow=Mock())
  with patch.object(desktop.ctypes,'windll',SimpleNamespace(user32=user32)),patch.object(desktop,'profile_windows',return_value=[11,22]),patch.object(desktop,'browser_profile',return_value=(self.data,'Profile 1')),patch.object(desktop,'foreground'),patch.object(desktop,'verify_shared_profile',side_effect=RuntimeError('bad profile')),patch.object(desktop,'window_identity',return_value=(123,456)),patch.object(desktop,'close_operation_window') as close:
   with self.assertRaisesRegex(RuntimeError,'bad profile'):asyncio.run(desktop.focus_profile(self.data,[11],lambda text:None))
   close.assert_called_once_with(22,self.data,[11],(123,456))
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
