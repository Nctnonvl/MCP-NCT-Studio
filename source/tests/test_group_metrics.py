import tempfile,time,unittest
from pathlib import Path
from store import Store
from group_metrics import statistics

class GroupMetricsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.s=Store(Path(self.tmp.name)/'db');self.now=time.time()
        self.a=self.s.add_group('facebook.com/groups/a','A');self.b=self.s.add_group('facebook.com/groups/b','B')
    def tearDown(self):self.tmp.cleanup()
    def job(self,gid,state,moderation='',detail='',age=0):
        with self.s.db() as c:
            return c.execute("INSERT INTO jobs(group_id,group_name,url,body,media,due,state,moderation_status,detail,created,updated) VALUES(?,'Group','https://facebook.com/groups/a/','body','',?,?,?,?,?,?)",(gid,self.now,state,moderation,detail,self.now-age,self.now)).lastrowid
    def test_groups_rates_and_windows_are_separate(self):
        self.job(self.a,'submitted');self.job(self.a,'pending');self.job(self.a,'error','removed');self.job(self.a,'error','declined')
        self.job(self.a,'uncertain');self.job(self.a,'queued');self.job(self.a,'error',detail='CONTROL_PREEMPTED')
        self.job(self.b,'submitted',age=10*86400)
        data=statistics(self.s,self.now);a,b=data['30']
        self.assertEqual((a['total'],a['published'],a['pending'],a['removed'],a['declined'],a['uncertain'],a['technical'],a['queued']),(5,1,1,1,1,1,1,1))
        self.assertEqual(a['success_rate'],20);self.assertEqual(b['success_rate'],100)
        self.assertIsNone(data['7'][1]['success_rate'])
        self.assertEqual(data['all'][1]['published'],1)
    def test_pending_recheck_and_later_approval_count_once(self):
        jid=self.job(self.a,'working')
        with self.s.db() as c:c.execute("INSERT INTO approval_checks(job_id,post_url,state,due,created,updated,profile_revision,checks,previous_state) VALUES(?,'','working',0,0,0,'',100,'pending')",(jid,))
        self.assertEqual(statistics(self.s,self.now)['30'][0]['pending'],1)
        with self.s.db() as c:c.execute("UPDATE jobs SET state='submitted',comment_status='failed' WHERE id=?",(jid,))
        row=statistics(self.s,self.now)['30'][0]
        self.assertEqual((row['published'],row['pending'],row['success_rate']),(1,0,100))
    def test_empty_cancelled_and_deleted_groups(self):
        self.job(self.a,'cancelled');self.job(self.a,'prepared');self.s.delete_group(self.b)
        rows=statistics(self.s,self.now)['30'];self.assertEqual(len(rows),1);self.assertEqual(rows[0]['total'],0);self.assertIsNone(rows[0]['success_rate'])

    def test_reset_keeps_published_and_history_but_counts_new_outcomes(self):
        from group_metrics import reset_nonpublished
        self.job(self.a,'submitted')
        pending=self.job(self.a,'pending');self.job(self.a,'error');self.job(self.b,'uncertain')
        before=self.s.rows('SELECT * FROM jobs ORDER BY id')
        reset_nonpublished(self.s)
        self.assertEqual(self.s.rows('SELECT * FROM jobs ORDER BY id'),before)
        rows=statistics(self.s,self.now)['30']
        self.assertEqual((rows[0]['published'],rows[0]['pending'],rows[0]['failed'],rows[1]['uncertain']),(1,0,0,0))
        self.job(self.a,'pending');self.assertEqual(statistics(self.s,self.now)['30'][0]['pending'],1)
        with self.s.db() as c:c.execute("UPDATE jobs SET state='submitted' WHERE id=?",(pending,))
        self.assertEqual(statistics(self.s,self.now)['30'][0]['published'],2)
