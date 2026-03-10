#!/usr/bin/env python3
"""Daily schedule agent powered by DeepSeek.

Features:
- Read local context files (profile/goals/preferences/fixed events).
- Generate next-day schedule based on current context + recent feedback.
- Record daily feedback (completion, mood, notes) for iterative adjustment.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import shutil
from typing import Any, Dict, List
from urllib import error, request
import re
import tempfile
import tomllib

BASE_DIR = Path(__file__).resolve().parent
USER_DATA_DIR = BASE_DIR / "user_data"
PLANS_DIR = BASE_DIR / "plans"
MONTHLY_PLAN_DIR = PLANS_DIR / "monthly"
WEEKLY_PLAN_DIR = PLANS_DIR / "weekly"
DAILY_PLAN_DIR = PLANS_DIR / "daily"

RUN_DATA_DIR = BASE_DIR / "run_data"
FEEDBACK_DIR = RUN_DATA_DIR / "feedback"
FEEDBACK_JSONL = RUN_DATA_DIR / "feedback_log.jsonl"
CHAT_ARCHIVE_DIR = RUN_DATA_DIR / "chat_archive"
SYNC_HISTORY_DIR = RUN_DATA_DIR / "sync_history"
SNAPSHOTS_DIR = RUN_DATA_DIR / "snapshots"
TODAY_WINDOW_ARCHIVE_DIR = RUN_DATA_DIR / "today_window_archive"
ADJUST_INPUT_FILE = BASE_DIR / "adjust.md"
LEGACY_INCIDENT_INPUT_FILE = RUN_DATA_DIR / "incident_input.md"

TODAY_WINDOW_FILE = BASE_DIR / "today_window.md"

PROFILE_FILE = USER_DATA_DIR / "profile.md"
GOALS_FILE = USER_DATA_DIR / "goals.md"
PREFERENCES_FILE = USER_DATA_DIR / "preferences.md"
FIXED_EVENTS_FILE = USER_DATA_DIR / "fixed_events.md"
TODAY_NOTES_FILE = USER_DATA_DIR / "today_notes.md"
STATE_FILE = USER_DATA_DIR / "state.md"

LEGACY_DATA_DIR = BASE_DIR / "data"
LEGACY_CHAT_WINDOW_FILE = LEGACY_DATA_DIR / "chat_window.md"

DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
DEFAULT_MODEL = "deepseek-chat"
DEFAULT_KEEP_DAYS = 30
DEFAULT_KEEP_FEEDBACK = 200
DEFAULT_KEEP_CHAT_SECTIONS = 20
CONFIG_FILE = BASE_DIR / "agent_config.toml"

DEFAULT_CONFIG: Dict[str, Any] = {
    "model": {
        "default_model": DEFAULT_MODEL,
        "plan_temperature": 0.3,
        "sync_chat_temperature": 0.1,
        "weekly_review_temperature": 0.2,
        "autopilot_temperature": 0.2,
    },
    "cleanup": {
        "keep_days": DEFAULT_KEEP_DAYS,
        "keep_feedback": DEFAULT_KEEP_FEEDBACK,
        "keep_chat_sections": DEFAULT_KEEP_CHAT_SECTIONS,
    },
    "autopilot": {
        "weekly_days": 7,
        "auto_cleanup": True,
    },
}


def default_config_toml() -> str:
    return (
        "[model]\n"
        f"default_model = \"{DEFAULT_MODEL}\"\n"
        "plan_temperature = 0.3\n"
        "sync_chat_temperature = 0.1\n"
        "weekly_review_temperature = 0.2\n"
        "autopilot_temperature = 0.2\n\n"
        "[cleanup]\n"
        f"keep_days = {DEFAULT_KEEP_DAYS}\n"
        f"keep_feedback = {DEFAULT_KEEP_FEEDBACK}\n"
        f"keep_chat_sections = {DEFAULT_KEEP_CHAT_SECTIONS}\n\n"
        "[autopilot]\n"
        "weekly_days = 7\n"
        "auto_cleanup = true\n"
    )


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged: Dict[str, Any] = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_agent_config() -> Dict[str, Any]:
    if not CONFIG_FILE.exists():
        return dict(DEFAULT_CONFIG)

    try:
        parsed = tomllib.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError:
        return dict(DEFAULT_CONFIG)

    if not isinstance(parsed, dict):
        return dict(DEFAULT_CONFIG)
    return deep_merge(DEFAULT_CONFIG, parsed)


def cfg_get(config: Dict[str, Any], section: str, key: str, fallback: Any) -> Any:
    section_value = config.get(section, {})
    if not isinstance(section_value, dict):
        return fallback
    return section_value.get(key, fallback)


def sync_input_template() -> str:
    return (
        "## Sync Input\n\n"
        "### Daily Template\n"
        "- Date: \n"
        "- Completion: \n"
        "- Mood: \n\n"
        "#### Must-Dos\n"
        "- \n\n"
        "#### Fixed Events\n"
        "- \n\n"
        "#### Constraints\n"
        "- \n\n"
        "#### Preference Tweaks\n"
        "- \n\n"
        "#### Reflection\n"
        "- \n\n"
        "### Free Message\n"
        "把临时想法、背景信息、感受直接写在这里。\n"
    )


def default_user_files() -> Dict[Path, str]:
    return {
        PROFILE_FILE: "# Profile\n\n- Name:\n- Work style:\n- Energy peak time:\n",
        GOALS_FILE: "# Goals\n\n## This week\n- \n\n## This month\n- \n",
        PREFERENCES_FILE: "# Preferences\n\n- Preferred schedule style:\n- Break frequency:\n- Deep work duration:\n",
        FIXED_EVENTS_FILE: "# Fixed Events\n\n- 09:30-10:00 Daily standup\n",
        TODAY_NOTES_FILE: "# Today Notes\n\n- Any temporary constraints or special events today.\n",
        STATE_FILE: (
            "# State\n\n"
            "## Short-term (1-2 weeks)\n"
            "- \n\n"
            "## Long-term (1-3 months)\n"
            "- \n\n"
            "## Risks\n"
            "- \n\n"
            "## Adjustment Rules\n"
            "- \n"
        ),
    }


def today_window_template(target_date: dt.date | None = None) -> str:
    date_value = (target_date or dt.date.today()).isoformat()
    return (
        f"# Today Window ({date_value})\n\n"
        "## 今日三件最重要的事\n"
        "- [ ] \n"
        "- [ ] \n"
        "- [ ] \n\n"
        "## 其他任务\n"
        "- [ ] \n\n"
        "## 今日反馈\n"
        "- Completion: \n"
        "- Mood: \n"
        "- Wins: \n"
        "- Blockers: \n"
        "- Notes: \n\n"
        f"{sync_input_template()}"
    )


def migrate_legacy_data() -> None:
    if not LEGACY_DATA_DIR.exists():
        return

    file_map = [
        (LEGACY_DATA_DIR / "profile.md", PROFILE_FILE),
        (LEGACY_DATA_DIR / "goals.md", GOALS_FILE),
        (LEGACY_DATA_DIR / "preferences.md", PREFERENCES_FILE),
        (LEGACY_DATA_DIR / "fixed_events.md", FIXED_EVENTS_FILE),
        (LEGACY_DATA_DIR / "today_notes.md", TODAY_NOTES_FILE),
        (LEGACY_DATA_DIR / "state.md", STATE_FILE),
        (LEGACY_DATA_DIR / "feedback_log.jsonl", FEEDBACK_JSONL),
        (LEGACY_DATA_DIR / "today_window.md", TODAY_WINDOW_FILE),
        (LEGACY_CHAT_WINDOW_FILE, TODAY_WINDOW_FILE),
    ]

    for old_path, new_path in file_map:
        if old_path.exists() and not new_path.exists():
            new_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(old_path, new_path)

    old_daily = LEGACY_DATA_DIR / "plans"
    if old_daily.exists():
        DAILY_PLAN_DIR.mkdir(parents=True, exist_ok=True)
        for path in old_daily.glob("*.md"):
            target = DAILY_PLAN_DIR / path.name
            if not target.exists():
                shutil.copy2(path, target)

    old_weekly = LEGACY_DATA_DIR / "weekly_reviews"
    if old_weekly.exists():
        WEEKLY_PLAN_DIR.mkdir(parents=True, exist_ok=True)
        for path in old_weekly.glob("*.md"):
            target = WEEKLY_PLAN_DIR / path.name
            if not target.exists():
                shutil.copy2(path, target)

    old_chat_archive = LEGACY_DATA_DIR / "chat_archive"
    if old_chat_archive.exists():
        CHAT_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        for path in old_chat_archive.glob("*.md"):
            target = CHAT_ARCHIVE_DIR / path.name
            if not target.exists():
                shutil.copy2(path, target)

    old_window_archive = LEGACY_DATA_DIR / "today_window_archive"
    if old_window_archive.exists():
        TODAY_WINDOW_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        for path in old_window_archive.glob("*.md"):
            target = TODAY_WINDOW_ARCHIVE_DIR / path.name
            if not target.exists():
                shutil.copy2(path, target)


def ensure_structure() -> None:
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    PLANS_DIR.mkdir(parents=True, exist_ok=True)
    MONTHLY_PLAN_DIR.mkdir(parents=True, exist_ok=True)
    WEEKLY_PLAN_DIR.mkdir(parents=True, exist_ok=True)
    DAILY_PLAN_DIR.mkdir(parents=True, exist_ok=True)
    RUN_DATA_DIR.mkdir(parents=True, exist_ok=True)
    FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)
    CHAT_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    SYNC_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    TODAY_WINDOW_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    migrate_legacy_data()

    if not CONFIG_FILE.exists():
        CONFIG_FILE.write_text(default_config_toml(), encoding="utf-8")

    defaults = default_user_files()
    defaults[TODAY_WINDOW_FILE] = today_window_template()

    for path, content in defaults.items():
        if not path.exists():
            path.write_text(content, encoding="utf-8")

    # Backfill sync input section for legacy today_window content.
    if TODAY_WINDOW_FILE.exists():
        window_text = TODAY_WINDOW_FILE.read_text(encoding="utf-8")
        if "## Sync Input" not in window_text:
            TODAY_WINDOW_FILE.write_text(window_text.rstrip() + "\n\n" + sync_input_template(), encoding="utf-8")

    if not FEEDBACK_JSONL.exists():
        FEEDBACK_JSONL.write_text("", encoding="utf-8")

    if not ADJUST_INPUT_FILE.exists():
        if LEGACY_INCIDENT_INPUT_FILE.exists():
            shutil.copy2(LEGACY_INCIDENT_INPUT_FILE, ADJUST_INPUT_FILE)
        else:
            ADJUST_INPUT_FILE.write_text(
            "# Incident Input\n\n"
            "在这里写今天突发情况，例如：临时会议、身体不适、外出、截止时间变化等。\n",
            encoding="utf-8",
            )


def load_env_file(env_path: Path) -> None:
    """Load simple KEY=VALUE pairs from a .env file into process env."""
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()

        if value and ((value[0] == value[-1]) and value[0] in {"'", '"'}):
            value = value[1:-1]

        if key and key not in os.environ:
            os.environ[key] = value


def clear_directory(dir_path: Path, keep_names: set[str] | None = None) -> int:
    keep = keep_names or set()
    removed = 0
    if not dir_path.exists():
        return removed

    for child in dir_path.iterdir():
        if child.name in keep:
            continue
        if child.is_dir():
            shutil.rmtree(child)
            removed += 1
        else:
            child.unlink(missing_ok=True)
            removed += 1
    return removed


def prune_old_files(dir_path: Path, keep_days: int) -> int:
    if not dir_path.exists():
        return 0

    cutoff = dt.datetime.now() - dt.timedelta(days=keep_days)
    removed = 0
    for path in dir_path.iterdir():
        if path.name.startswith("."):
            continue
        if not path.is_file():
            continue
        mtime = dt.datetime.fromtimestamp(path.stat().st_mtime)
        if mtime < cutoff:
            path.unlink(missing_ok=True)
            removed += 1
    return removed


def compact_from_chat_sections(path: Path, keep_last: int) -> bool:
    if not path.exists():
        return False

    text = path.read_text(encoding="utf-8")
    marker = "\n## From Chat"
    idx = text.find(marker)
    if idx == -1:
        return False

    head = text[:idx].rstrip() + "\n"
    tail = text[idx + 1 :]
    chunks = [chunk for chunk in tail.split("\n## From Chat") if chunk.strip()]
    if len(chunks) <= keep_last:
        return False

    kept = chunks[-keep_last:]
    rebuilt = head + "\n" + "\n".join(["## From Chat" + chunk for chunk in kept]).rstrip() + "\n"
    path.write_text(rebuilt, encoding="utf-8")
    return True


def truncate_feedback_jsonl(max_entries: int) -> int:
    if not FEEDBACK_JSONL.exists():
        return 0
    lines = [line for line in FEEDBACK_JSONL.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(lines) <= max_entries:
        return 0
    kept = lines[-max_entries:]
    FEEDBACK_JSONL.write_text("\n".join(kept) + "\n", encoding="utf-8")
    return len(lines) - len(kept)


def snapshot_before_reset() -> Path:
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    tmp_dir = Path(tempfile.mkdtemp(prefix="plan_agent_reset_"))

    for src in [USER_DATA_DIR, RUN_DATA_DIR, PLANS_DIR, TODAY_WINDOW_FILE]:
        if not src.exists():
            continue
        target = tmp_dir / src.name
        if src.is_dir():
            shutil.copytree(src, target, dirs_exist_ok=True)
        else:
            shutil.copy2(src, target)

    archive_base = SNAPSHOTS_DIR / f"reset_{stamp}"
    archive_path = shutil.make_archive(str(archive_base), "zip", root_dir=tmp_dir)
    shutil.rmtree(tmp_dir)
    return Path(archive_path)


def read_text_if_exists(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def parse_date(date_text: str | None) -> dt.date:
    if not date_text:
        return dt.date.today() + dt.timedelta(days=1)
    return dt.datetime.strptime(date_text, "%Y-%m-%d").date()


def now_text() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_feedback(limit: int = 14) -> List[Dict[str, Any]]:
    if not FEEDBACK_JSONL.exists():
        return []

    lines = [line for line in FEEDBACK_JSONL.read_text(encoding="utf-8").splitlines() if line.strip()]
    entries: List[Dict[str, Any]] = []

    for line in lines:
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    return entries[-limit:]


def load_recent_plans(limit: int = 7) -> List[Dict[str, str]]:
    plans = sorted(DAILY_PLAN_DIR.glob("*.md"))
    recent = plans[-limit:]
    result: List[Dict[str, str]] = []
    for path in recent:
        result.append({"date": path.stem, "content": read_text_if_exists(path)})
    return result


def load_plans_between(start_date: dt.date, end_date: dt.date) -> List[Dict[str, str]]:
    result: List[Dict[str, str]] = []
    for path in sorted(DAILY_PLAN_DIR.glob("*.md")):
        try:
            plan_date = dt.datetime.strptime(path.stem, "%Y-%m-%d").date()
        except ValueError:
            continue

        if start_date <= plan_date <= end_date:
            result.append({"date": plan_date.isoformat(), "content": read_text_if_exists(path)})
    return result


def load_feedback_between(start_date: dt.date, end_date: dt.date) -> List[Dict[str, Any]]:
    entries = load_feedback(limit=1000)
    selected: List[Dict[str, Any]] = []
    for entry in entries:
        date_text = str(entry.get("date", "")).strip()
        try:
            entry_date = dt.datetime.strptime(date_text, "%Y-%m-%d").date()
        except ValueError:
            continue
        if start_date <= entry_date <= end_date:
            selected.append(entry)
    return selected


def build_messages(target_date: dt.date) -> List[Dict[str, str]]:
    profile = read_text_if_exists(PROFILE_FILE)
    goals = read_text_if_exists(GOALS_FILE)
    preferences = read_text_if_exists(PREFERENCES_FILE)
    fixed_events = read_text_if_exists(FIXED_EVENTS_FILE)
    today_notes = read_text_if_exists(TODAY_NOTES_FILE)
    state = read_text_if_exists(STATE_FILE)

    feedback = load_feedback(limit=14)
    plans = load_recent_plans(limit=7)

    system_prompt = (
        "You are a practical daily planning assistant. "
        "You must create realistic schedules, adapt to feedback, and avoid over-planning. "
        "Always keep output concise and executable."
    )

    user_payload = {
        "target_date": target_date.isoformat(),
        "local_context": {
            "profile_md": profile,
            "goals_md": goals,
            "preferences_md": preferences,
            "fixed_events_md": fixed_events,
            "today_notes_md": today_notes,
            "state_md": state,
        },
        "recent_feedback": feedback,
        "recent_plans": plans,
        "instructions": [
            "Use local context and recent feedback to adjust tomorrow's plan.",
            "If completion was low recently, reduce workload and add recovery buffers.",
            "If mood/energy is low, schedule hard tasks during peak energy blocks only.",
            "Return Markdown in Chinese with these sections exactly:",
            "1) # 次日日程（YYYY-MM-DD）",
            "2) ## 调整依据",
            "3) ## 时间块安排",
            "4) ## 今日三件最重要的事",
            "5) ## 风险与备选方案",
            "6) ## 晚间复盘提示",
            "For 时间块安排, use a table: 时间 | 任务 | 说明.",
            "Keep it realistic for one day.",
        ],
    }

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, indent=2)},
    ]


def build_weekly_review_messages(start_date: dt.date, end_date: dt.date) -> List[Dict[str, str]]:
    profile = read_text_if_exists(PROFILE_FILE)
    goals = read_text_if_exists(GOALS_FILE)
    preferences = read_text_if_exists(PREFERENCES_FILE)
    fixed_events = read_text_if_exists(FIXED_EVENTS_FILE)
    today_notes = read_text_if_exists(TODAY_NOTES_FILE)
    state = read_text_if_exists(STATE_FILE)

    feedback = load_feedback_between(start_date, end_date)
    plans = load_plans_between(start_date, end_date)

    system_prompt = (
        "You are a practical weekly review assistant for personal productivity. "
        "Use evidence from plans and feedback to summarize patterns and produce clear action items."
    )

    user_payload = {
        "review_range": {
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
        },
        "local_context": {
            "profile_md": profile,
            "goals_md": goals,
            "preferences_md": preferences,
            "fixed_events_md": fixed_events,
            "today_notes_md": today_notes,
            "state_md": state,
        },
        "plans": plans,
        "feedback": feedback,
        "instructions": [
            "Return Markdown in Chinese with these sections exactly:",
            "1) # 周复盘（YYYY-MM-DD 到 YYYY-MM-DD）",
            "2) ## 本周完成情况",
            "3) ## 高效模式与低效模式",
            "4) ## 关键问题与成因",
            "5) ## 下周调整策略",
            "6) ## 下周三件最重要的事",
            "Use concrete evidence from provided data.",
            "Avoid generic advice.",
        ],
    }

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, indent=2)},
    ]


def build_adjust_today_messages(target_date: dt.date, incident_text: str, current_plan: str, today_window: str) -> List[Dict[str, str]]:
    profile = read_text_if_exists(PROFILE_FILE)
    goals = read_text_if_exists(GOALS_FILE)
    preferences = read_text_if_exists(PREFERENCES_FILE)
    fixed_events = read_text_if_exists(FIXED_EVENTS_FILE)
    today_notes = read_text_if_exists(TODAY_NOTES_FILE)
    state = read_text_if_exists(STATE_FILE)
    feedback = load_feedback(limit=14)

    system_prompt = (
        "You are a practical daily replanning assistant. "
        "Given unexpected incidents, adjust today's plan realistically while preserving priorities."
    )

    user_payload = {
        "target_date": target_date.isoformat(),
        "incident_text": incident_text,
        "current_plan_markdown": current_plan,
        "today_window_markdown": today_window,
        "local_context": {
            "profile_md": profile,
            "goals_md": goals,
            "preferences_md": preferences,
            "fixed_events_md": fixed_events,
            "today_notes_md": today_notes,
            "state_md": state,
        },
        "recent_feedback": feedback,
        "instructions": [
            "Adjust only today's plan.",
            "Keep priorities but reduce overload when needed.",
            "Return Markdown in Chinese with these sections exactly:",
            "1) # 今日调整计划（YYYY-MM-DD）",
            "2) ## 调整依据",
            "3) ## 时间块安排",
            "4) ## 今日三件最重要的事",
            "5) ## 风险与备选方案",
            "6) ## 晚间复盘提示",
            "For 时间块安排, use a table: 时间 | 任务 | 说明.",
        ],
    }

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, indent=2)},
    ]


def resolve_input_file(path_text: str | None) -> Path:
    if not path_text:
        return ADJUST_INPUT_FILE
    path = Path(path_text).expanduser()
    if not path.is_absolute():
        path = BASE_DIR / path
    return path


def extract_json_object(raw_text: str) -> Dict[str, Any]:
    text = raw_text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\\s*", "", text)
        text = re.sub(r"\\s*```$", "", text)

    try:
        value = json.loads(text)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise RuntimeError("Could not find JSON object in model output.")

    candidate = text[start : end + 1]
    value = json.loads(candidate)
    if not isinstance(value, dict):
        raise RuntimeError("Extracted JSON is not an object.")
    return value


def build_chat_extract_messages(chat_text: str) -> List[Dict[str, str]]:
    system_prompt = (
        "You are an information extraction assistant for a daily planner. "
        "Extract user chat text into structured JSON only. "
        "Do not include markdown or extra words."
    )

    schema = {
        "profile_updates": ["string"],
        "goals_updates": ["string"],
        "preferences_updates": ["string"],
        "fixed_events_updates": ["string"],
        "today_notes_updates": ["string"],
        "state_updates": ["string"],
        "feedback": {
            "date": "YYYY-MM-DD or empty",
            "completion": "string",
            "mood": "string",
            "notes": "string",
        },
        "summary": "one line summary",
    }

    user_payload = {
        "today": dt.date.today().isoformat(),
        "chat_text": chat_text,
        "requirements": [
            "Return valid JSON object only.",
            "If a field has no data, use empty array or empty string.",
            "Put short bullet-ready items in updates arrays.",
            "Only fill feedback if the chat includes completion/mood/reflection signals.",
        ],
        "output_schema": schema,
    }

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, indent=2)},
    ]


def split_chat_sections(chat_text: str) -> tuple[str, str]:
    """Split chat window into structured form section and free message section."""
    if "### Daily Template" in chat_text and "### Free Message" in chat_text:
        after_daily = chat_text.split("### Daily Template", 1)[1]
        form_text, free_text = after_daily.split("### Free Message", 1)
        return form_text.strip(), free_text.strip()

    if "## Daily Template" in chat_text and "## Free Message" in chat_text:
        after_daily = chat_text.split("## Daily Template", 1)[1]
        form_text, free_text = after_daily.split("## Free Message", 1)
        return form_text.strip(), free_text.strip()

    # Backward compatibility with old template.
    if "## New Message" in chat_text:
        return "", chat_text.split("## New Message", 1)[1].strip()

    return "", chat_text.strip()


def has_meaningful_chat_input(chat_text: str) -> bool:
    if not chat_text.strip():
        return False

    form_text, free_text = split_chat_sections(chat_text)
    placeholder = "把临时想法、背景信息、感受直接写在这里。"

    if free_text and free_text.strip() and free_text.strip() != placeholder:
        return True

    if not form_text.strip():
        return False

    parsed = parse_daily_template(form_text)
    list_keys = [
        "profile_updates",
        "goals_updates",
        "preferences_updates",
        "fixed_events_updates",
        "today_notes_updates",
    ]
    if any(parsed.get(key) for key in list_keys):
        return True

    feedback = parsed.get("feedback") or {}
    return any(str(feedback.get(k, "")).strip() for k in ["date", "completion", "mood", "notes"])


def _get_field_value(lines: List[str], field_name: str) -> str:
    prefix = f"- {field_name}:"
    for line in lines:
        if line.strip().startswith(prefix):
            return line.split(":", 1)[1].strip()
    return ""


def _collect_list_under_heading(lines: List[str], heading: str) -> List[str]:
    target = f"### {heading}"
    alt_target = f"#### {heading}"
    collecting = False
    items: List[str] = []

    for raw in lines:
        line = raw.strip()
        if line in {target, alt_target}:
            collecting = True
            continue

        if collecting and (line.startswith("### ") or line.startswith("#### ")):
            break

        if collecting and line.startswith("- "):
            item = line[2:].strip()
            if item:
                items.append(item)

    return items


def parse_daily_template(form_text: str) -> Dict[str, Any]:
    lines = form_text.splitlines()

    date_text = _get_field_value(lines, "Date")
    completion = _get_field_value(lines, "Completion")
    mood = _get_field_value(lines, "Mood")

    must_dos = _collect_list_under_heading(lines, "Must-Dos")
    fixed_events = _collect_list_under_heading(lines, "Fixed Events")
    constraints = _collect_list_under_heading(lines, "Constraints")
    preference_tweaks = _collect_list_under_heading(lines, "Preference Tweaks")
    reflections = _collect_list_under_heading(lines, "Reflection")

    notes_parts = []
    if reflections:
        notes_parts.extend(reflections)
    if constraints:
        notes_parts.append("constraints: " + " | ".join(constraints))
    notes_text = " | ".join(notes_parts)

    feedback: Dict[str, str] = {
        "date": date_text,
        "completion": completion,
        "mood": mood,
        "notes": notes_text,
    }

    return {
        "profile_updates": [],
        "goals_updates": must_dos,
        "preferences_updates": preference_tweaks,
        "fixed_events_updates": fixed_events,
        "today_notes_updates": constraints,
        "state_updates": [],
        "feedback": feedback,
        "summary": "parsed from daily template",
    }


def merge_extracted(primary: Dict[str, Any], secondary: Dict[str, Any]) -> Dict[str, Any]:
    result = {
        "profile_updates": [],
        "goals_updates": [],
        "preferences_updates": [],
        "fixed_events_updates": [],
        "today_notes_updates": [],
        "state_updates": [],
        "feedback": {
            "date": "",
            "completion": "",
            "mood": "",
            "notes": "",
        },
        "summary": "",
    }

    list_keys = [
        "profile_updates",
        "goals_updates",
        "preferences_updates",
        "fixed_events_updates",
        "today_notes_updates",
        "state_updates",
    ]

    for key in list_keys:
        merged_items = (primary.get(key) or []) + (secondary.get(key) or [])
        deduped = []
        seen = set()
        for item in merged_items:
            text = str(item).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            deduped.append(text)
        result[key] = deduped

    p_feedback = primary.get("feedback") or {}
    s_feedback = secondary.get("feedback") or {}
    result["feedback"] = {
        "date": str(p_feedback.get("date", "") or s_feedback.get("date", "")).strip(),
        "completion": str(p_feedback.get("completion", "") or s_feedback.get("completion", "")).strip(),
        "mood": str(p_feedback.get("mood", "") or s_feedback.get("mood", "")).strip(),
        "notes": " | ".join(
            [
                text
                for text in [
                    str(p_feedback.get("notes", "")).strip(),
                    str(s_feedback.get("notes", "")).strip(),
                ]
                if text
            ]
        ),
    }

    p_summary = str(primary.get("summary", "")).strip()
    s_summary = str(secondary.get("summary", "")).strip()
    result["summary"] = " | ".join([text for text in [p_summary, s_summary] if text])
    return result


def append_updates(path: Path, section_title: str, updates: List[str]) -> None:
    cleaned = [item.strip() for item in updates if item and item.strip()]
    if not cleaned:
        return

    block = [f"\n## {section_title} ({now_text()})\n"]
    for item in cleaned:
        block.append(f"- {item}\n")

    with path.open("a", encoding="utf-8") as f:
        f.writelines(block)


def apply_chat_updates(extracted: Dict[str, Any]) -> List[str]:
    actions: List[str] = []

    profile_updates = extracted.get("profile_updates") or []
    goals_updates = extracted.get("goals_updates") or []
    preferences_updates = extracted.get("preferences_updates") or []
    fixed_events_updates = extracted.get("fixed_events_updates") or []
    today_notes_updates = extracted.get("today_notes_updates") or []
    state_updates = extracted.get("state_updates") or []

    append_updates(PROFILE_FILE, "From Chat", profile_updates)
    if profile_updates:
        actions.append(f"profile.md +{len(profile_updates)}")

    append_updates(GOALS_FILE, "From Chat", goals_updates)
    if goals_updates:
        actions.append(f"goals.md +{len(goals_updates)}")

    append_updates(PREFERENCES_FILE, "From Chat", preferences_updates)
    if preferences_updates:
        actions.append(f"preferences.md +{len(preferences_updates)}")

    append_updates(FIXED_EVENTS_FILE, "From Chat", fixed_events_updates)
    if fixed_events_updates:
        actions.append(f"fixed_events.md +{len(fixed_events_updates)}")

    append_updates(TODAY_NOTES_FILE, "From Chat", today_notes_updates)
    if today_notes_updates:
        actions.append(f"today_notes.md +{len(today_notes_updates)}")

    append_updates(STATE_FILE, "From Chat", state_updates)
    if state_updates:
        actions.append(f"state.md +{len(state_updates)}")

    feedback = extracted.get("feedback") or {}
    completion = str(feedback.get("completion", "")).strip()
    mood = str(feedback.get("mood", "")).strip()
    notes = str(feedback.get("notes", "")).strip()
    feedback_date = str(feedback.get("date", "")).strip() or dt.date.today().isoformat()
    if completion and mood:
        record_feedback(feedback_date, completion, mood, notes)
        actions.append(f"feedback {feedback_date}")

    return actions


def _extract_sync_input_from_today_window(window_text: str) -> str:
    marker = "## Sync Input"
    if marker in window_text:
        return window_text.split(marker, 1)[1].strip()
    return window_text.strip()


def clear_sync_input_in_today_window() -> None:
    text = read_text_if_exists(TODAY_WINDOW_FILE)
    marker = "## Sync Input"
    if marker not in text:
        return
    prefix = text.split(marker, 1)[0].rstrip() + "\n\n"
    TODAY_WINDOW_FILE.write_text(prefix + sync_input_template(), encoding="utf-8")


def write_sync_history(record: Dict[str, Any]) -> Path:
    date_key = dt.date.today().isoformat()
    path = SYNC_HISTORY_DIR / f"{date_key}.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return path


def archive_chat(chat_text: str) -> Path:
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = CHAT_ARCHIVE_DIR / f"{stamp}.md"
    path.write_text(chat_text.strip() + "\n", encoding="utf-8")
    return path


def archive_today_window(target_date: dt.date | None = None) -> Path:
    date_value = target_date or dt.date.today()
    if TODAY_WINDOW_FILE.exists():
        content = read_text_if_exists(TODAY_WINDOW_FILE)
    else:
        content = ""

    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = TODAY_WINDOW_ARCHIVE_DIR / f"{date_value.isoformat()}_{stamp}.md"
    body = content if content else "# Today Window\n\n(no content)\n"
    path.write_text(body.strip() + "\n", encoding="utf-8")
    return path


def deepseek_chat(messages: List[Dict[str, str]], model: str, temperature: float = 0.3) -> str:
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Missing DEEPSEEK_API_KEY environment variable.")

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }

    req = request.Request(
        DEEPSEEK_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=90) as resp:
            raw = resp.read().decode("utf-8")
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"DeepSeek API HTTPError: {exc.code} {detail}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"DeepSeek API connection error: {exc}") from exc

    data = json.loads(raw)
    choices = data.get("choices", [])
    if not choices:
        raise RuntimeError(f"Unexpected DeepSeek response: {raw}")

    message = choices[0].get("message", {})
    content = message.get("content", "").strip()
    if not content:
        raise RuntimeError(f"DeepSeek returned empty content: {raw}")

    return content


def save_plan(target_date: dt.date, content: str) -> Path:
    plan_path = DAILY_PLAN_DIR / f"{target_date.isoformat()}.md"
    plan_path.write_text(content + "\n", encoding="utf-8")
    return plan_path


def _normalize_task_text(text: str) -> str:
    t = text.strip()
    t = re.sub(r"^\d+[\.)]\s*", "", t)
    return t.strip()


def _is_actionable_task(task: str) -> bool:
    skip_keywords = ["休息", "午餐", "晚餐", "睡眠", "自由时间", "准备休息", "补水", "放松"]
    return task and not any(k in task for k in skip_keywords)


def extract_tasks_from_plan(plan_text: str) -> tuple[List[str], List[str]]:
    top_tasks: List[str] = []
    other_tasks: List[str] = []

    # Parse the explicit top-3 section first.
    m_top = re.search(r"##\s*今日三件最重要的事\n(.*?)(\n##\s|$)", plan_text, flags=re.S)
    if m_top:
        block = m_top.group(1)
        for line in block.splitlines():
            line = line.strip()
            if not line:
                continue
            if re.match(r"^\d+[\.)]\s+", line):
                task = _normalize_task_text(line)
                if task and task not in top_tasks:
                    top_tasks.append(task)

    # Parse task column from schedule table.
    for line in plan_text.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) < 3:
            continue
        if cells[0] in {"时间", "------", "------:"}:
            continue
        if set("".join(cells)) <= {"-", ":"}:
            continue
        task = _normalize_task_text(cells[1])
        if task and _is_actionable_task(task) and task not in other_tasks and task not in top_tasks:
            other_tasks.append(task)

    if not top_tasks:
        top_tasks = other_tasks[:3]
        other_tasks = other_tasks[3:]

    return top_tasks[:3], other_tasks[:8]


def parse_checkbox_state(window_text: str) -> Dict[str, bool]:
    states: Dict[str, bool] = {}
    for line in window_text.splitlines():
        m = re.match(r"^- \[( |x|X)\]\s+(.*)$", line.strip())
        if not m:
            continue
        checked = m.group(1).lower() == "x"
        task = _normalize_task_text(m.group(2))
        if task:
            states[task] = checked
    return states


def replace_section(text: str, section_title: str, next_section_title: str, new_lines: List[str]) -> str:
    start = rf"##\s*{re.escape(section_title)}\n"
    end = rf"\n##\s*{re.escape(next_section_title)}"
    pattern = re.compile(start + r".*?(?=" + end + r")", flags=re.S)
    replacement = f"## {section_title}\n" + "\n".join(new_lines).rstrip() + "\n"
    if pattern.search(text):
        return pattern.sub(replacement, text, count=1)
    return text


def fill_today_window_from_plan(target_date: dt.date, plan_text: str) -> Path:
    if TODAY_WINDOW_FILE.exists():
        window_text = TODAY_WINDOW_FILE.read_text(encoding="utf-8")
    else:
        window_text = today_window_template(target_date)

    states = parse_checkbox_state(window_text)
    top_tasks, other_tasks = extract_tasks_from_plan(plan_text)

    if f"# Today Window ({target_date.isoformat()})" not in window_text:
        window_text = today_window_template(target_date)
        states = {}

    def to_checkbox(task: str) -> str:
        checked = states.get(task, False)
        mark = "x" if checked else " "
        return f"- [{mark}] {task}"

    top_lines = [to_checkbox(t) for t in top_tasks] or ["- [ ] "]
    other_lines = [to_checkbox(t) for t in other_tasks] or ["- [ ] "]

    updated = replace_section(window_text, "今日三件最重要的事", "其他任务", top_lines)
    updated = replace_section(updated, "其他任务", "今日反馈", other_lines)
    TODAY_WINDOW_FILE.write_text(updated.rstrip() + "\n", encoding="utf-8")
    return TODAY_WINDOW_FILE


def record_feedback(date_text: str, completion: str, mood: str, notes: str) -> Path:
    date_obj = dt.datetime.strptime(date_text, "%Y-%m-%d").date()

    entry = {
        "date": date_obj.isoformat(),
        "completion": completion,
        "mood": mood,
        "notes": notes,
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
    }

    with FEEDBACK_JSONL.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    feedback_md = (
        f"# 反馈 {entry['date']}\n\n"
        f"- Completion: {completion}\n"
        f"- Mood: {mood}\n"
        f"- Notes: {notes}\n"
    )
    feedback_path = FEEDBACK_DIR / f"{entry['date']}.md"
    feedback_path.write_text(feedback_md, encoding="utf-8")
    return feedback_path


def cmd_init(_: argparse.Namespace) -> None:
    ensure_structure()
    print("Initialized schedule agent files under ./user_data ./plans ./run_data")


def cmd_plan(args: argparse.Namespace) -> None:
    ensure_structure()
    target_date = parse_date(args.date)
    messages = build_messages(target_date)
    content = deepseek_chat(messages, model=args.model, temperature=args.temperature)
    path = save_plan(target_date, content)
    window_path = fill_today_window_from_plan(target_date, content)

    print(content)
    print(f"\nSaved plan to: {path}")
    print(f"Updated today window: {window_path}")


def cmd_feedback(args: argparse.Namespace) -> None:
    ensure_structure()
    path = record_feedback(
        date_text=args.date,
        completion=args.completion,
        mood=args.mood,
        notes=args.notes,
    )
    print(f"Feedback saved to: {path}")


def cmd_status(_: argparse.Namespace) -> None:
    ensure_structure()
    feedback = load_feedback(limit=5)
    recent_plans = load_recent_plans(limit=3)

    print("Recent feedback:")
    if not feedback:
        print("- None")
    else:
        for item in feedback:
            print(f"- {item.get('date')}: completion={item.get('completion')} mood={item.get('mood')}")

    print("\nRecent plans:")
    if not recent_plans:
        print("- None")
    else:
        for plan in recent_plans:
            print(f"- {plan['date']}")


def cmd_sync_chat(args: argparse.Namespace) -> None:
    ensure_structure()
    chat_text = read_text_if_exists(TODAY_WINDOW_FILE)
    if not chat_text:
        raise RuntimeError("today_window.md is empty. Re-run init or restore template.")

    sync_input = _extract_sync_input_from_today_window(chat_text)
    if not has_meaningful_chat_input(sync_input):
        print("No new sync input in today_window.md")
        return

    form_text, free_text = split_chat_sections(sync_input)

    form_extracted = parse_daily_template(form_text) if form_text else {
        "profile_updates": [],
        "goals_updates": [],
        "preferences_updates": [],
        "fixed_events_updates": [],
        "today_notes_updates": [],
        "state_updates": [],
        "feedback": {"date": "", "completion": "", "mood": "", "notes": ""},
        "summary": "",
    }

    free_extracted = {
        "profile_updates": [],
        "goals_updates": [],
        "preferences_updates": [],
        "fixed_events_updates": [],
        "today_notes_updates": [],
        "state_updates": [],
        "feedback": {"date": "", "completion": "", "mood": "", "notes": ""},
        "summary": "",
    }

    if free_text and free_text != "把临时想法、背景信息、感受直接写在这里。":
        messages = build_chat_extract_messages(free_text)
        raw = deepseek_chat(messages, model=args.model, temperature=args.temperature)
        free_extracted = extract_json_object(raw)

    extracted = merge_extracted(form_extracted, free_extracted)
    actions = apply_chat_updates(extracted)
    archive_path = archive_chat(sync_input)
    clear_sync_input_in_today_window()
    sync_log = write_sync_history(
        {
            "timestamp": now_text(),
            "summary": str(extracted.get("summary", "")).strip(),
            "actions": actions,
        }
    )

    print("Chat synced.")
    summary = str(extracted.get("summary", "")).strip()
    if summary:
        print(f"Summary: {summary}")

    if actions:
        print("Applied updates:")
        for action in actions:
            print(f"- {action}")
    else:
        print("Applied updates:\n- None")

    print(f"Archived chat: {archive_path}")
    print(f"Sync history: {sync_log}")

    if args.plan_after:
        target_date = parse_date(args.date)
        plan_messages = build_messages(target_date)
        content = deepseek_chat(plan_messages, model=args.model, temperature=args.temperature)
        plan_path = save_plan(target_date, content)
        window_path = fill_today_window_from_plan(target_date, content)
        print(f"Generated plan: {plan_path}")
        print(f"Updated today window: {window_path}")


def cmd_autopilot(args: argparse.Namespace) -> None:
    ensure_structure()
    current_date = parse_date(args.current_date) if args.current_date else dt.date.today()
    plan_date = parse_date(args.plan_date) if args.plan_date else (current_date + dt.timedelta(days=1))

    chat_actions: List[str] = []
    chat_summary = ""
    chat_synced = False

    chat_text = read_text_if_exists(TODAY_WINDOW_FILE)
    sync_input = _extract_sync_input_from_today_window(chat_text)
    if has_meaningful_chat_input(sync_input):
        form_text, free_text = split_chat_sections(sync_input)

        form_extracted = parse_daily_template(form_text) if form_text else {
            "profile_updates": [],
            "goals_updates": [],
            "preferences_updates": [],
            "fixed_events_updates": [],
            "today_notes_updates": [],
            "state_updates": [],
            "feedback": {"date": "", "completion": "", "mood": "", "notes": ""},
            "summary": "",
        }

        free_extracted = {
            "profile_updates": [],
            "goals_updates": [],
            "preferences_updates": [],
            "fixed_events_updates": [],
            "today_notes_updates": [],
            "state_updates": [],
            "feedback": {"date": "", "completion": "", "mood": "", "notes": ""},
            "summary": "",
        }

        if free_text and free_text != "把临时想法、背景信息、感受直接写在这里。":
            extract_messages = build_chat_extract_messages(free_text)
            raw = deepseek_chat(extract_messages, model=args.model, temperature=args.temperature)
            free_extracted = extract_json_object(raw)

        extracted = merge_extracted(form_extracted, free_extracted)
        chat_actions = apply_chat_updates(extracted)
        chat_summary = str(extracted.get("summary", "")).strip()
        archive_chat(sync_input)
        clear_sync_input_in_today_window()
        write_sync_history(
            {
                "timestamp": now_text(),
                "summary": chat_summary,
                "actions": chat_actions,
                "source": "autopilot",
            }
        )
        chat_synced = True

    plan_messages = build_messages(plan_date)
    plan_content = deepseek_chat(plan_messages, model=args.model, temperature=args.temperature)
    plan_path = save_plan(plan_date, plan_content)

    window_path = fill_today_window_from_plan(plan_date, plan_content)

    archived_today_window = archive_today_window(target_date=current_date)

    weekly_path: Path | None = None
    if args.weekly:
        weekly_end = current_date
        weekly_start = weekly_end - dt.timedelta(days=args.weekly_days - 1)
        weekly_messages = build_weekly_review_messages(weekly_start, weekly_end)
        weekly_content = deepseek_chat(weekly_messages, model=args.model, temperature=args.weekly_temperature)
        weekly_filename = f"{weekly_start.isoformat()}_to_{weekly_end.isoformat()}.md"
        weekly_path = WEEKLY_PLAN_DIR / weekly_filename
        weekly_path.write_text(weekly_content.strip() + "\n", encoding="utf-8")

    cleanup_stats: Dict[str, int] | None = None
    if args.auto_cleanup:
        cleanup_stats = run_cleanup(
            keep_days=args.cleanup_keep_days,
            keep_feedback=args.cleanup_keep_feedback,
            keep_chat_sections=args.cleanup_keep_chat_sections,
        )

    print("Autopilot done.")
    print(f"- Plan generated: {plan_path}")
    print(f"- Today window updated: {window_path}")
    print(f"- Today window archived: {archived_today_window}")
    print(f"- New today window date: {plan_date.isoformat()}")

    if chat_synced:
        print("- Chat synced: yes")
        if chat_summary:
            print(f"- Chat summary: {chat_summary}")
        if chat_actions:
            print("- Chat updates:")
            for action in chat_actions:
                print(f"  {action}")
    else:
        print("- Chat synced: no (no new input)")

    if weekly_path:
        print(f"- Weekly review: {weekly_path}")

    if cleanup_stats:
        print("- Auto cleanup:")
        print(f"  removed_files={cleanup_stats['removed_files']}")
        print(f"  dropped_feedback={cleanup_stats['dropped_feedback']}")
        print(f"  compacted_user_files={cleanup_stats['compacted_user_files']}")


def cmd_window_refresh(args: argparse.Namespace) -> None:
    ensure_structure()
    target_date = parse_date(args.date) if args.date else dt.date.today()
    archived = archive_today_window(target_date=target_date)
    next_date = target_date + dt.timedelta(days=1)
    TODAY_WINDOW_FILE.write_text(today_window_template(next_date), encoding="utf-8")
    print(f"Archived today window: {archived}")
    print(f"Created new today window for: {next_date.isoformat()}")


def cmd_weekly_review(args: argparse.Namespace) -> None:
    ensure_structure()
    end_date = parse_date(args.end_date) if args.end_date else dt.date.today()
    start_date = end_date - dt.timedelta(days=args.days - 1)

    messages = build_weekly_review_messages(start_date, end_date)
    content = deepseek_chat(messages, model=args.model, temperature=args.temperature)

    filename = f"{start_date.isoformat()}_to_{end_date.isoformat()}.md"
    out_path = WEEKLY_PLAN_DIR / filename
    out_path.write_text(content.strip() + "\n", encoding="utf-8")

    print(content)
    print(f"\nSaved weekly review to: {out_path}")


def cmd_adjust_today(args: argparse.Namespace) -> None:
    ensure_structure()
    target_date = dt.datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else dt.date.today()

    input_path = resolve_input_file(args.input_file)
    if not input_path.exists():
        raise RuntimeError(f"Input file not found: {input_path}")

    incident_text = read_text_if_exists(input_path)
    if not incident_text:
        raise RuntimeError(f"Input file is empty: {input_path}")

    plan_path = DAILY_PLAN_DIR / f"{target_date.isoformat()}.md"
    current_plan = read_text_if_exists(plan_path)
    today_window = read_text_if_exists(TODAY_WINDOW_FILE)

    messages = build_adjust_today_messages(target_date, incident_text, current_plan, today_window)
    updated_plan = deepseek_chat(messages, model=args.model, temperature=args.temperature)

    if plan_path.exists():
        stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = SNAPSHOTS_DIR / f"daily_{target_date.isoformat()}_before_adjust_{stamp}.md"
        backup_path.write_text(current_plan + "\n", encoding="utf-8")

    plan_path.write_text(updated_plan.strip() + "\n", encoding="utf-8")
    window_path = fill_today_window_from_plan(target_date, updated_plan)

    sync_log = write_sync_history(
        {
            "timestamp": now_text(),
            "source": "adjust-today",
            "date": target_date.isoformat(),
            "input_file": str(input_path),
        }
    )

    print(updated_plan)
    print(f"\nAdjusted plan saved to: {plan_path}")
    print(f"Updated today window: {window_path}")
    print(f"Sync history: {sync_log}")


def run_cleanup(keep_days: int, keep_feedback: int, keep_chat_sections: int) -> Dict[str, int]:
    removed = 0
    removed += prune_old_files(DAILY_PLAN_DIR, keep_days=keep_days)
    removed += prune_old_files(WEEKLY_PLAN_DIR, keep_days=keep_days)
    removed += prune_old_files(MONTHLY_PLAN_DIR, keep_days=keep_days)
    removed += prune_old_files(CHAT_ARCHIVE_DIR, keep_days=keep_days)
    removed += prune_old_files(SYNC_HISTORY_DIR, keep_days=keep_days)
    removed += prune_old_files(TODAY_WINDOW_ARCHIVE_DIR, keep_days=keep_days)
    removed += prune_old_files(FEEDBACK_DIR, keep_days=keep_days)

    dropped_feedback = truncate_feedback_jsonl(max_entries=keep_feedback)

    compacted_files = 0
    for path in [PROFILE_FILE, GOALS_FILE, PREFERENCES_FILE, FIXED_EVENTS_FILE, TODAY_NOTES_FILE, STATE_FILE]:
        if compact_from_chat_sections(path, keep_last=keep_chat_sections):
            compacted_files += 1

    return {
        "removed_files": removed,
        "dropped_feedback": dropped_feedback,
        "compacted_user_files": compacted_files,
    }


def cmd_cleanup(args: argparse.Namespace) -> None:
    ensure_structure()
    stats = run_cleanup(
        keep_days=args.keep_days,
        keep_feedback=args.keep_feedback,
        keep_chat_sections=args.keep_chat_sections,
    )

    print("Cleanup done.")
    print(f"- Removed old files: {stats['removed_files']}")
    print(f"- Truncated feedback entries: {stats['dropped_feedback']}")
    print(f"- Compacted user files: {stats['compacted_user_files']}")


def cmd_reset_data(args: argparse.Namespace) -> None:
    ensure_structure()
    if not args.yes:
        raise RuntimeError("This command is destructive. Re-run with --yes")

    snapshot_path: Path | None = None
    if not args.no_snapshot:
        snapshot_path = snapshot_before_reset()

    for path, content in default_user_files().items():
        path.write_text(content, encoding="utf-8")

    TODAY_WINDOW_FILE.write_text(today_window_template(dt.date.today()), encoding="utf-8")
    FEEDBACK_JSONL.write_text("", encoding="utf-8")

    clear_directory(FEEDBACK_DIR)
    clear_directory(CHAT_ARCHIVE_DIR)
    clear_directory(SYNC_HISTORY_DIR)
    clear_directory(TODAY_WINDOW_ARCHIVE_DIR)
    clear_directory(DAILY_PLAN_DIR, keep_names={".gitkeep"})
    clear_directory(WEEKLY_PLAN_DIR, keep_names={".gitkeep"})
    clear_directory(MONTHLY_PLAN_DIR, keep_names={".gitkeep"})

    if args.include_snapshots:
        clear_directory(SNAPSHOTS_DIR)

    print("Reset done.")
    if snapshot_path:
        print(f"- Snapshot: {snapshot_path}")
    print("- user_data reset to template")
    print("- plans and run_data logs cleared")


def build_parser(config: Dict[str, Any]) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DeepSeek daily schedule agent")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Initialize local data templates")
    p_init.set_defaults(func=cmd_init)

    p_plan = sub.add_parser("plan", help="Generate next-day plan with DeepSeek")
    p_plan.add_argument("--date", help="Target date in YYYY-MM-DD; default is tomorrow")
    p_plan.add_argument(
        "--model",
        default=cfg_get(config, "model", "default_model", DEFAULT_MODEL),
        help="DeepSeek model name",
    )
    p_plan.add_argument(
        "--temperature",
        type=float,
        default=cfg_get(config, "model", "plan_temperature", 0.3),
        help="Sampling temperature",
    )
    p_plan.set_defaults(func=cmd_plan)

    p_feedback = sub.add_parser("feedback", help="Record daily feedback")
    p_feedback.add_argument("--date", required=True, help="Feedback date in YYYY-MM-DD")
    p_feedback.add_argument(
        "--completion",
        required=True,
        help="Completion summary, e.g. 70%% or done 3/5",
    )
    p_feedback.add_argument("--mood", required=True, help="Mood/energy summary")
    p_feedback.add_argument("--notes", default="", help="Free-text reflection")
    p_feedback.set_defaults(func=cmd_feedback)

    p_status = sub.add_parser("status", help="Show recent plans and feedback")
    p_status.set_defaults(func=cmd_status)

    p_sync = sub.add_parser("sync-chat", help="Parse today_window sync input and update local context files")
    p_sync.add_argument(
        "--model",
        default=cfg_get(config, "model", "default_model", DEFAULT_MODEL),
        help="DeepSeek model name",
    )
    p_sync.add_argument(
        "--temperature",
        type=float,
        default=cfg_get(config, "model", "sync_chat_temperature", 0.1),
        help="Sampling temperature",
    )
    p_sync.add_argument("--plan-after", action="store_true", help="Generate plan after syncing chat")
    p_sync.add_argument("--date", help="Plan date in YYYY-MM-DD when using --plan-after")
    p_sync.set_defaults(func=cmd_sync_chat)

    p_window = sub.add_parser("window-refresh", help="Archive today_window and create a fresh one for next day")
    p_window.add_argument("--date", help="Current window date in YYYY-MM-DD; default is today")
    p_window.set_defaults(func=cmd_window_refresh)

    p_weekly = sub.add_parser("weekly-review", help="Generate weekly review from historical plans and feedback")
    p_weekly.add_argument("--end-date", help="Review end date in YYYY-MM-DD; default is today")
    p_weekly.add_argument("--days", type=int, default=7, help="Number of days to review, default 7")
    p_weekly.add_argument(
        "--model",
        default=cfg_get(config, "model", "default_model", DEFAULT_MODEL),
        help="DeepSeek model name",
    )
    p_weekly.add_argument(
        "--temperature",
        type=float,
        default=cfg_get(config, "model", "weekly_review_temperature", 0.2),
        help="Sampling temperature",
    )
    p_weekly.set_defaults(func=cmd_weekly_review)

    p_adjust = sub.add_parser("adjust-today", help="Adjust today's plan and today_window based on an incident file")
    p_adjust.add_argument("--input-file", help="Incident/context file path; default is ./adjust.md")
    p_adjust.add_argument("--date", help="Target date in YYYY-MM-DD; default is today")
    p_adjust.add_argument(
        "--model",
        default=cfg_get(config, "model", "default_model", DEFAULT_MODEL),
        help="DeepSeek model name",
    )
    p_adjust.add_argument(
        "--temperature",
        type=float,
        default=cfg_get(config, "model", "plan_temperature", 0.3),
        help="Sampling temperature",
    )
    p_adjust.set_defaults(func=cmd_adjust_today)

    p_auto = sub.add_parser("autopilot", help="Run daily pipeline: sync chat, plan next day, refresh today window")
    p_auto.add_argument("--current-date", help="Current date in YYYY-MM-DD; default is today")
    p_auto.add_argument("--plan-date", help="Plan date in YYYY-MM-DD; default is current date + 1")
    p_auto.add_argument(
        "--model",
        default=cfg_get(config, "model", "default_model", DEFAULT_MODEL),
        help="DeepSeek model name",
    )
    p_auto.add_argument(
        "--temperature",
        type=float,
        default=cfg_get(config, "model", "autopilot_temperature", 0.2),
        help="Sampling temperature for chat/plan",
    )
    p_auto.add_argument("--weekly", action="store_true", help="Also generate weekly review")
    p_auto.add_argument(
        "--weekly-days",
        type=int,
        default=cfg_get(config, "autopilot", "weekly_days", 7),
        help="Days for weekly review window",
    )
    p_auto.add_argument(
        "--weekly-temperature",
        type=float,
        default=cfg_get(config, "model", "weekly_review_temperature", 0.2),
        help="Sampling temperature for weekly review",
    )
    p_auto.add_argument(
        "--auto-cleanup",
        action=argparse.BooleanOptionalAction,
        default=cfg_get(config, "autopilot", "auto_cleanup", True),
        help="Run cleanup at the end of autopilot (enabled by default)",
    )
    p_auto.add_argument(
        "--cleanup-keep-days",
        type=int,
        default=cfg_get(config, "cleanup", "keep_days", DEFAULT_KEEP_DAYS),
        help="Retention days used by autopilot auto cleanup",
    )
    p_auto.add_argument(
        "--cleanup-keep-feedback",
        type=int,
        default=cfg_get(config, "cleanup", "keep_feedback", DEFAULT_KEEP_FEEDBACK),
        help="Feedback entries retained by autopilot auto cleanup",
    )
    p_auto.add_argument(
        "--cleanup-keep-chat-sections",
        type=int,
        default=cfg_get(config, "cleanup", "keep_chat_sections", DEFAULT_KEEP_CHAT_SECTIONS),
        help="From Chat sections retained by autopilot auto cleanup",
    )
    p_auto.set_defaults(func=cmd_autopilot)

    p_cleanup = sub.add_parser("cleanup", help="Prune old runtime data and compact accumulated notes")
    p_cleanup.add_argument(
        "--keep-days",
        type=int,
        default=cfg_get(config, "cleanup", "keep_days", DEFAULT_KEEP_DAYS),
        help="Keep files modified within this many days",
    )
    p_cleanup.add_argument(
        "--keep-feedback",
        type=int,
        default=cfg_get(config, "cleanup", "keep_feedback", DEFAULT_KEEP_FEEDBACK),
        help="Keep latest N feedback entries",
    )
    p_cleanup.add_argument(
        "--keep-chat-sections",
        type=int,
        default=cfg_get(config, "cleanup", "keep_chat_sections", DEFAULT_KEEP_CHAT_SECTIONS),
        help="Keep latest N 'From Chat' sections in user markdown files",
    )
    p_cleanup.set_defaults(func=cmd_cleanup)

    p_reset = sub.add_parser("reset-data", help="Fully clear user/runtime/plan data and reinitialize templates")
    p_reset.add_argument("--yes", action="store_true", help="Required confirmation for destructive reset")
    p_reset.add_argument("--no-snapshot", action="store_true", help="Do not create backup snapshot before reset")
    p_reset.add_argument("--include-snapshots", action="store_true", help="Also clear files under run_data/snapshots")
    p_reset.set_defaults(func=cmd_reset_data)

    return parser


def main() -> None:
    load_env_file(BASE_DIR / ".env")
    ensure_structure()
    config = load_agent_config()
    parser = build_parser(config)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
