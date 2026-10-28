"""Reject AI link placeholders; preserve the user supplied footer."""
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import writing_policy,post_footer

class PlaceholderTests(unittest.TestCase):
 def test_all_generated_fields_reject_placeholders(self):
  for value in ['Ghé ngay: [link Discord]','[link]','<link Discord>','{URL}','URL_HERE']:
   for index in range(3):
    fields=['Tiêu đề','Mời anh em trao đổi.','Ghé bên mình nhé.'];fields[index]=value
    self.assertTrue(writing_policy.issue(*fields),value)
 def test_real_footer_is_preserved_once(self):
  footer='https ://discord.gg/DzdDGgry (bỏ dấu cách trước dấu hai chấm hoặc xuống cmt nhá anh em )'
  self.assertFalse(writing_policy.issue('Dịch vụ Valorant','Ghé bên mình nhé.','Mời trao đổi.',footer))
  body,alt,saved=post_footer.append('Ghé bên mình nhé.','Mời trao đổi.',{'enabled':True,'text':footer})
  self.assertTrue(body.endswith(footer));self.assertEqual(body.count(footer),1)
  self.assertEqual(saved,footer);self.assertNotIn('discord.gg',alt)

if __name__=='__main__':unittest.main()
