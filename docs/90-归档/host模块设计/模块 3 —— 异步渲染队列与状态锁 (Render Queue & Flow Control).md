# 模块 3 —— 事务播放器与多级调度队列 (TransactionPlayer & Multi-Level Queue) v2.0

## v2.0 修订说明：从 boolean 锁 + 简陋队列到工业级事务状态机

本模块是 Host 端改动最大的部分，从 v1.x 的"eventQueue + isUIBusy + setTimeout 硬锁"完全重写为：

1. **多级队列**：`normalQueue` / `urgentQueue` / `interruptedTransaction` 三级调度，`popNextEvent()` 按优先级弹出。
2. **线性步骤状态机**：`s2c_reveal_transaction` 的 `steps[]` 由 `useTransactionPlayer` 按序推进，stepIndexRef 防止陈旧闭包。
3. **全局 Timer 统管**：`activeTimersRef`（`Set<NodeJS.Timeout>`）+ `clearAllTimers()` 在每次状态跃迁前清剿所有残留 timer，杜绝 Watchdog 与动画延时的双重触发。
4. **Watchdog 熔断**：每个 step 支持 `payload.timeoutMs` 动态超时，默认 15s，超时自动 `handleStepComplete`。
5. **Urgent 抢占**：`interruptActiveTransaction` / `resumeInterruptedTransaction` / `cancelInterruptedTransaction` 覆盖抢占的完整生命周期。
6. **瞬时事件白名单**：非事务事件由 `EventRouter` 直接消费（见模块 1），不进入队列。

---

### 第一部分：核心 Hook —— `useTransactionPlayer.ts`

```typescript
// src/client/host/hooks/useTransactionPlayer.ts
import { useEffect, useRef, useCallback } from 'react';
import { useHostStore } from '../store/useHostStore';

export function useTransactionPlayer() {
  const activeTransactionId = useHostStore(s => s.activeTransactionId);
  const completeActiveTransaction = useHostStore(s => s.completeActiveTransaction);

  // 步骤游标（ref 防止陈旧闭包）
  const stepIndexRef = useRef<number>(0);
  const stepsRef = useRef<any[]>([]);

  // 全局 Timer 管控中心
  const activeTimersRef = useRef<Set<ReturnType<typeof setTimeout>>>(new Set());

  const clearAllTimers = () => {
    activeTimersRef.current.forEach(t => clearTimeout(t));
    activeTimersRef.current.clear();
  };

  const safeSetTimeout = (callback: () => void, ms: number) => {
    const timer = setTimeout(() => {
      activeTimersRef.current.delete(timer);
      callback();
    }, ms);
    activeTimersRef.current.add(timer);
    return timer;
  };

  // ─── 核心控制循环 ───

  useEffect(() => {
    if (activeTransactionId) return; // 事务进行中，挂起

    const store = useHostStore.getState();
    const nextEvent = store.popNextEvent();
    if (!nextEvent) return;

    if (nextEvent.type !== 's2c_reveal_transaction') {
      // 不应该到这里——非事务事件由 EventRouter 直接消费
      console.warn('[TransactionPlayer] 队列中出现非事务事件，已跳过:', nextEvent.type);
      return;
    }

    const transaction = nextEvent.payload;
    stepsRef.current = transaction.steps || [];
    stepIndexRef.current = 0;

    store.setTransactionLock(transaction.transactionId);
    executeCurrentStep();
  }, [activeTransactionId]);

  // ─── 步骤执行 ───

  const executeCurrentStep = useCallback(() => {
    const index = stepIndexRef.current;
    const steps = stepsRef.current;

    if (index >= steps.length) {
      // 事务完结
      useHostStore.getState().completeActiveTransaction();
      return;
    }

    const currentStep = steps[index];
    console.log(`[TransactionPlayer] Step ${index}: ${currentStep.kind}`);

    // Watchdog：启动带超时的安全定时器
    const timeoutMs = currentStep.payload?.timeoutMs ?? 15000;
    safeSetTimeout(() => {
      console.warn(`[Watchdog] Step ${currentStep.kind} 超时熔断`);
      handleStepComplete();
    }, timeoutMs);

    dispatchStepExecution(currentStep);
  }, []);

  // ─── 步骤分发 ───

  const dispatchStepExecution = (step: any) => {
    const store = useHostStore.getState();

    switch (step.kind) {
      case 'roll':
        store.setRollEvent(step.payload);
        // 等待 Dice3DNode 调用 notifyDiceSettled() → handleStepComplete()
        break;

      case 'status_delta':
        store.applyPublicStatusDelta(step.payload.characterId, step.payload.publicDelta);
        // 预留 UI 动画时间后推进
        safeSetTimeout(handleStepComplete, step.payload.durationMs ?? 1500);
        break;

      case 'scene_transition':
        store.setSceneImage(step.payload.imageUrl);
        // 预留转场淡入淡出时间后推进
        safeSetTimeout(handleStepComplete, step.payload.durationMs ?? 3000);
        break;

      case 'narrative_text':
        // 统一传完整 text，生成临时 messageId
        store.appendChatMessage(
          `msg_${Date.now()}`,
          step.payload.text,
          { role: step.payload.role, speakerName: step.payload.speakerName }
        );
        // blocking 逻辑：若为 true，等待 Typewriter 回调；否则非阻塞立即推进
        if (step.payload.blocking) {
          // 解锁交由 TypewriterSubtitle 打字完成后通过回调触发
        } else {
          handleStepComplete();
        }
        break;

      default:
        console.warn(`[TransactionPlayer] 未知 step kind: ${step.kind}，安全跳过`);
        handleStepComplete();
    }
  };

  // ─── 步骤完成回调 ───

  const handleStepComplete = useCallback(() => {
    // 清理当前步骤的所有残留 timer（包括 Watchdog 和动画延时）
    clearAllTimers();
    stepIndexRef.current += 1;
    executeCurrentStep();
  }, [executeCurrentStep]);

  // ─── 暴露给外部组件的回调 ───

  const notifyDiceSettled = useCallback(() => {
    const store = useHostStore.getState();
    if (store.currentRollEvent) {
      store.setRollEvent(null);
      handleStepComplete();
    }
  }, [handleStepComplete]);

  // 组件卸载时清理所有 timer
  useEffect(() => {
    return () => clearAllTimers();
  }, []);

  return { notifyDiceSettled };
}
```

