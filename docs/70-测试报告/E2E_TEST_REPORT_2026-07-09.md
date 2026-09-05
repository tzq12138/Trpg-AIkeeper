# AI-Keeper 浏览器 Loop / 玩家 / AIKP 测试报告

测试时间：2026-07-09（Asia/Hong_Kong）

## 测试依据

- `docs/TEST_COVERAGE.md`
- `docs/20-核心链路/AI-Keeper核心链路架构.md`
- `docs/50-AI-Keeper-Platform/12-AI-Keeper核心系统/验收文档.md`
- `docs/PRDs/PRD-24-AI自动KP主持循环.md`

## 环境

- 前端入口：`http://127.0.0.1:5173/`
- 当前验证后端：`http://127.0.0.1:3002/`
- 说明：本机 `3001` 被旧 Codex/Edge 网络服务占用且普通进程无法释放；已将 Vite 代理改为可配置，测试时使用：
  - `VITE_API_TARGET=http://127.0.0.1:3002`
  - `VITE_WS_TARGET=ws://127.0.0.1:3002`
- 浏览器测试房间：`8acae1f6`
- 测试账号：`e2e_admin`

## 浏览器 Loop 结果

| 流程 | 结果 | 证据 |
| --- | --- | --- |
| 管理员登录 | 通过 | 成功进入创建房间页面 |
| 创建房间 | 通过 | 创建房间 `8acae1f6` |
| 玩家加入 | 通过 | `玩家一号 / 查尔斯·钱伯斯` 加入 |
| 玩家准备 | 通过 | Lobby 显示已准备 |
| 主持开始游戏 | 修复后通过 | 修复 `HostStage` HUD `queueStatus` 崩溃 |
| 玩家页导航 | 通过 | 行动、技能、装备、日志、地图均可打开 |
| 主持页导航 | 通过 | 传说、追逐、资料库、日志、地图均可打开 |
| 玩家行动提交 | 通过 | 两轮行动均进入 AIKP 结算 |
| AIKP 自动结算 | 通过 | 生成 `s2c_reveal_transaction`、`s2c_public_observation`、`s2c_action_completed` |
| 玩家重连回放 | 修复后通过 | 刷新后回放两轮检定结果 |
| 主持日志归档 | 修复后通过 | 日志显示 #53-#60 行动、叙事、公开、结算事件 |

## 玩家测试

- 玩家行动终端：可提交自然语言行动；结算期间按钮禁用，结算后恢复。
- 玩家技能页：可展示角色与技能入口。
- 玩家装备页：空背包/线索板可正常展示。
- 玩家日志页：可打开，当前主要结果通过 WS catch-up 回放在行动终端。
- 玩家地图页：无地图配置时显示等待初始化提示。
- 玩家 WS 重连：修复 `s2c_checkpoint_created` 类型后，重连不再因事件校验失败断开。

## AIKP 测试

- 自动 KP loop：单玩家行动提交后自动进入回合结算，生成检定叙事。
- AI 状态：`GET /api/rooms/{room_id}/ai-status` 返回房间 AI 状态。
- 手动 AI 回合：`POST /api/rooms/{room_id}/ai-turn` 支持 `X-Owner-Token`；无待处理动作时返回 `400 No pending actions to process`。
- 事件归档：AIKP 结算事件写入 `events`，主持日志可查询和展示。
- 防剧透/事件可见性：全量后端测试覆盖事件可见性、RAG 安全、SpoilerGuard、重连回放。

## 修复清单

- 修复 STT mock endpoint 的相对导入，补 `speech-to-text` mock 测试。
- 修复主持舞台 HUD REST `queueStatus`/`queue_status` 形状不一致导致的崩溃。
- 挂载 `router_archive`，恢复主持 timeline/checkpoint/export 路由。
- 修复主持日志请求只带 owner token、不带管理员 Bearer 的问题。
- 修复 `ai-turn` owner token fallback 鉴权顺序。
- 将前端 WebSocket 从硬编码 `:3001` 改成相对 `/ws`，通过 Vite 代理支持可切换后端/API loop。
- 将 Vite `/api`、`/ws` 代理目标改为环境变量可配置。
- 注册 `s2c_checkpoint_created` 事件类型，修复玩家重连回放断连。

## 自动化验证

- `python -m pytest tests/server -q`：`425 passed`
- `cd src/client && npm run test`：`4 passed / 7 tests`
- `cd src/client && npm run build`：通过
- 浏览器实测：
  - 玩家第二轮刷新后显示：`我调查门厅...检定结果 7/0，failure`、`我检查窗台灰尘...检定结果 3/0，failure`
  - 主持日志显示事件：`#53 action_queued`、`#54 叙事`、`#55 公开`、`#56 结算`、`#57 action_queued`、`#58 叙事`、`#59 公开`、`#60 结算`

## 后续注意

- 当前测试确认 loop 可通过环境变量切换后端；切换多模态 API 时优先保持 `VITE_API_TARGET` / `VITE_WS_TARGET` 指向同一后端实例。
- 角色模板加载在浏览器实测中偏慢，且测试剧本模板未优先显示为自定义模板；不阻塞本次 AIKP loop，但建议后续优化 presets/template 查询。
- 部分浏览器中历史中文数据曾出现 mojibake，当前核心流程不受阻塞；如要做发布级演示，建议单独排查数据库/终端编码链路。
