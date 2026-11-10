import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  ArrowDownToLine,
  ArrowUpRight,
  ArrowRight,
  ArrowLeftRight,
  Check,
  CheckCheck,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  FileText,
  Fingerprint,
  History,
  Inbox,
  LayoutDashboard,
  ListChecks,
  LoaderCircle,
  MessageSquare,
  Plus,
  Search,
  Send,
  Settings2,
  ShieldCheck,
  Sparkles,
  Upload,
  Wallet,
  X,
  RefreshCw,
  Undo2,
  FlaskConical,
  CircleAlert,
} from "lucide-react";
import {
  AreaChart,
  Area,
  ResponsiveContainer,
  XAxis,
  Tooltip,
  CartesianGrid,
} from "recharts";
import "./style.css";

type Tx = {
  id: string;
  platform: string;
  account: string;
  time: string;
  direction: string;
  amount: number;
  merchant: string;
  description: string;
  order_id: string;
  kind: string;
  category: string;
  confidence: number;
  excluded: boolean;
  linked_id: string;
  review_status: string;
  exclusion_reason?: string;
  sources: Record<string, unknown>[];
  raw: Record<string, unknown>;
};
type Review = {
  id: string;
  tx_id: string;
  kind: string;
  reason: string;
  merchant: string;
  amount: number;
  time: string;
  options: (string | { id: string; score: number })[];
};
type Summary = {
  count: number;
  confirmed: number;
  pending: number;
  excluded: number;
  expense: number;
  refund: number;
  net: number;
  income: number;
  categories: { name: string; value: number }[];
  months: { month: string; expense: number; refund: number; net: number }[];
  changes: { month: string; message: string }[];
  history_note: string;
};
type Job = {
  id: string;
  name: string;
  status: string;
  synthetic: boolean;
  imported: number;
  reimported: number;
  errors: Record<string, unknown>[];
  quality?: Record<string, unknown>;
  trace: { stage: string; message: string; time: string }[];
  ocr?: { file: string; text: string; confidence: number }[];
  mapping_required?: { token: string; file: string; columns: string[] }[];
};
type Config = {
  llm: {
    configured: boolean;
    pricing_configured: boolean;
    model: string;
    spent_cny: number;
    budget_cny: number;
    calls: number;
  };
  categories: string[];
  model: { ready: boolean; version: string };
};
type Event = {
  id: string;
  tx_id: string;
  reason: string;
  time: string;
  undone: boolean;
};
type Metrics = {
  selected?: string;
  classification?: { model: string; macro_f1: number; accuracy: number }[];
  matching?: Record<
    string,
    { precision: number; recall: number; f1: number; candidate_recall: number }
  >;
  rows?: number;
  split_counts?: Record<string, number>;
  classification_coverage?: number;
  anomaly?: { precision: number; recall: number; f1: number };
  limitations?: string[];
};
const emptySummary: Summary = {
  count: 0,
  confirmed: 0,
  pending: 0,
  excluded: 0,
  expense: 0,
  refund: 0,
  net: 0,
  income: 0,
  categories: [],
  months: [],
  changes: [],
  history_note: "",
};
const money = (v: number) =>
  new Intl.NumberFormat("zh-CN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(v / 100);
const kinds: Record<string, string> = {
  category: "消费分类",
  transfer: "账户转账",
  refund: "退款匹配",
  duplicate: "疑似重复",
  anomaly: "异常变化",
  field: "字段补充",
  status: "交易状态",
  ocr: "截图复核",
};
async function api<T>(url: string, options: RequestInit = {}): Promise<T> {
  const r = await fetch("/api" + url, {
    ...options,
    headers:
      options.body instanceof FormData
        ? undefined
        : { "Content-Type": "application/json", ...options.headers },
  });
  if (!r.ok) {
    let d;
    try {
      d = await r.json();
    } catch {
      d = { detail: "服务暂不可用" };
    }
    throw new Error(
      typeof d.detail === "string" ? d.detail : JSON.stringify(d.detail),
    );
  }
  return r.json();
}

function App() {
  const [tab, setTab] = useState("overview");
  const [rows, setRows] = useState<Tx[]>([]);
  const [summary, setSummary] = useState<Summary>(emptySummary);
  const [reviews, setReviews] = useState<Review[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [events, setEvents] = useState<Event[]>([]);
  const [config, setConfig] = useState<Config | null>(null);
  const [metrics, setMetrics] = useState<Metrics>({});
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [importOpen, setImportOpen] = useState(false);
  const [platform, setPlatform] = useState("微信");
  const [account, setAccount] = useState("我的微信");
  const [synthetic, setSynthetic] = useState(false);
  const [text, setText] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [detail, setDetail] = useState<Tx | null>(null);
  const [editCat, setEditCat] = useState("");
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("");
  const [page, setPage] = useState(0);
  const [message, setMessage] = useState("");
  const [remote, setRemote] = useState(false);
  const chatBox = useRef<HTMLDivElement>(null);
  const [chat, setChat] = useState<
    { role: string; text: string; mode?: string }[]
  >([
    {
      role: "agent",
      text: "你好，我是知账。导入微信、支付宝账单后，我会整理消费、匹配转账和退款，把需要你确认的问题集中在这里。",
    },
  ]);
  const [choices, setChoices] = useState<Record<string, string>>({});
  const [mapping, setMapping] = useState<
    Record<string, Record<string, string>>
  >({});
  const refresh = async () => {
    const [l, r, j, c, e, m] = await Promise.all([
      api<{ rows: Tx[]; summary: Summary }>("/ledger"),
      api<Review[]>("/reviews"),
      api<Job[]>("/jobs"),
      api<Config>("/config"),
      api<Event[]>("/events"),
      api<Metrics>("/metrics"),
    ]);
    setRows(l.rows);
    setSummary(l.summary);
    setReviews(r);
    setJobs(j);
    setConfig(c);
    setEvents(e);
    setMetrics(m);
  };
  useEffect(() => {
    refresh().catch((e) => setError(e.message));
  }, []);
  useEffect(() => {
    if (chatBox.current)
      chatBox.current.scrollTop = chatBox.current.scrollHeight;
  }, [chat]);
  const action = async (label: string, fn: () => Promise<void>) => {
    setBusy(label);
    setError("");
    setNotice("");
    try {
      await fn();
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  };
  const latest = jobs[0];
  const filtered = rows.filter(
    (r) =>
      (!search || (r.merchant + r.description + r.order_id).includes(search)) &&
      (!filter || r.review_status === filter),
  );
  const selected = filtered.slice(page * 12, page * 12 + 12);
  const demo = () =>
    action("正在整理演示账单", async () => {
      const j = await api<Job>("/demo", { method: "POST" });
      if (j.imported) await api("/jobs/" + j.id + "/run", { method: "POST" });
      setNotice(
        j.imported
          ? "构造演示账单已整理，请查看待核对项。"
          : "演示账单已导入过，可继续查看已有账本。",
      );
      setTab("overview");
    });
  const importData = () =>
    action("正在导入并整理", async () => {
      if (!synthetic) setRemote(false);
      let j: Job;
      if (files.length) {
        const f = new FormData();
        files.forEach((x) => f.append("files", x));
        f.append("platform", platform);
        f.append("account", account);
        f.append("synthetic", String(synthetic));
        j = await api<Job>("/import/files", { method: "POST", body: f });
      } else {
        j = await api<Job>("/import/text", {
          method: "POST",
          body: JSON.stringify({ text, platform, account, synthetic }),
        });
      }
      if (j.imported && !j.mapping_required?.length)
        await api("/jobs/" + j.id + "/run", { method: "POST" });
      setImportOpen(false);
      setFiles([]);
      setText("");
      setNotice(
        `本批新增 ${j.imported} 条，已导入过 ${j.reimported} 条，需补充 ${j.errors.length} 行。`,
      );
      setTab(j.mapping_required?.length ? "evidence" : "overview");
    });
  const answer = (q: Review, act: string, extra: Record<string, string> = {}) =>
    action("正在保存核对", async () => {
      await api("/reviews/" + q.id + "/answer", {
        method: "POST",
        body: JSON.stringify({ action: act, ...extra }),
      });
      setNotice("核对已保存，账本与汇总已更新。");
    });
  const send = () =>
    action("知账正在核对", async () => {
      if (!message.trim()) return;
      const q = message;
      setMessage("");
      setChat((v) => [...v, { role: "user", text: q }]);
      const r = await api<{ reply: string; mode: string }>("/chat", {
        method: "POST",
        body: JSON.stringify({ message: q, allow_remote: remote }),
      });
      setChat((v) => [...v, { role: "agent", text: r.reply, mode: r.mode }]);
    });
  const openDetail = (r: Tx) => {
    setDetail(r);
    setEditCat(r.category || "其他");
  };
  const nav = [
    { key: "overview", label: "账本概览", icon: LayoutDashboard },
    { key: "ledger", label: "交易明细", icon: Wallet },
    { key: "review", label: "待核对", icon: ListChecks, count: reviews.length },
    { key: "evidence", label: "处理记录", icon: History },
    { key: "experiments", label: "实验评估", icon: FlaskConical },
  ];
  return (
    <div className="shell">
      <aside className="sidebar">
        <a className="brand" href="#" onClick={() => setTab("overview")}>
          <span className="brand-mark">
            <ArrowLeftRight size={24} />
          </span>
          <span>
            知账<small>RECONCILIATION AGENT</small>
          </span>
        </a>
        <div className="workspace-label">
          个人工作台 <span>LOCAL</span>
        </div>
        <nav>
          {nav.map((n) => (
            <button
              key={n.key}
              className={tab === n.key ? "nav-item active" : "nav-item"}
              onClick={() => {
                setTab(n.key);
                setPage(0);
              }}
            >
              <n.icon size={19} />
              {n.label}
              {n.count ? <span className="count">{n.count}</span> : null}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="private-note">
            <ShieldCheck size={19} />
            <div>
              你的账单，留在本机<p>本地存储 · 可追溯修改</p>
            </div>
          </div>
          <button
            className={tab === "settings" ? "nav-item active" : "nav-item"}
            onClick={() => setTab("settings")}
          >
            <Settings2 size={18} />
            模型与设置
          </button>
          <div className="profile">
            <div className="avatar">我</div>
            <div>
              个人账本<small>微信 · 支付宝</small>
            </div>
            <span className="online-dot" />
          </div>
        </div>
      </aside>
      <main className="main">
        <header className="topbar">
          <div className="breadcrumb">
            个人账本 <ChevronRight size={14} />{" "}
            <strong>
              {nav.find((n) => n.key === tab)?.label || "模型与设置"}
            </strong>
          </div>
          <div className="topbar-right">
            <span className="local-badge">
              <span className="online-dot" />
              本地工作台
            </span>
            <button
              className="icon-btn"
              onClick={() => action("刷新中", refresh)}
              aria-label="刷新"
            >
              <RefreshCw size={17} />
            </button>
          </div>
        </header>
        <div className="page">
          <section className="page-heading">
            <div>
              <div className="eyebrow">A CLEARER PICTURE OF YOUR SPENDING</div>
              <h1>
                {tab === "overview"
                  ? "把每一笔，核对清楚。"
                  : tab === "ledger"
                    ? "所有交易，一目了然。"
                    : tab === "review"
                      ? "这几笔，想和你确认。"
                      : tab === "evidence"
                        ? "每一步，都有据可查。"
                        : tab === "experiments"
                          ? "用实验，检验实际效果。"
                          : "连接模型，保留控制。"}
              </h1>
              <p>
                {tab === "overview"
                  ? "整理多个账户，厘清转账与退款，看见真实支出。"
                  : tab === "review"
                    ? "不确定的判断交给你。确认后自动更新账本，修改始终留痕。"
                    : "个人多账户账单整理与异常核对 Agent"}
              </p>
            </div>
            <div className="heading-actions">
              <a
                className="button secondary"
                href="/api/export?format=xlsx"
                onClick={(e) => {
                  if (!rows.length) {
                    e.preventDefault();
                    setError("请先导入账单");
                  }
                }}
              >
                <ArrowDownToLine size={16} />
                导出账本
              </a>
              <button
                className="button primary"
                onClick={() => setImportOpen(true)}
              >
                <Plus size={17} />
                导入账单
              </button>
            </div>
          </section>
          {error && (
            <div className="banner error" role="alert">
              <CircleAlert size={17} />
              <span>{error}</span>
              <button onClick={() => setError("")}>
                <X size={16} />
              </button>
            </div>
          )}
          {notice && (
            <div className="banner success">
              <Check size={17} />
              <span>{notice}</span>
              <button onClick={() => setNotice("")}>
                <X size={16} />
              </button>
            </div>
          )}
          {busy && (
            <div className="banner processing">
              <LoaderCircle className="spin" size={17} />
              {busy}，请稍候…
            </div>
          )}
          {rows.some((r) => (r as Tx & { synthetic?: boolean }).synthetic) && (
            <div className="demo-ribbon">
              <FlaskConical size={14} />
              <strong>构造数据演示</strong>
              <span>当前演示账单为程序构造，不代表真实账户或真实消费。</span>
              <button onClick={() => setTab("experiments")}>
                查看评估 <ArrowUpRight size={13} />
              </button>
            </div>
          )}
          {tab === "overview" && (
            <>
              <section className="stats">
                <Stat
                  label="已核对净支出"
                  amount={summary.net}
                  sub="支出 − 当月到账退款"
                  highlight
                />
                <Stat
                  label="已核对消费"
                  amount={summary.expense}
                  sub={`${summary.confirmed} 条记录已核对`}
                  icon={<Wallet size={18} />}
                />
                <Stat
                  label="已匹配退款"
                  amount={summary.refund}
                  sub="已关联原消费订单"
                  icon={<ArrowLeftRight size={18} />}
                />
                <div className="stat">
                  <div className="stat-label">
                    等待你的确认{" "}
                    <span className="stat-icon amber">
                      <CircleHelp size={18} />
                    </span>
                  </div>
                  <div className="stat-value">
                    {summary.pending}
                    <span className="unit">笔</span>
                  </div>
                  <button
                    className="stat-link"
                    onClick={() => setTab("review")}
                  >
                    {reviews.length} 个待核对问题 <ArrowRight size={14} />
                  </button>
                </div>
              </section>
              <div className="workspace-grid">
                <div className="center-column">
                  <section className="panel trend-panel">
                    <div className="panel-heading">
                      <div>
                        <h2>消费趋势</h2>
                        <p>按实际收支月份，呈现核对后的净支出</p>
                      </div>
                      <span className="subtle-tag">
                        全部月份 <ChevronDown size={13} />
                      </span>
                    </div>
                    {summary.months.length ? (
                      <>
                        <div className="trend-total">
                          ¥ {money(summary.net)}
                          <span>累计净支出</span>
                        </div>
                        <div className="chart">
                          <ResponsiveContainer width="100%" height="100%">
                            <AreaChart
                              data={summary.months.map((m) => ({
                                ...m,
                                元: m.net / 100,
                              }))}
                              margin={{
                                left: 5,
                                right: 18,
                                top: 15,
                                bottom: 0,
                              }}
                            >
                              <defs>
                                <linearGradient
                                  id="fill"
                                  x1="0"
                                  y1="0"
                                  x2="0"
                                  y2="1"
                                >
                                  <stop
                                    offset="0%"
                                    stopColor="#277764"
                                    stopOpacity={0.2}
                                  />
                                  <stop
                                    offset="95%"
                                    stopColor="#277764"
                                    stopOpacity={0.01}
                                  />
                                </linearGradient>
                              </defs>
                              <CartesianGrid
                                vertical={false}
                                stroke="#edf0ed"
                              />
                              <XAxis
                                dataKey="month"
                                tickFormatter={(v) => v.slice(5) + "月"}
                                axisLine={false}
                                tickLine={false}
                                tick={{ fontSize: 11, fill: "#8a938c" }}
                                dy={8}
                              />
                              <Tooltip
                                formatter={(v) => [
                                  "¥ " + Number(v).toFixed(2),
                                  "净支出",
                                ]}
                              />
                              <Area
                                type="monotone"
                                dataKey="元"
                                stroke="#287863"
                                strokeWidth={2.5}
                                fill="url(#fill)"
                              />
                            </AreaChart>
                          </ResponsiveContainer>
                        </div>
                      </>
                    ) : (
                      <Empty
                        icon={<Wallet size={28} />}
                        title="从第一份账单开始"
                        text="支持微信、支付宝文件、文字与截图"
                        action={
                          <button
                            className="button primary"
                            onClick={() => setImportOpen(true)}
                          >
                            <Upload size={16} />
                            导入账单
                          </button>
                        }
                      />
                    )}
                  </section>
                  <section className="panel">
                    <div className="panel-heading">
                      <div>
                        <h2>
                          最近交易{" "}
                          <span className="title-count">{summary.count}</span>
                        </h2>
                        <p>原始记录保留，转账与重复记录单独标记</p>
                      </div>
                      <button
                        className="text-button"
                        onClick={() => setTab("ledger")}
                      >
                        全部明细 <ArrowRight size={14} />
                      </button>
                    </div>
                    <Table rows={rows.slice(0, 5)} onDetail={openDetail} />
                    {!rows.length && (
                      <div className="table-empty">还没有交易记录</div>
                    )}
                  </section>
                </div>
                <aside className="right-column">
                  <section className="panel agent-panel">
                    <div className="agent-heading">
                      <span className="agent-icon">
                        <Sparkles size={20} />
                      </span>
                      <div>
                        <h2>知账助手</h2>
                        <p>
                          {remote && config?.llm.configured
                            ? `${config.llm.model} · 联网问答`
                            : "本地工具 · 随时核对"}
                        </p>
                      </div>
                      <span className="online-dot" />
                    </div>
                    <div className="chat-messages" ref={chatBox}>
                      {chat.slice(-5).map((m, i) => (
                        <div key={i} className={"chat-message " + m.role}>
                          {m.role === "agent" && (
                            <span className="chat-name">
                              知账 {m.mode === "api" ? "· Qwen" : "· 本地"}
                            </span>
                          )}
                          {m.text}
                        </div>
                      ))}
                    </div>
                    <div className="quick-questions">
                      {["哪些需要核对？", "退款匹配情况"].map((q) => (
                        <button key={q} onClick={() => setMessage(q)}>
                          {q}
                        </button>
                      ))}
                    </div>
                    <div className="chat-input">
                      <input
                        aria-label="询问知账"
                        placeholder="问问这份账单…"
                        value={message}
                        onChange={(e) => setMessage(e.target.value)}
                        onKeyDown={(e) => e.key === "Enter" && !busy && send()}
                      />
                      <button
                        aria-label="发送"
                        disabled={!!busy || !message.trim()}
                        onClick={send}
                      >
                        <Send size={16} />
                      </button>
                    </div>
                    <label className="remote-option">
                      <input
                        type="checkbox"
                        checked={remote}
                        onChange={(e) => setRemote(e.target.checked)}
                        disabled={!config?.llm.configured}
                      />
                      允许发送本次问题与脱敏汇总至 API
                    </label>
                  </section>
                  <section className="panel category-panel">
                    <div className="panel-heading">
                      <h2>消费去向</h2>
                      <span className="muted">净支出</span>
                    </div>
                    {summary.categories.length ? (
                      summary.categories.slice(0, 6).map((c, i) => (
                        <div className="category-row" key={c.name}>
                          <div>
                            <span>
                              <i
                                style={{
                                  background: [
                                    "#246b59",
                                    "#578b77",
                                    "#9dba99",
                                    "#d1b26b",
                                    "#87a9ad",
                                    "#bcc6b7",
                                  ][i],
                                }}
                              />
                              {c.name}
                            </span>
                            <strong>¥ {money(c.value)}</strong>
                          </div>
                          <div className="bar-bg">
                            <div
                              style={{
                                width:
                                  (Math.max(0, c.value) /
                                    Math.max(
                                      ...summary.categories.map((c) => c.value),
                                      1,
                                    )) *
                                    100 +
                                  "%",
                                background: [
                                  "#246b59",
                                  "#578b77",
                                  "#9dba99",
                                  "#d1b26b",
                                  "#87a9ad",
                                  "#bcc6b7",
                                ][i],
                              }}
                            />
                          </div>
                        </div>
                      ))
                    ) : (
                      <p className="muted padded">核对完成后展示分类统计</p>
                    )}
                  </section>
                  <div className="audit-note">
                    <Fingerprint size={23} />
                    <div>
                      每一处修改，都可追溯<p>原始数据保留，确认操作可撤销。</p>
                    </div>
                  </div>
                </aside>
              </div>
              {reviews.length > 0 && (
                <section className="review-strip">
                  <div className="review-strip-icon">
                    <ListChecks size={23} />
                  </div>
                  <div>
                    <h3>还有 {summary.pending} 笔交易，等待你确认</h3>
                    <p>
                      分类不确定、退款未匹配或同额近时记录，集中核对后再计入汇总。
                    </p>
                  </div>
                  <button
                    className="button secondary"
                    onClick={() => setTab("review")}
                  >
                    开始核对 <ArrowRight size={16} />
                  </button>
                </section>
              )}
              {!rows.length && (
                <div className="demo-invite">
                  <span>想先看看完整流程？</span>
                  <button
                    className="text-button"
                    onClick={demo}
                    disabled={!!busy}
                  >
                    载入构造演示账单 <ArrowRight size={15} />
                  </button>
                </div>
              )}
            </>
          )}
          {tab === "ledger" && (
            <section className="panel">
              <div className="table-toolbar">
                <div className="search-box">
                  <Search size={17} />
                  <input
                    placeholder="搜索商户、说明或订单号"
                    value={search}
                    onChange={(e) => {
                      setSearch(e.target.value);
                      setPage(0);
                    }}
                  />
                </div>
                <select
                  value={filter}
                  onChange={(e) => {
                    setFilter(e.target.value);
                    setPage(0);
                  }}
                >
                  <option value="">全部核对状态</option>
                  <option>已核对</option>
                  <option>待核对</option>
                  <option>待处理</option>
                </select>
                <span className="muted">共 {filtered.length} 条</span>
              </div>
              <Table rows={selected} onDetail={openDetail} />
              {!selected.length && (
                <Empty
                  icon={<Inbox size={28} />}
                  title="暂无符合条件的交易"
                  text="导入账单或调整筛选条件"
                />
              )}
              <div className="pagination">
                <button
                  disabled={page === 0}
                  onClick={() => setPage((p) => p - 1)}
                >
                  上一页
                </button>
                <span>
                  {page + 1} / {Math.max(1, Math.ceil(filtered.length / 12))}
                </span>
                <button
                  disabled={(page + 1) * 12 >= filtered.length}
                  onClick={() => setPage((p) => p + 1)}
                >
                  下一页
                </button>
              </div>
            </section>
          )}
          {tab === "review" && (
            <>
              <div className="section-summary">
                <span className="amber-dot" />
                {reviews.length} 个问题 · {summary.pending} 笔交易待确认{" "}
                <span className="muted">未确认记录不计入已核对汇总</span>
              </div>
              <div className="review-grid">
                {reviews.map((q) => {
                  const r = rows.find((r) => r.id === q.tx_id);
                  const choice = choices[q.id] || "";
                  return (
                    <section className="panel review-card" key={q.id}>
                      <div className="review-card-heading">
                        <span className={"review-kind " + q.kind}>
                          {kinds[q.kind] || q.kind}
                        </span>
                        <button
                          className="text-button"
                          onClick={() => r && openDetail(r)}
                        >
                          原始记录 <ArrowUpRight size={13} />
                        </button>
                      </div>
                      <div className="review-merchant">
                        <span>{q.merchant || "未识别商户"}</span>
                        <strong>¥ {money(q.amount)}</strong>
                      </div>
                      <p className="muted small">
                        {q.time.replace("T", " ").slice(0, 16)} · {r?.account}
                      </p>
                      <p className="review-reason">{q.reason}</p>
                      {q.kind === "category" ? (
                        <>
                          <select
                            value={choice}
                            onChange={(e) =>
                              setChoices((v) => ({
                                ...v,
                                [q.id]: e.target.value,
                              }))
                            }
                          >
                            <option value="">请选择消费类别</option>
                            {config?.categories.map((c) => (
                              <option key={c}>{c}</option>
                            ))}
                          </select>
                          <button
                            className="button primary full"
                            disabled={!choice || !!busy}
                            onClick={() =>
                              answer(q, "category", { category: choice })
                            }
                          >
                            确认分类 <Check size={15} />
                          </button>
                        </>
                      ) : (
                        <>
                          <div className="candidate-list">
                            {q.options
                              .filter(
                                (o): o is { id: string; score: number } =>
                                  typeof o !== "string" && o.score >= 0.15,
                              )
                              .map((o) => {
                                const t = rows.find((t) => t.id === o.id);
                                return (
                                  <label
                                    key={o.id}
                                    className={
                                      choice === o.id
                                        ? "candidate selected"
                                        : "candidate"
                                    }
                                  >
                                    <input
                                      type="radio"
                                      name={q.id}
                                      checked={choice === o.id}
                                      onChange={() =>
                                        setChoices((v) => ({
                                          ...v,
                                          [q.id]: o.id,
                                        }))
                                      }
                                    />
                                    <span>
                                      {t?.merchant || o.id}
                                      <small>
                                        {t?.time.slice(0, 10)} · ¥{" "}
                                        {money(t?.amount || 0)} · {t?.account}
                                      </small>
                                    </span>
                                    <em>{Math.round(o.score * 100)}%</em>
                                  </label>
                                );
                              })}
                          </div>
                          {["refund", "transfer", "duplicate"].includes(
                            q.kind,
                          ) && (
                            <>
                              <select
                                aria-label="选择关联交易"
                                value={choice}
                                onChange={(e) =>
                                  setChoices((v) => ({
                                    ...v,
                                    [q.id]: e.target.value,
                                  }))
                                }
                              >
                                <option value="">从完整账本选择关联交易</option>
                                {rows
                                  .filter(
                                    (t) =>
                                      t.id !== q.tx_id &&
                                      !t.excluded &&
                                      (q.kind === "refund"
                                        ? t.direction === "支出" &&
                                          t.kind === "消费" &&
                                          t.time <= q.time &&
                                          t.amount >= q.amount
                                        : q.kind === "transfer"
                                          ? t.account !== r?.account &&
                                            t.direction !== r?.direction &&
                                            t.amount === q.amount
                                          : t.amount === q.amount &&
                                            t.direction === r?.direction),
                                  )
                                  .map((t) => (
                                    <option value={t.id} key={t.id}>
                                      {t.time.slice(0, 10)} {t.merchant} ¥
                                      {money(t.amount)} {t.account}
                                    </option>
                                  ))}
                              </select>
                              <button
                                className="button primary full"
                                disabled={!choice || !!busy}
                                onClick={() =>
                                  answer(q, "link", { target_id: choice })
                                }
                              >
                                确认关联 <Check size={15} />
                              </button>
                            </>
                          )}
                          <div className="review-buttons">
                            {q.kind !== "refund" && (
                              <button
                                className="button secondary"
                                disabled={!!busy}
                                onClick={() =>
                                  answer(
                                    q,
                                    ["anomaly", "status"].includes(q.kind)
                                      ? "confirm"
                                      : "keep",
                                  )
                                }
                              >
                                {q.kind === "transfer"
                                  ? "向他人付款，保留"
                                  : "确为真实交易，保留"}
                              </button>
                            )}
                            <button
                              className="button ghost"
                              disabled={!!busy}
                              onClick={() => answer(q, "exclude")}
                            >
                              排除此条
                            </button>
                          </div>
                        </>
                      )}
                    </section>
                  );
                })}
              </div>
              {!reviews.length && (
                <section className="panel">
                  <Empty
                    icon={<CheckCheck size={34} />}
                    title="当前没有待核对项"
                    text="导入后，知账会把不确定记录集中在这里。"
                    action={
                      <button
                        className="button secondary"
                        onClick={() => setTab("ledger")}
                      >
                        查看账本 <ArrowRight size={15} />
                      </button>
                    }
                  />
                </section>
              )}
            </>
          )}
          {tab === "evidence" && (
            <>
              <section className="panel">
                <div className="panel-heading">
                  <div>
                    <h2>Agent 处理轨迹</h2>
                    <p>LangGraph 保存任务状态，支持人工核对后恢复</p>
                  </div>
                  <span className="subtle-tag">{jobs.length} 个导入批次</span>
                </div>
                {jobs.map((j) => (
                  <div className="job" key={j.id}>
                    <div className="job-title">
                      <FileText size={19} />
                      <strong>{j.name}</strong>
                      <span className="status-badge">
                        {(
                          {
                            imported: "已导入",
                            review: "等待核对",
                            complete: "已完成",
                            error: "处理失败",
                            checking: "处理中",
                          } as Record<string, string>
                        )[j.status] || j.status}
                      </span>
                      {j.status === "imported" &&
                        !j.mapping_required?.length && (
                          <button
                            className="text-button"
                            onClick={() =>
                              action("处理账单", async () => {
                                await api("/jobs/" + j.id + "/run", {
                                  method: "POST",
                                });
                              })
                            }
                          >
                            开始整理 <ArrowRight size={14} />
                          </button>
                        )}
                    </div>
                    <p className="muted small">
                      新增 {j.imported} 条 · 已导入过 {j.reimported} 条 ·{" "}
                      {j.synthetic ? "构造数据" : "本地私有数据"}
                    </p>
                    <div className="timeline">
                      {j.trace.map((t, i) => (
                        <div key={i}>
                          <span className="timeline-dot" />
                          <div>
                            <strong>{t.message}</strong>
                            <small>
                              {new Date(t.time).toLocaleString("zh-CN")}
                            </small>
                          </div>
                        </div>
                      ))}
                    </div>
                    {j.errors.length > 0 && (
                      <details>
                        <summary>{j.errors.length} 行需补充或修正</summary>
                        <pre>{JSON.stringify(j.errors, null, 2)}</pre>
                      </details>
                    )}
                    {j.ocr?.map((o) => (
                      <details key={o.file}>
                        <summary>
                          OCR 原文：{o.file} · 最低识别置信度{" "}
                          {Math.round(o.confidence * 100)}%
                        </summary>
                        <pre>{o.text}</pre>
                      </details>
                    ))}
                    {j.mapping_required?.map((m) => (
                      <div className="mapping" key={m.token}>
                        <h3>指定字段映射：{m.file}</h3>
                        {[
                          ["time", "交易时间"],
                          ["amount", "金额（元）"],
                          ["direction", "收支方向"],
                          ["merchant", "交易对方"],
                          ["description", "商品说明"],
                          ["order_id", "订单号"],
                        ].map(([field, label]) => (
                          <label key={field}>
                            {label}
                            <select
                              value={mapping[m.token]?.[field] || ""}
                              onChange={(e) =>
                                setMapping((v) => ({
                                  ...v,
                                  [m.token]: {
                                    ...v[m.token],
                                    [field]: e.target.value,
                                  },
                                }))
                              }
                            >
                              <option value="">请选择原文件列</option>
                              {m.columns.map((c) => (
                                <option key={c}>{c}</option>
                              ))}
                            </select>
                          </label>
                        ))}
                        <button
                          className="button primary"
                          onClick={() =>
                            action("应用字段映射", async () => {
                              await api(`/jobs/${j.id}/mapping/${m.token}`, {
                                method: "POST",
                                body: JSON.stringify({
                                  mapping: mapping[m.token] || {},
                                  platform,
                                  account,
                                }),
                              });
                              setNotice("字段映射完成，可开始整理。");
                            })
                          }
                        >
                          保存映射
                        </button>
                      </div>
                    ))}
                  </div>
                ))}
                {!jobs.length && (
                  <p className="padded muted">
                    导入账单后，处理轨迹会保存在这里。
                  </p>
                )}
              </section>
              <section className="panel history-panel">
                <div className="panel-heading">
                  <div>
                    <h2>修改记录</h2>
                    <p>原始值与修改后值均保留，可按逆序撤销</p>
                  </div>
                </div>
                {events.map((e) => (
                  <div className="event-row" key={e.id}>
                    <span className="event-icon">
                      <History size={17} />
                    </span>
                    <div>
                      <strong>{e.reason}</strong>
                      <small>
                        {new Date(e.time).toLocaleString("zh-CN")} · {e.tx_id}
                      </small>
                    </div>
                    <button
                      className="text-button"
                      disabled={e.undone || !!busy}
                      onClick={() =>
                        action("撤销修改", async () => {
                          await api("/events/" + e.id + "/undo", {
                            method: "POST",
                          });
                          setNotice("已恢复修改前状态。");
                        })
                      }
                    >
                      <Undo2 size={14} />
                      {e.undone ? "已撤销" : "撤销"}
                    </button>
                  </div>
                ))}
                {!events.length && (
                  <p className="padded muted">还没有用户修改。</p>
                )}
              </section>
            </>
          )}
          {tab === "experiments" && (
            <>
              <div className="banner processing">
                <FlaskConical size={18} />
                <span>
                  以下结果来自固定种子的构造账单测试集，不代表真实账单效果。训练、验证与测试按商户组和关联事件隔离。
                </span>
              </div>
              <section className="stats">
                <div className="stat">
                  <div className="stat-label">构造数据规模</div>
                  <div className="stat-value">
                    {metrics.rows || "—"}
                    <span className="unit">条</span>
                  </div>
                  <p className="muted small">固定种子 20261110</p>
                </div>
                <div className="stat">
                  <div className="stat-label">选用分类模型</div>
                  <div className="model-name">
                    {metrics.selected || "尚未训练"}
                  </div>
                  <p className="muted small">由验证集 Macro-F1 选择</p>
                </div>
                <div className="stat">
                  <div className="stat-label">分类自动覆盖率</div>
                  <div className="stat-value">
                    {((metrics.classification_coverage || 0) * 100).toFixed(1)}
                    <span className="unit">%</span>
                  </div>
                  <p className="muted small">低置信度交由人工核对</p>
                </div>
                <div className="stat">
                  <div className="stat-label">数据划分</div>
                  <div className="split-count">
                    {Object.values(metrics.split_counts || {}).join(" / ")}
                  </div>
                  <p className="muted small">训练 / 验证 / 测试</p>
                </div>
              </section>
              <div className="experiment-grid">
                <section className="panel">
                  <div className="panel-heading">
                    <h2>消费分类对照</h2>
                    <span className="subtle-tag">构造测试集</span>
                  </div>
                  <table>
                    <thead>
                      <tr>
                        <th>方法</th>
                        <th>Macro-F1</th>
                        <th>准确率</th>
                      </tr>
                    </thead>
                    <tbody>
                      {metrics.classification?.map((m) => (
                        <tr key={m.model}>
                          <td>
                            {m.model}
                            {m.model === metrics.selected && (
                              <span className="mini-tag">选用</span>
                            )}
                          </td>
                          <td>{m.macro_f1.toFixed(4)}</td>
                          <td>{m.accuracy.toFixed(4)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </section>
                <section className="panel">
                  <div className="panel-heading">
                    <h2>交易匹配模型</h2>
                    <span className="muted">候选对级评估</span>
                  </div>
                  <table>
                    <thead>
                      <tr>
                        <th>任务</th>
                        <th>Precision</th>
                        <th>Recall</th>
                        <th>F1</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(metrics.matching || {}).map(([k, v]) => (
                        <tr key={k}>
                          <td>
                            {
                              {
                                transfer: "本人转账",
                                refund: "退款匹配",
                                duplicate: "重复识别",
                              }[k]
                            }
                          </td>
                          <td>{v.precision.toFixed(3)}</td>
                          <td>{v.recall.toFixed(3)}</td>
                          <td>{v.f1.toFixed(3)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <p className="padded muted small">
                    模型评分与最终自动关联不同：工作流还检查金额、时间、唯一性和累计退款上限。
                  </p>
                </section>
              </div>
              <section className="panel padded">
                <h2>适用边界</h2>
                {metrics.limitations?.map((t) => (
                  <p className="muted" key={t}>
                    • {t}
                  </p>
                ))}
                <p className="muted">
                  完整实验指标、错误案例与消融记录保存在 results
                  目录。真实样例尚需用户授权提供。
                </p>
              </section>
            </>
          )}
          {tab === "settings" && (
            <div className="settings-grid">
              <section className="panel padded">
                <h2>模型连接</h2>
                <div className="setting-line">
                  <span>默认对话模型</span>
                  <strong>{config?.llm.model}</strong>
                </div>
                <div className="setting-line">
                  <span>API 配置</span>
                  <span
                    className={
                      config?.llm.configured ? "green-text" : "amber-text"
                    }
                  >
                    {config?.llm.configured ? "已配置本地密钥" : "等待本机配置"}
                  </span>
                </div>
                <div className="setting-line">
                  <span>累计估算费用</span>
                  <strong>
                    ¥ {config?.llm.spent_cny.toFixed(6)} /{" "}
                    {config?.llm.budget_cny.toFixed(2)}
                  </strong>
                </div>
                <div className="setting-line">
                  <span>计费单价</span>
                  <span
                    className={
                      config?.llm.pricing_configured
                        ? "green-text"
                        : "amber-text"
                    }
                  >
                    {config?.llm.pricing_configured
                      ? "已配置估算单价"
                      : "等待确认当前平台单价"}
                  </span>
                </div>
                <div className="setting-line">
                  <span>请求次数（含失败预留）</span>
                  <strong>{config?.llm.calls}</strong>
                </div>
                <p className="setting-help">
                  将项目根目录的 .env.example 复制为 .env，在本机填写
                  LLM_API_KEY。密钥不展示在网页，也不进入公开仓库。配置后点击右上角刷新。
                </p>
                <p className="setting-help">
                  费用按配置单价与 tokens
                  估算；失败请求保留费用预估。原始图片、订单号、商户名不发送至对话
                  API；开启联网后会发送你本次输入的问题及脱敏汇总。
                </p>
              </section>
              <section className="panel padded">
                <h2>本地分类模型</h2>
                <div className="setting-line">
                  <span>训练状态</span>
                  <strong>{config?.model.ready ? "已就绪" : "未训练"}</strong>
                </div>
                <div className="setting-line">
                  <span>模型版本</span>
                  <strong>{config?.model.version || "—"}</strong>
                </div>
                <p className="setting-help">
                  用户确认的类别修正保存在本地。更新将合并历史训练集与修正记录，重新训练并保留旧版本；实验更新前请使用独立的适应样本，避免污染固定测试集。
                </p>
                <button
                  className="button primary"
                  disabled={!!busy}
                  onClick={() =>
                    action("正在更新模型", async () => {
                      const r = await api<{
                        version: string;
                        feedback_count: number;
                      }>("/models/update", { method: "POST" });
                      setNotice(
                        `已使用 ${r.feedback_count} 条纠正记录更新模型：${r.version}`,
                      );
                    })
                  }
                >
                  <RefreshCw size={16} />
                  更新分类模型
                </button>
              </section>
              <section className="panel padded">
                <h2>公开演示与本地数据</h2>
                <p className="setting-help">
                  公开样例全部为明确标注的构造数据；你上传的真实账单保存在本机
                  runtime 目录。不要将该目录上传到 GitHub。
                </p>
                <button
                  className="button secondary"
                  disabled={!!busy}
                  onClick={demo}
                >
                  <FlaskConical size={17} />
                  载入构造演示
                </button>
                <a className="button ghost" href="/api/export?format=csv">
                  导出完整 CSV
                </a>
              </section>
            </div>
          )}
          <footer>
            <span>知账 · 个人多账户账单整理与异常核对 Agent</span>
            <span>
              <ShieldCheck size={13} />
              人民币 · 金额精确到分
            </span>
          </footer>
        </div>
      </main>
      {importOpen && (
        <div className="overlay" onClick={() => !busy && setImportOpen(false)}>
          <section
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-label="导入账单"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              className="close"
              onClick={() => setImportOpen(false)}
              aria-label="关闭"
            >
              <X size={21} />
            </button>
            <span className="modal-symbol">
              <Upload size={25} />
            </span>
            <h2>让账单，汇在一起。</h2>
            <p className="muted">
              导入微信或支付宝账单，知账会保留原始记录再整理。
            </p>
            <div className="form-row">
              <label>
                账单平台
                <select
                  value={platform}
                  onChange={(e) => {
                    setPlatform(e.target.value);
                    setAccount("我的" + e.target.value);
                  }}
                >
                  <option>微信</option>
                  <option>支付宝</option>
                </select>
              </label>
              <label>
                本人账户别名
                <input
                  value={account}
                  onChange={(e) => setAccount(e.target.value)}
                  placeholder="如：我的微信"
                />
              </label>
            </div>
            <label className="drop-zone">
              <Upload size={28} />
              <strong>
                {files.length
                  ? `已选择 ${files.length} 个文件`
                  : "点击选择账单文件或截图"}
              </strong>
              <span>CSV / XLSX / PNG / JPG · 每个文件不超过12MB</span>
              <input
                type="file"
                multiple
                accept=".csv,.xlsx,.png,.jpg,.jpeg"
                onChange={(e) => setFiles(Array.from(e.target.files || []))}
              />
            </label>
            {files.length > 0 && (
              <div className="file-list">
                {files.map((f) => (
                  <span key={f.name}>
                    <FileText size={13} />
                    {f.name}
                  </span>
                ))}
              </div>
            )}
            <div className="or">
              <span />
              或粘贴账单文字
              <span />
            </div>
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder={
                "例如：2026-09-08 12:30 青禾面馆 支出 28.00元\n也可以粘贴带表头的 CSV 文字"
              }
              rows={4}
            />
            <label className="check-line">
              <input
                type="checkbox"
                checked={synthetic}
                onChange={(e) => setSynthetic(e.target.checked)}
              />
              这是明确构造的演示数据
            </label>
            <div className="import-note">
              <ShieldCheck size={16} />
              文件和原始截图保存在本机，不会上传到公开仓库。
            </div>
            <button
              className="button primary full"
              disabled={
                !!busy || (!files.length && !text.trim()) || !account.trim()
              }
              onClick={importData}
            >
              {busy ? (
                <LoaderCircle className="spin" size={16} />
              ) : (
                <Sparkles size={17} />
              )}
              导入并开始整理
            </button>
            <button
              className="demo-button"
              onClick={() => {
                setImportOpen(false);
                demo();
              }}
              disabled={!!busy}
            >
              没有账单？先用构造数据体验 <ArrowRight size={14} />
            </button>
          </section>
        </div>
      )}
      {detail && (
        <div className="overlay detail-overlay" onClick={() => setDetail(null)}>
          <aside className="detail-drawer" onClick={(e) => e.stopPropagation()}>
            <div className="drawer-header">
              <h2>交易核对依据</h2>
              <button
                className="icon-btn"
                onClick={() => setDetail(null)}
                aria-label="关闭详情"
              >
                <X size={22} />
              </button>
            </div>
            <span
              className={
                "platform-label " +
                (detail.platform === "微信" ? "wechat" : "alipay")
              }
            >
              {detail.platform}
            </span>
            <h3>{detail.merchant || "未识别商户"}</h3>
            <div className="detail-amount">
              {detail.direction === "支出" ? "-" : "+"} ¥ {money(detail.amount)}
            </div>
            <p className="muted">
              {detail.time.replace("T", " ")} · {detail.account}
            </p>
            <div className="detail-list">
              {[
                ["交易类型", detail.kind],
                ["核对状态", detail.review_status],
                ["订单号", detail.order_id || "未提供"],
                ["分类置信度", Math.round(detail.confidence * 100) + "%"],
                [
                  "计账口径",
                  detail.excluded
                    ? detail.exclusion_reason || "已排除"
                    : "纳入核对后汇总",
                ],
                ["关联记录", detail.linked_id || "无"],
              ].map(([k, v]) => (
                <div key={k}>
                  <span>{k}</span>
                  <strong>{v}</strong>
                </div>
              ))}
            </div>
            <label className="field-label">
              修正消费类别
              <select
                value={editCat}
                onChange={(e) => setEditCat(e.target.value)}
              >
                {config?.categories.map((c) => (
                  <option key={c}>{c}</option>
                ))}
              </select>
            </label>
            <button
              className="button primary full"
              disabled={!!busy}
              onClick={() =>
                action("保存类别修正", async () => {
                  await api("/ledger/" + detail.id, {
                    method: "PATCH",
                    body: JSON.stringify({ category: editCat }),
                  });
                  setDetail(null);
                  setNotice("类别已修正并保存为反馈标签。");
                })
              }
            >
              保存类别修正 <Check size={16} />
            </button>
            <h4>说明</h4>
            <p>{detail.description || "未提供"}</p>
            <h4>来源位置</h4>
            <pre>{JSON.stringify(detail.sources, null, 2)}</pre>
            <h4>原始记录</h4>
            <pre>{JSON.stringify(detail.raw, null, 2)}</pre>
            {detail.linked_id && (
              <button
                className="button secondary"
                onClick={() => {
                  const t = rows.find((t) => t.id === detail.linked_id);
                  if (t) openDetail(t);
                }}
              >
                查看关联交易 <ArrowRight size={15} />
              </button>
            )}
          </aside>
        </div>
      )}
      {!!busy && <div className="busy-block" aria-hidden="true" />}
    </div>
  );
}

function Stat({
  label,
  amount,
  sub,
  highlight = false,
  icon,
}: {
  label: string;
  amount: number;
  sub: string;
  highlight?: boolean;
  icon?: React.ReactNode;
}) {
  return (
    <div className={"stat " + (highlight ? "highlight" : "")}>
      <div className="stat-label">
        {label}
        <span className="stat-icon">{icon || <ArrowUpRight size={18} />}</span>
      </div>
      <div className="stat-value">
        <span className="currency">¥</span>
        {money(amount)}
      </div>
      <p>
        {highlight && <span className="tiny-dot" />}
        {sub}
      </p>
    </div>
  );
}
function Empty({
  icon,
  title,
  text,
  action,
}: {
  icon: React.ReactNode;
  title: string;
  text: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="empty">
      <div className="empty-icon">{icon}</div>
      <h3>{title}</h3>
      <p>{text}</p>
      {action}
    </div>
  );
}
function Table({ rows, onDetail }: { rows: Tx[]; onDetail: (r: Tx) => void }) {
  return (
    <div className="table-wrap">
      <table className="transactions">
        <thead>
          <tr>
            <th>交易对方 / 说明</th>
            <th>账户</th>
            <th>类别</th>
            <th>金额</th>
            <th>核对状态</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr
              key={r.id}
              onClick={() => onDetail(r)}
              tabIndex={0}
              onKeyDown={(e) => e.key === "Enter" && onDetail(r)}
            >
              <td>
                <div className="merchant-cell">
                  <span
                    className={
                      "merchant-icon " +
                      (r.kind === "退款" ? "refund-icon" : "")
                    }
                  >
                    {r.kind === "退款" ? (
                      <ArrowLeftRight size={17} />
                    ) : r.kind === "转账" ? (
                      <ArrowLeftRight size={17} />
                    ) : (
                      <Wallet size={17} />
                    )}
                  </span>
                  <div>
                    <strong>{r.merchant || "未识别商户"}</strong>
                    <small>
                      {r.time.slice(0, 10)} · {r.description.slice(0, 18)}
                    </small>
                  </div>
                </div>
              </td>
              <td>
                <span
                  className={
                    "platform-label " +
                    (r.platform === "微信" ? "wechat" : "alipay")
                  }
                >
                  {r.platform}
                </span>
              </td>
              <td>
                <span className="category-tag">
                  {r.kind === "退款"
                    ? "退款"
                    : r.kind === "转账"
                      ? "转账"
                      : r.category || r.kind}
                </span>
              </td>
              <td
                className={
                  "amount-cell " + (r.direction === "收入" ? "income" : "")
                }
              >
                {r.direction === "支出" ? "-" : "+"}
                {money(r.amount)}
              </td>
              <td>
                <span
                  className={
                    "status " +
                    (r.excluded
                      ? "excluded"
                      : r.review_status === "待核对"
                        ? "pending"
                        : r.review_status === "待处理"
                          ? "unprocessed"
                          : "confirmed")
                  }
                >
                  <i />
                  {r.excluded ? "排除计账" : r.review_status}
                </span>
              </td>
              <td>
                <ChevronRight size={15} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
