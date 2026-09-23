from .. import db

async def send_message_to_mom(content: str, device_id: int = 0) -> dict:
    """当孩子想给妈妈留言、说心里话、发消息、转达事情时调用此工具（孩子说'给妈妈留言''给妈妈说…''给妈妈回信'都算）。content 传入孩子想说的话，尽量保留原话完整。调用后留言会立即推送到妈妈的企微群。"""
    content = (content or "").strip()
    if not content or len(content) < 2:
        return {"success": False, "result": "没有听清你要留言的内容，再说一遍好吗"}
    mid = db.add_message("child", content, "voice", device_id)
    pushed = None   # None=设备未绑定接收端（不通知）；True/False=绑定后推送结果
    try:
        from .. import wecom_bot
        device_name = "小智设备"
        config_ids = []
        if device_id:
            d = db.get_device(device_id)
            if d:
                device_name = d["name"] or device_name
                if d["wecom_config_id"]:
                    # 设备已绑定接收端 → 只走该接收端的长连接
                    config_ids = [d["wecom_config_id"]]
                    pushed = await wecom_bot.notify_child_message(content, config_ids, device_name)
    except Exception:
        pass
    if pushed:
        db.mark_child_pushed(mid)                 # 推送成功 → 标记已送达
        return {"success": True, "result": "妈妈已经收到你的留言啦，她马上就能看到哦"}
    if pushed is None:
        return {"success": True, "result": "你的留言我已经记好啦"}
    return {"success": True, "result": "你的留言我记好啦。不过妈妈那边暂时没通知到，等会儿再说一次好吗"}

def read_messages_from_mom(limit: int = 5, device_id: int = 0) -> dict:
    """当孩子想听妈妈的留言、妈妈的回信时调用（孩子说'读留言''妈妈的留言''查留言''查信箱''妈妈有没有给我留言'都算）。返回妈妈最新未读留言并自动标记已读，已读过的不会重复出现。"""
    rows = db.unread_mom_messages(min(max(limit, 1), 10))
    if not rows:
        return {"success": True, "result": "暂时没有新的留言哦"}
    texts = [f"[{r['created_at'][5:16]}][{r['author'] or '妈妈'}]：{r['content']}" for r in rows]
    db.mark_read([r["id"] for r in rows])
    return {"success": True, "result": f"共有{len(rows)}条留言。\n\n" + "\n\n".join(texts)}

def get_unread_count(device_id: int = 0) -> dict:
    """当孩子想知道妈妈有没有新留言、有几条留言时调用（孩子说'妈妈有什么吗''有几条留言'都算），只返回数量不读内容。"""
    n = db.unread_mom_count()
    if n == 0:
        return {"success": True, "result": "妈妈暂时没有新留言"}
    return {"success": True, "result": f"妈妈有{n}条新留言，你说'读留言'我就讲给你听"}
