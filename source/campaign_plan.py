"""Finite campaign planning. Preview is read-only; no AI or browser calls."""
import datetime as dt
import hashlib
import time
import media_library
import content_ai
from queue_recovery import VN,day,next_day
from store import interval_bounds,post_variant,sample_gap

def preview(store,directory,obj,now=None):
    now=time.time() if now is None else now
    total=int(obj.get('total_posts',5));days=int(obj.get('horizon',3))
    cap=min(int(obj.get('groups_per_day',10)),int(store.get('daily_group_limit',20)))
    if not 1<=total<=90 or not 1<=days<=7 or not 1<=cap<=30:
        raise ValueError('Chọn 1–90 bài, 1–7 ngày và 1–30 nhóm/ngày.')
    bounds=interval_bounds(obj.get('minutes','30-60'))
    gap=bounds[1]*60
    mode=obj.get('selection_mode','auto')
    identity_mode=obj.get('identity_mode','group')
    if identity_mode not in {'group','auto'}:raise ValueError('Chọn danh tính theo nhóm hoặc tự chọn.')
    if mode not in {'auto','manual'}:raise ValueError('Chọn tự chọn nhóm hoặc nhóm đã tick.')
    selected={int(v) for v in obj.get('ids',[])}
    groups=store.rows('SELECT * FROM groups WHERE enabled=1 AND deleted=0')
    coverage_once=obj.get('coverage_once') is True
    if coverage_once:
        groups=[g for g in groups if mode!='manual' or g['id'] in selected]
        total=len(groups)
        if total>90:raise ValueError('Mỗi chiến dịch phủ tối đa 90 nhóm; chia thành nhiều chiến dịch.')
    available=[];excluded=[]
    for g in groups:
        if mode=='manual' and g['id'] not in selected:continue
        reason=''
        if g['link_policy'] not in {'allow','deny'}:reason='Chưa rõ quyền link'
        elif store.rows("SELECT id FROM jobs WHERE group_id=? AND state IN ('draft','queued','working') LIMIT 1",(g['id'],)):reason='Đang có lịch'
        else:
            try:media_library.choose_media(store,directory,g['id'])
            except ValueError as exc:reason=str(exc)
        if reason:excluded.append({'id':g['id'],'name':g['name'],'reason':reason});continue
        history=store.rows("SELECT MAX(CASE WHEN attempted_at>0 THEN attempted_at ELSE updated END) AS at FROM jobs WHERE group_id=? AND calendar_released=0 AND (attempted_at>0 OR state IN ('submitted','pending','uncertain'))",(g['id'],))
        g['last']=history[0]['at'] or 0;available.append(g)
    used={};occupied={}
    for row in store.rows("SELECT group_id,CASE WHEN attempted_at>0 THEN attempted_at ELSE updated END AS at FROM jobs WHERE calendar_released=0 AND (attempted_at>0 OR state IN ('working','submitted','pending','uncertain'))"):
        used.setdefault(day(row['at']),set()).add(row['group_id'])
    cursor=max(now,float(store.get('next_allowed',0)));end=dt.datetime.combine(day(now)+dt.timedelta(days=days),dt.time(),VN).timestamp()
    next_slot={g['id']:g['next_post_after'] for g in available};last={g['id']:g['last'] for g in available}
    cfg=content_ai.config(store);remaining=None
    if cfg['writer_provider']=='xkiro':
        used_calls=store.rows("SELECT COUNT(*) AS n FROM content_ai_calls WHERE provider='xkiro' AND date(at,'unixepoch','+7 hours')=date(?,'unixepoch','+7 hours')",(now,))[0]['n']
        remaining=max(0,int(cfg['daily_calls'])-used_calls)
    target=total if remaining is None else min(total,remaining)
    items=[];planned=set()
    while len(items)<target and cursor<end:
        date=day(cursor);taken=used.setdefault(date,set())|occupied.setdefault(date,set())
        choices=[g for g in available if g['id'] not in taken and (not coverage_once or g['id'] not in planned) and next_slot[g['id']]<=cursor]
        if len(taken)>=cap:cursor=next_day(cursor);continue
        if not choices:
            future=[next_slot[g['id']] for g in available if g['id'] not in taken and (not coverage_once or g['id'] not in planned) and cursor<next_slot[g['id']]<next_day(cursor)]
            cursor=min(future) if future else next_day(cursor);continue
        # Oldest first; stable shuffled ties make preview and execution agree.
        g=min(choices,key=lambda g:(last[g['id']],hashlib.sha256(f"{date}:{g['id']}".encode()).hexdigest()))
        item_gap=sample_gap(bounds)
        items.append({'group_id':g['id'],'name':g['name'],'category':g['category'],'due':cursor,'day':str(date),'gap_seconds':item_gap})
        planned.add(g['id'])
        occupied[date].add(g['id']);last[g['id']]=cursor;next_slot[g['id']]=cursor+86400;cursor+=item_gap
    reasons={g['id']:g['reason'] for g in excluded}
    uncovered=[{'id':g['id'],'name':g['name'],'reason':reasons.get(g['id'],'Chưa đủ thời gian, hạn mức AI hoặc lượt trống trong khoảng đã chọn')} for g in groups if (mode!='manual' or g['id'] in selected) and g['id'] not in planned]
    return {'coverage_once':coverage_once,'uncovered_groups':uncovered,'requested':total,'estimated_posts':len(items),'eligible_groups':len(available),'unique_groups':len({i['group_id'] for i in items}),
            'identity_mode':identity_mode,'groups_per_day':cap,'horizon':days,'gap_seconds':gap,'gap_min_seconds':interval_bounds(obj.get('minutes','30-60'))[0]*60,'ai_calls_remaining':remaining,'api_calls_min':len(items),'api_calls_max':remaining,'rewrite_until_valid':True,'items':items,'excluded':excluded,
            'note':'Mỗi bài tạo một lần, đăng một lần. Ước tính có thể giảm nếu AI lỗi; chưa gọi AI và chưa đăng.'}

