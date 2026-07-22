
先给结论：

> **不要把 RAG 设计成“所有剧本文本都切块塞进向量库”。**  
> 你们需要的是一套**版本化、按任务分区、按视角隔离、可追溯来源的检索投影系统**。

正确链路应该是：

```text
原始剧本与辅助资料
        ↓
source_documents / source_parts
        ↓
Module Compiler 结构化编译
        ↓
scenario_version
content_items
content_item_edges
        ↓
RAG Projection Planner
        ↓
构建一个新的 RAG Build
        ↓
校验来源、权限、剧透、向量空间
        ↓
原子激活 RAG Build
        ↓
Room 绑定固定 ModuleVersion + RAG Build
        ↓
按 AI 任务、当前角色和当前视角安全检索
```

Module 本身负责把 WorldBook、NPC、线索、地图、角色和规则素材组织成可复用、可校验、可开房的模板；RAG 只是这个模板的**检索投影**，不能反过来成为 Module 的权威真相库。

---

# 一、你们当前已经有什么

当前仓库其实已经建立了不错的骨架。

数据库已经存在：

```text
source_documents
source_parts
import_jobs
scenario_versions
scenario_version_sources
content_items
content_item_edges
content_projection_runs
rag_rebuild_records
document_chunks
```

其中：

- `source_documents` 保存来源文件；
    
- `source_parts` 保存页、段落、图片转写等解析片段；
    
- `scenario_versions` 保存不可变剧本版本；
    
- `content_items` 保存结构化后的 Scene、NPC、Clue、Ending 等规范对象；
    
- `content_item_edges` 保存结构化关系；
    
- `document_chunks` 才是真正的 RAG 检索表。
    

目前 `document_chunks` 已经有：

```text
source_type
source_id
room_id
content
metadata
source_part_id
scenario_version_id
rule_set_version_id
visibility
citation
embedding_model
embedding_dimensions
embedding
```

而且使用 PostgreSQL `vector` 扩展，所以 P0 阶段不需要马上迁移到 Qdrant、Milvus 或其他独立向量数据库。

当前发布版本时已经会：

```text
1. 索引 source_parts 原文片段；
2. 索引 NPC；
3. 索引 content_items 规范化内容；
4. 记录 rag_rebuild_records；
5. 把 rebuild_id 写入 scenario_versions.rag_index_version。
```

这条方向基本正确。

---

# 二、当前实现的几个关键问题

## 1. 当前仍然以“固定字符切块”为主

当前 `chunk_text_with_offsets()` 默认：

```text
500 字符
50 字符 overlap
```

这会把语义结构切断：

```text
Trigger 的 condition 在上一个 chunk
effect 在下一个 chunk

NPC 名称在上一个 chunk
秘密动机在下一个 chunk

表头在前一块
表格数据在后一块
```

当前 `index_scenario_version()` 也是直接对每个 source part 做固定长度切块。

这适合全文搜索兜底，不适合成为主要运行时知识源。

---

## 2. 原始剧本文本和规范化内容会同时被检索

当前发布版本会同时写：

```text
source_type=scenario
source_type=npc
source_type=content
```

这意味着同一个信息可能出现三遍：

```text
PDF 原文一遍
knowledge_graph NPC 一遍
content_items NPC 再一遍
```

如果 PDF 与勘误、Excel 或人工修订存在冲突，AI 可能召回旧信息和新信息，然后自行猜哪个正确。

因此必须明确：

> **运行时以 canonical content 为主；raw source 只用于 Admin 调试、来源核验和低置信度回退。**

---

## 3. 当前 `audience="ai"` 实际上没有可见性限制

`RAGContextBuilder` 当前调用：

```python
self.rag.search(..., audience="ai")
```

而 `_allowed_visibilities("ai")` 返回 `None`，相当于不对 `visibility` 添加过滤条件。

这意味着“AI”这个身份目前过宽。

但是不同 AI 任务的权限完全不同：

```text
Director AI 可以知道 Host 级结构
Player Assistant 只能知道玩家可见内容
Narrator AI 只能知道允许公开的事实
Mechanic Compiler 只需要规则和行动结构
```

所以必须取消模糊的：

```text
audience = ai
```

改成：

```text
task_scope
viewer_role
character_id
room_id
visibility_scope
unlock_state
```

