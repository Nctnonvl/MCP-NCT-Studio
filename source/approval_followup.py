"""Durable, serial permalink checks; an approval check never submits a post."""
import hashlib,json,random,time
from pathlib import Path
from receipts import post_url,has_verified_post

def profile_revision(data,job=None):
    if job and job.get("browser_profile_json"):
        return hashlib.sha256(job["browser_profile_json"].encode("utf-8")).hexdigest()[:20]
    p=Path(data)/'browser-profile.json'
    raw=p.read_bytes() if p.exists() else b'private-edge'
    return hashlib.sha256(raw).hexdigest()[:20]

def busy(c,gid=None):
    sql="SELECT 1 FROM approval_checks a JOIN jobs j ON j.id=a.job_id WHERE a.state='working'"
    return bool(c.execute(sql+(' AND j.group_id=?' if gid is not None else '')+' LIMIT 1',(gid,) if gid is not None else ()).fetchone())

def enabled(store):
    return bool(store.get('approval_monitor_enabled',not store.get('paused_by_user',True)))

def enqueue(store,jid,result,data):
    if result.get('state')!='pending':return False
    with store.db() as c:
        job=c.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone()
        if not job or job['calendar_released'] or job['hidden']:return False
        link=post_url(result.get('post_url',''),job['url'])
        if result.get('post_url') and not link:return False
        if not link and (job['post_attempted']!=1 or len(job['body'].strip())<15):return False
        now=time.time()
        c.execute("INSERT OR IGNORE INTO approval_checks(job_id,post_url,state,due,created,updated,profile_revision) VALUES(?,?,'waiting',?,?,?,?)",(jid,link,now+random.randint(900,1800),now,now,profile_revision(data,dict(job))))
        return True

def claim(store,data):
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE')
        if not enabled(store):return None
        if busy(c) or c.execute("SELECT 1 FROM jobs WHERE state='working'").fetchone():return None
        if c.execute("SELECT 1 FROM link_refresh WHERE state IN ('queued','working')").fetchone():return None
        if store.get('group_scan',{}).get('status')=='running' or store.get('studio_task',{}).get('status')=='running':return None
        if store.get('running') and store.get('next_allowed',0)<=time.time() and c.execute("SELECT 1 FROM jobs j JOIN groups g ON g.id=j.group_id WHERE j.state='queued' AND j.due<=? AND g.enabled=1 AND g.deleted=0 AND g.next_post_after<=? LIMIT 1",(time.time(),time.time())).fetchone():return None
        rows=c.execute("SELECT a.*,j.group_id,j.state job_state,j.hidden,j.calendar_released,g.enabled,g.deleted,g.comment_links FROM approval_checks a JOIN jobs j ON j.id=a.job_id JOIN groups g ON g.id=j.group_id WHERE a.state='waiting' AND a.due<=? ORDER BY a.due,a.job_id",(time.time(),)).fetchall()
        for row in rows:
            if row['hidden'] or row['calendar_released'] or row['deleted'] or row['job_state'] not in {'pending','submitted'}:
                c.execute("UPDATE approval_checks SET state='cancelled',detail='Nhóm/lượt không còn cho phép theo dõi.' WHERE job_id=?",(row['job_id'],));continue
            frozen_job=dict(c.execute('SELECT * FROM jobs WHERE id=?',(row['job_id'],)).fetchone())
            if row['profile_revision']!=profile_revision(data,frozen_job) or time.time()-row['created']>7*86400:
                c.execute("UPDATE approval_checks SET state='review',detail='Hồ sơ đã đổi hoặc đã theo dõi quá 7 ngày; cần kiểm tra.' WHERE job_id=?",(row['job_id'],));continue
            c.execute("UPDATE approval_checks SET state='working',updated=?,checks=checks+1 WHERE job_id=?",(time.time(),row['job_id']))
            job=dict(c.execute('SELECT * FROM jobs WHERE id=?',(row['job_id'],)).fetchone())
            c.execute("UPDATE approval_checks SET previous_state=? WHERE job_id=?",(job['state'],row['job_id']))
            c.execute("UPDATE jobs SET state='working' WHERE id=?",(row['job_id'],))
            job.update(task='approval_check',post_url=row['post_url'])
            if row['comment_links']=='deny':job['comment_policy']='off'
            return job
        return None

def complete(store,job,result):
    """Keep the original post attempt; notify only on a meaningful final outcome."""
    now=time.time();state='waiting';notify=False
    with store.db() as c:
        old=c.execute('SELECT previous_state,state FROM approval_checks WHERE job_id=?',(job['id'],)).fetchone()
        if not old or old['state']!='working':return False
        c.execute("UPDATE jobs SET state=? WHERE id=? AND state='working'",(old['previous_state'] if old else 'pending',job['id']))
    if has_verified_post(result,job['url']):
        state='done' if result.get('comment_status') in {'sent','submitted','fallback_sent','skipped'} else 'review'
        notify=True
        with store.db() as c:
            # A comment/recheck is not a new posting attempt: retain timestamps.
            c.execute("UPDATE jobs SET state='submitted',detail=? WHERE id=?",(result.get('detail','Đã xác minh bài được duyệt.'),job['id']))
        store.record_result(job,result)
    elif result.get('state')=='error' and result.get('your_content_checked') and result.get('verification_source')=='your_content':
        state='review';notify=True
        with store.db() as c:c.execute("UPDATE jobs SET state='error',detail=? WHERE id=?",(result.get('detail','Bài bị từ chối trong nhóm.'),job['id']))
        store.record_result(job,result)
    elif result.get('state')=='pending' and result.get('moderation_checked'):
        link=post_url(result.get('post_url',''),job['url'])
        with store.db() as c:
            c.execute("UPDATE jobs SET moderation_status='pending' WHERE id=?",(job['id'],))
            if link:
                c.execute('UPDATE approval_checks SET post_url=? WHERE job_id=?',(link,job['id']))
                c.execute('UPDATE jobs SET post_url=? WHERE id=?',(link,job['id']))
    elif result.get('comment_status')=='uncertain' and result.get('comment_attempted'):
        state='review';notify=True
    detail=result.get('comment_detail','') if state=='review' and has_verified_post(result,job['url']) else result.get('detail','')
    with store.db() as c:
        c.execute('UPDATE approval_checks SET state=?,due=?,updated=?,detail=? WHERE job_id=?',(state,now+random.randint(900,1800),now,detail[:700],job['id']))
    return notify

def recover(store):
    with store.db() as c:
        c.execute("UPDATE jobs SET state=(SELECT previous_state FROM approval_checks WHERE job_id=jobs.id) WHERE state='working' AND id IN (SELECT job_id FROM approval_checks WHERE state='working')")
        c.execute("UPDATE approval_checks SET state='review',detail='Kiểm tra duyệt bị ngắt; không tự gửi lại bình luận.' WHERE state='working'")

def status(store):
    return store.rows("SELECT a.job_id,a.state,a.due,a.checks,a.detail,a.post_url,j.group_name,j.state job_state FROM approval_checks a JOIN jobs j ON j.id=a.job_id WHERE j.hidden=0 AND a.state IN ('waiting','working','review') ORDER BY a.due LIMIT 100")
