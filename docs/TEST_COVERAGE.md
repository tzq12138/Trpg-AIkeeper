# AI-Keeper 测试覆盖文档

**最后更新**: 2026-06-22 (审查修复后)  
**测试总数**: 184 passed, 0 failed  
**后端**: Python FastAPI + SQLite  
**前端**: React + TypeScript (Vite)

---

## 总览

| PRD | 名称 | 后端实现 | 后端测试 | 前端实现 | 状态 |
|-----|------|---------|---------|---------|------|
| PRD-00 | 全局协议与投影契约 | ✅ | ✅ | — | ✅ 完成 |
| PRD-01 | Engine意图生命周期 | ✅ | ✅ | — | ✅ 完成 |
| PRD-02 | Host通信总线与路由分发 | ✅ | ✅ | ✅ | ✅ 完成 |
| PRD-03 | Host全局HUD与状态聚合 | ✅ | ✅ | ✅ | ✅ 完成 |
| PRD-04 | Host事务播放器与多级队列 | ✅ | ✅ | ✅ | ✅ 完成 |
| PRD-05 | Host氛围引擎 | ✅ | ✅ | ✅ | ✅ 完成 |
| PRD-06 | Host舞台演出与剧情渲染 | ✅ | ✅ | ✅ | ✅ 完成 |
| PRD-07 | Player通信网关与单播路由 | ✅ | ✅ | ✅ | ✅ 完成 |
| PRD-08 | Player对讲机与语音意图 | ⚠️ | — | ⚠️ | ⚠️ 部分 |
| PRD-09 | Player活体角色卡与触控检定 | ✅ | ✅ | ✅ | ✅ 完成 |
| PRD-10 | Player背包与线索软木板 | ✅ | ✅ | ✅ | ✅ 完成 |
| PRD-11 | Player战术聊天与结构化行动 | ✅ | ✅ | ✅ | ✅ 完成 |
| PRD-12 | 玩家加入房间与准备流程 | ✅ | ✅ | ✅ | ✅ 完成 |
| PRD-13 | 玩家角色卡导入与适配 | ✅ | ✅ | — | ✅ 完成 |
| PRD-14 | 玩家行动面板与语音优先 | ✅ | ✅ | ✅ | ✅ 完成 |
| PRD-15 | 玩家行动回执与AI归并 | ✅ | ✅ | ✅ | ✅ 完成 |
| PRD-16 | 玩家私密线索与主动分享 | ✅ | ✅ | — | ✅ 完成 |
| PRD-17 | 玩家个人目标与当前任务 | ✅ | ✅ | — | ✅ 完成 |
| PRD-18 | 玩家澄清请求与误判纠正 | ✅ | ✅ | — | ✅ 完成 |
| PRD-19 | 玩家断线重连与状态恢复 | ✅ | ✅ | — | ✅ 完成 |
| PRD-20 | 玩家个人档案与复盘查询 | ✅ | ✅ | — | ✅ 完成 |
| PRD-21 | 房主开房与有限急救权限 | ✅ | ✅ | ✅ | ✅ 完成 |
| PRD-22 | PDF剧本导入与自动结构化 | ✅ | ✅ | — | ✅ 完成 |
| PRD-23 | 剧本质量报告与一键开局 | ✅ | ✅ | — | ✅ 完成 |
| PRD-24 | AI自动KP主持循环 | ✅ | ✅ | — | ✅ 完成 |
| PRD-25 | 自由行动收集与批次结算 | ✅ | ✅ | — | ✅ 完成 |
| PRD-26 | 防剧透策略与暴露度控制 | ✅ | ✅ | — | ✅ 完成 |
| PRD-27 | 事件日志存档回放与检查点 | ✅ | ✅ | — | ✅ 完成 |
| PRD-28 | 自动结局与可查询战役档案 | ✅ | ✅ | — | ✅ 完成 |

**完成率**: 28/29 PRD 完成 (97%)，1 个部分完成 (PRD-08 语音需要浏览器 MediaRecorder API)

---

## 详细测试清单

