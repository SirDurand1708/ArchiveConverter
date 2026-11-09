import unittest
from pathlib import Path
import tempfile
from ui_web.api import DesktopAPI, cleanup_temp_files, TEMP_FOLDER


class TestDesktopAPI(unittest.TestCase):
    def setUp(self):
        self.sample_dir = Path(__file__).parent / "sample_files"
        self.sample_img = self.sample_dir / "sample.png"

    def test_initial_file_none(self):
        api = DesktopAPI()
        self.assertIsNone(api.get_initial_file())

    def test_initial_file_valid(self):
        api = DesktopAPI(initial_file=str(self.sample_img))
        info = api.get_initial_file()
        self.assertIsNotNone(info)
        self.assertEqual(info["name"], "sample.png")
        self.assertTrue(info["is_image"])
        self.assertIn("webp", info["supported_targets"])

    def test_temp_cleanup(self):
        TEMP_FOLDER.mkdir(parents=True, exist_ok=True)
        test_file = TEMP_FOLDER / "test_temp_file.txt"
        test_file.write_text("temporary data")
        self.assertTrue(test_file.exists())
        cleanup_temp_files()
        self.assertFalse(test_file.exists())


if __name__ == "__main__":
    unittest.main()
