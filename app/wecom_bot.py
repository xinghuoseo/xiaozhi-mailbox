"""企微智能机器人长连接（基于官方 SDK wecom-aibot-sdk）
协议细节（鉴权/心跳/断线/帧解析）全部由 SDK 处理。
消息规则：@帮助 / 查信息 日期 → 指令回复；其余文字 → 妈妈的回信入信箱。
"""
import asyncio, logging, re
from wecom_aibot_sdk import WSClient, WSAuthFailureError, generate_req_id
from . import db, wecom

log = logging.getLogger("wecombot")
_state = {}   # config_id -> {"client": WeComBotClient, "task": Task}

def strip_at_prefix(content: str) -> str:
    """清洗群里 @机器人 的各种写法：
    '@机器人 查未读' → '查未读'（@后带名字+空格，去掉名字）
    '@查未读'        → '查未读'（手打@直接跟内容，只去掉@）
    '@ 查未读'       → '查未读'
    '普通消息'       → 原样
    """
    c = (content or "").lstrip()
    if not c.startswith("@"):
        return c
    rest = c[1:].lstrip()                 # 去掉 @ 与紧随空格
    if " " in rest:                       # @后面还有空格 → 第一个词是机器人名，去掉
        rest = rest.split(" ", 1)[1].strip()
    return rest

class WeComBotClient:
    def __init__(self, cfg):
        self.cfg = dict(cfg)
        self.connected = False
        self.client = None

    def refresh(self, cfg):
        self.cfg = dict(cfg)

    async def start(self):
        while True:
            try:
                client = WSClient(bot_id=self.cfg["bot_id"], secret=self.cfg["bot_key"],
                                  max_reconnect_attempts=0)   # 内部不重连，由外层循环接管
                self.client = client
                self._register(client)
                await client.connect()                        # 连接+鉴权（失败抛异常）
                self.connected = True
                log.info("企微机器人 %s 长连接已建立", self.cfg["bot_id"])
                await asyncio.Event().wait()                  # 挂起保持运行，直到任务被取消
            except asyncio.CancelledError:
                if self.client:
                    try:
                        await self.client.disconnect()
                    except Exception:
                        pass
                raise
            except WSAuthFailureError as e:
                log.error("机器人%s 认证失败（检查 BotID/Secret）: %s，60 秒后重试", self.cfg["id"], e)
                await asyncio.sleep(60)
            except Exception as e:
                log.error("机器人连接异常: %s，5 秒后重连", e)
                await asyncio.sleep(5)
            finally:
                self.connected = False

    def _register(self, client: WSClient):
        async def on_text(frame):
            try:
                await self._handle_text(frame)
            except Exception:
                log.exception("处理机器人消息失败")
        client.on("message.text", on_text)

    async def _handle_text(self, frame):
        body = frame.get("body") or {}
        content = strip_at_prefix((body.get("text") or {}).get("content", ""))
        if not content:
            return
        chattype = body.get("chattype")            # group / single
        chatid = body.get("chatid") or ""
        userid = (body.get("from") or {}).get("userid") or ""
        # 回填会话标识（通知用）
        try:
            if chattype == "group" and chatid and chatid != self.cfg.get("chat_id"):
                db.update_wecom_chatid(self.cfg["id"], chatid)
                self.cfg["chat_id"] = chatid
                log.info("机器人%s 已记录群会话 %s", self.cfg["id"], chatid)
            elif chattype == "single" and userid and userid != self.cfg.get("mom_user"):
                db.update_wecom_user(self.cfg["id"], userid)
                self.cfg["mom_user"] = userid
        except Exception:
            pass
        # 指令（仅企微端）：查信息 / @帮助
        reply = wecom.handle_command(content)
        if reply:
            stream_id = generate_req_id("stream")
            await self.client.reply_stream(frame, stream_id, reply, True)
            return
        # 非指令 → 妈妈的回信入信箱
        wecom.on_mom_reply(content)

    async def send_markdown(self, chatid: str, content: str):
        """主动推送 markdown 到会话（群 chatid 或 单聊 userid）"""
        if not self.client:
            raise RuntimeError("机器人未在线")
        await self.client.send_message(chatid, {
            "msgtype": "markdown", "markdown": {"content": content}})

# ---------- 生命周期管理 ----------
def start_all():
    for c in db.list_wecom_configs():
        if c["mode"] == "bot" and c["enabled"]:
            start_one(c["id"])

def start_one(config_id: int):
    stop_one(config_id)
    cfg = db.get_wecom(config_id)
    if not cfg:
        return
    client = WeComBotClient(cfg)
    _state[config_id] = {"client": client, "task": asyncio.create_task(client.start())}

def stop_one(config_id: int):
    st = _state.pop(config_id, None)
    if st:
        st["task"].cancel()

def restart_one(config_id: int):
    cfg = db.get_wecom(config_id)
    if cfg and cfg["mode"] == "bot" and cfg["enabled"]:
        start_one(config_id)
    else:
        stop_one(config_id)

def connected_map() -> dict:
    return {cid: bool(st["client"].connected) for cid, st in _state.items()}

async def notify_child_message(content: str, config_ids=None) -> bool:
    """孩子留言 → 同步推送到机器人群/单聊；config_ids 指定时只推这些配置（设备绑定），否则推全部。
    返回是否至少成功送达一个目标。"""
    text = f"mailbox!孩子刚刚留言啦：\n\n{content}\n\n（回复机器人消息即可回信给孩子）"
    sent = False
    for config_id, st in list(_state.items()):
        if config_ids and config_id not in config_ids:
            continue
        cfg = db.get_wecom(config_id)
        if not cfg or not st["client"].connected:
            continue
        try:
            if cfg["chat_id"]:
                await st["client"].send_markdown(cfg["chat_id"], text)
                sent = True
            if cfg["mom_user"]:
                try:
                    await st["client"].send_markdown(cfg["mom_user"], text)
                except Exception as e:
                    log.warning("机器人单聊通知失败: %s", e)
        except Exception as e:
            log.warning("机器人%s 群通知失败: %s", config_id, e)
    return sent

# ---------- 连通测试（独立短连接） ----------
async def test_connection(bot_id: str, bot_key: str) -> dict:
    if not bot_id or not bot_key:
        return {"success": False, "message": "Bot ID 和 Secret 都要填"}
    client = WSClient(bot_id=bot_id, secret=bot_key, max_reconnect_attempts=0)
    try:
        await client.connect()
        return {"success": True, "message": "联通成功，机器人认证通过"}
    except WSAuthFailureError as e:
        return {"success": False, "message": f"认证失败，Bot ID 或 Secret 不正确（{e}）"}
    except Exception as e:
        return {"success": False, "message": f"连接失败: {e}"}
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass
