"""
Batch COC 7th Edition Character Card Generator
"""

import random
import sys
import os

# Enable UTF-8 console output on Windows (safe way — no TextIOWrapper which
# interferes with openpyxl's lxml backend during wb.save())
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
import openpyxl

# ============================================================
# Config
# ============================================================
TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "COC七版规则空白卡CY20.02.1.xlsx")
OUTPUT_DIR = os.path.dirname(__file__)
SHEET_NAME = "人物卡"

# ============================================================
# 1. Dice & skill base
# ============================================================
def roll(n, d, plus=0):
    return sum(random.randint(1, d) for _ in range(n)) + plus

SKILL_BASE = {
    "会计学":5, "人类学":1, "估价":5, "考古学":1, "取悦":15, "攀爬":20,
    "计算机使用":5, "信用评级":0, "克苏鲁神话":0, "乔装":5, "闪避":"DEX/2", "汽车驾驶":20,
    "电气维修":10, "电子学":1, "话术":5, "格斗":25, "射击":20, "急救":30, "历史":5,
    "恐吓":15, "跳跃":20, "外语":1, "母语":"EDU", "法律":5, "图书馆使用":20, "聆听":20,
    "锁匠":1, "机械维修":10, "医学":1, "博物学":10, "导航":10, "神秘学":5, "操作重型机械":1,
    "说服":10, "精神分析":1, "心理学":10, "骑术":5, "妙手":10,
    "侦查":25, "潜行":20, "生存":10, "游泳":20, "投掷":20, "追踪":10,
    "技艺":5, "科学":1, "驾驶":1,
}

# Map gen_investigator.py skill names → fill_sheet.py / template names
GEN_TO_TMPL = {
    "艺术与手艺": "技艺",
    "其他语言": "外语",
    "魅惑": "取悦",
    "领航": "导航",
}

# ============================================================
# 2. Occupations (from gen_investigator.py, with adapted skill names)
# ============================================================
OCCUPATIONS = {
    "记者": {
        "credit": (9, 30),
        "oskills": ["技艺(摄影)", "历史", "图书馆使用", "外语", "话术", "心理学", "侦查", "_自选一"],
        "formula": "edu4",
    },
    "私家侦探": {
        "credit": (9, 30),
        "oskills": ["技艺(摄影)", "乔装", "法律", "图书馆使用", "话术", "心理学", "侦查", "射击(手枪)"],
        "formula": "edu2_dex2",
    },
    "教授": {
        "credit": (20, 70),
        "oskills": ["图书馆使用", "外语", "母语", "心理学", "历史", "神秘学", "考古学", "科学"],
        "formula": "edu4",
    },
    "医生": {
        "credit": (30, 80),
        "oskills": ["急救", "外语(拉丁文)", "医学", "心理学", "科学(生物学)", "科学(药学)", "精神分析", "_自选一"],
        "formula": "edu4",
    },
    "古文物学家": {
        "credit": (5, 40),
        "oskills": ["估价", "技艺", "历史", "图书馆使用", "外语", "话术", "侦查", "神秘学"],
        "formula": "edu4",
    },
    "罪犯": {
        "credit": (5, 65),
        "oskills": ["话术", "心理学", "侦查", "潜行", "格斗(拳击)", "射击(手枪)", "锁匠", "妙手"],
        "formula": "edu2_dex2",
    },
    "作家": {
        "credit": (9, 30),
        "oskills": ["技艺(文学)", "历史", "图书馆使用", "博物学", "外语", "母语", "心理学", "神秘学"],
        "formula": "edu4",
    },
    "警察": {
        "credit": (9, 30),
        "oskills": ["格斗(拳击)", "射击(手枪)", "急救", "法律", "心理学", "侦查", "汽车驾驶", "聆听"],
        "formula": "edu2_dex2",
    },
}

# Pool for "_自选一" (choose one extra occupational skill)
SELF_PICK_POOL = ["聆听", "闪避", "急救", "图书馆使用", "汽车驾驶", "攀爬", "跳跃", "恐吓", "说服", "追踪", "估价", "机械维修", "博物学", "神秘学", "历史", "投掷", "游泳"]

