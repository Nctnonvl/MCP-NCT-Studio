import asyncio,json,tempfile,unittest,sys
from pathlib import Path
from unittest.mock import patch,AsyncMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from store import Store
import post_comments
class CommentSettingsTests(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.s=Store(Path(self.tmp.name)/'db');self.g=self.s.add_group('facebook.com/groups/test','test',link_policy='allow');self.s.enable_group(self.g,True);self.cid=self.s.content('body https://example.com',body_no_link='body')
 def tearDown(self):self.tmp.cleanup()
 def test_freezes_comment_and_blocks_group_that_forbids_it(self):
  self.s.set_comment_settings(self.cid,'always','https://example.com','@tester')
  ids=self.s.plan(self.cid,30);row=self.s.rows('SELECT * FROM jobs WHERE id=?',(ids[0],))[0]
  self.assertEqual(row['comment_text'],'https://example.com');self.assertIn('@tester',row['comment_fallback']);self.assertGreater(len(row['comment_fallback']),len('@tester'))
  self.s.set_comment_policy(self.g,'deny');self.assertEqual(self.s.rows('SELECT state FROM jobs WHERE id=?',(ids[0],))[0]['state'],'cancelled')
  with self.s.db() as c:self.s._freeze_comments(c,ids[0],self.cid,self.g)
  self.assertEqual(self.s.rows('SELECT comment_text FROM jobs WHERE id=?',(ids[0],))[0]['comment_text'],'')
 def test_custom_fallback_sentence_is_frozen(self):
  text='Bạn tìm mình trên TikTok @tester để trao đổi nhé.'
  self.s.set_comment_settings(self.cid,'always','https://example.com','@tester',text)
  ids=self.s.plan(self.cid,30)
  self.assertEqual(self.s.rows('SELECT comment_fallback FROM jobs WHERE id=?',(ids[0],))[0]['comment_fallback'],text)
 def test_bad_tiktok_or_non_http_link_rejected(self):
  for link,tiktok in [('javascript:alert(1)',''),('https://example.com','someone'),('https://example.com','@a/b')]:
   with self.assertRaises(ValueError):self.s.set_comment_settings(self.cid,'always',link,tiktok)

class CommentSendTests(unittest.IsolatedAsyncioTestCase):
 async def run_case(self,confirmed=False,rejected=False,prior=False,posting='default',identity='follow',editor_name='write a comment',temporary=False,direct_failure=False,delayed=False,blocked=False,prior_attempts=0):
  with tempfile.TemporaryDirectory() as d:
   Path(d,'work').mkdir();link='https://www.facebook.com/groups/test/posts/123/'
   job={'id':1,'data_dir':d,'url':'https://www.facebook.com/groups/test/','body':'This is the exact caption of our new post','comment_text':'https://example.com','comment_policy':'allowed','comment_fallback':'@tester','posting_identity':posting,'comment_identity':identity}
   if prior:Path(d,'work/comment-1.json').write_text(json.dumps({'status':'uncertain','detail':'previous attempt'}))
   if prior_attempts:
    event={'kind':'link','content':job['comment_text'],'baseline':0,'at':1}
    Path(d,'work/comment-1.json').write_text(json.dumps({**event,'status':'uncertain','attempted':True,'attempts':[event]*prior_attempts}),encoding='utf-8')
   target={'id':0,'name':editor_name,'role':'edit','loc':[10,10],'text':'edit "write a comment"'}
   if direct_failure:target['draft_text']=job['comment_text']
   base={'caption_seen':True,'timestamp':target,'editors':[target],'outside_texts':[]}
   after={**base,'outside_texts':['https://example.com'] if confirmed else []}
   calls=[];sent=[0];checks=[0]
   async def tool(name,args):
    calls.append((name,args))
    if name=='Type':sent[0]+=1;checks[0]=0
    return None,''
   async def observe(dom):return 'Không thể đăng bình luận' if direct_failure else 'Đã xảy ra lỗi. Chúng tôi gặp sự cố khi hoàn tất yêu cầu của bạn. Vui lòng thử lại.' if temporary else 'Links are not allowed' if rejected else ''
   def context(*args):
    if not sent[0]:return base
    checks[0]+=1
    if rejected and sent[0]>=2:return {**base,'outside_texts':['@tester']}
    if confirmed or (delayed and checks[0]>=2) or (direct_failure and sent[0]>=2):return {**base,'outside_texts':[job['comment_text']]}
    return base
   feedback={'kind':'blocked' if blocked else 'not_sent' if direct_failure else 'temporary','message':'Facebook chưa gửi bình luận.','dismiss':None}
   with patch('desktop.foreground'),patch('desktop.verify_live_target'),patch.object(post_comments,'read_error',return_value=feedback),patch.object(post_comments,'own_post_context',side_effect=context),patch.object(post_comments.asyncio,'sleep',new=AsyncMock()):
    result=await post_comments.finish_post(tool,observe,AsyncMock(return_value=link),1,job,{},True)
   ledger=Path(d,'work/comment-1.json')
   self.last_ledger=json.loads(ledger.read_text(encoding="utf-8")) if ledger.exists() else {}
   return result,calls
 async def test_confirmed_comment_is_success(self):
  result,calls=await self.run_case(confirmed=True);self.assertEqual(result['comment_status'],'sent');self.assertEqual(len(calls),1)
 async def test_late_confirmation_is_success_without_resending(self):
  result,calls=await self.run_case(delayed=True)
  self.assertEqual(result['comment_status'],'sent');self.assertEqual(len(calls),1)
 async def test_generic_facebook_error_stops_after_three_attempts(self):
  result,calls=await self.run_case(temporary=True)
  self.assertEqual(result['comment_status'],'failed');self.assertEqual(sum(n=='Type' for n,a in calls),3)
  self.assertTrue(result['comment_retry_exhausted'])
 async def test_explicit_not_sent_with_retained_draft_retries_once(self):
  result,calls=await self.run_case(direct_failure=True)
  self.assertEqual(result['comment_status'],'sent');self.assertEqual(sum(n=='Type' for n,a in calls),2)
  self.assertEqual(len(self.last_ledger['attempts']),2)
 async def test_blocking_message_never_retries_even_with_retained_draft(self):
  result,calls=await self.run_case(direct_failure=True,blocked=True)
  self.assertEqual(result['comment_status'],'uncertain');self.assertEqual(len(calls),1)
 async def test_anonymous_comment_is_allowed_when_editor_identity_matches(self):
  result,calls=await self.run_case(confirmed=True,posting='anonymous',editor_name='bình luận dưới tên người tham gia ẩn danh')
  self.assertEqual(result['comment_status'],'sent');self.assertEqual(len(calls),1)
 async def test_required_hidden_identity_never_sends_as_named_profile(self):
  result,calls=await self.run_case(identity='hidden',editor_name='bình luận dưới tên my profile')
  self.assertEqual(result['comment_status'],'failed');self.assertEqual(calls,[])
 async def test_unknown_outcome_rechecks_then_stops_at_three(self):
  result,calls=await self.run_case();self.assertEqual(result['comment_status'],'failed');self.assertEqual(sum(n=='Type' for n,a in calls),3);self.assertEqual(len(self.last_ledger['attempts']),3)
 async def test_explicit_link_rejection_sends_one_tiktok_fallback(self):
  result,calls=await self.run_case(rejected=True);self.assertEqual(result['comment_status'],'fallback_sent');self.assertEqual(sum(n=='Type' for n,a in calls),2);self.assertEqual(calls[-1][1]['text'],'@tester')
 async def test_ledger_prevents_second_comment(self):
  result,calls=await self.run_case(prior=True);self.assertEqual(result['comment_status'],'uncertain');self.assertEqual(calls,[])
 async def test_restart_retains_budget_only_one_more_send_after_two_attempts(self):
  result,calls=await self.run_case(prior_attempts=2)
  self.assertEqual(result['comment_status'],'failed')
  self.assertEqual(sum(n=='Type' for n,a in calls),1)
  self.assertEqual(len(self.last_ledger['attempts']),3)
 async def test_crash_after_third_attempt_never_sends_fourth(self):
  result,calls=await self.run_case(prior_attempts=3)
  self.assertEqual(result['comment_status'],'failed');self.assertTrue(result['comment_retry_exhausted'])
  self.assertEqual(calls,[])
if __name__=='__main__':unittest.main()
