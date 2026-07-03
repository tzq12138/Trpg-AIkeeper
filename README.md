# AI-Keeper 工作区入口

AI-Keeper 是一个 AI 自动 KP / TRPG 网团系统，当前代码主线是 Python FastAPI 后端、React/Vite 前端、PostgreSQL/pgvector、可选 Redis 和 KP MCP Server。

## 常用入口

| 路径 | 用途 |
|---|---|
| `docs/README.md` | 文档总索引，路线图、PRD、DeepSeek 任务包都从这里进入。 |
| `src/server/` | FastAPI 后端、Engine、AI、事件、Host/Player/Scenario 路由。 |
| `src/client/` | React/Vite 前端，Host 大屏和 Player 手机端页面。 |
| `kp_mcp_server/` | 独立 KP MCP Server 和 prompt 契约。 |
| `tests/` | 后端测试与前端相关测试入口。 |
| `data/` | 本地开发数据、剧本素材、测试素材。 |
| `scripts/` | 本地辅助脚本。 |

## 当前整理口径

- 根目录只保留项目入口、配置、启动脚本和源码目录。
- 历史计划已归档到 `docs/90-归档/历史计划/`。
- 根目录审查文档已归档到 `docs/90-归档/外部审查/`。
- AI KP soul 文档已移动到 `docs/20-核心链路/soul.md`；运行时 MCP prompt 仍在 `kp_mcp_server/prompts/soul.md`。
- 大型测试 PDF/xlsx/图片素材已移动到 `data/test_assets/最小测试模块/`。

## 开发提醒

- 当前工作区存在未提交改动，改代码前先运行 `git status --short`。
- 不要提交 `.runtime/`、`log/`、`.pytest-*`、`__pycache__/`、本地数据库、`node_modules/`、`dist/`。
- 新增计划和执行任务优先写入 `docs/30-DeepSeek任务包/`，不要再新增根目录 `plan/`。
