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

    def test_installer_does_not_bypass_powershell_policy_or_create_autostart(self) -> None:
        source = (ROOT / "loader" / "installer.py").read_text(encoding="utf-8")
        self.assertNotIn('"-ExecutionPolicy", "Bypass"', source)
        self.assertNotIn('"/Create", "/TN"', source)
        self.assertIn("_remove_legacy_autostart", source)

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
            self.assertIn("ProductVersion', u'1.1.7'", source)


if __name__ == "__main__":
    unittest.main()
