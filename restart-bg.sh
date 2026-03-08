#!/bin/bash

# Claude Web Chat 后台重启脚本

set -e

echo "🔄 后台重启 Claude Web Chat 服务..."

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
    source venv/bin/activate
else
    echo "❌ 虚拟环境不存在"
    exit 1
fi

# 检查 claude 命令
if ! command -v claude &> /dev/null; then
    echo "❌ 未找到 claude 命令"
    exit 1
fi

# 启动服务到后台
echo "🚀 启动服务到后台..."
nohup uvicorn main:app --host 0.0.0.0 --port 8000 > server.log 2>&1 &

# 等待服务启动
sleep 2

# 检查是否启动成功
if curl -s http://localhost:8000/api/status > /dev/null 2>&1; then
    echo "✅ 服务启动成功！"
    echo "🌐 访问: http://localhost:8000"
    echo "📝 日志: tail -f server.log"
else
    echo "⚠️  服务可能未启动成功，检查日志:"
    echo "   tail -f server.log"
fi