# Gen→Template name normalization for skills
def normalize_skill(name_with_sub):
    """Normalize gen_investigator skill name to template skill name.
    Returns (base_key, sub_type) where base_key matches SKILL_BASE keys.
    """
    if "(" in name_with_sub:
        base, sub = name_with_sub.split("(", 1)
        sub = sub.rstrip(")")
    else:
        base, sub = name_with_sub, None
    # Apply name mapping
    base = GEN_TO_TMPL.get(base, base)
    return base, sub

def get_base_value(skill_name):
    """Get base skill value (integer). Handles DEX/2, EDU formulas."""
    key, _ = normalize_skill(skill_name)
    val = SKILL_BASE.get(key, 5)
    if isinstance(val, str):
        return 25  # fallback for formula keys
    return val

# ============================================================
# 3. Background generator
# ============================================================
FIRST_NAMES_M = ["阿尔伯特", "亨利", "弗兰克", "爱德华", "乔治", "沃尔特", "查尔斯", "亚瑟", "约瑟夫", "杰克",
                 "威廉", "理查德", "罗伯特", "托马斯", "塞缪尔", "本杰明", "丹尼尔", "菲利普", "劳伦斯", "维克多"]
LAST_NAMES = ["莫里森", "沃克", "布莱克伍德", "科尔", "格雷", "沙利文", "奥康奈尔", "里德", "克劳福德", "伯恩",
              "霍桑", "温特斯", "阿什顿", "梅森", "钱伯斯", "哈珀", "弗莱彻", "索恩", "马奇班克斯", "斯特林"]

IDEAS = [
    "金钱是这个世界唯一通用的语言，其余的不过是华丽的说辞。",
    "每个人都有价格，问题在于你有没有找到那个数字。",
    "社会这座大厦的锁芯，我比造锁的人更懂怎么打开它。",
    "过去犯的错太多，但总有办法用今后的事来弥补——我是说，一定程度上。",
    "这世界是个巨大的骗局，我只是学会了在舞台背面行走。",
    "知识是唯一不能被夺走的财富，所以我不断阅读、记录、求证。",
    "真相往往藏在人们不愿多看一眼的角落里，而那里恰好是我的舒适区。",
    "正义和法律之间有一条很宽的河，我在河上划船。",
]

PEOPLE = [
    ("文森特·罗西", "地下钱庄老板，你的债主兼保护人。他信你，但信任是有利息的。"),
    ("玛格丽特·科尔", "你的妹妹，嫁给了一位正直的检察官。她以为你是个普通的锁具经销商。"),
    ("汤米·奥哈拉", "儿时玩伴，现在是码头的搬运工。他是少数几个见过你落魄一面的人。"),
    ("伊丽莎白·沃伦", "阿卡姆图书馆的管理员，你们在一次'夜间光顾'中偶然相识，互相都假装对方是走错了路。"),
    ("约瑟夫·克劳利", "退休的警察，在街上救过你一次。你不知道他为什么没抓你，但每年圣诞都会给他送一瓶波本。"),
    ("艾米莉·哈特", "大学时的同窗，现为波士顿环球报记者。她知道些你不愿见报的事，但从没写过。"),
    ("马丁·弗罗斯特", "疯人院的护工，曾帮你照顾过一位崩溃的朋友。他从不问你太多问题。"),
]

PLACES = [
    ("老码头仓库 14 号", "你在这里藏了一个工具箱，里面有你在深夜出入各种建筑物时需要的一切。"),
    ("波比的地下酒吧", "波士顿北端一家没有招牌的酒吧，后门直通你的公寓。酒保记得你的名字但从不问问题。"),
    ("布罗德街锁具修理店", "你体面的掩护身份。楼上的小公寓里堆满了报纸和咖啡罐，窗帘常年拉着——不是因为羞耻，而是因为方便。"),
    ("密斯卡托尼克河畔的长椅", "你常在深夜独自坐在这里，看着对岸大学图书馆的灯火。有时候，你甚至不觉得自己是个坏人。"),
    ("阿卡姆大学古籍部的阅览室", "你在这里度过无数个下午，翻阅那些不该存在于世的书籍。图书管理员看你的眼神越来越奇怪了。"),
    ("国王教堂的钟楼", "你每周日下午会爬上去坐一会儿。不是信教，只是那里没人打扰，能看到整座城市的轮廓。"),
]

