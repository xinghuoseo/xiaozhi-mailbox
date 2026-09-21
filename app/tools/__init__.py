from .mailbox import send_message_to_mom, read_messages_from_mom, get_unread_count

def _schema(properties: dict, required: list = None) -> dict:
    return {"type": "object", "properties": properties, "required": required or []}

REGISTRY = {
    "mailbox.send_message_to_mom": {
        "description": send_message_to_mom.__doc__.strip(),
        "schema": _schema({"content": {"type": "string", "description": "要转达给妈妈的留言原话"}},
                          ["content"]),
        "handler": send_message_to_mom,
    },
    "mailbox.read_messages_from_mom": {
        "description": read_messages_from_mom.__doc__.strip(),
        "schema": _schema({"limit": {"type": "integer", "description": "最多读几条，默认5"}}),
        "handler": read_messages_from_mom,
    },
    "mailbox.get_unread_count": {
        "description": get_unread_count.__doc__.strip(),
        "schema": _schema({}),
        "handler": get_unread_count,
    },
}
# 新增工具三步：写函数 → 注册进 REGISTRY → 重启服务
