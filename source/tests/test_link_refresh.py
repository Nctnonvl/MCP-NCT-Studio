"""Simulated storage/UI tests; no Windows or Facebook connection."""
import asyncio
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from store import Store, replace_link
import link_refresh as refresh
import link_refresh_ui as ui

OLD='https://discord.gg/old'
NEW='https://discord.gg/new'
GROUP='https://www.facebook.com/groups/test/'
BODY='Nội dung nguồn đầy đủ của bài kiểm thử. '+OLD


class RefreshStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.s=Store(Path(self.tmp.name)/'manager.sqlite3')
        gid=self.s.add_group(GROUP,'Test',link_policy='allow');self.s.enable_group(gid,True)
        self.cid=self.s.content(BODY,body_no_link='Bản không link')
        self.jid=self.s.plan(self.cid,60)[0]
        with self.s.db() as c:c.execute("UPDATE jobs SET state='submitted',post_url=?,attempted_at=? WHERE id=?",(GROUP+'posts/123/',time.time(),self.jid))
    def tearDown(self):self.tmp.cleanup()
    def preview(self):return self.s.preview_links(OLD,NEW,True)
    def apply(self):
        p=self.preview();return self.s.apply_links(OLD,NEW,p['digest'],True)
    def test_only_verified_published_posts_inside_36_hours(self):
        self.assertEqual(self.preview()['facebook_count'],1)
        with self.s.db() as c:c.execute('UPDATE jobs SET attempted_at=?',(time.time()-36*3600-5,))
        self.assertEqual(self.preview()['facebook_count'],0)
        with self.s.db() as c:c.execute("UPDATE jobs SET attempted_at=?,state='pending'",(time.time(),))
        self.assertEqual(self.preview()['facebook_count'],0)
        with self.s.db() as c:c.execute("UPDATE jobs SET state='submitted',post_url='https://evil.example/123'")
        self.assertEqual(self.preview()['facebook_count'],0)
    def test_opt_in_freezes_work_and_preserves_historical_source(self):
        self.assertEqual(self.s.preview_links(OLD,NEW)['facebook_count'],0)
        self.apply();work=self.s.rows('SELECT * FROM link_refresh')[0]
        self.assertEqual(work['body_before'],BODY);self.assertIn(NEW,work['body_after'])
        self.assertEqual(self.s.rows('SELECT body FROM jobs')[0]['body'],BODY)
        claimed=refresh.claim(self.s);self.assertEqual(claimed['id'],'refresh-'+str(work['id']))
        self.assertIsNone(refresh.claim(self.s));self.s.set('running',True);self.assertIsNone(self.s.claim())
    def test_live_selection_changes_invalidate_preview(self):
        p=self.preview()
        with self.s.db() as c:c.execute("UPDATE jobs SET state='pending'")
        with self.assertRaises(ValueError):self.s.apply_links(OLD,NEW,p['digest'],True)
        self.assertEqual(self.s.rows('SELECT * FROM link_refresh'),[])
    def test_recovery_keeps_uncertain_operation_and_cancels_remaining(self):
        self.apply();item=refresh.claim(self.s);refresh.checkpoint(self.s,item['refresh_id'],edit_state='uncertain')
        refresh.recover(self.s)
        self.assertEqual(self.s.rows('SELECT state FROM link_refresh')[0]['state'],'uncertain')
        self.assertEqual(self.preview()['facebook_count'],0)
    def test_confirmed_body_and_comment_carry_forward_for_next_link(self):
        self.apply();item=refresh.claim(self.s)
        refresh.checkpoint(self.s,item['refresh_id'],edit_state='saved',comment_state='sent',state='updated')
        third='https://discord.gg/third'
        p=self.s.preview_links(NEW,third,True)
        self.assertEqual(p['facebook_count'],1)
        self.assertEqual(self.preview()['facebook_count'],0)
    def test_comment_only_setting_and_fixed_footer_are_updated(self):
        with self.s.db() as c:
            c.execute('UPDATE contents SET body=?,comment_link=?,footer_text=?',('Không có link trong nội dung',OLD,OLD))
            c.execute('UPDATE jobs SET body=?,comment_text=?',('Không có link trong nội dung',OLD))
        self.s.set('post_footer',{'enabled':True,'text':OLD})
        p=self.preview();self.assertEqual(p['facebook_count'],1);self.assertFalse(p['facebook_posts'][0]['edit_body'])
        self.s.apply_links(OLD,NEW,p['digest'],True)
        self.assertEqual(self.s.rows('SELECT comment_link FROM contents')[0]['comment_link'],NEW)
        self.assertEqual(self.s.get('post_footer')['text'],NEW)
    def test_existing_footer_keeps_format_while_new_comment_is_regular_link(self):
        note=' (bỏ dấu cách trước dấu hai chấm hoặc xuống cmt nhá anh em )'
        body='Đây https ://discord.gg/old'+note
        self.assertEqual(replace_link(body,OLD,NEW),'Đây https ://discord.gg/new'+note)
        with self.s.db() as c:c.execute('UPDATE jobs SET body=?',(body,))
        self.apply()
        item=refresh.claim(self.s)
        self.assertEqual(item['body_after'],'Đây https ://discord.gg/new'+note)
        self.assertEqual(item['new_url'],NEW)
    def test_stop_cancels_queue_without_rewriting_source(self):
        self.apply();refresh.stop(self.s)
        self.assertIsNone(refresh.claim(self.s))
        self.assertEqual(self.s.rows('SELECT body FROM jobs')[0]['body'],BODY)


