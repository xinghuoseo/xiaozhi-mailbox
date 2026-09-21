"""MCP 多设备生命周期管理 + 接入点连通测试"""
import asyncio, json, logging, secrets, base64
from urllib.parse import urlparse, parse_qs
import websockets
from .. import config, db
from .client import XiaozhiMCPClient
from ..tools import REGISTRY

log = logging.getLogger("mcpmgr")
_state = {}  # device_id -> {"client": XiaozhiMCPClient, "task": Task}

# ---------- 设备ID解析（从接入点 JWT） ----------
def parse_agent_id(endpoint: str) -> str:
    try:
        token = parse_qs(urlparse(endpoint).query).get("token", [""])[0]
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload))
        return str(data.get("agentId") or data.get("agent_id") or "")
    except Exception:
        return ""

def fallback_agent_id() -> str:
    return "dev_" + secrets.token_hex(3)

# ---------- 生命周期 ----------
def migrate_env_device():
    """devices 表为空且 .env 里还有 MCP_ENDPOINT 时，自动导入为第一台设备"""
    if db.list_devices() or not config.MCP_ENDPOINT:
        return
    aid = parse_agent_id(config.MCP_ENDPOINT) or fallback_agent_id()
    db.add_device("小智设备", aid, config.MCP_ENDPOINT)
    log.info("已将 .env 中的 MCP 接入点导入为设备: 小智设备(agent=%s)", aid)

def start_all():
    migrate_env_device()
    for d in db.list_devices():
        _start_one(d["id"], d["endpoint"])

def _start_one(device_id: int, endpoint: str):
    _stop_one(device_id)
    client = XiaozhiMCPClient(endpoint, REGISTRY, device_id=device_id)
    _state[device_id] = {"client": client, "task": asyncio.create_task(client.start())}

def _stop_one(device_id: int):
    st = _state.pop(device_id, None)
    if st:
        st["task"].cancel()

def restart_device(device_id: int):
    d = db.get_device(device_id)
    if d:
        _start_one(d["id"], d["endpoint"])

def remove_device(device_id: int):
    _stop_one(device_id)

def connected_map() -> dict:
    return {dev_id: bool(st["client"].connected) for dev_id, st in _state.items()}

# ---------- 连通测试（独立短连接，不影响长连接） ----------
async def test_endpoint(endpoint: str) -> dict:
    if not endpoint.startswith(("wss://", "ws://")):
        return {"success": False, "message": "地址必须以 wss:// 或 ws:// 开头"}
    try:
        async with websockets.connect(endpoint, max_size=None,
                                      ping_interval=20, ping_timeout=20) as ws:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=5)
                msg = json.loads(raw)
                if msg.get("method") == "initialize":
                    await ws.send(json.dumps({"jsonrpc": "2.0", "id": msg.get("id"), "result": {
                        "protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                        "serverInfo": {"name": "family-mailbox", "version": "1.0.0"}}}))
                    return {"success": True, "message": "联通成功，MCP 握手完成"}
                return {"success": True, "message": "连接成功"}
            except asyncio.TimeoutError:
                return {"success": True, "message": "连接已建立（云端 5 秒内未发起握手，token 有效）"}
    except Exception as e:
        return {"success": False, "message": f"连接失败: {e}"}
