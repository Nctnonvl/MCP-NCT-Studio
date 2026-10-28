import sys,unittest,types,ctypes
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import desktop
class NativeDialogTests(unittest.TestCase):
 def test_changed_window_stops_before_accessibility_read(self):
  with patch.object(desktop,'foreground',side_effect=RuntimeError('changed')):
   with self.assertRaisesRegex(RuntimeError,'changed'):desktop.native_file_targets(1)
 def test_only_filename_edit_from_native_dialog_is_returned(self):
  class Fn:
   def __init__(self,f):self.f=f
   def __call__(self,*a):return self.f(*a)
  user32=types.SimpleNamespace(GetForegroundWindow=Fn(lambda:222),GetClassNameW=Fn(lambda h,b,n:setattr(b,'value','#32770')))
  def node(role,name,children=()):
   return types.SimpleNamespace(ControlTypeName=role,Name=name,GetChildren=lambda:children,BoundingRectangle=types.SimpleNamespace(left=10,top=20,right=110,bottom=40))
  root=node('WindowControl','Open',[node('EditControl','Name'),node('ComboBoxControl','File name:'),node('EditControl','File name:')])
  fake=types.ModuleType('windows_mcp.uia');fake.ControlFromHandle=lambda h:root
  com=types.ModuleType('comtypes');com.CoInitialize=lambda:None;com.CoUninitialize=lambda:None
  with patch.object(desktop,'foreground'),patch.object(desktop.ctypes,'windll',types.SimpleNamespace(user32=user32)),patch.dict(sys.modules,{'windows_mcp.uia':fake,'comtypes':com}),patch('windows_mcp.uia',fake,create=True):
   targets=desktop.native_file_targets(1)
   self.assertEqual(len(targets),1);self.assertEqual(targets[0]['name'],'file name:');self.assertEqual(targets[0]['loc'],[60,30])
if __name__=='__main__':unittest.main()
