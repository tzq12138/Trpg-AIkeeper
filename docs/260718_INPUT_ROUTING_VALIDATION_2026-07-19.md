# 260718 输入分流与私密资料验收记录（2026-07-19）

## 本批范围

- `speech`、`party_chat`、`ooc`、`rule_question`、`private_note` 与 `safety` 不创建正式 Action，也不进入规则或世界状态。
- 私密笔记加密写入 `player_notes`，并由玩家资料页的“我的笔记”入口创建、回看与编辑；编辑仅允许笔记所有者修改私密原件。
- 私密线索共享必须填写队伍摘要；原线索保持私密，队伍读取公开副本。
- 通用行动输入框不提供“分享线索”；未经选定具体线索的 `clue_share` 请求会被拒绝。
- 安全请求正文只加密保存在提交记录中；`s2c_safety_request` 仅向 Host 发送请求与角色标识，Host 控制台经授权读取正文，其他玩家、公共舞台、AI 与世界状态均不接收正文。

## 自动化证据

| 命令 | 结果 | 覆盖 |
| --- | --- | --- |
| `python -m pytest tests/server/test_action_drafts_v2.py tests/server/test_clues.py tests/server/test_channel_messages.py tests/server/test_host.py tests/server/test_events.py -q` | 108 passed | 角色发言/OOC/队聊事件、规则问题所有权、私密笔记加密、通用线索分享拒绝、私密线索公开副本、Safety Event 无正文投递、Host 解密读取与事件注册 |
| `python -m pytest tests/server/test_campaign_v2.py::test_private_note_is_encrypted_and_only_visible_to_its_owner tests/server/test_campaign_v2.py::test_owner_can_edit_private_note_without_mutating_shared_copy_or_events -q` | 2 passed | 私密笔记仅所有者可读、编辑后仍为密文、更新不产生事件且不会改写队伍脱敏副本 |
| `npm run test -- --run tests/player-input-modes.test.ts tests/player-action-composer.test.tsx tests/player-inventory.test.tsx tests/team-message.test.ts tests/host-stage.test.ts` | 21 passed | 安全请求的私密发送文案、输入模式标签、正式行动忙碌时的非状态输入、资料页笔记入口与创建控制、频道标签和 Host 安全请求面板 |
| `npm run test -- --run tests/player-api.test.ts tests/player-inventory.test.tsx` | 13 passed | 私密笔记编辑的客户端 `PATCH` 契约与资料页入口 |
| `python -m pytest tests/server/test_action_drafts_v2.py tests/server/test_player_action_settings_v2.py -q` | 73 passed | 默认角色发言仅写队伍频道；房主切换 `npc_dialogue` 后不创建队伍消息、改走草稿分析；玩家设置可读取房间策略 |
| `npm run test -- --run tests/player-input-modes.test.ts tests/player-api.test.ts` | 17 passed | 发言模式的默认记录文案与“对话预览”文案、忙碌期限制及客户端设置契约 |
| `python -m pytest tests/server/test_action_lifecycle_v2.py -q` | 13 passed | 结算包写入权威状态版本，玩家回执关联 `transaction_id` 与 `state_version` |
| `python -m pytest tests/server/test_archive.py -q` | 15 passed | “剧情”筛选支持已释放结算包；自己的结果/citation/状态版本可见，其他玩家只见已过滤叙事，`ready` 包不出现 |
| `python -m pytest tests/server/test_host.py -q -k 'restore_preserves_active or host_ack_releases_only'` | 2 passed | Host 状态重建保留活动事务、当前步骤和延迟事件；错误事务 ACK 不释放事件 |
| `npm run build` | passed | TypeScript 与 Vite 生产构建 |

## 浏览器证据

- 当前工作区前端 `http://127.0.0.1:5175/player/6c4a2468` 已显示十种输入类型，其中包含“场外信息”和安全边界，并且不再显示“分享线索”。
- 该测试房的玩家凭证已失效，页面明确显示“请重新从邀请链接进入房间”；本轮未用失效身份发送任何真实消息。
- 因此浏览器只确认了 UI 暴露；真实 WebSocket 投递与两名玩家可见性仍应在有效测试房中补做。

## 未覆盖项

- 私密笔记的分享和附件操作仍使用既有 API；资料页本批已补创建、回看与编辑入口。
- `speech` 默认只作为队伍可见的非状态频道；房主显式设置 `npc_dialogue` 后才进入草稿→确认→对话裁决。该分流尚未在有效浏览器测试房中完成真人演练。
- 实际公开副本由资料页中选定具体线索后创建；通用输入框不会伪造分享成功。
- 玩家日志的结算包筛选已自动化验证；尚未在真实浏览器测试房逐项检查剧情、行动、线索、检定和依据五种筛选视图。
- 安全请求尚未在有效浏览器测试房中验证 Host 的实时提示、其他玩家不可见与公共舞台不可见；自动化已覆盖事件负载不含正文和 Host 授权读取。
- `test_image_map_returns_visible_regions_and_safe_token_projection` 当前可独立复现 `baseAsset` 为 `{}` 的失败，与本批笔记路径无交集；未在本批修改地图逻辑。
