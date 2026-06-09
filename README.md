# 港美股雷达 (HK · US Stock Radar)

24 小时监控港股 / 美股资讯与量价异动，把分散的消息按个股/板块合并成**事件线**，5 分钟看完今日重点。
纯静态站 + 定时 Python 脚本，零后端，托管在 GitHub Pages，由 GitHub Actions 每 30 分钟自动更新。

> 样式参考自开源项目 [ai-news-radar](https://github.com/learnprompt/ai-news-radar)（MIT）。仅供研究参考，不构成投资建议。

---

## 目录结构

```
index.html                 # 页面
assets/
  styles.css               # 样式（米白杂志风，涨绿跌红）
  app.js                   # 渲染逻辑（原生 JS，消费 data/*.json）
  motion.js, logo.svg
feeds/
  sources.opml             # 信源清单（RSS/OPML），改这里增删源
scripts/
  update_radar.py          # 抓取 → 标的/市场/分类打分 → 去重 → 合并事件线 → 写 JSON
  requirements.txt         # Python 依赖（放 scripts/ 下，避免 Vercel 误判为 Python 项目）
data/                      # 自动生成的产物（前端读取）
  latest.json              # 资讯流 + 统计
  stories.json             # 焦点事件线
  movers.json              # 量价异动（占位，待行情源填充）
  source-status.json       # 信源健康度
vercel.json                # 声明为纯静态站，关闭构建
.github/workflows/update-radar.yml
```

## 数据流

```
feeds/sources.opml ─┐
                    ├─ update_radar.py ─→ data/*.json ─→ index.html (Pages)
富途 OpenD / 行情API ┘   (GitHub Actions 每 30 分钟)
```

每条资讯会被识别：**市场**（港股/美股/A股/全球）、**标的**（代码+名称）、**分类**（财报/IPO/并购/资金/评级/政策/宏观…），并打**港美股相关性分**；同一事件的多源消息按标的聚合成事件线。

---

## 本地运行

```bash
python3 -m venv .venv && .venv/bin/pip install -r scripts/requirements.txt
.venv/bin/python scripts/update_radar.py        # 生成 data/*.json
.venv/bin/python -m http.server 8777            # 打开 http://localhost:8777
```

> 注意：本机若用 Python 3.14 可能因 expat 库问题报错，建议用 3.11/3.12。

可调环境变量：`RADAR_WINDOW_HOURS`（时间窗，默认 48 小时）。

---

## 部署到 GitHub Pages

1. 把本目录推到一个 GitHub 仓库。
2. **Settings → Pages → Build and deployment → Source 选 "Deploy from a branch"**，分支 `main`、目录 `/ (root)`。
3. **Settings → Actions → General → Workflow permissions** 勾选 **Read and write permissions**（让 Action 能提交 data）。
4. Actions 里手动跑一次 `Update Stock Radar`（或等定时触发）。完成后访问 `https://<用户名>.github.io/<仓库名>/`。

---

## 增删信源

编辑 [feeds/sources.opml](feeds/sources.opml)：

```xml
<outline text="分组名" id="site_id">
  <outline title="源名" xmlUrl="RSS地址" market="HK|US|CN|GLOBAL"/>
</outline>
```

- `market` 可选，是**来源的市场提示**（仅在正文未命中标的/关键词时兜底）。
- 中文财经源（华尔街见闻、财联社、格隆汇、雪球等）需经 **RSSHub**：把 OPML 里被注释的那段中的 `RSSHUB` 换成你的实例域名（如 `https://rsshub.app` 或自建）后启用。

**接入你自己的源**：直接把 RSS 地址加进 OPML 即可；若不是 RSS（网页/API），告诉我形式，我在 `update_radar.py` 里加对应抓取器。

## 扩充标的词典

[scripts/update_radar.py](scripts/update_radar.py) 顶部的 `HK_TICKERS` / `US_TICKERS` 决定能识别哪些个股名/代码，按需补充即可（也可后续改成从外部清单文件加载）。

---

## 量价异动（movers）

`data/movers.json` 目前是空占位。本仓库已有富途只读行情 MCP（见 [README.md](README.md)），下一步可写一个脚本用富途 OpenD 拉港美股快照/资金流，按涨跌幅、成交额、资金净流入等阈值筛出异动标的，写入 `data/movers.json`，前端「量价异动」区即会展示。需要的话告诉我，我来接。

movers.json 格式：

```json
{
  "generated_at": "ISO时间",
  "movers": [
    {"symbol": "00700", "name": "腾讯控股", "market": "HK",
     "price": 380.2, "change_pct": 5.6, "turnover": 1.2e9,
     "reason": "成交额放量 + 资金净流入", "url": "...", "time": "ISO时间"}
  ]
}
```
