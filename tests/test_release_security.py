"""Regression checks for the Windows trust and false-positive safeguards."""

from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent.parent


class ReleaseSecurityTests(unittest.TestCase):
    def test_main_executable_does_not_require_elevation_at_launch(self) -> None:
        spec = (ROOT / "unlock.spec").read_text(encoding="utf-8")
        self.assertIn("uac_admin=False", spec)
        self.assertNotIn("uac_admin=True", spec)

    def test_release_does_not_ship_command_scripts(self) -> None:
        spec = (ROOT / "unlock.spec").read_text(encoding="utf-8")
        strategies = (ROOT / "unlock" / "strategies.py").read_text(encoding="utf-8")
        self.assertIn('{".bat", ".cmd", ".ps1"}', spec)
        self.assertIn("zapret-strategies.json", spec)
        self.assertIn("STRATEGY_MANIFEST", strategies)

    def test_msi_has_no_custom_action_or_bootstrap_downloader(self) -> None:
        msi = (ROOT / "installer" / "Unlock.wxs").read_text(encoding="utf-8")
        workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        self.assertNotIn("CustomAction", msi)
        self.assertIn('Scope="perUser"', msi)
        self.assertIn("UnlockInstaller.msi", workflow)
        self.assertNotIn("UnlockSetup.exe", workflow)

    def test_application_has_no_autostart_module(self) -> None:
        self.assertFalse((ROOT / "unlock" / "autostart.py").exists())

    def test_public_release_reports_its_signing_state(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        self.assertIn("Select signing mode", workflow)
        self.assertIn("SIGNING_ENABLED", workflow)
        self.assertIn("Verify every shipped executable", workflow)

    def test_version_resource_matches_release_version(self) -> None:
        for name in ("unlock_version_info.txt", "unlock_setup_version_info.txt"):
            source = (ROOT / "assets" / name).read_text(encoding="utf-8")
            self.assertIn("ProductVersion', u'1.1.8'", source)


if __name__ == "__main__":
    unittest.main()
