# 考研英语智能极简词典看板

> Kaoyan Smart Vocab Dashboard — 极简 · AI 驱动 · 渐进熟记

一个为考研党打造的英文单词管理看板，**Obsidian Minimal 极简风格** + **DeepSeek AI 自动查词**，让你专注背词本身。

---

## 核心亮点

- **Obsidian Minimal 极简风** — 深色 / 浅色双主题，排版干净克制，信息密度刚好，不炫技不扰眼。
- **3D / Modal 弹窗** — 每个单词卡片支持 3D 翻转动效，点击展开 Modal 详情弹窗，沉浸式查阅音标、释义、例句与翻译。
- **DeepSeek AI 自动查词** — 输入单词一键调用 DeepSeek 大模型，自动生成英式音标、考研级例句与精炼释义，告别手动录入。
- **熟记四级颜色渐变** — 每个单词支持 0~3 级掌握度标记，卡片颜色从浅灰 → 浅绿 → 深绿渐变，学习进度一目了然。

---

## 快速开始

### 1. 克隆项目

```bash
git clone <你的仓库地址>
cd my_project
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置 AI 查词（可选但推荐）

本项目使用 **DeepSeek** 大模型自动查词。你需要一个 DeepSeek API Key：

1. 前往 [DeepSeek 开放平台](https://platform.deepseek.com/) 注册并获取 API Key。
2. 在终端中设置环境变量：

```bash
# macOS / Linux
export ANTHROPIC_AUTH_TOKEN="你的DeepSeek-API-Key"

# Windows (CMD)
set ANTHROPIC_AUTH_TOKEN=你的DeepSeek-API-Key

# Windows (PowerShell)
$env:ANTHROPIC_AUTH_TOKEN="你的DeepSeek-API-Key"
```

> 未配置 Key 也能正常使用 —— 添加单词时会生成空白占位卡片，后续可手动编辑补充。

### 4. 启动应用

```bash
python app.py
```

浏览器访问 **http://127.0.0.1:5000** 即可看到词典看板。

---

## 项目结构

```
.
├── app.py              # Flask 后端主程序
├── templates/
│   └── index.html      # 前端页面（Tailwind CSS 构建）
├── words.json          # 本地单词数据（已附带测试数据，可直接使用）
├── requirements.txt    # Python 依赖清单
└── .gitignore
```

## 数据说明

- 所有单词数据存储在 `words.json` 中，纯 JSON 格式，方便备份或迁移。
- 初始文件包含少量考研高频词汇作为测试数据，你可以直接在此基础上增删。
- `mastery_stage` 字段取值 0~3，代表对该单词的掌握程度。

---

## License

MIT — 随意使用、修改和分享。
