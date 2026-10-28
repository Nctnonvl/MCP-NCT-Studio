import unittest,tempfile
from pathlib import Path
from runtime_guard import code_revision
class RevisionTests(unittest.TestCase):
 def test_python_change_invalidates_revision_but_html_does_not(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);p=root/'app.py';p.write_text('a=1')
   first=code_revision(root);self.assertEqual(first,code_revision(root))
   (root/'ui.html').write_text('new UI');self.assertEqual(first,code_revision(root))
   p.write_text('a=2');self.assertNotEqual(first,code_revision(root))
 def test_new_worker_module_also_invalidates_revision(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);(root/'app.py').write_text('a=1');first=code_revision(root)
   (root/'worker.py').write_text('b=1');self.assertNotEqual(first,code_revision(root))

 def test_old_controller_cannot_enable_queue_after_source_update(self):
  import app
  from unittest.mock import patch
  from types import SimpleNamespace
  values={'running':True,'paused_by_user':False}
  store=SimpleNamespace(get=lambda key,default=None:values.get(key,default),set=lambda key,value:values.__setitem__(key,value))
  with patch.object(app,'STORE',store),patch.object(app,'code_revision',return_value='different-code'):
   with self.assertRaisesRegex(ValueError,'khởi động lại'):app.run_queue()
  self.assertFalse(values['running']);self.assertTrue(values['paused_by_user'])
