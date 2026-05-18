import json
import os
import re
import threading

import requests
from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify

load_dotenv(override=True)

app = Flask(__name__)

WORDS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "words.json")
API_BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "https://api.deepseek.com").rstrip("/")
# 避免 /v1 重复拼接
if API_BASE_URL.endswith("/v1"):
    API_URL = f"{API_BASE_URL}/chat/completions"
else:
    API_URL = f"{API_BASE_URL}/v1/chat/completions"
API_MODEL = os.environ.get("ANTHROPIC_MODEL", "deepseek-chat")
API_KEY = os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY") or ""

file_lock = threading.Lock()

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
    """读取本地单词 JSON 文件，自动迁移旧版 status 字段为 mastery_stage。"""
    try:
        with open(WORDS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = {"words": []}
    if "words" not in data:
        data["words"] = []

    # 自动迁移: 旧版 'status' → 新版 'mastery_stage' (0-3)
    # 自动检测 type 字段 (含空格则为 phrase)
    changed = False
    for w in data["words"]:
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
        save_words(data)

    return data


def save_words(data):
    """线程安全地写入单词 JSON 文件。"""
    with file_lock:
        with open(WORDS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


def check_api_connection():
    """启动时检测 AI API 连通性，返回 (ok, message)。"""
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
            return False, f"API 认证失败 (401) — .env 中的 ANTHROPIC_AUTH_TOKEN 无效，请检查本地代理 {API_BASE_URL} 的令牌是否正确"
        if resp.status_code == 404:
            return False, f"API 端点不存在 (404) — 请确认模型名称 '{API_MODEL}' 在代理 {API_BASE_URL} 中已配置"
        if not resp.ok:
            return False, f"API 返回 {resp.status_code}: {resp.text[:200]}"
        return True, "AI API 连接正常"
    except requests.exceptions.ConnectionError:
        return False, f"无法连接到 {API_URL} — 请确认本地代理已启动 (端口 {API_BASE_URL.split(':')[-1] if ':' in API_BASE_URL else '?'})"
    except requests.exceptions.Timeout:
        return False, f"连接 {API_URL} 超时"
    except Exception as e:
        return False, f"未知错误: {e}"


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

    # 清理可能的 markdown 代码块包裹
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    cleaned = cleaned.strip()

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        # 尝试从文本中提取 JSON 对象
        match = re.search(r"\{[^{}]*\}", cleaned, re.DOTALL)
        if match:
            parsed = json.loads(match.group(0))
        else:
            raise ValueError(f"DeepSeek 返回内容无法解析为 JSON：{raw[:200]}")

    required = ["word", "phonetic", "definition", "sentence", "translation"]
    for field in required:
        if field not in parsed:
            parsed[field] = ""
    parsed.setdefault("variations", [])
    parsed.setdefault("phrases", [])
    parsed["mastery_stage"] = 0
    return parsed


def placeholder_lookup(word):
    """无 AI 时的占位查词，返回可手动填充的空白卡片。"""
    clean = word.strip()
    return {
        "word": clean.lower(),
        "phonetic": "",
        "definition": "（待完善 — 请手动编辑或配置 AI Key）",
        "sentence": "",
        "translation": "",
        "variations": [],
        "phrases": [],
        "mastery_stage": 0,
        "type": "phrase" if " " in clean else "word",
    }


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/words", methods=["GET"])
def api_get_words():
    data = load_words()
    return jsonify(data["words"])


@app.route("/api/words", methods=["POST"])
def api_add_word():
    body = request.get_json(silent=True) or {}
    raw_word = (body.get("word") or "").strip()
    if not raw_word:
        return jsonify({"error": "单词不能为空"}), 400

    # 检查是否已存在
    data = load_words()
    for w in data["words"]:
        if w["word"].lower() == raw_word.lower():
            return jsonify({"error": f"单词「{raw_word}」已存在"}), 409

    # 尝试 AI 查词，失败则使用占位
    try:
        word_data = call_deepseek(raw_word)
        word_data["type"] = "phrase" if " " in raw_word.strip() else "word"
    except Exception as e:
        err_msg = str(e)
        if "401" in err_msg:
            print(f"[AI 查词失败] 认证失败，请检查 .env 中 ANTHROPIC_AUTH_TOKEN 是否正确: {e}")
        else:
            print(f"[AI 查词失败] {e}")
        word_data = placeholder_lookup(raw_word)

    data["words"].append(word_data)
    save_words(data)
    return jsonify(word_data), 201


@app.route("/api/words/<int:index>", methods=["PUT"])
def api_update_word(index):
    body = request.get_json(silent=True) or {}
    data = load_words()
    if index < 0 or index >= len(data["words"]):
        return jsonify({"error": "索引越界"}), 404

    # 支持更新 mastery_stage
    if "mastery_stage" in body:
        stage = int(body["mastery_stage"])
        if 0 <= stage <= 3:
            data["words"][index]["mastery_stage"] = stage

    # 支持手动编辑其他字段
    for field in ("word", "phonetic", "definition", "sentence", "translation"):
        if field in body and body[field]:
            data["words"][index][field] = body[field]

    save_words(data)
    return jsonify(data["words"][index])


@app.route("/api/words/<int:index>", methods=["DELETE"])
def api_delete_word(index):
    data = load_words()
    if index < 0 or index >= len(data["words"]):
        return jsonify({"error": "索引越界"}), 404
    removed = data["words"].pop(index)
    save_words(data)
    return jsonify({"deleted": removed["word"]})


@app.route("/api/words/<int:index>/enrich", methods=["POST"])
def api_enrich_word(index):
    """为已有单词重新调用 AI，补充 variations / phrases 等字段。"""
    data = load_words()
    if index < 0 or index >= len(data["words"]):
        return jsonify({"error": "索引越界"}), 404

    word_entry = data["words"][index]
    raw_word = word_entry["word"]

    try:
        enriched = call_deepseek(raw_word)
    except Exception as e:
        msg = str(e)
        if "401" in msg:
            hint = " — AI 令牌无效，请检查 .env 中的 ANTHROPIC_AUTH_TOKEN 是否正确（当前值可能为占位符）"
        elif "ConnectionError" in str(e.__class__.__name__) or "Connection" in msg:
            hint = " — 无法连接 AI 服务，请确认本地代理已启动"
        else:
            hint = ""
        return jsonify({"error": f"AI 充实失败：{e}{hint}"}), 502

    # 合并：保留原有 mastery_stage 和 type，更新其他字段
    for key in ("word", "phonetic", "definition", "sentence", "translation", "variations", "phrases"):
        if key in enriched:
            word_entry[key] = enriched[key]
    word_entry["type"] = "phrase" if " " in raw_word.strip() else "word"

    save_words(data)
    return jsonify(word_entry)


@app.route("/api/ai-check", methods=["GET"])
def api_ai_check():
    """诊断 AI API 配置是否正常。"""
    ok, msg = check_api_connection()
    return jsonify({"ok": ok, "message": msg, "config": {
        "base_url": API_BASE_URL,
        "api_url": API_URL,
        "model": API_MODEL,
        "has_key": bool(API_KEY),
    }})


if __name__ == "__main__":
    print("=" * 56)
    print("  考研英语智能极简词典  /  Kaoyan Smart Vocab Dashboard")
    print("=" * 56)
    print(f"  Words file : {WORDS_FILE}")
    print(f"  API URL   : {API_URL}")
    print(f"  API Model : {API_MODEL}")
    print(f"  API Key   : {'[OK]' if API_KEY else '[MISSING] — placeholder mode'}")
    print(f"  访问地址  : http://127.0.0.1:5000")
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
    app.run(debug=True, host="127.0.0.1", port=5000)
