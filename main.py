"""
Claude Web 交互服务 - 本地 CLI 版本
通过调用本地 claude 命令实现交互
"""
import os
import json
import asyncio
import shlex
import threading
import time
import base64
import tempfile
import uuid
from typing import AsyncGenerator
from contextlib import asynccontextmanager
from collections import deque

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.responses import StreamingResponse, HTMLResponse, FileResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

# PPT 生成模块
import ppt_generator
from ppt_generator import (
    PPTSession, PPTOutline, SlideContent,
    get_or_create_ppt_session, delete_ppt_session,
    create_ppt_file, parse_outline_from_ai_response,
    parse_slide_content_from_ai_response, PPT_STORAGE_DIR
)

# 配置
CLAUDE_CMD = "claude"


def _get_common_bin_dirs():
    """返回常见的 node/claude 可执行文件目录列表"""
    import glob
    home = os.path.expanduser("~")
    dirs = []
    # nvm 安装（各版本，新版本优先）
    dirs.extend(sorted(glob.glob(os.path.join(home, ".nvm/versions/node/*/bin")), reverse=True))
    # fnm
    dirs.extend(sorted(glob.glob(os.path.join(home, ".fnm/node-versions/*/installation/bin")), reverse=True))
    # volta
    dirs.append(os.path.join(home, ".volta/bin"))
    # 全局 npm
    dirs.append(os.path.join(home, ".npm-global/bin"))
    # homebrew (Apple Silicon)
    dirs.append("/opt/homebrew/bin")
    # homebrew (Intel)
    dirs.append("/usr/local/bin")
    return [d for d in dirs if os.path.isdir(d)]


def find_claude_cmd():
    """
    查找 claude 命令的完整路径。
    macOS .app 启动时不会加载 shell profile，nvm/homebrew 等路径不在 PATH 中，
    需要主动搜索常见安装位置。
    """
    import shutil

    # 先检查 PATH 里是否已经有
    found = shutil.which("claude")
    if found:
        return found

    for bin_dir in _get_common_bin_dirs():
        candidate = os.path.join(bin_dir, "claude")
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate

    # 都找不到，返回默认值让后续报出明确错误
    return "claude"


def ensure_node_in_path(claude_path: str, env: dict):
    """
    确保 node 在子进程 PATH 中。
    claude 是 #!/usr/bin/env node 脚本，需要 node 可被找到。
    claude 和 node 可能不在同一目录（如 claude 通过 npm global 安装在 /opt/homebrew/.npm-global/bin/，
    而 node 在 ~/.nvm/versions/node/v22/bin/）。
    """
    import shutil

    current_path = env.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin")

    # 先加入 claude 所在目录
    claude_bin_dir = os.path.dirname(os.path.abspath(claude_path))
    if claude_bin_dir and claude_bin_dir not in current_path:
        current_path = claude_bin_dir + ":" + current_path

    # 如果 claude 是 symlink，也加入 symlink 目标所在目录
    try:
        real_claude = os.path.realpath(claude_path)
        real_bin_dir = os.path.dirname(real_claude)
        if real_bin_dir and real_bin_dir not in current_path:
            current_path = real_bin_dir + ":" + current_path
    except OSError:
        pass

    # 检查 node 是否已经在 PATH 中可找到
    env["PATH"] = current_path
    if shutil.which("node", path=current_path):
        return

    # node 不在 PATH 中，搜索常见位置
    for bin_dir in _get_common_bin_dirs():
        node_path = os.path.join(bin_dir, "node")
        if os.path.isfile(node_path) and os.access(node_path, os.X_OK):
            env["PATH"] = bin_dir + ":" + current_path
            print(f"📍 找到 node: {node_path}")
            return


# 启动时查找一次
CLAUDE_CMD = find_claude_cmd()

# 存储会话历史 (生产环境应使用 Redis/数据库)
sessions = {}

# 存储会话工作目录
session_cwd = {}

