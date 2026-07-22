# Semantic Interaction Demo

这是一个最小可运行原型，演示：

1. 玩家原话先形成 `UtteranceEnvelope`；
2. AI/解析器只产出 `SemanticCandidate`；
3. `ViewerSafeGrounder` 只能绑定当前玩家可见实体；
4. `SemanticRiskPolicy` 区分队伍建议、澄清、确认和低风险执行；
5. 玩家确认后才生成 `ActionCommand`；
6. `ActionCommand` 交给 Transaction，**它不是 RuleResult，也不直接写 State**。

## 运行测试

```bash
cd semantic_interaction_demo
python -m pytest -q
```

## 查看演示输出

```bash
cd semantic_interaction_demo
python -m semantic_demo.demo
```

## 启动 API

```bash
cd semantic_interaction_demo
uvicorn semantic_demo.api:app --reload
```

接口：

- `POST /semantic/compile`
- `POST /semantic/confirm`

## 生产替换点

`DemoSemanticModel` 只是为了让样例离线可运行。生产中应替换为 `AiGatewaySemanticModel`：

- 使用严格 JSON Schema 返回 `SemanticCandidate`；
- 模型上下文只包含 `SemanticContextSchema` 中的安全实体；
- 输出经过 Pydantic、实体 ID、权限、状态前置条件和规则包验证；
- 模型不能生成骰子、RuleResult 或 State mutation；
- `ActionCommand` 再交给 `14-Transaction -> 04-Rule -> 13-State`。
