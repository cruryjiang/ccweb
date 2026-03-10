#!/bin/bash

# Claude Web Chat (本地 CLI 版) 启动脚本

set -e

echo "🚀 启动 Claude Web Chat (本地 CLI 版)..."

# 检查 Python
if ! command -v python3 &> /dev/null; then
    echo "❌ 请先安装 Python 3"
    exit 1
fi

# 检查 Claude CLI
if ! command -v claude &> /dev/null; then
    echo "❌ 未找到 claude 命令，请确保 Claude Code 已安装"
    echo "安装方式: npm install -g @anthropic-ai/claude-code"
    exit 1
fi

echo "✅ 检测到 Claude CLI"

# 检查 Node.js
if ! command -v node &> /dev/null; then
    echo "❌ 请先安装 Node.js (用于构建前端)"
    exit 1
fi

# 构建前端
echo "📦 构建前端..."
(cd frontend && npm install --silent && npm run build) || {
    echo "❌ 前端构建失败"
    exit 1
}
echo "✅ 前端构建完成"

# 检查虚拟环境
if [ -d "venv" ]; then
    echo "📦 激活虚拟环境..."
    source venv/bin/activate
else
    echo "📦 创建虚拟环境..."
    python3 -m venv venv
    source venv/bin/activate
    echo "📥 安装依赖..."
    pip install -r requirements.txt -q
fi

echo "🌐 服务启动成功！访问: http://localhost:8000"
echo ""

# 启动服务
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
