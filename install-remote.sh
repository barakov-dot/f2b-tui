#!/usr/bin/env bash
# Download and print the commit; inspect, then run install.sh.
# Usage: install-remote.sh [REF] [--install]   (--install: root only, installs right after download)
set -euo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
ref=main
install=0
for arg in "$@"; do
    case "$arg" in
        --install) install=1 ;;
        *) ref="$arg" ;;
    esac
done
if [[ $install -eq 1 && $EUID -ne 0 ]]; then
    echo '--install needs root: run via sudo bash -s -- --install / нужен root' >&2
    exit 1
fi
[[ "$ref" =~ ^[a-zA-Z0-9][a-zA-Z0-9._/-]*$ && "$ref" != *..* ]] || { echo 'Invalid ref' >&2; exit 1; }
command -v git >/dev/null || { echo 'sudo apt install git' >&2; exit 1; }
source_dir="$(mktemp -d "${TMPDIR:-/tmp}/f2b-tui.XXXXXXXX")"
trap 'echo "Source retained / Исходники сохранены: $source_dir"' EXIT
export GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null GIT_TERMINAL_PROMPT=0
git -c core.hooksPath=/dev/null init -q "$source_dir"
git -c core.hooksPath=/dev/null -C "$source_dir" fetch --depth=1 https://github.com/barakov-dot/f2b-tui.git "$ref"
git -c core.hooksPath=/dev/null -C "$source_dir" checkout --detach FETCH_HEAD
git -C "$source_dir" rev-parse HEAD
if [[ $install -eq 1 ]]; then
    echo "Installing from / Установка из: $source_dir (--install)"
    bash "$source_dir/install.sh"
else
    printf 'Review files, then / Проверьте файлы, затем:\nsudo bash %q/install.sh\n' "$source_dir"
fi
