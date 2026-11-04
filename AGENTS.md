# MailMavenMCP, pagocs fork

A mappa: `~/mcp/MailMavenMCP`. A Cursor `~/.cursor/mcp.json` `mailmaven` bejegyzése ebből a mappából indítja a szervert. Deploykor a kiválasztott ág a `pagocs/main`. A változás a Cursor kilépése (Cmd+Q) és újranyitása után töltődik be.

## Remote-ok

- `origin` = `Smallcubed/MailMavenMCP`. Upstream, csak olvasásra.
- `fork` = `git@github.com:pagocs/MailMavenMCP.git`. Ide a bot pushol.

## Ágak

- `pagocs/review-date`: Due date szűrés. Kész funkció. Csak erre a funkcióra vonatkozó javítás mehet rá.
- `pagocs/reply`: reply. Az `origin/main` ágból indul. A törzs sorai osascript argumentumok, AppleScriptben linefeed fogja össze őket.
- `pagocs/tsv-fix`: TSV-mezők és a `list_mailboxes` fióknév. Az `origin/main` ágból indul. A tab, a CR és az LF szóköz lesz, mielőtt az érték a sorba kerül.
- `pagocs/main`: ez fut élesben. Az `origin/main` plusz az összes `pagocs/*` funkcióág mergelve.

Új funkció saját `pagocs/<név>` ágon készül, `origin/main` alapján. A funkcióág nem támaszkodhat egy másik funkcióág kódjára. Ütközésnél a merge megáll.

## Szerepek

- Cursor: fejlesztés a funkcióágakon, commit, a `pagocs/main` újraépítése helyben. Pusht nem csinál.
- Bot: push a forkba, a funkcionális tesztek futtatása a Macen, hétfőnként az upstream ellenőrzése, és rebase vagy merge javaslat, ha az upstream változik.

## Patch

Minden funkcióban legyen `# PAGOCS-PATCH: <név> v<N>` marker, és a `patches/` mappában egy `check_<név>.py`. A teszt `ok` / `missing` / `mismatch` állapotot ír, a kilépési kód 0 / 1 / 2. A funkciót működés közben ellenőrzi, valódi levelet nem küld, és levelet nem töröl.

```bash
~/mcp/MailMavenMCP/.venv/bin/python3 ~/mcp/MailMavenMCP/patches/check_review_filter.py
~/mcp/MailMavenMCP/.venv/bin/python3 ~/mcp/MailMavenMCP/patches/check_reply.py
~/mcp/MailMavenMCP/.venv/bin/python3 ~/mcp/MailMavenMCP/patches/check_tsv_fix.py
```