# 路径配置：区分资源目录（只读）和数据目录（可写）
# 打包模式下 app.py 会设置这两个环境变量
APP_DIR = os.environ.get('CLAUDE_WEB_APP_DIR', os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.environ.get('CLAUDE_WEB_DATA_DIR', os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CWD = os.path.expanduser('~')

# 存储会话日志队列 (最多保留 1000 条)
session_logs = {}
MAX_LOG_ENTRIES = 1000

# 图片存储目录（可写）
IMAGES_DIR = os.path.join(DATA_DIR, "temp_images")
os.makedirs(IMAGES_DIR, exist_ok=True)

# 模型配置文件路径（可写）
MODELS_CONFIG_PATH = os.path.join(DATA_DIR, "models.json")

# 会话配置存储目录（可写）
SESSIONS_CONFIG_DIR = os.path.join(DATA_DIR, "data", "sessions")
os.makedirs(SESSIONS_CONFIG_DIR, exist_ok=True)

# 会话图片映射
session_images = {}

# 权限请求存储
permission_requests = {}  # session_id -> {request_id: request_data}
permission_responses = {}  # session_id -> {request_id: response}

# WebSocket 连接管理
class LogConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, list[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, session_id: str):
        await websocket.accept()
        if session_id not in self.active_connections:
            self.active_connections[session_id] = []
        self.active_connections[session_id].append(websocket)

    def disconnect(self, websocket: WebSocket, session_id: str):
        if session_id in self.active_connections:
            if websocket in self.active_connections[session_id]:
                self.active_connections[session_id].remove(websocket)
            if not self.active_connections[session_id]:
                del self.active_connections[session_id]

    async def broadcast(self, session_id: str, message: dict):
        if session_id in self.active_connections:
            disconnected = []
            for connection in self.active_connections[session_id]:
                try:
                    await connection.send_json(message)
                except:
                    disconnected.append(connection)
            # 清理断开连接
            for conn in disconnected:
                self.active_connections[session_id].remove(conn)

log_manager = LogConnectionManager()


def load_models_config() -> dict:
    """加载模型配置"""
    try:
        if os.path.exists(MODELS_CONFIG_PATH):
            with open(MODELS_CONFIG_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        print(f"加载模型配置失败: {e}")
    # 返回默认配置
    return {
        "models": [
            {"id": "claude-opus-4-6", "name": "Claude Opus 4.6", "description": "最强推理能力", "tier": "opus"},
            {"id": "claude-sonnet-4-6", "name": "Claude Sonnet 4.6", "description": "平衡性能与速度", "tier": "sonnet"},
            {"id": "claude-haiku-4-5-20251001", "name": "Claude Haiku 4.5", "description": "快速响应", "tier": "haiku"}
        ],
        "default_model": "claude-sonnet-4-6"
    }


def save_models_config(config: dict) -> bool:
    """保存模型配置到 models.json"""
    try:
        with open(MODELS_CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"保存模型配置失败: {e}")
        return False


def get_session_config_path(session_id: str) -> str:
    """获取会话配置文件路径"""
    return os.path.join(SESSIONS_CONFIG_DIR, f"{session_id}.json")


def load_session_config(session_id: str) -> dict:
    """加载会话配置"""
    config_path = get_session_config_path(session_id)
    try:
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        print(f"加载会话配置失败: {e}")
    # 返回默认配置
    models_config = load_models_config()
    return {"model": models_config.get("default_model", "claude-sonnet-4-6")}


def save_session_config(session_id: str, config: dict):
    """保存会话配置"""
    config_path = get_session_config_path(session_id)
    try:
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"保存会话配置失败: {e}")


def add_log_entry(session_id: str, log_type: str, message: str, metadata: dict = None):
    """添加日志条目"""
    if session_id not in session_logs:
        session_logs[session_id] = deque(maxlen=MAX_LOG_ENTRIES)

    log_entry = {
        "timestamp": time.time(),
        "type": log_type,
        "message": message,
        "metadata": metadata or {}
    }
    session_logs[session_id].append(log_entry)

    # 异步广播到 WebSocket 连接
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(log_manager.broadcast(session_id, log_entry))
    except RuntimeError:
        # 没有运行的事件循环，忽略广播
        pass


class ChatRequest(BaseModel):
    session_id: str
    message: str
    agent: str = None
    allowed_tools: list = None
    cwd: str = None
    images: list = None  # 图片路径列表
    model: str = None  # 模型选择
    permission_mode: str = "auto"  # 权限模式: auto, acceptEdits, safe


class ImageUploadRequest(BaseModel):
    session_id: str
    image_data: str  # base64 编码的图片数据
    filename: str = None


class PermissionResponseRequest(BaseModel):
    session_id: str
    request_id: str
    approved: bool
    message: str = None  # 可选的拒绝原因


# 可用工具列表
AVAILABLE_TOOLS = [
    {"id": "Bash", "name": "Bash", "description": "执行 bash 命令"},
    {"id": "Edit", "name": "Edit", "description": "编辑文件"},
    {"id": "Read", "name": "Read", "description": "读取文件"},
    {"id": "Write", "name": "Write", "description": "创建文件"},
    {"id": "Glob", "name": "Glob", "description": "文件搜索"},
    {"id": "Grep", "name": "Grep", "description": "文本搜索"},
    {"id": "LS", "name": "LS", "description": "目录列表"},
    {"id": "Task", "name": "Task", "description": "创建子任务"},
    {"id": "WebFetch", "name": "WebFetch", "description": "获取网页内容"},
    {"id": "WebSearch", "name": "WebSearch", "description": "搜索网络"},
]

# 内置 Agents
BUILTIN_AGENTS = [
    {"id": "default", "name": "默认助手", "description": "通用助手，适合大多数任务"},
    {"id": "code-reviewer", "name": "代码审查", "description": "专注代码审查和质量分析"},
    {"id": "test-writer", "name": "测试编写", "description": "帮助编写单元测试和测试用例"},
    {"id": "architect", "name": "架构设计", "description": "专注系统架构和设计模式"},
]

# 自定义 Agents 存储
custom_agents = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    print("🚀 Claude Web 服务启动 (本地 CLI 模式)")
    print(f"📍 Claude 命令路径: {CLAUDE_CMD}")

    # 构建包含 node 路径的环境
    check_env = os.environ.copy()
    ensure_node_in_path(CLAUDE_CMD, check_env)

    # 检查 claude 命令是否可用
    try:
        process = await asyncio.create_subprocess_exec(
            CLAUDE_CMD, "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=check_env,
        )
        stdout, _ = await process.communicate()
        if process.returncode == 0:
            print(f"✅ {CLAUDE_CMD} 命令已就绪 ({stdout.decode().strip()})")
        else:
            print(f"⚠️  警告: {CLAUDE_CMD} 命令可能不可用")
    except FileNotFoundError:
        print(f"❌ 错误: 未找到 {CLAUDE_CMD} 命令，请确保 Claude Code 已安装")
    yield
    print("🛑 服务关闭")


app = FastAPI(title="Claude Web Chat (本地)", lifespan=lifespan)
templates = Jinja2Templates(directory=os.path.join(APP_DIR, "templates"))


def get_or_create_session(session_id: str) -> list:
    """获取或创建会话历史"""
    if session_id not in sessions:
        sessions[session_id] = []
    return sessions[session_id]


def build_prompt(history: list, new_message: str) -> str:
    """
    构建发送给 claude 的 prompt
    将对话历史格式化为上下文
    """
    if not history:
        return new_message

    parts = []
    for msg in history:
        role = "用户" if msg["role"] == "user" else "助手"
        parts.append(f"{role}: {msg['content']}")

    parts.append(f"用户: {new_message}")
    parts.append("助手: ")

    return "\n\n".join(parts)


async def read_stream(stream, session_id: str, stream_name: str, output_queue: asyncio.Queue, done_event: asyncio.Event):
    """读取子进程输出流并放入队列，同时记录日志"""
    buffer = b""
    try:
        while True:
            try:
                # 使用 read 而不是 readline 来避免行长度限制
                chunk = await stream.read(8192)
                if not chunk:
                    # 如果还有缓冲数据，处理它
                    if buffer:
                        text = buffer.decode('utf-8', errors='replace')
                        if text.strip():
                            add_log_entry(session_id, "process_output", text.rstrip(), {"stream": stream_name})
                            await output_queue.put((stream_name, text))
                    break

                buffer += chunk

                # 按换行符分割，处理完整的行
                while b'\n' in buffer:
                    line, buffer = buffer.split(b'\n', 1)
                    text = line.decode('utf-8', errors='replace')
                    if text.strip():
                        add_log_entry(session_id, "process_output", text.rstrip(), {"stream": stream_name})
                        await output_queue.put((stream_name, text + '\n'))

            except Exception as e:
                add_log_entry(session_id, "error", f"读取{stream_name}失败: {str(e)}")
                break
    finally:
        done_event.set()  # 标记此流已结束


async def stream_claude_response(
    prompt: str,
    session_id: str,
    agent: str = None,
    allowed_tools: list = None,
    cwd: str = None,
    images: list = None,
    model: str = None,
    permission_mode: str = "auto"
) -> AsyncGenerator[str, None]:
    """
    流式获取 Claude CLI 响应
    使用纯文本输出，按行读取模拟流式效果
    支持 Agent、工具权限控制、工作目录、图片、模型选择和权限模式
    """
    # 清除 CLAUDECODE 环境变量以绕过嵌套会话检查
    env = os.environ.copy()
    # 完全删除这些变量
    env.pop('CLAUDECODE', None)
    env.pop('CLAUDE_SESSION_ID', None)
    # 确保不会被子进程继承
    if 'CLAUDECODE' in env:
        del env['CLAUDECODE']

    # 确保 claude 所在目录的 node 在 PATH 中
    ensure_node_in_path(CLAUDE_CMD, env)

    # 从 models.json 读取模型对应的 API key 和 URL，注入到子进程环境变量
    if model:
        models_config = load_models_config()
        for m in models_config.get("models", []):
            if m["id"] == model:
                if m.get("api_name"):
                    env["ANTHROPIC_API_KEY"] = m["api_name"]
                    add_log_entry(session_id, "info", f"使用模型 {model} 的 API Key: {m['api_name'][:8]}...")
                if m.get("api_key"):
                    env["ANTHROPIC_API_KEY"] = m["api_key"]
                    add_log_entry(session_id, "info", f"使用模型 {model} 的 API Key: {m['api_key'][:8]}...")
                if m.get("url"):
                    env["ANTHROPIC_BASE_URL"] = m["url"]
                    add_log_entry(session_id, "info", f"使用模型 {model} 的 Base URL: {m['url']}")
                break

    # 记录启动日志
    add_log_entry(session_id, "info", "开始调用 Claude CLI", {
        "agent": agent or "default",
        "allowed_tools": allowed_tools,
        "cwd": cwd or DEFAULT_CWD
    })

    # 判断是否有图片需要处理
    has_images = images and len(images) > 0

    prompt_file = None
    try:
        if has_images:
            # 使用 stream-json 格式发送多模态消息（文本 + 图片）
            content_blocks = []

            # 添加文本内容（图片模式下必须有文本块）
            if prompt:
                content_blocks.append({"type": "text", "text": prompt})
            else:
                content_blocks.append({"type": "text", "text": "请分析这张图片"})

            # 添加图片内容块
            for img_path in images:
                if os.path.exists(img_path):
                    try:
                        with open(img_path, 'rb') as img_file:
                            img_data = img_file.read()
                            img_base64 = base64.b64encode(img_data).decode('utf-8')

                        ext = os.path.splitext(img_path)[1].lower()
                        mime_type = "image/png"
                        if ext in ['.jpg', '.jpeg']:
                            mime_type = "image/jpeg"
                        elif ext == '.gif':
                            mime_type = "image/gif"
                        elif ext == '.webp':
                            mime_type = "image/webp"

                        content_blocks.append({
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": mime_type,
                                "data": img_base64
                            }
                        })
                        add_log_entry(session_id, "info", f"已添加图片到消息: {os.path.basename(img_path)}")
                    except Exception as e:
                        add_log_entry(session_id, "warning", f"读取图片失败 {img_path}: {str(e)}")

            # 构建 stream-json 格式的消息
            # CLI 期望格式: {"type":"user","message":{"role":"user","content":[...]}}
            stream_message = json.dumps({
                "type": "user",
                "message": {
                    "role": "user",
                    "content": content_blocks
                }
            }, ensure_ascii=False)

            prompt_file = tempfile.NamedTemporaryFile(
                mode='w', suffix='.json', prefix='claude_prompt_',
                dir=DATA_DIR, delete=False, encoding='utf-8'
            )
            prompt_file.write(stream_message + "\n")
            prompt_file.close()
            add_log_entry(session_id, "info", f"使用 stream-json 格式发送 {len(images)} 张图片")
        else:
            # 无图片时使用原始文本格式
            prompt_file = tempfile.NamedTemporaryFile(
                mode='w', suffix='.txt', prefix='claude_prompt_',
                dir=DATA_DIR, delete=False, encoding='utf-8'
            )
            prompt_file.write(prompt)
            prompt_file.close()

        # 构建命令参数
        # 所有模式统一使用 --verbose --output-format stream-json
        # (--print 模式下 --output-format stream-json 要求 --verbose)
        # (--input-format stream-json 要求 --output-format stream-json)
        cmd_args = [
            CLAUDE_CMD,
            "-p",  # --print 的简写
            "--verbose",
            "--output-format", "stream-json",
        ]

        if has_images:
            # 图片模式：额外需要 stream-json 输入格式
            cmd_args.extend(["--input-format", "stream-json"])

        # 添加 Agent 参数
        if agent and agent != "default":
            cmd_args.extend(["--agent", agent])

        # 添加工具权限参数
        if allowed_tools:
            tools_str = " ".join(allowed_tools)
            cmd_args.extend(["--allowed-tools", tools_str])

        # 添加模型参数
        if model:
            cmd_args.extend(["--model", model])

        # 根据权限模式添加参数
        # auto: 自动批准所有操作（使用 dangerously-skip-permissions）
        # acceptEdits: 自动批准文件编辑，其他操作需要确认
        # safe: 所有操作都需要确认
        if permission_mode == "auto":
            cmd_args.append("--dangerously-skip-permissions")
        elif permission_mode == "acceptEdits":
            cmd_args.extend(["--permission-mode", "acceptEdits"])
        # safe 模式不需要额外参数，使用默认行为

        # 添加工作目录参数
        if cwd and cwd != DEFAULT_CWD:
            cmd_args.extend(["--cwd", cwd])

        cmd_str = " ".join(shlex.quote(str(arg)) for arg in cmd_args)
        add_log_entry(session_id, "command", f"执行命令: {cmd_str}")

        # 通过 shell 管道将 prompt 文件内容传给 claude stdin
        # 使用 shell=True 以确保 cat file | claude 的管道可靠工作
        shell_cmd = f"cat {shlex.quote(prompt_file.name)} | {cmd_str}"

        process = await asyncio.create_subprocess_shell(
            shell_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            cwd=cwd if cwd else DEFAULT_CWD,
        )

        add_log_entry(session_id, "process", f"子进程已启动，PID: {process.pid}")

        # 记录完整的 prompt
        actual_length = os.path.getsize(prompt_file.name) if os.path.exists(prompt_file.name) else len(prompt)
        add_log_entry(session_id, "prompt", f"发送 Prompt ({actual_length} 字符{'，含图片数据' if has_images else ''})", {
            "content": prompt if not has_images else f"[stream-json 多模态消息，文本: {prompt or '(无)'}，图片: {len(images)}张]",
            "full_length": actual_length,
            "model": model,
            "agent": agent or "default",
            "permission_mode": permission_mode,
            "cwd": cwd or DEFAULT_CWD
        })

        # 创建队列和结束事件
        output_queue = asyncio.Queue()
        stdout_done = asyncio.Event()
        stderr_done = asyncio.Event()

        # 启动读取任务
        stdout_task = asyncio.create_task(read_stream(process.stdout, session_id, "stdout", output_queue, stdout_done))
        stderr_task = asyncio.create_task(read_stream(process.stderr, session_id, "stderr", output_queue, stderr_done))

        # 等待所有流结束
        active_streams = 2
        consecutive_timeouts = 0
        max_consecutive_timeouts = 300  # 允许最多 30 秒的连续超时（用于长时间工具执行）

        while active_streams > 0:
            try:
                # 设置超时以便检查流是否结束
                stream_name, text = await asyncio.wait_for(output_queue.get(), timeout=0.1)
                consecutive_timeouts = 0  # 重置超时计数

                if stream_name == "stdout":
                    # 处理 stream-json 格式输出（文本和图片模式统一）
                    text = text.strip()
                    if text:
                        newline = '\n'
                        for line in text.split(newline):
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                data = json.loads(line)
                                if isinstance(data, dict):
                                    msg_type = data.get('type')
                                    if msg_type == 'system':
                                        # tools 可能是字符串列表 ["Task","Bash",...] 或对象列表
                                        raw_tools = data.get('tools', [])
                                        tool_names = [t if isinstance(t, str) else t.get('name', '') for t in raw_tools]
                                        yield f"data: {json.dumps({'type': 'system', 'model': data.get('model', ''), 'tools': tool_names}, ensure_ascii=False)}\n\n"
                                    elif msg_type == 'assistant':
                                        msg = data.get('message', {})
                                        contents = msg.get('content', [])
                                        if isinstance(contents, list):
                                            for item in contents:
                                                if item.get('type') == 'text':
                                                    yield f"data: {json.dumps({'type': 'content', 'text': item.get('text', '')}, ensure_ascii=False)}\n\n"
                                                elif item.get('type') == 'tool_use':
                                                    yield f"data: {json.dumps({'type': 'tool_call', 'name': item.get('name', ''), 'input': item.get('input', {}), 'id': item.get('id', '')}, ensure_ascii=False)}\n\n"
                                    elif msg_type == 'user':
                                        msg = data.get('message', {})
                                        contents = msg.get('content', [])
                                        tool_use_result = data.get('tool_use_result', {})
                                        if isinstance(contents, list):
                                            for item in contents:
                                                if item.get('type') == 'tool_result':
                                                    content = item.get('content', '')
                                                    if isinstance(content, list):
                                                        content = '\n'.join(
                                                            c.get('text', '') for c in content
                                                            if isinstance(c, dict) and c.get('type') == 'text'
                                                        )
                                                    result_data = {
                                                        'type': 'tool_result',
                                                        'content': content,
                                                        'tool_use_id': item.get('tool_use_id', ''),
                                                    }
                                                    if tool_use_result:
                                                        result_data['summary'] = {
                                                            k: v for k, v in tool_use_result.items()
                                                            if k != 'content'
                                                        }
                                                    yield f"data: {json.dumps(result_data, ensure_ascii=False)}\n\n"
                                    elif msg_type == 'result':
                                        yield f"data: {json.dumps({'type': 'result', 'cost': data.get('total_cost_usd'), 'duration': data.get('duration_ms')}, ensure_ascii=False)}\n\n"
                                else:
                                    # 非 dict JSON，当作普通文本
                                    yield f"data: {json.dumps({'type': 'content', 'text': line + newline}, ensure_ascii=False)}\n\n"
                            except json.JSONDecodeError:
                                # 不是 JSON，当作普通文本
                                yield f"data: {json.dumps({'type': 'content', 'text': line + newline}, ensure_ascii=False)}\n\n"
                elif stream_name == "stderr":
                    # stderr 可能包含有用的过程信息
                    if text.strip():
                        yield f"data: {json.dumps({'type': 'process', 'text': text}, ensure_ascii=False)}\n\n"
            except asyncio.TimeoutError:
                consecutive_timeouts += 1

                # 只有在进程已经结束且连续超时多次后才认为流结束
                if process.returncode is not None:
                    # 进程已结束，检查流是否真的结束
                    if stdout_done.is_set() and stderr_done.is_set():
                        break
                    if consecutive_timeouts >= max_consecutive_timeouts:
                        add_log_entry(session_id, "warning", "流读取超时，强制结束")
                        break
                elif consecutive_timeouts >= max_consecutive_timeouts:
                    # 进程还在运行但超时太久，继续等待
                    consecutive_timeouts = 0  # 重置计数继续等待

        # 等待读取任务完成
        await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)

        # 等待进程结束
        await process.wait()
        add_log_entry(session_id, "process", f"子进程已结束，返回码: {process.returncode}")

        # 检查错误
        if process.returncode != 0:
            add_log_entry(session_id, "error", f"进程异常退出，返回码: {process.returncode}")
            yield f"data: {json.dumps({'type': 'error', 'message': f'进程返回码: {process.returncode}'}, ensure_ascii=False)}\n\n"
        else:
            add_log_entry(session_id, "info", "处理完成")
            yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"

    except FileNotFoundError as e:
        error_msg = f'未找到 {CLAUDE_CMD} 命令，请确保 Claude Code 已安装'
        add_log_entry(session_id, "error", error_msg)
        yield f"data: {json.dumps({'type': 'error', 'message': error_msg}, ensure_ascii=False)}\n\n"
    except Exception as e:
        add_log_entry(session_id, "error", f"异常: {str(e)}")
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
    finally:
        # 清理临时 prompt 文件
        if prompt_file and os.path.exists(prompt_file.name):
            try:
                os.unlink(prompt_file.name)
            except OSError:
                pass


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """首页 - 聊天界面"""
    return templates.TemplateResponse("chat.html", {"request": request})


