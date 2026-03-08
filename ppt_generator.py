"""
PPT 生成器模块
提供交互式 PPT 制作功能
"""
import os
import json
import re
import asyncio
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, AsyncGenerator
from datetime import datetime
import tempfile
import shutil

# PPT 生成
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE

# 文档解析
try:
    from docx import Document as DocxDocument
    DOCX_AVAILABLE = True
except ImportError:
    DOCX_AVAILABLE = False

try:
    import PyPDF2
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False


@dataclass
class SlideContent:
    """单页幻灯片内容"""
    title: str = ""
    subtitle: str = ""
    bullets: List[str] = field(default_factory=list)
    notes: str = ""  # 演讲者备注
    layout_type: str = "content"  # title, content, title_only, blank, etc.

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "SlideContent":
        return cls(**data)


@dataclass
class PPTOutline:
    """PPT 大纲结构"""
    title: str = ""
    subtitle: str = ""
    slides: List[SlideContent] = field(default_factory=list)
    theme: str = "default"  # 主题风格
    source_doc: str = ""  # 源文档内容摘要

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "subtitle": self.subtitle,
            "theme": self.theme,
            "source_doc": self.source_doc,
            "slides": [s.to_dict() for s in self.slides]
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PPTOutline":
        slides = [SlideContent.from_dict(s) for s in data.get("slides", [])]
        return cls(
            title=data.get("title", ""),
            subtitle=data.get("subtitle", ""),
            theme=data.get("theme", "default"),
            source_doc=data.get("source_doc", ""),
            slides=slides
        )


@dataclass
class PPTSession:
    """PPT 制作会话"""
    session_id: str
    outline: PPTOutline = field(default_factory=PPTOutline)
    current_slide_index: int = 0
    status: str = "idle"  # idle, outline_generated, editing, finalizing, completed
    created_at: float = field(default_factory=lambda: datetime.now().timestamp())
    source_file: str = ""  # 上传的源文档路径
    output_file: str = ""  # 生成的 PPT 文件路径

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "outline": self.outline.to_dict(),
            "current_slide_index": self.current_slide_index,
            "status": self.status,
            "created_at": self.created_at,
            "source_file": self.source_file,
            "output_file": self.output_file
        }


# 内存存储（生产环境应使用 Redis/数据库）
ppt_sessions: Dict[str, PPTSession] = {}

# PPT 文件存储目录（使用数据目录，避免写入只读的打包目录）
_data_dir = os.environ.get('CLAUDE_WEB_DATA_DIR', os.path.dirname(os.path.abspath(__file__)))
PPT_STORAGE_DIR = os.path.join(_data_dir, "data", "ppt_files")
os.makedirs(PPT_STORAGE_DIR, exist_ok=True)


