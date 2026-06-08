#!/usr/bin/env python3
"""港美股雷达 — 抓取信源 → 港美股相关性/标的识别/分类打分 → 去重 → 合并事件线 → 写 JSON。

纯静态产物，运行后写入 data/*.json，前端直接消费。
依赖: feedparser, requests （见 requirements.txt）。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

import feedparser
import requests

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
FEEDS_FILE = ROOT / "feeds" / "sources.opml"

WINDOW_HOURS = int(os.environ.get("RADAR_WINDOW_HOURS", "48"))
NOW = datetime.now(timezone.utc)
WINDOW_START = NOW - timedelta(hours=WINDOW_HOURS)
USER_AGENT = "Mozilla/5.0 (compatible; HKUSStockRadar/1.0; +https://github.com/)"
TIMEOUT = 20

# ------------------------------------------------------------------ #
#  标的 / 市场识别词典
# ------------------------------------------------------------------ #
# 常见港股（代码 -> 名称）；可在 feeds 旁扩展，也可后续从用户清单注入
HK_TICKERS = {
    "00700": "腾讯控股", "09988": "阿里巴巴", "03690": "美团", "01810": "小米集团",
    "09618": "京东集团", "00941": "中国移动", "00939": "建设银行", "01299": "友邦保险",
    "00388": "香港交易所", "02318": "中国平安", "01024": "快手", "09999": "网易",
    "02020": "安踏体育", "01211": "比亚迪股份", "00883": "中国海洋石油",
    "09868": "小鹏汽车", "02015": "理想汽车", "09866": "蔚来", "06618": "京东健康",
    "03888": "金山软件", "00981": "中芯国际", "01928": "金沙中国", "02269": "药明生物",
}
HK_NAME_TO_CODE = {v: k for k, v in HK_TICKERS.items()}

# 常见美股（ticker -> 中文名）
US_TICKERS = {
    "AAPL": "苹果", "MSFT": "微软", "NVDA": "英伟达", "GOOGL": "谷歌", "GOOG": "谷歌",
    "AMZN": "亚马逊", "META": "Meta", "TSLA": "特斯拉", "AMD": "AMD", "INTC": "英特尔",
    "NFLX": "奈飞", "AVGO": "博通", "TSM": "台积电", "BABA": "阿里巴巴", "PDD": "拼多多",
    "JD": "京东", "NIO": "蔚来", "XPEV": "小鹏", "LI": "理想", "BIDU": "百度",
    "COIN": "Coinbase", "MSTR": "MicroStrategy", "PLTR": "Palantir", "MU": "美光",
    "ORCL": "甲骨文", "CRM": "Salesforce", "ADBE": "Adobe", "SMCI": "超微",
    "ARM": "Arm", "DELL": "戴尔", "QCOM": "高通", "MRVL": "Marvell",
}
US_NAME_TO_TICKER = {}
for t, n in US_TICKERS.items():
    US_NAME_TO_TICKER.setdefault(n, t)

# 市场关键词（用于无明确标的时的市场归属）
HK_KEYWORDS = ["港股", "恒生", "恒指", "港交所", "南向", "港元", "联交所", "h股", "国企指数", "hsi"]
US_KEYWORDS = ["美股", "纳斯达克", "纳指", "道指", "标普", "道琼斯", "纽交所", "美联储", "fed",
               "nasdaq", "s&p", "dow", "wall street", "华尔街"]
CN_KEYWORDS = ["a股", "上证", "深证", "创业板", "科创板", "沪深", "北向"]

# 股市强相关信号词（判断是否纳入）
STOCK_SIGNALS = [
    "股", "财报", "业绩", "营收", "净利", "盈利", "亏损", "指引", "回购", "分红", "派息",
    "减持", "增持", "ipo", "招股", "上市", "退市", "停牌", "复牌", "并购", "重组", "收购",
    "评级", "目标价", "研报", "做空", "做多", "涨", "跌", "成交", "市值", "估值", "美联储",
    "加息", "降息", "通胀", "cpi", "非农", "盘前", "盘后", "期权", "板块", "概念股",
    "earnings", "revenue", "guidance", "buyback", "dividend", "ipo", "merger", "acquisition",
    "upgrade", "downgrade", "stock", "shares", "nasdaq", "fed", "rate cut", "rate hike",
    "quarterly", "outlook", "analyst",
]

NOISE_WORDS = ["菜谱", "星座", "游戏攻略", "明星", "八卦", "穿搭"]

# 分类规则（按优先级）
CATEGORY_RULES = [
    ("earnings", ["财报", "业绩", "营收", "净利", "盈利", "季报", "年报", "earnings", "revenue", "quarterly results", "profit"]),
    ("guidance", ["指引", "展望", "预期", "guidance", "outlook", "forecast"]),
    ("ipo", ["ipo", "招股", "上市", "新股", "递表", "招股书", "退市", "listing"]),
    ("ma", ["并购", "重组", "收购", "合并", "私有化", "merger", "acquisition", "buyout", "takeover"]),
    ("capital", ["回购", "增持", "减持", "配股", "分红", "派息", "股东", "buyback", "dividend", "stake", "insider"]),
    ("rating", ["评级", "目标价", "研报", "上调", "下调", "买入", "卖出", "首予", "upgrade", "downgrade", "analyst", "price target", "rating"]),
    ("policy", ["监管", "政策", "证监会", "央行", "关税", "制裁", "调查", "处罚", "规定", "regulat", "sec ", "antitrust", "tariff", "sanction", "probe"]),
    ("macro", ["美联储", "加息", "降息", "通胀", "cpi", "非农", "gdp", "利率", "经济", "fed", "inflation", "rate", "jobs", "macro", "economy"]),
    ("product", ["发布", "推出", "新品", "合作", "订单", "中标", "launch", "unveil", "partnership", "deal", "contract"]),
]


def log(msg: str) -> None:
    print(f"[radar] {msg}", flush=True)


# ------------------------------------------------------------------ #
#  OPML 解析
# ------------------------------------------------------------------ #
def parse_opml(path: Path):
    """返回 [(site_id, site_name, feed_title, feed_url, market_hint)]"""
    feeds = []
    if not path.exists():
        log(f"feeds file not found: {path}")
        return feeds
    tree = ET.parse(path)
    root = tree.getroot()
    body = root.find("body")
    if body is None:
        return feeds

    def walk(node, site_id, site_name):
        for child in node.findall("outline"):
            url = child.get("xmlUrl")
            if url:
                feeds.append((
                    site_id or "misc",
                    site_name or "其他",
                    child.get("title") or child.get("text") or url,
                    url,
                    (child.get("market") or "").upper(),
                ))
            else:
                # 分组节点
                gid = child.get("id") or child.get("text") or site_id
                gname = child.get("text") or child.get("title") or site_name
                walk(child, gid, gname)

    walk(body, None, None)
    return feeds


# ------------------------------------------------------------------ #
#  抓取
# ------------------------------------------------------------------ #
def fetch_feed(url: str):
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
        resp.raise_for_status()
        return feedparser.parse(resp.content), None
    except Exception as e:  # noqa: BLE001
        return None, str(e)


def entry_time(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            try:
                return datetime.fromtimestamp(time.mktime(t), tz=timezone.utc)
            except Exception:  # noqa: BLE001
                pass
    return None


# ------------------------------------------------------------------ #
#  标的 / 市场 / 分类识别
# ------------------------------------------------------------------ #
def detect_tickers(text: str):
    tickers = []
    seen = set()

    # 港股 5 位代码 (00700 / 0700.HK / 700.HK)
    for m in re.finditer(r"\b(\d{4,5})(?:\.HK|\.hk)?\b", text):
        code = m.group(1).zfill(5)
        if code in HK_TICKERS and code not in seen:
            seen.add(code)
            tickers.append({"symbol": code, "name": HK_TICKERS[code], "market": "HK"})

    # 美股 $TICKER 或独立大写 ticker
    for m in re.finditer(r"\$?\b([A-Z]{2,5})\b", text):
        sym = m.group(1)
        if sym in US_TICKERS and sym not in seen:
            seen.add(sym)
            tickers.append({"symbol": sym, "name": US_TICKERS[sym], "market": "US"})

    # 中文名匹配
    for name, code in HK_NAME_TO_CODE.items():
        if name in text and code not in seen:
            seen.add(code)
            tickers.append({"symbol": code, "name": name, "market": "HK"})
    for name, sym in US_NAME_TO_TICKER.items():
        if name in text and sym not in seen:
            seen.add(sym)
            tickers.append({"symbol": sym, "name": name, "market": "US"})

    return tickers


def detect_markets(text_low: str, tickers, market_hint: str):
    markets = []
    # 1) 明确标的优先
    for t in tickers:
        if t["market"] not in markets:
            markets.append(t["market"])
    # 2) 正文关键词（比来源的泛市场提示更可信）
    if any(k in text_low for k in HK_KEYWORDS) and "HK" not in markets:
        markets.append("HK")
    if any(k in text_low for k in US_KEYWORDS) and "US" not in markets:
        markets.append("US")
    if any(k in text_low for k in CN_KEYWORDS) and "CN" not in markets:
        markets.append("CN")
    # 3) 来源提示兜底（仅在前两步都没命中时）
    if not markets and market_hint in ("HK", "US", "CN", "GLOBAL"):
        markets.append(market_hint)
    if not markets:
        markets.append("GLOBAL")
    return markets


def detect_category(text_low: str) -> str:
    for key, words in CATEGORY_RULES:
        if any(w in text_low for w in words):
            return key
    return "company"


def stock_score(text_low: str, tickers, markets, market_hint: str):
    """返回 (是否纳入, 分数 0-1)"""
    if any(n in text_low for n in NOISE_WORDS):
        return False, 0.0
    score = 0.0
    if tickers:
        score += 0.5 + min(0.2, 0.1 * len(tickers))
    hits = sum(1 for s in STOCK_SIGNALS if s in text_low)
    score += min(0.4, hits * 0.12)
    if market_hint in ("HK", "US"):
        score += 0.25  # 来自财经专源
    if any(k in text_low for k in HK_KEYWORDS + US_KEYWORDS + CN_KEYWORDS):
        score += 0.15
    score = min(1.0, round(score, 3))
    keep = bool(tickers) or score >= 0.5
    return keep, score


def make_id(url: str, title: str) -> str:
    return hashlib.sha1(f"{url}|{title}".encode("utf-8")).hexdigest()


def norm_title(title: str) -> str:
    return re.sub(r"[^\w一-鿿]+", "", title.lower())


# ------------------------------------------------------------------ #
#  主流程
# ------------------------------------------------------------------ #
def main():
    feeds = parse_opml(FEEDS_FILE)
    log(f"loaded {len(feeds)} feeds")

    items = []
    site_status = {}
    site_names = {}
    raw_count = 0

    for site_id, site_name, feed_title, url, market_hint in feeds:
        site_names[site_id] = site_name
        parsed, err = fetch_feed(url)
        st = site_status.setdefault(site_id, {"site_id": site_id, "site_name": site_name,
                                              "status": "ok", "count": 0, "errors": []})
        if err or parsed is None:
            st["status"] = "error"
            st["errors"].append(f"{feed_title}: {err}")
            log(f"  ! {feed_title}: {err}")
            continue

        for entry in parsed.entries:
            raw_count += 1
            title = (entry.get("title") or "").strip()
            link = (entry.get("link") or "").strip()
            if not title or not link:
                continue
            summary = re.sub(r"<[^>]+>", "", entry.get("summary", "") or "")[:400]
            pub = entry_time(entry)
            if pub and pub < WINDOW_START:
                continue

            blob = f"{title} {summary}"
            text_low = blob.lower()
            tickers = detect_tickers(blob)
            markets = detect_markets(text_low, tickers, market_hint)
            keep, score = stock_score(text_low, tickers, markets, market_hint)
            if not keep:
                continue
            category = detect_category(text_low)
            st["count"] += 1

            items.append({
                "id": make_id(link, title),
                "site_id": site_id,
                "site_name": site_name,
                "source": feed_title,
                "title": title,
                "url": link,
                "summary": summary,
                "published_at": pub.isoformat() if pub else None,
                "first_seen_at": NOW.isoformat(),
                "market": markets[0],
                "markets": markets,
                "tickers": tickers,
                "category": category,
                "score": score,
            })
        time.sleep(0.2)

    # 去重（同标题取分高 / 最新）
    by_norm = {}
    for it in items:
        key = norm_title(it["title"])
        cur = by_norm.get(key)
        if cur is None or it["score"] > cur["score"]:
            by_norm[key] = it
    items = list(by_norm.values())
    items.sort(key=lambda x: (x["published_at"] or x["first_seen_at"]), reverse=True)
    log(f"kept {len(items)} items (raw {raw_count})")

    # 统计
    market_stats = defaultdict(int)
    cat_stats = defaultdict(int)
    site_stats = defaultdict(int)
    for it in items:
        for m in it["markets"]:
            market_stats[m] += 1
        cat_stats[it["category"]] += 1
        site_stats[it["site_id"]] += 1

    # 合并事件线：按标的聚类；无标的则按 (市场+分类) 兜底
    stories = build_stories(items)

    # 写文件
    DATA_DIR.mkdir(exist_ok=True)
    write_json(DATA_DIR / "latest.json", {
        "generated_at": NOW.isoformat(),
        "window_hours": WINDOW_HOURS,
        "total_items": len(items),
        "source_count": len(feeds),
        "site_count": len(site_status),
        "market_stats": dict(market_stats),
        "category_stats": sorted(
            [{"key": k, "count": v} for k, v in cat_stats.items()],
            key=lambda x: x["count"], reverse=True),
        "site_stats": sorted(
            [{"site_id": k, "site_name": site_names.get(k, k), "count": v}
             for k, v in site_stats.items()],
            key=lambda x: x["count"], reverse=True),
        "items": items,
    })

    write_json(DATA_DIR / "stories.json", {
        "generated_at": NOW.isoformat(),
        "window_hours": WINDOW_HOURS,
        "total_stories": len(stories),
        "stories": stories,
    })

    # 量价异动占位（后续由富途 OpenD / 行情 API 填充 data/movers.json）
    movers_path = DATA_DIR / "movers.json"
    if not movers_path.exists():
        write_json(movers_path, {"generated_at": NOW.isoformat(), "movers": []})

    ok = sum(1 for s in site_status.values() if s["status"] == "ok")
    write_json(DATA_DIR / "source-status.json", {
        "generated_at": NOW.isoformat(),
        "sites": sorted(site_status.values(), key=lambda x: x["count"], reverse=True),
        "successful_sites": ok,
        "failed_sites": len(site_status) - ok,
        "fetched_raw_items": raw_count,
        "items_in_window": len(items),
    })

    log("done. wrote data/latest.json, stories.json, source-status.json")


def build_stories(items):
    groups = defaultdict(list)
    for it in items:
        if it["tickers"]:
            key = it["tickers"][0]["symbol"]
        else:
            key = f"{it['market']}:{it['category']}"
        groups[key].append(it)

    stories = []
    for key, group in groups.items():
        group.sort(key=lambda x: (x["published_at"] or x["first_seen_at"]), reverse=True)
        primary = max(group, key=lambda x: x["score"])
        tickers = primary["tickers"]
        markets = sorted({m for it in group for m in it["markets"]})
        sources = sorted({it["site_name"] for it in group})
        cats = [it["category"] for it in group]
        category = max(set(cats), key=cats.count)
        importance = 1
        if len(sources) >= 2:
            importance += 1
        if len(group) >= 3 or category in ("earnings", "ma", "policy", "ipo"):
            importance += 1
        times = [it["published_at"] or it["first_seen_at"] for it in group]
        label = (tickers[0]["name"] if tickers
                 else f"{MARKET_CN.get(markets[0], markets[0])}·{category}")
        stories.append({
            "key": key,
            "label": label,
            "market": markets[0] if markets else "GLOBAL",
            "markets": markets,
            "tickers": tickers,
            "category": category,
            "importance": importance,
            "count": len(group),
            "sources": sources,
            "latest_at": max(times),
            "earliest_at": min(times),
            "primary_item": primary,
            "items": group[:8],
        })

    # 排序：多源 + 多条 + 重要性 + 最新
    stories.sort(key=lambda s: (s["importance"], len(s["sources"]), s["count"], s["latest_at"]),
                 reverse=True)
    return stories


MARKET_CN = {"HK": "港股", "US": "美股", "CN": "A股", "GLOBAL": "全球"}


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