POSSESSIONS = [
    ("一套手工打造的撬锁工具", "你父亲留给你的——他是一个真正的锁匠。这是他留下的唯一一件没有当掉的东西。"),
    ("一枚圣母像吊坠", "你母亲临终前塞进你手里的。你不是信徒，但你从来不敢把它摘下来。"),
    ("一本袖珍版《麦克白》", "你在一次闯空门时偷出来的，本来想卖掉，翻开第一页就没能合上。现在书脊都快散了。"),
    ("一把柯尔特警探特装版", "枪柄上刻着不属于你的缩写。你不想谈它的来历，但它从来没卡过壳。"),
    ("一本老旧的皮革封皮日记", "封面已经模糊不清，里面用密码写着一些你不希望任何人读到的东西。"),
    ("一个黄铜罗盘", "表面上刻着你从未见过的符号。指针并不指北，而是指向……某处。你还没弄清它指向哪里。"),
]

TRAITS = [
    ("凡事留后路", "每次进入一栋建筑，你都会默记至少三条离开的路线。这个习惯救过你两次命。"),
    ("只偷该偷的人", "你有一条不成文的规矩：不碰穷人、不碰小商户、不碰看起来已经在哭的人。这让你赚得少，但睡得稍好一些。"),
    ("手指不停敲", "紧张的时候，你的右手食指会不由自主地在桌上敲出摩尔斯电码。你的母亲曾经是电报员。"),
    ("在黑暗中依然冷静", "灯关了的时候，大多数人会慌。你不会。黑暗是你的工具，而不是敌人。"),
    ("永远在提问", "你有一种令人不安的习惯，能从一句话里找出三个问题。朋友说你适合做记者，但你更想做能发问而不需要答案的人。"),
    ("能读懂沉默", "人们说话时暴露自己，而沉默时暴露更多。你学会了在对话的间隙阅读表情和微动作。"),
]

SCARS = [
    ("左手虎口处有一道旧刀疤，是一次撬锁时打滑留下的。"),
    ("右肩有一块烧伤疤痕，那晚仓库的火比预期烧得更快。"),
    ("左手无名指第一指节略弯，年轻时骨折没长好。"),
    ("左小腿外侧有一道细长的划痕，是从铁丝网下钻过时留下的。"),
    ("后颈处有一个小圆疤，你不知道是什么时候留下的，但偶尔会隐隐作痛。"),
]

SECRETS = [
    "你曾在一场火灾中路过而没有报警。不是因为冷漠，而是因为那里面有你不该在的东西。",
    "你有一段不愿提起的家族往事——你的叔叔曾在一次考古挖掘中失踪，当局说是流沙，但你知道不是。",
    "你在某本不该存在的书里读到了一个名字，从那以后你就睡不好觉了。",
    "有一张照片藏在你钱夹最深处，你从没向任何人展示过，也从不提及照片里的人是谁。",
    "你年轻时犯过一次严重错误，那次错误差点毁掉另一个人的生活。你至今仍在用各种方式弥补。",
]

def gen_background():
    first = random.choice(FIRST_NAMES_M)
    last = random.choice(LAST_NAMES)
    age = random.randint(25, 45)
    residence = random.choice(["阿卡姆", "波士顿", "普罗维登斯", "塞勒姆", "金斯波特", "敦威治"])
    hometown = random.choice(["波士顿", "纽约", "芝加哥", "费城", "伦敦", "旧金山"])

    idea = random.choice(IDEAS)
    person_name, person_desc = random.choice(PEOPLE)
    place_name, place_desc = random.choice(PLACES)
    item_name, item_desc = random.choice(POSSESSIONS)
    trait_title, trait_desc = random.choice(TRAITS)
    secret = random.choice(SECRETS)
    scar = random.choice(SCARS)

    return {
        "name": f"{first}·{last}",
        "age": age,
        "residence": residence,
        "hometown": hometown,
        "idea": idea,
        "person": (person_name, person_desc),
        "place": (place_name, place_desc),
        "possession": (item_name, item_desc),
        "trait": (trait_title, trait_desc),
        "secret": secret,
        "scar": scar,
    }

