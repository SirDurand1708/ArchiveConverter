# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all
from pathlib import Path

datas = [
    ('ui_web/index.html', 'ui_web'),
    ('assets', 'assets'),
]

# Recopilar recursos y modelos necesarios para las librerías
for pkg in ['reportlab', 'pillow_heif', 'pymupdf', 'rembg', 'onnxruntime']:
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
        datas.extend(pkg_datas)
    except Exception:
        pass

hiddenimports = [
    'win32com.client',
    'pythoncom',
    'openpyxl',
    'pptx',
    'docx',
    'docx2pdf',
    'pdf2docx',
    'PIL',
    'pillow_heif',
    'rembg',
    'onnxruntime',
    'reportlab',
    'pymupdf',
    'webview',
    'webview.platforms.winforms',
    'webview.platforms.edgechromium',
    'clr_loader',
    'pythonnet',
]

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'customtkinter', 'tkinterdnd2'],
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
