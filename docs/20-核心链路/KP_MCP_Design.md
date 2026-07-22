# KP MCP Server 设计文档 v0.1

## 1. 总览

```
┌──────────────────────┐        StreamableHTTP          ┌──────────────────────┐
│   FastAPI 后端        │ ──────────────────────────────▶ │   KP MCP Server      │
│   (uvicorn, N worker) │  POST /mcp                     │   (独立进程 :9100)    │
│                      │                                 │                      │
│   ResolutionPipeline  │  tools/discover                │   ├─ soul.md         │
│   RuleExecutor       │  tools/call                     │   ├─ COC 7th 规则    │
│   Engine             │  tools/list                     │   ├─ 剧本知识库       │
│                      │                                 │   └─ DeepSeek API    │
└──────────────────────┘ ◀───────────────────────────── └──────────────────────┘
                             JSON-RPC 2.0 response
```

- **协议**：MCP (Model Context Protocol) over HTTP (StreamableHTTP)
- **传输**：单一端点 `POST /mcp`，持久连接复用
- **端口**：`9100`（默认）
- **后端数量**：1 个 KP MCP Server 服务 N 个 uvicorn worker

---

## 2. MCP Tools 定义

### 2.1 `kp_resolve_turn` — 主结算（80% 的调用）

后端把一笔玩家行动 + 上下文发给 KP，KP 返回完整的 `KpResponse`。

**Input:**
```json
{
  "roomId": "room_abc",
  "action": {
    "characterId": "char_01",
    "declaredIntent": "我蹲下来仔细检查地板上的痕迹",
    "intentType": "investigate"
  },
  "context": {
    "sceneName": "废弃的停尸房",
    "sceneDescription": "铁门后是一间布满灰尘的房间，中央摆着三张金属床...",
    "npcsPresent": ["老看守员格里芬"],
    "visibleClues": [
      {"id": "clue_01", "text": "墙上有暗褐色的喷溅痕迹"}
    ],
    "characterState": {
      "name": "哈维",
      "hp": 12, "maxHp": 12,
      "san": 41, "maxSan": 99,
      "skills": {"侦查": 45, "聆听": 60, "医学": 30}
    },
    "recentEvents": [
      "[KP] 你们推开了停尸房的铁门。一股福尔马林混合着腐败的气味扑面而来。",
      "[char_02] 我打开手电照向房间深处。"
    ],
    "knownClues": ["墙上有暗褐色的喷溅痕迹"],
    "campaignPhase": "investigation"
  }
}
```

**Output — KpResponse:**
```json
{
  "narrative": {
    "public": "哈维蹲下身，手指沿着地板裂缝中的暗色痕迹缓缓移动。这些痕迹不是随机的——它们形成了一条隐约的拖曳轨迹，从中间的金属床一直延伸到房间后方那扇紧闭的铁柜前。",
    "perCharacter": {
      "char_01": "你的医学知识告诉你，这些痕迹的量远超过一次普通的外科手术。而且痕迹已经干涸发黑——至少是三天前留下的。",
      "char_02": null
    }
  },
  "rollRequests": [
    {
      "id": "roll_01",
      "skillName": "侦查",
      "difficulty": "regular",
      "bonusDice": 0,
      "reason": "确定拖曳痕迹的终点是否有隐藏的暗门",
      "targetCharacter": "char_01",
      "visibility": "public"
    }
  ],
  "stateMutations": [
    {
      "type": "gain_clue",
      "permission": "validate",
      "target": "char_01",
      "payload": {
        "text": "地板上的暗色痕迹形成一条拖曳轨迹，通向房间后方的铁柜",
        "source": "停尸房调查",
        "importance": "core"
      }
    }
  ],
  "tacticalPrompts": [
    {
      "text": "你需要更仔细地检查那些痕迹的终点",
      "actions": [
        {"label": "跟随拖曳痕迹检查铁柜", "intentType": "investigate"},
        {"label": "先检查中央的金属床", "intentType": "investigate"},
        {"label": "询问老看守员这些痕迹的来历", "intentType": "dialogue"}
      ]
    }
  ],
  "citations": [],
  "keeperNotes": "哈维接近发现暗门。如果检定成功，揭示铁柜后的密道通向地下室。线索 importance=core 意味着这个发现会推进主线。"
}
```

