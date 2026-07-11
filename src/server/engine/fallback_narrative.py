import re


def render_action_aware_fallback(
    declared_intent: str,
    *,
    character_name: str = "",
    succeeded: bool = True,
) -> str:
    declared = (declared_intent or "进行行动").strip()
    if len(declared) > 200:
        declared = declared[:200] + "..."
    actor = f"{character_name}把" if character_name else "你把"

    if re.search(r"观察|查看|看看|阅读|搜索|检查|环顾|聆听", declared):
        return f"{actor}注意力集中在「{declared}」上；可确认的细节将依据当前场景资料逐项展开。"
    if re.search(r"询问|交谈|告诉|说|喊|打招呼", declared):
        speaker = character_name or "你"
        return f"{speaker}明确表达了「{declared}」；在场角色的回应将依据其立场与已公开信息推进。"
    if re.search(r"移动|前往|进入|离开|走向|跑向", declared):
        return f"{actor}行动目标定在「{declared}」；路径、阻碍与风险将按当前地图和场景状态结算。"
    if succeeded:
        subject = character_name or "你"
        return f"{subject}开始执行「{declared}」；结果将依据当前场景状态与已公开事实推进。"
    return f"「{declared}」没有形成可确认的结果；现有状态保持不变。"
