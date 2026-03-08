# -*- mode: python ; coding: utf-8 -*-
"""
Claude Web Chat - PyInstaller 打包配置
"""

import os
import sys

block_cipher = None

# 获取当前目录
current_dir = os.path.dirname(os.path.abspath(SPEC))

# 收集所有数据文件
datas = [
    ('templates', 'templates'),
    ('models.json', '.'),
]

# 检查是否有 docs 目录
if os.path.exists(os.path.join(current_dir, 'docs')):
    datas.append(('docs', 'docs'))

a = Analysis(
    ['app.py'],
    pathex=[current_dir],
    binaries=[],
    datas=datas,
    hiddenimports=[
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        'starlette',
        'starlette.responses',
        'starlette.routing',
        'starlette.middleware',
        'starlette.staticfiles',
        'starlette.templating',
        'jinja2',
        'jinja2.ext',
        'multipart',
        'fastapi',
        'pydantic',
        'pydantic.json_schema',
        'webbrowser',
        'ppt_generator',
        'pptx',
        'docx',
        'PyPDF2',
        'PIL',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Claude Web Chat',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # 不显示控制台窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # 可以添加图标路径
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Claude Web Chat',
)

app = BUNDLE(
    coll,
    name='Claude Web Chat.app',
    icon=None,  # 可以添加图标路径
    bundle_identifier='com.claudeweb.chat',
    version='1.0.0',
    info_plist={
        'CFBundleName': 'Claude Web Chat',
        'CFBundleDisplayName': 'Claude Web Chat',
        'CFBundleVersion': '1.0.0',
        'CFBundleShortVersionString': '1.0.0',
        'CFBundleIdentifier': 'com.claudeweb.chat',
        'NSHighResolutionCapable': True,
        'LSMinimumSystemVersion': '10.13',
        'NSAppleEventsUsageDescription': 'This app needs to open your browser.',
        'CFBundleDocumentTypes': [],
    },
)