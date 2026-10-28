import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from store import Store,replace_link,validate_link

OLD='https://discord.gg/oldCode'
NEW='https://discord.gg/newCode'


class LinkChangeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.s=Store(Path(self.tmp.name)/'state.sqlite3')
        self.cid=self.s.content('Tham gia '+OLD+'. Hoặc '+OLD,'unchanged-image.jpg','Bản không link',category='Game')
        for i in range(5):
            gid=self.s.add_group(f'facebook.com/groups/g{i}/',link_policy='allow',category='Game');self.s.enable_group(gid,True)
        self.ids=self.s.plan(self.cid,'30-60')
        with self.s.db() as c:
            for jid,state in zip(self.ids,['draft','queued','submitted','pending','uncertain']):
                c.execute('UPDATE jobs SET state=? WHERE id=?',(state,jid))

    def tearDown(self):self.tmp.cleanup()

    def test_replace_exact_url_preserves_prefix_matches_and_punctuation(self):
        text=f'{OLD}. ({OLD}) {OLD}Longer'
        self.assertEqual(replace_link(text,OLD,NEW),f'{NEW}. ({NEW}) {OLD}Longer')

    def test_preview_counts_only_storage_and_unstarted_jobs(self):
        p=self.s.preview_links(OLD,NEW)
        self.assertEqual((p['content_count'],p['job_count'],p['historical_count']),(1,2,3))
        self.assertEqual(self.s.rows('SELECT body FROM contents')[0]['body'].count(OLD),2)

    def test_apply_keeps_historical_records_no_link_media_and_approval_state(self):
        self.s.set('running',True);p=self.s.preview_links(OLD,NEW)
        changed=self.s.apply_links(OLD,NEW,p['digest'])
        post=self.s.rows('SELECT * FROM contents')[0]
        self.assertNotIn(OLD,post['body']);self.assertIn(NEW,post['body'])
        self.assertEqual(post['body_no_link'],'Bản không link');self.assertEqual(post['media'],'unchanged-image.jpg')
        jobs=self.s.rows('SELECT * FROM jobs ORDER BY id')
        self.assertEqual([j['state'] for j in jobs],['draft','queued','submitted','pending','uncertain'])
        for j in jobs:
            self.assertIn(NEW if j['state'] in {'draft','queued'} else OLD,j['body'])
        self.assertFalse(self.s.get('running'));self.assertEqual(self.s.get('current_link'),NEW)
        audit=self.s.rows('SELECT * FROM link_changes')[0]
        self.assertEqual(audit['id'],changed['change_id']);self.assertIn(OLD,audit['before_json'])

    def test_active_worker_blocks_replacement(self):
        p=self.s.preview_links(OLD,NEW)
        with self.s.db() as c:c.execute("UPDATE jobs SET state='working' WHERE id=?",(self.ids[0],))
        with self.assertRaises(ValueError):self.s.apply_links(OLD,NEW,p['digest'])
        self.assertIn(OLD,self.s.rows('SELECT body FROM contents')[0]['body'])

    def test_open_edge_prepared_draft_is_not_claimed_as_updated(self):
        with self.s.db() as c:c.execute("UPDATE jobs SET state='prepared' WHERE id=?",(self.ids[0],))
        p=self.s.preview_links(OLD,NEW)
        self.assertEqual((p['job_count'],p['historical_count']),(1,4))
        self.s.apply_links(OLD,NEW,p['digest'])
        draft=self.s.rows('SELECT body FROM jobs WHERE id=?',(self.ids[0],))[0]
        self.assertIn(OLD,draft['body'])

    def test_stale_preview_is_rejected_without_partial_changes(self):
        p=self.s.preview_links(OLD,NEW)
        with self.s.db() as c:c.execute('UPDATE contents SET body=body||? WHERE id=?',(' Thêm thông tin',self.cid))
        with self.assertRaises(ValueError):self.s.apply_links(OLD,NEW,p['digest'])
        self.assertEqual(self.s.rows('SELECT * FROM link_changes'),[])
        self.assertTrue(all(OLD in j['body'] for j in self.s.rows('SELECT body FROM jobs')))

    def test_studio_cached_preview_is_updated(self):
        self.s.set('studio_task',{'status':'done','result':{'id':self.cid,'body':'Tham gia '+OLD}})
        p=self.s.preview_links(OLD,NEW);self.s.apply_links(OLD,NEW,p['digest'])
        self.assertIn(NEW,self.s.get('studio_task')['result']['body'])

    def test_inventory_and_repeated_weekly_change(self):
        first=self.s.preview_links(OLD,NEW);self.s.apply_links(OLD,NEW,first['digest'])
        last='https://discord.gg/thirdWeek'
        second=self.s.preview_links(NEW,last);self.s.apply_links(NEW,last,second['digest'])
        inventory=self.s.link_inventory()
        self.assertEqual(inventory,[{'url':last,'contents':1,'jobs':2}])

    def test_invalid_urls_same_url_and_empty_change_are_rejected(self):
        for url in ['javascript:alert(1)','https://user:pass@example.com','https://example.com/a b']:
            with self.assertRaises(ValueError):validate_link(url)
        with self.assertRaises(ValueError):self.s.preview_links(OLD,OLD)
        p=self.s.preview_links('https://example.com/not-present',NEW)
        with self.assertRaises(ValueError):self.s.apply_links(p['old_url'],NEW,p['digest'])


if __name__=='__main__':unittest.main()
