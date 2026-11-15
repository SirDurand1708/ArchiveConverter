import unittest
from pathlib import Path
import tempfile
import threading
import time
from unittest.mock import patch
from PIL import Image

from core import BackgroundRemover, PDFToolkit, ConverterManager
from core.pdf_tools import create_isolated_temp_file, _safe_save_pdf
from core.office_converter import OFFICE_COM_LOCK
from ui_web.api import DesktopAPI, TEMP_FOLDER


class TestStabilityAndConcurrency(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_dir = Path(__file__).parent / "sample_files"
        cls.output_dir = Path(__file__).parent / "output_files"
        cls.test_dir.mkdir(parents=True, exist_ok=True)
        cls.output_dir.mkdir(parents=True, exist_ok=True)

        # Create sample image
        cls.sample_img = cls.test_dir / "sample_stab.png"
        img = Image.new("RGBA", (80, 80), color=(0, 128, 255, 255))
        img.save(cls.sample_img)

        # Create sample PDF
        import pymupdf
        cls.sample_pdf = cls.test_dir / "sample_stab.pdf"
        doc = pymupdf.open()
        p = doc.new_page()
        p.insert_text((50, 72), "Texto de prueba para concurrencia y estabilidad.")
        doc.save(cls.sample_pdf)
        doc.close()

    # ================= 1. BLINDAJE DE CONCURRENCIA EN OFFICE =================

    def test_office_com_lock_reentrancy_and_mutual_exclusion(self):
        """Verifica que OFFICE_COM_LOCK sea un RLock y garantice exclusión mutua entre hilos."""
        self.assertTrue(hasattr(OFFICE_COM_LOCK, "__enter__"))
        self.assertTrue(hasattr(OFFICE_COM_LOCK, "__exit__"))

        # Probar reentrancia en el mismo hilo
        with OFFICE_COM_LOCK:
            with OFFICE_COM_LOCK:
                reentered = True
        self.assertTrue(reentered)

        # Probar exclusión mutua entre hilos
        lock_acquired = []
        barrier = threading.Barrier(2)

        def worker():
            barrier.wait()
            with OFFICE_COM_LOCK:
                lock_acquired.append("worker")

        t = threading.Thread(target=worker)
        with OFFICE_COM_LOCK:
            t.start()
            barrier.wait()
            time.sleep(0.05)
            # El worker debe estar esperando que liberemos el lock
            self.assertEqual(lock_acquired, [])
        t.join(timeout=2.0)
        self.assertEqual(lock_acquired, ["worker"])

    def test_convert_batch_office_concurrency_and_com_lifecycle(self):
        """Verifica que DesktopAPI.convert_batch maneje la inicialización/desinicialización de COM."""
        api = DesktopAPI()
        # Crear 2 copias para procesar en lote simultáneamente
        f1 = self.test_dir / "batch_sheet_1.xlsx"
        f2 = self.test_dir / "batch_sheet_2.xlsx"
        import openpyxl
        for f in (f1, f2):
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.append(["Col1", "Col2"])
            ws.append(["ValA", "ValB"])
            wb.save(f)
            wb.close()

        res = api.convert_batch([str(f1), str(f2)], target_format="pdf", output_dir=str(self.output_dir))
        self.assertEqual(res["total"], 2)
        self.assertEqual(res["success_count"], 2)
        self.assertEqual(res["failed_count"], 0)

    # ================= 2. EXCEPCIONES TRANSPARENTES EN BACKGROUND REMOVER =================

    def test_bg_remover_missing_module_error(self):
        """Verifica que cuando onnxruntime no está instalado, create_onnx_session levante un error descriptivo."""
        from core.bg_remover import BackgroundRemovalError, create_onnx_session
        with patch.dict("sys.modules", {"onnxruntime": None}):
            with self.assertRaises(BackgroundRemovalError) as ctx:
                create_onnx_session(self.test_dir / "dummy.onnx")
            self.assertEqual(ctx.exception.error_code, "PROCESSING_ERROR")
            self.assertIn("onnxruntime", str(ctx.exception).lower())

    def test_bg_remover_invalid_format_error(self):
        """Verifica que formatos inválidos levanten ValueError con lista transparente de formatos soportados."""
        fake_txt = self.test_dir / "test.txt"
        fake_txt.write_text("no es una imagen")
        with self.assertRaises(ValueError) as ctx:
            BackgroundRemover.remove_background(fake_txt)
        self.assertIn("Formato no soportado", str(ctx.exception))
        self.assertIn(".png", str(ctx.exception))

    def test_bg_remover_session_initialization_failure(self):
        """Verifica que si la sesión de onnxruntime falla al inicializar, capture el error detallado."""
        from core.bg_remover import BackgroundRemovalError, create_onnx_session
        fake_ort = unittest.mock.MagicMock()
        fake_ort.InferenceSession.side_effect = Exception("Fallo de motor ONNX")
        with patch.dict("sys.modules", {"onnxruntime": fake_ort}):
            with self.assertRaises(BackgroundRemovalError) as ctx:
                create_onnx_session(self.test_dir / "u2net.onnx")
            self.assertEqual(ctx.exception.error_code, "MODEL_CORRUPT")
            self.assertIn("Fallo de motor ONNX", str(ctx.exception))

    def test_get_session_raises_descriptive_error_on_failure(self):
        """Verifica que create_onnx_session levante error detallado si InferenceSession falla."""
        from core.bg_remover import BackgroundRemovalError, create_onnx_session
        fake_ort = unittest.mock.MagicMock()
        fake_ort.InferenceSession.side_effect = Exception("DirectML engine allocation failure")
        with patch.dict("sys.modules", {"onnxruntime": fake_ort}):
            with self.assertRaises(BackgroundRemovalError) as ctx:
                create_onnx_session(self.test_dir / "u2net.onnx")
            self.assertIn("DirectML engine allocation failure", str(ctx.exception))

    def test_api_remove_image_bg_returns_clean_error(self):
        """Verifica que DesktopAPI.remove_image_bg devuelva un mensaje de advertencia limpio para la UI."""
        api = DesktopAPI()
        fake_txt = self.test_dir / "test.xyz"
        fake_txt.write_text("datos")
        res = api.remove_image_bg(str(fake_txt))
        self.assertFalse(res["success"])
        self.assertIn("error_message", res)
        self.assertTrue(len(res["error_message"]) > 0)

    # ================= 3. AISLAMIENTO DE ARCHIVOS TEMPORALES CON UUID =================

    def test_create_isolated_temp_file_uniqueness(self):
        """Verifica que create_isolated_temp_file genere nombres únicos basados en UUID y timestamp."""
        p1 = create_isolated_temp_file(prefix="test_pdf")
        p2 = create_isolated_temp_file(prefix="test_pdf")
        self.assertNotEqual(p1, p2)
        self.assertTrue(p1.name.startswith("test_pdf_"))
        self.assertTrue(p2.name.endswith(".pdf"))

    def test_api_create_temp_path_uniqueness(self):
        """Verifica que DesktopAPI.create_temp_path aísle rutas temporales con UUID."""
        p1 = DesktopAPI.create_temp_path("documento.pdf", prefix="proc")
        p2 = DesktopAPI.create_temp_path("documento.pdf", prefix="proc")
        self.assertNotEqual(p1, p2)
        self.assertEqual(p1.name, "documento.pdf")
        self.assertEqual(p2.name, "documento.pdf")
        self.assertNotEqual(p1.parent, p2.parent)

    def test_load_dropped_base64_concurrent_isolation(self):
        """Verifica que múltiples archivos arrastrados con el mismo nombre se aíslen en carpetas UUID distintas."""
        api = DesktopAPI()
        dummy_b64 = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
        
        info1 = api.load_dropped_base64("reporte.png", dummy_b64)
        info2 = api.load_dropped_base64("reporte.png", dummy_b64)

        self.assertIsNotNone(info1)
        self.assertIsNotNone(info2)
        self.assertEqual(info1["name"], "reporte.png")
        self.assertEqual(info2["name"], "reporte.png")
        # Las rutas absolutas deben ser diferentes gracias al aislamiento por UUID
        self.assertNotEqual(info1["path"], info2["path"])
        self.assertTrue(Path(info1["path"]).exists())
        self.assertTrue(Path(info2["path"]).exists())

    def test_safe_save_pdf_atomic_replace(self):
        """Verifica que _safe_save_pdf realice escritura atómica con archivo temporal UUID y no deje residuos."""
        import pymupdf
        doc = pymupdf.open(str(self.sample_pdf))
        out_target = self.output_dir / "atomic_saved.pdf"
        res = _safe_save_pdf(doc, out_target)
        doc.close()

        self.assertTrue(res.exists())
        self.assertEqual(res, out_target)
        # Verificar que no queden archivos temporales residuales .tmp_* en el directorio
        temp_leftovers = list(out_target.parent.glob(f".tmp_{out_target.stem}_*.tmp"))
        self.assertEqual(len(temp_leftovers), 0)

    def test_convert_batch_collision_avoidance_same_filename(self):
        """Verifica que al convertir múltiples archivos con el mismo nombre en diferentes carpetas no colisionen."""
        api = DesktopAPI()
        dir_a = self.test_dir / "sub_a"
        dir_b = self.test_dir / "sub_b"
        dir_a.mkdir(exist_ok=True)
        dir_b.mkdir(exist_ok=True)

        img_a = dir_a / "comun.png"
        img_b = dir_b / "comun.png"

        im = Image.new("RGB", (60, 60), color=(255, 0, 0))
        im.save(img_a)
        im.save(img_b)

        batch_out = self.output_dir / "batch_collision_test"
        import shutil
        shutil.rmtree(batch_out, ignore_errors=True)
        batch_out.mkdir(exist_ok=True)

        res = api.convert_batch([str(img_a), str(img_b)], target_format="jpg", output_dir=str(batch_out))
        self.assertEqual(res["total"], 2)
        self.assertEqual(res["success_count"], 2)

        # Los dos archivos de salida deben existir y tener nombres distintos (uno con sufijo UUID)
        generated_files = list(batch_out.glob("comun*.jpg"))
        self.assertEqual(len(generated_files), 2)
        self.assertNotEqual(generated_files[0], generated_files[1])

    # ================= 4. PRODUCCIÓN: MAIN FALLBACK, MODELOS OFFLINE Y SECUENCIALIDAD IA =================

    def test_main_ui_web_failure_logs_to_stderr_and_exits_cleanly(self):
        """Verifica que main._launch_modern_gui capture errores de ui_web, loguee a stderr y salga con sys.exit(1)."""
        import io
        import main as app_main

        stderr_buf = io.StringIO()
        with patch("sys.stderr", stderr_buf):
            with patch.dict("sys.modules", {"ui_web": None}):
                with self.assertRaises(SystemExit) as ctx:
                    app_main._launch_modern_gui()
                self.assertEqual(ctx.exception.code, 1)

        err_output = stderr_buf.getvalue()
        self.assertIn("ERROR CRÍTICO", err_output)
        self.assertNotIn("No module named 'ui'", err_output)

    def test_bg_remover_offline_missing_model_message(self):
        """Verifica que si el modelo ONNX no existe localmente, devuelva mensaje claro y MODEL_MISSING."""
        from core.bg_remover import BackgroundRemovalError
        with patch.object(BackgroundRemover, "find_local_model", return_value=None):
            with patch.object(BackgroundRemover, "_is_offline", return_value=True):
                status = BackgroundRemover.check_model_availability()
                self.assertFalse(status["available"])
                self.assertTrue(status["offline"])
                self.assertIn("no disponible localmente en el entorno portable", status["message"])

                with self.assertRaises(BackgroundRemovalError) as ctx:
                    BackgroundRemover.remove_background(self.sample_img)
                self.assertEqual(ctx.exception.error_code, "MODEL_MISSING")
                self.assertIn("no disponible localmente en el entorno portable", str(ctx.exception))

    def test_bg_remover_finds_local_model_in_u2net_home(self):
        """Verifica que find_local_model detecte modelos ONNX en U2NET_HOME."""
        import os
        with tempfile.TemporaryDirectory() as tmpdir:
            model_file = Path(tmpdir) / "u2net.onnx"
            model_file.write_bytes(b"dummy-onnx-weights")
            with patch.dict(os.environ, {"U2NET_HOME": tmpdir}):
                found = BackgroundRemover.find_local_model("u2net")
                self.assertIsNotNone(found)
                self.assertEqual(found.resolve(), model_file.resolve())
                status = BackgroundRemover.check_model_availability("u2net")
                self.assertTrue(status["available"])

    def test_convert_batch_heavy_ai_uses_single_worker_sequentially(self):
        """Verifica que las tareas pesadas de IA en convert_batch usen max_workers=1 (secuencial)."""
        api = DesktopAPI()
        recorded_max_workers = []

        import concurrent.futures
        original_executor = concurrent.futures.ThreadPoolExecutor

        def spy_executor(*args, **kwargs):
            recorded_max_workers.append(kwargs.get("max_workers"))
            return original_executor(*args, **kwargs)

        with patch("concurrent.futures.ThreadPoolExecutor", side_effect=spy_executor):
            with patch.object(BackgroundRemover, "remove_background", side_effect=lambda inp, out: out or inp):
                res = api.remove_batch_bg([str(self.sample_img), str(self.sample_img)], output_dir=str(self.output_dir))

        self.assertEqual(recorded_max_workers, [1])
        self.assertEqual(res["total"], 2)
        self.assertEqual(res["success_count"], 2)

    # ================= 5. BLINDAJE DE NOMBRES RESERVADOS, JS SEGURO Y PROCESOS COM HUÉRFANOS =================

    def test_sanitize_windows_reserved_device_names(self):
        """Verifica que nombres reservados de Windows (CON, PRN, AUX, NUL, COM1-9, LPT1-9) sean renombrados."""
        from ui_web.api import sanitize_filename
        for reserved in ("CON.png", "prn.pdf", "AUX", "nul.txt", "COM1.docx", "lpt9.jpg"):
            sanitized = sanitize_filename(reserved)
            self.assertTrue(sanitized.startswith("safe_"), f"No se sanitizó el nombre reservado: {reserved} -> {sanitized}")

        # También verificar en create_temp_path y load_dropped_base64
        temp_p = DesktopAPI.create_temp_path("CON.png")
        self.assertEqual(temp_p.name, "safe_CON.png")

        api = DesktopAPI()
        dummy_b64 = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
        info = api.load_dropped_base64("NUL.png", dummy_b64)
        self.assertIsNotNone(info)
        self.assertEqual(info["name"], "safe_NUL.png")

    def test_safe_evaluate_js_survives_closed_or_busy_window(self):
        """Verifica que _safe_evaluate_js capture excepciones si la ventana PyWebView está cerrada u ocupada."""
        api = DesktopAPI()
        mock_win = unittest.mock.MagicMock()
        mock_win.evaluate_js.side_effect = RuntimeError("Window is closed")
        api.set_window(mock_win)

        # No debe lanzar excepción
        api._safe_evaluate_js("window.onBatchProgressUpdate(1, 2, 'test.pdf')")
        mock_win.evaluate_js.assert_called_once()

    def test_terminate_orphaned_com_pid(self):
        """Verifica que _terminate_orphaned_pid liquide procesos COM huérfanos vía psutil."""
        from core.office_converter import _terminate_orphaned_pid
        mock_proc = unittest.mock.MagicMock()
        mock_proc.is_running.return_value = True

        with patch("psutil.pid_exists", return_value=True):
            with patch("psutil.Process", return_value=mock_proc):
                _terminate_orphaned_pid(99999)
                mock_proc.terminate.assert_called_once()
                mock_proc.wait.assert_called_once_with(timeout=2)


if __name__ == "__main__":
    unittest.main()
