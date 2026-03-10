# 进度跟踪

- [x] 创建规划文件
- [x] 模板管理 (ppt_generator.py) — 新增 list/save/delete/get_template_path
- [x] URL 内容获取 — fetch_url_content + HTMLTextExtractor
- [x] 后端 API (main.py) — /api/ppt/templates + /api/ppt/generate
- [x] 前端面板 (chat.html) — PPT 助手面板 UI + JS
- [x] 内置模板 — 商务蓝/简约黑/学术风
- [x] 测试 — 模板创建、URL获取、PPT生成均通过

## 第二轮：UI 布局重构
- [x] 新增左侧导航栏（64px 宽，图标+工具提示）
- [x] 页面视图系统（page-chat / page-ppt / page-yuque / page-coder）
- [x] PPT 助手独立全页面（从弹出面板改为独立页面）
- [x] 右侧历史面板（可展开/收起，280px 宽）
- [x] switchPage() 导航切换逻辑
- [x] toggleRightHistory() 右侧面板控制
- [x] 清理旧的弹出面板 CSS/HTML
- [x] 语雀助手/编码助手占位页面
