import json
import os
import re
import threading
import uuid
from datetime import date, timedelta

import requests
from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify, session, redirect, url_for

load_dotenv(override=True)

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "vocab-dashboard-secret-key-2024")

# 登录密码
SITE_PASSWORD = os.environ.get("SITE_PASSWORD", "cxj200524")

WORDS_FILE = os.path.join(os.environ.get("DATA_DIR", os.path.dirname(os.path.abspath(__file__))), "words.json")

# 首次部署时，将仓库中的初始数据迁移到持久化目录
_seed_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "words.json")
if WORDS_FILE != _seed_file and not os.path.exists(WORDS_FILE):
    import shutil
    if os.path.exists(_seed_file):
        shutil.copy2(_seed_file, WORDS_FILE)
API_BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "https://api.deepseek.com").rstrip("/")
if API_BASE_URL.endswith("/v1"):
    API_URL = f"{API_BASE_URL}/chat/completions"
else:
    API_URL = f"{API_BASE_URL}/v1/chat/completions"
API_MODEL = os.environ.get("ANTHROPIC_MODEL", "deepseek-chat")
API_KEY = os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY") or ""

file_lock = threading.Lock()

# 间隔重复：晋升到各阶段后的复习间隔（天）
REVIEW_INTERVALS = [1, 3, 7]  # stage 1 → 1天, stage 2 → 3天, stage 3 → 7天

SYSTEM_PROMPT = """你是一个专业的考研英语词典编纂专家。用户会给你一个英文单词，请返回严格的 JSON 格式（不要包含 markdown 代码块标记），包含以下字段：
- word: 单词原形
- phonetic: 英式音标，如 /ˈpærədaɪm/
- definition: 核心词性 + 精炼中文释义，控制在20字以内
- sentence: 一句考研难度级别的英语例句，体现该词在学术语境中的典型用法
- translation: 该例句的准确中文翻译
- variations: 该单词的常见变形（派生词），以数组返回，每个元素含 form(变形词)、pos(词性缩写)、meaning(中文释义)，最多3个；无常见变形时返回空数组 []
- phrases: 该单词的1-2个常见短语搭配，以数组返回，每个元素含 phrase(短语)、meaning(中文释义)；无常见短语时返回空数组 []

只返回纯 JSON 对象，不要有任何额外文字。确保 JSON 是有效的、可被程序直接解析的。"""


