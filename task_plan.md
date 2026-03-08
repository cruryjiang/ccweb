# 任务计划：修复图片未随对话内容发送的问题

## 问题概述
用户上传的图片虽然在前端预览正常显示，但实际上并未以"图片"形式传递给 Claude 模型。
当前实现将图片 base64 编码后作为**纯文本**嵌入到 prompt 中，Claude CLI 不会将其解析为真正的图片。

## 排查步骤

### 步骤 1：分析前端图片上传流程 ✅
- 文件：`templates/chat.html`
- 流程：选择/粘贴图片 → base64 编码 → 上传到 `/api/upload-image` → 获取文件路径 → 发送到 `/api/chat`
- **前端逻辑正常，无问题**

### 步骤 2：分析后端图片处理流程 ✅
- 文件：`main.py`
- 流程：接收文件路径 → 读取文件 → 重新 base64 编码 → 作为文本嵌入 prompt → 管道传输到 `claude -p --verbose`
- **问题所在：base64 数据作为纯文本嵌入，CLI 无法识别为图片**

### 步骤 3：确认 Claude CLI 支持的图片输入方式 ✅
- CLI 版本：2.1.59
- 支持 `--input-format stream-json` 用于结构化 JSON 输入（支持多模态内容）
- 支持 `--output-format stream-json` 用于结构化 JSON 输出

### 步骤 4：实施修复
- 将图片发送方式从"文本嵌入"改为"stream-json 多模态消息"
- 修改 `stream_claude_response` 函数中的图片处理和命令构建逻辑
- 适配 stream-json 的输出解析（如果需要）

## 修复方案

### 方案（推荐）：使用 `--input-format stream-json`
当有图片时，将 CLI 调用改为使用 stream-json 输入格式，发送符合 Anthropic API 规范的多模态消息：
```json
{"type": "user_message", "content": [
  {"type": "text", "text": "用户消息"},
  {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "..."}}
]}
```

修改点：
1. `main.py:stream_claude_response()` - 当有图片时使用 stream-json 输入模式
2. 构建多模态 JSON 消息替代纯文本 prompt
3. 输出解析可能需要调整以适配 stream-json 格式

## 涉及的文件
1. `main.py` - 后端核心，需修改 `stream_claude_response` 函数（约 462-550 行）
2. `templates/chat.html` - 前端基本无需修改（图片上传逻辑已正常工作）
