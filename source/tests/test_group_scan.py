import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from store import Store
from group_scan import joined_cards,import_found,game_from_name,GroupScanner

class GroupScanTests(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.s=Store(Path(self.tmp.name)/'db')
 def tearDown(self):self.tmp.cleanup()
 def card(self,url='https://www.facebook.com/groups/123/?locale=fr_FR',name='Valorant France',view='Afficher le groupe',text='Dernière visite'):
  return {'text':text,'links':[{'url':url,'name':name},{'url':url,'name':view}]}
 def test_only_joined_cards_and_real_group_home_urls(self):
  good=self.card()
  pending=self.card(text='Demande d’adhésion envoyée')
  pending2=self.card(view='Mettre à jour les réponses')
  post=self.card(url='https://www.facebook.com/groups/123/posts/456/')
  foreign=self.card(url='https://evil.example/groups/123/')
  self.assertEqual(joined_cards([good,pending,pending2,post,foreign,good]),[{'url':'https://www.facebook.com/groups/123/','name':'Valorant France','category':'Valorant'}])
 def test_import_dedupes_hosts_queries_and_preserves_existing_settings_and_deleted(self):
  gid=self.s.add_group('facebook.com/groups/123','My custom name',rules='My rules',category='CS2',link_policy='allow');self.s.enable_group(gid,True)
  before=self.s.rows('SELECT * FROM groups WHERE id=?',(gid,))[0]
  deleted=self.s.add_group('facebook.com/groups/deleted','Old',link_policy='allow');self.s.delete_group(deleted)
  rows=[{'url':'https://m.facebook.com/groups/123/?x=1','name':'Valorant renamed'},{'url':'https://facebook.com/groups/deleted','name':'Old'},{'url':'https://facebook.com/groups/999','name':'The Isle Việt Nam'}]
  result=import_found(self.s,rows+rows)
  self.assertEqual((result['added'],result['duplicates'],result['found']),(1,2,3))
  self.assertEqual(self.s.rows('SELECT * FROM groups WHERE id=?',(gid,))[0],before)
  self.assertEqual(self.s.rows('SELECT deleted FROM groups WHERE id=?',(deleted,))[0]['deleted'],1)
  new=self.s.rows("SELECT * FROM groups WHERE url='https://www.facebook.com/groups/999/'")[0]
  self.assertEqual((new['category'],new['enabled'],new['link_policy']),('The isle',0,'unknown'))
  self.assertEqual(import_found(self.s,rows)['added'],0)
 def test_same_name_different_groups_are_not_merged(self):
  rows=[{'url':f'https://facebook.com/groups/{i}','name':'The Isle Việt Nam'} for i in (1,2)]
  self.assertEqual(import_found(self.s,rows)['added'],2)
 def test_verified_alias_is_remembered_and_never_creates_duplicate(self):
  gid=self.s.add_group('facebook.com/groups/123','The Isle Việt Nam')
  row={'url':'https://facebook.com/groups/123','name':'The Isle Việt Nam','aliases':['https://www.facebook.com/groups/theislevietnam/']}
  self.assertEqual(import_found(self.s,[row])['duplicates'],1)
  self.assertEqual(import_found(self.s,[{'url':row['aliases'][0],'name':row['name']}])['duplicates'],1)
  self.assertEqual(len(self.s.rows('SELECT id FROM groups')),1)
 def test_unresolved_same_name_group_is_held_for_review(self):
  result=import_found(self.s,[{'url':'https://facebook.com/groups/unknown','name':'The Isle Việt Nam','review_only':True}])
  self.assertEqual(result['added'],0);self.assertEqual(len(result['needs_review']),1)
 def test_ambiguous_card_is_skipped(self):
  card=self.card();card['links'].append({'url':'https://facebook.com/groups/other','name':'Other'})
  self.assertEqual(joined_cards([card]),[])
 def test_game_inference_does_not_invent_unknown_game(self):
  for name,game in [('CỘNG ĐỒNG PUBG PC','PUBG'),('Delta Force Việt Nam','Delta Force'),('Liên Minh Huyền Thoại','LOL'),('CS:GO - VN','CS2'),('Gaming Club','')]:self.assertEqual(game_from_name(name),game)
 def test_scan_and_posting_cannot_run_together(self):
  gid=self.s.add_group('facebook.com/groups/1',link_policy='allow');self.s.enable_group(gid,True)
  cid=self.s.content('A caption');ids=self.s.plan(cid,30);self.s.approve(ids);self.s.set('running',True)
  self.s.set('group_scan',{'status':'running'})
  self.assertIsNone(self.s.claim())
  with self.assertRaises(ValueError):GroupScanner(self.s,self.tmp.name).start()
 def test_start_pauses_queue_before_background_work(self):
  scanner=GroupScanner(self.s,self.tmp.name);self.s.set('running',True)
  with patch('group_scan.threading.Thread') as thread:
   scanner.start();thread.return_value.start.assert_called_once()
  self.assertFalse(self.s.get('running'));self.assertTrue(self.s.get('paused_by_user'))
  self.assertEqual(self.s.get('group_scan')['status'],'running')
 def test_each_scan_uses_a_fresh_process_instead_of_reusing_com_threads(self):
  scanner=GroupScanner(self.s,self.tmp.name)
  with patch('group_scan.subprocess.Popen') as spawn:
   spawn.return_value.poll.return_value=0
   scanner.monitor();scanner.monitor()
  self.assertEqual(spawn.call_count,2)
  self.assertTrue(spawn.call_args.args[0][1].endswith('group_scan.py'))
  self.assertEqual(spawn.call_args.args[0][2],'--worker')

if __name__=='__main__':unittest.main()
