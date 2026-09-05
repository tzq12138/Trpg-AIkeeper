# PRD-10 - Player 背包与线索软木板

**版本**: 1.0  
**状态**: 待开发  
**来源**: Player 模块 4、PRD-07、PRD-09  
**适用范围**: InventoryPanel、CorkboardView、Item/Clue Store

## 1. 背景

COC 的核心体验是调查与信息不对称。Player 端背包和线索板必须从 Engine 权威状态同步，不能由私密通知直接改本地数据。通知告诉玩家“发生了什么”，snapshot/patch 才是状态事实。

## 2. 目标

- 展示玩家自己的物品和已解锁线索。
- 物品使用/展示统一提交意图。
- 线索软木板位置稳定，不因新增线索跳动。
- 用详情 Modal 替代 alert。

## 3. 范围边界

**包含**
- `inventory`、`clues` Store 字段。
- `InventoryPanel` 物品列表与 bottom sheet。
- `CorkboardView` 线索卡片和缩放平移。
- 物品 `use_item` / `show_item` 意图。

**不包含**
- 线索关系自动推理。
- 拖拽编辑线索位置。
- 物品合成或装备系统。

## 4. 用户故事

| ID | 用户故事 | 优先级 |
|---|---|---|
| US-10-1 | 作为玩家，我需要随时查看自己拥有的物品和私密描述。 | P0 |
| US-10-2 | 作为玩家，我需要把物品用于场景或展示给队友。 | P0 |
| US-10-3 | 作为调查员，我需要线索板新增线索时旧线索位置不要跳变。 | P1 |

## 5. 功能需求

1. `inventory` 和 `clues` 仅由 `s2c_full_snapshot` 或 `s2c_state_patch` 更新。
2. `s2c_private_notice` 只负责通知，不直接插入 item/clue。
3. 背包以网格展示物品，秘密物品可有视觉标识。
4. 点击物品打开详情 bottom sheet，展示名称、描述、可用动作。
5. “尝试使用”提交 `intentType='use_item'`，params 包含 `itemId`。
6. “展示给队友”提交 `intentType='show_item'`，params 包含 `itemId`。
7. 软木板 `getPosition` 必须基于 `clue.id` 确定性散列。
8. 点击线索打开详情 Modal，不使用 alert。
9. 线索板支持基础缩放和平移。

## 6. 接口/事件依赖

| 类型 | 名称 | 用途 |
|---|---|---|
| Event | `s2c_full_snapshot` | 全量物品/线索 |
| Event | `s2c_state_patch` | 增量物品/线索 |
| Event | `s2c_private_notice` | 获得提示 |
| REST | `POST /api/player/intent` | 使用/展示物品 |
| Intent | `use_item` / `show_item` | 物品交互 |

## 7. 状态与错误处理

- actionState 非 IDLE 时物品动作按钮禁用。
- itemId 不存在时关闭详情并提示状态已更新。
- clue type 未知时使用默认样式。
- clue.id 为空的数据视为协议错误，不渲染。
- patch 更新 inventory/clues 时可采用全量替换，避免复杂数组 patch 错位。

## 8. 验收标准

- 私密通知不会单独改变背包或线索数组。
- 新增线索后已有线索位置保持不变。
- 使用/展示物品均走 `submitIntent`。
- 所有详情展示使用 Modal/bottom sheet。
- 背包和线索来自 Store 单一数据源。

## 9. 测试场景

1. 快照下发 3 个物品和 2 条线索，两个面板正确展示。
2. 私密通知到达但无 patch，背包数量不变。
3. 新增 clue 后旧 clue 的 `transform` 不变。
4. 点击“展示给队友”，提交 `show_item` 意图。

## 10. 风险依赖

- 线索板布局若后续支持手动拖拽，需要迁移位置存储。
- `react-zoom-pan-pinch` 或同类库需要移动端手势验证。
- 秘密物品是否可展示给队友需 Engine 决策。

