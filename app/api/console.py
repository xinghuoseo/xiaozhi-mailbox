"""控制台 API：登录、设备管理、对话记录、AI 设置、企微配置"""
import asyncio
from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
import os
from .. import auth, ai, db, wecom
from ..mcp import manager as mcp_manager

router = APIRouter()
_STATIC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "static")

def require_auth(request: Request):
    token = request.headers.get("X-Auth-Token") or request.query_params.get("token", "")
    if not auth.verify(token):
        raise HTTPException(status_code=401, detail="未登录或登录已过期")
    return token

@router.get("/")
async def index():
    return FileResponse(os.path.join(_STATIC, "index.html"))

@router.get("/WW_verify_{code}.txt")
async def wecom_domain_verify(code: str):
    """企业微信域名归属验证文件：https://域名/WW_verify_xxx.txt → static/ 下同名文件"""
    import re
    if not re.fullmatch(r"[A-Za-z0-9]+", code):   # 防路径穿越
        raise HTTPException(status_code=404, detail="Not Found")
    path = os.path.join(_STATIC, f"WW_verify_{code}.txt")
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Not Found")
    with open(path, encoding="utf8") as f:
        return PlainTextResponse(f.read().strip())

# ---------- 登录 ----------
@router.post("/api/login")
async def login(request: Request):
    body = await request.json()
    token = auth.login(body.get("username", ""), body.get("password", ""))
    if not token:
        raise HTTPException(status_code=401, detail="账号或密码错误")
    return {"token": token, "username": body.get("username")}

@router.post("/api/logout")
async def logout(request: Request, token: str = Depends(require_auth)):
    auth.logout(token)
    return {"ok": True}

@router.post("/api/change_password")
async def change_password(request: Request, token: str = Depends(require_auth)):
    body = await request.json()
    ok, msg = auth.change_password(token, body.get("old_password", ""), body.get("new_password", ""))
    return {"ok": ok, "msg": msg}

# ---------- 设备 ----------
@router.get("/api/devices")
async def devices(token: str = Depends(require_auth)):
    cmap = mcp_manager.connected_map()
    wnames = {c["id"]: c["name"] for c in db.list_wecom_configs()}
    return [{"id": d["id"], "name": d["name"], "agent_id": d["agent_id"],
             "endpoint": d["endpoint"], "connected": cmap.get(d["id"], False),
             "wecom_config_id": d["wecom_config_id"],
             "wecom_name": wnames.get(d["wecom_config_id"], "")}
            for d in db.list_devices()]

@router.post("/api/devices")
async def add_device(request: Request, token: str = Depends(require_auth)):
    body = await request.json()
    name, endpoint = (body.get("name") or "").strip(), (body.get("endpoint") or "").strip()
    if not name or not endpoint:
        raise HTTPException(status_code=400, detail="设备名称和接入点地址不能为空")
    if not endpoint.startswith(("wss://", "ws://")):
        raise HTTPException(status_code=400, detail="接入点必须以 wss:// 或 ws:// 开头")
    agent_id = mcp_manager.parse_agent_id(endpoint) or mcp_manager.fallback_agent_id()
    wcid = int(body.get("wecom_config_id") or 0)
    if wcid and not db.get_wecom(wcid):
        raise HTTPException(status_code=400, detail="绑定的企微配置不存在")
    device_id = db.add_device(name, agent_id, endpoint, wcid)
    mcp_manager.restart_device(device_id)
    return {"ok": True, "id": device_id, "agent_id": agent_id}

