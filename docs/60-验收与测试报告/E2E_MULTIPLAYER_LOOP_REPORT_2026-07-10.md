# AI-Keeper 四玩家 / Host / AIKP 联调报告

测试日期：`2026-07-10`（Asia/Hong_Kong）

## 1. 本次交付

- 新增可重复执行的多人联调脚本：`scripts/run_multiplayer_loop.py`
- 新增示例动作脚本：`scripts/loop_actions_yhdx.json`
- 已完成一次真实 4 玩家 + 1 Host 的自动实跑，并生成：
  - 总报告：`docs/loop_runs/20260710-004734-657300cb.md`
  - 原始捕获：`docs/loop_runs/20260710-004734-657300cb.json`
  - 玩家日志：
    - `docs/loop_runs/20260710-004734-657300cb-p1.md`
    - `docs/loop_runs/20260710-004734-657300cb-p2.md`
    - `docs/loop_runs/20260710-004734-657300cb-p3.md`
    - `docs/loop_runs/20260710-004734-657300cb-p4.md`

## 2. 浏览器实测（`http://127.0.0.1:5173/`）

本轮已人工用浏览器走通 Host 主链路，并验证关键页面：

- 登录页可用
- Host 创建房间可用
- Lobby 可看到 4 名玩家入房与 ready 状态
- Host 开局可进入 Stage
- Host 舞台页可继续访问日志 / 地图 / 资料等主导航

对应浏览器实测房间与抓档：

- 浏览器房间：`695ba1a2`
- 浏览器抓档：`docs/ROOM_695ba1a2_CAPTURE.json`

## 3. 自动 Loop 实跑结果

本次自动实跑房间：

- 房间：`657300cb`
- 剧本：`向火独行.pdf`
- `scenario_id`：`136694d7`
- 结局：`victory / 成功逃脱`

自动流程覆盖：

1. Host 登录
2. 按剧本开房
3. 4 个玩家账号登录
4. 4 张 xlsx 角色卡上传入房
5. 4 名玩家 ready
6. Host 开局
7. 同回合提交 4 条行动
8. 轮询每条 `action_id`，直到全部进入最终态
9. 导出 campaign / timeline / player archive / markdown export
10. 显式触发结局并生成报告

## 4. 这次补掉的问题

为保证 loop 真能跑通，本轮补了 3 个关键卡点：

- `src/server/engine/resolution_pipeline.py`
  - 补上 `import re`
  - 修复 fallback narrative 在处理“我是谁”类文本时抛异常，导致回合卡死
- `src/server/router_archive.py`
  - 修复 campaign summary 路由参数错误
  - `POST /api/rooms/{room_id}/end` 现在会写入 `s2c_campaign_ended`
  - 支持传入 `ending_type / ending_name / text`
- `scripts/run_multiplayer_loop.py`
  - 初版曾误用 `/api/rooms/{room_id}/turns/current` 判断“本轮已结算”
  - 现已改成按玩家 `action_id` 轮询 `/api/player/actions/{action_id}`
  - 避免 `turn` 进入 `resolving` 后新建下一轮造成的竞态误判

## 5. 已完成验证

- 后端定向测试：
  - `python -m pytest tests/server/test_resolution_pipeline.py tests/server/test_archive.py tests/server/test_campaign.py -q`
  - 结果：`27 passed`
- 脚本语法检查：
  - `python -m py_compile scripts/run_multiplayer_loop.py`
- 自动 loop 真机实跑：
  - 命令：
    - `python scripts/run_multiplayer_loop.py --api-base http://127.0.0.1:3002 --ensure-accounts --scenario-id 136694d7 --turn-script scripts/loop_actions_yhdx.json`
  - 结果：成功生成房间 `657300cb` 及全套日志文档

## 6. 后续如何换多模态 API

如果你后面要切新的多模态后端，当前方案已经留好了切口：

- 浏览器前端：
  - 继续通过 `VITE_API_TARGET`
  - 继续通过 `VITE_WS_TARGET`
- 自动 loop：
  - 只需要改 `--api-base`
  - 如果动作脚本要换，改 `--turn-script`

复跑命令示例：

```powershell
python scripts/run_multiplayer_loop.py `
  --api-base http://127.0.0.1:3002 `
  --ensure-accounts `
  --scenario-id 136694d7 `
  --turn-script scripts/loop_actions_yhdx.json
```

## 7. 已知限制

- 当前“到达结局”使用的是显式 `POST /api/rooms/{room_id}/end` 收口，不是 AI 自动命中剧本结局条件
- `campaign summary` 当前只稳定保留 `ending_type`，结局名主要从 `s2c_campaign_ended` 事件里读取
- 导出的 markdown 里仍会看到部分重复叙事，这是现有 export 组织方式问题，不影响 loop 成功
- Host / Player 的长期会话安全（如 `owner_token` / `player_token` 存储策略）仍属于后续收口项，不算这次 loop 的阻塞项

