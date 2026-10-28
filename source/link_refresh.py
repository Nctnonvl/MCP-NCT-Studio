"""Durable, explicitly requested updates of verified Facebook posts from the last 36h."""
import hashlib
import json
import time

WINDOW = 36 * 3600


def busy(c):
    return c.execute("SELECT 1 FROM link_refresh WHERE state IN ('queued','working') LIMIT 1").fetchone() is not None


def candidates(c, old, new):
    from store import replace_link, urls
    from receipts import post_url
    found = []
    for row in c.execute("SELECT j.*,g.comment_links FROM jobs j JOIN groups g ON g.id=j.group_id WHERE j.state='submitted' AND g.deleted=0 AND CASE WHEN j.attempted_at>0 THEN j.attempted_at ELSE j.updated END>=? ORDER BY j.id", (time.time()-WINDOW,)):
        item = dict(row)
        groups = [item['url']] + [r[0] for r in c.execute('SELECT alias FROM group_aliases WHERE group_id=?', (item['group_id'],))]
        if not any(post_url(item['post_url'], g) for g in groups):
            continue
        # Historical job text stays immutable. Carry forward only a confirmed edit.
        prior = c.execute("SELECT * FROM link_refresh WHERE job_id=? AND edit_state='saved' ORDER BY id DESC LIMIT 1", (item['id'],)).fetchone()
        if prior:
            item['body'] = prior['body_after']
        comment = c.execute("SELECT new_url FROM link_refresh WHERE job_id=? AND comment_state='sent' ORDER BY id DESC LIMIT 1", (item['id'],)).fetchone()
        item['comment_text'] = comment[0] if comment else item['comment_text']
        after = replace_link(item['body'], old, new)
        if len(after)>5000:raise ValueError(f"Bài Facebook lượt #{item['id']} sẽ vượt 5000 ký tự sau khi thay link.")
        if after == item['body'] and old not in urls(item['comment_text']):
            continue
        key = hashlib.sha256(json.dumps([item['id'], item['body'], item['comment_text'], old, new], ensure_ascii=False).encode()).hexdigest()
        # An interrupted send/edit must be reviewed, never silently repeated.
        if c.execute('SELECT 1 FROM link_refresh WHERE operation_key=?', (key,)).fetchone():
            continue
        item.update(body_after=after, operation_key=key, comment_allowed=item['comment_links'] != 'deny')
        found.append(item)
    return found


def enqueue(c, batch, items, old, new):
    now = time.time()
    for item in items:
        c.execute('INSERT INTO link_refresh(batch_id,job_id,old_url,new_url,body_before,body_after,comment_before,created,updated,operation_key) VALUES(?,?,?,?,?,?,?,?,?,?)',
                  (batch,item['id'],old,new,item['body'],item['body_after'],item['comment_text'],now,now,item['operation_key']))


def claim(store):
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE')
        from approval_followup import busy as approval_busy
        if approval_busy(c):return None
        if c.execute("SELECT 1 FROM jobs WHERE state='working'").fetchone():return None
        if c.execute("SELECT 1 FROM link_refresh WHERE state='working'").fetchone():return None
        scan=c.execute("SELECT v FROM kv WHERE k='group_scan'").fetchone()
        if scan and json.loads(scan[0]).get('status')=='running':return None
        row=c.execute("SELECT * FROM link_refresh WHERE state='queued' ORDER BY id LIMIT 1").fetchone()
        if not row:return None
        source=c.execute('SELECT j.*,g.comment_links FROM jobs j JOIN groups g ON g.id=j.group_id WHERE j.id=?', (row['job_id'],)).fetchone()
        if not source or source['state']!='submitted' or (source['attempted_at'] or source['updated'])<time.time()-WINDOW:
            c.execute("UPDATE link_refresh SET state='skipped',detail='Không còn lượt nguồn.' WHERE id=?",(row['id'],));return None
        c.execute("UPDATE link_refresh SET state='working',updated=? WHERE id=?",(time.time(),row['id']))
        return {**dict(source),'id':'refresh-'+str(row['id']),'refresh_id':row['id'],'body':row['body_before'],'body_after':row['body_after'],'new_url':row['new_url'],'task':'refresh_links','media':''}


def checkpoint(store, rid, **fields):
    allowed={'state','edit_state','comment_state','detail'}
    if not fields or not set(fields)<=allowed:raise ValueError('Invalid refresh checkpoint')
    with store.db() as c:
        c.execute('UPDATE link_refresh SET '+','.join(k+'=?' for k in fields)+',updated=? WHERE id=?',(*fields.values(),time.time(),rid))


def stop(store):
    with store.db() as c:
        c.execute("UPDATE link_refresh SET state='cancelled',detail='Người dùng dừng đợt cập nhật.',updated=? WHERE state='queued'",(time.time(),))


def recover(store):
    with store.db() as c:
        c.execute("UPDATE link_refresh SET state='uncertain',detail='Ứng dụng đóng giữa lượt cập nhật. Kiểm tra Facebook; không tự lặp.',updated=? WHERE state='working'",(time.time(),))
        c.execute("UPDATE link_refresh SET state='cancelled',detail='Ứng dụng đã đóng. Xem ảnh hưởng lại để cập nhật tiếp.',updated=? WHERE state='queued'",(time.time(),))


def status(store):
    return store.rows('SELECT r.*,j.group_name,j.post_url FROM link_refresh r JOIN jobs j ON j.id=r.job_id ORDER BY r.id DESC LIMIT 40')
