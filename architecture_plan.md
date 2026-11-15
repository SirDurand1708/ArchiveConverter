# ARCHITECTURE PLAN: Integración Frontend (`ui_web`) para IA Offline, Errores Tipados y Auto-Updater

## 1. Definición del Problema
Conectar la interfaz web de escritorio ([ui_web/index.html](file:///C:/Users/georg/Documents/GitHub/ArchiveConverter/ui_web/index.html)) con el backend blindado (`DesktopAPI`, `BackgroundRemover` v3 y `updater.py`) para ofrecer:
- Mensajes de error claros y accionables basados en `error_code` sin usar `alert()`/`confirm()` nativos.
- Diagnóstico inicial de IA offline (`check_ai_model_status`) y feedback visual de *downscaling* (`<= 2048 px`).
- Notificación silenciosa de actualizaciones de GitHub Releases con barra de progreso y confirmación no bloqueante.
- Bloqueo selectivo de botones de acción durante tareas pesadas manteniendo el resto de la interfaz navegable.

---

## 2. Especificaciones Técnicas por Componente

### 2.1 Mapeo Centralizado de Errores y Toasts/Banners (`ui_web/index.html`)
- **Prohibición de diálogos nativos del navegador (`alert`, `confirm`):** Toda notificación y confirmación usará un componente de **toast/banner inline no bloqueante** con soporte de botón de acción opcional y cierre manual/automático.
- **Diccionario `AI_ERROR_CATALOG` en JS:** Mapea cada `error_code` devuelto por `DesktopAPI.remove_image_bg`:
  - `MODEL_MISSING` / `MODEL_CORRUPT`: Mensaje claro sobre el modelo offline + sugerencia de reinstalar/verificar integridad; actualiza la píldora de estado IA a estado de alerta.
  - `PERMISSION_DENIED`: Mensaje indicando carpeta de solo lectura/protegida + botón de acción **"Elegir otra carpeta"** que dispara `select_folder()` para reintentar.
  - `ANIMATED_UNSUPPORTED`: Explica que imágenes animadas o multipágina (GIF/WebP/TIFF/APNG) no están soportadas.
  - `IMAGE_TOO_LARGE`: Explica el límite seguro de memoria (`40 MP`).
  - `UNSUPPORTED_FORMAT`: Lista los formatos aceptados (`.png`, `.jpg`, `.jpeg`, `.webp`, `.bmp`, `.tiff`).
  - `BUSY`: Avisa que ya hay una operación IA en curso sin sobrescribir el estado de error crítico.
  - `WORKER_CRASHED` / `WORKER_TIMEOUT` / `PROCESSING_ERROR`: Mensaje amigable indicando que el proceso aislado protegió la app y botón para reintentar.
- **Seguridad XSS en JS:** Todos los mensajes, nombres de archivo y versiones insertados en el DOM usarán `textContent` (o helper `escapeHtml()`) en lugar de interpolar HTML sin sanitizar.

### 2.2 Píldora de Estado IA y Feedback de *Downscaling*
- **Arranque (`pywebviewready`):**
  - Invocar `window.pywebview.api.check_ai_model_status()` de forma asíncrona (no bloqueante) al inicializar la UI.
  - Pintar una **píldora de estado discreta** en la cabecera:
    - Verde: `"IA Local Lista"` (tooltip con ruta local).
    - Ámbar/Rojo: `"IA Offline No Disponible"` (sin bloquear el resto de herramientas PDF/Office/Imagen).
- **Detección exacta de *downscaling* (`core/bg_remover.py` + `ui_web/api.py`):**
  - En `sanitize_and_load_image` / `run_inference_in_process` y `DesktopAPI.remove_image_bg`, incluir `downscaled: bool`, `original_width`, `original_height`, `width`, `height`.
  - Cuando `res.downscaled === true`, mostrar un aviso informativo junto al resultado: *"Imagen optimizada automáticamente de {original_width}×{original_height} a {width}×{height} px para proteger la memoria"*.

### 2.3 Auto-Updater en la UI (`ui_web/index.html` + `ui_web/api.py`)
- **Comprobación silenciosa al arranque (`pywebviewready`):**
  - Llamar `window.pywebview.api.check_for_updates()` tras cargar la UI (con un pequeño retardo opcional o en segundo plano). Si no hay red o `update_available === false`, no mostrar nada.
- **Banner sutil + Confirmación + Progreso:**
  - Si `update_available === true`, mostrar un **banner sutil** en la parte superior con la nueva versión (`tag_name`), notas breves y botón **"Actualizar"**.
  - Al pulsar **"Actualizar"**, abrir un **diálogo/banner inline de confirmación** (sin `confirm()` nativo) advirtiendo que la app se descargará y reiniciará automáticamente.
  - Al confirmar, deshabilitar el botón (guardia anti doble-clic), mostrar barra de progreso (`0–100%`) alimentada por `window.onUpdateDownloadProgress(downloaded, total, percent)` y llamar `download_and_install_update(download_url, filename)`.
  - Si `download_and_install_update` devuelve `{ success: false }`, re-habilitar el botón y mostrar el error en toast inline.
  - También incluir un botón discreto **"Buscar actualizaciones"** (por ejemplo en el pie/cabecera) para comprobación manual.

### 2.4 Bloqueo Selectivo de Concurrencia en UI
- **Estado `isAiOrBatchBusy` en JS:**
  - Al iniciar `remove_image_bg` o `convert_batch` (`remove_bg`), deshabilitar **únicamente** los botones de acción de conversión/IA afectados (cambiando el texto a *"Procesando en proceso aislado..."* con spinner CSS), **sin bloquear** la navegación entre pestañas, historial ni herramientas PDF independientes.
  - Garantizar la restauración de los botones dentro de un bloque `try { ... } finally { ... }` incluso si la promesa de PyWebView rechaza o falla.

---

## 3. Archivos a Modificar
- `core/bg_remover.py` (añadir `downscaled`, `original_width`, `original_height` al resultado estructurado)
- `ui_web/api.py` (propagar `downscaled`, `original_width`, `original_height` en `remove_image_bg`)
- `ui_web/index.html` (píldora IA, catálogo `AI_ERROR_CATALOG`, toasts/banners inline, banner/progreso de auto-updater, bloqueo selectivo en `try/finally`)
- `tests/test_bg_remover_v3.py` (verificar `downscaled`, `original_width`, `original_height` en payload)
