"""IP geography and network names. Stdlib only.

Offline: country + ASN/network name from DB-IP Lite (CC BY 4.0, https://db-ip.com),
stored in one SQLite file. Online (explicit user action only): ipwho.is + RDAP.
"""
import csv
import datetime
import gzip
import ipaddress
import json
import os
import re
import sqlite3
import tempfile
import time
import urllib.error
import urllib.request

import f2b_core as core

DOWNLOAD = 'https://download.db-ip.com/free/dbip-{kind}-lite-{month}.csv.gz'
ONLINE = 'https://ipwho.is/{ip}'
RDAP = 'https://rdap.org/ip/{ip}'
KINDS = {'country': 3, 'asn': 4}  # CSV column count per layer
MAX_DOWNLOAD = 200 * 1024 * 1024
MAX_ROWS = 4_000_000
MIN_ROWS = 1000
CACHE_TTL = 30 * 86400
CACHE_MAX = 1000
USER_AGENT = 'f2b-tui/' + core.VERSION


def db_path():
    return core.STATE / 'geo.sqlite'


def cache_path():
    return core.STATE / 'geo-cache.json'


def flag(code):
    """Regional-indicator flag emoji; empty unless a plain two-letter code."""
    if code and re.fullmatch(r'[A-Z]{2}', code) and code != 'ZZ':
        return ''.join(chr(0x1F1E6 + ord(c) - 65) for c in code)
    return ''


def _clean(text, limit=120):
    return re.sub(r'[\x00-\x1f\x7f]', ' ', str(text or '')).strip()[:limit]


def _key(addr):
    """(table suffix, sortable key). IPv4-mapped IPv6 is looked up as IPv4."""
    if addr.version == 6 and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return ('4', int(addr)) if addr.version == 4 else ('6', addr.packed)


def _cidr(start, end, addr):
    if isinstance(start, bytes):
        first, last = ipaddress.IPv6Address(start), ipaddress.IPv6Address(end)
    else:
        first, last = ipaddress.IPv4Address(start), ipaddress.IPv4Address(end)
    for net in ipaddress.summarize_address_range(first, last):
        if addr in net:
            return str(net)
    return ''


class Geo:
    """Cheap repeated lookups: one read-only connection and a per-instance memo."""

    def __init__(self):
        self.con = None
        self.memo = {}
        self.cache = None

    def close(self):
        if self.con:
            self.con.close()
        self.con, self.memo, self.cache = None, {}, None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def available(self):
        return db_path().is_file()

    def _connect(self):
        if self.con is None and self.available():
            self.con = sqlite3.connect(db_path().as_uri() + '?mode=ro', uri=True, timeout=5)
        return self.con

    def _row(self, table, key):
        row = self.con.execute(f'SELECT s,e,a,b FROM {table} WHERE s<=? ORDER BY s DESC LIMIT 1', (key,)).fetchone()
        return row if row and key <= row[1] else None

    def offline(self, ip):
        result = {}
        try:
            addr = ipaddress.ip_address(ip)
            if not self._connect():
                return result
            suffix, key = _key(addr)
            if suffix == '4' and addr.version == 6:
                addr = addr.ipv4_mapped
            row = self._row('country' + suffix, key)
            if row and row[2] and row[2] != 'ZZ':
                result['cc'] = row[2]
            row = self._row('asn' + suffix, key)
            if row:
                result['cidr'] = _cidr(row[0], row[1], addr)
                if row[2]:
                    result['asn'] = int(row[2])
                    result['org'] = row[3] or ''
        except (sqlite3.Error, ValueError):
            pass
        return result

    def lookup(self, ip):
        """Offline data first; cached online answers only fill the gaps."""
        if ip in self.memo:
            return self.memo[ip]
        data = self.offline(ip)
        if data:
            data['offline'] = True
        cached = self.cached(ip)
        if cached:
            for field, value in cached.items():
                if field != 'ts':
                    data.setdefault(field, value)
            data['online'] = True
        self.memo[ip] = data
        return data

    def cached(self, ip):
        if self.cache is None:
            self.cache = load_cache()
        item = self.cache.get(ip)
        if item and time.time() - item.get('ts', 0) < CACHE_TTL:
            return item
        return None

    def remember(self, ip, data):
        if self.cache is None:
            self.cache = load_cache()
        self.cache[ip] = {**data, 'ts': int(time.time())}
        if len(self.cache) > CACHE_MAX:
            for stale in sorted(self.cache, key=lambda k: self.cache[k].get('ts', 0))[:len(self.cache) - CACHE_MAX]:
                del self.cache[stale]
        save_cache(self.cache)
        self.memo.pop(ip, None)

    def info(self):
        """Database facts for the status page; empty dict when no database."""
        if not self._connect():
            return {}
        try:
            meta = dict(self.con.execute('SELECT k, v FROM meta'))
        except sqlite3.Error:
            return {}
        meta['size'] = db_path().stat().st_size
        return meta