---

### 2.2 `kp_resolve_sanity` — 理智事件

触发条件：角色目击恐怖场景、阅读禁书、遭遇神话存在。

**Input:** 同上 `context`，外加触发事件的 `trigger`：
```json
{
  "trigger": {
    "type": "witness_horror",
    "description": "铁柜门打开，里面是一具被肢解成七块的尸体，每块都被仔细排列成某种符号的形状",
    "sanityFormula": "auto"
  }
}
```

`sanityFormula: "auto"` 表示让 KP 根据 COC 规则自行判定 SAN 损失公式。

**Output — KpResponse（无 rollRequests）：**
```json
{
  "narrative": {
    "public": "柜门发出刺耳的金属呻吟。当手电的光束扫过柜内的景象时，哈维的呼吸停滞了——那不是一具尸体，是七块。每一块都被精确地排列，在铁柜背板上拼成了一个他从未见过的符号。",
    "perCharacter": {
      "char_01": "你的胃猛地收紧。大脑中某个原始的部分在尖叫着让你移开视线，但另一种病态的好奇心却让你无法转头。"
    }
  },
  "rollRequests": [],
  "stateMutations": [
    {
      "type": "san_loss",
      "permission": "validate",
      "target": "char_01",
      "payload": {
        "formula": "1/1D6+1",
        "reason": "目击被仪式性肢解的尸体"
      }
    },
    {
      "type": "add_status_tag",
      "permission": "direct",
      "target": "char_01",
      "payload": {
        "tag": "shaken",
        "duration": "scene"
      }
    }
  ],
  "tacticalPrompts": [],
  "keeperNotes": "尸体排列成旧日支配者符号。后续线索应指向邪教仪式。如果 char_01 后续调查符号，触发克苏鲁神话技能检定。"
}
```

---

### 2.3 `kp_resolve_combat_round` — 战斗轮

**Input:** 每个参战角色的当前状态 + 声明行动：
```json
{
  "combatants": [
    {
      "id": "char_01", "name": "哈维",
      "side": "player",
      "dex": 55, "hp": 12, "maxHp": 12,
      "skills": {"格斗(斗殴)": 25, "闪避": 27, "射击(手枪)": 40},
      "weapon": {"name": ".38左轮", "damage": "1D10", "hands": 1},
      "build": 0, "db": 0,
      "declaredAction": "我对食尸鬼开枪"
    },
    {
      "id": "npc_ghoul_01", "name": "食尸鬼",
      "side": "enemy",
      "dex": 70, "hp": 15,
      "attacksPerRound": 3,
      "skills": {"格斗(爪)": 60},
      "weapon": {"name": "利爪", "damage": "1D6+1D4"},
      "build": 1,
      "declaredAction": "冲向哈维"
    }
  ]
}
```

**Output — KpResponse:**
```json
{
  "narrative": {
    "public": null
  },
  "rollRequests": [
    {
      "id": "roll_cbt_01",
      "skillName": "射击(手枪)",
      "difficulty": "regular",
      "bonusDice": 0,
      "reason": "哈维对食尸鬼开枪。食尸鬼尝试寻找掩体闪避。",
      "targetCharacter": "char_01",
      "visibility": "public"
    }
  ],
  "stateMutations": [
    {
      "type": "combat_suggestion",
      "permission": "validate",
      "target": "room",
      "payload": {
        "turnOrder": ["npc_ghoul_01", "char_01"],
        "phase": "initiative",
        "note": "食尸鬼 DEX=70 先手。哈维持有已备好的枪械 +50 DEX=105，先手开火。"
      }
    }
  ],
  "tacticalPrompts": [],
  "keeperNotes": "COC 射击规则：火器攻击不可反击。食尸鬼可尝试闪避寻找掩体，成功则哈维承受惩罚骰。若造成 ≥8 HP 伤害触发重伤判定。"
}
```

---

### 2.4 `kp_structure_scenario` — 剧本结构化

全文本输入 → 结构化输出。替代现有的 `structure_scenario()`。

**Input:**
```json
{
  "rawText": "第一部：灯塔之谜\n\n调查员收到一封来自远房表亲的信...",
  "format": "full"
}
```

