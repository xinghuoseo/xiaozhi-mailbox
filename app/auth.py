import secrets, hashlib, logging, time
from . import db

log = logging.getLogger("auth")
TOKEN_TTL = 15 * 24 * 3600   # 登录态 15 天（持久化到数据库，重启/刷新页面都不失效）

def hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100000).hex()

def ensure_default_user():
    """首次启动创建默认账号 admin / xiaozhi123"""
    if db.user_count() == 0:
        salt = secrets.token_hex(8)
        db.add_user("admin", hash_password("xiaozhi123", salt), salt)
        log.info("已创建默认账号 admin / xiaozhi123，请登录后立即修改密码")

def reset_password(username: str, new_password: str):
    """管理员重置密码（服务器端操作用）"""
    salt = secrets.token_hex(8)
    db.update_password(username, hash_password(new_password, salt), salt)
    log.info("账号 %s 密码已重置", username)

def login(username: str, password: str):
    row = db.get_user(username)
    if not row or hash_password(password, row["salt"]) != row["password_hash"]:
        return None
    token = secrets.token_hex(24)
    db.save_token(token, username, time.time() + TOKEN_TTL)
    db.purge_expired_tokens(time.time())
    return token

def verify(token: str) -> bool:
    """token 是否有效（15 天内且未登出），持久化在数据库中"""
    if not token:
        return False
    row = db.get_token(token)
    if not row:
        return False
    if time.time() > row["expires"]:
        db.delete_token(token)
        return False
    return True

def username_of(token: str) -> str:
    if not verify(token):
        return ""
    row = db.get_token(token)
    return row["username"] if row else ""

def logout(token: str):
    db.delete_token(token)

def change_password(token: str, old_password: str, new_password: str):
    """校验旧密码后修改，并吊销该用户所有旧登录态"""
    username = username_of(token)
    if not username:
        return False, "登录已过期"
    row = db.get_user(username)
    if not row or hash_password(old_password, row["salt"]) != row["password_hash"]:
        return False, "旧密码错误"
    if len(new_password) < 6:
        return False, "新密码至少 6 位"
    salt = secrets.token_hex(8)
    db.update_password(username, hash_password(new_password, salt), salt)
    db.delete_user_tokens(username)   # 改密后所有旧登录态失效
    return True, "密码已修改，请重新登录"