def extract_text_from_document(file_path: str) -> str:
    """
    从文档中提取文本内容
    支持 TXT, MD, DOCX, PDF
    """
    ext = os.path.splitext(file_path)[1].lower()

    if ext in ['.txt', '.md', '.markdown']:
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            return f.read()

    elif ext == '.docx':
        if not DOCX_AVAILABLE:
            raise ImportError("python-docx 未安装，无法读取 Word 文档")
        doc = DocxDocument(file_path)
        texts = []
        for para in doc.paragraphs:
            if para.text.strip():
                texts.append(para.text)
        return '\n'.join(texts)

    elif ext == '.pdf':
        if not PDF_AVAILABLE:
            raise ImportError("PyPDF2 未安装，无法读取 PDF 文档")
        text = []
        with open(file_path, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                text.append(page.extract_text() or "")
        return '\n'.join(text)

    else:
        raise ValueError(f"不支持的文件格式: {ext}")


def generate_outline_prompt(source_text: str, user_requirement: str = "") -> str:
    """
    生成用于创建 PPT 大纲的 AI Prompt
    """
    prompt = f"""请根据以下内容生成一个 PPT 大纲。

要求：
1. 设计一个清晰的标题和副标题
2. 规划 5-15 页幻灯片（根据内容复杂度决定）
3. 每页包含：标题、要点（3-5 个 bullet points）、页面类型建议
4. 确保逻辑流畅，覆盖核心内容
5. 使用 JSON 格式输出

"""
    if user_requirement:
        prompt += f"用户需求：{user_requirement}\n\n"

    prompt += f"源文档内容：\n{source_text[:8000]}\n\n"  # 限制长度避免超出 token

    prompt += """请按以下 JSON 格式输出：
{
  "title": "PPT 主标题",
  "subtitle": "副标题",
  "theme": "business|academic|creative|minimal",
  "slides": [
    {
      "title": "页面标题",
      "subtitle": "副标题（可选，用于标题页）",
      "bullets": ["要点1", "要点2", "要点3"],
      "layout_type": "title|content|title_only|two_content"
    }
  ]
}

注意：
- 第一页通常是 title 类型（标题页）
- 内容页使用 content 类型
- layout_type 可选值：title, content, title_only, two_content, blank
"""
    return prompt


def generate_slide_content_prompt(outline: PPTOutline, slide_index: int, source_text: str = "") -> str:
    """
    生成用于完善单页幻灯片内容的 AI Prompt
    """
    if slide_index < 0 or slide_index >= len(outline.slides):
        return ""

    slide = outline.slides[slide_index]

    prompt = f"""请完善以下 PPT 页面的内容：

页面标题：{slide.title}
当前要点：
"""
    for bullet in slide.bullets:
        prompt += f"- {bullet}\n"

    prompt += f"\n页面类型：{slide.layout_type}\n"

    if source_text:
        prompt += f"\n参考原文（相关部分）：\n{source_text[:3000]}\n"

    prompt += """
请完善内容：
1. 优化标题，使其更吸引人
2. 扩展要点，使其更详细、有价值（每个要点 1-2 句话）
3. 添加演讲者备注（notes），帮助演讲者理解这页的重点
4. 如果需要，建议这页是否需要配图或图表

请按以下 JSON 格式输出：
{
  "title": "优化后的标题",
  "subtitle": "副标题（如有）",
  "bullets": ["详细要点1", "详细要点2", "详细要点3"],
  "notes": "演讲者备注",
  "suggestions": "设计建议，如配图建议"
}
"""
    return prompt


def parse_outline_from_ai_response(response: str) -> Optional[PPTOutline]:
    """
    从 AI 响应中解析 PPT 大纲
    """
    try:
        # 尝试提取 JSON 部分
        json_match = re.search(r'\{[\s\S]*\}', response)
        if not json_match:
            return None

        data = json.loads(json_match.group())

        # 构建 PPTOutline
        slides = []
        for slide_data in data.get("slides", []):
            slide = SlideContent(
                title=slide_data.get("title", ""),
                subtitle=slide_data.get("subtitle", ""),
                bullets=slide_data.get("bullets", []),
                notes=slide_data.get("notes", ""),
                layout_type=slide_data.get("layout_type", "content")
            )
            slides.append(slide)

        return PPTOutline(
            title=data.get("title", ""),
            subtitle=data.get("subtitle", ""),
            theme=data.get("theme", "default"),
            source_doc=data.get("source_doc", ""),
            slides=slides
        )
    except Exception as e:
        print(f"解析大纲失败: {e}")
        return None


def parse_slide_content_from_ai_response(response: str) -> Optional[SlideContent]:
    """
    从 AI 响应中解析单页幻灯片内容
    """
    try:
        json_match = re.search(r'\{[\s\S]*\}', response)
        if not json_match:
            return None

        data = json.loads(json_match.group())

        return SlideContent(
            title=data.get("title", ""),
            subtitle=data.get("subtitle", ""),
            bullets=data.get("bullets", []),
            notes=data.get("notes", ""),
            layout_type=data.get("layout_type", "content")
        )
    except Exception as e:
        print(f"解析幻灯片内容失败: {e}")
        return None


def get_or_create_ppt_session(session_id: str) -> PPTSession:
    """获取或创建 PPT 会话"""
    if session_id not in ppt_sessions:
        ppt_sessions[session_id] = PPTSession(session_id=session_id)
    return ppt_sessions[session_id]


def delete_ppt_session(session_id: str):
    """删除 PPT 会话及其文件"""
    if session_id in ppt_sessions:
        session = ppt_sessions[session_id]

        # 删除源文件
        if session.source_file and os.path.exists(session.source_file):
            try:
                os.remove(session.source_file)
            except:
                pass

        # 删除输出文件
        if session.output_file and os.path.exists(session.output_file):
            try:
                os.remove(session.output_file)
            except:
                pass

        del ppt_sessions[session_id]


def cleanup_old_sessions(max_age_hours: int = 24):
    """清理过期的会话和文件"""
    current_time = datetime.now().timestamp()
    to_delete = []

    for session_id, session in ppt_sessions.items():
        age_hours = (current_time - session.created_at) / 3600
        if age_hours > max_age_hours:
            to_delete.append(session_id)

    for session_id in to_delete:
        delete_ppt_session(session_id)


def create_ppt_file(outline: PPTOutline, output_path: str) -> str:
    """
    使用 python-pptx 创建 PPT 文件

    返回: 输出文件的完整路径
    """
    prs = Presentation()

    # 设置幻灯片尺寸为 16:9
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)

    for i, slide_content in enumerate(outline.slides):
        # 选择布局
        if slide_content.layout_type == "title" or i == 0:
            layout = prs.slide_layouts[0]  # Title Slide
        elif slide_content.layout_type == "title_only":
            layout = prs.slide_layouts[5]  # Title Only
        elif slide_content.layout_type == "two_content":
            layout = prs.slide_layouts[5]  # Use blank for custom layout
        else:
            layout = prs.slide_layouts[1]  # Title and Content

        slide = prs.slides.add_slide(layout)

        # 设置标题
        if slide.shapes.title:
            slide.shapes.title.text = slide_content.title

        # 设置内容
        if len(slide.placeholders) > 1:
            body_shape = slide.placeholders[1]
            tf = body_shape.text_frame
            tf.clear()

            for j, bullet in enumerate(slide_content.bullets):
                if j == 0:
                    p = tf.paragraphs[0]
                else:
                    p = tf.add_paragraph()
                p.text = bullet
                p.level = 0

        # 设置副标题（标题页）
        if slide_content.layout_type == "title" and slide_content.subtitle:
            if len(slide.placeholders) > 1:
                slide.placeholders[1].text = slide_content.subtitle

        # 添加演讲者备注
        if slide_content.notes:
            notes_slide = slide.notes_slide
            notes_slide.notes_text_frame.text = slide_content.notes

    # 添加结束页
    if outline.slides and outline.slides[-1].title not in ["谢谢", "Thank You", "结束", "Q&A"]:
        ending_layout = prs.slide_layouts[6]  # Blank
        ending_slide = prs.slides.add_slide(ending_layout)

        # 添加感谢文本
        left = Inches(2)
        top = Inches(3)
        width = Inches(9)
        height = Inches(1.5)

        textbox = ending_slide.shapes.add_textbox(left, top, width, height)
        tf = textbox.text_frame
        tf.text = "谢谢观看"
        p = tf.paragraphs[0]
        p.alignment = PP_ALIGN.CENTER
        p.font.size = Pt(44)
        p.font.bold = True

    # 保存文件
    prs.save(output_path)
    return output_path


