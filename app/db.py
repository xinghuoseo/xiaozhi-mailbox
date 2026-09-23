import sqlite3
from . import config

def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    import os
    schema = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")
    with get_db() as conn:
        conn.executescript(open(schema, encoding="utf8").read())
    # 旧表迁移：messages 补 device_id 列
    cols = [r[1] for r in get_db().execute("PRAGMA table_info(messages)").fetchall()]
    if "device_id" not in cols:
        with get_db() as conn:
            conn.execute("ALTER TABLE messages ADD COLUMN device_id INTEGER NOT NULL DEFAULT 0")
    # 旧表迁移：wecom_configs 补 mode/bot_id/bot_key 列
    wcols = [r[1] for r in get_db().execute("PRAGMA table_info(wecom_configs)").fetchall()]
    for col, ddl in [("mode", "TEXT NOT NULL DEFAULT 'app'"),
                     ("bot_id", "TEXT NOT NULL DEFAULT ''"),
                     ("bot_key", "TEXT NOT NULL DEFAULT ''")]:
        if col not in wcols:
            with get_db() as conn:
                conn.execute(f"ALTER TABLE wecom_configs ADD COLUMN {col} {ddl}")
    # 旧表迁移：wecom_configs 补 auto_approve 列
    wcols = [r[1] for r in get_db().execute("PRAGMA table_info(wecom_configs)").fetchall()]
    if "auto_approve" not in wcols:
        with get_db() as conn:
            conn.execute("ALTER TABLE wecom_configs ADD COLUMN auto_approve INTEGER NOT NULL DEFAULT 0")
    # 旧表迁移：devices 补 wecom_config_id 列
    dcols = [r[1] for r in get_db().execute("PRAGMA table_info(devices)").fetchall()]
    if "wecom_config_id" not in dcols:
        with get_db() as conn:
            conn.execute("ALTER TABLE devices ADD COLUMN wecom_config_id INTEGER NOT NULL DEFAULT 0")
    # 旧表迁移：messages 补 author 列 / wecom_members 补 nickname 列
    mcols = [r[1] for r in get_db().execute("PRAGMA table_info(messages)").fetchall()]
    if "author" not in mcols:
        with get_db() as conn:
            conn.execute("ALTER TABLE messages ADD COLUMN author TEXT NOT NULL DEFAULT ''")
    nkcols = [r[1] for r in get_db().execute("PRAGMA table_info(wecom_members)").fetchall()]
    if "nickname" not in nkcols:
        with get_db() as conn:
            conn.execute("ALTER TABLE wecom_members ADD COLUMN nickname TEXT NOT NULL DEFAULT ''")
    acols = [r[1] for r in get_db().execute("PRAGMA table_info(ai_settings)").fetchall()]
    if "summary_prompt" not in acols:
        with get_db() as conn:
            conn.execute("ALTER TABLE ai_settings ADD COLUMN summary_prompt TEXT NOT NULL DEFAULT ''")
    wcols2 = [r[1] for r in get_db().execute("PRAGMA table_info(wecom_configs)").fetchall()]
    if "webhook_url" not in wcols2:
        with get_db() as conn:
            conn.execute("ALTER TABLE wecom_configs ADD COLUMN webhook_url TEXT NOT NULL DEFAULT ''")
    # 数据修正：MiniMax 新平台端点（minimaxi.com 旧端点 → minimax.cn OpenAI 兼容端点）
    with get_db() as conn:
        conn.execute("UPDATE ai_settings SET base_url='https://api.minimax.cn/v1/chat/completions' "
                     "WHERE base_url LIKE '%minimaxi.com%'")

# ---------- 设备 ----------
def list_devices():
    with get_db() as conn:
        return conn.execute("SELECT * FROM devices ORDER BY id").fetchall()

def get_device(device_id: int):
    with get_db() as conn:
        return conn.execute("SELECT * FROM devices WHERE id=?", (device_id,)).fetchone()

def add_device(name: str, agent_id: str, endpoint: str, wecom_config_id: int = 0) -> int:
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO devices(name, agent_id, endpoint, wecom_config_id) VALUES(?,?,?,?)",
            (name, agent_id, endpoint, wecom_config_id))
        return cur.lastrowid

def update_device(device_id: int, name: str, endpoint: str, agent_id: str = None,
                  wecom_config_id: int = None):
    with get_db() as conn:
        if agent_id is None:
            if wecom_config_id is None:
                conn.execute("UPDATE devices SET name=?, endpoint=? WHERE id=?",
                             (name, endpoint, device_id))
            else:
                conn.execute("UPDATE devices SET name=?, endpoint=?, wecom_config_id=? WHERE id=?",
                             (name, endpoint, wecom_config_id, device_id))
        elif wecom_config_id is None:
            conn.execute("UPDATE devices SET name=?, endpoint=?, agent_id=? WHERE id=?",
                         (name, endpoint, agent_id, device_id))
        else:
            conn.execute("UPDATE devices SET name=?, endpoint=?, agent_id=?, wecom_config_id=? WHERE id=?",
                         (name, endpoint, agent_id, wecom_config_id, device_id))

