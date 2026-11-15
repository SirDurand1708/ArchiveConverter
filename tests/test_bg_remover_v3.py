import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
from PIL import Image

from core.bg_remover import (
    BackgroundRemovalError,
    BackgroundRemovalValueError,
    BackgroundRemover,
    _atomic_save_png_exclusive,
    run_inference_in_process,
    sanitize_and_load_image,
)
from ui_web.api import DesktopAPI


class _FakeInput:
    name = "input.1"


class _FakeOnnxSession:
    def get_inputs(self):
        return [_FakeInput()]

    def run(self, _output_names, feed_dict):
        arr = next(iter(feed_dict.values()))
        assert arr.shape == (1, 3, 320, 320)
        assert arr.dtype == np.float32
        mask = np.zeros((1, 1, 320, 320), dtype=np.float32)
        mask[:, :, 80:240, 80:240] = 1.0
        return [mask]


class TestBackgroundRemoverV3(unittest.TestCase):
    def setUp(self):
        self.tmp_obj = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self.tmp_obj.name)
        BackgroundRemover.shutdown_worker()
        BackgroundRemover._model_hash_cache.clear()

    def tearDown(self):
        BackgroundRemover.shutdown_worker()
        self.tmp_obj.cleanup()

    def test_verify_model_integrity_caches_sha256_and_detects_mismatch(self):
        model_file = self.tmp_dir / "u2net.onnx"
        model_file.write_bytes(b"fake-onnx-weights-payload")

        # Por defecto exige U2NET_EXPECTED_SHA256 oficial -> archivo dummy falla con MODEL_CORRUPT
        with self.assertRaises(BackgroundRemovalError) as ctx_default:
            BackgroundRemover.verify_model_integrity(model_file)
        self.assertEqual(ctx_default.exception.error_code, "MODEL_CORRUPT")

        digest1 = BackgroundRemover.verify_model_integrity(model_file, expected_sha256="")
        self.assertEqual(len(digest1), 64)

        # Segunda llamada debe venir de caché sin re-abrir el archivo
        with patch("builtins.open", side_effect=AssertionError("No debió re-hashear el modelo cacheado")):
            digest2 = BackgroundRemover.verify_model_integrity(model_file, expected_sha256="")
        self.assertEqual(digest1, digest2)

        with self.assertRaises(BackgroundRemovalError) as ctx:
            BackgroundRemover.verify_model_integrity(model_file, expected_sha256="0" * 64)
        self.assertEqual(ctx.exception.error_code, "MODEL_CORRUPT")

    def test_sanitize_rejects_animated_webp_or_tiff(self):
        frames = [Image.new("RGB", (64, 64), color=(i * 40, 0, 0)) for i in range(3)]
        anim_path = self.tmp_dir / "anim.webp"
        frames[0].save(anim_path, save_all=True, append_images=frames[1:], duration=50, loop=0)

        with self.assertRaises(BackgroundRemovalValueError) as ctx:
            sanitize_and_load_image(anim_path)
        self.assertEqual(ctx.exception.error_code, "ANIMATED_UNSUPPORTED")

    def test_sanitize_rejects_decompression_bomb_limit(self):
        big_img = Image.new("RGB", (500, 500), color=(10, 20, 30))
        big_path = self.tmp_dir / "big.png"
        big_img.save(big_path)

        with self.assertRaises(BackgroundRemovalValueError) as ctx:
            sanitize_and_load_image(big_path, max_pixels=10_000)
        self.assertEqual(ctx.exception.error_code, "IMAGE_TOO_LARGE")

    def test_sanitize_downscales_preserving_aspect_and_normalizes_modes(self):
        # Imagen 3000x1500 debe reducirse a 2048x1024
        wide = Image.new("CMYK", (3000, 1500), color=(0, 100, 100, 0))
        wide_path = self.tmp_dir / "wide_cmyk.jpg"
        wide.save(wide_path, format="JPEG")

        rgb_out, prior_alpha = sanitize_and_load_image(wide_path, max_dim=2048)
        self.assertIsNone(prior_alpha)
        self.assertEqual(rgb_out.mode, "RGB")
        self.assertLessEqual(max(rgb_out.size), 2048)
        self.assertAlmostEqual(rgb_out.width / rgb_out.height, 2.0, places=1)

        # Imagen I;16 y paleta P con transparencia
        arr16 = np.full((64, 64), 32768, dtype=np.uint16)
        i16_path = self.tmp_dir / "gray16.png"
        Image.fromarray(arr16).save(i16_path)
        rgb16, _ = sanitize_and_load_image(i16_path)
        self.assertEqual(rgb16.mode, "RGB")

        p_img = Image.new("RGBA", (64, 64), (255, 0, 0, 0)).convert("P", palette=Image.Palette.ADAPTIVE)
        p_path = self.tmp_dir / "pal.png"
        p_img.save(p_path)
        rgb_p, _ = sanitize_and_load_image(p_path)
        self.assertEqual(rgb_p.mode, "RGB")

    def test_atomic_save_never_overwrites_existing_file(self):
        out_dir = self.tmp_dir / "out"
        out_dir.mkdir()
        img = Image.new("RGBA", (32, 32), (10, 20, 30, 255))

        p1 = _atomic_save_png_exclusive(img, out_dir, "foto")
        p2 = _atomic_save_png_exclusive(img, out_dir, "foto")

        self.assertTrue(p1.exists())
        self.assertTrue(p2.exists())
        self.assertNotEqual(p1, p2)
        self.assertEqual(p1.name, "foto_nobg.png")
        self.assertTrue(p2.name.startswith("foto_nobg_"))
        # Sin temporales residuales
        self.assertEqual(list(out_dir.glob(".tmp_nobg_*")), [])

    def test_run_inference_in_process_end_to_end(self):
        in_path = self.tmp_dir / "sample.png"
        Image.new("RGB", (128, 64), (200, 100, 50)).save(in_path)
        out_dir = self.tmp_dir / "out"

        res = run_inference_in_process(
            input_path=in_path,
            out_dir=out_dir,
            model_path=self.tmp_dir / "dummy.onnx",
            session=_FakeOnnxSession(),
        )
        self.assertTrue(res["ok"])
        self.assertEqual(res["width"], 128)
        self.assertEqual(res["height"], 64)
        out_p = Path(res["output_path"])
        self.assertTrue(out_p.is_file())
        with Image.open(out_p) as saved:
            self.assertEqual(saved.mode, "RGBA")

    def test_spawn_worker_handles_corrupt_model_and_crash_isolation(self):
        # Crea un modelo dummy corrupto y una imagen real: el worker spawn real arranca,
        # falla create_onnx_session con MODEL_CORRUPT y el proceso padre sobrevive limpio.
        model_file = self.tmp_dir / "u2net.onnx"
        model_file.write_bytes(b"not-a-valid-onnx-protobuf")
        img_path = self.tmp_dir / "input.png"
        Image.new("RGB", (64, 64), (100, 150, 200)).save(img_path)

        with patch.dict(os.environ, {"U2NET_EXPECTED_SHA256": ""}):
            with patch.object(BackgroundRemover, "find_local_model", return_value=model_file):
                with self.assertRaises(BackgroundRemovalError) as ctx:
                    BackgroundRemover.remove_background_structured(img_path, output_dir=self.tmp_dir)
        self.assertEqual(ctx.exception.error_code, "MODEL_CORRUPT")

    def test_busy_rejection_when_semaphore_held(self):
        model_file = self.tmp_dir / "u2net.onnx"
        model_file.write_bytes(b"dummy")
        img_path = self.tmp_dir / "input.png"
        Image.new("RGB", (64, 64), (100, 150, 200)).save(img_path)

        acquired = BackgroundRemover._infer_semaphore.acquire(blocking=False)
        self.assertTrue(acquired)
        try:
            with patch.dict(os.environ, {"U2NET_EXPECTED_SHA256": ""}):
                with patch.object(BackgroundRemover, "find_local_model", return_value=model_file):
                    with self.assertRaises(BackgroundRemovalError) as ctx:
                        BackgroundRemover.remove_background_structured(
                            img_path,
                            output_dir=self.tmp_dir,
                            wait_if_busy=False,
                        )
            self.assertEqual(ctx.exception.error_code, "BUSY")
        finally:
            BackgroundRemover._infer_semaphore.release()

    def test_permission_denied_fails_fast_before_worker(self):
        img_path = self.tmp_dir / "input.png"
        Image.new("RGB", (32, 32), (1, 2, 3)).save(img_path)

        with patch.object(
            BackgroundRemover,
            "_validate_output_dir_writable",
            side_effect=BackgroundRemovalError("PERMISSION_DENIED", "Solo lectura"),
        ):
            with self.assertRaises(BackgroundRemovalError) as ctx:
                BackgroundRemover.remove_background_structured(img_path, output_dir=self.tmp_dir)
        self.assertEqual(ctx.exception.error_code, "PERMISSION_DENIED")

    def test_desktop_api_remove_image_bg_structured_payload(self):
        api = DesktopAPI()
        out_file = self.tmp_dir / "foto_nobg.png"
        Image.new("RGBA", (100, 80), (0, 0, 0, 255)).save(out_file)

        with patch.object(
            BackgroundRemover,
            "remove_background_structured",
            return_value={
                "ok": True,
                "output_path": str(out_file),
                "width": 100,
                "height": 80,
                "error_code": None,
                "message": None,
            },
        ):
            res = api.remove_image_bg(str(self.tmp_dir / "foto.png"), output_dir=str(self.tmp_dir))

        self.assertTrue(res["ok"])
        self.assertTrue(res["success"])
        self.assertEqual(res["width"], 100)
        self.assertEqual(res["height"], 80)
        self.assertIsNone(res["error_code"])
        self.assertEqual(res["filename"], "foto_nobg.png")

        # Caso de error tipado
        err_res = api.remove_image_bg(str(self.tmp_dir / "no_existe.png"))
        self.assertFalse(err_res["ok"])
        self.assertFalse(err_res["success"])
        self.assertEqual(err_res["error_code"], "UNSUPPORTED_FORMAT")
        self.assertTrue(len(err_res["error_message"]) > 0)

    def test_main_verify_model_headless_flag(self):
        import io
        import sys
        import main as app_main

        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        with patch.object(sys, "argv", ["main.py", "--verify-model"]):
            with patch.object(BackgroundRemover, "find_local_model", return_value=None):
                with patch("sys.stderr", stderr_buf):
                    with self.assertRaises(SystemExit) as ctx:
                        app_main.main()
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("no encontrado", stderr_buf.getvalue().lower())

        dummy_model = self.tmp_dir / "u2net.onnx"
        dummy_model.write_bytes(b"ok")
        with patch.object(sys, "argv", ["main.py", "--verify-model"]):
            with patch.object(BackgroundRemover, "find_local_model", return_value=dummy_model):
                with patch.object(BackgroundRemover, "verify_model_integrity", return_value="abc123"):
                    with patch("core.bg_remover.create_onnx_session", return_value=MagicMock()):
                        with patch("sys.stdout", stdout_buf):
                            app_main.main()
        self.assertIn("[OK] Modelo IA verificado", stdout_buf.getvalue())


if __name__ == "__main__":
    unittest.main()
