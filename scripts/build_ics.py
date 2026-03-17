#!/usr/bin/env python3
import datetime as dt
import html
import re
import sys
import urllib.request
from pathlib import Path

BASE = "https://www.haozhanhui.com"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123 Safari/537.36"


def fetch(url: str, timeout: int = 25) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    for enc in ("utf-8", "gbk", "gb2312", "big5"):
        try:
            return raw.decode(enc)
        except Exception:
            pass
    return raw.decode("utf-8", errors="ignore")


def parse_month_page(year: int, month: int):
    # Pattern observed from source site.
    url = f"{BASE}/zhanlanjihua/{year}_{month}___c_1.html"
    text = fetch(url)

    # Example:
    # <li>2026-03-26&nbsp;【交通工具】&nbsp;&nbsp;【海口】&nbsp;&nbsp;<a href="https://..." title="...">...</a></li>
    pattern = re.compile(
        r"<li>\s*(\d{4}-\d{2}-\d{2})\s*&nbsp;\s*【([^】]+)】\s*&nbsp;.*?【([^】]+)】\s*&nbsp;.*?<a\s+href=\"([^\"]+)\"[^>]*title=\"([^\"]+)\"",
        re.I | re.S,
    )

    events = []
    for m in pattern.finditer(text):
        date_s, category, city, detail_url, title = m.groups()
        try:
            d = dt.datetime.strptime(date_s, "%Y-%m-%d").date()
        except ValueError:
            continue
        events.append(
            {
                "date": d,
                "category": html.unescape(category).strip(),
                "city": html.unescape(city).strip(),
                "title": html.unescape(title).strip(),
                "url": detail_url.strip(),
            }
        )
    return events


def ics_escape(s: str) -> str:
    s = s.replace("\\", "\\\\")
    s = s.replace(";", "\\;").replace(",", "\\,")
    s = s.replace("\n", "\\n")
    return s


def build_ics(events):
    now = dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//taizi//China Expo Calendar//CN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:全国展会（日更）",
        "X-WR-TIMEZONE:Asia/Shanghai",
        "REFRESH-INTERVAL;VALUE=DURATION:P1D",
        "X-PUBLISHED-TTL:P1D",
    ]

    for e in events:
        start = e["date"].strftime("%Y%m%d")
        end = (e["date"] + dt.timedelta(days=1)).strftime("%Y%m%d")
        uid = re.sub(r"[^a-zA-Z0-9]+", "", f"{start}-{e['title']}-{e['city']}").lower()[:80] + "@taizi"
        summary = e["title"]
        location = f"{e['city']}（中国）"
        desc = f"分类：{e['category']}\\n来源：好展会\\n详情：{e['url']}"
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{uid}",
                f"DTSTAMP:{now}",
                f"DTSTART;VALUE=DATE:{start}",
                f"DTEND;VALUE=DATE:{end}",
                f"SUMMARY:{ics_escape(summary)}",
                f"LOCATION:{ics_escape(location)}",
                f"DESCRIPTION:{ics_escape(desc)}",
                f"URL:{ics_escape(e['url'])}",
                "STATUS:CONFIRMED",
                "TRANSP:TRANSPARENT",
                "END:VEVENT",
            ]
        )

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def main():
    today = dt.date.today()
    years = [today.year, today.year + 1]

    all_events = []
    for y in years:
        for m in range(1, 13):
            try:
                items = parse_month_page(y, m)
                all_events.extend(items)
            except Exception as ex:
                print(f"WARN failed month {y}-{m:02d}: {ex}", file=sys.stderr)

    # Keep from 30 days in the past to 540 days in the future.
    begin = today - dt.timedelta(days=30)
    end = today + dt.timedelta(days=540)

    dedup = {}
    for e in all_events:
        if not (begin <= e["date"] <= end):
            continue
        k = (e["date"].isoformat(), e["title"], e["city"])
        dedup[k] = e

    events = sorted(dedup.values(), key=lambda x: (x["date"], x["city"], x["title"]))

    out_dir = Path(__file__).resolve().parents[1] / "docs"
    out_dir.mkdir(parents=True, exist_ok=True)

    ics = build_ics(events)
    (out_dir / "china-expos.ics").write_text(ics, encoding="utf-8")

    updated = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    html_page = f"""<!doctype html>
<html lang=\"zh-CN\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>全国展会日历订阅</title>
  <style>body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:760px;margin:40px auto;padding:0 16px;line-height:1.6}}code{{background:#f3f3f3;padding:2px 4px;border-radius:4px}}</style>
</head>
<body>
  <h1>全国展会日历（每天自动更新）</h1>
  <p>当前事件数：<b>{len(events)}</b>，更新时间：{updated}（Asia/Shanghai）。</p>
  <p>订阅链接：<a href=\"./china-expos.ics\">china-expos.ics</a></p>
  <h2>Apple 日历添加方法</h2>
  <ol>
    <li>复制完整 ICS 链接（GitHub Pages 域名 + <code>/china-expos.ics</code>）。</li>
    <li>打开 iPhone / Mac「日历」→ 添加日历订阅。</li>
    <li>粘贴链接并保存；系统会定期自动拉取更新。</li>
  </ol>
</body>
</html>
"""
    (out_dir / "index.html").write_text(html_page, encoding="utf-8")
    print(f"Generated {len(events)} events")


if __name__ == "__main__":
    main()
