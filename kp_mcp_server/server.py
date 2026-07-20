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
    instructions="COC 7th Edition AI Keeper，负责剧本编译、结构化裁决计划和证据约束叙事。",
        host=config.host,
        port=config.port,
        streamable_http_path="/mcp",
        log_level=config.log_level,
    )

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
        name="kp_analyze_director_action",
        description="根据运行时上下文生成结构化 Director 裁决计划，不写入游戏状态。",
    )
    async def analyze_director_action(context: dict) -> str:
        result = await brain.analyze_director_action(context or {})
        return json.dumps(result, ensure_ascii=False)

    @mcp.tool(
        name="kp_narrate_action",
        description="基于已验证的裁决结果生成公开叙事，不创建事实或状态修改。",
    )
    async def narrate_action(context: dict) -> str:
        result = await brain.narrate_action(context or {})
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
        4,
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