def delete_device(device_id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM devices WHERE id=?", (device_id,))

# ---------- 留言 ----------
def add_message(sender: str, content: str, source: str, device_id: int = 0, author: str = "") -> int:
    if not author:
        author = "妈妈" if sender == "mom" else ""
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO messages(sender, content, source, device_id, author) VALUES(?,?,?,?,?)",
            (sender, content.strip(), source, device_id, author))
        return cur.lastrowid

def unread_mom_messages(limit: int = 5):
    with get_db() as conn:
        return conn.execute(
            "SELECT id, content, created_at, author FROM messages "
            "WHERE sender='mom' AND read_at IS NULL ORDER BY id ASC LIMIT ?",
            (limit,)).fetchall()

def mark_read(ids: list):
    if not ids:
        return
    with get_db() as conn:
        conn.execute(
            "UPDATE messages SET read_at=datetime('now','localtime') "
            "WHERE sender='mom' AND read_at IS NULL AND id IN (%s)" % ",".join("?" * len(ids)), ids)

def mark_child_pushed(message_id: int):
    """孩子留言推送企微成功 → 标记已送达"""
    with get_db() as conn:
        conn.execute("UPDATE messages SET read_at=datetime('now','localtime') WHERE id=?",
                     (message_id,))

def unread_mom_count() -> int:
    with get_db() as conn:
        return conn.execute(
            "SELECT COUNT(*) c FROM messages WHERE sender='mom' AND read_at IS NULL").fetchone()["c"]

def day_stats(limit: int = 90):
    """按天聚合：日期、对话总条数"""
    with get_db() as conn:
        return conn.execute(
            "SELECT date(created_at) d, COUNT(*) c FROM messages "
            "GROUP BY date(created_at) ORDER BY d DESC LIMIT ?", (limit,)).fetchall()

def messages_by_day(date_str: str):
    with get_db() as conn:
        return conn.execute(
            "SELECT sender, content, created_at, source, read_at, author FROM messages "
            "WHERE date(created_at)=? ORDER BY id", (date_str,)).fetchall()

# ---------- 每日总结 ----------
def get_summary(date_str: str):
    with get_db() as conn:
        return conn.execute("SELECT * FROM daily_summaries WHERE date=?", (date_str,)).fetchone()

def upsert_summary(date_str: str, short: str, full: str, status: str):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO daily_summaries(date, short, full, status) VALUES(?,?,?,?) "
            "ON CONFLICT(date) DO UPDATE SET short=excluded.short, full=excluded.full, "
            "status=excluded.status, created_at=datetime('now','localtime')",
            (date_str, short, full, status))

def missing_summary_dates(before: str):
    """有对话记录但还没有成功生成总结的日期（before 之前的）"""
    with get_db() as conn:
        return conn.execute(
            "SELECT DISTINCT date(created_at) d FROM messages "
            "WHERE date(created_at) < ? AND date(created_at) NOT IN "
            "(SELECT date FROM daily_summaries WHERE status='done') "
            "ORDER BY d DESC LIMIT 30", (before,)).fetchall()

# ---------- 用户 ----------
def user_count() -> int:
    with get_db() as conn:
        return conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]

def get_user(username: str):
    with get_db() as conn:
        return conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()

def add_user(username: str, password_hash: str, salt: str):
    with get_db() as conn:
        conn.execute("INSERT INTO users(username, password_hash, salt) VALUES(?,?,?)",
                     (username, password_hash, salt))

def update_password(username: str, password_hash: str, salt: str):
    with get_db() as conn:
        conn.execute("UPDATE users SET password_hash=?, salt=? WHERE username=?",
                     (password_hash, salt, username))

# ---------- AI 配置 ----------
DEFAULT_AI = {"api_key": "", "model": "MiniMax-M3",
              "base_url": "https://api.minimax.cn/v1/chat/completions"}

SUMMARY_PROMPT_DEFAULT = "请为下面这一天（{date}）孩子和妈妈之间的留言对话生成当日总结，语气温馨。"

def get_ai_settings() -> dict:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM ai_settings WHERE id=1").fetchone()
    if not row:
        s = dict(DEFAULT_AI); s["summary_prompt"] = ""
        return s
    return {"api_key": row["api_key"], "model": row["model"], "base_url": row["base_url"],
            "summary_prompt": row["summary_prompt"] or ""}

