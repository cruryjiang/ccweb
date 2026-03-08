# 显示 Claude CLI 所有中间状态（工具调用、结果等）

## 日期
2026-03-09

## 需求背景
当前 web 页面只显示最终文本结果，不显示中间状态（如工具调用名称和参数、工具返回结果、费用和耗时等）。需要让用户能看到 Claude 的完整执行过程。

## 核心思路
将 Claude CLI 的输出格式从纯文本 `--verbose` 改为 `--verbose --output-format stream-json`，获取结构化 JSON 流，前端解析并展示各类中间状态。

## Claude CLI stream-json 格式参考

### 输出格式（已测试确认，CLI v2.1.59）

```json
{"type":"system","subtype":"init","tools":["Task","Bash","Read",...],"model":"claude-opus-4-6",...}
{"type":"assistant","message":{"id":"...","type":"message","role":"assistant","content":[{"type":"text","text":"..."}],...}}
{"type":"assistant","message":{"content":[{"type":"tool_use","id":"...","name":"Grep","input":{...}}],...}}
{"type":"user","message":{"content":[{"type":"tool_result","content":"...","tool_use_id":"..."}]},"tool_use_result":{"content":"...","numFiles":0,"numLines":1}}
{"type":"result","subtype":"success","total_cost_usd":0.025,"duration_ms":11545,...}
```

### 输入格式（用于图片传递）

**正确格式**（必须有 `message` 包装和 `role` 字段）：
```json
{"type":"user","message":{"role":"user","content":[{"type":"text","text":"请分析这张图片"},{"type":"image","source":{"type":"base64","media_type":"image/png","data":"..."}}]}}
```

**错误格式**（缺少 `message` 包装，会导致 `TypeError: Cannot read properties of undefined (reading 'role')`）：
```json
{"type":"user","content":[{"type":"text","text":"请分析这张图片"},{"type":"image",...}]}
```

## CLI 标志组合约束

| 标志组合 | 是否可用 | 说明 |
|---------|---------|------|
| `-p --verbose --output-format stream-json` | **可用** | 文本模式标准组合 |
| `-p --output-format stream-json`（无 --verbose） | **不可用** | 报错: requires --verbose |
| `-p --input-format stream-json`（无 --output-format） | **不可用** | 报错: requires output-format=stream-json |
| `-p --verbose --output-format stream-json --input-format stream-json` | **可用** | 图片模式标准组合 |

## 实现方案

### 涉及文件
- `main.py` — 后端命令构建 + 输出解析（~530-670行）
- `templates/chat.html` — 前端展示（CSS ~900-1000行，JS ~3880-3970行）

### 后端 `main.py`

#### A. 命令参数构建（~530行）

两种模式统一使用 `--verbose --output-format stream-json`：

```python
cmd_args = [
    CLAUDE_CMD,
    "-p",
    "--verbose",
    "--output-format", "stream-json",
]

if has_images:
    # 图片模式：额外需要 stream-json 输入格式
    cmd_args.extend(["--input-format", "stream-json"])
```

#### B. stream-json 输入消息构建（~505行，图片模式）

```python
stream_message = json.dumps({
    "type": "user",
    "message": {
        "role": "user",
        "content": content_blocks  # 包含 text 和 image 块
    }
}, ensure_ascii=False)
```

#### C. 统一输出解析（~630行）

所有模式输出都是 stream-json 格式，用同一套解析逻辑：

```python
msg_type = data.get('type')
if msg_type == 'system':
    # tools 是字符串数组，不是对象数组
    raw_tools = data.get('tools', [])
    tool_names = [t if isinstance(t, str) else t.get('name', '') for t in raw_tools]
    # → 发送 {type:"system", model, tools}

elif msg_type == 'assistant':
    # 遍历 message.content[]
    # type=="text" → 发送 {type:"content", text}
    # type=="tool_use" → 发送 {type:"tool_call", name, input, id}

elif msg_type == 'user':
    # 遍历 message.content[]
    # type=="tool_result" → 发送 {type:"tool_result", content, tool_use_id, summary}
    # summary 来自 data.tool_use_result（numFiles, numLines 等）

elif msg_type == 'result':
    # → 发送 {type:"result", cost, duration}
```

### 前端 `templates/chat.html`

#### A. 新增 CSS 样式

- `.tool-call-params` — 工具调用关键参数摘要
- `.tool-details-toggle` / `.tool-details-full` — 可折叠详情按钮和内容区
- `.tool-result` / `.tool-result-summary` — 工具结果展示
- `.result-info` — 费用/耗时信息

#### B. 新增事件处理

| 事件类型 | 展示内容 |
|---------|---------|
| `system` | 模型名 + 可用工具数量 |
| `tool_call` | 工具名 + 关键参数摘要（pattern/file_path/command 等） + 可折叠完整 input |
| `tool_result` | 摘要信息（numFiles/numLines） + 可折叠完整内容 |
| `result` | 费用（$x.xxxx） + 耗时（x.xs） |

## 踩坑记录

### 1. stream-json 输入消息格式
- **问题**：旧代码用 `{"type":"user","content":[...]}` 格式，CLI 报 "Error parsing streaming input line"
- **根因**：CLI 尝试读取 `message.role` 但 `message` 未定义
- **修复**：改为 `{"type":"user","message":{"role":"user","content":[...]}}`
- **排查方法**：通过 `env -u CLAUDECODE` 直接运行 CLI 测试，完整 stderr 输出揭示了 `TypeError: Cannot read properties of undefined (reading 'role')`

### 2. system 消息中 tools 字段类型
- **问题**：代码用 `t.get('name', '')` 解析 tools，但实际是字符串数组
- **根因**：实际输出是 `["Task","Bash",...]`（字符串数组），不是 `[{"name":"Task"},...]`（对象数组）
- **修复**：`[t if isinstance(t, str) else t.get('name', '') for t in raw_tools]`

### 3. 在 Claude Code 内测试 CLI
- **问题**：直接运行 `claude` 命令报 "cannot be launched inside another Claude Code session"
- **解决**：`env -u CLAUDECODE` 清除环境变量后即可运行
