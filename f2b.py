#!/usr/bin/env python3
"""Fail2ban terminal UI, Python standard library only."""
import curses
import ipaddress
import os
import re
import shlex
import subprocess
from pathlib import Path

OVERRIDE = Path('/etc/fail2ban/jail.d/99-f2b-tui.local')
PATTERN = re.compile(r'^[A-Za-z0-9_-]+$')

def run(*args, timeout=12):
    try:
        p = subprocess.run(args, text=True, capture_output=True, timeout=timeout, check=False)
        return p.returncode == 0, (p.stdout + p.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)

def jails():
    ok, out = run('fail2ban-client', 'status')
    if not ok:
        return [], out
    match = re.search(r'Jail list:\s*(.*)', out)
    names = [x.strip() for x in match.group(1).split(',') if x.strip()] if match else []
    return names, out

def validate_jail(name):
    if not PATTERN.fullmatch(name):
        raise ValueError('Invalid jail name')
    return name

def validate_ip(value):
    return str(ipaddress.ip_address(value.strip()))

def write_setting(jail, setting, value):
    validate_jail(jail)
    if setting not in ('bantime', 'findtime', 'maxretry'):
        raise ValueError('Unsupported setting')
    if not value.isdecimal() or not 1 <= int(value) <= 31536000:
        raise ValueError('Enter positive integer (max 31536000)')
    # Preserve unrelated sections/keys in this managed override file.
    import configparser
    cfg = configparser.ConfigParser(interpolation=None, strict=False)
    cfg.optionxform = str
    if OVERRIDE.exists():
        cfg.read(OVERRIDE)
    if not cfg.has_section(jail):
        cfg.add_section(jail)
    cfg.set(jail, setting, value)
    OVERRIDE.parent.mkdir(parents=True, exist_ok=True)
    temp = OVERRIDE.with_suffix('.tmp')
    with temp.open('w') as f:
        cfg.write(f)
    os.chmod(temp, 0o600)
    os.replace(temp, OVERRIDE)

def prompt(stdscr, title):
    h, w = stdscr.getmaxyx()
    curses.echo()
    curses.curs_set(1)
    try:
        stdscr.move(h-2, 0)
        stdscr.clrtoeol()
        stdscr.addnstr(h-2, 0, title + ': ', max(1, w-1))
        raw = stdscr.getstr(h-2, min(len(title)+2, w-2), 120)
        return raw.decode('utf-8', errors='replace').strip()
    finally:
        curses.noecho()
        curses.curs_set(0)

def page(stdscr, title, content):
    lines = content.splitlines() or ['(empty)']
    start = 0
    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        if h < 5 or w < 25:
            stdscr.addnstr(0, 0, 'Enlarge terminal', max(1,w-1))
        else:
            stdscr.addnstr(0, 0, title, w-1, curses.A_BOLD)
            for i, line in enumerate(lines[start:start + h-3], 1):
                stdscr.addnstr(i, 0, line, w-1)
            stdscr.addnstr(h-1, 0, '↑/↓ scroll | q/ESC back', w-1)
        stdscr.refresh()
        key = stdscr.getch()
        if key in (ord('q'), 27, 10):
            return
        if key in (curses.KEY_DOWN, ord('j')):
            start = min(max(0, len(lines)-(h-3)), start+1)
        if key in (curses.KEY_UP, ord('k')):
            start = max(0, start-1)
        if key == curses.KEY_NPAGE:
            start = min(max(0, len(lines)-(h-3)), start+max(1,h-3))
        if key == curses.KEY_PPAGE:
            start = max(0, start-max(1,h-3))

def confirm(stdscr, question):
    return prompt(stdscr, question + ' [type YES]').strip() == 'YES'

