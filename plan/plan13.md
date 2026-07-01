# 修复剧本选择、剧本导入入口与房间按钮中文化

## Summary
- 图一 Host 大厅补“选择剧本”区域：房间未开始时可从已导入剧本中选择并保存到房间。
- 图二 Admin 剧本页补“添加/导入剧本”按钮：支持上传 PDF，导入完成后刷新列表并自动选中新剧本。
- 图三房间详情按钮和状态统一中文化：状态值、状态切换按钮、入口按钮都显示中文，不再裸露 `draft/lobby/active` 等英文。

## API / Interfaces
- 新增或固化 Host 可用接口：
  - `GET /api/rooms/{room_id}/scenario-options`：使用 `X-Owner-Token` 或管理员账号鉴权，返回 `{ scenarios: [{ scenario_id, title, import_status }] }`。
  - `PATCH /api/rooms/{room_id}/scenario`：使用 `X-Owner-Token` 或管理员账号鉴权，body 为 `{ scenario_id }`；仅允许 `draft/lobby/paused` 房间修改，`active/completed/archived` 返回 409。
- 修正 `/api/rooms/{room_id}` 返回：增加 `scenario_title`，避免前端再用 import-job 端点猜标题。
- Admin 继续复用现有 `POST /api/admin/scenarios/import-pdf`，前端用 `multipart/form-data` 上传，不手动设置 `Content-Type`。

## Key Changes
- `HostLobby`
  - 剧本卡片改成可操作区域：显示当前剧本、选择框、保存按钮、刷新按钮。
  - 未选择剧本时显示“未选择剧本”，并提示“请先选择剧本再开始游戏”。
  - `开始游戏` 按钮禁用条件改为：无玩家、仍有玩家未准备、未选择剧本时都禁用，并显示对应原因。
  - 选择保存成功后更新本地 `room.scenario_id/scenario_title`，刷新大厅展示。
- `AdminDashboard` 剧本页
  - 标题右侧新增黄色主按钮“导入剧本 PDF”。
  - 上传时显示“导入中...”，成功后刷新剧本列表、选中新剧本、清空错误。
  - 剧本为空时显示空状态：“还没有剧本，点击导入剧本 PDF 开始”。
  - 导入失败显示中文错误，不吞异常。
- `AdminDashboard` 房间页中文化
  - 建立统一映射：`draft=草稿`、`lobby=大厅等待`、`active=进行中`、`paused=已暂停`、`completed=已完成`、`archived=已归档`。
  - 房间列表、详情状态、状态切换按钮都使用中文 label，内部提交仍使用英文状态值。
  - `ROOM DETAIL` 改为“房间详情”，`Host 舞台` 改为“房主舞台”，`Player 入口` 改为“玩家入口”。
  - 玩家状态 `joined/active/pending_approval/removed` 等也做中文展示。
- 保持现有 Bauhaus/Neo-Brutalist 样式，不引入新 UI 库，不重做页面布局。

## Test Plan
- 后端测试：
  - 房主 token 可获取剧本选项、可在 lobby 绑定剧本。
  - 非房主不能修改剧本。
  - active/completed/archived 房间修改剧本返回 409。
  - `/api/rooms/{room_id}` 返回 `scenario_title`。
- 前端构建：`src/client` 跑 TypeScript/Vite build。
- 手动验证：
  - Admin 剧本页能看到“导入剧本 PDF”，上传后列表出现剧本。
  - Host 大厅能选择剧本，保存后“未选择剧本”变为剧本名。
  - 未选择剧本时不能开始游戏。
  - 房间管理详情页所有状态按钮显示中文，点击后状态正常更新。
  - 房主舞台/玩家入口链接仍可打开。

## Assumptions
- Host 大厅选择剧本只允许开局前修改，避免进行中房间换剧本污染状态。
- “加入剧本按钮”按“导入/添加剧本 PDF”理解。
- 剧本导入仍以 PDF 为主，本轮不新增手工创建空剧本表单。
