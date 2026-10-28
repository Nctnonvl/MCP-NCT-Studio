import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from writing_variation import copied,blueprint,DIRECTIONS
from studio import Studio
from store import Store

class VariationTests(unittest.TestCase):
 def test_changing_game_name_does_not_make_a_new_post(self):
  body='Bắn Valorant mà gặp kèo căng quá thì anh em tính sao? Ghé Discord bên mình để trao đổi thêm, nhiều game nhiều bản cho anh em lựa chọn với giá cả hợp lý.'
  self.assertTrue(copied(body.replace('Valorant','PUBG'),[body]))
 def test_reordering_the_same_sentences_is_rejected(self):
  one='Anh em có nhu cầu tìm hiểu các phiên bản game thì trao đổi cùng bên mình nhé.'
  two='Bên mình có nhiều game và nhiều lựa chọn để anh em tham khảo với giá cả hợp lý.'
  three='Liên hệ qua Discord để hỏi thêm thông tin phù hợp nhu cầu của mình.'
  self.assertTrue(copied(two+' '+three+' '+one,[one+' '+two+' '+three]))
 def test_same_facts_with_different_expression_are_allowed(self):
  a='Anh em nào muốn lên rank Valorant an toàn thì ghé Discord bên mình. Có nhiều game và phiên bản để lựa chọn, giá cả hợp lý.'
  b='Mỗi người một nhu cầu nên bên mình có nhiều lựa chọn về game lẫn phiên bản. Cần trao đổi thêm trước khi quyết định, anh em có thể tìm bên mình trên Discord.'
  self.assertFalse(copied(b,[a]))
 def test_small_synonym_edits_are_rejected(self):
  a='Chơi Valorant gặp kèo khó quá thì anh em tính sao? Ghé Discord bên mình để trao đổi thêm về các game và nhiều phiên bản phù hợp nhu cầu với giá cả hợp lý.'
  b=a.replace('khó quá','căng quá').replace('tính sao','làm sao').replace('trao đổi thêm','tìm hiểu thêm')
  self.assertTrue(copied(b,[a]))
 def test_repeated_opening_is_rejected_even_with_new_ending(self):
  lead='Thua mãi trong những trận Valorant căng quá thì phải làm sao anh em? '
  self.assertTrue(copied(lead+'Cần trao đổi thì nhắn bên mình.',[lead+'Bên mình có nhiều lựa chọn để anh em tham khảo tại Discord.']))
 def test_brief_shared_terms_are_not_a_duplicate(self):
  self.assertFalse(copied('Anh em vào Discord trao đổi nhu cầu và lựa chọn nhé.',['Discord, game, nhiều phiên bản, giá hợp lý.']))
 def test_a_shared_service_sentence_is_rejected_despite_different_openings(self):
  common='Bên mình có nhiều game và nhiều phiên bản cho anh em lựa chọn theo nhu cầu, giá cả hợp lý.'
  a='Bắn Valorant mà gặp kèo khó thì anh em tính sao? '+common+' Nhắn bên mình qua Discord để trao đổi thêm.'
  b='Cần cân nhắc các phiên bản trước khi quyết định thì cứ thong thả xem nhé. '+common
  self.assertTrue(copied(b,[a]))
 def test_blueprints_change_layout_and_length_across_cycles(self):
  self.assertNotEqual(blueprint(0),blueprint(1))
  self.assertNotEqual(blueprint(0),blueprint(len(DIRECTIONS)))
  self.assertGreater(len({blueprint(i)['writing_direction'] for i in range(40)}),20)
 def test_writing_temperature_differs_from_classification_without_changing_model(self):
  with tempfile.TemporaryDirectory() as d:
   s=Store(Path(d)/'db');studio=Studio(s,lambda:{'model':'unchanged'},Path(d))
   with patch('content_ai.config',return_value={'writer_provider':'src_muse'}),patch('content_ai.writer_json',return_value={}) as call:
    studio.chat_json('Write',{'brief':'Known facts'})
    self.assertEqual(call.call_args.kwargs['temperature'],.9)
    studio.chat_json('Classify',{'categories':['Valorant']})
    self.assertEqual(call.call_args.kwargs['temperature'],.2)
