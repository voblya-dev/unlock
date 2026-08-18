from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from unlock.ai_hosts import (
    AI_PROTECTED_HOSTS,
    _bundle_looks_useful,
    _filter_hosts_bundle,
)
from unlock.ai_dns import _apply_resolvers, _load_state, _remove_state, _save_state
from unlock.host_overrides import (
    AI_BEGIN,
    AI_END,
    BEGIN,
    END,
    _read_hosts,
    _write_hosts,
    render_ai_hosts,
    render_hosts,
)
from unlock.site_lists import (
    HostMapping,
    SiteListManager,
    SiteRuleType,
    normalize_domain,
    parse_import_lines,
    parse_rule,
)
from unlock.strategies import expand_args, find_strategy, load_strategies
from unlock.constants import LISTS_DIR


class SiteRuleParsingTests(unittest.TestCase):
    def test_domains_are_lowercase_and_keep_wildcard(self) -> None:
        self.assertEqual(normalize_domain("  *.ExAmPle.COM. "), "*.example.com")
        self.assertEqual(normalize_domain("BÜCHER.example"), "xn--bcher-kva.example")
        self.assertEqual(normalize_domain("https://Example.com:443/path?q=1"), "example.com")
        self.assertEqual(normalize_domain("example.com/path"), "example.com")
        self.assertEqual(parse_rule("https://Example.com:443/path?q=1").value, "example.com")
        self.assertIsNone(normalize_domain("not a host"))
        self.assertIsNone(normalize_domain("example"))

    def test_ip_and_cidr_are_classified_and_normalised(self) -> None:
        ip = parse_rule("2001:0db8::1")
        subnet = parse_rule("1.2.3.44/24")
        self.assertEqual((ip.type, ip.value), (SiteRuleType.IP, "2001:db8::1"))
        self.assertEqual((subnet.type, subnet.value), (SiteRuleType.SUBNET, "1.2.3.0/24"))
        self.assertIsNone(parse_rule("300.1.1.1"))
        self.assertIsNone(parse_rule("1.2.3.4/99"))

    def test_import_accepts_inline_comments_and_hosts_rows(self) -> None:
        self.assertEqual(
            parse_import_lines(
                "\nexample.com\n# a comment\n1.2.3.4 # note\n"
                "0.0.0.0 blocked.example alias.blocked.example # hosts list\n  8.8.8.8  \n"
            ),
            ["example.com", "1.2.3.4", "blocked.example", "alias.blocked.example", "8.8.8.8"],
        )


