"""Regression checks for the Windows trust and false-positive safeguards."""

from __future__ import annotations

from pathlib import Path
import unittest

from unlock.constants import APP_VERSION


ROOT = Path(__file__).resolve().parent.parent


class ReleaseSecurityTests(unittest.TestCase):
    def test_main_executable_starts_elevated_for_automatic_winws(self) -> None:
        spec = (ROOT / "unlock.spec").read_text(encoding="utf-8")
        self.assertIn("uac_admin=True", spec)

    def test_release_does_not_ship_command_scripts(self) -> None:
        spec = (ROOT / "unlock.spec").read_text(encoding="utf-8")
        strategies = (ROOT / "unlock" / "strategies.py").read_text(encoding="utf-8")
        self.assertIn('{".bat", ".cmd", ".ps1"}', spec)
        self.assertIn("zapret-strategies.json", spec)
        self.assertIn("STRATEGY_MANIFEST", strategies)

    def test_no_vpn_engine_is_left_in_the_product(self) -> None:
        for folder in ("sing-box", "xray", "wireproxy", "amneziawg"):
            self.assertFalse((ROOT / "bin" / folder).exists(), folder)
        spec = (ROOT / "unlock.spec").read_text(encoding="utf-8")
        self.assertIn('is_relative_to(bin_dir / "zapret")', spec)

    def test_installer_is_standard_without_script_code(self) -> None:
        script = (ROOT / "installer" / "Unlock.iss").read_text(encoding="utf-8")
        workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        self.assertNotIn("\n[Code]", script)
        self.assertIn("AppId=", script)
        self.assertIn("PrivilegesRequired=", script)
        self.assertIn("build_inno.py", workflow)
        self.assertIn("Unlock-*-Setup.exe", workflow)
        self.assertNotIn("UnlockInstaller.msi", workflow)
        self.assertNotIn("build_msi.py", workflow)

    def test_application_starts_services_automatically(self) -> None:
        main = (ROOT / "main.py").read_text(encoding="utf-8")
        self.assertIn("QTimer.singleShot(400, bootstrap)", main)
        self.assertIn("controller.connect()", main)

    def test_public_release_reports_its_signing_state(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        self.assertIn("Select signing mode", workflow)
        self.assertIn("SIGNING_ENABLED", workflow)
        self.assertIn("Verify every shipped executable", workflow)

    def test_version_resource_matches_release_version(self) -> None:
        for name in ("unlock_version_info.txt", "unlock_setup_version_info.txt"):
            source = (ROOT / "assets" / name).read_text(encoding="utf-8")
            self.assertIn(f"ProductVersion', u'{APP_VERSION}'", source)


if __name__ == "__main__":
    unittest.main()
