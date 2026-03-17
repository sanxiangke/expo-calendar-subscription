#!/usr/bin/env python3
import concurrent.futures as cf
import datetime as dt
import html
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

EXPO_BASE = "https://www.haozhanhui.com"
SHOWSTART_BASE = "https://www.showstart.com"
MAOYAN_BASE = "https://show.maoyan.com"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123 Safari/537.36"
ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = ROOT / "docs"
DATA_DIR = ROOT / "data"
EXPO_CACHE_PATH = DATA_DIR / "expo_detail_cache.json"


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


def strip_html(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    return " ".join(value.split())


def ics_escape(s: str) -> str:
    s = s.replace("\\", "\\\\")
    s = s.replace(";", "\\;").replace(",", "\\,")
    s = s.replace("\n", "\\n")
    return s


def fold_ics_line(line: str, limit: int = 73):
    data = line.encode("utf-8")
    out = []
    while len(data) > limit:
        cut = limit
        while cut > 0 and (data[cut] & 0b11000000) == 0b10000000:
            cut -= 1
        out.append(data[:cut].decode("utf-8", errors="ignore"))
        data = data[cut:]
    out.append(data.decode("utf-8", errors="ignore"))
    return "\r\n ".join(out)


def parse_ymd(date_s: str):
    return dt.datetime.strptime(date_s, "%Y-%m-%d").date()


def parse_month_page(year: int, month: int):
    url = f"{EXPO_BASE}/zhanlanjihua/{year}_{month}___c_1.html"
    text = fetch(url)
    pattern = re.compile(
        r"<li>\s*(\d{4}-\d{2}-\d{2})\s*&nbsp;\s*【([^】]+)】\s*&nbsp;.*?【([^】]+)】\s*&nbsp;.*?<a\s+href=\"([^\"]+)\"[^>]*title=\"([^\"]+)\"",
        re.I | re.S,
    )

    events = []
    for m in pattern.finditer(text):
        date_s, category, city, detail_url, title = m.groups()
        try:
            d = parse_ymd(date_s)
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


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def parse_expo_detail(url: str):
    text = fetch(url)
    meta = re.search(r'<meta name="description" content="([^"]+)"', text, re.I)
    desc = html.unescape(meta.group(1)).strip() if meta else ""

    date_match = re.search(r"在\s*(\d{4}-\d{2}-\d{2})\s*至\s*(\d{4}-\d{2}-\d{2})\s*在\s*([^\s]+)\s+([^,，。；\"]+)举办", desc)
    city = ""
    venue = ""
    start_date = None
    end_date = None
    if date_match:
        start_date = parse_ymd(date_match.group(1))
        end_date = parse_ymd(date_match.group(2))
        city = date_match.group(3).strip()
        venue = date_match.group(4).strip()
    else:
        cv = re.search(r"在\s*([^\s]+)\s+([^,，。；\"]+)举办", desc)
        if cv:
            city = cv.group(1).strip()
            venue = cv.group(2).strip()

    title_m = re.search(r"<h1[^>]*>(.*?)</h1>", text, re.S | re.I)
    title = strip_html(title_m.group(1)) if title_m else ""

    return {
        "title": title,
        "city": city,
        "venue": venue,
        "start_date": start_date.isoformat() if start_date else None,
        "end_date": end_date.isoformat() if end_date else None,
        "description": desc,
    }


def enrich_expo_details(events):
    cache = load_json(EXPO_CACHE_PATH, {})
    urls = sorted({e["url"] for e in events})
    missing = [u for u in urls if u not in cache]

    if missing:
        with cf.ThreadPoolExecutor(max_workers=10) as pool:
            future_map = {pool.submit(parse_expo_detail, url): url for url in missing}
            for fut in cf.as_completed(future_map):
                url = future_map[fut]
                try:
                    cache[url] = fut.result()
                except Exception as ex:
                    print(f"WARN failed expo detail {url}: {ex}", file=sys.stderr)
                    cache[url] = {}
        save_json(EXPO_CACHE_PATH, cache)

    for e in events:
        detail = cache.get(e["url"], {})
        if detail.get("city"):
            e["city"] = detail["city"]
        e["venue"] = detail.get("venue", "").strip()
        e["detail_description"] = detail.get("description", "")
        if detail.get("start_date"):
            e["start_date"] = parse_ymd(detail["start_date"])
        else:
            e["start_date"] = e["date"]
        if detail.get("end_date"):
            e["end_date"] = parse_ymd(detail["end_date"])
        else:
            e["end_date"] = e["date"]
    return events


def gather_expos():
    today = dt.date.today()
    years = [today.year, today.year + 1]
    all_events = []
    for y in years:
        for m in range(1, 13):
            try:
                all_events.extend(parse_month_page(y, m))
            except Exception as ex:
                print(f"WARN failed expo month {y}-{m:02d}: {ex}", file=sys.stderr)

    begin = today - dt.timedelta(days=30)
    end = today + dt.timedelta(days=540)
    dedup = {}
    for e in all_events:
        if not (begin <= e["date"] <= end):
            continue
        k = (e["date"].isoformat(), e["title"], e["city"], e["url"])
        dedup[k] = e

    events = sorted(dedup.values(), key=lambda x: (x["date"], x["city"], x["title"]))
    return enrich_expo_details(events)


def parse_showstart_page(page_no: int):
    url = f"{SHOWSTART_BASE}/event/list?cityCode=0&pageNo={page_no}"
    text = fetch(url)
    pattern = re.compile(
        r'<a href="(/event/(\d+))" class="show-item item".*?<div class="title">(.*?)</div>.*?<div class="time">时间：([^<]+)</div>.*?<div class="addr">.*?\[([^\]]+)\]([^<]+)</div>',
        re.S,
    )
    items = []
    for m in pattern.finditer(text):
        rel_url, event_id, title, time_s, city, venue = m.groups()
        title = strip_html(title)
        time_s = html.unescape(time_s).strip()
        city = html.unescape(city).strip()
        venue = strip_html(venue)
        items.append(
            {
                "id": event_id,
                "url": urllib.parse.urljoin(SHOWSTART_BASE, rel_url),
                "title": title,
                "time_raw": time_s,
                "city": city,
                "venue": venue,
            }
        )
    return items


def is_music_event(title: str):
    keywords = ["演唱会", "音乐节"]
    return any(k in title for k in keywords)


def parse_maoyan_next_data(text: str):
    marker = '__NEXT_DATA__ = '
    start = text.find(marker)
    if start == -1:
        return None
    s = text[start + len(marker):]
    level = 0
    in_str = False
    escape = False
    begin = None
    end = None
    for i, ch in enumerate(s):
        if begin is None:
            if ch == '{':
                begin = i
                level = 1
            continue
        if in_str:
            if escape:
                escape = False
            elif ch == '\\':
                escape = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == '{':
                level += 1
            elif ch == '}':
                level -= 1
                if level == 0:
                    end = i + 1
                    break
    if begin is None or end is None:
        return None
    try:
        return json.loads(s[begin:end])
    except Exception:
        return None


def expand_maoyan_date_range(value: str):
    value = value.strip()
    parts = [p.strip() for p in value.split(' - ')]
    if len(parts) == 2:
        left, right = parts
        left_match = re.match(r'(\d{4})\.(\d{2})\.(\d{2})', left)
        if left_match:
            year = int(left_match.group(1))
            month = int(left_match.group(2))
            day = int(left_match.group(3))
            start = dt.datetime(year, month, day, 19, 30)
            if re.match(r'\d{2}\.\d{2}$', right):
                end_month = int(right[:2])
                end_day = int(right[3:])
                end_dt = dt.datetime(year, end_month, end_day, 19, 30)
            elif re.match(r'\d{4}\.\d{2}\.\d{2}$', right):
                yy, mm, dd = map(int, right.split('.'))
                end_dt = dt.datetime(yy, mm, dd, 19, 30)
            else:
                end_dt = start
            return start, end_dt
    m = re.match(r'(\d{4})\.(\d{2})\.(\d{2})\s+(\d{2}):(\d{2})', value)
    if m:
        y, mo, d, hh, mm = map(int, m.groups())
        start = dt.datetime(y, mo, d, hh, mm)
        return start, start
    m = re.match(r'(\d{4})\.(\d{2})\.(\d{2})', value)
    if m:
        y, mo, d = map(int, m.groups())
        start = dt.datetime(y, mo, d, 19, 30)
        return start, start
    return None, None


def gather_maoyan_live_music():
    text = fetch(MAOYAN_BASE)
    data = parse_maoyan_next_data(text)
    if not data:
        return []
    categories = data.get('props', {}).get('pageProps', {}).get('categoryList', [])
    allowed_ids = {1, 6}  # 演唱会、音乐会
    raw = []
    for cat in categories:
        if cat.get('categoryId') not in allowed_ids:
            continue
        for key_name in ['hotListKey', 'newListKey']:
            list_key = cat.get(key_name)
            for item in cat.get(list_key, []) or []:
                title = (item.get('name') or '').strip()
                city = (item.get('cityName') or '').strip()
                venue = (item.get('shopName') or '').strip()
                address = (item.get('address') or '').strip()
                show_time = (item.get('showTimeRange') or '').strip()
                perf_id = str(item.get('performanceId') or item.get('projectExtendVO', {}).get('projectId') or '')
                if not title or not show_time or not perf_id:
                    continue
                start, end = expand_maoyan_date_range(show_time)
                if not start:
                    continue
                raw.append(
                    {
                        'id': f"maoyan-{perf_id}",
                        'url': urllib.parse.urljoin(MAOYAN_BASE, item.get('shareLink') or f"/pages/show/detail/index?id={perf_id}&isNewPage=true"),
                        'title': title,
                        'city': city,
                        'venue': venue or address or '待补充地点',
                        'address': address,
                        'start': start,
                        'end': (end + dt.timedelta(hours=3)) if end == start else (end + dt.timedelta(days=1)),
                        'source': '猫眼',
                    }
                )
    return raw


def gather_live_music(max_pages: int = 40):
    showstart_items = []
    seen_ids = set()
    stale_pages = 0

    for page_no in range(1, max_pages + 1):
        try:
            items = parse_showstart_page(page_no)
        except Exception as ex:
            print(f"WARN failed showstart page {page_no}: {ex}", file=sys.stderr)
            break

        if not items:
            break

        before = len(seen_ids)
        for item in items:
            if item['id'] not in seen_ids:
                seen_ids.add(item['id'])
                showstart_items.append(item)

        if len(seen_ids) == before:
            stale_pages += 1
        else:
            stale_pages = 0
        if stale_pages >= 2:
            break

    events = []
    now = dt.datetime.now()
    min_dt = now - dt.timedelta(days=7)
    max_dt = now + dt.timedelta(days=540)
    for item in showstart_items:
        title = item['title']
        if not is_music_event(title):
            continue
        try:
            start = dt.datetime.strptime(item['time_raw'], '%Y/%m/%d %H:%M')
        except ValueError:
            continue
        if not (min_dt <= start <= max_dt):
            continue
        events.append(
            {
                'id': f"showstart-{item['id']}",
                'url': item['url'],
                'title': title,
                'city': item['city'],
                'venue': item['venue'],
                'start': start,
                'end': start + dt.timedelta(hours=3),
                'source': '秀动',
            }
        )

    try:
        events.extend(gather_maoyan_live_music())
    except Exception as ex:
        print(f"WARN failed maoyan live music: {ex}", file=sys.stderr)

    dedup = {}
    for e in events:
        if not (min_dt <= e['start'] <= max_dt):
            continue
        norm_title = re.sub(r'\s+', '', e['title']).lower()
        key = (e['start'].strftime('%Y-%m-%d'), norm_title, e['city'])
        # Prefer 猫眼 if it has more structured venue, otherwise keep first.
        prev = dedup.get(key)
        if not prev:
            dedup[key] = e
        elif len(e.get('venue', '')) > len(prev.get('venue', '')):
            dedup[key] = e

    final_events = sorted(dedup.values(), key=lambda x: (x['start'], x['city'], x['title']))
    return final_events


def build_calendar(events, cal_name: str, prod_id: str, mode: str):
    now = dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{prod_id}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{ics_escape(cal_name)}",
        "X-WR-TIMEZONE:Asia/Shanghai",
        "REFRESH-INTERVAL;VALUE=DURATION:P1D",
        "X-PUBLISHED-TTL:P1D",
    ]

    for e in events:
        if mode == "expo":
            start = e["start_date"].strftime("%Y%m%d")
            end = (e["end_date"] + dt.timedelta(days=1)).strftime("%Y%m%d")
            uid_key = f"{start}-{e['title']}-{e['city']}-{e['venue']}"
            description = (
                f"分类：{e['category']}\n"
                f"城市：{e['city']}\n"
                f"地点：{e.get('venue') or '待补充'}\n"
                f"来源：好展会\n"
                f"详情：{e['url']}"
            )
            event_lines = [
                "BEGIN:VEVENT",
                f"UID:{re.sub(r'[^a-zA-Z0-9]+', '', uid_key).lower()[:100]}@taizi",
                f"DTSTAMP:{now}",
                f"DTSTART;VALUE=DATE:{start}",
                f"DTEND;VALUE=DATE:{end}",
                f"SUMMARY:{ics_escape(e['title'])}",
                f"LOCATION:{ics_escape((e['city'] + ' · ' + (e.get('venue') or '待补充地点')).strip())}",
                f"DESCRIPTION:{ics_escape(description)}",
                f"URL:{ics_escape(e['url'])}",
                "STATUS:CONFIRMED",
                "TRANSP:TRANSPARENT",
                "END:VEVENT",
            ]
        else:
            start = e["start"].strftime("%Y%m%dT%H%M%S")
            end = e["end"].strftime("%Y%m%dT%H%M%S")
            uid_key = f"{e['id']}-{e['title']}-{e['city']}-{e['venue']}"
            description = (
                f"城市：{e['city']}\n"
                f"地点：{e['venue']}\n"
                f"来源：{e.get('source', '聚合')}\n"
                f"详情：{e['url']}"
            )
            event_lines = [
                "BEGIN:VEVENT",
                f"UID:{re.sub(r'[^a-zA-Z0-9]+', '', uid_key).lower()[:100]}@taizi",
                f"DTSTAMP:{now}",
                f"DTSTART:{start}",
                f"DTEND:{end}",
                f"SUMMARY:{ics_escape(e['title'])}",
                f"LOCATION:{ics_escape(e['city'] + ' · ' + e['venue'])}",
                f"DESCRIPTION:{ics_escape(description)}",
                f"URL:{ics_escape(e['url'])}",
                "STATUS:CONFIRMED",
                "TRANSP:OPAQUE",
                "END:VEVENT",
            ]

        for line in event_lines:
            lines.append(fold_ics_line(line))

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def write_index(expo_events, live_events):
    updated = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    html_page = f"""<!doctype html>
<html lang=\"zh-CN\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>全国活动日历订阅</title>
  <style>
    body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:860px;margin:40px auto;padding:0 16px;line-height:1.7}}
    code{{background:#f3f3f3;padding:2px 4px;border-radius:4px}}
    .card{{border:1px solid #e5e7eb;border-radius:12px;padding:18px;margin:14px 0}}
  </style>
</head>
<body>
  <h1>全国活动日历订阅</h1>
  <p>更新时间：<b>{updated}</b>（Asia/Shanghai）</p>

  <div class=\"card\">
    <h2>1) 全国展会（日更）</h2>
    <p>事件数：<b>{len(expo_events)}</b></p>
    <p>订阅链接：<a href=\"./china-expos.ics\">china-expos.ics</a></p>
    <p>字段包含：展会名称、城市、具体场馆/地点、来源链接。</p>
  </div>

  <div class=\"card\">
    <h2>2) 全国演唱会和音乐节（日更）</h2>
    <p>事件数：<b>{len(live_events)}</b></p>
    <p>订阅链接：<a href=\"./china-live-music.ics\">china-live-music.ics</a></p>
    <p>字段包含：活动名称、城市、具体地点、时间、来源链接。</p>
  </div>

  <h2>Apple 日历添加方法</h2>
  <ol>
    <li>复制完整 ICS 链接（GitHub Pages 域名 + 文件名）。</li>
    <li>iPhone：设置 → 日历 → 账户 → 添加账户 → 其他 → 添加已订阅的日历。</li>
    <li>Mac：日历 → 文件 → 新建日历订阅。</li>
  </ol>
</body>
</html>
"""
    (DOCS_DIR / "index.html").write_text(html_page, encoding="utf-8")


def main():
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    expo_events = gather_expos()
    live_events = gather_live_music()

    (DOCS_DIR / "china-expos.ics").write_text(
        build_calendar(expo_events, "全国展会（日更）", "-//taizi//China Expo Calendar//CN", "expo"),
        encoding="utf-8",
    )
    (DOCS_DIR / "china-live-music.ics").write_text(
        build_calendar(live_events, "全国演唱会和音乐节（日更）", "-//taizi//China Live Music Calendar//CN", "live"),
        encoding="utf-8",
    )
    write_index(expo_events, live_events)
    print(f"Generated expos={len(expo_events)} live_music={len(live_events)}")


if __name__ == "__main__":
    main()
