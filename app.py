import json
import os
import re
import threading
import requests
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

WORDS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "words.json")
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"

file_lock = threading.Lock()

SYSTEM_PROMPT = """你是一个专业的考研英语词典编纂专家。用户会给你一个英文单词，请返回严格的 JSON 格式（不要包含 markdown 代码块标记），包含以下字段：
- word: 单词原形
- phonetic: 英式音标，如 /ˈpærədaɪm/
- definition: 核心词性 + 精炼中文释义，控制在20字以内
- sentence: 一句考研难度级别的英语例句，体现该词在学术语境中的典型用法
- translation: 该例句的准确中文翻译

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
    changed = False
    for w in data["words"]:
        if "mastery_stage" not in w:
            old_status = w.pop("status", "")
            # 旧版「已熟记」保守映射为 mastery_stage=1
            w["mastery_stage"] = 1 if old_status == "已熟记" else 0
            changed = True
        else:
            # 清理可能残留的旧字段
            w.pop("status", None)

    if changed:
        save_words(data)

    return data


def save_words(data):
    """线程安全地写入单词 JSON 文件。"""
    with file_lock:
        with open(WORDS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


def call_deepseek(word):
    """调用 DeepSeek API 查词，返回解析后的单词数据字典。"""
    api_key = os.environ.get("ANTHROPIC_AUTH_TOKEN")
    if not api_key:
        raise RuntimeError("未设置环境变量 ANTHROPIC_AUTH_TOKEN（DeepSeek API Key）")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"请查词：{word}"},
        ],
        "temperature": 0.3,
        "max_tokens": 600,
    }

    resp = requests.post(DEEPSEEK_URL, headers=headers, json=payload, timeout=30)
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
    parsed["mastery_stage"] = 0
    return parsed


def placeholder_lookup(word):
    """无 AI 时的占位查词，返回可手动填充的空白卡片。"""
    return {
        "word": word.strip().lower(),
        "phonetic": "",
        "definition": "（待完善 — 请手动编辑或配置 AI Key）",
        "sentence": "",
        "translation": "",
        "mastery_stage": 0,
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
    except Exception as e:
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


if __name__ == "__main__":
    print("=" * 56)
    print("  考研英语智能极简词典  /  Kaoyan Smart Vocab Dashboard")
    print("=" * 56)
    print(f"  Words file : {WORDS_FILE}")
    key_ok = bool(os.environ.get("ANTHROPIC_AUTH_TOKEN"))
    print(f"  AI Key      : {'[OK]' if key_ok else '[MISSING] — placeholder mode'}")
    print(f"  访问地址    : http://127.0.0.1:5000")
    print("=" * 56)
    app.run(debug=True, host="127.0.0.1", port=5000)
