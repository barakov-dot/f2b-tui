"""RU/EN curses interface, with keyboard-only cancellation and bounded rendering."""
import contextlib
import curses
import ipaddress
import json
import locale
import os
import re
import textwrap
import time
import unicodedata
from collections import deque

import f2b_bans as bans
import f2b_core as core
import f2b_geo as geo

TEXT = {
    'menu': ('Панель управления', 'Control panel'),
    'overview': ('Обзор службы и jail', 'Service and jail overview'),
    'details': ('Jail и их статус', 'Jail details'),
    'ban': ('Заблокировать IP', 'Ban IP'),
    'unban': ('Заблокированные IP · разбан', 'Banned IPs · unban'),
    'edit': ('Время блокировки и попытки', 'Timing and retry settings'),
    'logs': ('Журнал Fail2ban', 'Fail2ban log'),
    'follow': ('Журнал в реальном времени', 'Live log'),
    'geo': ('Геобаза и поиск IP', 'Geo database and IP lookup'),
    'test': ('Проверить конфигурацию', 'Validate configuration'),
    'reload': ('Перечитать конфигурацию', 'Reload configuration'),
    'restart': ('Перезапустить Fail2ban', 'Restart Fail2ban'),
    'backup': ('Создать резервную копию', 'Create configuration backup'),
    'restore': ('Восстановить конфигурацию', 'Restore configuration'),
    'language': ('Язык / Language', 'Language / Язык'), 'exit': ('Выход', 'Exit'),
    'nav': ('↑↓ выбор · Enter открыть · ESC назад · L язык · A значки · F флаги', '↑↓ select · Enter open · ESC back · L language · A icons · F flags'),
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
    'help': ('CLI: sudo f2b update | uninstall | backup | backups | restore ID | geo-update | geo-lookup IP', 'CLI: sudo f2b update | uninstall | backup | backups | restore ID | geo-update | geo-lookup IP'),
    # dashboard
    'banned_now': ('сейчас в бане', 'banned now'), 'banned_total': ('всего банов', 'total bans'),
    'jails_word': ('jail', 'jails'),
    # banned IP list
    'bans_nav': ('Enter разбан · Пробел отметка · / поиск · s сортировка · i инфо · ? помощь · ESC', 'Enter unban · Space mark · / search · s sort · i info · ? help · ESC'),
    'bans_nav_short': ('Enter разбан · Пробел · / · ? · ESC', 'Enter unban · Space · / · ? · ESC'),
    'col_ip': ('IP-адрес', 'IP address'), 'col_jail': ('Jail', 'Jail'), 'col_left': ('Осталось', 'Left'),
    'col_net': ('Сеть / провайдер', 'Network / provider'),     'sort': ('сортировка', 'sort'), 'you': ('вы', 'you'),
    'sort_time': ('время', 'time'), 'sort_country': ('страна', 'country'), 'sort_network': ('сеть', 'network'),
    'sort_jail': ('jail', 'jail'), 'sort_ip': ('IP', 'IP'),
    'filter': ('фильтр', 'filter'), 'filter_prompt': ('Поиск: IP, jail, страна, сеть (пусто — сбросить)', 'Search: IP, jail, country, network (empty clears)'),
    'marked': ('отмечено', 'marked'),
    'no_bans': ('Сейчас нет заблокированных IP', 'No banned IPs right now'),
    'no_match': ('Ничего не найдено', 'Nothing matches'),
    'no_geo': ('нет гео-базы: Меню → Геобаза', 'no geo database: Menu → Geo'),
    'unban_title': ('Разблокировать:', 'Unban:'),
    'unban_y': ('[y] разбанить в этом jail', '[y] unban in this jail'),
    'unban_a': ('[a] разбанить во всех jail', '[a] unban in all jails'),
    'unban_w': ('[w] разбанить и добавить в исключения (ignoreip) — больше не банить', '[w] unban and add to ignoreip — never ban again'),
    'unban_w_note': ('    (запишется в 99-f2b-tui.local, будет reload; список ignoreip этого jail фиксируется)', '    (written to 99-f2b-tui.local, triggers reload; freezes this jail\'s ignoreip list)'),
    'unban_n': ('[n] / ESC отмена', '[n] / ESC cancel'),
    'ask_keys': ('Нажмите клавишу из списка', 'Press one of the listed keys'),
    'unbanned': ('разбанено', 'unbanned'), 'failed': ('ошибок', 'failed'),
    'groups': ('Сети с несколькими IP', 'Networks with several IPs'),
    'groups_none': ('Нет сетей с несколькими IP', 'No networks with several IPs'),
    'unknown_net': ('неизвестная сеть', 'unknown network'),
    'online_ask': ('Отправить этот IP на ipwho.is и rdap.org для уточнения города и сети?', 'Send this IP to ipwho.is and rdap.org to get city and network?'),
    'online_keys': ('[y] да · [n] / ESC нет', '[y] yes · [n] / ESC no'),
    'online_wait': ('Запрос ipwho.is и RDAP… (ESC не прерывает)', 'Querying ipwho.is and RDAP… (ESC does not interrupt)'),
    'help_bans': (
        '↑↓ j k PgUp PgDn Home End — перемещение\n'
        'Enter — разбанить отмеченные (или выбранный) IP\n'
        'Пробел — отметить / снять отметку; * — отметить все видимые\n'
        '/ — поиск по IP, jail, стране, сети; пустая строка сбрасывает\n'
        's — сортировка: время, страна, сеть, jail, IP\n'
        'i — подробности об IP (офлайн-база)\n'
        'o — уточнить город/сеть онлайн (спросит разрешение)\n'
        'g — сети, из которых забанено несколько IP\n'
        'b — заблокировать IP вручную\n'
        'r — обновить сейчас (список обновляется сам каждые 5 с)\n'
        'L язык · A значки (Unicode → Nerd Font → ASCII) · F флаги\n'
        'ESC / q — назад',
        '↑↓ j k PgUp PgDn Home End — move\n'
        'Enter — unban the marked (or selected) IPs\n'
        'Space — mark / unmark; * — mark all visible\n'
        '/ — search by IP, jail, country, network; empty clears\n'
        's — sort: time, country, network, jail, IP\n'
        'i — IP details (offline database)\n'
        'o — look up city/network online (asks first)\n'
        'g — networks with several banned IPs\n'
        'b — ban an IP manually\n'
        'r — refresh now (the list refreshes itself every 5 s)\n'
        'L language · A icons (Unicode → Nerd Font → ASCII) · F flags\n'
        'ESC / q — back'),
    # IP info
    'f_jail': ('Jail', 'Jail'), 'f_since': ('Забанен', 'Banned at'), 'f_until': ('Разбан', 'Unban at'),
    'f_left': ('Осталось', 'Time left'), 'f_country': ('Страна', 'Country'), 'f_city': ('Город', 'City'),
    'f_cidr': ('Подсеть', 'Subnet'), 'f_asn': ('AS', 'AS'), 'f_org': ('Организация', 'Organization'),
    'f_net': ('Имя сети', 'Network name'), 'f_isp': ('Провайдер', 'ISP'), 'f_coords': ('Координаты', 'Coordinates'),
    'f_source': ('Источник', 'Source'), 'src_offline': ('офлайн-база DB-IP', 'offline DB-IP database'),
    'src_online': ('онлайн (кэш)', 'online (cached)'), 'src_none': ('нет данных — обновите геобазу', 'no data — update the geo database'),
    'permanent': ('навсегда', 'permanent'), 'unknown': ('неизвестно', 'unknown'),
    'private_ip': ('Частный/служебный адрес', 'Private/special address'),
    # geo menu
    'geo_status': ('Состояние базы', 'Database status'),
    'geo_update': ('Обновить базу (страна + сеть, ≈12 МБ)', 'Update database (country + network, ≈12 MB)'),
    'geo_lookup': ('Найти любой IP', 'Look up any IP'),
    'geo_clear': ('Очистить онлайн-кэш', 'Clear online cache'),
    'geo_confirm': ('Скачать базы DB-IP Lite (≈12 МБ) с download.db-ip.com?', 'Download DB-IP Lite databases (≈12 MB) from download.db-ip.com?'),
    'geo_progress': ('Загрузка', 'Downloading'), 'geo_cancel': ('ESC — отмена', 'ESC to cancel'),
    'geo_none': ('База не установлена. Выберите «Обновить базу».', 'No database installed. Choose "Update database".'),
    'geo_updated': ('Обновлено', 'Updated'), 'geo_source': ('Источник', 'Source'), 'geo_rows': ('Записей (страна / сеть)', 'Rows (country / network)'),
    'geo_size': ('Размер', 'Size'), 'geo_credit': ('Данные: DB-IP.com, лицензия CC BY 4.0', 'Data: DB-IP.com, CC BY 4.0 license'),
    'cache_cleared': ('Кэш очищен', 'Cache cleared'),
    'cancelled': ('Отменено', 'Cancelled'),
    # live log
    'follow_nav': ('↑↓ PgUp/PgDn прокрутка · End / f — следить · ESC назад', '↑↓ PgUp/PgDn scroll · End / f follow · ESC back'),
    'live': ('● LIVE', '● LIVE'), 'paused': ('Ⅱ пауза', 'Ⅱ paused'),
}
ACTIONS = ['overview', 'details', 'unban', 'ban', 'edit', 'logs', 'follow', 'geo', 'test', 'reload', 'restart', 'backup', 'restore', 'language', 'exit']
ICONS = ['◈', '▣', '⊖', '⊕', '⚙', '≡', '◉', '◍', '✓', '↻', '↯', '▤', '↶', '⌘', '×']
NERD_ICONS = ['', '', '', '', '', '', '', '', '', '', '', '', '', '', '']
MODES = ('unicode', 'nerd', 'ascii')
SORTS = ('time', 'country', 'network', 'jail', 'ip')


