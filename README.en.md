# Fail2ban TUI 0.3

English · [Русский](README.md)

A colorful, bilingual **RU/EN curses dashboard for Ubuntu 22.04 / 24.04**,
Python 3.10+, with no web server or third-party Python dependencies.

## Features

- Dashboard on the main screen: service state, bans per jail, latest Ban/Unban events.
- **Banned-IP list**: pick an IP with the arrow keys, press Enter to unban. Shows country, network/provider (AS), subnet and time left; refreshes itself.
- Multi-select (Space), search (`/`), sorting (`s`), networks with many IPs (`g`), IP details (`i`).
- Unban in one jail, in all jails, or unban **and whitelist** (`ignoreip`).
- Offline geography: country + AS/network name from DB-IP Lite, updated from the program. Optional online lookup of city/network for one IP.
- Live log (`tail -f` style) with Ban/Unban/Found highlighting.
- Single-address IPv4/IPv6 ban with explicit confirmation; loopback and **your own SSH address are refused**.
- Timing/retry changes, configuration validation, reload and restart.
- Full configuration backups, restoration and automatic rollback of failed edits.
- Icons: Unicode, **Nerd Font** or ASCII (`A` cycles), flags on/off (`F`), colorless terminals, RU/EN switch (`L`).
- Scrolling menus, resize handling and **ESC cancellation in every input**, including partial IPs.

Minimum terminal: 48×12; recommended: 100×26. Unicode mode needs no Nerd Font; use `sudo f2b --nerd` or `A` for Nerd Font glyphs.
Preferences are saved per server in `/var/lib/f2b-tui/preferences.json`.
ASCII changes decorations; Russian text still requires UTF-8.
Use `sudo f2b --lang en --ascii` for limited terminal fonts.
Fail2ban/systemd diagnostics retain their original language.

## Banned IPs, geography and networks

Menu → **Banned IPs · unban**:

```text
  Banned IPs · unban
      CC IP address        Jail            Left     Network / provider
    ○ RU 77.88.8.8         nginx-http-auth  1m 24s  AS13238 YANDEX LLC · 77.88.8.0/22  🇷🇺
  > ○ FI 95.216.1.9        sshd             4m 54s  AS24940 Hetzner Online GmbH · 95.216.0.0/15  🇫🇮
    ○ DE 2a00:1450:4001::1 sshd             1d 23h  AS15169 Google LLC · 2a00:1450::/32  🇩🇪
```

| Key | Action |
|---|---|
| ↑↓ / j k / PgUp PgDn / Home End | move |
| **Enter** | unban the marked (or selected) IPs → choose `y` this jail, `a` all jails, `w` unban + whitelist |
| Space / `*` | mark / mark all visible |
| `/` | search by IP, jail, country, network |
| `s` | sort: time, country, network, jail, IP |
| `i` / `o` | details (offline) / refine city and network online |
| `g` | networks with several banned IPs (spot targeted attacks) |
| `b` | ban an IP manually (refuses loopback and your SSH address) |
| `r`, `?` | refresh now (auto every 5 s), help |

`w` writes `ignoreip` for that jail to `99-f2b-tui.local` using the same transactional
path as other edits (backup → write → validate → reload → verify → rollback). It freezes
that jail's ignore list at its current effective value plus the new IP.

