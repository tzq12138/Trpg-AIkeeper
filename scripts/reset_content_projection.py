from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.server.db_adapter import PgDatabase
from src.server.scenario.content_projection import ContentProjectionService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="重置单个剧本版本的规范内容投影；不会改动原件、世界书、RAG 或房间。"
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL", "postgresql://aikeeper:aikeeper123@127.0.0.1:5432/aikeeper"),
    )
    parser.add_argument("--scenario-version-id", required=True)
    parser.add_argument("--requested-by", default="content-projection-cli")
    parser.add_argument(
        "--confirm-reset",
        action="store_true",
        help="明确确认删除该版本的规范节点和关系；保留原件、世界书、RAG、房间和运行记录。",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.confirm_reset:
        raise SystemExit("拒绝执行：请显式传入 --confirm-reset")

    database = PgDatabase(dsn=args.database_url)
    database.connect()
    database.initialize()
    try:
        result = ContentProjectionService(database.get_connection()).reset(
            args.scenario_version_id,
            requested_by=args.requested_by,
        )
        print(json.dumps(result, ensure_ascii=False))
    finally:
        database.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
