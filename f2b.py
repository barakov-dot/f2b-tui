#!/usr/bin/python3 -I
"""Fail2ban TUI entry point. Use isolated Python even when invoked through sudo."""
import argparse
import locale
import os
from pathlib import Path
import sys

# -I excludes script directory too: import only this resolved, trusted installation.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import f2b_core as core


def confirm(message, yes=False):
    print(message)
    if yes:
        return True
    if not sys.stdin.isatty():
        raise RuntimeError('Confirmation requires a terminal; use --yes / Нужен терминал или --yes')
    try:
        return input('Type YES / Введите YES: ').strip() == 'YES'
    except EOFError:
        return False


def main(argv=None):
    parser = argparse.ArgumentParser(description='Fail2ban TUI / Панель управления Fail2ban')
    parser.add_argument('--version', action='version', version=core.VERSION)
    parser.add_argument('--lang', choices=('ru', 'en'))
    parser.add_argument('--ascii', action='store_true', help='ASCII icons / значки ASCII')
    sub = parser.add_subparsers(dest='command')
    for command in ('backup', 'backups'):
        sub.add_parser(command)
    p = sub.add_parser('restore')
    p.add_argument('id')
    p.add_argument('--yes', action='store_true')
    p = sub.add_parser('update')
    p.add_argument('--ref', default='main', help='Git tag or full commit SHA (default: main)')
    p.add_argument('--yes', action='store_true')
    p = sub.add_parser('uninstall')
    p.add_argument('--yes', action='store_true')
    p = sub.add_parser('install', help=argparse.SUPPRESS)
    p.add_argument('source')
    args = parser.parse_args(argv)
    if os.geteuid() != 0:
        parser.exit(1, 'Run with sudo / Запустите через sudo: sudo f2b\n')
    os.environ['PATH'] = core.SAFE_PATH
    os.umask(0o077)
    try:
        if args.command == 'backup':
            with core.locked():
                print(core.backup())
        elif args.command == 'backups':
            print('\n'.join(core.backups()) or 'No backups / Нет копий')
        elif args.command == 'restore':
            if confirm('Replace ALL /etc/fail2ban and reload / Заменить ВСЮ /etc/fail2ban и выполнить reload: ' + args.id, args.yes):
                print('Safety backup / Страховочная копия:', core.restore(args.id))
        elif args.command == 'uninstall':
            if confirm('Remove TUI only; preserve Fail2ban, configs, backups / Удалить только панель, сохранив конфиги и копии?', args.yes):
                print('Backup / Копия:', core.uninstall())
        elif args.command == 'install':
            print('Backup / Копия:', core.install(args.source))
        elif args.command == 'update':
            with core.update_source(args.ref) as (source, commit):
                if confirm('Install code from / Установить код из ' + core.REPO + '\nCommit: ' + commit, args.yes):
                    # Use the downloaded installer so future release migrations are supported.
                    core.checked('/bin/bash', source / 'install.sh', timeout=180)
                    print('Updated / Обновлено:', commit)
        else:
            import curses
            import f2b_ui
            locale.setlocale(locale.LC_ALL, '')
            curses.wrapper(lambda screen: f2b_ui.UI(screen, args.lang, args.ascii).app())
        return 0
    except (OSError, ValueError, RuntimeError, core.subprocess.SubprocessError) as exc:
        print('ERROR / ОШИБКА: ' + str(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('\nCancelled / Отменено', file=sys.stderr)
        return 130


if __name__ == '__main__':
    sys.exit(main())
