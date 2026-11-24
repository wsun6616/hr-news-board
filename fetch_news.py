#!/usr/bin/env python3
"""HR资讯免费在线版抓取脚本。
仅使用 Python 标准库，适合 GitHub Actions 定时运行。
"""
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from html import unescape
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DAILY_DIR = DATA_DIR / "daily"
LATEST_PATH = DATA_DIR / "latest.json"
ARCHIVE_PATH = DATA_DIR / "archive.json"
INVEST_PATH = DATA_DIR / "invest.json"
INLINE_DATA_PATH = DATA_DIR / "inline-data.js"
STANDALONE_PATH = ROOT / "双击打开-100条.html"
MAX_LATEST = 100
MAX_ARCHIVE = 500
MAX_INVEST = 50
BJT = timezone(timedelta(hours=8))

HUBEI_WORK_URL = "https://rst.hubei.gov.cn/bmdt/dtyw/gzdt/index_zzms.shtml"
MOHRSS_RSS_URL = "https://www.mohrss.gov.cn/SYrlzyhshbzb/dongtaixinwen/SYtupianxinwen/rss.xml"
CHINA_FINANCE_RSS_URL = "https://www.chinanews.com.cn/rss/finance.xml"
TENCENT_QUOTE_URL = "https://qt.gtimg.cn/q=usDJI,usIXIC,usINX,hf_GC,hf_SI,hf_CL,hf_HG"
SINA_FX_URL = "https://hq.sinajs.cn/list=fx_susdcny"

POSITIVE_RE = re.compile(
    r"社保|医保|养老|医疗|公积金|退休|生育|失业|社保卡|劳动合同|试用期|工伤|仲裁|欠薪|加班|裁员|竞业|"
    r"招聘|就业|薪酬|工资|用工|求职|毕业生|灵活就业|职业技能|补贴|见习|劳动人事|维权|薪资|稳岗"
)
NEGATIVE_RE = re.compile(
    r"出席|会晤|致辞|表彰|访问|主持|视频会议|全体大会|部长|新闻发布会|体育|演唱会|旅游|美食|地震|洪水|枪击|台风"
)
INVEST_RE = re.compile(
    r"美股|纳斯达克|纳指|标普|道指|华尔街|美联储|加息|降息|美债|国债|债券|黄金|白银|贵金属|铜|"
    r"原油|大宗商品|期货|基金|QDII|ETF|汇率|人民币|美元|通胀|CPI|PCE|央行|利率|股市|A股|"
    r"金融|融资|经贸|关税|出口|进口|世界经济|营商环境|芯片|人工智能|软件|出海|产业|企业"
)
INVEST_EXCLUDE_RE = re.compile(r"乡村|扶贫|帮扶|农田|蔬菜|操场|学校|公益|铁路|渔业|门店|古茗|小学|医圣|医院|经方|医疗")


def fetch_bytes(url, encoding=None):
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": "https://finance.sina.com.cn/",
        },
    )
    with urlopen(request, timeout=45) as response:
        raw = response.read()
    if encoding:
        return raw.decode(encoding, errors="replace")
    return raw.decode("utf-8", errors="replace")


def fetch_text(url):
    return fetch_bytes(url)


