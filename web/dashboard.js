document.addEventListener("DOMContentLoaded", async () => {
  try {
    renderDashboard(await getJson("/api/dashboard"));
  } catch (error) {
    setText("attentionTitle", "首页摘要暂不可用");
    setText("attentionMessage", error.message);
  }
});

async function getJson(url) {
  const response = await fetch(url);
  const body = await response.json();
  if (!response.ok || body.available === false) throw new Error(body.error || response.statusText);
  return body;
}

function renderDashboard(payload) {
  const summary = payload.summary || {};
  const marketStatus = payload.market_data_status || {};
  const cycle = payload.cycle || {};
  const cycleLatest = cycle.latest || {};
  const fear = payload.fear || {};
  const allocation = payload.allocation || {};
  const risk = payload.risk_overview || {};
  setText("modelLine", `${payload.model_version || "--"} · 股票账户研究摘要`);
  setText("basisDate", summary.basis_trade_date || "--");
  setText("freshnessState", marketStatus.requires_attention ? "需要检查更新" : "数据已覆盖");
  setText("equityRange", summary.recommended_equity_position_range || "不可用");
  setText("positionScore", `仓位分 ${formatNumber(summary.market_position_score)}`);
  setText("regimeLabel", summary.market_regime_label || "--");
  setText("decisionSummary", summary.market_observation?.summary || "暂无今日盘面观察");
  setText("cycleState", cycleLatest.latest_state || "--");
  setText("cycleRange", `权益 ${cycleLatest.recommended_equity_range || "不可用"}`);
  setText("cycleMonth", `基准月 ${cycleLatest.latest_month || "--"}`);
  setText("opportunityScore", formatNumber(summary.market_opportunity_score));
  setText("trendLabel", summary.trend_state_label || "--");
  renderFreshness(marketStatus);
  renderObservation(summary.market_observation || {});
  renderReasons(summary.decision_explain || {}, summary.risk_caps || []);
  renderAllocation(allocation);
  renderFear(fear);
  renderReminders(marketStatus, risk, summary);
  renderRecentChart(payload.recent_chart?.records || []);
}

function renderFreshness(status) {
  const node = document.getElementById("freshnessAlert");
  const attention = Boolean(status.requires_attention);
  node.classList.toggle("ok", !attention);
  setText("attentionTitle", status.title || (attention ? "研究需要检查" : "研究数据正常"));
  setText("attentionMessage", status.message || "当前没有数据新鲜度提醒。");
}

function renderObservation(observation) {
  setText("observationDate", observation.basis_trade_date || "今日");
  setText("observationTitle", observation.title || observation.label || "结构观察");
  setText("observationMessage", observation.summary || observation.message || "暂无盘面观察。");
  const items = observation.observations || observation.evidence || observation.next_actions || [];
  document.getElementById("observationSignals").innerHTML = (Array.isArray(items) ? items : []).slice(0, 4).map((item) => `<div class="signal-item">${escapeHtml(typeof item === "string" ? item : item.message || item.text || JSON.stringify(item))}</div>`).join("") || `<div class="signal-item">暂无补充观察</div>`;
}

function renderReasons(explain, caps) {
  const reasons = [...(explain.why_position_changed || []), ...(explain.risk_factors || [])].slice(0, 5);
  document.getElementById("decisionReasons").innerHTML = reasons.map((item) => `<div class="reason-item">${escapeHtml(item)}</div>`).join("") || `<div class="reason-item">暂无仓位变化说明</div>`;
  document.getElementById("riskCaps").textContent = caps.length ? caps.map((item) => item.message || item.reason).join("；") : "当前没有硬性风险上限。";
}

function renderAllocation(allocation) {
  setText("allocationState", `${allocation.state || "--"} · 风险资产 ${allocation.total_risk_asset_range || "--"}`);
  const sleeves = Array.isArray(allocation.sleeves) ? allocation.sleeves : Object.entries(allocation.sleeves || {}).map(([key, value]) => ({ key, ...value }));
  document.getElementById("allocationCards").innerHTML = sleeves.slice(0, 4).map((item) => `<div class="allocation-card"><strong>${escapeHtml(item.label || item.name || item.key || "--")}</strong><b>${escapeHtml(item.target_range || item.range || "--")}</b><small>${escapeHtml(item.description || item.purpose || "")}</small></div>`).join("") || `<div class="signal-item">暂无四仓配置</div>`;
}

