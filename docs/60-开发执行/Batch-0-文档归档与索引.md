# Batch 0：文档归档与索引

## 目标

把当前项目的路线图、现状盘点、核心链路和历史计划统一放进 `docs/`，让后续 DeepSeek 执行不再依赖散落的附件和旧根目录计划文件。

## 范围

- 新增或维护 `docs/README.md`。
- 新增 `docs/00-路线图/`、`docs/10-现状盘点/`、`docs/20-核心链路/`、`docs/30-DeepSeek任务包/`。
- 将历史 `plan*.md` 归档到 `docs/90-归档/历史计划/`，保持原文不改。
- 不修改服务端、前端、测试代码。

## 文件方向

| 操作 | 路径 |
|---|---|
| 新增 | `docs/README.md` |
| 新增 | `docs/00-路线图/平台能力分层与MVP边界.md` |
| 新增 | `docs/10-现状盘点/当前项目状态与风险.md` |
| 新增 | `docs/20-核心链路/AI-Keeper核心链路架构.md` |
| 新增 | `docs/30-DeepSeek任务包/*.md` |
| 新增 | `docs/90-归档/历史计划/` |

## 验收

```powershell
Get-ChildItem -Recurse docs | Select-Object FullName
```

预期：能看到上述新增目录和历史计划归档文件。

```powershell
Select-String -Path docs\README.md -Pattern "DeepSeek 任务包"
```

预期：命中总索引里的任务包入口。

```powershell
git status --short
```

预期：只出现本批新增/复制的文档文件，以及执行前已存在的无关改动。

## 禁止事项

- 不再在根目录新增 `plan/`。
- 不改历史计划正文。
- 不把附件原文逐字大段复制进新文档，只做路线图级整理。
