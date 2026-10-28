"""Calendar holds and explicit operator releases, independent of Facebook state."""
import hashlib,json
from queue_recovery import day,next_day


def revision(group,jobs):
    evidence=[(j['id'],j['state'],j['updated'],j['due'],j['attempted_at'],j['post_attempted']) for j in jobs]
    return hashlib.sha256(json.dumps([group['id'],group['next_post_after'],evidence]).encode()).hexdigest()[:20]


def summaries(c,now):
    settings={r['k']:json.loads(r['v']) for r in c.execute("SELECT k,v FROM kv WHERE k IN ('next_allowed','failure_cooldown_until','daily_group_limit')")}
    global_due=max(settings.get('next_allowed',0),settings.get('failure_cooldown_until',0))
    cap=max(1,min(30,int(settings.get('daily_group_limit',20))))
    jobs=list(c.execute('SELECT * FROM jobs WHERE calendar_released=0 ORDER BY id'))
    attempted_today={j['group_id'] for j in jobs if (j['attempted_at']>0 or j['state'] in {'working','submitted','pending','uncertain'}) and day(j['attempted_at'] or j['updated'])==day(now)}
    result={}
    for group in c.execute('SELECT * FROM groups WHERE deleted=0'):
        own=[j for j in jobs if j['group_id']==group['id']]
        active=[j for j in own if j['state'] in {'draft','queued','working'}]
        job_cap=min([cap]+[j['campaign_daily_limit'] for j in active if j['campaign_daily_limit']>0])
        history=[j for j in own if j['attempted_at']>0 or j['state'] in {'submitted','pending','uncertain'}]
        last=max(history,key=lambda j:j['attempted_at'] or j['updated']) if history else None
        occupied=any(j['state'] in {'working','submitted','pending','uncertain'} and day(j['updated'])==day(now) for j in own)
        group_due=max(group['next_post_after'],next_day(now) if occupied else 0)
        ready=max(group_due,global_due,next_day(now) if len(attempted_today)>=job_cap else 0)
        reservation=min((j['due'] for j in active),default=0)
        ready=max(ready,reservation)
        reasons=[]
        if active:reasons.append('Đang thao tác' if any(j['state']=='working' for j in active) else f"Có {len(active)} lịch chờ")
        if group_due>now:reasons.append('Đang nghỉ giữa hai lần đăng của nhóm')
        if global_due>now:reasons.append('Đang nghỉ giữa các lượt')
        if len(attempted_today)>=job_cap:reasons.append('Đã đủ trần nhóm hôm nay')
        if not group['enabled']:reasons.append('Nhóm đang tắt')
        result[group['id']]={'revision':revision(group,own),'available_at':ready if ready>now else 0,'group_ready_at':group_due if group_due>now else 0,
            'reservation_at':min((j['due'] for j in active),default=0),'reservations':[{'id':j['id'],'content_id':j['content_id'],'state':j['state'],'due':j['due']} for j in active],
            'last_attempt_at':(last['attempted_at'] or last['updated']) if last else 0,'last_state':last['state'] if last else '',
            'last_job_id':last['id'] if last else 0,'reasons':reasons,'working':any(j['state']=='working' for j in active)}
    return result
