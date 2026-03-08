#!/bin/bash

# Claude Web Chat 重启脚本

set -e

echo "🔄 重启 Claude Web Chat 服务..."

# 查找并停止占用 8000 端口的进程
echo "📍 查找占用端口 8000 的进程..."
PIDS=$(lsof -ti :8000 2>/dev/null || true)

if [ -n "$PIDS" ]; then
    for PID in $PIDS; do
        echo "🛑 停止进程 (PID: $PID)..."
        kill "$PID" 2>/dev/null || true
    done
    sleep 2

    # 强制结束仍在运行的进程
    PIDS=$(lsof -ti :8000 2>/dev/null || true)
    if [ -n "$PIDS" ]; then
        echo "⚠️  强制终止残留进程..."
        kill -9 $PIDS 2>/dev/null || true
        sleep 1
    fi
else
    echo "ℹ️  端口 8000 未被占用"
fi

# 检查虚拟环境
if [ -d "venv" ]; then
    echo "📦 激活虚拟环境..."
    source venv/bin/activate
else
    echo "❌ 虚拟环境不存在，请先运行 ./start.sh 初始化"
    exit 1
fi

# 检查 claude 命令
if ! command -v claude &> /dev/null; then
    echo "❌ 未找到 claude 命令"
    exit 1
fi

echo "🚀 启动服务..."
echo "🌐 服务将在 http://localhost:8000 启动"
echo ""

# 启动服务
python main.py
