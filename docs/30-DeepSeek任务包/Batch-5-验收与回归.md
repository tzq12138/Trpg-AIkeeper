# Batch 5：验收与回归

## 目标

在前四批修复完成后，对 AI-Keeper 核心链路做全量回归和手动验收，确认系统能真实跑完一条 AI-KP 主流程。

## 范围

- 后端全量测试。
- 前端类型检查和构建。
- 核心手动流程验收。
- 文档更新：把实际测试结果补到对应任务记录或测试覆盖文档。

## 验收命令

```powershell
python -m pytest tests/server -q
```

预期：后端测试通过；如有历史失败，必须列出失败用例、错误摘要和是否与本轮相关。

```powershell
cd src/client
node ./node_modules/typescript/bin/tsc --noEmit
npm.cmd run build
```

预期：TypeScript 和 Vite build 通过。

```powershell
python dev.py --check
```

预期：服务运行时健康检查可读；服务未运行时提示明确且无乱码。

## 手动主链路

按顺序验证：

1. 房主创建房间并选择剧本。
2. 两名玩家加入等待室。
3. 玩家导入或绑定角色卡。
4. 两名玩家 ready。
5. 房主开始游戏，Host 进入舞台，Player 进入行动页。
6. 玩家提交自由行动。
7. AI/规则裁决生成结果。
8. Host 收到公共演出。
9. 当事 Player 收到私密反馈或状态 patch。
10. 事件日志能查到行动、裁决、状态变化和投影。

## 安全验收

- Player 不能伪造 `characterId` 操作他人角色。
- Host 不直接写权威状态。
- 房主不看到完整 KP-only 真相。
- AI 不直接落库。
- 未发现线索不进入 Player 可见事件或 AI Player 上下文。

## 禁止事项

- 不把局部测试通过包装成全量通过。
- 不跳过手动主链路。
- 不在验收阶段引入新功能。
