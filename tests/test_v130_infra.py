import hashlib
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pymupdf
from PIL import Image

from core.diagnostics import export_diagnostic_report, init_logging, sanitize_log_text, shutdown_logging
from core.ocr_engine import OCREngine
from core.pdf_tools import PDFToolkit
from core.settings import DEFAULT_SETTINGS, SettingsManager
from core.single_instance import SingleInstanceManager
from core.updater import _select_best_asset, generate_update_script, is_installed_mode, verify_release_sha256
from ui_web.api import DesktopAPI


class TestV130Infra(unittest.TestCase):
    def setUp(self):
        self.tmp_obj = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self.tmp_obj.name)

    def tearDown(self):
        shutdown_logging()
        self.tmp_obj.cleanup()

    def test_settings_load_save_atomic_and_sanitize(self):
        cfg_path = self.tmp_dir / "settings.json"
        initial = SettingsManager.load(path=cfg_path)
        self.assertEqual(initial, DEFAULT_SETTINGS)

        saved = SettingsManager.save(
            {"theme": "light", "pdf_compression_mode": "aggressive_150", "invalid_key": 123},
            path=cfg_path,
        )
        self.assertEqual(saved["theme"], "light")
        self.assertEqual(saved["pdf_compression_mode"], "aggressive_150")
        self.assertNotIn("invalid_key", saved)

        reloaded = SettingsManager.load(path=cfg_path)
        self.assertEqual(reloaded["theme"], "light")
        self.assertEqual(reloaded["pdf_compression_mode"], "aggressive_150")

        # Corrupción de JSON -> fallback seguro a defaults
        cfg_path.write_text("{corrupt-json", encoding="utf-8")
        self.assertEqual(SettingsManager.load(path=cfg_path), DEFAULT_SETTINGS)

    def test_diagnostics_sanitize_and_export(self):
        log_path = self.tmp_dir / "logs" / "app.log"
        logger = init_logging(is_primary=True, log_path=log_path)
        logger.info("Test log entry")

        raw_path = r"C:\Users\georg\Documents\contrato_secreto.pdf"
        sanitized = sanitize_log_text(raw_path)
        self.assertNotIn("contrato_secreto", sanitized)
        self.assertIn(".pdf", sanitized)

        report_path = self.tmp_dir / "diag.txt"
        out = export_diagnostic_report(output_path=report_path, app_version="1.3.0", log_path=log_path)
        self.assertTrue(out.is_file())
        content = out.read_text(encoding="utf-8")
        self.assertIn("App Version: 1.3.0", content)

    def test_single_instance_mutex_and_named_pipe_ipc(self):
        uid = "test_" + str(threading.get_ident())
        mgr_primary = SingleInstanceManager(
            mutex_name=rf"Local\TestACMutex_{uid}",
            pipe_name=rf"\\.\pipe\TestACPipe_{uid}",
        )
        received = []
        evt = threading.Event()

        def on_files(files):
            received.extend(files)
            evt.set()

        is_primary = mgr_primary.acquire_or_forward([], on_files_received=on_files)
        self.assertTrue(is_primary)
        try:
            ok = SingleInstanceManager.send_args_to_primary(
                [r"C:\tmp\doc1.pdf", r"C:\tmp\doc2.png"],
                pipe_name=rf"\\.\pipe\TestACPipe_{uid}",
                timeout=3.0,
            )
            self.assertTrue(ok)
            self.assertTrue(evt.wait(timeout=3.0))
            self.assertEqual(received, [r"C:\tmp\doc1.pdf", r"C:\tmp\doc2.png"])
        finally:
            mgr_primary.release()

    def test_updater_fail_closed_sha256sums(self):
        payload = b"binary-update-bytes"
        upd_file = self.tmp_dir / "ArchiveConverter-Portable.zip"
        upd_file.write_bytes(payload)
        good_hash = hashlib.sha256(payload).hexdigest()

        # Sin URL -> fail-closed (False)
        self.assertFalse(verify_release_sha256(upd_file, None, "ArchiveConverter-Portable.zip"))

        fake_resp = MagicMock()
        fake_resp.status = 200
        fake_resp.read.return_value = f"{good_hash}  ArchiveConverter-Portable.zip\n".encode("utf-8")
        fake_resp.__enter__.return_value = fake_resp

        with patch("urllib.request.urlopen", return_value=fake_resp):
            self.assertTrue(
                verify_release_sha256(upd_file, "https://example.com/SHA256SUMS.txt", "ArchiveConverter-Portable.zip")
            )

        # Hash distinto -> False
        bad_resp = MagicMock()
        bad_resp.status = 200
        bad_resp.read.return_value = f"{'0' * 64}  ArchiveConverter-Portable.zip\n".encode("utf-8")
        bad_resp.__enter__.return_value = bad_resp
        with patch("urllib.request.urlopen", return_value=bad_resp):
            self.assertFalse(
                verify_release_sha256(upd_file, "https://example.com/SHA256SUMS.txt", "ArchiveConverter-Portable.zip")
            )

    def test_updater_selects_setup_when_installed_and_zip_when_portable(self):
        assets = [
            {"name": "ArchiveConverter-Portable.zip", "browser_download_url": "https://ex/p.zip"},
            {"name": "ArchiveConverter-Setup-v1.3.0.exe", "browser_download_url": "https://ex/s.exe"},
        ]
        self.assertEqual(_select_best_asset(assets, installed=True)["name"], "ArchiveConverter-Setup-v1.3.0.exe")
        self.assertEqual(_select_best_asset(assets, installed=False)["name"], "ArchiveConverter-Portable.zip")

        bat = generate_update_script(
            downloaded_file=self.tmp_dir / "ArchiveConverter-Setup-v1.3.0.exe",
            target_exe=self.tmp_dir / "ArchiveConverter.exe",
            script_dir=self.tmp_dir,
        )
        txt = bat.read_text(encoding="utf-8")
        self.assertIn("/SILENT /CLOSEAPPLICATIONS /RESTARTAPPLICATIONS", txt)

    def test_pdf_compress_aggressive_150_and_cancel(self):
        # Crear imagen RGB grande (1200x1200) insertada en una página pequeña (100x100 pt) -> DPI muy alto
        rgb_img = Image.new("RGB", (1200, 1200), color=(180, 60, 40))
        # Dibujar ruido/gradiente para que no comprima trivialmente en PNG/JPEG
        px = rgb_img.load()
        for y in range(0, 1200, 3):
            for x in range(0, 1200, 3):
                px[x, y] = ((x * 7) % 256, (y * 11) % 256, ((x + y) * 5) % 256)
        rgb_path = self.tmp_dir / "highres.png"
        rgb_img.save(rgb_path, format="PNG")

        pdf_in = self.tmp_dir / "input.pdf"
        doc = pymupdf.open()
        page = doc.new_page(width=144, height=144)  # 2x2 pulgadas -> 1200px = 600 DPI
        page.insert_image(page.rect, filename=str(rgb_path))
        doc.save(str(pdf_in))
        doc.close()

        out_pdf = PDFToolkit.compress(pdf_in, output_path=self.tmp_dir / "out_150.pdf", mode="aggressive_150")
        self.assertTrue(out_pdf.is_file())
        self.assertLess(out_pdf.stat().st_size, pdf_in.stat().st_size)

        # Cancelación cooperativa
        evt = threading.Event()
        evt.set()
        with self.assertRaises(InterruptedError):
            PDFToolkit.compress(pdf_in, output_path=self.tmp_dir / "cancelled.pdf", mode="aggressive_150", cancel_event=evt)

    def test_ocr_engine_formats_and_cancel(self):
        pdf_in = self.tmp_dir / "scan.pdf"
        doc = pymupdf.open()
        page = doc.new_page(width=400, height=300)
        page.insert_text((40, 60), "Factura Prueba", fontsize=16)
        doc.save(str(pdf_in))
        doc.close()

        fake_mod = types.ModuleType("rapidocr_onnxruntime")

        class FakeRapidOCR:
            def __call__(self, img_arr):
                return [([[10, 10], [150, 10], [150, 40], [10, 40]], "TEXTO OCR DETECTADO", 0.99)], None

        fake_mod.RapidOCR = FakeRapidOCR

        with patch.dict(sys.modules, {"rapidocr_onnxruntime": fake_mod}):
            OCREngine._engine = None
            out_txt = OCREngine.process_pdf(pdf_in, output_format="txt", output_path=self.tmp_dir / "out.txt")
            self.assertTrue(out_txt.is_file())
            self.assertIn("TEXTO OCR DETECTADO", out_txt.read_text(encoding="utf-8"))

            out_docx = OCREngine.process_pdf(pdf_in, output_format="docx", output_path=self.tmp_dir / "out.docx")
            self.assertTrue(out_docx.is_file())
            self.assertGreater(out_docx.stat().st_size, 0)

            out_pdf = OCREngine.process_pdf(pdf_in, output_format="pdf", output_path=self.tmp_dir / "out_ocr.pdf")
            self.assertTrue(out_pdf.is_file())
            verify_doc = pymupdf.open(str(out_pdf))
            self.assertIn("TEXTO OCR DETECTADO", verify_doc[0].get_text())
            verify_doc.close()

            evt = threading.Event()
            evt.set()
            with self.assertRaises(InterruptedError):
                OCREngine.process_pdf(pdf_in, output_format="txt", cancel_event=evt)

    def test_desktop_api_v130_endpoints_and_ipc(self):
        api = DesktopAPI()

        # IPC queue
        api.enqueue_ipc_files([r"C:\tmp\a.pdf", r"C:\tmp\b.docx"])
        first_pop = api.consume_pending_files()
        self.assertEqual(len(first_pop), 2)
        self.assertEqual(api.consume_pending_files(), [])

        # Settings roundtrip
        cfg_path = self.tmp_dir / "ui_settings.json"
        with patch.object(SettingsManager, "get_settings_path", return_value=cfg_path):
            res_save = api.save_settings({"theme": "light", "pdf_compression_mode": "aggressive_96"})
            self.assertEqual(res_save["theme"], "light")
            res_get = api.get_settings()
            self.assertEqual(res_get["theme"], "light")
            self.assertEqual(res_get["pdf_compression_mode"], "aggressive_96")

        # Export diagnostics
        diag_res = api.export_diagnostic_report(output_dir=str(self.tmp_dir))
        self.assertTrue(diag_res["success"])
        self.assertTrue(Path(diag_res["output_path"]).is_file())

        # Expand dropped paths (ignora ocultos)
        sub = self.tmp_dir / "drop_dir"
        sub.mkdir()
        f1 = sub / "doc.pdf"
        f2 = sub / ".hidden.pdf"
        f1.write_bytes(b"%PDF-1.4")
        f2.write_bytes(b"%PDF-1.4")
        expanded = api.expand_dropped_paths([str(sub)], recursive=True)
        self.assertEqual(len(expanded), 1)
        self.assertEqual(Path(expanded[0]).name, "doc.pdf")

        # Cancelación cooperativa en convert_batch
        def _fake_convert(input_path, target_format, output_path=None, **kw):
            out = Path(output_path) if output_path else Path(input_path)
            out.write_bytes(b"ok")
            api.cancel_current_task()
            return types.SimpleNamespace(
                success=True,
                output_path=out,
                elapsed_seconds=0.01,
                error_message=None,
            )

        with patch.object(api.manager, "convert_file", side_effect=_fake_convert):
            f_img = self.tmp_dir / "one.png"
            f_img2 = self.tmp_dir / "two.png"
            Image.new("RGB", (10, 10)).save(f_img)
            Image.new("RGB", (10, 10)).save(f_img2)
            batch_res = api.convert_batch([str(f_img), str(f_img2)], "jpg", output_dir=str(self.tmp_dir))
            self.assertTrue(batch_res["cancelled"])

        # PDF OCR endpoint
        pdf_in = self.tmp_dir / "api_ocr.pdf"
        doc = pymupdf.open()
        doc.new_page(width=200, height=200)
        doc.save(str(pdf_in))
        doc.close()
        with patch("core.ocr_engine.OCREngine.process_pdf", return_value=self.tmp_dir / "api_ocr_ocr.txt"):
            ocr_res = api.pdf_ocr(str(pdf_in), output_format="txt", output_dir=str(self.tmp_dir))
            self.assertTrue(ocr_res["success"])
            self.assertTrue(ocr_res["output_path"].endswith("api_ocr_ocr.txt"))


if __name__ == "__main__":
    unittest.main()
