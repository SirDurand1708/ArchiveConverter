# ARCHITECTURE PLAN v3 (FINAL): IA Local Offline (Background Remover con Blindaje Enterprise)

## 1. Definición del Problema
Integrar la eliminación de fondos con IA local (`u2net.onnx`) en **ArchiveConverter** (aplicación de escritorio Windows con PyWebView y PyInstaller) garantizando:
- Operación **100% offline** sin llamadas de red ni descargas ocultas.
- **Aislamiento real de fallos nativos en C++** (`onnxruntime` y codecs nativos de imagen) para que un *Access Violation* o `abort()` nunca cierre PyWebView.
- **Protección contra OOM** en equipos de gama baja (4–8 GB RAM) mediante control estricto de decodificación, resolución y concurrencia.
- **Integridad de modelo y contrato de salida atómico** en Windows.

---

## 2. Decisiones Arquitectónicas Cerradas

### 2.1 Estrategia de Empaquetado PyInstaller (`--onedir`) e Integridad del Modelo
- **Modo de distribución:** `ArchiveConverter.spec` utiliza **`--onedir`** (`exclude_binaries=True` + `COLLECT`).
- **Resolución de ruta (Frozen + Dev):**
  - En binario PyInstaller: `Path(sys._MEIPASS) / "models" / "u2net.onnx"`.
  - En entorno de desarrollo (cuando `sys._MEIPASS` no existe): fallback a `<repo_root>/assets/models/u2net.onnx` o `%LOCALAPPDATA%\ArchiveConverter\models\u2net.onnx`.
  - **Sin copia redundante en arranque:** En `--onedir` el modelo ya reside en disco en ruta de solo lectura, por lo que no se duplica hacia `%LOCALAPPDATA%` al iniciar.
- **Verificación *lazy* cacheada en el proceso principal:**
  - La comprobación de existencia, tamaño esperado y hash **SHA-256** de `u2net.onnx` se ejecuta una sola vez en la primera invocación (en hilo de fondo, nunca bloqueando el arranque de la UI) y su resultado válido queda cacheado en el proceso principal para toda la sesión. Así, si el worker se reinicia tras expirar su TTL, **no recalcula** el SHA-256 de 176 MB.
  - Al pasar la ruta del modelo a `onnxruntime`, se normaliza con `pathlib` (y soporte Unicode/rutas largas en Windows cuando aplique).

### 2.2 Stack de Inferencia Estricto (`onnxruntime` directo, sin `rembg` / `pooch`)
- **Eliminación de `rembg` y `pooch` en inferencia:** `BackgroundRemover` (`core/bg_remover.py`) utilizará **únicamente `onnxruntime.InferenceSession` + `numpy` + `Pillow`**, implementando directamente el pre-procesado (`320×320`, normalización ImageNet) y post-procesado de máscara alfa U2-Net (`alpha_matting` deshabilitado).
- **Beneficios:** Cero riesgo de descargas en red ocultas (`pooch` eliminado del flujo) y eliminación de dependencias problemáticas en PyInstaller (`pymatting`, `numba`, `llvmlite`).
- **Configuración de sesión ONNX:**
  - `providers=["CPUExecutionProvider"]` fijo (evita fallos nativos de DirectML/CUDA en GPUs integradas de gama baja).
  - Hilos acotados: `intra_op_num_threads = min(4, os.cpu_count() or 2)` e `inter_op_num_threads = 1`.

### 2.3 Aislamiento Real de Procesos Nativos, Job Object y Ciclo de Vida
- **Blindaje de `main.py`:** Toda inicialización de PyWebView, ventana y single-instance lock estará estrictamente aislada bajo `if __name__ == "__main__":`, acompañado de `multiprocessing.freeze_support()` al inicio, para evitar relanzamientos de GUI al usar `spawn` en PyInstaller.
- **Subproceso dedicado (`multiprocessing` con `spawn`) e IPC ligero:**
  - El proceso principal **únicamente envía `(input_path, out_dir, model_path)`** al worker. Toda la decodificación de Pillow y la inferencia ONNX ocurren **dentro del subproceso worker**, protegiendo a PyWebView de crashes en `libjpeg`/`libtiff`/`libwebp` y de picos de RAM.
  - Si el worker muere por crash nativo (`0xC0000005`, `SIGSEGV`, `abort()`) o excede el timeout de ejecución (`120 s`), el padre limpia la referencia del worker y devuelve `WORKER_CRASHED` o `WORKER_TIMEOUT` sin tumbar la UI.
- **Anti-zombis en Windows (`Job Object`):**
  - Al crear el subproceso worker en Windows, el proceso padre lo asocia inmediatamente a un **Windows Job Object** configurado con `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`. Si el proceso principal cae abruptamente o es terminado desde el Administrador de Tareas, el kernel de Windows liquida automáticamente al worker.
- **Concurrencia y sincronización TTL vs `Semaphore(1)`:**
  - **Política de concurrencia:** `Semaphore(1)` (o cola FIFO en un hilo trabajador no-UI) para serializar inferencias. Si la UI ya tiene una inferencia en curso y se requiere respuesta inmediata en modo interactivo, puede devolverse `BUSY` o encolarse en hilo de fondo sin bloquear el hilo de PyWebView; el timeout de `120 s` mide únicamente el tiempo de ejecución dentro del worker.
  - **Gestor de estado sincronizado (sin race condition con TTL):** El arranque, despacho de tarea, cancelación de timer y apagado por TTL (`60 s` de inactividad) comparten un único `threading.Lock` de ciclo de vida: el timer de `60 s` se cancela al adquirir el lock para despachar una tarea y solo se reprograma al finalizar la tarea (cuando `in_flight == False`), garantizando que nunca mate al worker durante un despacho o inferencia lenta.

