# Diceframe《玻璃雨夜》本地试点

本页记录已完成的 0.1.0 双人试点。当前转换器已扩展为 0.2.0 四卡候选包；新环境与后续进度见 [候选版说明](CANDIDATE.md)。现有试点安装包与存档没有被替换。

目标是验证能否用原生 Diceframe 减少 AI-Keeper 的开发维护量。本仓只维护一个内容转换器、针对性测试和试点记录；上游核心保持零修改。

- 固定版本：[Diceframe v2.6.1](https://github.com/diceframe/diceframe/tree/962fda45a68caa24bac38fd2313d92d66fa59a7a)，提交 `962fda45a68caa24bac38fd2313d92d66fa59a7a`。
- 当前本机入口：<http://127.0.0.1:19876>。数据保存在 `.runtime/diceframe-pilot/data/`。
- 内容：一个世界、两张角色卡、继承原生 `freeform_coc` 的声明式规则；仅将建卡属性上限从 460 调至 480，以保留程雁与许遥的原始数值。
- [试点记录](../../docs/60-验收与测试报告/diceframe-pilot-20261003/试点记录.md) 区分自动化、真实网页、真实模型与未完成验证。

## 首次准备

以下 PowerShell 命令从 AI-Keeper 仓库根目录运行，需要可用的 Python 3.11+、Node/npm 和 Git。已创建的试点不必重新执行初始化。

```powershell
git clone --branch v2.6.1 --depth 1 https://github.com/diceframe/diceframe.git .runtime/diceframe-pilot/app
git -C .runtime/diceframe-pilot/app rev-parse HEAD
# 必须与上面的固定提交一致。
python -m venv .runtime/diceframe-pilot/venv
$trialPython = (Resolve-Path .runtime/diceframe-pilot/venv/Scripts/python.exe).Path
& $trialPython -m pip install -r .runtime/diceframe-pilot/app/requirements-dev.txt
Push-Location .runtime/diceframe-pilot/app/frontend-v2
npm ci
npm run build
Pop-Location
```

本次使用 Python 3.12、Node 24.14.0、npm 11.9.0 构建通过；上游 npm engines 声明为 `^10.9.0`，本次安装产生版本提示。

## 生成与安装内容

```powershell
$trialPython = (Resolve-Path .runtime/diceframe-pilot/venv/Scripts/python.exe).Path
& $trialPython experiments/diceframe/build_glass_rain.py .runtime/diceframe-pilot/content/aikeeper-glass-rain
& $trialPython .runtime/diceframe-pilot/app/scripts/package_plugin.py .runtime/diceframe-pilot/content/aikeeper-glass-rain --output-dir .runtime/diceframe-pilot/packages
& $trialPython -m pytest experiments/diceframe/test_glass_rain.py -q
```

生成器拒绝覆盖已存在的目录，避免误改人工调整过的内容。需要重新生成时，用新的父目录，末级目录仍须为 `aikeeper-glass-rain`。打包器也默认拒绝覆盖。

启动后在「管理 → 插件」选择生成的 `.dfplugin` 文件，安装并启用。插件会注册世界、规则与两张角色卡。当前试点已经安装启用。

生成物包含原模组的私用内容，遵循 `AI-Keeper-Original-Private-Use-1.0`，保留 `source.json` 中的原许可和输入 SHA-256。不要把生成包发布到公共插件商店或上游仓库。运行目录、密钥、存档和第三方依赖均被 Git 忽略。

没有 Diceframe checkout 时，真实宿主集成测试会跳过；可设置 `DICEFRAME_ROOT` 指向上述固定提交，并使用已安装上游依赖的 Python 运行全部四项测试。

## 启动与停止

```powershell
$trialRoot = Join-Path (Get-Location) '.runtime/diceframe-pilot'
$env:TRPG_DATA_DIR = Join-Path $trialRoot 'data'
$env:TRPG_WEB_HOST = '127.0.0.1'
$env:TRPG_WEB_PORT = '19876'
$env:PYTHONIOENCODING = 'utf-8'
$trialProcess = Start-Process -FilePath (Join-Path $trialRoot 'venv/Scripts/python.exe') -ArgumentList 'web_server.py' -WorkingDirectory (Join-Path $trialRoot 'app') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $trialRoot 'server.out.log') -RedirectStandardError (Join-Path $trialRoot 'server.err.log') -PassThru
$trialProcess.Id | Set-Content (Join-Path $trialRoot 'server.pid')
```

运行前确认端口没有现存试点进程；重复启动不会创建独立环境。访问密码由 Diceframe 首次启动生成，保存在本地 `data/access_token.txt`，不要复制到报告或 Git。后续启动会复用数据和模型设置。

停止时先确认记录的进程确实为本试点，再停止它：

```powershell
$trialProcessId = [int](Get-Content .runtime/diceframe-pilot/server.pid)
$trialParent = Get-CimInstance Win32_Process -Filter "ProcessId=$trialProcessId"
$trialExpectedPython = (Resolve-Path .runtime/diceframe-pilot/venv/Scripts/python.exe).Path
if ($trialParent.ExecutablePath -ne $trialExpectedPython) { throw 'PID 不属于本试点' }
$trialChildren = @(Get-CimInstance Win32_Process -Filter "ParentProcessId=$trialProcessId")
$trialChildren | Select-Object ProcessId, ExecutablePath, CommandLine
# Windows venv 可能由启动进程派生实际服务进程；核对为 web_server.py 后执行：
foreach ($trialChild in $trialChildren) { Stop-Process -Id $trialChild.ProcessId }
Stop-Process -Id $trialProcessId -ErrorAction SilentlyContinue
```

## 试玩流程

1. 用户在「管理 → 设置」自行填写模型提供方、地址、模型和 API Key，保存并测试。转换器不读取本机已有模型凭据。
2. 「创建新冒险」选择「玻璃雨夜 · 两人迁移试点」，规则选「玻璃雨夜 · CoC 轻量预设」，多人模式、第三人称叙事。
3. 移除默认空角色，从卡库选择程雁与许遥。原生界面会生成房间密码。
4. 两个席位均须先认领；未认领席位不参与等待。当前本机房主兼程雁，普通玩家许遥用独立浏览器来源验证。
5. 开局私人钩子保留在 GM 世界书中，尚未自动投递给所属玩家；可用 GM「角色感知」分别发给对应角色。本次已实际投递并核对正常投影。

本次实测已完成 5 个行动回合并形成撤离叙事，当前保留第 6 轮存档。服务重启后，原生 Diceframe 会将未结束的战役恢复为暂停状态；角色、记录与私信仍保留。它没有自动转换成旧系统的结团档案。

试点仅监听回环地址。原生分享弹窗可能自动选取局域网 IP，本机测试使用 `127.0.0.1:19876`；它不是已开放的远程联机服务。

## 迁移边界

这是叙事内容包，原 AI-Keeper 的节点前置条件、倒计时、SAN 触发、结局互斥与结构化战役归档并未迁移为程序规则。原生骰子结算和状态更新能工作，不代表原模组约束全部等价。

当前稳定版的普通玩家正常投影能隐藏他人私人钩子，但本地验证发现跨席位身份边界不足。上游主分支 `297da1f` 已含 GM 席位分享保护，本次单独执行其 18 项相关测试通过；运行中的试点仍固定为 v2.6.1。该结果不代表普通玩家之间的隔离已全面验证。

同时，一次真实模型回合出现内部提示混入公开剧情。权限边界和模型输出质量是正式迁移前的门槛；具体权限复现仅保留在本地试点证据中。当前环境适合可信人员本机试用，不足以批准完整切换。
