import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import uuid
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

APP_VERSION = "1.2.0"
GITHUB_RELEASES_API = "https://api.github.com/repos/SirDurand1708/ArchiveConverter/releases/latest"
TEMP_FOLDER = Path(tempfile.gettempdir()) / "ArchiveConverter"


def parse_semver(version_str: str) -> Tuple[int, int, int]:
    """
    Convierte una cadena de versión SemVer (ej: 'v1.2.0', '1.1.0-beta')
    en una tupla numérica comparable (major, minor, patch).
    """
    if not version_str:
        return (0, 0, 0)
    clean = version_str.strip().lstrip("vV")
    # Extraer únicamente los componentes numéricos principales (major.minor.patch)
    nums = [int(n) for n in re.findall(r"\d+", clean)[:3]]
    while len(nums) < 3:
        nums.append(0)
    return (nums[0], nums[1], nums[2])


def is_newer_version(remote_tag: str, local_version: str = APP_VERSION) -> bool:
    """Compara si la versión remota es estrictamente superior a la versión local."""
    return parse_semver(remote_tag) > parse_semver(local_version)


def check_for_updates(
    current_version: str = APP_VERSION,
    api_url: str = GITHUB_RELEASES_API,
    timeout: int = 5,
) -> Optional[Dict[str, Any]]:
    """
    Consulta la API de GitHub Releases usando exclusivamente urllib.request y json.
    Si hay una versión superior disponible, devuelve un diccionario con:
      - version: etiqueta de la nueva versión
      - download_url: URL directa del asset (.exe o .zip)
      - asset_name: nombre del archivo
      - asset_size: tamaño en bytes
      - release_notes: descripción del release
      - html_url: URL web del release
    Si no hay red, ocurre un timeout o cualquier error, falla de forma silenciosa
    devolviendo None para no interrumpir la experiencia offline.
    """
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"ArchiveConverter-Updater/{current_version}",
    }
    req = urllib.request.Request(api_url, headers=headers, method="GET")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError, OSError):
        # Fallo silencioso garantizado en entornos offline o sin conectividad
        return None
    except Exception:
        return None

    tag_name = payload.get("tag_name", "")
    if not tag_name or not is_newer_version(tag_name, current_version):
        return None

    assets = payload.get("assets", [])
    if not isinstance(assets, list) or not assets:
        return None

    # Seleccionar el asset más adecuado (.zip portable o .exe)
    selected_asset = _select_best_asset(assets)
    if not selected_asset:
        return None

    return {
        "update_available": True,
        "current_version": current_version,
        "version": tag_name.lstrip("vV"),
        "tag_name": tag_name,
        "download_url": selected_asset["browser_download_url"],
        "asset_name": selected_asset.get("name", "ArchiveConverter_update"),
        "asset_size": selected_asset.get("size", 0),
        "release_notes": payload.get("body", ""),
        "html_url": payload.get("html_url", ""),
    }


