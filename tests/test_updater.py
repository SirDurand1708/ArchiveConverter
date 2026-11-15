import io
import json
import tempfile
import unittest
import urllib.error
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.updater import (
    APP_VERSION,
    apply_update_and_restart,
    check_for_updates,
    download_update,
    generate_update_script,
    is_newer_version,
    parse_semver,
)
from ui_web.api import DesktopAPI


class TestAutoUpdater(unittest.TestCase):
    def test_semver_parsing_and_comparison(self):
        self.assertEqual(parse_semver("v1.1.0"), (1, 1, 0))
        self.assertEqual(parse_semver("1.2.3-beta"), (1, 2, 3))
        self.assertTrue(is_newer_version("v1.2.0", "1.1.0"))
        self.assertTrue(is_newer_version("2.0.0", "1.1.0"))
        self.assertFalse(is_newer_version("v1.1.0", "1.1.0"))
        self.assertFalse(is_newer_version("1.0.9", "1.1.0"))

    def test_check_for_updates_finds_newer_release(self):
        fake_payload = {
            "tag_name": "v1.2.0",
            "body": "Mejoras de estabilidad",
            "html_url": "https://github.com/SirDurand1708/ArchiveConverter/releases/tag/v1.2.0",
            "assets": [
                {
                    "name": "ArchiveConverter-Portable.zip",
                    "browser_download_url": "https://example.com/ArchiveConverter-Portable.zip",
                    "size": 123456,
                },
                {
                    "name": "ArchiveConverter.exe",
                    "browser_download_url": "https://example.com/ArchiveConverter.exe",
                    "size": 654321,
                },
            ],
        }
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps(fake_payload).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            info = check_for_updates(current_version="1.1.0")

        self.assertIsNotNone(info)
        self.assertTrue(info["update_available"])
        self.assertEqual(info["version"], "1.2.0")
        self.assertTrue(info["download_url"].startswith("https://example.com/"))

    def test_check_for_updates_silent_fail_offline(self):
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("offline")):
            info = check_for_updates(current_version="1.1.0")
        self.assertIsNone(info)

        api = DesktopAPI()
        with patch("urllib.request.urlopen", side_effect=TimeoutError("timed out")):
            api_res = api.check_for_updates()
        self.assertFalse(api_res["update_available"])
        self.assertEqual(api_res["current_version"], APP_VERSION)

    def test_download_update_with_progress(self):
        data = b"A" * 1024 + b"B" * 1024
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.headers = {"Content-Length": str(len(data))}
        mock_resp.read.side_effect = [data[:1024], data[1024:], b""]
        mock_resp.__enter__.return_value = mock_resp

        progress_events = []
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("urllib.request.urlopen", return_value=mock_resp):
                downloaded = download_update(
                    "https://example.com/ArchiveConverter.exe",
                    filename="ArchiveConverter.exe",
                    temp_dir=Path(tmpdir),
                    progress_callback=lambda d, t, p: progress_events.append((d, t, p)),
                )

            self.assertIsNotNone(downloaded)
            self.assertTrue(downloaded.exists())
            self.assertEqual(downloaded.read_bytes(), data)
            self.assertGreaterEqual(len(progress_events), 2)
            self.assertEqual(progress_events[-1][2], 100.0)
            # Sin residuos parciales
            self.assertEqual(list(Path(tmpdir).glob(".part_*.tmp")), [])

    def test_download_update_handles_network_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("connection reset")):
                res = download_update("https://example.com/update.exe", temp_dir=Path(tmpdir))
        self.assertIsNone(res)

    def test_generate_update_script_for_exe(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            new_exe = tmp / "ArchiveConverter_new.exe"
            new_exe.write_bytes(b"MZ_NEW")
            target_exe = tmp / "ArchiveConverter.exe"

            bat = generate_update_script(new_exe, target_exe, script_dir=tmp)
            self.assertTrue(bat.exists())
            content = bat.read_text(encoding="utf-8")
            self.assertIn("timeout /t 2 /nobreak > nul", content)
            self.assertIn(f'copy /y "{new_exe.resolve()}" "{target_exe.resolve()}"', content)
            self.assertIn(f'start "" "{target_exe.resolve()}"', content)

    def test_generate_update_script_for_zip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            zip_path = tmp / "ArchiveConverter-Portable.zip"
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr("ArchiveConverter/ArchiveConverter.exe", b"MZ_ZIP")

            target_exe = tmp / "app" / "ArchiveConverter.exe"
            bat = generate_update_script(zip_path, target_exe, script_dir=tmp)
            self.assertTrue(bat.exists())
            content = bat.read_text(encoding="utf-8")
            self.assertIn("timeout /t 2 /nobreak > nul", content)
            self.assertIn("xcopy /s /e /y /i", content)
            self.assertIn(f'start "" "{target_exe.resolve()}"', content)

    def test_apply_update_and_restart_launches_popen_and_exits(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            new_exe = tmp / "ArchiveConverter_new.exe"
            new_exe.write_bytes(b"MZ")
            target_exe = tmp / "ArchiveConverter.exe"

            with patch("subprocess.Popen") as mock_popen:
                with self.assertRaises(SystemExit) as ctx:
                    apply_update_and_restart(new_exe, target_exe=target_exe, exit_app=True)
                self.assertEqual(ctx.exception.code, 0)
                mock_popen.assert_called_once()
                cmd_args = mock_popen.call_args[0][0]
                self.assertEqual(cmd_args[0], "cmd.exe")
                self.assertEqual(cmd_args[1], "/c")
                self.assertTrue(cmd_args[2].endswith(".bat"))


if __name__ == "__main__":
    unittest.main()