@app.post("/api/chat")
async def chat(request: ChatRequest):
    """
    聊天接口 - 流式响应
    调用本地 claude 命令获取回复
    """
    # 获取会话历史
    history = get_or_create_session(request.session_id)

    # 构建包含上下文的 prompt
    prompt = build_prompt(history, request.message)

    print(f"📝 收到消息: {request.message[:50]}...")

    async def generate():
        assistant_content = ""

        async for chunk in stream_claude_response(
            prompt,
            session_id=request.session_id,
            agent=request.agent,
            allowed_tools=request.allowed_tools,
            cwd=request.cwd,
            images=request.images,
            model=request.model,
            permission_mode=request.permission_mode
        ):
            # 解析 chunk 中返回的数据
            try:
                data = json.loads(chunk[6:])  # 去掉 "data: " 前缀
                if data.get('type') == 'content':
                    assistant_content += data.get('text', '')
            except:
                pass
            yield chunk

        # 记录完整的 response
        add_log_entry(request.session_id, "response", f"收到 Response ({len(assistant_content)} 字符)", {
            "content": assistant_content,
            "full_length": len(assistant_content),
            "model": request.model,
            "agent": request.agent or "default"
        })

        # 保存对话历史
        user_message = {"role": "user", "content": request.message}
        if request.images and len(request.images) > 0:
            user_message["images"] = request.images
        history.append(user_message)
        history.append({"role": "assistant", "content": assistant_content})

        # 限制历史长度
        if len(history) > 20:
            sessions[request.session_id] = history[-20:]

        print(f"✅ 响应完成，长度: {len(assistant_content)}, agent: {request.agent or 'default'}, tools: {request.allowed_tools or 'all'}")

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@app.post("/api/clear")
async def clear_session(request: Request):
    """清除会话历史"""
    data = await request.json()
    session_id = data.get("session_id")
    if session_id in sessions:
        del sessions[session_id]
    return {"status": "ok"}


