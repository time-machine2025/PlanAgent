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
from typing import Any, Dict, List
from urllib import error, request
import re

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
PLANS_DIR = DATA_DIR / "plans"
FEEDBACK_DIR = DATA_DIR / "feedback"
FEEDBACK_JSONL = DATA_DIR / "feedback_log.jsonl"
CHAT_WINDOW_FILE = DATA_DIR / "chat_window.md"
CHAT_ARCHIVE_DIR = DATA_DIR / "chat_archive"

DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
DEFAULT_MODEL = "deepseek-chat"


def chat_window_template() -> str:
    return (
        "# Chat Window\n\n"
        "在这个文件里你可以同时使用两种输入：\n"
        "1) Daily Template：每天固定信息（结构化）\n"
        "2) Free Message：随手说（非结构化）\n\n"
        "## Daily Template\n"
        "- Date: \n"
        "- Completion: \n"
        "- Mood: \n\n"
        "### Must-Dos\n"
        "- \n\n"
        "### Fixed Events\n"
        "- \n\n"
        "### Constraints\n"
        "- \n\n"
        "### Preference Tweaks\n"
        "- \n\n"
        "### Reflection\n"
        "- \n\n"
        "## Free Message\n"
        "把临时想法、背景信息、感受直接写在这里。\n"
    )


def ensure_structure() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PLANS_DIR.mkdir(parents=True, exist_ok=True)
    FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)
    CHAT_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

    defaults = {
        DATA_DIR / "profile.md": "# Profile\n\n- Name:\n- Work style:\n- Energy peak time:\n",
        DATA_DIR / "goals.md": "# Goals\n\n## This week\n- \n\n## This month\n- \n",
        DATA_DIR / "preferences.md": "# Preferences\n\n- Preferred schedule style:\n- Break frequency:\n- Deep work duration:\n",
        DATA_DIR / "fixed_events.md": "# Fixed Events\n\n- 09:30-10:00 Daily standup\n",
        DATA_DIR / "today_notes.md": "# Today Notes\n\n- Any temporary constraints or special events today.\n",
        CHAT_WINDOW_FILE: chat_window_template(),
    }

    for path, content in defaults.items():
        if not path.exists():
            path.write_text(content, encoding="utf-8")

    if not FEEDBACK_JSONL.exists():
        FEEDBACK_JSONL.write_text("", encoding="utf-8")


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
    plans = sorted(PLANS_DIR.glob("*.md"))
    recent = plans[-limit:]
    result: List[Dict[str, str]] = []
    for path in recent:
        result.append({"date": path.stem, "content": read_text_if_exists(path)})
    return result


def build_messages(target_date: dt.date) -> List[Dict[str, str]]:
    profile = read_text_if_exists(DATA_DIR / "profile.md")
    goals = read_text_if_exists(DATA_DIR / "goals.md")
    preferences = read_text_if_exists(DATA_DIR / "preferences.md")
    fixed_events = read_text_if_exists(DATA_DIR / "fixed_events.md")
    today_notes = read_text_if_exists(DATA_DIR / "today_notes.md")

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
    if "## Daily Template" in chat_text and "## Free Message" in chat_text:
        after_daily = chat_text.split("## Daily Template", 1)[1]
        form_text, free_text = after_daily.split("## Free Message", 1)
        return form_text.strip(), free_text.strip()

    # Backward compatibility with old template.
    if "## New Message" in chat_text:
        return "", chat_text.split("## New Message", 1)[1].strip()

    return "", chat_text.strip()


def _get_field_value(lines: List[str], field_name: str) -> str:
    prefix = f"- {field_name}:"
    for line in lines:
        if line.strip().startswith(prefix):
            return line.split(":", 1)[1].strip()
    return ""


