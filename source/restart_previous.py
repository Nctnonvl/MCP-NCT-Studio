"""Stop only an idle, verified controller from this project before startup."""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import sys
import time

import psutil


def matches_script(process, root, script):
    try:
        if process.name().lower() not in {'python.exe','pythonw.exe','py.exe'}:return False
        args=process.cmdline()[1:]
        cwd=Path(process.cwd()).resolve()
        expected=Path(root).resolve()/script
        return any((Path(arg) if Path(arg).is_absolute() else cwd/arg).resolve()==expected
                   for arg in args if Path(arg).name==script)
    except (psutil.Error,OSError,ValueError):
        return False


def pause_idle_controller(data):
    database=Path(data)/'manager.sqlite3'
    if not database.is_file():return
    with closing(sqlite3.connect(database.as_uri()+'?mode=rw',uri=True,timeout=5)) as connection,connection:
        connection.execute('BEGIN IMMEDIATE')
        work=connection.execute("SELECT id FROM jobs WHERE state='working' LIMIT 1").fetchone()
        raw=dict(connection.execute("SELECT k,v FROM kv WHERE k IN ('studio_task','ai_busy','control_revision','group_scan')"))
        task=json.loads(raw.get('studio_task','{}'))
        if json.loads(raw.get('group_scan','{}')).get('status')=='running':
            raise RuntimeError('Dang quet nhom Facebook. Bam Dung quet va cho ket thuc truoc khi khoi dong lai.')
        if connection.execute("SELECT 1 FROM sqlite_master WHERE name='link_refresh'").fetchone() and connection.execute("SELECT 1 FROM link_refresh WHERE state IN ('queued','working')").fetchone():
            raise RuntimeError('Dang cap nhat link Facebook. Dung cap nhat va cho worker ket thuc truoc khi khoi dong lai.')
        if work:
            raise RuntimeError(f'Luot #{work[0]} dang thao tac Facebook. Bam Tam dung, cho worker ket thuc, roi chay start.bat lai.')
        if task.get('status')=='running' or json.loads(raw.get('ai_busy','false')):
            raise RuntimeError('AI dang tao bai. Cho tac vu hoan tat roi chay start.bat lai.')
        # Commit while holding the same write lock as Store.claim(): no new job
        # can slip into the gap between this check and pausing the old scheduler.
        connection.execute("INSERT INTO kv VALUES('running','false') ON CONFLICT(k) DO UPDATE SET v=excluded.v")
        revision=int(json.loads(raw.get('control_revision','0')))+1
        connection.execute("INSERT INTO kv VALUES('control_revision',?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",(json.dumps(revision),))
        # paused_by_user is intentionally preserved. Startup recovery respects it.


def stop_previous(root, data):
    root=Path(root).resolve();data=Path(data).resolve()
    processes=list(psutil.process_iter())
    controllers=[p for p in processes if p.pid!=os.getpid() and matches_script(p,root,'app.py')]
    listeners={c.pid for c in psutil.net_connections(kind='tcp') if c.laddr.port==8765 and c.status=='LISTEN'}
    unknown=listeners-{p.pid for p in controllers}
    if unknown:
        raise RuntimeError('Cong 8765 do chuong trinh khac giu (PID '+', '.join(map(str,sorted(unknown)))+'). Khong tu tat tien trinh khong thuoc NCT_Group_Manager nay.')
    if any(matches_script(p,root,'desktop.py') for p in processes):
        raise RuntimeError('Worker Facebook van dang chay. Bam Tam dung va cho worker ket thuc truoc khi khoi dong lai.')
    if any(matches_script(p,root,'group_scan.py') for p in processes):
        raise RuntimeError('Bo quet Facebook van dang chay. Dung quet va cho ket thuc truoc khi khoi dong lai.')
    if not controllers:return []
    pause_idle_controller(data)
    identities=[(p,p.create_time()) for p in controllers]
    stopped=[]
    for process,created in identities:
        try:
            if process.create_time()!=created or not matches_script(process,root,'app.py'):
                raise RuntimeError('Nhan dien tien trinh da thay doi; da dung de tranh tat nham.')
            process.terminate()
            try:process.wait(timeout=10)
            except psutil.TimeoutExpired:
                if process.create_time()!=created:raise RuntimeError('PID da thay doi; khong tat tien trinh moi.')
                process.kill();process.wait(timeout=5)
            stopped.append(process.pid)
        except psutil.NoSuchProcess:pass
    deadline=time.monotonic()+5
    while any(c.laddr.port==8765 and c.status=='LISTEN' for c in psutil.net_connections(kind='tcp')):
        if time.monotonic()>=deadline:raise RuntimeError('Cong 8765 chua duoc giai phong; chua mo ban moi.')
        time.sleep(.1)
    return stopped


def main():
    root=Path(__file__).resolve().parent
    data=Path(os.environ.get('NCT_DATA_DIR',str(root/'data'))).resolve()
    try:
        stopped=stop_previous(root,data)
        print('Da dong NCT_Group_Manager cu: '+', '.join(map(str,stopped)) if stopped else 'Khong co ban NCT_Group_Manager cu dang chay.')
        return 0
    except (RuntimeError,psutil.Error,sqlite3.Error,OSError) as error:
        print('Chua khoi dong ban moi: '+str(error),file=sys.stderr)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
