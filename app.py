#!/usr/bin/env python3
"""
Claude Web Chat - macOS 应用入口
"""

import os
import sys
import subprocess
import threading
import webbrowser
import time

def get_resource_path(relative_path):
    """获取资源文件路径，兼容打包后的路径"""
    if hasattr(sys, '_MEIPASS'):
        # PyInstaller 打包后的路径
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)

def open_browser(url):
    """延迟打开浏览器"""
    time.sleep(2)  # 等待服务器启动
    webbrowser.open(url)

def main():
    # 获取应用目录（资源文件所在位置）
    if hasattr(sys, '_MEIPASS'):
        app_dir = sys._MEIPASS
    else:
        app_dir = os.path.dirname(os.path.abspath(__file__))

    # 数据目录：使用用户主目录下的固定路径，避免写入只读的 _MEIPASS
    data_dir = os.path.join(os.path.expanduser('~'), '.claude-web-chat')
    os.makedirs(data_dir, exist_ok=True)

    # 设置环境变量，供 main.py 读取
    os.environ['CLAUDE_WEB_APP'] = '1'
    os.environ['CLAUDE_WEB_APP_DIR'] = app_dir
    os.environ['CLAUDE_WEB_DATA_DIR'] = data_dir

    # 切换工作目录到可写的数据目录
    os.chdir(data_dir)

    # 创建必要的目录
    os.makedirs(os.path.join(data_dir, 'data', 'sessions'), exist_ok=True)
    os.makedirs(os.path.join(data_dir, 'temp_images'), exist_ok=True)
    os.makedirs(os.path.join(data_dir, 'data', 'ppt_files'), exist_ok=True)

    # 复制 models.json 到数据目录（首次运行时）
    data_models = os.path.join(data_dir, 'models.json')
    bundled_models = os.path.join(app_dir, 'models.json')
    if not os.path.exists(data_models) and os.path.exists(bundled_models):
        import shutil
        shutil.copy2(bundled_models, data_models)

    # 启动浏览器
    browser_thread = threading.Thread(target=open_browser, args=('http://localhost:8000',))
    browser_thread.daemon = True
    browser_thread.start()

    # 启动 UVicorn 服务器
    import uvicorn
    from main import app

    print("=" * 50)
    print("Claude Web Chat 正在启动...")
    print("访问地址: http://localhost:8000")
    print("按 Ctrl+C 退出应用")
    print("=" * 50)

    uvicorn.run(app, host="0.0.0.0", port=8000)

if __name__ == '__main__':
    main()