def schedule(store,plan,results):
    """Freeze one successful draft to its planned group, atomically; never repeat it."""
    ids=[];now=time.time();by_index={r['item'][1]:r['result'] for r in results}
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE')
        for index,item in enumerate(plan['items']):
            if index not in by_index:continue
            gid=item['group_id'];cid=by_index[index]
            g=c.execute('SELECT * FROM groups WHERE id=?',(gid,)).fetchone()
            p=c.execute('SELECT * FROM contents WHERE id=?',(cid,)).fetchone()
            if not g or not p or not store._eligible(c,p,g,'random'):raise ValueError('Nhóm hoặc bài đã thay đổi; giữ bản nháp, hãy xem lại.')
            if c.execute("SELECT 1 FROM jobs WHERE group_id=? AND state IN ('draft','queued','working')",(gid,)).fetchone() and gid not in {x[0] for x in ids}:
                raise ValueError('Nhóm vừa có lịch khác; giữ bản nháp, không tạo chồng lịch.')
            body,media=post_variant(p,g['link_policy'],g['category'])
            if c.execute("SELECT 1 FROM jobs WHERE group_id=? AND body=? AND media=? AND calendar_released=0 AND state='uncertain' LIMIT 1",(gid,body,media)).fetchone():
                raise ValueError('Nội dung này có lượt chưa rõ kết quả trong nhóm. Giữ bản nháp, không tự gửi lại.')
            jid=c.execute('INSERT INTO jobs(group_id,group_name,url,body,media,due,created,updated,gap_seconds,group_gap_seconds,content_id,routing_mode,campaign_daily_limit) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (gid,g['name'],g['url'],body,media,item['due'],now,now,item.get('gap_seconds',plan['gap_seconds']),86400,cid,'random',plan['groups_per_day'])).lastrowid
            store._freeze_comments(c,jid,cid,gid,plan.get('gap_min_seconds',plan['gap_seconds']));ids.append((gid,jid))
            if plan.get('identity_mode')=='auto' and g['posting_identity']=='default':
                c.execute("UPDATE jobs SET posting_identity='auto' WHERE id=?",(jid,))
    return [jid for gid,jid in ids]
