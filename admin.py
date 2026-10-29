"""/admin: password-protected viewer for the API call logs (api-bot.jsonl, api-web.jsonl) the bot and site write."""
import base64
import hmac
import html
import json
from datetime import datetime, timezone
from urllib.parse import urlencode

from aiohttp import web

PAGE_SIZE = 200
SOURCES = ("bot", "web")


def read_calls(log_dir):
    """Every logged call from both files, newest first, each with its source and on-disk line size."""
    calls = []
    for src in SOURCES:
        path = log_dir / f"api-{src}.jsonl"
        if not path.exists():
            continue
        with open(path, encoding="utf8") as f:
            for line in f:
                try:
                    c = json.loads(line)
                except ValueError:
                    continue  # a line cut short by a crash mid-write
                c["src"], c["line"] = src, len(line.encode("utf8"))
                calls.append(c)
    calls.sort(key=lambda c: c.get("t", 0), reverse=True)
    return calls


def ok(c):
    return isinstance(c.get("status"), int) and c["status"] < 400


def call_stats(calls):
    ms = sorted(c.get("ms", 0) for c in calls)
    return {
        "count": len(calls),
        "errors": sum(not ok(c) for c in calls),
        "avg_ms": round(sum(ms) / len(ms)) if ms else 0,
        "p95_ms": ms[min(len(ms) - 1, int(len(ms) * 0.95))] if ms else 0,
        "max_ms": ms[-1] if ms else 0,
        "bytes": sum(c.get("bytes", 0) for c in calls),
        "log_bytes": sum(c["line"] for c in calls),
    }


def filter_calls(calls, src="", q="", errors=False):
    q = q.lower()
    return [c for c in calls if (not src or c["src"] == src) and (not errors or not ok(c))
            and (not q or q in c.get("url", "").lower() or q in json.dumps(c.get("params", {})).lower())]


def size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:,.0f} {unit}" if unit == "B" else f"{n:,.1f} {unit}"
        n /= 1024


def authorized(request, password):
    """HTTP Basic auth; any username, the password must match."""
    header = request.headers.get("Authorization", "")
    if not header.startswith("Basic "):
        return False
    try:
        _, _, given = base64.b64decode(header[6:]).decode("utf8").partition(":")
    except (ValueError, UnicodeDecodeError):
        return False
    return hmac.compare_digest(given.encode(), password.encode())


