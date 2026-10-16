"""RU/EN curses interface, with keyboard-only cancellation and bounded rendering."""
import curses
import ipaddress
import json
import locale
import os
import re
import textwrap
import unicodedata
from collections import deque

import f2b_core as core

TEXT = {
    'menu': ('Панель управления', 'Control panel'),
    'overview': ('Обзор службы и jail', 'Service and jail overview'),
    'details': ('Jail и заблокированные IP', 'Jail details and banned IPs'),
    'ban': ('Заблокировать IP', 'Ban IP'), 'unban': ('Разблокировать IP', 'Unban IP'),
    'edit': ('Время блокировки и попытки', 'Timing and retry settings'),
    'logs': ('Журнал Fail2ban', 'Fail2ban log'), 'test': ('Проверить конфигурацию', 'Validate configuration'),
    'reload': ('Перечитать конфигурацию', 'Reload configuration'),
    'restart': ('Перезапустить Fail2ban', 'Restart Fail2ban'),
    'backup': ('Создать резервную копию', 'Create configuration backup'),
    'restore': ('Восстановить конфигурацию', 'Restore configuration'),
    'language': ('Язык / Language', 'Language / Язык'), 'exit': ('Выход', 'Exit'),
    'nav': ('↑↓ выбор · Enter открыть · ESC назад · L язык · A значки', '↑↓ select · Enter open · ESC back · L language · A icons'),
    'nav_ascii': ('Up/Down: выбор | Enter: открыть | ESC: назад | L: язык | A: значки', 'Up/Down: select | Enter: open | ESC: back | L: language | A: icons'),
    'back': ('↑↓ / PgUp/PgDn прокрутка · ESC назад', '↑↓ / PgUp/PgDn scroll · ESC back'),
    'input': ('Enter — принять; ESC — отмена', 'Enter to submit; ESC to cancel'),
    'confirm': ('Введите YES для подтверждения', 'Type YES to confirm'),
    'empty': ('Нет данных', 'No data'), 'choose': ('Выберите jail', 'Choose jail'),
    'no_jails': ('Нет активных jail', 'No active jails'),
    'ip': ('Адрес IPv4 или IPv6', 'IPv4 or IPv6 address'),
    'error': ('Ошибка', 'Error'), 'ok': ('Готово', 'Done'),
    'size': ('Увеличьте терминал: минимум 48 x 12. ESC — выход.', 'Enlarge terminal: minimum 48 x 12. ESC to leave.'),
    'number': ('Целое число от 1 до 31536000', 'Integer from 1 to 31536000'),
    'setting': ('Выберите параметр', 'Choose setting'),
    'seconds': ('секунды', 'seconds'), 'count': ('попытки', 'attempts'),
    'apply': ('Сохранить и применить? При ошибке изменение будет отменено.', 'Save and apply? Failed changes will be rolled back.'),
    'saved': ('Резервная копия', 'Backup'),
    'restore_warn': ('Заменить ВСЮ /etc/fail2ban выбранной копией и выполнить reload?', 'Replace ALL of /etc/fail2ban with this backup and reload?'),
    'working': ('Выполняется…', 'Working…'),
    'help': ('CLI: sudo f2b update | uninstall | backup | backups | restore ID', 'CLI: sudo f2b update | uninstall | backup | backups | restore ID'),
}
ICONS = ['◈', '▣', '⊕', '⊖', '⚙', '≡', '✓', '↻', '↯', '▤', '↶', '◎', '×']
ACTIONS = ['overview', 'details', 'ban', 'unban', 'edit', 'logs', 'test', 'reload', 'restart', 'backup', 'restore', 'language', 'exit']


def cell_width(text):
    return sum(0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in 'WF' else 1 for c in text)


def clip(text, width):
    out, used = [], 0
    for char in str(text):
        if unicodedata.category(char).startswith('C'):
            char = ' '  # Logs must not inject terminal controls.
        size = cell_width(char)
        if used + size > width:
            break
        used += size
        out.append(char)
    return ''.join(out)


