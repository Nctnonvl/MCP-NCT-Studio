import importlib.util,logging,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
class CallbackTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory()
  with patch.dict(os.environ,{'NCT_DATA_DIR':self.tmp.name}):
   spec=importlib.util.spec_from_file_location('feedback_controller',Path(__file__).resolve().parents[1]/'app.py');self.app=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.app)
  s=self.app.STORE;s.set('owner_id',12);s.set('owner_chat',34)
  gid=s.add_group('facebook.com/groups/test','Test',link_policy='allow')
  self.rid=s.record_result({'id':1,'group_id':gid,'group_name':'Test','url':'https://www.facebook.com/groups/test/'},{'state':'submitted'})
 def tearDown(self):logging.shutdown();self.tmp.cleanup()
 def query(self,uid=12,chat=34):return {'id':'cb','from':{'id':uid},'message':{'chat':{'id':chat},'message_id':5},'data':f'review:keep:{self.rid}'}
 def test_owner_can_keep_and_buttons_are_removed(self):
  with patch.object(self.app,'telegram') as tg:self.app.handle_callback(self.query())
  self.assertEqual(self.app.STORE.rows('SELECT decision FROM group_reviews')[0]['decision'],'keep')
  self.assertEqual(tg.call_count,2)
 def test_other_user_or_chat_cannot_change_review(self):
  with patch.object(self.app,'telegram') as tg:
   self.app.handle_callback(self.query(uid=99));self.app.handle_callback(self.query(chat=99));tg.assert_not_called()
  self.assertEqual(self.app.STORE.rows('SELECT decision FROM group_reviews')[0]['decision'],'')
 def test_keyboard_contains_real_post_link_and_both_decisions(self):
  row=self.app.STORE.rows('SELECT * FROM group_reviews')[0];row['post_url']='https://www.facebook.com/groups/test/posts/1/'
  keyboard=self.app.review_keyboard(row)['inline_keyboard']
  self.assertEqual(keyboard[1][0]['url'],row['post_url']);self.assertEqual(len(keyboard[-1]),2)
 def test_removal_followup_report_keeps_group_action_buttons(self):
  import json
  job={'id':1,'content_id':117,'group_name':'Test','url':'https://www.facebook.com/groups/test/'}
  self.app.notify_approval_result(job,{'state':'error','moderation_status':'removed','detail':'Bài đã bị gỡ.'})
  item=self.app.STORE.rows('SELECT * FROM outbox')[0]
  self.assertIn('Bài đã bị gỡ',item['text'])
  buttons=[b for row in json.loads(item['reply_markup'])['inline_keyboard'] for b in row]
  self.assertEqual([b['text'] for b in buttons],['Xem nhóm','Giữ nhóm','Xóa nhóm'])
  self.assertEqual(buttons[0]['url'],job['url'])
  self.assertEqual(buttons[1]['callback_data'],f'review:keep:{self.rid}')
  self.assertEqual(buttons[2]['callback_data'],f'review:delete:{self.rid}')
 def test_owner_delete_button_removes_group_from_tool_only(self):
  query=self.query();query['data']=f'review:delete:{self.rid}'
  with patch.object(self.app,'telegram') as tg:self.app.handle_callback(query)
  self.assertEqual(self.app.STORE.rows('SELECT deleted FROM groups')[0]['deleted'],1)
  self.assertEqual(self.app.STORE.rows('SELECT decision FROM group_reviews')[0]['decision'],'delete')
  self.assertEqual(tg.call_count,2)
if __name__=='__main__':unittest.main()
