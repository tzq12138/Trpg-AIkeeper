# Diceframe 云主机部署计划

> **For agentic workers:** 使用 superpowers:executing-plans 在当前会话逐项执行。已有用户授权部署；主机信息仍待提供。

**Goal:** 将已验收候选版部署到用户指定云主机，提供可登录、可邀请、重启不丢档的 HTTPS 入口。

**Architecture:** 单台 Linux AMD64 主机，Docker Compose 管理固定版本 Diceframe 和 Caddy。沿用已验证的席位补丁；应用、数据和 HTTPS 证书分别持久化。资料站与 Space 保留为项目资料入口。

**Tech Stack:** Python 3.11、上游 npm 锁文件、Docker Compose、Caddy。

**Spec:** `docs/superpowers/specs/2026-10-03-diceframe-candidate.md` 的游戏与权限合同继续有效；本计划新增公网部署验收。

## 约束与检查重点

- 上游固定 `297da1f06d1e177ade2324eb35d9eb8e1dff89cb`，应用 `0001-bind-player-seats.patch`；容器不使用上游托管更新器。
- 只从固定 Git 提交导出构建源码，不打包工作区数据、模型密钥、会话和日志。
- 云端首次生成独立访问密码，模型由用户在设置页配置；统计默认关闭。
- 应用端口只在 Docker 网络内使用；公网仅提供 HTTPS 与证书验证所需 HTTP。反向代理保留实时流，Cookie 加 Secure。
- 新版本先备份数据，记录镜像 ID；回滚镜像时配套恢复同一备份，不假设数据库能降级。
- 不购买主机、不猜测目标地址。实际 SSH、域名、端口占用与现有服务先检查。

## Task 1：可复现部署包

**Files:** `experiments/diceframe/prepare_cloud.py`、`test_cloud_bundle.py`、`cloud/`。

- [x] 测试导出固定提交、应用补丁、忽略未提交凭据、拒绝覆盖既有输出和错误基线。
- [x] 实现部署包与对应源码下载包；Python 使用上游带哈希的 Linux AMD64 依赖锁。
- [x] 验证 Compose 与 Caddy 配置，构建并启动独立容器，检查匿名权限、禁止自更新、持久化重启和权限回归。
- [x] 记录实际通过项和环境限制。

## Task 2：接入目标主机并上线

**Consumes:** Task 1 部署包、用户提供的 SSH 接入及域名。

- [ ] 只读检查主机系统、资源、Docker、端口、DNS 和已有服务；确定独立部署目录。
- [ ] 上传经核对的部署包，建立数据目录，启动并验证 HTTPS、登录、实时连接和重启恢复。
- [ ] 安装私用玻璃雨夜内容包，用户完成云端模型配置后进行真实模型验收。
- [ ] 验证备份可恢复，更新 Space 和资料站中的实际游戏入口。

## 执行记录

- 2026-10-04：现有本机没有 SSH config 或云平台 CLI 配置入口。用户追问能否复用 Sites 或 ChatGPT 云端工作电脑：当前 Sites 需要 Worker 兼容产物，无法原样运行本 Python 服务；当前工具及官方说明未提供云端工作电脑的长期托管入口。继续完成可搬迁部署包，实际运行位置待选择，任务 2 尚未开始。
- 独立审查发现并修复了初始密码进入日志、插件子进程依赖路径丢失、健康探测持续创建会话三项问题。第二份补丁只应用于云部署导出，不修改当前本机候选服务。
- 3 项打包测试、14 项真实 HTTP 身份合同、本机容器 HTTPS/授权/重启检查通过；详细证据见 `docs/60-验收与测试报告/diceframe-cloud-20261004/部署准备验收.md`。
