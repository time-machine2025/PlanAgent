# Daily Schedule Agent (DeepSeek)

一个可本地运行的日程安排 Agent：
- 读取你的本地信息（目标、偏好、固定事件、临时备注）
- 根据每天反馈（完成情况、感受）自动调整第二天计划
- 支持 `chat_window.md` 双输入模式：结构化模板 + 自由输入

## Features

- DeepSeek 模型驱动（`deepseek-chat`）
- 本地文件工作流，数据可控
- 日计划自动落盘（`data/plans/`）
- 反馈历史记录（`data/feedback_log.jsonl`）

## Quick Start

### 1. 环境准备

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. 配置 API Key

在项目根目录创建 `.env`（可参考 `.env.example`）：

```env
DEEPSEEK_API_KEY=your_api_key_here
```

### 3. 初始化数据模板

```bash
python3 scheduler_agent.py init
```

### 4. 双输入聊天窗口（推荐）

编辑 `data/chat_window.md`，填写：
- `## Daily Template`：每天固定信息
- `## Free Message`：自由输入临时信息

然后执行：

```bash
python3 scheduler_agent.py sync-chat --plan-after
```

## 常用命令

```bash
python3 scheduler_agent.py init
python3 scheduler_agent.py sync-chat
python3 scheduler_agent.py sync-chat --plan-after
python3 scheduler_agent.py plan --date 2026-03-11
python3 scheduler_agent.py feedback --date 2026-03-10 --completion "3/5" --mood "还行" --notes "会议偏多"
python3 scheduler_agent.py status
```

## 项目结构

```text
.
├── scheduler_agent.py
├── pyproject.toml
├── .env.example
├── data/
│   ├── .gitkeep
│   └── README.md
└── README.md
```

说明：`data/` 下的运行时文件默认不进入 Git，避免上传隐私信息。

## 发布到 GitHub

### 1. 初始化仓库并提交

```bash
git init
git add .
git commit -m "Initial commit: daily schedule agent"
```

### 2. 绑定远程仓库

把 `<your-user>` 和 `<your-repo>` 替换成你的信息：

```bash
git branch -M main
git remote add origin git@github.com:<your-user>/<your-repo>.git
git push -u origin main
```

如果你使用 HTTPS：

```bash
git remote add origin https://github.com/<your-user>/<your-repo>.git
git push -u origin main
```

## Packaging (optional)

项目包含 `pyproject.toml`，可安装命令行入口：

```bash
pip install -e .
schedule-agent --help
```

## Security Notes

- 不要上传 `.env`
- 不要上传 `data/` 下的个人计划与反馈内容
- 分享仓库前，先检查 `git status` 与 `git diff --cached`

## License

MIT
