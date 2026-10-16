"""Exercise actual curses through a pseudo-terminal, not only a mocked screen."""
import fcntl
import os
from pathlib import Path
import pty
import select
import struct
import subprocess
import sys
import tempfile
import termios
import time
import unittest


class TerminalTests(unittest.TestCase):
    def run_terminal(self, body, keys, expected, lang='en', ascii_mode=False):
        with tempfile.TemporaryDirectory() as state:
            master, slave = pty.openpty()
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 24, 90, 0, 0))
            script = f'''
import curses, locale
from pathlib import Path
import f2b_core, f2b_ui
locale.setlocale(locale.LC_ALL, '')
f2b_core.STATE = Path({state!r})
def app(screen):
    ui = f2b_ui.UI(screen, {lang!r}, {ascii_mode!r})
    {body}
curses.wrapper(app)
print('TERMINAL_OK', flush=True)
'''
            process = subprocess.Popen([sys.executable, '-c', script], cwd=Path(__file__).resolve().parents[1],
                                       stdin=slave, stdout=slave, stderr=slave,
                                       env={**os.environ, 'TERM': 'xterm-256color', 'LC_ALL': 'C.UTF-8'})
            os.close(slave)
            output = bytearray()
            def read_until(marker, timeout=8):
                deadline = time.monotonic() + timeout
                while marker not in output and time.monotonic() < deadline:
                    if select.select([master], [], [], 0.1)[0]:
                        try:
                            chunk = os.read(master, 65536)
                        except OSError:
                            break
                        if not chunk:
                            break
                        output.extend(chunk)
                self.assertIn(marker, output, output.decode(errors='replace'))
            try:
                read_until(expected.encode())
                os.write(master, keys)
                read_until(b'TERMINAL_OK')
                self.assertEqual(process.wait(timeout=5), 0)
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait()
                os.close(master)

    def test_real_ru_unicode_menu(self):
        self.run_terminal("assert ui.menu('menu', f2b_ui.ACTIONS, True, True) is None", b'\x1b', 'Панель', 'ru')

    def test_real_en_ascii_menu(self):
        self.run_terminal("assert ui.menu('menu', f2b_ui.ACTIONS, True, True) is None", b'q', 'Control panel', ascii_mode=True)

    def test_real_partial_input_escape(self):
        self.run_terminal("assert ui.prompt('IPv4 / IPv6') is None", b'192.0.2.1\x1b', 'IPv4 / IPv6')

    def test_real_text_submit(self):
        self.run_terminal("assert ui.prompt('Address') == '2001:db8::1'", b'2001:db8::1\n', 'Address')


if __name__ == '__main__':
    unittest.main()
