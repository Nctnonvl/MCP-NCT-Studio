"""Regression: never let a composer decision click the Facebook navigation logo."""
import sys
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import desktop

class LiveTargetTests(unittest.TestCase):
    target={'text':'button "Write something..." [action: click]','loc':[278,146]}
    def run_hit(self,node):
        com=ModuleType('comtypes');com.CoInitialize=Mock();com.CoUninitialize=Mock()
        package=ModuleType('windows_mcp');package.__path__=[]
        uia=ModuleType('windows_mcp.uia');uia.ControlFromPoint=Mock(return_value=node)
        package.uia=uia
        with patch.dict(sys.modules,{'comtypes':com,'windows_mcp':package,'windows_mcp.uia':uia}):
            try:return desktop.verify_live_target(self.target)
            finally:com.CoUninitialize.assert_called_once()
    def test_logo_under_expected_composer_point_is_blocked(self):
        with self.assertRaisesRegex(RuntimeError,'thực tế: link facebook'):
            self.run_hit(SimpleNamespace(ControlTypeName='HyperlinkControl',Name='Facebook'))
    def test_mcp_link_and_uia_hyperlink_are_equivalent(self):
        target={'text':'link "Vừa xong"','role':'link','name':'vừa xong','loc':[10,20]}
        with patch.object(self,'target',target):self.run_hit(SimpleNamespace(ControlTypeName='HyperlinkControl',Name='Vừa xong'))
    def test_invisible_timestamp_and_matching_group_child_resolve_to_same_link(self):
        target={'text':'link "V\u034fừa xong"','role':'link','name':'vừa xong','loc':[10,20]}
        parent=SimpleNamespace(ControlTypeName='HyperlinkControl',Name='Vừa xong')
        child=SimpleNamespace(ControlTypeName='GroupControl',Name='Vừa xong',GetParentControl=lambda:parent)
        with patch.object(self,'target',target):self.run_hit(child)
    def test_same_named_group_cannot_resolve_to_facebook_logo(self):
        target={'text':'link "Vừa xong"','role':'link','name':'vừa xong','loc':[10,20]}
        logo=SimpleNamespace(ControlTypeName='HyperlinkControl',Name='Facebook')
        child=SimpleNamespace(ControlTypeName='GroupControl',Name='Vừa xong',GetParentControl=lambda:logo)
        with patch.object(self,'target',target),self.assertRaises(RuntimeError):self.run_hit(child)
    def test_matching_live_button_is_allowed(self):
        self.run_hit(SimpleNamespace(ControlTypeName='ButtonControl',Name='Write something...'))
    def test_text_child_can_resolve_to_expected_button(self):
        parent=SimpleNamespace(ControlTypeName='ButtonControl',Name='Write something...')
        self.run_hit(SimpleNamespace(ControlTypeName='TextControl',Name='Write something...',GetParentControl=lambda:parent))
    def test_composer_words_inside_navigation_or_metadata_do_not_authorize_click(self):
        for value in ['hyperlink "Write something..." [action: click]',
                      'button "Facebook Write something..." [action: click]',
                      'button "Facebook" [action: click] [value:"Create post"]',
                      'document "Create post entire page" [action: click]']:
            self.assertFalse(desktop.composer_click_allowed({'text':value}),value)
        self.assertTrue(desktop.composer_click_allowed(self.target))

class TreeNameTests(unittest.TestCase):
    def test_multiline_name_is_one_target_with_separate_role_and_name(self):
        snapshot='UI Tree:\nwindow "Group"\n├── (100,200) button "Bạn viết gì đi...\nTạo bài viết"  [action: click]\n└── (200,300) button "Đăng"  [action: click]'
        targets=desktop.parse_targets(snapshot)
        self.assertEqual(len(targets),2)
        self.assertEqual(desktop.target_identity(targets[0]),('button','bạn viết gì đi... tạo bài viết'))
        self.assertTrue(desktop.composer_click_allowed(targets[0]))
        self.assertTrue(desktop.is_post_button(targets[1]))

    def test_coordinates_inside_page_text_do_not_become_targets(self):
        snapshot='UI Tree:\nwindow "Group"\ntext "Example (278,146) button Write something"\n(100,200) button "Bạn viết gì đi..." [action: click]'
        targets=desktop.parse_targets(snapshot)
        self.assertEqual([t['loc'] for t in targets],[[100,200]])

    def test_quoted_name_and_metadata_are_kept_separate(self):
        targets=desktop.parse_targets('UI Tree:\n(100,200) button "Facebook" [action: click] [value:"Create post"]')
        self.assertEqual(desktop.target_identity(targets[0]),('button','facebook'))
        self.assertFalse(desktop.composer_click_allowed(targets[0]))

    def test_malformed_input_error_has_diagnostic_text(self):
        with self.assertRaisesRegex(RuntimeError,'Dữ liệu:'):
            desktop.target_identity({'text':'unexpected MCP shape'})

if __name__=='__main__':unittest.main()
