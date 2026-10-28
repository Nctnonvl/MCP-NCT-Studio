import base64,json,tempfile,unittest,hashlib,io
from unittest.mock import patch
from pathlib import Path
from cryptography.hazmat.primitives import serialization,hashes
from cryptography.hazmat.primitives.asymmetric import rsa,padding
import online_update

class UpdateTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.key=rsa.generate_private_key(public_exponent=65537,key_size=2048);self.public=Path(self.tmp.name)/'public.pem';self.public.write_bytes(self.key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo))
 def tearDown(self):self.tmp.cleanup()
 def envelope(self,info):
  payload=json.dumps(info);return json.dumps({'payload':payload,'signature':base64.b64encode(self.key.sign(payload.encode(),padding.PKCS1v15(),hashes.SHA256())).decode()})
 def test_download_ignores_old_partial(self):
  body=b'MZ'+b'installer';info={'version':'9.0.0','url':'https://example.com/setup.exe','sha256':hashlib.sha256(body).hexdigest()}
  class Store:
   def get(self,key,default=None):return info if key=='update_status' else default
  updates=Path(self.tmp.name)/'updates';updates.mkdir();old=updates/'NCT-Studio-Setup-9.0.0.partial';old.write_bytes(b'old')
  with patch.object(online_update,'check',return_value={'available':True}),patch.object(online_update.urllib.request,'urlopen',return_value=io.BytesIO(body)):
   result=online_update.download(Store(),self.tmp.name,self.tmp.name)
  self.assertEqual(Path(result['path']).read_bytes(),body);self.assertEqual(old.read_bytes(),b'old')
 def test_duplicate_download_is_blocked(self):
  online_update._DOWNLOAD_LOCK.acquire()
  try:
   with self.assertRaisesRegex(ValueError,'Đang tải'):online_update.download(None,None,None)
  finally:online_update._DOWNLOAD_LOCK.release()
 def test_signed_manifest_accepted(self):
  info={'version':'1.2.0','url':'https://github.com/example/app/releases/download/v1.2.0/setup.exe','sha256':'a'*64}
  self.assertEqual(online_update.verify(self.envelope(info),self.public),info)
 def test_tampered_manifest_rejected(self):
  data=json.loads(self.envelope({'version':'1.2.0','url':'https://example.com/setup.exe','sha256':'a'*64}));data['payload']=data['payload'].replace('1.2.0','9.0.0')
  with self.assertRaises(Exception):online_update.verify(json.dumps(data),self.public)
 def test_unsigned_and_http_update_rejected(self):
  with self.assertRaises(Exception):online_update.verify('{"version":"1.2.0"}',self.public)
  with self.assertRaises(ValueError):online_update.url('http://example.com/update.json')
 def test_signature_from_other_publisher_rejected(self):
  other=rsa.generate_private_key(public_exponent=65537,key_size=2048)
  self.public.write_bytes(other.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo))
  with self.assertRaises(Exception):online_update.verify(self.envelope({'version':'1.2.0','url':'https://example.com/setup.exe','sha256':'a'*64}),self.public)