async def stream_ppt_creation_process(
    session_id: str,
    claude_stream_func,
    message: str = ""
) -> AsyncGenerator[str, None]:
    """
    流式获取 PPT 创建过程

    claude_stream_func: 调用 Claude CLI 的流式函数
    """
    session = get_or_create_ppt_session(session_id)

    if session.status == "idle":
        # 第一步：生成大纲
        yield json.dumps({
            "type": "status",
            "message": "正在分析文档并生成 PPT 大纲...",
            "step": "outline"
        })

        source_text = ""
        if session.source_file:
            try:
                source_text = extract_text_from_document(session.source_file)
            except Exception as e:
                yield json.dumps({
                    "type": "error",
                    "message": f"读取源文档失败: {str(e)}"
                })
                return

        prompt = generate_outline_prompt(source_text, message)

        # 调用 Claude 生成大纲
        response_text = ""
        async for chunk in claude_stream_func(prompt, session_id):
            try:
                data = json.loads(chunk[6:])  # 去掉 "data: " 前缀
                if data.get("type") == "content":
                    response_text += data.get("text", "")
                elif data.get("type") == "done":
                    break
            except:
                pass

        # 解析大纲
        outline = parse_outline_from_ai_response(response_text)
        if outline:
            session.outline = outline
            session.status = "outline_generated"
            yield json.dumps({
                "type": "outline_ready",
                "outline": outline.to_dict(),
                "message": f"大纲已生成，共 {len(outline.slides)} 页"
            })
        else:
            yield json.dumps({
                "type": "error",
                "message": "无法解析 AI 返回的大纲，请重试"
            })

    elif session.status == "outline_generated":
        # 处于大纲已生成状态，等待用户确认或修改
        yield json.dumps({
            "type": "status",
            "message": "请确认大纲或提出修改意见",
            "step": "review_outline",
            "outline": session.outline.to_dict()
        })

    elif session.status == "editing":
        # 编辑单页内容
        current_slide = session.outline.slides[session.current_slide_index]
        yield json.dumps({
            "type": "status",
            "message": f"正在编辑第 {session.current_slide_index + 1} 页...",
            "step": "editing_slide",
            "slide_index": session.current_slide_index,
            "slide": current_slide.to_dict()
        })

    elif session.status == "finalizing":
        # 生成最终 PPT 文件
        yield json.dumps({
            "type": "status",
            "message": "正在生成 PPT 文件...",
            "step": "generating_file"
        })

        output_filename = f"ppt_{session_id}_{int(datetime.now().timestamp())}.pptx"
        output_path = os.path.join(PPT_STORAGE_DIR, output_filename)

        try:
            create_ppt_file(session.outline, output_path)
            session.output_file = output_path
            session.status = "completed"

            yield json.dumps({
                "type": "ppt_ready",
                "message": "PPT 生成完成！",
                "filename": output_filename,
                "download_url": f"/api/ppt/download/{output_filename}",
                "slide_count": len(session.outline.slides)
            })
        except Exception as e:
            yield json.dumps({
                "type": "error",
                "message": f"生成 PPT 文件失败: {str(e)}"
            })


# PPT 命令帮助文本
PPT_COMMAND_HELP = """
📊 PPT 制作命令帮助

使用方法：
/ppt [需求描述]  - 进入 PPT 制作模式

工作流程：
1. 上传源文档（可选）- 支持 TXT, MD, DOCX, PDF
2. 输入需求描述      - 如："制作一个产品经理年终总结 PPT"
3. AI 生成大纲       - 预览并确认 PPT 结构
4. 逐页编辑内容      - 修改每页的标题和要点
5. 生成 PPT 文件     - 下载 .pptx 文件

编辑命令：
- 确认 / 下一步     - 确认当前步骤继续
- 修改第N页         - 编辑指定页面
- 添加一页          - 在最后添加新页面
- 删除第N页         - 删除指定页面
- 完成              - 生成最终 PPT 文件
- 退出              - 退出 PPT 制作模式
"""
