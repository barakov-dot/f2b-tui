import contextlib
import gzip
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import f2b_core as core
import f2b_geo as geo

COUNTRY = '0.0.0.0,0.255.255.255,ZZ\n1.0.0.0,1.0.0.255,AU\n203.0.113.0,203.0.113.255,DE\n::,1fff:ffff:ffff:ffff:ffff:ffff:ffff:ffff,ZZ\n2001:db8::,2001:db8:ffff:ffff:ffff:ffff:ffff:ffff,CH\nbad,row,XX\n'
ASN = '1.0.0.0,1.0.0.255,13335,"Cloudflare, Inc."\n203.0.113.0,203.0.113.127,64500,"Example\tHosting\x1b[31m"\n2001:db8::,2001:db8::ffff,64501,"Example v6"\n'


class FakeResponse(io.BytesIO):
    def __init__(self, text):
        data = gzip.compress(text.encode())
        super().__init__(data)
        self.headers = {'Content-Length': str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class GeoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.stack = contextlib.ExitStack()
        self.stack.enter_context(patch.object(core, 'STATE', Path(self.temp.name)))
        self.stack.enter_context(patch.object(geo, 'MIN_ROWS', 1))
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.stack.close)

    def build(self):
        def opener(kind):
            return FakeResponse(COUNTRY if kind == 'country' else ASN), '2026-10'
        with patch.object(geo, '_open', side_effect=opener):
            return geo.update()

    def test_no_database_gives_empty_result(self):
        finder = geo.Geo()
        self.assertFalse(finder.available())
        self.assertEqual(finder.lookup('203.0.113.5'), {})
        self.assertEqual(finder.info(), {})

    def test_update_and_lookup_ipv4_ipv6_mapped_and_cidr(self):
        meta = self.build()
        self.assertEqual(meta['country_rows'], '5')
        finder = geo.Geo()
        info = finder.lookup('203.0.113.5')
        self.assertEqual((info['cc'], info['asn'], info['cidr']), ('DE', 64500, '203.0.113.0/25'))
        self.assertNotIn('\x1b', info['org'])
        self.assertEqual(finder.lookup('203.0.113.200')['cc'], 'DE')
        self.assertNotIn('asn', finder.lookup('203.0.113.200'))  # outside the ASN range
        self.assertEqual(finder.lookup('::ffff:1.0.0.7')['org'], 'Cloudflare, Inc.')
        v6 = finder.lookup('2001:db8::42')
        self.assertEqual((v6['cc'], v6['asn']), ('CH', 64501))
        self.assertEqual(finder.lookup('0.1.2.3'), {})  # ZZ means unknown
        self.assertEqual(finder.lookup('not an ip'), {})
        self.assertEqual(finder.info()['source'], 'DB-IP Lite 2026-10')
        self.assertEqual((core.STATE / 'geo.sqlite').stat().st_mode & 0o777, 0o644)

    def test_failed_update_keeps_previous_database(self):
        self.build()
        def broken(kind):
            raise RuntimeError('network down')
        with patch.object(geo, '_open', side_effect=broken), self.assertRaises(RuntimeError):
            geo.update()
        self.assertEqual(geo.Geo().lookup('203.0.113.5')['cc'], 'DE')
        self.assertEqual([p.name for p in core.STATE.iterdir() if p.name.startswith('.geo-')], [])

    def test_tiny_database_is_rejected(self):
        with patch.object(geo, 'MIN_ROWS', 100), patch.object(geo, '_open', side_effect=lambda kind: (FakeResponse(COUNTRY), '2026-10')):
            with self.assertRaises(RuntimeError):
                geo.update()
        self.assertFalse((core.STATE / 'geo.sqlite').exists())

    def test_cancel_from_progress_cleans_up(self):
        def progress(*args):
            raise KeyboardInterrupt
        with patch.object(geo, '_open', side_effect=lambda kind: (FakeResponse(COUNTRY), '2026-10')), self.assertRaises(KeyboardInterrupt):
            geo.update(progress)
        self.assertEqual(list(core.STATE.glob('.geo-*')), [])

    def test_online_result_is_cached_and_fills_gaps_only(self):
        self.build()
        finder = geo.Geo()
        finder.remember('203.0.113.5', {'cc': 'XX', 'city': 'Berlin', 'country': 'Germany'})
        info = finder.lookup('203.0.113.5')
        self.assertEqual((info['cc'], info['city'], info['country']), ('DE', 'Berlin', 'Germany'))  # offline wins
        self.assertTrue(info['online'] and info['offline'])
        self.assertEqual(geo.Geo().lookup('203.0.113.5')['city'], 'Berlin')  # persisted
        geo.clear_cache()
        self.assertNotIn('city', geo.Geo().lookup('203.0.113.5'))

    def test_online_lookup_merges_sources_and_survives_one_failure(self):
        ipwho = {'success': True, 'country_code': 'US', 'country': 'United States', 'region': 'California', 'city': 'San Jose',
                 'latitude': 37.33939, 'longitude': -121.89496, 'connection': {'asn': 15169, 'org': 'Google LLC', 'isp': 'Google LLC', 'domain': 'google.com'}}
        rdap = {'name': 'GOGL', 'country': 'US', 'cidr0_cidrs': [{'v4prefix': '9.9.9.0', 'length': 24}, {'v4prefix': '8.8.8.0', 'length': 24}]}
        responses = {'ipwho.is': ipwho, 'rdap.org': rdap}
        with patch.object(geo, '_get_json', side_effect=lambda url, timeout: responses[url.split('/')[2]]):
            data = geo.online('8.8.8.8')
        self.assertEqual((data['city'], data['asn'], data['netname'], data['cidr']), ('San Jose', 15169, 'GOGL', '8.8.8.0/24'))
        def only_rdap(url, timeout):
            if 'ipwho' in url:
                raise OSError('down')
            return rdap
        with patch.object(geo, '_get_json', side_effect=only_rdap):
            self.assertEqual(geo.online('8.8.8.8')['netname'], 'GOGL')
        with patch.object(geo, '_get_json', side_effect=OSError('down')), self.assertRaises(RuntimeError):
            geo.online('8.8.8.8')

    def test_online_refuses_private_addresses(self):
        with patch.object(geo, '_get_json') as fetch:
            for ip in ('192.168.1.1', '10.0.0.1', '127.0.0.1', 'fe80::1'):
                with self.assertRaises(ValueError):
                    geo.online(ip)
            fetch.assert_not_called()

    def test_flags(self):
        self.assertEqual(geo.flag('DE'), '\U0001F1E9\U0001F1EA')
        for bad in ('', None, 'ZZ', 'de', 'DEU', '1A'):
            self.assertEqual(geo.flag(bad), '')


if __name__ == '__main__':
    unittest.main()
