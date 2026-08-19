"""Generate a neofetch-style SVG card for a GitHub profile README.

Usage:  GITHUB_TOKEN=xxx python3 generate.py
Output: dark_mode.svg / light_mode.svg
"""

import datetime
import hashlib
import io
import json
import os
import re
import sys
from collections import deque
from pathlib import Path
from xml.sax.saxutils import escape

import numpy as np
import requests
import yaml
from PIL import Image

ROOT = Path(__file__).parent
CACHE = ROOT / "cache"
API = "https://api.github.com/graphql"
TOKEN = os.environ.get("GITHUB_TOKEN", "")
HEADERS = {"Authorization": f"bearer {TOKEN}"} if TOKEN else {}

# dense -> light, same feel as the reference card
RAMP = "$@B%8&WM#*oahkbdpqwmZO0QLCJUYXzcvunxrjft/|()1{}[]?-_+~<>i!lI;:,\"^`'. "


def graphql(query, variables):
    r = requests.post(API, json={"query": query, "variables": variables}, headers=HEADERS, timeout=30)
    r.raise_for_status()
    data = r.json()
    if "errors" in data:
        raise RuntimeError(data["errors"])
    return data["data"]


# ---------------------------------------------------------------- stats


def user_stats(username):
    q = """
    query($login: String!) {
      user(login: $login) {
        id
        createdAt
        followers { totalCount }
        repositories(ownerAffiliations: OWNER) { totalCount }
        contributionsCollection { totalCommitContributions restrictedContributionsCount }
      }
    }"""
    return graphql(q, {"login": username})["user"]


def contribution_calendar(username):
    """One year of daily contribution counts."""
    q = """
    query($login: String!) {
      user(login: $login) {
        contributionsCollection {
          contributionCalendar {
            totalContributions
            weeks { contributionDays { date contributionCount } }
          }
        }
      }
    }"""
    cal = graphql(q, {"login": username})["user"]["contributionsCollection"]["contributionCalendar"]
    return cal


def streaks(calendar):
    """(current streak, longest streak, best day) from the calendar."""
    days = [d for week in calendar["weeks"] for d in week["contributionDays"]]
    days = [d for d in days if d["date"] <= datetime.date.today().isoformat()]
    longest = run = 0
    for day in days:
        run = run + 1 if day["contributionCount"] else 0
        longest = max(longest, run)
    current = 0
    for day in reversed(days):
        if day["contributionCount"]:
            current += 1
        elif current or day is not days[-1]:  # today may still be empty
            break
    best = max((d["contributionCount"] for d in days), default=0)
    return current, longest, best


def all_repos(username):
    """Repos the user owns or contributes to, with stargazers."""
    q = """
    query($login: String!, $cursor: String, $affil: [RepositoryAffiliation]) {
      user(login: $login) {
        repositories(first: 100, after: $cursor, ownerAffiliations: $affil) {
          pageInfo { hasNextPage endCursor }
          nodes {
            nameWithOwner
            isPrivate
            isFork
            pushedAt
            stargazerCount
            languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
              edges { size node { name } }
            }
            defaultBranchRef { target { ... on Commit { history { totalCount } } } }
          }
        }
      }
    }"""
    out, cursor = [], None
    while True:
        page = graphql(q, {"login": username, "cursor": cursor,
                           "affil": ["OWNER", "COLLABORATOR", "ORGANIZATION_MEMBER"]})
        rep = page["user"]["repositories"]
        out += rep["nodes"]
        if not rep["pageInfo"]["hasNextPage"]:
            return out
        cursor = rep["pageInfo"]["endCursor"]