# ============================================================
# 4. Character generator
# ============================================================
def gen_character(occ_name):
    """Generate a random character for the given occupation. Returns raw data dict."""
    occ = OCCUPATIONS[occ_name]

    # Stats
    stats = {
        "STR": roll(3, 6) * 5, "CON": roll(3, 6) * 5, "SIZ": roll(2, 6, 6) * 5,
        "DEX": roll(3, 6) * 5, "APP": roll(3, 6) * 5, "INT": roll(2, 6, 6) * 5,
        "POW": roll(3, 6) * 5, "EDU": roll(2, 6, 6) * 5, "LUCK": roll(3, 6) * 5,
    }
    hp = (stats["CON"] + stats["SIZ"]) // 10
    san = stats["POW"]
    mp = stats["POW"] // 5

    # DB / Build / MOV
    total = stats["STR"] + stats["SIZ"]
    if total < 65:       db, build = "-2", -2
    elif total < 85:     db, build = "-1", -1
    elif total < 125:    db, build = "0", 0
    elif total < 165:    db, build = "+1D4", 1
    elif total < 205:    db, build = "+1D6", 2
    else:                db, build = "+2D6", 3

    above = sum(1 for v in [stats["STR"], stats["DEX"]] if v >= stats["SIZ"])
    mov = 7 if above == 0 else (8 if above == 1 else 9)

    # Credit rating
    credit_min, credit_max = occ["credit"]
    credit = random.randint(credit_min, credit_max)

    # Occupational points
    if occ["formula"] == "edu4":
        occ_pts = stats["EDU"] * 4
    else:
        occ_pts = stats["EDU"] * 2 + stats["DEX"] * 2

    int_pts = stats["INT"] * 2

    # Build occupational skills list, resolving "_自选一"
    raw_oskills = []
    for sk in occ["oskills"]:
        if sk == "_自选一":
            pick = random.choice(SELF_PICK_POOL)
            raw_oskills.append(pick)
        else:
            raw_oskills.append(sk)

    # Allocate occupational points with variance
    skills = {}
    n = len(raw_oskills)
    base_alloc = occ_pts // n
    rem = occ_pts % n
    alloc = [base_alloc + (1 if i < rem else 0) for i in range(n)]
    for i in range(len(alloc)):
        shift = random.randint(-15, 15)
        if 0 <= i + 1 < len(alloc):
            alloc[i] += shift
            alloc[i + 1] -= shift
    alloc = [max(5, a) for a in alloc]

    for sk, pts in zip(raw_oskills, alloc):
        base_key, sub = normalize_skill(sk)
        if base_key not in skills:
            skills[base_key] = {"base": get_base_value(sk), "occ": 0, "int": 0, "sub": sub}
        skills[base_key]["occ"] += pts

    # Credit rating
    skills["信用评级"] = {"base": 0, "occ": credit, "int": 0, "sub": None}

    # Interest points
    interest_pool = ["聆听", "闪避", "急救", "图书馆使用", "汽车驾驶", "攀爬",
                     "跳跃", "恐吓", "说服", "追踪", "估价", "机械维修",
                     "博物学", "神秘学", "历史", "投掷", "游泳"]
    chosen = random.sample(interest_pool, random.randint(4, 6))
    ipts = int_pts
    for i, c in enumerate(chosen):
        pts = ipts // (len(chosen) - i)
        pts = max(5, pts)
        base_key, _ = normalize_skill(c)
        if base_key not in skills:
            skills[base_key] = {"base": get_base_value(c), "occ": 0, "int": 0, "sub": None}
        skills[base_key]["int"] += pts
        ipts -= pts

    # Fix formula-based skills (闪避 = DEX/2, 母语 = EDU)
    for key in ["闪避", "母语"]:
        if key not in skills:
            skills[key] = {"base": 25, "occ": 0, "int": 0, "sub": None}

    # 闪避 base = DEX // 2
    skills["闪避"]["base"] = stats["DEX"] // 2
    # 母语 base = EDU
    skills["母语"]["base"] = stats["EDU"]

    # Calculate totals
    for key, sd in skills.items():
        sd["total"] = sd["base"] + sd["occ"] + sd["int"]

    bg = gen_background()
    return {
        "stats": stats, "hp": hp, "san": san, "mp": mp,
        "db": db, "build": build, "mov": mov,
        "occ_name": occ_name, "credit": credit,
        "skills": skills, "bg": bg,
    }

