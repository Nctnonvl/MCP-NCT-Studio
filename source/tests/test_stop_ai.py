"""Cancellation tests use a temporary store and a blocked fake API."""
import sys,tempfile,threading,time,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from store import Store
from studio import Studio
import writing_policy

class StopAITests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.store=Store(Path(self.tmp.name)/'db.sqlite3')
  self.studio=Studio(self.store,lambda:{'model':'fake','mode':'publish'},Path(self.tmp.name)/'media')
  self.entered=threading.Event();self.release=threading.Event()
 def tearDown(self):
  self.release.set();self.wait();self.tmp.cleanup()
 def wait(self):
  end=time.monotonic()+4
  while self.studio.lock.locked() and time.monotonic()<end:time.sleep(.01)
  self.assertFalse(self.studio.lock.locked());return self.store.get('studio_task',{})
 def answer(self):return {'title':'Bài mới','body':'Ghé bên mình trao đổi về các lựa chọn phù hợp nhé.','body_no_link':'Ghé bên mình trao đổi về các lựa chọn phù hợp nhé.'}
 def blocked(self,*args):
  self.entered.set();self.release.wait(3);return self.answer()
 def test_provider_outage_stops_batch_and_preserves_drafts_without_scheduling(self):
  calls=[];activated=[]
  def generate(i):
   calls.append(i)
   if i==1:raise RuntimeError('Dịch vụ Muse · HTTP 502: Chưa xác nhận gửi tới Muse')
   return self.store.content('Draft '+str(i),category='Valorant')
  self.studio.background('group_autopost',range(5),generate,lambda *a:activated.append(True))
  task=self.wait()
  self.assertEqual(task['status'],'error');self.assertEqual(calls,[0,1]);self.assertEqual(activated,[])
  self.assertEqual(len(self.store.rows('SELECT * FROM contents')),1)
  self.assertEqual(len(task['errors']),1)

 def test_single_discards_inflight_result_then_can_restart(self):
  self.studio.chat_json=self.blocked
  self.studio.start({'brief':'Dịch vụ cho người chơi Valorant','category':'Valorant'})
  self.assertTrue(self.entered.wait(2));self.studio.stop()
  self.assertTrue(self.store.get('studio_task')['stop_requested'])
  self.release.set();self.assertEqual(self.wait()['status'],'stopped')
  self.assertEqual(self.store.rows('SELECT * FROM contents'),[])
  self.assertEqual(self.store.rows('SELECT * FROM jobs'),[])
  self.studio.chat_json=lambda *a:self.answer()
  self.studio.start({'brief':'Dịch vụ cho người chơi Valorant','category':'Valorant'})
  self.assertEqual(self.wait()['status'],'done')
 def test_batch_preserves_first_draft_and_does_not_activate(self):
  calls=[];activated=[]
  def generate(i):
   calls.append(i)
   if i==1:self.entered.set();self.release.wait(3)
   with self.studio.commit_lock:
    self.studio.check_cancel();return self.store.content('Draft '+str(i),category='Valorant')
  self.studio.background('test',range(90),generate,lambda *a:activated.append(True))
  self.assertTrue(self.entered.wait(2));self.studio.stop();self.release.set()
  task=self.wait();self.assertEqual(task['status'],'stopped')
  self.assertEqual(calls,[0,1]);self.assertEqual(activated,[])
  self.assertEqual(len(self.store.rows('SELECT * FROM contents')),1)
  self.assertEqual(self.store.rows('SELECT * FROM jobs'),[])
 def test_error_from_cancelled_api_is_stopped(self):
  def failing(*args):
   self.entered.set();self.release.wait(3);raise TimeoutError('fake timeout')
  self.studio.chat_json=failing
  self.studio.start({'brief':'Dịch vụ Valorant','category':'Valorant'})
  self.assertTrue(self.entered.wait(2));self.studio.stop();self.release.set()
  self.assertEqual(self.wait()['status'],'stopped')
 def test_stop_during_rewrites_keeps_latest_rejected_draft(self):
  calls=[];brief='Dữ kiện game mới và phiên bản cho người chơi lựa chọn, trao đổi qua Discord.'
  def writer(*args):
   calls.append(1)
   if len(calls)==3:self.studio.stop()
   return {'body':brief,'body_no_link':brief}
  self.studio.chat_json=writer
  self.studio.start({'brief':brief,'category':'Game'})
  task=self.wait()
  self.assertEqual(task['status'],'stopped');self.assertEqual(len(calls),3)
  self.assertEqual(self.store.rows('SELECT * FROM contents'),[])
  self.assertEqual(self.store.rows('SELECT * FROM jobs'),[])
  self.assertEqual(self.store.get('ai_rewrite_drafts')['single']['attempt'],2)

 def test_idle_stop_does_not_poison_next_task(self):
  self.studio.stop();self.assertFalse(self.studio.cancel_event.is_set())
 def test_recruitment_draft_rejected(self):
  self.assertTrue(writing_policy.issue('','Tìm bạn bắn Valorant','Ghé Discord',category='Valorant'))
  system=writing_policy.apply('',{'category':'Valorant'})
  self.assertIn('khách hàng',system);self.assertIn('không phải tuyển bạn',system)

if __name__=='__main__':unittest.main()
