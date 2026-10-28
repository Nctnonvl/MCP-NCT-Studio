import asyncio,json,sys,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import desktop

def response(state=None,error=None):
    text=error if error is not None else json.dumps({'state':state,'wait_seconds':10 if state=='user' else 0})
    return SimpleNamespace(isError=error is not None,content=[SimpleNamespace(type='text',text=text)])

class MCPControlTests(unittest.TestCase):
    def test_initial_control_wait_uses_only_read_only_status(self):
        session=SimpleNamespace(call_tool=AsyncMock(side_effect=[response('user'),response('ready')]))
        reports=[]
        with patch.object(desktop.asyncio,'sleep',new=AsyncMock()):asyncio.run(desktop.wait_initial_control(session,reports.append))
        self.assertEqual([c.args for c in session.call_tool.call_args_list],[('ControlStatus',{}),('ControlStatus',{})])
        self.assertTrue(any('10 giây' in x for x in reports))
    def test_unavailable_control_stops_without_attempting_input(self):
        session=SimpleNamespace(call_tool=AsyncMock(return_value=response('unavailable')))
        with self.assertRaisesRegex(RuntimeError,'unavailable'):asyncio.run(desktop.wait_initial_control(session,lambda _:None))
        self.assertEqual(session.call_tool.call_count,1)
    def test_physical_input_timeout_is_bounded(self):
        session=SimpleNamespace(call_tool=AsyncMock(return_value=response('user')))
        with self.assertRaisesRegex(RuntimeError,'nhường quyền'):asyncio.run(desktop.wait_initial_control(session,lambda _:None,timeout=0))
        self.assertEqual(session.call_tool.call_count,1)
    def test_original_mcp_errors_remain_visible(self):
        detail=desktop.mcp_error('Shortcut',response(error='{"code":"USER_CONTROL","status":{"state":"user","wait_seconds":9}}'))
        self.assertIn('USER_CONTROL',detail);self.assertIn('10 giây',detail);self.assertIn('Shortcut',detail)
        self.assertIn('Validation error: unknown key',desktop.mcp_error('Shortcut',response(error='Validation error: unknown key')))
if __name__=='__main__':unittest.main()
