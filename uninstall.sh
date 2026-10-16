#!/usr/bin/env bash
set -euo pipefail
if [[ $EUID -ne 0 ]]; then echo 'Run with sudo'; exit 1; fi
rm -f /usr/local/bin/f2b
rm -f /opt/fail2ban-tui/f2b.py
rmdir /opt/fail2ban-tui 2>/dev/null || true
echo 'Removed program; managed Fail2ban overrides preserved.'
