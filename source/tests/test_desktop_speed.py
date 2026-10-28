import unittest
from types import SimpleNamespace
from unittest.mock import patch, Mock, AsyncMock
import desktop


class AddressTests(unittest.TestCase):
    def test_only_facebook_toolbar_addresses_are_accepted(self):
        self.assertEqual(desktop.browser_address('www.facebook.com/groups/123/'), 'https://www.facebook.com/groups/123/')
        self.assertEqual(desktop.browser_address('https://www.facebook.com/groups/123/posts/456/'), 'https://www.facebook.com/groups/123/posts/456/')
        for value in ('', 'facebook.com.evil.test/groups/123/', 'https://evil.test/facebook.com', 'https://user@facebook.com/', 'javascript:alert(1)', 'https://facebook.com:443/', 'facebook.com/groups/1 with space', 'https://[bad'):
            with self.subTest(value=value):self.assertEqual(desktop.browser_address(value), '')

    def read(self, control, foreground=None):
        window=Mock();window.EditControl.return_value=control
        uia=SimpleNamespace(ControlFromHandle=Mock(return_value=window))
        com=SimpleNamespace(CoInitialize=Mock(),CoUninitialize=Mock())
        with patch.dict('sys.modules', {'comtypes':com,'windows_mcp':SimpleNamespace(uia=uia),'windows_mcp.uia':uia}), patch.object(desktop,'foreground',foreground or Mock()) as guard:
            result=desktop.read_browser_address(123)
        return result,window,com,guard

    def test_reads_bound_toolbar_and_rechecks_foreground(self):
        control=Mock(HasKeyboardFocus=False);control.Exists.return_value=True
        control.GetValuePattern.return_value.Value='www.facebook.com/groups/123/'
        result,window,com,guard=self.read(control)
        self.assertEqual(result,'https://www.facebook.com/groups/123/')
        window.EditControl.assert_called_once_with(AutomationId='view_1017',searchDepth=12)
        self.assertEqual(guard.call_count,2)
        com.CoUninitialize.assert_called_once()

    def test_editing_address_is_not_trusted(self):
        control=Mock(HasKeyboardFocus=True);control.Exists.return_value=True
        result,_,com,_=self.read(control)
        self.assertEqual(result,'');control.GetValuePattern.assert_not_called()
        com.CoUninitialize.assert_called_once()

    def test_missing_uia_value_allows_clipboard_fallback(self):
        control=Mock(HasKeyboardFocus=False);control.Exists.return_value=True
        control.GetValuePattern.side_effect=RuntimeError('unavailable')
        result,_,com,_=self.read(control)
        self.assertEqual(result,'');com.CoUninitialize.assert_called_once()

    def test_window_switch_is_not_swallowed(self):
        control=Mock(HasKeyboardFocus=False);control.Exists.return_value=True
        control.GetValuePattern.return_value.Value='https://facebook.com/groups/123/'
        with self.assertRaisesRegex(RuntimeError,'switched'):
            self.read(control,Mock(side_effect=[None,RuntimeError('switched')]))

    def test_chrome_omnibox_id_fallback(self):
        missing=Mock();missing.Exists.return_value=False
        chrome=Mock();chrome.Exists.return_value=True
        window=Mock();window.EditControl.side_effect=[missing,chrome]
        self.assertIs(desktop.toolbar_address_control(window),chrome)
        self.assertEqual(window.EditControl.call_args_list[-1].kwargs['AutomationId'],'view_1001')

    def test_installed_chrome_toolbar_id_1012(self):
        missing=Mock();missing.Exists.return_value=False
        chrome=Mock();chrome.Exists.return_value=True
        window=Mock();window.EditControl.side_effect=[missing,missing,chrome]
        self.assertIs(desktop.toolbar_address_control(window),chrome)
        self.assertEqual(window.EditControl.call_args_list[-1].kwargs['AutomationId'],'view_1012')


class StartupTests(unittest.IsolatedAsyncioTestCase):
    async def test_ready_window_does_not_sleep(self):
        with patch.object(desktop,'profile_windows',return_value=[1,2]),patch.object(desktop.asyncio,'sleep',new_callable=AsyncMock) as sleep:
            await desktop.wait_profile_windows('data',[1])
            sleep.assert_not_awaited()

    async def test_waits_for_new_window_not_existing_profile(self):
        with patch.object(desktop,'profile_windows',side_effect=[[1],[1,2]]),patch.object(desktop.asyncio,'sleep',new_callable=AsyncMock) as sleep:
            await desktop.wait_profile_windows('data',[1])
            sleep.assert_awaited_once_with(.4)

    async def test_startup_wait_is_bounded(self):
        with patch.object(desktop,'profile_windows',return_value=[1]),patch.object(desktop.time,'monotonic',side_effect=[0,16]):
            await desktop.wait_profile_windows('data',[1])


if __name__=='__main__':unittest.main()
