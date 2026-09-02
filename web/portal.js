const page = document.body.dataset.page || "research";
document.addEventListener("DOMContentLoaded", () => loadPage().catch((error) => { const node = document.getElementById("pageError"); if (node) node.textContent = `读取失败：${error.message}`; }));

async function json(url) { const response = await fetch(url); const body = await response.json(); if (!response.ok) throw new Error(body.error || response.statusText); return body; }
async function loadPage() {
  const data = await json(page === "risk" ? "/api/index" : "/api/index");
  const latest = data.summary || {};
  setText("pageDate", latest.basis_trade_date || "--"); setText("pageModel", data.model_version || "--");
  if (page === "research") renderResearch(data); else if (page === "risk") renderRisk(data); else if (page === "cycle") renderCycle(data); else if (page === "allocation") renderAllocation(data); else renderMethodology(data);
}
function renderResearch(data) {
  const s = data.summary || {}; setText("positionScore", format(s.market_position_score)); setText("opportunityScore", format(s.market_opportunity_score)); setText("equityRange", s.recommended_equity_position_range || "--"); setText("regime", s.market_regime_label || "--");
  const explain = s.decision_explain || {}; fillList("whyList", [...(explain.why_position_changed || []), ...(explain.risk_factors || [])]);
  const modules = data.modules || {}; document.getElementById("moduleRows").innerHTML = Object.entries(modules).map(([key,item]) => `<tr><td>${escapeHtml(item.label || key)}</td><td>${format(item.score)}</td><td>${format(item.weight)}</td><td>${escapeHtml(item.summary || "")}</td></tr>`).join("");
  const rows = data.history_table?.rows || []; document.getElementById("historyRows").innerHTML = rows.slice(0,120).map((row) => `<tr><td>${escapeHtml(row.basis_trade_date || "--")}</td><td>${format(row.market_opportunity_score)}</td><td>${format(row.market_position_score)}</td><td>${escapeHtml(row.recommended_equity_position_range || "--")}</td><td>${escapeHtml(row.market_regime_label || "--")}</td></tr>`).join("");
}
function renderRisk(data) {
  const fear = data.fear?.record || {}; const risk = data.risk_overview || {}; setText("fearScore", format(fear.fear_score)); setText("fearLevel", fear.level?.label || "--"); setText("fearChange", formatSigned(fear.change_1d)); setText("fearSpread", formatSigned(fear.small_cap_fear_spread)); setText("riskCount", `${risk.risk_caps?.count || 0} 项`); setText("quality", `${risk.data_quality?.warning_count || 0} 条 warning`);
  const components = fear.components || {}; document.getElementById("componentRows").innerHTML = Object.entries(components).map(([key,item]) => `<tr><td>${escapeHtml(key)}</td><td>${format(item.score)}</td><td>${format(Number(item.weight) * 100)}%</td></tr>`).join("");
  fillList("riskList", (risk.risk_caps?.items || []).map((item) => item.message || item.reason), "risk");
  const history = data.fear?.record ? [] : []; setText("riskNote", fear.safety?.note || "A-FEAR 只用于恐慌监测，不直接改变仓位建议。");
}
function renderCycle(data) {
  const cycle = data.cycle_engine_position_policy || {}; const latest = cycle.latest || {}; setText("cycleState", latest.latest_state || "--"); setText("cycleRange", latest.recommended_equity_range || "--"); setText("cycleCount", `${cycle.record_count || 0} 个月`); setText("cycleCount2", `${cycle.record_count || 0} 个月`); const rows = cycle.records || []; document.getElementById("cycleRows").innerHTML = rows.slice().reverse().map((row) => `<tr><td>${escapeHtml(row.month || "--")}</td><td>${escapeHtml(row.basis_trade_date || "--")}</td><td>${escapeHtml(row.stable_state || "--")}</td><td>${row.equity_min_pct == null ? "不可用" : `${row.equity_min_pct}%`}</td><td>${row.equity_max_pct == null ? "不可用" : `${row.equity_max_pct}%`}</td><td>${escapeHtml(row.policy_reason || "--")}</td></tr>`).join("");
}
function renderAllocation(data) {
  const allocation = data.allocation_policy || {}; setText("allocationState", allocation.state || "--"); setText("allocationRange", allocation.total_risk_asset_range || "--"); const sleeves = allocation.sleeves || []; document.getElementById("sleeveRows").innerHTML = sleeves.map((item) => `<tr><td>${escapeHtml(item.label || item.key || "--")}</td><td>${escapeHtml(item.target_range || "--")}</td><td>${format(item.midpoint)}</td><td>${escapeHtml(item.description || "")}</td></tr>`).join(""); const history = allocation.history || []; document.getElementById("allocationRows").innerHTML = history.slice().reverse().slice(0,100).map((row) => `<tr><td>${escapeHtml(row.basis_trade_date || "--")}</td><td>${escapeHtml(row.state || "--")}</td><td>${format(row.market_position_score)}</td><td>${escapeHtml(row.sleeves?.liquidity?.target_range || "--")}</td></tr>`).join("");
}
function renderMethodology(data) { setText("methodModel", data.model_version || "--"); setText("methodPolicy", data.position_policy_version || "--"); const links = data.source_endpoints || {}; document.getElementById("apiLinks").innerHTML = Object.entries(links).map(([key,value]) => `<a href="${escapeHtml(value)}">${escapeHtml(key)} · ${escapeHtml(value)}</a>`).join(""); }
function fillList(id, items, className = "") { const node = document.getElementById(id); if (node) node.innerHTML = items.length ? items.slice(0,8).map((item) => `<li class="${className}">${escapeHtml(item)}</li>`).join("") : "<li>暂无记录</li>"; }
function setText(id, value) { const node = document.getElementById(id); if (node) node.textContent = value; }
function format(value) { return value == null || !Number.isFinite(Number(value)) ? "--" : Number(value).toFixed(2); }
function formatSigned(value) { const number = Number(value); return Number.isFinite(number) ? `${number >= 0 ? "+" : ""}${number.toFixed(2)}` : "--"; }
function escapeHtml(value) { return String(value ?? "").replace(/[&<>\"']/g, (char) => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", "\"":"&quot;", "'":"&#39;" }[char])); }
