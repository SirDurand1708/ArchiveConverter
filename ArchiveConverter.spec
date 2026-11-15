# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_all, copy_metadata
from pathlib import Path

datas = [
    ('ui_web/index.html', 'ui_web'),
    ('assets', 'assets'),
]

_model_src = Path('models/u2net.onnx')
if _model_src.is_file():
    datas.append((str(_model_src), 'models'))
elif os.environ.get('REQUIRE_OFFLINE_MODEL') == '1':
    raise FileNotFoundError(
        "REQUIRE_OFFLINE_MODEL=1 activo, pero falta 'models/u2net.onnx' para el empaquetado Full Offline."
    )

# Copiar metadatos de paquetes que usan importlib.metadata (resuelve PackageNotFoundError)
for pkg in ['tqdm', 'numpy', 'jsonschema']:
    try:
        datas.extend(copy_metadata(pkg))
    except Exception:
        pass

binaries = []
hiddenimports = [
    'win32com.client',
    'pythoncom',
    'psutil',
    'numpy',
    'openpyxl',
    'pptx',
    'docx',
    'docx2pdf',
    'pdf2docx',
    'PIL',
    'pillow_heif',
    'onnxruntime',
    'rapidocr_onnxruntime',
    'reportlab',
    'pymupdf',
    'webview',
    'webview.platforms.winforms',
    'webview.platforms.edgechromium',
    'clr_loader',
    'pythonnet',
]

# Recopilar recursos, binarios y submódulos necesarios para las librerías
for pkg in ['reportlab', 'pillow_heif', 'pymupdf', 'onnxruntime', 'rapidocr_onnxruntime']:
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
        datas.extend(pkg_datas)
        binaries.extend(pkg_binaries)
        hiddenimports.extend(pkg_hidden)
    except Exception:
        pass

hiddenimports = list(dict.fromkeys(hiddenimports))

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'customtkinter', 'tkinterdnd2', 'adodbapi'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ArchiveConverter',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    icon='assets/icon.ico'
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ArchiveConverter',
)
