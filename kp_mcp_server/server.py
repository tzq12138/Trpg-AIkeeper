"""
KP MCP Server - COC 7th Edition AI Keeper

Usage:
    python -m kp_mcp_server
    OPENAI_API_KEY=*** OPENAI_MODEL=gpt-5.4 python -m kp_mcp_server
    DEEPSEEK_API_KEY=*** python -m kp_mcp_server
"""

import asyncio
import json
import logging
import sys

from mcp.server.fastmcp import FastMCP

from .config import Config
from .kp_brain import KpBrain

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("kp_mcp_server")


def build_server(config: Config) -> FastMCP:
    brain = KpBrain(config)
    mcp = FastMCP(
        name="kp-mcp-server",
        instructions="COC 7th Edition AI Keeper，负责主持、规则和叙事生成。",
        host=config.host,
        port=config.port,
        streamable_http_path="/mcp",
        log_level=config.log_level,
    )

    @mcp.tool(
        name="kp_resolve_turn",
        description="处理一轮玩家行动，返回叙事、检定请求、状态变更和战术提示。",
    )
    async def resolve_turn(roomId: str, action: dict, context: dict) -> str:
        result = await brain.resolve_turn(
            {"roomId": roomId, "action": action, "context": context}
        )
        return json.dumps(result, ensure_ascii=False)

    @mcp.tool(
        name="kp_generate_narrative",
        description="根据玩家发言或重写约束，生成一段公开叙事。",
    )
    async def generate_narrative(context: dict) -> str:
        result = await brain.generate_narrative(context or {})
        return json.dumps(result, ensure_ascii=False)

    @mcp.tool(
        name="kp_resolve_sanity",
        description="处理理智事件，生成 SAN 检定与叙事。",
    )
    async def resolve_sanity(roomId: str, context: dict, trigger: dict) -> str:
        result = await brain.resolve_sanity(
            {"roomId": roomId, "context": context, "trigger": trigger}
        )
        return json.dumps(result, ensure_ascii=False)

    @mcp.tool(
        name="kp_resolve_combat_round",
        description="处理一轮战斗，确定行动顺序、检定请求与结果。",
    )
    async def resolve_combat_round(roomId: str, combatants: list) -> str:
        result = await brain.resolve_combat_round(
            {"roomId": roomId, "combatants": combatants}
        )
        return json.dumps(result, ensure_ascii=False)

    @mcp.tool(
        name="kp_structure_scenario",
        description="将剧本文本结构化，提取场景、NPC、线索、真相和结局。",
    )
    async def structure_scenario(
        rawText: str = "",
        format: str = "full",
        contentPackage: dict | None = None,
    ) -> str:
        result = await brain.structure_scenario({
            "rawText": rawText,
            "format": format,
            "contentPackage": contentPackage,
        })
        return json.dumps(result, ensure_ascii=False)

    @mcp.tool(
        name="kp_query_rules",
        description="查询 COC 七版规则、检定和战斗机制。",
    )
    async def query_rules(question: str, context: dict | None = None) -> str:
        result = await brain.query_rules(
            {"question": question, "context": context or {}}
        )
        return json.dumps(result, ensure_ascii=False)

    @mcp.tool(
        name="kp_query_knowledge",
        description="查询当前剧本、NPC、线索和真相相关知识。",
    )
    async def query_knowledge(
        query: str,
        roomId: str = "",
        sources: list | None = None,
        maxTokens: int = 500,
    ) -> str:
        result = await brain.query_knowledge(
            {
                "query": query,
                "roomId": roomId,
                "sources": sources or ["scenario", "rules"],
                "maxTokens": maxTokens,
            }
        )
        return json.dumps(result, ensure_ascii=False)

    @mcp.tool(
        name="kp_health_check",
        description="返回 KP MCP Server 当前状态。",
    )
    async def health_check() -> str:
        return json.dumps(
            {
                "status": "ok" if not config.is_mock else "mock",
                "provider": config.provider,
                "model": brain.model,
                "rulesVersion": "COC 7th v1.2.1",
            },
            ensure_ascii=False,
        )

    logger.info(
        "KP MCP Server built (provider=%s, model=%s, mock=%s, tools=%s)",
        config.provider,
        config.model,
        config.is_mock,
        8,
    )
    return mcp


def main():
    config = Config.from_env()
    mcp = build_server(config)

    logger.info("Starting KP MCP Server on http://%s:%s/mcp", config.host, config.port)
    try:
        asyncio.run(mcp.run_streamable_http_async())
    except KeyboardInterrupt:
        logger.info("KP MCP Server stopped.")
        sys.exit(0)


if __name__ == "__main__":
    main()
