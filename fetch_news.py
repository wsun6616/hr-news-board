#!/usr/bin/env python3
"""HR与投资资讯免费在线版抓取脚本。

仅使用 Python 标准库，适合 GitHub Actions 定时运行。
公开仓库只写入公开资讯，不写入任何个人持仓、账户或聊天记录。
"""
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
from urllib.parse import quote, urljoin
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DAILY_DIR = DATA_DIR / "daily"
LATEST_PATH = DATA_DIR / "latest.json"
ARCHIVE_PATH = DATA_DIR / "archive.json"
INVEST_PATH = DATA_DIR / "invest.json"
GLOBAL_PATH = DATA_DIR / "global.json"
INLINE_DATA_PATH = DATA_DIR / "inline-data.js"
STANDALONE_PATH = ROOT / "双击打开-100条.html"
MAX_LATEST = 100
MAX_ARCHIVE = 500
MAX_INVEST = 50
MAX_GLOBAL = 50
BJT = timezone(timedelta(hours=8))

HUBEI_WORK_URL = "https://rst.hubei.gov.cn/bmdt/dtyw/gzdt/index_zzms.shtml"
MOHRSS_RSS_URL = "https://www.mohrss.gov.cn/SYrlzyhshbzb/dongtaixinwen/SYtupianxinwen/rss.xml"
CHINA_FINANCE_RSS_URL = "https://www.chinanews.com.cn/rss/finance.xml"
TENCENT_QUOTE_URL = "https://qt.gtimg.cn/q=usDJI,usIXIC,usINX,hf_GC,hf_SI,hf_CL,hf_HG"
SINA_FX_URL = "https://hq.sinajs.cn/list=fx_susdcny"

# Bloomberg、Reuters 旧官方 RSS 在部分网络中已停用或不稳定，仍保留尝试。
BLOOMBERG_RSS_URLS = [
    "https://feeds.bloomberg.com/markets/news.rss",
    "https://feeds.bloomberg.com/business/news.rss",
    "https://feeds.bloomberg.com/economics/news.rss",
]
REUTERS_RSS_URLS = [
    "https://feeds.reuters.com/reuters/businessNews",
    "https://feeds.reuters.com/reuters/technologyNews",
    "https://feeds.reuters.com/news/wealth",
]

