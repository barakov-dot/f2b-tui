#!/usr/bin/env bash
set -euo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
umask 077
[[ $EUID -eq 0 ]] || { echo 'Run with sudo / Запустите через sudo' >&2; exit 1; }
command -v python3 >/dev/null
command -v fail2ban-client >/dev/null || { echo 'Install dependencies / Установите зависимости: sudo apt install python3 fail2ban git' >&2; exit 1; }
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
/usr/bin/python3 -I "$SCRIPT_DIR/f2b.py" install "$SCRIPT_DIR"
echo 'Installed / Установлено: sudo f2b'
