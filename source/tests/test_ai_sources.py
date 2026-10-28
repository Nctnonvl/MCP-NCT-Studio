"""Provider management and routing with mocked HTTP; no live API or billing."""
import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from store import Store
import ai_sources as sources
import ai_provider
import content_ai

class SourceTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.s=Store(Path(self.tmp.name)/'manager.sqlite3')
  self.key='FAKE-LOCAL-KEY';self.obj={'name':'Oxion test','base_url':'https://www.oxionai.com/v1','model':'model-test','api_key':self.key}
  self.source=sources.save(self.s,self.obj);self.id=self.source['id']
 def tearDown(self):self.tmp.cleanup()
 def test_public_config_hides_credentials_blank_keeps_key_and_rename_keeps_id(self):
  self.assertNotIn(self.key,json.dumps(sources.catalog(self.s)))
  renamed=sources.save(self.s,{**self.obj,'id':self.id,'name':'Tên mới','api_key':''})
  self.assertEqual(renamed['id'],self.id);self.assertEqual(sources.get(self.s,self.id,True)['api_key'],self.key)
  self.assertEqual(renamed['name'],'Tên mới')
 def test_destination_change_requires_new_key(self):
  with self.assertRaises(ValueError):sources.save(self.s,{**self.obj,'id':self.id,'base_url':'https://other.example/v1','api_key':''})
 def test_delete_used_source_is_rejected_then_unused_can_delete(self):
  ai_provider.save_config(self.s,{'provider':self.id})
  with self.assertRaises(ValueError):sources.delete(self.s,self.id)
  self.s.set('control_ai',{'provider':'ollama'})
  sources.delete(self.s,self.id);self.assertEqual(sources.catalog(self.s),[])
 def test_writer_routes_to_source_without_free_suffix(self):
  content_ai.save_config(self.s,{'writer_provider':self.id})
  response={'choices':[{'message':{'content':'{"body":"Test"}'},'finish_reason':'stop'}],'usage':{'prompt_tokens':4,'completion_tokens':3}}
  with patch('net.request_json',return_value=response) as request:
   self.assertEqual(content_ai.writer_json(self.s,'system',{'brief':'test'}),{'body':'Test'})
   self.assertEqual(request.call_args.args[0],self.obj['base_url']+'/chat/completions')
   self.assertEqual(request.call_args.args[1]['model'],'model-test')
  self.assertNotIn(self.key,json.dumps(content_ai.config(self.s)))
 def test_control_routes_to_source_and_preserves_builtin_settings(self):
  self.s.set('control_ai',{'provider':'xkiro','api_key':content_ai.protect('legacy-key'),'model':ai_provider.DEFAULT_MODEL})
  ai_provider.save_config(self.s,{'provider':self.id})
  with patch('net.request_json',return_value={'choices':[{'message':{'content':'{"action":"done"}'}}]}) as request:
   result=ai_provider.control_chat({'messages':[{'role':'system','content':'test'}]}, {'id':1,'data_dir':self.tmp.name,'control_ai':{'provider':self.id,'model':'model-test'}})
   self.assertIn('done',result['message']['content'])
   self.assertEqual(request.call_args.args[0],self.obj['base_url']+'/chat/completions')
   self.assertNotIn('reasoning_effort',request.call_args.args[1])
  self.assertEqual(content_ai.unprotect(self.s.get('control_ai')['api_key']),'legacy-key')
  self.assertNotIn(self.key,json.dumps(ai_provider.config(self.s)))
 def test_check_lists_models_without_completion_or_quota_guess(self):
  with patch('net.request_json',return_value={'data':[{'id':'model-test'}]}) as request:
   result=sources.check(self.s,self.id)
   self.assertTrue(result['selected_model_listed']);self.assertNotIn('remaining',result)
   self.assertEqual(request.call_count,1);self.assertTrue(request.call_args.args[0].endswith('/models'))
 def test_errors_hide_key_and_invalid_addresses_rejected(self):
  with patch('net.request_json',side_effect=RuntimeError('error '+self.key)):
   with self.assertRaises(RuntimeError) as caught:sources.check(self.s,self.id)
   self.assertNotIn(self.key,str(caught.exception))
  for base in ['http://example.com','https://user:pass@example.com/v1','https://example.com/v1?key=x']:
   with self.assertRaises(ValueError):sources.save(self.s,{**self.obj,'base_url':base})
 def test_http_loopback_sources_and_remote_rejection(self):
  for base in ['http://localhost:8000/v1','http://127.0.0.1:8000/v1','http://[::1]:8000/v1']:
   with self.subTest(base=base):
    row=sources.save(self.s,{**self.obj,'base_url':base})
    with patch('net.request_json',return_value={'data':[{'id':'model-test'}]}) as request:
     self.assertTrue(sources.check(self.s,row['id'])['selected_model_listed'])
     self.assertTrue(request.call_args.kwargs['local_only'])
  for base in ['http://localhost.evil.test/v1','http://192.168.1.5/v1','http://user@localhost/v1','http://localhost/v1?key=x','http://127.0.0.1:99999/v1']:
   with self.subTest(base=base),self.assertRaises(ValueError):sources.save(self.s,{**self.obj,'base_url':base})

 def test_active_generation_blocks_changes(self):
  self.s.set('studio_task',{'status':'running'})
  with self.assertRaises(ValueError):sources.save(self.s,self.obj)
  with self.assertRaises(ValueError):sources.delete(self.s,self.id)
 def test_key_can_be_saved_before_fetching_models(self):
  row=sources.save(self.s,{**self.obj,'model':''})
  with self.assertRaises(ValueError):ai_provider.save_config(self.s,{'provider':row['id']})
