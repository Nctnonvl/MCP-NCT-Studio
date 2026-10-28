import json,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from store import Store,has_link
from studio import Studio
import post_footer
class FooterTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.s=Store(Path(self.tmp.name)/'db.sqlite3');self.studio=Studio(self.s,lambda:{'model':'fake','mode':'publish'},Path(self.tmp.name)/'media')
  self.footer='https ://discord.gg/DzdDGgry (bỏ dấu cách trước dấu hai chấm)'
 def tearDown(self):self.tmp.cleanup()
 def save(self,text=None,enabled=True):return post_footer.save(self.s,{'enabled':enabled,'text':self.footer if text is None else text})
 def wait(self):
  end=time.monotonic()+5
  while self.studio.lock.locked() and time.monotonic()<end:time.sleep(.01)
  self.assertFalse(self.studio.lock.locked());return self.s.get('studio_task')
 def test_preserves_both_url_formats_exactly_at_end(self):
  for footer in [self.footer,'https://discord.gg/DzdDGgry']:
   cfg=self.save(footer);body,alt,frozen=post_footer.append('Nội dung mới.','Bản không link.',cfg)
   self.assertEqual(body,'Nội dung mới.\n\n'+footer);self.assertEqual(alt,'Bản không link.');self.assertEqual(frozen,footer)
 def test_plain_text_footer_is_also_appended_to_no_link_variant(self):
  cfg=self.save('Cảm ơn mọi người!');body,alt,_=post_footer.append('Bài.','Bản khác.',cfg)
  self.assertTrue(body.endswith(cfg['text']));self.assertTrue(alt.endswith(cfg['text']));self.assertFalse(has_link(alt))
 def test_no_duplicate_footer_and_equivalent_url_is_removed_from_brief(self):
  cfg=self.save();body,alt,_=post_footer.append('Bài mới.\n\n'+self.footer,'Bản khác.',cfg)
  self.assertEqual(body.count(self.footer),1)
  self.assertEqual(post_footer.remove('Dữ kiện. https://discord.gg/DzdDGgry',self.footer),'Dữ kiện.')
 def test_disable_and_invalid_or_oversize_footer(self):
  cfg=self.save(enabled=False);self.assertEqual(post_footer.append('Bài','Khác',cfg),('Bài','Khác',''))
  for text in ['', 'x'*1001,'https://user:password@example.com']:
   with self.assertRaises(ValueError):self.save(text)
  with self.assertRaises(ValueError):post_footer.append('x'*4990,'Khác',self.save())
 def test_single_generation_appends_outside_ai_and_does_not_send_reserved_link(self):
  self.save();answer={'title':'Test','body':'Có nhiều lựa chọn để bạn tìm hiểu trong cộng đồng. Mời trao đổi thêm thông tin tại Discord.','body_no_link':'Mời mọi người tìm hiểu các lựa chọn đang được cung cấp và trao đổi thêm trong cộng đồng.'}
  with patch.object(self.studio,'chat_json',return_value=answer) as ai:
   self.studio.start({'brief':'Thông tin cộng đồng game. https://discord.gg/DzdDGgry','category':'Game'});task=self.wait()
  self.assertEqual(task['status'],'done');row=self.s.rows('SELECT * FROM contents')[0]
  self.assertTrue(row['body'].endswith(self.footer));self.assertEqual(row['footer_text'],self.footer);self.assertFalse(has_link(row['body_no_link']))
  self.assertEqual(ai.call_args.args[1]['allowed_urls'],[]);self.assertNotIn('DzdDGgry',ai.call_args.args[1]['brief'])
 def test_edit_only_affects_future_generation_preserving_old_post_and_frozen_job(self):
  cfg=self.save();body,alt,footer=post_footer.append('Nội dung','Bản khác',cfg)
  cid=self.s.content(body,body_no_link=alt,footer_text=footer)
  gid=self.s.add_group('facebook.com/groups/footer','Footer',link_policy='allow');self.s.enable_group(gid,True);jobs=self.s.plan(cid,30)
  self.save('https://discord.gg/new-code')
  self.assertEqual(self.s.rows('SELECT body FROM contents WHERE id=?',(cid,))[0]['body'],body)
  self.assertEqual(self.s.rows('SELECT body FROM jobs WHERE id=?',(jobs[0],))[0]['body'],body)
  self.assertEqual(post_footer.config(Store(Path(self.tmp.name)/'db.sqlite3'))['text'],'https://discord.gg/new-code')
 def test_adding_same_footer_does_not_make_distinct_drafts_look_duplicated(self):
  self.save('Dòng cố định rất dài để mọi người biết cách liên hệ. '+self.footer)
  answers=[{'title':'Một','body':'Khi lựa chọn vai trò trong đội, hãy trao đổi rõ cách phối hợp từ đầu. Điều này giúp mọi người thống nhất mục tiêu của buổi chơi.','body_no_link':'Cách phối hợp trong đội có nhiều lựa chọn để cùng trao đổi. Mỗi người có thể chia sẻ vai trò mình yêu thích.'},
   {'title':'Hai','body':'Bạn thích quan sát điều gì trên giao diện khi xem một trận đấu? Mời chia sẻ góc nhìn từ những chi tiết có sẵn trên màn hình.','body_no_link':'Nhìn từ giao diện trận đấu, mỗi người thường chú ý đến những thông tin khác nhau. Bạn quan tâm chi tiết nào nhất?'}]
  with patch.object(self.studio,'chat_json',side_effect=answers):
   for _ in range(2):self.studio.start({'brief':'Chia sẻ về game và phối hợp trong đội.','category':'Game'});self.assertEqual(self.wait()['status'],'done')
  self.assertEqual(len(self.s.rows('SELECT * FROM contents')),2)
if __name__=='__main__':unittest.main()
