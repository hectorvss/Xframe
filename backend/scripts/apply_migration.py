"""Apply one repository migration to the configured database.

Usage: python scripts/apply_migration.py ../supabase/015_example.sql
The connection string is read through application settings and is never printed.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import asyncpg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import get_settings


async def apply(path: Path) -> None:
    connection = await asyncpg.connect(str(get_settings().database_url))
    try:
        await connection.execute(path.read_text(encoding="utf-8"))
    finally:
        await connection.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("migration", type=Path)
    args = parser.parse_args()
    asyncio.run(apply(args.migration.resolve()))