def commit_stats(username, user_id, repos):
    """Commits + lines of code authored by the user (cached per repo)."""
    CACHE.mkdir(exist_ok=True)
    cache_file = CACHE / (hashlib.sha256(username.encode()).hexdigest() + ".json")
    cached = json.loads(cache_file.read_text()) if cache_file.exists() else {}

    q = """
    query($owner: String!, $name: String!, $id: ID!, $cursor: String) {
      repository(owner: $owner, name: $name) {
        defaultBranchRef { target { ... on Commit {
          history(author: {id: $id}, first: 100, after: $cursor) {
            totalCount
            pageInfo { hasNextPage endCursor }
            nodes { additions deletions }
          } } } }
      }
    }"""

    commits = added = deleted = 0
    for repo in repos:
        owner, name = repo["nameWithOwner"].split("/")
        head = (repo.get("defaultBranchRef") or {}).get("target") or {}
        fingerprint = str(head.get("history", {}).get("totalCount", 0))
        key = repo["nameWithOwner"]
        if cached.get(key, {}).get("fingerprint") == fingerprint:
            entry = cached[key]
        else:
            c = a = d = 0
            cursor = None
            while True:
                try:
                    res = graphql(q, {"owner": owner, "name": name, "id": user_id, "cursor": cursor})
                except Exception as exc:  # empty repo / no access
                    print(f"  skip {key}: {exc}", file=sys.stderr)
                    break
                branch = (res["repository"] or {}).get("defaultBranchRef")
                if not branch:
                    break
                hist = branch["target"]["history"]
                c = hist["totalCount"]
                for node in hist["nodes"]:
                    a += node["additions"]
                    d += node["deletions"]
                if not hist["pageInfo"]["hasNextPage"]:
                    break
                cursor = hist["pageInfo"]["endCursor"]
            entry = {"fingerprint": fingerprint, "commits": c, "added": a, "deleted": d}
            cached[key] = entry
        commits += entry["commits"]
        added += entry["added"]
        deleted += entry["deleted"]

    cache_file.write_text(json.dumps(cached, indent=1))
    return commits, added, deleted


# ---------------------------------------------------------------- ascii art


def load_image(source):
    if source.startswith(("http://", "https://")):
        return Image.open(io.BytesIO(requests.get(source, timeout=30).content))
    return Image.open(ROOT / source)


def background_mask(gray, tolerance):
    """Flood fill the uniform backdrop inwards from the borders."""
    mode = np.bincount(gray.flatten()).argmax()
    flat = np.abs(gray - mode) < tolerance
    h, w = gray.shape
    seen = np.zeros_like(flat)
    queue = deque()
    for x in range(w):
        for y in (0, h - 1):
            if flat[y, x] and not seen[y, x]:
                seen[y, x] = True
                queue.append((y, x))
    for y in range(h):
        for x in (0, w - 1):
            if flat[y, x] and not seen[y, x]:
                seen[y, x] = True
                queue.append((y, x))
    while queue:
        y, x = queue.popleft()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and flat[ny, nx] and not seen[ny, nx]:
                seen[ny, nx] = True
                queue.append((ny, nx))
    return seen


