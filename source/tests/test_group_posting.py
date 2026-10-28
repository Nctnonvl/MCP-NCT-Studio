import unittest
from unittest.mock import AsyncMock,patch
from group_posting import membership,newest_first
class MembershipTests(unittest.TestCase):
 def test_join_control_is_checked_only_in_group_header(self):
  share={'role':'button','name':'chia sẻ nhóm','loc':[1000,300]}
  join={'role':'button','name':'tham gia nhóm','loc':[850,300]}
  self.assertEqual(membership([share,join]),'not_joined')
  self.assertEqual(membership([share,{**join,'name':'đã tham gia'}]),'joined')
  self.assertEqual(membership([share,{**join,'name':'hủy yêu cầu'}]),'requested')
  self.assertEqual(membership([share,{**join,'loc':[850,700]}]),'unknown')
class SortTests(unittest.IsolatedAsyncioTestCase):
 async def test_only_selects_new_posts_from_observed_sort_menu(self):
  first='UI Tree:\n(320,846) button "sắp xếp bảng feed nhóm theo Phù hợp nhất" [action: click]'
  menu='UI Tree:\n(300,800) menu item "Phù hợp nhất" [action: click]\n(300,850) menu item radio button "Bài viết mới Hiển thị bài viết gần đây đầu tiên" [action: click]'
  tool=AsyncMock();observe=AsyncMock(side_effect=[menu,'new feed'])
  with patch('desktop.verify_live_target'):
   text,selected=await newest_first(tool,observe,first,1,lambda _:None)
  self.assertTrue(selected);self.assertEqual(text,'new feed');self.assertEqual(tool.await_count,2)
  self.assertEqual(tool.await_args_list[-1].args,('Click',{'loc':[300,850]}))
 async def test_no_sort_control_never_clicks_unrelated_post(self):
  tool=AsyncMock();observe=AsyncMock()
  text,selected=await newest_first(tool,observe,'UI Tree:\n(100,100) button "Xem thêm" [action: click]',1,lambda _:None)
  self.assertFalse(selected);tool.assert_not_awaited();observe.assert_not_awaited()


class SortRoleTests(unittest.TestCase):
 def test_composite_aria_radio_menu_role_matches_native_uia(self):
  from posting_identity import live_role_matches
  from types import SimpleNamespace
  self.assertTrue(live_role_matches(SimpleNamespace(ControlTypeName='MenuItemControl'),'menu item radio button'))
  self.assertTrue(live_role_matches(SimpleNamespace(ControlTypeName='RadioButtonControl'),'menu item radio button'))
  self.assertFalse(live_role_matches(SimpleNamespace(ControlTypeName='ButtonControl'),'menu item radio button'))
