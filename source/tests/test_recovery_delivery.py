"""Temporary databases and fake Telegram/Windows controls; no external posts."""
import datetime as dt
import importlib.util
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from store import Store
import desktop
from final_report import render


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.s=Store(Path(self.tmp.name)/'db')
        self.now=dt.datetime(2026,10,24,10,tzinfo=dt.timezone(dt.timedelta(hours=7))).timestamp()
        self.cid=self.s.content('Nội dung đã duyệt',body_no_link='Bản không link')
        self.groups=[]
        for i in range(3):
            gid=self.s.add_group(f'facebook.com/groups/t{i}',link_policy='allow')
            self.s.enable_group(gid,True);self.groups.append(gid)

    def tearDown(self):self.tmp.cleanup()

    def queue(self):
        ids=self.s.plan(self.cid,30,start=self.now-10800)
        self.s.approve(ids)
        return ids

    def test_missed_posts_keep_ids_text_approval_and_push_later_slots(self):
        ids=self.queue();before=self.s.rows('SELECT id,body,state FROM jobs ORDER BY id')
        with patch('store.time.time',return_value=self.now):
            self.assertEqual(self.s.reflow_queue(),3)
        self.assertEqual(before,self.s.rows('SELECT id,body,state FROM jobs ORDER BY id'))
        jobs=self.s.rows('SELECT * FROM jobs ORDER BY due')
        self.assertEqual([j['due'] for j in jobs],[self.now,self.now+1800,self.now+3600])
        self.assertTrue(all(j['schedule_note'] and j['original_due']<self.now for j in jobs))
        with patch('store.time.time',return_value=self.now):self.assertEqual(self.s.reflow_queue(),0)

    def test_recover_resumes_only_approved_jobs_and_respects_pause(self):
        self.queue();self.s.set('resume_approved_on_start',True)
        with patch('store.time.time',return_value=self.now):self.s.recover()
        self.assertTrue(self.s.get('running'))
        self.s.set('paused_by_user',True)
        with patch('store.time.time',return_value=self.now):self.s.recover()
        self.assertFalse(self.s.get('running'))

    def test_draft_is_not_approved_or_rescheduled(self):
        self.s.plan(self.cid,30,start=self.now-1000)
        before=self.s.rows('SELECT id,due,state FROM jobs')
        self.s.set('resume_approved_on_start',True)
        with patch('store.time.time',return_value=self.now):self.s.recover()
        self.assertFalse(self.s.get('running'));self.assertEqual(before,self.s.rows('SELECT id,due,state FROM jobs'))

    def test_interrupted_worker_is_never_requeued_or_resumed(self):
        ids=self.queue();self.s.set('resume_approved_on_start',True)
        with self.s.db() as c:c.execute("UPDATE jobs SET state='working' WHERE id=?",(ids[0],))
        with patch('store.time.time',return_value=self.now):self.s.recover()
        self.assertFalse(self.s.get('running'))
        self.assertEqual(self.s.rows('SELECT state FROM jobs WHERE id=?',(ids[0],))[0]['state'],'uncertain')

    def test_daily_cap_rolls_remaining_posts_into_next_vietnam_day(self):
        self.queue();self.s.set('daily_group_limit',2)
        with patch('store.time.time',return_value=self.now):self.s.reflow_queue()
        jobs=self.s.rows('SELECT due FROM jobs ORDER BY due')
        vn=dt.timezone(dt.timedelta(hours=7))
        days=[dt.datetime.fromtimestamp(j['due'],vn).day for j in jobs]
        self.assertEqual(days,[24,24,25])

    def test_safe_window_failure_has_one_retry_and_retains_same_job(self):
        ids=self.queue()
        with self.s.db() as c:c.execute("UPDATE jobs SET state='working',attempted_at=? WHERE id=?",(self.now,ids[0]))
        result={'post_attempted':False,'safe_to_retry':True,'detail':'Cửa sổ Edge chưa sẵn sàng'}
        with patch('store.time.time',return_value=self.now):self.assertTrue(self.s.defer_safe_failure(ids[0],result))
        row=self.s.rows('SELECT * FROM jobs WHERE id=?',(ids[0],))[0]
        self.assertEqual(row['state'],'queued');self.assertEqual(row['safe_retries'],1)
        self.assertGreater(row['due'],self.now)
        with self.s.db() as c:c.execute("UPDATE jobs SET state='working' WHERE id=?",(ids[0],))
        self.assertFalse(self.s.defer_safe_failure(ids[0],result))

    def test_uncertain_or_unknown_submit_never_retries(self):
        ids=self.queue()
        for result in ({'post_attempted':True,'safe_to_retry':True},{'safe_to_retry':True},{'post_attempted':False,'safe_to_retry':False}):
            self.assertFalse(self.s.defer_safe_failure(ids[0],result))

    def test_footer_is_preserved_for_allow_and_moved_only_to_allowed_comment(self):
        footer='https ://discord.gg/DzdDGgry (bỏ dấu cách trước dấu hai chấm)'
        cid=self.s.content('Nội dung\n\n'+footer,body_no_link='Nội dung',footer_text=footer)
        self.s.set('footer_comment_fallback',True)
        self.s.set_link_policy(self.groups[1],'deny')
        self.s.set_comment_policy(self.groups[1],'allow')
        self.s.set_link_policy(self.groups[2],'deny')
        ids=self.s.plan(cid,30)
        jobs=self.s.rows('SELECT * FROM jobs WHERE content_id=? ORDER BY group_id',(cid,))
        self.assertEqual(jobs[0]['body'],'Nội dung\n\n'+footer)
        self.assertEqual(jobs[1]['body'],'Nội dung')
        self.assertEqual(jobs[1]['comment_text'],'https://discord.gg/DzdDGgry')
        self.assertEqual(jobs[2]['comment_text'],'')
        self.assertIn('chưa được phép',jobs[2]['variant_note'])


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        with patch.dict(os.environ,{'NCT_DATA_DIR':self.tmp.name}):
            spec=importlib.util.spec_from_file_location('delivery_controller',Path(__file__).resolve().parents[1]/'app.py')
            self.app=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.app)

    def tearDown(self):logging.shutdown();self.tmp.cleanup()

    def test_photo_report_sends_one_message_with_caption_and_buttons(self):
        photo=Path(self.tmp.name)/'receipt.png';photo.write_bytes(b'fake')
        markup={'inline_keyboard':[[{'text':'Mở bài','url':'https://facebook.com/'}]]}
        self.app.STORE.notify('Kết quả cuối cùng',str(photo),markup,'Caption')
        item=self.app.STORE.rows('SELECT * FROM outbox')[0]
        with patch.object(self.app,'send_text') as text,patch.object(self.app,'send_photo') as image:
            self.app.deliver_outbox_item(34,item)
        text.assert_not_called();image.assert_called_once_with(34,str(photo),'Kết quả cuối cùng',reply_markup=markup)
        item=self.app.STORE.rows('SELECT * FROM outbox')[0]
        with patch.object(self.app,'send_photo') as image:self.app.deliver_outbox_item(34,item);image.assert_not_called()

    def test_missing_photo_sends_text_once(self):
        self.app.STORE.notify('Kết quả','missing.png')
        item=self.app.STORE.rows('SELECT * FROM outbox')[0]
        with patch.object(self.app,'send_text') as text,patch.object(self.app,'send_photo') as image:
            self.app.deliver_outbox_item(34,item)
        text.assert_called_once();image.assert_not_called()

    def test_final_report_combines_post_comment_and_link_under_caption_limit(self):
        text=render({'id':87,'content_id':6,'group_name':'Nhóm','url':'https://facebook.com/groups/test','comment_text':'link'},
            {'state':'submitted','post_url':'https://facebook.com/groups/test/posts/1/','comment_status':'sent','detail':'x'*3000})
        self.assertIn('Đã đăng',text);self.assertIn('Bình luận: đã gửi',text)
        self.assertLessEqual(len(text),900);self.assertNotIn('x'*20,text)


class WindowSelectionTests(unittest.TestCase):
    def test_reused_profile_selects_actual_foreground_browser(self):
        self.assertEqual(desktop.choose_profile_window([10,20],[10,20],20),20)
        self.assertEqual(desktop.choose_profile_window([10,20],[10],10),20)
        with self.assertRaises(RuntimeError):desktop.choose_profile_window([10,20],[10,20],99)

    def test_facebook_timestamp_ignores_invisible_combining_joiner(self):
        self.assertEqual(desktop.normalized('V\u034fừ\u034fa\u034f xong'),'vừa xong')


if __name__=='__main__':unittest.main()
