"""Simulated Facebook progress/toasts; no Windows input or network."""
import unittest,tempfile
from pathlib import Path
from unittest.mock import patch,AsyncMock
from types import SimpleNamespace
from publication_wait import busy_text,wait_submission,wait_video_ready

READY={'complete':True,'composer':True,'enabled':True,'busy':False,'notices':''}
SENT={**READY,'composer':False}

class NativeSurfaceTests(unittest.TestCase):
 def test_native_toast_outside_composer_is_read_and_upload_progress_blocks(self):
  from publication_wait import read_surface
  def node(role,name='',**kw):return SimpleNamespace(ControlTypeName=role,Name=name,AriaRole='',IsOffscreen=False,**kw)
  root=node('WindowControl');dialog=node('GroupControl');dialog.AriaRole='dialog'
  edit=node('EditControl','Create post');button=node('ButtonControl','Gửi',IsEnabled=True)
  progress=node('ProgressBarControl');toast=node('TextControl','Bài viết của bạn đang chờ phê duyệt')
  entries=[(root,()),(dialog,(root,)),(edit,(root,dialog)),(button,(root,dialog)),(progress,(root,dialog)),(toast,(root,))]
  com=SimpleNamespace(CoInitialize=lambda:None,CoUninitialize=lambda:None)
  uia=SimpleNamespace(ControlFromHandle=lambda _:root)
  with patch.dict('sys.modules',{'comtypes':com,'windows_mcp.uia':uia}),patch('windows_mcp.uia',uia,create=True),patch('desktop.foreground'),patch('uia_snapshot.capture',return_value=(entries,True)):
   surface=read_surface(1)
  self.assertTrue(surface['composer']);self.assertTrue(surface['enabled']);self.assertTrue(surface['busy'])
  self.assertIn('chờ phê duyệt',surface['notices'])

class PublicationTests(unittest.IsolatedAsyncioTestCase):
 def test_busy_caption_is_not_a_progress_indicator(self):
  self.assertFalse(busy_text('đang xử lý','đang xử lý'))
  self.assertTrue(busy_text('Video của bạn đang được xử lý'))

 async def test_enabled_button_does_not_override_video_processing(self):
  surfaces=[{**READY,'busy':True},READY,READY]
  with patch('publication_wait.read_surface',side_effect=surfaces),patch('publication_wait.asyncio.sleep',new=AsyncMock()) as sleep:
   await wait_video_ready(AsyncMock(return_value='caption'),1,{'body':'caption'},lambda _:None)
  self.assertEqual(sleep.await_count,2)

 async def test_disabled_button_never_ready(self):
  with patch('publication_wait.read_surface',return_value={**READY,'enabled':False}),patch('publication_wait.asyncio.sleep',new=AsyncMock()),patch('publication_wait.time.monotonic',side_effect=[0,0,0,481]):
   with self.assertRaisesRegex(RuntimeError,'chưa bấm Đăng'):
    await wait_video_ready(AsyncMock(return_value=''),1,{'body':'caption'},lambda _:None)

 async def test_native_pending_toast_is_preserved_without_refresh(self):
  notice='Bài viết của bạn đang chờ quản trị viên phê duyệt'
  job={'body':'unique caption'}
  with patch('publication_wait.read_surface',return_value={**SENT,'notices':notice}):
   await wait_submission(AsyncMock(return_value='feed'),1,job,'',lambda _:None,video=True)
  self.assertEqual(job['submit_pending_receipt'],notice)

 async def test_old_pending_toast_cannot_mark_new_send_pending(self):
  notice='Bài viết của bạn đang chờ quản trị viên phê duyệt'
  job={'body':'unique caption'}
  with patch('publication_wait.read_surface',return_value={**SENT,'notices':notice}),patch('publication_wait.asyncio.sleep',new=AsyncMock()),patch('publication_wait.time.monotonic',side_effect=[0,0,0,4,4]):
   await wait_submission(AsyncMock(return_value=''),1,job,notice,lambda _:None)
  self.assertNotIn('submit_pending_receipt',job)

 async def test_still_processing_is_not_refreshed_or_assumed_sent(self):
  with patch('publication_wait.read_surface',return_value={**SENT,'notices':'Uploading video'}),patch('publication_wait.asyncio.sleep',new=AsyncMock()),patch('publication_wait.time.monotonic',side_effect=[0,0,181]):
   with self.assertRaisesRegex(RuntimeError,'không gửi lại'):
    await wait_submission(AsyncMock(return_value=''),1,{'body':'caption'},'',lambda _:None,video=True)