@app.get("/api/status")
async def get_status():
    """获取服务状态"""
    return {
        "mode": "local-cli",
        "command": CLAUDE_CMD,
    }


@app.get("/api/tools")
async def get_tools():
    """获取可用工具列表"""
    return {
        "tools": AVAILABLE_TOOLS,
        "readonly_preset": ["Read", "Glob", "Grep", "LS"],
    }


@app.get("/api/agents")
async def get_agents():
    """获取可用 Agent 列表"""
    all_agents = BUILTIN_AGENTS + [
        {"id": k, "name": v["name"], "description": v["description"]}
        for k, v in custom_agents.items()
    ]
    return {"agents": all_agents}


@app.post("/api/agents")
async def create_agent(request: Request):
    """添加自定义 Agent"""
    data = await request.json()
    agent_id = data.get("id")
    name = data.get("name")
    description = data.get("description")

    if not agent_id or not name:
        return {"status": "error", "message": "id and name are required"}

    custom_agents[agent_id] = {
        "name": name,
        "description": description or "",
    }
    return {"status": "ok", "agent": {"id": agent_id, "name": name, "description": description}}


@app.get("/api/models")
async def get_models():
    """获取可用模型列表"""
    config = load_models_config()
    return {
        "models": config.get("models", []),
        "default_model": config.get("default_model")
    }


