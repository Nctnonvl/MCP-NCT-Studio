"""Updates require an HTTPS feed and a manifest signed by this release key."""
import base64,hashlib,json,re,urllib.request,threading,uuid
from pathlib import Path
from urllib.parse import urlsplit
VERSION='1.1.9'
FEED='https://github.com/Nctnonvl/MCP-NCT-Studio/releases/latest/download/update.json'
_DOWNLOAD_LOCK=threading.Lock()

def url(value):
    p=urlsplit(str(value))
    if p.scheme!='https' or not p.hostname or p.username or p.password or p.fragment:raise ValueError('Địa chỉ cập nhật phải là HTTPS, không chứa thông tin đăng nhập.')
    return str(value)

def verify(raw,public_key):
    from cryptography.hazmat.primitives import serialization,hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    envelope=json.loads(raw);payload=envelope['payload']
    if not isinstance(payload,str):raise ValueError('Manifest không hợp lệ.')
    serialization.load_pem_public_key(Path(public_key).read_bytes()).verify(base64.b64decode(envelope['signature'],validate=True),payload.encode('utf-8'),padding.PKCS1v15(),hashes.SHA256())
    info=json.loads(payload)
    if not re.fullmatch(r'\d+\.\d+\.\d+',info.get('version','')) or not re.fullmatch(r'[a-f0-9]{64}',info.get('sha256','')):raise ValueError('Thông tin bản cập nhật không hợp lệ.')
    url(info['url']);return info

def check(store,root):
    feed=store.get('update_feed',FEED)
    if not feed:raise ValueError('Chưa có địa chỉ phát hành. Nhập URL update.json trên GitHub Releases hoặc website của bro.')
    request=urllib.request.Request(url(feed),headers={'User-Agent':'NCT-Studio/'+VERSION})
    with urllib.request.urlopen(request,timeout=30) as response:raw=response.read(128*1024+1)
    if len(raw)>128*1024:raise ValueError('Manifest cập nhật quá lớn.')
    try:info=verify(raw,Path(root)/'assets/update-public.pem')
    except Exception as exc:raise ValueError('Không xác minh được chữ ký bản cập nhật; chưa tải hoặc chạy file.') from exc
    available=tuple(map(int,info['version'].split('.')))>tuple(map(int,VERSION.split('.')))
    store.set('update_status',{**info,'available':available})
    return {'available':available,'version':info['version'],'message':'Có bản '+info['version']+'. Bấm Tải và cài khi sẵn sàng.' if available else 'Bro đang dùng bản mới nhất của nguồn phát hành này.'}

def download(store,root,data):
    if not _DOWNLOAD_LOCK.acquire(blocking=False):raise ValueError('Đang tải bản cập nhật. Vui lòng chờ lượt tải hiện tại hoàn tất.')
    try:return _download(store,root,data)
    finally:_DOWNLOAD_LOCK.release()

def _download(store,root,data):
    # Re-fetch and verify signed metadata at download time, never trust a browser-supplied URL.
    checked=check(store,root)
    if not checked['available']:raise ValueError('Chưa có bản mới để cài.')
    info=store.get('update_status',{});folder=Path(data)/'updates';folder.mkdir(exist_ok=True)
    target=folder/('NCT-Studio-Setup-'+info['version']+'-'+uuid.uuid4().hex+'.exe');partial=target.with_suffix('.partial')
    digest=hashlib.sha256();size=0
    try:
        with urllib.request.urlopen(urllib.request.Request(url(info['url']),headers={'User-Agent':'NCT-Studio/'+VERSION}),timeout=60) as response,partial.open('wb') as output:
            while True:
                block=response.read(1024*1024)
                if not block:break
                size+=len(block)
                if size>800*1024*1024:raise ValueError('Gói cập nhật vượt 800 MB.')
                digest.update(block);output.write(block)
        if digest.hexdigest()!=info['sha256']:raise ValueError('File tải về không khớp SHA-256; không cài bản này.')
        with partial.open('rb') as file:
            if file.read(2)!=b'MZ':raise ValueError('Gói cập nhật không phải bộ cài Windows.')
        partial.replace(target)
        return {'path':str(target.resolve()),'sha256':info['sha256'],'version':info['version']}
    finally:
        try:partial.unlink(missing_ok=True)
        except OSError:pass

def status(store):return {'version':VERSION,'feed':store.get('update_feed',FEED),'latest':store.get('update_status',{})}
