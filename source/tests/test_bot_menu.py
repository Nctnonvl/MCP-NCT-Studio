import sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import test_review_callbacks as fixtures
class MenuTests(fixtures.CallbackTests):
 def message(self,text):return {'from':{'id':12},'chat':{'id':34,'type':'private'},'text':text}
 def click(self,data):q=self.query();q['data']=data;return q
 def test_plain_menu_and_command_send_visible_inline_buttons(self):
  for text in ('Menu','menu','🏠 Menu','/menu'):
   with patch.object(self.app,'telegram') as tg:self.app.handle_message(self.message(text))
   payload=tg.call_args.args[1];rows=payload['reply_markup']['inline_keyboard']
   self.assertIn('BẢNG ĐIỀU KHIỂN',payload['text']);self.assertTrue(any(b['callback_data']=='panel:groups:0' for row in rows for b in row))
 def test_menu_leaves_wizard_and_does_not_save_text_as_content(self):
  s=self.app.STORE;s.set('bot_wizard',{'kind':'manual','step':'body'})
  with patch.object(self.app,'telegram'):self.app.handle_message(self.message('Menu'))
  self.assertIsNone(s.get('bot_wizard'));self.assertEqual(s.rows('SELECT * FROM contents'),[])
 def test_group_card_has_delete_button_but_does_not_delete(self):
  with patch.object(self.app,'telegram') as tg:self.app.handle_callback(self.click('panel:group:1'))
  rows=tg.call_args.args[1]['reply_markup']['inline_keyboard'];self.assertTrue(any(b.get('callback_data')=='panel:deletegroup:1' for row in rows for b in row))
  with patch.object(self.app,'telegram'):self.app.handle_callback(self.click('panel:deletegroup:1'))
  self.assertTrue(self.app.STORE.get('pending_delete_group'));self.assertEqual(self.app.STORE.rows('SELECT deleted FROM groups')[0]['deleted'],0)
 def test_other_user_cannot_open_private_menu(self):
  q=self.click('panel:home:0');q['from']['id']=99
  with patch.object(self.app,'telegram') as tg:self.app.handle_callback(q);tg.assert_not_called()
 def test_pagination_limits_group_buttons(self):
  for i in range(9):self.app.STORE.add_group(f'facebook.com/groups/group{i}')
  with patch.object(self.app,'telegram') as tg:self.app.panel(34,'groups',0)
  rows=tg.call_args.args[1]['reply_markup']['inline_keyboard']
  self.assertEqual(sum(b.get('callback_data','').startswith('panel:group:') for row in rows for b in row),6)
  self.assertTrue(any(b.get('callback_data')=='panel:groups:1' for row in rows for b in row))
 def test_delete_post_can_be_cancelled(self):
  s=self.app.STORE;cid=s.content('Keep this')
  with patch.object(self.app,'telegram'):self.app.handle_callback(self.click(f'panel:deletepost:{cid}'))
  p=s.get('pending_delete_post');self.assertTrue(s.rows('SELECT id FROM contents WHERE id=?',(cid,)))
  with patch.object(self.app,'telegram'):self.app.handle_callback(self.click('postdelete:no:'+p['nonce']))
  self.assertTrue(s.rows('SELECT id FROM contents WHERE id=?',(cid,)))
 def test_navigation_edits_current_card_without_new_messages_or_outbox(self):
  with patch.object(self.app,'telegram') as tg:self.app.handle_callback(self.click('panel:home:0'))
  self.assertEqual([c.args[0] for c in tg.call_args_list],['answerCallbackQuery','editMessageText'])
  self.assertEqual(self.app.STORE.rows('SELECT * FROM outbox'),[])
 def test_status_responds_directly_in_same_card(self):
  with patch.object(self.app,'telegram') as tg:self.app.handle_callback(self.click('panel:status:0'))
  self.assertEqual([c.args[0] for c in tg.call_args_list],['answerCallbackQuery','editMessageText'])
  self.assertEqual(self.app.STORE.rows('SELECT * FROM outbox'),[])
 def test_unchanged_card_is_not_sent_again(self):
  with patch.object(self.app,'telegram',side_effect=RuntimeError('Bad Request: message is not modified')) as tg:
   result=self.app.render_panel(34,'same',{'inline_keyboard':[]},5)
  self.assertTrue(result['unchanged']);tg.assert_called_once()
 def test_random_menu_uses_existing_posts_and_only_creates_drafts(self):
  store=self.app.STORE;store.enable_group(1,True)
  store.group_category(1,'Game')
  store.content('Saved game post',category='Game');store.content('Saved sales post',category='Sales')
  with patch.object(self.app,'telegram'),patch.object(self.app,'studio',side_effect=AssertionError('No AI drafting')),patch.object(self.app,'run_queue') as run:
   self.app.handle_callback(self.click('panel:randomcreate:0'))
  jobs=store.rows('SELECT * FROM jobs');self.assertTrue(jobs)
  self.assertTrue(all(j['state']=='draft' and j['routing_mode']=='random' for j in jobs))
  self.assertTrue(all(j['body']=='Saved game post' for j in jobs))
  self.assertEqual(len(store.rows('SELECT * FROM contents')),2);run.assert_not_called()
if __name__=='__main__':unittest.main()
