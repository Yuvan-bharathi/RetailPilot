"""Reset the database to clean baseline for demonstrations (spec Phase 9).

Usage:
    cd backend && uv run python -m scripts.reset_demo
"""

import asyncio
import redis
from sqlalchemy import text
from app.core.config import get_settings
from app.core.db import get_async_session_factory, use_selector_event_loop


async def reset_demo_database() -> None:
    print("[RESET] Resetting RetailPilot AI demo database...")

    session_factory = get_async_session_factory()
    async with session_factory() as session:
        # Clear transactional and operational tables atomically
        tables = [
            "notification",
            "llm_usage",
            "decision_evidence",
            "tool_call",
            "agent_run",
            "approval",
            "goods_receipt_line",
            "goods_receipt",
            "po_line",
            "purchase_order",
            "transfer_order",
            "replenishment_need",
            "recommendation",
            "forecast",
            "association_rule",
            "inventory_movement",
            "batch",
            "inventory_position",
        ]
        sql = f"TRUNCATE TABLE {', '.join(tables)} CASCADE;"
        await session.execute(text(sql))
        await session.commit()
        print("[RESET] All transactional and operational tables truncated atomically.")

    # Invalidate Redis cache
    try:
        settings = get_settings()
        r = redis.Redis.from_url(settings.redis_url)
        keys = r.keys("retailpilot:*")
        if keys:
            r.delete(*keys)
            print(f"[RESET] Cleared {len(keys)} Redis cache keys.")
    except Exception as e:
        print(f"  Redis cache clear skipped: {e}")

    print("[RESET] Demo database reset complete.")


if __name__ == "__main__":
    use_selector_event_loop()
    asyncio.run(reset_demo_database())
