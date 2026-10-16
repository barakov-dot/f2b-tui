import curses
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from f2b_ui import UI, TEXT, ACTIONS, cell_width, clip


class Screen:
    def __init__(self, keys, size=(24, 80)):
        self.keys = iter(keys)
        self.size = size
        self.drawn = []
    def keypad(self, flag): pass
    def getmaxyx(self): return self.size
    def erase(self): pass
    def refresh(self): pass
    def move(self, y, x): pass
    def timeout(self, ms): pass
    def get_wch(self): return next(self.keys)
    def addstr(self, y, x, text, attr):
        assert 0 <= y < self.size[0]
        assert cell_width(text) < self.size[1] - x
        self.drawn.append(text)


class UITests(unittest.TestCase):
    def ui(self, keys, size=(24, 80), lang='ru', ascii_mode=False, nerd=False):
        with patch('curses.curs_set', side_effect=curses.error), patch('curses.set_escdelay'), patch('curses.has_colors', return_value=False):
            return UI(Screen(keys, size), lang, ascii_mode, nerd)

    def test_escape_empty_and_partial_input(self):
        for keys in [['\x1b'], ['1', '2', '7', '\x1b']]:
            with patch('curses.curs_set', side_effect=curses.error):
                self.assertIsNone(self.ui(keys).prompt('IP'))

    def test_edit_input(self):
        with patch('curses.curs_set', side_effect=curses.error):
            self.assertEqual(self.ui(['a', 'c', curses.KEY_LEFT, 'b', '\n']).prompt('text'), 'abc')

    def test_cancel_ban_and_unban_never_executes(self):
        for action in ['ban', 'unban']:
            ui = self.ui(['\x1b'])
            with patch.object(ui, 'choose_jail', return_value='sshd'), patch('f2b_ui.bans.all_bans', return_value=([], [])), \
                    patch('f2b_ui.bans.ban') as ban, patch('f2b_ui.bans.unban') as unban, patch('curses.curs_set', side_effect=curses.error):
                ui.execute(action)
                ban.assert_not_called()
                unban.assert_not_called()

    def test_all_items_accessible_on_small_terminal(self):
        ui = self.ui([curses.KEY_END, '\n'], size=(12, 48))
        self.assertEqual(ui.menu('menu', ACTIONS, True, True), len(ACTIONS) - 1)
        self.assertTrue(any('Выход' in line for line in ui.s.drawn))

    def test_tiny_terminal_safe_cancel(self):
        for size in [(1, 1), (4, 10), (11, 47)]:
            self.assertIsNone(self.ui(['\x1b'], size).menu('menu', ACTIONS, True))

    def test_both_languages_and_ascii(self):
        self.assertTrue(all(len(pair) == 2 and all(pair) for pair in TEXT.values()))
        for lang in ['ru', 'en']:
            ui = self.ui(['\x1b'], lang=lang, ascii_mode=True)
            ui.menu('menu', ACTIONS, True, True)
            self.assertTrue(any('01' in line for line in ui.s.drawn))

    def test_confirmation_escape_is_false(self):
        with patch('curses.curs_set', side_effect=curses.error):
            self.assertFalse(self.ui(['\x1b']).confirm('Confirm'))

    def test_wide_characters_and_control_characters(self):
        self.assertEqual(clip('中文abc', 5), '中文a')
        self.assertNotIn('\x1b', clip('abc\x1b[31m', 50))


def make_ban(ip, jail='sshd', minutes=10, cc='', net=''):
    import datetime
    end = datetime.datetime.now() + datetime.timedelta(minutes=minutes)
    return {'jail': jail, 'ip': ip, 'start': end - datetime.timedelta(minutes=60), 'end': end, 'permanent': False}


