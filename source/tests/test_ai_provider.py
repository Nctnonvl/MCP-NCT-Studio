import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from store import Store
import ai_provider as ai

class AIProviderTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.s=Store(self.root/'manager.sqlite3');self.key='sk-test-LOCAL-FAKE-ONLY'
        ai.save_config(self.s,{'provider':'xkiro','model':ai.DEFAULT_MODEL,'api_key':self.key})
        self.job={'id':7,'data_dir':str(self.root),'control_ai':{'provider':'xkiro','model':ai.DEFAULT_MODEL}}
        self.payload={'model':'qwen3:8b','messages':[{'role':'system','content':'Return JSON.'},{'role':'user','content':json.dumps({'page':'x'*20000,'targets':[{'id':0,'text':'Create post'}]})}],'format':{'type':'object'}}
    def tearDown(self):self.tmp.cleanup()
    def test_public_config_never_contains_key_and_blank_save_preserves_it(self):
        self.assertNotIn(self.key,json.dumps(ai.config(self.s)))
        ai.save_config(self.s,{'provider':'xkiro','model':ai.DEFAULT_MODEL,'api_key':''})
        self.assertEqual(ai.config(self.s,True)['api_key'],self.key)
    def test_free_only_no_paid_model_or_provider_fallback(self):
        for model in ['anthropic/claude-sonnet','qwen/max','https://evil/free']:
            with self.assertRaises(ValueError):ai.save_config(self.s,{'provider':'xkiro','model':model})
        job={**self.job,'control_ai':{'provider':'xkiro','model':'paid/model'}}
        with patch.object(ai,'request_json') as request,self.assertRaises(ValueError):ai.control_chat(self.payload,job)
        request.assert_not_called()
    def test_cloud_translation_tokens_and_no_secret_in_payload(self):
        reply={'choices':[{'message':{'content':'{"action":"wait","target":0}'},'finish_reason':'stop'}],'usage':{'prompt_tokens':100,'completion_tokens':20,'total_tokens':120}}
        with patch.object(ai,'request_json',return_value=reply) as request:result=ai.control_chat(self.payload,self.job)
        args,kwargs=request.call_args;body=args[1]
        self.assertEqual(args[0],ai.XKIRO+'/chat/completions');self.assertEqual(kwargs['headers']['Authorization'],'Bearer '+self.key)
        self.assertNotIn(self.key,json.dumps(body));self.assertEqual(body['max_tokens'],768);self.assertEqual(body['response_format'],{'type':'json_object'})
        self.assertEqual(len(json.loads(body['messages'][1]['content'])['page']),6000)
        self.assertIn('action',result['message']['content']);summary=ai.usage_summary(self.s);self.assertEqual(summary['total_tokens'],120);self.assertEqual(summary['per_job'][0]['job_id'],7)
    def test_error_redaction_and_no_retry_after_quota_failure(self):
        with patch.object(ai,'request_json',side_effect=RuntimeError('HTTP 429: '+self.key)) as request:
            with self.assertRaises(RuntimeError) as caught:ai.control_chat(self.payload,self.job)
        self.assertNotIn(self.key,str(caught.exception));self.assertIn('không tự chuyển',str(caught.exception));self.assertEqual(request.call_count,1)
    def test_truncation_records_usage_and_stops_before_execution(self):
        reply={'choices':[{'message':{'content':'{'},'finish_reason':'length'}],'usage':{'prompt_tokens':100,'completion_tokens':768,'total_tokens':868}}
        with patch.object(ai,'request_json',return_value=reply),self.assertRaisesRegex(RuntimeError,'bị cắt'):ai.control_chat(self.payload,self.job)
        self.assertEqual(ai.usage_summary(self.s)['total_tokens'],868)
    def test_usage_read_only_keeps_account_identity_out_of_dashboard(self):
        with patch.object(ai,'request_json',return_value={'user':{'email':'private@example.com'},'wallet':{'balance_usd':'10'},'free_tokens':{'used_today':5,'limit_per_day':1000000,'remaining':999995}}):quota=ai.check_connection(self.s)
        self.assertEqual(quota['remaining'],999995);self.assertNotIn('email',json.dumps(quota));self.assertEqual(ai.usage_summary(self.s)['calls'],0)
    def test_existing_local_worker_still_uses_ollama(self):
        with patch('net.request_json',return_value={'message':{'content':'{}'}}) as request:ai.control_chat(self.payload,{'id':1})
        self.assertEqual(request.call_args.args[0],'http://127.0.0.1:11434/api/chat')
if __name__=='__main__':unittest.main()
