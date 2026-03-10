# Commands Guide

本文档说明 `scheduler_agent.py` 各命令的用途、常用参数和示例。

## Global Pattern

```bash
python3 scheduler_agent.py <command> [options]
```

大多数命令默认参数来自 `agent_config.toml`，命令行参数会覆盖配置文件。

## 1) init

用途：初始化目录和模板文件，必要时迁移旧 `data/` 内容。

```bash
python3 scheduler_agent.py init
```

输出：创建并校验 `user_data/`, `plans/`, `run_data/`, `today_window.md`。

## 2) sync-chat

用途：读取 `today_window.md` 的 `## Sync Input`，提取并分解信息写入 `user_data/` 与 `run_data/`。

```bash
python3 scheduler_agent.py sync-chat
python3 scheduler_agent.py sync-chat --plan-after
python3 scheduler_agent.py sync-chat --plan-after --date 2026-03-11
```

常用参数：
- `--model`：模型名称
- `--temperature`：抽取温度
- `--plan-after`：同步后生成次日计划
- `--date`：配合 `--plan-after` 指定目标计划日期

## 3) plan

用途：基于当前 `user_data/`、最近计划与反馈生成日计划。

```bash
python3 scheduler_agent.py plan
python3 scheduler_agent.py plan --date 2026-03-11
python3 scheduler_agent.py plan --temperature 0.25
```

常用参数：
- `--date`：默认是明天
- `--model`
- `--temperature`

输出：`plans/daily/YYYY-MM-DD.md`

附加行为：自动将计划任务填入 `today_window.md` 的勾选区（`今日三件最重要的事` 与 `其他任务`）。

## 4) feedback

用途：手动记录反馈（可替代从 Sync Input 自动提取）。

```bash
python3 scheduler_agent.py feedback \
  --date 2026-03-10 \
  --completion "3/5" \
  --mood "一般" \
  --notes "会议较多"
```

常用参数：
- `--date`（必填）
- `--completion`（必填）
- `--mood`（必填）
- `--notes`

输出：
- `run_data/feedback_log.jsonl`
- `run_data/feedback/YYYY-MM-DD.md`

## 5) window-refresh

用途：归档当天 `today_window.md`，并创建下一天窗口模板。

```bash
python3 scheduler_agent.py window-refresh
python3 scheduler_agent.py window-refresh --date 2026-03-10
```

常用参数：
- `--date`：指定当前窗口日期（默认今天）

输出：
- `run_data/today_window_archive/`
- 新的 `today_window.md`

## 5.5) adjust-today

用途：当日出现突发情况时，根据指定文件重排“今天”的计划，并同步更新 `today_window.md` 勾选项。

```bash
python3 scheduler_agent.py adjust-today
python3 scheduler_agent.py adjust-today --input-file ./adjust.md
python3 scheduler_agent.py adjust-today --date 2026-03-12
```

常用参数：
- `--input-file`：突发情况输入文件路径（默认 `./adjust.md`）
- `--date`：目标日期（默认今天）
- `--model`
- `--temperature`

输出：
- 覆盖更新 `plans/daily/YYYY-MM-DD.md`
- 自动更新 `today_window.md` 勾选任务
- 写入 `run_data/sync_history/*.jsonl`

## 6) weekly-review

用途：基于过去 N 天计划与反馈生成周复盘。

```bash
python3 scheduler_agent.py weekly-review
python3 scheduler_agent.py weekly-review --end-date 2026-03-10 --days 7
```

常用参数：
- `--end-date`：复盘结束日期（默认今天）
- `--days`：窗口天数（默认 7）
- `--model`
- `--temperature`

输出：`plans/weekly/start_to_end.md`

## 7) autopilot

用途：一键执行日常流程。

流程：
1. 同步 `Sync Input`（有内容才执行）
2. 生成次日计划
3. 归档并刷新 `today_window.md`
4. 可选周复盘
5. 默认自动清理

```bash
python3 scheduler_agent.py autopilot
python3 scheduler_agent.py autopilot --weekly
python3 scheduler_agent.py autopilot --no-auto-cleanup
python3 scheduler_agent.py autopilot --cleanup-keep-days 21 --cleanup-keep-feedback 150 --cleanup-keep-chat-sections 10
```

常用参数：
- `--current-date`
- `--plan-date`
- `--model`
- `--temperature`
- `--weekly`
- `--weekly-days`
- `--weekly-temperature`
- `--auto-cleanup` / `--no-auto-cleanup`
- `--cleanup-keep-days`
- `--cleanup-keep-feedback`
- `--cleanup-keep-chat-sections`

## 8) cleanup

用途：执行可控清理，防止信息不断堆砌。

```bash
python3 scheduler_agent.py cleanup
python3 scheduler_agent.py cleanup --keep-days 21 --keep-feedback 150 --keep-chat-sections 10
```

常用参数：
- `--keep-days`
- `--keep-feedback`
- `--keep-chat-sections`

## 9) reset-data

用途：全量重置（危险）。

```bash
python3 scheduler_agent.py reset-data --yes
python3 scheduler_agent.py reset-data --yes --no-snapshot
python3 scheduler_agent.py reset-data --yes --include-snapshots
```

常用参数：
- `--yes`：必填确认
- `--no-snapshot`：不生成 reset 前备份
- `--include-snapshots`：连 `run_data/snapshots` 一起清空

## 10) status

用途：快速查看最近反馈和最近日计划。

```bash
python3 scheduler_agent.py status
```

## Recommended Daily Usage

```bash
python3 scheduler_agent.py autopilot
```

周末建议：

```bash
python3 scheduler_agent.py autopilot --weekly
```
