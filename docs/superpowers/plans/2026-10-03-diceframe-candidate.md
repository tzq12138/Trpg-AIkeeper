# Diceframe Playable Candidate Implementation Plan

> REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan inline, task by task, with one fresh final review.

**Goal:** 交付独立身份、可续玩并能找回结团记录的《玻璃雨夜》双人/四人候选版。
**Architecture:** 固定 Diceframe 主分支提交，独立本地运行目录；本仓维护最少内容转换、候选版准备方式及验收证据。用户已选择最小权限补丁路线。
**Tech Stack:** Python 3.12、aiohttp/pytest、Diceframe Vue/Vite、PowerShell。
**Spec:** `docs/superpowers/specs/2026-10-03-diceframe-candidate.md`

## Global Constraints

- 基线提交 `297da1f06d1e177ade2324eb35d9eb8e1dff89cb`；不修改旧试点运行数据、旧服务或其模型设置。
- 候选版端口 19877，数据、第三方源码和证据原件仅存 `.runtime/diceframe-candidate/`。
- 合成权限测试无需模型或真实凭据；真实模型测试等待用户配置候选版。
- 最小补丁须先证明失败，再实现修复；未获路线选择前不改上游核心。
- 新方法采用带 `<summary>` 等标签的说明；不新增泛化迁移框架。
- 对本次改动运行相关测试；不以旧 AI-Keeper 全套测试替代候选版测试。
- GitHub 同步已有授权；真实运行数据、密钥、私用生成包不提交。

## Review Focus

1. URL、POST 入座、SSE 和重连是否有绕过身份绑定的不同路径；用真实 HTTP 覆盖。
2. 初次认领、并发认领、已有会话恢复、房主代操作是否混淆；补丁若选用须覆盖副作用和竞争。
3. 四张卡是否都适合实际规则，公开投影是否漏出私人钩子；用源数值和字面量期望断言。
4. 模型错误、服务重启是否发生重复结算或丢失私信；比较持久状态并执行恢复测试。
5. 报告是否把自动化、API 会话、真实浏览器和真实模型混称为全量验证；逐项标明证据与限制。

### Task 1: Prepare the pinned candidate and four-character content

**Files:** modify `experiments/diceframe/build_glass_rain.py`, `experiments/diceframe/test_glass_rain.py`; add `experiments/diceframe/CANDIDATE.md`.
**Interfaces — Consumes:** 原黄金模组与现有内容包格式。
**Interfaces — Produces:** 保持插件 ID 的四人内容包、固定候选运行目录、设置页入口。

- [x] 为四卡生成、数值保真及私有材料隔离加入回归并先运行。
- [x] 只扩展角色列表、文案和来源元信息；保留两人开团能力。
- [x] 安装候选版独立依赖并构建原生前端，生成内容包。
- [x] 运行内容测试及真实插件加载测试。
  Command: `.runtime/diceframe-candidate/venv/Scripts/python.exe -m pytest experiments/diceframe/test_glass_rain.py -q`
  Expected: 全部通过，无集成跳过（`DICEFRAME_ROOT` 指向候选源码）。
- [x] 提交本任务改动；记录构建和配置情况。

### Task 2: Establish the player identity boundary

**Files:** if approved add `experiments/diceframe/patches/` and candidate HTTP regression tests; update `CANDIDATE.md`.
**Interfaces — Consumes:** Task 1 固定提交、用户关于核心补丁的路线选择。
**Interfaces — Produces:** 可验证的玩家绑定行为、适用提交明确的最小补丁，或明确记录零修改路线的未通过门槛。

- [x] 在固定提交上保留跨席位私信/入座失败复现。
- [x] 若用户选择补丁，先锁定最小接口方案并记入 ledger，再写失败回归、补丁、验证；否则保留门槛并继续可独立完成的证据工作。
- [x] 本人、其他普通玩家、GM、房主预览、初次入座、并发认领、重新连接和 SSE 均须验证；失败请求不改绑定或状态。
- [x] 运行新回归及上游相关身份/投影测试，记录有意收紧的旧行为。
  Expected: 所有候选版合同通过；不得靠跳过新的失败用例宣称通过。
- [x] 提交补丁/测试/说明。

### Task 3: Run the two acceptance games and recovery checks

**Files:** add report under `docs/60-验收与测试报告/diceframe-candidate-20261003/`; update `CANDIDATE.md`.
**Interfaces — Consumes:** Task 1 内容、Task 2 身份边界、用户配置的模型。
**Interfaces — Produces:** 双人和四人短团、状态恢复及结团记录证据。

- [x] 启动候选版，使用原生创建/加入流程，逐人投递私人钩子。
- [x] 房主与所有普通玩家分离；完成两次短团，浏览器抽验并保存脱敏截图。
- [x] 定向模拟模型异常，验证恢复；分别验证会话重连、服务重启和继续游戏。
- [x] 用原生能力结束或暂停并保存回顾，重载验证；确有原生缺口时先记录，不盲目扩展 UI。
- [x] 写明真实模型成本计数、失败回合、验证边界和剩余问题。
  Expected: spec 六项标准均有对应证据；未满足的标准维持目标未完成。
- [x] 提交报告，做一次全分支独立审查，修复实质问题，验证后同步 GitHub。