# ============================================================
# 5. Template SKILL_MAP builder
# ============================================================
def build_skill_map(template_path):
    """Read the blank template and build a SKILL_MAP.
    Returns dict: {skill_key: (side, row, sub_type_cell_value_or_None)}
    side: 'L' (col F=6) or 'R' (col AB=28)

    Key naming convention:
      - Main slot (e.g. "格斗：" or "格斗") → key = "格斗" (base name)
      - Numbered slot (e.g. "格斗①") → key = "格斗①" (preserves number)
      - "Ω" is stripped as meaningless noise
    """
    wb = openpyxl.load_workbook(template_path)
    ws = wb[SHEET_NAME]
    skill_map = {}

    def make_key(raw):
        s = str(raw).strip()
        # Strip trailing Ω (noise marker) and ：
        s = s.rstrip("Ω： ").strip()
        return s

    # Left side: F col (6), sub-type in H col (8)
    for row in range(16, 50):
        f = ws.cell(row=row, column=6).value
        h = ws.cell(row=row, column=8).value
        if f and not str(f).startswith("="):
            key = make_key(f)
            # Avoid overwriting main slot with numbered variant
            # e.g. if "格斗" (from "格斗：") is already stored, don't overwrite with "格斗" (from "格斗①")
            if key not in skill_map or "①" not in str(f):
                skill_map[key] = ("L", row, h)

    # Right side: AB col (28), no sub-type column
    for row in range(16, 50):
        ab = ws.cell(row=row, column=28).value
        if ab and not str(ab).startswith("="):
            key = make_key(ab)
            if key not in skill_map or "①" not in str(ab):
                skill_map[key] = ("R", row, None)

    wb.close()
    return skill_map

def find_skill_slot(skill_map, base_key, sub, used_slots):
    """Find the right template slot for a multi-slot skill.
    Prefers the main slot first, then falls back to numbered slots.
    """
    multi_slot_bases = ("格斗", "射击", "技艺", "外语", "科学", "驾驶")

    if base_key not in multi_slot_bases:
        return skill_map.get(base_key)

    # Main slot first (e.g. "格斗")
    main = skill_map.get(base_key)
    if main is not None:
        side, row, _ = main
        if (side, row) not in used_slots:
            return main

    # Numbered slots
    for suffix in ["①", "②", "③"]:
        slot = skill_map.get(base_key + suffix)
        if slot is not None:
            side, row, _ = slot
            if (side, row) not in used_slots:
                return slot

    # All busy — reuse main slot as last resort
    return main

# ============================================================
# 6. Template filler
# ============================================================
def safe_set(ws, row, col, value):
    """Safely set cell value, handling merged cells."""
    cell = ws.cell(row=row, column=col)
    try:
        cell.value = value
    except AttributeError:
        # MergedCell — find the parent cell
        for merged_range in ws.merged_cells.ranges:
            if cell.coordinate in merged_range:
                parent = ws.cell(row=merged_range.min_row, column=merged_range.min_col)
                parent.value = value
                return
        print(f"  [WARN] Cannot write to merged cell {cell.coordinate}")