def clean_text(value):
    value = unescape(value or "")
    value = re.sub(r"<br\s*/?>", "\n", value, flags=re.I)
    value = re.sub(r"<[^>]+>", "", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def to_float(value):
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return None


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


def classify_invest(title, description):
    text = f"{title} {description}"
    rules = (
        (re.compile(r"美债|国债|债券"), "bond", "债券市场"),
        (re.compile(r"美股|纳指|纳斯达克|标普|道指|华尔街|科技股|A股|股市"), "usstock", "全球股市"),
        (re.compile(r"黄金|白银|贵金属|铜"), "metals", "贵金属与铜"),
        (re.compile(r"原油|大宗商品|期货"), "commodity", "大宗商品"),
        (re.compile(r"基金|QDII|ETF"), "fund", "基金产品"),
        (re.compile(r"芯片|人工智能|软件|智能制造|新能源|材料|工业"), "industry", "产业科技"),
        (re.compile(r"商务部|经贸|关税|出口|进口|出海|贸易"), "trade", "国际贸易"),
        (re.compile(r"美联储|央行|加息|降息|通胀|CPI|PCE|利率|汇率|美元|人民币|金融|融资|营商环境|企业"), "macro", "宏观利率"),
    )
    for regex, channel_id, channel_name in rules:
        if regex.search(title):
            return channel_id, channel_name
    for regex, channel_id, channel_name in rules:
        if regex.search(text):
            return channel_id, channel_name
    return "macro", "宏观市场"


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


def build_invest_item(title, link, source, pub_date, description):
    title = clean_text(title)
    description = clean_text(description)
    text = f"{title} {description}"
    if not title or not link or not INVEST_RE.search(text) or INVEST_EXCLUDE_RE.search(title):
        return None
    channel_id, channel_name = classify_invest(title, description)
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

        item = build_item(
            title=get_text("title"),
            link=get_text("link"),
            source="人力资源和社会保障部",
            pub_date=get_text("pubDate"),
            description=get_text("description"),
        )
        if item:
            items.append(item)
    return items


def parse_invest_news():
    xml_text = fetch_text(CHINA_FINANCE_RSS_URL)
    root = ET.fromstring(xml_text)
    items = []
    for node in root.findall(".//item"):
        def get_text(tag):
            found = node.find(tag)
            return clean_text(found.text) if found is not None and found.text else ""

        item = build_invest_item(
            title=get_text("title"),
            link=get_text("link"),
            source="中新网·财经",
            pub_date=get_text("pubDate"),
            description=get_text("description"),
        )
        if item:
            items.append(item)
    return items


def parse_market_quotes():
    text = fetch_bytes(TENCENT_QUOTE_URL, encoding="gbk")
    quotes = []
    for code, payload in re.findall(r'v_([^=]+)="([^"]*)"', text):
        if code.startswith("us"):
            fields = payload.split("~")
            if len(fields) >= 35:
                quotes.append({
                    "code": code,
                    "name": fields[1],
                    "price": to_float(fields[3]),
                    "change": to_float(fields[31]),
                    "changePercent": to_float(fields[32]),
                    "high": to_float(fields[33]),
                    "low": to_float(fields[34]),
                    "time": fields[30],
                    "category": "美股指数",
                })
        elif code.startswith("hf"):
            fields = payload.split(",")
            if len(fields) >= 14:
                price = to_float(fields[0])
                pre_close = to_float(fields[7])
                change = round(price - pre_close, 4) if price is not None and pre_close is not None else None
                category = {
                    "hf_GC": "贵金属",
                    "hf_SI": "贵金属",
                    "hf_HG": "工业金属",
                    "hf_CL": "能源",
                }.get(code, "大宗商品")
                quotes.append({
                    "code": code,
                    "name": fields[13],
                    "price": price,
                    "change": change,
                    "changePercent": to_float(fields[1]),
                    "high": to_float(fields[4]),
                    "low": to_float(fields[5]),
                    "time": f"{fields[12]} {fields[6]}",
                    "category": category,
                })

    fx_text = fetch_bytes(SINA_FX_URL, encoding="gbk")
    for _, payload in re.findall(r'hq_str_([^=]+)="([^"]*)"', fx_text):
        fields = payload.split(",")
        if len(fields) >= 12:
            quotes.append({
                "code": "USDCNY",
                "name": fields[9],
                "price": to_float(fields[1]),
                "change": to_float(fields[10]),
                "changePercent": to_float(fields[11]),
                "high": to_float(fields[6]),
                "low": to_float(fields[7]),
                "time": fields[0],
                "category": "汇率",
            })
    return quotes


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


def load_old_invest():
    if not INVEST_PATH.exists():
        return []
    try:
        data = json.loads(INVEST_PATH.read_text(encoding="utf-8"))
        return data.get("items", [])
    except (json.JSONDecodeError, OSError):
        return []


def save_invest(items, quotes):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    unique = {}
    for item in items:
        if INVEST_EXCLUDE_RE.search(item.get("title", "")):
            continue
        unique[item["link"]] = item
    invest_items = sorted(unique.values(), key=time_key, reverse=True)[:MAX_INVEST]
    payload = {
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "count": len(invest_items),
        "quotes": quotes,
        "items": invest_items,
    }
    INVEST_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def save_daily(latest, timestamp):
    DAILY_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.fromtimestamp(timestamp, BJT).strftime("%Y-%m-%d")
    payload = {
        "date": today,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "count": len(latest),
        "items": latest,
    }
    (DAILY_DIR / f"{today}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    dates = []
    for path in sorted(DAILY_DIR.glob("*.json"), reverse=True):
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.json", path.name):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                dates.append({"date": data.get("date", path.stem), "count": data.get("count", 0), "path": f"data/daily/{path.name}"})
            except (json.JSONDecodeError, OSError):
                continue
    (DAILY_DIR / "index.json").write_text(
        json.dumps({"updatedAt": datetime.now(timezone.utc).isoformat(), "dates": dates}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def save_data(items):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    unique = {}
    for item in items:
        unique[item["link"]] = item
    merged = sorted(unique.values(), key=time_key, reverse=True)
    timestamp = datetime.now(timezone.utc).timestamp()
    now_iso = datetime.now(timezone.utc).isoformat()

    latest = merged[:MAX_LATEST]
    archive = merged[:MAX_ARCHIVE]
    latest_payload = {"updatedAt": now_iso, "count": len(latest), "items": latest}
    archive_payload = {"updatedAt": now_iso, "count": len(archive), "items": archive}
    LATEST_PATH.write_text(json.dumps(latest_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    ARCHIVE_PATH.write_text(json.dumps(archive_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    INLINE_DATA_PATH.write_text(
        "window.INLINE_HR_DATA = " + json.dumps(latest_payload, ensure_ascii=False, indent=2) + ";\n",
        encoding="utf-8",
    )
    save_daily(latest, timestamp)

    invest_payload = None
    if INVEST_PATH.exists():
        invest_payload = json.loads(INVEST_PATH.read_text(encoding="utf-8"))
    index_html = (ROOT / "index.html").read_text(encoding="utf-8")
    invest_script = ""
    if invest_payload:
        invest_script = "<script>window.INLINE_INVEST_DATA = " + json.dumps(invest_payload, ensure_ascii=False, indent=2) + ";</script>"
    standalone_html = index_html.replace(
        '<script src="data/inline-data.js"></script>',
        "<script>window.INLINE_HR_DATA = "
        + json.dumps(latest_payload, ensure_ascii=False, indent=2)
        + ";</script>"
        + invest_script,
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

    invest_items = []
    quotes = []
    try:
        invest_items = parse_invest_news()
    except Exception as exc:
        errors.append(f"parse_invest_news: {exc}")
    try:
        quotes = parse_market_quotes()
    except Exception as exc:
        errors.append(f"parse_market_quotes: {exc}")
    invest_payload = save_invest(load_old_invest() + invest_items, quotes)

    latest, archive = save_data(old_items + collected)
    print(f"latest={len(latest)} archive={len(archive)} invest={invest_payload['count']} quotes={len(quotes)}")
    if errors:
        print("warnings:", " | ".join(errors), file=sys.stderr)
    if not latest:
        sys.exit(1)


if __name__ == "__main__":
    main()
