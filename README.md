# 小智留言系统 · 小智亲子伴侣

> 让孩子对小智AI音箱说一句话，就能给妈妈留言；妈妈在企业微信里回一句，孩子随时能听到。

基于 **小智 AI MCP 协议** 与 **企业微信智能机器人** 的家庭留言信箱系统。

## 功能特性

- 🎙️ **语音留言**：孩子对小智说“给妈妈留言，说……”，留言立即入库并推送到妈妈的企微群
- 📮 **语音读信**：妈妈在企业微信回信，孩子对小智说“读留言”即可听到最新未读留言，读完自动标记已读
- 🤖 **企微智能机器人**（官方 SDK 长连接）：无需公网回调地址与白名单，留言秒推群、群里 @机器人 即回信
- 📊 **AI 每日总结**：每天 00:05 自动调用 MiniMax 生成当日对话总结（15 字短总结 + 完整总结），支持手动生成与补跑
- 📱 **Web 控制台**：账号登录（15 天免登录），设备管理 / 对话记录 / AI 设置 / 企微配置 四个导航
- 🔌 **多设备 + 多机器人**：多台小智设备可绑定不同的企微机器人，互不干扰
- 💬 **企微小指令**：`查信息 9.15` 查历史总结、`查未读` 看孩子没听的留言、`@帮助` 看使用说明

## 系统架构

```
孩子说话 → 小智设备 → 小智云端(ASR+LLM+TTS)
                          │ LLM 决定调用工具（MCP 协议）
                          ▼
          MCP 接入点 wss://api.xiaozhi.me/mcp/?token=...
                          ▲ 本服务主动反向连接（JSON-RPC 2.0）
                          │
              ┌───────────┴───────────┐
              │   亲子信箱服务 (本仓库)  │
              │  · MCP 工具：留言/读信   │
              │  · 企微机器人长连接      │──── 企业微信（群通知 + 回信）
              │  · Web 控制台           │
              │  · MiniMax 每日总结     │
              └───────────┬───────────┘
                          ▼
                    SQLite（留言/设备/总结）
```

## 快速开始

### 环境要求

- Python 3.10+
- 一台 [xiaozhi.me](https://xiaozhi.me) 智能体的 MCP 接入点（控制台 → 智能体配置页右下角）
- 企业微信 + 一个「智能机器人」（API 模式 → 使用长连接，获取 Bot ID 和 Secret）

### 安装

```bash
git clone https://github.com/xinghuoseo/xiaozhi-mailbox.git
cd xiaozhi-mailbox
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

### 配置

创建 `.env`（参考下方说明填写）：

```ini
MCP_ENDPOINT=wss://api.xiaozhi.me/mcp/?token=你的接入点token
DB_PATH=/path/to/mailbox.db
```

### 运行

```bash
venv/bin/uvicorn main:app --host 127.0.0.1 --port 8300
```

浏览器打开 `http://127.0.0.1:8300`，默认账号 `admin / xiaozhi123`（**登录后立即修改密码**）。

### 使用流程

1. 控制台 → **设备** → 添加设备（粘贴小智 MCP 接入点），状态变绿点即连接成功；
2. 控制台 → **企微配置** → 添加配置（填入 Bot ID / Secret），点“连通”验证 → 把机器人拉进家庭群，群里 @它 发条消息自动记录群会话；
3. 对小智说 **“给妈妈留言，说……”** → 群里秒收提醒；
4. 妈妈在群里 **@机器人** 回文字（或机器人单聊直接发，不用 @）→ 孩子对小智说 **“读留言”**；
5. 控制台 → **AI 设置** → 填入 MiniMax APIKey → 每天自动生成对话总结。

## 企微端指令（仅企微可用，设备端不开放）

| 指令 | 说明 |
|---|---|
| `查信息 9.15` | 查看 9 月 15 日的对话总结（不写年份默认当年） |
| `查未读` | 查看孩子还没听过的留言列表 |
| `@帮助` | 查看使用说明 |

> 指令必须**单独发一条**消息；后面跟了其他字会被当作给孩子的留言。
> 群聊里机器人只能收到 @ 它的消息（企微官方规则）；机器人单聊不需要 @。

## MCP 工具（对小智设备开放）

| 工具 | 触发话术 | 说明 |
|---|---|---|
| `mailbox.send_message_to_mom` | “给妈妈留言，说……” | 留言入库 + 推送企微群，成功标记已送达 |
| `mailbox.read_messages_from_mom` | “读留言”“妈妈的留言”“查信箱” | 读取未读留言并标记已读，按时间正序朗读 |
| `mailbox.get_unread_count` | “妈妈有什么吗”“有几条留言” | 只返回未读数量 |

新增工具：在 `app/tools/` 写函数（返回 `{"success": bool, "result": "适合朗读的中文短句"}`）→ 注册进 `app/tools/__init__.py` 的 `REGISTRY` → 重启。

## 部署（宝塔面板）

- Python 项目管理器：启动命令 `venv/bin/uvicorn main:app --host 127.0.0.1 --port 8300`
- Nginx 反向代理 `127.0.0.1:8300`（建议 HTTPS）
- `.env` 权限 600，`mailbox.db` 已启用 WAL

## 目录结构

```
├── main.py              # 入口：lifespan + 服务
├── app/
│   ├── config.py        # 配置（.env + 运行时更新）
│   ├── db.py / schema.sql
│   ├── auth.py          # 登录鉴权（15 天持久化 token）
│   ├── ai.py            # MiniMax 调用与每日总结
│   ├── scheduler.py     # 定时总结任务
│   ├── wecom.py         # 企微指令处理（查信息/查未读/帮助）
│   ├── wecom_bot.py     # 企微智能机器人长连接（官方 SDK）
│   ├── mcp/             # 小智 MCP 客户端与多设备管理
│   ├── tools/           # MCP 工具注册表
│   └── api/             # 控制台 API
└── static/index.html    # 前端单页
```

## 安全说明

- `.env`（MCP 接入点 token）与数据库**永不入库** git（已配置 .gitignore）
- MCP 接入点 token 等同密钥，泄露后请在 xiaozhi.me 控制台重新生成
- 登录密码 PBKDF2-SHA256 加盐存储；企微机器人 Secret 在控制台以掩码显示

## 技术栈

FastAPI · Uvicorn · WebSocket（小智 MCP / 企微长连接）· wecom-aibot-sdk · SQLite(WAL) · MiniMax · 原生 JS 单页前端
