"""Per-group reporting from durable jobs; no Facebook calls or status inference."""
import json
import time

KINDS=('published','pending','failed','removed','declined','uncertain','technical')


def outcome(job):
    state=job['approval_previous'] if job['state']=='working' and job.get('approval_previous') else job['state']
    if state in {'queued','draft','prepared','cancelled','working'}:return None
    if job['moderation_status']=='removed':return 'removed'
    if job['moderation_status']=='declined':return 'declined'
    if state=='submitted':return 'published'
    if state=='pending':return 'pending'
    if state=='uncertain':return 'uncertain'
    if state=='error':
        if any(s in job['detail'] for s in ('CONTROL_PREEMPTED','Quyền thao tác đã chuyển','runtime revision','Mã nguồn đã thay đổi')):return 'technical'
        return 'failed'
    return None


def reset_nonpublished(store):
    """Reset reporting only; retain posting evidence, states and approval tracking."""
    with store.db() as connection:
        connection.execute('BEGIN IMMEDIATE')
        jobs=connection.execute('SELECT j.*,a.previous_state AS approval_previous FROM jobs j LEFT JOIN approval_checks a ON a.job_id=j.id').fetchall()
        ignored={}
        for row in jobs:
            job=dict(row);kind=outcome(job)
            if kind and kind!='published':ignored[str(job['id'])]=kind
        snapshot={'at':time.time(),'outcomes':ignored}
        connection.execute('INSERT INTO kv VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v',('group_metrics_reset',json.dumps(snapshot)))
    return snapshot


def statistics(store,now=None):
    now=time.time() if now is None else now
    groups=store.rows('SELECT id,name,url,category,enabled,next_post_after FROM groups WHERE deleted=0 ORDER BY id')
    jobs=store.rows('SELECT j.*,a.previous_state AS approval_previous FROM jobs j LEFT JOIN approval_checks a ON a.job_id=j.id JOIN groups g ON g.id=j.group_id WHERE g.deleted=0')
    ignored=store.get('group_metrics_reset',{}).get('outcomes',{})
    windows={}
    for window,seconds in [('7',7*86400),('30',30*86400),('all',None)]:
        rows={g['id']:{**g,**dict.fromkeys(KINDS,0),'queued':0,'drafts':0,'next_due':0,'last_outcome':'','last_at':0,'last_detail':'','last_post_url':''} for g in groups}
        for job in jobs:
            row=rows[job['group_id']]
            if job['state'] in {'queued','draft'}:
                row['queued' if job['state']=='queued' else 'drafts']+=1
                if job['state']=='queued':row['next_due']=min(row['next_due'] or job['due'],job['due'])
            at=job['attempted_at'] or job['created']
            if seconds and at<now-seconds:continue
            kind=outcome(job)
            if not kind or (kind!='published' and ignored.get(str(job['id']))==kind):continue
            row[kind]+=1
            if at>=row['last_at']:
                row.update(last_at=at,last_outcome=kind,last_detail=job['detail'][:400],last_post_url=job['post_url'])
        for row in rows.values():
            row['total']=sum(row[k] for k in KINDS if k!='technical')
            row['success_rate']=round(100*row['published']/row['total'],1) if row['total'] else None
        windows[window]=list(rows.values())
    return windows
