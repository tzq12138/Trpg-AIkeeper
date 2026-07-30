# CoC 7 版规则与《玻璃雨夜》V2 验收记录

日期：2026-07-30

## 结论

本轮按 `G:\hermes-agent-workplace\D&D\COC\COC7th核心规则书v1.2.1.pdf` 校对了 M0 固定模组会实际触发的 CoC 7 版核心规则，并修正了规则执行器、行动管线、战斗反应、追逐和 SAN/疯狂运行态。`《玻璃雨夜》` 已升级为最新 V2、AI-only 的黄金样本；房间运行态在结局时归档，新房间从干净状态开始。

这里的“通过规则书校对”限定为下表列出的 M0 核心范围，不表示平台已经实现整本 CoC 7 版规则。

## 规则书核对矩阵

规则书页码同时列出 PDF 页码和书内印刷页码；本记录只转述规则，不复制规则书原文。

| 范围 | 核对页 | 修正后的权威行为 | 主要实现 | 回归证据 |
| --- | --- | --- | --- | --- |
| 对抗检定 | PDF 76 / 印刷 68 | 先比较成功等级，再比较双方技能值；完全相同才重掷。失败也按同一比较链结算，不再把平手交给 Host。 | `src/server/rules/coc_handlers.py` | `test_coc7_rulebook_regressions.py` |
| 幸运与团体幸运 | PDF 75、83 / 印刷 67、75 | 团体幸运检定使用当前场景参与者中的最低 Luck；推动检定、失败后花费 Luck 等限制由 Engine 校验。 | `src/server/rules/coc_handlers.py`、`src/server/engine/resolution_pipeline.py` | `test_coc7_rulebook_regressions.py`、`test_coc7_core_rules.py` |
| 战斗顺序与行动 | PDF 85 / 印刷 77 | 按 DEX 降序；已准备枪械使用 DEX+50；每轮一次主要行动；掩体可消耗下一次攻击机会。 | `src/server/combat_round_planner.py`、`src/server/rules/encounter_handlers.py` | `test_combat_round_planner.py`、`test_coc7_rulebook_regressions.py` |
| 近战反应 | PDF 86 / 印刷 78 | NPC 近战攻击立即等待玩家选择闪避或反击；双方按 CoC 对抗等级结算；战斗检定不允许推动。该机制不再只写死给黑熊。 | `src/server/engine/solo_combat_reactions.py`、`src/server/engine/resolution_pipeline.py` | `test_coc7_rulebook_regressions.py`、`test_solo_adventure_runtime.py` |
| 追逐速度与移动行动 | PDF 115–117 / 印刷 107–109 | 根据 MOV 差计算移动行动；移动、障碍和追逐动作由 Engine 结算；追逐检定不允许推动。 | `src/server/rules/encounter_handlers.py` | `test_coc7_rulebook_regressions.py` |
| SAN 损失与疯狂 | PDF 75、133–138 / 印刷 67、125–130 | 大失败按当前 SAN 检定目标的阈值判定并取最大损失；单次损失 5+ 触发 INT 检定；同一游戏日累计损失达到当日起始 SAN 的 1/5 触发不定性疯狂；SAN 0 进入永久疯狂。发作、潜在疯狂、再次触发和持续时间均是结构化状态。 | `src/server/rules/coc_handlers.py`、`src/server/engine/rule_executor.py`、`src/server/engine/resolution_pipeline.py` | `test_coc7_rulebook_regressions.py`、`test_rule_executor.py` |
| 疯狂表现与背景变化 | PDF 135–138 / 印刷 127–130 | AI 只能选择结构化症状 ID；危险表现进入安全替换流程，失败一次后使用确定性安全结果；不保存自由文本症状。背景变化必须等待玩家确认。 | `src/server/rules/coc_handlers.py` | `test_coc7_rulebook_regressions.py` |
| SAN 0 与局后 | PDF 133–138 / 印刷 125–130 | SAN 0 的调查员转为 AI 控制并记录永久疯狂；结局档案保存角色 SAN 结果，可改用备用调查员。新房间不会继承该运行态。 | `src/server/campaign_archive.py`、`src/server/engine/resolution_pipeline.py` | `test_coc7_rulebook_regressions.py`、`test_glass_rain_golden_flow.py` |

## 额外修正

- 技能检定的大失败阈值现在使用实际难度目标，而不是未经难度调整的基础技能值。
- 推动检定失败后的后果由 Engine 直接结算，不再退回 Human Host。
- 剧本运行包的 `runtime_policy` 和 `rule_triggers` 会被编译并注入行动管线。
- 触发器会校验配置中声明的全部条件字段；非阻塞 SAN 触发不会取消原本的移动行动。
- AI 建议的 SAN/疯狂原始文本或越权状态变更会被拒绝，权威状态只由规则执行器写入。
- 未注册的规则类型会明确拒绝，不再静默落入 Host 兜底。

