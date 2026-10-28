"""Local media intake. No arbitrary filesystem paths are accepted from the dashboard."""
import json
import mimetypes
import secrets
from pathlib import Path

MAX_UPLOAD = 500*1024*1024
MAX_IMAGE_UPLOAD = 100*1024*1024
EXTENSIONS = {'.jpg','.jpeg','.png','.webp','.mp4','.mov','.webm'}


def paths(value):
    if not value:
        return []
    if str(value).startswith('['):
        result=json.loads(value)
        if not isinstance(result,list) or not all(isinstance(p,str) for p in result):
            raise ValueError('Danh sách tệp không hợp lệ.')
        return result
    return [str(value)]


def serialize(items):
    return json.dumps(items,ensure_ascii=False) if len(items)>1 else (items[0] if items else '')


def validate_file(path):
    path=Path(path)
    ext=path.suffix.lower()
    with path.open('rb') as file:header=file.read(32)
    valid = ((ext in {'.jpg','.jpeg'} and header.startswith(b'\xff\xd8\xff')) or
        (ext=='.png' and header.startswith(b'\x89PNG\r\n\x1a\n')) or
        (ext=='.webp' and header.startswith(b'RIFF') and header[8:12]==b'WEBP') or
        (ext in {'.mp4','.mov'} and b'ftyp' in header[:24]) or
        (ext=='.webm' and header.startswith(b'\x1aE\xdf\xa3')))
    if not valid:
        raise ValueError('Định dạng tệp không khớp ảnh/video được hỗ trợ.')
    return 'video' if ext in {'.mp4','.mov','.webm'} else 'image'


def receive(stream,size,filename,directory):
    ext=Path(filename).suffix.lower()
    limit=MAX_UPLOAD if ext in {'.mp4','.mov','.webm'} else MAX_IMAGE_UPLOAD
    if ext not in EXTENSIONS or not 0<size<=limit:
        raise ValueError('Hỗ trợ JPG, PNG, WEBP, MP4, MOV, WEBM; ảnh tối đa 100 MB, video tối đa 500 MB trên dashboard.')
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    target=directory/(secrets.token_hex(16)+ext)
    try:
        with target.open('wb') as output:
            left=size
            while left:
                chunk=stream.read(min(left,1024*1024))
                if not chunk:
                    raise ValueError('Tải tệp bị gián đoạn.')
                output.write(chunk);left-=len(chunk)
        kind=validate_file(target)
        return {'id':target.name,'name':Path(filename).name[:160],'kind':kind,'bytes':size}
    except BaseException:
        target.unlink(missing_ok=True)
        raise


def resolve(ids,directory):
    if not isinstance(ids,list) or len(ids)>10:
        raise ValueError('Tối đa 10 ảnh hoặc 1 video cho mỗi bài.')
    base=Path(directory).resolve();result=[];kinds=[]
    for name in ids:
        if not isinstance(name,str) or Path(name).name!=name:
            raise ValueError('Tên tệp không hợp lệ.')
        p=(base/name).resolve()
        if not p.is_relative_to(base) or not p.is_file():
            raise ValueError('Tệp không tồn tại trong kho media.')
        kinds.append(validate_file(p));result.append(str(p))
    if 'video' in kinds and len(kinds)>1:
        raise ValueError('Chọn một video, hoặc nhiều ảnh. Tách ảnh và video thành hai bài.')
    return serialize(result)


def public(value):
    return [{'id':Path(p).name,'kind':'video' if Path(p).suffix.lower() in {'.mp4','.mov','.webm'} else 'image'} for p in paths(value)]
