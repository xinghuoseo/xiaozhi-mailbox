"""MiniMax 国内版 AI 模块：配置、连通测试、每日总结生成"""
import json, re, logging
import httpx
from . import db

log = logging.getLogger("ai")

def get_settings() -> dict:
    return db.get_ai_settings()

def save_settings(api_key: str, model: str, base_url: str):
    db.save_ai_settings(api_key.strip(), model.strip(), base_url.strip())

def chat(prompt: str, system: str = "") -> str:
    """调用 MiniMax chatcompletion_v2，返回模型回复文本"""
    s = get_settings()
    if not s["api_key"]:
        raise RuntimeError("AI 未配置，请先在 AI 设置中填写 APIKey")
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    r = httpx.post(s["base_url"],
                   headers={"Authorization": f"Bearer {s['api_key']}"},
                   json={"model": s["model"], "messages": messages, "temperature": 0.6},
                   timeout=120)
    _last_model_used = s["model"]
    if r.status_code != 200:
        raise RuntimeError(f"AI 接口返回 {r.status_code}: {r.text[:200]}")
    data = r.json()
    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError):
        raise RuntimeError(f"AI 返回格式异常: {json.dumps(data, ensure_ascii=False)[:300]}")

def test_connection() -> dict:
    """AI 设置页的连通测试"""
    try:
        reply = chat("请只回复两个字：正常")
        return {"success": True, "message": f"联通成功，AI 回复：{reply[:50]}"}
    except Exception as e:
        return {"success": False, "message": str(e)}

def _extract_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError(f"AI 未返回 JSON: {text[:200]}")
    return json.loads(m.group())

def generate_daily_summary(date_str: str) -> dict:
    """生成指定日期的总结：short(15字内) + full(完整总结)"""
    rows = db.messages_by_day(date_str)
    if not rows:
        db.upsert_summary(date_str, "", "当天没有对话记录", "empty")
        return {"status": "empty", "message": "当天没有对话记录"}
    lines = []
    for r in rows:
        who = "孩子" if r["sender"] == "child" else "妈妈"
        lines.append(f"[{r['created_at'][11:16]}] {who}{'留言' if r['sender']=='child' else '回信'}：{r['content']}")
    transcript = "\n".join(lines)
    # 提示词：优先使用控制台自定义模板（占位符 {date} {transcript}），为空用默认
    tpl = get_settings().get("summary_prompt") or db.SUMMARY_PROMPT_DEFAULT
    prompt = tpl.replace("{date}", date_str).replace("{transcript}", transcript)
    try:
        data = _extract_json(chat(prompt))
        short = (data.get("short") or "").strip()[:30]
        full = (data.get("full") or "").strip()
        if not short or not full:
            raise ValueError("AI 返回内容不完整")
        db.upsert_summary(date_str, short, full, "done")
        log.info("已生成 %s 的对话总结: %s", date_str, short)
        return {"status": "done", "short": short}
    except RuntimeError:
        raise  # AI 未配置等错误向上抛，由调用方处理
    except Exception as e:
        db.upsert_summary(date_str, "", f"总结生成失败: {e}", "failed")
        log.warning("生成 %s 总结失败: %s", date_str, e)
        return {"status": "failed", "message": str(e)}

def backfill_summaries(today: str):
    """启动/每日补跑：生成所有遗漏的每日总结（AI 未配置时静默跳过）"""
    try:
        rows = db.missing_summary_dates(before=today)
    except Exception:
        return
    for r in rows:
        try:
            generate_daily_summary(r["d"])
        except RuntimeError as e:
            log.info("补跑总结跳过（%s）", e)
            break
        except Exception as e:
            log.warning("补跑总结失败 %s: %s", r["d"], e)