@router.put("/api/devices/{device_id}")
async def edit_device(device_id: int, request: Request, token: str = Depends(require_auth)):
    if not db.get_device(device_id):
        raise HTTPException(status_code=404, detail="设备不存在")
    body = await request.json()
    name, endpoint = (body.get("name") or "").strip(), (body.get("endpoint") or "").strip()
    if not name or not endpoint:
        raise HTTPException(status_code=400, detail="设备名称和接入点地址不能为空")
    agent_id = mcp_manager.parse_agent_id(endpoint) or mcp_manager.fallback_agent_id()
    wcid = int(body.get("wecom_config_id") or 0)
    if wcid and not db.get_wecom(wcid):
        raise HTTPException(status_code=400, detail="绑定的企微配置不存在")
    db.update_device(device_id, name, endpoint, agent_id, wcid)
    mcp_manager.restart_device(device_id)   # 地址可能变了，重连
    return {"ok": True}

@router.delete("/api/devices/{device_id}")
async def del_device(device_id: int, token: str = Depends(require_auth)):
    db.delete_device(device_id)
    mcp_manager.remove_device(device_id)
    return {"ok": True}

@router.post("/api/devices/{device_id}/test")
async def test_device(device_id: int, token: str = Depends(require_auth)):
    d = db.get_device(device_id)
    if not d:
        raise HTTPException(status_code=404, detail="设备不存在")
    return await mcp_manager.test_endpoint(d["endpoint"])

# ---------- 对话记录 ----------
@router.get("/api/records/days")
async def records_days(token: str = Depends(require_auth)):
    stats = {r["d"]: r["c"] for r in db.day_stats(90)}
    dates = sorted(stats.keys(), reverse=True)
    out = []
    for d in dates:
        s = db.get_summary(d)
        out.append({"date": d, "count": stats[d],
                    "short": s["short"] if s else "",
                    "status": s["status"] if s else "pending",
                    "full": s["full"] if s else ""})
    return out

@router.get("/api/records/day/{date_str}")
async def records_day(date_str: str, token: str = Depends(require_auth)):
    return [{"sender": r["sender"], "content": r["content"],
             "time": r["created_at"], "source": r["source"], "read": bool(r["read_at"])}
            for r in db.messages_by_day(date_str)]

@router.post("/api/records/send")
async def records_send(request: Request, token: str = Depends(require_auth)):
    """控制台以妈妈身份直接给孩子留言（入信箱，孩子读留言即可听到）"""
    body = await request.json()
    content = (body.get("content") or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="内容不能为空")
    db.add_message("mom", content, "web")
    return {"ok": True}

@router.post("/api/summary/generate")
async def summary_generate(request: Request, token: str = Depends(require_auth)):
    body = await request.json()
    date_str = body.get("date", "")
    try:
        result = ai.generate_daily_summary(date_str)
        return {"ok": True, **result}
    except RuntimeError as e:
        return JSONResponse(status_code=400, content={"ok": False, "msg": str(e)})

# ---------- AI 设置 ----------
@router.get("/api/ai/settings")
async def ai_settings(token: str = Depends(require_auth)):
    s = ai.get_settings()
    key = s["api_key"]
    s["api_key"] = (key[:6] + "****" + key[-4:]) if len(key) > 12 else ("已设置" if key else "")
    s["has_key"] = bool(key)
    return s

@router.post("/api/ai/settings")
async def save_ai_settings(request: Request, token: str = Depends(require_auth)):
    body = await request.json()
    model = (body.get("model") or "MiniMax-M3").strip()
    base_url = (body.get("base_url") or "https://api.minimaxi.com/v1/text/chatcompletion_v2").strip()
    api_key = (body.get("api_key") or "").strip()
    # 掩码值表示未修改，保留原 key
    if not api_key or "****" in api_key or api_key == "已设置":
        api_key = ai.get_settings()["api_key"]
    ai.save_settings(api_key, model, base_url)
    return {"ok": True}

@router.post("/api/ai/test")
async def ai_test(token: str = Depends(require_auth)):
    return await asyncio.to_thread(ai.test_connection)

# ---------- 企业微信配置 ----------
def _mask(s: str) -> str:
    if not s:
        return ""
    return s[:4] + "****" + s[-4:] if len(s) > 10 else "已设置"

