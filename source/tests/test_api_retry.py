import unittest
from unittest.mock import Mock,patch
from studio import Studio,StudioCancelled

class ApiRetryTests(unittest.TestCase):
 def make(self):
  store=Mock();store.get.side_effect=lambda key,default=None: 0 if key=='control_revision' else default
  return Studio(store,lambda:{},'.')
 def test_server_errors_retry_same_request_until_response(self):
  s=self.make();s._chat_json_once=Mock(side_effect=[RuntimeError('HTTP 500'),RuntimeError('HTTP 503'),{'body':'ok'}])
  with patch('studio.time.monotonic',side_effect=[0,11,20,41]):
   self.assertEqual(s.chat_json('system','request'),{'body':'ok'})
  self.assertEqual(s._chat_json_once.call_count,3)
  self.assertTrue(all(c.args==('system','request') for c in s._chat_json_once.call_args_list))
 def test_stop_interrupts_backoff(self):
  s=self.make();s._chat_json_once=Mock(side_effect=RuntimeError('HTTP 500'))
  s.cancel_event.wait=Mock(side_effect=lambda delay:s.cancel_event.set() or True)
  with self.assertRaises(StudioCancelled):s.chat_json('system','request')
  self.assertEqual(s._chat_json_once.call_count,1)
 def test_credentials_and_quota_do_not_loop(self):
  for error in ['HTTP 401','HTTP 429: insufficient_quota','HTTP 400']:
   s=self.make();s._chat_json_once=Mock(side_effect=RuntimeError(error))
   with self.assertRaises(RuntimeError):s.chat_json('system','request')
   self.assertEqual(s._chat_json_once.call_count,1)