class UI:
    def __init__(self, screen, lang=None, ascii_mode=False):
        self.s = screen
        self.s.keypad(True)
        self.lang = lang or ('ru' if locale.getlocale()[0] and locale.getlocale()[0].startswith('ru') else 'en')
        self.ascii = ascii_mode or 'UTF' not in locale.getpreferredencoding(False).upper()
        self.colors = False
        try:
            prefs = json.loads((core.STATE / 'preferences.json').read_text())
            if not lang and prefs.get('language') in ('ru', 'en'):
                self.lang = prefs['language']
            self.ascii = self.ascii or prefs.get('ascii', False)
        except (OSError, ValueError):
            pass
        try:
            curses.curs_set(0)
            curses.set_escdelay(25)
            if curses.has_colors():
                curses.start_color()
                curses.use_default_colors()
                curses.init_pair(1, curses.COLOR_CYAN, -1)
                curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_CYAN)
                curses.init_pair(3, curses.COLOR_YELLOW, -1)
                self.colors = True
        except curses.error:
            pass

    def t(self, key):
        return TEXT[key][0 if self.lang == 'ru' else 1]

    def put(self, y, x, text, attr=0):
        h, w = self.s.getmaxyx()
        if 0 <= y < h and 0 <= x < w - 1:
            try:
                self.s.addstr(y, x, clip(text, w - x - 1), attr)
            except (curses.error, UnicodeError):
                pass

    def color(self, n):
        return curses.color_pair(n) if self.colors else (curses.A_REVERSE if n == 2 else curses.A_BOLD)

    def frame(self, title, footer=None):
        self.s.erase()
        h, w = self.s.getmaxyx()
        self.put(0, 1, f'F2B / {core.VERSION}                              {self.lang.upper()}', self.color(1) | curses.A_BOLD)
        self.put(1, 1, ('-' if self.ascii else '─') * max(0, w - 3), self.color(1))
        self.put(2, 2, title, curses.A_BOLD)
        self.put(h - 2, 1, ('-' if self.ascii else '─') * max(0, w - 3), self.color(1))
        self.put(h - 1, 1, footer or self.t('nav_ascii' if self.ascii else 'nav'), self.color(1))
        if h < 12 or w < 48:
            self.s.erase()
            self.put(0, 0, self.t('size'))
            return False
        return True

    def key(self):
        try:
            return self.s.get_wch()
        except curses.error:
            return None

    def save_preferences(self):
        try:
            with core.locked():
                core.atomic_write(core.STATE / 'preferences.json', json.dumps({'language': self.lang, 'ascii': self.ascii}).encode())
        except (OSError, RuntimeError) as exc:
            self.page(self.t('error'), str(exc))

    def toggle(self, key):
        if key in ('l', 'L'):
            self.lang = 'en' if self.lang == 'ru' else 'ru'
        elif key in ('a', 'A'):
            self.ascii = not self.ascii
        else:
            return False
        self.save_preferences()
        return True

    def menu(self, title, choices, translate=False, icons=False):
        pos = 0
        if not choices:
            self.page(title, self.t('empty'))
            return None
        while True:
            ready = self.frame(self.t(title) if translate else title)
            h, _ = self.s.getmaxyx()
            rows = max(1, h - 7)
            start = max(0, pos - rows + 1)
            if ready:
                for row, i in enumerate(range(start, min(len(choices), start + rows))):
                    label = self.t(choices[i]) if translate else choices[i]
                    icon = (f'{i+1:02d}' if self.ascii else ICONS[i]) if icons else '-'
                    self.put(row + 4, 2, f'{">" if i == pos else " "} {icon}  {label}', self.color(2) if i == pos else 0)
                self.put(h - 3, 2, f'{pos + 1} / {len(choices)}', self.color(3))
            self.s.refresh()
            key = self.key()
            if key in ('\x1b', 'q', 'Q'):
                return None
            if self.toggle(key) or not ready:
                continue
            if key in (curses.KEY_DOWN, 'j'):
                pos = (pos + 1) % len(choices)
            elif key in (curses.KEY_UP, 'k'):
                pos = (pos - 1) % len(choices)
            elif key == curses.KEY_NPAGE:
                pos = min(len(choices) - 1, pos + rows)
            elif key == curses.KEY_PPAGE:
                pos = max(0, pos - rows)
            elif key == curses.KEY_HOME:
                pos = 0
            elif key == curses.KEY_END:
                pos = len(choices) - 1
            elif key in ('\n', '\r', curses.KEY_ENTER):
                return pos

    def prompt(self, title):
        value, cursor = '', 0
        while True:
            ready = self.frame('', self.t('input'))
            if ready:
                h, w = self.s.getmaxyx()
                input_row = h - 4
                for row, line in enumerate(textwrap.wrap(title, max(1, w - 6))[:input_row - 2], 2):
                    self.put(row, 3, line, curses.A_BOLD)
                # Keep cursor visible even for a long pasted address/value.
                start = max(0, cursor - max(1, (w - 8) // 2))
                self.put(input_row, 3, value[start:])
                try:
                    curses.curs_set(1)
                    self.s.move(input_row, min(w - 2, 3 + cell_width(value[start:cursor])))
                except curses.error:
                    pass
            self.s.refresh()
            key = self.key()
            if key == '\x1b':
                result = None
                break
            if not ready:
                continue
            if key in ('\n', '\r', curses.KEY_ENTER):
                result = value.strip()
                break
            if key in (curses.KEY_BACKSPACE, '\x7f', '\b') and cursor:
                value = value[:cursor - 1] + value[cursor:]
                cursor -= 1
            elif key == curses.KEY_DC:
                value = value[:cursor] + value[cursor + 1:]
            elif key == curses.KEY_LEFT:
                cursor = max(0, cursor - 1)
            elif key == curses.KEY_RIGHT:
                cursor = min(len(value), cursor + 1)
            elif key == curses.KEY_HOME:
                cursor = 0
            elif key == curses.KEY_END:
                cursor = len(value)
            elif isinstance(key, str) and key.isprintable() and len(value) < 256:
                value = value[:cursor] + key + value[cursor:]
                cursor += len(key)
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        return result

    def confirm(self, question):
        return self.prompt(question + ' / ' + self.t('confirm')) == 'YES'

    def page(self, title, text):
        lines = str(text).splitlines() or [self.t('empty')]
        pos, horizontal = 0, 0
        while True:
            ready = self.frame(title, self.t('back').replace('↑↓', 'Up/Down') if self.ascii else self.t('back'))
            h, _ = self.s.getmaxyx()
            rows = max(1, h - 6)
            pos = min(pos, max(0, len(lines) - rows))
            if ready:
                for i, line in enumerate(lines[pos:pos + rows]):
                    self.put(i + 4, 2, line[horizontal:])
            self.s.refresh()
            key = self.key()
            if key in ('\x1b', 'q', 'Q', '\n', '\r'):
                return
            if key in (curses.KEY_DOWN, 'j'):
                pos = min(max(0, len(lines) - rows), pos + 1)
            elif key in (curses.KEY_UP, 'k'):
                pos = max(0, pos - 1)
            elif key == curses.KEY_NPAGE:
                pos = min(max(0, len(lines) - rows), pos + rows)
            elif key == curses.KEY_PPAGE:
                pos = max(0, pos - rows)
            elif key == curses.KEY_RIGHT:
                horizontal += 8
            elif key == curses.KEY_LEFT:
                horizontal = max(0, horizontal - 8)

    def working(self):
        self.frame(self.t('working'), '')
        self.s.refresh()

    def choose_jail(self):
        self.working()
        output = core.checked('fail2ban-client', 'status')
        match = re.search(r'Jail list:\s*([^\n]*)', output)
        names = [v.strip() for v in match.group(1).split(',') if v.strip()] if match else []
        if not names:
            self.page(self.t('no_jails'), output)
            return None
        index = self.menu(self.t('choose'), names)
        return names[index] if index is not None else None

    def execute(self, action):
        if action in ('details', 'ban', 'unban', 'edit'):
            jail = self.choose_jail()
            if jail is None:
                return
            if action == 'details':
                self.working()
                self.page(jail, core.checked('fail2ban-client', 'status', jail))
            elif action in ('ban', 'unban'):
                raw = self.prompt(self.t('ip'))
                if raw is None:
                    return
                ip = str(ipaddress.ip_address(raw))
                if self.confirm(f'{self.t(action)}: {ip} / {jail}?'):
                    self.working()
                    with core.locked():
                        output = core.checked('fail2ban-client', 'set', jail, action + 'ip', ip)
                    self.page(self.t('ok'), output)
            else:
                keys = ['bantime', 'findtime', 'maxretry']
                idx = self.menu(self.t('setting'), [k + ' / ' + self.t('count' if k == 'maxretry' else 'seconds') for k in keys])
                if idx is None:
                    return
                value = self.prompt(jail + ' / ' + keys[idx] + ': ' + self.t('number'))
                if value is None or not self.confirm(self.t('apply')):
                    return
                self.working()
                ident = core.write_setting(jail, keys[idx], value)
                self.page(self.t('ok'), self.t('saved') + ': ' + ident)
        elif action == 'overview':
            self.working()
            service = core.run('systemctl', 'is-active', 'fail2ban')[1]
            status = core.run('fail2ban-client', 'status')[1]
            self.page(self.t(action), service + '\n\n' + status + '\n\n' + self.t('help'))
        elif action == 'logs':
            self.working()
            path = core.Path('/var/log/fail2ban.log')
            if path.exists():
                with path.open(errors='replace') as stream:
                    output = ''.join(deque(stream, maxlen=250))
            else:
                output = core.checked('journalctl', '-u', 'fail2ban', '-n', '250', '--no-pager')
            self.page(self.t(action), output)
        elif action == 'test':
            self.working()
            self.page(self.t('ok'), core.validate())
        elif action in ('reload', 'restart'):
            if self.confirm(self.t(action) + '?'):
                self.working()
                with core.locked():
                    core.validate()
                    ident = core.backup(action)
                    output = core.reload_service() if action == 'reload' else core.checked('systemctl', 'restart', 'fail2ban', timeout=60)
                self.page(self.t('ok'), output + '\n' + self.t('saved') + ': ' + ident)
        elif action == 'backup':
            self.working()
            with core.locked():
                ident = core.backup()
            self.page(self.t('ok'), str(core.STATE / 'backups' / ident))
        elif action == 'restore':
            names = core.backups()
            idx = self.menu(self.t(action), names)
            if idx is not None and self.confirm(self.t('restore_warn') + ' ' + names[idx]):
                self.working()
                ident = core.restore(names[idx])
                self.page(self.t('ok'), self.t('saved') + ': ' + ident)
        elif action == 'language':
            self.toggle('l')

    def app(self):
        while True:
            idx = self.menu('menu', ACTIONS, translate=True, icons=True)
            if idx is None or ACTIONS[idx] == 'exit':
                return
            try:
                self.execute(ACTIONS[idx])
            except (ValueError, OSError, RuntimeError) as exc:
                self.page(self.t('error'), str(exc))