---

## 3. Pipeline de Saneamiento de Imagen (Ejecutado 100% dentro del Worker)

Orden estricto de operaciones dentro del subproceso worker:

1. **Límite anti *Decompression Bomb*:** Configurar `Image.MAX_IMAGE_PIXELS = 40_000_000` (40 MP) antes de abrir archivos. Capturar `Image.DecompressionBombError`, `UnidentifiedImageError` y `MemoryError` (devolviendo `IMAGE_TOO_LARGE`, `UNSUPPORTED_FORMAT` o `PROCESSING_ERROR`).
2. **Inspección de cabecera sin decodificar píxeles completos:**
   - Abrir con `Image.open(input_path)` y validar `img.format`, `img.size` y `getattr(img, "n_frames", 1)` antes de llamar a `load()`.
   - **Rechazo de animaciones/multipágina:** Cualquier imagen con `getattr(img, "n_frames", 1) > 1` (incluye `.webp` animados, `.gif`, APNG `.png` y `.tiff` multipágina) se rechaza explícitamente con código `ANIMATED_UNSUPPORTED`.
3. **Reducción previa a decodificación pesada + EXIF:**
   - Para JPEG de gran tamaño, aplicar `img.draft("RGB", (2048, 2048))` cuando supere `2048 px` antes de decodificar.
   - Aplicar `ImageOps.exif_transpose(img)` para corregir orientación de cámara.
   - Si `max(img.size) > 2048`, aplicar `img.thumbnail((2048, 2048), Image.Resampling.LANCZOS)` preservando *aspect ratio*.
4. **Normalización explícita de modos de color y alfa previo:**
   - `I;16`: escalar píxeles de 16 bits a 8 bits (`arr >> 8` / `(arr / 257).astype(np.uint8)`) antes de construir `RGBA`.
   - `I` (int32): normalizar/clampear rango entero a `uint8` (`0–255`) según rango observado (`> 255` -> escala lineal o `>> 8`, sino clip `0–255`).
   - `F` (float32): sanear `NaN`/`Inf` (`np.nan_to_num`), si el máximo está en `<= 1.0` escalar `* 255.0`, y clampear a `uint8` (`0–255`).
   - `P` (paletizado): convertir a `RGBA` preservando transparencia (`info["transparency"]`).
   - `1`, `L`, `LA`, `CMYK`, `RGB`: convertir explícitamente a `RGBA`.
   - **Imágenes con canal alfa previo (`RGBA`, `LA`, `P` transparente):** Para evitar *color bleed* de píxeles transparentes (`alpha == 0` con RGB residual), componer los píxeles `RGB` sobre fondo neutro antes de alimentar el tensor de entrada de U2-Net (y opcionalmente combinar con la máscara resultante respetando la transparencia previa).
5. **Contrato de resolución de salida:**
   - La salida es siempre **PNG con canal alfa (`RGBA`)** en la resolución procesada (máximo `2048 px` en el lado mayor, manteniendo *aspect ratio*).

---

## 4. Contrato de Salida y Puente API (`ui_web/api.py`)

1. **Validación previa de permisos de destino:**
   - Antes de despachar al worker, verificar que `out_dir` existe y es escribible creando y cerrando/eliminando un temporal con `tempfile.NamedTemporaryFile(dir=out_dir)`.
   - Si el directorio es de solo lectura (ej. `Program Files`, unidad óptica/red) o está bloqueado por *Controlled Folder Access* (`PermissionError`), fallar rápido con `PERMISSION_DENIED` (o usar el directorio de salida configurado por el usuario).
2. **Escritura atómica sin sobrescritura ni TOCTOU en Windows:**
   - El worker (o el API al recibir el PNG temporal generado en `out_dir`) escribe primero los datos en un archivo temporal único (`tempfile.NamedTemporaryFile(dir=out_dir, prefix=".tmp_nobg_", suffix=".png", delete=False)`), ejecuta `flush()` + `os.fsync()` y cierra el descriptor.
   - **Reserva exclusiva sin pisar archivos existentes:** **No se usa `os.replace()` sobre nombres candidatos** (ya que `os.replace` sobrescribiría un archivo existente). Para asignar `<stem>_nobg.png` o `<stem>_nobg_<uuid8>.png`, se intenta abrir/crear el nombre destino de forma exclusiva (`os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY)`) o enlazar/mover sin reemplazo (`os.link(tmp_path, candidate)` seguido de `os.unlink(tmp_path)`, con fallback a copia exclusiva bajo `O_CREAT | O_EXCL`) dentro de un bucle acotado.
   - **Resiliencia ante bloqueos transitorios de Windows:** Envolver el movimiento/limpieza final en reintentos breves con backoff (ej. 3 intentos, `50–150 ms`) ante `PermissionError` (`WinError 5` / `WinError 32` por Windows Defender, OneDrive o Explorer), y limpiar siempre el `.tmp` en `finally`.
3. **Respuesta estructurada hacia PyWebView (`DesktopAPI.remove_image_bg`):**
   - Retornar siempre un payload JSON uniforme:
     ```json
     {
       "ok": true,
       "output_path": "C:\\ruta\\foto_nobg.png",
       "width": 1536,
       "height": 2048,
       "error_code": null,
       "message": null
     }
     ```
   - Códigos de error tipados: `MODEL_MISSING`, `MODEL_CORRUPT`, `ANIMATED_UNSUPPORTED`, `IMAGE_TOO_LARGE`, `UNSUPPORTED_FORMAT`, `PERMISSION_DENIED`, `BUSY`, `WORKER_CRASHED`, `WORKER_TIMEOUT`, `PROCESSING_ERROR`.
