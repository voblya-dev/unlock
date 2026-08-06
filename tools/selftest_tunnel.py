"""Smoke check: bring the Telegram MTProto bridge up and connect to it.

Runs on localhost. Verifies the vendored tg-ws-proxy engine binds, hands out a
usable tg:// link and accepts a TCP session, then shuts down cleanly.

    python tools/selftest_tunnel.py
"""

from __future__ import annotations

import logging
import socket
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from unlock import logger  # noqa: E402
from unlock.telegram_proxy import TelegramProxy, TelegramProxyError  # noqa: E402

PROXY_PORT = 11443


def main() -> int:
    logger.setup_logging(logging.INFO)
    proxy = TelegramProxy(PROXY_PORT)

    try:
        proxy.start()
    except TelegramProxyError as exc:
        print(f"bridge start: FAIL ({exc})")
        return 1

    try:
        link = proxy.proxy_link or ""
        if f"port={PROXY_PORT}" not in link or "secret=dd" not in link:
            print(f"proxy link: FAIL ({link!r})")
            return 1

        with socket.create_connection(("127.0.0.1", PROXY_PORT), timeout=5):
            pass
    except OSError as exc:
        print(f"listener connect: FAIL ({exc})")
        return 1
    finally:
        proxy.stop()

    if proxy.running:
        print("shutdown: FAIL (thread still alive)")
        return 1

    print("telegram bridge: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
