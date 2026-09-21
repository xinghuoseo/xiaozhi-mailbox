"""企微指令处理（智能机器人长连接模式专用）
消息处理规则：@帮助 / 查信息 日期 → 指令回复；其余一切文字 → 妈妈的回信入信箱
"""
import re, logging
from datetime import datetime
from . import db

log = logging.getLogger("wecom")

HELP_TEXT = (
    "📮 亲子信箱 · 使用帮助\n\n"
    "这是一台连接小智AI音箱的家庭信箱：孩子对着小智说话，就能给妈妈留言；妈妈在这里回信，孩子随时能听到。\n\n"
    "【怎么用】\n"
    "1. 孩子对小智说：“给妈妈留言，说……”，群里马上会收到机器人提醒；\n"
    "2. 在群里 @我 发文字（或在我的单聊里直接发，不用@），就是给孩子回信；\n"
    "3. 孩子对小智说“读一下妈妈的留言”，就能听到你写的话。\n\n"
    "【小指令】\n"
    "· 发送：查信息 9.15 —— 看 9 月 15 日那天的对话总结（不写年份就是今年）\n"
    "· 发送：查信息 2026.9.15 —— 看指定年份那天的总结\n"
    "· 发送：查未读 —— 看孩子还有几条留言没听（附内容列表）\n"
    "· 发送：@帮助 —— 显示这段说明\n\n"
    "【小提醒】\n"
    "· 在群里要 @我 我才能看到哦（企业微信的规则），单独找我聊不用@；\n"
    "· 指令要单独发一条：比如只发“查未读”三个字，如果后面还跟了别的话，就会当成给孩子的留言\n"
    "· 除了指令，发给我的其他文字都会转达给孩子。"
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
            return "日期格式没看懂哦，请这样发：查信息 9.15 或 查信息 2026.9.15"
        date = f"{y:04d}-{mo:02d}-{d:02d}"
        s = db.get_summary(date)
        if not s or s["status"] == "empty":
            return f"📭 {date} 当天没有对话记录"
        if s["status"] != "done":
            return f"⏳ {date} 的总结还没生成好，稍后再试试（也可以在控制台点\u201c总结\u201d按钮）"
        return f"📬 {date} 的对话总结：\n\n{s['full']}"
    # 企微专用：查孩子未读留言（不对小智设备开放）
    if t in ("未读", "查未读", "未读留言", "查未读留言", "孩子读了吗"):
        rows = db.unread_mom_messages(20)
        if not rows:
            return "📭 暂时没有未读的留言，孩子都听过啦"
        lines = [f"{i}. {r['content'][:80]}（{r['created_at'][5:16]}写）" for i, r in enumerate(rows, 1)]
        return f"📬 孩子还有 {len(rows)} 条留言没听过：\n\n" + "\n".join(lines) + "\n\n（孩子对小智说“读留言”就能听到）"
    return None

def on_mom_reply(content: str):
    """妈妈的回信入信箱"""
    db.add_message("mom", content, "wecom")
    log.info("妈妈回信已入信箱: %s", content)
