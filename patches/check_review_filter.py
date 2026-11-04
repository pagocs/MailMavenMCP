#!/usr/bin/env python3
"""Functional check: does MailMavenMCP's search_messages support review (Due) date filtering?

Run on the Mac with the MailMavenMCP venv python:
    ~/mcp/MailMavenMCP/.venv/bin/python check_review_filter.py [path/to/MavenMCP.py]

Read-only towards mail (only MailMaven temp query objects are created).
Prints JSON {status, params_found, mcp_count, direct_count, details}.
Exit: 0 = ok, 1 = missing, 2 = mismatch / error.
"""
import importlib.util, inspect, json, os, subprocess, sys

LIMIT = 500
path = os.path.expanduser(sys.argv[1] if len(sys.argv) > 1 else "~/mcp/MailMavenMCP/MavenMCP.py")
out = {"status": None, "params_found": [], "mcp_count": None, "direct_count": None, "details": ""}

def done(status, code, details=""):
    out["status"] = status
    if details:
        out["details"] = details
    print(json.dumps(out, ensure_ascii=False, indent=2))
    sys.exit(code)

try:
    spec = importlib.util.spec_from_file_location("MavenMCP_check", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
except Exception as e:
    done("mismatch", 2, f"import failed: {e!r}")

fn = getattr(mod, "search_messages", None)
fn = getattr(fn, "fn", fn)  # in case a future FastMCP wraps the function
if not callable(fn):
    done("mismatch", 2, "search_messages not found/callable")
params = list(inspect.signature(fn).parameters)
found = [p for p in params if any(k in p.lower() for k in ("review", "due", "tickler"))]
out["params_found"] = found
if not found:
    done("missing", 1, "no review/due/tickler parameter in search_messages")

# MCP call (best-effort parameter choice)
kwargs = {"limit": LIMIT}
if "review_overdue" in params:
    kwargs["review_overdue"] = True
elif "review_start_days_back" in params and "review_length_days" in params:
    kwargs.update(review_start_days_back=3650, review_length_days=3650)
else:
    cands = [p for p in found if "overdue" in p.lower()]
    if not cands:
        done("mismatch", 2, f"review params present but no known overdue mode: {found}")
    kwargs[cands[0]] = True
try:
    res = fn(**kwargs)
except Exception as e:
    done("mismatch", 2, f"MCP call {kwargs} failed: {e!r}")
mcp_set = {(r.get("subject", ""), r.get("reviewDate", "")) for r in res}
out["mcp_count"] = len(res)

# Direct osascript query with the tested relative review date criterion
script = r'''
on safeStr(v)
    try
        if v is missing value then return ""
        return v as string
    on error
        return ""
    end try
end safeStr
tell application "MailMaven"
    with transaction
        set _q to make new query with properties {name:"check_review_filter"}
        set logic of _q to all criteria
        make new relative review date criterion with properties {unit:day, starting at:-3650, for duration:3650} at end of criteria of _q
        set _msgs to messages of _q
        set _count to count of _msgs
        if _count > %d then set _count to %d
        set _out to ""
        repeat with i from 1 to _count
            set m to item i of _msgs
            set _out to _out & (my safeStr(subject of m)) & tab & (my safeStr(review date of m)) & return
        end repeat
    end transaction
    return _out
end tell
''' % (LIMIT, LIMIT)
try:
    p = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=120)
except Exception as e:
    done("mismatch", 2, f"osascript failed: {e!r}")
if p.returncode != 0:
    done("mismatch", 2, f"osascript error: {p.stderr.strip()}")
direct = []
for line in p.stdout.strip("\r\n").split("\r"):
    if line.strip():
        s, _, d = line.partition("\t")
        direct.append((s, d.strip()))
direct_set = set(direct)
out["direct_count"] = len(direct)
mcp_set = {(s, d.strip()) for s, d in mcp_set}
if mcp_set == direct_set and out["mcp_count"] == len(direct):
    done("ok", 0, f"used {kwargs}")
done("mismatch", 2, json.dumps({
    "used": {k: v for k, v in kwargs.items()},
    "only_in_mcp": sorted(mcp_set - direct_set)[:20],
    "only_in_direct": sorted(direct_set - mcp_set)[:20],
}, ensure_ascii=False))
