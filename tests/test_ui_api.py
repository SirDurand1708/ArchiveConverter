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

    def test_load_dropped_base64_traversal_protection(self):
        api = DesktopAPI()
        # Test that path traversal in filename is sanitized
        evil_filename = "../../evil.png"
        dummy_data = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
        info = api.load_dropped_base64(evil_filename, dummy_data)
        self.assertIsNotNone(info)
        # Name should be sanitized to just evil.png inside TEMP_FOLDER
        self.assertEqual(info["name"], "evil.png")
        saved_path = Path(info["path"])
        self.assertTrue(saved_path.is_relative_to(TEMP_FOLDER.resolve()))

    def test_pdf_split_range_validation(self):
        api = DesktopAPI()
        sample_pdf = self.sample_dir / "sample_doc.pdf"
        # Invalid non-numeric range
        res = api.pdf_split(str(sample_pdf), mode="range", page_range="abc-def")
        self.assertFalse(res["success"])
        self.assertIn("no válido", res["error_message"])

        # Invalid format
        res2 = api.pdf_split(str(sample_pdf), mode="range", page_range="1-2-3")
        self.assertFalse(res2["success"])


if __name__ == "__main__":
    unittest.main()