def ascii_art(source, width, invert=False, remove_bg=True, tolerance=14, char_ratio=0.53):
    src = load_image(source)
    gray = np.array(src.convert("L")).astype(int)
    if invert:
        gray = 255 - gray

    if src.mode in ("RGBA", "LA"):
        bg = np.array(src.convert("RGBA"))[:, :, 3] < 128
    elif remove_bg:
        bg = background_mask(gray, tolerance)
    else:
        bg = np.zeros(gray.shape, dtype=bool)

    subject = gray[~bg] if (~bg).any() else gray
    lo, hi = np.percentile(subject, 2), np.percentile(subject, 98)
    norm = np.clip((gray - lo) / max(1, hi - lo), 0, 1)

    rows_n = max(1, int(width * gray.shape[0] / gray.shape[1] * char_ratio))
    tone = Image.fromarray((norm * 255).astype("uint8")).resize((width, rows_n), Image.LANCZOS)
    hole = Image.fromarray((bg * 255).astype("uint8")).resize((width, rows_n), Image.LANCZOS)

    rows = []
    for y in range(rows_n):
        line = ""
        for x in range(width):
            if hole.getpixel((x, y)) > 140:
                line += " "
            else:
                line += RAMP[min(len(RAMP) - 1, tone.getpixel((x, y)) * len(RAMP) // 256)]
        rows.append(line.rstrip())
    while rows and not rows[0].strip():
        rows.pop(0)
    while rows and not rows[-1].strip():
        rows.pop()
    return rows


# ---------------------------------------------------------------- svg


TAGS = {"g": "green", "r": "red", "v": "value", "l": "label"}
RULE = "\u2500"  # solid box-drawing line, like the reference header
MARKUP = re.compile(r"\[([grvl])](.*?)\[/]")


def spans(content, default, theme):
    """Split '[g]+5[/] ok' into coloured tspans."""
    out, pos = [], 0
    for m in MARKUP.finditer(content):
        if m.start() > pos:
            out.append((content[pos:m.start()], default))
        out.append((m.group(2), TAGS[m.group(1)]))
        pos = m.end()
    if pos < len(content):
        out.append((content[pos:], default))
    return [(t, theme[k]) for t, k in out if t]


def plain(content):
    return MARKUP.sub(r"\2", content)


def tspan(txt, fill, bold=False):
    return (f'<tspan fill="{fill}"' + (' font-weight="bold"' if bold else "") + ">"
            + escape(txt) + "</tspan>")


def rule_spans(length, theme):
    """Solid horizontal rule that ends in the reference's `-<rule>-` tail."""
    length = max(4, length)
    return [(RULE * (length - 3), theme["rule"]), ("-" + RULE + "-", theme["rule"])]


def build_svg(cfg, art, rows, theme, char_w, line_h, font_size):
    pad_x, pad_y = 26, 24
    body_cols = cfg.get("body_width", 66)
    art_cols = max((len(r) for r in art), default=0)

    # the art is printed exactly as given; only its font size is scaled so the
    # block ends up as tall as the text column next to it
    scale = cfg.get("ascii_scale", 1.0)
    body_h = len(rows) * line_h
    art_line_h = (body_h / len(art)) * scale if art else line_h
    art_font = art_line_h / 1.25
    art_char_w = art_font * 0.6
    art_w = art_cols * art_char_w

    body_x = pad_x + art_w + 3 * char_w
    width = body_x + body_cols * char_w + pad_x
    height = pad_y * 2 + max(len(art) * art_line_h, body_h) + 6

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" height="{height:.0f}" '
        f'font-family="JetBrains Mono, Cascadia Code, DejaVu Sans Mono, Consolas, monospace" '
        f'font-size="{font_size}">',
        f'<rect width="100%" height="100%" rx="16" fill="{theme["bg"]}"/>',
    ]

    y = pad_y + art_font
    for row in art:
        out.append(f'<text x="{pad_x}" y="{y:.1f}" fill="{theme["ascii"]}" '
                   f'font-size="{art_font:.2f}" xml:space="preserve">{escape(row)}</text>')
        y += art_line_h

    y = pad_y + font_size
    for row in rows:
        pieces = []
        kind = row[0]
        if kind == "blank":
            pieces = [(".", theme["dots"])]
        elif kind == "title":
            label = row[1]
            pieces = [(label + " ", theme["title"])] + rule_spans(body_cols - len(label) - 1, theme)
        elif kind == "section":
            label = row[1]
            pieces = ([("- ", theme["rule"]), (label + " ", theme["title"])]
                      + rule_spans(body_cols - len(label) - 3, theme))
        elif kind == "item":
            label, value = row[1], row[2]
            text_len = len(plain(value))
            dots = "." * max(1, body_cols - 2 - (len(label) + 2) - text_len - 1)
            pieces = [(". ", theme["dots"]), (label, theme["label"]), (":", theme["value"]),
                      (" " + dots + " ", theme["dots"])] + spans(value, "value", theme)
        elif kind == "split":
            (l1, v1), (l2, v2) = row[1], row[2]
            half = (body_cols - 5) // 2
            d1 = "." * max(1, half - len(l1) - 2 - len(plain(v1)))
            d2 = "." * max(1, (body_cols - 5 - half) - len(l2) - 2 - len(plain(v2)))
            pieces = ([(". ", theme["dots"]), (l1, theme["label"]), (":", theme["value"]),
                       (" " + d1 + " ", theme["dots"])]
                      + spans(v1, "value", theme)
                      + [(" | ", theme["rule"]), (l2, theme["label"]), (":", theme["value"]),
                         (" " + d2 + " ", theme["dots"])]
                      + spans(v2, "value", theme))
        out.append(f'<text x="{body_x:.1f}" y="{y:.1f}" xml:space="preserve">'
                   + "".join(tspan(t, c, bold=(c != theme["dots"])) for t, c in pieces)
                   + "</text>")
        y += line_h

    out.append("</svg>")
    return "\n".join(out)


LANG_COLORS = {
    "Python": "#3572A5", "JavaScript": "#f1e05a", "TypeScript": "#3178c6",
    "HTML": "#e34c26", "CSS": "#563d7c", "Shell": "#89e051", "C": "#555555",
    "C++": "#f34b7d", "Java": "#b07219", "Go": "#00ADD8", "Rust": "#dea584",
    "Jupyter Notebook": "#DA5B0B", "Dockerfile": "#384d54", "Makefile": "#427819",
}


def build_activity_svg(cfg, theme, calendar, lang_sizes, stats, width, char_w, font_size):
    """Contribution heatmap + language bars, in the same palette as the card."""
    pad = 26
    gap = 3
    weeks = calendar["weeks"]
    cell = (width - 2 * pad) / len(weeks) - gap  # heatmap spans the whole card
    grid_w = len(weeks) * (cell + gap)
    top = pad + 30
    ranked = sorted(lang_sizes.items(), key=lambda kv: -kv[1])[:5]
    height = top + 7 * (cell + gap) + 26 + 34 + 38 + len(ranked) * 22 + pad

    peak = max((d["contributionCount"] for w in weeks for d in w["contributionDays"]), default=0) or 1
    steps = [theme["bg"], "#173a2a", "#1f6f3f", "#2ea043", "#4ae168"]

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" height="{height:.0f}" '
        f'font-family="JetBrains Mono, Cascadia Code, DejaVu Sans Mono, Consolas, monospace" '
        f'font-size="{font_size}">',
        f'<rect width="100%" height="100%" rx="16" fill="{theme["bg"]}"/>',
        f'<text x="{pad}" y="{pad + 14}" font-weight="bold" fill="{theme["title"]}">'
        f'contribution activity</text>',
        f'<text x="{pad + grid_w - 8:.0f}" y="{pad + 14}" text-anchor="end" fill="{theme["label"]}" '
        f'font-weight="bold">{calendar["totalContributions"]:,} contributions this year</text>',
    ]

    for wx, week in enumerate(weeks):
        for dy, day in enumerate(week["contributionDays"]):
            n = day["contributionCount"]
            level = 0 if not n else min(4, 1 + int(n * 3 / peak))
            x = pad + wx * (cell + gap)
            y = top + dy * (cell + gap)
            out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{cell:.1f}" height="{cell:.1f}" rx="3" '
                       f'fill="{steps[level]}" stroke="#1d2530"/>')

    y = top + 7 * (cell + gap) + 26
    current, longest, best = stats
    parts = [("current streak", f"{current} days"), ("longest streak", f"{longest} days"),
             ("best day", f"{best} commits")]
    x = pad
    for label, value in parts:
        out.append(f'<text x="{x}" y="{y}" fill="{theme["label"]}" font-weight="bold">{label}:</text>')
        out.append(f'<text x="{x + (len(label) + 2) * char_w:.0f}" y="{y}" fill="{theme["value"]}" '
                   f'font-weight="bold">{value}</text>')
        x += (len(label) + len(value) + 5) * char_w

    # language bars
    total = sum(lang_sizes.values()) or 1
    y += 34
    out.append(f'<text x="{pad}" y="{y}" fill="{theme["title"]}" font-weight="bold">most used languages</text>')
    bar_x = pad + 200
    bar_w = width - bar_x - pad - 70
    y += 8
    left = 0.0
    for name, size in ranked:
        frac = size / total
        w = bar_w * frac
        out.append(f'<rect x="{bar_x + left:.1f}" y="{y}" width="{max(2, w):.1f}" height="14" rx="3" '
                   f'fill="{LANG_COLORS.get(name, theme["value"])}"/>')
        left += w
    y += 30
    for name, size in ranked:
        pct = size * 100 / total
        out.append(f'<text x="{pad}" y="{y}" fill="{theme["label"]}" font-weight="bold">{escape(name)}</text>')
        out.append(f'<rect x="{bar_x}" y="{y - 11}" width="{max(2, (width - bar_x - pad - 70) * pct / 100):.1f}" '
                   f'height="12" rx="3" fill="{LANG_COLORS.get(name, theme["value"])}"/>')
        out.append(f'<text x="{width - pad:.0f}" y="{y}" text-anchor="end" fill="{theme["value"]}" '
                   f'font-weight="bold">{pct:.1f}%</text>')
        y += 22
    out.append("</svg>")
    return "\n".join(out)


