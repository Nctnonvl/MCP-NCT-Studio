import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from content_links import supplied_urls,validate_provided_urls
from store import has_link
class LinkTests(unittest.TestCase):
 def test_user_discord_with_space_is_same_provided_link(self):
  brief='https: //discord.gg/qwwrrMcP (bỏ dấu cách sau dấu 2 chấm hoặc xuống cmt)'
  validate_provided_urls('Tham gia https://discord.gg/qwwrrMcP',brief)
  validate_provided_urls('Tham gia https: //discord.gg/qwwrrMcP',brief)
 def test_newline_and_scheme_case_are_recognized_without_changing_invite_case(self):
  self.assertEqual(supplied_urls('HTTPS:\n//DISCORD.GG/qwwrrMcP.'),{'https://discord.gg/qwwrrMcP'})
 def test_changed_invite_extra_host_and_unknown_spaced_link_are_rejected(self):
  for body in ['https://discord.gg/OTHER','https://discord.gg/qwwrrmcp','https://discord.gg/qwwrrMcP/extra','https://discord.gg.evil.example/qwwrrMcP','https: //other.example/x']:
   with self.assertRaises(ValueError):validate_provided_urls(body,'https: //discord.gg/qwwrrMcP')
 def test_substring_of_supplied_url_is_not_allowed(self):
  with self.assertRaises(ValueError):validate_provided_urls('https://example.com/short','https://example.com/shorter')
 def test_no_link_guard_still_recognizes_obfuscated_url(self):
  self.assertTrue(has_link('https: //discord.gg/qwwrrMcP'))
  self.assertTrue(has_link('https:\n//discord.gg/qwwrrMcP'))
if __name__=='__main__':unittest.main()
