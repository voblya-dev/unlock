"""Outbound socket factory for the bridge.

Every upstream connection the bridge makes — WebSocket to a Telegram DC, the
plain-TCP fallback, the masking domain — goes through here, so pointing it at
the VPN's SOCKS listener is one assignment instead of a patch per call site.

Without this the bridge dials Telegram from the machine's default route while
the VPN is up: Telegram Desktop talks to our local MTProto listener, which is
not something the Windows proxy setting can redirect, so the tunnel never sees
the traffic. Other VPN clients avoid the problem by capturing at the adapter
level (TUN); we have no adapter, so the socket has to be steered by hand.
"""

from __future__ import annotations

import asyncio
import socket

from .config import proxy_config


class SocksError(OSError):
    pass


_SOCKS5_ERRORS = {
    1: "general failure",
    2: "connection not allowed",
    3: "network unreachable",
    4: "host unreachable",
    5: "connection refused",
    6: "TTL expired",
    7: "command not supported",
    8: "address type not supported",
}


async def open_connection(host, port, *, ssl=None, server_hostname=None):
    """asyncio.open_connection, routed through the upstream SOCKS proxy if set."""
    upstream = proxy_config.upstream_socks
    if not upstream:
        return await asyncio.open_connection(
            host, port, ssl=ssl, server_hostname=server_hostname
        )

    sock = await _socks5_connect(upstream, host, port)
    return await asyncio.open_connection(
        sock=sock, ssl=ssl, server_hostname=server_hostname
    )


async def _recv_exactly(loop, sock, count: int) -> bytes:
    buffer = b""
    while len(buffer) < count:
        chunk = await loop.sock_recv(sock, count - len(buffer))
        if not chunk:
            raise SocksError("SOCKS proxy closed the connection")
        buffer += chunk
    return buffer


async def _socks5_connect(upstream, host, port: int) -> socket.socket:
    loop = asyncio.get_running_loop()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setblocking(False)
    try:
        await loop.sock_connect(sock, upstream)

        # Greeting: SOCKS5, one method, "no authentication".
        await loop.sock_sendall(sock, b"\x05\x01\x00")
        version, method = await _recv_exactly(loop, sock, 2)
        if version != 0x05 or method != 0x00:
            raise SocksError(f"SOCKS5 handshake refused (method {method:#x})")

        try:
            request = b"\x05\x01\x00\x01" + socket.inet_aton(host)
        except OSError:
            # Not a literal IPv4 address: let the proxy resolve the name, which
            # also keeps the lookup inside the tunnel.
            name = host.encode("idna")
            request = b"\x05\x01\x00\x03" + bytes([len(name)]) + name
        await loop.sock_sendall(sock, request + port.to_bytes(2, "big"))

        reply = await _recv_exactly(loop, sock, 4)
        if reply[1] != 0x00:
            reason = _SOCKS5_ERRORS.get(reply[1], f"code {reply[1]}")
            raise SocksError(f"SOCKS5 CONNECT to {host}:{port} failed: {reason}")

        # The bound address is unused, but it has to be drained off the socket
        # before the tunnelled stream starts.
        kind = reply[3]
        if kind == 0x01:
            await _recv_exactly(loop, sock, 4 + 2)
        elif kind == 0x03:
            length = (await _recv_exactly(loop, sock, 1))[0]
            await _recv_exactly(loop, sock, length + 2)
        elif kind == 0x04:
            await _recv_exactly(loop, sock, 16 + 2)
        else:
            raise SocksError(f"SOCKS5 replied with address type {kind:#x}")
    except BaseException:
        sock.close()
        raise
    return sock
