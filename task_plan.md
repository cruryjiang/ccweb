# PPT 助手重构计划

## 目标
重构 PPT 助手功能，支持：
1. 模板选择（内置模板 + 自定义上传模板）
2. 参考文档链接输入
3. 生成提示词输入
4. 一键生成 + 下载

## 实现步骤

### Step 1: 模板管理 (ppt_generator.py)
- 新增 `PPT_TEMPLATE_DIR` 存储模板文件
- 新增 `list_templates()` / `save_template()` / `delete_template()`
- 修改 `create_ppt_file()` 支持基于模板生成

### Step 2: URL 内容获取
- 新增 `fetch_url_content()` 从 URL 获取参考文档

### Step 3: 后端 API (main.py)
- `GET /api/ppt/templates` - 列出模板
- `POST /api/ppt/templates/upload` - 上传模板
- `DELETE /api/ppt/templates/{name}` - 删除模板
- `POST /api/ppt/generate` - 一键生成（模板+URL+提示词）

### Step 4: 前端面板 (chat.html)
- PPT 助手面板 HTML + JS
- 模板选择、URL输入、提示词输入、生成、下载
