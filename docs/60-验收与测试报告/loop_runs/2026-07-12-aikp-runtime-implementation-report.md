# AI KP 剧本编译与人类化主持运行时实施验收报告

日期：2026-07-12

## 结论

- 已完成 `Module Compiler + Director + Narrator` 主链路、结构化契约、数据库增量结构、发布门禁、玩家叙事页、安全地图投影、Host 只读导演台和 V2 切换工具。
- 《向火独行》已重新编译为可发布运行包；运行时使用固定快照，不在每回合重新解释整份原文。
- 浏览器已完成登录、建房、建卡、准备、开局、自然语言行动、失败恢复、刷新恢复和地图投影验收。
- 确定性测试与构建全部通过；真实图文供应商和第二套纯文本供应商验收仍受本机活动配置 `key_unavailable` 阻塞。

## 主要实现

### Module Compiler

- 新增不可变 `RuntimePackageVersion`，编译事实世界书、故事证据节点、语义推进规则、角色物品、地图语义、结局、引用和质量异常。
- 图片必须绑定到场景、NPC、物品、线索或地图区域；未绑定素材阻止发布。
- 发布门禁校验 citation、矛盾、规则版本、权限、分支可达性、结局完整性和素材绑定。
- 新增运行包预览、异常确认、发布和指定版本重编译接口。

### Director 与 Narrator

- Director 只输出结构化计划；状态补丁继续由确定性规则执行器验证和应用。
- 低置信、多义、证据不足和供应商失败进入追问、恢复或 Host 异常队列，不生成伪叙事。
- Narrator 只演绎已验证结果，拒绝额外状态修改、编号条目泄露和无依据事实。
- 新增 `ai_stage_changed`、`player_clarification_required`、`director_plan_validated`、`narration_completed`、`ai_recovery_required` 事件及前端阶段展示。

### 玩家与 Host

- 玩家主界面改为叙事对话流、判定/回执、自然语言行动和响应式辅助面板。
- 行动灵感只填充可编辑示例，不自动提交。
- 地图仅为只读状态投影；移动必须走自然语言行动链。
- Host 舞台改为只读导演台，显示当前场景、事实、待触发条件、风险和异常队列。

## 《向火独行》黄金模组

- `ScenarioVersion`：`85c70458-0d96-40e0-87b0-77c21af6853f`
- `RuntimePackageVersion`：`5ddbfe70-0d22-458c-8f8e-7d494c6b7daf`
- 编译结果：`ready`，异常 `0`，故事证据节点 `301`，citation `124`。
- 浏览器验收房间：`bcf79e68`；调查员：`林烬验收`，HP `11`，SAN `55`。

## 六类样本矩阵

| 样本 | 结果 |
| --- | --- |
| 文本 PDF《向火独行》 | 57 parts，65,303 chars |
| 图片/扫描样本 | 1 part，多模态待供应商理解 |
| DOCX | 300 parts，15,397 chars |
| Handouts | 3 parts，5,099 chars |
| 规则资料 | 186 parts，170,870 chars |
| XLSX 角色卡 | 67 skills，HP 10，SAN 70 |

旧式 `.doc` 未进入支持范围；扫描覆盖使用图片样本完成。

## 浏览器发现并修复

1. 行动灵感接口前端使用 GET、后端只接受 POST，导致 `405`；已改为 POST，并增加前端回归测试。
2. `ai_recovery_required` 到达后只更新阶段条，没有回读权威回执，页面会停在 `queued/directing`；已在恢复事件中刷新回执和行动状态。
3. 战役首页显示“条目 1”和“条目 1 场景图”；已改为“当前场景”和“当前场景插图”。
4. 玩家地图泄露“条目 1”和“转到263”；已在服务端地图投影层清洗编号标题和跳转指令，浏览器复验均为 `false`。

截图：

- `2026-07-12-aikp-narrative-390.png`
- `2026-07-12-aikp-composer-390.png`
- `2026-07-12-aikp-narrative-360.png`
- `2026-07-12-aikp-action-recovery.png`
- `2026-07-12-aikp-semantic-map-clean.png`

## V2 切换

- 切换 ID：`b531afb4-02c5-4437-945d-0d880c6f15a3`
- 已清理旧房运行状态：13 个房间。
- 备份：`data/backups/v2-cutover/v2-cutover-20260712T061906Z-b531afb4.zip`
- SHA-256：`0ae46b6714901481eb100a3f2e6ba9347b721175eb7abc6f66f43b7756c96879`
- 注意：当前备份覆盖迁移核心数据，不应宣称包含未来新增的每一张运行时表；正式生产切换前仍需执行恢复演练并核对表清单。

## 自动化验证

- `python -m pytest tests/server -q`：819 passed，4 warnings，768.52s。
- `npm run test -- --run`：16 files，54 passed。
- `npm run build`：TypeScript 与 Vite 构建通过。
- `git diff --check`：通过；仅有 Windows 行尾提示，无空白错误。
- 后端 warning 为两处测试构造 dict citation 时的 Pydantic 序列化提示，不影响测试结果，建议后续改成 `RedactedCitation` 实例消除。

## 未完成与阻塞

- 活动供应商 `mimo / mimo-v2.5` 当前为 `key_unavailable`，因此真实图文模型叙事和“双供应商切换”未完成现场验收。
- 当前自然语言调查动作按安全策略进入 `awaiting_host_exception`，没有生成“周围暂时没有新的变化”等伪叙事，刷新后完整恢复 `queued → resolving → awaiting_host_exception` 时间线。
- 尚未完成真实 `1 Host + 4 玩家` 弱网并发浏览器长跑；自动化覆盖多人合并、乱序、重连和权限逻辑，但不能替代真实供应商压力验收。
- 首页和地图仍展示较长的玩家可见场景原文；编号与跳转已清洗。接入有效 Narrator 后应优先展示 AI 演绎摘要，把长原文降级为可展开依据。

## 下一轮验收条件

1. 在管理页保存并测试通过一套图文供应商和一套纯文本备用供应商。
2. 重新执行单人开局至结局，覆盖调查、战斗、理智、伤害和结局 citation。
3. 执行 1 Host + 4 玩家协作/冲突、弱网、重复事件、AI 中断和恢复测试。
4. 对 V2 备份执行独立数据库恢复演练，输出逐表计数和哈希核对结果。
