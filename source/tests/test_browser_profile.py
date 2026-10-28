import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import desktop

class BrowserProfileTests(unittest.TestCase):
 def test_standard_edge_without_switch_requires_explicit_shared_profile(self):
  with tempfile.TemporaryDirectory() as d,patch.dict(desktop.os.environ,{'LOCALAPPDATA':d}):
   root=(Path(d)/'Microsoft/Edge/User Data').resolve()
   with patch.object(desktop,'browser_profile',return_value=(root,'Profile 1')):
    self.assertTrue(desktop.profile_matches(['msedge.exe'],'unused'))
    self.assertFalse(desktop.profile_matches(['--user-data-dir=wrong'],'unused'))
   with patch.object(desktop,'browser_profile',return_value=(root,None)):
    self.assertFalse(desktop.profile_matches(['msedge.exe'],'unused'))
 def test_default_remains_private(self):
  with tempfile.TemporaryDirectory() as d:
   self.assertEqual(desktop.browser_profile(d),((Path(d)/'edge-profile').resolve(),None))
 def test_explicit_profile_launch_and_process_match(self):
  with tempfile.TemporaryDirectory() as d:
   data=Path(d);root=data/'shared';(root/'Profile 1').mkdir(parents=True)
   (root/'Profile 1'/'Preferences').write_text('{}')
   (data/'browser-profile.json').write_text(json.dumps({'user_data_dir':str(root),'profile_directory':'Profile 1'}))
   with patch.object(desktop,'edge_path',return_value='edge.exe'),patch.object(desktop.subprocess,'Popen') as launch:
    desktop.launch_browser(data,'https://www.facebook.com/groups/test/')
    args=launch.call_args.args[0]
    self.assertIn('--profile-directory=Profile 1',args)
    self.assertTrue(desktop.profile_matches(args,data))
    self.assertFalse(desktop.profile_matches(['--user-data-dir='+str(data/'edge-profile')],data))
 def test_invalid_or_missing_profile_never_falls_back(self):
  with tempfile.TemporaryDirectory() as d:
   data=Path(d)
   for directory in ('../Default','Missing','Profile 9'):
    (data/'browser-profile.json').write_text(json.dumps({'user_data_dir':d,'profile_directory':directory}))
    with self.assertRaises(ValueError):desktop.browser_profile(data)

 def test_chrome_shared_profile_uses_chrome_and_never_matches_edge(self):
  with tempfile.TemporaryDirectory() as d,patch.dict(desktop.os.environ,{'LOCALAPPDATA':d}):
   data=Path(d)/'data';data.mkdir();root=Path(d)/'Google/Chrome/User Data'
   (root/'Default').mkdir(parents=True);(root/'Default/Preferences').write_text('{}')
   (data/'browser-profile.json').write_text(json.dumps({'browser':'chrome','user_data_dir':str(root),'profile_directory':'Default','display_name':'Test profile'}))
   self.assertEqual(desktop.browser_process(data),'chrome.exe')
   self.assertTrue(desktop.profile_matches(['chrome.exe'],data))
   self.assertFalse(desktop.profile_matches(['msedge.exe'],data))
   self.assertFalse(desktop.profile_matches(['chrome.exe','--user-data-dir=wrong'],data))
   with patch.object(desktop,'browser_executable',return_value='chrome.exe'),patch.object(desktop.subprocess,'Popen') as launch:
    desktop.launch_browser(data,'https://www.facebook.com/groups/test/')
   args=launch.call_args.args[0]
   self.assertEqual(args[0],'chrome.exe');self.assertIn('--profile-directory=Default',args)
   self.assertEqual(desktop.browser_status(data),{'name':'Google Chrome','profile':'Test profile'})

 def test_unknown_browser_is_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   (Path(d)/'browser-profile.json').write_text(json.dumps({'browser':'unknown'}))
   with self.assertRaises(ValueError):desktop.browser_kind(d)

 def test_private_chrome_profile_can_be_initialized_without_copying_login(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d)/'chrome-profile'
   (Path(d)/'browser-profile.json').write_text(json.dumps({'browser':'chrome','user_data_dir':str(root),'profile_directory':None}))
   self.assertEqual(desktop.browser_profile(d),(root.resolve(),None))
   self.assertTrue(desktop.profile_matches(['chrome.exe','--user-data-dir='+str(root)],d))
   self.assertFalse(desktop.profile_matches(['chrome.exe'],d))
   self.assertFalse(root.exists())

if __name__=='__main__':unittest.main()