def load_cache():
    try:
        data = json.loads(cache_path().read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_cache(cache):
    core.private_dir(core.STATE)
    core.atomic_write(cache_path(), json.dumps(cache, ensure_ascii=False).encode())


def clear_cache():
    cache_path().unlink(missing_ok=True)


# ----------------------------------------------------------------- database update

class _Limited:
    """File-like wrapper that counts bytes, reports progress and caps download size."""

    def __init__(self, stream, label, total, progress):
        self.stream, self.label, self.total, self.progress, self.count = stream, label, total, progress, 0

    def read(self, size=-1):
        chunk = self.stream.read(size)
        self.count += len(chunk)
        if self.count > MAX_DOWNLOAD:
            raise RuntimeError('Download too large / Файл слишком большой')
        if self.progress:
            self.progress(self.label, self.count, self.total)
        return chunk


def _months():
    today = datetime.date.today()
    previous = (today.replace(day=1) - datetime.timedelta(days=1))
    return [today.strftime('%Y-%m'), previous.strftime('%Y-%m')]


def _open(kind):
    errors = []
    for month in _months():
        url = DOWNLOAD.format(kind=kind, month=month)
        try:
            request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
            return urllib.request.urlopen(request, timeout=30), month
        except urllib.error.HTTPError as exc:
            errors.append(f'{url}: HTTP {exc.code}')
        except (urllib.error.URLError, OSError) as exc:
            raise RuntimeError(f'Network error / Ошибка сети: {url}: {exc}') from exc
    raise RuntimeError('Database not found / База не найдена: ' + '; '.join(errors))


def _rows(kind, progress):
    """Yield (suffix, start, end, a, b) validated rows from one DB-IP CSV."""
    response, month = _open(kind)
    with response:
        total = int(response.headers.get('Content-Length') or 0) or None
        stream = _Limited(response, kind, total, progress)
        count = 0
        with gzip.open(stream, 'rt', encoding='utf-8', newline='') as text:
            for row in csv.reader(text):
                if len(row) != KINDS[kind]:
                    continue
                try:
                    start, end = ipaddress.ip_address(row[0]), ipaddress.ip_address(row[1])
                    if start.version != end.version or start > end:
                        continue
                    if kind == 'country':
                        if not re.fullmatch(r'[A-Z]{2}', row[2]):
                            continue
                        a, b = row[2], None
                    else:
                        a, b = int(row[2]), _clean(row[3])
                except ValueError:
                    continue
                count += 1
                if count > MAX_ROWS:
                    raise RuntimeError('Too many rows / Слишком много записей')
                suffix, low = _key(start)
                _, high = _key(end)
                yield suffix, low, high, a, b, month


def update(progress=None):
    """Download country + ASN layers and atomically replace the database.

    progress(label, bytes_done, bytes_total_or_None) may raise to cancel.
    """
    with core.locked():
        fd, name = tempfile.mkstemp(prefix='.geo-', suffix='.sqlite', dir=core.STATE)
        os.close(fd)
        try:
            con = sqlite3.connect(name)
            con.execute('PRAGMA journal_mode=OFF')
            con.execute('PRAGMA synchronous=OFF')
            con.execute('CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT)')
            counts, months = {}, set()
            for kind in KINDS:
                for suffix, kind_type in (('4', 'INTEGER'), ('6', 'BLOB')):
                    con.execute(f'CREATE TABLE {kind}{suffix} (s {kind_type} PRIMARY KEY, e {kind_type} NOT NULL, a, b) WITHOUT ROWID')
                batch, counts[kind] = {'4': [], '6': []}, 0
                for suffix, low, high, a, b, month in _rows(kind, progress):
                    months.add(month)
                    batch[suffix].append((low, high, a, b))
                    counts[kind] += 1
                    if len(batch[suffix]) >= 20000:
                        con.executemany(f'INSERT OR IGNORE INTO {kind}{suffix} VALUES (?,?,?,?)', batch[suffix])
                        batch[suffix] = []
                for suffix in batch:
                    con.executemany(f'INSERT OR IGNORE INTO {kind}{suffix} VALUES (?,?,?,?)', batch[suffix])
                if counts[kind] < MIN_ROWS:
                    raise RuntimeError(f'Suspiciously small {kind} database / Подозрительно маленькая база: {counts[kind]}')
            meta = {'updated': datetime.datetime.now().strftime('%Y-%m-%d %H:%M'), 'source': 'DB-IP Lite ' + ', '.join(sorted(months)),
                    'country_rows': str(counts['country']), 'asn_rows': str(counts['asn'])}
            con.executemany('INSERT INTO meta VALUES (?,?)', meta.items())
            con.commit()
            con.close()
            os.chmod(name, 0o644)
            os.replace(name, db_path())
        finally:
            if os.path.exists(name):
                os.unlink(name)
    return meta


# ----------------------------------------------------------------- online lookup

def _get_json(url, timeout):
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, 'Accept': 'application/json'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read(1_000_000).decode('utf-8', 'replace'))


