"""Regression checks for the Telegram bridge startup behaviour.

Telegram Desktop shows multi-second ping when every new client connection
burns through sequential 5-10s upstream timeouts. The wrapper must therefore
race the upstreams once at startup, pin the winners, and warm the pools.
"""

from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent.parent


class TelegramBridgeTests(unittest.TestCase):
    def test_start_races_upstreams_in_background(self) -> None:
        source = (ROOT / "unlock" / "telegram_proxy.py").read_text(encoding="utf-8")
        self.assertIn("_race_upstreams", source)
        self.assertIn("threading.Thread(target=self._race_upstreams", source)

    def test_race_pins_winners_and_warms_pools(self) -> None:
        source = (ROOT / "unlock" / "telegram_proxy.py").read_text(encoding="utf-8")
        self.assertIn("ip_fail_until", source)
        self.assertIn("update_domain_for_dc", source)
        self.assertIn("ws_pool.warmup()", source)

    def test_upstream_check_falls_back_to_cf_front(self) -> None:
        source = (ROOT / "unlock" / "telegram_proxy.py").read_text(encoding="utf-8")
        self.assertIn("get_domains_for_dc", source)


if __name__ == "__main__":
    unittest.main()
