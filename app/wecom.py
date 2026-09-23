"""企微指令处理（智能机器人长连接模式专用）
消息处理规则：@帮助 / 查信息 日期 / 查未读 → 指令回复；其余一切文字 → 妈妈的回信入信箱
注意：企微 markdown 消息在手机端单个 \n 不换行，所有换行一律使用 \n\n
"""
import re, logging
from datetime import datetime
from . import db

log = logging.getLogger("wecom")

HELP_TEXT = (
    "【小智留言系统 · 使用说明】\n\n"
    "本系统为亲子留言信箱：孩子通过小智AI音箱发送留言，监护人通过企业微信回复，孩子即可通过音箱收听。\n\n"
    "一、使用方法\n\n"
    "1. 孩子对小智说：“给妈妈留言，说……”；\n\n"
    "2. 系统会将留言实时推送至本会话及关联群聊；\n\n"
    "3. 直接回复本消息（群聊需 @机器人），留言即送达孩子；\n\n"
    "4. 孩子对小智说“读留言”，即可收听未读留言，收听后自动标记已读。\n\n"
    "二、指令列表（指令需单独发送一条消息）\n\n"
    "· 查信息 9.15 —— 查看 9 月 15 日的对话总结（不填年份默认当年）\n\n"
    "· 查信息 2026.9.15 —— 查看指定日期的对话总结\n\n"
    "· 查未读 —— 查看孩子尚未收听的留言列表\n\n"
    "· 帮助 —— 显示本说明\n\n"
    "三、注意事项\n\n"
    "· 群聊中需 @机器人，消息才会被接收（企业微信平台规则）；单聊无需 @；\n\n"
    "· 除上述指令外，发送的其他文字均作为留言转达给孩子。"
)

def handle_command(text: str):
    """企微端指令。返回回复文本表示是指令已处理；返回 None 表示普通消息（作为回信入信箱）"""
    t = (text or "").strip()
    if not t:
        return None
    if t in ("@帮助", "帮助"):
        return HELP_TEXT
    m = re.match(r"^查信息\s*(\d{1,4}[.。、]\d{1,2}(?:[.。、]\d{1,2})?)\s*$", t)
    if m:
        parts = re.split(r"[.。、]", m.group(1))
        try:
            if len(parts) == 3:
                y, mo, d = int(parts[0]), int(parts[1]), int(parts[2])
            else:
                y, mo, d = datetime.now().year, int(parts[0]), int(parts[1])
            if not 1 <= mo <= 12 or not 1 <= d <= 31:
                raise ValueError
        except (ValueError, IndexError):
            return None
        date = f"{y:04d}-{mo:02d}-{d:02d}"
        s = db.get_summary(date)
        if not s or s["status"] == "empty":
            return f"📭 {date} 当天没有对话记录"
        if s["status"] != "done":
            return f"⏳ {date} 的总结还没生成好，稍后再试试"
        return f"📬 {date} 的对话总结：\n\n{s['full']}"
    # 企微专用：查孩子未读留言（不对小智设备开放）
    if t in ("未读", "查未读", "未读留言", "查未读留言", "孩子读了吗"):
        rows = db.unread_mom_messages(20)
        if not rows:
            return "📭 暂时没有未读的留言，孩子都听过啦"
        lines = [f"{r['created_at'][5:16]}：{r['content'][:80]}" for r in rows]
        return f"📬 还有 {len(rows)} 条未听过。\n\n" + "\n\n".join(lines)
    return None

def on_mom_reply(content: str, author: str = ""):
    """回信入信箱（author 为企微成员身份，如 妈妈/爸爸）"""
    db.add_message("mom", content, "wecom", author=author or "妈妈")
    log.info("回信已入信箱 [%s]: %s", author or "妈妈", content)
