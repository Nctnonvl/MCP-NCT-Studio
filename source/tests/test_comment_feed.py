"""Comment in the matched group-feed post without opening its timestamp modal."""
import sys,tempfile,unittest,json
from pathlib import Path
from unittest.mock import AsyncMock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import post_comments

class FeedCommentTests(unittest.IsolatedAsyncioTestCase):
 async def run_case(self,foreign=False,folded=False,prior=False,reconciled=False):
  with tempfile.TemporaryDirectory() as data:
   Path(data,'work').mkdir()
   group='https://www.facebook.com/groups/test/';permalink=group+'posts/123/'
   job={'id':1,'data_dir':data,'body':'Exact post caption to match in group feed','url':group,'posting_identity':'anonymous','comment_identity':'follow','comment_text':'https://example.com','comment_policy':'allowed'}
   timestamp={'role':'link','name':'vừa xong','url':permalink,'loc':[10,10],'text':'link "Vừa xong"'}
   editor={'role':'edit','name':'bình luận dưới tên người tham gia ẩn danh','loc':[20,50],'text':'edit "Bình luận dưới tên Người tham gia ẩn danh"'}
   expand={'role':'button','name':'xem thêm','loc':[20,30],'text':'button "Xem thêm"'}
   base={'timestamp':timestamp,'caption_seen':True,'editors':[editor],'outside_texts':[]}
   after={**base,'outside_texts':[job['comment_text']]}
   contexts=[base,base,base,after]
   if reconciled:contexts=[after,after,after]
   if folded:contexts=[{**base,'caption_seen':False,'expand':[expand]},base,base,base,after]
   if prior:Path(data,'work/comment-1.json').write_text(json.dumps({'status':'uncertain','attempted':True,'content':job['comment_text'] if reconciled else '', 'baseline':0}),encoding='utf-8')
   location=AsyncMock(side_effect=[group,'https://www.facebook.com/groups/other/']) if foreign else AsyncMock(return_value=group)
   tool=AsyncMock();observe=AsyncMock(return_value='')
   with patch('desktop.foreground'),patch('desktop.verify_live_target'),patch('post_comments.own_post_context',side_effect=contexts),patch('post_comments.asyncio.sleep',new=AsyncMock()):
    result=await post_comments.finish_post(tool,observe,location,42,job,{},True)
   return result,tool.await_args_list
 async def test_types_in_feed_without_opening_post_modal(self):
  result,calls=await self.run_case()
  self.assertEqual(result['comment_status'],'sent');self.assertEqual(result['comment_surface'],'group_feed')
  self.assertEqual(result['post_url'],'https://www.facebook.com/groups/test/posts/123/')
  self.assertEqual([c.args[0] for c in calls],['Type'])
 async def test_leaving_group_prevents_comment(self):
  result,calls=await self.run_case(foreign=True)
  self.assertEqual(result['comment_status'],'failed');self.assertEqual(calls,[])
 async def test_expands_only_matched_post_before_commenting(self):
  result,calls=await self.run_case(folded=True)
  self.assertEqual(result['comment_status'],'sent')
  self.assertEqual([c.args[0] for c in calls],['Click','Type']);self.assertEqual(calls[0].args[1]['loc'],[20,30])
 async def test_feed_path_does_not_repeat_uncertain_comment(self):
  result,calls=await self.run_case(prior=True)
  self.assertEqual(result['comment_status'],'uncertain');self.assertEqual(calls,[])

 async def test_existing_uncertain_comment_is_confirmed_readonly_without_resending(self):
  result,calls=await self.run_case(prior=True,reconciled=True)
  self.assertEqual(result['comment_status'],'sent');self.assertEqual(calls,[])

class FeedScopeTests(unittest.TestCase):
 def test_wrong_post_href_and_different_caption_are_rejected(self):
  job={'url':'https://www.facebook.com/groups/test/'}
  ctx={'caption_seen':True,'timestamp':{'url':job['url']+'posts/999/','name':'vừa xong'}}
  self.assertFalse(post_comments.page_matches(job['url'],job,ctx,job['url']+'posts/123/',True))
  self.assertFalse(post_comments.page_matches(job['url'],job,{**ctx,'caption_seen':False},job['url']+'posts/999/',True))

if __name__=='__main__':unittest.main()


class PlaceholderFeedLinkTests(unittest.TestCase):
 def test_verified_feed_accepts_group_placeholder_but_rejects_other_group(self):
  from post_comments import page_matches
  group='https://www.facebook.com/groups/test/'
  context={'caption_seen':True,'timestamp':{'url':group+'?tracking=ignored','name':'50 phút trước'}}
  self.assertTrue(page_matches(group,{'url':group},context,'',True))
  self.assertFalse(page_matches(group,{'url':group},{**context,'timestamp':{'url':group.replace('/test/','/other/')}},'',True))
  self.assertFalse(page_matches(group,{'url':group},context,'',False))