**Output:**
```json
{
  "scenarioTitle": "灯塔之谜",
  "scenes": [
    {"name": "收到来信", "order": 1, "description": "...", "npcsPresent": [], "cluesAvailable": ["信件内容"]},
    ...
  ],
  "npcs": [
    {"name": "爱德华·马什", "role": "委托人", "personality": "焦虑、健谈", "motivation": "寻找失踪的弟弟", "secret": "..."}
  ],
  "clues": [...],
  "truth": {"summary": "灯塔下的洞窟中...", "triggerConditions": "..."},
  "endings": [...],
  "triggerMechanics": [
    {"condition": "调查员检查灯塔地基", "effect": "触发侦查检定，成功发现暗门"}
  ]
}
```

---

### 2.5 `kp_query_rules` — 规则咨询

后端在校验 stateMutations 时遇到不确定的规则，直接问 KP。

**Input:**
```json
{
  "question": "角色在水中窒息三轮后，每轮的 CON 检定需要什么难度？",
  "context": {"characterState": {"con": 50}}
}
```

**Output:**
```json
{
  "answer": "窒息前三轮无需检定。从第四轮起每轮进行一次 CON 检定。若角色在从事体力劳动（如挣扎），检定难度为困难。失败则每轮受到 1D6 伤害直至死亡或恢复呼吸。",
  "ruleReference": "COC 7th 核心规则书 其他类型伤害表 — 窒息与溺水",
  "mechanicSuggestion": {
    "type": "hp_loss",
    "permission": "validate",
    "payload": {"formula": "1D6", "reason": "窒息伤害", "condition": "CON检定失败后每轮"}
  }
}
```

---

### 2.6 `kp_health_check` — 存活探测

**Input:** `{}`

**Output:**
```json
{
  "status": "ok",
  "model": "deepseek-v4-pro",
  "rulesVersion": "COC 7th v1.2.1",
  "uptimeSeconds": 12345
}
```

---

### 2.7 `kp_query_knowledge` — 知识库问答

Host 后台查询剧本细节或规则知识。KP 从已加载的剧本和规则中检索回答。

**Input:**
```json
{
  "query": "老看守员格里芬的真实身份是什么？",
  "roomId": "room_abc",
  "sources": ["scenario", "rules"],
  "maxTokens": 500
}
```

`sources` 可选值：`scenario`（从当前剧本检索）、`rules`（从 COC 规则书检索）、`both`。

**Output:**
```json
{
  "answer": "格里芬表面上是停尸房的老看守员。实际上他是当地邪教的低阶成员，负责确保没有人发现停尸房地下室的仪式痕迹。他的动机是恐惧——邪教以他的孙女为人质。",
  "citations": [
    {"source": "灯塔之谜 剧本 NPC 资料", "text": "格里芬（老看守员）：表面身份是停尸房看守，实为邪教外围成员。"},
    {"source": "灯塔之谜 剧本 真相摘要", "text": "邪教通过绑架家属来控制关键位置的线人。"}
  ],
  "confidence": "high"
}
```

---

## 3. KpResponse 合同详解

### 3.1 五层结构

| 层 | 消费方 | 权限 |
|---|--------|------|
| `narrative` | ProjectionDispatcher → WebSocket 推送 | Level 2（全权） |
| `rollRequests` | RuleExecutor → 掷骰 → 回传结果 | Level 1（后端执行） |
| `stateMutations` | Engine → 分级校验 → 写入 DB | Level 1 或 Level 2 |
| `tacticalPrompts` | 前端 UI（可选行动按钮） | Level 2（全权） |
| `citations` | 前端 UI / Host 审计 | Level 2（全权） |
| `keeperNotes` | DB 存储（供后续 context 使用） | 仅存储 |
| `_error` | 后端日志 / Host 监控 | 降级时填充 |

### 3.2 Permission 标记

每个 `stateMutations[*].permission` 显式声明：

```python
# Level 2 — 后端直接写，不校验
"direct"

# Level 1 — 后端先校验，再执行
"validate"
```

### 3.3 默认权限分配表

