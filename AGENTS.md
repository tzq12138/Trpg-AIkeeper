# 仓库指南

## 项目结构与模块组织

AI-Keeper 是一个 FastAPI + React/Vite 的 TRPG 网团平台。后端代码位于 `src/server/`，按领域拆分为 `player/`、`host/`、`engine/`、`ai/`、`scenario/`、事件、路由和持久化辅助模块。前端代码位于 `src/client/src/`，页面在 `pages/`，共享工具在 `shared/`，可复用 UI 在 `components/`。后端测试在 `tests/server/`。产品、PRD 和执行文档位于 `docs/`。本地剧本、素材和测试资源位于 `data/`。独立 KP MCP Server 位于 `kp_mcp_server/`。

## 构建、测试与开发命令

- `python dev.py`：启动 Docker 服务、`:3001` FastAPI 后端和 Vite 前端。
- `python dev.py --check`：只运行本地健康检查，不启动服务。
- `python dev.py --stop`：停止 Docker 服务。
- `docker compose up -d`：只启动 PostgreSQL/pgvector 和 Redis。
- `python -m pytest tests/server -q`：运行后端测试。
- `cd src/client && npm run dev`：启动前端开发服务器。
- `cd src/client && npm run build`：运行 TypeScript 检查并构建 Vite 输出。
- `cd src/client && npm run test`：运行 Vitest。

## 编码风格与命名约定

遵循 `.editorconfig`：UTF-8、LF、文件末尾换行；Python 使用 4 空格缩进，TypeScript、Markdown、JSON 使用 2 空格缩进。Python 模块和函数使用 `snake_case`。React 组件和页面使用 `PascalCase` 文件名，例如 `HostLobby.tsx`。共享 TypeScript 工具使用描述性的短横线或小写文件名。优先沿用现有 router、service、helper 模式，不随意引入新抽象。不要提交 `.runtime/`、`log/`、`.pytest-*`、`__pycache__/`、`node_modules/`、`dist/` 等运行产物。

## 测试规范

后端使用 pytest，前端使用 Vitest。后端测试文件命名为 `tests/server/test_<feature>.py`，尽量让测试靠近对应功能。修改权限、房间、投影、AI 安全相关逻辑时，先跑相关定向测试；可行时再跑 `python -m pytest tests/server -q`。修改前端页面或类型时，应通过 `npm run build`。

## 提交与 PR 规范

近期提交使用简短前缀，如 `fix:`、`docs:`、`test:`、`chore:`。提交信息保持祈使语气并说明范围，例如 `fix: harden host websocket auth`。PR 应包含简短摘要、测试证据、关联 issue 或计划；有可见 UI 改动时附截图。涉及迁移、配置或安全敏感行为时必须明确说明。

## 安全与配置提示

不要提交密钥或本地数据库。开发环境之外必须设置强随机 `JWT_SECRET`。`owner_token`、`player_token`、日志、房间导出数据和 AI prompt 都应视为敏感信息；公开 DTO 和导出内容必须保持脱敏。
