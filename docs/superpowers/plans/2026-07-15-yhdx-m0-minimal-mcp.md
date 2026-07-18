# 《向火独行》M0 最小 MCP 与单人通关计划

## 目标

在不改动既有未提交产品文档的前提下，使《向火独行》以单个调查员走完可信的 AI KP 主链：自然语言行动、确定性裁决、叙事、战斗/理智、结局与可恢复回执。输出可复现的浏览器验收记录。

## 运行契约

- MIMO 后台活动配置是首选 AI 运行提供方；不从前端、日志或报告读取密钥。
- 本地 MCP 仅由 DeepSeek 用户级环境变量启动，并只作为兼容/备用 AI 适配器。
- MCP 只暴露四个工具：`kp_structure_scenario`、`kp_analyze_director_action`、`kp_narrate_action`、`kp_health_check`。
- Engine 是状态唯一写入者；MCP 与 MIMO 只能返回结构化候选，不能直接修改房间、角色、遭遇或结局。

## 实施切片

1. 为四个 MCP 工具、DeepSeek 环境加载和未映射任务建立失败测试。
2. 收敛 MCP 服务与客户端映射，并为 Director/Narrator 提供与现有 DTO 相容的结构化提示。
3. 以真实 DeepSeek MCP 健康检查和 MIMO 主提供方验证回退顺序与密钥不泄漏。
4. 创建全新《向火独行》单人房间，浏览器执行开局、自然语言调查、确认、战斗/理智、结局和刷新恢复。
5. 记录截图、API/事件证据、失败项与复现方式到 `docs/loop_runs/`。

## 验收标准

- MCP 的工具清单精确为四项；旧的直接裁决工具不可再经 MCP 调用。
- `analyze_director_action` 与 `narrate_action` 均可通过 MCP 返回可验证 JSON；无密钥、超时或上游失败时返回受控失败并走现有回退。
- 《向火独行》使用已发布 `RuntimePackageVersion`，至少具备一个角色模板、确认素材绑定、语义场景和结局条件。
- 浏览器新建单人房间，从开局到一个合法结局的每一步都走自然语言行动链；地图仅为投影，不显示条目号或可跳转编号。
- 报告如实标注未通过项；不把接口或数据库检查写成浏览器截图证据。

## 验证命令

```powershell
python -m pytest tests/server/test_kp_mcp_config.py tests/server/test_kp_mcp_brain.py tests/server/test_ai_providers.py tests/server/test_director_runtime.py tests/server/test_narrator_runtime.py tests/server/test_solo_adventure_runtime.py -q
cd src/client; npm run test -- --run
cd src/client; npm run build
git diff --check
```
