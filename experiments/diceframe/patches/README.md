# 候选版席位权限补丁

`0001-bind-player-seats.patch` 只适用于 Diceframe 提交 `297da1f06d1e177ade2324eb35d9eb8e1dff89cb`。补丁包含原上游上下文，遵循随附的 GNU AGPL v3 许可；原项目来源为 <https://github.com/diceframe/diceframe>。本地修改日期：2026-10-03。

## 行为

- 普通玩家的私信、行动及实时连接使用服务端会话身份，修改 `user` 参数不会切换席位。
- 邀请页仍可读取公开详情、申请首次认领。已认领席位不能靠房间密码和角色 ID 被重新占用；并发认领在原有状态锁内处理。
- 身份认领标记随原生存档保存；将角色转交 AI 或设为等待认领不会解除此前的身份绑定。
- 房主可继续预览、代操作。建团时第一张卡选择“等待认领”或“AI 托管”，房主便独立于角色；第一张卡选择“玩家”仍由房主兼任。独立房主可正常订阅实时桌面。

代价：清除 cookie 或换设备后，普通玩家不能再仅靠旧链接恢复已经认领的席位。此候选版仅承诺原浏览器刷新/断线恢复；尚未增加房主批准换设备的界面。空席位仍按原生房间邀请规则先到先认领，不等价于实名账号或定向邀请。

## 应用与验证

从 AI-Keeper 仓库根目录运行，先停止候选服务。失败时不要强行应用或自动升级：

```powershell
$upstream = '.runtime/diceframe-candidate/app'
if ((git -C $upstream rev-parse HEAD) -ne '297da1f06d1e177ade2324eb35d9eb8e1dff89cb') { throw '上游提交不匹配' }
$patchFile = (Resolve-Path experiments/diceframe/patches/0001-bind-player-seats.patch).Path
git -C $upstream apply --check $patchFile
if ($LASTEXITCODE -ne 0) { throw '补丁无法干净应用；检查是否已应用或存在其他改动' }
git -C $upstream apply $patchFile
if ($LASTEXITCODE -ne 0) { throw '应用失败' }
$env:DICEFRAME_ROOT = (Resolve-Path $upstream).Path
& .runtime/diceframe-candidate/venv/Scripts/python.exe -m pytest experiments/diceframe/test_candidate_identity.py experiments/diceframe/test_glass_rain.py -q
```

HTTP 回归通过子进程加载上游，避免两个项目同名 `src` 包互相覆盖。详细用例在 `../checks/identity_http.py`；只使用合成游戏和临时会话，不读取模型密钥。

补丁同时更新两项允许冒领的旧断言，并给原 NPC 投影测试补充真实玩家 cookie；没有删除或跳过这些用例。当前 13 项新 HTTP 用例与 173 项相关上游用例通过，类型检查通过。上游 aiohttp 使用字符串 app/request 键的提示仍存在。

撤销仅针对没有其他改动的候选源码：停服后先 `git apply --reverse --check`，核对通过才撤销；旧试点不受影响。上游正式修复覆盖同等合同后，应移除本补丁并重新运行这些回归。
