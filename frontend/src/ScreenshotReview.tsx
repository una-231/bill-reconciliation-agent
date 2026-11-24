import React, { useEffect, useState } from "react";
import { Check, ChevronLeft, ChevronRight, Save, X } from "lucide-react";

type Fields = {
  id: string; date: string | null; time: string | null; merchant: string;
  amount_yuan: string | null; direction: string | null; kind: string;
  platform: string | null; account: string; description: string;
};
type Draft = {
  id: string; file: string; image_token: string; row: number; fields: Fields;
  status: string; reviewed: boolean; error: string; raw: Record<string, unknown>;
};
export type ScreenshotJob = {
  id: string; name: string; screenshot_revision?: number; screenshot_drafts?: Draft[];
};
type Request = <T>(path: string, options?: RequestInit) => Promise<T>;
const ready = (f: Fields) => !!(f.date && f.time && f.merchant.trim() && f.account.trim() &&
  f.platform && f.direction && f.amount_yuan !== null && /^\d+(\.\d{1,2})?$/.test(f.amount_yuan));

export default function ScreenshotReview({ job, request, onClose, onImported }: {
  job: ScreenshotJob; request: Request; onClose: () => void;
  onImported: (child: { id: string; imported: number }) => Promise<void>;
}) {
  const cacheKey = "bill-screenshot-edits:" + job.id;
  const [revision, setRevision] = useState(job.screenshot_revision || 1);
  const [drafts, setDrafts] = useState<Draft[]>(() => {
    try {
      const cached = JSON.parse(localStorage.getItem(cacheKey) || "null");
      if (cached?.revision === job.screenshot_revision && Array.isArray(cached.drafts)) return cached.drafts;
    } catch { /* 无效缓存由服务端草稿恢复。 */ }
    return job.screenshot_drafts || [];
  });
  const [index, setIndex] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const active = drafts[index];
  const confirmed = drafts.filter(d => d.status === "pending" && d.reviewed);
  const pending = drafts.filter(d => d.status !== "imported");
  useEffect(() => { localStorage.setItem(cacheKey, JSON.stringify({ revision, drafts })); }, [drafts, revision]);
  const edit = (patch: Partial<Fields>) => {
    setMessage("");
    setDrafts(rows => rows.map((d, i) => i === index ? {
      ...d, fields: { ...d.fields, ...patch }, reviewed: false, status: "pending",
    } : d));
  };
  const save = async (next = drafts) => {
    const items = next.filter(d => d.status !== "imported").map(d => ({
      id: d.id, fields: d.fields, reviewed: d.reviewed, held: d.status === "held",
    }));
    if (!items.length) return revision;
    const saved = await request<ScreenshotJob>(`/jobs/${job.id}/screenshots`, {
      method: "PATCH", body: JSON.stringify({ revision, items }),
    });
    setDrafts(saved.screenshot_drafts || []);
    setRevision(saved.screenshot_revision!);
    return saved.screenshot_revision!;
  };
  const perform = async (fn: () => Promise<void>) => {
    setBusy(true); setError(""); setMessage("");
    try { await fn(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  const mark = (held: boolean) => perform(async () => {
    const next = drafts.map((d, i) => i === index ? { ...d, reviewed: !held, status: held ? "held" : "pending" } : d);
    await save(next);
    setIndex(Math.min(index + 1, drafts.length - 1));
    setMessage(held ? "此条已暂缓，可补充完整信息后继续。" : "字段已确认，尚未入账。");
  });
  const commit = () => perform(async () => {
    const version = await save();
    const child = await request<{ id: string; imported: number }>(`/jobs/${job.id}/screenshots/commit`, {
      method: "POST", body: JSON.stringify({ revision: version, ids: confirmed.map(d => d.id) }),
    });
    const parent = await request<ScreenshotJob>(`/jobs/${job.id}`);
    setDrafts(parent.screenshot_drafts || []); setRevision(parent.screenshot_revision!);
    await onImported(child);
    setMessage(`已新增 ${child.imported} 条交易。分类、退款和重复关系请继续查看待核对。`);
  });
  if (!active) return null;
  const f = active.fields;
  const locked = active.status === "imported";
  return <div className="overlay screenshot-overlay">
    <section className="screenshot-modal" role="dialog" aria-modal="true" aria-labelledby="screenshot-title">
      <header className="screenshot-heading">
        <div><h2 id="screenshot-title">截图核对</h2><p>对照原图确认字段，信息不完整的记录可暂缓。</p></div>
        <button className="icon-button" title="保存并关闭" aria-label="保存并关闭截图核对" disabled={busy}
          onClick={() => perform(async () => { await save(); await onImported({ id: "", imported: 0 }); onClose(); })}><X size={20} /></button>
      </header>
      <div className="screenshot-workspace">
        <div className="screenshot-source">
          <div className="screenshot-source-label"><strong>原始截图</strong><span>{active.file}</span></div>
          <div className="screenshot-image-scroll"><img src={`/api/jobs/${job.id}/images/${active.image_token}`} alt={`${active.file} 原始账单截图`} /></div>
        </div>
        <div className="screenshot-editor">
          <div className="screenshot-navigation">
            <button className="icon-button" aria-label="上一条" disabled={busy || index === 0} onClick={() => setIndex(index - 1)}><ChevronLeft size={18} /></button>
            <select aria-label="选择截图记录" value={index} disabled={busy} onChange={e => setIndex(Number(e.target.value))}>
              {drafts.map((d, i) => <option key={d.id} value={i}>{i + 1}. {d.fields.merchant || "待补充商户"} · {d.status === "imported" ? "已入账" : d.status === "held" ? "暂缓" : d.reviewed ? "已确认" : "待核对"}</option>)}
            </select>
            <button className="icon-button" aria-label="下一条" disabled={busy || index === drafts.length - 1} onClick={() => setIndex(index + 1)}><ChevronRight size={18} /></button>
          </div>
          <p className="muted small">第 {index + 1} / {drafts.length} 条 · {active.file}</p>
          {active.error && <div className="note-warning">识别提示：{active.error}</div>}
          {locked && <div className="note-warning">此条已入账，后续类别与关联核对请在交易明细中处理。</div>}
          <fieldset className="screenshot-fields" disabled={busy || locked}>
            <label>交易日期<input type="date" value={f.date || ""} onChange={e => edit({ date: e.target.value || null })} /></label>
            <label>交易时间<input type="time" value={f.time || ""} onChange={e => edit({ time: e.target.value || null })} /></label>
            <label className="screenshot-wide">商户 / 交易对方<input value={f.merchant} onChange={e => edit({ merchant: e.target.value })} /></label>
            <label>金额（元）<input inputMode="decimal" value={f.amount_yuan ?? ""} placeholder="对照原图填写" onChange={e => edit({ amount_yuan: e.target.value || null })} /></label>
            <label>收支方向<select value={f.direction || ""} onChange={e => edit({ direction: e.target.value || null })}><option value="">请选择</option><option>支出</option><option>收入</option><option>不计收支</option></select></label>
            <label>交易类型<select value={f.kind} onChange={e => edit({ kind: e.target.value })}><option>消费</option><option>收入</option><option>退款</option><option>转账</option></select></label>
            <label>平台<select value={f.platform || ""} onChange={e => edit({ platform: e.target.value })}><option>微信</option><option>支付宝</option></select></label>
            <label className="screenshot-wide">本人账户<input value={f.account} onChange={e => edit({ account: e.target.value })} /></label>
          </fieldset>
          <details className="screenshot-raw"><summary>查看此条OCR原文</summary><pre>{String(active.raw.ocr_block || active.raw.ocr_text || active.raw.text || "未提取到文本")}</pre></details>
          <div className="screenshot-row-actions">
            <button className="button secondary" disabled={busy || locked} onClick={() => mark(true)}>暂缓此条</button>
            <button className="button primary" disabled={busy || locked || !ready(f)} onClick={() => mark(false)}><Check size={15} />字段无误，下一条</button>
          </div>
          {!ready(f) && !locked && <p className="muted small">缺失信息需根据完整截图或交易详情补充后确认。</p>}
          {error && <p className="screenshot-error" role="alert">{error}</p>}
          {message && <p className="screenshot-message" role="status">{message}</p>}
        </div>
      </div>
      <footer className="screenshot-footer">
        <span>待处理 {pending.length} 条 · 已确认 {confirmed.length} 条 · 暂缓 {drafts.filter(d => d.status === "held").length} 条</span>
        <div><button className="button secondary" disabled={busy || !pending.length} onClick={() => perform(async () => { await save(); setMessage("截图草稿已保存，重新打开可继续核对。"); })}><Save size={15} />保存草稿</button>
          <button className="button primary" disabled={busy || !confirmed.length} onClick={commit}>{busy ? "正在保存…" : `将已确认的 ${confirmed.length} 条入账`}</button></div>
      </footer>
    </section>
  </div>;
}
