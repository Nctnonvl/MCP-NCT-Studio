"""Operator queue actions. Preserve submission evidence and serialize schedules."""
import json,time


def _get(c,key,default):
    row=c.execute('SELECT v FROM kv WHERE k=?',(key,)).fetchone()
    return json.loads(row[0]) if row else default


def _idle(c):
    from approval_followup import busy as approvals_busy
    from link_refresh import busy as links_busy
    if c.execute("SELECT 1 FROM jobs WHERE state='working' LIMIT 1").fetchone() or approvals_busy(c) or links_busy(c) or _get(c,'group_scan',{}).get('status')=='running':
        raise ValueError('Có tác vụ đang thao tác Facebook. Chờ kết thúc rồi đổi lịch.')


def _valid(store,c,job):
    group=c.execute('SELECT * FROM groups WHERE id=?',(job['group_id'],)).fetchone()
    if not group or group['deleted'] or not group['enabled']:raise ValueError('Nhóm đang tắt hoặc đã xóa.')
    if job['account_id']!=group['account_id']:raise ValueError('Tài khoản nhóm đã đổi. Tạo lịch mới với đúng tài khoản.')
    if job['account_id']!='main' and not c.execute('SELECT 1 FROM facebook_accounts WHERE id=?',(job['account_id'],)).fetchone():raise ValueError('Tài khoản Facebook không còn tồn tại.')
    if job['prepare_only']:raise ValueError('Lượt này chỉ thử điền bài. Tạo lịch đăng thật trước.')
    post=c.execute('SELECT * FROM contents WHERE id=?',(job['content_id'],)).fetchone() if job['content_id'] else None
    if post is not None and not store._eligible(c,post,group,job['routing_mode']):raise ValueError('Bài không còn phù hợp với nhóm hoặc tài khoản. Tạo lịch mới.')
    from store import has_link
    if group['link_policy']=='unknown' or (group['link_policy']=='deny' and has_link(job['body'])):raise ValueError('Nội dung không phù hợp quy định link hiện tại của nhóm.')
    return group


def _reflow(c,now,priority=None):
    from queue_recovery import reflow
    evidence=c.execute("SELECT MAX(updated+CASE WHEN gap_seconds>0 THEN gap_seconds ELSE 3600 END) FROM jobs WHERE calendar_released=0 AND (state IN ('submitted','pending') OR (state='uncertain' AND post_attempted<>0))").fetchone()[0] or 0
    cooldown=max(_get(c,'next_allowed',0),_get(c,'failure_cooldown_until',0),evidence)
    cap=max(1,min(30,int(_get(c,'daily_group_limit',20))))
    if priority is None:return reflow(c,now,cooldown,cap)
    return reflow(c,now,cooldown,cap,compact=True,priority_jid=priority)


def restore(store,jid):
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE');_idle(c)
        source=c.execute('SELECT * FROM jobs WHERE id=?',(int(jid),)).fetchone()
        if not source or source['state']!='error' or source['post_attempted']!=0:raise ValueError('Chỉ khôi phục lượt lỗi đã xác định chưa gửi bài. Lượt chưa rõ kết quả cần kiểm tra trước.')
        group=_valid(store,c,source)
        existing=c.execute('SELECT * FROM jobs WHERE retry_of=? ORDER BY id DESC LIMIT 1',(source['id'],)).fetchone()
        if existing:
            if existing['state']=='queued' and existing['attempted_at']==0 and existing['post_attempted'] in (-1,0) and not existing['calendar_released']:
                return {'job_id':existing['id'],'due':existing['due'],'moved':0}
            raise ValueError('Lượt này đã được khôi phục. Kiểm tra lượt khôi phục gần nhất trước khi tiếp tục.')
        duplicate=c.execute("SELECT 1 FROM jobs WHERE group_id=? AND body=? AND media=? AND calendar_released=0 AND state IN ('draft','queued','working','submitted','pending','uncertain') LIMIT 1",(source['group_id'],source['body'],source['media'])).fetchone()
        if duplicate:raise ValueError('Đã có lượt cùng nội dung trong nhóm hoặc chưa rõ kết quả; không tạo lượt trùng.')
        now=time.time();job=dict(source);origin=job.pop('id')
        job.update(retry_of=origin,state='queued',calendar_released=0,hidden=0,created=now,updated=now,due=max(now,group['next_post_after']),original_due=0,attempted_at=0,post_attempted=0,post_url='',photo='',detail='',moderation_status='',comment_status='',safe_retries=0,schedule_note=f'Khôi phục từ lượt #{origin}; lượt cũ giữ nguyên bằng chứng.')
        job['gap_seconds']=max(60,job['gap_seconds'],job['gap_min_seconds'])
        new_id=c.execute(f"INSERT INTO jobs({','.join(job)}) VALUES({','.join('?' for _ in job)})",list(job.values())).lastrowid
        moved=_reflow(c,now)
        return {'job_id':new_id,'due':c.execute('SELECT due FROM jobs WHERE id=?',(new_id,)).fetchone()[0],'moved':moved}


def move_now(store,jid):
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE');_idle(c)
        job=c.execute('SELECT * FROM jobs WHERE id=?',(int(jid),)).fetchone()
        if not job or job['state']!='queued' or job['attempted_at']!=0 or job['post_attempted'] not in (-1,0) or job['calendar_released'] or job['hidden']:raise ValueError('Chỉ đưa lên đầu lịch đã duyệt và chưa thao tác.')
        _valid(store,c,job)
        now=time.time();moved=_reflow(c,now,job['id'])
        due=c.execute('SELECT due FROM jobs WHERE id=?',(job['id'],)).fetchone()[0]
        c.execute("UPDATE jobs SET schedule_note='Đã đưa lên đầu hàng đợi; giữ khoảng nghỉ và giới hạn nhóm.' WHERE id=?",(job['id'],))
        for key,value in [('running',True),('paused_by_user',False),('approval_monitor_enabled',True)]:
            c.execute('INSERT INTO kv VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v',(key,json.dumps(value)))
        return {'job_id':job['id'],'due':due,'moved':moved}
