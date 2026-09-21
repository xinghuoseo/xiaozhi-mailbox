import os
from dotenv import load_dotenv

load_dotenv()

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 项目根

# ---- 小智 ----
MCP_ENDPOINT = os.getenv("MCP_ENDPOINT", "")            # wss://... 接入点（devices 表为空时自动导入）

# ---- 通用 ----
DB_PATH = os.getenv("DB_PATH", os.path.join(_BASE_DIR, "mailbox.db"))

ENV_PATH = os.path.join(_BASE_DIR, ".env")

def update_env(key: str, value: str):
    """更新 .env 中的配置项并刷新内存值（运行时改配置用）"""
    lines = []
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, encoding="utf8") as f:
            lines = f.readlines()
    for i, line in enumerate(lines):
        if line.strip().startswith(f"{key}="):
            lines[i] = f"{key}={value}\n"
            break
    else:
        lines.append(f"{key}={value}\n")
    with open(ENV_PATH, "w", encoding="utf8") as f:
        f.writelines(lines)
    os.chmod(ENV_PATH, 0o600)
    globals()[key] = value
