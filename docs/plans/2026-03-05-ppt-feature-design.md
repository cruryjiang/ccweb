# PPT 制作功能设计文档

## 1. 功能概述

实现一个交互式 PPT 制作命令 (`/ppt`)，支持用户：
- 上传源文档（Word/PDF/Markdown/TXT）
- 描述 PPT 需求
- AI 自动生成 PPT 大纲
- 逐页编辑完善内容
- 生成并下载标准 .pptx 文件

## 2. 工作流程

### 2.1 用户使用流程

```
用户输入 /ppt [需求描述]
         ↓
    打开 PPT 侧面板
         ↓
    ┌─────────────────────────────────────┐
    │ 阶段1：准备                          │
    │ • 上传源文档（可选）                  │
    │ • 输入 PPT 需求描述                   │
    └─────────────────────────────────────┘
         ↓ 点击"生成 PPT 大纲"
    ┌─────────────────────────────────────┐
    │ 阶段2：大纲预览                      │
    │ AI 分析文档/需求 → 生成大纲          │
    │ • 显示标题、副标题                   │
    │ • 显示各页面标题列表                  │
    └─────────────────────────────────────┘
         ↓ 点击"确认并编辑"
    ┌─────────────────────────────────────┐
    │ 阶段3：逐页编辑                      │
    │ • 编辑标题、副标题                   │
    │ • 编辑要点（bullet points）          │
    │ • 编辑演讲备注                       │
    │ • 上一页/下一页导航                   │
    │ • 添加/删除页面                      │
    └─────────────────────────────────────┘
         ↓ 点击"完成并生成 PPT"
    ┌─────────────────────────────────────┐
    │ 阶段4：完成下载                      │
    │ • 生成 .pptx 文件                    │
    │ • 提供下载链接                       │
    └─────────────────────────────────────┘
```

## 3. 技术架构

### 3.1 后端模块

```
main.py
├── PPT API 端点
│   ├── POST /api/ppt/upload         # 文件上传
│   ├── POST /api/ppt/outline        # 生成大纲（流式）
│   ├── GET  /api/ppt/session/{id}   # 获取会话
│   ├── DEL  /api/ppt/session/{id}   # 删除会话
│   ├── GET  /api/ppt/slide/{id}/{i} # 获取页面
│   ├── POST /api/ppt/slide/{id}/{i} # 更新页面
│   ├── POST /api/ppt/slide/{id}     # 添加页面
│   ├── DEL  /api/ppt/slide/{id}/{i} # 删除页面
│   ├── POST /api/ppt/finalize       # 生成 PPT
│   └── GET  /api/ppt/download/{fn}  # 下载
│
ppt_generator.py
├── 数据结构
│   ├── SlideContent    # 单页内容
│   ├── PPTOutline      # PPT 大纲
│   └── PPTSession      # 会话状态
│
├── 文档提取
│   ├── extract_text_from_document()
│   ├── .txt/.md 读取
│   ├── .docx 读取（python-docx）
│   └── .pdf 读取（PyPDF2）
│
├── AI Prompt 生成
│   ├── generate_outline_prompt()
│   └── generate_slide_content_prompt()
│
└── PPT 文件生成
    ├── create_ppt_file()
    └── python-pptx 库
```

### 3.2 前端模块

```
chat.html
├── CSS 样式 (~300行)
│   ├── .ppt-panel      # 侧面板
│   ├── .ppt-upload-area # 上传区
│   ├── .ppt-outline    # 大纲展示
│   ├── .ppt-editor     # 页面编辑器
│   └── .ppt-btn        # 按钮样式
│
├── HTML 结构
│   ├── #pptStage1      # 上传/需求输入
│   ├── #pptStage2      # 大纲预览
│   ├── #pptStage3      # 页面编辑
│   └── #pptStage4      # 完成下载
│
└── JavaScript (~500行)
    ├── handlePPTCommand()      # /ppt 命令
    ├── open/closePPTPanel()    # 面板控制
    ├── generatePPTOutline()    # 生成大纲
    ├── displayPPTOutline()     # 显示大纲
    ├── loadSlideToEditor()     # 加载页面
    ├── saveCurrentSlide()      # 保存页面
    ├── prev/nextPPTSlide()     # 页面导航
    ├── addPPTSlide()           # 添加页面
    ├── deleteCurrentSlide()    # 删除页面
    └── finalizePPT()           # 完成生成
```

