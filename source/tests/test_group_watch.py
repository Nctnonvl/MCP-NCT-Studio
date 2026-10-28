import tempfile,unittest
from pathlib import Path
from store import Store

class GroupWatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.s=Store(Path(self.tmp.name)/'db')
        self.gid=self.s.add_group('facebook.com/groups/watch','Watch')
    def tearDown(self):self.tmp.cleanup()
    def job(self,state='pending',moderation='',detail=''):
        with self.s.db() as c:
            return c.execute("INSERT INTO jobs(group_id,group_name,url,body,media,due,state,moderation_status,detail,created,updated) VALUES(?,?,?,?,?,0,?,?,?,0,0)",(self.gid,'Watch','https://facebook.com/groups/watch/','body','',state,moderation,detail)).lastrowid
    def test_threshold_and_removed_declined_count_once(self):
        for _ in range(5):self.job()
        self.assertEqual(self.s.group_watchlist(),[])
        jid=self.job('error','removed')
        row=self.s.group_watchlist()[0]
        self.assertEqual((row['total'],row['pending'],row['removed']),(6,5,1))
        self.assertEqual(self.s.group_watchlist()[0]['total'],6)
        self.job('error','declined');self.assertEqual(self.s.group_watchlist()[0]['declined'],1)
        with self.s.db() as c:c.execute("UPDATE jobs SET state='submitted',moderation_status='submitted' WHERE id=?",(jid,))
        self.assertEqual(self.s.group_watchlist()[0]['total'],6)
    def test_uncertain_comment_failure_control_and_success_not_group_failure(self):
        self.job('uncertain');self.job('submitted','submitted');self.job('error',detail='CONTROL_PREEMPTED')
        for _ in range(5):self.job('error')
        self.assertEqual(self.s.group_watchlist(),[])
        self.job('error');self.assertEqual(self.s.group_watchlist()[0]['failed'],6)
    def test_keep_resets_window_and_delete_removes_group_from_tool(self):
        for _ in range(6):self.job()
        self.s.decide_group_watch(self.gid,'keep');self.assertEqual(self.s.group_watchlist(),[])
        for _ in range(6):self.job('error','removed')
        self.assertEqual(self.s.group_watchlist()[0]['total'],6)
        self.s.decide_group_watch(self.gid,'delete');self.assertEqual(self.s.group_watchlist(),[])
        self.assertEqual(self.s.rows('SELECT deleted FROM groups')[0]['deleted'],1)

    def test_keep_still_counts_preexisting_queue_when_it_later_fails(self):
        queued=self.job('queued')
        for _ in range(6):self.job()
        self.s.decide_group_watch(self.gid,'keep')
        with self.s.db() as c:c.execute("UPDATE jobs SET state='error' WHERE id=?",(queued,))
        for _ in range(5):self.job('error')
        self.assertEqual(self.s.group_watchlist()[0]['total'],6)