@app.post("/api/models")
async def save_models(request: Request):
    """保存模型配置"""
    data = await request.json()
    models = data.get("models", [])
    default_model = data.get("default_model")

    # 验证
    if not models:
        return {"status": "error", "message": "models 不能为空"}

    model_ids = [m.get("id") for m in models]
    if default_model and default_model not in model_ids:
        return {"status": "error", "message": f"默认模型 {default_model} 不在模型列表中"}

    # 如果没有指定默认模型，使用第一个
    if not default_model and models:
        default_model = models[0].get("id")

    config = {
        "models": models,
        "default_model": default_model
    }

    if save_models_config(config):
        return {"status": "ok", "message": "模型配置已保存"}
    else:
        return {"status": "error", "message": "保存失败"}


@app.get("/api/session/{session_id}/model")
async def get_session_model(session_id: str):
    """获取会话的模型配置"""
    config = load_session_config(session_id)
    models_config = load_models_config()
    return {
        "status": "ok",
        "model": config.get("model", models_config.get("default_model"))
    }


@app.post("/api/session/{session_id}/model")
async def set_session_model(session_id: str, request: Request):
    """设置会话的模型配置"""
    data = await request.json()
    model_id = data.get("model")

    if not model_id:
        return {"status": "error", "message": "model is required"}

    # 验证模型是否存在
    models_config = load_models_config()
    valid_models = [m["id"] for m in models_config.get("models", [])]
    if model_id not in valid_models:
        return {"status": "error", "message": f"无效的模型: {model_id}"}

    # 加载并更新会话配置
    config = load_session_config(session_id)
    config["model"] = model_id
    save_session_config(session_id, config)

    add_log_entry(session_id, "system", f"模型切换到: {model_id}")

    return {
        "status": "ok",
        "model": model_id
    }


@app.get("/api/cwd")
async def get_cwd(session_id: str = None):
    """获取当前工作目录"""
    if session_id and session_id in session_cwd:
        cwd = session_cwd[session_id]
    else:
        cwd = DEFAULT_CWD

    # 验证目录是否存在
    if not os.path.exists(cwd):
        cwd = DEFAULT_CWD
        if session_id:
            session_cwd[session_id] = cwd

    return {
        "cwd": cwd,
        "default_cwd": DEFAULT_CWD,
        "exists": os.path.exists(cwd),
        "is_dir": os.path.isdir(cwd) if os.path.exists(cwd) else False,
    }


@app.post("/api/cwd")
async def set_cwd(request: Request):
    """设置工作目录"""
    data = await request.json()
    session_id = data.get("session_id")
    new_cwd = data.get("cwd")

    if not session_id:
        return {"status": "error", "message": "session_id is required"}

    if not new_cwd:
        return {"status": "error", "message": "cwd is required"}

    # 展开用户主目录
    new_cwd = os.path.expanduser(new_cwd)

    # 验证目录是否存在
    if not os.path.exists(new_cwd):
        return {"status": "error", "message": f"目录不存在: {new_cwd}"}

    if not os.path.isdir(new_cwd):
        return {"status": "error", "message": f"路径不是目录: {new_cwd}"}

    # 转换为绝对路径
    new_cwd = os.path.abspath(new_cwd)

    # 保存到会话
    session_cwd[session_id] = new_cwd

    # 记录日志
    add_log_entry(session_id, "system", f"工作目录切换到: {new_cwd}")

    return {
        "status": "ok",
        "cwd": new_cwd,
    }