def _keep_or_new(new_val: str, old_val: str) -> str:
    """编辑时：空值或掩码表示未修改，保留原值"""
    new_val = (new_val or "").strip()
    if not new_val or "****" in new_val or new_val == "已设置":
        return old_val
    return new_val

def _bot_connected(config_id: int) -> bool:
    from .. import wecom_bot
    return bool(wecom_bot._state.get(config_id, {}).get("ws"))

def _wecom_out(cfg) -> dict:
    return {"id": cfg["id"], "name": cfg["name"],
            "bot_id": cfg["bot_id"] or "", "bot_key_mask": _mask(cfg["bot_key"]),
            "chat_id": cfg["chat_id"],
            "connected": _bot_connected(cfg["id"])}

@router.get("/api/wecom")
async def wecom_list(token: str = Depends(require_auth)):
    return [_wecom_out(c) for c in db.list_wecom_configs()]

@router.post("/api/wecom")
async def wecom_add(request: Request, token: str = Depends(require_auth)):
    body = await request.json()
    name = (body.get("name") or "").strip()
    bot_id = (body.get("bot_id") or "").strip()
    bot_key = (body.get("bot_key") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="配置名称不能为空")
    if not bot_id or not bot_key:
        raise HTTPException(status_code=400, detail="Bot ID 和 Secret 不能为空")
    cid = db.add_wecom(name, bot_id, bot_key)
    from .. import wecom_bot
    wecom_bot.restart_one(cid)
    return {"ok": True, "id": cid}

@router.put("/api/wecom/{config_id}")
async def wecom_edit(config_id: int, request: Request, token: str = Depends(require_auth)):
    cfg = db.get_wecom(config_id)
    if not cfg:
        raise HTTPException(status_code=404, detail="配置不存在")
    body = await request.json()
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="配置名称不能为空")
    # 掩码/空值 = 未修改，保留原值
    bot_id = (body.get("bot_id") or "").strip() or cfg["bot_id"]
    bot_key = _keep_or_new(body.get("bot_key"), cfg["bot_key"])
    if not (bot_id and bot_key):
        raise HTTPException(status_code=400, detail="Bot ID 和 Secret 不能为空")
    db.update_wecom(config_id, name, bot_id, bot_key)
    from .. import wecom_bot
    wecom_bot.restart_one(config_id)
    return {"ok": True}

@router.delete("/api/wecom/{config_id}")
async def wecom_del(config_id: int, token: str = Depends(require_auth)):
    from .. import wecom_bot
    wecom_bot.stop_one(config_id)
    db.delete_wecom(config_id)
    return {"ok": True}

@router.post("/api/wecom/{config_id}/send")
async def wecom_send(config_id: int, request: Request, token: str = Depends(require_auth)):
    """管理用：主动往机器人的群/单聊发消息（chatid 空则用自动记录的群会话）"""
    cfg = db.get_wecom(config_id)
    if not cfg:
        raise HTTPException(status_code=404, detail="配置不存在")
    body = await request.json()
    chatid = (body.get("chatid") or "").strip() or cfg["chat_id"]
    content = (body.get("content") or "").strip()
    if not chatid:
        return JSONResponse(status_code=400, content={"ok": False,
            "msg": "还没有群会话记录：先在群里 @机器人 发一条消息"})
    if not content:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "内容不能为空"})
    from .. import wecom_bot
    st = wecom_bot._state.get(config_id)
    if not st or not st["client"].connected:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "机器人不在线"})
    try:
        await st["client"].send_markdown(chatid, content)
        return {"ok": True}
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "msg": str(e)})

@router.post("/api/wecom/{config_id}/test")
async def wecom_test(config_id: int, token: str = Depends(require_auth)):
    cfg = db.get_wecom(config_id)
    if not cfg:
        raise HTTPException(status_code=404, detail="配置不存在")
    from .. import wecom_bot
    return await wecom_bot.test_connection(cfg["bot_id"], cfg["bot_key"])
