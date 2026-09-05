这里确实要再挖深。**“AI 自动整理线索”能不能成立，前提不是模型够聪明，而是剧本和辅助资料先被编译成一套结构稳定、来源清楚、权限明确的中间表示。**

核心结论先放前面：

> **不要把产品设计成“上传一堆文件 → 全部切块进向量库 → AI 自己理解”。**  
> 应该设计成：  
> **多格式素材包 → 原文保真解析 → 语义单元识别 → 实体与关系对齐 → 规则和触发器编译 → 人工复核 → 不可变 ModuleVersion → 面向不同任务和视角的运行时投影。**

我建议把这套内部能力命名为：

# **Module Compiler / 模组编译器**

它不是新的大型产品模块，而是串联现有模块的内部编译管线：

```text
18-Asset        负责文件、安全存储、assetId
07-WorldBook    负责文档解析、语义抽取、知识结构
19-Module       负责草稿、校验、版本、发布和实例化
12-AI-Keeper    负责候选识别和语义建议
21-Safety       负责可见性、反剧透和字段裁剪
04-Rule         负责规则结构和触发器验证
05/06/08/09     接收角色、NPC、线索、地图编译结果
```

多格式文档可以先转成统一文档表示，再进入语义层。类似 Docling 这样的文档处理项目已经采用“多格式解析 → 统一文档表示”的路线，覆盖 PDF、DOCX、PPTX、XLSX、HTML、EPUB、音频、图片等格式，并保留布局、表格和阅读顺序等结构；这比简单抽取纯文本更适合复杂模组。([Docling Project](https://docling-project.github.io/docling/ "Index - Docling"))

---

# 一、首先要分清两个维度：文件格式和资料角色

这是最容易被忽略的一点。

同样是 PDF，它可能是：

```text
核心剧本
规则书
补充章节
勘误
玩家 Handout
主持人地图册
角色预设
战役年表
实际跑团记录
```

同样是 XLSX，它可能是：

```text
NPC 数值表
角色预设
随机遭遇表
时间线
物品价格表
线索矩阵
本地化术语表
```

所以系统不能只问：

> 这是什么文件格式？

还必须问：

> 这份资料在模组中扮演什么角色？它有没有权威性？谁能看？它会覆盖什么？

建议每个导入源都至少带四组分类。

## 1. 物理格式

```text
PDF
DOCX / ODT
EPUB / HTML / Markdown / TXT
PPTX / ODP
XLSX / CSV / ODS
JSON / YAML / XML
PNG / JPG / TIFF / WEBP
WAV / MP3 / WEBVTT
ZIP / 模组包
未知二进制文件
```

## 2. 语义角色 `sourceRole`

```text
core_adventure          核心剧本
canonical_supplement     官方补充
errata                   勘误
rule_reference           规则参考
module_rule_override     模组规则覆盖
house_rule               房间团规
npc_roster               NPC 表
character_templates      预设角色
map_pack                 地图包
map_key                  地图说明
clue_catalog             线索目录
player_handout           玩家手册/手out
gm_reference             主持人速查
random_tables            随机表
timeline_reference       剧本时间线
asset_pack               图片音频素材
localization             翻译/术语表
actual_play_example      实际跑团示例
runtime_patch            Host 后续补丁
```

## 3. 权威等级 `authorityClass`

```text
canonical
canonical_override
module_override
house_rule
reference_only
example_only
player_authored
ai_inferred
```

## 4. 可见性

```text
admin_only
host_only
hidden_until_reveal
party_after_reveal
player_private
public
```

最关键的规则是：

> **文件格式不能决定权威性，文件名不能决定可见性，AI 推断不能自动获得 canonical 身份。**

---

# 二、建立一个显式的 Module Manifest

对于结构良好的模组包，最好允许作者、Host 或平台提供一个 `module.yaml`。

它是整个模组资料的目录和优先级说明。

```yaml
module:
  moduleId: mod_hospital_001
  title: 圣玛丽医院
  version: 1.2.0
  ruleset:
    id: coc7e
    edition: 7
    language: zh-CN

sources:
  - sourceId: src_core
    path: core_adventure.pdf
    role: core_adventure
    authority: canonical
    visibility: host_only

  - sourceId: src_npcs
    path: data/npcs.xlsx
    role: npc_roster
    authority: canonical
    visibility: host_only

  - sourceId: src_errata
    path: errata.md
    role: errata
    authority: canonical_override
    appliesTo:
      sourceId: src_core
      version: 1.1.0

  - sourceId: src_map
    path: maps/hospital_floor_1.png
    role: map_pack
    authority: canonical
    visibility: hidden_until_reveal

  - sourceId: src_handout_01
    path: handouts/burnt_prescription.png
    role: player_handout
    authority: canonical
    visibility: hidden_until_reveal

  - sourceId: src_house_rules
    path: house_rules.yaml
    role: house_rule
    authority: house_rule
    visibility: party_after_reveal

bindings:
  - asset: src_map
    targetRef: location:hospital_floor_1
    bindingRole: map_image

  - asset: src_handout_01
    targetRef: clue:burnt_prescription
    bindingRole: handout_image
```

没有 manifest 时，AI 可以生成一个**候选 manifest**，但需要进入复核队列：

```text
AI 判断：npcs.xlsx 可能是 NPC 名册
置信度：0.94
[确认] [修改资料角色] [仅作为附件]
```

也就是说：

> **显式配置优先，确定性识别其次，AI 推断最后。**

---

# 三、不要直接把所有文件转成纯文本

需要先建立一个统一的：

# **Normalized Source Document / 规范化源文档**

它保留的不只是文字，还要保留原始结构和定位信息。

不同格式的来源定位方式不同：

|格式|必须保留的 SourceRef|
|---|---|
|PDF|页码、区域坐标、块 ID、阅读顺序|
|扫描 PDF|页码、OCR 区域、OCR 置信度|
|DOCX|标题路径、段落 ID、表格单元格|
|EPUB/HTML|章节、DOM 路径、锚点|
|PPTX|幻灯片号、对象 ID、备注区|
|XLSX|Sheet、表格名、行列、单元格范围|
|CSV|行号、列名|
|JSON/YAML|JSON Pointer / 对象路径|
|图片地图|像素区域、标注框、多边形、图层|
|音频视频|起止时间、说话人、转写片段|
|ZIP|包内路径、文件哈希、manifest 关系|

例如：

```json
{
  "sourceRef": {
    "sourceId": "src_core",
    "format": "pdf",
    "page": 47,
    "blockId": "block_47_18",
    "bbox": [83, 211, 482, 365],
    "textHash": "sha256:..."
  }
}
```

这样以后才能回答：

```text
这条 NPC 信息来自哪一页？
这条规则是在表格哪一行？
这张手out 对应哪个 clue？
AI 为什么认为这里是一段玩家朗读文本？
```

Apache Tika 也采用格式适配器抽取不同办公文档、PDF、音频等内容和元数据；但对你们而言，重点不是选定某个库，而是建立稳定的“格式适配器 → 统一源文档”接口。([Apache Tika](https://tika.apache.org/2.9.2/formats.html "Apache Tika – Supported Document Formats"))

---

# 四、建议建立三层中间表示，而不是直接生成知识图谱

## 第一层：Source IR

保留文档原始结构：

```text
Document
Section
Heading
Paragraph
Table
TableRow
List
Image
Caption
Footnote
Sidebar
Callout
StatBlock
ReadAloudBox
MapRegion
AudioSegment
```

这一层尽量不解释剧情，只负责：

```text
原文是什么
位于哪里
布局是什么
哪一块与哪一块相邻
```

---

## 第二层：Semantic IR

识别这段内容“在表达什么”。

例如：

```text
Entity
Assertion
Instruction
Condition
Effect
NarrativeTemplate
RuleSpec
RandomTable
Variant
Reference
AssetBinding
```

---

## 第三层：Runtime IR

把已经确认的语义对象编译成系统可使用的对象：

```text
SceneTemplate
NpcTemplate
ClueTemplate
ItemTemplate
EncounterTemplate
MapDraft
CharacterTemplate
TriggerDefinition
RuleOverride
SpoilerSensitiveItem
RagChunk
NarrativeTemplate
ModuleReadinessReport
```

整体链路：

```text
原始文件
  ↓
Source IR
  ↓
Semantic IR
  ↓
校验与人工复核
  ↓
Runtime IR
  ↓
不可变 ModuleVersion
  ↓
Room 实例化
```

GraphRAG 的官方索引管线会从非结构化文本中抽取实体、关系和 claims，并生成层次化摘要和向量表示；你们可以借鉴这种“多产物索引”，但不能只停在实体关系图，因为 TRPG 还需要条件、规则、权限、时态和运行态区分。([GitHub上微软](https://microsoft.github.io/graphrag/index/overview/ "Overview - GraphRAG"))

---

# 五、最关键的结构：一段文本到底属于什么语义模式

这是 AI 是否会“合理识别”的生死线。

模组里的句子不能全部被当成世界事实。

建议每个语义单元都必须有 `semanticMode`。

|模式|示例|AI 应如何处理|
|---|---|---|
|`canonical_fact`|院长实际参与了实验|Host-only 模组真相|
|`conditional_trigger`|若调查员检查抽屉，则发现钥匙|编译成条件和效果，不是已发生事实|
|`gm_instruction`|若节奏过慢，可让警报响起|Host 建议，不自动执行|
|`read_aloud_template`|“走廊尽头传来拖拽声……”|可用叙事模板，不是已经播出的事件|
|`testimony`|护士说院长昨晚没离开办公室|记录为证词，不认定内容为真|
|`rumor`|有人说地下室闹鬼|传闻，不是事实|
|`optional_variant`|可选：院长也可能是无辜的|变体，不与主版本同时生效|
|`random_table_option`|1–2 狼群，3–6 匪徒|随机候选，不表示全部存在|
|`rule_definition`|黑暗环境增加一个惩罚骰|规则对象|
|`example`|示例：调查员可以尝试说服守卫|示例，不是剧情事件|
|`player_handout`|写给玩家看的信件内容|待揭示素材|
|`metadata`|推荐 3–5 名玩家|模组元数据|
|`editorial_note`|译者注：原文有歧义|资料说明，不进入剧情|

建议统一对象：

```json
{
  "unitId": "unit_xxx",
  "kind": "clue_definition",
  "semanticMode": "conditional_trigger",
  "authorityClass": "canonical",
  "visibility": "host_only",
  "text": "若调查员成功搜查书桌，则发现黄铜钥匙。",
  "subjectRefs": [
    "location:director_office",
    "object:desk"
  ],
  "condition": {
    "type": "successful_check",
    "action": "search",
    "targetRef": "object:desk"
  },
  "effect": {
    "type": "instantiate_clue",
    "templateRef": "clue:brass_key"
  },
  "sourceRefs": [
    {
      "sourceId": "src_core",
      "page": 47,
      "blockId": "block_47_18"
    }
  ],
  "reviewStatus": "confirmed"
}
```

这段话绝不能被 RAG 简化成：

> 玩家已经找到了黄铜钥匙。

它只表示：

> **存在一个尚未触发的发现条件。**

---

# 六、每个语义对象都要带五个维度

建议不要只存：

```text
type
text
confidence
```

至少要存：

## 1. 类型

```text
NPC
Scene
Location
Clue
Item
Rule
Trigger
Handout
EventTemplate
Faction
Ending
```

## 2. 语义模式

```text
fact
condition
instruction
template
testimony
rumor
variant
random_option
example
```

## 3. 权威等级

```text
canonical
errata_override
module_override
house_rule
reference
ai_inferred
```

## 4. 可见性

```text
host_only
hidden_until_reveal
party
player_private
public
```

## 5. 生命周期

```text
latent          已在模组里定义，但未实例化
available       当前条件允许触发
instantiated    已进入房间运行态
revealed        已向对应玩家揭示
resolved        已处理
invalidated     被修订或分支恢复失效
```

有了这五个维度，AI 才不会把：

```text
可选剧情
随机表结果
Host 建议
玩家朗读文本
未触发线索
```

混成已经发生的事实。

---

# 七、统一的实体 ID 比名字更重要

所有模组对象必须有稳定 ID：

```text
npc:professor_chen
location:hospital_basement
scene:night_shift
clue:burnt_prescription
item:brass_key
trigger:search_director_desk
map:st_mary_floor_1
```

名字只能作为 label 或 alias：

```json
{
  "entityId": "npc:professor_chen",
  "entityType": "npc",
  "labels": {
    "zh-CN": "陈致远教授",
    "en": "Professor Chen"
  },
  "aliases": [
    {
      "text": "陈教授",
      "sourceId": "src_core",
      "status": "confirmed"
    },
    {
      "text": "戴银框眼镜的男人",
      "sourceId": "src_handout",
      "status": "possible"
    }
  ]
}
```

AI 看到“陈教授”“陈致远”“院长的顾问”，不能直接自动合并。

建议关系状态：

```text
confirmed_same_entity
possible_same_entity
distinct_entities
needs_review
```

在调查剧本中，“可能是同一个人”本身就可能是谜题，不能因实体消歧而提前泄露答案。

---

# 八、跨文件关联应该分五个等级

## 1. 显式关联

最可靠。

来源：

```text
manifest
assetId
内部超链接
书签
JSON foreign key
表格 ID
文件内对象引用
```

例如：

```yaml
asset: handout_01
targetRef: clue:burnt_prescription
```

可直接确认。

---

## 2. 确定性规则关联

例如：

```text
XLSX 的 npc_id 与 JSON 的 npc_id 一致
文件名和显式 ID 一致
PDF 文字写“见附录 B-12”
地图标号和 map key 表一致
```

通常可以自动确认，但仍保留来源。

---

## 3. 布局和空间关联

例如：

```text
图片紧跟在“烧焦处方”标题下
表格位于“院长”人物章节内部
地图标注 B2 位于地下室区域
PPTX 备注属于当前幻灯片
```

这类关系依赖布局，不能把 PDF 只转纯文本后再处理。

---

## 4. 语义候选关联

例如：

```text
“陈教授”
“陈致远”
“医院顾问”
```

AI 判断可能同一人。

这只能进入：

```text
proposed_link
```

不能直接成为 canonical link。

---

## 5. 人工确认关联

Host 或编辑者最终确认：

```text
确认同一对象
保持分开
建立“可能同一人”关系
```

每条关联建议记录：

```text
linkMethod
linkConfidence
reviewStatus
confirmedBy
sourceRefs
reason
```

---

# 九、不要只存一个“confidence”

AI 置信度经常被滥用。

建议至少拆成：

```text
parseConfidence
typeConfidence
entityResolutionConfidence
linkConfidence
extractionConfidence
```

但这些都不等于：

```text
这件剧情事实有 90% 概率是真的
```

还要单独存：

```text
authorityClass
epistemicStatus
reviewStatus
```

例如：

```json
{
  "parseConfidence": 0.98,
  "typeConfidence": 0.94,
  "linkConfidence": 0.72,
  "authorityClass": "canonical",
  "epistemicStatus": "testimony",
  "reviewStatus": "needs_review"
}
```

这里即使文本解析置信度很高，它仍然只是一段证词，不是世界真相。

---

# 十、辅助资料之间不应使用单一全局优先级

不同领域要使用不同覆盖规则。

## 剧情真相

```text
Host 正式 Retcon
> 官方 Errata
> 当前 ModuleVersion 核心剧本
> 官方补充
> AI 推断
```

## 规则结算

```text
房间 House Rule
> 模组 Rule Override
> 当前 Ruleset Edition
> 通用默认规则
> AI 建议
```

## 素材展示

```text
Room 运行态指定素材
> Scene AssetBinding
> Module 默认封面
> AI 推荐素材
```

## 本地化文本

```text
Host 手工修订
> 官方翻译
> 社区翻译
> 自动翻译
> 原文 fallback
```

因此建议每个覆盖关系显式记录：

```text
overrides
supersedes
appliesTo
effectiveVersion
```

W3C PROV-O 中也提供了来源、派生、修订和生成活动等通用溯源概念；你们不必直接引入完整 RDF 技术栈，但非常值得借用“谁从什么来源、经什么活动生成、修订了谁”的模型。([W3C](https://www.w3.org/TR/prov-o/ "PROV-O: The PROV Ontology"))

---

# 十一、建议定义一个 Module Intermediate Representation

# **MIR：Module Intermediate Representation**

这是整个模组编译器的核心产物。

它可以使用普通 JSON，不强制上 RDF，但概念上借鉴 linked data：

```json
{
  "moduleId": "mod_hospital",
  "moduleVersionId": "mod_hospital@1.2.0",
  "ruleset": {
    "id": "coc7e",
    "edition": "7"
  },
  "entities": [],
  "assertions": [],
  "scenes": [],
  "triggers": [],
  "rules": [],
  "narrativeTemplates": [],
  "assetBindings": [],
  "characterTemplates": [],
  "mapDrafts": [],
  "sourceDocuments": [],
  "conflicts": [],
  "reviewDecisions": [],
  "qualityReport": {}
}
```

JSON-LD 的价值在于通过稳定节点标识和上下文，把不同 JSON 对象连接成可互操作的 linked data；即使你们初期只使用普通 JSON，也建议采用相似的“稳定 ID + 类型 + 引用”原则。([W3C](https://www.w3.org/TR/json-ld11/ "JSON-LD 1.1"))

---

# 十二、AI 抽取不能是一遍大 Prompt

不建议：

```text
把 300 页 PDF 全部交给模型
→ 让它返回完整 JSON
```

正确方式应该是多阶段编译。

## Stage 0：安全接入

```text
格式探测
MIME / 文件头
大小限制
解压限制
文件哈希
病毒/危险格式策略
SourceAsset 创建
```

## Stage 1：确定性解析

```text
布局解析
文字抽取
表格识别
图片提取
章节层级
页码和坐标
OCR 置信度
```

## Stage 2：文档区域分类

识别：

```text
正文
主持人说明
玩家朗读框
NPC 数值块
规则块
随机表
地图 Key
Handout
附录
脚注
示例
```

## Stage 3：语义候选抽取

按小块生成候选：

```text
NPC 候选
Location 候选
Scene 候选
Clue 候选
Rule 候选
Trigger 候选
AssetBinding 候选
```

每个候选必须带 SourceRef。

## Stage 4：实体消歧

```text
名称
别名
章节范围
显式 ID
表格引用
上下文
布局
```

低置信度不自动合并。

## Stage 5：关系与 Assertion 抽取

例如：

```text
NPC belongs_to Faction
Clue located_in Location
Scene follows Scene
Trigger reveals Clue
NPC reports Statement
Rule modifies Check
Asset illustrates Scene
```

## Stage 6：规则与触发器编译

将自然语言条件转成结构化 DSL。

例如：

```text
“若调查员成功搜查抽屉，发现钥匙”
```

编译为：

```json
{
  "triggerId": "trigger:desk_search",
  "scope": "scene",
  "condition": {
    "type": "successful_check",
    "action": "search",
    "targetRef": "object:director_desk"
  },
  "effects": [
    {
      "type": "instantiate_clue",
      "templateRef": "clue:brass_key"
    }
  ]
}
```

## Stage 7：确定性校验

检查：

```text
引用的 NPC 是否存在
Trigger target 是否存在
Clue 是否有 sourceRefs
Map node 是否可解析
Rule type 是否支持
Player handout 是否绑定 reveal 条件
Host-only 字段是否误标 public
随机表范围是否连续
场景 ID 是否重复
```

图数据可使用形状和约束做机器校验。SHACL 就是面向图结构描述和验证约束的标准；你们可以采用 JSON Schema、自定义验证器或类似 SHACL 的约束思想，重点是不要把“LLM 返回了 JSON”当成“结构正确”。([W3C](https://www.w3.org/TR/shacl/ "Shapes Constraint Language (SHACL)"))

## Stage 8：冲突检测

检查：

```text
同一 NPC 两个不同年龄
同一地点两个不同编号
Errata 和核心文本冲突
地图 Key 和地图标签冲突
规则表和正文冲突
两个文件都声明自己是 authoritative
```

冲突只进入 review queue，不由 AI 静默裁决。

## Stage 9：人工复核

只让人复核高风险内容：

```text
模组真相
结局
实体合并
触发器
规则覆盖
可见性
勘误覆盖
地图拓扑
Handout 揭示条件
```

## Stage 10：编译 ModuleVersion

通过质量门后生成不可变版本。

---

# 十三、人工复核不应该让 Host 看完全部抽取结果

需要风险分级。

## 自动接受

```text
确定性 ID 引用
显式表格字段
manifest 绑定
标题和章节层级
低风险元数据
```

## 建议快速确认

```text
NPC 别名
图片与场景绑定
人物关系
地图区域名称
规则引用
```

## 必须人工确认

```text
世界真相
结局
隐藏线索
实体合并
触发器 condition/effect
规则 override
勘误覆盖
public / host_only 边界
```

Import Review UI 可以分成：

```text
需要确认的实体
未绑定的素材
存在冲突的资料
低质量 OCR
无来源的候选
危险可见性
不支持的规则
无效触发器
```

---

# 十四、手工修改必须是 Overlay，不能直接改掉 AI 产物

否则下一次重新导入就会丢失人工修订。

建议保存：

```text
Generated Layer
Manual Overlay
Compiled Result
```

例如：

```text
AI 抽取：
陈教授 -> npc_temp_021

Host 修正：
canonicalId = npc:professor_chen
alias = 陈教授
```

重新编译时：

```text
原始来源变化
→ 重做 Generated Layer
→ 重新应用 Manual Overlay
→ 检查 Overlay 是否仍有效
→ 生成新的 Compiled Result
```

人工修订应记录：

```text
actor
reason
before
after
sourceVersion
createdAt
```

---

# 十五、辅助资料更新必须做增量编译

加入一张新地图，不应该重新处理整本 300 页 PDF。

建议用依赖图：

```text
SourceFragment
→ SemanticUnit
→ Entity / Trigger / AssetBinding
→ Runtime View
```

当一个源发生变化时，只重编译受影响对象。

例如：

```text
errata.md 修改 NPC 年龄
```

只影响：

```text
npc:professor_chen
人物卡
RAG chunks
quality report
ModuleVersion
```

不必重建所有地图和角色模板。

---

# 十六、活跃房间必须固定在不可变 ModuleVersion 上

这是长期团稳定性的关键。

错误设计：

```text
Room 只引用 scenario_id
Admin 修改源 scenario
运行中的房间立即受到影响
```

正确设计：

```text
Room.moduleVersionId = mod_hospital@1.2.0
```

以后资料更新生成：

```text
mod_hospital@1.2.1
```

老房间仍使用 1.2.0。

Host 可以显式选择：

```text
保持当前版本
查看差异
迁移到新版本
```

迁移需要显示：

```text
NPC 变化
规则变化
Trigger 变化
地图变化
Handout 变化
可能影响的运行态状态
```

---

# 十七、不同任务不能共用一个“大 RAG”

运行时 AI 不应该直接搜索所有原始文档。

建议编译出不同的任务视图。

## 1. `NarrativeContextView`

只提供：

```text
当前场景
当前已发生事件
可见 NPC
允许叙事的事实
NarrativeTemplate
```

## 2. `RuleContextView`

只提供：

```text
当前 ruleset
module rule override
house rule
相关 RuleSpec
```

## 3. `InvestigationContextView`

只提供：

```text
当前玩家已知的证据
人物卡
开放问题
玩家授权的笔记
```

## 4. `AssetContextView`

只提供：

```text
当前场景可用素材
授权 assetId
reveal state
```

## 5. `HostReviewContextView`

提供：

```text
完整来源
抽取置信度
冲突
规则计划
审计链
```

## 6. `PublicModuleView`

只提供：

```text
公开标题
公开简介
人数
时长
规则系统
内容警示
公开封面
```

RAG 的基本思想是让生成模型访问显式的外部知识存储，而不是只依赖模型参数；但在你们的场景中，检索之后还必须额外判断来源权威性、可见性、时态和语义模式。([arXiv](https://arxiv.org/abs/2005.11401?utm_source=chatgpt.com "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks"))

---

# 十八、运行时 AI 应该采用混合检索，而不是只做向量相似度

推荐检索顺序：

```text
1. 精确 ID 和当前状态
2. 显式引用
3. 图关系邻域
4. 关键词 / BM25
5. 向量语义召回
6. 重新排序
7. 权限和语义模式最终过滤
```

向量搜索适合找：

```text
语义相近的描述
可能相关的段落
不同措辞的同一概念
```

它不适合单独决定：

```text
哪个规则优先
这是不是事实
玩家有没有权限
一条资料是否已过期
两个 NPC 是否真是同一人
某个 Trigger 是否已触发
```

---

# 十九、给 AI 一个明确的任务路由器

AI 收到请求时先判断任务，不是直接搜全文。

|任务|主要数据视图|
|---|---|
|“这个 NPC 是谁？”|EntityView + 已知事件|
|“我角色知道这件事吗？”|Knowledge / Projection View|
|“这次该掷什么？”|RuleContext + Intent Contract|
|“搜索抽屉会发生什么？”|当前 Scene + Trigger，但只给 Engine/Host|
|“显示场景图”|AssetBinding + reveal state|
|“我们有哪些矛盾证词？”|InvestigationContext|
|“给我上次剧情摘要”|Journal + Memory View|
|“重建模组索引”|Admin Compiler View|

任务路由决定：

```text
查哪些索引
允许看什么
是否需要 SourceRef
是否允许返回隐藏内容
```

---

# 二十、一个完整的多资料关联示例

模组包有：

```text
core.pdf
npcs.xlsx
maps/hospital.png
maps/map_key.csv
handouts/burnt_prescription.png
errata.md
house_rules.yaml
```

## `core.pdf`

第 47 页：

> 若调查员成功搜查院长书桌，会发现一把刻有 M-17 的黄铜钥匙。

编译：

```text
scene:director_office
object:director_desk
trigger:search_director_desk
item:brass_key_m17
```

## `npcs.xlsx`

```text
NPC_ID: NPC_07
姓名：陈致远
别名：陈教授
职位：医院顾问
心理学对抗：60
```

编译：

```text
npc:professor_chen
alias: 陈教授
stat.psychology_resistance = 60
```

## `hospital.png`

AI 识别到标签：

```text
B-17
院长办公室
地下通道
```

但地图区域不能直接自动确认为拓扑。

AI 生成候选：

```text
region_12 可能对应 location:director_office
region_18 可能对应 location:basement_passage
```

Host 确认后生成 MapDraft。

## `map_key.csv`

```text
B-17,院长办公室,连接 B-18
B-18,废弃档案室,秘密门
```

这为地图候选提供确定性 ID 关联。

## `burnt_prescription.png`

图片本身作为：

```text
asset:burnt_prescription_image
```

OCR 抽取到院长签名，但 OCR 结果不能自动变成剧情真相。

它绑定到：

```text
clue:burnt_prescription
```

并标记：

```text
hidden_until_reveal
```

## `errata.md`

> 第 47 页的 M-17 应为 B-17。

编译为：

```text
errata_override
supersedes source claim
```

最终钥匙指向：

```text
location:b17
```

而不是原始 OCR / PDF 中的 M-17。

## `house_rules.yaml`

```yaml
search:
  assist:
    maxHelpers: 1
```

只覆盖规则层，不改变剧情真相。

---

# 二十一、玩家行动时，AI 应怎样合理识别

玩家说：

> “我在院长不注意的时候搜一下书桌，重点看看有没有能开地下室门的钥匙。”

运行时流程：

```text
1. Intent Compiler 识别：
   target = object:director_desk
   goal = 找到地下室相关钥匙
   method = 隐蔽搜查

2. 当前 Scene 检查：
   玩家在 director_office
   书桌可交互
   院长在场

3. Trigger 检索：
   trigger:search_director_desk

4. RuleContext：
   需要侦查/潜行或模组规则组合
   使用服务器角色数值

5. 结算成功：
   State / ClueService 实例化 clue:brass_key_b17

6. Projection：
   只向当前玩家或 Party 下发安全版本

7. Investigation：
   自动生成证据卡，但不说明钥匙最终用途

8. Journal：
   记录 actionId / transactionId / source trigger / stateVersion
```

AI 不应该在第一步就读取：

```text
最终结局
地下室里的真凶
钥匙将开启的最终仪式室
```

它只需要当前行动相关的最小上下文。

---

# 二十二、质量报告要从“文件解析成功”升级成“模组可运行”

建议 ModuleReadinessReport 至少包括：

```text
sourceParseCoverage
sourceRefCoverage
entityResolutionCoverage
unresolvedEntityCount
ambiguousAliasCount
conflictCount
invalidTriggerCount
unsupportedRuleCount
unboundAssetCount
missingMapBindingCount
visibilityUnknownCount
playerLeakRiskCount
lowConfidenceOcrCount
spoilerIndexCoverage
manualReviewRemaining
```

质量等级：

## `ready`

```text
关键对象均有来源
无阻断冲突
Trigger 可验证
可见性完整
无已知玩家泄露
```

## `warning`

```text
少量非关键资产未绑定
部分别名未确认
低风险 OCR 待复核
```

## `highRisk`

```text
部分 Trigger 未确认
地图绑定不完整
关键人物存在消歧冲突
部分可见性未知
```

## `blocked`

```text
核心剧本无法解析
关键引用缺失
规则包不支持
Host-only 真相可能泄露
主要场景无结构
Trigger 有非法写入
```

---

# 二十三、导入后台应该长什么样

建议 19-Module 的导入页增加一个“编译工作台”。

## 左侧：源资料树

```text
核心剧本
补充资料
规则参考
地图
Handout
角色
NPC
音频
勘误
房规
```

## 中间：原文 / 原图

显示：

```text
PDF 页
Excel 表
地图区域
音频时间段
```

## 右侧：编译对象

显示：

```text
识别成 NPC
识别成 Trigger
识别成玩家朗读文本
绑定到 Scene
可见性
权威等级
来源
置信度
```

## 顶部质量卡

```text
已识别场景 28
NPC 46
线索 73
Trigger 112
未解析引用 7
待确认实体合并 4
未绑定 Handout 3
高风险可见性 1
```

## 视角预览

必须支持：

```text
Admin 视角
Host 视角
Player 新开局视角
Player 已解锁中期视角
Public 模组页视角
```

这样编辑者能在发布前看到：

> 玩家到底会看到什么？

---

# 二十四、未知格式怎么处理

不能因为 AI 无法解析就拒绝整个模组。

建议三种降级：

## 1. 可解析

进入完整编译流程。

## 2. 仅能提取文本或元数据

作为：

```text
reference_only
```

可供 Host 搜索，但不自动生成 Trigger 或事实。

## 3. 完全无法解析

作为：

```text
opaque_asset
```

保留文件、哈希、名称、手工说明和 AssetBinding。

Host 可以手动绑定：

```text
这是第二幕的背景音乐
这是玩家 Handout
这是院长办公室地图
```

重要原则：

> **不认识的文件可以被管理，但不能被假装理解。**

---

# 二十五、多语言和翻译也要分层

保留：

```text
originalText
normalizedText
translatedText
language
translationOf
translator
reviewStatus
```

原文永远是来源。

自动翻译只是派生文本：

```text
authority = machine_translation
```

不能让翻译中的错误反向覆盖原始事实。

实体标签可以多语言：

```json
{
  "entityId": "npc:professor_chen",
  "labels": {
    "zh-CN": "陈致远教授",
    "en": "Professor Chen",
    "ja": "陳教授"
  }
}
```

---

# 二十六、实际跑团记录不能当作模组 Canon

很多人会上传：

```text
实际跑团录音
直播字幕
战报
主持人笔记
上一桌的事件记录
```

这些资料很有价值，但它们描述的是：

> 某一桌怎样跑过这个模组。

不是：

> 模组本身规定必须这样发生。

所以应标记：

```text
sourceRole = actual_play_example
authority = example_only
```

可用于：

```text
Host 参考
常见问题
节奏建议
玩家行为案例
```

不能用来：

```text
补写模组真相
决定固定 NPC 行为
把上一桌的随机结果写入新房间
```

---

# 二十七、存储不应只选一个数据库

建议按职责分工：

```text
对象存储 / 文件系统
→ 原始文件和派生图片

关系数据库
→ ModuleVersion、Entity、Trigger、规则、审核、权限

全文搜索
→ 精确词、标题、名称、段落

向量索引
→ 语义召回

图投影
→ 实体关系、来源关系、依赖关系

State / Event Store
→ 房间运行态和已发生事件
```

不建议：

```text
所有东西都放向量库
所有东西都放知识图谱
所有东西都复制进一个 JSONB
```

可把图作为派生索引，而不是唯一真相源。

---

# 二十八、这套能力与“调查工作台”的关系

模组编译器负责：

```text
剧本里有哪些潜在线索
哪些人物和地点存在
哪些 Trigger 可以产生线索
哪些文本是证词模板
哪些内容 Host-only
```

调查工作台负责：

```text
玩家实际获得了哪些线索
谁知道什么
玩家建立了哪些假说
哪些问题仍未解决
```

两者之间必须通过运行态事件连接：

```text
Module ClueTemplate
        ↓ Trigger 被满足
Room Clue Instance
        ↓ Projection / Share
Player EvidenceCard
```

不能直接：

```text
Module 里有 73 条线索
→ 玩家证据板显示“还有 69 条没找到”
```

那会严重剧透。

---

# 二十九、P0 实施范围

第一轮不需要支持所有格式和所有语义。

建议 P0 只做：

## 格式

```text
PDF
DOCX
Markdown / TXT
XLSX / CSV
JSON / YAML
PNG / JPG
ZIP + manifest
```

## 核心对象

```text
Scene
Location
NPC
Clue
Item
Rule
Trigger
NarrativeTemplate
AssetBinding
CharacterTemplate
```

## 核心能力

```text
SourceRef
sourceRole
authorityClass
visibility
semanticMode
stable IDs
aliases
manual review
quality gate
immutable ModuleVersion
task-specific runtime views
```

## P1 再做

```text
复杂地图自动区域识别
PPTX / EPUB / HTML
音频视频
跨语言实体对齐
随机表高级编译
规则版本转换
VTT 包导入
增量重编译
自动冲突检测
```

---

# 三十、明确禁止的实现方式

```text
把整本 PDF 一次性扔给 AI 返回完整 JSON
只切 chunk，不保留页码和布局
所有句子都当作事实
所有相关名称自动合并
低置信度关联直接写 canonical graph
AI 推断自动变成规则或 Trigger
把 Handout 默认设为 public
把未触发 Clue 放进玩家 RAG
把 actual play 战报当模组真相
重新导入时覆盖人工修订
编辑源模组后直接影响 active room
让玩家 AI 搜索完整 Host 资料
用隐藏内容决定“线索重要性”
```

---

# 三十一、工程验收最关键的测试

```text
1. “若玩家搜查抽屉，发现钥匙”不会变成“玩家已经发现钥匙”。
2. “护士说教授没去地下室”保持 testimony，不变成 canonical fact。
3. Read-aloud 文本不会自动写入 Journal。
4. Random table 所有结果不会被同时实例化。
5. Actual play 记录不会写入新房间 Canon。
6. Errata 能覆盖旧声明，同时保留修订来源。
7. House rule 只覆盖规则层，不覆盖剧情真相。
8. 两个同名 NPC 不会未经确认自动合并。
9. 每个关键 Trigger 都有 SourceRef。
10. 每个公开 Handout 都有明确 reveal condition。
11. Player RAG 不包含 latent clue、ending、hidden NPC。
12. AI 推断没有人工确认时不能变成 canonical。
13. 重新导入不会覆盖 Manual Overlay。
14. active room 固定在原 ModuleVersion。
15. 新资料只增量重编译受影响对象。
16. 同一模组在 Admin、Host、Player、Public 视角下输出不同且正确。
17. 无法解析的文件进入 opaque_asset，而不是产生虚构内容。
18. 质量报告能阻止高风险模组发布。
```

---

# 三十二、这条能力最终的产品壁垒

普通平台可以做到：

```text
上传 PDF
搜索 PDF
问 PDF 问题
```

你们需要做到：

```text
识别这是核心剧本还是补充资料
识别一段文字是事实、证词、条件、规则还是朗读模板
识别一个表格是 NPC 数据、随机表还是时间线
识别一张图片是地图、Handout 还是场景图
把同一 NPC 在 PDF、Excel 和地图说明中的引用连接起来
知道 Errata 覆盖了哪个旧信息
知道 House Rule 只覆盖规则层
知道线索尚未被玩家发现
知道 AI 只能检索当前任务和当前视角允许的内容
```

这不是普通 RAG。

这是：

# **可编译、可校验、可追溯的模组语义系统**

最终可以收敛成一句产品定义：

> **AI-Keeper 不把模组当作一堆可搜索文本，而是把不同格式的剧本、规则、地图、角色、手out、勘误和素材编译成有稳定 ID、来源、权威等级、可见性、条件和版本的 Module IR；AI 可以提出结构和关联，但只有经过校验和复核的内容才能进入运行时。**