def _select_best_asset(assets: list[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Selecciona el asset de descarga más apropiado entre los archivos .zip y .exe
    publicados en el Release de GitHub.
    """
    zip_assets = []
    exe_assets = []

    for asset in assets:
        url = asset.get("browser_download_url", "")
        name = str(asset.get("name", "")).lower()
        if not url:
            continue
        if name.endswith(".zip"):
            zip_assets.append(asset)
        elif name.endswith(".exe"):
            exe_assets.append(asset)

    # Si es distribución portable empaquetada en carpeta (_internal o múltiples archivos),
    # priorizar .zip; si no, priorizar .exe y luego .zip.
    is_onedir = getattr(sys, "frozen", False) and (Path(sys.executable).parent / "_internal").exists()
    if is_onedir and zip_assets:
        return zip_assets[0]
    if exe_assets:
        return exe_assets[0]
    if zip_assets:
        return zip_assets[0]
    return None


def download_update(
    download_url: str,
    filename: Optional[str] = None,
    temp_dir: Optional[Path] = None,
    progress_callback: Optional[Callable[[int, int, float], None]] = None,
    timeout: int = 30,
) -> Optional[Path]:
    """
    Descarga el archivo de actualización dentro de TEMP_FOLDER en segundo plano.
    Reporta el progreso opcionalmente vía `progress_callback(descargado, total, porcentaje)`.
    Maneja excepciones de conectividad de forma limpia devolviendo None si falla.
    """
    if not download_url or not download_url.startswith(("https://", "http://")):
        return None

    target_dir = (Path(temp_dir) if temp_dir else TEMP_FOLDER / "updates").resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    safe_name = Path(filename).name if filename else Path(download_url.split("?")[0]).name
    safe_name = "".join(c for c in safe_name if c not in '<>:"/\\|?*').strip() or "ArchiveConverter_update.bin"

    uid = uuid.uuid4().hex[:8]
    dest_path = target_dir / f"{Path(safe_name).stem}_{uid}{Path(safe_name).suffix}"
    partial_path = target_dir / f".part_{uid}.tmp"

    headers = {"User-Agent": f"ArchiveConverter-Updater/{APP_VERSION}"}
    req = urllib.request.Request(download_url, headers=headers, method="GET")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status not in (200, 206):
                return None

            total_header = resp.headers.get("Content-Length")
            total_bytes = int(total_header) if total_header and total_header.isdigit() else 0
            downloaded = 0
            chunk_size = 65536  # 64 KB

            with open(partial_path, "wb") as f:
                while True:
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback:
                        percent = (downloaded / total_bytes * 100.0) if total_bytes > 0 else 0.0
                        try:
                            progress_callback(downloaded, total_bytes, round(percent, 1))
                        except Exception:
                            pass

        partial_path.replace(dest_path)
        return dest_path
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        return None
    except Exception:
        return None
    finally:
        if partial_path.exists():
            try:
                partial_path.unlink(missing_ok=True)
            except Exception:
                pass


def generate_update_script(
    downloaded_file: Path,
    target_exe: Path,
    script_dir: Optional[Path] = None,
) -> Path:
    """
    Genera dinámicamente el script auxiliar `update.bat` para realizar el reemplazo
    atómico en Windows una vez que `ArchiveConverter.exe` haya liberado el bloqueo del archivo.
    Soporta tanto ejecutables directos (.exe) como paquetes portables (.zip).
    """
    downloaded_file = Path(downloaded_file).resolve()
    target_exe = Path(target_exe).resolve()
    out_dir = (Path(script_dir) if script_dir else TEMP_FOLDER / "updates").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    uid = uuid.uuid4().hex[:8]
    bat_path = out_dir / f"update_{uid}.bat"

    if downloaded_file.suffix.lower() == ".zip":
        # Extraer el paquete ZIP antes de cerrar la app para que el .bat solo copie archivos
        extract_dir = out_dir / f"extracted_{uid}"
        extract_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(downloaded_file, "r") as zf:
            # Validación básica contra Zip Slip
            for member in zf.namelist():
                member_path = (extract_dir / member).resolve()
                if not member_path.is_relative_to(extract_dir):
                    raise ValueError(f"Entrada ZIP insegura detectada: {member}")
            zf.extractall(extract_dir)

        # Si el ZIP contiene una única subcarpeta raíz (ej. ArchiveConverter/), usarla como origen
        entries = list(extract_dir.iterdir())
        source_dir = entries[0] if len(entries) == 1 and entries[0].is_dir() else extract_dir
        app_dir = target_exe.parent

        bat_content = (
            "@echo off\n"
            "chcp 65001 > nul\n"
            "timeout /t 2 /nobreak > nul\n"
            f'xcopy /s /e /y /i "{source_dir}\\*" "{app_dir}\\" > nul\n'
            f'start "" "{target_exe}"\n'
            f'rmdir /s /q "{extract_dir}" 2>nul\n'
            f'del /f /q "{downloaded_file}" 2>nul\n'
            '(goto) 2>nul & del "%~f0"\n'
        )
    elif "setup" in downloaded_file.name.lower() or "installer" in downloaded_file.name.lower():
        # Instalador Inno Setup
        bat_content = (
            "@echo off\n"
            "chcp 65001 > nul\n"
            "timeout /t 2 /nobreak > nul\n"
            f'start "" "{downloaded_file}" /SILENT\n'
            '(goto) 2>nul & del "%~f0"\n'
        )
    else:
        # Reemplazo directo de binario .exe
        bat_content = (
            "@echo off\n"
            "chcp 65001 > nul\n"
            "timeout /t 2 /nobreak > nul\n"
            f'copy /y "{downloaded_file}" "{target_exe}" > nul\n'
            f'del /f /q "{downloaded_file}" 2>nul\n'
            f'start "" "{target_exe}"\n'
            '(goto) 2>nul & del "%~f0"\n'
        )

    bat_path.write_text(bat_content, encoding="utf-8")
    return bat_path


def apply_update_and_restart(
    downloaded_file: Path,
    target_exe: Optional[Path] = None,
    exit_app: bool = True,
) -> Path:
    """
    Genera `update.bat`, lo ejecuta en segundo plano desacoplado mediante `subprocess.Popen`
    y cierra inmediatamente la aplicación con `sys.exit(0)` para liberar el ejecutable.
    """
    exe_path = Path(target_exe) if target_exe else Path(sys.executable)
    bat_path = generate_update_script(downloaded_file=downloaded_file, target_exe=exe_path)

    creation_flags = 0
    if sys.platform == "win32":
        creation_flags = (
            getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
            | getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
        )

    subprocess.Popen(
        ["cmd.exe", "/c", str(bat_path)],
        creationflags=creation_flags,
        close_fds=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    if exit_app:
        sys.exit(0)

    return bat_path
