"""Privileged operations. No shell commands; one lock for all mutations."""
import configparser
import contextlib
import datetime
import fcntl
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import uuid

VERSION = '0.2.0'
CONFIG = Path('/etc/fail2ban')
STATE = Path('/var/lib/f2b-tui')
INSTALL = Path('/opt/fail2ban-tui')
LAUNCHER = Path('/usr/local/bin/f2b')
REPO = 'https://github.com/barakov-dot/f2b-tui.git'
FILES = ('f2b.py', 'f2b_core.py', 'f2b_ui.py')
SAFE_PATH = '/usr/sbin:/usr/bin:/sbin:/bin'


def run(*args, timeout=30):
    try:
        result = subprocess.run([str(x) for x in args], capture_output=True,
                                text=True, errors='replace', timeout=timeout,
                                env={**os.environ, 'PATH': SAFE_PATH, 'LC_ALL': 'C'})
        return result.returncode == 0, (result.stdout + result.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)


def checked(*args, **kwargs):
    ok, output = run(*args, **kwargs)
    if not ok:
        raise RuntimeError(output or 'Command failed: ' + str(args[0]))
    return output


def private_dir(path):
    if path.is_symlink():
        raise RuntimeError('Refusing symlink: ' + str(path))
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    st = path.stat()
    if st.st_uid != os.geteuid() or st.st_mode & 0o022:
        raise RuntimeError('Unsafe ownership/permissions: ' + str(path))
    os.chmod(path, 0o700)


@contextlib.contextmanager
def locked():
    private_dir(STATE)
    fd = os.open(STATE / 'lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another f2b operation is running / Другая операция f2b уже выполняется')
        yield
    finally:
        os.close(fd)