### 第二部分：体验闭环

模拟一个完整的 `s2c_reveal_transaction`，包含 `[roll, status_delta, narrative_text]` 三个 step：

| 时刻 | 事件 |
|------|------|
| 0.0s | `popNextEvent()` 取出事务，`setTransactionLock(txnId)`，`stepIndex=0` |
| 0.0s | `dispatchStepExecution` → `roll` → `setRollEvent(payload)` → Dice3DNode 挂载 |
| 0~3s | 3D 骰子翻滚，Watchdog 15s 倒计时中 |
| 3.0s | 骰子停稳 → `notifyDiceSettled()` → `clearAllTimers()` → `stepIndex=1` |
| 3.0s | `dispatchStepExecution` → `status_delta` → `applyPublicStatusDelta` |
| 3~4.5s | HUD 血条闪红动画（`durationMs=1500`），Watchdog 15s 重新计时 |
| 4.5s | `safeSetTimeout` 触发 → `clearAllTimers()` → `stepIndex=2` |
| 4.5s | `dispatchStepExecution` → `narrative_text` → `appendChatMessage` → 立即 `handleStepComplete()` |
| 4.5s | `stepIndex=3 >= steps.length` → `completeActiveTransaction()` → 事务完结 |

**若 3D 骰子渲染失败**：Watchdog 在 15s 时熔断 → `handleStepComplete()` → 跳过当前 step → 继续后续步骤，Host 大屏不会永久卡死。

**若 Urgent 事务到达**：`interruptActiveTransaction(newTxId)` 保存当前中断点 → 播放 Urgent 事务 → Engine 下发 `s2c_resume_transaction` 或 `s2c_cancel_transaction` 决定原事务的命运。

### 模块 3 小结

多级队列 + 线性步骤状态机 + 全局 Timer 统管 + Watchdog 熔断，四层防护确保 Host 端的演出时序坚不可摧。任何环节失败都不会导致永久死锁。
