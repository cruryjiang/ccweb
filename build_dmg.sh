#!/bin/bash
# Claude Web Chat - macOS 打包脚本
# 生成 .app 和 .dmg 安装包

set -e

echo "=========================================="
echo "Claude Web Chat - macOS 打包脚本"
echo "=========================================="

# 进入项目目录
cd "$(dirname "$0")"
PROJECT_DIR=$(pwd)

echo "📦 项目目录: $PROJECT_DIR"

# 激活虚拟环境
echo "🔧 激活虚拟环境..."
source venv/bin/activate

# 安装必要的依赖
echo "📥 检查依赖..."
pip install pyinstaller uvicorn fastapi jinja2 python-multipart pydantic -q

# 清理旧的构建文件
echo "🧹 清理旧构建文件..."
rm -rf build/ dist/ *.spec.bak

# 执行 PyInstaller 打包
echo "📦 执行 PyInstaller 打包..."
pyinstaller ClaudeWebChat.spec --clean

# 检查打包结果
if [ ! -d "dist/Claude Web Chat.app" ]; then
    echo "❌ 打包失败：找不到 .app 文件"
    exit 1
fi

echo "✅ .app 打包成功"

# 创建 DMG
echo "💽 创建 DMG 安装包..."
DMG_NAME="Claude Web Chat-1.0.0.dmg"
DMG_DIR="$PROJECT_DIR/dist"

# 使用 macOS 内置工具创建 DMG
hdiutil create -volname "Claude Web Chat" \
    -srcfolder "dist/Claude Web Chat.app" \
    -ov -format UDZO \
    "$DMG_DIR/$DMG_NAME"

if [ -f "$DMG_DIR/$DMG_NAME" ]; then
    echo "✅ DMG 创建成功"
    echo ""
    echo "=========================================="
    echo "🎉 打包完成！"
    echo "=========================================="
    echo "📍 .app 文件: $PROJECT_DIR/dist/Claude Web Chat.app"
    echo "📍 DMG 文件: $DMG_DIR/$DMG_NAME"
    echo ""
    echo "安装方法："
    echo "  1. 双击 $DMG_NAME 打开"
    echo "  2. 将 Claude Web Chat 拖到 Applications 文件夹"
    echo "=========================================="
else
    echo "❌ DMG 创建失败"
    exit 1
fi