def wrap(text, cols):
    """Greedy word wrap for a monospace column."""
    words, lines, line = text.split(), [], ""
    for word in words:
        if line and len(line) + 1 + len(word) > cols:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    if line:
        lines.append(line)
    return lines


LOGOS = ROOT / "logos"


def logo_path(slug):
    """Simple Icons glyph (24x24 path data), cached in logos/ so builds work offline."""
    if not slug:
        return None
    LOGOS.mkdir(exist_ok=True)
    f = LOGOS / f"{slug}.svg"
    if not f.exists():
        sources = [f"https://cdn.jsdelivr.net/npm/simple-icons@latest/icons/{slug}.svg",
                   f"https://cdn.simpleicons.org/{slug}"]
        for url in sources:
            try:
                r = requests.get(url, timeout=20)
            except requests.RequestException:
                continue
            if r.status_code == 200 and "<path" in r.text:
                f.write_text(r.text)
                break
        else:
            return None
    m = re.search(r'<path[^>]*\sd="([^"]+)"', f.read_text())
    return m.group(1) if m else None


def rich_spans(text):
    """Split '**bold**' markup into (chunk, bold) pairs."""
    return [(p, i % 2 == 1) for i, p in enumerate(re.split(r"\*\*", text)) if p]


def wrap_rich(text, cols):
    """Word wrap that keeps '**bold**' runs intact, returning lines of (chunk, bold)."""
    lines, line, used = [], [], 0
    tail_space = True
    for chunk, bold in rich_spans(text):
        # '**bold**.' keeps the '.' tight, 'an **bold**' keeps its space
        glue = not (chunk.startswith(" ") or tail_space)
        tail_space = chunk.endswith(" ")
        for word in chunk.split(" "):
            if not word:
                glue = False
                continue
            space = bool(used) and not glue
            glue = False
            need = len(word) + (1 if space else 0)
            if used and used + need > cols:
                lines.append(line)
                line, used = [], 0
                need, space = len(word), False
            piece = (" " if space else "") + word
            if line and line[-1][1] == bold:
                line[-1] = (line[-1][0] + piece, bold)
            else:
                line.append((piece, bold))
            used += need
    if line:
        lines.append(line)
    return lines