@app.post("/api/list-files")
async def list_files(request: Request):
    """列出目录文件结构"""
    data = await request.json()
    session_id = data.get("session_id")
    path = data.get("path", ".")
    depth = data.get("depth", 2)

    # 如果有会话工作目录，使用它
    if session_id and session_id in session_cwd:
        base_path = session_cwd[session_id]
    else:
        base_path = DEFAULT_CWD

    # 展开路径
    if path.startswith("~"):
        path = os.path.expanduser(path)
    elif not os.path.isabs(path):
        path = os.path.join(base_path, path)

    path = os.path.abspath(path)

    # 安全检查：确保在允许的范围内
    if not os.path.exists(path):
        return {"status": "error", "message": f"路径不存在: {path}"}

    if not os.path.isdir(path):
        return {"status": "error", "message": f"路径不是目录: {path}"}

    add_log_entry(session_id or "unknown", "info", f"列出目录: {path}, depth={depth}")

    def build_tree(dir_path, current_depth=0):
        """递归构建目录树"""
        if current_depth > depth:
            return []

        items = []
        try:
            entries = sorted(os.listdir(dir_path))
            # 优先列出目录，然后是文件
            dirs = [e for e in entries if os.path.isdir(os.path.join(dir_path, e))]
            files = [e for e in entries if os.path.isfile(os.path.join(dir_path, e))]

            for entry in dirs:
                # 跳过隐藏目录和常见忽略目录
                if entry.startswith('.') or entry in ['node_modules', '__pycache__', 'venv', '.git', 'dist', 'build']:
                    continue
                full_path = os.path.join(dir_path, entry)
                children = build_tree(full_path, current_depth + 1) if current_depth < depth else []
                items.append({
                    "name": entry,
                    "is_dir": True,
                    "path": full_path,
                    "children": children
                })

            for entry in files:
                # 跳过隐藏文件和大文件
                if entry.startswith('.'):
                    continue
                full_path = os.path.join(dir_path, entry)
                try:
                    size = os.path.getsize(full_path)
                    # 跳过大于1MB的文件
                    if size > 1024 * 1024:
                        continue
                except:
                    pass

                items.append({
                    "name": entry,
                    "is_dir": False,
                    "path": full_path
                })
        except PermissionError:
            pass

        return items

    try:
        tree = build_tree(path)
        return {
            "status": "ok",
            "path": path,
            "files": tree
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/read-file")
async def read_file(request: Request):
    """读取文件内容"""
    data = await request.json()
    session_id = data.get("session_id")
    file_path = data.get("path")

    if not file_path:
        return {"status": "error", "message": "path is required"}

    # 如果有会话工作目录，使用它
    if session_id and session_id in session_cwd:
        base_path = session_cwd[session_id]
    else:
        base_path = DEFAULT_CWD

    # 展开路径
    if file_path.startswith("~"):
        file_path = os.path.expanduser(file_path)
    elif not os.path.isabs(file_path):
        file_path = os.path.join(base_path, file_path)

    file_path = os.path.abspath(file_path)

    # 安全检查
    if not os.path.exists(file_path):
        return {"status": "error", "message": f"文件不存在: {file_path}"}

    if not os.path.isfile(file_path):
        return {"status": "error", "message": f"路径不是文件: {file_path}"}

    # 检查文件大小
    try:
        size = os.path.getsize(file_path)
        if size > 1024 * 1024:  # 1MB
            return {"status": "error", "message": f"文件太大 ({size} 字节)，无法读取"}
    except Exception as e:
        return {"status": "error", "message": f"无法获取文件大小: {str(e)}"}

    try:
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()

        add_log_entry(session_id or "unknown", "info", f"读取文件: {file_path} ({len(content)} 字符)")

        return {
            "status": "ok",
            "path": file_path,
            "content": content
        }
    except Exception as e:
        return {"status": "error", "message": f"读取文件失败: {str(e)}"}


@app.get("/api/logs")
async def get_logs(session_id: str, limit: int = 100):
    """获取会话日志"""
    if session_id not in session_logs:
        return {"logs": []}

    logs = list(session_logs[session_id])[-limit:]
    return {"logs": logs}


@app.post("/api/logs/clear")
async def clear_logs(request: Request):
    """清除会话日志"""
    data = await request.json()
    session_id = data.get("session_id")

    if session_id in session_logs:
        session_logs[session_id].clear()

    return {"status": "ok"}


@app.get("/api/session/{session_id}")
async def get_session(session_id: str):
    """获取会话历史"""
    if session_id in sessions:
        return {
            "status": "ok",
            "session_id": session_id,
            "history": sessions[session_id]
        }
    return {"status": "error", "message": "Session not found"}


@app.post("/api/session/{session_id}")
async def save_session(session_id: str, request: Request):
    """保存会话历史（用于前端本地存储同步）"""
    data = await request.json()
    history = data.get("history", [])

    if history:
        sessions[session_id] = history
        return {"status": "ok", "message_count": len(history)}
    return {"status": "error", "message": "No history provided"}


@app.delete("/api/session/{session_id}")
async def delete_session(session_id: str):
    """删除会话及所有相关数据"""
    deleted_items = []

    # 删除会话历史
    if session_id in sessions:
        del sessions[session_id]
        deleted_items.append("history")

    # 删除工作目录记录
    if session_id in session_cwd:
        del session_cwd[session_id]
        deleted_items.append("cwd")

    # 删除日志
    if session_id in session_logs:
        del session_logs[session_id]
        deleted_items.append("logs")

    # 删除图片记录
    if session_id in session_images:
        # 删除图片文件
        for filepath in session_images[session_id]:
            try:
                if os.path.exists(filepath):
                    os.remove(filepath)
            except:
                pass
        del session_images[session_id]
        deleted_items.append("images")

    # 删除权限请求记录
    if session_id in permission_requests:
        del permission_requests[session_id]
        deleted_items.append("permission_requests")

    if session_id in permission_responses:
        del permission_responses[session_id]
        deleted_items.append("permission_responses")

    # 删除会话配置文件
    config_path = get_session_config_path(session_id)
    if os.path.exists(config_path):
        try:
            os.remove(config_path)
            deleted_items.append("config")
        except:
            pass

    return {
        "status": "ok",
        "deleted": deleted_items,
        "message": f"会话已删除: {', '.join(deleted_items) if deleted_items else '无数据'}"
    }


@app.websocket("/ws/logs/{session_id}")
async def websocket_logs(websocket: WebSocket, session_id: str):
    """WebSocket 实时日志流"""
    print(f"WebSocket 连接请求: session_id={session_id}")
    await log_manager.connect(websocket, session_id)
    print(f"WebSocket 已接受: session_id={session_id}")

    try:
        # 发送历史日志（限制最近50条避免过多）
        if session_id in session_logs and len(session_logs[session_id]) > 0:
            logs_to_send = list(session_logs[session_id])[-50:]
            for log in logs_to_send:
                await websocket.send_json(log)
            print(f"已发送 {len(logs_to_send)} 条历史日志")
        else:
            # 发送连接成功的确认消息
            await websocket.send_json({
                "timestamp": time.time(),
                "type": "system",
                "message": "WebSocket 连接已建立，等待新的日志...",
                "metadata": {}
            })

        add_log_entry(session_id, "system", "WebSocket 日志连接已建立")

        # 保持连接
        while True:
            try:
                # 接收心跳或命令
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                msg = json.loads(data)
                if msg.get("action") == "ping":
                    await websocket.send_json({"type": "pong", "timestamp": time.time()})
                elif msg.get("action") == "clear":
                    if session_id in session_logs:
                        session_logs[session_id].clear()
                    await websocket.send_json({"type": "cleared", "timestamp": time.time()})
            except asyncio.TimeoutError:
                # 发送心跳保持连接
                await websocket.send_json({"type": "heartbeat", "timestamp": time.time()})
    except WebSocketDisconnect:
        print(f"WebSocket 断开: session_id={session_id}")
    except Exception as e:
        print(f"WebSocket 错误: session_id={session_id}, error={e}")
    finally:
        log_manager.disconnect(websocket, session_id)


@app.post("/api/upload-image")
async def upload_image(request: ImageUploadRequest):
    """上传图片并保存到临时目录"""
    try:
        # 解码 base64 图片数据
        # 处理 data:image/png;base64, 前缀
        image_data = request.image_data
        if ',' in image_data:
            image_data = image_data.split(',')[1]

        image_bytes = base64.b64decode(image_data)

        # 检查图片大小 (限制 5MB)
        if len(image_bytes) > 5 * 1024 * 1024:
            return {"status": "error", "message": "图片太大，请压缩后重试 (最大 5MB)"}

        # 生成唯一文件名
        ext = os.path.splitext(request.filename or '.png')[1] or '.png'
        filename = f"{request.session_id}_{uuid.uuid4().hex[:8]}{ext}"
        filepath = os.path.join(IMAGES_DIR, filename)

        # 保存图片
        with open(filepath, 'wb') as f:
            f.write(image_bytes)

        # 记录到会话图片列表
        if request.session_id not in session_images:
            session_images[request.session_id] = []
        session_images[request.session_id].append(filepath)

        add_log_entry(request.session_id, "info", f"图片上传成功: {filename} ({len(image_bytes)} 字节)")

        return {
            "status": "ok",
            "filename": filename,
            "path": filepath,
            "size": len(image_bytes)
        }
    except Exception as e:
        return {"status": "error", "message": f"图片上传失败: {str(e)}"}


@app.get("/api/images/{session_id}")
async def get_session_images(session_id: str):
    """获取会话的所有图片"""
    images = session_images.get(session_id, [])
    return {
        "status": "ok",
        "images": images
    }


@app.post("/api/clear-images")
async def clear_session_images(request: Request):
    """清理会话的图片文件"""
    data = await request.json()
    session_id = data.get("session_id")

    if session_id in session_images:
        for filepath in session_images[session_id]:
            try:
                if os.path.exists(filepath):
                    os.remove(filepath)
            except:
                pass
        del session_images[session_id]

    return {"status": "ok"}


@app.get("/api/test")
async def test_claude():
    """测试 Claude CLI 是否正常工作"""
    try:
        process = await asyncio.create_subprocess_exec(
            CLAUDE_CMD,
            "--print",
            "--no-session-persistence",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        # 发送测试消息
        test_prompt = "Hello, respond with 'OK' only."
        process.stdin.write(test_prompt.encode('utf-8'))
        await process.stdin.drain()
        process.stdin.close()

        # 读取输出
        stdout, stderr = await process.communicate()

        return {
            "status": "ok" if process.returncode == 0 else "error",
            "returncode": process.returncode,
            "stdout": stdout.decode('utf-8', errors='replace')[:200],
            "stderr": stderr.decode('utf-8', errors='replace')[:200] if stderr else None,
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e),
        }


@app.get("/api/permission/{session_id}")
async def get_permission_requests(session_id: str):
    """获取会话的待处理权限请求"""
    requests = permission_requests.get(session_id, {})
    return {"requests": list(requests.values())}


@app.post("/api/permission/respond")
async def respond_to_permission(request: PermissionResponseRequest):
    """响应权限请求"""
    session_id = request.session_id
    request_id = request.request_id

    if session_id not in permission_requests:
        return {"status": "error", "message": "会话不存在"}

    if request_id not in permission_requests[session_id]:
        return {"status": "error", "message": "请求不存在"}

    # 存储响应
    if session_id not in permission_responses:
        permission_responses[session_id] = {}

    permission_responses[session_id][request_id] = {
        "approved": request.approved,
        "message": request.message
    }

    # 从待处理列表中移除
    del permission_requests[session_id][request_id]

    return {"status": "ok"}


@app.get("/api/permission/{session_id}/pending")
async def has_pending_permission(session_id: str):
    """检查是否有待处理的权限请求"""
    requests = permission_requests.get(session_id, {})
    return {"has_pending": len(requests) > 0, "count": len(requests)}


# ===================== PPT 制作功能 API =====================

class PPTSlideRequest(BaseModel):
    session_id: str
    slide_index: int
    content: dict


class PPTMessageRequest(BaseModel):
    session_id: str
    message: str


@app.post("/api/ppt/upload")
async def upload_ppt_document(file: UploadFile = File(...), session_id: str = None):
    """上传 PPT 制作的源文档"""
    if not session_id:
        return {"status": "error", "message": "session_id is required"}

    # 检查文件类型
    allowed_extensions = ['.txt', '.md', '.markdown', '.docx', '.pdf']
    ext = os.path.splitext(file.filename)[1].lower()

    if ext not in allowed_extensions:
        return {
            "status": "error",
            "message": f"不支持的文件格式: {ext}。支持: {', '.join(allowed_extensions)}"
        }

    try:
        # 创建 PPT 存储目录
        upload_dir = os.path.join(PPT_STORAGE_DIR, "uploads")
        os.makedirs(upload_dir, exist_ok=True)

        # 保存文件
        filename = f"{session_id}_{int(time.time())}{ext}"
        file_path = os.path.join(upload_dir, filename)

        with open(file_path, 'wb') as f:
            content = await file.read()
            f.write(content)

        # 创建或获取 PPT 会话
        ppt_session = get_or_create_ppt_session(session_id)
        ppt_session.source_file = file_path

        return {
            "status": "ok",
            "message": f"文件上传成功: {file.filename}",
            "filename": file.filename,
            "size": len(content)
        }

    except Exception as e:
        return {"status": "error", "message": f"上传失败: {str(e)}"}


@app.post("/api/ppt/outline")
async def generate_ppt_outline(request: Request):
    """生成 PPT 大纲"""
    data = await request.json()
    session_id = data.get("session_id")
    requirement = data.get("requirement", "")

    if not session_id:
        return {"status": "error", "message": "session_id is required"}

    ppt_session = get_or_create_ppt_session(session_id)

    # 读取源文档（如果有）
    source_text = ""
    if ppt_session.source_file and os.path.exists(ppt_session.source_file):
        try:
            source_text = ppt_generator.extract_text_from_document(ppt_session.source_file)
        except Exception as e:
            return {"status": "error", "message": f"读取源文档失败: {str(e)}"}

    # 生成 Prompt
    prompt = ppt_generator.generate_outline_prompt(source_text, requirement)

    async def generate():
        response_text = ""

        async for chunk in stream_claude_response(prompt, session_id):
            try:
                data = json.loads(chunk[6:])  # 去掉 "data: " 前缀
                if data.get("type") == "content":
                    response_text += data.get("text", "")
                elif data.get("type") == "done":
                    break
                yield chunk
            except:
                yield chunk

        # 记录完整的 response
        add_log_entry(session_id, "response", f"PPT大纲 Response ({len(response_text)} 字符)", {
            "content": response_text,
            "full_length": len(response_text)
        })

        # 解析大纲
        outline = parse_outline_from_ai_response(response_text)
        if outline:
            ppt_session.outline = outline
            ppt_session.status = "outline_generated"

            result = {
                'type': 'outline_ready',
                'outline': outline.to_dict(),
                'message': f'大纲已生成，共 {len(outline.slides)} 页'
            }
            yield f"data: {json.dumps(result, ensure_ascii=False)}\n\n"
        else:
            result = {
                'type': 'error',
                'message': '无法解析 AI 返回的大纲格式，请重试'
            }
            yield f"data: {json.dumps(result, ensure_ascii=False)}\n\n"

        yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


@app.get("/api/ppt/session/{session_id}")
async def get_ppt_session(session_id: str):
    """获取 PPT 会话状态"""
    ppt_session = get_or_create_ppt_session(session_id)
    return {
        "status": "ok",
        "ppt_session": ppt_session.to_dict()
    }


@app.delete("/api/ppt/session/{session_id}")
async def delete_ppt_session_endpoint(session_id: str):
    """删除 PPT 会话及文件"""
    delete_ppt_session(session_id)
    return {"status": "ok", "message": "PPT 会话已删除"}


@app.get("/api/ppt/slide/{session_id}/{slide_index}")
async def get_slide(session_id: str, slide_index: int):
    """获取单页幻灯片内容"""
    ppt_session = get_or_create_ppt_session(session_id)

    if slide_index < 0 or slide_index >= len(ppt_session.outline.slides):
        return {"status": "error", "message": "无效的幻灯片索引"}

    ppt_session.current_slide_index = slide_index

    return {
        "status": "ok",
        "slide_index": slide_index,
        "slide": ppt_session.outline.slides[slide_index].to_dict()
    }


@app.post("/api/ppt/slide/{session_id}/{slide_index}")
async def update_slide(session_id: str, slide_index: int, request: Request):
    """更新单页幻灯片内容"""
    data = await request.json()

    ppt_session = get_or_create_ppt_session(session_id)

    if slide_index < 0 or slide_index >= len(ppt_session.outline.slides):
        return {"status": "error", "message": "无效的幻灯片索引"}

    # 更新幻灯片内容
    slide = ppt_session.outline.slides[slide_index]
    slide.title = data.get("title", slide.title)
    slide.subtitle = data.get("subtitle", slide.subtitle)
    slide.bullets = data.get("bullets", slide.bullets)
    slide.notes = data.get("notes", slide.notes)
    slide.layout_type = data.get("layout_type", slide.layout_type)

    return {
        "status": "ok",
        "message": f"第 {slide_index + 1} 页已更新",
        "slide": slide.to_dict()
    }


@app.post("/api/ppt/slide/{session_id}/{slide_index}/enhance")
async def enhance_slide(session_id: str, slide_index: int):
    """使用 AI 完善单页内容"""
    ppt_session = get_or_create_ppt_session(session_id)

    if slide_index < 0 or slide_index >= len(ppt_session.outline.slides):
        return {"status": "error", "message": "无效的幻灯片索引"}

    # 获取源文档内容
    source_text = ""
    if ppt_session.source_file and os.path.exists(ppt_session.source_file):
        try:
            source_text = ppt_generator.extract_text_from_document(ppt_session.source_file)
        except:
            pass

    # 生成完善内容的 Prompt
    prompt = ppt_generator.generate_slide_content_prompt(
        ppt_session.outline, slide_index, source_text
    )

    async def generate():
        response_text = ""

        async for chunk in stream_claude_response(prompt, session_id):
            try:
                data = json.loads(chunk[6:])
                if data.get("type") == "content":
                    response_text += data.get("text", "")
                elif data.get("type") == "done":
                    break
                yield chunk
            except:
                yield chunk

        # 记录完整的 response
        add_log_entry(session_id, "response", f"PPT幻灯片 Response ({len(response_text)} 字符)", {
            "content": response_text,
            "full_length": len(response_text)
        })

        # 解析完善后的内容
        enhanced = parse_slide_content_from_ai_response(response_text)
        if enhanced:
            ppt_session.outline.slides[slide_index] = enhanced
            result = {
                'type': 'slide_enhanced',
                'slide_index': slide_index,
                'slide': enhanced.to_dict()
            }
            yield f"data: {json.dumps(result, ensure_ascii=False)}\n\n"

        yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


@app.post("/api/ppt/slide/{session_id}")
async def add_slide(session_id: str, request: Request):
    """添加新幻灯片"""
    data = await request.json()

    ppt_session = get_or_create_ppt_session(session_id)

    new_slide = SlideContent(
        title=data.get("title", "新页面"),
        subtitle=data.get("subtitle", ""),
        bullets=data.get("bullets", ["要点 1", "要点 2", "要点 3"]),
        layout_type=data.get("layout_type", "content")
    )

    ppt_session.outline.slides.append(new_slide)

    return {
        "status": "ok",
        "message": f"已添加第 {len(ppt_session.outline.slides)} 页",
        "slide_index": len(ppt_session.outline.slides) - 1,
        "slide": new_slide.to_dict()
    }


@app.delete("/api/ppt/slide/{session_id}/{slide_index}")
async def delete_slide(session_id: str, slide_index: int):
    """删除幻灯片"""
    ppt_session = get_or_create_ppt_session(session_id)

    if slide_index < 0 or slide_index >= len(ppt_session.outline.slides):
        return {"status": "error", "message": "无效的幻灯片索引"}

    deleted = ppt_session.outline.slides.pop(slide_index)

    # 调整当前索引
    if ppt_session.current_slide_index >= len(ppt_session.outline.slides):
        ppt_session.current_slide_index = max(0, len(ppt_session.outline.slides) - 1)

    return {
        "status": "ok",
        "message": f"第 {slide_index + 1} 页已删除",
        "deleted_slide": deleted.to_dict()
    }


@app.post("/api/ppt/finalize")
async def finalize_ppt(request: Request):
    """生成最终 PPT 文件"""
    data = await request.json()
    session_id = data.get("session_id")

    if not session_id:
        return {"status": "error", "message": "session_id is required"}

    ppt_session = get_or_create_ppt_session(session_id)

    if len(ppt_session.outline.slides) == 0:
        return {"status": "error", "message": "PPT 内容为空，请先生成大纲"}

    try:
        output_filename = f"ppt_{session_id}_{int(time.time())}.pptx"
        output_path = os.path.join(PPT_STORAGE_DIR, output_filename)

        create_ppt_file(ppt_session.outline, output_path)
        ppt_session.output_file = output_path
        ppt_session.status = "completed"

        return {
            "status": "ok",
            "message": "PPT 生成完成！",
            "filename": output_filename,
            "download_url": f"/api/ppt/download/{output_filename}",
            "slide_count": len(ppt_session.outline.slides)
        }

    except Exception as e:
        return {"status": "error", "message": f"生成 PPT 失败: {str(e)}"}


@app.get("/api/ppt/download/{filename}")
async def download_ppt(filename: str):
    """下载生成的 PPT 文件"""
    file_path = os.path.join(PPT_STORAGE_DIR, filename)

    if not os.path.exists(file_path):
        return {"status": "error", "message": "文件不存在"}

    return FileResponse(
        file_path,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation"
    )


@app.get("/api/ppt/help")
async def get_ppt_help():
    """获取 PPT 制作帮助"""
    return {
        "status": "ok",
        "help": ppt_generator.PPT_COMMAND_HELP
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
