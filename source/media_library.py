"""Logical game pools over the existing flat media folder; originals never moved."""
import hashlib,json,random,time
from pathlib import Path
import media
POOLS=('Valorant','Delta Force','PUBG','LOL','The isle','CS2')

def pool(value):
    if value not in POOLS:raise ValueError('Chọn một trong sáu kho game.')
    return value

def register(store,directory,item,category=''):
    if category:pool(category)
    media.resolve([item['id']],directory)
    with store.db() as c:c.execute('INSERT OR IGNORE INTO media_catalog(id,pool,name,kind) VALUES(?,?,?,?)',(item['id'],category,item.get('name',item['id']),item['kind']))

def initialize(store,directory):
    with store.db() as c:c.executemany('INSERT OR IGNORE INTO media_pools VALUES(?)',[(p,) for p in POOLS])
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    # Seed only exact existing game labels once; a user-cleared mapping stays cleared.
    seeded=set(store.get('media_pool_seeded_groups',[]));labels={p.casefold():p for p in POOLS}
    for g in store.rows('SELECT id,category FROM groups WHERE deleted=0'):
        if g['id'] in seeded:continue
        category=labels.get(g['category'].strip().casefold())
        if category and not store.rows('SELECT pool FROM group_media_pools WHERE group_id=?',(g['id'],)):
            with store.db() as c:c.execute('INSERT OR IGNORE INTO group_media_pools VALUES(?,?)',(g['id'],category))
        seeded.add(g['id'])
    store.set('media_pool_seeded_groups',sorted(seeded))
    known={r['id'] for r in store.rows('SELECT id FROM media_catalog')}
    for path in directory.iterdir():
        if path.name in known or not path.is_file() or path.suffix.lower() not in media.EXTENSIONS:continue
        try:register(store,directory,{'id':path.name,'kind':media.validate_file(path)})
        except (ValueError,OSError):continue

def catalog(store):
    result=[]
    for r in store.rows('SELECT * FROM media_catalog ORDER BY pool,name'):
        r['analysis']=json.loads(r['analysis']);r.pop('scan_hash',None);result.append(r)
    return result

def assign(store,directory,ids,category):
    pool(category)
    if not isinstance(ids,list) or not 1<=len(ids)<=100:raise ValueError('Chọn từ 1 đến 100 tệp.')
    for name in ids:media.resolve([name],directory)
    with store.db() as c:c.executemany('UPDATE media_catalog SET pool=? WHERE id=? AND archived=0',[(category,n) for n in ids])

def group_pools(store,gid,values):
    if not isinstance(values,list):raise ValueError('Danh sách kho không hợp lệ.')
    values=list(dict.fromkeys('ALL' if v=='ALL' else pool(v) for v in values))
    if not store.rows('SELECT id FROM groups WHERE id=? AND deleted=0',(gid,)):raise ValueError('Không tìm thấy nhóm.')
    with store.db() as c:
        c.execute('DELETE FROM group_media_pools WHERE group_id=?',(gid,))
        c.executemany('INSERT INTO group_media_pools VALUES(?,?)',[(gid,v) for v in values])

