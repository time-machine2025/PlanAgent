# Plan Agent (DeepSeek)

一个本地优先的日程系统：
- 读取 `user_data/` 的长期信息
- 生成并调整 `plans/`（月/周/日）
- 在 `today_window.md` 完成勾选、反馈、自由输入
- 把运行日志写入 `run_data/`

## 目录结构

```text
.
├── user_data/                 # 长期静态信息（相对稳定）
│   ├── profile.md             # 用户画像
│   ├── goals.md               # 长期目标（可含月/季）
│   ├── preferences.md         # 用户偏好
│   ├── fixed_events.md        # 固定日程
│   └── today_notes.md         # 临时约束/补充
│
├── plans/                     # 计划输出（可被查看/编辑）
│   ├── monthly/
│   ├── weekly/
│   └── daily/
│
├── today_window.md            # 勾选完成 + 反馈 + 自由输入
│
├── run_data/                  # 运行时与历史记录（程序自动写）
│   ├── feedback_log.jsonl
│   ├── chat_archive/
│   ├── sync_history/
│   ├── snapshots/
│   └── today_window_archive/
│
└── scheduler_agent.py
```

## 快速开始

1. 配置环境

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. 配置 API Key（根目录 `.env`）

```env
DEEPSEEK_API_KEY=your_api_key_here
```

3. 初始化

```bash
python3 scheduler_agent.py init
```

4. 集中配置（推荐）

直接编辑根目录 `agent_config.toml`，可统一修改模型参数、autopilot 默认参数、清理保留策略。修改后命令会自动使用新默认值。

## 日常命令

```bash
python3 scheduler_agent.py sync-chat --plan-after
python3 scheduler_agent.py window-refresh
python3 scheduler_agent.py weekly-review
python3 scheduler_agent.py autopilot
python3 scheduler_agent.py autopilot --weekly
python3 scheduler_agent.py cleanup
python3 scheduler_agent.py reset-data --yes
```

参数总览请看：`PARAMETERS.md`，集中可编辑配置文件是：`agent_config.toml`
命令使用说明请看：`COMMANDS.md`

说明：
- `sync-chat` 会读取 `today_window.md` 里的 `## Sync Input` 区域，提取信息后写入 `user_data/` 和 `run_data/`。
- 生成日计划时，系统会自动把计划任务填入 `today_window.md` 的勾选区（用于打勾追踪完成情况）。
- `window-refresh` 会归档旧 `today_window.md` 并生成下一天窗口。
- `weekly-review` 会基于过去数据产出周复盘到 `plans/weekly/`。
- `autopilot` 一键串联日流程（同步 -> 次日计划 -> 刷新窗口，可选周复盘）。

## 清理机制（防止不断堆砌）

定期清理（推荐每周或每月一次）：

```bash
python3 scheduler_agent.py cleanup
python3 scheduler_agent.py cleanup --keep-days 21 --keep-feedback 150 --keep-chat-sections 10
```

作用：
- 清理超过保留天数的运行文件（计划、归档、日志）
- 截断反馈日志，仅保留最近 N 条
- 压缩 `user_data/*.md` 中过多的 `From Chat` 历史段落

全量重置（危险操作）：

```bash
python3 scheduler_agent.py reset-data --yes
```

默认会先在 `run_data/snapshots/` 生成备份 zip，再重置 `user_data/`、`plans/`、`run_data/` 运行数据。

## 兼容迁移

如果你有旧版 `data/` 目录，`init` 会自动迁移历史内容到新结构（仅在目标文件不存在时复制，不会覆盖你现有内容）。

## 隐私与 Git

默认已忽略：
- `user_data/**`
- `run_data/**`
- `plans/daily/**`、`plans/weekly/**`、`plans/monthly/**`
- `today_window.md`

这样可以避免把个人计划和反馈上传到 GitHub。

## License

MIT
