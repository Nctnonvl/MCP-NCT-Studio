import datetime as dt
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from store import Store, interval_bounds, has_link


class SchedulePolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.s = Store(Path(self.tmp.name)/'state.sqlite3')

    def tearDown(self):
        self.tmp.cleanup()

    def group(self, name, policy='allow'):
        gid = self.s.add_group('facebook.com/groups/'+name+'/', name, link_policy=policy)
        self.s.enable_group(gid, True)
        return gid

    def test_range_validation(self):
        self.assertEqual(interval_bounds('30-60'), (30,60))
        self.assertEqual(interval_bounds(60), (60,60))
        for x in ('60-30', '0-60', '-1', '30-x', '1-10081'):
            with self.subTest(value=x), self.assertRaises(ValueError):interval_bounds(x)

    def test_random_gaps_are_frozen_and_accumulated(self):
        for i in range(3):self.group('g'+str(i))
        cid=self.s.content('Caption')
        with patch('store.sample_gap', side_effect=[1800,2700,3600]):
            ids=self.s.plan(cid,'30-60',start=100000)
        before=self.s.rows('SELECT due,gap_seconds FROM jobs ORDER BY id')
        self.assertEqual([j['due'] for j in before],[100000,101800,104500])
        self.s.approve(ids)
        self.assertEqual(before,self.s.rows('SELECT due,gap_seconds FROM jobs ORDER BY id'))

    def test_unknown_group_cannot_be_enabled(self):
        gid=self.s.add_group('facebook.com/groups/unknown/')
        with self.assertRaises(ValueError):self.s.enable_group(gid,True)

    def test_choose_link_and_no_link_versions_per_group(self):
        self.group('links','allow');self.group('nolinks','deny')
        cid=self.s.content('Thông tin: https://example.com','original-image.jpg','Nội dung phù hợp không có link')
        ids=self.s.plan(cid,'30-60')
        self.assertEqual(len(ids),2)
        jobs=self.s.rows('SELECT * FROM jobs ORDER BY id')
        self.assertIn('https://',jobs[0]['body'])
        self.assertEqual(jobs[1]['body'],'Nội dung phù hợp không có link')
        self.assertEqual(jobs[1]['media'],'') # Never silently reuse a possibly linked image.

    def test_missing_no_link_variant_skips_and_notifies(self):
        self.group('nolinks','deny')
        cid=self.s.content('Thông tin https://example.com')
        self.assertEqual(self.s.plan(cid,'30-60'),[])
        self.assertIn('Bỏ qua nhóm',self.s.rows('SELECT text FROM outbox')[0]['text'])

    def test_no_link_editor_rejects_urls_and_domains(self):
        cid=self.s.content('Thông tin')
        for body in ('https://example.com','discord.gg/test','www.example.com'):
            self.assertTrue(has_link(body))
            with self.assertRaises(ValueError):self.s.no_link_content(cid,body)

    def test_cycle_has_at_most_one_job_per_group_day_and_one_to_three_day_gaps(self):
        self.group('g1');self.group('g2')
        cid=self.s.content('Caption')
        ids=self.s.cycle(cid,'30-60',1,3,30)
        self.assertTrue(ids)
        for gid in (1,2):
            jobs=self.s.rows('SELECT * FROM jobs WHERE group_id=? ORDER BY due',(gid,))
            days=[dt.datetime.fromtimestamp(j['due'],dt.timezone(dt.timedelta(hours=7))).date() for j in jobs]
            self.assertEqual(len(days),len(set(days)))
            for a,b in zip(jobs,jobs[1:]):
                self.assertGreaterEqual(b['due']-a['due'],86400)
                self.assertLessEqual(b['due']-a['due'],259200)
            self.assertTrue(all(1800<=j['gap_seconds']<=3600 for j in jobs))

    def test_cycle_does_not_create_overlapping_campaign(self):
        self.group('g1');cid=self.s.content('Caption')
        self.assertTrue(self.s.cycle(cid,'30-60',1,3,7))
        self.assertEqual(self.s.cycle(cid,'30-60',1,3,7),[])

    def test_completion_enforces_sampled_group_cooldown(self):
        self.group('g1');cid=self.s.content('Caption')
        ids=self.s.cycle(cid,'30-60',1,3,7)
        self.s.approve(ids);self.s.set('running',True)
        first=self.s.claim();self.assertIsNotNone(first)
        self.s.finish(first['id'],'submitted','Visible')
        deadline=self.s.rows('SELECT next_post_after FROM groups')[0]['next_post_after']
        self.assertGreaterEqual(deadline,time.time()+first['group_gap_seconds']-1)
        with self.s.db() as c:c.execute("UPDATE jobs SET due=? WHERE state='queued'",(time.time()-1,))
        self.assertIsNone(self.s.claim())
        # The independent Vietnam calendar-day guard still blocks if cooldown metadata is missing.
        with self.s.db() as c:c.execute('UPDATE groups SET next_post_after=0')
        self.assertIsNone(self.s.claim())

    def test_change_policy_invalidates_approved_link_jobs(self):
        gid=self.group('g1');cid=self.s.content('https://example.com')
        ids=self.s.plan(cid,60);self.s.approve(ids)
        self.s.set_link_policy(gid,'deny')
        self.assertEqual(self.s.rows('SELECT state FROM jobs')[0]['state'],'cancelled')

    def test_retime_preserves_group_day_spacing_and_requires_reapproval(self):
        self.group('g1');cid=self.s.content('Caption')
        ids=self.s.cycle(cid,60,1,3,10);self.s.approve(ids)
        self.s.retime('30-60')
        jobs=self.s.rows('SELECT * FROM jobs ORDER BY due')
        self.assertTrue(all(j['state']=='draft' for j in jobs))
        for a,b in zip(jobs,jobs[1:]):self.assertGreaterEqual(b['due']-a['due'],a['group_gap_seconds'])


if __name__=='__main__':unittest.main()
