import sys,threading,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import httpx,telegram_transport as transport
class TransportTests(unittest.TestCase):
 def setUp(self):self.p=patch.object(transport,'_clients',threading.local());self.p.start()
 def tearDown(self):self.p.stop()
 def test_reuses_one_connection_client_without_repeating_requests(self):
  response=Mock();response.json.return_value={'ok':True,'result':True}
  client=Mock();client.post.return_value=response
  with patch.object(transport.httpx,'Client',return_value=client) as factory:
   for _ in range(2):self.assertTrue(transport.request_telegram('hidden','getMe',{},12))
  factory.assert_called_once();self.assertEqual(client.post.call_count,2)
 def test_network_timeout_is_not_retried_and_never_exposes_token(self):
  client=Mock();client.post.side_effect=httpx.ReadTimeout('secret-token-in-url')
  with patch.object(transport.httpx,'Client',return_value=client):
   with self.assertRaises(RuntimeError) as caught:transport.request_telegram('secret-token-in-url','sendMessage',{})
  self.assertNotIn('secret-token-in-url',str(caught.exception));client.post.assert_called_once();client.close.assert_called_once();self.assertIsNone(transport._clients.client)
 def test_api_error_is_redacted(self):
  client=Mock();client.post.return_value.json.return_value={'ok':False,'description':'rejected token123'}
  with patch.object(transport.httpx,'Client',return_value=client):
   with self.assertRaisesRegex(RuntimeError,r'rejected \[TOKEN\]'):transport.request_telegram('token123','sendMessage',{})
  client.post.assert_called_once()
if __name__=='__main__':unittest.main()