def load_words():
    """读取本地单词 JSON 文件，自动迁移旧版字段。"""
    try:
        with open(WORDS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = {"words": []}
    if "words" not in data:
        data["words"] = []

    today_str = date.today().isoformat()
    changed = False
    for w in data["words"]:
        if "id" not in w:
            w["id"] = str(uuid.uuid4())
            changed = True
        if "review_date" not in w:
            w["review_date"] = today_str
            changed = True
        if "mastery_stage" not in w:
            old_status = w.pop("status", "")
            w["mastery_stage"] = 1 if old_status == "已熟记" else 0
            changed = True
        else:
            w.pop("status", None)
        if "type" not in w:
            w["type"] = "phrase" if " " in w.get("word", "") else "word"
            changed = True

    if changed:
        _write_words(data)

    return data


def _write_words(data):
    """写入单词文件（不加锁，调用者负责持锁）。"""
    with open(WORDS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def save_words(data):
    """线程安全写入（带锁）。用于 load_words 自动迁移后回写。"""
    with file_lock:
        _write_words(data)


def _extract_json(text):
    """从 AI 返回文本中提取 JSON 对象（支持嵌套）。"""
    cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip())
    cleaned = re.sub(r"\s*```$", "", cleaned)
    cleaned = cleaned.strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    start = cleaned.find("{")
    if start == -1:
        raise ValueError("AI 返回内容中没有找到 JSON 对象")

    depth = 0
    for i in range(start, len(cleaned)):
        ch = cleaned[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(cleaned[start:i + 1])

    raise ValueError("AI 返回的 JSON 大括号不匹配")


def _next_review_date(stage):
    """根据晋升后的阶段计算下次复习日期。"""
    if stage == 0:
        return date.today().isoformat()
    idx = stage - 1
    if idx < len(REVIEW_INTERVALS):
        return (date.today() + timedelta(days=REVIEW_INTERVALS[idx])).isoformat()
    return None  # stage 3+ 无需再复习


def call_deepseek(word):
    """调用 AI API 查词，返回解析后的单词数据字典。"""
    if not API_KEY:
        raise RuntimeError("未设置 ANTHROPIC_AUTH_TOKEN 或 ANTHROPIC_API_KEY")

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "x-api-key": API_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "model": API_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"请查词：{word}"},
        ],
        "temperature": 0.3,
        "max_tokens": 600,
    }

    resp = requests.post(API_URL, headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
    body = resp.json()
    raw = body["choices"][0]["message"]["content"].strip()

    parsed = _extract_json(raw)

    for field in ("word", "phonetic", "definition", "sentence", "translation"):
        parsed.setdefault(field, "")
    parsed.setdefault("variations", [])
    parsed.setdefault("phrases", [])
    parsed["mastery_stage"] = 0
    parsed["review_date"] = date.today().isoformat()
    parsed["id"] = str(uuid.uuid4())
    return parsed


def placeholder_lookup(word):
    """无 AI 时的占位卡片。"""
    clean = word.strip()
    return {
        "id": str(uuid.uuid4()),
        "word": clean.lower(),
        "phonetic": "",
        "definition": "（待完善 — 请手动编辑或配置 AI Key）",
        "sentence": "",
        "translation": "",
        "variations": [],
        "phrases": [],
        "mastery_stage": 0,
        "review_date": date.today().isoformat(),
        "type": "phrase" if " " in clean else "word",
    }


def check_api_connection():
    """启动时检测 AI API 连通性。"""
    if not API_KEY:
        return False, "未设置 ANTHROPIC_AUTH_TOKEN 或 ANTHROPIC_API_KEY，请在 .env 中配置"
    try:
        headers = {
            "Authorization": f"Bearer {API_KEY}",
            "x-api-key": API_KEY,
            "Content-Type": "application/json",
        }
        payload = {
            "model": API_MODEL,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
        }
        resp = requests.post(API_URL, headers=headers, json=payload, timeout=10)
        if resp.status_code == 401:
            return False, f"API 认证失败 (401) — 请检查 ANTHROPIC_AUTH_TOKEN"
        if resp.status_code == 404:
            return False, f"API 端点不存在 (404) — 请确认模型名称 '{API_MODEL}'"
        if not resp.ok:
            return False, f"API 返回 {resp.status_code}: {resp.text[:200]}"
        return True, "AI API 连接正常"
    except requests.exceptions.ConnectionError:
        return False, f"无法连接到 {API_URL} — 请确认本地代理已启动"
    except requests.exceptions.Timeout:
        return False, f"连接 {API_URL} 超时"
    except Exception as e:
        return False, f"未知错误: {e}"


# ---------------------------------------------------------------------------
# 登录认证
# ---------------------------------------------------------------------------

@app.before_request
def require_login():
    """除登录页外，所有请求需验证密码。"""
    if request.path == "/login" or request.path.startswith("/static"):
        return None
    if "logged_in" not in session:
        if request.path.startswith("/api/"):
            return jsonify({"error": "未登录"}), 401
        return redirect(url_for("login_page"))


@app.route("/login", methods=["GET", "POST"])
def login_page():
    error = ""
    if request.method == "POST":
        pwd = request.form.get("password", "")
        if pwd == SITE_PASSWORD:
            session["logged_in"] = True
            return redirect(url_for("index"))
        error = "密码错误，请重试"
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login_page"))


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/words", methods=["GET"])
def api_get_words():
    data = load_words()
    filter_type = request.args.get("filter", "all")
    today_str = date.today().isoformat()

    words = data["words"]
    if filter_type == "due":
        words = [w for w in words
                 if w.get("review_date", "") <= today_str and w.get("mastery_stage", 0) < 3]

    return jsonify(words)


@app.route("/api/words", methods=["POST"])
def api_add_word():
    body = request.get_json(silent=True) or {}
    raw_word = (body.get("word") or "").strip()
    if not raw_word:
        return jsonify({"error": "单词不能为空"}), 400

    with file_lock:
        data = load_words()
        for w in data["words"]:
            if w["word"].lower() == raw_word.lower():
                return jsonify({"error": f"单词「{raw_word}」已存在"}), 409

        try:
            word_data = call_deepseek(raw_word)
        except Exception:
            word_data = placeholder_lookup(raw_word)

        word_data["type"] = "phrase" if " " in raw_word else "word"
        data["words"].append(word_data)
        _write_words(data)

    return jsonify(word_data), 201


@app.route("/api/words/batch", methods=["POST"])
def api_batch_add():
    """批量导入单词列表。"""
    body = request.get_json(silent=True) or {}
    raw_words = body.get("words", [])
    if not raw_words:
        return jsonify({"error": "单词列表不能为空"}), 400

    results = []
    with file_lock:
        data = load_words()
        existing = {w["word"].lower() for w in data["words"]}

        for raw in raw_words:
            word = raw.strip()
            if not word:
                continue
            if word.lower() in existing:
                results.append({"word": word, "status": "skipped", "reason": "已存在"})
                continue

            try:
                wd = call_deepseek(word)
            except Exception:
                wd = placeholder_lookup(word)

            wd["type"] = "phrase" if " " in word else "word"
            data["words"].append(wd)
            existing.add(word.lower())
            results.append({"word": word, "status": "added", "data": wd})

        _write_words(data)

    added = sum(1 for r in results if r["status"] == "added")
    return jsonify({"results": results, "added": added, "skipped": len(results) - added})


@app.route("/api/words/<word_id>", methods=["PUT"])
def api_update_word(word_id):
    body = request.get_json(silent=True) or {}

    with file_lock:
        data = load_words()
        word_entry = None
        for w in data["words"]:
            if w.get("id") == word_id:
                word_entry = w
                break

        if word_entry is None:
            return jsonify({"error": "单词不存在"}), 404

        if "mastery_stage" in body:
            stage = int(body["mastery_stage"])
            if 0 <= stage <= 3:
                word_entry["mastery_stage"] = stage
                new_due = _next_review_date(stage)
                if new_due:
                    word_entry["review_date"] = new_due

        for field in ("word", "phonetic", "definition", "sentence", "translation"):
            if field in body and body[field]:
                word_entry[field] = body[field]

        _write_words(data)

    return jsonify(word_entry)


@app.route("/api/words/<word_id>", methods=["DELETE"])
def api_delete_word(word_id):
    with file_lock:
        data = load_words()
        for i, w in enumerate(data["words"]):
            if w.get("id") == word_id:
                removed = data["words"].pop(i)
                _write_words(data)
                return jsonify({"deleted": removed["word"], "id": word_id})

    return jsonify({"error": "单词不存在"}), 404


@app.route("/api/words/<word_id>/enrich", methods=["POST"])
def api_enrich_word(word_id):
    """为已有单词重新调用 AI 补充变形和短语。"""
    with file_lock:
        data = load_words()
        word_entry = None
        for w in data["words"]:
            if w.get("id") == word_id:
                word_entry = w
                break

        if word_entry is None:
            return jsonify({"error": "单词不存在"}), 404

        raw_word = word_entry["word"]

        try:
            enriched = call_deepseek(raw_word)
        except Exception as e:
            msg = str(e)
            if "401" in msg:
                hint = " — AI 令牌无效，请检查 .env 中的 ANTHROPIC_AUTH_TOKEN"
            elif "Connection" in msg:
                hint = " — 无法连接 AI 服务，请确认本地代理已启动"
            else:
                hint = ""
            return jsonify({"error": f"AI 充实失败：{e}{hint}"}), 502

        for key in ("word", "phonetic", "definition", "sentence", "translation", "variations", "phrases"):
            if key in enriched:
                word_entry[key] = enriched[key]
        word_entry["type"] = "phrase" if " " in raw_word else "word"

        _write_words(data)

    return jsonify(word_entry)


@app.route("/api/ai-check", methods=["GET"])
def api_ai_check():
    ok, msg = check_api_connection()
    return jsonify({"ok": ok, "message": msg, "config": {
        "base_url": API_BASE_URL,
        "api_url": API_URL,
        "model": API_MODEL,
        "has_key": bool(API_KEY),
    }})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    print("=" * 56)
    print("  考研英语智能极简词典  /  Kaoyan Smart Vocab Dashboard")
    print("=" * 56)
    print(f"  Words file : {WORDS_FILE}")
    print(f"  API URL   : {API_URL}")
    print(f"  API Model : {API_MODEL}")
    print(f"  API Key   : {'[OK]' if API_KEY else '[MISSING] — placeholder mode'}")
    print(f"  访问地址  : http://0.0.0.0:{port}")
    print("-" * 56)
    ok, msg = check_api_connection()
    if ok:
        print(f"  AI 状态   : [OK] {msg}")
    else:
        print(f"  AI 状态   : [FAIL] {msg}")
        print("  ")
        print("  解决方法：")
        print("    1. 打开你的 AI 代理管理面板（通常是 http://localhost:3000/）")
        print("    2. 创建一个 API 令牌 (Token / API Key)")
        print("    3. 将令牌写入 .env 的 ANTHROPIC_AUTH_TOKEN=你的令牌")
        print("    4. 重新启动本程序")
    print("=" * 56)
    app.run(debug=debug, host="0.0.0.0", port=port)
