const page = document.body.dataset.page || "research";
document.addEventListener("DOMContentLoaded", () => loadPage().catch((error) => { const node = document.getElementById("pageError"); if (node) node.textContent = `读取失败：${error.message}`; }));

async function json(url) { const response = await fetch(url); const body = await response.json(); if (!response.ok) throw new Error(body.error || response.statusText); return body; }
async function loadPage() {
  if (page === "chatgpt-qa") {
    const data = await json("/api/chatgpt-qa/history");
    renderChatgptQa(data);
    return;
  }
  const data = await json("/api/index");
  const latest = data.summary || {};
  setText("pageDate", latest.basis_trade_date || "--"); setText("pageModel", data.model_version || "--");
  if (page === "research") renderResearch(data); else if (page === "risk") renderRisk(data); else if (page === "cycle") renderCycle(data, await json("/api/cycle-engine/evidence")); else if (page === "allocation") renderAllocation(data); else renderMethodology(data);
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
function renderCycle(data, evidence) {
  const cycle = data.cycle_engine_position_policy || {}; const latest = cycle.latest || {}; const current = evidence.latest || {}; const candidate = current.candidate || {}; const stateMachine = current.state_machine || {}; const policy = current.policy || {};
  const basis = evidence.basis_month || latest.latest_month || "--"; const raw = candidate.candidate_state || "--"; const stable = stateMachine.stable_state || latest.latest_state || "--"; const range = policy.equity_min_pct == null ? (latest.recommended_equity_range || "不可用") : `${policy.equity_min_pct}%-${policy.equity_max_pct}%`;
  setText("cycleBasis", `${basis} · ${evidence.basis_trade_date || "--"}`); setText("cycleCandidate", stateLabel(raw)); setText("cycleState", stateLabel(stable)); setText("cycleRange", range); setText("cycleCount", `${cycle.record_count || 0} 个月`); setText("cycleCount2", `${cycle.record_count || 0} 个月`); setText("cycleTransition", `${transitionLabel(stateMachine.transition_status)} · ${reasonLabel((stateMachine.stable_reason_codes || [])[0])}`);
  const held = raw !== stable || raw === "ambiguous";
  setText("cycleHeadline", held ? `当前稳定状态沿用：${stateLabel(stable)}` : `当前状态已确认：${stateLabel(stable)}`);
  setText("cycleEvidenceSummary", held ? `${basis} 的四域规则先得到“${stateLabel(raw)}”，没有直接匹配明确的牛熊候选规则；稳定状态机执行“${transitionLabel(stateMachine.transition_status)}”，因此沿用上一稳定状态“${stateLabel(stable)}”，再映射为股票账户权益 ${range}。` : `${basis} 的四域规则得到“${stateLabel(raw)}”，稳定状态机确认后映射为股票账户权益 ${range}。`);
  renderCycleDomains(current.domain_signals || {}); renderCycleFeatures(current.selected_features || []); renderCycleRules(evidence.algorithm || {}); renderCycleTrace(evidence.recent_state_trace || []); renderCycleMapping(evidence.algorithm?.position_mapping || [], stable); renderCycleAudits(evidence);
  const rows = cycle.records || []; const table = document.getElementById("cycleRows"); if (table) table.innerHTML = rows.slice().reverse().map((row) => `<tr><td>${escapeHtml(row.month || "--")}</td><td>${escapeHtml(row.basis_trade_date || "--")}</td><td>${escapeHtml(stateLabel(row.stable_state))}</td><td>${row.equity_min_pct == null ? "不可用" : `${row.equity_min_pct}%`}</td><td>${row.equity_max_pct == null ? "不可用" : `${row.equity_max_pct}%`}</td><td>${escapeHtml(row.policy_reason || "--")}</td></tr>`).join("");
}
function renderCycleDomains(domains) {
  const definitions = [["valuation", "估值域", "长期价格位置"], ["earnings", "盈利域", "增长与盈利质量"], ["macro_confirmation", "宏观确认域", "PMI 方向确认"], ["trend", "趋势域", "沪深300 / 中证500 / 中证1000"], ["sentiment_overlay", "恐慌覆盖层", "只展示，不参与状态判定"]];
  const node = document.getElementById("cycleDomainCards"); if (!node) return;
  node.innerHTML = definitions.map(([key, label, hint]) => { const item = domains[key] || {}; return `<article class="domain-card"><div><span>${escapeHtml(label)}</span><strong>${escapeHtml(stateLabel(item.state || "unavailable"))}</strong></div><small>${escapeHtml(hint)}</small><p>${escapeHtml(domainSummary(key, item))}</p></article>`; }).join("");
}
function domainSummary(key, item) {
  if (key === "valuation") return `参与 ${item.participating_components?.join("、") || "--"}；可用 ${item.ready ? "是" : "否"}；中性 ${item.neutral_count ?? "--"} / 便宜 ${item.cheap_count ?? "--"} / 昂贵 ${item.expensive_count ?? "--"}。${item.unavailable_components?.length ? `缺失：${item.unavailable_components.join("、")}` : ""}`;
  if (key === "earnings") return `增长分位 ${format(item.growth_rank)}，3个月变化 ${formatSigned(item.growth_rank_change_3m)}；质量分位 ${format(item.quality_rank)}，3个月变化 ${formatSigned(item.quality_rank_change_3m)}。`;
  if (key === "macro_confirmation") return `${(item.reason_codes || []).join("、") || "无附加说明"}；${item.ready ? "数据可用" : "数据不足"}。`;
  if (key === "trend") return `指数状态：${Object.entries(item.index_states || {}).map(([name, value]) => `${name}=${stateLabel(value)}`).join("，") || "--"}；分化度 ${item.dispersion ?? "--"}。`;
  return `A-FEAR ${format(item.score)}；角色 ${item.role || "overlay_only"}；模型输入就绪：${item.model_ready ? "是" : "否"}。`;
}
function renderCycleFeatures(features) {
  const node = document.getElementById("cycleFeatureRows"); if (!node) return;
  node.innerHTML = features.map((item) => `<tr><td title="${escapeHtml(item.path)}">${escapeHtml(item.path)}</td><td>${escapeHtml(featureValue(item.raw_value, item.unit))}</td><td>${item.percentile == null ? "--" : `${format(item.percentile)}%`}</td><td>${escapeHtml(item.unit || "--")}</td><td>${escapeHtml(item.normalization_source || "--")} · ${escapeHtml(item.pit_date || "--")}</td><td>${item.available ? "是" : "否"}</td></tr>`).join("") || `<tr><td colspan="6">暂无输入证据</td></tr>`;
}
function renderCycleRules(algorithm) {
  const candidateNode = document.getElementById("cycleCandidateRules"); const stateNode = document.getElementById("cycleStateMachineRules");
  if (candidateNode) candidateNode.innerHTML = (algorithm.candidate_rules || []).map((rule) => `<li><b>${rule.priority}. ${escapeHtml(rule.name)}</b><span>${escapeHtml(rule.condition)}</span><em>→ ${escapeHtml(rule.result)}</em></li>`).join("");
  if (stateNode) stateNode.innerHTML = (algorithm.state_machine_rules || []).map((rule) => `<li>${escapeHtml(rule)}</li>`).join("");
}
function renderCycleTrace(rows) {
  const node = document.getElementById("cycleTraceRows"); if (!node) return;
  node.innerHTML = rows.slice().reverse().map((row) => `<tr><td>${escapeHtml(row.month || "--")}</td><td>${escapeHtml(stateLabel(row.raw_candidate_state))}</td><td>${escapeHtml(stateLabel(row.stable_state))}</td><td>${escapeHtml(transitionLabel(row.transition_status))}</td><td>${escapeHtml(row.pending_target ? stateLabel(row.pending_target) : "--")}</td><td>${escapeHtml(reasonLabel((row.stable_reason_codes || [])[0]))}</td></tr>`).join("");
}
function renderCycleMapping(rows, stable) {
  const node = document.getElementById("cycleMappingRows"); if (!node) return;
  node.innerHTML = rows.map((row) => `<tr class="${row.state === stable ? "current-row" : ""}"><td>${escapeHtml(stateLabel(row.state))}</td><td>${escapeHtml(row.equity_range)}</td><td>${row.state === stable ? "当前映射" : ""}</td></tr>`).join("");
}
function renderCycleAudits(evidence) {
  const node = document.getElementById("cycleAuditList"); if (!node) return;
  const audits = Object.entries(evidence.audits || {}).map(([name, item]) => `${name} 审计：${item.passed ? "通过" : "未通过"}（${item.path || "--"}）`); node.innerHTML = [...audits, ...(evidence.boundaries || [])].map((item, index) => `<li class="${index < audits.length ? "" : "risk"}">${escapeHtml(item)}</li>`).join("");
}
function renderAllocation(data) {
  const allocation = data.allocation_policy || {}; setText("allocationState", allocation.state || "--"); setText("allocationRange", allocation.total_risk_asset_range || "--"); const sleeves = allocation.sleeves || []; document.getElementById("sleeveRows").innerHTML = sleeves.map((item) => `<tr><td>${escapeHtml(item.label || item.key || "--")}</td><td>${escapeHtml(item.target_range || "--")}</td><td>${format(item.midpoint)}</td><td>${escapeHtml(item.description || "")}</td></tr>`).join(""); const history = allocation.history || []; document.getElementById("allocationRows").innerHTML = history.slice().reverse().slice(0,100).map((row) => `<tr><td>${escapeHtml(row.basis_trade_date || "--")}</td><td>${escapeHtml(row.state || "--")}</td><td>${format(row.market_position_score)}</td><td>${escapeHtml(row.sleeves?.liquidity?.target_range || "--")}</td></tr>`).join("");
}
function renderMethodology(data) { setText("methodModel", data.model_version || "--"); setText("methodPolicy", data.position_policy_version || "--"); const links = data.source_endpoints || {}; document.getElementById("apiLinks").innerHTML = Object.entries(links).map(([key,value]) => `<a href="${escapeHtml(value)}">${escapeHtml(key)} · ${escapeHtml(value)}</a>`).join(""); }
function renderChatgptQa(data) {
  const latest = data.latest || {};
  setText("qaBasisDate", latest.basis_trade_date || "--"); setText("qaModel", latest.model || "--"); setText("qaStage", latest.period_stage || "--"); setText("qaConfidence", `置信度 ${format(latest.confidence)}%`); setText("qaPosition", latest.position_range || `${format(latest.position_pct)}%`); setText("qaAction", latest.action || "--"); setText("qaCount", data.record_count ?? 0); setText("qaTrade", latest.no_trade ? "无需交易" : (latest.action || "--")); setText("qaRun", latest.source_run_id || "--"); setText("qaSummary", latest.core_summary || "暂无问答记录"); setText("qaAnswer", latest.answer_markdown || "暂无完整回答"); const auditLink = document.getElementById("qaAuditLink"); if (auditLink) { auditLink.href = latest.source_url || "#"; auditLink.style.display = latest.source_url ? "inline" : "none"; }
  renderQaList("qaDirections", latest.directions, (item) => `${item.name || "--"}：${item.reason || ""}`);
  renderQaList("qaAvoid", latest.avoid_directions, (item) => `${item.name || "--"}：${item.reason || ""}`);
  fillList("qaAddSignals", latest.turning_point_add_missing || []); fillList("qaReduceSignals", latest.turning_point_reduce_missing || []);
  const rows = data.records || []; const node = document.getElementById("qaHistoryRows"); if (node) node.innerHTML = rows.slice().reverse().map((row) => `<tr><td>${escapeHtml(row.basis_trade_date || "--")}</td><td>${escapeHtml(row.asked_at || "--")}</td><td>${escapeHtml(row.period_stage || "--")}</td><td>${format(row.confidence)}%</td><td>${escapeHtml(row.position_range || `${format(row.position_pct)}%`)}</td><td>${escapeHtml(row.action || "--")}</td><td>${escapeHtml((row.directions || []).map((item) => item.name || item).join("、"))}</td><td>${escapeHtml(row.comparison_to_previous?.summary || row.changes_vs_yesterday || "--")}</td><td>${row.source_url ? `<a href="${escapeHtml(row.source_url)}" target="_blank" rel="noopener">打开原文</a>` : "--"}</td></tr>`).join("") || `<tr><td colspan="9">暂无问答记录</td></tr>`;
}
function renderQaList(id, items, formatter) { const node = document.getElementById(id); if (!node) return; node.innerHTML = (items || []).map((item) => `<li>${escapeHtml(formatter(item))}</li>`).join("") || "<li>暂无记录</li>"; }
function fillList(id, items, className = "") { const node = document.getElementById(id); if (node) node.innerHTML = items.length ? items.slice(0,8).map((item) => `<li class="${className}">${escapeHtml(item)}</li>`).join("") : "<li>暂无记录</li>"; }
function setText(id, value) { const node = document.getElementById(id); if (node) node.textContent = value; }
function format(value) { return value == null || !Number.isFinite(Number(value)) ? "--" : Number(value).toFixed(2); }
function formatSigned(value) { const number = Number(value); return Number.isFinite(number) ? `${number >= 0 ? "+" : ""}${number.toFixed(2)}` : "--"; }
function featureValue(value, unit) { if (value === true) return "是"; if (value === false) return "否"; if (value == null || value === "") return "--"; const number = Number(value); return Number.isFinite(number) ? number.toFixed(unit === "ratio" ? 4 : 2) : String(value); }
function stateLabel(value) { return ({ ambiguous: "模糊", late_bull: "牛市后段", bull: "牛市", early_bull: "牛市早段", bottoming: "筑底", distribution: "分配", bear: "熊市", deep_bear: "深熊", insufficient_history: "历史不足", neutral: "中性", cheap: "便宜", expensive: "偏贵", recovery: "盈利修复", deterioration: "盈利恶化", mixed: "结构分化", extended: "趋势延伸", damaged: "趋势受损", up: "上行", negative: "偏负", positive: "偏正", insufficient_data: "数据不足", watch: "警觉", high_fear: "高恐慌", unavailable: "不可用" }[value] || value || "--"); }
function transitionLabel(value) { return ({ held_ambiguous: "模糊保持", held_same: "同状态保持", transition_confirmed: "两次命中后确认", pending_started: "开始等待确认", pending_replaced: "待确认目标替换", pending_expired: "待确认过期", initialized: "初始化" }[value] || value || "--"); }
function reasonLabel(value) { return ({ ambiguous_hold: "模糊状态保持", current_state_reconfirmed: "当前状态再确认", two_hit_transition_confirmed: "连续两月确认转换", pending_first_evidence: "首次候选证据", initial_non_ambiguous_state: "首个明确状态" }[value] || value || "--"); }
function escapeHtml(value) { return String(value ?? "").replace(/[&<>\"']/g, (char) => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", "\"":"&quot;", "'":"&#39;" }[char])); }
