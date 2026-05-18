---
title: 考研英语智能极简词典
emoji: 📖
colorFrom: blue
colorTo: indigo
sdk: docker
pinned: false
---

# 考研英语智能极简词典看板

> Kaoyan Smart Vocab Dashboard — 极简 · AI 驱动 · 渐进熟记

一个为考研党打造的英文单词管理看板，**Obsidian Minimal 极简风格** + **DeepSeek AI 自动查词**，让你专注背词本身。

---

## 核心亮点

- **AI 智能查词** — 输入单词，一键调用 DeepSeek 大模型，自动生成英式音标、词性释义、考研难度例句、中文翻译、常见变形和短语搭配，告别手动录入。
- **间隔重复 · 四级进阶** — 基于遗忘曲线，单词按 0→1→2→3 逐级晋升（复习间隔 1/3/7 天），卡片颜色灰→琥珀→翠绿→靛蓝渐变，掌握度一目了然。
- **词性分类筛选** — 侧栏支持按名词/动词/形容词/副词/介词/连词分类过滤，一键只看待复习单词或短语搭配。
- **Modal 详情弹窗** — 点击卡片查看完整信息：音标、释义、变形、短语、考研真题例句与翻译，支持升降级、AI 充实、删除（可撤销）。
- **批量导入** — 粘贴多行单词一键入库，自动去重，已有单词智能跳过。
- **记忆追踪面板** — 右侧显示待复习数量和掌握进度条，学习状态实时可见。
- **深色 / 浅色双主题** — Obsidian Minimal 极简风格，排版干净克制，专注背词本身。
- **响应式布局** — PC 三栏 / 平板两栏 / 手机单栏自适应，随时随地在平板上背单词。
- **云端部署 · 自动同步** — 部署在 HuggingFace Spaces，每次推送代码自动更新，无需电脑开机即可访问。

---

## 快速开始

### 本地运行

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置 AI 查词（可选）
# 在 .env 中写入：
#   ANTHROPIC_AUTH_TOKEN=你的DeepSeek-API-Key
#   ANTHROPIC_BASE_URL=https://api.deepseek.com
#   ANTHROPIC_MODEL=deepseek-chat

# 3. 启动
python app.py
# 浏览器打开 http://127.0.0.1:5000
```

### 云端访问（无需电脑开机）

直接访问 **https://huggingface.co/spaces/EwingX2979/smart-vocab** 即可使用。

> 免费版 HF Space 15 分钟无人访问会休眠，下次打开约 30 秒冷启动。

---

## 项目结构

```
.
├── app.py                  # Flask 后端：API + 单词管理 + AI 查词
├── templates/
│   └── index.html          # 前端单页：Tailwind CSS + Vanilla JS
├── words.json              # 单词数据（云端持久化至 /data/）
├── Dockerfile              # HuggingFace Spaces Docker 部署
├── .github/workflows/
│   └── deploy.yml          # GitHub Actions 自动部署到 HF Space
├── requirements.txt
└── .gitignore
```

## 技术栈

| 层 | 技术 |
|---|------|
| 后端 | Python · Flask · gunicorn |
| 前端 | Tailwind CSS（CDN）· Vanilla JS |
| AI | DeepSeek API（兼容 OpenAI 格式） |
| 存储 | JSON 文件（云端 /data 持久卷） |
| 部署 | Docker · HuggingFace Spaces · GitHub Actions |

---

## License

MIT — 随意使用、修改和分享。