# 稳定的国际公开备用源。
GLOBAL_DIRECT_FEEDS = [
    ("CNBC", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
    ("CNBC", "https://www.cnbc.com/id/10001147/device/rss/rss.html"),
    ("CNBC", "https://www.cnbc.com/id/15839135/device/rss/rss.html"),
    ("CNBC", "https://www.cnbc.com/id/10000664/device/rss/rss.html"),
    ("Nasdaq", "https://www.nasdaq.com/feed/rssoutbound?category=Markets"),
    ("NPR", "https://feeds.npr.org/1006/rss.xml"),
    ("ABC News", "https://abcnews.go.com/abcnews/businessheadlines"),
]

POSITIVE_RE = re.compile(
    r"社保|医保|养老|医疗|公积金|退休|生育|失业|社保卡|劳动合同|试用期|工伤|仲裁|欠薪|加班|裁员|竞业|"
    r"招聘|就业|薪酬|工资|用工|求职|毕业生|灵活就业|职业技能|补贴|见习|劳动人事|维权|薪资|稳岗"
)
NEGATIVE_RE = re.compile(
    r"出席|会晤|致辞|表彰|访问|主持|视频会议|全体大会|部长|新闻发布会|体育|演唱会|旅游|美食|地震|洪水|枪击|台风|"
    r"活动|启动|走进|专场|仪式|会议|座谈|调研|视察|督导|部署|讲话|走访|党组|党委"
)
INVEST_RE = re.compile(
    r"美股|纳斯达克|纳指|标普|道指|华尔街|美联储|加息|降息|美债|国债|债券|黄金|白银|贵金属|铜|"
    r"原油|大宗商品|期货|基金|QDII|ETF|汇率|人民币|美元|通胀|CPI|PCE|央行|利率|股市|A股|"
    r"金融|融资|经贸|关税|出口|进口|世界经济|营商环境|芯片|人工智能|软件|出海|产业|企业"
)
INVEST_EXCLUDE_RE = re.compile(r"乡村|扶贫|帮扶|农田|蔬菜|操场|学校|公益|铁路|渔业|门店|古茗|小学|医圣|医院|经方|医疗")

GLOBAL_RE = re.compile(
    r"market|stock|stocks|share|shares|bond|bonds|fed|federal reserve|rate|rates|interest|inflation|"
    r"economy|economic|treasury|yield|dollar|currency|oil|gold|silver|copper|commodity|commodities|"
    r"etf|fund|central bank|earnings|company|companies|tech|technology|ai|artificial intelligence|"
    r"semiconductor|chip|chips|trade|tariff|nasdaq|s&p|dow|wall street|global|bank|banks|deal|"
    r"business|macro|recession|ecb|imf|crude|brent|wti|merger|acquisition|ipo|equity|equities",
    re.I,
)
GLOBAL_EXCLUDE_RE = re.compile(
    r"sport|celebrity|movie|music|weather|royal|oscars|grammy|nfl|nba|hollywood|game|horoscope|obituary",
    re.I,
)


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


def parse_datetime(value):
    value = clean_text(value)
    if not value:
        return None
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        pass
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
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


def classify_global(title, description):
    text = f"{title} {description}"
    rules = (
        (re.compile(r"fed|federal reserve|ecb|central bank|rate|rates|interest|inflation|cpi|pce|treasury|yield|bond|bonds|dollar|currency", re.I), "gbank", "央行利率"),
        (re.compile(r"oil|gold|silver|copper|commodity|commodities|crude|brent|wti|natural gas", re.I), "gcommodities", "大宗商品"),
        (re.compile(r"ai|artificial intelligence|chip|chips|semiconductor|software|technology|tech|nvidia|apple|microsoft|robot", re.I), "gtech", "科技产业"),
        (re.compile(r"stock|stocks|share|shares|wall street|nasdaq|s&p|dow|equity|equities|ipo|earnings|market", re.I), "gstocks", "海外股市"),
        (re.compile(r"company|companies|merger|acquisition|deal|business|ceo|bank|banks|retail|automaker", re.I), "gcompany", "公司商业"),
        (re.compile(r"economy|economic|global|trade|tariff|imf|recession|macro", re.I), "gmacro", "全球宏观"),
    )
    for regex, channel_id, channel_name in rules:
        if regex.search(title):
            return channel_id, channel_name
    for regex, channel_id, channel_name in rules:
        if regex.search(text):
            return channel_id, channel_name
    return "gmacro", "全球宏观"


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
        "region": "domestic",
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
        "region": "domestic",
    }


def build_global_item(title, link, source, pub_date, description):
    title = clean_text(title)
    title = re.sub(r"\s+-\s+(Bloomberg|Reuters|CNBC|Nasdaq|NPR|ABC News)$", "", title, flags=re.I)
    description = clean_text(description)
    text = f"{title} {description}"
    if not title or not link or not GLOBAL_RE.search(text) or GLOBAL_EXCLUDE_RE.search(title):
        return None
    channel_id, channel_name = classify_global(title, description)
    return {
        "id": link,
        "title": title,
        "link": link,
        "source": source,
        "pubDate": pub_date,
        "description": description[:220],
        "channelId": channel_id,
        "channelName": channel_name,
        "region": "global",
    }


def parse_rss(url, default_source, builder):
    xml_text = fetch_text(url)
    root = ET.fromstring(xml_text)
    items = []
    for node in root.findall(".//item"):
        def get_text(tag):
            found = node.find(tag)
            return clean_text(found.text) if found is not None and found.text else ""

        source = get_text("source") or default_source
        item = builder(
            title=get_text("title"),
            link=get_text("link"),
            source=source,
            pub_date=get_text("pubDate"),
            description=get_text("description"),
        )
        if item:
            items.append(item)
    return items


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
    return parse_rss(MOHRSS_RSS_URL, "人力资源和社会保障部", build_item)


