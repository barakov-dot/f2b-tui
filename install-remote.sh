#!/usr/bin/env bash
set -euo pipefail

REPO="https://github.com/barakov-dot/f2b-tui.git"
INSTALL_DIR=$(mktemp -d)

trap 'rm -rf "$INSTALL_DIR"' EXIT

if [[ $EUID -ne 0 ]]; then
    echo "Ошибка: запустите установщик через sudo"
    exit 1
fi

echo "=== Fail2ban TUI Installer ==="

echo "[1/3] Установка зависимостей..."
apt-get update
apt-get install -y git python3 fail2ban

echo "[2/3] Загрузка F2B TUI..."
git clone --depth 1 "$REPO" "$INSTALL_DIR"

echo "[3/3] Установка..."
bash "$INSTALL_DIR/install.sh"

echo ""
echo "Установка завершена!"
echo "Запуск: sudo f2b"