def build_about_svg(cfg, theme, width, char_w, font_size):
    """The About paragraph inside a rounded panel, same palette as the card."""
    pad, box_pad = 26, 22
    line_h = font_size * 1.65
    cols = int((width - 2 * pad - 2 * box_pad) / char_w)
    title = cfg.get("about_title", "about")
    lines = wrap_rich(cfg["about"].strip(), cols)
    box_h = box_pad * 2 + line_h * (len(lines) + 1)
    height = pad * 2 + box_h

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" height="{height:.0f}" '
        f'font-family="JetBrains Mono, Cascadia Code, DejaVu Sans Mono, Consolas, monospace" '
        f'font-size="{font_size:.1f}">',
        f'<rect width="100%" height="100%" rx="16" fill="{theme["bg"]}"/>',
        f'<rect x="{pad}" y="{pad}" width="{width - 2 * pad:.0f}" height="{box_h:.1f}" rx="12" '
        f'fill="#131922" stroke="#263140"/>',
    ]
    x = pad + box_pad
    y = pad + box_pad + font_size
    out.append(f'<text x="{x}" y="{y:.1f}" font-weight="bold" fill="{theme["label"]}">'
               f'{escape(title)}</text>')
    for line in lines:
        y += line_h
        spans = "".join(tspan(t, theme["title"] if b else theme["value"], bold=b) for t, b in line)
        out.append(f'<text x="{x}" y="{y:.1f}" xml:space="preserve">{spans}</text>')
    out.append("</svg>")
    return "\n".join(out)