def fill_template(char_data, skill_map, output_path):
    """Fill character data into a copy of the blank template and save."""
    data = char_data
    stats = data["stats"]
    skills = data["skills"]
    bg = data["bg"]

    wb = openpyxl.load_workbook(TEMPLATE_PATH)
    ws = wb[SHEET_NAME]

    # --- Clear all skill point cells (template has demo values) ---
    for row in range(16, 50):
        safe_set(ws, row, 14, None)   # N col occ points (left)
        safe_set(ws, row, 16, None)   # P col int points (left)
        safe_set(ws, row, 8, None)    # H col sub-type (left)
        safe_set(ws, row, 36, None)   # AJ col occ points (right)
        safe_set(ws, row, 38, None)   # AL col int points (right)
        safe_set(ws, row, 30, None)   # AD col sub-type (right)

    # --- Clear background cells (rows 61-76, AA col) ---
    for row in range(60, 80):
        safe_set(ws, row, 27, None)   # AA col

    # --- Basic info ---
    safe_set(ws, row=3, col=5, value=bg["name"])     # E3 姓名
    safe_set(ws, row=4, col=5, value="玩家")          # E4 玩家
    safe_set(ws, row=5, col=5, value=data["occ_name"]) # E5 职业
    safe_set(ws, row=5, col=13, value="")             # M5 职业序号 (清空)
    safe_set(ws, row=6, col=5, value=bg["age"])       # E6 年龄
    safe_set(ws, row=6, col=13, value="男")           # M6 性别
    safe_set(ws, row=7, col=5, value=bg["residence"]) # E7 住地
    safe_set(ws, row=7, col=13, value=bg["hometown"]) # M7 故乡

    # --- Attributes ---
    safe_set(ws, row=3, col=21, value=stats["STR"])   # U3 力量
    safe_set(ws, row=5, col=21, value=stats["CON"])   # U5 体质
    safe_set(ws, row=7, col=21, value=stats["SIZ"])   # U7 体型
    safe_set(ws, row=3, col=27, value=stats["DEX"])   # AA3 敏捷
    safe_set(ws, row=5, col=27, value=stats["APP"])   # AA5 外貌
    safe_set(ws, row=7, col=27, value=stats["INT"])   # AA7 智力
    safe_set(ws, row=3, col=33, value=stats["POW"])   # AG3 意志
    safe_set(ws, row=5, col=33, value=stats["EDU"])   # AG5 教育
    safe_set(ws, row=7, col=33, value=stats["LUCK"])  # AG7 幸运

    # --- HP / SAN / MP ---
    safe_set(ws, row=10, col=5, value=data["hp"])     # E10 HP
    safe_set(ws, row=10, col=14, value=data["san"])   # N10 SAN
    safe_set(ws, row=10, col=23, value=data["mp"])    # W10 MP

    # --- Skills ---
    used_slots = set()  # Track which slots are filled to avoid duplicates
    for skill_key, sd in sorted(skills.items(), key=lambda x: -x[1].get("total", 0)):
        base_key = skill_key
        sub = sd.get("sub")

        # Try to find the slot
        slot = find_skill_slot(skill_map, base_key, sub, used_slots)
        if slot is None:
            # Try without sub-type prefix
            print(f"  [WARN] Skill '{skill_key}' not found in template, skipping")
            continue

        side, row, existing_sub = slot
        slot_id = (side, row)
        if slot_id in used_slots and base_key not in ("格斗", "射击", "技艺", "外语", "科学"):
            print(f"  [WARN] Slot already used for '{skill_key}', skipping")
            continue
        used_slots.add(slot_id)

        occ_val = sd.get("occ", 0)
        int_val = sd.get("int", 0)

        if side == "L":
            safe_set(ws, row, 14, occ_val)  # N col = occ points
            safe_set(ws, row, 16, int_val)  # P col = int points
            # Write sub-type if applicable
            if sub and base_key in ("格斗", "射击", "技艺", "外语"):
                safe_set(ws, row, 8, sub)   # H col = sub-type name
        else:
            safe_set(ws, row, 36, occ_val)  # AJ col = occ points
            safe_set(ws, row, 38, int_val)  # AL col = int points
            # Write sub-type for 科学 on right side
            if sub and base_key == "科学":
                safe_set(ws, row, 30, sub)   # AD col = sub-type name

    # --- Background story (AA col = 27, rows 61-76) ---
    trait_title, trait_desc = bg["trait"]
    person_name, person_desc = bg["person"]
    place_name, place_desc = bg["place"]
    item_name, item_desc = bg["possession"]

    height_cm = random.randint(165, 188)
    weight_kg = random.randint(55, 90)
    appearance = f"身高约{height_cm}cm，体重约{weight_kg}kg。外表普通，穿着得体但不引人注目。目光锐利，手指上有长期劳作留下的茧痕。"

    bg_rows = {
        61: ("个人描述", appearance),
        63: ("思想信念", f"「{bg['idea']}」"),
        65: ("重要之人", f"{person_name}——{person_desc}"),
        67: ("意义非凡之地", f"{place_name}——{place_desc}"),
        69: ("宝贵之物", f"{item_name}——{item_desc}"),
        71: ("特质", f"{trait_title}——{trait_desc}"),
        73: ("难言之隐", bg["secret"]),
        75: ("伤口和疤痕", bg["scar"]),
    }

    for row, (label, text) in bg_rows.items():
        safe_set(ws, row, 27, text)  # AA col

    # Note: DB, Build, MOV are auto-computed by template formulas from STR/SIZ/DEX values.
    # HP formula: G10 = INT((U5+U7)/10)
    # MP formula: Y10 = INT(AG3/5)
    # MOV formula: AF10 = AI11+8

    # Save
    wb.save(output_path)
    wb.close()
    print(f"  ✓ Saved: {os.path.basename(output_path)}")

