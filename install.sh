#!/usr/bin/env bash
set -euo pipefail
# Run this script from a reviewed, trusted repository clone or release archive.
if [[ $EUID -ne 0 ]]; then echo 'Run with sudo'; exit 1; fi
command -v python3 >/dev/null || { echo 'Python 3 is required'; exit 1; }
command -v fail2ban-client >/dev/null || { echo 'Install fail2ban first: sudo apt install fail2ban'; exit 1; }
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
install -d -m 755 /opt/fail2ban-tui
install -m 755 "$SCRIPT_DIR/f2b.py" /opt/fail2ban-tui/f2b.py
ln -sfn /opt/fail2ban-tui/f2b.py /usr/local/bin/f2b
echo 'Installed: sudo f2b'