---

## 4. 当前 RAG Context Builder 没有真正消费 NPC 结果

当前查询列表包含：

```text
npc
```

但结果分类时只处理：

```text
rule
scenario
character
event
clue
asset
```

没有对应的 `npc` 分支，因此 NPC 搜索结果实际上可能被召回后丢弃。

---

## 5. 角色直接上下文仍从 `xlsx_data` 读取 HP/SAN

当前 `RAGContextBuilder` 的 `characters_direct` 仍直接从：

```text
characters.xlsx_data
```

读取：

```text
hp
san
skills
```

而你们后面的 State / Character 设计已经明确：

```text
xlsx_data = 静态角色卡
character_runtime_state = 当前 HP/SAN/MP/Luck 权威值
```

当前写法容易让 AI 看到旧状态。

正确做法是：

```text
当前数值不进向量检索
直接从 CharacterRuntimeView 读取
```

---

## 6. 可见性枚举目前不统一

`ContentProjectionService` 目前允许：

```text
player
host_only
keeper
internal
```

但 `RAGStore._content_visibility()` 只承认：

```text
public
party
host_only
internal
```

其他值默认降为 `host_only`。

这会导致：

```text
player
keeper
party
public
```

在不同模块里语义漂移。

必须统一为平台级枚举，例如：

```text
public
party
character_private
host_only
admin_only
internal
```

然后另外用：

```text
unlock_state
character_scope
```

表达动态权限。

---

## 7. 当前 RAG Build 还不是真正的原子版本

当前有：

```text
scenario_versions.rag_index_version
rag_rebuild_records.rebuild_id
```

但 `document_chunks` 中没有：

```text
rag_build_id
```

因此 `rag_index_version` 目前主要是审计标识，查询时不能明确限定：

> 只检索本次已完成构建中的 chunk。

如果三类索引中：

```text
原文索引成功
NPC 索引成功
content 索引失败
```

前两类 chunk 可能已经写入，但整个版本发布失败。

应增加：

```text
rag_build_id
build_status
```

查询只允许使用已激活的 Build。

---

# 三、RAG 不是唯一检索通道

这是整个设计最重要的一条：

> **结构化事实先走 SQL / 图关系 / State，模糊语义才走向量检索。**

建议把知识访问分成三条路线。

## 1. 权威结构检索

用于：

```text
当前 HP/SAN
当前位置
物品剩余次数
Trigger 条件
RevealGate
NPC 当前状态
Scene 当前状态
角色技能值
规则版本
地图连接
线索归属
```

这些必须走：

```text
State
Rule
content_items
content_item_edges
数据库精确查询
```

不能向量搜索。

---

## 2. 图关系检索

用于：

```text
某 NPC 与哪些场景有关
某线索在哪些地点可能出现
某场景有哪些合法转换
某物品绑定哪个 Handout
某 NPC 属于哪个 Faction
```

这应该优先查询：

```text
content_item_edges
稳定实体 ID
```

不是靠文本相似度猜关联。

---

## 3. RAG 语义检索

适合：

```text
寻找相关背景描述
寻找 NPC 对话风格
寻找规则解释段落
寻找与玩家行动相关的剧本描述
寻找长期事件和证词
寻找语义相近的旧记录
```

因此最终 Context Assembler 应该是：

```text
Structured Context
+ Graph Context
+ Semantic RAG Context
+ Runtime Knowledge Context
```

而不是单纯：

```text
向量 Top K
```

---

# 四、建议建立四个逻辑语料库

可以继续使用同一张 `document_chunks` 表，但必须逻辑分区。

# 1. `admin_source`

保存：

```text
PDF 原始段落
OCR 文本
Excel 原始行
辅助资料原文
勘误原文
```

用途：

```text
Admin 调试
来源核验
重新编译
低置信度问题排查
```

权限：

```text
admin_only / internal
```

不进入普通运行时 AI。

---

# 2. `module_internal`

保存当前 `ModuleVersion` 的规范化知识：

```text
Scene
NPC
Location
ClueTemplate
ItemTemplate
StoryThread
NpcAgenda
RuleOverride
NarrativeTemplate
Trigger 解释
```

用途：

```text
Director AI
Host Review
Module 编译排查
```

