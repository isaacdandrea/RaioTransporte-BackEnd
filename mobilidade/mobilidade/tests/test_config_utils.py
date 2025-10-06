from django.test import SimpleTestCase

from mobilidade.mobilidade.config_utils import extend_allowed_hosts, hosts_from_origins


class HostsFromOriginsTests(SimpleTestCase):
    def test_extracts_hosts_from_http_urls(self):
        origins = ["https://example.com", "http://191.9.114.117:18001"]

        self.assertEqual(
            hosts_from_origins(origins),
            ["example.com", "191.9.114.117"],
        )

    def test_ignores_empty_entries(self):
        origins = ["", "   "]

        self.assertEqual(hosts_from_origins(origins), [])

    def test_accepts_scheme_less_hosts(self):
        origins = ["api.example.com", "api.example.com:8443", "https://valid.example"]

        self.assertEqual(
            hosts_from_origins(origins),
            ["api.example.com", "api.example.com", "valid.example"],
        )


class ExtendAllowedHostsTests(SimpleTestCase):
    def test_extends_hosts_when_wildcard_missing(self):
        base = ["localhost"]
        cors = ["https://191.9.114.117"]
        csrf = ["https://secure.example"]

        self.assertEqual(
            extend_allowed_hosts(base, cors, csrf),
            ["localhost", "191.9.114.117", "secure.example"],
        )

    def test_preserves_order_and_deduplicates(self):
        base = ["localhost"]
        cors = ["https://example.com", "https://example.com"]
        csrf = ["https://example.com", "https://api.example.com"]

        self.assertEqual(
            extend_allowed_hosts(base, cors, csrf),
            ["localhost", "example.com", "api.example.com"],
        )

    def test_returns_base_when_wildcard_present(self):
        base = ["*"]

        self.assertEqual(extend_allowed_hosts(base, ["https://x"]), ["*"])

    def test_returns_base_when_no_additions(self):
        base = ["localhost"]

        self.assertEqual(extend_allowed_hosts(base, []), ["localhost"])
