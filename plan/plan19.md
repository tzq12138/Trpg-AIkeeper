# 修复 Host 日志 / 地图串页

## Summary
- 修复 Host 舞台中 `日志` 和 `地图` tab 渲染同一 UI 的问题。
- 不改后端 API；复用已有 Host 地图接口 `/api/host/{room_id}/map/full`。
- 保持 Bauhaus 风格，让地图页有自己的 Host 监督视图，而不是日志兜底页。

## Key Changes
- 将 `HostSkeletonPanels` 改成显式分支：
  - `combat` 渲染遭遇/追逐面板。
  - `database` 渲染资料库骨架。
  - `logs` 渲染 `HostLogsPanel`。
  - `map` 渲染新的 `HostMapPanel`。
  - 未知 tab 只显示“面板未配置”，不再默认显示日志。
- 新增 `HostMapPanel`：
  - 拉取 `/api/host/{room_id}/map/full`。
  - 有地图时展示节点、连接、玩家位置、已探索/隐藏状态。
  - 无地图或 404 时显示“当前房间未初始化地图”，不能显示日志 UI。
  - 支持最小 Host 操作：揭示/隐藏节点；如已有角色位置数据，则支持选择角色强制移动。
- Host 舞台收到 `s2c_map_updated`、`s2c_player_moved`、`s2c_map_revealed` 后刷新地图面板；如果当前不在地图 tab，只更新内部刷新计数，不强行切页。
- 地图和日志视觉要明显不同：
  - 日志页：时间线、筛选、导出、检查点。
  - 地图页：节点图、玩家位置、节点详情、可见性控制。

## Test Plan
- 前端构建：在 `src/client` 跑 TypeScript/Vite build。
- 手动验收：
  - 进入 `/host/{roomId}/stage`。
  - 点击 `日志`，看到事件时间线和检查点。
  - 点击 `地图`，看到地图面板或“未初始化地图”空状态。
  - 在无地图房间里，地图页不能出现日志筛选/导出/检查点 UI。
  - 地图事件发生后，地图面板能刷新玩家位置或节点状态。
- 回归检查：
  - `传说` 投影不变。
  - `追逐` 面板不变。
  - `资料库` 面板不变。
  - 右侧调查员监控仍正常显示。

## Assumptions
- 后端 Host 地图接口已存在并可用：`/api/host/{room_id}/map/full`。
- 本轮只修 Host 地图页展示和基础监督操作，不做完整地图编辑器。
- 玩家端地图暂不改，除非发现它也有同类 tab 串页问题。
