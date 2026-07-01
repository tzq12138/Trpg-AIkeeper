"""
KP MCP Server — COC 7th Edition AI Keeper

StreamableHTTP MCP server using FastMCP (mcp >= 1.0).
Usage:
    python -m kp_mcp_server
    DEEPSEEK_API_KEY=*** python -m kp_mcp_server
"""

import asyncio
import json
import logging
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.types import Tool, TextContent

from .config import Config
from .kp_brain import KpBrain

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("kp_mcp_server")

# ── build server ─────────────────────────────────────────

def build_server(config: Config) -> FastMCP:
    brain = KpBrain(config)
    mcp = FastMCP(
        name="kp-mcp-server",
        instructions="COC 7th Edition AI Keeper — 克苏鲁的呼唤 AI 守秘人",
        host=config.host,
        port=config.port,
        streamable_http_path="/mcp",
        log_level=config.log_level,
    )

    # ── tool: kp_resolve_turn ──
    @mcp.tool(
        name="kp_resolve_turn",
        description="处理一轮玩家行动：返回叙事、检定请求、状态变更。这是主要的 KP 结算入口。",
    )
    async def resolve_turn(
        roomId: str,
        action: dict,
        context: dict,
    ) -> str:
        result = await brain.resolve_turn({
            "roomId": roomId, "action": action, "context": context,
        })
        return json.dumps(result, ensure_ascii=False)

    # ── tool: kp_resolve_sanity ──
    @mcp.tool(
        name="kp_resolve_sanity",
        description="处理理智事件：目击恐怖场景、阅读禁书、遭遇神话存在时的 SAN 检定与叙事。",
    )
    async def resolve_sanity(
        roomId: str,
        context: dict,
        trigger: dict,
    ) -> str:
        result = await brain.resolve_sanity({
            "roomId": roomId, "context": context, "trigger": trigger,
        })
        return json.dumps(result, ensure_ascii=False)

    # ── tool: kp_resolve_combat_round ──
    @mcp.tool(
        name="kp_resolve_combat_round",
        description="处理一轮战斗：确定行动顺序、提出检定请求、判定战术结果。",
    )
    async def resolve_combat_round(
        roomId: str,
        combatants: list,
    ) -> str:
        result = await brain.resolve_combat_round({
            "roomId": roomId, "combatants": combatants,
        })
        return json.dumps(result, ensure_ascii=False)

    # ── tool: kp_structure_scenario ──
    @mcp.tool(
        name="kp_structure_scenario",
        description="将剧本原文结构化：提取场景、NPC、线索、真相、结局。",
    )
    async def structure_scenario(
        rawText: str,
        format: str = "full",
    ) -> str:
        result = await brain.structure_scenario({
            "rawText": rawText, "format": format,
        })
        return json.dumps(result, ensure_ascii=False)

    # ── tool: kp_query_rules ──
    @mcp.tool(
        name="kp_query_rules",
        description="查询 COC 七版规则：掷骰规则、战斗规则、理智规则等。",
    )
    async def query_rules(
        question: str,
        context: dict | None = None,
    ) -> str:
        result = await brain.query_rules({
            "question": question, "context": context or {},
        })
        return json.dumps(result, ensure_ascii=False)

    # ── tool: kp_query_knowledge ──
    @mcp.tool(
        name="kp_query_knowledge",
        description="Host 知识库问答：查询当前剧本的 NPC 详情、线索关联、真相信息。",
    )
    async def query_knowledge(
        query: str,
        roomId: str = "",
        sources: list | None = None,
        maxTokens: int = 500,
    ) -> str:
        result = await brain.query_knowledge({
            "query": query,
            "roomId": roomId,
            "sources": sources or ["scenario", "rules"],
            "maxTokens": maxTokens,
        })
        return json.dumps(result, ensure_ascii=False)

    # ── tool: kp_health_check ──
    @mcp.tool(
        name="kp_health_check",
        description="存活探测：返回 KP MCP Server 状态。",
    )
    async def health_check() -> str:
        return json.dumps({
            "status": "ok" if not config.is_mock else "mock",
            "model": brain.model,
            "rulesVersion": "COC 7th v1.2.1",
        }, ensure_ascii=False)

    logger.info("KP MCP Server built (model=%s, mock=%s, 7 tools)",
                config.deepseek_model, config.is_mock)
    return mcp


# ── entry ────────────────────────────────────────────────

def main():
    config = Config.from_env()
    mcp = build_server(config)

    logger.info("Starting KP MCP Server on http://%s:%s/mcp",
                config.host, config.port)
    try:
        asyncio.run(mcp.run_streamable_http_async())
    except KeyboardInterrupt:
        logger.info("KP MCP Server stopped.")
        sys.exit(0)


if __name__ == "__main__":
    main()
