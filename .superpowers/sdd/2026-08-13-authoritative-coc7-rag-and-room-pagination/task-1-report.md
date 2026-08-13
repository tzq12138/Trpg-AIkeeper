# Task 1 报告：规则来源状态与数据库最小模型

## 改动

- 新增固定 CoC7 规则书来源校验：文件名、SHA-256 与 PDF 页数必须全部匹配。
- 在共享 `SCHEMA_SQL` 新增来源页状态、发布门槛、房间裁定的最小表结构，以及规则版本运行资格、房间规则来源状态和所需索引。
- 新增只读/无副作用的生命周期接口；本任务不会发布、切换、导入或退休任何真实规则数据。
- 新增定向回归测试，覆盖错误来源拒绝、逐物理页状态持久化、发布门槛快照和 Task 1 生命周期无副作用契约。

## Red 证据

命令：`python -m pytest tests/server/test_authoritative_coc7.py -q`

结果：失败于测试收集，`ModuleNotFoundError: No module named 'src.server.rules.authoritative_coc7'`。这是预期的缺失功能失败，发生在任何生产实现前。

## Green 证据

命令：`python -m pytest tests/server/test_authoritative_coc7.py -q`

结果：`4 passed, 1 warning in 1.62s`。唯一 warning 是既有 FastAPI TestClient/`httpx` 弃用提示。

命令：`git diff --check`

结果：通过，无空白错误。

## 提交

Commit SHA：`916d038f234a9eb3fe8cd0e569780f84293203f6`。

## 风险与边界

- 未接触 Task 2+：没有导入、发布、运行时切换、检索过滤、房间阻断或实际退休旧规则。
- 正式 PDF 不在本任务内；校验器在文件不存在、文件名、哈希或页数不匹配时均拒绝，绝不猜测来源。
- 生命周期函数目前刻意无副作用；后续任务应在各自 TDD 周期中扩展退休和房间守卫行为。
