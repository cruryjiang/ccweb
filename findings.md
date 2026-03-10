# 发现和关键信息

- ppt_generator.py 使用 `Presentation()` 创建空白 PPT，不支持模板
- python-pptx 支持 `Presentation(template_path)` 加载模板
- 前端有 PPT panel CSS 但无对应 HTML 结构
- 当前通过 `/ppt` 命令交互，需重构为面板式 UI
- 模板存储路径: `data/ppt_templates/`
- PPT 输出路径: `data/ppt_files/`
