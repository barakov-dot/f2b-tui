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
    def get_wch(self): return next(self.keys)
    def addstr(self, y, x, text, attr):
        assert 0 <= y < self.size[0]
        assert cell_width(text) < self.size[1] - x
        self.drawn.append(text)


class UITests(unittest.TestCase):
    def ui(self, keys, size=(24, 80), lang='ru', ascii_mode=False):
        with patch('curses.curs_set', side_effect=curses.error), patch('curses.set_escdelay'), patch('curses.has_colors', return_value=False):
            return UI(Screen(keys, size), lang, ascii_mode)

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
            with patch.object(ui, 'choose_jail', return_value='sshd'), patch('f2b_ui.core.checked') as command, patch('curses.curs_set', side_effect=curses.error):
                ui.execute(action)
                command.assert_not_called()

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


if __name__ == '__main__':
    unittest.main()
