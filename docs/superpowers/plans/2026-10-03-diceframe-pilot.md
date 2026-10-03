# Diceframe Glass Rain Pilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付使用原生 Diceframe 的《玻璃雨夜》两人试玩环境和迁移差异证据。

**Architecture:** 固定上游版本放在忽略的运行目录；本仓只维护内容转换、启动说明和验收。生成的私用内容包保留在本地，核心零修改。

**Tech Stack:** Python 3.11+、Diceframe v2.6.1、Vue/Vite 原生界面、声明式 JSON 内容包。

**Spec:** `docs/superpowers/specs/2026-10-03-diceframe-pilot.md`

## Global Constraints

- 固定上游提交 `962fda45a68caa24bac38fd2313d92d66fa59a7a`；不改其核心。
- 回环地址部署；配置凭据不输出、不提交。
- 保留来源许可；生成包仅本地私用。
- Python 新方法使用含 summary/param/returns 的文档字符串；局部变量无需注释。

## Review Focus

- 世界简介、公共角色背景和公开线索误带秘密：检查真实内容投影。
- 内容包重复安装覆盖已修改的用户内容：新运行目录，文档说明只初始化一次。
- 角色属性/技能值的格式或点数规则不兼容：用上游实际验证器和创建流程核对。
- 重载后世界/角色/线索丢失：保存后重启并比较关键字段。
- 缺失模型配置被误报为成功试玩：检查实际模型响应并在报告分级。

### Task 1: 可安装内容包和独立环境

**Files:**
- Create: `experiments/diceframe/build_glass_rain.py`
- Create: `experiments/diceframe/test_glass_rain.py`
- Create: `experiments/diceframe/README.md`

**Interfaces:**
- Consumes: `data/golden_modules/02-short-team-glass-rain/module.json`。
- Produces: `build_pack(source: Path, destination: Path) -> Path`，生成 plugin.json、world JSON、两张 character JSON、原许可及来源信息。

- [x] 写内容隔离与角色转换测试，执行确认缺少生成器/产物时失败。
- [x] 实现单模组转换，秘密单独进入 GM 条目，私人钩子不进入公共角色卡。
- [x] 执行测试、上游打包校验；安装到独立数据目录，构建原生界面。
- [x] 记录测试结果并提交可复用代码。

### Task 2: 实际试玩与迁移报告

**Files:**
- Create: `docs/60-验收与测试报告/diceframe-pilot-20261003/试点记录.md`
- Modify: `experiments/diceframe/README.md`

**Interfaces:**
- Consumes: Task 1 的内容包与固定上游。
- Produces: 本地可访问试玩地址、操作说明、脱敏验证结果及截图。

- [x] 启动独立服务，使用用户在试点页自行填写的模型配置。
- [x] 验证两人开团、可见性、一次检定、保存/重载；推进到叙事收束，并记录身份边界失败和未自动归档。
- [x] 将无法等价实现的原运行约束写入差异清单，不改核心补齐。
- [x] 做独立复查，确认无密钥或依赖进入提交，再提交并推送试点分支。
