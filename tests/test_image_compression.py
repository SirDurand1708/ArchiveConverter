import unittest
from pathlib import Path
from PIL import Image
from core import ImageConverter


class TestImageCompression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_dir = Path(__file__).parent / "sample_files"
        cls.output_dir = Path(__file__).parent / "output_files"
        cls.test_dir.mkdir(parents=True, exist_ok=True)
        cls.output_dir.mkdir(parents=True, exist_ok=True)

        # Create a large 1200x1200 sample image with colors/noise
        cls.large_img = cls.test_dir / "large_sample.jpg"
        img = Image.new("RGB", (1200, 1200), color=(120, 150, 200))
        # Draw some variation to create file size
        for x in range(0, 1200, 50):
            for y in range(0, 1200, 50):
                img.paste((x % 255, y % 255, (x + y) % 255), (x, y, x + 50, y + 50))
        img.save(cls.large_img, quality=100)

    def test_compress_with_target_size(self):
        target_kb = 150
        out_p = self.output_dir / "compressed_sample.jpg"
        result_path, old_sz, new_sz = ImageConverter.compress_image(
            self.large_img,
            output_path=out_p,
            max_size_kb=target_kb
        )
        self.assertTrue(result_path.exists())
        self.assertLessEqual(new_sz, target_kb * 1024)
        self.assertLess(new_sz, old_sz)


if __name__ == "__main__":
    unittest.main()
