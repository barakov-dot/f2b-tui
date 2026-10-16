import contextlib
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import f2b_core as core


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = self.root / 'etc/fail2ban'
        self.config.mkdir(parents=True)
        (self.config / 'jail.d').mkdir()
        (self.config / 'jail.local').write_text('# customer\n[sshd]\nenabled = true\n')
        self.override = self.config / 'jail.d/99-f2b-tui.local'
        self.state = self.root / 'state'
        self.install = self.root / 'opt/fail2ban-tui'
        self.launcher = self.root / 'bin/f2b'
        self.stack = contextlib.ExitStack()
        for name, value in [('CONFIG', self.config), ('STATE', self.state), ('INSTALL', self.install), ('LAUNCHER', self.launcher)]:
            self.stack.enter_context(patch.object(core, name, value))
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.stack.close)

    def test_backup_preserves_bytes_permissions_and_links(self):
        (self.config / 'jail.local').chmod(0o640)
        (self.config / 'linked').symlink_to('jail.local')
        with core.locked():
            ident = core.backup()
        saved = self.state / 'backups' / ident / 'config'
        self.assertEqual((saved / 'jail.local').read_bytes(), (self.config / 'jail.local').read_bytes())
        self.assertEqual((saved / 'jail.local').stat().st_mode & 0o777, 0o640)
        self.assertEqual(os.readlink(saved / 'linked'), 'jail.local')
        self.assertEqual((self.state / 'backups').stat().st_mode & 0o777, 0o700)
        self.assertEqual(core.backups(), [ident])

    def test_edit_keeps_user_files(self):
        original = (self.config / 'jail.local').read_bytes()
        self.override.write_text('[other]\nmaxretry = 9\n')
        with patch.object(core, 'checked', return_value='600'):
            ident = core.write_setting('sshd', 'bantime', '600')
        self.assertEqual((self.config / 'jail.local').read_bytes(), original)
        self.assertIn('[other]', self.override.read_text())
        self.assertIn('bantime = 600', self.override.read_text())
        self.assertIn(ident, core.backups())

    def test_validation_failure_restores_exact_override(self):
        original = b'# keep comments\n[sshd]\nbantime = 10\n'
        self.override.write_bytes(original)
        with patch.object(core, 'validate', side_effect=['OK', RuntimeError('bad config')]), patch.object(core, 'reload_service') as reload:
            with self.assertRaisesRegex(RuntimeError, 'Rolled back'):
                core.write_setting('sshd', 'bantime', '600')
        self.assertEqual(self.override.read_bytes(), original)
        reload.assert_called_once()

    def test_reload_failure_removes_new_override(self):
        with patch.object(core, 'validate'), patch.object(core, 'reload_service', side_effect=[RuntimeError('reload failed'), 'OK']):
            with self.assertRaisesRegex(RuntimeError, 'Rolled back'):
                core.write_setting('sshd', 'bantime', '600')
        self.assertFalse(self.override.exists())

    def test_masked_value_rolls_back(self):
        with patch.object(core, 'checked', return_value='9'):
            with self.assertRaisesRegex(RuntimeError, 'Effective value differs'):
                core.write_setting('sshd', 'bantime', '600')
        self.assertFalse(self.override.exists())

    def test_rollback_failure_reports_backup(self):
        with patch.object(core, 'validate'), patch.object(core, 'reload_service', side_effect=RuntimeError('offline')):
            with self.assertRaisesRegex(RuntimeError, 'Rollback needs attention.*|Ошибка отката') as err:
                core.write_setting('sshd', 'bantime', '600')
        self.assertIn('Backup:', str(err.exception))
        self.assertFalse(self.override.exists())

    def test_invalid_input_does_not_backup_or_write(self):
        for jail, key, value in [('x\n[DEFAULT]', 'bantime', '1'), ('sshd', 'action', '1'), ('sshd', 'maxretry', '-1'), ('sshd', 'bantime', '999999999999999999999999')]:
            with self.assertRaises(ValueError):
                core.write_setting(jail, key, value)
        self.assertEqual(core.backups(), [])

    def test_symlink_override_refused(self):
        outside = self.root / 'outside'
        outside.write_text('unchanged')
        self.override.symlink_to(outside)
        with self.assertRaisesRegex(RuntimeError, 'symlink'):
            core.write_setting('sshd', 'maxretry', '2')
        self.assertEqual(outside.read_text(), 'unchanged')

    def test_lock_excludes_other_writer(self):
        with core.locked():
            with self.assertRaisesRegex(RuntimeError, 'Another'):
                with core.locked():
                    pass

    def test_backup_failure_blocks_edit(self):
        with patch.object(core, 'validate'), patch.object(core, 'backup', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                core.write_setting('sshd', 'bantime', '60')
        self.assertFalse(self.override.exists())

    def test_restore_and_safety_copy(self):
        with core.locked():
            ident = core.backup()
        (self.config / 'jail.local').write_text('new content')
        with patch.object(core, 'checked', return_value='OK'):
            safety = core.restore(ident)
        self.assertIn('# customer', (self.config / 'jail.local').read_text())
        self.assertEqual((self.state / 'backups' / safety / 'config/jail.local').read_text(), 'new content')

    def test_failed_restore_returns_to_previous(self):
        with core.locked():
            ident = core.backup()
        (self.config / 'jail.local').write_text('current content')
        with patch.object(core, 'checked', return_value='OK'), patch.object(core, 'reload_service', side_effect=[RuntimeError('failed'), 'OK']):
            with self.assertRaisesRegex(RuntimeError, 'Restore cancelled'):
                core.restore(ident)
        self.assertEqual((self.config / 'jail.local').read_text(), 'current content')

    def test_restore_rejects_path_traversal(self):
        with self.assertRaises(ValueError):
            core.restore('../../etc')

    def test_install_update_uninstall_preserve_configs_and_unknown_files(self):
        source = Path(__file__).resolve().parents[1]
        original = (self.config / 'jail.local').read_bytes()
        with patch.object(core, 'checked', return_value='OK'):
            core.install(source)
            (self.install / 'user-note').write_text('keep')
            core.install(source)
        self.assertTrue(self.launcher.is_symlink())
        self.assertEqual((self.install / 'user-note').read_text(), 'keep')
        core.uninstall()
        self.assertFalse(self.launcher.exists())
        self.assertFalse((self.install / 'f2b.py').exists())
        self.assertEqual((self.install / 'user-note').read_text(), 'keep')
        self.assertEqual((self.config / 'jail.local').read_bytes(), original)
        self.assertEqual(len(core.backups()), 3)

    def test_failed_install_restores_old_program(self):
        self.install.mkdir(parents=True)
        (self.install / 'f2b.py').write_text('old version')
        with patch.object(core, 'checked', side_effect=['OK', RuntimeError('smoke failed')]):
            with self.assertRaisesRegex(RuntimeError, 'smoke failed'):
                core.install(Path(__file__).resolve().parents[1])
        self.assertEqual((self.install / 'f2b.py').read_text(), 'old version')

    def test_unrelated_launcher_is_preserved(self):
        self.launcher.parent.mkdir()
        self.launcher.write_text('owned by user')
        with self.assertRaisesRegex(RuntimeError, 'unrelated launcher'):
            core.install(Path(__file__).resolve().parents[1])
        self.assertEqual(self.launcher.read_text(), 'owned by user')

    def test_failed_install_before_activation_restores_old_program(self):
        self.install.mkdir(parents=True)
        (self.install / 'f2b.py').write_text('old version')
        real_rename = core.os.rename
        def rename(src, dst):
            if Path(src).name == 'next':
                raise OSError('activation failed')
            return real_rename(src, dst)
        with patch.object(core, 'checked', return_value='OK'), patch.object(core.os, 'rename', side_effect=rename):
            with self.assertRaises(OSError):
                core.install(Path(__file__).resolve().parents[1])
        self.assertEqual((self.install / 'f2b.py').read_text(), 'old version')


if __name__ == '__main__':
    unittest.main()