def atomic_write(path, data, mode=0o600):
    if path.is_symlink() or path.parent.is_symlink():
        raise RuntimeError('Refusing symlink: ' + str(path))
    fd, name = tempfile.mkstemp(prefix='.f2b-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def copy_config(source, target):
    """copy2 preserves modes/times; explicitly retain ownership, including links."""
    shutil.copytree(source, target, symlinks=True)
    for directory, dirs, files in os.walk(source, followlinks=False):
        for path in [Path(directory), *(Path(directory) / name for name in dirs + files)]:
            destination = target / path.relative_to(source)
            before, after = path.lstat(), destination.lstat()
            if (before.st_uid, before.st_gid) != (after.st_uid, after.st_gid):
                os.chown(destination, before.st_uid, before.st_gid, follow_symlinks=False)


def backup(reason='manual'):
    """Caller holds lock. Publish only complete snapshots; keep symbolic links as links."""
    if CONFIG.is_symlink() or not CONFIG.is_dir():
        raise RuntimeError('Expected real configuration directory: ' + str(CONFIG))
    root = STATE / 'backups'
    private_dir(root)
    ident = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + uuid.uuid4().hex[:8]
    staging = Path(tempfile.mkdtemp(prefix='.pending-', dir=root))
    try:
        copy_config(CONFIG, staging / 'config')
        atomic_write(staging / 'metadata.json', json.dumps({'reason': reason, 'version': VERSION}).encode())
        os.rename(staging, root / ident)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return ident


def backups():
    root = STATE / 'backups'
    if not root.exists():
        return []
    return sorted((p.name for p in root.iterdir() if re.fullmatch(r'\d{8}T\d{6}Z-[a-f0-9]{8}', p.name)
                   and not p.is_symlink() and (p / 'config').is_dir()), reverse=True)


def validate():
    return checked('fail2ban-client', '-c', CONFIG, '-t')


def reload_service():
    return checked('fail2ban-client', '-c', CONFIG, 'reload', timeout=60)


def write_setting(jail, key, value):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', jail) or jail.startswith('-') or jail == 'DEFAULT':
        raise ValueError('Invalid jail / Некорректный jail')
    if key not in ('bantime', 'findtime', 'maxretry'):
        raise ValueError('Invalid setting / Некорректный параметр')
    if not re.fullmatch(r'[0-9]+', value) or not 1 <= int(value) <= 31536000:
        raise ValueError('1..31536000 required / Нужно число от 1 до 31536000')
    with locked():
        target = CONFIG / 'jail.d' / '99-f2b-tui.local'
        if target.is_symlink() or target.parent.is_symlink():
            raise RuntimeError('Refusing symlink: ' + str(target))
        validate()  # Do not attribute pre-existing errors to this edit.
        before = target.read_bytes() if target.exists() else None
        mode = target.stat().st_mode & 0o777 if target.exists() else 0o600
        cfg = configparser.ConfigParser(interpolation=None)
        if before is not None:
            cfg.read_string(before.decode('utf-8'))
        if not cfg.has_section(jail):
            cfg.add_section(jail)
        cfg.set(jail, key, str(int(value)))
        buf = io.StringIO()
        cfg.write(buf)
        ident = backup('edit ' + jail + ' ' + key)
        target.parent.mkdir(exist_ok=True)
        try:
            atomic_write(target, buf.getvalue().encode(), mode)
            validate()
            reload_service()
            # Detect a later override silently masking the setting.
            effective = checked('fail2ban-client', 'get', jail, key)
            if effective.strip() != str(int(value)):
                raise RuntimeError('Effective value differs / Значение перекрыто другим конфигом: ' + effective)
        except BaseException as exc:
            try:
                if before is None:
                    target.unlink(missing_ok=True)
                else:
                    atomic_write(target, before, mode)
                reload_service()
            except Exception as rollback:
                raise RuntimeError(f'{exc}\nRollback needs attention / Ошибка отката: {rollback}\nBackup: {ident}') from exc
            raise RuntimeError(f'{exc}\nRolled back / Изменение отменено. Backup: {ident}') from exc
        return ident


def restore(ident):
    with locked():
        if ident not in backups():
            raise ValueError('Unknown backup / Неизвестная копия')
        source = STATE / 'backups' / ident / 'config'
        if source.is_symlink():
            raise RuntimeError('Refusing symlink backup')
        safety = backup('before restore ' + ident)
        # Same filesystem permits directory renames. A mount point fails safely.
        staging = Path(tempfile.mkdtemp(prefix='.f2b-restore-', dir=CONFIG.parent))
        old = staging / 'previous'
        moved = False
        try:
            copy_config(source, staging / 'next')
            checked('fail2ban-client', '-c', staging / 'next', '-t')
            os.rename(CONFIG, old)
            moved = True
            os.rename(staging / 'next', CONFIG)
            validate()
            reload_service()
        except BaseException as exc:
            if moved:
                try:
                    if CONFIG.exists():
                        os.rename(CONFIG, staging / 'failed')
                    os.rename(old, CONFIG)
                    reload_service()
                except Exception as rollback:
                    # Keep previous tree if a rename failed; never discard recovery data.
                    raise RuntimeError(f'{exc}\nRollback failed: {rollback}\nRecovery: {staging}\nBackup: {safety}') from exc
            raise RuntimeError(f'{exc}\nRestore cancelled / Восстановление отменено. Backup: {safety}') from exc
        finally:
            if staging.exists() and not old.exists():
                shutil.rmtree(staging)
        if staging.exists():
            shutil.rmtree(staging)
        return safety


def install(source):
    """Install reviewed source. Keep previous program until new launcher is verified."""
    source = Path(source).resolve()
    with locked():
        if INSTALL.is_symlink():
            raise RuntimeError('Refusing symlink installation')
        if os.path.lexists(LAUNCHER) and (not LAUNCHER.is_symlink() or os.readlink(LAUNCHER) != str(INSTALL / 'f2b.py')):
            raise RuntimeError('Refusing to overwrite unrelated launcher: ' + str(LAUNCHER))
        ident = backup('install/update')
        INSTALL.parent.mkdir(parents=True, exist_ok=True)
        LAUNCHER.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix='.f2b-install-', dir=INSTALL.parent))
        new, old = staging / 'next', staging / 'previous'
        had_old = INSTALL.exists()
        activated = False
        success = False
        had_launcher = os.path.lexists(LAUNCHER)
        try:
            new.mkdir(mode=0o755)
            os.chmod(new, 0o755)
            for name in FILES:
                src = source / name
                if src.is_symlink() or not src.is_file():
                    raise RuntimeError('Missing or symbolic source: ' + name)
                compile(src.read_bytes(), name, 'exec')
                shutil.copyfile(src, new / name)
                os.chmod(new / name, 0o755 if name == 'f2b.py' else 0o644)
            atomic_write(new / 'INSTALL.json', json.dumps({'version': VERSION, 'files': FILES}).encode(), 0o644)
            checked('/usr/bin/python3', '-I', new / 'f2b.py', '--version')
            # Replacing a legacy installation preserves every unknown file.
            if had_old:
                for entry in INSTALL.iterdir():
                    if entry.name not in (*FILES, 'INSTALL.json', '__pycache__'):
                        if entry.is_dir() and not entry.is_symlink():
                            shutil.copytree(entry, new / entry.name, symlinks=True)
                        else:
                            shutil.copy2(entry, new / entry.name, follow_symlinks=False)
                os.rename(INSTALL, old)
            os.rename(new, INSTALL)
            activated = True
            # Create the temporary symlink on the destination filesystem.
            temp_link = LAUNCHER.parent / ('.f2b-link-' + uuid.uuid4().hex)
            try:
                temp_link.symlink_to(INSTALL / 'f2b.py')
                os.replace(temp_link, LAUNCHER)
            finally:
                temp_link.unlink(missing_ok=True)
            checked('/usr/bin/python3', '-I', INSTALL / 'f2b.py', '--version')
            success = True
        except BaseException:
            if activated:
                os.rename(INSTALL, staging / 'failed')
            if old.exists():
                os.rename(old, INSTALL)
            if not had_launcher and activated and LAUNCHER.is_symlink() and os.readlink(LAUNCHER) == str(INSTALL / 'f2b.py'):
                LAUNCHER.unlink()
            raise
        finally:
            # If rollback rename itself fails, retain previous program for recovery.
            if not old.exists() or success:
                shutil.rmtree(staging)
        return ident


