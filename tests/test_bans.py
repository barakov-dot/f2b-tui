import datetime
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import f2b_bans as bans
import f2b_core as core

TIMED = ('203.0.113.7\t2026-10-16 10:00:00 + 600 = 2026-10-16 10:10:00\n'
         '2001:db8::5\t2026-10-16 10:01:00 + 3600 = 2026-10-16 11:01:00\n'
         '198.51.100.9\t2026-10-16 10:02:00 + -1 = -1\n')


class BanTests(unittest.TestCase):
    def test_parse_timed_ipv4_ipv6_and_permanent(self):
        found = bans.parse_bans('sshd', TIMED)
        self.assertEqual([b['ip'] for b in found], ['203.0.113.7', '2001:db8::5', '198.51.100.9'])
        self.assertEqual(found[0]['end'], datetime.datetime(2026, 10, 16, 10, 10))
        self.assertTrue(found[2]['permanent'])
        self.assertEqual(bans.remaining(found[2]), -1)
        self.assertEqual(bans.remaining(found[0], datetime.datetime(2026, 10, 16, 10, 7)), 180)
        self.assertEqual(bans.remaining(found[0], datetime.datetime(2026, 10, 17)), 0)

    def test_parse_python_list_repr_with_escaped_tabs(self):
        text = r"['203.0.113.7 \t2026-10-16 10:00:00 + 600 = 2026-10-16 10:10:00', '2001:db8::5 \t2026-10-16 10:01:00 + 60 = 2026-10-16 10:02:00']"
        self.assertEqual([b['ip'] for b in bans.parse_bans('sshd', text)], ['203.0.113.7', '2001:db8::5'])

    def test_parse_plain_lists_from_old_servers(self):
        for text in ["['203.0.113.7', '2001:db8::5']", '203.0.113.7 2001:db8::5', '203.0.113.7, 2001:db8::5']:
            found = bans.parse_bans('sshd', text)
            self.assertEqual([b['ip'] for b in found], ['203.0.113.7', '2001:db8::5'])
            self.assertIsNone(bans.remaining(found[0]))
        self.assertEqual(bans.parse_bans('sshd', ''), [])
        self.assertEqual(bans.parse_bans('sshd', 'garbage 999.1.1.1 2026-10-16'), [])

    def test_duration_formats(self):
        self.assertEqual(bans.duration(45), '45s')
        self.assertEqual(bans.duration(552), '9m 12s')
        self.assertEqual(bans.duration(7380, 'ru'), '2ч 03м')
        self.assertEqual(bans.duration(90000), '1d 01h')
        self.assertEqual(bans.duration(-1), '∞')
        self.assertEqual(bans.duration(None), '?')

    def test_jail_bans_falls_back_to_status(self):
        with patch.object(core, 'run', return_value=(False, 'unknown option')), \
                patch.object(core, 'checked', return_value='|- Currently banned:\t1\n`- Banned IP list:\t203.0.113.7 2001:db8::5'):
            self.assertEqual([b['ip'] for b in bans.jail_bans('sshd')], ['203.0.113.7', '2001:db8::5'])

    def test_one_broken_jail_does_not_hide_others(self):
        def jail_bans(name):
            if name == 'bad':
                raise RuntimeError('boom')
            return bans.parse_bans(name, TIMED)
        with patch.object(bans, 'jails', return_value=['bad', 'sshd']), patch.object(bans, 'jail_bans', side_effect=jail_bans):
            found, errors = bans.all_bans()
        self.assertEqual(len(found), 3)
        self.assertIn('bad: boom', errors[0])

    def test_guard_refuses_loopback_and_own_address(self):
        with patch.object(bans, 'own_ips', return_value={'203.0.113.50'}):
            for ip in ('127.0.0.1', '::1', '0.0.0.0', '203.0.113.50'):
                with self.assertRaises(ValueError):
                    bans.guard_ban(ip)
            self.assertEqual(bans.guard_ban('203.0.113.51'), '203.0.113.51')

    def test_own_address_from_ssh_environment(self):
        with patch.dict(os.environ, {'SSH_CONNECTION': '2001:db8::77 5555 192.0.2.1 22'}, clear=False):
            self.assertIn('2001:db8::77', bans.own_ips())
        with patch.dict(os.environ, {}, clear=True), patch.object(core, 'run', return_value=(True, 'root pts/0 2026-10-16 (203.0.113.9)')):
            self.assertEqual(bans.own_ips(), {'203.0.113.9'})

    def test_unban_validates_and_reports_failures(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(core, 'STATE', Path(directory)):
            calls = []
            def checked(*args, **kwargs):
                calls.append(args)
                if args[-1] == '203.0.113.8':
                    raise RuntimeError('not banned')
                return '1'
            with patch.object(core, 'checked', side_effect=checked):
                done, failures = bans.unban([('sshd', '203.0.113.7'), ('sshd', '203.0.113.8'), ('--bad', '203.0.113.9'), ('sshd', 'nope')])
        self.assertEqual(done, [('sshd', '203.0.113.7')])
        self.assertEqual(len(failures), 3)
        self.assertEqual(calls[0], ('fail2ban-client', 'set', 'sshd', 'unbanip', '203.0.113.7'))

    def test_recent_events_newest_first_and_ignores_noise(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / 'f2b.log'
            log.write_text('2026-10-16 10:00:00,123 fail2ban.actions        [900]: NOTICE  [sshd] Ban 203.0.113.7\n'
                           '2026-10-16 10:05:00,000 fail2ban.filter         [900]: INFO    [sshd] Found 203.0.113.8 - 2026\n'
                           '2026-10-16 10:06:00,000 fail2ban.actions        [900]: NOTICE  [sshd] Unban 203.0.113.7\n'
                           '2026-10-16 10:07:00,000 fail2ban.actions        [900]: NOTICE  [sshd] Ban not-an-ip\n')
            events = bans.recent_events(5, log)
        self.assertEqual([(e['action'], e['ip']) for e in events], [('Unban', '203.0.113.7'), ('Ban', '203.0.113.7')])
        self.assertEqual(bans.recent_events(3, Path('/nonexistent/log')), [])


if __name__ == '__main__':
    unittest.main()
