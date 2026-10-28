import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
import desktop

class CloseWindowTests(unittest.TestCase):
 def run_close(self,previous=(),actual=(123,1.0),profile=True):
  user32=SimpleNamespace(IsWindow=Mock(side_effect=[True,False]),PostMessageW=Mock(return_value=1))
  process=SimpleNamespace(name=lambda:'msedge.exe',cmdline=lambda:['edge.exe'])
  with patch.object(desktop.ctypes,'windll',SimpleNamespace(user32=user32)),patch.object(desktop,'window_identity',return_value=actual),patch.object(desktop,'profile_matches',return_value=profile),patch.object(desktop,'browser_process',return_value='msedge.exe'),patch('psutil.Process',return_value=process):
   closed=desktop.close_operation_window(99,'data',previous,(123,1.0))
  return closed,user32
 def test_closes_only_new_verified_window_normally(self):
  closed,user32=self.run_close();self.assertTrue(closed)
  user32.PostMessageW.assert_called_once_with(99,0x0010,0,0)
 def test_preexisting_window_is_never_closed(self):
  closed,user32=self.run_close(previous=[99]);self.assertFalse(closed);user32.PostMessageW.assert_not_called()
 def test_changed_pid_identity_or_wrong_profile_is_never_closed(self):
  for kwargs in ({'actual':(999,2.0)},{'profile':False}):
   closed,user32=self.run_close(**kwargs);self.assertFalse(closed);user32.PostMessageW.assert_not_called()

if __name__=='__main__':unittest.main()
