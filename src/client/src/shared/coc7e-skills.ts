// COC 7e Skill Dictionary — local, no RAG dependency for v1.
// Ported from AIkpprojects and extended with descriptions and aliases.

export interface SkillDefinition {
  name: string;          // Chinese display name
  enName?: string;       // Optional English name
  base: number;          // Base value (0-30)
  category: SkillCategory;
  half: boolean;         // Whether half-value check applies
  rare: boolean;         // Whether this is a rare/specialty skill
  aliases?: string[];    // Chinese variations for fuzzy matching
  description: string;   // Short description
}

export type SkillCategory = 'investigation' | 'social' | 'knowledge' | 'action' | 'combat' | 'other';

export const CATEGORY_META: Record<SkillCategory, { label: string; enLabel: string }> = {
  investigation: { label: '调查', enLabel: 'Investigation' },
  social:        { label: '社交', enLabel: 'Social' },
  knowledge:     { label: '知识', enLabel: 'Knowledge' },
  action:        { label: '行动', enLabel: 'Action' },
  combat:        { label: '战斗', enLabel: 'Combat' },
  other:         { label: '其他', enLabel: 'Other' },
};

export const SKILLS: SkillDefinition[] = [
  // ----- investigation -----
  { name: '侦查', enName: 'Spot Hidden', base: 25, category: 'investigation', half: true, rare: false, aliases: ['侦察'], description: '观察环境，发现隐藏的线索、物品或异常细节。' },
  { name: '聆听', enName: 'Listen', base: 20, category: 'investigation', half: true, rare: false, aliases: ['听力'], description: '察觉细微的声音，如远处的脚步声、低语或机械异响。' },
  { name: '图书馆使用', enName: 'Library Use', base: 20, category: 'investigation', half: true, rare: false, aliases: ['图书馆'], description: '在图书馆、档案馆或数据库中快速查找所需信息。' },
  { name: '导航', enName: 'Navigate', base: 10, category: 'investigation', half: true, rare: false, aliases: ['方向感'], description: '在野外、城市或复杂建筑中找到正确的路线，不迷路。' },
  { name: '估价', enName: 'Appraise', base: 5, category: 'investigation', half: true, rare: false, aliases: ['鉴定'], description: '判断物品的年代、材质、真伪及市场价值。' },
  { name: '追踪', enName: 'Track', base: 10, category: 'investigation', half: true, rare: false, aliases: ['跟踪'], description: '寻找并跟随人或动物留下的足迹、痕迹。' },

  // ----- social -----
  { name: '话术', enName: 'Fast Talk', base: 5, category: 'social', half: true, rare: false, aliases: ['忽悠', '巧言'], description: '用快速、巧妙的言辞让对方暂时相信或配合你。' },
  { name: '说服', enName: 'Persuade', base: 10, category: 'social', half: true, rare: false, aliases: ['劝说', '交涉'], description: '通过理性的论据或情感诉求让对方改变立场。' },
  { name: '心理学', enName: 'Psychology', base: 10, category: 'social', half: true, rare: false, aliases: ['心理分析'], description: '洞察他人的情绪、动机，判断对方是否在说谎或隐瞒。' },
  { name: '威胁', enName: 'Intimidate', base: 15, category: 'social', half: true, rare: false, aliases: ['恐吓', '威吓'], description: '以暴力或权力恐吓对方，迫使其服从你的要求。' },
  { name: '魅惑', enName: 'Charm', base: 15, category: 'social', half: true, rare: false, aliases: ['魅力', '吸引'], description: '通过个人魅力吸引或引诱对方，获得好感与合作。' },
  { name: '信用评级', enName: 'Credit Rating', base: 0, category: 'social', half: true, rare: false, aliases: ['信用', '财富'], description: '代表社会地位和经济实力，影响他人对你的态度和资源获取能力。' },

  // ----- knowledge -----
  { name: '神秘学', enName: 'Occult', base: 5, category: 'knowledge', half: true, rare: false, aliases: ['超自然'], description: '了解民间传说、魔法仪式、超自然现象及克苏鲁神话相关知识。' },
  { name: '考古学', enName: 'Archaeology', base: 1, category: 'knowledge', half: true, rare: true, aliases: [], description: '古代文明、遗迹发掘与文物断代方面的专业知识。' },
  { name: '历史', enName: 'History', base: 5, category: 'knowledge', half: true, rare: false, aliases: ['历史学'], description: '对重大历史事件、人物和文化变迁的广泛了解。' },
  { name: '自然', enName: 'Natural World', base: 10, category: 'knowledge', half: true, rare: false, aliases: ['博物学', '自然学'], description: '动植物识别、自然生态、野外生存方面的综合知识。' },
  { name: '医学', enName: 'Medicine', base: 1, category: 'knowledge', half: true, rare: true, aliases: [], description: '疾病的诊断与治疗、人体解剖、药物学方面的专业医学知识。' },
  { name: '法律', enName: 'Law', base: 5, category: 'knowledge', half: true, rare: false, aliases: [], description: '了解法律法规、司法程序以及如何利用法律保护自身权益。' },
  { name: '簿记', enName: 'Accounting', base: 5, category: 'knowledge', half: true, rare: false, aliases: ['会计', '账目'], description: '审查财务账目，发现资金异常、造假或隐藏的财务线索。' },
  { name: '密码学', enName: 'Cryptography', base: 1, category: 'knowledge', half: true, rare: true, aliases: ['密码', '解密'], description: '破解密码、密文和加密通讯的专业技能。' },
  { name: '电脑使用', enName: 'Computer Use', base: 5, category: 'knowledge', half: true, rare: false, aliases: ['计算机', '电脑'], description: '操作计算机、编写程序、搜索数据库和破解系统安全的能力。' },
  { name: '数学', enName: 'Mathematics', base: 10, category: 'knowledge', half: true, rare: false, aliases: [], description: '高级数学推理、概率计算、几何分析等方面的能力。' },
  { name: '生物学', enName: 'Biology', base: 1, category: 'knowledge', half: true, rare: true, aliases: [], description: '对生物体结构、功能、分类和生态关系的系统知识。' },
  { name: '物理学', enName: 'Physics', base: 1, category: 'knowledge', half: true, rare: true, aliases: [], description: '物质、能量、力学和电磁波方面的专业科学知识。' },
  { name: '天文学', enName: 'Astronomy', base: 1, category: 'knowledge', half: true, rare: true, aliases: [], description: '天体运行、星系结构和天文观测方面的专业知识。' },
  { name: '地质学', enName: 'Geology', base: 1, category: 'knowledge', half: true, rare: true, aliases: [], description: '岩石、矿物、地层结构和地质作用方面的专业知识。' },
  { name: '化学', enName: 'Chemistry', base: 1, category: 'knowledge', half: true, rare: true, aliases: [], description: '物质成分、化学反应和实验室分析方面的专业科学知识。' },
  { name: '药学', enName: 'Pharmacy', base: 1, category: 'knowledge', half: true, rare: true, aliases: ['药剂'], description: '药物配方、药理学和药物相互作用方面的专业知识。' },
  { name: '人类学', enName: 'Anthropology', base: 1, category: 'knowledge', half: true, rare: true, aliases: [], description: '人类社会文化、习俗演变和考古学方面的综合研究知识。' },
  { name: '语言学', enName: 'Linguistics', base: 1, category: 'knowledge', half: true, rare: true, aliases: [], description: '语言结构、语法分析和语言演变方面的系统知识。' },
  { name: '拉丁语', enName: 'Latin', base: 1, category: 'knowledge', half: true, rare: true, aliases: [], description: '阅读和理解拉丁文古籍、铭文和学术文献的能力。' },
  { name: '英语', enName: 'English', base: 0, category: 'knowledge', half: true, rare: false, aliases: ['英文'], description: '使用英语进行听说读写的能力（母语或外语）。' },

  // ----- action -----
  { name: '闪避', enName: 'Dodge', base: 0, category: 'action', half: true, rare: false, aliases: ['躲避'], description: '在战斗中回避攻击或躲避突如其来的危险（基础值=DEX/2）。' },
  { name: '潜行', enName: 'Stealth', base: 20, category: 'action', half: true, rare: false, aliases: ['隐匿', '悄悄'], description: '安静地移动，不被他人察觉地穿过区域或跟踪目标。' },
  { name: '攀爬', enName: 'Climb', base: 20, category: 'action', half: true, rare: false, aliases: ['攀登'], description: '攀爬墙壁、树木、悬崖等垂直或陡峭的表面。' },
  { name: '跳跃', enName: 'Jump', base: 20, category: 'action', half: true, rare: false, aliases: ['跳'], description: '跳过沟壑、跨越障碍物或从高处安全跳下。' },
  { name: '游泳', enName: 'Swim', base: 20, category: 'action', half: true, rare: false, aliases: [], description: '在水中安全移动，抵抗水流或在紧急情况下游到安全地带。' },
  { name: '投掷', enName: 'Throw', base: 20, category: 'action', half: true, rare: false, aliases: ['扔'], description: '精确地投掷物品、武器或工具到目标位置。' },
  { name: '驾驶', enName: 'Drive Auto', base: 20, category: 'action', half: true, rare: false, aliases: ['开车'], description: '安全驾驶汽车、卡车等机动车辆，包括危险情况下的操控。' },
  { name: '骑术', enName: 'Ride', base: 5, category: 'action', half: true, rare: false, aliases: ['骑马'], description: '骑马或骑乘其他动物的能力，包括战斗中控制坐骑。' },
  { name: '机械维修', enName: 'Mechanical Repair', base: 10, category: 'action', half: true, rare: false, aliases: ['修理', '机械'], description: '修理或改造机械设备，如发动机、齿轮装置和机械锁。' },
  { name: '电气维修', enName: 'Electrical Repair', base: 10, category: 'action', half: true, rare: false, aliases: ['电工', '电器'], description: '修理或改造电气设备和电路系统的能力。' },
  { name: '急救', enName: 'First Aid', base: 30, category: 'action', half: true, rare: false, aliases: ['治疗', '包扎'], description: '进行紧急医疗处理，止血、包扎伤口，稳定伤员生命体征。成功可恢复1点HP。' },
  { name: '操作重型机器', enName: 'Operate Heavy Machinery', base: 1, category: 'action', half: true, rare: true, aliases: ['重型机器'], description: '安全操作起重机、推土机、压路机等重型工业设备。' },
  { name: '爆破', enName: 'Demolitions', base: 1, category: 'action', half: true, rare: true, aliases: ['炸药', '爆破学'], description: '安全设置和引爆炸药，计算爆炸范围，拆除爆炸装置。' },
  { name: '锁匠', enName: 'Locksmith', base: 1, category: 'action', half: true, rare: false, aliases: ['开锁', '撬锁'], description: '使用工具打开各种锁具，包括机械锁和简易电子锁。' },
  { name: '摄影', enName: 'Photography', base: 5, category: 'action', half: true, rare: false, aliases: ['拍照'], description: '使用相机拍摄清晰照片，包括暗房冲洗和特殊条件下的拍摄。' },
  { name: '速记', enName: 'Shorthand', base: 5, category: 'action', half: true, rare: false, aliases: ['快速记录'], description: '用速记符号快速准确地记录听到的对话或口述信息。' },

  // ----- combat -----
  { name: '斗殴', enName: 'Brawl', base: 25, category: 'combat', half: true, rare: false, aliases: ['徒手攻击', '格斗'], description: '使用拳头、脚踢或小型钝器进行近身肉搏战斗。' },
  { name: '手枪', enName: 'Handgun', base: 20, category: 'combat', half: true, rare: false, aliases: ['射击'], description: '使用手枪类武器（包括左轮和半自动手枪）进行射击。' },
  { name: '步枪', enName: 'Rifle', base: 25, category: 'combat', half: true, rare: false, aliases: ['长枪'], description: '使用步枪、猎枪等长管火器进行射击。' },
  { name: '弓术', enName: 'Bow', base: 15, category: 'combat', half: true, rare: false, aliases: ['射箭', '弓箭'], description: '使用弓弩类武器进行精确射击的能力。' },
  { name: '冲锋枪', enName: 'Submachine Gun', base: 15, category: 'combat', half: true, rare: false, aliases: ['SMG'], description: '使用冲锋枪等全自动小型火器进行射击。' },
  { name: '霰弹枪', enName: 'Shotgun', base: 25, category: 'combat', half: true, rare: false, aliases: ['猎枪'], description: '使用霰弹枪进行近距离大面积射击。' },
  { name: '火焰喷射器', enName: 'Flamethrower', base: 10, category: 'combat', half: true, rare: true, aliases: ['火焰'], description: '操作火焰喷射器，对较大范围造成火焰伤害。' },
  { name: '机枪', enName: 'Machine Gun', base: 10, category: 'combat', half: true, rare: true, aliases: ['重机枪'], description: '使用固定或车载重型机枪进行持续火力压制。' },
  { name: '矛', enName: 'Spear', base: 20, category: 'combat', half: true, rare: false, aliases: ['长矛'], description: '使用矛、标枪等长柄穿刺武器进行近战或投掷。' },
  { name: '剑', enName: 'Sword', base: 20, category: 'combat', half: true, rare: false, aliases: ['刀剑'], description: '使用剑类武器进行砍、刺等近战攻击。' },
  { name: '刀', enName: 'Knife', base: 20, category: 'combat', half: true, rare: false, aliases: ['匕首', '小刀'], description: '使用匕首、刀具等小型利器进行近身攻击。' },
  { name: '斧', enName: 'Axe', base: 15, category: 'combat', half: true, rare: false, aliases: ['斧头'], description: '使用斧头类武器进行劈砍攻击。' },
  { name: '鞭', enName: 'Whip', base: 5, category: 'combat', half: true, rare: false, aliases: ['鞭子'], description: '使用鞭子进行远距离抽打或缠绕控制。' },
  { name: '绞索', enName: 'Garrote', base: 15, category: 'combat', half: true, rare: false, aliases: ['绞杀'], description: '使用绞索或类似工具从背后进行无声的窒息攻击。' },

  // ----- other -----
  { name: '乔装', enName: 'Disguise', base: 5, category: 'other', half: true, rare: false, aliases: ['伪装', '易容'], description: '通过化妆、服装和假扮改变自己的外貌和身份。' },
  { name: '母语', enName: 'Own Language', base: 0, category: 'other', half: true, rare: false, aliases: ['汉语', '中文', '语言'], description: '自己的母语能力，基础值=EDU。用于精确表达、写作或识破文字陷阱。' },
  { name: '艺术', enName: 'Art', base: 5, category: 'other', half: true, rare: false, aliases: ['美术', '绘画', '雕塑'], description: '绘画、雕塑、音乐创作等艺术表达方面的才能。' },
  { name: '手艺', enName: 'Craft', base: 5, category: 'other', half: true, rare: false, aliases: ['手工', '制作'], description: '手工制作、修理物品的特殊技艺（需指定具体门类）。' },
  { name: '驯兽', enName: 'Animal Handling', base: 5, category: 'other', half: true, rare: false, aliases: ['动物驯养'], description: '安抚、训练和指挥动物的能力。' },
];

