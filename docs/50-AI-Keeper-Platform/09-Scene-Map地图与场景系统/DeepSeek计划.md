# Scene / Map 地图与场景系统 DeepSeek 计划初版

## 执行定位

Scene / Map 模块在 Host/Player 主链路稳定后推进，先做轻量场景和地图，不做动态光照。

## Batch 建议

| Batch | 目标 | 文件方向 | 验收命令 | 禁止事项 |
|---|---|---|---|---|
| Map-1 | 当前场景状态和切换事件 | `src/server/map_store.py`、`src/server/router_map.py`、`tests/server/test_projection.py` | `python -m pytest tests/server/test_projection.py -q` | 不让前端直接改当前场景。 |
| Map-2 | 地图资源绑定和加载兜底 | `src/server/map_persistence.py`、`src/client/src/components/HostMapPanel.tsx` | `npm run build` | 不引入 CDN 和资源市场。 |
| Map-3 | 标记和隐藏区域可见性 | `src/server/engine/projection.py`、`tests/server/test_spoiler_guard.py` | `python -m pytest tests/server/test_spoiler_guard.py -q` | 不靠 CSS 隐藏敏感区域。 |

## DeepSeek 执行规则

- 地图功能不能绕过 Projection。
- 场景事实由 Engine/State 管理。
- 动态光照和完整战棋后置。