def uninstall():
    with locked():
        if INSTALL.is_symlink():
            raise RuntimeError('Refusing symlink installation')
        ident = backup('uninstall')
        if LAUNCHER.is_symlink() and os.readlink(LAUNCHER) == str(INSTALL / 'f2b.py'):
            LAUNCHER.unlink()
        for name in (*FILES, 'INSTALL.json'):
            (INSTALL / name).unlink(missing_ok=True)
        # Unknown files are intentionally retained, including caches.
        try:
            INSTALL.rmdir()
        except OSError:
            pass
        return ident


@contextlib.contextmanager
def update_source(ref):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]{0,150}', ref) or '..' in ref:
        raise ValueError('Invalid Git ref')
    with tempfile.TemporaryDirectory(prefix='f2b-update-') as directory:
        src = Path(directory)
        # Isolate Git from root's hooks/config, including insteadOf URL rewrites.
        env = {'PATH': SAFE_PATH, 'HOME': directory, 'GIT_CONFIG_NOSYSTEM': '1',
               'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_TERMINAL_PROMPT': '0', 'LC_ALL': 'C'}
        for args in (('git', 'init', '-q', directory),
                     ('git', '-C', directory, 'fetch', '--depth=1', REPO, ref),
                     ('git', '-C', directory, 'checkout', '--detach', 'FETCH_HEAD')):
            subprocess.run(args, env=env, check=True, timeout=180, stdin=subprocess.DEVNULL)
        commit = subprocess.check_output(('git', '-C', directory, 'rev-parse', 'HEAD'), env=env, text=True).strip()
        yield src, commit