```
直接写 (direct, Level 2):
  • narrative              — 叙事文本
  • tactical_prompts        — 行动提示
  • scene_transition        — 场景切换
  • npc_reaction            — NPC 态度/情绪
  • add_status_tag          — "恐惧""重伤""昏迷"标签

校验后写 (validate, Level 1):
  • san_loss                — 校验公式合法性
  • hp_loss                 — 校验伤害范围
  • mp_loss                 — 校验 MP 消耗
  • luck_change             — 校验范围
  • gain_clue               — 去重
  • gain_item               — 去重
  • move_location           — 校验地点存在
  • combat_suggestion       — 校验参战角色

永不写 (block):
  • attribute_change        — 属性值
  • skill_value_change      — 技能值
  • credit_rating_change    — 信用评级
```

---

## 4. 后端调用流程

### 4.1 ResolutionPipeline 改造

```python
# 现有流程:
#   PlayerIntent → MechanicCompiler → RuleExecutor → 写 DB → ProjectionDispatcher

# 新流程:
#   PlayerIntent + Context → kp_resolve_turn() → KpResponse
#     → narrative → ProjectionDispatcher 直接推
#     → rollRequests → RuleExecutor 掷骰
#     → stateMutations → Engine 分级写入
#     → keeperNotes → DB 存储

async def resolve_action_via_mcp(self, action, character, room):
    context = self.build_context(action, character, room)
    kp_response = await self.mcp_client.call_tool("kp_resolve_turn", {
        "roomId": room.id,
        "action": action,
        "context": context,
    })

    # 1. Level 2: 直接推送
    if kp_response.narrative:
        await self.dispatcher.push_narrative(room.id, kp_response.narrative)
    if kp_response.tacticalPrompts:
        await self.dispatcher.push_prompts(room.id, kp_response.tacticalPrompts)

    # 2. Level 1: 掷骰
    roll_results = {}
    for req in kp_response.rollRequests:
        result = await self.rule_executor.execute_roll(req)
        roll_results[req.id] = result

    # 3. Level 1+2: 状态写入
    for mutation in kp_response.stateMutations:
        if mutation.permission == "direct":
            await self.engine.apply_direct(mutation)
        elif mutation.permission == "validate":
            if self.validator.check(mutation):
                await self.engine.apply_validated(mutation)

    # 4. 保存 KP 备注
    await self.db.save_keeper_notes(room.id, kp_response.keeperNotes)

    # 5. 把掷骰结果回传给 KP 用于下一轮叙事
    await self.db.save_roll_results(room.id, roll_results)

    return kp_response
```

### 4.2 MCP Client 初始化

```python
# 后端 config.yaml 或 .env
KP_MCP_SERVER_URL = "http://localhost:9100/mcp"

# 连接代码
from mcp.client.streamable_http import streamablehttp_client

class KpMcpClient:
    def __init__(self, url: str):
        self.url = url

    async def call_tool(self, tool_name: str, arguments: dict) -> dict:
        async with streamablehttp_client(self.url) as (read, write, _):
            # MCP 协议握手
            await write({"jsonrpc": "2.0", "method": "initialize", ...})
            # 调用工具
            await write({
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments},
            })
            response = await read()
            return response["result"]
```

---

## 5. Server 实现骨架

### 5.1 文件结构

```
kp_mcp_server/
├── server.py           # MCP 入口 + HTTP 路由
├── kp_brain.py         # 核心 AI 调用（soul.md + 规则）
├── tools.py            # 7 个 MCP tool handler
├── context_builder.py  # 构建 LLM context
├── config.py           # 配置
├── prompts/
│   ├── soul.md         # KP 人格设定
│   ├── rules.md        # COC 7th 规则摘要
│   └── contract.md     # KpResponse schema 说明
└── requirements.txt
```

### 5.2 server.py 骨架

```python
import asyncio
from mcp.server import Server, NotificationOptions
from mcp.server.models import InitializationCapabilities
from mcp.server.stdio import stdio_server
from mcp.server.streamable_http import streamable_http_server

from .tools import register_tools
from .kp_brain import KpBrain
from .config import Config

class KpMcpServer:
    def __init__(self, config: Config):
        self.config = config
        self.server = Server("kp-mcp-server")
        self.brain = KpBrain(config)
        register_tools(self.server, self.brain)

    async def run_http(self, host: str = "0.0.0.0", port: int = 9100):
        """StreamableHTTP 模式"""
        capabilities = InitializationCapabilities(
            sampling={},
            experimental={},
        )
        async with streamable_http_server(
            self.server, host=host, port=port,
            capabilities=capabilities,
            notification_options=NotificationOptions(),
        ) as server:
            print(f"KP MCP Server listening on http://{host}:{port}/mcp")
            await server.serve_forever()

# 启动
if __name__ == "__main__":
    cfg = Config.from_env()
    server = KpMcpServer(cfg)
    asyncio.run(server.run_http())
```

