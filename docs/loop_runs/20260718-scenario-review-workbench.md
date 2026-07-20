# 剧本导入与 AI 备团审核台验收记录

## 本次范围

- 管理员从任意剧本版本创建独立的 `draft_review` 审核草稿；原版本、已发布版本和房间快照不被直接修改。
- 质量报告输出稳定问题代码、阻塞标记、目标类型和修复提示。
- 核心完整性问题（场景、NPC、线索、真相、结局、剧透边界等）不能豁免；非核心项只能以“无须适用 + 必填理由”关闭。
- 管理端审核步骤默认显示完整性待办，并提供“原文 + AI 备团”和“剧情时间线”视图。
- 原件通过管理员专用接口读取；PDF/图片优先显示原件，无法读取时显示已提取文本。
- AI 可对单个问题找证据起草，或整本重读；所有结果都是待确认候选，管理员显式采用后才进入草稿，再由重编译写入备团包。
- 发布入口拒绝存在核心审核问题的审核草稿。

## 自动化证据

| 验证 | 结果 |
| --- | --- |
| `python -m pytest tests/server/test_scenario_review_workbench.py tests/server/test_quality.py tests/server/test_scenario_import_workflow.py tests/server/test_module_compiler.py tests/server/test_ai_gateway.py -q` | 73 passed（58.60s） |
| `npm run test -- --run ScenarioReviewWorkbench.test.ts` | 1 passed |
| `npm run build` | 通过，包含 TypeScript 检查与 Vite 构建 |
| `npm run test` | 82 passed / 1 failed；失败项为既有 `CampaignHomePanel` 断言仍期待“1 个可选方向”，实际页面已是开放式“继续当前场景”。本次审核台测试通过。 |
| `python -m pytest tests/server -q` | 6 分钟无输出后超时终止；不能作为全量通过证据。 |

## 浏览器验收状态

首次尝试访问 `http://127.0.0.1:5186/admin` 时得到 `ERR_CONNECTION_REFUSED`。后续启动后的 `:5173` / `:3001` 虽可登录，但实际运行的是另一个旧工作区：前端源码不含 `ScenarioReviewWorkbench`，后端 OpenAPI 也不含 `review-workbench` 接口。因此本次没有把旧页面截图或人工点击误标为本分支的验收。

服务启动后，建议按以下路径做人工验收：

1. 使用管理员账号进入“后台 → 剧本 → 2. AI 编译与审核”。
2. 选择现有剧本版本，点击“从此版本创建审核草稿”。
3. 在“完整性待办”打开一个核心问题，确认没有“不适用”操作。
4. 在“原文 + AI 备团”核对 PDF/图片原件和页面解析文本；点击“AI 找证据并起草”，确认候选不会自动写入。
5. 采用一个带 `source_part_id` 的候选或填写“管理员补写”理由，点击“重编译并复查”。
6. 返回“完整性待办”确认问题状态更新；验证未修复核心问题时发布被拒绝。
7. 对非核心问题填写理由标记为不适用，确认理由仍可见且不会解除核心门禁。
