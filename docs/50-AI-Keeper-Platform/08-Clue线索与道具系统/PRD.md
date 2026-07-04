# Clue 线索与道具系统 PRD 初版

## 目标

提供线索和道具的发现、归属、分享、可见性和证据链能力，保证调查玩法可追溯且不剧透。

## 范围

包含线索库、发现状态、归属、私密线索、主动分享、道具所有权、可见性、来源和投放记录。不包含高级推理板 UI、AI 自动解谜和复杂物品经济。

## 角色

| 角色 | 权限 |
|---|---|
| 玩家 | 查看自己线索、分享线索、管理笔记。 |
| Engine | 授予线索、转移道具、记录事件。 |
| AI KP | 建议线索投放和公共摘要。 |
| 房主 | 查看公共线索板和必要诊断。 |

## 用户故事

| 编号 | 用户故事 | 优先级 |
|---|---|---:|
| CLUE-1 | 作为玩家，我能获得只属于我的私密线索。 | P0 |
| CLUE-2 | 作为玩家，我能主动分享线索给团队。 | P0 |
| CLUE-3 | 作为系统，我不会把未发现线索展示给玩家。 | P0 |
| CLUE-4 | 作为长团玩家，我能追溯线索来源。 | P1 |

## 数据边界

线索有 truth source、discovery state、owner audience、public summary、source event、related NPC/location/event、importance。道具有 owner、visibility、effect、consumable state。所有变更进入事件日志。

## 接口 / 事件方向

- REST：查询线索、分享线索、查询道具、使用道具、绑定笔记。
- Event：`clue_discovered`、`clue_shared`、`item_gained`、`item_used`、`clue_visibility_changed`。
- Projection：私密线索投给 owner，分享后投给 party。

## 验收标准

- 私密线索默认只对拥有者可见。
- 分享后生成团队可见版本。
- 未发现线索不会被 AI 或查询接口泄露给玩家。
- 线索和道具变化都能追溯来源事件。