export const CATEGORY_SKILLS: Record<SkillCategory, string[]> = {
  investigation: ['侦查', '聆听', '图书馆使用', '导航', '估价', '追踪'],
  social: ['话术', '说服', '心理学', '威胁', '魅惑', '信用评级'],
  knowledge: ['神秘学', '考古学', '历史', '自然', '医学', '法律', '簿记', '密码学', '电脑使用', '数学', '生物学', '物理学', '天文学', '地质学', '化学', '药学', '人类学', '语言学', '拉丁语', '英语'],
  action: ['闪避', '潜行', '攀爬', '跳跃', '游泳', '投掷', '驾驶', '骑术', '机械维修', '电气维修', '急救', '操作重型机器', '爆破', '锁匠', '摄影', '速记'],
  combat: ['斗殴', '手枪', '步枪', '弓术', '冲锋枪', '霰弹枪', '火焰喷射器', '机枪', '矛', '剑', '刀', '斧', '鞭', '绞索'],
  other: ['乔装', '母语', '艺术', '手艺', '驯兽'],
};

export const OCCUPATIONS = [
  { id: 'detective', name: '侦探', creditMin: 20, creditMax: 50, skillPoints: ['edu', 'str', 'dex'] as const, skills: ['侦查', '法律', '图书馆使用', '话术', '潜行', '锁匠', '心理学', '乔装'] },
  { id: 'journalist', name: '记者', creditMin: 9, creditMax: 30, skillPoints: ['edu', 'pow', 'app'] as const, skills: ['话术', '心理学', '图书馆使用', '说服', '母语', '摄影', '速记'] },
  { id: 'professor', name: '教授', creditMin: 20, creditMax: 70, skillPoints: ['edu', 'int', 'pow'] as const, skills: ['图书馆使用', '母语', '心理学', '说服', '历史', '自然', '神秘学'] },
  { id: 'doctor', name: '医生', creditMin: 30, creditMax: 70, skillPoints: ['edu', 'pow', 'dex'] as const, skills: ['急救', '医学', '生物学', '心理学', '说服', '拉丁语', '母语'] },
  { id: 'police', name: '警察', creditMin: 9, creditMax: 30, skillPoints: ['edu', 'str', 'dex'] as const, skills: ['侦查', '法律', '话术', '斗殴', '手枪', '潜行', '心理学', '驾驶'] },
  { id: 'private_investigator', name: '私家侦探', creditMin: 9, creditMax: 30, skillPoints: ['edu', 'pow', 'dex'] as const, skills: ['侦查', '话术', '法律', '潜行', '锁匠', '心理学', '乔装', '摄影'] },
  { id: 'antiquarian', name: '古董商', creditMin: 10, creditMax: 40, skillPoints: ['edu', 'app', 'pow'] as const, skills: ['估价', '历史', '图书馆使用', '神秘学', '说服', '话术', '信用评级'] },
  { id: 'artist', name: '艺术家', creditMin: 9, creditMax: 50, skillPoints: ['edu', 'pow', 'app'] as const, skills: ['艺术', '手艺', '历史', '图书馆使用', '心理学', '说服'] },
  { id: 'writer', name: '作家', creditMin: 9, creditMax: 30, skillPoints: ['edu', 'pow', 'int'] as const, skills: ['母语', '图书馆使用', '心理学', '历史', '神秘学', '说服'] },
  { id: 'musician', name: '音乐家', creditMin: 9, creditMax: 30, skillPoints: ['edu', 'pow', 'app'] as const, skills: ['艺术', '话术', '心理学', '说服', '聆听'] },
  { id: 'actor', name: '演员', creditMin: 9, creditMax: 30, skillPoints: ['edu', 'app', 'pow'] as const, skills: ['艺术', '乔装', '话术', '心理学', '说服', '魅惑'] },
  { id: 'athlete', name: '运动员', creditMin: 9, creditMax: 30, skillPoints: ['edu', 'str', 'con'] as const, skills: ['攀爬', '跳跃', '游泳', '投掷', '闪避', '斗殴', '驾驶'] },
  { id: 'soldier', name: '军人', creditMin: 9, creditMax: 30, skillPoints: ['edu', 'str', 'con'] as const, skills: ['步枪', '手枪', '急救', '潜行', '导航', '生存', '斗殴', '游泳'] },
  { id: 'mechanic', name: '机械师', creditMin: 9, creditMax: 30, skillPoints: ['edu', 'str', 'dex'] as const, skills: ['机械维修', '电气维修', '驾驶', '手艺', '操作重型机器'] },
  { id: 'computer_engineer', name: '电脑工程师', creditMin: 20, creditMax: 50, skillPoints: ['edu', 'int', 'dex'] as const, skills: ['电脑使用', '电气维修', '密码学', '图书馆使用', '数学'] },
  { id: 'lawyer', name: '律师', creditMin: 30, creditMax: 80, skillPoints: ['edu', 'pow', 'app'] as const, skills: ['法律', '说服', '话术', '心理学', '图书馆使用', '信用评级', '母语'] },
  { id: 'clergy', name: '神职人员', creditMin: 9, creditMax: 30, skillPoints: ['edu', 'pow', 'app'] as const, skills: ['说服', '心理学', '神秘学', '历史', '母语', '急救', '图书馆使用'] },
  { id: 'criminal', name: '罪犯', creditMin: 0, creditMax: 20, skillPoints: ['edu', 'dex', 'pow'] as const, skills: ['潜行', '锁匠', '乔装', '话术', '斗殴', '闪避', '侦查'] },
  { id: 'hobo', name: '流浪汉', creditMin: 0, creditMax: 5, skillPoints: ['edu', 'pow', 'con'] as const, skills: ['潜行', '聆听', '心理学', '导航', '生存', '乔装'] },
  { id: 'ordinary', name: '普通人', creditMin: 5, creditMax: 15, skillPoints: ['edu', 'pow', 'dex'] as const, skills: ['聆听', '心理学', '急救', '驾驶', '话术', '母语'] },
];