class RefreshUITests(unittest.IsolatedAsyncioTestCase):
    async def run_case(self,receipt_state='submitted',prepare=False,mismatched_editor=False,verify_saved=True,comment_allowed=False):
        with tempfile.TemporaryDirectory() as d:
            Path(d,'work').mkdir();store=Store(Path(d,'manager.sqlite3'))
            job={'id':'refresh-1','refresh_id':1,'data_dir':d,'url':GROUP,'post_url':GROUP+'posts/123/','body':BODY,'body_after':BODY.replace(OLD,NEW),'new_url':NEW,'comment_links':'unknown' if comment_allowed else 'deny','mode':'prepare' if prepare else 'publish'}
            receipt={'state':receipt_state,'verification_source':'your_content','post_url':job['post_url']}
            target={'loc':[50,50],'name':'menu','role':'button','text':'menu'}
            card={'state':'submitted','post_url':job['post_url'],'post_menu':target,'key':[0,0,100,100]}
            before={'editor':{**target,'value':'wrong' if mismatched_editor else BODY},'save':target}
            after={'editor':{**target,'value':job['body_after']},'save':target}
            calls=[]
            async def tool(name,args):calls.append((name,args));return None,''
            with patch('own_content.verify',new=AsyncMock(side_effect=[receipt,receipt if verify_saved else {}])),patch('own_content.read_matches',return_value=[card]),patch('desktop.verify_live_target'),patch('desktop.parse_targets',return_value=[{**target,'name':'chỉnh sửa bài viết'}]),patch.object(ui,'edit_controls',side_effect=[before,after]),patch.object(ui.asyncio,'sleep',new=AsyncMock()),patch('post_context.own_post_context',side_effect=[{'caption_seen':True,'post_menu':target,'post_actor':'Người tham gia ẩn danh','timestamp':{'url':job['post_url']},'editors':[target]} if receipt_state=='submitted' else {},{'caption_seen':True,'timestamp':{'url':job['post_url']},'editors':[target]} if verify_saved else {}]),patch('post_comments.finish_post',new=AsyncMock(return_value={'comment_status':'sent','comment_detail':'Đã xác nhận bình luận.'})) as comment_sender:
                try:result=await ui.execute(tool,AsyncMock(return_value=''),AsyncMock(return_value=job['post_url']),AsyncMock(),1,job,lambda _:None)
                except RuntimeError as e:result={'state':'error','detail':str(e)}
            self.comment_calls=comment_sender.await_count
            return result,calls
    async def test_pending_never_opens_edit_or_comments(self):
        r,c=await self.run_case(receipt_state='pending');self.assertEqual(r['state'],'skipped');self.assertEqual(c,[])
    async def test_prepare_never_types_saves_or_comments(self):
        r,c=await self.run_case(prepare=True);self.assertEqual(r['state'],'prepared');self.assertEqual([v[0] for v in c],['Click','Click'])
    async def test_mismatched_full_caption_never_types(self):
        r,c=await self.run_case(mismatched_editor=True);self.assertEqual(r['state'],'error');self.assertFalse(any(v[0]=='Type' for v in c))
    async def test_save_is_verified_before_comment_stage(self):
        r,c=await self.run_case(verify_saved=False);self.assertEqual(r['state'],'uncertain');self.assertEqual(len([v for v in c if v[0]=='Type']),1)
    async def test_group_forbids_comment_link(self):
        r,c=await self.run_case();self.assertEqual(r['state'],'updated');self.assertEqual(r['comment_status'],'skipped')

    async def test_verified_save_then_exact_post_gets_one_new_comment(self):
        r,c=await self.run_case(comment_allowed=True)
        self.assertEqual(r['state'],'updated');self.assertEqual(r['comment_status'],'sent')
        self.assertEqual(self.comment_calls,1)

    async def test_direct_navigation_has_no_scroll(self):
        r,c=await self.run_case(comment_allowed=True)
        self.assertFalse(any(name=='Scroll' for name,args in c))