注意：

> Trigger 真正执行仍走结构化对象，不由 RAG 决定。

---

# 3. `rule_corpus`

保存：

```text
基础规则
模组规则覆盖
房间 House Rule
规则示例
规则说明
```

按当前优先级：

```text
Room House Rule
> Module Rule Override
> Ruleset Version
> Base Rule
```

当前 `RAGStore.search()` 已经有基于 `room_rule_bindings` 和 `scenario_rule_bindings` 的规则优先级方向，可以保留。

---

# 4. `room_knowledge`

保存房间运行过程中已经成立、已经被允许知道的信息：

```text
Party 已知事件
玩家本人私密线索
已分享线索的 publicVersion
NPC 已公开资料
调查工作台证据
长期记忆摘要
Session recap
```

这是 Player Assistant 和 Investigation AI 的主要语料库。

最安全的原则是：

> **不要让 Player AI 直接检索 Module 中尚未揭示的内容；当内容被正式揭示后，再物化成 room_knowledge。**

例如：

```text
Module 中：
clue:brass_key = latent / host_only

玩家发现后：
创建 room clue instance
创建 player-private RAG chunk

玩家分享后：
再创建 party RAG chunk，内容使用 publicVersion
```

---

# 五、剧本导入时到底写什么

## 第一层：原始来源，不立即作为运行时 RAG

导入文件后先写：

```text
source_documents
source_parts
```

你们当前导入服务已经会把每个解析 part 保存：

```text
part_kind
page_number
text_content
mime_type
anchor
checksum
```

这是正确的。

这一步的目标是：

```text
保真
可追溯
可重新编译
```

不是立即让 Player AI 搜全文。

---

## 第二层：编译成 canonical content

Module Compiler 生成：

```text
content_items
content_item_edges
```

当前 ContentProjection 已经覆盖：

```text
scene
npc
clue
ending
branch
truth
branch_node
```

并通过稳定逻辑键生成稳定 `content_item_id`。

后续建议扩展：

```text
location
item
handout
rule_override
trigger
narrative_template
story_thread
npc_agenda
opening_profile
encounter_template
```

---

## 第三层：生成专用 RAG Projection

不要直接把 `payload` 整包转成字符串。

每种对象需要专用的文本投影器。

例如：

### Scene Host Chunk

```text
场景：院长办公室
用途：调查场景
公开描述：宽大的书桌后是落满灰尘的档案柜。
当前可交互对象：书桌、档案柜、窗户。
主持信息：成功搜查书桌可能触发黄铜钥匙线索。
```

### Scene Narrative Chunk

```text
场景：院长办公室
视觉：宽大的书桌、积灰的档案柜、半开的窗户。
气氛：安静、压抑、有消毒水气味。
```

### Scene Player Chunk

不应在模组发布时直接进入 `room_knowledge`。

应该等场景被正式揭示后，根据公开字段生成。

---

# 六、每个 RAG Chunk 建议的数据结构

```json
{
  "chunkId": "chunk_xxx",
  "ragBuildId": "rag_build_xxx",

  "corpus": "module_internal",
  "projectionKind": "npc_host_profile",

  "sourceType": "content_item",
  "sourceId": "npc:professor_chen",
  "contentItemId": "ci_xxx",

  "scenarioId": "scenario_xxx",
  "scenarioVersionId": "version_xxx",
  "roomId": null,
  "characterId": null,

  "authorityClass": "canonical",
  "semanticMode": "entity_profile",
  "visibility": "host_only",
  "unlockKey": null,

  "entityRefs": [
    "npc:professor_chen",
    "location:hospital"
  ],

  "content": "NPC：陈教授……",
  "contentHash": "sha256:...",

  "citation": {
    "sourceDocumentId": "src_xxx",
    "sourcePartId": "part_xxx",
    "sourceRef": "core.pdf#page=47",
    "pageNumber": 47,
    "excerpt": "……"
  },

  "embeddingSpaceId": "text2vec-zh-768-v1",
  "embedding": [],
  "status": "staged"
}
```

---

# 七、建议新增的字段

当前 `document_chunks` 可以先扩展：

```text
rag_build_id
corpus
projection_kind
authority_class
semantic_mode
character_id
unlock_key
content_hash
entity_refs JSONB
status
language
token_count
```