class AiDnsStateTests(unittest.TestCase):
    def test_dns_snapshot_is_persisted_for_exact_restore(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            state = Path(root) / "ai-dns-state.json"
            snapshot = [{"index": 7, "ipv4": ["192.0.2.1"], "ipv6": ["2001:db8::1"]}]
            _save_state(snapshot, state)
            self.assertEqual(_load_state(state), snapshot)
            _remove_state(state)
            self.assertIsNone(_load_state(state))

    def test_dns_apply_uses_cross_version_powershell_syntax(self) -> None:
        snapshot = [{"index": 7, "ipv4": ["192.0.2.1"], "ipv6": ["2001:db8::1"]}]
        with patch("unlock.ai_dns._run_powershell") as run:
            _apply_resolvers(snapshot, restore=False)
        script = run.call_args.args[0]
        self.assertIn("Set-DnsClientServerAddress -InterfaceIndex", script)
        self.assertNotIn("-AddressFamily", script)


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
        self.assertEqual(
            (self.hostlist.parent / "list-exclude-user.txt").read_text(encoding="utf-8"),
            "",
        )
        self.assertEqual(
            (self.ipset.parent / "ipset-exclude-user.txt").read_text(encoding="utf-8"),
            "",
        )
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

    def test_wildcards_are_written_as_winws_domains_and_merged_with_base(self) -> None:
        base_hosts = Path(self.temp.name) / "base-hosts.txt"
        base_ips = Path(self.temp.name) / "base-ips.txt"
        base_hosts.write_text("bundled.example\n", encoding="utf-8")
        base_ips.write_text("10.0.0.0/8\n", encoding="utf-8")
        manager = SiteListManager(
            self.store,
            self.hostlist,
            self.ipset,
            base_hostlist_path=base_hosts,
            base_ipset_path=base_ips,
        )
        manager.add_text("instagram.com\n*.instagram.com\n203.0.113.0/24")
        self.assertEqual(self.hostlist.read_text(encoding="utf-8"), "instagram.com\n")
        self.assertEqual(
            (self.hostlist.parent / "list-general.txt").read_text(encoding="utf-8"),
            "bundled.example\ninstagram.com\n",
        )
        self.assertEqual(
            (self.ipset.parent / "ipset-all.txt").read_text(encoding="utf-8"),
            "10.0.0.0/8\n203.0.113.0/24\n",
        )

    def test_ai_mode_stays_out_of_zapret_lists(self) -> None:
        self.manager.add_text("chatgpt.com")
        before_hostlist = self.hostlist.read_text(encoding="utf-8")
        before_rules = self.manager.rules()
        enabled = self.manager.set_ai_sites_enabled(True)
        self.assertTrue(self.manager.ai_sites_enabled)
        self.assertTrue(enabled.touched)
        self.assertEqual(self.manager.rules(), before_rules)
        self.assertEqual(self.hostlist.read_text(encoding="utf-8"), before_hostlist)
        self.manager.set_ai_sites_enabled(False)
        self.assertFalse(self.manager.ai_sites_enabled)
        self.assertEqual(self.manager.rules(), before_rules)

    def test_legacy_generated_ai_rules_are_removed_but_user_rules_survive(self) -> None:
        self.store.write_text(json.dumps({
            "version": 1,
            "rules": [
                {"type": "domain", "value": "chatgpt.com", "source": "ai", "enabled": True},
                {"type": "domain", "value": "example.com", "source": "user", "enabled": True},
            ],
            "hosts": [],
            "hosts_enabled": False,
            "ai_sites_enabled": True,
        }), encoding="utf-8")
        migrated = SiteListManager(self.store, self.hostlist, self.ipset)
        self.assertEqual([rule.value for rule in migrated.rules()], ["example.com"])
        self.assertTrue(migrated.ai_sites_enabled)
        document = json.loads(self.store.read_text(encoding="utf-8"))
        self.assertEqual(document["rules"], [{
            "type": "domain", "value": "example.com", "enabled": True,
        }])

    def test_host_mapping_is_validated_and_serialised(self) -> None:
        self.assertTrue(self.manager.add_host_mapping("Example.COM", "2001:db8::7"))
        self.assertFalse(self.manager.add_host_mapping("*.example.com", "1.2.3.4"))
        self.assertFalse(self.manager.add_host_mapping("example.net", "not-ip"))
        self.assertEqual(self.manager.host_mappings(), (HostMapping("example.com", "2001:db8::7"),))


class ZapretArgumentTests(unittest.TestCase):
    def test_general_lists_are_replaced_by_merged_runtime_files(self) -> None:
        args = expand_args([
            "--hostlist=%LISTS%list-general.txt",
            "--hostlist=%LISTS%list-general-user.txt",
            "--new",
            "--hostlist=%LISTS%list-google.txt",
            "--ipset=%LISTS%ipset-all.txt",
            "--hostlist-exclude=%LISTS%list-exclude.txt",
            "--hostlist-exclude=%LISTS%list-exclude-user.txt",
            "--ipset-exclude=%LISTS%ipset-exclude.txt",
            "--ipset-exclude=%LISTS%ipset-exclude-user.txt",
        ])
        self.assertEqual(len(args), 9)
        self.assertTrue(args[0].endswith("zapret-lists\\list-general.txt"))
        self.assertTrue(args[1].endswith("zapret-lists\\list-general-user.txt"))
        self.assertIn(str(LISTS_DIR).lower(), args[3].lower())
        self.assertTrue(args[4].endswith("zapret-lists\\ipset-all.txt"))
        self.assertTrue(args[6].endswith("zapret-lists\\list-exclude-user.txt"))
        self.assertTrue(args[8].endswith("zapret-lists\\ipset-exclude-user.txt"))
        self.assertFalse(any("unlock-hostlist.txt" in arg for arg in args))

    def test_every_shipped_strategy_uses_runtime_user_lists(self) -> None:
        strategies = load_strategies()
        self.assertTrue(strategies)
        for strategy in strategies:
            args = [arg.lower() for arg in strategy.args]
            self.assertTrue(
                any("zapret-lists\\list-general.txt" in arg for arg in args),
                strategy.name,
            )
            self.assertTrue(
                any("zapret-lists\\ipset-all.txt" in arg for arg in args),
                strategy.name,
            )
            self.assertFalse(
                any("%lists%list-exclude-user.txt" in arg for arg in args),
                strategy.name,
            )
        self.assertIsNone(find_strategy("removed-local-profile"))

    def test_hosts_rendering_changes_only_unlock_markers(self) -> None:
        original = "127.0.0.1 localhost\n# user line\n"
        rendered = render_hosts(original, (HostMapping("example.com", "203.0.113.7"),))
        self.assertIn("127.0.0.1 localhost", rendered)
        self.assertIn("# user line", rendered)
        self.assertIn(BEGIN, rendered)
        self.assertIn(END, rendered)
        self.assertEqual(render_hosts(rendered, ()), "127.0.0.1 localhost\n# user line\n")

    def test_ai_hosts_rendering_keeps_user_and_manual_blocks(self) -> None:
        original = (
            "127.0.0.1 localhost\n"
            f"{BEGIN}\n203.0.113.7\texample.com\n{END}\n"
            "# user line\n"
        )
        rendered = render_ai_hosts(original, "45.155.204.190\tchatgpt.com\n0.0.0.0\tads.example\n")
        self.assertIn(BEGIN, rendered)
        self.assertIn("example.com", rendered)
        self.assertIn(AI_BEGIN, rendered)
        self.assertIn(AI_END, rendered)
        self.assertEqual(render_ai_hosts(rendered, ""), original)

    def test_hosts_io_preserves_utf16(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "hosts"
            path.write_text("# комментарий\r\n127.0.0.1 localhost\r\n", encoding="utf-16")
            text, encoding = _read_hosts(path)
            self.assertEqual(encoding, "utf-16")
            self.assertIn("комментарий", text)
            _write_hosts(path, text + "203.0.113.7 example.com\r\n", encoding)
            self.assertIn("example.com", path.read_text(encoding="utf-16"))


class AiHostsFeedTests(unittest.TestCase):
    def test_feed_keeps_full_bundle_but_protects_github_updates(self) -> None:
        source = (
            "45.155.204.190 chatgpt.com api.openai.com\n"
            "45.155.204.190 www.example.com\n"
            "0.0.0.0 claude.ai\n"
            "127.0.0.1 github.com\n"
            "62.133.62.97 gemini.google.com\n"
        )
        filtered = _filter_hosts_bundle(source)
        self.assertNotIn("github.com", filtered)
        self.assertIn("www.example.com", filtered)
        self.assertIn("0.0.0.0 claude.ai", filtered)
        self.assertTrue(_bundle_looks_useful(filtered))
        self.assertIn("raw.githubusercontent.com", AI_PROTECTED_HOSTS)


if __name__ == "__main__":
    unittest.main()
