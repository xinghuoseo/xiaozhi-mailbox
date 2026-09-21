"""定时任务：每天 00:05 总结前一天对话，启动时补跑遗漏"""
import asyncio, logging
from datetime import datetime, timedelta
from . import ai

log = logging.getLogger("scheduler")

async def start():
    asyncio.create_task(_loop())

async def _loop():
    today = datetime.now().date().isoformat()
    await asyncio.to_thread(ai.backfill_summaries, today)
    while True:
        now = datetime.now()
        target = (now + timedelta(days=1)).replace(hour=0, minute=5, second=0, microsecond=0)
        wait = (target - now).total_seconds()
        log.info("每日总结任务将于 %s 执行（%.0f 小时后）", target, wait / 3600)
        await asyncio.sleep(wait)
        yesterday = (datetime.now().date() - timedelta(days=1)).isoformat()
        try:
            await asyncio.to_thread(ai.generate_daily_summary, yesterday)
            await asyncio.to_thread(ai.backfill_summaries, datetime.now().date().isoformat())
        except Exception as e:
            log.warning("每日总结执行失败: %s", e)