其中真正需要建立普通数据库索引的字段：

```text
rag_build_id
corpus
scenario_version_id
room_id
character_id
visibility
source_type
projection_kind
status
```

不建议所有东西都只塞进 `metadata JSONB`，因为权限过滤字段必须可稳定查询。

---

# 八、切块不能再只按 500 字符

建议按内容类型切块。

|内容类型|切块方法|
|---|---|
|Scene|一个 Scene 一个或多个功能块|
|NPC|Public profile、Host profile、战术资料分别切|
|Clue|定义、公开版本、触发条件分开|
|Trigger|condition + effect 必须保持一个完整原子单元|
|Rule|按规则条款或表格单元切|
|Table|表头随每个行组重复|
|Read-aloud|单独 narrative_template|
|Timeline|每个事件或同一时间段一块|
|Handout|标题、OCR、公开摘要分别保存|
|长正文|按标题、段落、语义边界切，最后才使用长度限制|

建议长度不是绝对固定，可使用：

```text
中文正文：300～800 字
规则条款：一个完整规则单元
Trigger：完整 condition + effect
NPC：一个视角投影一块
表格：表头 + 5～20 行
```

只有连续正文才需要 overlap。

结构化对象一般不应 overlap，否则容易产生重复召回。

---

# 九、同一个对象可能需要多个投影

例如一个 NPC：

```text
npc_host_profile
npc_public_profile
npc_dialogue_style
npc_combat_tactics
npc_investigation_summary
```

但这些投影不是同时给所有任务。

|AI 任务|可用投影|
|---|---|
|Director|host_profile、agenda、tactics|
|Narrator|已允许的 public_profile、dialogue_style|
|Investigation|玩家当前已知的人物卡|
|Combat AI|当前 NPC 可知信息 + tactics|
|Public export|public_profile|

不要把所有字段塞进一个大 Chunk，再指望 Prompt 提醒模型：

> “不要说出其中的秘密。”

---

# 十、RAG 写入应当发生在什么时候

建议分四个阶段。

## 阶段 1：导入草稿

写入：

```text
source_documents
source_parts
scenario_version draft
content_items draft
```

此时可以建立：

```text
admin_source staging index
```

只供 Admin 导入预览和质量排查。

不能供运行时房间使用。

---

## 阶段 2：编译与复核

执行：

```text
结构校验
实体消歧
勘误覆盖
可见性校验
Trigger 校验
SourceRef 校验
内容泄露扫描
```

生成：

```text
canonical content projection
```

---

## 阶段 3：发布前构建 RAG

生成新的：

```text
rag_build_id
```

所有 Chunk 先写：

```text
status=staged
```

完成后执行：

```text
embedding 数量校验
embedding 维度校验
citation 覆盖检查
visibility 检查
敏感词和路径扫描
重复 Chunk 检查
检索回归测试
```

---

## 阶段 4：原子激活

只有全部通过后：

```text
scenario_versions.rag_index_version = new_build_id
new build status = active
old build status = superseded
```

查询时必须显式：

```sql
WHERE rag_build_id = scenario_versions.rag_index_version
  AND status = 'active'
```

这样重建失败不会影响现有房间。

---

# 十一、具体的写入服务

建议不要让 ImportService 分散调用：

```text
index_scenario_version
index_npc_graph
index_content_projection
```

改成一个统一入口：

```python
class RAGIndexService:
    def build_scenario_version(
        self,
        scenario_id: str,
        scenario_version_id: str,
        requested_by: str,
    ) -> RAGBuildResult:
        ...
```

伪代码：

```python
def build_scenario_version(...):
    version = load_scenario_version(scenario_version_id)
    items = load_content_items(scenario_version_id)
    edges = load_content_edges(scenario_version_id)
    sources = load_source_parts(scenario_version_id)

    build = begin_rag_build(
        scenario_version_id=scenario_version_id,
        embedding_space=select_embedding_space(),
    )

    plan = rag_projection_planner.build(
        version=version,
        content_items=items,
        content_edges=edges,
        raw_sources=sources,
    )

    embedding_session = open_embedding_session(build.embedding_space)

    for batch in batch_chunks(plan.chunks):
        vectors = embedding_session.embed([c.content for c in batch])

        validate_vectors(batch, vectors)

        insert_staged_chunks(
            build_id=build.id,
            chunks=batch,
            vectors=vectors,
        )

    report = validate_rag_build(build.id)

    if report.blockers:
        fail_build(build.id, report)
        return failed_result(report)

    activate_build_atomically(
        scenario_version_id=scenario_version_id,
        build_id=build.id,
    )

    return completed_result(build.id, report)
```

