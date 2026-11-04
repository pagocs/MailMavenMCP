#!/usr/bin/env python3
"""Functional check: reply_message keeps LF text and a > quote, and does not send.

Run on the Mac with the MailMavenMCP venv python:
    ~/mcp/MailMavenMCP/.venv/bin/python patches/check_reply.py [path/to/MavenMCP.py]

Each case replies to the newest inbox message with the composer hidden. The
tool checks the text it set against the text MailMaven stored, then deletes
the composer without saving. No message is sent.
Prints JSON {status, details}.
Exit: 0 = ok, 1 = missing, 2 = mismatch / error.
"""
import importlib.util
import inspect
import json
import os
import subprocess
import sys

MARKER = "# PAGOCS-PATCH: reply v2"
REQUIRED = (
    "identifier",
    "body",
    "reply_to_all",
    "from_account",
    "template_name",
    "show_window",
    "send",
)

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
    spec = importlib.util.spec_from_file_location("MavenMCP_check_reply", source)
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


def window_count():
    """Return how many MailMaven windows are open.

    Returns:
        The window count.

    Raises:
        RuntimeError: MailMaven did not answer.
    """
    script = 'tell application "MailMaven" to count of windows'
    proc = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip())
    return int(proc.stdout.strip())


try:
    source = open(path, encoding="utf-8").read()
except Exception as exc:
    done("mismatch", 2, f"cannot read {path}: {exc!r}")

if MARKER not in source:
    done("missing", 1, "marker not in MavenMCP.py")

try:
    mod = load_module(path)
except Exception as exc:
    done("mismatch", 2, f"import failed: {exc!r}")

fn = unwrap(getattr(mod, "reply_message", None))
if not callable(fn):
    done("missing", 1, "reply_message not found")

params = list(inspect.signature(fn).parameters)
missing_params = [name for name in REQUIRED if name not in params]
if missing_params:
    done("missing", 1, "missing parameters: " + ", ".join(missing_params))

if '"> "' not in source or "wrote:" not in source:
    done("missing", 1, "reply quote is not the > form")

if os.environ.get("ENABLE_SENDING", "").lower() == "true":
    done("mismatch", 2, "ENABLE_SENDING is set; check_reply will not run a send path")

try:
    fn(identifier=0, send=True)
except ValueError as exc:
    if "ENABLE_SENDING" not in str(exc):
        done("mismatch", 2, f"send gate raised the wrong error: {exc!r}")
except Exception as exc:
    done("mismatch", 2, f"send=True reached MailMaven: {exc!r}")
else:
    done("mismatch", 2, "send=True did not fail closed")

try:
    recent = unwrap(mod.get_recent_messages)(mailbox_name="inbox", limit=1, include_content=False)
except Exception as exc:
    done("mismatch", 2, f"inbox lookup failed: {exc!r}")
if not recent:
    done("mismatch", 2, "inbox is empty")

identifier = int(recent[0]["identifier"])
cases = (
    ("empty line", "első\n\nmásodik", "első\n\nmásodik"),
    ("trailing newline", "vége\n", "vége\n"),
    ("quote and backslash", 'mondta "x" és \\y', 'mondta "x" és \\y'),
    ("literal newline", "sor1\\nsor2", "sor1\nsor2"),
    ("accent and emoji", "őűŐŰ 😀", "őűŐŰ 😀"),
    ("crlf input", "sor1\r\nsor2", "sor1\nsor2"),
)

try:
    before = window_count()
except Exception as exc:
    done("mismatch", 2, f"window count failed: {exc!r}")

for label, raw_body, expected in cases:
    try:
        result = fn(identifier=identifier, body=raw_body, show_window=False, send=False)
    except Exception as exc:
        done("mismatch", 2, f"{label} failed: {exc!r}")
    if result.get("sent"):
        done("mismatch", 2, f"{label} reported sent")
    if result.get("normalizedBody") != expected:
        done("mismatch", 2, f"{label} normalized body differs")
    if "\r" in result.get("normalizedBody", ""):
        done("mismatch", 2, f"{label} still contains CR")

try:
    after = window_count()
except Exception as exc:
    done("mismatch", 2, f"window count failed: {exc!r}")
if after != before:
    done("mismatch", 2, "reply opened or closed a window")

done("ok", 0, f"identifier={identifier} cases={len(cases)}")
