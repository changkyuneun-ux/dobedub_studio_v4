from __future__ import annotations

import html
import re
from datetime import datetime
from pathlib import Path

from backend.app.core.config import get_settings


def inline_markdown(text: str) -> str:
    escaped = html.escape(text or "")
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"\[([^\]]+)\]\((#[^)]+)\)", r'<a href="\2">\1</a>', escaped)
    return escaped


def render_manual_table(lines: list[str]) -> str:
    rows = []
    for line in lines:
        cells = [inline_markdown(cell.strip()) for cell in line.strip().strip("|").split("|")]
        rows.append(cells)
    if len(rows) >= 2 and all(set(cell.replace(":", "").strip()) <= {"-"} for cell in rows[1]):
        header = rows[0]
        body = rows[2:]
    else:
        header = []
        body = rows
    parts = ['<div class="manual-table-wrap"><table>']
    if header:
        parts.append("<thead><tr>")
        parts.extend(f"<th>{cell}</th>" for cell in header)
        parts.append("</tr></thead>")
    parts.append("<tbody>")
    for row in body:
        parts.append("<tr>")
        parts.extend(f"<td>{cell}</td>" for cell in row)
        parts.append("</tr>")
    parts.append("</tbody></table></div>")
    return "\n".join(parts)


def render_manual_toc(lines: list[str]) -> str:
    """Render the manual's indented Markdown TOC as a real nested navigation tree."""
    root: list[dict[str, object]] = []
    stack: list[tuple[int, list[dict[str, object]]]] = [(-1, root)]

    for line in lines:
        item = re.match(r"^(?P<indent>\s*)(?P<marker>\d+\.|[-*])\s+(?P<body>.+)$", line)
        if not item:
            continue
        indent = len(item.group("indent").expandtabs(2))
        while len(stack) > 1 and indent < stack[-1][0]:
            stack.pop()
        if indent > stack[-1][0]:
            if stack[-1][0] < 0:
                stack.append((indent, root))
            elif stack[-1][1]:
                children: list[dict[str, object]] = []
                stack[-1][1][-1]["children"] = children
                stack.append((indent, children))

        stack[-1][1].append(
            {
                "ordered": item.group("marker").endswith("."),
                "body": item.group("body"),
                "children": [],
            }
        )

    def render_items(items: list[dict[str, object]], depth: int = 0) -> str:
        if not items:
            return ""
        tag = "ol" if bool(items[0]["ordered"]) else "ul"
        parts = [f'<{tag} class="manual-toc-level manual-toc-level-{depth}">']
        for item in items:
            parts.append("<li>")
            parts.append(inline_markdown(str(item["body"])))
            parts.append(render_items(item["children"], depth + 1))
            parts.append("</li>")
        parts.append(f"</{tag}>")
        return "".join(parts)

    return f'<nav class="manual-toc" aria-label="사용자 매뉴얼 목차">{render_items(root)}</nav>'


def render_manual_markdown(markdown: str) -> str:
    lines = markdown.splitlines()
    parts = []
    i = 0
    in_list = False
    list_tag = "ul"
    in_code = False
    code_lines = []

    def close_list():
        nonlocal in_list, list_tag
        if in_list:
            parts.append(f"</{list_tag}>")
            in_list = False
            list_tag = "ul"

    while i < len(lines):
        line = lines[i].rstrip()
        stripped = line.strip()
        if stripped.startswith("```"):
            if in_code:
                parts.append(f"<pre><code>{html.escape(chr(10).join(code_lines))}</code></pre>")
                code_lines = []
                in_code = False
            else:
                close_list()
                in_code = True
            i += 1
            continue
        if in_code:
            code_lines.append(line)
            i += 1
            continue
        if not stripped:
            close_list()
            i += 1
            continue
        if stripped.startswith("|") and "|" in stripped[1:]:
            close_list()
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i])
                i += 1
            parts.append(render_manual_table(table_lines))
            continue
        image = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)$", stripped)
        if image:
            close_list()
            caption = image.group(1).strip()
            source = Path(image.group(2).strip()).name
            safe_caption = html.escape(caption or source)
            parts.append(
                "<figure>"
                f'<img src="/docs/manual-assets/{html.escape(source)}" alt="{safe_caption}" />'
                f"<figcaption>{safe_caption}</figcaption>"
                "</figure>"
            )
            i += 1
            continue
        heading = re.match(r"^(#{1,4})\s+(.+)$", stripped)
        if heading:
            close_list()
            level = len(heading.group(1))
            text = heading.group(2).strip()
            tag = "h1" if level == 1 else "h2" if level == 2 else "h3"
            # 목차의 Markdown 앵커는 GitHub와 같은 소문자 slug 규칙을 사용한다.
            # 제목의 영문 대소문자가 남아 있으면 같은 문서를 가리키는 링크가 대상
            # 요소를 찾지 못하고 iframe의 기본 페이지 이동으로 이어질 수 있다.
            normalized_heading = re.sub(r"[^0-9A-Za-z가-힣\s-]", "", text.lower())
            heading_id = re.sub(r"\s", "-", normalized_heading).strip("-")
            parts.append(f'<{tag} id="{html.escape(heading_id)}">{inline_markdown(text)}</{tag}>')
            i += 1
            if text == "목차":
                while i < len(lines) and not lines[i].strip():
                    i += 1
                toc_lines = []
                while i < len(lines) and re.match(r"^\s*(?:\d+\.|[-*])\s+", lines[i]):
                    toc_lines.append(lines[i].rstrip())
                    i += 1
                parts.append(render_manual_toc(toc_lines))
            continue
        bullet = re.match(r"^[-*]\s+(.+)$", stripped)
        number = re.match(r"^\d+\.\s+(.+)$", stripped)
        if bullet or number:
            next_tag = "ol" if number else "ul"
            if in_list and list_tag != next_tag:
                close_list()
            if not in_list:
                list_tag = next_tag
                parts.append(f"<{list_tag}>")
                in_list = True
            parts.append(f"<li>{inline_markdown((bullet or number).group(1))}</li>")
            i += 1
            continue
        close_list()
        parts.append(f"<p>{inline_markdown(stripped)}</p>")
        i += 1
    close_list()
    if in_code:
        parts.append(f"<pre><code>{html.escape(chr(10).join(code_lines))}</code></pre>")
    return "\n".join(parts)


