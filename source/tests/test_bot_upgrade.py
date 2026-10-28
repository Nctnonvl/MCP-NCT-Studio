import unittest,time
from unittest.mock import patch
import test_review_callbacks as fixtures
import bot_ui

class UpgradeTests(fixtures.CallbackTests):
 def click(self,data):q=self.query();q['data']=data;return q
 def message(self,text):return {'from':{'id':12},'chat':{'id':34,'type':'private'},'text':text}
 def make_job(self,state='draft',attempted=0):
  s=self.app.STORE;s.enable_group(1,True);s.group_category(1,'Valorant')
  cid=s.content('Nội dung cố định',category='Valorant');jid=s.plan(cid,30)[0]
  with s.db() as c:c.execute('UPDATE jobs SET state=?,post_attempted=? WHERE id=?',(state,attempted,jid))
  return jid
 def test_every_main_card_renders_and_callbacks_fit_limits(self):
  for screen in ['home','groups','posts','queue','drafts','pending','attention','history','reviews','stats','worst','statpending','watch','ai','status','help','random']:
   with self.subTest(screen=screen),patch.object(self.app,'telegram',return_value={'message_id':5}) as tg:
    self.app.panel(34,screen,0,5);payload=tg.call_args.args[1]
    self.assertLessEqual(len(payload['text']),4000)
    for row in payload['reply_markup']['inline_keyboard']:
     for button in row:
      if 'callback_data' in button:self.assertLessEqual(len(button['callback_data'].encode()),64)
 def test_new_commands_open_cards_without_outbox(self):
  for command in ['/stats','/ai','/queue','/groups','/contents','/help']:
   with patch.object(self.app,'telegram') as tg:self.app.handle_message(self.message(command))
   self.assertTrue(tg.called)
  self.assertEqual(self.app.STORE.rows('SELECT * FROM outbox'),[])
 def test_cancel_confirmation_is_scoped_and_one_use(self):
  jid=self.make_job('queued')
  with self.app.STORE.db() as c:other=c.execute("INSERT INTO jobs(group_id,group_name,url,body,media,due,created,updated,state) SELECT group_id,group_name,url,body,media,due,created,updated,'draft' FROM jobs WHERE id=?",(jid,)).lastrowid
  with patch.object(self.app,'telegram'):self.app.handle_callback(self.click('tg:cancel:'+str(jid)))
  pending=self.app.STORE.get('tg_confirmation');self.assertEqual(self.app.STORE.rows('SELECT state FROM jobs WHERE id=?',(jid,))[0]['state'],'queued')
  with patch.object(self.app,'telegram'):self.app.handle_callback(self.click('tg:confirm:0:'+pending['nonce']))
  self.assertEqual(self.app.STORE.rows('SELECT state FROM jobs WHERE id=?',(jid,))[0]['state'],'cancelled')
  self.assertEqual(self.app.STORE.rows('SELECT state FROM jobs WHERE id=?',(other,))[0]['state'],'draft')
  with patch.object(self.app,'telegram'),self.assertRaises(ValueError):self.app.handle_callback(self.click('tg:confirm:0:'+pending['nonce']))
 def test_unverified_post_has_no_retry_and_retry_is_rejected(self):
  jid=self.make_job('uncertain',1)
  with patch.object(self.app,'telegram') as tg:self.app.panel(34,'job',jid,5)
  callbacks=[b.get('callback_data','') for row in tg.call_args.args[1]['reply_markup']['inline_keyboard'] for b in row]
  self.assertFalse(any(c.startswith('tg:retry') for c in callbacks))
  with patch.object(self.app,'telegram'),self.assertRaises(ValueError):self.app.handle_callback(self.click('tg:retry:'+str(jid)))
 def test_reschedule_keeps_payload_and_requires_approval(self):
  jid=self.make_job('queued');before=self.app.STORE.rows('SELECT body FROM jobs WHERE id=?',(jid,))[0]['body']
  with patch.object(self.app,'telegram'):self.app.handle_callback(self.click('tg:reschedule:'+str(jid)))
  from datetime import datetime,timedelta,timezone
  text=(datetime.now(timezone(timedelta(hours=7)))+timedelta(days=1)).strftime('%Y-%m-%d %H:%M')
  with patch.object(self.app,'telegram'):self.app.handle_message(self.message(text))
  row=self.app.STORE.rows('SELECT * FROM jobs WHERE id=?',(jid,))[0];self.assertEqual(row['state'],'draft');self.assertEqual(row['body'],before)
 def test_campaign_does_not_call_ai_until_confirmation(self):
  s=self.app.STORE;s.enable_group(1,True);s.group_category(1,'Valorant')
  plan={'items':[{'group_id':1,'due':time.time()+100}], 'unique_groups':1,'requested':1,'estimated_posts':1,'api_calls_min':1,'uncovered_groups':[]}
  with patch.object(self.app,'telegram',return_value={'message_id':5}),patch.object(bot_ui.campaign_plan,'preview',return_value=plan),patch.object(self.app,'studio') as studio:
   self.app.handle_callback(self.click('tg:aistart:0'))
   self.app.handle_callback(self.click('tg:campaigngame:0:Valorant'))
   self.app.handle_message(self.message('Dữ kiện cho game, trao đổi qua Discord.'))
   self.app.handle_callback(self.click('tg:campaignpreview:0:15'))
   studio.assert_not_called();pending=s.get('tg_confirmation')
   studio.return_value.draft_groups.return_value={'message':'Đã bắt đầu'}
   self.app.handle_callback(self.click('tg:confirm:0:'+pending['nonce']))
   studio.return_value.draft_groups.assert_called_once();options=studio.return_value.draft_groups.call_args.args[0]
   self.assertTrue(options['coverage_once']);self.assertEqual(options['ids'],[1])
 def test_non_owner_cannot_use_new_actions(self):
  q=self.click('tg:bulkset:0');q['from']['id']=99
  with patch.object(self.app,'telegram') as tg:self.app.handle_callback(q);tg.assert_not_called()
  self.assertIsNone(self.app.STORE.get('tg_confirmation'))
 def test_group_category_buttons_include_all(self):
  with patch.object(self.app,'telegram') as tg:self.app.handle_callback(self.click('tg:category:1'))
  buttons=[b for row in tg.call_args.args[1]['reply_markup']['inline_keyboard'] for b in row]
  self.assertTrue(any(b.get('callback_data')=='tg:setcategory:1:ALL' for b in buttons))
 def test_search_posts_is_read_only(self):
  s=self.app.STORE;s.content('Nội dung về game',category='Valorant')
  with patch.object(self.app,'telegram') as tg:
   self.app.handle_callback(self.click('tg:searchpost:0'));self.app.handle_message(self.message('game'))
  self.assertIn('KẾT QUẢ TÌM KIẾM',tg.call_args.args[1]['text'])
  self.assertEqual(len(s.rows('SELECT * FROM contents')),1)
 def test_link_preview_needs_confirmation_and_does_not_change_posts(self):
  s=self.app.STORE;old='https://discord.gg/old';new='https://discord.gg/new';s.content('Liên hệ '+old)
  with patch.object(self.app,'telegram'),patch.object(self.app,'apply_link_change') as apply:
   self.app.handle_callback(self.click('tg:linkscope:0'));self.app.handle_message(self.message(old));self.app.handle_message(self.message(new))
   apply.assert_not_called();p=s.get('tg_confirmation');self.assertEqual(p['operation'],'links')
   self.app.handle_callback(self.click('tg:confirm:0:'+p['nonce']));apply.assert_called_once_with(old,new,p['extra']['preview']['digest'],facebook=False)
 def test_bulk_reports_unknown_groups_without_partial_error(self):
  s=self.app.STORE;other=s.add_group('facebook.com/groups/unknown','Unknown');s.enable_group(1,False)
  with patch.object(self.app,'telegram') as tg:
   self.app.handle_callback(self.click('tg:bulkset:1'));p=s.get('tg_confirmation');self.app.handle_callback(self.click('tg:confirm:0:'+p['nonce']))
  self.assertEqual(s.rows('SELECT enabled FROM groups WHERE id=1')[0]['enabled'],1)
  self.assertEqual(s.rows('SELECT enabled FROM groups WHERE id=?',(other,))[0]['enabled'],0)
  self.assertIn('Bỏ qua 1',tg.call_args.args[1]['text'])
 def test_campaign_custom_options_are_validated(self):
  s=self.app.STORE;s.set('bot_wizard',{'kind':'tg_campaign','step':'options','brief':'Thông tin đúng cho game','scope':'any'})
  with patch.object(self.app,'telegram'):self.app.handle_message(self.message('15 5 40-80'))
  w=s.get('bot_wizard');self.assertEqual((w['per_day'],w['horizon'],w['minutes']),(15,5,'40-80'))

 def test_plan_details_do_not_start_ai_or_consume_confirmation(self):
  s=self.app.STORE;plan={'items':[{'group_id':1,'name':'Test','due':time.time()+500}], 'uncovered_groups':[{'id':2,'name':'Other','reason':'Chưa đủ điều kiện'}]}
  with patch.object(self.app,'telegram',return_value={'message_id':5}),patch.object(self.app,'studio') as studio:
   bot_ui.confirm(self.app._bot_context(),34,'campaign',0,'Preview',5,{'plan':plan,'options':{}})
   nonce=s.get('tg_confirmation')['nonce']
   self.app.handle_callback(self.click('tg:planlist:0'));self.app.handle_callback(self.click('tg:uncovered:0'))
   self.assertEqual(s.get('tg_confirmation')['nonce'],nonce);studio.assert_not_called()
 def test_expired_confirmation_cannot_modify_queue(self):
  jid=self.make_job('queued');s=self.app.STORE
  s.set('tg_confirmation',{'nonce':'expired','operation':'cancel','value':jid,'at':time.time()-601,'extra':{}})
  with patch.object(self.app,'telegram'),self.assertRaises(ValueError):self.app.handle_callback(self.click('tg:confirm:0:expired'))
  self.assertEqual(s.rows('SELECT state FROM jobs WHERE id=?',(jid,))[0]['state'],'queued')

 def test_home_cancels_pending_wizard(self):
  self.app.STORE.set('bot_wizard',{'kind':'tg_campaign','step':'brief'})
  with patch.object(self.app,'telegram'):self.app.handle_callback(self.click('panel:home:0'))
  self.assertIsNone(self.app.STORE.get('bot_wizard'))
if __name__=='__main__':unittest.main()