class BanListTests(UITests):
    def screen_ui(self, keys, found, size=(24, 90), **kwargs):
        ui = self.ui(keys, size, **kwargs)
        for b in found:
            b.setdefault('cc', 'DE')
            b.setdefault('net', 'AS24940 Hetzner Online GmbH · 203.0.113.0/24')
            b.setdefault('haystack', (b['ip'] + ' ' + b['jail'] + ' de hetzner').lower())
        return ui

    def run_list(self, keys, found, **kwargs):
        ui = self.screen_ui(keys, found, **kwargs)
        with patch.object(ui, 'load_bans', side_effect=lambda: ([dict(b) for b in found], [])), \
                patch('f2b_ui.bans.unban', return_value=([('sshd', '203.0.113.2')], [])) as unban, \
                patch('f2b_ui.bans.own_ips', return_value=set()), \
                patch('curses.curs_set', side_effect=curses.error):
            ui.bans_screen()
        return ui, unban

    def test_arrow_select_and_enter_unbans_selected_ip(self):
        found = [make_ban('203.0.113.1', minutes=5), make_ban('203.0.113.2', minutes=9)]
        # Sorted by time left: .1 first; Down selects .2; Enter, then 'y' for this jail; ESC leaves.
        ui, unban = self.run_list([curses.KEY_DOWN, '\n', 'y', '\x1b'], found)
        unban.assert_called_once_with([('sshd', '203.0.113.2')])
        self.assertTrue(any('203.0.113.2' in line for line in ui.s.drawn))
        self.assertTrue(any('Hetzner' in line for line in ui.s.drawn))

    def test_cancelling_confirmation_never_unbans(self):
        for answer in ('n', '\x1b'):
            _, unban = self.run_list(['\n', answer, '\x1b'], [make_ban('203.0.113.1')])
            unban.assert_not_called()

    def test_marked_ips_unban_together_and_all_jails_expands(self):
        found = [make_ban('203.0.113.1', 'sshd', 5), make_ban('203.0.113.2', 'sshd', 6), make_ban('203.0.113.1', 'nginx', 7)]
        _, unban = self.run_list([' ', ' ', '\n', 'y', '\x1b'], found)
        unban.assert_called_once_with([('sshd', '203.0.113.1'), ('sshd', '203.0.113.2')])
        _, unban = self.run_list(['\n', 'a', '\x1b'], found)
        self.assertCountEqual(unban.call_args[0][0], [('sshd', '203.0.113.1'), ('nginx', '203.0.113.1')])

    def test_whitelist_choice_adds_ignoreip_before_unban(self):
        order = []
        ui = self.screen_ui(['\n', 'w', '\x1b'], [make_ban('203.0.113.1')])
        with patch.object(ui, 'load_bans', return_value=([dict(make_ban('203.0.113.1'), cc='DE', net='', haystack='x')], [])), \
                patch('f2b_ui.core.add_ignoreip', side_effect=lambda *a: order.append(('ignore', a))), \
                patch('f2b_ui.bans.unban', side_effect=lambda e: order.append(('unban', e)) or (e, [])), \
                patch('f2b_ui.bans.own_ips', return_value=set()), patch('curses.curs_set', side_effect=curses.error):
            ui.bans_screen()
        self.assertEqual([name for name, _ in order], ['ignore', 'unban'])

    def test_filter_and_empty_state(self):
        ui, _ = self.run_list(['/', 'z', 'z', 'z', '\n', '\x1b'], [make_ban('203.0.113.1')])
        self.assertTrue(any('Ничего не найдено' in line or 'Nothing matches' in line for line in ui.s.drawn))
        ui, _ = self.run_list(['\x1b'], [])
        self.assertTrue(any('нет заблокированных' in line.lower() or 'No banned' in line for line in ui.s.drawn))

    def test_small_terminal_and_all_icon_modes(self):
        found = [make_ban('2001:db8::1')]
        for size in [(12, 48), (1, 1), (11, 47)]:
            self.run_list(['\x1b'], found, size=size)
        for kwargs in [{'ascii_mode': True}, {'nerd': True}, {}]:
            with patch('f2b_ui.UI.save_preferences'):
                ui, _ = self.run_list(['a', 'f', '\x1b'], found, **kwargs)
            self.assertTrue(any('2001:db8::1' in line for line in ui.s.drawn))

    def test_icon_modes_cycle_and_nerd_icons_survive_clip(self):
        ui = self.ui([])
        ui.mode = 'unicode'
        with patch.object(ui, 'save_preferences'):
            ui.toggle('a'); self.assertEqual(ui.mode, 'nerd')
            ui.toggle('a'); self.assertEqual(ui.mode, 'ascii')
            ui.toggle('a'); self.assertEqual(ui.mode, 'unicode')
        self.assertEqual(clip('\uf09c x', 5), '\uf09c x')
        from f2b_ui import ICONS, NERD_ICONS
        self.assertEqual(len(ICONS), len(ACTIONS))
        self.assertEqual(len(NERD_ICONS), len(ACTIONS))

    def test_geo_menu_status_lookup_and_cancelled_update(self):
        ui = self.ui(['\x1b'])
        with patch('curses.curs_set', side_effect=curses.error):
            ui.geo_menu()
        self.assertTrue(any('Геобаза' in line for line in ui.s.drawn))
        ui = self.ui(['\n', '\x1b', '\x1b'], lang='en')  # open status page, leave it, leave menu
        with patch('f2b_ui.geo.Geo.info', return_value={}), patch('curses.curs_set', side_effect=curses.error):
            ui.geo_menu()
        self.assertTrue(any('No database installed' in line for line in ui.s.drawn))
        ui = self.ui(['\x1b'], lang='en')
        with patch('f2b_ui.geo.update') as update:
            ui.geo_action('geo_update')  # ESC at the confirmation: nothing downloaded
            update.assert_not_called()

    def test_info_page_shows_network_for_known_ip(self):
        ui = self.ui([])
        with patch.object(ui.geo, 'lookup', return_value={'cc': 'DE', 'asn': 24940, 'org': 'Hetzner', 'cidr': '203.0.113.0/24', 'offline': True}):
            text = '\n'.join(line for line, _ in ui.info_lines('203.0.113.7', make_ban('203.0.113.7')))
        for expected in ('Hetzner', '203.0.113.0/24', 'AS24940', 'DE', 'sshd'):
            self.assertIn(expected, text)

    def test_help_texts_cover_both_languages(self):
        self.assertTrue(TEXT['help_bans'][0] and TEXT['help_bans'][1])


if __name__ == '__main__':
    unittest.main()