def online(ip, timeout=10):
    """City/region/country name/network via public services. Raises RuntimeError if both fail."""
    addr = ipaddress.ip_address(ip)
    if not addr.is_global:
        raise ValueError('Not a public address / Не публичный адрес')
    data, errors = {}, []
    try:
        j = _get_json(ONLINE.format(ip=addr), timeout)
        if j.get('success') is False:
            raise ValueError(j.get('message') or 'lookup failed')
        conn = j.get('connection') or {}
        data.update(cc=_clean(j.get('country_code'), 2).upper(), country=_clean(j.get('country')), region=_clean(j.get('region')),
                    city=_clean(j.get('city')), isp=_clean(conn.get('isp')), domain=_clean(conn.get('domain')))
        if conn.get('asn'):
            data['asn'], data['org'] = int(conn['asn']), _clean(conn.get('org'))
        if isinstance(j.get('latitude'), (int, float)) and isinstance(j.get('longitude'), (int, float)):
            data['lat'], data['lon'] = round(j['latitude'], 4), round(j['longitude'], 4)
    except (OSError, ValueError, TypeError, urllib.error.URLError) as exc:
        errors.append('ipwho.is: ' + str(exc))
    try:
        j = _get_json(RDAP.format(ip=addr), timeout)
        data['netname'] = _clean(j.get('name'))
        for item in j.get('cidr0_cidrs') or []:
            prefix = item.get('v4prefix') or item.get('v6prefix')
            if prefix and ipaddress.ip_address(prefix) <= addr:
                net = ipaddress.ip_network(f'{prefix}/{int(item["length"])}', strict=False)
                if addr in net:
                    data['cidr'] = str(net)
                    break
        if j.get('country') and not data.get('cc'):
            data['cc'] = _clean(j['country'], 2).upper()
    except (OSError, ValueError, TypeError, KeyError, urllib.error.URLError) as exc:
        errors.append('RDAP: ' + str(exc))
    data = {k: v for k, v in data.items() if v not in ('', None)}
    if not data:
        raise RuntimeError('Online lookup failed / Онлайн-поиск не удался: ' + '; '.join(errors))
    return data
