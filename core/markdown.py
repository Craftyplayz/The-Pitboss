"""Just enough markdown for Claude's replies on the call page: headings, lists, tables, code, bold, italics.
shortcut: no nested lists, links or images; use a real markdown library if replies start needing them."""
import html
import re

INLINE = [(re.compile(r"`([^`]+)`"), r"<code>\1</code>"), (re.compile(r"\*\*(.+?)\*\*"), r"<b>\1</b>"),
          (re.compile(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])"), r"<i>\1</i>")]
ITEM = re.compile(r"\s*(?:[-*+]|(\d+)[.)])\s+(.*)")


def inline(text):
    text = html.escape(text)
    for pattern, repl in INLINE:
        text = pattern.sub(repl, text)
    return text


def cells(row):
    return [c.strip() for c in row.strip().strip("|").split("|")]


def render(md):
    out, lines, i = [], md.splitlines(), 0
    while i < len(lines):
        ln = lines[i]
        if not ln.strip():
            i += 1
        elif ln.startswith("```"):
            end = next((j for j in range(i + 1, len(lines)) if lines[j].startswith("```")), len(lines))
            out.append(f"<pre>{html.escape(chr(10).join(lines[i + 1:end]))}</pre>")
            i = end + 1
        elif m := re.match(r"(#{1,6})\s+(.*)", ln):
            level = min(len(m[1]) + 1, 4)  # the card title is the h2
            out.append(f"<h{level}>{inline(m[2])}</h{level}>")
            i += 1
        elif re.fullmatch(r"\s*([-*_])\s*(\1\s*){2,}", ln):
            out.append("<hr>")
            i += 1
        elif ln.lstrip().startswith("|"):
            rows = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                rows.append(lines[i])
                i += 1
            head = len(rows) > 1 and re.fullmatch(r"[\s|:-]+", rows[1])
            body = [r for k, r in enumerate(rows) if not (head and k == 1)]
            out.append('<div class="tw"><table>' + "".join(
                "<tr>" + "".join(f"<{t}>{inline(c)}</{t}>" for c in cells(r)) + "</tr>"
                for k, r in enumerate(body) for t in ["th" if head and k == 0 else "td"]) + "</table></div>")
        elif m := ITEM.match(ln):
            tag, start, items = ("ol" if m[1] else "ul"), m[1], []
            while i < len(lines) and (m := ITEM.match(lines[i])):
                items.append(m[2])
                i += 1
            first = f' start="{start}"' if start and start != "1" else ""
            out.append(f"<{tag}{first}>" + "".join(f"<li>{inline(x)}</li>" for x in items) + f"</{tag}>")
        else:
            para, i = [inline(ln)], i + 1  # always take the first line, so "#5" can't stall the loop
            while i < len(lines) and lines[i].strip() and not (ITEM.match(lines[i]) or lines[i].lstrip().startswith(("|", "#", "```"))):
                para.append(inline(lines[i]))
                i += 1
            out.append("<p>" + "<br>".join(para) + "</p>")
    return "".join(out)
