/* 港美股雷达 — 前端渲染（纯原生 JS，消费 data/*.json） */
"use strict";

const DATA = {
  latest: "data/latest.json",
  stories: "data/stories.json",
  movers: "data/movers.json",
  status: "data/source-status.json",
};

const CATEGORY_LABELS = {
  earnings: "财报业绩",
  guidance: "业绩指引",
  policy: "政策监管",
  ipo: "IPO新股",
  ma: "并购重组",
  capital: "资金动向",
  rating: "评级研报",
  product: "产品业务",
  macro: "宏观市场",
  company: "公司动态",
  other: "其他",
};

const MARKET_LABELS = { HK: "港股", US: "美股", CN: "A股", GLOBAL: "全球" };

const state = {
  data: null,
  stories: [],
  movers: [],
  status: null,
  market: "",
  category: "",
  site: "",
  query: "",
  moverMarket: "",
};

const $ = (sel) => document.querySelector(sel);
const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
};

/* ---------- 工具 ---------- */
function fmtTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const now = new Date();
  const diff = (now - d) / 1000;
  if (diff < 60) return "刚刚";
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`;
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  const hh = String(d.getHours()).padStart(2, "0");
  const mi = String(d.getMinutes()).padStart(2, "0");
  return `${mm}-${dd} ${hh}:${mi}`;
}

function fmtClock(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("zh-CN", { hour12: false });
}

function catLabel(key) {
  return CATEGORY_LABELS[key] || key || "其他";
}
function marketLabel(m) {
  return MARKET_LABELS[m] || m || "";
}

async function loadJSON(url) {
  try {
    const res = await fetch(`${url}?t=${Date.now()}`);
    if (!res.ok) throw new Error(res.status);
    return await res.json();
  } catch (e) {
    console.warn("load failed", url, e);
    return null;
  }
}

/* ---------- 过滤 ---------- */
function filteredItems() {
  const items = state.data?.items || [];
  const q = state.query.trim().toLowerCase();
  return items.filter((it) => {
    if (state.market) {
      const ms = it.markets && it.markets.length ? it.markets : [it.market];
      if (!ms.includes(state.market)) return false;
    }
    if (state.category && it.category !== state.category) return false;
    if (state.site && it.site_id !== state.site) return false;
    if (q) {
      const hay = [
        it.title,
        it.source,
        it.site_name,
        (it.tickers || []).map((t) => `${t.symbol} ${t.name}`).join(" "),
      ]
        .join(" ")
        .toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
}

/* ---------- 渲染：统计条 ---------- */
function renderStats() {
  const d = state.data;
  const wrap = $("#stats");
  wrap.innerHTML = "";
  if (!d) return;
  const ms = d.market_stats || {};
  const cells = [
    ["24h 信号", d.total_items ?? 0],
    ["港股", ms.HK ?? 0],
    ["美股", ms.US ?? 0],
    ["事件线", state.stories.length],
    ["信源", d.source_count ?? 0],
  ];
  cells.forEach(([label, value]) => {
    const s = el("div", "stat");
    s.append(el("strong", null, String(value)), el("span", null, label));
    wrap.appendChild(s);
  });
}

/* ---------- 渲染：覆盖条 ---------- */
function renderCoverage() {
  const wrap = $("#coverageStrip");
  wrap.innerHTML = "";
  const st = state.status;
  if (!st) return;
  const card = (label, value, meta, tone = "") => {
    const node = el("div", `coverage-card ${tone}`.trim());
    node.append(
      el("span", "coverage-label", label),
      el("strong", null, String(value)),
      el("span", "coverage-meta", meta)
    );
    return node;
  };
  const ok = st.successful_sites ?? 0;
  const fail = st.failed_sites ?? 0;
  const total = (st.sites || []).length;
  wrap.append(
    card("信源在线", `${ok}/${total}`, fail ? `${fail} 个异常` : "全部正常", fail ? "warn" : "good"),
    card("抓取条数", st.fetched_raw_items ?? "—", "去重前"),
    card("24h 入选", st.items_in_window ?? state.data?.total_items ?? "—", "命中港美股"),
    card("更新于", fmtTime(st.generated_at), fmtClock(st.generated_at))
  );
}

/* ---------- 渲染：事件线（焦点） ---------- */
function importanceTone(imp) {
  if (imp >= 3) return "high";
  if (imp >= 2) return "mid";
  return "low";
}

function renderStories() {
  const board = $("#bolePicksList");
  board.innerHTML = "";
  let stories = state.stories;
  if (state.market) {
    stories = stories.filter((s) => (s.markets || [s.market]).includes(state.market));
  }
  if (!stories.length) {
    board.append(el("div", "bole-empty", "暂无满足条件的事件线。"));
    $("#bolePicksMeta").textContent = "0 条事件线";
    return;
  }
  $("#bolePicksMeta").textContent = `${stories.length} 条事件线 · 按热度`;

  const [lead, ...rest] = stories;

  // 头条卡片
  const leadCard = el("a", "bole-lead-card");
  leadCard.href = lead.primary_item?.url || "#";
  leadCard.target = "_blank";
  leadCard.rel = "noopener noreferrer";
  const top = el("div", "bole-lead-top");
  top.append(
    el("span", "bole-kicker", marketTickerKicker(lead)),
    el("span", "bole-score-orb", String(lead.count))
  );
  const ltitle = el("div", "bole-lead-title", lead.primary_item?.title || lead.label);
  const lreason = el("div", "bole-lead-reason", storyReason(lead));
  const lfoot = el("div", "bole-lead-foot");
  lfoot.innerHTML = `<span>${escapeHtml(lead.primary_item?.site_name || "多源")}</span><span>${fmtTime(lead.latest_at)}</span>`;
  leadCard.append(top, ltitle, lreason, lfoot);

  const timeline = el("div", "bole-timeline");
  rest.slice(0, 12).forEach((s) => timeline.appendChild(buildStoryRow(s)));

  const layout = el("div", "bole-lead-wrap");
  layout.append(leadCard, timeline);
  board.appendChild(layout);
}

function marketTickerKicker(s) {
  const mk = (s.markets || [s.market]).map(marketLabel).filter(Boolean).join("/");
  const tk = (s.tickers || []).slice(0, 2).map((t) => t.name || t.symbol).join("、");
  return [mk, tk].filter(Boolean).join(" · ") || "市场";
}

function storyReason(s) {
  const srcCount = (s.sources || []).length;
  const parts = [];
  parts.push(srcCount > 1 ? `${srcCount} 源命中` : "单源");
  if (s.count > 1) parts.push(`合并 ${s.count} 条`);
  parts.push(catLabel(s.category));
  return parts.join(" · ");
}

function buildStoryRow(s) {
  const row = el("a", "bole-row");
  row.href = s.primary_item?.url || "#";
  row.target = "_blank";
  row.rel = "noopener noreferrer";
  const time = el("time", "bole-row-time", fmtTime(s.latest_at));
  const body = el("div", "bole-row-body");
  const meta = el("div", "bole-row-meta");
  const tag = el("span", `category tone-${importanceTone(s.importance)}`, marketTickerKicker(s));
  meta.append(tag);
  const title = el("div", "bole-row-title", s.primary_item?.title || s.label);
  const reason = el("div", "bole-row-reason", storyReason(s));
  body.append(meta, title, reason);
  row.append(time, body);
  return row;
}

/* ---------- 渲染：量价异动 ---------- */
function renderMovers() {
  const list = $("#moversList");
  list.innerHTML = "";
  let movers = state.movers;
  if (state.moverMarket) movers = movers.filter((m) => m.market === state.moverMarket);
  $("#moversUpdatedAt").textContent = state.moversGeneratedAt
    ? fmtTime(state.moversGeneratedAt)
    : "暂无数据";

  if (!movers.length) {
    list.append(
      el(
        "div",
        "waytoagi-empty",
        "暂无量价异动数据。接入富途 OpenD 或行情 API 后，这里会展示涨跌幅、成交额、资金流等异动标的。"
      )
    );
    $("#moversMeta").textContent = "";
    return;
  }
  $("#moversMeta").textContent = `${movers.length} 个异动标的`;
  movers.slice(0, 30).forEach((m) => {
    const row = el("a", "mover-item");
    row.href = m.url || "#";
    row.target = "_blank";
    row.rel = "noopener noreferrer";
    const up = (m.change_pct ?? 0) >= 0;
    const head = el("div", "mover-head");
    head.append(
      el("span", "mover-name", `${m.name || m.symbol}`),
      el("span", "mover-sym", `${marketLabel(m.market)} ${m.symbol}`)
    );
    const right = el("div", "mover-right");
    const pct = el("span", `mover-pct ${up ? "up" : "down"}`,
      `${up ? "+" : ""}${(m.change_pct ?? 0).toFixed(2)}%`);
    right.append(pct);
    if (m.price != null) right.append(el("span", "mover-price", String(m.price)));
    const reason = el("div", "mover-reason", m.reason || "");
    row.append(head, right, reason);
    list.appendChild(row);
  });
}

/* ---------- 渲染：资讯流 ---------- */
function renderList() {
  const list = $("#newsList");
  list.innerHTML = "";
  const items = filteredItems();
  $("#resultCount").textContent = `${items.length} 条`;
  if (!items.length) {
    list.append(el("div", "bole-empty", "没有符合条件的资讯。"));
    return;
  }
  items.slice(0, 200).forEach((it) => {
    const card = el("article", "news-card");
    const meta = el("div", "meta-row");
    const ms = (it.markets && it.markets.length ? it.markets : [it.market]).filter(Boolean);
    ms.forEach((m) => meta.append(el("span", `site market-${m}`, marketLabel(m))));
    meta.append(el("span", "category", catLabel(it.category)));
    meta.append(el("span", "source", it.source || it.site_name || ""));
    const t = el("time", "time", fmtTime(it.published_at || it.first_seen_at));
    meta.append(t);
    const a = el("a", "title", it.title);
    a.href = it.url || "#";
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    card.append(meta, a);
    if (it.tickers && it.tickers.length) {
      const tk = el("div", "card-tickers");
      it.tickers.slice(0, 4).forEach((x) =>
        tk.append(el("span", "ticker-chip", `${x.name || x.symbol}`))
      );
      card.append(tk);
    }
    list.appendChild(card);
  });
}

/* ---------- 信源健康 + 下拉 ---------- */
function renderSourceHealth() {
  const box = $("#sourceHealth");
  const st = state.status;
  if (!st) return;
  const sites = st.sites || [];
  const bad = sites.filter((s) => s.status !== "ok");
  box.textContent = bad.length
    ? `异常信源：${bad.map((s) => s.site_name).join("、")}`
    : `全部 ${sites.length} 个信源正常`;

  const pills = $("#sitePills");
  pills.innerHTML = "";
  sites.forEach((s) => {
    const p = el("span", `site-pill ${s.status === "ok" ? "" : "down"}`.trim());
    p.append(el("span", "name", s.site_name), el("span", "count", String(s.count ?? 0)));
    pills.appendChild(p);
  });
}

function fillSelectors() {
  const catSel = $("#categorySelect");
  const cats = state.data?.category_stats || [];
  cats.forEach((c) => {
    const o = el("option", null, `${catLabel(c.key)} (${c.count})`);
    o.value = c.key;
    catSel.appendChild(o);
  });
  const siteSel = $("#siteSelect");
  (state.data?.site_stats || []).forEach((s) => {
    const o = el("option", null, `${s.site_name} (${s.count})`);
    o.value = s.site_id;
    siteSel.appendChild(o);
  });
}

/* ---------- 事件绑定 ---------- */
function bindEvents() {
  $("#searchInput").addEventListener("input", (e) => {
    state.query = e.target.value;
    renderList();
  });
  document.querySelectorAll("[data-market]").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("[data-market]").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      state.market = btn.dataset.market;
      $("#modeHint").textContent = state.market ? marketLabel(state.market) : "全部市场";
      renderStats();
      renderStories();
      renderList();
    });
  });
  $("#categorySelect").addEventListener("change", (e) => {
    state.category = e.target.value;
    renderList();
  });
  $("#siteSelect").addEventListener("change", (e) => {
    state.site = e.target.value;
    renderList();
  });
  document.querySelectorAll("[data-mover-market]").forEach((btn) => {
    btn.addEventListener("click", () => {
      document
        .querySelectorAll("[data-mover-market]")
        .forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      state.moverMarket = btn.dataset.moverMarket;
      renderMovers();
    });
  });
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

/* ---------- 启动 ---------- */
async function init() {
  bindEvents();
  const [latest, stories, movers, status] = await Promise.all([
    loadJSON(DATA.latest),
    loadJSON(DATA.stories),
    loadJSON(DATA.movers),
    loadJSON(DATA.status),
  ]);
  state.data = latest;
  state.stories = stories?.stories || [];
  state.movers = movers?.movers || [];
  state.moversGeneratedAt = movers?.generated_at;
  state.status = status;

  $("#updatedAt").textContent = fmtClock(latest?.generated_at);
  $("#advancedSummary").textContent = `${(status?.sites || []).length} 信源 · ${
    latest?.total_items ?? 0
  } 条`;

  fillSelectors();
  renderStats();
  renderCoverage();
  renderSourceHealth();
  renderStories();
  renderMovers();
  renderList();
  if (window.__radarMotion) window.__radarMotion();
}

document.addEventListener("DOMContentLoaded", init);
