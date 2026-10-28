import json,sys,unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import desktop

class SnapshotEnvelopeTests(unittest.TestCase):
    # Shape observed over real 0.8.8 stdio on Edge, in both DOM modes.
    tree=('UI Tree:\ndesktop\n├── window "Group - Edge"\n'
          '│   ├── (278,146) link "Facebook"  [action: click]\n'
          '│   └── (720,844) button "Bạn viết gì đi..."  [action: click]\n'
          '└── window "Other Edge"\n'
          '    └── (100,200) button "Write something wrong window" [action: click]')
    def test_json_text_list_decodes_before_window_and_target_parsing(self):
        raw=json.dumps([self.tree],ensure_ascii=False)
        response=SimpleNamespace(content=[SimpleNamespace(type='text',text=raw)])
        self.assertEqual(desktop.mcp_text(response),self.tree)
        for value in (raw,desktop.mcp_text(response),desktop.active_window_tree(raw)):
            targets=desktop.parse_targets(value)
            self.assertEqual(len(targets),2)
            self.assertEqual(targets[1]['loc'],[720,844])
            self.assertEqual(targets[1]['name'],'bạn viết gì đi...')
            self.assertFalse(desktop.composer_click_allowed(targets[0]))
            self.assertTrue(desktop.composer_click_allowed(targets[1]))
        self.assertNotIn('Other Edge',desktop.active_window_tree(raw))
    def test_plain_text_and_status_json_remain_unchanged(self):
        for value in (self.tree,'{"state":"ready"}','[1,2]','["unterminated'):
            self.assertEqual(desktop.unwrap_mcp_text(value),value)
    def test_multiple_text_parts_and_literal_backslash_preserved(self):
        text='UI Tree:\nwindow "Group"\n(10,20) edit "literal \\n and quote \\"" [action: type]'
        self.assertEqual(desktop.unwrap_mcp_text(json.dumps([text,'tail'])),text+'\ntail')

if __name__=='__main__':unittest.main()
