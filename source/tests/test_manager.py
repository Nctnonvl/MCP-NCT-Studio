import importlib
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from store import Store, group_url
from desktop import parse_targets, is_post_button, json_choice, error_detail


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.s = Store(Path(self.tmp.name)/'test.sqlite3')
        self.g = self.s.add_group('https://m.facebook.com/groups/test-group/?ref=share', 'Test', link_policy='allow')
        self.cid = self.s.content('Nội dung đã duyệt')

    def tearDown(self):
        self.tmp.cleanup()

    def enable(self):
        self.s.enable_group(self.g, True)

    def test_reject_other_hosts_and_post_links(self):
        for value in ['https://facebook.com.evil.test/groups/a/', 'https://facebook.com@evil.test/groups/a/', 'https://www.facebook.com/groups/a/posts/123/', 'https://www.facebook.com/groups/feed/', 'https://www.facebook.com:9000/groups/a/']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                group_url(value)

    def test_normalize_and_deduplicate_groups(self):
        self.assertEqual(group_url('m.facebook.com/groups/test-group?x=1'), 'https://www.facebook.com/groups/test-group/')
        self.assertEqual(self.s.add_group('facebook.com/groups/test-group/', 'New'), self.g)
        self.assertEqual(len(self.s.rows('SELECT * FROM groups')), 1)

    def test_group_is_disabled_until_explicitly_enabled(self):
        with self.assertRaises(ValueError):
            self.s.plan(self.cid, 60)

    def test_plan_freezes_caption(self):
        self.enable()
        ids = self.s.plan(self.cid, 60)
        with self.s.db() as c:
            c.execute('UPDATE contents SET body=? WHERE id=?', ('Đã sửa', self.cid))
        self.assertEqual(self.s.rows('SELECT body FROM jobs WHERE id=?', (ids[0],))[0]['body'], 'Nội dung đã duyệt')

    def test_unapproved_jobs_never_claimed(self):
        self.enable()
        self.s.plan(self.cid, 60)
        self.s.set('running', True)
        self.assertIsNone(self.s.claim())

    def test_approval_run_and_no_reclaim(self):
        self.enable()
        ids = self.s.plan(self.cid, 60)
        self.assertEqual(self.s.approve(ids), 1)
        self.assertIsNone(self.s.claim())
        self.s.set('running', True)
        job = self.s.claim()
        self.assertEqual(job['id'], ids[0])
        self.assertIsNone(self.s.claim())

    def test_no_duplicate_after_uncertain(self):
        self.enable()
        ids = self.s.plan(self.cid, 60)
        self.s.finish(ids[0], 'uncertain', 'Kiểm tra')
        self.assertEqual(self.s.plan(self.cid, 60), [])

    def test_test_mode_can_be_replanned(self):
        self.enable()
        ids = self.s.plan(self.cid, 60)
        self.s.finish(ids[0], 'prepared', 'Chưa bấm đăng')
        self.assertEqual(len(self.s.plan(self.cid, 60)), 1)

    def test_disable_cancels_queued(self):
        self.enable()
        ids = self.s.plan(self.cid, 60)
        self.s.approve(ids)
        self.s.enable_group(self.g, False)
        self.assertEqual(self.s.rows('SELECT state FROM jobs')[0]['state'], 'cancelled')

    def test_recovery_marks_interrupted_job_uncertain(self):
        self.enable()
        ids = self.s.plan(self.cid, 60)
        self.s.approve(ids)
        self.s.set('running', True)
        self.s.claim()
        second = Store(self.s.path)
        self.assertTrue(second.get('running'))  # Mere second instance must not disturb live work.
        second.recover()
        self.assertFalse(second.get('running'))
        self.assertEqual(second.rows('SELECT state FROM jobs')[0]['state'], 'uncertain')

    def test_atomic_claim(self):
        self.enable()
        ids = self.s.plan(self.cid, 60)
        self.s.approve(ids)
        self.s.set('running', True)
        result = []
        workers = [threading.Thread(target=lambda: result.append(self.s.claim())) for _ in range(4)]
        for t in workers:
            t.start()
        for t in workers:
            t.join()
        self.assertEqual(sum(r is not None for r in result), 1)

    def test_sleep_catchup_is_spaced(self):
        self.enable()
        ids = self.s.plan(self.cid, 60)
        self.s.approve(ids)
        self.s.set('running', True)
        self.s.set('next_allowed', time.time()+3600)
        self.assertIsNone(self.s.claim())

    def test_mix_uses_only_user_selected_contents(self):
        self.enable()
        g2 = self.s.add_group('facebook.com/groups/other/', 'Other', link_policy='allow')
        self.s.enable_group(g2, True)
        other = self.s.content('Bản nháp khác')
        ids = self.s.plan_many([self.cid, other], 120)
        jobs = self.s.rows('SELECT * FROM jobs ORDER BY id')
        self.assertEqual(len(ids), 2)
        self.assertEqual(jobs[1]['due']-jobs[0]['due'], 7200)
        self.assertTrue(all(j['body'] in {'Nội dung đã duyệt', 'Bản nháp khác'} for j in jobs))


