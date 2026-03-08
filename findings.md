# 发现：图片未随对话发送的根本原因

## 核心问题

**图片 base64 数据被当作纯文本嵌入到 prompt 中，Claude CLI 无法将其识别为图片。**

## 详细分析

### 当前图片处理流程

```
前端                              后端                              Claude CLI
用户选择图片                       /api/upload-image
  ↓ base64编码                       ↓ 解码保存为文件
pendingImages[]                    temp_images/xxx.png
  ↓ sendMessage()                     ↓
uploadSingleImage()                返回文件路径
  ↓                                   ↓
imagePaths[]                       /api/chat 接收路径
  ↓                                   ↓
streamResponse(msg, paths)         stream_claude_response()
                                     ↓ 读取文件
                                     ↓ 重新base64编码
                                     ↓ 作为文本嵌入prompt
                                     ↓
                                   cat prompt.txt | claude -p
                                                                     ↓
                                                             CLI收到纯文本
                                                             (不是图片!)
```

### 问题代码位置

**`main.py` 第 462-492 行：**
```python
# 处理图片：如果有图片，将图片内容嵌入到 prompt 中
if images and len(images) > 0:
    image_parts = []
    image_parts.append("\n\n[附带的图片]:")
    for img_path in images:
        if os.path.exists(img_path):
            with open(img_path, 'rb') as img_file:
                img_data = img_file.read()
                img_base64 = base64.b64encode(img_data).decode('utf-8')
            # 在 prompt 中嵌入 base64 图片引用
            image_parts.append(f"\n图片 ({os.path.basename(img_path)}):")
            image_parts.append(f"data:{mime_type};base64,{img_base64}")
    prompt += "\n".join(image_parts)
```

**问题**：
1. `data:image/png;base64,iVBOR...` 是 HTML/Web 的 Data URI 格式
2. Claude CLI 的 `-p` 模式接收纯文本输入
3. CLI 将整个 base64 字符串当作普通文本传给模型
4. 模型看到的是几十万个字符的 base64 编码文本，而不是实际图片
5. 这导致上下文被大量无用文本占满，且图片无法被"看到"

### 命令构建位置

**`main.py` 第 504-551 行：**
```python
cmd_args = [CLAUDE_CMD, "-p", "--verbose"]
# ... 添加其他参数 ...
shell_cmd = f"cat {shlex.quote(prompt_file.name)} | {cmd_str}"
process = await asyncio.create_subprocess_shell(shell_cmd, ...)
```

文本通过 `cat file | claude -p --verbose` 管道传入，整个输入都是纯文本。

## Claude CLI 图片支持情况

CLI 版本：2.1.59，支持以下输入格式：
- `--input-format text`（默认）：纯文本输入，**不支持图片**
- `--input-format stream-json`：结构化 JSON 输入，**可支持多模态内容**

## 修复方向

当有图片时，应使用 `--input-format stream-json` 发送结构化消息：
```json
{
  "type": "user_message",
  "content": [
    {"type": "text", "text": "用户的文字消息"},
    {
      "type": "image",
      "source": {
        "type": "base64",
        "media_type": "image/png",
        "data": "实际的base64数据"
      }
    }
  ]
}
```

这样 Claude CLI 就能正确解析图片内容并传递给模型。