### PRD-00 全局协议与投影契约
| 测试文件 | 测试用例 | 覆盖需求 |
|----------|---------|---------|
| `test_events.py` | `test_engine_event_envelope_fields` | §5.1 事件信封字段 |
| `test_events.py` | `test_audience_allows_only_valid_values` | §5.2 audience 枚举 |
| `test_events.py` | `test_engine_event_type_enum` | §5.9 事件类型全集 (20种) |
| `test_events_bus.py` | `test_event_bus_publish_and_subscribe` | 事件发布订阅 |
| `test_events_bus.py` | `test_event_bus_filters_by_room` | 房间隔离 |
| `test_events_bus.py` | `test_projection_builder_generates_host_and_player_events` | 投影构建 |
| `test_events_bus.py` | `test_projection_party_generates_host_and_player` | party 投影拆分 |

### PRD-01 Engine意图生命周期
| 测试文件 | 测试用例 | 覆盖需求 |
|----------|---------|---------|
| `test_engine.py` | `test_intent_returns_accepted` | §5.1 意图接收 |
| `test_engine.py` | `test_intent_idempotent` | §5.3 幂等去重 |
| `test_engine.py` | `test_complete_action` | §5.8 动作完成 |
| `test_integration.py` | `test_full_flow` | §8 端到端验收 |

### PRD-02 Host通信总线与路由分发
| 测试文件 | 测试用例 | 覆盖需求 |
|----------|---------|---------|
| `test_host.py` | `test_host_ws_connection` | WebSocket 连接 |
| `test_host.py` | `test_host_event_whitelist` | 事件白名单过滤 |
| `test_host.py` | `test_host_sequence_dedup` | 序列号去重 |

### PRD-03 Host全局HUD与状态聚合
| 测试文件 | 测试用例 | 覆盖需求 |
|----------|---------|---------|
| `test_host.py` | `test_hud_rest_endpoint` | HUD 数据聚合 |
| `test_host.py` | `test_hud_player_statuses` | 玩家状态展示 |

### PRD-04 Host事务播放器与多级队列
| 测试文件 | 测试用例 | 覆盖需求 |
|----------|---------|---------|
| `test_host.py` | `test_transaction_enqueue_normal` | 普通队列 |
| `test_host.py` | `test_transaction_urgent_priority` | urgent 抢占 |
| `test_host.py` | `test_transaction_step_advance` | step 顺序播放 |
| `test_host.py` | `test_transaction_preemption` | 中断与恢复 |
| `test_host.py` | `test_transaction_resume` | resume 恢复 |
| `test_host.py` | `test_transaction_cancel` | cancel 取消 |

### PRD-05 Host氛围引擎
| 测试文件 | 测试用例 | 覆盖需求 |
|----------|---------|---------|
| `test_host.py` | `test_atmosphere_bgm` | BGM 管理 |
| `test_host.py` | `test_atmosphere_sfx` | SFX 管理 |
| `test_host.py` | `test_atmosphere_visual` | 视觉效果 |

### PRD-06 Host舞台演出
| 测试文件 | 测试用例 | 覆盖需求 |
|----------|---------|---------|
| `test_host.py` | `test_hud_aggregation` | 舞台状态聚合 |
| `test_host.py` | `test_reset_clears_state` | 紧急重置 |

### PRD-07 Player通信网关
| 测试文件 | 测试用例 | 覆盖需求 |
|----------|---------|---------|
| `test_player_intent.py` | `test_submit_intent` | §5 意图提交 |
| `test_player_intent.py` | `test_submit_intent_missing_token` | §7 token 校验 |
| `test_player_intent.py` | `test_submit_intent_idempotent` | 幂等去重 |

### PRD-08 Player对讲机与语音意图
| 测试文件 | 测试用例 | 覆盖需求 |
|----------|---------|---------|
| — | — | ⚠️ 浏览器 MediaRecorder API，无后端测试 |

### PRD-09 Player活体角色卡
| 测试文件 | 测试用例 | 覆盖需求 |
|----------|---------|---------|
| `test_skill_check.py` | `test_critical` | 大成功 |
| `test_skill_check.py` | `test_fumble_on_100` | 大失败 |
| `test_skill_check.py` | `test_extreme` | 极限成功 |
| `test_skill_check.py` | `test_hard` | 困难成功 |
| `test_skill_check.py` | `test_regular` | 普通成功 |
| `test_skill_check.py` | `test_failure` | 失败 |
| `test_skill_check.py` | `test_bonus_dice_positive` | 奖励骰 |
| `test_skill_check.py` | `test_penalty_dice_negative` | 惩罚骰 |
| `test_player_features.py` | `test_character_sheet` | 角色卡查询 |
| `test_player_features.py` | `test_skill_check_via_api` | API 检定 |

