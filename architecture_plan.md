# ARCHITECTURE PLAN v1.3.0 (FINAL): Expansión Enterprise (OCR Local, Compresión PDF Agresiva, Cancelación, Instancia Única y Diagnóstico)

## 1. Definición del Problema
Expandir **ArchiveConverter** manteniendo su arquitectura 100% offline, UI monolítica en `ui_web/index.html` sin Node/Webpack y empaquetado `--onedir`, cerrando todos los requisitos de seguridad, concurrencia y estabilidad en Windows.

---

## 2. Decisiones Arquitectónicas Cerradas (Resolución de Bloqueos)

### 2.1 OCR Local Ligero (`core/ocr_engine.py` + `ArchiveConverter.spec`)
- **Motor:** `rapidocr_onnxruntime` ejecutado sobre `CPUExecutionProvider`.
- **Control de memoria (anti-OOM):**
  - Renderizado por página en *streaming* (liberando `pix = None` tras cada página).
  - Tope duro de resolución por página (`max_dim = 3500 px` en el lado mayor, calculando el factor de zoom efectivo para no exceder dicho límite en planos grandes).
- **Capa de texto buscable en PDF:**
  - Inversión de `/Rotate` y `CropBox` mediante la matriz inversa de PyMuPDF (`page.derotation_matrix`) al posicionar `insert_text(..., render_mode=3)` con fuente Unicode compatible.
- **Empaquetado `--onedir`:** Incluir `collect_all('rapidocr_onnxruntime')` en `ArchiveConverter.spec` para empaquetar modelos ONNX, diccionarios y `config.yaml` sin descargas en runtime.

### 2.2 Compresión Real de PDF Agresiva (`core/pdf_tools.py`)
- **Modos en `PDFToolkit.compress`:** `balanced`, `aggressive_150` (150 DPI) y `aggressive_96` (96 DPI).
- **Preservación de canales especiales:**
  - Excluir e intactar imágenes `1-bit` (CCITT/JBIG2), `Indexed` (paleta) y `CMYK` (para evitar explosión de tamaño o inversión de colores).
  - Re-muestrear proporcionalmente cualquier `SMask` asociado para conservar la transparencia sin fondos negros.
- **Deduplicación de `xref` y verificación de ganancia:**
  - Calcular el DPI efectivo máximo de cada `xref` entre todas las páginas donde aparece; solo re-muestrear si supera el DPI objetivo.
  - Comparar bytes del stream recomprimido vs original y conservar el menor.
- **Atomicidad:** Cerrar todos los handles de `fitz.Document` y escribir en `NamedTemporaryFile` dentro del **mismo directorio** que el destino antes de `os.replace()`.

### 2.3 Cancelación Cooperativa por `job_id` (`ui_web/api.py` + `core/ocr_engine.py` + `core/pdf_tools.py`)
- **Token inmutable por ejecución:** Cada lote o tarea larga crea su propio `threading.Event` asociado a un `job_id` único (eliminando carreras entre lotes consecutivos).
- **Propagación:** El `cancel_event` se comprueba entre archivos en `convert_batch` y **entre páginas** dentro de `PDFToolkit.compress` y `OCREngine`; al abortar, limpia archivos temporales parciales y devuelve `cancelled: True`.

### 2.4 Persistencia de Preferencias (`core/settings.py`)
- **Ruta:** `%APPDATA%\ArchiveConverter\settings.json` (fallback `~/.config/ArchiveConverter/settings.json`).
- **Esquema:** `{ "theme": "dark"|"light", "default_output_dir": str|null, "pdf_compression_mode": "balanced"|"aggressive_150"|"aggressive_96", "recursive_folder_scan": bool }`.
- **Escritura atómica:** `NamedTemporaryFile(dir=settings_dir)` + `flush()` + `os.replace()`.

### 2.5 Drag & Drop Recursivo de Carpetas + Reporte `downscaled` en Lote
- **PyWebView + Seguridad de escaneo:** Uso del hook nativo de PyWebView para obtener rutas reales de carpetas; escaneo recursivo acotado (máx. 500 archivos, filtrando symlinks, *Junction Points* de Windows y archivos *cloud-only* offline de OneDrive cuando aplique).
- **Lote `remove_bg`:** Acumula `downscaled_count` en `convert_batch` y lo devuelve en el resumen a `ui_web/index.html`.

### 2.6 Instancia Única con Mutex + Named Pipe IPC (`core/single_instance.py` + `main.py`)
- **Windows Named Mutex (`Local\ArchiveConverterSingleInstanceMutex`):** Adquirido en `main.py` tras `freeze_support()` y flags CLI headless (`--verify-model`).
- **Named Pipe (`\\.\pipe\ArchiveConverterIPC`):**
  - El servidor usa `PIPE_UNLIMITED_INSTANCES` con descriptor de seguridad restringido al SID del usuario actual.
  - Los procesos secundarios (ráfaga de menú contextual) usan bucle de reintentos con `WaitNamedPipe` / backoff (hasta 8–10 s), envían rutas Unicode con *framing* JSON delimitado y salen con `sys.exit(0)`.
  - El proceso primario encola rutas en `pending_files` hasta que `bootstrapApp()` drene la cola y restaura la ventana desde su hilo GUI.

### 2.7 Auto-Updater Diferenciado y Fail-Closed (`core/updater.py` + `ui_web/api.py`)
- **Detección exacta de instalación:** Comparar `InstallLocation` de `HKCU`/`HKLM\Software\Microsoft\Windows\CurrentVersion\Uninstall\{5F7C7A28-D9E4-4284-9694-87A29E4C93B1}_is1` con `Path(sys.executable).parent.resolve()`.
- **Fail-Closed SHA-256:** Descargar obligatoriamente `SHA256SUMS.txt` del Release y verificar el SHA-256 del asset descargado antes de ejecutarlo (abortar si falta o no coincide).
- **Ejecución limpia:** Liberar el Mutex de instancia única y cerrar WebView2 antes de lanzar `*Setup*.exe /SILENT /CLOSEAPPLICATIONS /RESTARTAPPLICATIONS` (instalado) o el script `.bat` (portable `.zip`).

### 2.8 Logs de Diagnóstico Local Offline (`core/diagnostics.py`)
- **Logging rotativo:** Inicializado únicamente tras adquirir el Mutex primario en `%LOCALAPPDATA%\ArchiveConverter\logs\app.log` (2 MB × 3 archivos).
- **Exportación sanitizada (`export_diagnostic_report()`):** Incluye versión, SO, RAM (`psutil`), estado del modelo ONNX y últimas 150 líneas del log enmascarando `%USERNAME%` y nombres de archivos de usuario.
