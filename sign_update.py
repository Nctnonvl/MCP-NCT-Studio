"""Publisher tool: sign update.json locally; never ship the private signing key."""
import argparse,base64,hashlib,json
from pathlib import Path
from cryptography.hazmat.primitives import serialization,hashes
from cryptography.hazmat.primitives.asymmetric import rsa,padding
ROOT=Path(__file__).resolve().parent

def signing_key():
    folder=ROOT/'signing';folder.mkdir(exist_ok=True)
    private=folder/'release-private.pem'
    if private.exists():key=serialization.load_pem_private_key(private.read_bytes(),password=None)
    else:
        key=rsa.generate_private_key(public_exponent=65537,key_size=3072)
        private.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
    (ROOT/'source/assets/update-public.pem').write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo))
    return key

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--init',action='store_true');p.add_argument('--version');p.add_argument('--url');p.add_argument('--installer');a=p.parse_args();key=signing_key()
    if not a.init:
        if not all([a.version,a.url,a.installer]):p.error('Cần --version --url --installer')
        info={'version':a.version,'url':a.url,'sha256':hashlib.sha256(Path(a.installer).read_bytes()).hexdigest()}
        payload=json.dumps(info,ensure_ascii=False,separators=(',',':'))
        envelope={'payload':payload,'signature':base64.b64encode(key.sign(payload.encode(),padding.PKCS1v15(),hashes.SHA256())).decode()}
        (ROOT/'output/update.json').write_text(json.dumps(envelope,indent=2),encoding='utf-8')
        print('Đã tạo output/update.json. Chỉ đăng file này và bộ cài; không chia sẻ thư mục signing.')
