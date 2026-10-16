"""Banned-IP data and actions: listing, unban, ban guards, dashboard summary."""
import datetime
import ipaddress
import os
from pathlib import Path
import re

import f2b_core as core

LOG = Path('/var/log/fail2ban.log')
STAMP = r'\d{4}-\d\d-\d\d \d\d:\d\d:\d\d'
TIMED = re.compile(r'([0-9A-Fa-f:.]+)(?:\s|\\t)+(' + STAMP + r')\s*\+\s*(-?\d+)\s*=\s*(' + STAMP + r'|-?\d+)')
EVENT = re.compile(r'^(\d{4}-\d\d-\d\d) (\d\d:\d\d:\d\d)[,.]\d+ .*?\[([^\]]+)\] (Ban|Unban|Restore Ban) (\S+)')


def jails():
    match = re.search(r'Jail list:\s*([^\n]*)', core.checked('fail2ban-client', 'status'))
    return [v.strip() for v in match.group(1).split(',') if v.strip()] if match else []


def _time(text):
    return datetime.datetime.strptime(text, '%Y-%m-%d %H:%M:%S')


def parse_bans(jail, text):
    """Parse `get <jail> banip --with-time`, or plain IP lists from older versions."""
    bans, seen = [], set()
    for m in TIMED.finditer(text):
        try:
            ip = str(ipaddress.ip_address(m.group(1)))
            start, length = _time(m.group(2)), int(m.group(3))
            end = None if length < 0 or not re.fullmatch(STAMP, m.group(4)) else _time(m.group(4))
        except ValueError:
            continue
        if ip not in seen:
            seen.add(ip)
            bans.append({'jail': jail, 'ip': ip, 'start': start, 'end': end, 'permanent': length < 0})
    if not bans:
        for token in re.split(r'[\s,\[\]\'"]+', text):
            try:
                ip = str(ipaddress.ip_address(token))
            except ValueError:
                continue
            if ip not in seen:
                seen.add(ip)
                bans.append({'jail': jail, 'ip': ip, 'start': None, 'end': None, 'permanent': False})
    return bans


def jail_bans(jail):
    core.check_jail(jail)
    ok, text = core.run('fail2ban-client', 'get', jail, 'banip', '--with-time')
    if ok:
        return parse_bans(jail, text)
    text = core.checked('fail2ban-client', 'status', jail)  # Older servers lack --with-time.
    match = re.search(r'Banned IP list:\s*([^\n]*)', text)
    return parse_bans(jail, match.group(1) if match else '')


def all_bans():
    """(bans, errors). One broken jail must not hide the others."""
    bans, errors = [], []
    for jail in jails():
        try:
            bans.extend(jail_bans(jail))
        except (RuntimeError, ValueError) as exc:
            errors.append(f'{jail}: {exc}')
    return bans, errors


def remaining(ban, now=None):
    """Seconds left, -1 for permanent, None when unknown."""
    if ban.get('permanent'):
        return -1
    if not ban.get('end'):
        return None
    return max(0, int(((ban['end'] - (now or datetime.datetime.now())).total_seconds())))


def duration(seconds, lang='en'):
    if seconds is None:
        return '?'
    if seconds < 0:
        return '∞'
    d, rest = divmod(seconds, 86400)
    h, rest = divmod(rest, 3600)
    m, s = divmod(rest, 60)
    u = ('д', 'ч', 'м', 'с') if lang == 'ru' else ('d', 'h', 'm', 's')
    if d:
        return f'{d}{u[0]} {h:02d}{u[1]}'
    if h:
        return f'{h}{u[1]} {m:02d}{u[2]}'
    return f'{m}{u[2]} {s:02d}{u[3]}' if m else f'{s}{u[3]}'


def own_ips():
    """The operator's address, from the SSH session, so it can be protected."""
    found = set()
    for name in ('SSH_CONNECTION', 'SSH_CLIENT'):
        parts = os.environ.get(name, '').split()
        if parts:
            found.add(parts[0])
    if not found:
        ok, text = core.run('who', 'am', 'i')
        found.update(re.findall(r'\(([0-9A-Fa-f:.]+)\)', text) if ok else [])
    result = set()
    for item in found:
        try:
            result.add(str(ipaddress.ip_address(item)))
        except ValueError:
            pass
    return result


def guard_ban(ip):
    """Refuse addresses that would lock the operator out or are meaningless to ban."""
    addr = ipaddress.ip_address(ip)
    if addr.is_loopback or addr.is_unspecified or addr.is_multicast:
        raise ValueError('Refusing loopback/special address / Нельзя блокировать служебный адрес: ' + str(addr))
    if str(addr) in own_ips():
        raise ValueError('This is YOUR current address; banning it would lock you out / Это ваш текущий адрес: блокировка отрежет доступ: ' + str(addr))
    return str(addr)


def ban(jail, ip):
    core.check_jail(jail)
    ip = guard_ban(ip)
    with core.locked():
        return core.checked('fail2ban-client', 'set', jail, 'banip', ip)


def unban(entries):
    """entries: iterable of (jail, ip). Returns (done, failures)."""
    done, failures = [], []
    with core.locked():
        for jail, ip in entries:
            try:
                core.check_jail(jail)
                core.checked('fail2ban-client', 'set', jail, 'unbanip', str(ipaddress.ip_address(ip)))
                done.append((jail, ip))
            except (RuntimeError, ValueError) as exc:
                failures.append(f'{jail} {ip}: {exc}')
    return done, failures


def summary():
    ok, state = core.run('systemctl', 'is-active', 'fail2ban')
    rows = []
    for jail in jails() if state.strip() == 'active' else []:
        text = core.run('fail2ban-client', 'status', jail)[1]
        pick = lambda label: int((re.search(label + r':\s*(\d+)', text) or [0, 0])[1])
        rows.append({'jail': jail, 'banned': pick('Currently banned'), 'total': pick('Total banned')})
    return {'service': state.strip() or '?', 'jails': rows, 'events': recent_events()}


def recent_events(limit=3, path=None):
    path = path or LOG
    try:
        with path.open('rb') as stream:
            stream.seek(0, os.SEEK_END)
            stream.seek(max(0, stream.tell() - 262144))
            lines = stream.read().decode('utf-8', 'replace').splitlines()
    except OSError:
        return []
    events = []
    for line in reversed(lines):
        m = EVENT.match(line)
        if m:
            try:
                ipaddress.ip_address(m.group(5))
            except ValueError:
                continue
            events.append({'date': m.group(1), 'time': m.group(2), 'jail': m.group(3), 'action': m.group(4), 'ip': m.group(5)})
            if len(events) == limit:
                break
    return events
