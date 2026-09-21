CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    sender      TEXT NOT NULL CHECK(sender IN ('child','mom')),
    content     TEXT NOT NULL,
    source      TEXT NOT NULL DEFAULT 'voice',
    created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    read_at     TEXT,
    device_id   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_sender_read ON messages(sender, read_at);
CREATE INDEX IF NOT EXISTS idx_day ON messages(created_at);

CREATE TABLE IF NOT EXISTS devices (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    agent_id    TEXT NOT NULL DEFAULT '',
    endpoint    TEXT NOT NULL,
    wecom_config_id INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    salt          TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS ai_settings (
    id       INTEGER PRIMARY KEY CHECK (id = 1),
    api_key  TEXT NOT NULL DEFAULT '',
    model    TEXT NOT NULL DEFAULT 'MiniMax-M3',
    base_url TEXT NOT NULL DEFAULT 'https://api.minimaxi.com/v1/text/chatcompletion_v2'
);

CREATE TABLE IF NOT EXISTS daily_summaries (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    date       TEXT NOT NULL UNIQUE,
    short      TEXT NOT NULL DEFAULT '',
    full       TEXT NOT NULL DEFAULT '',
    status     TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS wecom_configs (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    name      TEXT NOT NULL,
    mode      TEXT NOT NULL DEFAULT 'app',
    corp_id   TEXT NOT NULL DEFAULT '',
    secret    TEXT NOT NULL DEFAULT '',
    agent_id  INTEGER NOT NULL DEFAULT 0,
    token     TEXT NOT NULL DEFAULT '',
    aes_key   TEXT NOT NULL DEFAULT '',
    bot_id    TEXT NOT NULL DEFAULT '',
    bot_key   TEXT NOT NULL DEFAULT '',
    mom_user  TEXT NOT NULL DEFAULT '',
    chat_id   TEXT NOT NULL DEFAULT '',
    enabled   INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS auth_tokens (
    token    TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    expires  REAL NOT NULL                       -- unix 时间戳
);
