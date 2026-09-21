import asyncio, json, logging
from datetime import datetime
import websockets

log = logging.getLogger("mcp")

class XiaozhiMCPClient:
    """反向接入：我们主动连接小智云端 MCP 接入点，按 JSON-RPC 2.0 应答"""

    def __init__(self, endpoint: str, registry: dict, device_id: int = 0):
        self.endpoint = endpoint
        self.registry = registry  # {name: {"description","schema","handler"}}
        self.device_id = device_id
        self.connected = False    # 连接状态（管理后台展示用）
        self.connected_at = ""

    async def start(self):
        while True:
            try:
                async with websockets.connect(self.endpoint, max_size=None,
                                              ping_interval=20, ping_timeout=20) as ws:
                    self.connected = True
                    self.connected_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    log.info("设备%s 已连接小智 MCP 接入点", self.device_id)
                    async for raw in ws:
                        try:
                            msg = json.loads(raw)
                        except (json.JSONDecodeError, UnicodeDecodeError):
                            log.warning("收到非 JSON 消息，忽略")
                            continue
                        asyncio.create_task(self._handle(ws, msg))
            except asyncio.CancelledError:
                self.connected = False
                raise
            except Exception as e:
                self.connected = False
                log.error("设备%s MCP 连接断开: %s，5 秒后重连", self.device_id, e)
                await asyncio.sleep(5)

    async def _handle(self, ws, msg: dict):
        method, mid, params = msg.get("method"), msg.get("id"), msg.get("params") or {}

        try:
            if method == "initialize":
                await self._send(ws, {"jsonrpc": "2.0", "id": mid, "result": {
                    "protocolVersion": params.get("protocolVersion", "2024-11-05"),
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "family-mailbox", "version": "1.0.0"}}})

            elif method == "notifications/initialized":
                log.info("设备%s MCP 握手完成，等待工具调用...", self.device_id)

            elif method == "ping":
                await self._send(ws, {"jsonrpc": "2.0", "id": mid, "result": {}})

            elif method == "tools/list":
                tools = [{"name": n, "description": t["description"], "inputSchema": t["schema"]}
                         for n, t in self.registry.items()]
                await self._send(ws, {"jsonrpc": "2.0", "id": mid, "result": {"tools": tools}})

            elif method == "tools/call":
                name, args = params.get("name"), params.get("arguments") or {}
                log.info("设备%s 工具调用: %s 参数: %s", self.device_id, name, args)
                tool = self.registry.get(name)
                try:
                    if not tool:
                        raise ValueError(f"未知工具: {name}")
                    result = tool["handler"](**args, device_id=self.device_id)
                    if asyncio.iscoroutine(result):
                        result = await result
                except TypeError as e:
                    log.warning("工具参数错误: %s", e)
                    result = {"success": False, "result": "参数好像不对，再说一遍好吗"}
                except Exception as e:
                    log.exception("工具执行失败: %s", name)
                    result = {"success": False, "result": "操作出了点小问题，等会儿再试吧"}
                await self._send(ws, {"jsonrpc": "2.0", "id": mid, "result": {
                    "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
                    "isError": False}})
                log.info("设备%s 工具调用完成: %s -> %s", self.device_id, name, result)

            else:
                # 未知请求（带 id 需回错误，通知则忽略）
                if mid is not None:
                    await self._send(ws, {"jsonrpc": "2.0", "id": mid, "error": {
                        "code": -32601, "message": f"Method not found: {method}"}})
        except Exception:
            log.exception("处理 MCP 消息失败: %s", msg)

    async def _send(self, ws, data: dict):
        await ws.send(json.dumps(data, ensure_ascii=False))
