import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import unittest,time
from unittest.mock import patch
import test_review_callbacks as fixtures
class DeleteCommandTests(fixtures.CallbackTests):
 def request(self,value='1'):
  with patch.object(self.app,'telegram') as tg:
   self.app.handle_message({'from':{'id':12},'chat':{'id':34,'type':'private'},'text':'/deletegroup '+value})
  self.assertEqual(self.app.STORE.rows('SELECT deleted FROM groups')[0]['deleted'],0)
  pending=self.app.STORE.get('pending_delete_group');self.assertTrue(pending)
  q=self.query();q['data']='groupdelete:yes:'+pending['nonce'];return q
 def test_command_requires_confirmation_then_hides_group(self):
  q=self.request()
  with patch.object(self.app,'telegram'):self.app.handle_callback(q)
  self.assertEqual(self.app.STORE.rows('SELECT deleted,enabled FROM groups')[0],{'deleted':1,'enabled':0})
  self.assertEqual(len(self.app.STORE.rows('SELECT * FROM group_reviews')),1)
 def test_group_url_is_supported(self):
  q=self.request('https://www.facebook.com/groups/test/?locale=vi_VN')
  self.assertTrue(q['data'].startswith('groupdelete:yes:'))
 def test_cancel_does_not_delete_group(self):
  q=self.request();q['data']=q['data'].replace(':yes:',':no:')
  with patch.object(self.app,'telegram'):self.app.handle_callback(q)
  self.assertEqual(self.app.STORE.rows('SELECT deleted FROM groups')[0]['deleted'],0)
 def test_expired_or_unauthorized_callback_cannot_delete(self):
  q=self.request();q['from']['id']=99
  with patch.object(self.app,'telegram'):self.app.handle_callback(q)
  p=self.app.STORE.get('pending_delete_group');p['at']=time.time()-601;self.app.STORE.set('pending_delete_group',p);q['from']['id']=12
  with patch.object(self.app,'telegram'):self.app.handle_callback(q)
  self.assertEqual(self.app.STORE.rows('SELECT deleted FROM groups')[0]['deleted'],0)
 def test_working_job_blocks_delete_without_changing_schedule(self):
  s=self.app.STORE;s.enable_group(1,True);cid=s.content('frozen');ids=s.plan(cid,30)
  with s.db() as c:c.execute("UPDATE jobs SET state='working' WHERE id=?",(ids[0],))
  q=self.request()
  with patch.object(self.app,'telegram'):
   with self.assertRaisesRegex(ValueError,'/pause'):self.app.handle_callback(q)
  self.assertEqual(s.rows('SELECT deleted FROM groups')[0]['deleted'],0)
if __name__=='__main__':unittest.main()
