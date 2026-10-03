# 《玻璃雨夜》可用候选版

[目标](../../docs/superpowers/specs/2026-10-03-diceframe-candidate.md)要求独立房主与普通玩家、两人/四人完整短团、私人信息隔离、中断恢复及结团记录。

## 固定环境

- Diceframe 提交 `297da1f06d1e177ade2324eb35d9eb8e1dff89cb`。
- 候选目录 `.runtime/diceframe-candidate/`，入口 <http://127.0.0.1:19877>。
- 旧试点 <http://127.0.0.1:19876> 及其存档保留。
- 四张卡：程雁、许遥、贺北、苏眠；开团可只选择其中两张。
- 核心权限补丁已获用户授权，尚在实施；在完成权限验收前不要开放给外部人员。

## 首次准备

以下命令从本仓根目录执行。需要 Python 3.11+、Node、npm、Git。依赖和运行数据均被 Git 忽略。

```powershell
git clone https://github.com/diceframe/diceframe.git .runtime/diceframe-candidate/app
git -C .runtime/diceframe-candidate/app checkout --detach 297da1f06d1e177ade2324eb35d9eb8e1dff89cb
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
```

当前内容测试 4 项通过，含实际宿主启用、四张卡的规则验证和私有材料隔离。多人权限、真实模型短团与恢复仍待后续验收，不能据此宣称候选版完成。