# ============================================================
# 7. Main — batch generation
# ============================================================
def main():
    random.seed()

    print("=" * 60)
    print("  COC 七版角色卡批量生成器")
    print("  模板:", os.path.basename(TEMPLATE_PATH))
    print("  输出:", OUTPUT_DIR)
    print("=" * 60)

    # Build skill map from template
    print("\n[1/3] 读取模板技能映射...")
    skill_map = build_skill_map(TEMPLATE_PATH)
    print(f"  共发现 {len(skill_map)} 个技能槽位")

    # Generate and fill one card per occupation
    occ_names = list(OCCUPATIONS.keys())
    print(f"\n[2/3] 为 {len(occ_names)} 种职业生成角色卡...\n")

    for i, occ_name in enumerate(occ_names):
        print(f"--- [{i+1}/8] {occ_name} ---")
        char_data = gen_character(occ_name)

        # Print summary
        s = char_data["stats"]
        print(f"  姓名: {char_data['bg']['name']}  年龄: {char_data['bg']['age']}")
        print(f"  STR:{s['STR']} CON:{s['CON']} SIZ:{s['SIZ']} DEX:{s['DEX']} APP:{s['APP']} INT:{s['INT']} POW:{s['POW']} EDU:{s['EDU']} LUCK:{s['LUCK']}")
        print(f"  HP:{char_data['hp']} SAN:{char_data['san']} MP:{char_data['mp']} DB:{char_data['db']} MOV:{char_data['mov']}")
        print(f"  信用评级:{char_data['credit']}%  技能数:{len(char_data['skills'])}")

        # Fill and save
        out_name = f"tzq12138_{i+1:02d}_{occ_name}.xlsx"
        out_path = os.path.join(OUTPUT_DIR, out_name)
        fill_template(char_data, skill_map, out_path)
        print()

    print("[3/3] 全部完成！")
    print(f"共生成 {len(occ_names)} 张角色卡，保存在: {OUTPUT_DIR}")
    for i, occ_name in enumerate(occ_names):
        print(f"  {i+1}. tzq12138_{i+1:02d}_{occ_name}.xlsx — {occ_name}")

if __name__ == "__main__":
    main()
