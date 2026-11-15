# ARCHITECTURE PLAN: CI/CD & Empaquetado Full Offline (`u2net.onnx` + Release v1.2.x)

## 1. Definición del Problema
Garantizar que tanto el paquete portable (`ArchiveConverter-Portable.zip`) como el instalador de Windows (`ArchiveConverter-Setup-*.exe`) generados por GitHub Actions incluyan obligatoriamente el modelo `u2net.onnx` (~176 MB) verificado por SHA-256, cumpliendo la promesa **100% Offline** desde el primer arranque sin commitear binarios pesados al repositorio Git.

---

## 2. Arquitectura y Flujo de Datos del Pipeline CI/CD

### 2.1 Origen, Descarga y Verificación SHA-256 en CI (`.github/workflows/build-release.yml`)
1. **Caché de modelo en GitHub Actions (`actions/cache@v4`):**
   - Cachear `assets/models/u2net.onnx` usando clave basada en el hash SHA-256 oficial esperado (`u2net-onnx-<sha256>`).
2. **Descarga verificada (si hay *cache miss*):**
   - Descargar `u2net.onnx` desde la fuente oficial (`https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net.onnx`) con reintentos ante errores transitorios de red/HTTP.
   - Validar inmediatamente tamaño mínimo (>100 MB) y **checksum SHA-256 exacto** antes de continuar el build; si el hash no coincide, abortar el workflow.
3. **Sincronización de versión dinámica:**
   - Leer `APP_VERSION` desde `core/updater.py` (o extraer de `github.ref_name` en tags `v*`) y pasarlo a Inno Setup (`/DMyAppVersion=<version>`) para evitar desincronización con `#define MyAppVersion` en `installer/setup.iss`.
4. **Gate de pruebas automatizadas en CI:**
   - Ejecutar `python -m unittest discover tests -v` antes de compilar con PyInstaller para bloquear releases rotos.
5. **Smoke test post-empaquetado en CI:**
   - Verificar antes de comprimir que `dist/ArchiveConverter/_internal/models/u2net.onnx` (o ruta resuelta por `_MEIPASS`) existe y supera 100 MB, y ejecutar un chequeo rápido de disponibilidad del modelo desde el binario o módulo congelado.

### 2.2 Empaquetado en `ArchiveConverter.spec` y `installer/setup.iss`
1. **`ArchiveConverter.spec` (`--onedir`):**
   - Mapear explícitamente `assets/models/u2net.onnx` hacia la subcarpeta `models` dentro del bundle (`('assets/models/u2net.onnx', 'models')` cuando exista en disco), para que `sys._MEIPASS / "models" / "u2net.onnx"` sea la ruta primaria determinista en ejecución congelada.
   - Evitar que `('assets', 'assets')` duplique `assets/models/u2net.onnx` dentro de `_internal/assets/models/` (filtrando o moviendo `models/` fuera de `assets` o excluyendo `assets/models` de la copia genérica de `assets`), evitando duplicar 176 MB dentro del mismo `.zip`/`.exe`.
2. **`installer/setup.iss`:**
   - Aceptar `MyAppVersion` sobrescribible desde línea de comandos (`#ifndef MyAppVersion ... #endif`).
   - Mantener `Source: "..\dist\ArchiveConverter\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs` para incluir `models/u2net.onnx` dentro de `{app}`.
3. **`.gitignore`:**
   - Ignorar `assets/models/*.onnx` (y `models/*.onnx`) para impedir que el archivo de 176 MB se suba por error a Git.

### 2.3 Sincronización de Integridad en Runtime (`core/bg_remover.py`)
1. **Hash SHA-256 oficial fijado (`U2NET_SHA256`):**
   - Definir la constante `U2NET_EXPECTED_SHA256` en `BackgroundRemover` coincidiendo con el hash verificado en CI, de modo que `verify_model_integrity()` detecte corrupción en disco en el equipo del usuario sin depender de variables de entorno externas (permitiendo override solo para tests vía parámetro o env var).

### 2.4 Documentación SmartScreen / Windows Defender (`README.md`)
- Añadir una sección clara explicando que los binarios Open Source sin certificado comercial de *Code Signing* pueden mostrar aviso de Windows SmartScreen ("Windows protegió su PC") y cómo verificar la integridad mediante el hash SHA-256 publicado en cada Release.

---

## 3. Archivos a Modificar
- `.github/workflows/build-release.yml`
- `ArchiveConverter.spec`
- `installer/setup.iss`
- `core/bg_remover.py`
- `.gitignore`
- `README.md`
