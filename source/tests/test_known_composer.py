import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import desktop
class KnownComposerTests(unittest.TestCase):
 def targets(self,tree):return desktop.parse_targets('UI Tree:\n'+tree)
 def test_never_selects_logo_or_comment_editor(self):
  targets=self.targets('(10,10) link "Facebook" [action: click]\n(20,20) edit "Viết bình luận" [action: fill]')
  self.assertIsNone(desktop.known_composer_action(targets,False,False,True,False))
 def test_unambiguous_composer_and_media_path(self):
  targets=self.targets('(10,10) button "Bạn viết gì đi..." [action: click]')
  self.assertEqual(desktop.known_composer_action(targets,False,False,True,False)['action'],'click')
  targets=self.targets('(10,10) edit "Tạo bài viết công khai..." [action: fill]\n(20,20) button "Ảnh/video" [action: click]')
  self.assertEqual(desktop.known_composer_action(targets,False,False,True,False)['action'],'type_caption')
  self.assertEqual(desktop.known_composer_action(targets,True,False,True,False)['action'],'click')
 def test_ambiguous_composer_is_not_chosen(self):
  targets=self.targets('(10,10) button "Bạn viết gì đi..." [action: click]\n(20,20) button "Tạo bài viết" [action: click]')
  self.assertIsNone(desktop.known_composer_action(targets,False,False,True,False))
if __name__=='__main__':unittest.main()