---

# 十二、Embedding 模型必须按 Build 固定

当前默认本地模型是：

```text
shibing624/text2vec-base-chinese
```

本地失败后可以回退远程模型，当前代码还会记录实际模型和维度。

这个方向有一个风险：

```text
原文索引使用本地模型
NPC 索引时本地失败，使用远程模型
content 索引又恢复本地模型
```

同一个 RAG Build 可能混入多个向量空间。

当前搜索只在：

```text
embedding_model 相同
embedding_dimensions 相同
```

时计算向量相似度，所以不同模型的部分 Chunk 会退化成只走关键词检索。

正确做法是：

# `EmbeddingSession`

构建开始时选择一个模型：

```text
本次全部使用本地
```

如果失败：

```text
整个 Build 失败
```

或者：

```text
整个 Build 从头使用远程模型重建
```

不能在同一 Build 中途切换模型。

建议增加：

```text
embedding_space_id
model_name
dimensions
normalization
model_revision
```

P0 最简单：

```text
全平台统一一个生产 embedding model
固定 768 维
每次更换模型都新建 Build
```

---

# 十三、检索请求也必须结构化

不要只有：

```python
rag.search(query, room_id, top_k)
```

建议定义：

```json
{
  "task": "player_intent_understanding",
  "viewerRole": "player",
  "roomId": "room_xxx",
  "characterId": "char_xxx",
  "scenarioVersionId": "version_xxx",
  "stateVersion": 85,

  "query": "我想搜查院长书桌",
  "sourceTypes": [
    "rule",
    "room_knowledge"
  ],

  "allowedVisibilities": [
    "party",
    "character_private"
  ],

  "entityRefs": [
    "location:director_office",
    "object:director_desk"
  ],

  "maxChunks": 8,
  "maxTokens": 2500
}
```

---

# 十四、建议的查询顺序

```text
1. 身份与房间鉴权
2. 绑定当前 scenarioVersion / ragBuild
3. 读取当前 State 和角色权威值
4. 精确匹配当前实体 ID
5. 查询图关系和当前 Trigger
6. 根据 task_scope 选择允许的 corpus
7. 权限过滤
8. 向量 + 关键词召回
9. Rerank
10. 去重和多样性控制
11. final context filter
12. 生成 ContextPackage
```

Current RAG 已经使用：

```text
75% 向量相似度
25% 关键词分数
```

作为混合检索基础，可以保留。

但建议改成：

```text
先召回 20～40 条候选
→ 再按任务、实体、权威性、时态和来源重新排序
→ 最终给模型 5～10 条
```

而不是七个 source type 各自固定取几条。

---

# 十五、Rerank 建议考虑什么

```text
语义相似度
关键词命中
当前实体匹配
当前场景匹配
当前线程匹配
来源权威等级
是否为 canonical
是否为当前版本
是否为当前房间
时间新鲜度
是否已被 superseded
玩家是否有权知道
是否已经 unlock
内容重复度
```

示意：

```text
final_score =
0.35 * semantic
+ 0.15 * lexical
+ 0.20 * entity_match
+ 0.15 * authority
+ 0.10 * recency
+ 0.05 * source_quality
- duplicate_penalty
- stale_penalty
```

但：

> 权限、visibility、unlock 和 branch 不是打分项，而是硬过滤项。

---

# 十六、不同 AI 任务应该搜不同语料

|AI 任务|允许检索|
|---|---|
|IntentCompiler|玩家可见场景、实体、角色能力、当前物品|
|MechanicCompiler|Rule Corpus、房规、模组规则覆盖|
|DirectorAdvisor|Module Internal、StoryThread、NPC Agenda、Clock|
|Narrator Public|已提交 public facts、公共素材、公开描述|
|Narrator Private|本角色私密结果、本人知识|
|Investigation Assistant|room_knowledge、Party 证据、本人笔记授权|
|Host Review|Rule evidence、State diff、Module source citation|
|Admin Import Review|admin_source、结构化候选、冲突和低置信度来源|

