# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.utils.hooks import collect_all

import os

datas = []
binaries = []
# Bundle MFC + VC++ runtime DLLs so win32ui (pywin32, used by pywinauto) loads on
# client machines that don't have the VC++ 2015-2022 Redistributable installed.
_sys32 = os.path.join(os.environ.get('SystemRoot', r'C:\Windows'), 'System32')
for _dll in ['mfc140u.dll', 'vcruntime140.dll', 'vcruntime140_1.dll', 'msvcp140.dll']:
    _path = os.path.join(_sys32, _dll)
    if not os.path.exists(_path):
        raise SystemExit(f'[activity.spec] Missing {_path} - install VC++ 2015-2022 Redistributable (x64) on the build machine.')
    binaries.append((_path, '.'))
hiddenimports = ['base64', 'email', 'email.mime.text', 'email.mime.multipart', 'email.mime.image', 'pytesseract', 'PIL', 'PIL.Image', 'PIL.ImageEnhance', 'mss', 'numpy', 'win32gui', 'win32process', 'win32api', 'win32con', 'comtypes', 'pyautogui', 'App', 'grid_keyboard_nav', 'grid_ocr_nav', 'logger_config', 'proc_utils', 'pages', 'pages.administration_page', 'pages.control_center_page', 'pages.login_page', 'pages.main_page', 'pages.pledge_page', 'pages.report_download', 'pages.report_setup', 'pages.share_payout_page']
hiddenimports += collect_submodules('pages')
tmp_ret = collect_all('pytesseract')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('PIL')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('cv2')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pywinauto')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['activity.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PyQt5', 'PyQt6', 'PySide2', 'PySide6'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='activity',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