## 《玻璃雨夜》V2 黄金流程

黄金模组位于 `data/golden_modules/02-short-team-glass-rain/module.json`，其运行合同为：

- `runtime_version = v2`
- `session_mode = ai_only`
- `state_scope = room_run`
- `archive_on_end = true`
- `fresh_state_on_new_room = true`

自动化全流程从真实 API 入口安装模组、创建房间、加入两名预设调查员并开局，覆盖：

1. AI 在权威提交前不可用时走确定性降级，不创建 Human Host 例外。
2. 玩家移动到蓄水池并触发非阻塞 SAN 检定。
3. 安全暂停不公开触发者；暂停期间行动被挂起；只有触发玩家可以恢复。
4. 成功路线取得维护无线电并归档 `victory`。
5. 新房间从干净运行态开始，取得重启日志后归档 `mixed`。
6. 再建新房间触发安全暂停，由桌务协助者结束并归档 `safe_abort`。
7. 三个档案互不复用 SAN/疯狂运行态。

对应测试：`tests/server/test_glass_rain_golden_flow.py`。

## 管理后台回归

同一轮还修复了管理后台房间显示和四类批量删除：

- 房间详情具备加载、成功、失败和重试状态，并防止快速切换时旧请求覆盖新选择。
- 桌面为列表/详情双栏，窄屏纵向堆叠；详情恢复紧凑白底布局。
- 房间、剧本、角色、账号统一为“卡片点击查看，复选框选择删除”。
- 前后端都要求显式确认；请求使用 `POST /api/admin/{entity}/batch-delete` 和 `{ ids, confirm: true }`。
- 响应逐项区分删除成功、未找到、依赖阻止和系统错误，前端只移除实际删除成功的 ID。
- 房间和角色使用真实外键链清理；账号保留 AI 配置审计，并阻止删除仍拥有房间的账号；被房间引用的剧本继续禁止删除。

## 明确未实现的范围

以下规则没有被 `《玻璃雨夜》` M0 主链调用，本轮保持“明确不支持”，而不是用 Human Host 静默兜底：

- 全套枪械连发、弹药、故障、穿透和掩体矩阵。
- 完整追逐障碍、载具、碰撞与随机事件表。
- 幕间成长、职业与信用评级的完整经济规则。
- 魔法、克苏鲁神话典籍和怪物专属规则。

这些范围若进入后续模组，应先增加结构化规则处理器和对应规则书回归测试，再允许发布该模组。

## 验证记录

### 自动化

- 后端全量：`python -m pytest tests/server -q` → `1246 passed, 1 warning`，耗时 `1905.88s`。唯一警告为第三方 `starlette.testclient` 的弃用提示。
- 管理后台批量删除定向集成测试：`tests/server/test_admin_bulk_delete.py` → `16 passed`。
- 战斗依赖、SAN 阈值和行动管线定向回归 → `51 passed`。
- 《玻璃雨夜》黄金流程：`tests/server/test_glass_rain_golden_flow.py` → `1 passed`。
- 前端全量：`npm run test -- --run` → `45` 个测试文件、`173 passed`。
- 前端生产构建：`npm run build` → TypeScript 检查与 Vite 构建通过。
- 静态验证：`python -m compileall -q src/server` 与 `git diff --check` 通过；后者只有 Windows 工作区的 LF/CRLF 转换提示，没有空白错误。

### 真实浏览器与本地服务

- 初次复现 `Failed to fetch` 时，`127.0.0.1:5173` 与 `127.0.0.1:3001` 均未监听；启动 `python dev.py` 后，`python dev.py --check` 显示数据库、前端、RAG 和编译器健康检查总体为 `ok`。
- 在 `http://127.0.0.1:5173/admin` 实测房间详情的桌面双栏和 `620×900` 窄屏堆叠，加载状态、详情内容、状态按钮及房主/玩家入口均可见。
- 房间、剧本、角色、账号四页均实测选择计数、批量删除入口、第二次确认按钮与取消按钮。
- 创建一次性账号 `codex_delete_probe_7ae6168d`（ID `02ce60f3`），在账号页通过复选框选择并完成真实批量删除；页面返回 `成功删除：02ce60f3`，刷新后账号不再存在。未删除任何既有业务数据。
- 最终重新启动服务后，再次在账号页选择首项，确认页面显示 `请确认后再执行删除`、`确认删除（1）` 与 `取消`；随后取消并清空选择，未删除该账号。浏览器控制台错误/警告为空，页面以“已选择 0 个账号、批量删除禁用”的安全状态保留。
