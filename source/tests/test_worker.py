"""Scripted UI/MCP tests. These never connect to Facebook or operate a real desktop."""
import asyncio
import contextlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import desktop
import post_comments


@contextlib.contextmanager
def fake_readers():
    with contextlib.ExitStack() as stack:
        stack.enter_context(patch('post_comments.own_post_context',return_value={}))
        stack.enter_context(patch('post_context.own_post_context',return_value={}))
        stack.enter_context(patch('feed_confirmation.verify_feed',new=AsyncMock(return_value={'state':'uncertain','detail':'No matching feed post'})))
        stack.enter_context(patch('publication_wait.read_surface',return_value={'complete':True,'composer':True,'enabled':True,'busy':False,'notices':''}))
        stack.enter_context(patch('publication_wait.wait_video_ready',new=AsyncMock()))
        stack.enter_context(patch('publication_wait.wait_submission',new=AsyncMock()))
        yield

class WorkerTests(unittest.TestCase):
    def simulate(self, mode='prepare', fail_submit=False, caption='Nội dung chính xác đã duyệt', initial_choices=None, banner='', pending_receipt='', redirect_after_click=False, copy_fails=False, background=False, video_rejection=False, no_fallback_photo=False, french=False, bounded=False, confirmed_result=None,approval=False,existing=False):
        with tempfile.TemporaryDirectory() as d:
            data = Path(d)
            (data/'work').mkdir()
            job = {'id':1,'url':'https://www.facebook.com/groups/test/','body':caption,'media':'',
                'bounded_composer':bounded,'group_name':'Test Group','group_id':1,'data_dir':d,'model':'fake-local','mode':mode,'result':str(data/'result.json'),'progress':str(data/'progress.json')}
            snapshots = [
                'UI Tree:\n(100,100) button "Write something..." [action: click]',
                'UI Tree:\n(100,150) edit "Create post text" [action: fill]\n(100,200) button "Post" [action: click]',
                f'UI Tree:\n(100,200) button "Post" [action: click]\ntext "{caption}"',
                f'UI Tree:\n(100,200) button "Post" [action: click]\ntext "{caption}"',
                f'UI Tree:\n(100,300) button "Group details" [action: click]\ntext "{caption}"',
            ]
            choices = [
                {'action':'click','target':0}, {'action':'type_caption','target':0},
                {'action':'submit','target':0}, {'action':'done','outcome':'submitted','evidence':caption}]
            if video_rejection:
                (data/'media').mkdir()
                clip_path=data/'media'/'clip.mp4';clip_path.write_bytes(b'\x00\x00\x00\x18ftypmp42')
                image_path=data/'media'/'fallback.png';image_path.write_bytes(b'\x89PNG\r\n\x1a\n'+b'fake')
                job['media']=str(clip_path);job['video_fallback_media']='' if no_fallback_photo else str(image_path)
                composer=f'UI Tree:\n(100,150) edit "Create a public post" [action: fill]\ntext "{caption}"\n(100,180) button "Photo/video" [action: click]\n(100,200) button "Post" [action: click]'
                native='UI Tree:\n(100,150) edit "File name" [action: fill]'
                rejected=f'UI Tree:\n(100,150) edit "Create a public post" [action: fill]\ntext "{caption}"\ntext "Could not upload your video"\n(100,170) button "Remove video" [action: click]\n(100,200) button "Post" [action: click]'
                ready=f'UI Tree:\n(100,150) edit "Create a public post" [action: fill]\ntext "{caption}"\n(100,200) button "Post" [action: click]'
                snapshots=[snapshots[0],composer,composer,native,rejected,composer,composer,native,ready,ready,snapshots[-1]]
                choices=[{'action':'click','target':0},{'action':'type_caption','target':0},{'action':'click','target':1},{'action':'type_media','target':0},{'action':'click','target':1},{'action':'type_media','target':0},{'action':'submit','target':1},{'action':'done','outcome':'submitted','evidence':caption}]
            if banner:snapshots=[value+'\ntext \"'+banner+'\"' for value in snapshots]
            if pending_receipt:
                snapshots[-1]+='\ntext \"'+pending_receipt+'\"'
                choices[-1]={'action':'done','outcome':'pending','evidence':pending_receipt}
            choices=(initial_choices or [])+choices
            if background:
                snapshots=['UI Tree:\ndesktop\n├── window "Target Group"\n'+value.split('UI Tree:\n')[-1]+'\n└── window "Facebook home"\n    (100,100) button "Write something wrong window" [action: click]\ntext "captcha"' for value in snapshots]
            if french:
                labels={'Write something...':'Exprimez-vous...', 'Create post text':'Créer une publication publique...', 'Post':'Publier'}
                for source,destination in labels.items():
                    snapshots=[s.replace('"'+source+'"','"'+destination+'"') for s in snapshots]
            if approval:job.update(task='approval_check',post_url='https://www.facebook.com/groups/test/posts/123/')
            if existing:job.update(task='verify_existing')
            calls=[]
            clipboard=['old clipboard'];page=['https://www.facebook.com/'];address=['']
            class FakeSession:
                async def __aenter__(self):return self
                async def __aexit__(self,*args):return False
                async def initialize(self):return None
                async def call_tool(self,name,args):
                    calls.append((name,args))
                    if name=='Shortcut':
                        shortcut=args['shortcut']
                        if shortcut=='ctrl+v':address[0]=clipboard[0]
                        if shortcut=='enter':page[0]=address[0]
                        if shortcut=='ctrl+c' and not copy_fails:clipboard[0]=page[0]
                    if redirect_after_click and name=='Click':page[0]='https://www.facebook.com/' 
                    text=(snapshots.pop(0) if len(snapshots)>1 else snapshots[0]) if name=='Snapshot' else (json.dumps({'state':'ready','wait_seconds':0}) if name=='ControlStatus' else 'OK')
                    if fail_submit and name=='Click' and args.get('loc')==[100,200]:
                        return SimpleNamespace(isError=True,content=[])
                    return SimpleNamespace(isError=False,content=[SimpleNamespace(type='text',text=text)])
            @contextlib.asynccontextmanager
            async def fake_stdio(params):yield (None,None)
            mcp=ModuleType('mcp');mcp.ClientSession=lambda *args:FakeSession();mcp.StdioServerParameters=lambda **kwargs:kwargs
            client=ModuleType('mcp.client');stdio=ModuleType('mcp.client.stdio');stdio.stdio_client=fake_stdio
            clip=ModuleType('pyperclip');clip.paste=lambda:clipboard[0];clip.copy=lambda text:clipboard.__setitem__(0,text)
            def fake_model(*args,**kwargs):return {'message':{'content':json.dumps(choices.pop(0))}}
            modules={'mcp':mcp,'mcp.client':client,'mcp.client.stdio':stdio,'pyperclip':clip}
            with patch.dict(sys.modules,modules), patch.object(desktop,'os',SimpleNamespace(name='nt',environ=os.environ)), \
                 patch.object(desktop,'foreground',return_value=[0,0,800,600]), patch.object(desktop,'active_root',return_value=1), \
                 fake_readers(), patch('receipts.read_post_receipt',return_value={}), patch.object(desktop,'startup_tip_present',return_value=False), patch.object(desktop,'verify_live_target'), patch.object(desktop,'native_file_targets',return_value=[{'id':0,'role':'edit','name':'file name','text':'edit "File name"','loc':[100,150]}]), patch.object(desktop,'launch_browser'), patch.object(desktop,'wait_profile_windows',new=AsyncMock()), patch.object(desktop,'read_browser_address',return_value=''), patch.object(desktop,'profile_windows',return_value=[]), patch.object(desktop,'focus_profile',new=AsyncMock(return_value=1)), patch.object(desktop.asyncio,'sleep',new=AsyncMock()), \
                 patch.object(desktop,'window_identity',return_value=(123,1.0)), patch.object(desktop,'close_operation_window',return_value=True), patch('net.request_json',side_effect=fake_model),patch('post_comments.finish_post',new=AsyncMock(return_value=confirmed_result) if confirmed_result is not None else post_comments.finish_post) as finish_check,patch('own_content.verify',new=AsyncMock(return_value={})) as receipt_check:
                result=asyncio.run(desktop.execute(job))
                self.assertEqual(receipt_check.await_count,1 if result.get('post_attempted') and not bounded and not desktop.has_verified_post(result,job['url']) else 0)
                if confirmed_result is not None:finish_check.assert_awaited_once()
            self.assertEqual(json.loads((data/'result.json').read_text(encoding='utf-8'))['state'],result['state'])
            db=data/'manager.sqlite3'
            if db.exists():
                from store import Store
                self.last_notices=Store(db).rows('SELECT text FROM outbox')
            else:self.last_notices=[]
            return result,calls

    def test_video_rejection_switches_to_photo_and_submits_once(self):
        result,calls=self.simulate('publish',video_rejection=True)
        self.assertEqual(result['state'],'submitted');self.assertTrue(result['video_fallback_used'])
        self.assertEqual(sum(n=='Click' and a.get('loc')==[100,200] for n,a in calls),1)
        self.assertEqual(sum(n=='Click' and a.get('loc')==[100,170] for n,a in calls),1)
        uploads=[a['text'] for n,a in calls if n=='Type' and a.get('press_enter')]
        self.assertTrue(uploads[0].endswith('clip.mp4'));self.assertTrue(uploads[1].endswith('fallback.png'))
    def test_video_rejection_prepare_only_still_does_not_submit(self):
        result,calls=self.simulate('prepare',video_rejection=True)
        self.assertEqual(result['state'],'prepared');self.assertTrue(result['video_fallback_used'])
        self.assertFalse(any(n=='Click' and a.get('loc')==[100,200] for n,a in calls))
    def test_video_rejection_without_photo_stops_before_post(self):
        result,calls=self.simulate('publish',video_rejection=True,no_fallback_photo=True)
        self.assertEqual(result['state'],'error');self.assertFalse(result['video_fallback_used'])
        self.assertFalse(any(n=='Click' and a.get('loc') in ([100,200],[100,170]) for n,a in calls))
    def test_uncertain_submit_after_photo_fallback_is_not_retried(self):
        result,calls=self.simulate('publish',video_rejection=True,fail_submit=True)
        self.assertEqual(result['state'],'uncertain')
        self.assertEqual(sum(n=='Click' and a.get('loc')==[100,200] for n,a in calls),1)

    def test_bounded_unconfirmed_receipt_never_reposts_or_trusts_model_done(self):
        result,calls=self.simulate('publish',bounded=True)
        self.assertEqual(result['state'],'uncertain')
        self.assertTrue(result['post_attempted'])
        self.assertEqual(sum(n=='Click' and a.get('loc')==[100,200] for n,a in calls),1)

    def test_approval_worker_only_opens_and_verifies_permalink_without_posting(self):
        complete={'state':'submitted','receipt_verified':True,'verification_source':'post_permalink','post_url':'https://www.facebook.com/groups/test/posts/123/','comment_status':'sent'}
        with patch('post_link_check.verify',new=AsyncMock(return_value=complete)) as verify:
            result,calls=self.simulate('publish',approval=True)
        verify.assert_awaited_once();self.assertFalse(result['post_attempted'])
        self.assertFalse(any(name in {'Click','Type'} for name,args in calls))
        self.assertTrue(result['browser_closed'])

    def test_existing_post_check_cannot_enter_new_post_composer(self):
        result,calls=self.simulate('publish',existing=True)
        self.assertFalse(result['post_attempted'])
        self.assertFalse(any(name in {'Click','Type'} for name,args in calls))
        self.assertTrue(result['browser_closed'])

    def test_join_button_does_not_block_available_composer(self):
        from unittest.mock import patch
        with patch('group_posting.membership',return_value='not_joined') as membership:
            result,calls=self.simulate('publish',bounded=True,banner='Tham gia nhóm')
        membership.assert_not_called()
        self.assertTrue(result['post_attempted'])
        self.assertEqual(sum(n=='Click' and a.get('loc')==[100,200] for n,a in calls),1)

    def test_requested_membership_does_not_block_preparation(self):
        with patch('group_posting.membership',return_value='requested') as membership:
            result,calls=self.simulate('prepare',bounded=True,banner='Hủy yêu cầu')
        membership.assert_not_called()
        self.assertEqual(result['state'],'prepared')
        self.assertFalse(result['post_attempted'])

    def test_verified_post_and_comment_do_not_return_to_group_or_management(self):
        receipt={'state':'submitted','receipt_verified':True,'verification_source':'post_permalink','post_url':'https://www.facebook.com/groups/test/posts/123/','comment_status':'sent','post_identity_verified':True,'post_identity':'anonymous'}
        result,calls=self.simulate('publish',confirmed_result=receipt)
        self.assertEqual(result['state'],'submitted');self.assertEqual(result['comment_status'],'sent')
        self.assertEqual(result['post_identity'],'anonymous')
        # One initial navigation only; no return to the group after publishing.
        self.assertEqual(sum(n=='Shortcut' and a.get('shortcut')=='ctrl+v' for n,a in calls),1)
        self.assertEqual(sum(n=='Click' and a.get('loc')==[100,200] for n,a in calls),1)

    def test_prepare_never_presses_post(self):
        result,calls=self.simulate('prepare')
        self.assertEqual(result['state'],'prepared')
        self.assertTrue(result['browser_closed'])
        self.assertFalse(any(n=='Click' and a.get('loc')==[100,200] for n,a in calls))

    def test_french_prepare_fills_caption_without_publishing(self):
        result,calls=self.simulate('prepare',french=True)
        self.assertEqual(result['state'],'prepared')
        self.assertFalse(result['post_attempted'])
        typed=[a for n,a in calls if n=='Type']
        self.assertEqual(typed[0]['text'],'Nội dung chính xác đã duyệt')
        self.assertFalse(typed[0]['press_enter'])
        self.assertFalse(any(n=='Click' and a.get('loc')==[100,200] for n,a in calls))

    def test_publish_uses_frozen_caption_and_submits_once(self):
        result,calls=self.simulate('publish')
        self.assertEqual(result['state'],'submitted')
        self.assertTrue(result['browser_closed'])
        self.assertEqual(sum(n=='Click' and a.get('loc')==[100,200] for n,a in calls),1)
        typed=[a for n,a in calls if n=='Type']
        self.assertEqual(typed[0]['text'],'Nội dung chính xác đã duyệt')
        self.assertFalse(typed[0]['press_enter'])

    def test_error_during_submit_is_uncertain(self):
        result,calls=self.simulate('publish',True)
        self.assertEqual(result['state'],'uncertain')
        self.assertEqual(sum(n=='Click' and a.get('loc')==[100,200] for n,a in calls),1)


    def test_coordinate_response_is_repaired_before_any_click(self):
        result,calls=self.simulate(initial_choices=[{'action':'click','target':[100,100]}])
        self.assertEqual(result['state'],'prepared')
        self.assertEqual(sum(n=='Click' for n,a in calls),1)

    def test_invalid_choices_stop_without_click_or_type(self):
        result,calls=self.simulate(initial_choices=[{'action':'click','target':999},{'action':'click','target':-1}])
        self.assertEqual(result['state'],'error')
        self.assertIn('sau 2 lần',result['detail'])
        self.assertFalse(any(n in {'Click','Type'} for n,a in calls))


    def test_group_approval_banner_is_deferred_to_single_final_report(self):
        result,calls=self.simulate('publish',banner='Đang chờ quản trị viên phê duyệt: 2 bài viết')
        self.assertEqual(result['state'],'submitted');self.assertTrue(result['approval_notice'])
        self.assertEqual(sum(n=='Click' and a.get('loc')==[100,200] for n,a in calls),1)
        self.assertEqual(self.last_notices,[]) # Result is reported by the scheduler, after comments finish.

    def test_new_post_pending_receipt_is_recorded_without_reposting(self):
        result,calls=self.simulate('publish',banner='Đang chờ quản trị viên phê duyệt: 2 bài viết',pending_receipt='Bài viết của bạn đang chờ quản trị viên phê duyệt')
        self.assertEqual(result['state'],'pending')
        self.assertEqual(sum(n=='Click' and a.get('loc')==[100,200] for n,a in calls),1)

    def test_old_banner_is_not_evidence_the_new_post_is_pending(self):
        banner='Đang chờ quản trị viên phê duyệt: 2 bài viết'
        result,calls=self.simulate('publish',banner=banner,pending_receipt=banner)
        self.assertEqual(result['state'],'uncertain')
        self.assertEqual(sum(n=='Click' and a.get('loc')==[100,200] for n,a in calls),1)

    def test_real_posting_restriction_still_blocks_before_click(self):
        result,calls=self.simulate('publish',banner='Bạn không thể đăng bài. Đang chờ quản trị viên phê duyệt')
        self.assertEqual(result['state'],'error')
        self.assertFalse(any(n in {'Click','Type'} for n,a in calls))


    def test_navigation_opens_target_after_mcp_ready(self):
        result,calls=self.simulate()
        self.assertEqual(result['state'],'prepared')
        names=[(n,a.get('shortcut')) for n,a in calls]
        self.assertLess(names.index(('ControlStatus',None)),names.index(('Shortcut','ctrl+v')))
        self.assertLess(names.index(('Shortcut','enter')),next(i for i,(n,a) in enumerate(calls) if n=='Click'))

    def test_redirect_after_composer_click_stops_before_typing(self):
        result,calls=self.simulate(redirect_after_click=True)
        self.assertEqual(result['state'],'error')
        self.assertIn('https://www.facebook.com/',result['detail'])
        self.assertFalse(any(n=='Type' for n,a in calls))

    def test_stale_clipboard_cannot_pass_address_check(self):
        result,calls=self.simulate(copy_fails=True)
        self.assertEqual(result['state'],'error')
        self.assertIn('Không sao chép được',result['detail'])
        self.assertFalse(any(n in {'Click','Type'} for n,a in calls))

    def test_background_window_warning_and_targets_are_excluded(self):
        result,calls=self.simulate(background=True)
        self.assertEqual(result['state'],'prepared')
        tree='UI Tree:\ndesktop\n├── window "Group"\n│   (1,2) button "Write something"\n└── window "Home"\n    (3,4) button "Post"'
        self.assertEqual(len(desktop.parse_targets(tree)),1)
        self.assertNotIn('Home',desktop.active_window_tree(tree))


if __name__=='__main__':unittest.main()
