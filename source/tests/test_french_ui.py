"""Simulated accessibility labels only; no real Windows inputs or Facebook requests."""
import sys, unittest, types
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import desktop, video_fallback
from facebook_labels import caption_editor_allowed
from post_context import own_post_context
from receipts import read_post_receipt

class FrenchTests(unittest.TestCase):
 def targets(self, text): return desktop.parse_targets('UI Tree:\n'+text)
 def test_composer_media_publish(self):
  for name in ('Exprimez-vous...', 'Créer une publication', 'Photo/vidéo', 'Ajouter des photos/vidéos'):
   t=self.targets('(10,10) button "'+name+'" [action: click]')[0]
   self.assertTrue(desktop.composer_click_allowed(t),name)
  for name in ('Publier',):
   t=self.targets('(10,10) button "'+name+'" [action: click]')[0]
   self.assertTrue(desktop.is_post_button(t));self.assertFalse(desktop.composer_click_allowed(t))
  for name in ('Facebook', 'Rejoindre le groupe', 'Publier un commentaire', 'Partager'):
   t=self.targets('(10,10) button "'+name+'" [action: click]')[0]
   self.assertFalse(desktop.is_post_button(t));self.assertFalse(desktop.composer_click_allowed(t))
 def test_known_editor_and_filename(self):
  for name in ('Créer une publication publique...', 'Créez une publication publique...', 'Exprimez-vous...'):
   ts=self.targets('(10,10) edit "'+name+'" [action: fill]')
   self.assertEqual(desktop.known_composer_action(ts,False,False,False,False)['action'],'type_caption')
  ts=self.targets('(10,10) edit "Nom du fichier :" [action: fill]')
  self.assertEqual(desktop.known_composer_action(ts,True,False,True,True)['action'],'type_media')
 def test_never_types_caption_in_french_comment_reply_or_search(self):
  for name in ('écrivez un commentaire public...', 'répondre à Paul', 'rechercher sur facebook', 'mot de passe'):
   self.assertFalse(caption_editor_allowed('edit',name))
   ts=self.targets('(10,10) edit "'+name+'" [action: fill]')
   self.assertIsNone(desktop.known_composer_action(ts,False,False,False,False))
 def test_specific_pending_and_security(self):
  msg='Votre publication est en attente d’approbation'
  self.assertTrue(desktop.valid_pending_receipt(msg,'','A uniquely approved caption'))
  self.assertFalse(desktop.valid_pending_receipt(msg,msg,'A uniquely approved caption'))
  self.assertFalse(desktop.valid_pending_receipt('En attente d’approbation','',''))
  self.assertIn('vous ne pouvez pas publier',desktop.BLOCKED)
 def test_video_rejection_requires_composer(self):
  ts=self.targets('(10,10) edit "Créer une publication publique" [action: fill]\n(20,20) button "Supprimer la vidéo" [action: click]')
  caption='Un texte de test exact pour cette publication'
  snap=caption+' Impossible d’importer votre vidéo'
  self.assertEqual(video_fallback.removal_target(snap,ts,caption,submitted=False,attached=True,has_video=True,used=False)['name'],'supprimer la vidéo')
  self.assertIsNone(video_fallback.removal_target(snap,ts,caption,submitted=True,attached=True,has_video=True,used=False))
 def test_french_context_receipt_and_exclusion_of_comment_timestamp(self):
  caption='Texte de test unique pour identifier exactement cette publication'
  url='https://www.facebook.com/groups/test/posts/123/'
  class Node:
   def __init__(self,name='',control='GroupControl',children=(),href=''):
    self.Name=name;self.ControlTypeName=control;self.children=children;self.href=href
    self.AriaRole='';self.IsOffscreen=False
    self.BoundingRectangle=types.SimpleNamespace(left=10,top=20,right=110,bottom=40)
   def GetChildren(self):return self.children
   def GetLegacyIAccessiblePattern(self):return types.SimpleNamespace(Value=self.href)
  root=Node(children=[Node(caption,'TextControl'),Node('À l’instant','HyperlinkControl',href=url),
   Node('Actions pour cette publication de Paul','ButtonControl'),Node('En voir plus','ButtonControl'),
   Node('Écrivez un commentaire public...','EditControl'),Node('Répondre à Paul','EditControl'),
   Node('il y a 1 minute','HyperlinkControl',href=url+'?comment_id=2')])
  com=types.ModuleType('comtypes');com.CoInitialize=lambda:None;com.CoUninitialize=lambda:None
  uia=types.ModuleType('windows_mcp.uia');uia.ControlFromHandle=lambda h:root
  package=types.ModuleType('windows_mcp');package.__path__=[];package.uia=uia
  with patch.dict(sys.modules,{'comtypes':com,'windows_mcp':package,'windows_mcp.uia':uia}):
   ctx=own_post_context(1,caption)
   self.assertEqual(len(ctx['editors']),1);self.assertEqual(len(ctx['expand']),1)
   self.assertEqual(ctx['timestamp']['name'],'à l’instant')
   self.assertEqual(read_post_receipt(1,caption,'https://www.facebook.com/groups/test/')['post_url'],url)

if __name__=='__main__':unittest.main()
