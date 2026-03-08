# 进度跟踪：图片发送问题修复

## 当前状态：修复已完成

## 排查阶段

| 步骤 | 状态 | 说明 |
|------|------|------|
| 分析项目结构 | ✅ | FastAPI + 纯 HTML/JS 前端，通过 CLI 调用 Claude |
| 分析前端图片流程 | ✅ | 前端逻辑正常：上传、预览、发送路径均工作 |
| 分析后端图片处理 | ✅ | **发现问题**：base64 作为纯文本嵌入 prompt |
| 确认 CLI 能力 | ✅ | CLI 2.1.59 支持 stream-json 多模态输入 |
| 定位根因 | ✅ | main.py:462-492 行，图片被当文本处理 |

## 根因总结

`main.py` 的 `stream_claude_response()` 函数（原第 462-492 行）将图片文件读取后转为 base64，
然后作为 `data:mime;base64,...` 纯文本追加到 prompt 字符串中。
通过 `cat prompt.txt | claude -p --verbose` 管道传入 CLI 时，CLI 只看到纯文本，
无法将其识别为图片。模型收到的是一大串 base64 字符而非实际图片。

## 修复阶段

| 步骤 | 状态 | 说明 |
|------|------|------|
| 修改图片处理逻辑 | ✅ | 改为构建 stream-json 多模态消息 |
| 修改命令构建 | ✅ | 有图片时使用 --input-format stream-json --output-format stream-json |
| 修改输出解析 | ✅ | 兼容 verbose 和 stream-json 两种输出格式 |
| 验证语法 | ✅ | Python 语法检查通过 |
| 运行时测试 | ⏳ | 需要启动服务并上传图片测试 |

## 修改文件清单

### `main.py` - 3 处修改

1. **图片处理逻辑（原 461-492 行）**
   - 删除：将 base64 文本嵌入 prompt 的逻辑
   - 新增：构建 stream-json 格式的多模态消息（text + image content blocks）
   - 当有图片时，prompt 文件写入 JSON 格式
   - 当无图片时，保持原始文本格式

2. **命令构建（原 504-509 行）**
   - 有图片：`claude -p --input-format stream-json --output-format stream-json`
   - 无图片：`claude -p --verbose`（保持不变）

3. **输出解析（原 585-613 行）**
   - 新增 stream-json 输出格式解析：
     - `{"type": "assistant", "message": {"type": "text", ...}}` → content
     - `{"type": "assistant", "message": {"type": "tool_use", ...}}` → tool_call
     - `{"type": "user", "message": {"type": "tool_result", ...}}` → tool_result
   - 保留原 verbose 格式解析（无图片时使用）

## 注意事项

- stream-json 输出格式可能因 Claude CLI 版本不同而有差异
- 如果 stream-json 格式与预期不符，可能需要调试输出格式并调整解析逻辑
- 建议启动服务后查看日志来确认图片是否被正确发送
