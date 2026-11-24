#!/usr/bin/env python3
"""Functional check: days_back includes today as one of N calendar days.

Run on the Mac with the MailMavenMCP venv python:
    ~/mcp/MailMavenMCP/.venv/bin/python patches/check_days_back.py [path/to/MavenMCP.py]

Reads mail only. Compares search_messages(days_back=N) with a direct
MailMaven query for the same window. Nothing is sent or deleted.
Prints JSON {status, details}.
Exit: 0 = ok, 1 = missing, 2 = mismatch / error.
"""
import importlib.util
import json
import os
import subprocess
import sys

MARKER = "# PAGOCS-PATCH: days-back v1"
FORMULA = '"starting at": 1 - days_back'
LIMIT = 500
SAMPLES = (1, 3)

path = os.path.expanduser(sys.argv[1] if len(sys.argv) > 1 else "~/mcp/MailMavenMCP/MavenMCP.py")
out = {"status": None, "details": ""}


def done(status, code, details=""):
    """Print the check result and stop.

    Args:
        status: ok, missing, or mismatch.
        code: Process exit code. 0, 1, or 2.
        details: Short reason safe to print.
    """
    out["status"] = status
    if details:
        out["details"] = details
    print(json.dumps(out, ensure_ascii=False))
    sys.exit(code)


def load_module(source):
    """Load MavenMCP from a file path without using the import path.

    Args:
        source: Absolute or relative path to MavenMCP.py.

    Returns:
        The loaded module.
    """
    spec = importlib.util.spec_from_file_location("MavenMCP_check_days_back", source)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def unwrap(fn):
    """Return the callable under a FastMCP tool wrapper, if there is one.

    Args:
        fn: Object stored under the tool name.

    Returns:
        A callable, or the original object.
    """
    return getattr(fn, "fn", fn)


def direct_ids(start, duration, limit):
    """List message identifiers for one relative calendar window.

    Args:
        start: MailMaven "starting at" day offset. 0 is today.
        duration: Window length in calendar days. The end day is exclusive.
        limit: Maximum identifiers, newest first.

    Returns:
        Identifiers as strings, newest first.

    Raises:
        RuntimeError: MailMaven did not answer.
    """
    script = f'''
tell application "MailMaven"
    with transaction
        set _q to make new query with properties {{name:"check_days_back"}}
        set logic of _q to all criteria
        set sort order of _q to sort by date received
        set sort ascending of _q to false
        make new relative message date criterion with properties {{unit:day, starting at:{start}, for duration:{duration}}} at end of criteria of _q
        set _msgs to messages of _q
        set _count to count of _msgs
        if _count > {limit} then set _count to {limit}
        set _out to ""
        repeat with i from 1 to _count
            set m to item i of _msgs
            set _out to _out & ((identifier of m) as string) & linefeed
        end repeat
    end transaction
    return _out
end tell
'''
    try:
        proc = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except Exception as exc:
        raise RuntimeError(f"osascript failed: {exc!r}") from exc
    if proc.returncode != 0:
        raise RuntimeError("osascript error: " + proc.stderr.strip())
    text = proc.stdout.replace("\r\n", "\n").replace("\r", "\n")
    return [line.strip() for line in text.split("\n") if line.strip()]


try:
    source = open(path, encoding="utf-8").read()
except Exception as exc:
    done("mismatch", 2, f"cannot read {path}: {exc!r}")

if MARKER not in source:
    done("missing", 1, "marker not in MavenMCP.py")
if FORMULA not in source:
    done("missing", 1, "days_back still starts at -N and excludes today")

try:
    mod = load_module(path)
except Exception as exc:
    done("mismatch", 2, f"import failed: {exc!r}")

search_messages = unwrap(getattr(mod, "search_messages", None))
if not callable(search_messages):
    done("missing", 1, "search_messages is missing")

counts = []
try:
    for days_back in SAMPLES:
        start = 1 - days_back
        found = search_messages(
            days_back=days_back,
            limit=LIMIT,
            include_content=False,
            sort_by="date received",
            sort_ascending=False,
        )
        found_ids = [str(row.get("identifier", "")).strip() for row in found]
        direct = direct_ids(start, days_back, LIMIT)
        if found_ids != direct:
            done(
                "mismatch",
                2,
                f"days_back={days_back} search={len(found_ids)} direct={len(direct)} start={start}",
            )
        counts.append(f"{days_back}:{len(found_ids)}")
    yesterday = direct_ids(-1, 1, LIMIT)
    explicit = search_messages(
        period_start_days_back=1,
        period_length_days=1,
        limit=LIMIT,
        include_content=False,
        sort_by="date received",
        sort_ascending=False,
    )
    explicit_ids = [str(row.get("identifier", "")).strip() for row in explicit]
    if explicit_ids != yesterday:
        done(
            "mismatch",
            2,
            f"period 1+1 search={len(explicit_ids)} direct={len(yesterday)}",
        )
except Exception as exc:
    done("mismatch", 2, f"search compare failed: {exc!r}")

done("ok", 0, "windows " + ",".join(counts) + f" period1={len(yesterday)}")
