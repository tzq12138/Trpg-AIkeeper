# Asset 素材库系统 DeepSeek 计划初版

## 执行定位

Asset 模块在核心链路之后推进，先做本地资源索引和权限，不直接上 CDN。

## Batch 建议

| Batch | 目标 | 文件方向 | 验收命令 | 禁止事项 |
|---|---|---|---|---|
| Asset-1 | 本地素材元数据和绑定 | `src/server/map_persistence.py`、`src/server/models.py` | `python -m pytest tests/server -q` | 不引入对象存储依赖。 |
| Asset-2 | Handout 权限和投影 | `src/server/player/router_clues.py`、`src/server/engine/projection.py` | `python -m pytest tests/server/test_clues.py tests/server/test_projection.py -q` | 不公开私密资源 URL。 |
| Asset-3 | 导入导出资源包 | `src/server/export.py`、`tests/server/test_archive.py` | `python -m pytest tests/server/test_archive.py -q` | 不导出未授权私密数据。 |

## DeepSeek 执行规则

- 资源访问需要权限校验。
- 资源文件不进日志正文。
- 大文件和 CDN 后置。

