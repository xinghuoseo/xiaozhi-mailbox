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
        # 来源会话（群=群chatid / 私聊=userid），记录到成员上供通知定位
        member_chat_id = chatid if chattype == "group" else userid
        member_chat_type = "group" if chattype == "group" else "single"
        # ---- 成员名单校验（企微端准入）----
        member = db.get_wecom_member(self.cfg["id"], userid) if userid else None
        if member is None and userid:
            # 该配置还没有任何已通过成员时，首个发消息者视为管理员自动通过
            first = not db.has_approved_member(self.cfg["id"])
            new_status = "approved" if (first or self.cfg.get("auto_approve")) else "pending"
            db.add_wecom_member(self.cfg["id"], userid, new_status,
                                chat_id=member_chat_id, chat_type=member_chat_type)
            if new_status != "approved":
                stream_id = generate_req_id("stream")
                await self.client.reply_stream(frame, stream_id,
                    "📮 你好！使用信箱需要管理员开通权限，已为你提交申请，请等待管理员在控制台通过。", True)
                return
            member = db.get_wecom_member(self.cfg["id"], userid)
        elif member and not member["chat_id"]:
            # 老成员缺会话记录 → 补记
            db.update_wecom_member_chat(member["id"], member_chat_id, member_chat_type)
            member = db.get_wecom_member(self.cfg["id"], userid)
        if member and member["status"] != "approved":
            return   # 未通过/已拒绝：静默忽略
        # ---- 已通过成员：指令 / 回信 ----
        reply = wecom.handle_command(content)
        if reply:
            stream_id = generate_req_id("stream")
            await self.client.reply_stream(frame, stream_id, reply, True)
            return
        # 非指令 → 回信入信箱（带成员身份 + 成员账号，供后续通知定位会话）
        author = ""
        if member:
            author = member["nickname"] or userid
        wecom.on_mom_reply(content, author, userid)

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
    """孩子留言 → 按来源会话发送：
    优先定位该配置下最近一条「妈妈发出」记录对应的成员，按其会话类型发送
    （私聊直发 / 群聊用企微 markdown 提及语法 <@userid> @该成员）；
    无回信历史时兜底：向所有已通过成员的会话去重发送（群直接发群，不@）。
    config_ids 指定时只推这些配置，None=广播全部。"""
    from datetime import datetime
    stamp = datetime.now().strftime("%m-%d %H:%M")
    sent = False
    for config_id, st in list(_state.items()):
        if config_ids is not None and config_id not in config_ids:
            continue
        if not st["client"].connected:
            continue
        targets = []   # [(chatid, chat_type, mention_userid)]
        last = db.last_mom_sender(config_id)
        if last:
            # 按最近一次发送端成员的会话定位
            if last["chat_type"] == "group" and last["chat_id"]:
                targets.append((last["chat_id"], "group", last["userid"]))
            else:
                targets.append((last["userid"], "single", ""))
        else:
            # 兜底：还没有回信历史 → 所有已通过成员的会话去重发送
            seen = set()
            for m in db.list_approved_members(config_id):
                key = m["chat_id"] if m["chat_type"] == "group" else m["userid"]
                if not key or key in seen:
                    continue
                seen.add(key)
                targets.append((key, m["chat_type"], ""))
        for chatid, ctype, mention in targets:
            text = f"【{stamp}】{device_name} 留言：\n\n{content}"
            if ctype == "group" and mention:
                text = f"<@{mention}> {text}"   # 企微 markdown 提及语法
            try:
                await st["client"].send_markdown(chatid, text)
                sent = True
            except Exception as e:
                log.warning("通知会话%s 失败: %s", chatid, e)
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