class DesktopTests(unittest.TestCase):
    def test_mcp_targets_derive_from_tree_coordinates(self):
        text = 'Cursor Position: (1,2)\nUI Tree:\n├── (120,300) button "Write something..." [action: click]\n└── (-20,500) edit "Post text" [action: fill]'
        items = parse_targets(text)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]['loc'], [120,300])
        self.assertEqual(items[1]['loc'], [-20,500])

    def test_submit_gate_requires_exact_post_button(self):
        self.assertTrue(is_post_button({'text': 'button "Đăng" [action: click]'}))
        self.assertFalse(is_post_button({'text': 'button "Comment on post" [action: click]'}))
        self.assertFalse(is_post_button({'text': 'edit "Post" [action: fill]'}))

    def test_model_output_must_be_json(self):
        self.assertEqual(json_choice('```json\n{"action":"wait"}\n```')['action'], 'wait')
        for value in ['please click', '[]', 'null']:
            with self.assertRaises(RuntimeError):
                json_choice(value)

    def test_nested_error_preserves_actionable_cause(self):
        self.assertEqual(error_detail(ExceptionGroup('outer', [ValueError('Sai cửa sổ')])), 'Sai cửa sổ')


class ControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        os.environ['NCT_DATA_DIR'] = cls.tmp.name
        cls.app = importlib.import_module('app')

    @classmethod
    def tearDownClass(cls):
        # Windows cannot remove the temporary controller log while its handler is open.
        import logging
        for handler in list(logging.getLogger().handlers):
            filename=getattr(handler,'baseFilename','')
            if filename and Path(filename).is_relative_to(Path(cls.tmp.name)):
                logging.getLogger().removeHandler(handler)
                handler.close()
        cls.tmp.cleanup()

    def setUp(self):
        self.tmpcase = tempfile.TemporaryDirectory()
        self.app.STORE = Store(Path(self.tmpcase.name)/'state.sqlite3')
        self.app.STOP_WORK.clear()

    def tearDown(self):
        self.tmpcase.cleanup()

    def message(self, uid, text, kind='private'):
        return {'from': {'id': uid, 'is_bot': False}, 'chat': {'id': uid, 'type': kind}, 'text': text}

    def test_pairing_requires_secret_and_owner_commands(self):
        with patch.object(self.app, 'send_text'):
            self.app.handle_message(self.message(11, '/pair wrong'))
            self.assertIsNone(self.app.STORE.get('owner_id'))
            self.app.handle_message(self.message(11, '/pair '+self.app.STORE.get('pair_code')))
            self.assertEqual(self.app.STORE.get('owner_id'), 11)
            self.app.handle_message(self.message(22, '/new UNAUTHORIZED'))
            self.assertEqual(self.app.STORE.rows('SELECT * FROM contents'), [])
            self.app.handle_message(self.message(11, '/new Approved content'))
            self.assertEqual(len(self.app.STORE.rows('SELECT * FROM contents')), 1)

    def test_group_chat_cannot_pair(self):
        self.app.handle_message(self.message(11, '/pair '+self.app.STORE.get('pair_code'), 'group'))
        self.assertIsNone(self.app.STORE.get('owner_id'))

    def test_pause_keeps_queue_and_bot_configuration(self):
        s = self.app.STORE
        g = s.add_group('facebook.com/groups/test/', link_policy='allow')
        s.enable_group(g, True)
        ids = s.plan(s.content('Body'), 60)
        s.approve(ids)
        s.set('running', True)
        self.app.pause()
        self.assertFalse(s.get('running'))
        self.assertTrue(self.app.STOP_WORK.is_set())
        self.assertEqual(s.rows('SELECT state FROM jobs')[0]['state'], 'queued')

    def test_local_state_never_exposes_token(self):
        token = '123456789:' + 'A' * 35
        self.app.STORE.set('config', {'token': token, 'model': 'qwen3:8b'})
        self.assertNotIn(token, json.dumps(self.app.web_state()))
        self.assertNotIn(token, self.app.safe_error(ValueError(token)))

    def test_edit_does_not_modify_approved_job(self):
        s = self.app.STORE
        s.set('owner_id', 1)
        s.set('owner_chat', 1)
        g = s.add_group('facebook.com/groups/test/', link_policy='allow')
        s.enable_group(g, True)
        cid = s.content('Original')
        ids = s.plan(cid, 60)
        s.approve(ids)
        self.app.handle_message(self.message(1, f'/edit {cid} Changed'))
        self.assertEqual(s.rows('SELECT body FROM jobs')[0]['body'], 'Original')

    def test_telegram_manual_wizard_creates_category_and_no_link_version(self):
        s=self.app.STORE;s.set('owner_id',1);s.set('owner_chat',1)
        with patch.object(self.app,'send_text'):
            for text in ['➕ Tạo bài','Chia sẻ bàn phím https://example.com','Công nghệ','Chia sẻ bàn phím để mọi người giao lưu']:
                self.app.handle_message(self.message(1,text))
        post=s.rows('SELECT * FROM contents')[0]
        self.assertEqual(post['category'],'Công nghệ')
        self.assertEqual(post['body_no_link'],'Chia sẻ bàn phím để mọi người giao lưu')
        self.assertIsNone(s.get('bot_wizard'))

    def test_pause_is_not_swallowed_by_bot_wizard(self):
        s=self.app.STORE;s.set('owner_id',1);s.set('owner_chat',1);s.set('running',True)
        with patch.object(self.app,'send_text'):
            self.app.handle_message(self.message(1,'➕ Tạo bài'))
            self.app.handle_message(self.message(1,'/pause'))
        self.assertFalse(s.get('running'));self.assertEqual(s.rows('SELECT * FROM contents'),[])


if __name__ == '__main__':
    unittest.main()