### 5.3 kp_brain.py 骨架

```python
import httpx
from pathlib import Path

class KpBrain:
    def __init__(self, config: Config):
        self.api_key = config.deepseek_api_key
        self.api_base = config.deepseek_api_base
        self.model = config.deepseek_model
        self.system_prompt = self._load_system_prompt()

    def _load_system_prompt(self) -> str:
        soul = (Path(__file__).parent / "prompts/soul.md").read_text(encoding="utf-8")
        rules = (Path(__file__).parent / "prompts/rules.md").read_text(encoding="utf-8")
        contract = (Path(__file__).parent / "prompts/contract.md").read_text(encoding="utf-8")
        return f"{soul}\n\n{rules}\n\n{contract}"

    async def think(self, user_message: str) -> dict:
        """调用 DeepSeek，返回 parsed KpResponse"""
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{self.api_base}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": self.system_prompt},
                        {"role": "user", "content": user_message},
                    ],
                    "temperature": 0.8,
                },
            )
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return json.loads(content)
```

### 5.4 tools.py 骨架

```python
from mcp.server import Server
from mcp.types import Tool, TextContent

def register_tools(server: Server, brain: KpBrain):
    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="kp_resolve_turn",
                description="处理一轮玩家行动，返回叙事、检定请求、状态变更。这是主要的 KP 结算入口。",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "roomId": {"type": "string"},
                        "action": {
                            "type": "object",
                            "properties": {
                                "characterId": {"type": "string"},
                                "declaredIntent": {"type": "string"},
                                "intentType": {"type": "string"},
                            },
                            "required": ["characterId", "declaredIntent"],
                        },
                        "context": {"type": "object"},
                    },
                    "required": ["roomId", "action", "context"],
                },
            ),
            Tool(name="kp_resolve_sanity", ...),
            Tool(name="kp_resolve_combat_round", ...),
            Tool(name="kp_structure_scenario", ...),
            Tool(name="kp_query_rules", ...),
            Tool(name="kp_query_knowledge", ...),
            Tool(name="kp_health_check", ...),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        match name:
            case "kp_resolve_turn":
                result = await brain.resolve_turn(arguments)
            case "kp_resolve_sanity":
                result = await brain.resolve_sanity(arguments)
            case "kp_resolve_combat_round":
                result = await brain.resolve_combat_round(arguments)
            case "kp_structure_scenario":
                result = await brain.structure_scenario(arguments)
            case "kp_query_rules":
                result = await brain.query_rules(arguments)
            case "kp_query_knowledge":
                result = await brain.query_knowledge(arguments)
            case "kp_health_check":
                result = {"status": "ok", ...}
            case _:
                raise ValueError(f"Unknown tool: {name}")
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]
```

---

## 6. context 构建：决定 KP 质量的 80%

`soul.md` 要求区分**客观真相 / 玩家已知 / 角色认知 / 未证实猜测**。context 构建必须忠实于这四层。

### 6.1 上下文注入清单

每次 `kp_resolve_turn` 调用，后端必须注入：

| 必须注入 | 来源 | 说明 |
|----------|------|------|
| 场景名称+描述 | `scenarios.scenario_assets.scenes[].description` | KP 需要知道玩家在哪 |
| NPC 列表+性格/动机 | `scenarios.knowledge_graph.npcs[]` | KP 不能发明 NPC |
| 已发现线索 | `clues` 表 | KP 知道玩家知道什么 |
| 角色当前状态 | `characters.xlsx_data` | HP/SAN/MP/技能 |
| 最近事件 | `events` 表（最近 5-10 条） | KP 知道刚才发生了什么 |
| 剧本真相摘要 | `scenarios.knowledge_graph.truth` | KP 知道真相但不会剧透 |
| 本轮行动 | 玩家提交的 intent | 触发 KP 结算的原因 |

