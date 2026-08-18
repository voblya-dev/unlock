"""Windows DNS companion for the managed AI hosts mode.

Zapret-GUI's AI DNS switch is a pair of changes: a large, managed hosts block
and the dns.malw.link resolvers on active adapters.  Keeping the resolver
snapshot in a separate, plain state document makes the operation reversible
even when Unlock is restarted between enabling and disabling the mode.
"""

from __future__ import annotations

import base64
import json
import subprocess
from pathlib import Path

from .constants import AI_DNS_STATE_PATH
from .host_overrides import apply_ai_hosts, remove_ai_hosts_block


AI_DNS_IPV4 = ("84.21.189.133", "193.23.209.189")
AI_DNS_IPV6 = ("2a12:bec4:1460:294::2", "2a01:ecc0:680:120::2")


class AiDnsError(RuntimeError):
    """The AI DNS resolver configuration could not be changed safely."""


class AiDnsPermissionError(AiDnsError):
    """The resolver change needs the elevated helper process."""


def _run_powershell(script: str) -> str:
    """Run a deliberately self-contained administrative PowerShell command."""
    try:
        completed = subprocess.run(
            [
                "powershell", "-NoProfile", "-NonInteractive",
                "-ExecutionPolicy", "Bypass", "-Command", script,
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=35,
            creationflags=0x08000000,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise AiDnsError(f"Could not run Windows DNS command: {exc}") from exc
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()
        permission_markers = (
            "access is denied", "access denied", "requires elevation",
            "administrator", "отказано в доступе", "требуется повышение",
        )
        if any(marker in detail.casefold() for marker in permission_markers):
            raise AiDnsPermissionError(detail or "Administrator rights are required")
        raise AiDnsError(detail or f"Windows DNS command failed ({completed.returncode})")
    return completed.stdout


def _active_dns_snapshot() -> list[dict]:
    """Read DNS settings of connected adapters in a locale-independent form."""
    script = r"""
$ErrorActionPreference = 'Stop'
$adapters = @(Get-NetAdapter | Where-Object { $_.Status -eq 'Up' })
$items = foreach ($adapter in $adapters) {
    [PSCustomObject]@{
        index = [int]$adapter.ifIndex
        ipv4 = @(Get-DnsClientServerAddress -InterfaceIndex $adapter.ifIndex -AddressFamily IPv4 |
            ForEach-Object { $_.ServerAddresses } | Where-Object { $_ })
        ipv6 = @(Get-DnsClientServerAddress -InterfaceIndex $adapter.ifIndex -AddressFamily IPv6 |
            ForEach-Object { $_.ServerAddresses } | Where-Object { $_ })
    }
}
@($items) | ConvertTo-Json -Compress -Depth 4
"""
    raw = _run_powershell(script).strip() or "[]"
    try:
        decoded = json.loads(raw)
    except ValueError as exc:
        raise AiDnsError("Windows returned an unreadable DNS configuration") from exc
    if isinstance(decoded, dict):
        decoded = [decoded]
    if not isinstance(decoded, list):
        raise AiDnsError("Windows returned an invalid DNS configuration")
    snapshot: list[dict] = []
    for item in decoded:
        if not isinstance(item, dict) or not isinstance(item.get("index"), int):
            continue
        snapshot.append({
            "index": item["index"],
            "ipv4": [str(v) for v in item.get("ipv4", []) if isinstance(v, str)],
            "ipv6": [str(v) for v in item.get("ipv6", []) if isinstance(v, str)],
        })
    if not snapshot:
        raise AiDnsError("No active network adapter was found")
    return snapshot


def _encoded_json(value: object) -> str:
    return base64.b64encode(json.dumps(value).encode("utf-8")).decode("ascii")


def _apply_resolvers(snapshot: list[dict], *, restore: bool) -> None:
    """Set the published resolvers, or restore exactly the captured servers."""
    state = _encoded_json(snapshot)
    v4 = _encoded_json(list(AI_DNS_IPV4))
    v6 = _encoded_json(list(AI_DNS_IPV6))
    script = rf"""
$ErrorActionPreference = 'Stop'
$snapshot = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{state}')) | ConvertFrom-Json
$v4 = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{v4}')) | ConvertFrom-Json
$v6 = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{v6}')) | ConvertFrom-Json
foreach ($item in @($snapshot)) {{
    # Set-DnsClientServerAddress has no address-family parameter on supported
    # Windows 10/11 builds. It accepts both IPv4 and IPv6 servers in one list
    # and applies each address family to the interface itself.
    if ({'$true' if restore else '$false'}) {{
        $servers = @($item.ipv4) + @($item.ipv6) | Where-Object {{ $_ }}
    }} else {{
        $servers = @($v4) + @($v6)
    }}
    if ($servers.Count -gt 0) {{
        Set-DnsClientServerAddress -InterfaceIndex ([int]$item.index) -ServerAddresses $servers
    }} else {{
        Set-DnsClientServerAddress -InterfaceIndex ([int]$item.index) -ResetServerAddresses
    }}
}}
Clear-DnsClientCache
"""
    _run_powershell(script)


def _load_state(path: Path = AI_DNS_STATE_PATH) -> list[dict] | None:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    snapshot = document.get("dns_snapshot") if isinstance(document, dict) else None
    if not isinstance(snapshot, list) or not snapshot:
        return None
    return snapshot


def _save_state(snapshot: list[dict], path: Path = AI_DNS_STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps({"dns_snapshot": snapshot}), encoding="utf-8")
    temporary.replace(path)


def _remove_state(path: Path = AI_DNS_STATE_PATH) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def enable_ai_dns(hosts_text: str) -> None:
    """Enable the full upstream-style AI mode and retain its rollback state."""
    snapshot = _load_state()
    created_snapshot = snapshot is None
    if snapshot is None:
        snapshot = _active_dns_snapshot()
        # Save before changing the system so even a sudden reboot has a path to
        # restoration on the next explicit disable.
        _save_state(snapshot)
    try:
        _apply_resolvers(snapshot, restore=False)
        apply_ai_hosts(hosts_text)
    except Exception:
        if created_snapshot:
            try:
                _apply_resolvers(snapshot, restore=True)
            finally:
                _remove_state()
        raise


def disable_ai_dns() -> None:
    """Remove only Unlock's hosts block and restore the user's DNS snapshot."""
    snapshot = _load_state()
    remove_ai_hosts_block()
    if snapshot is not None:
        _apply_resolvers(snapshot, restore=True)
        _remove_state()