def build_tools_svg(cfg, theme, width, char_w, font_size):
    """Categorised logo pills inside a rounded panel."""
    pad, box_pad = 26, 22
    pill_h = font_size * 2.1
    gap, row_gap = 9, 12
    icon = font_size * 1.15
    label_cols = max(len(c["name"]) for c in cfg["tools"])
    label_w = label_cols * char_w + 26
    avail = width - 2 * pad - 2 * box_pad - label_w

    rows, total_h = [], 0
    for cat in cfg["tools"]:
        lines, line, used = [], [], 0.0
        for item in cat["items"]:
            name = item[0]
            slug = item[1] if len(item) > 1 else None
            d = logo_path(slug)
            w = len(name) * char_w + (icon + 12 if d else 0) + 28
            if line and used + gap + w > avail:
                lines.append(line)
                line, used = [], 0.0
            line.append((name, d, item[2] if len(item) > 2 else theme["label"], w))
            used += w + (gap if used else 0)
        if line:
            lines.append(line)
        rows.append((cat["name"], lines))
        total_h += len(lines) * pill_h + (len(lines) - 1) * 6 + row_gap

    box_h = box_pad * 2 + font_size * 1.65 + total_h
    height = pad * 2 + box_h
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" height="{height:.0f}" '
        f'font-family="JetBrains Mono, Cascadia Code, DejaVu Sans Mono, Consolas, monospace" '
        f'font-size="{font_size:.1f}">',
        f'<rect width="100%" height="100%" rx="16" fill="{theme["bg"]}"/>',
        f'<rect x="{pad}" y="{pad}" width="{width - 2 * pad:.0f}" height="{box_h:.1f}" rx="12" '
        f'fill="#131922" stroke="#263140"/>',
        f'<text x="{pad + box_pad}" y="{pad + box_pad + font_size:.1f}" font-weight="bold" '
        f'fill="{theme["label"]}">{escape(cfg.get("tools_title", "toolbox"))}</text>',
    ]

    y = pad + box_pad + font_size * 1.65 + 8
    for name, lines in rows:
        out.append(f'<text x="{pad + box_pad}" y="{y + pill_h / 2 + font_size * 0.36:.1f}" '
                   f'fill="{theme["dots"]}" font-weight="bold">{escape(name)}</text>')
        for line in lines:
            x = pad + box_pad + label_w
            for label, d, color, w in line:
                out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{pill_h:.1f}" '
                           f'rx="{pill_h / 2:.1f}" fill="#f4f8fc"/>')
                tx = x + 14
                if d:
                    s = icon / 24
                    out.append(f'<path d="{d}" fill="{color}" transform="translate('
                               f'{tx:.1f},{y + (pill_h - icon) / 2:.1f}) scale({s:.4f})"/>')
                    tx += icon + 12
                out.append(f'<text x="{tx:.1f}" y="{y + pill_h / 2 + font_size * 0.36:.1f}" '
                           f'fill="#0d1117">{escape(label)}</text>')
                x += w + gap
            y += pill_h + 6
        y += row_gap - 6
    out.append("</svg>")
    return "\n".join(out)


