import io
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import media
from store import Store
from studio import Studio


class StudioTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.store=Store(self.root/'state.sqlite3')
        self.studio=Studio(self.store,lambda:{'model':'fake-local','mode':'publish'},self.root/'media')

    def tearDown(self):self.tmp.cleanup()

    def wait(self):
        limit=time.monotonic()+4
        while (self.store.get('studio_task',{}).get('status')=='running' or self.studio.lock.locked()) and time.monotonic()<limit:time.sleep(.01)
        result=self.store.get('studio_task',{})
        self.assertNotEqual(result.get('status'),'running')
        return result

    def add_group(self,name,category):
        gid=self.store.add_group('facebook.com/groups/'+name+'/',name,link_policy='allow',category=category)
        self.store.enable_group(gid,True);return gid

    def response(self):return {'title':'Bài thử','body':'Thông tin chính xác. Mời mọi người chia sẻ kinh nghiệm.','body_no_link':'Thông tin chính xác. Mời mọi người chia sẻ kinh nghiệm.'}

    def test_category_routes_only_to_matching_groups(self):
        game=self.add_group('game','Game');self.add_group('pc','Công nghệ')
        cid=self.store.content('Bài game',category='Game')
        ids=self.store.cycle(cid,'30-60',1,3,7)
        self.assertTrue(ids)
        self.assertEqual({j['group_id'] for j in self.store.rows('SELECT group_id FROM jobs')},{game})

    def test_unclassified_groups_never_selected(self):
        self.add_group('unknown','')
        cid=self.store.content('Bài',category='Game')
        self.assertEqual(self.store.cycle(cid,60,1,3,7),[])

    def test_category_change_cancels_old_queue(self):
        gid=self.add_group('game','Game');cid=self.store.content('Bài',category='Game')
        ids=self.store.plan(cid,60);self.store.approve(ids)
        self.store.group_category(gid,'Công nghệ')
        self.assertEqual(self.store.rows('SELECT state FROM jobs')[0]['state'],'cancelled')

    def test_generation_accepts_explicit_discord_with_space_in_brief(self):
        answer=self.response();answer['body']='Mời tham gia https://discord.gg/qwwrrMcP'
        with patch.object(self.studio,'chat_json',return_value=answer):
            self.studio.start({'brief':'https: //discord.gg/qwwrrMcP (bỏ dấu cách sau dấu 2 chấm hoặc xuống cmt)','category':'Game'});result=self.wait()
        self.assertEqual(result['status'],'done');self.assertEqual(self.store.rows('SELECT body FROM contents')[0]['body'],answer['body']);self.assertEqual(self.store.rows('SELECT * FROM jobs'),[])
    def test_spaced_link_still_cannot_enter_no_link_variant(self):
        answer=self.response();answer['body_no_link']='https: //discord.gg/qwwrrMcP'
        with patch.object(self.studio,'chat_json',side_effect=[answer,answer,RuntimeError('HTTP 429: limit')]):
            self.studio.start({'brief':'https: //discord.gg/qwwrrMcP','category':'Game'});result=self.wait()
        self.assertEqual(result['status'],'error');self.assertEqual(self.store.rows('SELECT * FROM contents'),[])
    def test_single_button_retries_copy_of_user_sample_before_saving(self):
        brief='Anh em nào muốn lên rank Valorant an toàn thì ghé ngay Discord của bên mình nhé. Ở đây cung cấp đầy đủ game nhiều bản cho anh em lựa chọn với giá cả hợp lý.'
        copy={'title':'Copy','body':brief,'body_no_link':brief}
        rewritten={'title':'Mời trao đổi tại Discord','body':'Discord bên mình là nơi để bạn tìm hiểu các lựa chọn game và phiên bản đang được cung cấp. Mức giá hướng tới sự hợp lý; nếu quan tâm Valorant, bạn có thể ghé trao đổi thêm.','body_no_link':'Bạn quan tâm Valorant hoặc muốn tìm hiểu các phiên bản game đang có? Có thể trao đổi tại cộng đồng Discord của bên mình để biết thêm thông tin và mức giá phù hợp.'}
        with patch.object(self.studio,'chat_json',side_effect=[copy,rewritten]) as ai:
            self.studio.start({'brief':brief,'category':'Valorant','tone':'Rõ ràng, chuyên nghiệp'});task=self.wait()
        self.assertEqual(task['status'],'done');self.assertEqual(ai.call_count,2)
        self.assertEqual(self.store.rows('SELECT body FROM contents')[0]['body'],rewritten['body']);self.assertEqual(self.store.rows('SELECT * FROM jobs'),[])
        self.assertEqual(ai.call_args.args[1]['tone'],'Rõ ràng, chuyên nghiệp');self.assertIn('revision_request',ai.call_args.args[1])
    def test_single_button_repairs_invented_link_once(self):
        bad={**self.response(),'body':'Mời tham gia https://discord.gg/invented'}
        with patch.object(self.studio,'chat_json',side_effect=[bad,self.response()]) as ai:
            self.studio.start({'brief':'Mời trao đổi tại Discord, chưa có đường link.','category':'Game'});task=self.wait()
        self.assertEqual(task['status'],'done');self.assertEqual(ai.call_count,2);self.assertEqual(ai.call_args.args[1]['allowed_urls'],[])
        self.assertNotIn('https://',self.store.rows('SELECT body FROM contents')[0]['body'])
    def test_single_button_does_not_save_duplicate_when_retry_still_copies(self):
        brief='Anh em nào muốn lên rank Valorant an toàn thì ghé ngay Discord của bên mình nhé. Ở đây cung cấp đầy đủ game nhiều bản cho anh em lựa chọn với giá cả hợp lý.'
        with patch.object(self.studio,'chat_json',side_effect=[{'body':brief,'body_no_link':brief},{'body':brief,'body_no_link':brief},RuntimeError('HTTP 429: limit')]) as ai:
            self.studio.start({'brief':brief,'category':'Valorant'});task=self.wait()
        self.assertEqual(task['status'],'error');self.assertEqual(ai.call_count,3);self.assertEqual(self.store.rows('SELECT * FROM contents'),[])
    def test_single_button_checks_previous_posts_of_same_category(self):
        answer=self.response();self.store.content(answer['body'],category='Game')
        with patch.object(self.studio,'chat_json',side_effect=[answer,answer,RuntimeError('HTTP 429: limit')]) as ai:
            self.studio.start({'brief':'Dữ kiện mới để viết khác cách cũ','category':'Game'});task=self.wait()
        self.assertEqual(task['status'],'error');self.assertEqual(ai.call_count,3);self.assertEqual(len(self.store.rows('SELECT * FROM contents')),1)
    def test_rewrites_until_fourth_response_passes(self):
        bad=self.response();self.store.content(bad['body'],category='Game')
        clean={'title':'Khác','body':'Có nhiều cách lựa chọn phiên bản, anh em cứ cân nhắc theo nhu cầu của mình. Mình sẵn sàng trao đổi cụ thể qua Discord khi anh em cần.', 'body_no_link':'Tùy nhu cầu, anh em có thể tham khảo các phiên bản rồi trao đổi trước khi lựa chọn.'}
        with patch.object(self.studio,'chat_json',side_effect=[bad,bad,bad,clean]) as ai:
            self.studio.start({'brief':'Thông tin game và phiên bản, trao đổi qua Discord.','category':'Game'});task=self.wait()
        self.assertEqual(task['status'],'done');self.assertEqual(ai.call_count,4)
        self.assertEqual(len(self.store.rows('SELECT * FROM contents')),2)
        recovery=self.store.get('ai_rewrite_drafts')['single']
        self.assertEqual(recovery['attempt'],3);self.assertEqual(recovery['status'],'accepted')
        self.assertEqual(recovery['body'],bad['body'])

    def test_single_button_sends_a_different_writing_direction_next_time(self):
        first=self.response();second={'title':'Khác','body':'Một hướng trao đổi khác cho cộng đồng là quan sát thói quen phối hợp và chọn vai trò. Bạn có thể nêu trải nghiệm của mình để mọi người thảo luận.','body_no_link':'Việc chọn vai trò và phối hợp có nhiều cách nhìn. Mời mọi người chia sẻ trải nghiệm riêng để cùng tham khảo.'}
        directions=[]
        def generate(*args):directions.append(args[1]['writing_direction']);return first if len(directions)==1 else second
        with patch.object(self.studio,'chat_json',side_effect=generate):
            for _ in range(2):self.studio.start({'brief':'Dữ kiện để viết bài giao lưu','category':'Game'});self.wait()
        self.assertNotEqual(directions[0],directions[1]);self.assertEqual(len(self.store.rows('SELECT * FROM contents')),2)
    def test_generation_saves_two_variants_without_posting(self):
        with patch.object(self.studio,'chat_json',return_value=self.response()):
            self.studio.start({'brief':'Thông tin chính xác','category':'Game'})
            result=self.wait()
        self.assertEqual(result['status'],'done')
        self.assertEqual(self.store.rows('SELECT category FROM contents')[0]['category'],'Game')
        self.assertEqual(self.store.rows('SELECT * FROM jobs'),[])
        self.assertFalse(self.store.get('running'))

    def test_autopost_requires_pairing(self):
        with self.assertRaises(ValueError):self.studio.start({'brief':'Test','category':'Game','autopost':True})

    def test_explicit_autopost_scopes_to_category_and_selected_period(self):
        game=self.add_group('game','Game');self.add_group('pc','Công nghệ');self.store.set('owner_id',1)
        with patch.object(self.studio,'chat_json',return_value=self.response()):
            self.studio.start({'brief':'Thông tin chính xác','category':'Game','autopost':True,'horizon':3})
            result=self.wait()
        self.assertEqual(result['status'],'done')
        jobs=self.store.rows('SELECT * FROM jobs')
        self.assertTrue(jobs)
        self.assertTrue(all(j['state']=='queued' and j['group_id']==game for j in jobs))

    def test_pause_during_generation_prevents_autopost(self):
        self.add_group('game','Game');self.store.set('owner_id',1)
        def response(*args):self.store.set('control_revision',1);return self.response()
        with patch.object(self.studio,'chat_json',side_effect=response):
            self.studio.start({'brief':'Thông tin chính xác','category':'Game','autopost':True})
            result=self.wait()
        self.assertEqual(result['status'],'error')
        self.assertEqual(len(self.store.rows('SELECT * FROM contents')),1)
        self.assertEqual(self.store.rows('SELECT * FROM jobs'),[])

    def test_no_link_output_is_checked_before_saving(self):
        response={**self.response(),'body_no_link':'Ghé https://example.com'}
        with patch.object(self.studio,'chat_json',side_effect=[response,response,RuntimeError('HTTP 429: limit')]):
            self.studio.start({'brief':'Thông tin','category':'Game'});result=self.wait()
        self.assertEqual(result['status'],'error');self.assertEqual(self.store.rows('SELECT * FROM contents'),[])

    def test_low_confidence_classification_keeps_group_unclassified(self):
        gid=self.add_group('maybe','Chung')
        with patch.object(self.studio,'chat_json',return_value={'category':'Game','confidence':0.2}):
            self.studio.classify([gid],['Game','Công nghệ']);result=self.wait()
        self.assertEqual(result['status'],'done')
        self.assertEqual(self.store.rows('SELECT category FROM groups')[0]['category'],'')

    def test_media_signatures_paths_and_video_mixing(self):
        png=b'\x89PNG\r\n\x1a\n'+b'\0'*32
        image=media.receive(io.BytesIO(png),len(png),'photo.png',self.root/'media')
        video=b'\0\0\0\x18ftypmp42'+b'\0'*24
        clip=media.receive(io.BytesIO(video),len(video),'clip.mp4',self.root/'media')
        self.assertEqual(image['kind'],'image');self.assertEqual(clip['kind'],'video')
        self.assertTrue(media.resolve([image['id']],self.root/'media'))
        with self.assertRaises(ValueError):media.resolve([image['id'],clip['id']],self.root/'media')
        with self.assertRaises(ValueError):media.resolve(['../state.sqlite3'],self.root/'media')
        with self.assertRaises(ValueError):media.receive(io.BytesIO(b'fake'),4,'fake.png',self.root/'media')
        with self.assertRaises(ValueError):media.receive(io.BytesIO(png),media.MAX_UPLOAD+1,'big.png',self.root/'media')


if __name__=='__main__':unittest.main()
