# AI-only P0-6B 测量门禁（2026-08-20）

状态：测量器与发布门槛已建立；真实 30 场 benchmark 尚未执行，因此不宣称 P0-6B 或发布候选通过。

## 已建立的测量口径

`src/server/scenario/ai_only_benchmark.py` 固定九类玩家画像：

`normal`、`cautious`、`aggressive`、`divergent`、`rules_lawyer`、`silent`、`high_frequency`、`spoiler_probe`、`conflict`。

每个固定种子场次必须提交一个 `BenchmarkObservation`，包含玩家人数、结局、接受动作数、澄清/纠正/无意义检定计数、普通动作延迟，以及 Host 裁决、剧透、非法写入、重复投掷/提交、死锁和 Trace 完整计数。

报告强制保留：

- 分子、分母和 scope；
- 15 场双人 + 15 场四人的样本分层；
- 硬阻断与观察指标分离；
- 分母为零时标记 `not_measurable`，不当作零风险；
- 30 场、双人/四人样本、硬阻断和观察阈值全部满足后才可 `release_ready=true`。

## 验证证据

```text
python -m pytest tests/server/test_ai_only_benchmark.py -q
3 passed
```

测试覆盖健康样本、分母缺失和硬阻断/观察阈值分离。合成观测只验证聚合逻辑，不替代真实跑团。

## 尚未执行

- 真实固定种子 30 场（15 双人、15 四人）；
- 玩家模型驱动的跨回合行为与冲突/沉默/剧透探测场景；
- Provider 故障、重连、重复提交和 hash freeze 的整场统计；
- 真实浏览器/多玩家证据和延迟采样。