def save_ai_settings(api_key: str, model: str, base_url: str, summary_prompt: str = None):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO ai_settings(id, api_key, model, base_url) VALUES(1,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET api_key=excluded.api_key, model=excluded.model, "
            "base_url=excluded.base_url", (api_key, model, base_url))
        if summary_prompt is not None:
            conn.execute("UPDATE ai_settings SET summary_prompt=? WHERE id=1", (summary_prompt,))

# ---------- 企业微信配置 ----------
def list_wecom_configs():
    with get_db() as conn:
        return conn.execute("SELECT * FROM wecom_configs ORDER BY id").fetchall()

def list_wecom_enabled():
    with get_db() as conn:
        return conn.execute("SELECT * FROM wecom_configs WHERE enabled=1").fetchall()

def get_wecom(config_id: int):
    with get_db() as conn:
        return conn.execute("SELECT * FROM wecom_configs WHERE id=?", (config_id,)).fetchone()

def add_wecom(name: str, bot_id: str, bot_key: str) -> int:
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO wecom_configs(name, mode, bot_id, bot_key) VALUES(?,?,?,?)",
            (name, "bot", bot_id, bot_key))
        return cur.lastrowid

def update_wecom(config_id: int, name: str, bot_id: str, bot_key: str):
    with get_db() as conn:
        conn.execute("UPDATE wecom_configs SET name=?, bot_id=?, bot_key=? WHERE id=?",
                     (name, bot_id, bot_key, config_id))

def set_wecom_auto_approve(config_id: int, auto: int):
    with get_db() as conn:
        conn.execute("UPDATE wecom_configs SET auto_approve=? WHERE id=?", (auto, config_id))

def update_wecom_user(config_id: int, mom_user: str):
    with get_db() as conn:
        conn.execute("UPDATE wecom_configs SET mom_user=? WHERE id=?", (mom_user, config_id))

def update_wecom_chatid(config_id: int, chat_id: str):
    with get_db() as conn:
        conn.execute("UPDATE wecom_configs SET chat_id=? WHERE id=?", (chat_id, config_id))

def delete_wecom(config_id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM wecom_configs WHERE id=?", (config_id,))

# ---------- 登录令牌（持久化，重启不失效） ----------
def save_token(token: str, username: str, expires: float):
    with get_db() as conn:
        conn.execute("INSERT OR REPLACE INTO auth_tokens(token, username, expires) VALUES(?,?,?)",
                     (token, username, expires))

def get_token(token: str):
    with get_db() as conn:
        return conn.execute("SELECT * FROM auth_tokens WHERE token=?", (token,)).fetchone()

def delete_token(token: str):
    with get_db() as conn:
        conn.execute("DELETE FROM auth_tokens WHERE token=?", (token,))

def delete_user_tokens(username: str):
    with get_db() as conn:
        conn.execute("DELETE FROM auth_tokens WHERE username=?", (username,))

def purge_expired_tokens(now: float):
    with get_db() as conn:
        conn.execute("DELETE FROM auth_tokens WHERE expires < ?", (now,))


# ---------- 企微成员名单 ----------
def get_wecom_member(config_id: int, userid: str):
    with get_db() as conn:
        return conn.execute("SELECT * FROM wecom_members WHERE config_id=? AND userid=?",
                            (config_id, userid)).fetchone()

def has_approved_member(config_id: int) -> bool:
    with get_db() as conn:
        return conn.execute("SELECT 1 FROM wecom_members WHERE config_id=? AND status='approved' LIMIT 1",
                            (config_id,)).fetchone() is not None

def add_wecom_member(config_id: int, userid: str, status: str) -> bool:
    """新增成员，返回是否为新插入"""
    with get_db() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO wecom_members(config_id, userid, status) VALUES(?,?,?)",
            (config_id, userid, status))
        return cur.rowcount > 0

def set_wecom_member_nickname(member_id: int, nickname: str):
    with get_db() as conn:
        conn.execute("UPDATE wecom_members SET nickname=? WHERE id=?", (nickname.strip(), member_id))

def set_wecom_member_status(member_id: int, status: str):
    with get_db() as conn:
        conn.execute("UPDATE wecom_members SET status=?, decided_at=datetime('now','localtime') WHERE id=?",
                     (status, member_id))

def delete_wecom_member(member_id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM wecom_members WHERE id=?", (member_id,))

def list_wecom_members(config_id: int = None):
    with get_db() as conn:
        if config_id:
            return conn.execute("SELECT * FROM wecom_members WHERE config_id=? ORDER BY id DESC",
                                (config_id,)).fetchall()
        return conn.execute("SELECT * FROM wecom_members ORDER BY id DESC").fetchall()
