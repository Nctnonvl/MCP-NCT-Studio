"""Reflow approved work after downtime without cloning or dropping a post."""
import datetime as dt

VN = dt.timezone(dt.timedelta(hours=7))

def day(timestamp):
    return dt.datetime.fromtimestamp(timestamp, VN).date()

def next_day(timestamp):
    return dt.datetime.combine(day(timestamp)+dt.timedelta(days=1), dt.time(), VN).timestamp()

def should_pause(result):
    if result.get('state')=='prepared':return True
    if result.get('state') not in {'error','uncertain'}:return False
    # Unknown acknowledgement after a possible submit must never accelerate the queue.
    if result.get('post_attempted') is not False:return True
    detail=str(result.get('detail','')).casefold()
    return any(s in detail for s in ('gặp cảnh báo hoặc yêu cầu xác minh','captcha','tài khoản bị hạn chế','temporarily blocked','người dùng yêu cầu dừng','quyền thao tác đã chuyển','mcp đang nhường','cửa sổ đang hoạt động đã đổi','windows đang khóa','control_preempted','user_control','takeover_pending','không kết nối được dịch vụ','không tìm thấy microsoft edge','không lấy được cửa sổ edge','windows mcp','không xác định được một cửa sổ edge'))


def hard_pause(result):
    """Operator/security stops cannot be resumed by the failure cooldown timer."""
    if result.get('state')=='prepared':return True
    detail=str(result.get('detail','')).casefold()
    return any(s in detail for s in ('gặp cảnh báo hoặc yêu cầu xác minh','captcha','tài khoản bị hạn chế','temporarily blocked','người dùng yêu cầu dừng','quyền thao tác đã chuyển','mcp đang nhường','cửa sổ đang hoạt động đã đổi','windows đang khóa','control_preempted','user_control','takeover_pending'))

def reflow(connection, now, next_allowed, cap,compact=False):
    jobs = connection.execute("SELECT j.*,g.next_post_after FROM jobs j JOIN groups g ON g.id=j.group_id WHERE j.state='queued' AND g.enabled=1 AND g.deleted=0 ORDER BY j.due,j.id").fetchall()
    if not jobs:
        return 0
    used = {}
    occupied = {}
    for row in connection.execute("SELECT group_id,state,CASE WHEN attempted_at>0 THEN attempted_at ELSE updated END AS at FROM jobs WHERE calendar_released=0 AND (attempted_at>0 OR state IN ('working','submitted','pending','uncertain'))"):
        used.setdefault(day(row['at']), set()).add(row['group_id'])
        if row['state'] in {'working','submitted','pending','uncertain'}:
            occupied.setdefault(day(row['at']),set()).add(row['group_id'])
    # A working post reserves both the global gap and its group's next slot.
    cursor = max(now, next_allowed)
    group_due = {}
    for row in connection.execute("SELECT group_id,updated,gap_seconds,group_gap_seconds FROM jobs WHERE state='working'"):
        cursor=max(cursor,now+max(60,row['gap_seconds']))
        group_due[row['group_id']]=now+max(86400,row['group_gap_seconds'])
    changed = 0
    for job in jobs:
        gid=job['group_id']
        job_cap=min(cap,job['campaign_daily_limit']) if 'campaign_daily_limit' in job.keys() and job['campaign_daily_limit'] else cap
        floor=dt.datetime.combine(day(job['due']),dt.time(),VN).timestamp() if compact else job['due']
        due=max(floor,cursor,job['next_post_after'],group_due.get(gid,0))
        # Keep both the daily attempted-group cap and one slot per group/day.
        while gid in occupied.get(day(due),set()) or len(used.get(day(due),set()))>=job_cap:
            due=next_day(due)
        if abs(due-job['due'])>1:
            original=job['original_due'] or job['due']
            note='Đã dồn lên sau lượt cần kiểm tra; giữ khoảng nghỉ và giới hạn ngày.' if compact else 'Đã dời lịch để giữ bài quá giờ và tránh chồng lượt.'
            connection.execute("UPDATE jobs SET due=?,original_due=?,schedule_note=? WHERE id=?",(due,original,note,job['id']))
            changed+=1
        used.setdefault(day(due),set()).add(gid)
        occupied.setdefault(day(due),set()).add(gid)
        group_due[gid]=due+max(86400,job['group_gap_seconds'])
        cursor=due+max(60,job['gap_seconds'])
    return changed
