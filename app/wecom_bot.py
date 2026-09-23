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
                # 关键：监听 SDK 断线/错误事件（被新连接顶替、网络断开、服务端踢线等
                # 都不会抛异常，必须靠事件唤醒下方的重连等待）
                disc = asyncio.Event()
                client.on("disconnected", lambda reason: disc.set())
                client.on("error", lambda e: disc.set())
                await client.connect()                        # 连接+鉴权（失败抛异常）
                self.connected = True
                log.info("企微机器人 %s 长连接已建立", self.cfg["bot_id"])
                await disc.wait()                             # 断线事件触发 → 立即重连
                log.warning("机器人%s 连接断开，5 秒后重连", self.cfg["id"])
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
                self.connected = False
                continue
            except Exception as e:
                log.error("机器人连接异常: %s，5 秒后重连", e)
                await asyncio.sleep(5)
            self.connected = False
            await asyncio.sleep(5)                            # 断线后稍等再重连

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
            # 会话绑定：仅首次记录（绑定关系稳定，不被后续会话覆盖）
            if chattype == "group" and chatid and not self.cfg.get("chat_id"):
                db.update_wecom_chatid(self.cfg["id"], chatid)
                self.cfg["chat_id"] = chatid
                log.info("机器人%s 已绑定群会话 %s", self.cfg["id"], chatid)
            elif chattype == "single" and userid and not self.cfg.get("mom_user"):
                db.update_wecom_user(self.cfg["id"], userid)
                self.cfg["mom_user"] = userid
                log.info("机器人%s 已绑定单聊会话 %s", self.cfg["id"], userid)
        except Exception:
            pass
        # ---- 成员名单校验（企微端准入）----
        member = db.get_wecom_member(self.cfg["id"], userid) if userid else None
        if member is None and userid:
            # 该配置还没有任何已通过成员时，首个发消息者视为管理员自动通过
            first = not db.has_approved_member(self.cfg["id"])
            new_status = "approved" if (first or self.cfg.get("auto_approve")) else "pending"
            db.add_wecom_member(self.cfg["id"], userid, new_status)
            if new_status != "approved":
                stream_id = generate_req_id("stream")
                await self.client.reply_stream(frame, stream_id,
                    "📮 你好！使用信箱需要管理员开通权限，已为你提交申请，请等待管理员在控制台通过。", True)
                return
            member = db.get_wecom_member(self.cfg["id"], userid)
        if member and member["status"] != "approved":
            return   # 未通过/已拒绝：静默忽略
        # ---- 已通过成员：指令 / 回信 ----
        reply = wecom.handle_command(content)
        if reply:
            stream_id = generate_req_id("stream")
            await self.client.reply_stream(frame, stream_id, reply, True)
            return
        # 非指令 → 回信入信箱（带成员身份）
        author = ""
        if member:
            author = member["nickname"] or userid
        wecom.on_mom_reply(content, author)

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

async def notify_child_message(content: str, config_ids=None, device_name: str = "小智设备") -> bool:
    """孩子留言 → 同步推送到机器人群/单聊；config_ids 指定时只推这些配置（设备绑定），否则推全部。
    返回是否至少成功送达一个目标。"""
    from datetime import datetime
    stamp = datetime.now().strftime("%m-%d %H:%M")
    text = f"【{stamp}】{device_name} 留言：\n\n{content}"
    sent = False
    for config_id, st in list(_state.items()):
        # config_ids 语义：None=广播全部；[]或列表=仅推指定配置（设备绑定）
        if config_ids is not None and config_id not in config_ids:
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
