#!/usr/bin/env python3
"""HR资讯免费在线版抓取脚本。
仅使用 Python 标准库，适合 GitHub Actions 定时运行。
"""
import json
import re
import sys
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
LATEST_PATH = DATA_DIR / "latest.json"
ARCHIVE_PATH = DATA_DIR / "archive.json"
INLINE_DATA_PATH = DATA_DIR / "inline-data.js"
STANDALONE_PATH = ROOT / "双击打开-100条.html"
MAX_LATEST = 100
MAX_ARCHIVE = 500

HUBEI_WORK_URL = "https://rst.hubei.gov.cn/bmdt/dtyw/gzdt/index_zzms.shtml"
MOHRSS_RSS_URL = "https://www.mohrss.gov.cn/SYrlzyhshbzb/dongtaixinwen/SYtupianxinwen/rss.xml"

POSITIVE_RE = re.compile(
    r"社保|医保|养老|医疗|公积金|退休|生育|失业|社保卡|劳动合同|试用期|工伤|仲裁|欠薪|加班|裁员|竞业|"
    r"招聘|就业|薪酬|工资|用工|求职|毕业生|灵活就业|职业技能|补贴|见习|劳动人事|维权|薪资|稳岗"
)
NEGATIVE_RE = re.compile(
    r"出席|会晤|致辞|表彰|访问|主持|视频会议|全体大会|部长|新闻发布会|体育|演唱会|旅游|美食|地震|洪水|枪击|台风"
)


def fetch_text(url):
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    with urlopen(request, timeout=45) as response:
        raw = response.read()
    return raw.decode("utf-8", errors="replace")


def clean_text(value):
    value = unescape(value or "")
    value = re.sub(r"<br\s*/?>", "\n", value, flags=re.I)
    value = re.sub(r"<[^>]+>", "", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def classify(title, description):
    case_re = re.compile(r"仲裁|争议|维权|欠薪|工伤|劳务碰瓷|劳动用工|劳动关系|违法解除|竞业|薪资|工资")
    practical_re = re.compile(r"社保|医保|养老|失业|社保卡|生育|公积金|稳岗返还|社会保险|医疗")
    market_re = re.compile(r"招聘|就业|求职|岗位|薪酬|创业|用工|毕业生|灵活就业")
    policy_re = re.compile(r"政策|条例|规定|培训|技能|人才|通知|办法")

    for regex, result in (
        (case_re, ("cases", "劳动争议案例")),
        (practical_re, ("practical", "社保医保实务")),
        (market_re, ("market", "招聘市场")),
        (policy_re, ("policy", "政策法规")),
    ):
        if regex.search(title):
            return result

    text = f"{title} {description}"
    for regex, result in (
        (case_re, ("cases", "劳动争议案例")),
        (practical_re, ("practical", "社保医保实务")),
        (market_re, ("market", "招聘市场")),
        (policy_re, ("policy", "政策法规")),
    ):
        if regex.search(text):
            return result
    return "market", "招聘市场"


def build_item(title, link, source, pub_date, description):
    title = clean_text(title)
    description = clean_text(description)
    if not title or not link or not POSITIVE_RE.search(title) or NEGATIVE_RE.search(title):
        return None
    channel_id, channel_name = classify(title, description)
    return {
        "id": link,
        "title": title,
        "link": link,
        "source": source,
        "pubDate": pub_date,
        "description": description[:220],
        "channelId": channel_id,
        "channelName": channel_name,
    }


def parse_hubei_work():
    html = fetch_text(HUBEI_WORK_URL)
    pattern = re.compile(
        r'<div class="txt_erji"><a href="([^"]+)"[^>]*title="([^"]+)"[^>]*>.*?'
        r'<span class="date">([^<]+)</span>\s*<p>(.*?)</p>',
        re.S,
    )
    items = []
    for href, title, date, description in pattern.findall(html):
        link = urljoin(HUBEI_WORK_URL, href)
        item = build_item(
            title=title,
            link=link,
            source="湖北省人社厅·工作动态",
            pub_date=f"{clean_text(date)} 00:00",
            description=description,
        )
        if item:
            items.append(item)
    return items


def parse_mohrss_rss():
    xml_text = fetch_text(MOHRSS_RSS_URL)
    root = ET.fromstring(xml_text)
    items = []
    for node in root.findall(".//item"):
        def get_text(tag):
            found = node.find(tag)
            return clean_text(found.text) if found is not None and found.text else ""

        title = get_text("title")
        link = get_text("link")
        description = get_text("description")
        pub_date = get_text("pubDate")
        item = build_item(
            title=title,
            link=link,
            source="人力资源和社会保障部",
            pub_date=pub_date,
            description=description,
        )
        if item:
            items.append(item)
    return items


def time_key(item):
    for fmt in ("%Y-%m-%d %H:%M", "%a, %d %b %Y %H:%M:%S %z", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(item["pubDate"], fmt)
            if parsed.tzinfo:
                parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
            return parsed.timestamp()
        except ValueError:
            continue
    return 0


def load_old_archive():
    if not ARCHIVE_PATH.exists():
        return []
    try:
        data = json.loads(ARCHIVE_PATH.read_text(encoding="utf-8"))
        return data.get("items", [])
    except (json.JSONDecodeError, OSError):
        return []


def save_data(items):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    unique = {}
    for item in items:
        unique[item["link"]] = item
    merged = sorted(unique.values(), key=time_key, reverse=True)
    timestamp = datetime.now(timezone.utc).isoformat()

    latest = merged[:MAX_LATEST]
    archive = merged[:MAX_ARCHIVE]
    latest_payload = {
        "updatedAt": timestamp,
        "count": len(latest),
        "items": latest,
    }
    archive_payload = {
        "updatedAt": timestamp,
        "count": len(archive),
        "items": archive,
    }
    LATEST_PATH.write_text(
        json.dumps(latest_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    ARCHIVE_PATH.write_text(
        json.dumps(archive_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    INLINE_DATA_PATH.write_text(
        "window.INLINE_HR_DATA = "
        + json.dumps(latest_payload, ensure_ascii=False, indent=2)
        + ";\n",
        encoding="utf-8",
    )
    index_html = (ROOT / "index.html").read_text(encoding="utf-8")
    standalone_html = index_html.replace(
        '<script src="data/inline-data.js"></script>',
        "<script>window.INLINE_HR_DATA = "
        + json.dumps(latest_payload, ensure_ascii=False, indent=2)
        + ";</script>",
    )
    STANDALONE_PATH.write_text(standalone_html, encoding="utf-8")
    return latest, archive


def main():
    old_items = load_old_archive()
    collected = []
    errors = []
    for parser in (parse_hubei_work, parse_mohrss_rss):
        try:
            collected.extend(parser())
        except Exception as exc:
            errors.append(f"{parser.__name__}: {exc}")

    latest, archive = save_data(old_items + collected)
    print(f"latest={len(latest)} archive={len(archive)}")
    if errors:
        print("warnings:", " | ".join(errors), file=sys.stderr)
    if not latest:
        sys.exit(1)


if __name__ == "__main__":
    main()
