#!/usr/bin/env python3
"""Functional check: reply_message builds a reply composer and does not send.

Run on the Mac with the MailMavenMCP venv python:
    ~/mcp/MailMavenMCP/.venv/bin/python patches/check_reply.py [path/to/MavenMCP.py]

Calls reply_message with the composer hidden, and runs the same reply inside
one AppleScript transaction to confirm the reply text is above an indented
copy of the original. That composer is deleted before the transaction ends.
No message is sent.
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
REQUIRED = (
    "identifier",
    "body",
    "reply_to_all",
    "from_account",
    "template_name",
    "show_window",
    "send",
)
BODY = "MCP check_reply. Discard this composer."
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


def window_names():
    """Return the current MailMaven window names, one per line.

    Returns:
        Window names separated by newlines. Empty when MailMaven has none.
    """
    script = r'''
tell application "MailMaven"
    set _out to ""
    repeat with w in windows
        try
            set _out to _out & ((name of w) as string) & linefeed
        end try
    end repeat
    return _out
end tell
'''
    proc = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip())
    return proc.stdout.replace("\r\n", "\n").replace("\r", "\n")


def direct_reply(identifier, body_literal):
    """Reply inside one transaction, check the text, and delete the composer.

    Args:
        identifier: Integer MailMaven message id.
        body_literal: AppleScript string literal for the reply text.

    Returns:
        (address, body) read back from the composer before it is deleted.

    Raises:
        RuntimeError: AppleScript failed.
    """
    script = f'''
tell application "MailMaven"
    with transaction
        set _msg to message id {int(identifier)}
        set _comp to reply _msg given reply to all:false
        set _orig to ""
        try
            set _orig to content of _msg as string
        end try
        if _orig is "missing value" then set _orig to ""
        set _oldDelims to AppleScript's text item delimiters
        try
            set AppleScript's text item delimiters to return & linefeed
            set _parts to text items of _orig
            set AppleScript's text item delimiters to return
            set _orig to _parts as string
            set AppleScript's text item delimiters to linefeed
            set _parts to text items of _orig
            set AppleScript's text item delimiters to return
            set _orig to _parts as string
            set _lines to text items of _orig
            set _quotedLines to {{}}
            repeat with _line in _lines
                set end of _quotedLines to ("{INDENT}" & _line)
            end repeat
            set _quoted to _quotedLines as string
            set AppleScript's text item delimiters to _oldDelims
        on error errMsg number errNum
            set AppleScript's text item delimiters to _oldDelims
            error errMsg number errNum
        end try
        set content of _comp to {body_literal} & return & return & _quoted
        set _now to content of _comp as string
        set _addr to address of item 1 of recipients of _comp as string
        delete _comp
    end transaction
    return _addr & linefeed & _now
end tell
'''
    proc = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=90)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip())
    text = proc.stdout.replace("\r\n", "\n").replace("\r", "\n")
    addr, _, body = text.partition("\n")
    return addr.strip(), body


def quoted_ok(body):
    """Return whether the reply text is above indented original lines.

    Args:
        body: Composer text, with any common newline form.

    Returns:
        True when the first line is the check body and every later non-empty
        line starts with four spaces.
    """
    lines = body.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if not lines or lines[0] != BODY:
        return False
    quoted = [line for line in lines[1:] if line.strip()]
    return bool(quoted) and all(line.startswith(INDENT) for line in quoted)


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
try:
    before = window_names()
    result = fn(identifier=identifier, body=BODY, show_window=False, send=False)
    after = window_names()
except Exception as exc:
    done("mismatch", 2, f"reply_message failed: {exc!r}")

if result.get("sent"):
    done("mismatch", 2, "reply reported sent")
if not result.get("composerId"):
    done("mismatch", 2, "no composerId")
if after.count("\n") != before.count("\n"):
    done("mismatch", 2, "hidden reply opened or closed a window")

try:
    addr, body = direct_reply(identifier, mod._to_applescript(BODY))
except Exception as exc:
    done("mismatch", 2, f"direct reply failed: {exc!r}")
if not quoted_ok(body):
    done("mismatch", 2, "quoted lines are not indented")
if not addr:
    done("mismatch", 2, "reply has no recipient")
done("ok", 0, f"identifier={identifier} quoted_ok")