def menu(stdscr, title, choices):
    pos = 0
    while True:
        stdscr.erase()
        h,w = stdscr.getmaxyx()
        stdscr.addnstr(0,0,title,max(1,w-1),curses.A_BOLD)
        for i, item in enumerate(choices[:max(0,h-3)]):
            stdscr.addnstr(i+2,0, ('> ' if i==pos else '  ')+item,max(1,w-1),curses.A_REVERSE if i==pos else 0)
        if h >= 2:
            stdscr.addnstr(h-1,0,'↑/↓ select | Enter confirm | q back',max(1,w-1))
        stdscr.refresh()
        key=stdscr.getch()
        if key in (ord('q'),27): return None
        if key in (curses.KEY_DOWN,ord('j')): pos=(pos+1)%len(choices)
        if key in (curses.KEY_UP,ord('k')): pos=(pos-1)%len(choices)
        if key in (10,13,curses.KEY_ENTER): return pos

def choose_jail(stdscr):
    names, output = jails()
    if not names:
        page(stdscr,'No active jails',output)
        return None
    index = menu(stdscr,'Select jail',names)
    return names[index] if index is not None else None

def show_result(stdscr, title, result):
    ok,out=result
    page(stdscr, ('OK: ' if ok else 'ERROR: ')+title, out or '(no output)')

def app(stdscr):
    curses.curs_set(0)
    stdscr.keypad(True)
    options=['Service and jail overview','Jail details / banned IPs','Ban IP','Unban IP','Edit jail timing/retries','View Fail2ban logs','Validate configuration','Restart Fail2ban','Exit']
    while True:
        selected=menu(stdscr,'FAIL2BAN TUI — sudo f2b',options)
        if selected is None or selected==8: return
        if selected==0:
            a=run('systemctl','is-active','fail2ban')
            b=run('fail2ban-client','status')
            page(stdscr,'Overview',f'Service: {a[1]}\n\n{b[1]}')
        elif selected==1:
            jail=choose_jail(stdscr)
            if jail: show_result(stdscr,jail,run('fail2ban-client','status',jail))
        elif selected in (2,3):
            jail=choose_jail(stdscr)
            if not jail: continue
            raw=prompt(stdscr,'IPv4/IPv6 address')
            try: ip=validate_ip(raw)
            except ValueError: page(stdscr,'Invalid IP',raw); continue
            operation='banip' if selected==2 else 'unbanip'
            if confirm(stdscr,f'{operation} {ip} in {jail}?'):
                show_result(stdscr,operation,run('fail2ban-client','set',jail,operation,ip))
        elif selected==4:
            jail=choose_jail(stdscr)
            if not jail: continue
            idx=menu(stdscr,'Which setting?',['bantime (seconds)','findtime (seconds)','maxretry (count)'])
            if idx is None: continue
            key=['bantime','findtime','maxretry'][idx]
            value=prompt(stdscr,f'{jail} {key} (positive integer)')
            try:
                write_setting(jail,key,value)
                ok,out=run('fail2ban-client','-t')
                if not ok:
                    page(stdscr,'Config test failed — fix before reload',out)
                elif confirm(stdscr,'Config valid. Reload Fail2ban now?'):
                    show_result(stdscr,'reload',run('fail2ban-client','reload'))
                else:
                    page(stdscr,'Saved',f'{OVERRIDE}\nChanges take effect after reload.')
            except (ValueError,OSError) as e:
                page(stdscr,'Error',str(e))
        elif selected==5:
            path=Path('/var/log/fail2ban.log')
            if path.exists():
                try: data=path.read_text(errors='replace').splitlines()[-250:]
                except OSError as e: data=[str(e)]
                page(stdscr,'Last 250 log lines','\n'.join(data))
            else:
                show_result(stdscr,'journalctl',run('journalctl','-u','fail2ban','-n','250','--no-pager'))
        elif selected==6: show_result(stdscr,'Config test',run('fail2ban-client','-t'))
        elif selected==7:
            if confirm(stdscr,'Restart fail2ban?'):
                show_result(stdscr,'Restart',run('systemctl','restart','fail2ban'))

def main():
    if os.geteuid()!=0:
        print('Run with sudo: sudo f2b')
        raise SystemExit(1)
    curses.wrapper(app)

if __name__=='__main__': main()
