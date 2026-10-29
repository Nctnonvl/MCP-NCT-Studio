import tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from store import Store
from queue_actions import restore,move_now

class QueueActionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.s=Store(Path(self.tmp.name)/'test.db');self.now=time.time()
        self.g=self.s.add_group('facebook.com/groups/test-one',link_policy='allow');self.s.enable_group(self.g,True)
        self.cid=self.s.content('Frozen approved caption');self.j=self.s.plan(self.cid,'1',start=self.now+3600)[0];self.s.approve([self.j])
    def tearDown(self):self.tmp.cleanup()
    def job(self,jid):return self.s.rows('SELECT * FROM jobs WHERE id=?',(jid,))[0]
    def fail(self):self.s.finish(self.j,'error','Before sending',post_attempted=False)
    def test_restore_preserves_evidence_payload_and_is_idempotent(self):
        self.fail();before=self.job(self.j);result=restore(self.s,self.j);new=self.job(result['job_id'])
        self.assertEqual(before,self.job(self.j));self.assertEqual(new['retry_of'],self.j)
        for key in ['body','media','comment_text','account_id','browser_profile_json','posting_identity']:self.assertEqual(new[key],before[key])
        self.assertEqual(restore(self.s,self.j)['job_id'],new['id']);self.assertEqual(new['state'],'queued');self.assertEqual(new['attempted_at'],0)
    def test_restore_refuses_unknown_or_already_sent(self):
        for state,attempted in [('error',True),('uncertain',False),('pending',True),('submitted',True)]:
            self.s.finish(self.j,state,'evidence',post_attempted=attempted)
            with self.assertRaises(ValueError):restore(self.s,self.j)
        self.assertEqual(len(self.s.rows('SELECT id FROM jobs')),1)
    def test_restore_refuses_account_mismatch(self):
        self.fail()
        with self.s.db() as c:c.execute("UPDATE groups SET account_id='other' WHERE id=?",(self.g,))
        with self.assertRaises(ValueError):restore(self.s,self.j)
    def test_restore_respects_failure_cooldown(self):
        self.fail();self.s.set('failure_cooldown_until',self.now+5000)
        self.assertGreaterEqual(restore(self.s,self.j)['due'],self.now+5000)
    def test_move_to_front_reflows_later_jobs_and_starts_queue(self):
        g2=self.s.add_group('facebook.com/groups/test-two',link_policy='allow');self.s.enable_group(g2,True)
        with self.s.db() as c:
            row=dict(c.execute('SELECT * FROM jobs WHERE id=?',(self.j,)).fetchone());row.pop('id');row.update(group_id=g2,due=self.now+7200)
            j2=c.execute(f"INSERT INTO jobs({','.join(row)}) VALUES({','.join('?' for _ in row)})",list(row.values())).lastrowid
        with patch('queue_actions.time.time',return_value=self.now):r=move_now(self.s,j2)
        self.assertAlmostEqual(r['due'],self.now,delta=1);self.assertGreaterEqual(self.job(self.j)['due'],r['due']+self.job(j2)['gap_seconds'])
        self.assertTrue(self.s.get('running'));self.assertFalse(self.s.get('paused_by_user'))
    def test_move_respects_group_cooldown_and_rejects_attempted(self):
        with self.s.db() as c:c.execute('UPDATE groups SET next_post_after=? WHERE id=?',(self.now+9000,self.g))
        self.assertGreaterEqual(move_now(self.s,self.j)['due'],self.now+9000)
        with self.s.db() as c:c.execute('UPDATE jobs SET attempted_at=1 WHERE id=?',(self.j,))
        with self.assertRaises(ValueError):move_now(self.s,self.j)
    def test_busy_scan_blocks_changes_atomically(self):
        self.fail();self.s.set('group_scan',{'status':'running'})
        with self.assertRaises(ValueError):restore(self.s,self.j)
        self.assertEqual(len(self.s.rows('SELECT id FROM jobs')),1)
    def test_dry_run_cannot_be_converted_to_post(self):
        with self.s.db() as c:c.execute('UPDATE jobs SET prepare_only=1 WHERE id=?',(self.j,))
        with self.assertRaises(ValueError):move_now(self.s,self.j)

if __name__=='__main__':unittest.main()