**Geography.** Menu → *Geo database* → *Update database* downloads
[DB-IP Lite](https://db-ip.com/db/lite.php) country and ASN CSVs (≈12 MB, HTTPS) and builds
`/var/lib/f2b-tui/geo.sqlite` (≈50 MB) atomically; a failed or cancelled (ESC) download keeps
the previous database. Also: `sudo f2b geo-update`, `sudo f2b geo-lookup 8.8.8.8 [--online]`.
Lookups are local; no address leaves the server. Cities are not in the offline base (the
DB-IP city file is ~90 MB compressed). Pressing `o` or looking up an IP in the Geo menu can
ask **ipwho.is** and **rdap.org** for city and network name, but only after your explicit
confirmation; results are cached for 30 days (`geo-cache.json`, clearable from the menu).
Flag emoji are shown at the end of each row because terminals disagree about their width;
`F` hides them. Data: © DB-IP.com, CC BY 4.0.

## Install / upgrade from 0.1

The old version does not support `f2b update`. Run this installation once to
upgrade it; existing jail configuration is preserved.

```bash
sudo apt-get update
sudo apt-get install -y python3 fail2ban git
src=$(mktemp -d)
git clone --depth 1 https://github.com/barakov-dot/f2b-tui.git "$src"
git -C "$src" rev-parse HEAD
# Review install.sh, f2b.py, f2b_core.py, f2b_geo.py, f2b_bans.py and f2b_ui.py in "$src".
sudo bash "$src/install.sh"
sudo f2b --lang en
```

Use a reviewed full commit SHA or tag for reproducible installation.
`install-remote.sh [REF]` downloads source **without root**, prints its SHA and
an installation command, and retains the directory for review. It deliberately
rejects `curl … | sudo bash`. The installer does not install system packages,
change the service or overwrite `/etc/fail2ban`. It refuses to replace an unrelated
`/usr/local/bin/f2b`. Application files live in `/opt/fail2ban-tui`.

## Controls and commands

Arrows / `j` / `k`, Home/End and PgUp/PgDn navigate; Enter opens an item.
ESC cancels any input or confirmation. `q` leaves menus/viewers but is ordinary
text in an input. Destructive actions require typing `YES`. Left/right arrows
scroll long lines in the output viewer.

```bash
sudo f2b update                         # main, displays SHA and asks for YES
sudo f2b update --ref FULL_COMMIT_SHA   # pinned code
sudo f2b uninstall                      # asks for YES
sudo f2b backup                         # prints snapshot ID
sudo f2b backups                        # newest first
sudo f2b restore BACKUP_ID              # confirms full configuration replacement
```

`update`, `uninstall`, and `restore` accept `--yes` for intentional automation.
Update requires Git and HTTPS access to GitHub. Download and launch failures
are checked; the old program is retained until the new installation passes its
startup check, and restored on installation failure. Downloaded code executes
as root after confirmation. A displayed SHA identifies code but is not an
independent signature. Downloads use a private temporary directory.

## Configuration safety

Before settings changes, install/update/uninstall, reload/restart, and restore,
the entire `/etc/fail2ban` directory is copied into
`/var/lib/f2b-tui/backups/ID/config`. Snapshots are root-only, may contain secrets,
and are never automatically pruned. Monitor disk space. A failed backup prevents
the operation. Ban/unban changes runtime state only and does not create a snapshot.
Backups exclude the active bans database, firewall state, logs and external
symlink targets; symbolic links themselves are retained.

Only `/etc/fail2ban/jail.d/99-f2b-tui.local` is written by the settings editor.
Other jail files are untouched. Other sections/values in the managed override
are retained, although its formatting/comments can be normalized.
The editor accepts integers 1…31536000 for `bantime`/`findtime` (seconds) and
`maxretry` (count); it does not change existing values until explicitly edited.

Each edit validates the baseline, creates a snapshot, atomically writes the
override, runs `fail2ban-client -t`, reloads, and checks the effective value.
A masked setting or failed validation/reload restores the previous override
byte-for-byte and reloads again. If rollback reload also fails, the error and
backup ID are reported; check the running service manually. A shared lock prevents
concurrent mutations by this application. Avoid editing configs externally during
an operation.

Restore **replaces all of `/etc/fail2ban`**, first backs up the current tree,
validates the selected snapshot, and rolls back on failure. It restores configuration,
not bans. Arbitrary archive imports are unsupported. Restoration expects a real
directory, not a symlink or a separate mount point. Power loss / SIGKILL between
directory renames cannot guarantee automatic rollback; backups remain available
for manual recovery. Consider which jails the selected snapshot enables.

Uninstall removes only the application and its owned launcher. Fail2ban, the managed
override, customer configs, preferences, backups and unknown application-directory
files remain. Reinstall the panel to use its restore command after removal.

## Tests

```bash
python3 -m unittest discover -s tests -v
bash -n install.sh install-remote.sh uninstall.sh
# Linux/root only, Fail2ban installed; private daemon with no firewall actions:
sudo python3 tests/integration_linux.py
```

CI covers Ubuntu 22.04 / 24.04: cancellation, both languages, small terminals,
customer configuration preservation, validation/reload/installation failure paths,
real IPv4/IPv6 ban/unban, settings changes and configuration restoration.