def _collect_list_under_heading(lines: List[str], heading: str) -> List[str]:
    target = f"### {heading}"
    collecting = False
    items: List[str] = []

    for raw in lines:
        line = raw.strip()
        if line == target:
            collecting = True
            continue

        if collecting and line.startswith("### "):
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

    append_updates(DATA_DIR / "profile.md", "From Chat", profile_updates)
    if profile_updates:
        actions.append(f"profile.md +{len(profile_updates)}")

    append_updates(DATA_DIR / "goals.md", "From Chat", goals_updates)
    if goals_updates:
        actions.append(f"goals.md +{len(goals_updates)}")

    append_updates(DATA_DIR / "preferences.md", "From Chat", preferences_updates)
    if preferences_updates:
        actions.append(f"preferences.md +{len(preferences_updates)}")

    append_updates(DATA_DIR / "fixed_events.md", "From Chat", fixed_events_updates)
    if fixed_events_updates:
        actions.append(f"fixed_events.md +{len(fixed_events_updates)}")

    append_updates(DATA_DIR / "today_notes.md", "From Chat", today_notes_updates)
    if today_notes_updates:
        actions.append(f"today_notes.md +{len(today_notes_updates)}")

    feedback = extracted.get("feedback") or {}
    completion = str(feedback.get("completion", "")).strip()
    mood = str(feedback.get("mood", "")).strip()
    notes = str(feedback.get("notes", "")).strip()
    feedback_date = str(feedback.get("date", "")).strip() or dt.date.today().isoformat()
    if completion and mood:
        record_feedback(feedback_date, completion, mood, notes)
        actions.append(f"feedback {feedback_date}")

    return actions


def reset_chat_window() -> None:
    CHAT_WINDOW_FILE.write_text(chat_window_template(), encoding="utf-8")


def archive_chat(chat_text: str) -> Path:
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = CHAT_ARCHIVE_DIR / f"{stamp}.md"
    path.write_text(chat_text.strip() + "\n", encoding="utf-8")
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
    plan_path = PLANS_DIR / f"{target_date.isoformat()}.md"
    plan_path.write_text(content + "\n", encoding="utf-8")
    return plan_path


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
    print("Initialized schedule agent data files under ./data")


def cmd_plan(args: argparse.Namespace) -> None:
    ensure_structure()
    target_date = parse_date(args.date)
    messages = build_messages(target_date)
    content = deepseek_chat(messages, model=args.model, temperature=args.temperature)
    path = save_plan(target_date, content)

    print(content)
    print(f"\nSaved plan to: {path}")


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
    chat_text = read_text_if_exists(CHAT_WINDOW_FILE)
    if not chat_text:
        raise RuntimeError("chat_window.md format is invalid. Re-run init or restore template.")

    form_text, free_text = split_chat_sections(chat_text)
    if not form_text and not free_text:
        print("No new message in chat_window.md")
        return

    form_extracted = parse_daily_template(form_text) if form_text else {
        "profile_updates": [],
        "goals_updates": [],
        "preferences_updates": [],
        "fixed_events_updates": [],
        "today_notes_updates": [],
        "feedback": {"date": "", "completion": "", "mood": "", "notes": ""},
        "summary": "",
    }

    free_extracted = {
        "profile_updates": [],
        "goals_updates": [],
        "preferences_updates": [],
        "fixed_events_updates": [],
        "today_notes_updates": [],
        "feedback": {"date": "", "completion": "", "mood": "", "notes": ""},
        "summary": "",
    }

    if free_text and free_text != "把临时想法、背景信息、感受直接写在这里。":
        messages = build_chat_extract_messages(free_text)
        raw = deepseek_chat(messages, model=args.model, temperature=args.temperature)
        free_extracted = extract_json_object(raw)

    extracted = merge_extracted(form_extracted, free_extracted)
    actions = apply_chat_updates(extracted)
    archive_path = archive_chat(chat_text)
    reset_chat_window()

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

    if args.plan_after:
        target_date = parse_date(args.date)
        plan_messages = build_messages(target_date)
        content = deepseek_chat(plan_messages, model=args.model, temperature=args.temperature)
        plan_path = save_plan(target_date, content)
        print(f"Generated plan: {plan_path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DeepSeek daily schedule agent")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Initialize local data templates")
    p_init.set_defaults(func=cmd_init)

    p_plan = sub.add_parser("plan", help="Generate next-day plan with DeepSeek")
    p_plan.add_argument("--date", help="Target date in YYYY-MM-DD; default is tomorrow")
    p_plan.add_argument("--model", default=DEFAULT_MODEL, help="DeepSeek model name")
    p_plan.add_argument("--temperature", type=float, default=0.3, help="Sampling temperature")
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

    p_sync = sub.add_parser("sync-chat", help="Parse chat_window.md and update local context files")
    p_sync.add_argument("--model", default=DEFAULT_MODEL, help="DeepSeek model name")
    p_sync.add_argument("--temperature", type=float, default=0.1, help="Sampling temperature")
    p_sync.add_argument("--plan-after", action="store_true", help="Generate plan after syncing chat")
    p_sync.add_argument("--date", help="Plan date in YYYY-MM-DD when using --plan-after")
    p_sync.set_defaults(func=cmd_sync_chat)

    return parser


def main() -> None:
    load_env_file(BASE_DIR / ".env")
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
