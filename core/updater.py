import hashlib
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

APP_VERSION = "1.3.0"
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

    # Seleccionar el asset más adecuado (.zip portable o Setup.exe) y SHA256SUMS.txt
    selected_asset = _select_best_asset(assets)
    if not selected_asset:
        return None

    sha256sums_url = _find_sha256sums_url(assets)

    return {
        "update_available": True,
        "current_version": current_version,
        "version": tag_name.lstrip("vV"),
        "tag_name": tag_name,
        "download_url": selected_asset["browser_download_url"],
        "asset_name": selected_asset.get("name", "ArchiveConverter_update"),
        "asset_size": selected_asset.get("size", 0),
        "sha256sums_url": sha256sums_url,
        "installed_mode": is_installed_mode(),
        "release_notes": payload.get("body", ""),
        "html_url": payload.get("html_url", ""),
    }


_INNO_UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{5F7C7A28-D9E4-4284-9694-87A29E4C93B1}_is1"


def is_installed_mode(exe_path: Optional[Path] = None) -> bool:
    """
    Detecta de forma exacta si la ejecución actual corresponde a una instalación de Inno Setup
    comparando `InstallLocation` del registro contra la carpeta del ejecutable actual.
    """
    if sys.platform != "win32":
        return False
    try:
        import winreg
        current_dir = Path(exe_path or sys.executable).resolve().parent
        for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(root, _INNO_UNINSTALL_KEY) as key:
                    val, _ = winreg.QueryValueEx(key, "InstallLocation")
                    if val and Path(str(val)).resolve() == current_dir:
                        return True
            except OSError:
                continue
    except Exception:
        pass
    return False


def _find_sha256sums_url(assets: list[Dict[str, Any]]) -> Optional[str]:
    for asset in assets:
        name = str(asset.get("name", "")).strip().lower()
        url = asset.get("browser_download_url", "")
        if name == "sha256sums.txt" and url:
            return str(url)
    return None


def verify_release_sha256(
    downloaded_file: Path,
    sha256sums_url: Optional[str],
    asset_name: Optional[str] = None,
    timeout: int = 10,
) -> bool:
    """
    Verificación fail-closed contra SHA256SUMS.txt del Release.
    Devuelve True únicamente si SHA256SUMS.txt existe, contiene el hash del asset y coincide.
    """
    if not sha256sums_url or not downloaded_file.is_file():
        return False

    try:
        req = urllib.request.Request(
            sha256sums_url,
            headers={"User-Agent": f"ArchiveConverter-Updater/{APP_VERSION}"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return False
            content = resp.read().decode("utf-8", errors="replace")
    except Exception:
        return False

    target_name = (asset_name or downloaded_file.name).strip().lower()
    expected_hash: Optional[str] = None
    for line in content.splitlines():
        clean = line.strip()
        if not clean:
            continue
        m = re.match(r"^([0-9a-fA-F]{64})\s+\*?(.+)$", clean)
        if not m:
            continue
        h_hex, fname = m.group(1).lower(), Path(m.group(2).strip()).name.lower()
        if fname == target_name:
            expected_hash = h_hex
            break

    if not expected_hash:
        return False

    digest = hashlib.sha256()
    with open(downloaded_file, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)

    return digest.hexdigest().lower() == expected_hash


def _select_best_asset(
    assets: list[Dict[str, Any]],
    installed: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    """
    Selecciona el asset de descarga apropiado según modo Instalado (*Setup*.exe) vs Portable (.zip).
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

    use_installed = is_installed_mode() if installed is None else installed
    if use_installed:
        setup_exes = [a for a in exe_assets if "setup" in str(a.get("name", "")).lower()]
        if setup_exes:
            return setup_exes[0]
        if exe_assets:
            return exe_assets[0]
        if zip_assets:
            return zip_assets[0]
        return None

    is_onedir = getattr(sys, "frozen", False) and (Path(sys.executable).parent / "_internal").exists()
    if (is_onedir or not use_installed) and zip_assets:
        return zip_assets[0]
    if exe_assets:
        return exe_assets[0]
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
        # Instalador Inno Setup con cierre y reinicio controlado
        bat_content = (
            "@echo off\n"
            "chcp 65001 > nul\n"
            "timeout /t 2 /nobreak > nul\n"
            f'start "" "{downloaded_file}" /SILENT /CLOSEAPPLICATIONS /RESTARTAPPLICATIONS\n'
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

    try:
        from .single_instance import SingleInstanceManager
        SingleInstanceManager.release_active()
    except Exception:
        pass

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