| 不应注入 | 原因 |
|----------|------|
| 未发现的线索 | 防止 KP 无意剧透 |
| 隐藏 NPC 动机/秘密 | 防止 NPC 行为不一致 |
| 其他玩家私有信息 | 除非行动涉及 |

### 6.2 敏感信息裁剪

剧本真相通过 `SpoilerController`（现有代码 `ai/spoiler_control.py`）裁剪后再注入：

```python
# 三级裁剪
# strict:   只注入场景描述，不注入真相
# standard: 注入真相摘要（无细节）
# cinematic: 注入更多上下文（可能暗示线索位置）

context["truth"] = spoiler_controller.filter(truth, level="standard")
```

---

## 7. 错误处理

### 7.1 LLM 调用失败

```
┌─ 第 1 次失败 → 重试（间隔 1s）
├─ 第 2 次失败 → 重试（间隔 2s）
├─ 第 3 次失败 → 降级响应（返回简单叙事 + 原因说明）
└─ 第 3+ 次   → 标记 room 异常，通知房主手动接管
```

降级响应格式：
```json
{
  "narrative": {
    "public": "KP 暂时陷入沉默。场景中的阴影继续在墙壁上蠕动，但没有人回应你的行动。（AI 服务暂时不可用，请稍后重试）"
  },
  "rollRequests": [],
  "stateMutations": [],
  "tacticalPrompts": [],
  "keeperNotes": "FALLBACK: LLM unavailable after 3 retries. Room state preserved.",
  "_error": {"type": "llm_unavailable", "retries": 3}
}
```

### 7.2 后端校验失败

当 `stateMutations` 中某个条目被校验层拒绝时，**不阻塞整批**。拒绝单条，写日志，其余正常执行。

```python
# 校验失败的 mutation 记为 rejected，其余照常
for m in kp_response.stateMutations:
    if m.permission == "validate":
        if not self.validator.check(m):
            logger.warning(f"Mutation rejected: {m.type} on {m.target}")
            rejected.append(m)
            continue
    await self.engine.apply(m)
```

### 7.3 超时

- MCP 调用超时：30s（覆盖大部分 LLM 响应时间）
- 超时后降级为 mock narrative
- 不阻塞游戏流程

---

## 8. Provider 链与 AiGateway

### 8.1 Provider 优先级

v1 默认：`DeepSeek → Hermes MCP → Local 兜底`。后续 Hermes 稳定后可改为 `Hermes MCP → DeepSeek → Local 兜底`。

```
调用链:
  AiGateway.resolve_turn()
    → try DeepSeekProvider (直连 API, 带上 soul.md + rules)
      → 失败 → try KpMcpProvider (POST /mcp)
        → 失败 → LocalFallbackProvider (模板叙事)
```

环境变量：
```bash
AI_PROVIDER_ORDER=deepseek,mcp,local    # 逗号分隔，优先级从左到右
KP_MCP_SERVER_URL=http://127.0.0.1:9100/mcp
AI_TIMEOUT_SECONDS=30
```

### 8.2 AiGateway 统一入口

后端所有 AI 调用走 `AiGateway`，不再散落调用 DeepSeek：

| 方法 | 用途 | 替代的旧代码 |
|------|------|-------------|
| `resolve_turn(context)` | 玩家行动结算 | `AIKP.process_batch()` + `GameAgent.run()` |
| `resolve_sanity(context)` | 理智事件 | 散落在 `MechanicCompiler` 中的逻辑 |
| `resolve_combat_round(context)` | 战斗轮 | 手动规则判定 |
| `structure_scenario(raw_text)` | PDF→结构化剧本 | `structure_scenario()` |
| `query_knowledge(query, room_id)` | Host 资料库问答 | 无（新增场景） |
| `query_rules(question)` | 规则咨询 | 无（新增场景） |
| `compile_mechanic(intent, context)` | 意图→机制编译 | `MechanicCompiler.compile()` |