// ----- helpers -----

export function rollDice(count: number, sides: number): number[] {
  const results: number[] = [];
  for (let i = 0; i < count; i++) {
    results.push(Math.floor(Math.random() * sides) + 1);
  }
  return results;
}

export function rollAttribute(type: '3d6' | '2d6+6'): { dice: number[]; total: number; value: number } {
  if (type === '3d6') {
    const dice = rollDice(3, 6);
    const total = dice.reduce((a, b) => a + b, 0);
    return { dice, total, value: total * 5 };
  } else {
    const dice = rollDice(2, 6);
    const total = dice.reduce((a, b) => a + b, 0) + 6;
    return { dice: dice, total: dice.reduce((a, b) => a + b, 0), value: total * 5 };
  }
}

export function rollLuck(): { attempts: number[][]; best: number } {
  const attempts: number[][] = [];
  let best = 0;
  for (let i = 0; i < 3; i++) {
    const dice = rollDice(3, 6);
    const value = dice.reduce((a, b) => a + b, 0) * 5;
    attempts.push(dice);
    if (value > best) best = value;
  }
  return { attempts, best };
}

export function calcHP(con: number, siz: number): number {
  return Math.floor((con + siz) / 10);
}

export function calcMP(pow: number): number {
  return Math.floor(pow / 5);
}

