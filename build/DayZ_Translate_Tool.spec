# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['D:\\MY\\_tools\\DayZ_Translate_Tool\\main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['aiohttp', 'anyio', 'cryptography', 'dateutil', 'dns', 'docx2txt', 'email_validator', 'fsspec', 'httpx', 'jinja2', 'lxml', 'markdown_it', 'mypy', 'numpy', 'openpyxl', 'pandas', 'PIL', 'pydantic', 'pydantic_core', 'pygments', 'pypdf', 'pytest', 'rich', 'scipy', 'setuptools', 'websockets', 'yaml'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='DayZ_Translate_Tool',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='DayZ_Translate_Tool',
)