配置 API：
```
GET    /api/admin/ai/config           → 全局 AI 配置
PATCH  /api/admin/ai/config           → 修改 provider 顺序/超时/权限
GET    /api/rooms/{room_id}/ai-config  → 房间级覆盖
PATCH  /api/rooms/{room_id}/ai-config  → 房间级覆盖
POST   /api/admin/ai/health-check     → 触发 Hermes health check
```

### 8.3 与现有代码的关系

| 现有模块 | 处理方式 |
|----------|----------|
| `ai/ai_kp.py` (AIKP) | → **替换**。KP MCP Server 承担其职责 |
| `ai/mechanic_compiler.py` | → **保留**。作为 MCP 不可用时的降级方案 |
| `agent/game_agent.py` | → **替换**。KP MCP Server 承担 Agent Loop 职责 |
| `agent/tools.py` | → **废弃**。工具调度逻辑移到 KP MCP Server 内部 |
| `engine/resolution_pipeline.py` | → **改造**（见第 4.1 节） |
| `engine/rule_executor.py` | → **保留**。负责掷骰 + 结果计算 |
| `ai/spoiler_control.py` | → **保留**。context 构建时用于裁剪敏感信息 |

### 8.4 渐进迁移

```
Phase 1: AiGateway 上线，内部 provider=deepseek（不变更行为）
         → 引入 KpResponse schema 校验
         → 把 AIKP + GameAgent 调用迁到 AiGateway

Phase 2: KP MCP Server 上线，provider=deepseek,mcp,local
         → kp_resolve_turn / kp_structure_scenario 优先走 MCP
         → DeepSeek 作为一级 fallback
         → 切换开关: AI_PROVIDER_ORDER

Phase 3: 全量 MCP，provider=mcp,deepseek,local
         → 全部结算走 MCP
         → 移除 agent/ 目录（game_agent + tools）
```

---

## 9. 审计日志

### 9.1 `ai_call_logs` 表

每次 AI 调用记录一条，用于监控、调试和成本追踪。

```sql
CREATE TABLE ai_call_logs (
    id BIGSERIAL PRIMARY KEY,
    room_id VARCHAR(64),
    action_id VARCHAR(64),
    task_type VARCHAR(32),          -- resolve_turn / structure_scenario / query_knowledge / ...
    provider VARCHAR(32),           -- deepseek / mcp / local
    provider_order VARCHAR(128),    -- "deepseek,mcp,local"
    duration_ms INTEGER,
    status VARCHAR(16),             -- success / fallback / error
    fallback_chain TEXT[],          -- ["deepseek:timeout", "mcp:ok"]
    response_summary VARCHAR(256),  -- 叙事摘要（不存完整 prompt）
    input_tokens INTEGER,
    output_tokens INTEGER,
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### 9.2 安全约束

- **不记录完整 prompt**：`response_summary` 只存叙事前 256 字符
- **不记录 API key**：provider 凭证从环境变量读取，不写入日志
- **开发模式可开启 raw debug**：`AI_DEBUG_LOG=true` 写完整 prompt → 独立表 `ai_debug_logs`，3 天 TTL 自动清理
- **敏感信息脱敏**：即使 debug 模式，`DEEPSEEK_API_KEY` 也在写入前替换为 `***`

### 9.3 健康检查端点扩展

`GET /api/health` 额外返回：
```json
{
  "ai": {
    "deepseek_configured": true,
    "hermes_reachable": true,
    "hermes_url": "http://127.0.0.1:9100/mcp",
    "provider_order": "deepseek,mcp,local",
    "active_provider": "deepseek",
    "recent_errors": 0,
    "total_calls_24h": 342,
    "fallback_rate_24h": 0.03
  }
}
```

---

## 10. 后续扩展点

1. **多模型池**：`kp_brain.py` 可路由不同工具到不同模型（叙事→旗舰模型，规则查询→轻量模型）
2. **Session Memory**：跨回合的 KP 记忆（"NPC X 对玩家 Y 的印象是..."），存储在 KP MCP Server 内存或独立 KV store
3. **剧本知识库 RAG**：把结构化剧本向量化，KP 调用前先检索相关场景/NPC，减少 context 体积
4. **A/B 叙事质量**：同一场景用两个 model 生成，后端选更好的
5. **流式输出**：MCP 支持 streaming（`tools/call` 的 `_meta` 字段），可用于逐段推送叙事
