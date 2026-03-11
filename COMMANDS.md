# Commands Guide

本文档说明 `scheduler_agent.py` 各命令的用途、常用参数和示例。

## Global Pattern

```bash
python3 scheduler_agent.py <command> [options]
```

大多数命令默认参数来自 `agent_config.toml`，命令行参数会覆盖配置文件。

## 1) init

用途：初始化目录和模板文件，必要时迁移旧 `data/` 内容。

分层约束：生成日计划时会自动参考目标日期对应的周计划（若存在）。
```bash
python3 scheduler_agent.py init
```

输出：创建并校验 `user_data/`, `plans/`, `run_data/`, `today_window.md`。

## 2) sync-chat

用途：读取 `today_window.md` 的 `## Sync Input`，提取并分解信息写入 `user_data/` 与 `run_data/`。

附加行为：使用 `--plan-after` 时，会先根据 `today_window.md` 的 `今日反馈` 自动微调对应周计划，再生成次日计划。

```bash
python3 scheduler_agent.py sync-chat
常用参数：
- `--model`：模型名称
分层约束：调整日计划时会自动参考目标日期对应的周计划（若存在）。

## 3) plan

用途：基于当前 `user_data/`、最近计划与反馈生成日计划。

```bash
python3 scheduler_agent.py plan
python3 scheduler_agent.py plan --date 2026-03-11
python3 scheduler_agent.py plan --temperature 0.25
```

常用参数：
- `--date`：默认是明天

## 4) feedback
分层约束：调整周计划时会自动参考覆盖该时间段的月计划（若存在）。
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
## 5) window-refresh

用途：归档当天 `today_window.md`，并创建下一天窗口模板。

分层约束：生成周计划时会自动参考覆盖该时间段的月计划（若存在）。
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

## 5.6) adjust-weekly

用途：当周出现突发变化时，基于当前周计划进行重排，并覆盖更新该周计划。

```bash
python3 scheduler_agent.py adjust-weekly
python3 scheduler_agent.py adjust-weekly --start-date 2026-03-09
python3 scheduler_agent.py adjust-weekly --start-date 2026-03-09 --days 7
python3 scheduler_agent.py adjust-weekly --input-file ./adjust_weekly.md --no-sync-today-window
```

常用参数：
- `--input-file`：周突发变化输入文件路径（默认 `./adjust_weekly.md`）
- `--start-date`：目标周开始日期（默认自动匹配“覆盖今天”的周计划，若无则取最新周计划）
- `--days`：目标周天数（默认 7）
- `--model`
- `--temperature`
- `--sync-today-window` / `--no-sync-today-window`：是否同步更新 `today_window.md` 的 `本周视图（来自周计划）`（默认开启）

输出：
- 覆盖更新 `plans/weekly/start_to_end_plan.md`
- 自动在 `run_data/snapshots/` 生成调整前周计划备份
- 可选更新 `today_window.md` 的本周视图
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

## 6.5) weekly-plan

用途：生成未来一周（默认从下周一开始）的周计划。

```bash
python3 scheduler_agent.py weekly-plan
python3 scheduler_agent.py weekly-plan --start-date 2026-03-16
python3 scheduler_agent.py weekly-plan --start-date 2026-03-16 --days 7 --temperature 0.25
```

常用参数：
- `--start-date`：周计划开始日期（默认下周一）
- `--days`：计划天数（默认 7）
- `--model`
- `--temperature`
- `--sync-today-window` / `--no-sync-today-window`：是否同步更新 `today_window.md` 的 `本周视图（来自周计划）`（默认开启）

输出：`plans/weekly/start_to_end_plan.md`

附加行为：默认自动把 `today_window.md` 中“当前窗口日期”对应的周计划行写入 `本周视图（来自周计划）`。

## 7) autopilot

用途：一键执行日常流程。

流程：
1. 同步 `Sync Input`（有内容才执行）
2. 根据 `today_window.md` 的 `今日反馈` 自动微调对应周计划（可匹配到时）
3. 生成次日计划
4. 归档并刷新 `today_window.md`
5. 可选周复盘
6. 默认自动清理

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
