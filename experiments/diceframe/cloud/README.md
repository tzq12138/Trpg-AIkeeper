# Diceframe 云部署包

运行位置需要一台可持续运行 Docker 的 Linux AMD64 主机。ChatGPT Sites 当前部署入口要求兼容 Worker 的产物，不能直接上传本包运行；ChatGPT 云端工作电脑也没有在本任务中提供长期服务器的接入入口。

## 本机生成

在 AI-Keeper 仓库根目录执行（Python 3.11.8+、Git）：

```powershell
python experiments/diceframe/prepare_cloud.py .runtime/diceframe-cloud-release
```

只从固定提交导出源码，然后应用已验收的权限补丁。云部署另加 `0002-cloud-runtime.patch`：首次密码只写文件、不打印到容器日志；健康探测不创建玩家会话。两份补丁沿用上游 GNU AGPL v3 许可，本次云补丁修改日期为 2026-10-04。拒绝覆盖已有输出。包中不含候选版的 `data`、模型密钥、会话、登录密码或私用剧本。`release.json` 记录版本和补丁哈希；`source/diceframe-cloud-source.zip` 提供这一版本的对应源码及上游许可。

## 目标主机启动

先检查目标主机已有服务、端口及 Docker Compose，确认域名解析到该主机；为本部署使用独立目录。下列操作从上传后的部署包目录执行，需要相应的 Docker 和文件权限：

```sh
cp settings.env.example settings.env
# 编辑 settings.env，只填真实域名。
install -d -m 700 -o 10001 -g 10001 data
docker compose --env-file settings.env config --quiet
docker compose --env-file settings.env build web
docker compose --env-file settings.env up -d --wait
```

仅开放代理的 80/443；应用 9876 不映射公网。首次密码由 Diceframe 在 `data/access_token.txt` 生成，通过可信的主机终端读取，不写入 Git、聊天或部署日志。登录后在设置页配置模型并关闭统计。私用《玻璃雨夜》通过原生插件安装入口另行导入。

容器以普通用户运行，应用目录只读，数据落入 `data/`。不使用上游托管更新器，因此网页中的一键更新不可用；升级必须重新核对基线、应用补丁、运行身份测试并重建镜像。初始基础镜像使用 Python 3.11、Node 22、Caddy 2 系列标签；正式上线时记录实际镜像摘要，重新构建不保证基础镜像字节一致。

不要直接复制本机的 `secrets.json`、会话库或带房间凭据的原始存档。跨域名后浏览器 Cookie 不会自动迁移，已认领席位也不会因为搬服务器自动恢复。

## 验收

- HTTPS 证书有效，首页可达，响应 Cookie 含 HttpOnly 和 Secure。
- 匿名访问 `/api/games` 返回 401；登录后才可管理房间和配置。
- `/api/system/update/health` 返回 `ok: true`，更新状态显示当前安装不支持页面内更新。
- 两个独立浏览器的普通玩家身份隔离，实时事件能及时到达。
- 重启 `web` 后登录及测试存档保留；完成一次备份恢复演练。
- 在邀请说明中提供 `/source/diceframe-cloud-source.zip`，方便用户获取此版本对应源码。

## 备份与回滚

`data` 包含敏感凭据，备份也按私密数据保管。以下步骤停服后再归档，确保 SQLite 和 JSON 处于同一时点。归档失败也会重新启动服务；上传异地副本前另行确定私有存储位置。

```sh
(
set -eu
umask 077
mkdir -p backups
backup="backups/data-$(date -u +%Y%m%dT%H%M%SZ).tar.gz"
docker compose --env-file settings.env stop web
trap 'docker compose --env-file settings.env start web' EXIT
sudo tar -czf "$backup" data
sudo chmod 600 "$backup"
docker image inspect aikeeper-diceframe:297da1f-seat-patch --format '{{.Id}}' > "$backup.image-id"
docker compose --env-file settings.env start web
trap - EXIT
)
```

恢复时先停 `web`，把现有 `data` 改名保留，核对备份归档仅包含 `data/` 下文件，再还原权限并启动。版本回滚同时使用对应旧镜像及升级前的数据备份；不要用旧代码直接读取已升级的数据。当前包不擅自修改主机防火墙、不安装系统软件、不创建付费资源。

参考：[Caddy 实时代理](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy)、[Compose 健康依赖](https://docs.docker.com/compose/how-tos/startup-order/)。
