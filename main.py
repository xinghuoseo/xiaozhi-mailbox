import asyncio, logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import PlainTextResponse, Response
from app import config, db, auth, scheduler
from app.mcp import manager as mcp_manager
from app import wecom_bot
from app.api.console import router as console_router

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("main")

@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    auth.ensure_default_user()
    mcp_manager.start_all()
    wecom_bot.start_all()
    await scheduler.start()
    log.info("亲子信箱服务启动（V2 控制台版）")
    yield
    for st in list(mcp_manager._state.values()):
        st["task"].cancel()
    for st in list(wecom_bot._state.values()):
        st["task"].cancel()

app = FastAPI(title="亲子信箱", lifespan=lifespan)
app.include_router(console_router)

@app.get("/health")
async def health():
    cmap = mcp_manager.connected_map()
    return {"ok": True, "devices": len(cmap), "connected": sum(cmap.values()),
            "unread_mom": db.unread_mom_count()}
