"""Classified image/video pools, fake writers, no scans or Facebook posts."""
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from store import Store
from studio import Studio
import media
import media_library as library


class MixedMediaTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.directory=self.root/'media';self.directory.mkdir();self.s=Store(self.root/'db')
        for name,game in [('v.png','Valorant'),('d1.png','Delta Force'),('d2.png','Delta Force'),('delta.mp4','Delta Force'),('pubg.mp4','PUBG'),('unassigned.png','')]:
            kind='video' if name.endswith('.mp4') else 'image'
            (self.directory/name).write_bytes(b'\x00\x00\x00\x18ftypmp42' if kind=='video' else b'\x89PNG\r\n\x1a\n'+name.encode())
            library.register(self.s,self.directory,{'id':name,'name':name,'kind':kind},game)
        self.gid=self.s.add_group('facebook.com/groups/mixed','Test',link_policy='allow',category='Valorant')
        self.s.enable_group(self.gid,True);library.group_pools(self.s,self.gid,['Valorant'])
        self.studio=Studio(self.s,lambda:{'model':'fake','mode':'publish'},self.directory)

    def test_all_group_chooses_game_images_and_accepts_matching_draft(self):
        self.s.group_category(self.gid,'ALL')
        library.group_pools(self.s,self.gid,['ALL'])
        for game in ['Valorant','Delta Force']:
            with patch('media_library.random.SystemRandom') as rng:
                rng.return_value.choice.return_value=game
                rng.return_value.randint.return_value=1
                chosen=library.choose_media(self.s,self.directory,self.gid)
            self.assertEqual(chosen[0][0]['pool'],game)
            self.assertTrue(all(r['kind']=='image' for r,a in chosen))
            cid=self.s.content('Bài '+game,category=game)
            self.s.targets(cid,'selected',[self.gid])
            with self.s.db() as c:
                post=c.execute('SELECT * FROM contents WHERE id=?',(cid,)).fetchone()
                group=c.execute('SELECT * FROM groups WHERE id=?',(self.gid,)).fetchone()
                self.assertTrue(self.s._eligible(c,post,group))

    def test_all_draft_never_routes_to_specific_game_group(self):
        cid=self.s.content('Bài tổng hợp',category='ALL')
        with self.assertRaises(ValueError):self.s.targets(cid,'selected',[self.gid])
        with patch('media_library.random.SystemRandom') as rng:
            rng.return_value.choice.return_value='Delta Force'
            rng.return_value.randint.return_value=1
            chosen=library.choose_media_pool(self.s,self.directory,'ALL')
        self.assertEqual(chosen[0][0]['pool'],'Delta Force')
        self.assertEqual(chosen[0][0]['kind'],'image')

    def tearDown(self):self.tmp.cleanup()

    def wait(self):
        end=time.monotonic()+6
        while self.studio.lock.locked() and time.monotonic()<end:time.sleep(.01)
        self.assertFalse(self.studio.lock.locked());return self.s.get('studio_task')

    def answer(self):
        return {'title':'Giao lưu game','body':'Có nhiều cách để bắt đầu một buổi trao đổi về game. Mời mọi người chia sẻ nhu cầu và kinh nghiệm của mình nhé.','body_no_link':'Cùng tìm hiểu các lựa chọn game theo nhu cầu riêng. Mình mong được nghe những chia sẻ của mọi người trong cộng đồng.'}

    def test_mixed_game_then_video_is_one_classified_file_without_any_scan(self):
        with patch('media_library.random.SystemRandom') as rng,patch('content_ai.completion') as ai:
            rng.return_value.choice.side_effect=['Delta Force','video']
            selected=library.choose_media_pool(self.s,self.directory,'__all__')
        self.assertEqual([r['id'] for r,a in selected],['delta.mp4']);ai.assert_not_called()
        self.assertEqual(selected[0][1],{'game':'Delta Force','kind':'video','source':'user_assigned'})

    def test_mixed_game_then_images_never_mixes_video_or_other_game(self):
        with patch('media_library.random.SystemRandom') as rng:
            rng.return_value.choice.side_effect=['Delta Force','image'];rng.return_value.randint.return_value=2
            selected=library.choose_media_pool(self.s,self.directory,'__all__')
        self.assertEqual({r['id'] for r,a in selected},{'d1.png','d2.png'})

    def test_video_only_pool_works_and_fixed_photo_count_does_not_add_other_files(self):
        self.assertEqual(library.choose_media_pool(self.s,self.directory,'PUBG',3,None)[0][0]['id'],'pubg.mp4')

    def test_group_scope_never_picks_another_game_even_with_legacy_mixed_flag(self):
        self.assertEqual(library.choose_media(self.s,self.directory,self.gid)[0][0]['pool'],'Valorant')
        with patch('media_library.random.SystemRandom') as rng:
            rng.return_value.choice.side_effect=['Delta Force','video']
            self.assertEqual(library.choose_media(self.s,self.directory,self.gid,mixed_games=True)[0][0]['pool'],'Valorant')

    def test_trash_unassigned_missing_corrupt_and_oversize_are_not_chosen(self):
        library.archive(self.s,['d1.png']);(self.directory/'d2.png').unlink()
        (self.directory/'delta.mp4').write_bytes(b'bad')
        with (self.directory/'pubg.mp4').open('r+b') as f:f.truncate(media.MAX_UPLOAD+1)
        eligible=library.eligible_media(self.s,self.directory,set(library.POOLS))
        self.assertEqual([r['id'] for r,a in eligible],['v.png'])

    def test_single_ai_saves_selected_game_and_one_video_for_both_variants(self):
        with patch.object(self.studio,'chat_json',return_value=self.answer()) as writer,patch('media_library.random.SystemRandom') as rng:
            rng.return_value.choice.return_value='video'
            self.studio.start({'brief':'Giao lưu các game, nhiều lựa chọn.','category':'Delta Force','image_mode':'auto','image_pool':'__all__'})
            task=self.wait()
        self.assertEqual(task['status'],'done');self.assertEqual(task['result']['category'],'Delta Force')
        self.assertEqual(task['result']['automatic_media_kind'],'video')
        saved=self.s.rows('SELECT * FROM contents')[0]
        self.assertEqual([Path(p).name for p in media.paths(saved['media'])],['delta.mp4'])
        self.assertEqual(saved['media'],saved['media_no_link'])
        self.assertEqual(writer.call_args.args[1]['category'],'Delta Force')
        self.assertNotIn('summary',json.dumps(writer.call_args.args[1]['attachments']))
        self.assertEqual(self.s.rows('SELECT * FROM jobs'),[])

    def test_batch_mixed_keeps_selected_game_and_explicit_group_target(self):
        with patch.object(self.studio,'chat_json',return_value=self.answer()),patch('media_library.random.SystemRandom') as rng:
            rng.return_value.choice.side_effect=['Delta Force','video']
            self.studio.draft_groups({'ids':[self.gid],'brief':'Giao lưu các game.','game_mode':'mixed','media_count_mode':'random'})
            task=self.wait()
        self.assertEqual(task['status'],'done')
        saved=self.s.rows('SELECT * FROM contents')[0]
        self.assertEqual(saved['category'],'Valorant')
        self.assertEqual(self.s.rows('SELECT group_id FROM content_targets'),[{'group_id':self.gid}])
        self.assertEqual(self.s.rows('SELECT * FROM jobs'),[])

    def test_video_fallback_uses_the_matching_group_and_post_game(self):
        self.s.group_category(self.gid,'Delta Force')
        cid=self.s.content('Bài về Delta Force',str(self.directory/'delta.mp4'),category='Delta Force')
        ids=self.s.cycle_pool([cid],[self.gid],30,1,1,1,routing_mode='random')
        job=self.s.rows('SELECT * FROM jobs WHERE id=?',(ids[0],))[0]
        self.assertIn(Path(media.paths(job['video_fallback_media'])[0]).name,{'d1.png','d2.png'})

    def test_saving_existing_prose_keeps_declared_game_in_mixed_mode(self):
        files,alt,selected=library.resolve_for_save(self.s,self.directory,{'category':'Valorant','image_mode':'auto','image_pool':'__all__'})
        self.assertEqual(Path(media.paths(files)[0]).name,'v.png')
        self.assertEqual(files,alt)
        self.assertEqual(selected[0][0]['pool'],'Valorant')

    def test_single_autopost_cannot_schedule_a_different_game_for_group(self):
        self.s.set('owner_id',123)
        video=library.eligible_media(self.s,self.directory,{'Delta Force'},'video')
        with patch.object(self.studio,'chat_json',return_value=self.answer()),patch.object(library,'choose_media_pool',return_value=video):
            self.studio.start({'brief':'Giao lưu nhiều game.','category':'Valorant','image_mode':'auto','image_pool':'__all__','autopost':True,'horizon':1})
            task=self.wait()
        self.assertEqual(task['status'],'error')
        self.assertEqual(self.s.rows('SELECT * FROM jobs'),[])


if __name__=='__main__':unittest.main()