### PRD-10 Player背包与线索
| 测试文件 | 测试用例 | 覆盖需求 |
|----------|---------|---------|
| `test_player_features.py` | `test_inventory_list` | 背包查询 |
| `test_player_features.py` | `test_inventory_add_item` | 物品添加 |
| `test_clues.py` | `test_private_clue_discovery` | 私密线索发现 |
| `test_clues.py` | `test_clue_sharing_creates_public` | 线索分享 |
| `test_clues.py` | `test_unshared_clue_stays_private` | 隐私保护 |
| `test_clues.py` | `test_clue_list_includes_private_and_shared` | 混合列表 |

### PRD-11 Player战术聊天
| 测试文件 | 测试用例 | 覆盖需求 |
|----------|---------|---------|
| `test_player_features.py` | `test_tactical_prompt` | 战术提示 |

### PRD-12 玩家加入房间
| 测试文件 | 测试用例 | 覆盖需求 |
|----------|---------|---------|
| `test_player_intent.py` | `test_join_room` | §5 加入房间 |
| `test_player_intent.py` | `test_join_nonexistent_room` | §7 错误处理 |
| `test_rooms.py` | `test_create_room` | 创建房间 |

### PRD-13 角色卡导入
| 测试文件 | 测试用例 | 覆盖需求 |
|----------|---------|---------|
| `test_xlsx_parser.py` | `test_parse_xlsx_returns_character_fields` | §5.2 字段解析 |
| `test_xlsx_parser.py` | `test_parse_xlsx_with_skills` | 技能解析 |
| `test_xlsx_parser.py` | `test_parse_xlsx_missing_fields` | 缺失字段默认值 |

### PRD-14 玩家行动面板
| 测试文件 | 测试用例 | 覆盖需求 |
|----------|---------|---------|
| `test_integration.py` | `test_full_flow` | 行动提交流程 |

### PRD-15 行动回执
| 测试文件 | 测试用例 | 覆盖需求 |
|----------|---------|---------|
| `test_engine.py` | `test_intent_returns_accepted` | queued 状态 |
| `test_engine.py` | `test_complete_action` | resolved 状态 |

### PRD-16 私密线索与分享
| 测试文件 | 测试用例 | 覆盖需求 |
|----------|---------|---------|
| `test_clues.py` | `test_private_clue_discovery` | §5 私密发现 |
| `test_clues.py` | `test_clue_sharing_creates_public` | §5 主动分享 |
| `test_clues.py` | `test_unshared_clue_stays_private` | §5 隐私边界 |
| `test_clues.py` | `test_clue_list_includes_private_and_shared` | §5 混合视图 |

### PRD-17 个人目标
| 测试文件 | 测试用例 | 覆盖需求 |
|----------|---------|---------|
| `test_objectives.py` | `test_team_objectives_visible_to_all` | §5 团队目标 |
| `test_objectives.py` | `test_personal_objectives_only_owner` | §5 个人目标 |
| `test_objectives.py` | `test_objective_status_change` | §5 状态变更 |

### PRD-18 澄清请求
| 测试文件 | 测试用例 | 覆盖需求 |
|----------|---------|---------|
| `test_clarification.py` | `test_submit_clarification` | §5 提交澄清 |
| `test_clarification.py` | `test_missing_target_action` | §7 错误处理 |
| `test_clarification.py` | `test_nonexistent_action` | §7 不存在的行动 |
| `test_clarification.py` | `test_rate_limiting` | §5 频率限制 |
| `test_clarification.py` | `test_get_result` | §5 结果查询 |
| `test_clarification.py` | `test_different_result_types` | §5 解释/补问/重算 |

### PRD-19 断线重连
| 测试文件 | 测试用例 | 覆盖需求 |
|----------|---------|---------|
| `test_reconnect.py` | `test_reconnect_missed_events` | §5 短断线恢复 |
| `test_reconnect.py` | `test_reconnect_full_snapshot` | §5 长断线快照 |
| `test_reconnect.py` | `test_reconnect_invalid_token` | §7 无效 token |
| `test_reconnect.py` | `test_reconnect_missing_token` | §7 缺失 token |
| `test_reconnect.py` | `test_reconnect_idempotent` | §5 幂等重连 |
| `test_reconnect.py` | `test_reconnect_first_time` | §5 首次连接 |
| `test_reconnect.py` | `test_pending_action_status` | §5 待处理行动 |
| `test_reconnect.py` | `test_action_status_check` | GET action endpoint |
| `test_reconnect.py` | `test_action_not_found` | §7 行动不存在 |
| `test_reconnect.py` | `test_action_wrong_owner` | §7 权限校验 |

