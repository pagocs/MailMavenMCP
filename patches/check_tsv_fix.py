#!/usr/bin/env python3
"""Functional check: TSV rows stay intact, and list_mailboxes accepts an account.

Run on the Mac with the MailMavenMCP venv python:
    ~/mcp/MailMavenMCP/.venv/bin/python patches/check_tsv_fix.py [path/to/MavenMCP.py]

Reads mail only. Compares search_messages with a direct MailMaven count, and
calls list_mailboxes for the first account. Nothing is sent or deleted.
Prints JSON {status, details}.
Exit: 0 = ok, 1 = missing, 2 = mismatch / error.
"""
import importlib.util
import json
import os
import subprocess
import sys

MARKER = "# PAGOCS-PATCH: tsv-fix v1"
DAYS_BACK = 365
LIMIT = 40
CONTENT_LIMIT = 5
FIELDS = (
    "identifier",
    "subject",
    "originalSubject",
    "alternateSubject",
    "dateReceived",
    "readStatus",
    "junkStatus",
    "flagged",
    "importance",
    "mailboxName",
    "accountName",
    "size",
    "attachmentCount",
    "keywords",
    "project",
    "notes",
    "reviewDate",
    "contentIdentifier",
    "mavenIdentifier",
    "messageIdUrl",
    "mavenUrl",
    "conversationId",
)
BREAK_FIELDS = (
    ("notes", "notes of m"),
    ("subject", "subject of m"),
    ("originalSubject", "original subject of m"),
    ("alternateSubject", "alternate subject of m"),
    ("project", "project of m"),
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
    spec = importlib.util.spec_from_file_location("MavenMCP_check_tsv", source)
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


def flatten_field(value):
    """Replace tab, CR, and LF with a space, matching flattenField.

    Args:
        value: Raw MailMaven text.

    Returns:
        The same text with each of those characters turned into one space.
    """
    return value.replace("\t", " ").replace("\r", " ").replace("\n", " ")


def has_break(value):
    """Return whether a parsed TSV field still contains a row-splitting character.

    Args:
        value: One field from search_messages.

    Returns:
        True when tab, CR, or LF remains.
    """
    return "\t" in value or "\r" in value or "\n" in value


def run_osascript(script, argv=None, timeout=120):
    """Run AppleScript and return stdout without stripping interior whitespace.

    Args:
        script: AppleScript source. With argv it must declare ``on run argv``.
        argv: Arguments after ``--``.
        timeout: Seconds before the process is killed.

    Returns:
        Raw stdout.

    Raises:
        RuntimeError: osascript failed.
    """
    command = ["osascript", "-l", "AppleScript", "-e", script]
    if argv is not None:
        command.append("--")
        command.extend(argv)
    proc = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip())
    text = proc.stdout
    if text.endswith("\n"):
        text = text[:-1]
    return text


def direct_rows(limit):
    """List recent message ids and which returned field contains a break.

    Args:
        limit: Maximum messages, matching search_messages.

    Returns:
        List of (identifier, field_name or "").
    """
    checks = "\n".join(
        f'''            if _flag is "" then
                if my hasBreak({expr}) then set _flag to "{name}"
            end if'''
        for name, expr in BREAK_FIELDS
    )
    script = f'''
on hasBreak(v)
    if v is missing value then return false
    set _s to ""
    try
        set _s to v as string
    on error
        return false
    end try
    if _s contains tab then return true
    if _s contains return then return true
    if _s contains linefeed then return true
    return false
end hasBreak
tell application "MailMaven"
    with transaction
        set _q to make new query with properties {{name:"check_tsv_fix"}}
        set logic of _q to all criteria
        set sort order of _q to sort by date received
        set sort ascending of _q to false
        make new relative message date criterion with properties {{unit:day, starting at:-{DAYS_BACK}, for duration:{DAYS_BACK}}} at end of criteria of _q
        set _msgs to messages of _q
        set _count to count of _msgs
        if _count > {limit} then set _count to {limit}
        set _out to ""
        repeat with i from 1 to _count
            set m to item i of _msgs
            set _flag to ""
{checks}
            set _out to _out & ((identifier of m) as string) & "|" & _flag & linefeed
        end repeat
    end transaction
    return _out
end tell
'''
    text = run_osascript(script)
    rows = []
    for line in text.split("\n"):
        if not line.strip():
            continue
        identifier, _, flag = line.partition("|")
        rows.append((identifier.strip(), flag.strip()))
    return rows


def raw_field(identifier, field_name):
    """Read one message field without putting it through TSV.

    Args:
        identifier: Integer message id.
        field_name: notes, subject, originalSubject, alternateSubject,
            project, or content.

    Returns:
        The raw field text. Missing values become an empty string.
    """
    script = r'''
on run argv
    set msgId to item 1 of argv as integer
    set fieldName to item 2 of argv
    tell application "MailMaven"
        set m to message id msgId
        set rawText to ""
        try
            if fieldName is "notes" then
                set rawText to notes of m as string
            else if fieldName is "subject" then
                set rawText to subject of m as string
            else if fieldName is "originalSubject" then
                set rawText to original subject of m as string
            else if fieldName is "alternateSubject" then
                set rawText to alternate subject of m as string
            else if fieldName is "project" then
                set rawText to project of m as string
            else if fieldName is "content" then
                set rawText to content of m as string
            end if
        end try
        if rawText is "missing value" then set rawText to ""
    end tell
    return "@@TSVFIX-BEGIN@@" & linefeed & rawText & linefeed & "@@TSVFIX-END@@"
end run
'''
    text = run_osascript(script, [str(identifier), field_name])
    start = text.find("@@TSVFIX-BEGIN@@\n")
    end = text.rfind("\n@@TSVFIX-END@@")
    if start < 0 or end < 0 or end < start:
        raise RuntimeError("field markers missing for " + field_name)
    return text[start + len("@@TSVFIX-BEGIN@@\n"):end]


