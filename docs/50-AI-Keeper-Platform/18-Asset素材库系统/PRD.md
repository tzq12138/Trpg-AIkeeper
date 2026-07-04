# Asset 素材库系统 PRD 初版

## 目标

提供可绑定、可检索、可授权的素材管理能力，为场景、线索、NPC、地图和模组编辑服务。

## 范围

包含图片、地图、Token、Handout、模板、标签、权限、导入导出。不包含 CDN、付费素材市场和完整版权交易。

## 角色

| 角色 | 权限 |
|---|---|
| 房主/创作者 | 上传、绑定、管理素材。 |
| 玩家 | 查看授权素材和 Handout。 |
| Engine | 根据线索和场景投放素材。 |
| Admin/Ops | 管理存储、配额和删除。 |

## 用户故事

| 编号 | 用户故事 | 优先级 |
|---|---|---:|
| ASSET-1 | 作为创作者，我能上传场景图并绑定地点。 | P1 |
| ASSET-2 | 作为玩家，我只能看到被投放给我的 Handout。 | P1 |
| ASSET-3 | 作为房主，我能按标签查找素材。 | P1 |
| ASSET-4 | 作为系统，我能导出模组资源包。 | P1 |

## 数据边界

素材属于平台、用户、房间或模组。每个资源有 assetId、owner、type、mime、visibility、linkedEntity、tags、source、createdAt。资源 URL 访问需权限校验。

## 接口 / 事件方向

- REST：上传、查询、绑定、授权、导入导出、删除。
- Event：`asset_uploaded`、`asset_bound`、`asset_visibility_changed`、`handout_revealed`。
- Projection：资源投放只下发授权 URL 或资源引用。

## 验收标准

- 资源可绑定场景、NPC、线索或模组。
- 未授权用户不能访问私密 Handout。
- 导出资源包不包含无权限私密素材。
- 资源缺失不阻断核心跑团链路。

