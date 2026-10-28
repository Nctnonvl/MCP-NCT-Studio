"""Cleanup ownership and all scanner outcomes; no live browser interaction."""
import json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,Mock
import browser_cleanup
from group_scan import GroupScanner
from store import Store

class CleanupTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.data=Path(self.tmp.name);self.path=self.data/'work/browser.json'
 def tearDown(self):self.tmp.cleanup()
 def test_supervisor_cleans_killed_workers_window_once(self):
  browser_cleanup.register(self.path,99,[11],(123,1.0))
  with patch('desktop.close_operation_window',return_value=True) as close:
   self.assertTrue(browser_cleanup.recover(self.path,self.data,os.getpid()))
   self.assertTrue(browser_cleanup.recover(self.path,self.data,os.getpid()))
  close.assert_called_once_with(99,self.data,[11],(123,1.0))
 def test_different_worker_never_closes_stale_window(self):
  browser_cleanup.register(self.path,99,[11],(123,1.0))
  with patch('desktop.close_operation_window') as close:
   self.assertFalse(browser_cleanup.recover(self.path,self.data,os.getpid()+1))
  close.assert_not_called()
 def test_unsuccessful_close_is_not_marked_consumed(self):
  browser_cleanup.register(self.path,99,[99],(123,1.0))
  with patch('desktop.close_operation_window',return_value=False):
   self.assertFalse(browser_cleanup.recover(self.path,self.data,os.getpid()))
  self.assertFalse(json.loads(self.path.read_text())['closed'])
 def test_stop_worker_preserves_edge_process(self):
  process=Mock(pid=123);process.poll.return_value=None
  server=Mock();server.name.return_value='python.exe';server.cmdline.return_value=['python.exe','-m','windows_mcp','serve']
  edge=Mock();edge.name.return_value='msedge.exe';edge.cmdline.return_value=['msedge.exe']
  with patch('psutil.Process') as lookup:
   lookup.return_value.children.return_value=[server,edge]
   browser_cleanup.stop_worker(process)
  process.terminate.assert_called_once();server.terminate.assert_called_once();edge.terminate.assert_not_called()
 def test_leave_confirmation_only_in_native_browser_dialog(self):
  class Node:
   IsEnabled=True
   def __init__(self,role,name,children=()):self.ControlTypeName=role;self.Name=name;self.children=children
   def GetChildren(self):return self.children
  leave=Node('ButtonControl','Leave')
  dialog=Node('WindowControl','Leave site?',[leave])
  self.assertIs(browser_cleanup.leave_button(Node('WindowControl','Edge',[dialog])),leave)
  self.assertIsNone(browser_cleanup.leave_button(Node('WindowControl','Edge',[Node('DocumentControl','Web page',[dialog])])))
 def test_scan_closes_after_done_stopped_and_error(self):
  store=Store(self.data/'state.db')
  for outcome in ('done','stopped','error'):
   scanner=GroupScanner(store,self.data);scanner.window=99;scanner.previous=[11];scanner.identity=(123,1.0)
   async def scan():
    if outcome=='error':raise RuntimeError('fake scan error')
    return [],outcome=='done'
   scanner.scan=scan
   with patch('browser_cleanup.finish',return_value=True) as close:scanner.run()
   close.assert_called_once_with(99,self.data,[11],(123,1.0),self.data/'work/group-scan-browser.json')
   self.assertEqual(store.get('group_scan')['status'],outcome)
   self.assertTrue(store.get('group_scan')['browser_closed'])

if __name__=='__main__':unittest.main()
