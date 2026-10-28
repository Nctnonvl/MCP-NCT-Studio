"""Detect Python source updates so an old controller cannot run new workers."""
import hashlib
from pathlib import Path
_cache={}

def code_revision(root):
 root=Path(root).resolve();files=sorted(root.glob('*.py'))
 stamp=tuple((p.name,p.stat().st_size,p.stat().st_mtime_ns) for p in files)
 old=_cache.get(str(root))
 if old and old[0]==stamp:return old[1]
 digest=hashlib.sha256()
 for path in files:
  digest.update(path.name.encode());digest.update(path.read_bytes())
 revision=digest.hexdigest()[:16]
 _cache[str(root)]=(stamp,revision)
 return revision
