"""Vocabulary and voice checks, with mocked AI only; never posts to Facebook."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import writing_policy
from test_studio import StudioTests
from test_batch_ai import BatchAITests


class PolicyTests(unittest.TestCase):
    def test_word_boundaries_and_all_output_fields(self):
        for term in ('CHEAT', 'hack', 'aimbot', 'ESP', 'wallhack', 'gian lận', 'aim  bot'):
            for position in range(4):
                values = ['Bài viết', 'Mời anh em trao đổi.', 'Cùng tìm hiểu nhé.', 'Discord']
                values[position] = 'Không dùng ' + term
                self.assertTrue(writing_policy.issue(*values), (term, position))
        self.assertFalse(writing_policy.issue('Respawn', 'Especially useful', 'Trao đổi nhé.'))

    def test_examples_are_style_only_and_sample_is_available(self):
        context = {}
        prompt = writing_policy.apply('System.', context)
        self.assertIn('KHÔNG là dữ kiện', prompt)
        self.assertIn('Thua quá', ' '.join(context['voice_examples']))

    def test_game_examples_do_not_leak_to_other_categories(self):
        for category, expected in [('Delta Force', 'Cày đồ'), ('The isle', 'Khủng long'), ('Valorant', 'Bắn Valorant'), ('LOL','Đánh LOL'), ('PUBG','Bắn PUBG')]:
            for context in ({'category': category}, {'group': {'category': category}}):
                writing_policy.apply('System.', context)
                examples = ' '.join(context['game_voice_examples'])
                if expected:
                    self.assertIn(expected, examples)
                else:
                    self.assertEqual(examples, '')

    def test_fps_verbs_are_checked_in_title_body_and_alternative(self):
        for game in ('Valorant','PUBG','CS2','Delta Force'):
            for position in range(3):
                values=['Giao lưu game','Mời anh em chơi cùng.','Cùng trao đổi kinh nghiệm.']
                values[position]='Đánh rank hôm nay khó quá anh em.'
                self.assertTrue(writing_policy.issue(*values,category=game))
            self.assertFalse(writing_policy.issue('Bắn '+game,'Anh em chơi cùng nhé.','Cùng trao đổi.',category=game))
        self.assertFalse(writing_policy.issue('Đánh LOL','Đi đường cùng anh em.','Cùng giao tranh.',category='LOL'))
        self.assertFalse(writing_policy.issue('Đánh giá Valorant','Mời chia sẻ đánh giá.','Đánh dấu lịch chơi.',category='Valorant'))

    def test_prompts_use_game_specific_verbs_without_leaking_fps_examples(self):
        for game,word in [('Valorant','bắn Valorant'),('PUBG','bắn PUBG'),('Delta Force','cày đồ'),('LOL','đánh LOL')]:
            context={'category':game};prompt=writing_policy.apply('System.',context)
            self.assertIn(word,prompt)
            self.assertIn(word,context['game_language'])
        context={'category':'The isle'};writing_policy.apply('System.',context)
        self.assertNotIn('bắn',' '.join(context['voice_examples']).casefold())


class SinglePolicyTests(StudioTests):
    def test_wrong_valorant_verb_retries_before_saving(self):
        clean=self.response()
        bad={**clean,'body':'Đánh Valorant mà gặp kèo căng quá thì anh em tính sao?'}
        with patch.object(self.studio,'chat_json',side_effect=[bad,clean]) as ai:
            self.studio.start({'brief':'Mời anh em trao đổi kinh nghiệm Valorant.','category':'Valorant'})
            task=self.wait()
        self.assertEqual(task['status'],'done');self.assertEqual(ai.call_count,2)
        self.assertIn('dùng bắn',ai.call_args.args[1]['revision_request'])
        self.assertEqual(self.store.rows('SELECT body FROM contents')[0]['body'],clean['body'])

    # Reuse fixture helpers, without duplicating the inherited suite at discovery.
    def test_forbidden_title_retries_and_saves_only_clean_output(self):
        clean = self.response()
        with patch.object(self.studio, 'chat_json', side_effect=[{**clean, 'title': 'ESP cho game'}, clean]) as ai:
            self.studio.start({'brief': 'Mời anh em trao đổi thông tin game tại Discord.', 'category': 'Game'})
            result = self.wait()
        self.assertEqual(result['status'], 'done')
        self.assertEqual(ai.call_count, 2)
        self.assertIn('voice_examples', ai.call_args.args[1])
        self.assertEqual(self.store.rows('SELECT title FROM contents')[0]['title'], clean['title'])

    def test_forbidden_alt_after_retry_does_not_save_or_schedule(self):
        bad = {**self.response(), 'body_no_link': 'Không có cheat nhé.'}
        with patch.object(self.studio, 'chat_json', side_effect=[bad,bad,RuntimeError('HTTP 429: limit')]):
            self.studio.start({'brief': 'Thông tin game cho anh em.', 'category': 'Game'})
            result = self.wait()
        self.assertEqual(result['status'], 'error')
        self.assertEqual(self.store.rows('SELECT * FROM contents'), [])
        self.assertEqual(self.store.rows('SELECT * FROM jobs'), [])


class BatchPolicyTests(BatchAITests):
    def test_batch_retries_forbidden_words_and_keeps_voice_context(self):
        bad = self.answer('Không cần hack, mời anh em nhé.')
        clean = self.answer(self.bodies[0])
        with patch.object(self.studio, 'chat_json', side_effect=[bad, clean]) as ai:
            self.studio.draft_groups(self.options(ids=self.ids[:1], posts_per_group=1))
            result = self.wait()
        self.assertEqual(result['status'], 'done')
        self.assertEqual(ai.call_count, 2)
        self.assertIn('voice_examples', ai.call_args.args[1])
        self.assertEqual(len(self.s.rows('SELECT * FROM contents')), 1)
        self.assertEqual(self.s.rows('SELECT * FROM jobs'), [])


def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()
    for cls in (PolicyTests, SinglePolicyTests, BatchPolicyTests):
        suite.addTests(cls(name) for name in cls.__dict__ if name.startswith('test_'))
    return suite


if __name__ == '__main__':
    unittest.main()