def build_systems_svg(cfg, theme, projects, width, char_w, font_size):
    """One boxed panel per project, in the same palette as the card."""
    pad = 26
    line_h = font_size * 1.5
    box_pad = 18
    gap = 14
    chip_h = font_size + 12
    text_cols = int((width - 2 * pad - 2 * box_pad) / char_w)

    boxes = []
    y = pad + font_size + 22
    for project in projects:
        body = wrap(project["about"], text_cols)
        height = box_pad * 2 + line_h * (1 + len(body)) + chip_h + 8
        boxes.append((y, height, project, body))
        y += height + gap
    height = y - gap + pad

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" height="{height:.0f}" '
        f'font-family="JetBrains Mono, Cascadia Code, DejaVu Sans Mono, Consolas, monospace" '
        f'font-size="{font_size}">',
        f'<rect width="100%" height="100%" rx="16" fill="{theme["bg"]}"/>',
        f'<text x="{pad}" y="{pad + font_size}" font-weight="bold" fill="{theme["title"]}">'
        f'{escape(cfg.get("systems_title", "systems in production"))}</text>',
    ]

    for top, box_h, project, body in boxes:
        out.append(f'<rect x="{pad}" y="{top:.1f}" width="{width - 2 * pad:.0f}" height="{box_h:.1f}" '
                   f'rx="12" fill="#131922" stroke="#263140"/>')
        x = pad + box_pad
        ty = top + box_pad + font_size
        name = project["name"]
        out.append(f'<text x="{x}" y="{ty:.1f}" xml:space="preserve">'
                   + tspan(name, theme["label"], bold=True)
                   + tspan("  " + project.get("tag", ""), theme["dots"])
                   + "</text>")
        for line in body:
            ty += line_h
            out.append(f'<text x="{x}" y="{ty:.1f}" fill="{theme["value"]}" xml:space="preserve">'
                       f'{escape(line)}</text>')

        cy = ty + 14
        cx = x
        for chip in project.get("stack", []):
            w = len(chip) * char_w + 20
            out.append(f'<rect x="{cx:.1f}" y="{cy:.1f}" width="{w:.1f}" height="{chip_h}" rx="{chip_h / 2:.1f}" '
                       f'fill="{theme["bg"]}" stroke="{theme["dots"]}"/>')
            out.append(f'<text x="{cx + w / 2:.1f}" y="{cy + chip_h - 8:.1f}" text-anchor="middle" '
                       f'fill="{theme["title"]}">{escape(chip)}</text>')
            cx += w + 8

    out.append("</svg>")
    return "\n".join(out)


# ---------------------------------------------------------------- content


def language_sizes(repos, exclude=()):
    """Bytes written per language across the user's non-fork repos."""
    sizes = {}
    for repo in repos:
        if repo.get("isFork"):
            continue
        for edge in (repo.get("languages") or {}).get("edges", []):
            name = edge["node"]["name"]
            if name in exclude:
                continue
            sizes[name] = sizes.get(name, 0) + edge["size"]
    return sizes


def top_languages(sizes, fallback, top_n=4):
    """Share of bytes per language across the user's own repos."""
    total = sum(sizes.values())
    if not total:
        return fallback
    ranked = sorted(sizes.items(), key=lambda kv: -kv[1])[:top_n]
    return ", ".join(f"{name} {size * 100 / total:.0f}%" for name, size in ranked)


def last_commit(repos):
    """How long ago the most recently pushed repo was updated."""
    stamps = [r["pushedAt"] for r in repos if r.get("pushedAt")]
    if not stamps:
        return "n/a"
    newest = max(stamps)
    when = datetime.datetime.fromisoformat(newest.replace("Z", "+00:00"))
    delta = datetime.datetime.now(datetime.timezone.utc) - when
    hours = delta.days * 24 + delta.seconds // 3600
    if hours < 1:
        ago = f"{max(1, delta.seconds // 60)} minutes ago"
    elif hours < 48:
        ago = f"{hours} hours ago"
    else:
        ago = f"{delta.days} days ago"
    repo = max(repos, key=lambda r: r.get("pushedAt") or "")["nameWithOwner"].split("/")[-1]
    return f"{ago} ({repo})"


def local_time(tz_name, offset_hours):
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=offset_hours)))
    return f"{now.strftime('%I:%M %p').lstrip('0')} ({tz_name})"


def uptime_from(birthday):
    b = datetime.date.fromisoformat(birthday)
    t = datetime.date.today()
    years = t.year - b.year - ((t.month, t.day) < (b.month, b.day))
    anniversary = datetime.date(t.year - (1 if (t.month, t.day) < (b.month, b.day) else 0), b.month, b.day)
    days = (t - anniversary).days
    return f"{years} years, {days // 30} months, {days % 30} days"


def layout_rows(cfg, values):
    rows = [("title", cfg["title"])]
    for section in cfg["sections"]:
        if section.get("name"):
            rows.append(("section", section["name"]))
        for item in section["items"]:
            if len(item) == 4:
                rows.append(("split", (item[0], item[1].format(**values)),
                             (item[2], item[3].format(**values))))
            else:
                rows.append(("item", item[0], item[1].format(**values)))
        rows.append(("blank",))
    return rows[:-1]


