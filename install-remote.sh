#!/usr/bin/env bash
# Download as a regular user, inspect, then sudo bash install.sh.
set -euo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
if [[ $EUID -eq 0 ]]; then
    echo 'Run as a regular user. Review downloaded files before sudo / Запустите без sudo и проверьте файлы.' >&2
    exit 1
fi
ref="${1:-main}"
[[ "$ref" =~ ^[a-zA-Z0-9][a-zA-Z0-9._/-]*$ && "$ref" != *..* ]] || { echo 'Invalid ref' >&2; exit 1; }
command -v git >/dev/null || { echo 'sudo apt install git' >&2; exit 1; }
source_dir="$(mktemp -d "${TMPDIR:-/tmp}/f2b-tui.XXXXXXXX")"
trap 'echo "Source retained / Исходники сохранены: $source_dir"' EXIT
export GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null GIT_TERMINAL_PROMPT=0
git -c core.hooksPath=/dev/null init -q "$source_dir"
git -c core.hooksPath=/dev/null -C "$source_dir" fetch --depth=1 https://github.com/barakov-dot/f2b-tui.git "$ref"
git -c core.hooksPath=/dev/null -C "$source_dir" checkout --detach FETCH_HEAD
git -C "$source_dir" rev-parse HEAD
printf 'Review files, then / Проверьте файлы, затем:\nsudo bash %q/install.sh\n' "$source_dir"
