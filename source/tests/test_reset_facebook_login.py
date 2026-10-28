from contextlib import closing
"""Only fake cookie databases: never touches the real browser session."""
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reset_facebook_login import clear_facebook_cookies,cookie_files
import reset_facebook_login as reset


class CookieResetTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.profile=self.root/'edge-profile'

    def tearDown(self):self.tmp.cleanup()

    def database(self,relative,hosts):
        target=self.profile/relative;target.parent.mkdir(parents=True,exist_ok=True)
        with closing(sqlite3.connect(target)) as connection, connection:
            connection.execute('CREATE TABLE cookies(host_key TEXT,name TEXT,value TEXT)')
            connection.executemany('INSERT INTO cookies VALUES(?,?,?)',[(h,'fake','fake') for h in hosts])
        return target

    def test_only_facebook_and_its_subdomains_are_deleted(self):
        keep=['example.com','notfacebook.com','.facebook.com.evil.com','messenger.com']
        target=self.database('Default/Network/Cookies',['facebook.com','.facebook.com','m.facebook.com','.M.FACEBOOK.COM',*keep])
        self.assertEqual(clear_facebook_cookies(self.profile),4)
        with closing(sqlite3.connect(target)) as connection, connection:self.assertEqual([r[0] for r in connection.execute('SELECT host_key FROM cookies')],keep)

    def test_other_profiles_and_non_cookie_data_are_preserved(self):
        self.database('Profile 1/Network/Cookies',['.facebook.com'])
        self.database('Default/Cookies',['.facebook.com'])
        marker=self.profile/'Default/Login Data';marker.write_bytes(b'keep passwords')
        self.assertEqual(clear_facebook_cookies(self.profile),2)
        self.assertEqual(marker.read_bytes(),b'keep passwords')

    def test_no_cookie_database_does_not_create_profile(self):
        self.assertEqual(clear_facebook_cookies(self.profile),0)
        self.assertFalse(self.profile.exists())

    def test_unknown_schema_is_not_replaced_or_deleted(self):
        target=self.database('Default/Network/Cookies',[])
        with closing(sqlite3.connect(target)) as connection, connection:connection.execute('DROP TABLE cookies');connection.execute('CREATE TABLE custom(x)')
        with self.assertRaises(RuntimeError):clear_facebook_cookies(self.profile)
        with closing(sqlite3.connect(target)) as connection, connection:self.assertEqual(connection.execute("SELECT name FROM sqlite_master WHERE name='custom'").fetchone(),('custom',))

    def test_cancel_does_not_clear_or_open_facebook(self):
        with patch.object(reset,'blocking_processes',return_value=[]),patch.object(reset,'clear_facebook_cookies') as clear,patch('builtins.input',return_value=''),patch('builtins.print'):
            self.assertEqual(reset.main(),0)
        clear.assert_not_called()

    def test_running_bot_blocks_cookie_reset_before_confirmation(self):
        with patch.object(reset,'blocking_processes',return_value=['NCT Group Manager']),patch.object(reset,'clear_facebook_cookies') as clear,patch('builtins.input',return_value='XOA'),patch('builtins.print'):
            self.assertEqual(reset.main(),2)
        clear.assert_not_called()


if __name__=='__main__':unittest.main()