def fingerprint(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def scan(store,directory,name):
    raise ValueError('Đã bỏ quét AI. Chỉ cần gán ảnh/video vào kho game rồi chọn random.')


def eligible_media(store,directory,allowed,kind=None):
    selected=[]
    for r in store.rows('SELECT * FROM media_catalog WHERE archived=0'):
        if r['pool'] not in allowed or (kind and r['kind']!=kind):continue
        try:
            path=Path(media.paths(media.resolve([r['id']],directory))[0])
            actual=media.validate_file(path)
            if actual!=r['kind'] or path.stat().st_size>(media.MAX_UPLOAD if actual=='video' else media.MAX_IMAGE_UPLOAD):continue
        except (ValueError,OSError):continue
        # Category is user supplied. No scan, model, image upload, or visual claims.
        selected.append((r,{'game':r['pool'],'kind':actual,'source':'user_assigned'}))
    return selected


def eligible_images(store,directory,allowed):
    return eligible_media(store,directory,allowed,'image')


def pick_images(selected,count=1,max_count=None):
    if type(count) is not int or not 1<=count<=10:raise ValueError('Số ảnh từ 1 đến 10.')
    if max_count is not None and (type(max_count) is not int or not count<=max_count<=10):raise ValueError('Khoảng số ảnh không hợp lệ.')
    if len(selected)<count:raise ValueError('Kho chưa đủ ảnh đã phân loại. Thêm ảnh vào đúng kho game; không tự đăng bài chỉ có chữ.')
    total=random.SystemRandom().randint(count,min(max_count,len(selected))) if max_count is not None else count
    random.shuffle(selected);selected.sort(key=lambda x:x[0]['last_used'])
    return selected[:total]

def choose(store,directory,gid,count=1,max_count=None):
    allowed={r['pool'] for r in store.rows('SELECT pool FROM group_media_pools WHERE group_id=?',(gid,))}
    if 'ALL' in allowed:allowed=set(POOLS)
    if not allowed:raise ValueError('Nhóm chưa được gán kho ảnh game.')
    return pick_images(eligible_images(store,directory,allowed),count,max_count)

def choose_pool(store,directory,category,count=1,max_count=3):
    if str(category).strip().upper()=='ALL':
        return pick_media(eligible_images(store,directory,set(POOLS)),count,max_count)
    name=next((p for p in POOLS if p.casefold()==str(category).strip().casefold()),None)
    if name is None:raise ValueError('Chọn kho ảnh game cụ thể cho lần AI tạo bài: '+', '.join(POOLS)+'.')
    return pick_images(eligible_images(store,directory,{name}),count,max_count)


def pick_media(selected,count=1,max_count=3):
    if not selected:raise ValueError('Kho chưa có ảnh/video đã phân loại hợp lệ.')
    games=sorted({r['pool'] for r,a in selected})
    game=random.SystemRandom().choice(games) if len(games)>1 else games[0]
    selected=[item for item in selected if item[0]['pool']==game]
    kinds=sorted({r['kind'] for r,a in selected})
    kind=random.SystemRandom().choice(kinds) if len(kinds)>1 else kinds[0]
    choices=[item for item in selected if item[0]['kind']==kind]
    if kind=='video':
        random.shuffle(choices);choices.sort(key=lambda x:x[0]['last_used'])
        return choices[:1]
    return pick_images(choices,count,max_count)


def choose_media(store,directory,gid,count=1,max_count=3,mixed_games=False):
    groups=store.rows('SELECT category FROM groups WHERE id=?',(gid,))
    if groups and groups[0]['category'].strip().upper()=='ALL':
        return pick_media(eligible_images(store,directory,set(POOLS)),count,max_count)
    game=next((p for p in POOLS if groups and p.casefold()==groups[0]['category'].strip().casefold()),None)
    if not game:raise ValueError('Nhóm chưa có phân loại game hợp lệ; không lấy ảnh/video game khác.')
    allowed={game}
    return pick_media(eligible_media(store,directory,allowed),count,max_count)


def choose_media_pool(store,directory,category,count=1,max_count=3):
    if str(category).strip().upper()=='ALL':
        return pick_media(eligible_images(store,directory,set(POOLS)),count,max_count)
    if category=='__all__':allowed=set(POOLS)
    else:
        name=next((p for p in POOLS if p.casefold()==str(category).strip().casefold()),None)
        if not name:raise ValueError('Chọn kho game hoặc Trộn tất cả game.')
        allowed={name}
    return pick_media(eligible_media(store,directory,allowed),count,max_count)


def mark_used(store,ids):
    with store.db() as c:c.executemany("UPDATE media_catalog SET last_used=? WHERE id=? OR scan_hash=(SELECT scan_hash FROM media_catalog WHERE id=? AND scan_hash<>'')",[(time.time(),n,n) for n in ids])


def archive(store,ids,restore=False):
    """Remove from future automatic selection; retain original files and post history."""
    if not isinstance(ids,list) or not 1<=len(ids)<=100 or not all(isinstance(n,str) and Path(n).name==n for n in ids):
        raise ValueError('Chọn từ 1 đến 100 tệp trong kho.')
    ids=list(dict.fromkeys(ids))
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE')
        for name in ids:
            if not c.execute('SELECT 1 FROM media_catalog WHERE id=?',(name,)).fetchone():raise ValueError('Không tìm thấy tệp trong kho.')
        c.executemany('UPDATE media_catalog SET archived=? WHERE id=?',[(0 if restore else 1,n) for n in ids])
    return len(ids)


def resolve_for_save(store,directory,obj):
    mode=obj.get('image_mode','manual')
    if mode not in {'auto','manual'}:raise ValueError('Chọn tự lấy ảnh từ kho hoặc tệp thủ công.')
    ids=obj.get('media_ids',[]);alt_ids=obj.get('no_link_media_ids',[])
    if mode=='auto' and not ids:
        category=str(obj.get('category','Chung')).strip();source=str(obj.get('image_pool','')).strip() or category
        if source!='__all__' and category.casefold() in {p.casefold() for p in POOLS} and source.casefold()!=category.casefold():raise ValueError('Kho ảnh phải cùng game với phân loại bài.')
        # Saving existing prose must keep its declared game; only AI creation can
        # select another game before writing new text.
        if source=='__all__' and category in POOLS:source=category
        selected=choose_media_pool(store,directory,source,1,3)
        files=media.resolve([r['id'] for r,a in selected],directory)
        return files,media.resolve(alt_ids,directory) if alt_ids else files,selected
    return media.resolve(ids,directory),media.resolve(alt_ids,directory),[]
