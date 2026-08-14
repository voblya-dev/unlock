from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from unlock.host_overrides import BEGIN, END, render_hosts
from unlock.site_lists import (
    AI_SITES,
    HostMapping,
    SiteListManager,
    SiteRuleSource,
    SiteRuleType,
    normalize_domain,
    parse_import_lines,
    parse_rule,
)
from unlock.strategies import expand_args


class SiteRuleParsingTests(unittest.TestCase):
    def test_domains_are_lowercase_and_keep_wildcard(self) -> None:
        self.assertEqual(normalize_domain("  *.ExAmPle.COM. "), "*.example.com")
        self.assertEqual(normalize_domain("BÜCHER.example"), "xn--bcher-kva.example")
        self.assertIsNone(normalize_domain("not a host"))
        self.assertIsNone(normalize_domain("example"))

    def test_ip_and_cidr_are_classified_and_normalised(self) -> None:
        ip = parse_rule("2001:0db8::1")
        subnet = parse_rule("1.2.3.44/24")
        self.assertEqual((ip.type, ip.value), (SiteRuleType.IP, "2001:db8::1"))
        self.assertEqual((subnet.type, subnet.value), (SiteRuleType.SUBNET, "1.2.3.0/24"))
        self.assertIsNone(parse_rule("300.1.1.1"))
        self.assertIsNone(parse_rule("1.2.3.4/99"))

    def test_import_drops_comments_and_blank_rows(self) -> None:
        self.assertEqual(
            parse_import_lines("\nexample.com\n# a comment\n1.2.3.4 # note\n  8.8.8.8  \n"),
            ["example.com", "8.8.8.8"],
        )


class SiteListStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.store = root / "sites.json"
        self.hostlist = root / "zapret-lists" / "hostlist.txt"
        self.ipset = root / "zapret-lists" / "ipset.txt"
        self.manager = SiteListManager(self.store, self.hostlist, self.ipset)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_deduplication_serialisation_and_generated_files(self) -> None:
        result = self.manager.add_text("Example.COM\n1.2.3.4\n1.2.3.44/24\nexample.com\ninvalid host")
        self.assertEqual(result.added, 3)
        self.assertEqual(result.duplicates, 1)
        self.assertEqual(result.invalid, ("invalid host",))
        self.assertEqual(self.hostlist.read_text(encoding="utf-8"), "example.com\n")
        self.assertEqual(self.ipset.read_text(encoding="utf-8"), "1.2.3.0/24\n1.2.3.4\n")
        document = json.loads(self.store.read_text(encoding="utf-8"))
        self.assertEqual(document["version"], 1)
        self.assertEqual(len(document["rules"]), 3)
        reloaded = SiteListManager(self.store, self.hostlist, self.ipset)
        self.assertEqual([rule.value for rule in reloaded.rules()], ["example.com", "1.2.3.4", "1.2.3.0/24"])

    def test_disabled_entries_do_not_reach_zapret_files(self) -> None:
        self.manager.add_text("example.com\n1.2.3.4")
        self.manager.set_enabled(["example.com"], False)
        self.assertEqual(self.hostlist.read_text(encoding="utf-8"), "")
        self.assertEqual(self.ipset.read_text(encoding="utf-8"), "1.2.3.4\n")

    def test_ai_collection_only_removes_its_own_source(self) -> None:
        self.manager.add_text("chatgpt.com")
        enabled = self.manager.set_ai_sites_enabled(True)
        self.assertTrue(self.manager.ai_sites_enabled)
        self.assertGreater(enabled.added, 0)
        self.assertIn("chatgpt.com", [rule.value for rule in self.manager.rules()])
        self.manager.set_ai_sites_enabled(False)
        remaining = self.manager.rules()
        self.assertFalse(self.manager.ai_sites_enabled)
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0].source, SiteRuleSource.USER)
        self.assertEqual(remaining[0].value, "chatgpt.com")

    def test_host_mapping_is_validated_and_serialised(self) -> None:
        self.assertTrue(self.manager.add_host_mapping("Example.COM", "2001:db8::7"))
        self.assertFalse(self.manager.add_host_mapping("*.example.com", "1.2.3.4"))
        self.assertFalse(self.manager.add_host_mapping("example.net", "not-ip"))
        self.assertEqual(self.manager.host_mappings(), (HostMapping("example.com", "2001:db8::7"),))


class ZapretArgumentTests(unittest.TestCase):
    def test_user_lists_are_added_next_to_preset_lists(self) -> None:
        args = expand_args([
            "--hostlist=%LISTS%list-general.txt",
            "--ipset=%LISTS%ipset-all.txt",
            "--hostlist-exclude=%LISTS%list-exclude.txt",
            "--ipset-exclude=%LISTS%ipset-exclude.txt",
        ])
        user_hosts = [arg for arg in args if "unlock-hostlist.txt" in arg]
        user_ips = [arg for arg in args if "unlock-ipset.txt" in arg]
        self.assertEqual(len(user_hosts), 1)
        self.assertEqual(len(user_ips), 1)
        self.assertEqual(len(args), 6)

    def test_hosts_rendering_changes_only_unlock_markers(self) -> None:
        original = "127.0.0.1 localhost\n# user line\n"
        rendered = render_hosts(original, (HostMapping("example.com", "203.0.113.7"),))
        self.assertIn("127.0.0.1 localhost", rendered)
        self.assertIn("# user line", rendered)
        self.assertIn(BEGIN, rendered)
        self.assertIn(END, rendered)
        self.assertEqual(render_hosts(rendered, ()), "127.0.0.1 localhost\n# user line\n")


if __name__ == "__main__":
    unittest.main()
