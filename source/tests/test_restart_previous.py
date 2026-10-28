"""Fake processes only: verify startup never kills unrelated programs."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from store import Store
import restart_previous as restart


class FakeProcess:
    def __init__(self,pid,root,script='app.py',name='python.exe'):
        self.pid=pid;self.root=root;self.script=script;self.process_name=name;self.stopped=False
    def name(self):return self.process_name
    def cwd(self):return str(self.root)
    def cmdline(self):return ['python.exe',self.script]
    def create_time(self):return 123.0
    def terminate(self):self.stopped=True
    def wait(self,timeout):return 0


class RestartTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve()
        self.data=self.root/'data';self.data.mkdir();self.s=Store(self.data/'manager.sqlite3')
        self.old=FakeProcess(987650,self.root)

    def tearDown(self):self.tmp.cleanup()

    def listener(self,pid):return SimpleNamespace(pid=pid,laddr=SimpleNamespace(port=8765),status='LISTEN')

    def test_only_exact_project_python_controller_matches(self):
        self.assertTrue(restart.matches_script(self.old,self.root,'app.py'))
        self.assertFalse(restart.matches_script(FakeProcess(2,self.root/'other'),self.root,'app.py'))
        self.assertFalse(restart.matches_script(FakeProcess(3,self.root,'unrelated.py'),self.root,'app.py'))
        self.assertFalse(restart.matches_script(FakeProcess(4,self.root,name='chrome.exe'),self.root,'app.py'))

    def test_idle_controller_is_stopped_and_approved_jobs_are_preserved(self):
        gid=self.s.add_group('facebook.com/groups/restart',link_policy='allow');self.s.enable_group(gid,True)
        cid=self.s.content('Keep this approved post');ids=self.s.plan(cid,30);self.s.approve(ids);self.s.set('running',True)
        with patch.object(restart.psutil,'process_iter',return_value=[self.old]),patch.object(restart.psutil,'net_connections',side_effect=[[self.listener(self.old.pid)],[]]):
            self.assertEqual(restart.stop_previous(self.root,self.data),[self.old.pid])
        self.assertTrue(self.old.stopped);self.assertFalse(self.s.get('running'))
        self.assertEqual(self.s.rows('SELECT id,state,body FROM jobs'),[{'id':ids[0],'state':'queued','body':'Keep this approved post'}])

    def test_port_owned_by_other_program_is_never_killed(self):
        other=FakeProcess(77,self.root/'other')
        with patch.object(restart.psutil,'process_iter',return_value=[other]),patch.object(restart.psutil,'net_connections',return_value=[self.listener(other.pid)]):
            with self.assertRaisesRegex(RuntimeError,'chuong trinh khac'):restart.stop_previous(self.root,self.data)
        self.assertFalse(other.stopped)

    def test_worker_is_not_interrupted(self):
        worker=FakeProcess(88,self.root,'desktop.py')
        with patch.object(restart.psutil,'process_iter',return_value=[self.old,worker]),patch.object(restart.psutil,'net_connections',return_value=[self.listener(self.old.pid)]):
            with self.assertRaisesRegex(RuntimeError,'Worker Facebook'):restart.stop_previous(self.root,self.data)
        self.assertFalse(self.old.stopped);self.assertFalse(worker.stopped)

    def test_busy_database_blocks_restart_before_process_stop(self):
        self.s.set('studio_task',{'status':'running'})
        with patch.object(restart.psutil,'process_iter',return_value=[self.old]),patch.object(restart.psutil,'net_connections',return_value=[self.listener(self.old.pid)]):
            with self.assertRaisesRegex(RuntimeError,'AI dang'):restart.stop_previous(self.root,self.data)
        self.assertFalse(self.old.stopped)

    def test_working_job_blocks_restart_without_orphaning_a_post(self):
        gid=self.s.add_group('facebook.com/groups/restart',link_policy='allow');self.s.enable_group(gid,True)
        cid=self.s.content('Keep');ids=self.s.plan(cid,30)
        with self.s.db() as connection:connection.execute("UPDATE jobs SET state='working' WHERE id=?",(ids[0],))
        with self.assertRaisesRegex(RuntimeError,'dang thao tac'):restart.pause_idle_controller(self.data)
        self.assertEqual(self.s.rows('SELECT state FROM jobs')[0]['state'],'working')

    def test_no_old_controller_needs_no_database_changes(self):
        self.s.set('running',True)
        with patch.object(restart.psutil,'process_iter',return_value=[]),patch.object(restart.psutil,'net_connections',return_value=[]):
            self.assertEqual(restart.stop_previous(self.root,self.data),[])
        self.assertTrue(self.s.get('running'))

    def test_explicit_user_pause_is_preserved(self):
        self.s.set('paused_by_user',True);restart.pause_idle_controller(self.data)
        self.assertTrue(self.s.get('paused_by_user'))


if __name__=='__main__':unittest.main()