不能存在：

```text
一个 build()
一套 SOURCE_QUOTAS
所有 AI 任务通用
```

---

# 十七、运行时数据怎么写入 RAG

Module RAG 发布后应该保持不可变。

房间运行过程中写的是：

# **Room Runtime RAG**

## 事件

当前代码会直接把：

```text
[event_type] + JSON payload
```

写进 RAG。

建议改成先生成安全视图：

```text
HostEventIndexView
PartyEventIndexView
CharacterEventIndexView
```

然后分别写入。

不能直接向量化原始事件 payload，因为其中可能包含：

```text
private patch
internal IDs
调试字段
隐藏信息
```

---

## 线索

玩家获得线索：

```text
private:self chunk
```

分享后：

```text
新增 party chunk
内容只能使用 publicVersion
```

不能把私密原文 Chunk 的 visibility 直接改为 Party。

应保留：

```text
私人原文
Party 公共版本
```

两个独立 Chunk。

---

## 角色

适合向量化：

```text
人物背景
性格
关系
长期经历
叙事偏好
```

不适合向量化：

```text
当前 HP
当前 SAN
当前 Luck
当前装备次数
当前位置
当前状态
```

后者直接从 State / CharacterRuntimeView 提供。

---

## NPC

房间内已公开 NPC 信息应从：

```text
NpcKnowledgeView
```

生成，不直接索引完整 Module NPC。

---

## 调查工作台

可以写：

```text
EvidenceCard
OpenQuestion
Hypothesis
Party Note
Player Private Note（仅明确授权 AI）
```

玩家 Hypothesis 必须带：

```text
epistemic_status=hypothesis
```

不能让 AI 将其当 Canon。

---

# 十八、当前代码建议优先修的 10 项

## P0-1：取消 `audience="ai"`

改为：

```text
task_scope
viewer_role
character_id
```

---

## P0-2：统一 visibility 枚举

统一：

```text
public
party
character_private
host_only
admin_only
internal
```

---

## P0-3：Player AI 禁止检索 raw scenario

Player 任务只能检索：

```text
room_knowledge
rule public view
本人 private knowledge
```

---

## P0-4：以 content projection 为主要 Module 索引

运行时主索引：

```text
content_items
```

原文索引：

```text
admin_source fallback
```

---

## P0-5：修复 NPC 检索结果丢失

RAG Context 返回对象应有：

```text
npcs
```

或者直接统一成：

```text
chunks[]
```

避免按类型手写分支漏掉。

---

## P0-6：角色当前状态改为 direct runtime context

不再从 `xlsx_data` 提供当前 HP/SAN。

---

## P0-7：Chunk 增加 `rag_build_id`

检索只访问当前 active Build。

---

## P0-8：Embedding 模型按 Build 固定

禁止一个 Build 中混用本地和远程向量。

---

## P0-9：语义切块替代纯字符切块

至少先支持：

```text
Scene
NPC
Clue
Rule
Trigger
NarrativeTemplate
```

专用 Chunker。

---

## P0-10：Room Runtime RAG 与 Module RAG 分离

不要让：

```text
未触发 Module Clue
```

和：

```text
玩家已获得 Clue
```

存在同一个可被 Player AI 查询的语料空间。

---

# 十九、推荐实施批次

## RAG-0：当前链路和泄露测试

锁定：

```text
audience=ai
visibility enum
NPC 结果丢失
xlsx_data runtime
raw scenario player prompt
```

---

## RAG-1：RAG Build 与版本原子化

增加：

```text
rag_build_id
status
active build pointer
EmbeddingSession
```

---

## RAG-2：Canonical Projection Index

把：

```text
content_items
```

变成 Module Runtime 的主要检索来源。

---

## RAG-3：语义 Chunker

分别实现：

```text
SceneChunker
NpcChunker
ClueChunker
RuleChunker
TriggerChunker
NarrativeChunker
```

---

## RAG-4：Task-aware Context Builder

替换通用 `RAGContextBuilder.build()`：

```text
build_for_intent()
build_for_mechanic()
build_for_director()
build_for_public_narrative()
build_for_private_narrative()
build_for_investigation()
build_for_host_review()
```

