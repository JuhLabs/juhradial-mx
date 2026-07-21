#!/usr/bin/env python3
"""Render the repository star-history chart to assets/github/star-history.svg.

Runs in CI (see .github/workflows/star-history.yml) where GITHUB_TOKEN grants
stargazer access; GitHub restricts that data to repository admins and
collaborators, so public chart services can no longer serve it.

Usage: GITHUB_TOKEN=... [GITHUB_REPOSITORY=owner/repo] scripts/render-star-history.py
"""
import datetime
import json
import os
import sys
import urllib.request

REPO = os.environ.get("GITHUB_REPOSITORY", "JuhLabs/juhradial-mx")
TOKEN = os.environ.get("GITHUB_TOKEN")
OUT = os.path.join(os.path.dirname(__file__), "..", "assets", "github", "star-history.svg")

W, H = 600, 380
PAD_L, PAD_R, PAD_T, PAD_B = 64, 36, 52, 56
MATTE, STROKE, BG, GRID, MUTED, FG, ACCENT = (
    12, "#30363d", "#0d1117", "#21262d", "#9198a1", "#e6edf3", "#4FEFC9",
)


def fetch_star_dates():
    if not TOKEN:
        sys.exit("GITHUB_TOKEN is required")
    dates, page = [], 1
    while True:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{REPO}/stargazers?per_page=100&page={page}",
            headers={
                "Accept": "application/vnd.github.star+json",
                "Authorization": f"Bearer {TOKEN}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            batch = json.load(resp)
        if not batch:
            break
        dates += [
            datetime.datetime.fromisoformat(s["starred_at"].replace("Z", "+00:00"))
            for s in batch
        ]
        page += 1
    return sorted(dates)


def render(dates):
    n = len(dates)
    t0, t1 = dates[0], dates[-1]
    span = (t1 - t0).total_seconds() or 1
    x0, x1 = PAD_L + MATTE, W - PAD_R + MATTE
    y0, y1 = H - PAD_B + MATTE, PAD_T + MATTE

    def point(i, d):
        x = x0 + (x1 - x0) * (d - t0).total_seconds() / span
        y = y0 - (y0 - y1) * (i / n)
        return x, y

    pts = [point(i + 1, d) for i, d in enumerate(dates)]
    poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    area = f"{x0:.1f},{y0:.1f} {poly} {pts[-1][0]:.1f},{y0:.1f}"

    step = max(10, (n // 4 + 9) // 10 * 10)
    grid, ylabels = [], []
    for count in range(0, n + step, step):
        y = y0 - (y0 - y1) * (count / n)
        if y < y1 - 1:
            break
        grid.append(f'<line x1="{x0}" y1="{y:.1f}" x2="{x1}" y2="{y:.1f}" stroke="{GRID}"/>')
        ylabels.append(
            f'<text x="{x0 - 10}" y="{y + 4:.1f}" text-anchor="end" fill="{MUTED}" font-size="11">{count}</text>'
        )

    xlabels, seen = [], set()
    d = t0
    while d <= t1:
        if (d.year, d.month) not in seen:
            seen.add((d.year, d.month))
            x = x0 + (x1 - x0) * (d - t0).total_seconds() / span
            xlabels.append((x, d.strftime("%b %y")))
        d += datetime.timedelta(days=1)
    if len(xlabels) > 6:
        xlabels = xlabels[:: (len(xlabels) + 5) // 6]
    months = "".join(
        f'<text x="{x:.1f}" y="{y0 + 22}" fill="{MUTED}" font-size="11">{label}</text>'
        for x, label in xlabels
    )

    tw, th = W + 2 * MATTE, H + 2 * MATTE
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{tw}" height="{th}" viewBox="0 0 {tw} {th}" role="img" aria-label="{REPO} cumulative GitHub stars over time, currently {n}">
<rect width="{tw}" height="{th}" fill="{BG}"/>
<rect x="0.5" y="0.5" width="{tw - 1}" height="{th - 1}" fill="none" stroke="{STROKE}"/>
<text x="{tw / 2}" y="{MATTE + 28}" text-anchor="middle" fill="{FG}" font-size="15" font-weight="600" font-family="system-ui, sans-serif">{REPO} · star history</text>
{"".join(grid)}
{"".join(ylabels)}
{months}
<polygon points="{area}" fill="{ACCENT}" opacity="0.12"/>
<polyline points="{poly}" fill="none" stroke="{ACCENT}" stroke-width="2" stroke-linejoin="round"/>
<circle cx="{pts[-1][0]:.1f}" cy="{pts[-1][1]:.1f}" r="4" fill="{ACCENT}"/>
<text x="{pts[-1][0] - 10:.1f}" y="{pts[-1][1] - 10:.1f}" text-anchor="end" fill="{FG}" font-size="12" font-family="system-ui, sans-serif">{n} stars</text>
</svg>
"""


def main():
    dates = fetch_star_dates()
    if not dates:
        sys.exit("no stargazer data returned")
    svg = render(dates)
    with open(OUT, "w") as f:
        f.write(svg)
    print(f"rendered {len(dates)} stars to {os.path.relpath(OUT)}")


if __name__ == "__main__":
    main()
