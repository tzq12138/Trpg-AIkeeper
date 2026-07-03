# 中文文案与 UTF-8 编码护栏收口计划

## Summary
- 分两条线做：先防止“正常 UTF-8 被 PowerShell 读成乱码”的假问题，再扫一遍真实页面文案。
- 不做全仓强制转码；只有检测确认文件真实损坏时才改内容。
- 本轮只处理源码、核心脚本、核心文档和用户可见页面；排除 `node_modules`、`dist`、`.vite`、测试缓存、设计稿归档和本地素材。

## Key Changes
- 新增编码检查脚本，例如 `scripts/check_text_quality.py`：
  - 只扫描 `src/`、`tests/`、`scripts/`、核心 `docs/PRDs`。
  - 检查 UTF-8 decode error、`�`、常见 mojibake 片段、明显残缺中文字符串。
  - 输出文件、行号、命中片段；默认只检查不修改。
- 增加最小 `.editorconfig`：
  - `*.py`、`*.ts`、`*.tsx`、`*.md`、`*.json`、`*.ps1` 使用 `utf-8`。
  - 不引入全仓换行重写，避免制造大 diff。
- 收口 Windows 脚本编码：
  - `scripts/test.ps1`、启动脚本显式设置 UTF-8 输出、`PYTHONUTF8=1`、`PYTHONIOENCODING=utf-8`。
  - 文档补一段 Windows PowerShell 读文件建议：用 `rg` 或 `Get-Content -Encoding UTF8`，避免误判源码乱码。
- 前端文案打磨：
  - 扫 `Admin / Host / Player / RAG 测试 / 车卡 / 行动 / 技能 / 背包 / 地图 / 日志` 等现有页面。
  - 修正空状态、按钮、错误提示、等待态、禁用态文案；保持 Bauhaus 风格，不引入 i18n 框架。
  - 页面文案保留“中文主文案 + 必要英文功能标签”的视觉风格。
- 后端用户可见错误收口：
  - 玩家/Host/Admin API 的常见 `HTTPException` detail 统一为清楚中文。
  - 内部日志仍可英文；不要把异常堆栈直接暴露给前端。
- Git 边界：
  - 不提交 `src/client/dist/`、`node_modules/.vite/`、`.pytest-tmp-*`、`.runtime/`、`__pycache__/`。
  - 如果缓存文件已经被误跟踪，只记录风险；是否从 index 移除单独确认，不混进本轮文案提交。

## Test Plan
- 运行 `python scripts/check_text_quality.py`，确认无真实乱码和 UTF-8 解码错误。
- 用 `rg` 抽查关键中文：提交行动、调查日志、暂无地图、已被选择、解锁音频、未命名玩家。
- 前端跑 TypeScript/Vite build。
- 手动打开 `/`、`/admin`、`/host/create`、`/host/:roomId/stage`、`/player/join`、`/player/:roomId`、`/rag-test`，确认无乱码、无残缺提示、无明显风格跳脱。
- 后端跑核心 server tests，确保只改文案不破坏行为。

## Assumptions
- 当前大面积乱码主要来自 PowerShell 读取 UTF-8 的显示问题，不是源码真实损坏。
- 本轮不做多语言系统，也不重构 UI 架构。
- 设计稿目录只作为参考，不参与批量文案修复。
