import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from desktop import ui_choice_schema,validate_ui_choice,parse_targets
class UIChoiceTests(unittest.TestCase):
    def setUp(self):self.targets=parse_targets('UI Tree:\nwindow "Facebook"\n├── (30,40) button "Bạn viết gì đi..." [action: click]\n└── (50,60) edit "Tạo bài viết" [action: fill]')
    def test_real_tree_coordinates_are_numbered_locally(self):
        self.assertEqual([t['id'] for t in self.targets],[0,1]);self.assertEqual(self.targets[0]['loc'],[30,40])
        schema=ui_choice_schema(self.targets);self.assertEqual(schema['properties']['target'],{'type':'integer','enum':[0,1]})
    def test_numeric_string_is_only_accepted_for_an_existing_id(self):
        self.assertEqual(validate_ui_choice({'action':'click','target':'1'},self.targets)['target'],1)
        for value in (True,-1,2,'99',[30,40],{'id':1},None):
            with self.subTest(value=value),self.assertRaises(ValueError):validate_ui_choice({'action':'click','target':value},self.targets)
    def test_non_target_actions_and_unknown_actions(self):
        self.assertEqual(validate_ui_choice({'action':'wait'},self.targets)['action'],'wait')
        with self.assertRaises(ValueError):validate_ui_choice({'action':'run_shell','target':0},self.targets)
if __name__=='__main__':unittest.main()