export function calcMOV(str: number, dex: number, siz: number, age: number): number {
  let mov = 8;
  if (str < siz && dex < siz) mov = 7;
  else if (str > siz && dex > siz) mov = 9;
  if (age >= 80) mov -= 3;
  else if (age >= 60) mov -= 2;
  else if (age >= 40) mov -= 1;
  return mov;
}

export function calcDBBuild(str: number, siz: number): { db: string; build: number } {
  const sum = str + siz;
  if (sum <= 65) return { db: '-2', build: -2 };
  if (sum <= 84) return { db: '-1', build: -1 };
  if (sum <= 124) return { db: '0', build: 0 };
  if (sum <= 164) return { db: '+1d4', build: 1 };
  if (sum <= 204) return { db: '+1d6', build: 2 };
  return { db: '+2d6', build: 3 };
}

export function getSkillBase(name: string): number {
  const skill = SKILLS.find(s => s.name === name);
  if (name === '闪避') return 0; // DEX/2
  if (name === '母语') return 0; // EDU
  return skill?.base ?? 0;
}

export function getDifficultyThresholds(skillValue: number) {
  return {
    regular: skillValue,
    hard: Math.floor(skillValue / 2),
    extreme: Math.floor(skillValue / 5),
  };
}

export function getSkillDef(name: string): SkillDefinition | undefined {
  return SKILLS.find(s => s.name === name || s.aliases?.includes(name));
}

export function getSkillByAlias(name: string): SkillDefinition | undefined {
  return SKILLS.find(
    s => s.name === name || s.enName?.toLowerCase() === name.toLowerCase() || s.aliases?.some(a => a === name),
  );
}
