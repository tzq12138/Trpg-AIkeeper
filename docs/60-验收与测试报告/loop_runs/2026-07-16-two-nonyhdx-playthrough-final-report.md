# 两个非《向火独行》黄金模组通关报告

**测试时间：** 2026-07-16 至 2026-07-17（Asia/Hong_Kong）  
**运行入口：** 隔离后端 `http://127.0.0.1:3008` 的玩家行动 API 端到端链路  
**结论：** 两个非《向火独行》黄金模组均由自然语言行动推进至正式结局；没有使用 Host 强制结局、状态覆盖或手工跳转。

## 范围与限制

- 本次验证的是后端权威行动链：草稿分析、确认、规则结算、语义场景推进、线索持久化、结局判定、叙事降级与恢复 Session。
- 这不是 React 玩家页的浏览器验收；本轮没有启动前端，因此未宣称点击流、移动视口或实际 WebSocket UI 已验收。
- 当前活动的 MIMO 配置在隔离运行时返回 `key_unavailable`，原因是该环境无法解密既有加密密钥。本轮未发送真实 MIMO 请求，也没有读取、记录或导出密钥。
- 因此 AI 调用失败后，运行使用受证据约束的本地 Director / 已验证 Narrator 降级链路；这验证了可恢复性，不替代重新填写 MIMO Key 后的真实模型验收。

## 通关一：玻璃雨夜

| 项目 | 结果 |
| --- | --- |
| 模组 | `golden-golden-team-glass-rain`（《玻璃雨夜》） |
| 测试房间 | `8e674eb2` |
| 最终状态 | `completed`，状态版本 `3` |
| 场景轨迹 | `glass-gate` → `orchid-hall` → `cistern` |
| 结局 | `glass-timeout` |

### 玩家自然语言操作

1. “我沿着湿滑的展廊前往兰花展厅，检查被砸开的标签柜和 G-17 测试表。”
   - 完成；获得线索 `g17-test-sheet`。
2. “我走向地下蓄水池，继续查看阀门平台。”
   - 完成；满足结局条件并进入 `glass-timeout`。

### AI KP / 系统操作

- Director 将玩家的地点名称映射为已发布运行包中的场景边。
- 状态执行器验证前置条件并落库场景访问记录。
- 叙事模型超时后使用当前场景的可见事实生成已验证叙事，没有改写骰点、线索、场景或结局。

## 通关二：雾港失物局

| 项目 | 结果 |
| --- | --- |
| 模组 | `golden-golden-sandbox-lost-property`（《雾港失物局》） |
| 测试房间 | `89237451` |
| 最终状态 | `completed`，状态版本 `4` |
| 场景轨迹 | `lost-property-counter` → `harbor-post` → `ferry-warehouse` → `sorting-room` |
| 结局 | `lost-stop-machine`（`victory`） |
| 结局引用 | `cit-lost-ending-stop` |

### 玩家自然语言操作

1. “我前往港口邮驿站。”
2. “我检查并记录午夜退件路线。”
   - 完成；获得线索 `return-route`。
3. “我前往渡轮仓库。”
4. “我翻查未登记行李，找到并带上地下通道钥匙。”
   - 完成；获得线索 `basement-key`。
5. “我用地下通道钥匙前往旧分拣间。”
6. “我查阅并记录记忆寄存总账。”
   - 完成；获得线索 `memory-ledger`，结局条件成立。

### AI KP / 系统操作

- Director 将自由文本行动对应到语义地图、线索和访问条件，未向玩家暴露后台条目号。
- 每次确认后由确定性执行器应用场景与线索变化；结局由运行包条件和 citation 判定。
- 玩家端轮询等待曾超时，但使用 `restore-session` 后恢复同一角色的服务器权威状态，未重复执行行动。
- 叙事模型调用超时后均使用 `local_fallback`，并保留 `narrator_timeout` 作为被拒绝的上游原因。

## 发现、修复与回归保护

| 问题 | 修复 | 回归覆盖 |
| --- | --- | --- |
| “翻查未登记行李”未被识别为低风险调查 | 补充 `翻查`、`查阅`、`检查` 等调查动词 | 中文物品搜索降级测试 |
| 上游把线索 ID `return-route` 误判为场景目标 | 低风险调查遇到无效语义推进时丢弃该推进并重建本地计划 | 无效 AI 场景目标测试 |
| Narrator 的引用字段违规会阻塞已结算行动 | 仅对 `narrator_fact_violation` 使用已验证本地叙事 | 引用违规降级测试 |
| 场景事实冲突也被错误降级 | `narrator_scene_fact_conflict` 保持进入 Host 异常队列 | 马车/车辆场景矛盾测试 |
| 本地 Director 测试声称走 AI 路由 | 将测试契约改为实际的 `resolution_route=local`，正常上游成功仍为 `ai` | 两条路由区分测试 |

## 待处理风险

1. **P1：响应速度。** 本次已完成行动约为 33–61 秒；主要原因是先等待 30 秒 Narrator 上游超时，再执行本地叙事。需要在真实 MIMO Key 恢复后测量成功路径，并决定是否缩短超时或更早切换降级。
2. **P1：真实模型验收。** 管理页重新输入并保存 MIMO Key 后，需执行图文、纯文本、模型切换和失败回退的浏览器测试；本次没有消费真实 API。
3. **P1：玩家页面验收。** 仍需在实际前端完成两剧本的输入、确认卡、地图投影、叙事流、重连以及 360/390/430px 视口检查。
4. **P2：多人。** 本次是单人通关；尚未覆盖 1 Host + 4 玩家短窗口合并、冲突和弱网恢复。

## 自动化验证

执行命令：

```powershell
python -m pytest tests/server/test_host_room_lifecycle.py tests/server/test_ai_provider_config.py tests/server/test_director_runtime.py tests/server/test_narrator_runtime.py tests/server/test_module_compiler.py tests/server/test_ending_conditions.py tests/server/test_map_draft_v2.py -q
```

结果：`132 passed in 134.28s`。

测试输出保存在本地忽略目录：`.runtime/golden-playthrough-20260716/targeted-regression.log`。