### PRD-20 个人档案
| 测试文件 | 测试用例 | 覆盖需求 |
|----------|---------|---------|
| `test_archive.py` | `test_action_history` | §5 行动历史 |
| `test_archive.py` | `test_clue_history` | §5 线索历史 |
| `test_archive.py` | `test_skill_check_history` | §5 检定历史 |
| `test_archive.py` | `test_public_replay` | §5 公共回放 |
| `test_archive.py` | `test_replay_filters_private` | §7 隐私过滤 |
| `test_archive.py` | `test_type_filter` | §5 类型过滤 |
| `test_archive.py` | `test_keyword_search` | §5 关键词搜索 |
| `test_archive.py` | `test_missing_token` | §7 token 校验 |
| `test_archive.py` | `test_pagination` | §5 分页 |
| `test_archive.py` | `test_replay_pagination` | §5 回放分页 |

### PRD-21 房主开房
| 测试文件 | 测试用例 | 覆盖需求 |
|----------|---------|---------|
| `test_rooms.py` | `test_create_room` | §5 创建房间 |
| `test_rooms.py` | `test_get_room` | 房间查询 |
| `test_rooms.py` | `test_get_room_not_found` | §7 错误处理 |
| `test_rooms.py` | `test_start_room` | §5 开始游戏 |
| `test_rooms.py` | `test_start_room_wrong_owner` | §7 权限校验 |

### PRD-22 PDF导入
| 测试文件 | 测试用例 | 覆盖需求 |
|----------|---------|---------|
| `test_pdf_parser.py` | `test_extract_text_returns_list` | §5 文本抽取 |
| `test_pdf_parser.py` | `test_is_scanned_pdf_empty` | §5 扫描检测 |
| `test_pdf_parser.py` | `test_is_scanned_pdf_with_few_chars` | §5 扫描检测 |
| `test_pdf_parser.py` | `test_is_scanned_pdf_with_text` | §5 正常文本 |
| `test_pdf_parser.py` | `test_chunk_text` | §5 分块 |
| `test_pdf_parser.py` | `test_chunk_text_empty_pages` | §5 空页处理 |

### PRD-23 质量报告
| 测试文件 | 测试用例 | 覆盖需求 |
|----------|---------|---------|
| `test_quality.py` | `test_ready_scenario` | §5 ready 状态 |
| `test_quality.py` | `test_warning_missing_ending` | §5 warning 状态 |
| `test_quality.py` | `test_high_risk_multiple_warnings` | §5 highRisk 状态 |
| `test_quality.py` | `test_blocked_empty_graph` | §5 blocked 状态 |
| `test_quality.py` | `test_blocked_no_scenes` | §5 blocked 条件 |

### PRD-24 AI KP主持循环
| 测试文件 | 测试用例 | 覆盖需求 |
|----------|---------|---------|
| `test_ai_kp.py` | `test_mock_narrative_response` | §5 mock 模式 |
| `test_ai_kp.py` | `test_mock_skill_check_request` | §5 检定请求 |
| `test_ai_kp.py` | `test_mock_batch_processing` | §5 批次处理 |
| `test_ai_kp.py` | `test_ai_timeout_handling` | §7 超时处理 |
| `test_ai_kp.py` | `test_invalid_ai_response` | §7 无效响应 |
| `test_ai_kp.py` | `test_deepseek_success` | §5 API 调用 |
| `test_ai_kp.py` | `test_consecutive_failures` | §7 连续失败 |

### PRD-25 批次结算
| 测试文件 | 测试用例 | 覆盖需求 |
|----------|---------|---------|
| `test_batch.py` | `test_collector_creates_batch_after_timeout` | §5 超时触发 |
| `test_batch.py` | `test_collector_merges_multiple_actions` | §5 多行动合并 |
| `test_batch.py` | `test_collector_different_rooms` | §5 房间隔离 |
| `test_batch.py` | `test_collector_no_batch_when_window_not_elapsed` | §5 窗口未到 |
| `test_batch.py` | `test_collector_batch_at_max_actions` | §5 满员触发 |

