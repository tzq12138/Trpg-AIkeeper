import json
import logging
from typing import Any

import httpx

from .tools import get_tools, ToolExecutor

logger = logging.getLogger(__name__)

MAX_ROUNDS = 5

AGENT_SYSTEM_PROMPT = """你是COC守秘人(KP)，负责推进剧情、扮演NPC、控制氛围。

你的职责：
1. 理解玩家的意图
2. 使用工具查询游戏状态（NPC、地点、线索）
3. 使用工具执行游戏规则（检定、保存线索）
4. 生成沉浸式叙事文本

工作流程：
1. 玩家输入后，先查询相关信息（query_npcs, query_location, query_clues, query_recent_events）
2. 根据玩家意图执行相应操作（engine_roll_check, engine_save_clue）
3. 最后调用 output_narrative 输出叙事文本

规则：
- 只能使用工具返回的NPC和地点，不能发明新的
- NPC必须根据personality和motivation说话和行动
- 如果玩家问NPC问题，NPC必须给出具体回答
- 检定结果必须由engine_roll_check返回，不能自己编造
- 发现的线索必须通过engine_save_clue保存
- 叙事文本200字以内，简体中文
- 如果玩家说"说下去"，先查recent_events了解上一条叙事，然后继续

重要：你必须在推理结束时调用output_narrative输出最终叙事。"""


class GameAgent:
    def __init__(
        self,
        api_key: str = "",
        model: str = "deepseek-v4-pro",
        api_base: str = "https://api.deepseek.com",
    ):
        self.api_key = api_key
        self.model = model
        self.api_base = api_base

    @property
    def is_available(self) -> bool:
        return bool(self.api_key)

    async def run(
        self,
        player_input: str,
        conn,
        room_id: str,
        character_id: str,
        scenario: dict | None,
    ) -> dict:
        """Run the agent to process a player input and generate narrative.

        Returns dict with keys: narrative, state_changes, rounds.
        """
        if not self.is_available:
            return {"narrative": "", "state_changes": [], "rounds": 0}

        tool_executor = ToolExecutor(conn, room_id, character_id, scenario)
        tools = get_tools()

        messages = [
            {"role": "system", "content": AGENT_SYSTEM_PROMPT},
            {"role": "user", "content": player_input},
        ]

        narrative = ""
        state_changes: list[dict] = []

        for round_num in range(MAX_ROUNDS):
            try:
                response = await self._call_llm(messages, tools)
            except Exception as e:
                logger.warning("Agent LLM call failed at round %d: %s", round_num, e)
                break

            message = response.get("choices", [{}])[0].get("message", {})
            finish_reason = response.get("choices", [{}])[0].get("finish_reason", "")
            content = message.get("content", "")
            tool_calls = message.get("tool_calls", [])

            if content:
                messages.append({"role": "assistant", "content": content})

            if finish_reason == "stop" or not tool_calls:
                narrative = content or narrative
                break

            if tool_calls:
                messages.append({"role": "assistant", "tool_calls": tool_calls})

                for tc in tool_calls:
                    tc_id = tc.get("id", "")
                    func = tc.get("function", {})
                    func_name = func.get("name", "")
                    func_args = func.get("arguments", "{}")

                    try:
                        args = json.loads(func_args) if isinstance(func_args, str) else func_args
                    except json.JSONDecodeError:
                        args = {}

                    logger.info("Agent tool call: %s(%s)", func_name, json.dumps(args, ensure_ascii=False)[:100])

                    result = await tool_executor.execute(func_name, args)
                    logger.info("Agent tool result: %s...", result[:100])

                    if func_name == "output_narrative":
                        try:
                            result_data = json.loads(result)
                            narrative = result_data.get("narrative", "")
                        except Exception:
                            narrative = args.get("text", "")

                    if func_name == "engine_roll_check":
                        try:
                            roll_data = json.loads(result)
                            state_changes.append({
                                "type": "skill_check",
                                "data": roll_data,
                            })
                        except Exception:
                            pass

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": result,
                    })

        return {
            "narrative": narrative,
            "state_changes": state_changes,
            "rounds": round_num + 1,
        }

    async def _call_llm(self, messages: list, tools: list) -> dict:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{self.api_base}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": messages,
                    "tools": tools,
                    "tool_choice": "auto",
                    "temperature": 0.7,
                },
            )
            response.raise_for_status()
            return response.json()