def cell_width(text):
    return sum(0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in 'WF' else 1 for c in text)


def clip(text, width):
    out, used = [], 0
    for char in str(text):
        category = unicodedata.category(char)
        if category.startswith('C') and category != 'Co':  # Private use holds Nerd Font icons.
            char = ' '  # Logs must not inject terminal controls.
        size = cell_width(char)
        if used + size > width:
            break
        used += size
        out.append(char)
    return ''.join(out)


def pad(text, width):
    text = clip(text, width)
    return text + ' ' * max(0, width - cell_width(text))


def fill(text, width):
    """Pad only; never clip, so a two-part flag emoji is not cut in half."""
    return text + ' ' * max(0, width - cell_width(text))


def network_text(info):
    parts = []
    if info.get('org'):
        parts.append(f'AS{info["asn"]} {info["org"]}')
    elif info.get('netname'):
        parts.append(info['netname'])
    if info.get('cidr'):
        parts.append(info['cidr'])
    return ' · '.join(parts)


class Cancelled(RuntimeError):
    pass


class UI:
    def __init__(self, screen, lang=None, ascii_mode=False, nerd=False):
        self.s = screen
        self.s.keypad(True)
        self.lang = lang or ('ru' if locale.getlocale()[0] and locale.getlocale()[0].startswith('ru') else 'en')
        forced_ascii = ascii_mode or 'UTF' not in locale.getpreferredencoding(False).upper()
        self.mode = 'ascii' if forced_ascii else ('nerd' if nerd else 'unicode')
        self.flags = True
        self.colors = False
        self.geo = geo.Geo()
        try:
            prefs = json.loads((core.STATE / 'preferences.json').read_text())
            if not lang and prefs.get('language') in ('ru', 'en'):
                self.lang = prefs['language']
            if not forced_ascii and not nerd:
                if prefs.get('icons') in MODES:
                    self.mode = prefs['icons']
                elif prefs.get('ascii'):
                    self.mode = 'ascii'
            elif prefs.get('ascii'):
                self.mode = 'ascii'
            self.flags = bool(prefs.get('flags', True))
        except (OSError, ValueError, AttributeError):
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
                curses.init_pair(4, curses.COLOR_RED, -1)
                curses.init_pair(5, curses.COLOR_GREEN, -1)
                curses.init_pair(6, curses.COLOR_MAGENTA, -1)
                self.colors = True
        except curses.error:
            pass

    @property
    def ascii(self):
        return self.mode == 'ascii'

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
        right = f'{self.lang.upper()} · {self.mode}'
        self.put(0, 1, f'F2B / {core.VERSION}', self.color(1) | curses.A_BOLD)
        self.put(0, max(1, w - 2 - cell_width(right)), right, self.color(1) | curses.A_BOLD)
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

    def set_timeout(self, ms):
        try:
            self.s.timeout(ms)
        except (AttributeError, curses.error):
            pass

    @contextlib.contextmanager
    def blocking(self):
        """Modal dialogs inside a ticking screen wait for keys without redraw ticks."""
        self.set_timeout(-1)
        try:
            yield
        finally:
            self.set_timeout(1000)

    def save_preferences(self):
        try:
            with core.locked():
                core.atomic_write(core.STATE / 'preferences.json', json.dumps(
                    {'language': self.lang, 'ascii': self.ascii, 'icons': self.mode, 'flags': self.flags}).encode())
        except (OSError, RuntimeError) as exc:
            self.page(self.t('error'), str(exc))

    def toggle(self, key):
        if key in ('l', 'L'):
            self.lang = 'en' if self.lang == 'ru' else 'ru'
        elif key in ('a', 'A'):
            self.mode = MODES[(MODES.index(self.mode) + 1) % len(MODES)]
        elif key in ('f', 'F'):
            self.flags = not self.flags
        else:
            return False
        self.save_preferences()
        return True

    def icon(self, i):
        if self.ascii:
            return f'{i + 1:02d}'
        return (NERD_ICONS if self.mode == 'nerd' else ICONS)[i]

    def menu(self, title, choices, translate=False, icons=False, header=None):
        pos = 0
        if not choices:
            self.page(title, self.t('empty'))
            return None
        header = header or []
        while True:
            ready = self.frame(self.t(title) if translate else title)
            h, w = self.s.getmaxyx()
            total_rows = max(1, h - 7)
            head = min(len(header), max(0, total_rows - 10))  # Never starve the menu itself.
            rows = max(1, total_rows - (head + 1 if head else 0))
            first = 4 + (head + 1 if head else 0)
            start = max(0, pos - rows + 1)
            if ready:
                for row, (text, attr) in enumerate(header[:head]):
                    self.put(4 + row, 2, text, attr)
                for row, i in enumerate(range(start, min(len(choices), start + rows))):
                    label = self.t(choices[i]) if translate else choices[i]
                    icon = self.icon(i) if icons else '-'
                    line = f'{">" if i == pos else " "} {icon}  {label}'
                    self.put(row + first, 2, pad(line, w - 5) if i == pos else line, self.color(2) if i == pos else 0)
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

    def ask(self, lines, keys, footer=None):
        """Single-key choice. Returns one of `keys`, 'n' for n, or None for ESC."""
        while True:
            ready = self.frame('', footer or self.t('ask_keys'))
            if ready:
                h, w = self.s.getmaxyx()
                row = 2
                for text, attr in lines:
                    for part in textwrap.wrap(text, max(1, w - 6), subsequent_indent='    ') or ['']:
                        if row < h - 3:
                            self.put(row, 3, part, attr)
                        row += 1
            self.s.refresh()
            key = self.key()
            if key == '\x1b':
                return None
            if ready and isinstance(key, str) and key.lower() in keys + 'n':
                return key.lower()

    def page(self, title, text, styler=None):
        lines = str(text).splitlines() or [self.t('empty')]
        pos, horizontal = 0, 0
        while True:
            ready = self.frame(title, self.t('back').replace('↑↓', 'Up/Down') if self.ascii else self.t('back'))
            h, _ = self.s.getmaxyx()
            rows = max(1, h - 6)
            pos = min(pos, max(0, len(lines) - rows))
            if ready:
                for i, line in enumerate(lines[pos:pos + rows]):
                    self.put(i + 4, 2, line[horizontal:], styler(line) if styler else 0)
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

    def working(self, message=''):
        self.frame(self.t('working'), '')
        if message:
            self.put(4, 2, message)
        self.s.refresh()

    def log_attr(self, line):
        if 'Unban' in line:
            return self.color(5)
        if ' Ban ' in line or ' ERROR ' in line:
            return self.color(4) | curses.A_BOLD
        if ' Found ' in line or ' WARNING ' in line:
            return self.color(3)
        return 0

    # ------------------------------------------------------------ geography helpers

    def cc_code(self, info):
        return info.get('cc') or ('--' if self.ascii else '··')

    def cc_cell(self, info):
        """Free-form country text. Flag emoji width differs between terminals, so never mid-column."""
        code = info.get('cc', '')
        flag = geo.flag(code) if self.flags and not self.ascii else ''
        return f'{code} {flag}'.strip()

    def info_lines(self, ip, ban=None):
        info = self.geo.lookup(ip)
        t = self.t
        lines = [(ip, curses.A_BOLD)]
        field = lambda key, value: lines.append((f'{t(key):<14} {value}', 0)) if value not in ('', None) else None
        if ban:
            field('f_jail', ban['jail'])
            field('f_since', ban['start'].strftime('%Y-%m-%d %H:%M:%S') if ban.get('start') else '')
            left = bans.remaining(ban)
            field('f_until', t('permanent') if left == -1 else ban['end'].strftime('%Y-%m-%d %H:%M:%S') if ban.get('end') else '')
            field('f_left', bans.duration(left, self.lang) if left is not None else '')
        try:
            if not ipaddress.ip_address(ip).is_global:
                field('f_source', t('private_ip'))
        except ValueError:
            pass
        code = info.get('cc', '')
        field('f_country', ' '.join(x for x in (geo.flag(code) if not self.ascii and self.flags else '', code, info.get('country', '')) if x))
        field('f_city', ', '.join(x for x in (info.get('city'), info.get('region')) if x))
        field('f_cidr', info.get('cidr'))
        field('f_asn', f'AS{info["asn"]}' if info.get('asn') else '')
        field('f_org', info.get('org'))
        field('f_net', info.get('netname'))
        field('f_isp', info.get('isp') if info.get('isp') != info.get('org') else '')
        field('f_coords', f'{info["lat"]}, {info["lon"]}' if 'lat' in info else '')
        sources = [t('src_offline')] if info.get('offline') else []
        if info.get('online'):
            sources.append(t('src_online'))
        field('f_source', ', '.join(sources) or t('src_none'))
        return lines

    def show_info(self, ip, ban=None):
        self.page(ip, '\n'.join(text for text, _ in self.info_lines(ip, ban)[1:]))

    def online_flow(self, ip):
        try:
            if not ipaddress.ip_address(ip).is_global:
                self.page(ip, self.t('private_ip'))
                return
        except ValueError:
            return
        answer = self.ask([(self.t('online_ask'), curses.A_BOLD), (ip, 0)], 'yn', self.t('online_keys'))
        if answer != 'y':
            return
        self.working(self.t('online_wait'))
        self.geo.remember(ip, geo.online(ip))
        self.show_info(ip)

    # ------------------------------------------------------------ banned IP list

    def load_bans(self):
        found, errors = bans.all_bans()
        for b in found:
            info = self.geo.lookup(b['ip'])
            b['cc'] = info.get('cc', '')
            b['net'] = network_text(info)
            b['haystack'] = ' '.join((b['ip'], b['jail'], b['cc'], b['net'], info.get('country', ''), info.get('city', ''))).lower()
        return found, errors

    @staticmethod
    def ban_sorter(mode):
        def ipkey(b):
            addr = ipaddress.ip_address(b['ip'])
            return addr.version, int(addr)

        def time_key(b):
            left = bans.remaining(b)
            return (left is None, float('inf') if left == -1 else left or 0, ipkey(b))
        return {'time': time_key,
                'country': lambda b: (b['cc'] == '', b['cc'], ipkey(b)),
                'network': lambda b: (b['net'] == '', b['net'].lower(), ipkey(b)),
                'jail': lambda b: (b['jail'], ipkey(b)),
                'ip': ipkey}[mode]

    def bans_screen(self):
        self.working()
        rows, errors = self.load_bans()
        pos, marks, needle, sort_index, note = 0, set(), '', 0, ''
        last = time.monotonic()
        self.set_timeout(1000)
        try:
            while True:
                view = [b for b in rows if all(word in b['haystack'] for word in needle.lower().split())]
                view.sort(key=self.ban_sorter(SORTS[sort_index]))
                pos = max(0, min(pos, len(view) - 1))
                own = bans.own_ips()
                ready = self.frame(self.t('unban'), self.t('bans_nav') if self.s.getmaxyx()[1] >= 92 else self.t('bans_nav_short'))
                h, w = self.s.getmaxyx()
                if ready:
                    if note:
                        self.put(2, 4 + cell_width(self.t('unban')), note[0], self.color(note[1]))
                    avail = max(1, h - 7)
                    start = max(0, pos - avail + 1)
                    shown = view[start:start + avail]
                    ipw = max([11] + [len(b['ip']) for b in shown])
                    jw = max([4] + [len(b['jail']) for b in shown])
                    on, off = ('[x]', '[ ]') if self.ascii else ('●', '○')
                    cc_w = 2
                    left_w = 8
                    fixed = 2 + len(on) + 1 + cc_w + 1 + ipw + 1 + jw + 1 + left_w + 1
                    head = f'  {" " * len(on)} {pad("CC", cc_w)} {pad(self.t("col_ip"), ipw)} {pad(self.t("col_jail"), jw)} {self.t("col_left"):>{left_w}} {self.t("col_net") if w - 4 - fixed >= 8 else ""}'
                    self.put(3, 2, head, curses.A_DIM)
                    if not view:
                        self.put(5, 4, self.t('no_match') if rows else self.t('no_bans'), self.color(3))
                    for row, b in enumerate(shown):
                        i = start + row
                        selected = i == pos
                        left = bans.duration(bans.remaining(b), self.lang)
                        if self.ascii and left == '∞':
                            left = 'perm'
                        info = self.geo.lookup(b['ip'])
                        you = f'({self.t("you")}) ' if b['ip'] in own else ''
                        flag = geo.flag(info.get('cc', '')) if self.flags and not self.ascii else ''
                        line = (f'{">" if selected else " "} {on if (b["jail"], b["ip"]) in marks else off} {pad(self.cc_code(info), cc_w)} '
                                f'{pad(b["ip"], ipw)} {pad(b["jail"], jw)} {left:>{left_w}} {you}{b["net"]}' + (f'  {flag}' if flag else ''))
                        attr = self.color(2) if selected else (self.color(3) if b['ip'] in own else 0)
                        self.put(row + 4, 2, fill(line, w - 5) if selected else line, attr)
                    status = [f'{pos + 1 if view else 0} / {len(view)}']
                    if len(view) != len(rows):
                        status[0] += f' ({len(rows)})'
                    if marks:
                        status.append(f'{self.t("marked")}: {len(marks)}')
                    if needle:
                        status.append(f'{self.t("filter")}: {needle}')
                    status.append(f'{self.t("sort")}: {self.t("sort_" + SORTS[sort_index])}')
                    if not self.geo.available():
                        status.append(self.t('no_geo'))
                    if errors:
                        status.append(errors[0][:60])
                    self.put(h - 3, 2, ' · '.join(status), self.color(4) if errors else self.color(3))
                self.s.refresh()
                key = self.key()
                if key is None:
                    if time.monotonic() - last >= 5:
                        rows, errors = self.refresh_bans(rows, marks)
                        last = time.monotonic()
                    continue
                if key in ('\x1b', 'q', 'Q'):
                    return
                if self.toggle(key) or not ready:
                    continue
                current = view[pos] if view else None
                if key in (curses.KEY_DOWN, 'j'):
                    pos = (pos + 1) % len(view) if view else 0
                elif key in (curses.KEY_UP, 'k'):
                    pos = (pos - 1) % len(view) if view else 0
                elif key == curses.KEY_NPAGE:
                    pos = min(len(view) - 1, pos + max(1, h - 7))
                elif key == curses.KEY_PPAGE:
                    pos = max(0, pos - max(1, h - 7))
                elif key == curses.KEY_HOME:
                    pos = 0
                elif key == curses.KEY_END:
                    pos = max(0, len(view) - 1)
                elif key == ' ' and current:
                    marks ^= {(current['jail'], current['ip'])}
                    pos = min(len(view) - 1, pos + 1)
                elif key == '*' and view:
                    everyone = {(b['jail'], b['ip']) for b in view}
                    marks = marks - everyone if everyone <= marks else marks | everyone
                elif key == '/':
                    with self.blocking():
                        answer = self.prompt(self.t('filter_prompt'))
                    if answer is not None:
                        needle, pos = answer, 0
                elif key == 's':
                    sort_index = (sort_index + 1) % len(SORTS)
                elif key == 'i' and current:
                    with self.blocking():
                        self.show_info(current['ip'], current)
                elif key == 'o' and current:
                    with self.blocking():
                        self.guarded(self.online_flow, current['ip'])
                    rows, errors = self.safe_reload(rows, errors)
                elif key == 'g':
                    with self.blocking():
                        self.page(self.t('groups'), self.group_report(rows))
                elif key == 'b':
                    with self.blocking():
                        self.guarded(self.execute, 'ban')
                    rows, errors = self.safe_reload(rows, errors)
                elif key == 'r':
                    rows, errors = self.safe_reload(rows, errors)
                    last = time.monotonic()
                elif key == '?':
                    with self.blocking():
                        self.page('?', self.t('help_bans'))
                elif key in ('\n', '\r', curses.KEY_ENTER) and current:
                    targets = [b for b in rows if (b['jail'], b['ip']) in marks] or [current]
                    with self.blocking():
                        outcome = self.guarded(self.unban_flow, targets, rows)
                    if outcome:
                        done, failures = outcome
                        marks -= set(done)
                        note = (f'{self.t("unbanned")}: {len(done)}' + (f' · {self.t("failed")}: {len(failures)}' if failures else ''),
                                4 if failures else 5)
                        if failures:
                            with self.blocking():
                                self.page(self.t('error'), '\n'.join(failures))
                        rows, errors = self.safe_reload(rows, errors)
                        last = time.monotonic()
        finally:
            self.set_timeout(-1)

    def guarded(self, function, *args):
        try:
            return function(*args)
        except (ValueError, OSError, RuntimeError) as exc:
            self.page(self.t('error'), str(exc))
            return None

    def safe_reload(self, rows, errors):
        try:
            return self.load_bans()
        except (RuntimeError, OSError, ValueError) as exc:
            self.page(self.t('error'), str(exc))
            return rows, errors

    def refresh_bans(self, rows, marks):
        try:
            fresh = self.load_bans()
        except (RuntimeError, OSError, ValueError):
            return rows, []
        marks &= {(b['jail'], b['ip']) for b in fresh[0]}
        return fresh

    def unban_flow(self, targets, rows):
        shown = targets[:6]
        lines = [(self.t('unban_title'), curses.A_BOLD)]
        for b in shown:
            info = self.geo.lookup(b['ip'])
            lines.append((f'  {b["ip"]}  [{b["jail"]}]  {self.cc_cell(info)}  {b["net"]}', 0))
        if len(targets) > len(shown):
            lines.append((f'  … +{len(targets) - len(shown)}', 0))
        lines += [('', 0), (self.t('unban_y'), self.color(5)), (self.t('unban_a'), self.color(5)),
                  (self.t('unban_w'), self.color(3)), (self.t('unban_w_note'), curses.A_DIM), (self.t('unban_n'), 0)]
        choice = self.ask(lines, 'yaw')
        if choice not in ('y', 'a', 'w'):
            return None
        failures = []
        if choice == 'w':
            self.working()
            for jail, ip in sorted({(b['jail'], b['ip']) for b in targets}):
                try:
                    core.add_ignoreip(jail, ip)
                except (RuntimeError, ValueError) as exc:
                    failures.append(f'{jail} {ip}: {exc}')
        entries = [(b['jail'], b['ip']) for b in targets]
        if choice == 'a':
            ips = {b['ip'] for b in targets}
            entries = [(b['jail'], b['ip']) for b in rows if b['ip'] in ips]
        self.working()
        done, more = bans.unban(entries)
        return done, failures + more

    def group_report(self, rows):
        groups = {}
        for b in rows:
            info = self.geo.lookup(b['ip'])
            name = f'AS{info["asn"]} {info["org"]}' if info.get('org') else info.get('cidr') or self.t('unknown_net')
            group = groups.setdefault(name, {'ips': set(), 'jails': set(), 'cc': set()})
            group['ips'].add(b['ip'])
            group['jails'].add(b['jail'])
            if b['cc']:
                group['cc'].add(b['cc'])
        lines = [f'{len(g["ips"]):>4}  {name}  [{",".join(sorted(g["cc"]))}]  {",".join(sorted(g["jails"]))}'
                 for name, g in sorted(groups.items(), key=lambda item: -len(item[1]['ips'])) if len(g['ips']) > 1]
        return '\n'.join(lines) or self.t('groups_none')

    # ------------------------------------------------------------ dashboard, geo, live log

    def dashboard(self):
        try:
            data = bans.summary()
        except (RuntimeError, OSError, ValueError) as exc:
            return [(str(exc).splitlines()[0] if str(exc) else self.t('error'), self.color(4))]
        healthy = data['service'] == 'active'
        now = sum(j['banned'] for j in data['jails'])
        total = sum(j['total'] for j in data['jails'])
        dot = '*' if self.ascii else '●'
        lines = [(f'{dot} fail2ban: {data["service"]} · {self.t("jails_word")}: {len(data["jails"])} · {self.t("banned_now")}: {now} · {self.t("banned_total")}: {total}',
                  (self.color(5) if healthy else self.color(4)) | curses.A_BOLD)]
        if data['jails']:
            lines.append((' · '.join(f'{j["jail"]} {j["banned"]}' for j in data['jails']), 0))
        for event in data['events']:
            unban = event['action'] == 'Unban'
            info = self.geo.lookup(event['ip'])
            cc = self.cc_cell(info).strip() if info.get('cc') else ''
            lines.append((f'{event["date"][5:]} {event["time"]}  {event["action"]:<6} {event["ip"]}  [{event["jail"]}]  {cc}',
                          self.color(5) if unban else self.color(4)))
        return lines

    def geo_menu(self):
        keys = ['geo_status', 'geo_update', 'geo_lookup', 'geo_clear']
        while True:
            idx = self.menu(self.t('geo'), [self.t(k) for k in keys])
            if idx is None:
                return
            self.guarded(self.geo_action, keys[idx])

    def geo_action(self, key):
        if key == 'geo_status':
            info = self.geo.info()
            if not info:
                self.page(self.t('geo'), self.t('geo_none') + '\n\n' + self.t('geo_credit'))
                return
            self.page(self.t('geo'), '\n'.join([
                f'{self.t("geo_updated")}: {info.get("updated", "?")}', f'{self.t("geo_source")}: {info.get("source", "?")}',
                f'{self.t("geo_rows")}: {info.get("country_rows", "?")} / {info.get("asn_rows", "?")}',
                f'{self.t("geo_size")}: {info["size"] / 1048576:.1f} MB', '', self.t('geo_credit')]))
        elif key == 'geo_update':
            if self.ask([(self.t('geo_confirm'), curses.A_BOLD)], 'yn', self.t('online_keys')) != 'y':
                return
            self.run_geo_update()
        elif key == 'geo_lookup':
            raw = self.prompt(self.t('ip'))
            if raw:
                ip = str(ipaddress.ip_address(raw))
                self.show_info(ip)
                self.online_flow(ip)
        elif key == 'geo_clear':
            geo.clear_cache()
            self.geo.close()
            self.page(self.t('ok'), self.t('cache_cleared'))

    def run_geo_update(self):
        ticker = {'at': 0.0}

        def progress(label, done, total):
            now = time.monotonic()
            if now - ticker['at'] < 0.15:
                return
            ticker['at'] = now
            self.set_timeout(0)
            key = self.key()
            self.set_timeout(-1)
            if key == '\x1b':
                raise Cancelled(self.t('cancelled'))
            size = f'{done / 1048576:.1f}' + (f' / {total / 1048576:.1f}' if total else '')
            self.working(f'{self.t("geo_progress")} {label}: {size} MB    ({self.t("geo_cancel")})')
        self.working()
        self.geo.close()
        meta = geo.update(progress)
        self.geo.close()
        self.page(self.t('ok'), f'{self.t("geo_source")}: {meta["source"]}\n{self.t("geo_rows")}: {meta["country_rows"]} / {meta["asn_rows"]}\n\n{self.t("geo_credit")}')

    def follow_log(self):
        path = bans.LOG
        if not path.exists():
            self.execute('logs')
            return
        lines, partial = deque(maxlen=1000), ''
        following, pos = True, 0
        self.set_timeout(500)
        try:
            with path.open('r', errors='replace') as stream:
                inode = os.fstat(stream.fileno()).st_ino
                size = os.fstat(stream.fileno()).st_size
                stream.seek(max(0, size - 65536))
                if stream.tell():
                    stream.readline()
                lines.extend(stream.read().splitlines()[-250:])
                while True:
                    ready = self.frame(self.t('follow'), self.t('follow_nav'))
                    h, w = self.s.getmaxyx()
                    rows = max(1, h - 6)
                    pos = max(0, len(lines) - rows) if following else min(pos, max(0, len(lines) - rows))
                    if ready:
                        label = self.t('live') if following else self.t('paused')
                        self.put(2, max(2, w - 3 - cell_width(label)), label, self.color(5 if following else 3) | curses.A_BOLD)
                        for i, line in enumerate(list(lines)[pos:pos + rows]):
                            self.put(i + 4, 2, line, self.log_attr(line))
                    self.s.refresh()
                    key = self.key()
                    if key in ('\x1b', 'q', 'Q'):
                        return
                    if key == curses.KEY_DOWN or key == 'j':
                        pos, following = min(max(0, len(lines) - rows), pos + 1), pos + 1 >= len(lines) - rows
                    elif key in (curses.KEY_UP, 'k'):
                        pos, following = max(0, pos - 1), False
                    elif key == curses.KEY_NPAGE:
                        pos = min(max(0, len(lines) - rows), pos + rows)
                        following = pos >= len(lines) - rows
                    elif key == curses.KEY_PPAGE:
                        pos, following = max(0, pos - rows), False
                    elif key == curses.KEY_HOME:
                        pos, following = 0, False
                    elif key in (curses.KEY_END, 'f', 'F'):
                        following = True
                    # Pick up new data; reopen after rotation or truncation.
                    try:
                        current = os.stat(path)
                    except OSError:
                        continue
                    if current.st_ino != inode:
                        return self.follow_log()
                    if current.st_size < stream.tell():
                        stream.seek(0)
                    chunk = partial + stream.read()
                    parts = chunk.split('\n')
                    partial = parts.pop()
                    lines.extend(parts)
        finally:
            self.set_timeout(-1)

    # ------------------------------------------------------------ actions

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
        if action == 'unban':
            self.bans_screen()
        elif action in ('details', 'ban', 'edit'):
            jail = self.choose_jail()
            if jail is None:
                return
            if action == 'details':
                self.working()
                self.page(jail, core.checked('fail2ban-client', 'status', jail))
            elif action == 'ban':
                raw = self.prompt(self.t('ip'))
                if raw is None:
                    return
                ip = bans.guard_ban(raw)
                if self.confirm(f'{self.t(action)}: {ip} / {jail}?'):
                    self.working()
                    self.page(self.t('ok'), bans.ban(jail, ip))
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
            path = bans.LOG
            if path.exists():
                with path.open(errors='replace') as stream:
                    output = ''.join(deque(stream, maxlen=250))
            else:
                output = core.checked('journalctl', '-u', 'fail2ban', '-n', '250', '--no-pager')
            self.page(self.t(action), output, self.log_attr)
        elif action == 'follow':
            self.follow_log()
        elif action == 'geo':
            self.geo_menu()
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
            self.working()
            idx = self.menu('menu', ACTIONS, translate=True, icons=True, header=self.dashboard())
            if idx is None or ACTIONS[idx] == 'exit':
                return
            try:
                self.execute(ACTIONS[idx])
            except Cancelled as exc:
                self.page(self.t('cancelled'), str(exc))
            except (ValueError, OSError, RuntimeError) as exc:
                self.page(self.t('error'), str(exc))
