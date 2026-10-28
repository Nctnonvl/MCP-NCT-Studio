import tempfile
from pathlib import Path
import unittest
from store import Store,post_variant

class AllLinksTests(unittest.TestCase):
    def test_all_only_uses_direct_discord_link(self):
        body='Nội dung chính\n\nhttps: //discord.gg/mjzJyBTP (bỏ dấu cách sau dấu hai chấm hoặc xuống cmt nhá anh em )'
        p={'body':body,'media':'','body_no_link':'Không link','media_no_link':''}
        self.assertEqual(post_variant(p,'allow','ALL')[0],'Nội dung chính\n\nhttps://discord.gg/mjzJyBTP')
        self.assertEqual(post_variant(p,'allow','Valorant')[0],body)
        self.assertEqual(p['body'],body)
        self.assertEqual(post_variant(p,'deny','ALL')[0],'Không link')

    def test_all_selection_sets_link_permission(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'db')
            gid=store.add_group('facebook.com/groups/alltest',category='ALL')
            row=store.rows('SELECT * FROM groups WHERE id=?',(gid,))[0]
            self.assertEqual(row['link_policy'],'allow')
