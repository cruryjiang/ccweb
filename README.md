# Claude Web Chat

基于 Claude Code CLI 的 Web 聊天界面，提供浏览器端的 AI 对话交互体验。通过调用本地 `claude` 命令与大模型通信，支持多模型管理、流式输出、Agent 角色、PPT 生成等功能。

## 系统架构

```
浏览器 (chat.html)
  ↕ SSE / WebSocket / REST
FastAPI 后端 (main.py)
  ↕ subprocess
本地 claude CLI
```

- **后端**：Python FastAPI + Uvicorn，通过 `asyncio.create_subprocess_exec` 调用本地 `claude` CLI，以 SSE (Server-Sent Events) 流式返回结果
- **前端**：Jinja2 模板 + React 组件（渐进式迁移），导航栏和头部已组件化（React + Vite + TypeScript），使用 Lucide Icons；其余页面仍为原生 JS/CSS
- **桌面端**：PyInstaller 打包为 macOS `.app` / `.dmg`

## 功能概览

### 对话交互
- 流式输出，实时显示模型回复
- 多轮对话上下文管理，支持随时重置上下文（仅清除历史，不清屏）
- 对话历史侧边栏（新建、切换、删除历史对话，本地持久化）
- 暂停 / 继续生成
- 图片上传（支持多张，Base64 嵌入 prompt 发送给模型）
- Markdown 渲染与代码高亮
- 放大编辑模式（弹窗全屏输入长文本）

### 快捷命令
- `/brainstorm <想法>` — 头脑风暴模式，先探索设计再实现
- `/plan <任务>` — 文件规划模式，创建任务规划文档
- `/ppt <需求>` — PPT 制作模式，交互式创建演示文稿

### PPT 生成
- 通过对话描述需求，AI 自动生成大纲
- 逐页编辑幻灯片内容（标题、副标题、要点、演讲者备注）
- 支持上传 Word (.docx) / PDF 文档作为参考素材
- AI 润色增强单页内容
- 导出为 `.pptx` 文件下载

### 模型管理
- 支持配置多个模型（模型 ID、API Key、自定义 API URL、描述、等级）
- 按会话切换模型，设置默认模型
- 模型配置持久化在 `models.json`，启动时通过环境变量 `ANTHROPIC_API_KEY` / `ANTHROPIC_BASE_URL` 注入子进程

### PPT 模板管理
- 支持上传自定义 PPT 模板（`.pptx`）
- 在线搜索并下载公共模板
- 从 URL 抓取模板文件

### Agent 角色
- 内置多种 Agent：默认助手、PPT 助手、语雀助手、编码助手
- 通过下拉菜单随时切换

### 权限控制
- 三种权限模式：
  - **自动执行** — 自动批准所有操作
  - **自动编辑** — 自动批准文件编辑，其他操作需确认
  - **安全模式** — 所有操作都需要用户手动确认
- 工具权限细粒度控制（全部允许 / 只读模式 / 禁止所有 / 逐项勾选）
- 权限请求弹窗审批

### 工作目录
- 可视化目录浏览器，切换 Claude CLI 工作目录
- 支持手动输入路径或逐级点击浏览
- 文件内容在线预览

### 交互日志
- WebSocket 实时推送日志到日志面板
- 记录命令执行、进程状态、prompt 内容、响应详情、错误信息

## 前置依赖

- **Python 3.9+**
- **Node.js 18+**（用于安装 Claude CLI 及构建前端）
- **Claude Code CLI**：
  ```bash
  npm install -g @anthropic-ai/claude-code
  ```

## 快速启动

```bash
# 首次启动（自动创建虚拟环境并安装依赖）
./start.sh

# 重启服务（前台）
./restart.sh

# 后台重启
./restart-bg.sh
```

服务默认运行在 http://localhost:8000

### 手动启动

```bash
# 构建前端
cd frontend && npm install && npm run build && cd ..

# 启动后端
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### 后台模式日志

```bash
tail -f server.log
```

## 打包为 macOS 应用

```bash
./build_dmg.sh
```

产物位于 `dist/` 目录：
- `Claude Web Chat.app` — 可直接运行的 macOS 应用
- `Claude Web Chat-1.0.0.dmg` — 安装镜像

> 注意：目标机器需要安装 Claude Code CLI 才能正常使用。

## API 接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/` | GET | 聊天页面 |
| `/api/chat` | POST | 发送消息（SSE 流式响应） |
| `/api/clear` | POST | 清除会话历史 |
| `/api/status` | GET | 服务状态 |
| `/api/models` | GET | 获取模型列表 |
| `/api/models` | POST | 保存模型配置 |
| `/api/session/{id}/model` | GET/POST | 获取/设置会话模型 |
| `/api/cwd` | GET/POST | 获取/设置工作目录 |
| `/api/ls` | POST | 列出目录内容 |
| `/api/file` | POST | 读取文件内容 |
| `/api/upload-image` | POST | 上传图片 |
| `/api/ppt/*` | - | PPT 生成相关接口 |
| `/ws/logs/{id}` | WebSocket | 实时日志推送 |

## 项目结构

```
main.py              # 后端核心：API 路由、会话管理、CLI 调用
app.py               # 桌面应用入口（PyInstaller 打包用）
ppt_generator.py     # PPT 生成模块（大纲解析、幻灯片生成、模板管理）
templates/chat.html  # 前端页面（Jinja2 模板 + vanilla JS）
frontend/            # React + Vite + TypeScript 前端项目
  src/bridge.ts      #   React ↔ vanilla JS 双向通信桥梁
  src/components/    #   React 组件（LeftNav, Header）
  src/hooks/         #   自定义 Hooks（useBridge）
  vite.config.ts     #   Vite 构建配置（IIFE library 模式）
static/              # 前端构建产物（clawweb-ui.js）
models.json          # 模型配置（ID、API Key、URL、等级）
ClaudeWebChat.spec   # PyInstaller 打包配置
requirements.txt     # Python 依赖
start.sh             # 首次启动脚本（含前端构建）
restart.sh           # 前台重启脚本（含前端构建）
restart-bg.sh        # 后台重启脚本（含前端构建）
build_dmg.sh         # macOS 打包脚本
data/sessions/       # 会话配置持久化目录
data/ppt_templates/  # PPT 模板存储目录
temp_images/         # 上传图片临时存储
```

## 技术栈

- **后端**：Python 3.9 + FastAPI + Uvicorn + asyncio subprocess
- **前端**：React 19 + TypeScript + Vite（组件化部分）+ 原生 JS/CSS（渐进迁移中）
- **图标**：Lucide Icons（SVG，替代 emoji）
- **通信**：SSE（对话流式传输）+ WebSocket（日志推送）+ REST（配置管理）
- **PPT 生成**：python-pptx + python-docx + PyPDF2
- **桌面打包**：PyInstaller

## 注意事项

1. 首次使用 Claude CLI 可能需要登录授权
2. 会话对话历史存储在后端内存中，重启服务后会丢失；前端有本地 localStorage 备份
3. `models.json` 中的 API Key 以明文存储，注意保护该文件
