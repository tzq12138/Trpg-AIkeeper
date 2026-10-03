# 《玻璃雨夜》可用候选版

[目标](../../docs/superpowers/specs/2026-10-03-diceframe-candidate.md)要求独立房主与普通玩家、两人/四人完整短团、私人信息隔离、中断恢复及结团记录。

## 固定环境

- Diceframe 提交 `297da1f06d1e177ade2324eb35d9eb8e1dff89cb`。
- 候选目录 `.runtime/diceframe-candidate/`，入口 <http://127.0.0.1:19877>。
- 旧试点 <http://127.0.0.1:19876> 及其存档保留。
- 四张卡：程雁、许遥、贺北、苏眠；开团可只选择其中两张。
- 已实现[最小席位权限补丁](patches/README.md)，自动化身份验证通过；真实多人验收仍在进行。

## 首次准备

以下命令从本仓根目录执行。需要 Python 3.11+、Node、npm、Git。依赖和运行数据均被 Git 忽略。

```powershell
git clone https://github.com/diceframe/diceframe.git .runtime/diceframe-candidate/app
git -C .runtime/diceframe-candidate/app checkout --detach 297da1f06d1e177ade2324eb35d9eb8e1dff89cb
# 按 patches/README.md 检查并应用权限补丁，再启动服务。
python -m venv .runtime/diceframe-candidate/venv
$candidatePython = (Resolve-Path .runtime/diceframe-candidate/venv/Scripts/python.exe).Path
& $candidatePython -m pip install -r .runtime/diceframe-candidate/app/requirements-dev.txt
Push-Location .runtime/diceframe-candidate/app/frontend-v2
npm ci
npm run build
Pop-Location
& $candidatePython experiments/diceframe/build_glass_rain.py .runtime/diceframe-candidate/content/aikeeper-glass-rain
```

生成包版本为 0.2.0，不覆盖旧输出。输出包含原私用内容，不可提交或公开再分发。固定提交只决定应用基线；安装的 Python/npm 依赖仍以其依赖约束和锁文件解析。

本次独立 Python 环境安装成功，原生前端构建通过；Node 24.14.0/npm 11.9.0 产生上游 npm 版本提示，构建也报告大 chunk 提示。

## 本机运行

```powershell
$candidateRoot = Join-Path (Get-Location) '.runtime/diceframe-candidate'
$env:TRPG_DATA_DIR = Join-Path $candidateRoot 'data'
$env:TRPG_WEB_HOST = '127.0.0.1'
$env:TRPG_WEB_PORT = '19877'
$env:PYTHONIOENCODING = 'utf-8'
& (Join-Path $candidateRoot 'venv/Scripts/python.exe') (Join-Path $candidateRoot 'app/web_server.py')
```

当前本机已预装并启用生成的内容包。新环境可使用上游 `scripts/package_plugin.py` 打包后在管理页安装并启用。访问密码由上游生成，保存在候选数据目录的 `access_token.txt`。模型由用户在设置页配置；统计关闭。不要同时启动两个指向同一数据目录的进程。

## 验证

```powershell
$env:DICEFRAME_ROOT = (Resolve-Path .runtime/diceframe-candidate/app).Path
& .runtime/diceframe-candidate/venv/Scripts/python.exe -m pytest experiments/diceframe/test_glass_rain.py -q
& .runtime/diceframe-candidate/venv/Scripts/python.exe -m pytest experiments/diceframe/test_candidate_identity.py -q
```

当前内容测试 4 项通过，含实际宿主启用、四张卡的规则验证和私有材料隔离；身份测试入口内部执行 14 项真实 HTTP 合同，另有 173 项相关上游测试通过。模型异常的回滚、保留行动队列与重试来自上游真实服务加模型替身的故障注入测试。真实模型双人/四人短团与实际服务重启仍待后续验收，不能据此宣称候选版完成。

建团时，把所有预设卡切换为“等待认领”，房主即可独立主持；各玩家用自己的浏览器首次认领。每张卡认领后由 GM 的“角色感知”单独发送该角色私人钩子。保留浏览器 cookie 用于重连。