def manual_html_page(manual_path: Path | None = None) -> str:
    settings = get_settings()
    manual_path = manual_path or settings.project_root / "docs" / "dobedub-studio-user-manual.md"
    if not manual_path.exists():
        raise FileNotFoundError(manual_path.name)
    markdown = manual_path.read_text(encoding="utf-8")
    modified = datetime.fromtimestamp(manual_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    body = render_manual_markdown(markdown)
    return f"""<!doctype html>
<html lang="ko">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>dobedub studio 사용자 매뉴얼</title>
    <style>
      :root {{ color-scheme: light; --blue: #2f80ff; --line: #d6dde8; --muted: #596574; }}
      * {{ box-sizing: border-box; }}
      body {{ margin: 0; background: #f7f9fc; color: #111827; font-family: -apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo", "Malgun Gothic", Arial, sans-serif; line-height: 1.62; }}
      main {{ max-width: 980px; margin: 0 auto; padding: 42px 48px 56px; background: #fff; min-height: 100vh; box-shadow: 0 18px 60px rgba(15, 23, 42, 0.12); }}
      h1 {{ margin: 0 0 12px; font-size: 34px; font-weight: 700; letter-spacing: 0; }}
      h2 {{ border-top: 1px solid var(--line); margin: 34px 0 14px; padding-top: 24px; font-size: 25px; letter-spacing: 0; }}
      h3 {{ margin: 24px 0 10px; font-size: 18px; }}
      p {{ margin: 0 0 12px; }}
      ul {{ margin: 0 0 14px 20px; padding: 0; }}
      li {{ margin: 5px 0; }}
      .manual-toc {{ background: #f8fafc; border: 1px solid var(--line); border-radius: 8px; margin: 14px 0 22px; padding: 16px 20px; }}
      .manual-toc ol, .manual-toc ul {{ margin: 0; padding-left: 21px; }}
      .manual-toc .manual-toc-level-0 {{ padding-left: 18px; }}
      .manual-toc li {{ margin: 5px 0; }}
      .manual-toc a {{ color: #0f56b3; text-decoration: none; }}
      .manual-toc a:hover {{ text-decoration: underline; }}
      code {{ background: #eef4ff; border: 1px solid #d7e5ff; border-radius: 4px; color: #0f56b3; padding: 1px 5px; }}
      pre {{ background: #111827; border-radius: 8px; color: #f8fafc; overflow: auto; padding: 14px; }}
      figure {{ margin: 18px 0 22px; }}
      figure img {{ border: 1px solid #cbd5e1; border-radius: 8px; display: block; max-width: 100%; width: 100%; }}
      figcaption {{ color: var(--muted); font-size: 13px; margin-top: 8px; text-align: center; }}
      mark.manual-hit {{ background: #fde68a; border-radius: 3px; color: #111827; padding: 0 2px; }}
      mark.manual-hit.is-current {{ background: #fb923c; color: #111827; }}
      .manual-table-wrap {{ overflow-x: auto; margin: 14px 0 20px; }}
      table {{ border-collapse: collapse; min-width: 720px; width: 100%; }}
      th {{ background: #2563eb; color: #fff; font-weight: 700; }}
      th, td {{ border: 1px solid var(--line); padding: 9px 10px; text-align: left; vertical-align: top; }}
      td {{ background: #fbfdff; }}
      @media (max-width: 720px) {{ main {{ padding: 28px 20px 40px; }} h1 {{ font-size: 28px; }} h2 {{ font-size: 22px; }} }}
    </style>
  </head>
  <body>
    <main>
      <p style="color: var(--muted); margin-bottom: 24px;">Last updated: {html.escape(modified)}</p>
      {body}
    </main>
  </body>
</html>"""
