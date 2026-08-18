"""Direct outbound socket factory for the Telegram bridge."""

from __future__ import annotations

import asyncio


async def open_connection(host, port, *, ssl=None, server_hostname=None):
    """Open a direct connection to Telegram infrastructure."""
    return await asyncio.open_connection(host, port, ssl=ssl, server_hostname=server_hostname)