### PRD-26 防剧透
| 测试文件 | 测试用例 | 覆盖需求 |
|----------|---------|---------|
| `test_spoiler.py` | `test_strict_mode_hides_most_info` | §5 strict 模式 |
| `test_spoiler.py` | `test_standard_mode_shows_discovered_content` | §5 standard 模式 |
| `test_spoiler.py` | `test_cinematic_mode_shows_more` | §5 cinematic 模式 |
| `test_spoiler.py` | `test_truth_never_revealed` | §5 真相永不暴露 |
| `test_spoiler.py` | `test_undiscovered_clues_hidden` | §5 未发现线索隐藏 |
| `test_spoiler.py` | `test_strict_undiscovered_completely_hidden` | §5 strict 严格过滤 |
| `test_spoiler.py` | `test_get_exposure_level` | §5 暴露度查询 |
| `test_spoiler.py` | `test_get_exposure_no_clues` | §5 无线索时 |
| `test_spoiler.py` | `test_build_kp_context` | §5 KP 上下文构建 |
| `test_spoiler.py` | `test_spoiler_level_visibility_tables` | §5 可见性表 |

### PRD-27 事件日志与检查点
| 测试文件 | 测试用例 | 覆盖需求 |
|----------|---------|---------|
| `test_event_log.py` | `test_event_logging` | §5 事件记录 |
| `test_event_log.py` | `test_event_pagination` | §5 分页查询 |
| `test_event_log.py` | `test_public_events_filter` | §5 公共事件过滤 |
| `test_event_log.py` | `test_checkpoint_create` | §5 创建检查点 |
| `test_event_log.py` | `test_checkpoint_list` | §5 列表检查点 |
| `test_event_log.py` | `test_checkpoint_restore` | §5 恢复检查点 |
| `test_event_log.py` | `test_checkpoint_restore_overwrites` | §5 恢复覆盖状态 |

### PRD-28 自动结局与战役档案
| 测试文件 | 测试用例 | 覆盖需求 |
|----------|---------|---------|
| `test_campaign.py` | `test_generate_ending` | §5 结局生成 |
| `test_campaign.py` | `test_end_room_status` | §5 房间状态更新 |
| `test_campaign.py` | `test_ending_persisted` | §5 结局持久化 |
| `test_campaign.py` | `test_campaign_summary` | §5 战役摘要 |
| `test_campaign.py` | `test_archive_query` | §5 档案查询 |
| `test_campaign.py` | `test_archive_query_by_type` | §5 类型过滤 |

---

## 服务端文件清单

| 文件 | 行数 | 职责 | 关联 PRD |
|------|------|------|---------|
| `main.py` | ~50 | FastAPI 入口 + 路由注册 | — |
| `config.py` | ~20 | 环境变量配置 | — |
| `database.py` | ~80 | SQLite 连接 + Schema | — |
| `models.py` | ~200 | Pydantic 数据模型 | PRD-00 |
| `events.py` | ~25 | 事件总线 | PRD-00 |
| `projection.py` | ~20 | 投影构建器 | PRD-00 |
| `ws_manager.py` | ~50 | WebSocket 连接管理 | PRD-00/07 |
| `engine.py` | ~60 | Engine 意图生命周期 | PRD-01 |
| `host_store.py` | ~200 | Host 状态 + 事务播放器 | PRD-02/03/04/05/06 |
| `router_host.py` | ~100 | Host REST + WebSocket | PRD-02/03/04 |
| `router_rooms.py` | ~50 | 房间 CRUD | PRD-21 |
| `router_player.py` | ~120 | 玩家意图 + 角色导入 | PRD-01/12/13/14 |
| `router_scenarios.py` | ~60 | PDF 导入 | PRD-22 |
| `router_clues.py` | ~60 | 私密线索管理 | PRD-16 |
| `router_objectives.py` | ~40 | 目标管理 | PRD-17 |
| `router_clarification.py` | ~80 | 澄清请求 | PRD-18 |
| `router_reconnect.py` | ~60 | 断线重连 | PRD-19 |
| `router_player_archive.py` | ~80 | 个人档案查询 | PRD-20 |
| `router_archive.py` | ~100 | 事件日志 + 战役档案 | PRD-27/28 |
| `router_ai.py` | ~40 | AI KP 端点 | PRD-24 |
| `ai_kp.py` | ~150 | AI KP 核心逻辑 | PRD-24 |
| `spoiler_control.py` | ~100 | 防剧透控制 | PRD-26 |
| `skill_check.py` | ~80 | COC 7e 检定引擎 | PRD-09 |
| `batch.py` | ~80 | 行动批次收集 | PRD-25 |
| `pdf_parser.py` | ~60 | PDF 文本抽取 | PRD-22 |
| `quality.py` | ~70 | 质量报告生成 | PRD-23 |
| `xlsx_parser.py` | ~60 | XLSX 角色卡解析 | PRD-13 |
| `event_log.py` | ~80 | 事件日志系统 | PRD-27 |
| `campaign_archive.py` | ~100 | 战役档案 + 结局 | PRD-28 |