def body_width_for(rows):
    """Narrowest column that still fits every line with a dot leader."""
    need = 0
    for row in rows:
        if row[0] == "item":
            need = max(need, 2 + len(row[1]) + 2 + 1 + len(plain(row[2])))
        elif row[0] == "split":
            (l1, v1), (l2, v2) = row[1], row[2]
            need = max(need, 2 + len(l1) + 2 + 1 + len(plain(v1)) + 3
                       + len(l2) + 2 + 1 + len(plain(v2)))
        elif row[0] in ("title", "section"):
            need = max(need, len(row[1]) + 8)
    return need + 1


def main():
    cfg = yaml.safe_load((ROOT / "config.yml").read_text())
    username = cfg["username"]

    print(f"fetching stats for {username} ...")
    user = user_stats(username)
    repos = all_repos(username)
    stars = sum(r["stargazerCount"] for r in repos)
    calendar = contribution_calendar(username)
    lang_sizes = language_sizes(repos, exclude=set(cfg.get("exclude_languages") or []))

    if os.environ.get("SKIP_LOC") == "1":
        commits = user["contributionsCollection"]["totalCommitContributions"]
        added = deleted = 0
    else:
        commits, added, deleted = commit_stats(username, user["id"], repos)

    values = {
        "uptime": uptime_from(cfg["birthday"]),
        "repos": f"{user['repositories']['totalCount']:,}",
        "contributed": f"{len(repos):,}",
        "stars": f"{stars:,}",
        "commits": f"{commits:,}",
        "followers": f"{user['followers']['totalCount']:,}",
        "loc": f"{added - deleted:,}",
        "loc_added": f"{added:,}",
        "loc_deleted": f"{deleted:,}",
        "top_langs": top_languages(lang_sizes, cfg.get("languages_fallback", "n/a")),
        "last_commit": last_commit(repos),
        "local_time": local_time(cfg.get("timezone", "Asia/Dhaka"),
                                 cfg.get("timezone_offset", 6)),
    }

    art_file = cfg.get("ascii_file")
    if art_file and (ROOT / art_file).exists():
        art = (ROOT / art_file).read_text().splitlines()
    else:
        art = ascii_art(cfg.get("avatar_url") or f"https://github.com/{username}.png?size=400",
                        cfg["ascii_width"],
                        invert=cfg.get("invert_ascii", False),
                        remove_bg=cfg.get("remove_background", True),
                        tolerance=cfg.get("background_tolerance", 14),
                        char_ratio=cfg.get("char_ratio", 0.53))
    (ROOT / "ascii_preview.txt").write_text("\n".join(art))

    rows = layout_rows(cfg, values)
    if not cfg.get("body_width"):
        cfg["body_width"] = body_width_for(rows)
    char_w = cfg.get("char_width", 8.4)
    line_h = cfg.get("line_height", 17.0)
    font_size = cfg.get("font_size", 14)

    card = build_svg(cfg, art, rows, cfg["theme"], char_w, line_h, font_size)
    (ROOT / "dark_mode.svg").write_text(card)
    (ROOT / "light_mode.svg").write_text(
        build_svg(cfg, art, rows, cfg["light_theme"], char_w, line_h, font_size))

    width = float(re.search(r'width="(\d+)"', card).group(1))

    panel_scale = cfg.get("panel_font_scale", 1.25)
    panel_font, panel_char_w = font_size * panel_scale, char_w * panel_scale

    if cfg.get("about"):
        (ROOT / "about.svg").write_text(
            build_about_svg(cfg, cfg["theme"], width, panel_char_w, panel_font))
        print("wrote about.svg")

    if cfg.get("tools"):
        (ROOT / "tools.svg").write_text(
            build_tools_svg(cfg, cfg["theme"], width, panel_char_w, panel_font))
        print("wrote tools.svg")

    if cfg.get("projects"):
        (ROOT / "systems.svg").write_text(
            build_systems_svg(cfg, cfg["theme"], cfg["projects"], width, panel_char_w, panel_font))
        print("wrote systems.svg")

    if cfg.get("activity_card", True):
        (ROOT / "activity.svg").write_text(
            build_activity_svg(cfg, cfg["theme"], calendar, lang_sizes,
                               streaks(calendar), width, char_w, font_size))
        print("wrote activity.svg")
    print("wrote dark_mode.svg + light_mode.svg")


if __name__ == "__main__":
    main()