def parse_invest_news():
    return parse_rss(CHINA_FINANCE_RSS_URL, "中新网·财经", build_invest_item)


def google_news_url(brand):
    query = (
        f"site:{brand.lower()}.com AND "
        "(markets OR economy OR stocks OR bonds OR fed OR interest rates OR inflation OR dollar OR gold OR oil)"
    )
    return "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q=" + quote(query)


def parse_google_news_brand(brand):
    def builder(title, link, source, pub_date, description):
        actual_source = brand if brand.lower() in source.lower() else source or brand
        return build_global_item(
            title=title,
            link=link,
            source=f"{actual_source} · Google News",
            pub_date=pub_date,
            description=description,
        )
    return parse_rss(google_news_url(brand), brand, builder)


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
    parsed = parse_datetime(item.get("pubDate"))
    if parsed is None:
        return 0
    if parsed.tzinfo:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed.timestamp()


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


def parse_global_news(errors):
    items = []

    # 优先获取 Bloomberg、Reuters 来源。
    for brand in ("Bloomberg", "Reuters"):
        try:
            items.extend(parse_google_news_brand(brand))
        except Exception as exc:
            errors.append(f"Google News {brand}: {exc}")

    # 若官方旧 RSS 仍可用，则直接接入。
    for source, urls in (("Bloomberg", BLOOMBERG_RSS_URLS), ("Reuters", REUTERS_RSS_URLS)):
        for url in urls:
            try:
                items.extend(parse_rss(url, source, build_global_item))
            except Exception as exc:
                errors.append(f"{source} RSS: {exc}")

    # 稳定国际来源兜底，保证国外板块不空。
    for source, url in GLOBAL_DIRECT_FEEDS:
        try:
            items.extend(parse_rss(url, source, build_global_item))
        except Exception as exc:
            errors.append(f"{source} RSS: {exc}")

    unique = {}
    seen_titles = set()
    for item in items:
        title_key = re.sub(r"[^a-z0-9]+", "", item["title"].lower())[:90]
        if title_key in seen_titles:
            continue
        seen_titles.add(title_key)
        unique[item["link"]] = item
    return sorted(unique.values(), key=time_key, reverse=True)[:MAX_GLOBAL]


def save_global(items):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    sources = sorted({item["source"] for item in items})
    payload = {
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "count": len(items),
        "sources": sources,
        "items": items,
    }
    GLOBAL_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
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
        if NEGATIVE_RE.search(item.get("title", "")):
            continue
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
    global_payload = None
    if INVEST_PATH.exists():
        invest_payload = json.loads(INVEST_PATH.read_text(encoding="utf-8"))
    if GLOBAL_PATH.exists():
        global_payload = json.loads(GLOBAL_PATH.read_text(encoding="utf-8"))

    inline_scripts = ["<script>window.INLINE_HR_DATA = " + json.dumps(latest_payload, ensure_ascii=False, indent=2) + ";</script>"]
    if invest_payload:
        inline_scripts.append("<script>window.INLINE_INVEST_DATA = " + json.dumps(invest_payload, ensure_ascii=False, indent=2) + ";</script>")
    if global_payload:
        inline_scripts.append("<script>window.INLINE_GLOBAL_DATA = " + json.dumps(global_payload, ensure_ascii=False, indent=2) + ";</script>")

    index_html = (ROOT / "index.html").read_text(encoding="utf-8")
    standalone_html = index_html.replace('<script src="data/inline-data.js"></script>', "\n".join(inline_scripts))
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

    global_items = parse_global_news(errors)
    global_payload = save_global(global_items)

    latest, archive = save_data(old_items + collected)
    print(
        f"latest={len(latest)} archive={len(archive)} "
        f"invest={invest_payload['count']} quotes={len(quotes)} global={global_payload['count']}"
    )
    if errors:
        print("warnings:", " | ".join(errors), file=sys.stderr)
    if not latest:
        sys.exit(1)
    if not global_payload["items"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