## 4. 数据模型

### 4.1 SlideContent
```python
@dataclass
class SlideContent:
    title: str           # 页面标题
    subtitle: str        # 副标题
    bullets: List[str]   # 要点列表
    notes: str           # 演讲备注
    layout_type: str     # 布局类型
```

### 4.2 PPTOutline
```python
@dataclass
class PPTOutline:
    title: str           # PPT 主标题
    subtitle: str        # 副标题
    slides: List[SlideContent]  # 页面列表
    theme: str           # 主题风格
    source_doc: str      # 源文档摘要
```

### 4.3 PPTSession
```python
@dataclass
class PPTSession:
    session_id: str
    outline: PPTOutline
    current_slide_index: int
    status: str          # idle/outline_generated/editing/finalizing/completed
    source_file: str     # 上传的源文档路径
    output_file: str     # 生成的 PPT 路径
```

## 5. API 规范

### 5.1 POST /api/ppt/upload
**请求**: multipart/form-data
- file: 上传的文件
- session_id: 会话ID

**响应**:
```json
{
  "status": "ok",
  "filename": "document.docx",
  "path": "/path/to/file",
  "size": 12345
}
```

### 5.2 POST /api/ppt/outline
**请求**:
```json
{
  "session_id": "xxx",
  "requirement": "描述文本"
}
```

**响应**: SSE 流式响应
- `type: content` - AI 生成内容
- `type: outline_ready` - 大纲生成完成
- `type: error` - 错误信息
- `type: done` - 完成

### 5.3 POST /api/ppt/finalize
**请求**:
```json
{
  "session_id": "xxx"
}
```

**响应**:
```json
{
  "status": "ok",
  "filename": "ppt_xxx.pptx",
  "download_url": "/api/ppt/download/xxx.pptx",
  "slide_count": 10
}
```

## 6. 核心算法

### 6.1 大纲生成 Prompt
```
请根据以下内容生成一个 PPT 大纲。

要求：
1. 设计一个清晰的标题和副标题
2. 规划 5-15 页幻灯片
3. 每页包含：标题、要点（3-5 个 bullet points）、页面类型建议
4. 确保逻辑流畅，覆盖核心内容
5. 使用 JSON 格式输出

用户需求：{用户输入}
源文档内容：{文档内容}

请按以下 JSON 格式输出：
{
  "title": "PPT 主标题",
  "subtitle": "副标题",
  "slides": [{"title": "...", "bullets": [...]}]
}
```

### 6.2 PPT 文件生成
```python
def create_ppt_file(outline, output_path):
    prs = Presentation()
    prs.slide_width = Inches(13.333)   # 16:9
    prs.slide_height = Inches(7.5)

    for slide_content in outline.slides:
        # 选择布局
        layout = select_layout(slide_content.layout_type)
        slide = prs.slides.add_slide(layout)

        # 设置标题和内容
        slide.shapes.title.text = slide_content.title
        set_bullets(slide, slide_content.bullets)

        # 添加演讲备注
        if slide_content.notes:
            slide.notes_slide.notes_text_frame.text = slide_content.notes

    prs.save(output_path)
```

## 7. 文件存储

```
data/
├── ppt_files/           # 生成的 PPT 文件
│   └── ppt_{session_id}_{timestamp}.pptx
├── ppt_uploads/         # 上传的源文档
│   └── {session_id}_{filename}
└── sessions/            # 会话配置
    └── {session_id}.json
```

## 8. 依赖项

```
python-pptx==1.0.2     # PPTX 文件生成
python-docx==1.1.2     # Word 文档读取
PyPDF2==3.0.1          # PDF 文档读取
```

## 9. 扩展建议

1. **模板系统** - 支持多种预设模板风格
2. **图片生成/插入** - 集成 AI 图片生成
3. **协作功能** - 多人实时编辑
4. **版本历史** - 保存编辑历史记录
5. **云端存储** - 对接云存储服务

## 10. 实现时间

- 设计阶段：2026-03-05
- 实现阶段：2026-03-05
- 代码行数：
  - 后端：~800 行
  - 前端：~800 行
  - 总计：~1600 行
