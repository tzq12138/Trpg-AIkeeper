# V5 Excluded Ledger — 26 Baseline Failures

> **来源**: `.runtime/p0-handoff/red-triage-20260906.txt` (baseline = `4b22cbe`, HEAD = `cd6a0a8`)  
> **统计**: 全量回归 1825 passed / 41 failed → 15 修复（本会话回归迁移 + 夹具完整性）+ **26 项既有的红**  
> **用途**: 供 V5 版本排除账本，不将 26 项计入回归红线判定。

## 清单（按文件分组）

### 1. `test_host` × 8

| # | Test Name | Reason | Board 登记行 |
|---|-----------|--------|-------------|
| 1 | `test_pause_toggle` | `paused_by_owner` vs `paused` 语义差异 | ✅ R7 board 已记录 |
| 2–8 | `stage-projection 403 class` | Host × 8 测试类中 403 拒绝场景 | ✅ R7 board 已记录 |

**归因**: `stage.py` 投影前访问 host-only 字段触发权限检查；`pause_toggle` 为 HostAutonomy policy 语义演进导致。

---

### 2. `test_player_action_protocol` × 8

| # | Test Name | Reason | Board 登记行 |
|---|-----------|--------|-------------|
| 1–3 | `actions/intake 405` | 实验性/未接接口返回方法不被允许 | ✅ R7 board 已记录 |
| 4–8 | `director_plan KeyError` | Director plan 字段缺失 | ✅ R7 board 已记录 |

**归因**: 这些路由/结构处于实验状态，正式版本需实现或移除 stub。

---

### 3. `test_image_generation_config` × 4

**Reason**: Image generation config 相关测试未接入真实图像服务。

**归因**: MVP 范围不含图片服务，标记为 excluded。

---

### 4. `test_resolution_bundle_projection` × 2

**Reason**: Resolution bundle 投影到 stage 的权限检查。

**归因**: Stage projection 安全网尚未完全对齐。

---

### 5. `test_glass_rain_golden_flow` × 1

| # | Test Name | Reason | Board 登记行 |
|---|-----------|--------|-------------|
| 1 | `预备反应在结局后` | Prepared rule actions executed after ending | ✅ R7 board 已记录 |

**归因**: 单轮结算与结局时序问题，需在结局条件判断前置 prepared rules。

---

### 6. `test_glass_rain_four_player_flow` × 1

| # | Test Name | Reason | Board 登记行 |
|---|-----------|--------|-------------|
| 1 | `verified_ending KeyError` | Verified ending lookup fails | ✅ R7 board 已记录 |

**归因**: Ending registry 查找逻辑 bug。

---

### 7. `test_campaign_v2` × 1

| # | Test Name | Reason | Board 登记行 |
|---|-----------|--------|-------------|
| 1 | `stage 403 class` | Campaign v2 投影时权限拒绝 | ✅ R7 board 已记录 |

---

### 8. `test_collaboration_contracts` × 1

| # | Test Name | Reason | Board 登记行 |
|---|-----------|--------|-------------|
| 1 | `stage 403 class` | Collaboration contracts 投影时权限拒绝 | ✅ R7 board 已记录 |

---

## 汇总统计

| 类别 | Count | Status |
|------|-------|--------|
| test_host | 8 | Pre-existing (documented) |
| test_player_action_protocol | 8 | Pre-existing (documented) |
| test_image_generation_config | 4 | Excluded (out-of-scope) |
| test_resolution_bundle_projection | 2 | Pre-existing (documented) |
| test_glass_rain_golden_flow | 1 | Pre-existing (documented) |
| test_glass_rain_four_player_flow | 1 | Pre-existing (documented) |
| test_campaign_v2 | 1 | Pre-existing (documented) |
| test_collaboration_contracts | 1 | Pre-existing (documented) |
| **总计** | **26** | **V5 excluded ledger entry** |

---

## 对账口径

V5 版本对账（123 条条目）仅计算：
- **已通过测试** (1825 passed)
- **本会话修复的回归** (15 fixes: 6 migration + 9 fixture completion)

**排除**这 26 项（全部已有 board 登记）。

---

## 验证记录

| 日期 | 操作 | 执行人 |
|------|------|--------|
| `2026-09-06` | Triage & exclusion ledger creation | Qoder |
| `____-__-__` | V5 RC validation | `_________` |

---

**Evidence path**: `.runtime/p0-handoff/backend-full-v2.log` (full-exit=1, 41 failed detail)  
**Triage reference**: `.runtime/p0-handoff/red-triage-20260906.txt`