def row_ok(message, include_content):
    """Return an error string when a parsed row is not one well-formed record.

    Args:
        message: One search_messages dict.
        include_content: Whether the content column is required.

    Returns:
        Empty string when the row is well formed, otherwise a short reason.
    """
    expected = FIELDS + (("content",) if include_content else ())
    missing = [name for name in expected if name not in message]
    if missing:
        return "missing columns " + ",".join(missing)
    for name in expected:
        if has_break(str(message.get(name, ""))):
            return name + " still contains a tab or line break"
    return ""


try:
    source = open(path, encoding="utf-8").read()
except Exception as exc:
    done("mismatch", 2, f"cannot read {path}: {exc!r}")

if MARKER not in source:
    done("missing", 1, "marker not in MavenMCP.py")
if "safeStr(name of _acct)" not in source:
    done("missing", 1, "list_mailboxes does not pass the account name through safeStr")
if "{tab, return, linefeed}" not in source:
    done("missing", 1, "safeStr does not replace tab, CR, and LF")

try:
    mod = load_module(path)
except Exception as exc:
    done("mismatch", 2, f"import failed: {exc!r}")

list_accounts = unwrap(getattr(mod, "list_accounts", None))
list_mailboxes = unwrap(getattr(mod, "list_mailboxes", None))
search_messages = unwrap(getattr(mod, "search_messages", None))
if not callable(list_accounts) or not callable(list_mailboxes) or not callable(search_messages):
    done("missing", 1, "list_accounts, list_mailboxes, or search_messages is missing")

try:
    accounts = list_accounts()
except Exception as exc:
    done("mismatch", 2, f"list_accounts failed: {exc!r}")
if not accounts:
    done("mismatch", 2, "no accounts")
account_name = str(accounts[0].get("name", ""))
if not account_name:
    done("mismatch", 2, "first account has no name")

try:
    boxes = list_mailboxes(account_name=account_name)
except Exception as exc:
    done("mismatch", 2, f"list_mailboxes({account_name!r}) failed: {exc!r}")
if not boxes:
    done("mismatch", 2, f"list_mailboxes({account_name!r}) returned no mailboxes")
bad_accounts = [box.get("account") for box in boxes if box.get("account") != account_name]
if bad_accounts:
    done("mismatch", 2, f"account field {bad_accounts[0]!r} != {account_name!r}")

try:
    direct = direct_rows(LIMIT)
    found = search_messages(days_back=DAYS_BACK, limit=LIMIT, include_content=False)
except Exception as exc:
    done("mismatch", 2, f"search compare failed: {exc!r}")

direct_ids = [identifier for identifier, _flag in direct]
found_ids = [str(row.get("identifier", "")).strip() for row in found]
if direct_ids != found_ids:
    done(
        "mismatch",
        2,
        f"row count direct={len(direct_ids)} search={len(found_ids)}",
    )
for row in found:
    problem = row_ok(row, include_content=False)
    if problem:
        done("mismatch", 2, problem)

broken = next(((identifier, flag) for identifier, flag in direct if flag), None)
compared = "ids"
if broken:
    identifier, field_name = broken
    try:
        raw = raw_field(identifier, field_name)
    except Exception as exc:
        done("mismatch", 2, f"raw {field_name} failed: {exc!r}")
    match = next((row for row in found if str(row.get("identifier", "")).strip() == identifier), None)
    if match is None:
        done("mismatch", 2, f"id {identifier} missing from search_messages")
    if str(match.get(field_name, "")) != flatten_field(raw):
        done("mismatch", 2, f"{field_name} was not flattened for id {identifier}")
    compared = field_name
else:
    try:
        content_rows = search_messages(
            days_back=DAYS_BACK,
            limit=CONTENT_LIMIT,
            include_content=True,
        )
    except Exception as exc:
        done("mismatch", 2, f"content search failed: {exc!r}")
    if not content_rows and not found:
        done("mismatch", 2, "no messages to test")
    for row in content_rows:
        problem = row_ok(row, include_content=True)
        if problem:
            done("mismatch", 2, problem)
    compared = "no-multiline-field"
    for row in content_rows:
        content_id = str(row.get("identifier", "")).strip()
        try:
            raw_content = raw_field(content_id, "content")
        except Exception as exc:
            done("mismatch", 2, f"raw content failed: {exc!r}")
        if not has_break(raw_content):
            continue
        if str(row.get("content", "")) != flatten_field(raw_content):
            done("mismatch", 2, f"content was not flattened for id {content_id}")
        compared = "content"
        break

done(
    "ok",
    0,
    f"account={account_name} mailboxes={len(boxes)} messages={len(found)} checked={compared}",
)