def render(calls, stats, files, src, q, errors, page):
    pages = max(1, -(-len(calls) // PAGE_SIZE))
    page = min(max(page, 1), pages)
    rows = []
    for c in calls[(page - 1) * PAGE_SIZE:page * PAGE_SIZE]:
        t = c.get("t", 0)
        when = datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        params = "&".join(f"{k}={v}" for k, v in (c.get("params") or {}).items())
        status = c.get("status")
        rows.append(f'<tr><td><time data-t="{t}">{when}</time></td><td><span class="src {c["src"]}">{c["src"]}</span></td>'
                    f'<td class="url">{html.escape(c.get("url", ""))}<span class="mu">{"?" + html.escape(params) if params else ""}</span></td>'
                    f'<td class="{"good" if ok(c) else "bad"}">{html.escape(str(status))}</td>'
                    f'<td class="n">{c.get("ms", 0):,} ms</td><td class="n">{size(c.get("bytes", 0))}</td><td class="n">{c["line"]} B</td></tr>')

    def link(**kw):
        args = {"src": src, "q": q, "errors": "1" if errors else "", "page": page, **kw}
        return "?" + urlencode({k: v for k, v in args.items() if v})

    tiles = [("Calls", f'{stats["count"]:,}'), ("Errors", f'{stats["errors"]:,}'), ("Avg response", f'{stats["avg_ms"]:,} ms'),
             ("95th percentile", f'{stats["p95_ms"]:,} ms'), ("Slowest", f'{stats["max_ms"]:,} ms'),
             ("Data received", size(stats["bytes"])), ("Log size (these calls)", size(stats["log_bytes"]))]
    files_html = " · ".join(f"{name}: <b>{size(n)}</b>" for name, n in files) or "no log files yet"
    nav = (f'<a href="{link(page=page - 1)}">← Newer</a>' if page > 1 else "<span></span>") + \
          f"<span>Page {page} of {pages}</span>" + (f'<a href="{link(page=page + 1)}">Older →</a>' if page < pages else "<span></span>")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pitboss Admin</title><link rel="icon" href="/static/favicon.svg" type="image/svg+xml">
<style>
:root{{--bg:#0f141b;--card:#161c25;--line:#242d3a;--tx:#dbdee1;--mu:#8792a2;--gold:#F0C35A;--up:#4fc98a;--dn:#e5636d}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--tx);font:14px Inter,system-ui,sans-serif;padding:20px 16px}}
h1{{font:700 20px Cinzel,Georgia,serif;color:var(--gold);margin:0 0 4px}}.mu{{color:var(--mu)}}
.tiles{{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px;margin:16px 0}}
.tile{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px}}.tile .l{{color:var(--mu);font-size:11px;text-transform:uppercase;letter-spacing:.06em}}.tile .v{{font-size:20px;font-weight:600;margin-top:4px}}
form{{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:12px}}input,select,button{{background:var(--card);color:var(--tx);border:1px solid var(--line);border-radius:6px;padding:7px 10px;font:inherit}}
button{{background:var(--gold);color:#111;border:0;font-weight:600;cursor:pointer}}
.wrap{{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:10px}}table{{border-collapse:collapse;width:100%;min-width:760px}}
th,td{{padding:7px 10px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}}th{{color:var(--mu);font-size:11px;text-transform:uppercase;letter-spacing:.06em}}
td.url{{white-space:normal;word-break:break-all;font-family:Consolas,monospace;font-size:12px}}td.n{{text-align:right;font-variant-numeric:tabular-nums}}
.good{{color:var(--up)}}.bad{{color:var(--dn);font-weight:600}}.src{{font-size:11px;font-weight:600;padding:2px 6px;border-radius:4px}}.src.bot{{background:#5865f233;color:#a5adf7}}.src.web{{background:#f0c35a26;color:var(--gold)}}
.nav{{display:flex;justify-content:space-between;align-items:center;margin:12px 0}}a{{color:var(--gold)}}
</style></head><body>
<h1>API calls</h1><div class="mu">Log files: {files_html}</div>
<div class="tiles">{"".join(f'<div class="tile"><div class="l">{l}</div><div class="v">{v}</div></div>' for l, v in tiles)}</div>
<form><select name="src"><option value="">Bot + website</option>{"".join(f'<option value="{s}"{" selected" if s == src else ""}>{s}</option>' for s in SOURCES)}</select>
<input name="q" value="{html.escape(q)}" placeholder="Filter by URL or params"><label><input type="checkbox" name="errors" value="1"{" checked" if errors else ""}> Errors only</label>
<button>Apply</button>{'<a href="/admin">Clear</a>' if src or q or errors else ""}</form>
<div class="nav">{nav}</div>
<div class="wrap"><table><tr><th>When</th><th>From</th><th>Endpoint</th><th>Status</th><th>Response time</th><th>Response size</th><th>Log line</th></tr>{"".join(rows) or '<tr><td colspan="7" class="mu">No calls match.</td></tr>'}</table></div>
<div class="nav">{nav}</div>
<script>document.querySelectorAll('time[data-t]').forEach(e=>e.textContent=new Date(e.dataset.t*1000).toLocaleString())</script>
</body></html>"""


async def admin(request):
    password = request.app["admin_password"]
    if not password:
        raise web.HTTPNotFound()  # no password configured: the page doesn't exist
    if not authorized(request, password):
        raise web.HTTPUnauthorized(headers={"WWW-Authenticate": 'Basic realm="Pitboss admin"'})
    log_dir = request.app["log_dir"]
    src = request.query.get("src", "") if request.query.get("src") in SOURCES else ""
    q, errors = request.query.get("q", "")[:200], request.query.get("errors") == "1"
    try:
        page = int(request.query.get("page", "1"))
    except ValueError:
        page = 1
    calls = filter_calls(read_calls(log_dir), src, q, errors)
    files = [(f"api-{s}.jsonl", (log_dir / f"api-{s}.jsonl").stat().st_size) for s in SOURCES if (log_dir / f"api-{s}.jsonl").exists()]
    return web.Response(text=render(calls, call_stats(calls), files, src, q, errors, page), content_type="text/html",
                        headers={"Cache-Control": "no-store"})
