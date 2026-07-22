# 统一内容数据层与《向火独行》原版运行：验收报告

日期：2026-07-11  
范围：统一内容投影、版本化 RAG、原版 PDF 导入质量、编号单人冒险运行时及 390px 玩家浏览器闭环。

## 已交付

- 新增版本范围的 `content_items`、`content_item_edges`、`content_projection_runs`，并写入两套 PostgreSQL 初始化入口。
- `ScenarioImportService` 在草稿版本落库后建立规范内容投影；旧 `knowledge_graph` 保留为兼容输入，不改动既有 Room、Engine、WebSocket 或角色页数据。
- 发布时为规范节点生成 `document_chunks.source_type='content'`，保留内容类型、版本、来源分段、页码与 citation；房间检索范围包含已绑定版本的该类切片。
- 新增受确认的单版本重置脚本：`python scripts/reset_content_projection.py --scenario-version-id <id> --confirm-reset`。它只清除规范节点和关系，保留原件、世界书、RAG、房间及运行记录。
- 原版 PDF 的“编号# / 转到编号”被确定性解析为 `solo_adventure`；无效编号图会在质量报告中标为 `blocked`，发布返回 `invalid_solo_adventure`，管理员不能绕过。
- `SoloAdventureRuntime` 使用规范节点和边校验当前条目、显式转移与陈旧请求；同一事务写入 `room_scene_state`、房间状态版本和 V2 行动完成记录，并发出 `s2c_scene_sync`。
- 玩家文字场景只投影当前条目、允许出口与当前 citation；普通地图状态不会泄露未到达条目正文。

## 原版黄金基线

- `向火独行.pdf`：270 个唯一节点、410 条显式跳转、无重复节点、无失链；不可达节点仅为信息级诊断。
- 条目 `1` 的正文从“太阳高悬天空”开始，唯一出口为条目 `263`；不再错误混入页面右栏的条目 `9/15/22`。
- PDF 本地提取会在双栏文本纵向重叠时先读左栏、再读右栏；单栏 PDF 仍保持原抽取路径。
- 解析层会去除纯 ASCII 的重复书名页眉碎片和独立罗马页码，条目 `263` 不再出现 `ALONE AGAINST…` 页眉污染。
- 外部机制编译器即使返回 `move` 但遗漏目标，也会保留已确认意图中的 `fromNodeId`、`targetNodeId` 和 `solo_adventure` 标记，保证单人分支由确定性规则结算。

## 浏览器验收

- 在 `390×844` 视口的本地验收环境完成注册、邀请房间预检、账号角色恢复和进行中房间进入。
- 条目 `1` 地图投影只显示当前正文、原文定位 `向火独行.pdf#page=4` 和“转到条目 263”。
- 点击出口后显示 `analyzing → awaiting_confirmation`；玩家确认后显示 `queued → resolving → completed` 完整时间线。
- 在 `resolving` 前成功撤回一次已排队行动，时间线记录 `queued → canceled`；随后重新提交并结算。
- 最终房间状态为 `current_scene='solo:263'`、`visited_scenes=['solo:1','solo:263']`、`state_version=1`；玩家地图显示条目 `263`、其原文 citation 和唯一出口条目 `8`。
- 本轮已在对话中附上最终移动端验收截图。活动模型的草稿分析约为 13–14 秒；阶段状态持续可见，但这不是性能基准测试结果。

## 验证

```text
python -m pytest tests/server -q
747 passed in 658.77s

cd src/client && npm run test
14 files / 39 tests passed

cd src/client && npm run build
TypeScript 检查与 Vite 生产构建通过
```

已额外执行 `git diff --check`，用于确认补丁没有空白错误。

## 边界

- 本轮仅处理已授权的本地原版黄金素材；不向 Host 或 Player 下发完整规则原文。
- 浏览器夹具使用本地临时账号、房间和数据库记录，仅用于验收；生产数据不受修改。
- 多人性能、弱网和跨剧本隔离仍由既有 V2 回归覆盖，不把本轮单人原版验收误报为完整性能结论。
