#!/usr/bin/env python3
"""Functional check: a hidden reply keeps the body lines and is not sent.

Run on the Mac with the MailMavenMCP venv python:
    ~/mcp/MailMavenMCP/.venv/bin/python patches/check_reply.py [path/to/MavenMCP.py]

Opens one reply with show_window false, reads the composer content back,
and compares the body line by line. MailMaven's composer does not support
close. The hidden composer is discarded when its transaction ends. The
check compares composer and draft counts so nothing was saved or sent,
and fails if a new window opens.
Prints JSON {status, details}.
Exit: 0 = ok, 1 = missing, 2 = mismatch / error.
"""
import importlib.util
import inspect
import json
import os
import subprocess
import sys

MARKER = "# PAGOCS-PATCH: reply v1"
PROBE = "----MCP-REPLY-PROBE----"
REQUIRED = (
    "identifier",
    "body",
    "reply_to_all",
    "from_account",
    "template_name",
    "show_window",
    "send",
)
BODY_LINES = (
    "Első sor áéíóöőúüű ÁÉÍÓÖŐÚÜŰ",
    'Idézet: "szia" és útvonal c:\\notes\\mail',
    "",
    "Utolsó sor",
)
INDENT = "    "

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


def as_lines(text):
    """Split composer text into lines without dropping a blank line in the middle.

    Args:
        text: Composer content. CR and CRLF count as one line break.

    Returns:
        Lines without a trailing empty entry caused only by a final break.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if text.endswith("\n"):
        text = text[:-1]
    if text == "":
        return []
    return text.split("\n")


def mail_snapshot():
    """Count composers, windows, and drafts.

    Returns:
        (composer_count, window_count, draft_count).

    Raises:
        RuntimeError: MailMaven did not answer.
    """
    script = r'''
tell application "MailMaven"
    set _c to count of composer messages
    set _w to count of windows
    set _d to 0
    repeat with a in accounts
        try
            set _d to _d + (count of messages of draft mailbox of a)
        end try
    end repeat
    return (_c as string) & "," & (_w as string) & "," & (_d as string)
end tell
'''
    proc = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip())
    parts = proc.stdout.strip().split(",")
    if len(parts) != 3:
        raise RuntimeError("snapshot " + proc.stdout.strip())
    return tuple(int(part) for part in parts)


def install_probe(mod):
    """Read composer content inside reply_message's transaction.

    The composer does not exist after the transaction, so the read has to
    happen in the script reply_message already built. The wrapper returns
    only the composer id to reply_message and keeps the content here.

    Args:
        mod: Loaded MavenMCP module.

    Returns:
        Dict filled with content and composer_id when a reply script runs.
    """
    real = mod._run_applescript
    captured = {}

    def wrapped(script, timeout=60, argv=None):
        """Run script, and capture reply content when this is a reply."""
        probe_script = script
        if "set _comp to reply" in script and "    end transaction" in script:
            probe_script = script.replace(
                "    end transaction",
                "        set _mcpProbe to content of _comp as string\n    end transaction",
                1,
            )
            probe_script = probe_script.replace(
                "    return _id",
                f'    return _id & linefeed & "{PROBE}" & linefeed & _mcpProbe',
                1,
            )
        raw = real(probe_script, timeout=timeout, argv=argv)
        marker = "\n" + PROBE + "\n"
        if marker in raw:
            composer_id, _, content = raw.partition(marker)
            captured["content"] = content
            captured["composer_id"] = composer_id.strip()
            return composer_id.strip()
        return raw

    mod._run_applescript = wrapped
    return captured


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

try:
    origin = inspect.getsource(fn)
except Exception as exc:
    done("mismatch", 2, f"cannot read reply_message source: {exc!r}")
if "_bodyText & linefeed & linefeed" not in origin or "argv=body_lines" not in origin:
    done("missing", 1, "reply body is not passed as argv and joined with linefeed")
if INDENT not in origin:
    done("missing", 1, "reply_message does not indent the quoted original")

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
captured = install_probe(mod)

try:
    before = mail_snapshot()
except Exception as exc:
    done("mismatch", 2, f"snapshot failed: {exc!r}")

body = "\n".join(BODY_LINES)
try:
    result = fn(identifier=identifier, body=body, show_window=False, send=False)
except Exception as exc:
    done("mismatch", 2, f"reply_message failed: {exc!r}")

if result.get("sent"):
    done("mismatch", 2, "reply reported sent")
if not result.get("composerId"):
    done("mismatch", 2, "no composerId")
if "content" not in captured:
    done("mismatch", 2, "composer content was not read back")

lines = as_lines(captured["content"])
received = lines[:len(BODY_LINES)]
if received != list(BODY_LINES):
    done("mismatch", 2, "body lines differ: " + repr(received))
rest = lines[len(BODY_LINES):]
if not rest or rest[0] != "":
    done("mismatch", 2, "missing the single blank line before the quote")
if len(rest) > 1 and rest[1] == "":
    done("mismatch", 2, "double blank line before the quote")
quoted = [line for line in rest[1:] if line.strip()]
if not quoted or any(not line.startswith(INDENT) for line in quoted):
    done("mismatch", 2, "quoted original is not indented by four spaces")

try:
    after = mail_snapshot()
except Exception as exc:
    done("mismatch", 2, f"snapshot failed: {exc!r}")
if after[0] != before[0] or after[2] != before[2]:
    done("mismatch", 2, f"composer or draft count changed {before} -> {after}")
if after[1] > before[1]:
    done("mismatch", 2, f"reply opened a window {before} -> {after}")

done("ok", 0, f"identifier={identifier} lines={len(BODY_LINES)}")