---

## RAG-5：Room Runtime Corpus

实现：

```text
EventIndexView
CluePrivateIndex
CluePartyIndex
NpcKnowledgeIndex
MemoryClaimIndex
InvestigationIndex
```

---

## RAG-6：Hybrid Retrieval 与 Rerank

```text
结构查询
图扩展
关键词
向量
Rerank
去重
Token Budget
```

---

## RAG-7：质量门和回归

验证：

```text
检索准确性
引用覆盖率
权限
剧透
版本切换
重建失败
Embedding 模型变化
```

---

# 二十、最关键的验收测试

```text
1. 未发布草稿不能进入活动房间 RAG。
2. active room 只能检索绑定的 scenarioVersion 和 ragBuild。
3. 新 RAG Build 失败不影响旧 Build。
4. Player AI 不能检索 raw scenario。
5. Player AI 不能检索 latent clue。
6. Player A 私密线索不能进入 Player B 上下文。
7. 分享线索后 Party 只检索 publicVersion。
8. Host-only truth 不进入 public narrator。
9. Narrator AI 不能检索完整 ending。
10. Trigger condition/effect 不被拆到不同 Chunk。
11. Errata 生效后 canonical RAG 只返回有效值。
12. 原始冲突版本只在 Admin source audit 中可见。
13. 每个 canonical Chunk 都有 sourcePart/citation。
14. 检索结果能够返回页码、Sheet、单元格或来源锚点。
15. 同一个 Build 中所有 embedding model 和 dimensions 一致。
16. 更换 embedding model 必须完整重建。
17. 当前 HP/SAN 不从向量库读取。
18. 当前地图位置不从向量库读取。
19. NPC 搜索结果会真实进入对应 Context。
20. Restore 后只检索当前历史分支允许的 runtime knowledge。
21. RAG 结果不能绕过 RevealGate 创建世界事实。
22. AI 生成内容不能直接反写 RAG 成为 canonical。
```

---

# 一个端到端例子

原始剧本写道：

> 若调查员成功搜查院长书桌，则发现一把刻有 B-17 的黄铜钥匙。

导入后不应只生成一段向量文本。

应该生成：

## Canonical 结构

```text
object:director_desk
clue:brass_key_b17
trigger:search_director_desk
location:b17
```

## Trigger 结构

```json
{
  "condition": {
    "type": "successful_search",
    "targetRef": "object:director_desk"
  },
  "effect": {
    "type": "instantiate_clue",
    "templateRef": "clue:brass_key_b17"
  }
}
```

Trigger 的执行走：

```text
Engine / Rule / Clue / State
```

不走向量搜索。

## Module RAG Chunk

```text
corpus=module_internal
projectionKind=trigger_explanation
visibility=host_only

“成功搜查院长书桌时，可以实例化黄铜钥匙线索。”
```

用于 Director / Host Review 解释。

## 玩家尚未发现时

```text
room_knowledge 中没有该钥匙
Player AI 不可能召回它
```

## 玩家发现后

系统创建：

```text
ClueInstance
ItemInstance
PlayerPrivateKnowledge
```

并向 Room Runtime RAG 写：

```text
corpus=room_character
characterId=char_a
visibility=character_private

“你在院长书桌中发现了一把刻有 B-17 的黄铜钥匙。”
```

## 玩家分享后

另外写：

```text
corpus=room_party
visibility=party

“队伍得知：院长书桌里藏着一把刻有 B-17 的黄铜钥匙。”
```

原私密 Chunk 不改变。

---

# 最终定义

> **AI-Keeper 的 RAG 不应是完整剧本的向量副本，而应是 Module、Ruleset 和 Room Runtime 的版本化检索投影。原始文件保存在 Source 层，规范事实保存在 content_items 和 State 中，图关系负责精确连接，RAG 只负责语义召回。每个 Chunk 都必须绑定 ModuleVersion、RAG Build、来源引用、权威等级、任务范围和可见性；Player AI 只检索房间中已经被正式揭示的知识，Director 和 Host 才能访问 Module Internal。RAG 可以帮助 AI 找到相关信息，但不能执行 Trigger、决定事实、修改状态或绕过 RevealGate。**