function renderFear(fear) {
  setText("fearScore", formatNumber(fear.fear_score));
  setText("fearLevel", fear.level?.label || "--");
  setText("fearPhase", fear.phase?.label || "--");
  setText("fear300", formatNumber(fear.fear_300));
  setText("fear1000", formatNumber(fear.fear_1000));
  setText("fearSpread", formatSigned(fear.small_cap_fear_spread));
  const score = Math.max(0, Math.min(100, Number(fear.fear_score) || 0));
  document.getElementById("fearChart").innerHTML = `<div class="fear-meter"><div class="fear-meter-value" style="width:${score}%"></div></div>`;
}

function renderReminders(status, risk, summary) {
  const reminders = [];
  if (status.requires_attention) reminders.push(status.message || "研究基准日需要检查");
  if (risk.risk_caps?.count) reminders.push(risk.risk_caps.message || `已触发 ${risk.risk_caps.count} 项风险上限`);
  if (summary.confidence && summary.confidence !== "high") reminders.push(`模型置信度：${summary.confidence}`);
  document.getElementById("reminderList").innerHTML = reminders.map((item) => `<div class="reminder-item">${escapeHtml(item)}</div>`).join("") || `<div class="reminder-item">暂无待处理提醒</div>`;
}

function renderRecentChart(records) {
  const container = document.getElementById("recentChart");
  if (!records.length) { container.textContent = "暂无近期曲线"; return; }
  const width = 1180, height = 330, margin = { top: 20, right: 24, bottom: 38, left: 48 };
  const plotWidth = width - margin.left - margin.right, plotHeight = height - margin.top - margin.bottom;
  const indices = records.map((item) => Number(item.shanghai_composite)).filter(Number.isFinite);
  const indexMin = Math.min(...indices), indexMax = Math.max(...indices);
  const x = (i) => margin.left + (i / Math.max(records.length - 1, 1)) * plotWidth;
  const yPosition = (v) => margin.top + (1 - v / 100) * plotHeight;
  const yIndex = (v) => margin.top + (1 - (v - indexMin) / Math.max(indexMax - indexMin, 1)) * plotHeight;
  const svg = createSvg("svg", { viewBox: `0 0 ${width} ${height}`, role: "img" });
  svg.appendChild(createSvg("title", {}, "近期仓位分与上证指数"));
  [0, 25, 50, 75, 100].forEach((tick) => { const yy = yPosition(tick); svg.appendChild(createSvg("line", { class: "grid-line", x1: margin.left, y1: yy, x2: width - margin.right, y2: yy })); svg.appendChild(createSvg("text", { class: "chart-tick", x: 8, y: yy + 4 }, `${tick}`)); });
  svg.appendChild(createSvg("text", { class: "chart-tick", x: 8, y: margin.top - 7 }, "仓位分"));
  svg.appendChild(createSvg("text", { class: "chart-tick", x: width - 62, y: margin.top - 7 }, "上证"));
  const path = (field, mapper) => records.map((item, i) => { const value = Number(item[field]); return Number.isFinite(value) ? `${i ? "L" : "M"} ${x(i)} ${mapper(value)}` : ""; }).filter(Boolean).join(" ");
  svg.appendChild(createSvg("path", { class: "chart-line index", d: path("shanghai_composite", yIndex) }));
  svg.appendChild(createSvg("path", { class: "chart-line position", d: path("market_position_score", yPosition) }));
  records.forEach((item, i) => { if (i !== records.length - 1 && i % Math.max(1, Math.ceil(records.length / 7)) !== 0) return; svg.appendChild(createSvg("text", { class: "chart-tick", x: x(i), y: height - 10, "text-anchor": "middle" }, String(item.basis_trade_date || "").slice(5, 10))); });
  container.innerHTML = `<div class="chart-legend"><span>仓位分</span><span class="index">上证指数</span></div>`;
  container.appendChild(svg);
}

function createSvg(tag, attrs, textContent) { const node = document.createElementNS("http://www.w3.org/2000/svg", tag); Object.entries(attrs || {}).forEach(([key, value]) => node.setAttribute(key, value)); if (textContent !== undefined) node.textContent = textContent; return node; }
function setText(id, value) { const node = document.getElementById(id); if (node) node.textContent = value; }
function formatNumber(value) { return value === null || value === undefined || !Number.isFinite(Number(value)) ? "--" : Number(value).toFixed(2); }
function formatSigned(value) { const number = Number(value); return Number.isFinite(number) ? `${number >= 0 ? "+" : ""}${number.toFixed(2)}` : "--"; }
function escapeHtml(value) { return String(value ?? "").replace(/[&<>\"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" }[char])); }
