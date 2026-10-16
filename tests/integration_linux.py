"""Real Fail2ban daemon, private config/socket, no firewall actions. Linux/root only."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import f2b_core as core


def main():
    assert sys.platform == 'linux' and os.geteuid() == 0
    with tempfile.TemporaryDirectory(prefix='f2b-integration-') as directory:
        root = Path(directory)
        config = root / 'config'
        shutil.copytree('/etc/fail2ban', config, symlinks=True)
        (root / 'auth.log').touch()
        (config / 'jail.local').write_text('[DEFAULT]\nenabled = false\n[sshd]\nenabled = false\n[f2b-test]\nenabled = true\nbackend = polling\nfilter = f2b-test\nlogpath = ' + str(root / 'auth.log') + '\naction =\nbantime = 30\nfindtime = 60\nmaxretry = 2\n')
        (config / 'filter.d/f2b-test.conf').write_text('[Definition]\nfailregex = ^<HOST> failed$\nignoreregex =\n')
        socket, pid = root / 'server.sock', root / 'server.pid'
        (config / 'fail2ban.local').write_text('[Definition]\nsocket = ' + str(socket) + '\npidfile = ' + str(pid) + '\nlogtarget = ' + str(root / 'fail2ban.log') + '\ndbfile = ' + str(root / 'db.sqlite3') + '\n')
        base = ['fail2ban-client', '-c', str(config), '-s', str(socket), '-p', str(pid)]
        subprocess.run(base + ['-x', 'start'], check=True)
        original_run = core.run
        def isolated_run(*args, **kwargs):
            if args[0] == 'fail2ban-client':
                args = (args[0], '-s', socket, *args[1:])
            return original_run(*args, **kwargs)
        try:
            with patch.object(core, 'CONFIG', config), patch.object(core, 'STATE', root / 'state'), patch.object(core, 'run', side_effect=isolated_run):
                os.chown(config / 'jail.local', 65534, 65534)
                customer = (config / 'jail.local').read_bytes()
                with core.locked():
                    snapshot = core.backup()
                for ip in ('192.0.2.19', '2001:db8::19'):
                    core.checked('fail2ban-client', 'set', 'f2b-test', 'banip', ip)
                    assert ip in core.checked('fail2ban-client', 'get', 'f2b-test', 'banip')
                    core.checked('fail2ban-client', 'set', 'f2b-test', 'unbanip', ip)
                core.write_setting('f2b-test', 'bantime', '600')
                assert core.checked('fail2ban-client', 'get', 'f2b-test', 'bantime') == '600'
                assert (config / 'jail.local').read_bytes() == customer
                # Real reload, then simulated failure at the response boundary: rollback must reapply old value.
                real_reload = core.reload_service
                calls = 0
                def failed_response():
                    nonlocal calls
                    calls += 1
                    result = real_reload()
                    if calls == 1:
                        raise RuntimeError('injected lost reload response')
                    return result
                with patch.object(core, 'reload_service', side_effect=failed_response):
                    try:
                        core.write_setting('f2b-test', 'bantime', '900')
                        raise AssertionError('expected rollback')
                    except RuntimeError as exc:
                        assert 'Rolled back' in str(exc), str(exc)
                assert core.checked('fail2ban-client', 'get', 'f2b-test', 'bantime') == '600'
                core.restore(snapshot)
                assert core.checked('fail2ban-client', 'get', 'f2b-test', 'bantime') == '30'
                assert not (config / 'jail.d/99-f2b-tui.local').exists()
                assert (config / 'jail.local').stat().st_uid == 65534
                assert (config / 'jail.local').stat().st_gid == 65534
                assert (config / 'jail.local').read_bytes() == customer
                # Real staged install smoke checks, upgrade, and removal, under a private prefix.
                with patch.object(core, 'INSTALL', root / 'opt/app'), patch.object(core, 'LAUNCHER', root / 'bin/f2b'):
                    source = Path(__file__).resolve().parents[1]
                    core.install(source)
                    assert subprocess.check_output([str(core.LAUNCHER), '--version'], text=True).strip() == core.VERSION
                    core.install(source)
                    core.uninstall()
                    assert not core.LAUNCHER.exists()
                    assert not core.INSTALL.exists()
                    assert (config / 'jail.local').read_bytes() == customer
                print('PASS: live IPv4/IPv6 ban/unban, edit/reload, rollback, restore, install/update/uninstall; customer config unchanged')
        finally:
            subprocess.run(base + ['stop'], check=False)


if __name__ == '__main__':
    main()