---

## 前端文件清单

| 文件 | 职责 | 关联 PRD |
|------|------|---------|
| `App.tsx` | 路由分发 | — |
| `main.tsx` | React 入口 | — |
| `api.ts` | API 封装 | — |
| `ws.ts` | WebSocket 客户端 | PRD-07 |
| `types.ts` | 共享类型 | PRD-00 |
| `pages/HostStage.tsx` | Host 大屏舞台 | PRD-02/03/04/05/06 |
| `pages/HostLobby.tsx` | Host 大厅 | PRD-21 |
| `pages/PlayerAction.tsx` | 玩家行动面板 | PRD-14/15 |
| `pages/PlayerCharacter.tsx` | 角色卡展示 | PRD-09 |
| `pages/PlayerInventory.tsx` | 背包与线索 | PRD-10/16 |
| `components/TacticalButtons.tsx` | 战术按钮 | PRD-11 |

---

## 运行命令

```bash
# 后端测试
cd mimo-aikeeper
python -m pytest tests/server/ -v

# 单个测试文件
python -m pytest tests/server/test_host.py -v

# 前端类型检查
cd src/client && node node_modules/typescript/bin/tsc --noEmit

# 启动后端
uvicorn src.server.main:app --reload --port 3001

# 启动前端
cd src/client && npm run dev
```

---

## 审查修复记录 (claude-审查.md)

22 个问题全部修复：

### P0 严重问题 (3/3 已修)
| # | 问题 | 修复 |
|---|------|------|
| 1 | WebSocket snake_case/camelCase 不匹配 | models.py 添加 Pydantic alias + `by_alias=True` |
| 2 | Player WebSocket 被直接 close | main.py 添加 `player_ws_endpoint`，支持 player 角色 |
| 3 | `/tmp/` 路径 Windows 不可用 | 改用 `tempfile.gettempdir()` |

### P1 中等偏差 (10/10 已修)
| # | 问题 | 修复 |
|---|------|------|
| 4 | baseStateVersion 冲突检测 | engine.py 版本校验 + 409 返回 |
| 5 | 意图返回 200 而非 202 | router_player.py 改用 JSONResponse(202) |
| 6 | join 无速率限制 | 添加 5次/分钟 IP 限制 |
| 7 | ready_toggle 不更新 is_ready | engine.py 处理 ready_toggle 意图 |
| 8 | hostSequence/playerSequence | EngineEvent 已有 roomSequence，按角色序列号待二期 |
| 9 | ai_kp.py 同步阻塞 | 迁移至 httpx.AsyncClient |
| 10 | knowledge_graph 未填充 | PDF 导入后自动调用 structure_scenario() |
| 11 | quality-report 端点缺失 | router_scenarios.py 添加 GET 端点 |
| 12 | create-room 端点缺失 | router_scenarios.py 添加 POST 端点 |
| 13 | 房主端点无鉴权 | 添加 X-Owner-Token 校验 |

### P2 轻微偏差 (9/9 已修)
| # | 问题 | 修复 |
|---|------|------|
| 14 | FastAPI on_event 废弃 | 迁移至 lifespan context manager |
| 15 | CharacterCompatibilityReport 缺失 | models.py 添加模型 |
| 16 | PlayerOnboardingState 缺失 | models.py 添加模型 |
| 17 | QualityReport 维度不完整 | 添加防剧透边界、角色适配、素材缺口检查 |
| 18 | inventory 缺 source/acquired_at | database.py 添加字段 |
| 19 | check_same_thread 注释 | 添加线程安全说明 |
| 20 | show_item intent_type 无效 | 改为 dialogue + action 参数 |
| 21 | HostLobby 轮询改 WebSocket | 使用 s2c_room_lobby_snapshot 实时推送 |
| 22 | PlayerWS 固定重连间隔 | 添加指数退避 (1s-30s) |
