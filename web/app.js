const moduleOrder = [
  "index_trend",
  "breadth",
  "liquidity",
  "capital_flow",
  "mainline",
  "valuation",
  "macro",
];

const moduleColors = {
  index_trend: "#2c68a0",
  breadth: "#2f7d4f",
  liquidity: "#047d73",
  capital_flow: "#b7791f",
  mainline: "#bf3d2b",
  valuation: "#6b7280",
  macro: "#7c5f1d",
};

const chartColors = {
  position: "#047d73",
  preCap: "#6b7280",
  opportunity: "#2c68a0",
  shanghai: "#aeb8b3",
  penalty: "#bf3d2b",
  betaCore: "#2c68a0",
  alphaActive: "#bf3d2b",
  defensiveFactor: "#2f7d4f",
  liquidity: "#6b7280",
};

const allocationColors = {
  beta_core: chartColors.betaCore,
  alpha_active: chartColors.alphaActive,
  defensive_factor: chartColors.defensiveFactor,
  liquidity: chartColors.liquidity,
};

// Compatibility fallback only. The default page uses /api/index.position_policy_map.bands.
const fallbackPositionScoreBands = [
  { score_min: 0, score_max: 20, position_range: "0%-20%", label: "极弱 / 防守", description: "市场位置偏弱，股票账户以防守为主。" },
  { score_min: 20, score_max: 35, position_range: "20%-40%", label: "弱修复 / 谨慎", description: "市场有修复迹象，但仍不适合高仓位。" },
  { score_min: 35, score_max: 50, position_range: "40%-60%", label: "中性震荡", description: "市场处于中性区，仓位以均衡为主。" },
  { score_min: 50, score_max: 65, position_range: "55%-75%", label: "结构性偏强", description: "市场有较明确结构性机会，可维持中高仓位。" },
  { score_min: 65, score_max: 80, position_range: "75%-90%", label: "趋势偏强", description: "趋势和风险收益较好，可较高仓位参与。" },
  { score_min: 80, score_max: 100, position_range: "90%-100%", label: "低拥挤强趋势", description: "市场健康且风险约束未触发时，股票账户可接近满仓。" },
];

const fallbackMarketCycleReference = {
  title: "市场八浪周期与评分区间",
  is_prediction: false,
  basis: "示意图只解释模型在不同周期位置的典型评分反应，不用于预测当前浪位。",
  waves: [
    { wave: "1", phase: "impulse", label: "熊末反弹", price_level: 42, opportunity_score_range: "45-60", position_score_range: "40-70", equity_position_range: "40%-75%", note: "估值开始有吸引力，但趋势和资金通常还需要确认。" },
    { wave: "2", phase: "impulse", label: "回踩确认", price_level: 32, opportunity_score_range: "35-50", position_score_range: "35-60", equity_position_range: "20%-60%", note: "便宜度仍在，但回踩会压低趋势、宽度和风险偏好。" },
    { wave: "3", phase: "impulse", label: "主升共振", price_level: 82, opportunity_score_range: "75-90", position_score_range: "80-100", equity_position_range: "90%-100%", note: "趋势、宽度、资金和主线共振，是模型最愿意重仓的位置。" },
    { wave: "4", phase: "impulse", label: "中继调整", price_level: 64, opportunity_score_range: "60-75", position_score_range: "60-80", equity_position_range: "55%-90%", note: "牛市中继回撤，仓位不追高，但也不按熊市处理。" },
    { wave: "5", phase: "impulse", label: "牛末冲顶", price_level: 90, opportunity_score_range: "60-80", position_score_range: "20-45", equity_position_range: "20%-60%", note: "人气和趋势仍强，但估值、拥挤、波动和风险上限开始压仓位。" },
    { wave: "a", phase: "corrective", label: "顶部杀跌", price_level: 55, opportunity_score_range: "40-55", position_score_range: "20-40", equity_position_range: "20%-60%", note: "顶部后的第一波下跌，风险释放不充分，先控制仓位。" },
    { wave: "b", phase: "corrective", label: "反抽诱多", price_level: 68, opportunity_score_range: "50-65", position_score_range: "20-45", equity_position_range: "20%-60%", note: "反抽会抬高短期机会分，但若估值和资金没有修复，仓位仍受约束。" },
    { wave: "c", phase: "corrective", label: "悲观出清", price_level: 22, opportunity_score_range: "25-45", position_score_range: "10-40", equity_position_range: "0%-40%", note: "最悲观时估值便宜，但趋势、资金和宽度常未确认，不会盲目满仓。" },
  ],
};

const svgNs = "http://www.w3.org/2000/svg";

let state = {
  history: null,
  records: [],
  latest: null,
  index: null,
  historyVersionFilter: null,
  selectedModule: "index_trend",
};

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("scoreButton").addEventListener("click", appendCurrentScore);
  document.getElementById("moduleSelect").addEventListener("change", (event) => {
    state.selectedModule = event.target.value;
    renderModuleGrid();
    renderModuleDetails();
  });
  loadHistory();
});

async function loadHistory() {
  setStatus("读取历史");
  const [payload, indexPayload] = await Promise.all([fetchJson("/api/history"), fetchJson("/api/index")]);
  state.history = payload.history;
  state.historyVersionFilter = payload.version_filter || payload.history?.version_filter || null;
  state.records = normalizeRecords(payload.history.records || []);
  state.latest = state.records[state.records.length - 1] || null;
  state.index = indexPayload;
  setStatus(state.latest ? "已更新" : "无评分记录");
  renderAll();
}

async function appendCurrentScore() {
  const button = document.getElementById("scoreButton");
  button.disabled = true;
  setStatus("记录中");
  try {
    const payload = await fetchJson("/api/score", { method: "POST" });
    state.history = payload.history;
    state.records = normalizeRecords(payload.history.records || []);
    state.latest = state.records[state.records.length - 1] || null;
    state.index = await fetchJson("/api/index");
    setStatus("已记录");
    renderAll();
  } catch (error) {
    setStatus(`失败：${error.message}`);
  } finally {
    button.disabled = false;
  }
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || response.statusText);
  }
  return payload;
}

function normalizeRecords(records) {
  return [...records].sort((a, b) => String(a.scored_at).localeCompare(String(b.scored_at)));
}

function renderAll() {
  renderBasisStatus();
  renderSummary();
  renderRiskOverview();
  renderContrarianOverlay();
  renderAllocationPolicy();
  renderPositionMap();
  renderMarketCycleReference();
  renderOverviewChart();
  renderModuleSelect();
  renderModuleGrid();
  renderModuleDetails();
  renderHistoryTable();
  renderApiCatalog();
}

function renderBasisStatus() {
  const status = state.index?.market_data_status || {};
  const latest = state.latest || {};
  const basis = status.basis_trade_date || latest.basis_trade_date || "--";
  const severity = ["normal", "warning", "critical"].includes(status.severity) ? status.severity : "normal";
  const band = document.getElementById("basisStatusBand");
  if (band) {
    band.classList.remove("normal", "warning", "critical");
    band.classList.add(severity);
  }
  setText("basisStatusDate", `基准日 ${basis}`);
  setText("basisStatusMessage", status.message || "暂无市场研究状态。");
  const details = status.details || [];
  const detailText = details.length ? details.join(" · ") : `最新完整数据日 ${status.latest_data_trade_date || "--"}`;
  setText("basisStatusDetails", detailText);
}

function renderSummary() {
  const latest = state.latest;
  if (!latest) {
    setText("modelLine", "暂无评分历史");
    ["positionScore", "opportunityScore", "crowdingPenalty", "marketRegime"].forEach((id) => setText(id, "--"));
    setText("positionRange", "--");
    setText("volAdjustedRange", "--");
    setMeter("positionMeter", 0, 100);
    setMeter("opportunityMeter", 0, 100);
    setMeter("crowdingMeter", 0, 30);
    return;
  }

  setText("modelLine", `${latest.model_version} · ${formatDateTime(latest.scored_at)}`);
  setText("positionScore", formatNumber(latest.market_position_score));
  setText("opportunityScore", formatNumber(latest.market_opportunity_score));
  setText("crowdingPenalty", formatNumber(latest.crowding_penalty));
  setText("marketRegime", latest.market_regime || "--");
  setText("basisDate", `基准日 ${latest.basis_trade_date || "--"}`);
  setText("confidence", `置信度 ${confidenceLabel(latest.confidence)}`);
  const recommendedRange = officialPositionRange(latest);
  const riskCapCount = (latest.risk_caps || []).length;
  const overlay = latest.contrarian_beta_overlay || {};
  const overlayNote = overlay.active ? ` · 逆向β +${formatNumber(latest.contrarian_beta_add_score)}` : "";
  setText("positionRange", `官方推荐权益 ${recommendedRange}`);
  setText(
    "volAdjustedRange",
    `${latest.position_policy_version || "stock_account_position_policy_v2"} · ${riskCapCount ? `已触发${riskCapCount}项风险上限` : "未触发风险上限"}${overlayNote}`,
  );
  setMeter("positionMeter", latest.market_position_score, 100);
  setMeter("opportunityMeter", latest.market_opportunity_score, 100);
  setMeter("crowdingMeter", latest.crowding_penalty, 30);
  setText("recordCount", `${state.records.length} 条记录`);
  const filter = state.historyVersionFilter;
  const scope = filter?.include_legacy
    ? "全部版本"
    : `当前版本 ${filter?.model_version || latest.model_version || "--"} · ${filter?.position_policy_version || latest.position_policy_version || "--"}`;
  setText("historyUpdated", state.history?.updated_at ? `更新 ${formatDateTime(state.history.updated_at)} · ${scope}` : scope);
}

function renderRiskOverview() {
  const latest = state.latest;
  const overview = state.index?.risk_overview || buildRiskOverviewFromRecord(latest);
  if (!latest) {
    setText("riskOverviewStatus", "暂无评分");
    setText("riskConfidence", "--");
    setText("riskConfidenceDetail", "--");
    setText("qualityWarningCount", "--");
    setText("qualityDataDetail", "--");
    setText("riskCapTotal", "--");
    setText("riskCapDetail", "--");
    renderMessageList("qualityWarnings", [], "暂无数据质量 warning");
    renderMessageList("riskCapList", [], "未触发风险上限");
    return;
  }

  const confidence = overview.confidence || {};
  const quality = overview.data_quality || {};
  const caps = overview.risk_caps || {};
  const warnings = Array.isArray(quality.warnings) ? quality.warnings : [];
  const riskCaps = Array.isArray(caps.items) ? caps.items : [];
  const statusLabel = overview.status_label || (warnings.length || riskCaps.length ? "需关注" : "正常");

  setText("riskOverviewStatus", `${statusLabel} · ${warnings.length} 条 warning · ${riskCaps.length} 项风险上限`);
  setText("riskConfidence", confidence.label || confidenceLabel(confidence.value || latest.confidence));
  setText("riskConfidenceDetail", confidence.message || "置信度由核心字段、warning 和样本质量决定。");
  setText("qualityWarningCount", `${quality.warning_count ?? warnings.length} 条`);
  setText(
    "qualityDataDetail",
    `${quality.message || (warnings.length ? `存在 ${warnings.length} 条数据质量 warning。` : "暂无数据质量 warning。")} 缺失字段 ${quality.missing_field_count ?? 0} 个，数据源 ${quality.source_count ?? 0} 个。`,
  );
  setText("riskCapTotal", `${caps.count ?? riskCaps.length} 项`);
  setText("riskCapDetail", caps.message || (riskCaps.length ? `已触发 ${riskCaps.length} 项风险上限。` : "未触发风险上限。"));
  renderMessageList("qualityWarnings", warnings, "暂无数据质量 warning");
  renderMessageList("riskCapList", riskCaps, "未触发风险上限", riskCapMessage);
}

function renderContrarianOverlay() {
  const latest = state.latest;
  const summaryOverlay = state.index?.summary?.contrarian_beta_overlay;
  const policyOverlay = state.index?.allocation_policy?.contrarian_beta_overlay;
  const overlay = summaryOverlay || policyOverlay || latest?.contrarian_beta_overlay || {};
  if (!latest) {
    setText("contrarianStatus", "暂无评分");
    setText("contrarianActive", "--");
    setText("contrarianAction", "--");
    setText("contrarianScore", "--");
    setText("contrarianFloor", "--");
    setText("contrarianBetaOnly", "--");
    renderMessageList("contrarianDrivers", [], "暂无逆向仓位数据");
    return;
  }

  const active = Boolean(overlay.active);
  const addScore = numeric(overlay.add_score);
  const intensity = numeric(overlay.intensity_score);
  const floor = numeric(overlay.score_floor);
  setText("contrarianStatus", active ? "已启用" : "未启用");
  setText("contrarianActive", active ? "β核心仓加仓" : "保持常规仓位");
  setText(
    "contrarianAction",
    active
      ? `仓位分从 ${formatNumber(overlay.current_score_before_overlay)} 抬到 ${formatNumber(overlay.target_score)}`
      : "未满足低估、深回撤、资金稳定的组合条件",
  );
  setText("contrarianScore", `${formatNumber(intensity)} / +${formatNumber(addScore)}`);
  setText("contrarianFloor", active ? `仓位分地板 ${formatNumber(floor)}，风险上限后 ${formatNumber(overlay.score_after_risk_caps)}` : "强度不足或存在阻断条件");
  setText("contrarianBetaOnly", overlay.beta_core_only === false ? "需复核" : "β only");
  renderMessageList(
    "contrarianDrivers",
    active ? overlay.drivers || [] : overlay.blockers || [],
    active ? "暂无触发依据" : "暂无阻断条件",
  );
}

function buildRiskOverviewFromRecord(record) {
  if (!record) return {};
  const dataQuality = record.data_quality || {};
  const warnings = Array.isArray(dataQuality.warnings) ? dataQuality.warnings : [];
  const missingFields = Array.isArray(dataQuality.missing_fields) ? dataQuality.missing_fields : [];
  const sourcesUsed = Array.isArray(dataQuality.sources_used) ? dataQuality.sources_used : [];
  const riskCaps = Array.isArray(record.risk_caps) ? record.risk_caps : [];
  return {
    status_label: warnings.length || riskCaps.length || record.confidence === "low" ? "需关注" : "正常",
    confidence: {
      value: record.confidence,
      label: confidenceLabel(record.confidence),
      message: "置信度由核心字段、warning 和样本质量决定。",
    },
    data_quality: {
      warning_count: warnings.length,
      warnings,
      missing_field_count: missingFields.length,
      source_count: sourcesUsed.length,
      message: warnings.length ? `存在 ${warnings.length} 条数据质量 warning。` : "暂无数据质量 warning。",
    },
    risk_caps: {
      count: riskCaps.length,
      items: riskCaps,
      message: riskCaps.length ? `已触发 ${riskCaps.length} 项风险上限。` : "未触发风险上限。",
    },
  };
}

function renderMessageList(containerId, items, emptyText, mapper = (item) => String(item)) {
  const container = document.getElementById(containerId);
  if (!container) return;
  const list = Array.isArray(items) ? items : [];
  if (!list.length) {
    container.innerHTML = `<div class="message-item normal">${escapeHtml(emptyText)}</div>`;
    return;
  }
  const visible = list.slice(0, 6);
  const extraCount = list.length - visible.length;
  container.innerHTML = [
    ...visible.map((item) => `<div class="message-item">${escapeHtml(mapper(item))}</div>`),
    extraCount > 0 ? `<div class="message-item muted">另有 ${extraCount} 条未展开</div>` : "",
  ].join("");
}

function riskCapMessage(cap) {
  if (!cap || typeof cap !== "object") return String(cap);
  const severity = cap.severity ? `${severityLabel(cap.severity)} · ` : "";
  const reason = cap.reason ? `${cap.reason} · ` : "";
  return `${severity}${reason}${cap.message || "风险上限已触发"}`;
}

function renderAllocationPolicy() {
  const policy = state.index?.allocation_policy || state.latest?.allocation_policy || null;
  const cards = document.getElementById("allocationCards");
  const chart = document.getElementById("allocationChart");
  const triggerBox = document.getElementById("allocationTriggers");
  if (!policy || !policy.available && !Array.isArray(policy.sleeves)) {
    setText("allocationState", "暂无配置研究");
    renderEmpty(cards, "暂无四仓配置");
    renderEmpty(chart, "暂无配置曲线");
    renderEmpty(triggerBox, "暂无配置依据");
    return;
  }

  const sleeves = Array.isArray(policy.sleeves) ? policy.sleeves : [];
  setText(
    "allocationState",
    `${policy.state || "--"} · 风险资产 ${policy.total_risk_asset_range || officialPositionRange(state.latest)}`,
  );
  cards.innerHTML = sleeves
    .map((sleeve) => {
      const color = allocationColors[sleeve.key] || chartColors.position;
      return `
        <article class="allocation-card">
          <header>
            <span class="allocation-swatch" style="background:${color}"></span>
            <div>
              <strong>${escapeHtml(sleeve.label || sleeve.key || "--")}</strong>
              <small>${escapeHtml(sleeve.asset || "")}</small>
            </div>
          </header>
          <b>${escapeHtml(sleeve.target_range || "--")}</b>
          <p>${escapeHtml(sleeve.role || "")}</p>
          <small>${escapeHtml(sleeve.driver || "")}</small>
        </article>
      `;
    })
    .join("");

  const history = Array.isArray(policy.history) && policy.history.length
    ? policy.history
    : state.records.map((record) => ({
        basis_trade_date: record.basis_trade_date,
        scored_at: record.scored_at,
        sleeves: sleevesToHistoryMap(record.allocation_policy?.sleeves || []),
      }));
  renderStackedAllocationChart(chart, history, sleeves);

  const triggers = Array.isArray(policy.triggers) ? policy.triggers : [];
  const principles = Array.isArray(policy.principles) ? policy.principles : [];
  const lines = [...triggers.slice(0, 4), ...principles.slice(0, 2)];
  triggerBox.innerHTML = lines.length
    ? lines.map((text) => `<div class="allocation-trigger">${escapeHtml(text)}</div>`).join("")
    : `<div class="allocation-trigger muted">暂无配置依据</div>`;
}

function sleevesToHistoryMap(sleeves) {
  if (!Array.isArray(sleeves)) return {};
  return sleeves.reduce((memo, sleeve) => {
    if (sleeve && sleeve.key) {
      memo[sleeve.key] = {
        target_range: sleeve.target_range,
        midpoint: sleeve.midpoint,
      };
    }
    return memo;
  }, {});
}

function renderStackedAllocationChart(container, history, sleeves) {
  if (!container) return;
  container.innerHTML = "";
  const sleeveList = Array.isArray(sleeves) ? sleeves.filter((sleeve) => sleeve?.key) : [];
  const rows = (Array.isArray(history) ? history : [])
    .map((record) => ({
      label: recordLabel(record),
      title: recordPointTitle(record),
      sleeves: record.sleeves || {},
    }))
    .filter((record) => sleeveList.some((sleeve) => numeric(record.sleeves?.[sleeve.key]?.midpoint) !== null));

  if (!rows.length || !sleeveList.length) {
    renderEmpty(container, "暂无配置柱状图");
    return;
  }

  const legend = document.createElement("div");
  legend.className = "chart-legend allocation-stack-legend";
  legend.innerHTML = sleeveList
    .map((sleeve) => {
      const color = allocationColors[sleeve.key] || chartColors.position;
      return `
        <span class="legend-item">
          <span class="legend-swatch stacked" style="background:${color}"></span>
          ${escapeHtml(sleeve.label || sleeve.key)}
        </span>
      `;
    })
    .join("");
  container.appendChild(legend);

  const width = 920;
  const height = 360;
  const margin = { top: 18, right: 28, bottom: 46, left: 48 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const svg = createSvg("svg", {
    class: "chart-svg allocation-stacked-chart",
    viewBox: `0 0 ${width} ${height}`,
    role: "img",
  });
  svg.appendChild(createSvg("title", {}, "四仓配置历史：每根柱子代表一个研究日，柱内四段长度为四仓配置中位数。"));

  for (let i = 0; i <= 4; i += 1) {
    const value = i * 25;
    const y = yPos(value, { min: 0, max: 100 }, margin, plotHeight);
    svg.appendChild(createSvg("line", { class: "grid-line", x1: margin.left, y1: y, x2: width - margin.right, y2: y }));
    svg.appendChild(createSvg("text", { class: "tick-label", x: 8, y: y + 4 }, `${value}%`));
  }

  svg.appendChild(createSvg("line", { class: "axis-line", x1: margin.left, y1: height - margin.bottom, x2: width - margin.right, y2: height - margin.bottom }));
  svg.appendChild(createSvg("line", { class: "axis-line", x1: margin.left, y1: margin.top, x2: margin.left, y2: height - margin.bottom }));

  const step = plotWidth / rows.length;
  const barWidth = clamp(step * 0.62, 12, 44);
  const labelStep = Math.max(1, Math.ceil(rows.length / 8));
  rows.forEach((record, index) => {
    const x = margin.left + step * index + (step - barWidth) / 2;
    let yCursor = height - margin.bottom;
    sleeveList.forEach((sleeve) => {
      const rawValue = numeric(record.sleeves?.[sleeve.key]?.midpoint);
      const value = clamp(rawValue ?? 0, 0, 100);
      if (value <= 0) return;
      const segmentHeight = (value / 100) * plotHeight;
      const y = yCursor - segmentHeight;
      const rect = createSvg("rect", {
        class: "allocation-stack-segment",
        x,
        y,
        width: barWidth,
        height: Math.max(segmentHeight, 1),
        fill: allocationColors[sleeve.key] || chartColors.position,
      });
      rect.appendChild(createSvg("title", {}, `${sleeve.label || sleeve.key} ${record.title}: ${formatNumber(value)}%`));
      svg.appendChild(rect);
      yCursor = y;
    });

    if (index % labelStep === 0 || index === rows.length - 1) {
      svg.appendChild(createSvg("text", { class: "tick-label", x: x + barWidth / 2, y: height - 16, "text-anchor": "middle" }, compactLabel(record.label)));
    }
  });

  container.appendChild(svg);
}

function severityLabel(value) {
  if (value === "high") return "高风险";
  if (value === "medium") return "中风险";
  if (value === "low") return "低风险";
  return value || "风险";
}

function renderPositionMap() {
  const container = document.getElementById("positionMapChart");
  const latest = state.latest;
  if (!latest) {
    setText("positionMapLabel", "--");
    renderEmpty(container, "暂无仓位映射");
    renderPositionBenchmarks(fallbackPositionScoreBands);
    return;
  }

  const policyMap = currentPositionPolicyMap();
  const current = policyMap.current || {};
  const currentScore = numeric(current.market_position_score ?? latest.market_position_score);
  const recommendedRange = current.recommended_equity_position_range || officialPositionRange(latest);
  setText("positionMapLabel", `仓位分 ${formatNumber(currentScore)} · 官方推荐权益 ${recommendedRange}`);
  renderPositionCurve(container, policyMap);
  renderPositionBenchmarks(policyMap.bands || fallbackPositionScoreBands);
}

function renderPositionCurve(container, policyMap) {
  container.innerHTML = "";
  const current = policyMap.current || {};
  const bands = normalizePositionBands(policyMap.bands);
  const currentScore = numeric(current.market_position_score);
  if (currentScore === null) {
    renderEmpty(container, "暂无仓位映射");
    return;
  }

  const width = 920;
  const height = 390;
  const margin = { top: 28, right: 46, bottom: 54, left: 56 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const xRange = { min: numeric(policyMap.score_min) ?? 0, max: numeric(policyMap.score_max) ?? 100 };
  const yRange = { min: numeric(policyMap.position_min) ?? 0, max: numeric(policyMap.position_max) ?? 100 };
  const xForScore = (score) => margin.left + ((clamp(score, xRange.min, xRange.max) - xRange.min) / (xRange.max - xRange.min)) * plotWidth;
  const yForPosition = (position) => yPos(clamp(position, yRange.min, yRange.max), yRange, margin, plotHeight);
  const currentRange = current.recommended_equity_position_range || officialPositionRange(state.latest);
  const currentPosition = positionFromRange(currentRange, currentScore);
  const preCapScoreValue = numeric(current.pre_cap_market_position_score);
  const preCapRange = positionRangeForScore(preCapScoreValue, bands);
  const preCapPosition = preCapScoreValue === null ? null : positionFromRange(preCapRange, preCapScoreValue);
  const riskCaps = Array.isArray(current.risk_caps) ? current.risk_caps : [];

  const svg = createSvg("svg", {
    class: "position-map-svg",
    viewBox: `0 0 ${width} ${height}`,
    role: "img",
  });

  const bandFills = ["#f3ded7", "#f4ead4", "#e8efe9", "#dcebe3", "#d7e5ec", "#eadff0"];
  bands.forEach((band, index) => {
    const x = xForScore(band.score_min);
    const bandWidth = xForScore(band.score_max) - x;
    const rangeMid = positionFromRange(band.position_range, (band.score_min + band.score_max) / 2);
    const y = yForPosition(rangeMid);
    svg.appendChild(createSvg("rect", { x, y: margin.top, width: bandWidth, height: plotHeight, fill: bandFills[index % bandFills.length] }));
    svg.appendChild(
      createSvg(
        "text",
        { class: "position-band-label", x: x + bandWidth / 2, y: margin.top + 18, "text-anchor": "middle" },
        band.label,
      ),
    );
    svg.appendChild(
      createSvg(
        "text",
        { class: "position-band-range-label", x: x + bandWidth / 2, y: margin.top + 36, "text-anchor": "middle" },
        band.position_range,
      ),
    );
    svg.appendChild(createSvg("line", { class: "position-score-band-line", x1: x + 6, y1: y, x2: x + bandWidth - 6, y2: y }));
  });

  for (let value = 0; value <= 100; value += 20) {
    const y = yForPosition(value);
    svg.appendChild(createSvg("line", { class: "grid-line", x1: margin.left, y1: y, x2: width - margin.right, y2: y }));
    svg.appendChild(createSvg("text", { class: "tick-label", x: 8, y: y + 4 }, `${value}%`));
  }

  scoreTicksFromBands(bands).forEach((value) => {
    const x = xForScore(value);
    svg.appendChild(createSvg("line", { class: "position-map-tick", x1: x, y1: margin.top, x2: x, y2: height - margin.bottom }));
    svg.appendChild(createSvg("text", { class: "tick-label", x, y: height - 22, "text-anchor": "middle" }, String(value)));
  });

  svg.appendChild(createSvg("line", { class: "axis-line", x1: margin.left, y1: height - margin.bottom, x2: width - margin.right, y2: height - margin.bottom }));
  svg.appendChild(createSvg("line", { class: "axis-line", x1: margin.left, y1: margin.top, x2: margin.left, y2: height - margin.bottom }));
  svg.appendChild(createSvg("text", { class: "axis-label", x: width / 2, y: height - 6, "text-anchor": "middle" }, policyMap.x_axis || "市场仓位分 / market_position_score"));
  svg.appendChild(createSvg("text", { class: "axis-label", x: 12, y: margin.top - 10 }, policyMap.y_axis || "股票账户推荐权益仓位"));

  svg.appendChild(
    createSvg(
      "text",
      { class: "position-map-note", x: width - margin.right, y: margin.top - 8, "text-anchor": "end" },
      riskCaps.length ? `风险上限已将仓位分从 ${formatNumber(preCapScoreValue)} 压至 ${formatNumber(currentScore)}` : "未触发风险上限，最终仓位分等于扣上限前分",
    ),
  );

  const markerX = xForScore(currentScore);
  const markerY = yForPosition(currentPosition);
  if (preCapScoreValue !== null) {
    const preCapX = xForScore(preCapScoreValue);
    const preCapY = yForPosition(preCapPosition);
    if (Math.abs(preCapScoreValue - currentScore) >= 0.01) {
      svg.appendChild(createSvg("line", { class: "risk-cap-link", x1: preCapX, y1: preCapY, x2: markerX, y2: markerY }));
    }
    svg.appendChild(createSvg("circle", { cx: preCapX, cy: preCapY, r: 5, class: "pre-cap-score-dot" }));
    svg.appendChild(createSvg("text", { class: "pre-cap-score-label", x: preCapX + 8, y: preCapY - 8 }, `扣上限前 ${formatNumber(preCapScoreValue)}`));
  }
  svg.appendChild(createSvg("line", { class: "current-score-line", x1: markerX, y1: margin.top, x2: markerX, y2: height - margin.bottom }));
  svg.appendChild(createSvg("circle", { cx: markerX, cy: markerY, r: 6.5, class: "current-score-dot" }));

  const labelWidth = 270;
  const labelHeight = 86;
  const labelX = clamp(markerX + 14, margin.left + 4, width - margin.right - labelWidth);
  const labelY = clamp(markerY - labelHeight - 12, margin.top + 10, height - margin.bottom - labelHeight - 8);
  svg.appendChild(createSvg("rect", { class: "current-score-label-box", x: labelX, y: labelY, width: labelWidth, height: labelHeight, rx: 6 }));
  svg.appendChild(createSvg("text", { class: "current-score-label strong", x: labelX + 12, y: labelY + 22 }, `当前仓位分 ${formatNumber(currentScore)}`));
  svg.appendChild(createSvg("text", { class: "current-score-label", x: labelX + 12, y: labelY + 42 }, `官方推荐权益 ${currentRange}`));
  svg.appendChild(createSvg("text", { class: "current-score-label muted", x: labelX + 12, y: labelY + 61 }, `扣上限前 ${formatNumber(preCapScoreValue)} · 风险上限 ${riskCaps.length} 项`));
  svg.appendChild(createSvg("text", { class: "current-score-label muted", x: labelX + 12, y: labelY + 78 }, current.market_regime || state.latest?.market_regime || "--"));
  svg.appendChild(createSvg("title", {}, `当前股票账户仓位分 ${formatNumber(currentScore)}，官方推荐权益 ${currentRange}，风险上限 ${riskCaps.length} 项`));

  container.appendChild(svg);
}

function renderPositionBenchmarks(bands) {
  const container = document.getElementById("positionBenchmarks");
  if (!container) return;
  container.innerHTML = normalizePositionBands(bands)
    .map(
      (item) => `
        <article class="position-benchmark-card">
          <span>${escapeHtml(item.label)}</span>
          <strong>净分 ${escapeHtml(scoreRangeText(item))} · 权益 ${escapeHtml(item.position_range)}</strong>
          <small>${escapeHtml(item.description || "")}</small>
        </article>
      `,
    )
    .join("");
}

function renderMarketCycleReference() {
  const container = document.getElementById("marketCycleChart");
  const reference = currentMarketCycleReference();
  const waves = normalizeMarketCycleWaves(reference.waves);
  if (!container) return;
  if (!waves.length) {
    setText("cycleMapLabel", "--");
    renderEmpty(container, "暂无周期示意");
    renderMarketCycleCards([]);
    return;
  }

  setText("cycleMapLabel", reference.is_prediction === false ? "示意图 · 不预测当前浪位" : reference.basis || "周期评分示意");
  renderMarketCycleChart(container, { ...reference, waves });
  renderMarketCycleProfile(reference.current_profile);
  renderMarketCycleCards(waves);
}

function currentMarketCycleReference() {
  const reference = state.index?.market_cycle_reference;
  if (reference && Array.isArray(reference.waves) && reference.waves.length) return reference;
  return fallbackMarketCycleReference;
}

function normalizeMarketCycleWaves(waves) {
  const source = Array.isArray(waves) && waves.length ? waves : fallbackMarketCycleReference.waves;
  return source
    .map((wave, index) => ({
      wave: String(wave.wave ?? index + 1),
      phase: wave.phase === "corrective" ? "corrective" : "impulse",
      label: wave.label || "",
      price_level: numeric(wave.price_level) ?? 50,
      opportunity_score_range: wave.opportunity_score_range || "--",
      position_score_range: wave.position_score_range || "--",
      equity_position_range: wave.equity_position_range || "--",
      note: wave.note || "",
    }))
    .slice(0, 8);
}

function renderMarketCycleChart(container, reference) {
  container.innerHTML = "";
  const waves = reference.waves;
  const width = 980;
  const height = 520;
  const margin = { top: 42, right: 34, bottom: 48, left: 42 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const xForIndex = (index) => margin.left + (index / Math.max(waves.length - 1, 1)) * plotWidth;
  const yForPrice = (priceLevel) => yPos(clamp(priceLevel, 0, 100), { min: 0, max: 100 }, margin, plotHeight);
  const points = waves.map((wave, index) => ({
    ...wave,
    x: xForIndex(index),
    y: yForPrice(wave.price_level),
  }));

  const svg = createSvg("svg", {
    class: "market-cycle-svg",
    viewBox: `0 0 ${width} ${height}`,
    role: "img",
  });
  svg.appendChild(createSvg("title", {}, "市场八浪周期示意：每个位置标注市场机会分和最终仓位分的典型区间。"));

  [
    { y: 74, label: "高位风险", className: "risk" },
    { y: 48, label: "健康趋势", className: "trend" },
    { y: 22, label: "低位观察", className: "base" },
  ].forEach((zone) => {
    const y = yForPrice(zone.y);
    svg.appendChild(createSvg("line", { class: `cycle-zone-line ${zone.className}`, x1: margin.left, y1: y, x2: width - margin.right, y2: y }));
    svg.appendChild(createSvg("text", { class: "cycle-zone-label", x: margin.left + 6, y: y - 8 }, zone.label));
  });

  const impulsePoints = points.filter((pointItem) => pointItem.phase !== "corrective");
  const correctivePoints = points.filter((pointItem) => pointItem.phase === "corrective");
  if (impulsePoints.length > 1) {
    svg.appendChild(createSvg("path", { class: "cycle-path impulse", d: smoothPath(impulsePoints) }));
  }
  if (correctivePoints.length) {
    const correctivePathPoints = [points[4], ...correctivePoints].filter(Boolean);
    svg.appendChild(createSvg("path", { class: "cycle-path corrective", d: smoothPath(correctivePathPoints) }));
  }
  renderNestedWave(svg, points);

  svg.appendChild(createSvg("line", { class: "axis-line", x1: margin.left, y1: height - margin.bottom, x2: width - margin.right, y2: height - margin.bottom }));
  svg.appendChild(createSvg("text", { class: "axis-label", x: width / 2, y: height - 12, "text-anchor": "middle" }, "1-5 推动浪上升，a-b-c 调整浪下降"));

  points.forEach((pointItem, index) => {
    const isCorrective = pointItem.phase === "corrective";
    const markerClass = isCorrective ? "cycle-node corrective" : "cycle-node impulse";
    svg.appendChild(createSvg("circle", { class: markerClass, cx: pointItem.x, cy: pointItem.y, r: 6 }));
    svg.appendChild(
      createSvg(
        "text",
        { class: isCorrective ? "wave-label corrective" : "wave-label", x: pointItem.x, y: pointItem.y - 12, "text-anchor": "middle" },
        `${pointItem.wave}浪`,
      ),
    );
    appendCycleCallout(svg, pointItem, index, width, height, margin);
  });

  container.appendChild(svg);
}

function renderNestedWave(svg, points) {
  const second = points[1];
  const third = points[2];
  if (!second || !third) return;
  const nested = [0.08, 0.24, 0.42, 0.62, 0.82].map((ratio, index) => {
    const baseX = second.x + (third.x - second.x) * ratio;
    const baseY = second.y + (third.y - second.y) * ratio;
    const offset = index % 2 === 0 ? 14 : -16;
    return { x: baseX, y: baseY + offset };
  });
  svg.appendChild(createSvg("path", { class: "cycle-subwave", d: smoothPath(nested) }));
  svg.appendChild(createSvg("text", { class: "cycle-subwave-label", x: nested[2].x + 12, y: nested[2].y - 18 }, "浪中有浪"));
}

function appendCycleCallout(svg, pointItem, index, width, height, margin) {
  const boxWidth = 132;
  const boxHeight = 66;
  const offsets = [
    { dx: -26, dy: -96 },
    { dx: -18, dy: 22 },
    { dx: -56, dy: -100 },
    { dx: -58, dy: 26 },
    { dx: -82, dy: 24 },
    { dx: -76, dy: 28 },
    { dx: -90, dy: -96 },
    { dx: -116, dy: 20 },
  ];
  const offset = offsets[index] || { dx: 10, dy: -84 };
  const x = clamp(pointItem.x + offset.dx, margin.left + 4, width - margin.right - boxWidth);
  const y = clamp(pointItem.y + offset.dy, margin.top + 4, height - margin.bottom - boxHeight - 4);
  const isCorrective = pointItem.phase === "corrective";
  svg.appendChild(createSvg("rect", { class: isCorrective ? "cycle-callout-box corrective" : "cycle-callout-box", x, y, width: boxWidth, height: boxHeight, rx: 6 }));
  svg.appendChild(createSvg("text", { class: "cycle-callout-title", x: x + 10, y: y + 18 }, `${pointItem.wave}浪 · ${pointItem.label}`));
  svg.appendChild(createSvg("text", { class: "cycle-callout-text opportunity", x: x + 10, y: y + 38 }, `机会 ${pointItem.opportunity_score_range}`));
  svg.appendChild(createSvg("text", { class: "cycle-callout-text position", x: x + 10, y: y + 56 }, `仓位 ${pointItem.position_score_range}`));
}

function smoothPath(points) {
  if (!points.length) return "";
  if (points.length === 1) return `M ${points[0].x} ${points[0].y}`;
  let d = `M ${points[0].x} ${points[0].y}`;
  for (let index = 0; index < points.length - 1; index += 1) {
    const p0 = points[index - 1] || points[index];
    const p1 = points[index];
    const p2 = points[index + 1];
    const p3 = points[index + 2] || p2;
    const cp1x = p1.x + (p2.x - p0.x) / 6;
    const cp1y = p1.y + (p2.y - p0.y) / 6;
    const cp2x = p2.x - (p3.x - p1.x) / 6;
    const cp2y = p2.y - (p3.y - p1.y) / 6;
    d += ` C ${cp1x} ${cp1y}, ${cp2x} ${cp2y}, ${p2.x} ${p2.y}`;
  }
  return d;
}

function renderMarketCycleCards(waves) {
  const container = document.getElementById("marketCycleCards");
  if (!container) return;
  if (!waves.length) {
    renderEmpty(container, "暂无周期示意");
    return;
  }
  container.innerHTML = waves
    .map(
      (wave) => `
        <article class="market-cycle-card ${escapeHtml(wave.phase)}">
          <span>${escapeHtml(wave.wave)}浪 · ${escapeHtml(wave.label)}</span>
          <strong>机会 ${escapeHtml(wave.opportunity_score_range)} · 仓位 ${escapeHtml(wave.position_score_range)}</strong>
          <small>股票账户 ${escapeHtml(wave.equity_position_range)}。${escapeHtml(wave.note)}</small>
        </article>
      `,
    )
    .join("");
}

function renderMarketCycleProfile(profile) {
  const container = document.getElementById("marketCycleProfile");
  if (!container) return;
  const item = profile && typeof profile === "object" ? profile : {};
  if (!item.available) {
    container.innerHTML = `
      <article class="market-cycle-profile-card muted">
        <span>当前评分特征</span>
        <strong>暂无评分特征</strong>
        <small>有最新评分记录后，这里会显示当前更接近哪类周期风险特征。</small>
      </article>
    `;
    return;
  }
  const observations = Array.isArray(item.observations) ? item.observations.slice(0, 4) : [];
  const waves = Array.isArray(item.reference_waves) ? item.reference_waves.map((wave) => `${wave}浪`).join(" / ") : "--";
  container.innerHTML = `
    <article class="market-cycle-profile-card">
      <span>当前评分特征 · ${escapeHtml(item.note || "不判定当前浪位")}</span>
      <strong>${escapeHtml(item.label || "--")}</strong>
      <div class="cycle-profile-meta">
        <b>${escapeHtml(item.score_line || "--")}</b>
        <b>参照 ${escapeHtml(waves || "--")}</b>
      </div>
      <p>${escapeHtml(item.message || "")}</p>
      <small>${escapeHtml(item.stance || "")}</small>
      <ul>
        ${observations.map((text) => `<li>${escapeHtml(text)}</li>`).join("")}
      </ul>
    </article>
  `;
}

function renderApiCatalog() {
  const catalog = state.index?.api_catalog || {};
  const total = numeric(catalog.total_endpoints);
  setText("apiCatalogTotal", total === null ? "--" : `${formatNumber(total, 0)} 个公开接口`);

  const recommendedContainer = document.getElementById("apiRecommendedEntrypoints");
  const groupsContainer = document.getElementById("apiCatalogGroups");
  const safetyContainer = document.getElementById("apiSafetyNotes");
  if (!recommendedContainer || !groupsContainer || !safetyContainer) return;

  const recommended = Array.isArray(catalog.recommended_entrypoints) ? catalog.recommended_entrypoints : [];
  recommendedContainer.innerHTML = recommended.length
    ? recommended
        .slice(0, 6)
        .map(
          (item) => `
            <a class="api-chip" href="${escapeHtml(apiPathOnly(item.path || ""))}" target="_blank" rel="noreferrer">
              <b>${escapeHtml(item.method || "GET")}</b>
              <span>${escapeHtml(item.path || "--")}</span>
            </a>
          `,
        )
        .join("")
    : `<span class="api-chip muted">暂无推荐入口</span>`;

  const groups = Array.isArray(catalog.groups) ? catalog.groups : [];
  groupsContainer.innerHTML = groups.length
    ? groups
        .map(
          (group) => `
            <span class="api-chip">
              <b>${escapeHtml(group.label || group.key || "--")}</b>
              <span>${formatNumber(group.endpoint_count, 0)} 个</span>
            </span>
          `,
        )
        .join("")
    : `<span class="api-chip muted">暂无分组</span>`;

  const boundaries = Array.isArray(catalog.safety?.boundaries) ? catalog.safety.boundaries : [];
  safetyContainer.innerHTML = boundaries.length
    ? boundaries.slice(0, 5).map((text) => `<li>${escapeHtml(text)}</li>`).join("")
    : `<li>暂无安全边界说明</li>`;
}

function apiPathOnly(path) {
  const value = String(path || "");
  return value.includes("?") ? value.slice(0, value.indexOf("?")) : value || "/api";
}

function currentPositionPolicyMap() {
  const map = state.index?.position_policy_map;
  if (map && Array.isArray(map.bands) && map.bands.length) return map;
  const latest = state.latest || {};
  return {
    title: "股票账户净分-推荐权益仓位映射",
    account_scope: "stock_account",
    position_policy_version: latest.position_policy_version || "stock_account_position_policy_v2",
    x_axis: "市场仓位分 / market_position_score",
    y_axis: "股票账户推荐权益仓位",
    score_min: 0,
    score_max: 100,
    position_min: 0,
    position_max: 100,
    bands: fallbackPositionScoreBands,
    current: {
      market_position_score: latest.market_position_score,
      pre_cap_market_position_score: preCapScore(latest),
      recommended_equity_position_range: officialPositionRange(latest),
      risk_caps: latest.risk_caps || [],
      market_regime: latest.market_regime,
    },
  };
}

function normalizePositionBands(bands) {
  const source = Array.isArray(bands) && bands.length ? bands : fallbackPositionScoreBands;
  return source
    .map((band) => ({
      score_min: numeric(band.score_min),
      score_max: numeric(band.score_max),
      position_range: band.position_range || "--",
      label: band.label || "",
      description: band.description || "",
    }))
    .filter((band) => band.score_min !== null && band.score_max !== null && band.score_max > band.score_min);
}

function scoreTicksFromBands(bands) {
  return [...new Set([0, 100, ...bands.flatMap((band) => [band.score_min, band.score_max])])]
    .map(numeric)
    .filter((value) => value !== null)
    .sort((a, b) => a - b);
}

function scoreRangeText(band) {
  return `${formatNumber(band.score_min, 0)}-${formatNumber(band.score_max, 0)}`;
}

function positionRangeForScore(score, bands) {
  const scoreNumber = numeric(score);
  if (scoreNumber === null) return "--";
  const band = normalizePositionBands(bands).find((item, index, list) => {
    const isLast = index === list.length - 1;
    return scoreNumber >= item.score_min && (scoreNumber < item.score_max || (isLast && scoreNumber <= item.score_max));
  });
  return band?.position_range || fallbackPositionRangeFromScore(scoreNumber);
}

function positionFromRange(rangeText, score) {
  const parsedRange = parsePercentRange(rangeText);
  if (parsedRange) return (parsedRange[0] + parsedRange[1]) / 2;
  return fallbackPositionFromScore(score);
}

function parsePercentRange(rangeText) {
  if (!rangeText || !String(rangeText).includes("-")) return null;
  const [left, right] = String(rangeText).replaceAll("%", "").split("-");
  const leftNumber = numeric(left);
  const rightNumber = numeric(right);
  if (leftNumber === null || rightNumber === null) return null;
  return [leftNumber, rightNumber];
}

function fallbackPositionFromScore(score) {
  const reference = [
    { score: 0, position: 10 },
    { score: 20, position: 20 },
    { score: 35, position: 40 },
    { score: 50, position: 60 },
    { score: 65, position: 75 },
    { score: 80, position: 90 },
    { score: 100, position: 100 },
  ];
  const safeScore = clamp(score, 0, 100);
  for (let index = 0; index < reference.length - 1; index += 1) {
    const left = reference[index];
    const right = reference[index + 1];
    if (safeScore >= left.score && safeScore <= right.score) {
      const ratio = (safeScore - left.score) / (right.score - left.score || 1);
      return left.position + ratio * (right.position - left.position);
    }
  }
  return reference[reference.length - 1].position;
}

function fallbackPositionRangeFromScore(score) {
  const band = fallbackPositionScoreBands.find((item, index, list) => {
    const isLast = index === list.length - 1;
    return score >= item.score_min && (score < item.score_max || (isLast && score <= item.score_max));
  });
  return band?.position_range || "--";
}

function renderOverviewChart() {
  const records = state.records;
  const container = document.getElementById("overviewChart");
  if (!records.length) {
    renderEmpty(container, "暂无评分历史");
    return;
  }

  const labels = records.map(recordLabel);
  const titles = records.map(recordPointTitle);
  renderLineChart(
    container,
    [
      {
        name: "股票账户仓位分",
        color: chartColors.position,
        axis: "left",
        weight: "bold",
        data: records.map((record, index) => point(labels[index], record.market_position_score, titles[index])),
      },
      {
        name: "扣上限前分",
        color: chartColors.preCap,
        axis: "left",
        data: records.map((record, index) => point(labels[index], preCapScore(record), titles[index])),
      },
      {
        name: "市场机会分",
        color: chartColors.opportunity,
        axis: "left",
        data: records.map((record, index) => point(labels[index], record.market_opportunity_score, titles[index])),
      },
      {
        name: "拥挤惩罚",
        color: chartColors.penalty,
        axis: "left",
        data: records.map((record, index) => point(labels[index], record.crowding_penalty, titles[index])),
      },
      {
        name: "上证指数",
        color: chartColors.shanghai,
        axis: "right",
        style: "background-dashed",
        points: false,
        data: records.map((record, index) => point(labels[index], record.shanghai_composite, titles[index])),
      },
    ],
    {
      leftMin: 0,
      leftMax: 100,
      rightLabel: "上证",
      backgroundFirst: true,
    },
  );
}

function renderModuleSelect() {
  const select = document.getElementById("moduleSelect");
  const latestModules = state.latest?.modules || {};
  select.innerHTML = "";
  moduleOrder.forEach((key) => {
    const module = latestModules[key];
    if (!module) return;
    const option = document.createElement("option");
    option.value = key;
    option.textContent = module.label;
    if (key === state.selectedModule) option.selected = true;
    select.appendChild(option);
  });
  if (!latestModules[state.selectedModule]) {
    state.selectedModule = select.value || "index_trend";
  }
}

function renderModuleGrid() {
  const grid = document.getElementById("moduleGrid");
  const latest = state.latest;
  if (!latest) {
    renderEmpty(grid, "暂无子项分");
    return;
  }

  grid.innerHTML = "";
  moduleOrder.forEach((key) => {
    const module = latest.modules?.[key];
    if (!module) return;
    const card = document.createElement("article");
    card.className = `module-card${key === state.selectedModule ? " active" : ""}`;
    card.tabIndex = 0;
    card.dataset.module = key;
    card.innerHTML = `
      <div class="module-title">
        <h3>${escapeHtml(module.label)}</h3>
        <strong>${formatNumber(module.score)} / ${formatNumber(module.weight)}</strong>
      </div>
      <p>${escapeHtml(module.summary || "")}</p>
      <div class="sparkline"></div>
    `;
    card.addEventListener("click", () => selectModule(key));
    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        selectModule(key);
      }
    });
    grid.appendChild(card);
    const values = state.records.map((record) => numeric(record.modules?.[key]?.score_pct));
    renderSparkline(card.querySelector(".sparkline"), values, moduleColors[key] || chartColors.position, 0, 100);
  });
}

function selectModule(key) {
  state.selectedModule = key;
  const select = document.getElementById("moduleSelect");
  select.value = key;
  renderModuleGrid();
  renderModuleDetails();
}

function renderModuleDetails() {
  const latest = state.latest;
  const key = state.selectedModule;
  const module = latest?.modules?.[key];
  if (!module) {
    renderEmpty(document.getElementById("metricCharts"), "暂无依据曲线");
    renderEmpty(document.getElementById("evidenceTable"), "暂无依据明细");
    return;
  }

  setText("selectedModuleLabel", `${module.label} · ${formatNumber(module.score_pct)}%`);
  setText("latestRun", latest.run_id || "--");
  renderMetricCharts(key, module);
  renderEvidence(module);
}

function renderMetricCharts(key, module) {
  const container = document.getElementById("metricCharts");
  container.innerHTML = "";
  const metrics = module.metrics || {};
  Object.entries(metrics).forEach(([metricKey, meta]) => {
    const card = document.createElement("article");
    card.className = "metric-card";
    card.innerHTML = `
      <header>
        <h3>${escapeHtml(meta.label || metricKey)}</h3>
        <strong>${escapeHtml(valueWithUnit(meta.value, meta.unit))}</strong>
      </header>
      <div class="metric-chart"></div>
    `;
    container.appendChild(card);
    const labels = state.records.map(recordLabel);
    const titles = state.records.map(recordPointTitle);
    const values = state.records.map((record) => numeric(record.modules?.[key]?.metrics?.[metricKey]?.value));
    renderLineChart(
      card.querySelector(".metric-chart"),
      [
        {
          name: meta.label || metricKey,
          color: moduleColors[key] || chartColors.position,
          axis: "left",
          data: values.map((value, index) => point(labels[index], value, titles[index])),
        },
      ],
      { compact: true, legend: false },
    );
  });

  if (!container.children.length) {
    renderEmpty(container, "暂无依据曲线");
  }
}

function renderEvidence(module) {
  const container = document.getElementById("evidenceTable");
  const rows = module.evidence || [];
  if (!rows.length) {
    renderEmpty(container, "暂无依据明细");
    return;
  }
  container.innerHTML = rows
    .map(
      (item) => `
        <div class="evidence-row">
          <div>
            <strong>${escapeHtml(item.label || "")}</strong>
            <span>${escapeHtml(valueWithUnit(item.value, item.unit))}</span>
          </div>
          <div>
            <strong>${formatNumber(item.score)}</strong>
            <span>满分 ${formatNumber(item.max_score)}</span>
          </div>
          <div>
            <strong>${formatNumber(scorePercent(item.score, item.max_score))}%</strong>
            <span>贡献率</span>
          </div>
          <small>${escapeHtml(item.note || "")}</small>
        </div>
      `,
    )
    .join("");
}

function renderHistoryTable() {
  const tbody = document.getElementById("historyRows");
  if (!state.records.length) {
    tbody.innerHTML = `<tr><td colspan="10" class="empty-state">暂无评分历史</td></tr>`;
    return;
  }
  tbody.innerHTML = [...state.records]
    .reverse()
    .map(
      (record) => `
        <tr>
          <td>${escapeHtml(formatDateTime(record.scored_at))}</td>
          <td>${escapeHtml(record.basis_trade_date || "--")}</td>
          <td class="score-up">${formatNumber(record.market_opportunity_score)}</td>
          <td class="score-risk">${formatNumber(record.crowding_penalty)}</td>
          <td>${formatNumber(preCapScore(record))}</td>
          <td class="score-up">${formatNumber(record.market_position_score)}</td>
          <td>${escapeHtml(officialPositionRange(record))}</td>
          <td>${formatNumber(record.shanghai_composite)}</td>
          <td>${escapeHtml(record.position_policy_version || "--")}</td>
          <td>${escapeHtml(record.market_regime || "--")}</td>
        </tr>
      `,
    )
    .join("");
}

function renderLineChart(container, series, options = {}) {
  container.innerHTML = "";
  const activeSeries = series
    .map((item) => ({
      ...item,
      data: (item.data || []).filter((pointItem) => numeric(pointItem.value) !== null),
    }))
    .filter((item) => item.data.length);

  if (!activeSeries.length) {
    renderEmpty(container, "暂无曲线数据");
    return;
  }

  if (options.legend !== false) {
    const legend = document.createElement("div");
    legend.className = "chart-legend";
    legend.innerHTML = activeSeries
      .map(
        (item) => `
          <span class="legend-item">
            <span class="legend-swatch" style="background:${item.color}"></span>
            ${escapeHtml(item.name)}
          </span>
        `,
      )
      .join("");
    container.appendChild(legend);
  }

  const width = options.compact ? 360 : 820;
  const height = options.compact ? 180 : 360;
  const margin = options.compact
    ? { top: 12, right: 18, bottom: 28, left: 34 }
    : { top: 18, right: 58, bottom: 42, left: 48 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;

  const leftValues = activeSeries
    .filter((item) => item.axis !== "right")
    .flatMap((item) => item.data.map((pointItem) => numeric(pointItem.value)))
    .filter((value) => value !== null);
  const rightValues = activeSeries
    .filter((item) => item.axis === "right")
    .flatMap((item) => item.data.map((pointItem) => numeric(pointItem.value)))
    .filter((value) => value !== null);

  const leftRange = rangeFor(leftValues, options.leftMin, options.leftMax);
  const rightRange = rangeFor(rightValues);
  const labelCount = Math.max(...activeSeries.map((item) => item.data.length));
  const labels = widestLabels(activeSeries);

  const svg = createSvg("svg", {
    class: options.compact ? "chart-svg compact" : "chart-svg",
    viewBox: `0 0 ${width} ${height}`,
    role: "img",
  });

  for (let i = 0; i <= 4; i += 1) {
    const value = leftRange.min + ((leftRange.max - leftRange.min) * i) / 4;
    const y = yPos(value, leftRange, margin, plotHeight);
    svg.appendChild(createSvg("line", { class: "grid-line", x1: margin.left, y1: y, x2: width - margin.right, y2: y }));
    if (!options.compact) {
      svg.appendChild(createSvg("text", { class: "tick-label", x: 8, y: y + 4 }, formatNumber(value, 0)));
    }
  }

  if (rightValues.length && !options.compact) {
    svg.appendChild(
      createSvg("text", { class: "tick-label", x: width - margin.right + 8, y: margin.top + 4 }, formatNumber(rightRange.max, 0)),
    );
    svg.appendChild(
      createSvg("text", { class: "tick-label", x: width - margin.right + 8, y: height - margin.bottom + 4 }, formatNumber(rightRange.min, 0)),
    );
    if (options.rightLabel) {
      svg.appendChild(createSvg("text", { class: "axis-label", x: width - 34, y: margin.top + 20 }, options.rightLabel));
    }
  }

  svg.appendChild(
    createSvg("line", {
      class: "axis-line",
      x1: margin.left,
      y1: height - margin.bottom,
      x2: width - margin.right,
      y2: height - margin.bottom,
    }),
  );
  svg.appendChild(
    createSvg("line", {
      class: "axis-line",
      x1: margin.left,
      y1: margin.top,
      x2: margin.left,
      y2: height - margin.bottom,
    }),
  );

  const labelStep = Math.max(1, Math.ceil(labelCount / (options.compact ? 3 : 8)));
  labels.forEach((label, index) => {
    if (index % labelStep !== 0 && index !== labels.length - 1) return;
    const x = xPos(index, labels.length, margin, plotWidth);
    svg.appendChild(
      createSvg(
        "text",
        {
          class: "tick-label",
          x,
          y: height - (options.compact ? 8 : 16),
          "text-anchor": "middle",
        },
        compactLabel(label),
      ),
    );
  });

  const drawSeries = options.backgroundFirst
    ? [
        ...activeSeries.filter((item) => item.style === "background-dashed"),
        ...activeSeries.filter((item) => item.style !== "background-dashed"),
      ]
    : activeSeries;

  drawSeries.forEach((item) => {
    const range = item.axis === "right" ? rightRange : leftRange;
    const points = item.data.map((pointItem, index) => {
      const value = numeric(pointItem.value);
      return {
        x: xPos(index, item.data.length, margin, plotWidth),
        y: yPos(value, range, margin, plotHeight),
        value,
        label: pointItem.label,
        titleLabel: pointItem.titleLabel || pointItem.label,
      };
    });

    if (points.length > 1) {
      const d = points.map((itemPoint, index) => `${index === 0 ? "M" : "L"} ${itemPoint.x} ${itemPoint.y}`).join(" ");
      const isBackground = item.style === "background-dashed";
      const strokeWidth = item.weight === "bold" ? (options.compact ? 3.2 : 4.8) : (options.compact ? 2.2 : 2.8);
      svg.appendChild(
        createSvg("path", {
          d,
          fill: "none",
          stroke: item.color,
          "stroke-width": isBackground ? 2 : strokeWidth,
          "stroke-dasharray": isBackground ? "7 8" : null,
          "stroke-opacity": isBackground ? 0.55 : 1,
          "stroke-linecap": "round",
          "stroke-linejoin": "round",
        }),
      );
    }

    if (item.points === false) return;
    points.forEach((itemPoint) => {
      const circle = createSvg("circle", {
        cx: itemPoint.x,
        cy: itemPoint.y,
        r: item.weight === "bold" ? (options.compact ? 4 : 5.4) : (options.compact ? 3.2 : 4),
        fill: item.color,
      });
      circle.appendChild(createSvg("title", {}, `${item.name} ${itemPoint.titleLabel}: ${formatNumber(itemPoint.value)}`));
      svg.appendChild(circle);
    });
  });

  container.appendChild(svg);
}

function renderSparkline(container, values, color, minValue = null, maxValue = null) {
  container.innerHTML = "";
  const clean = values.map(numeric).filter((value) => value !== null);
  if (!clean.length) {
    return;
  }
  const width = 220;
  const height = 58;
  const margin = 6;
  const range = rangeFor(clean, minValue, maxValue);
  const svg = createSvg("svg", { viewBox: `0 0 ${width} ${height}` });
  svg.appendChild(createSvg("line", { x1: margin, y1: height - margin, x2: width - margin, y2: height - margin, stroke: "#e6ece9" }));
  const points = values.map(numeric).map((value, index) => {
    if (value === null) return null;
    const x = values.length === 1 ? width / 2 : margin + (index / (values.length - 1)) * (width - margin * 2);
    const y = height - margin - ((value - range.min) / (range.max - range.min || 1)) * (height - margin * 2);
    return { x, y, value };
  }).filter(Boolean);
  if (points.length > 1) {
    svg.appendChild(
      createSvg("path", {
        d: points.map((pointItem, index) => `${index === 0 ? "M" : "L"} ${pointItem.x} ${pointItem.y}`).join(" "),
        fill: "none",
        stroke: color,
        "stroke-width": 2.5,
        "stroke-linecap": "round",
      }),
    );
  }
  points.forEach((pointItem) => {
    svg.appendChild(createSvg("circle", { cx: pointItem.x, cy: pointItem.y, r: 3.2, fill: color }));
  });
  container.appendChild(svg);
}

function createSvg(tag, attrs = {}, text = null) {
  const node = document.createElementNS(svgNs, tag);
  Object.entries(attrs).forEach(([key, value]) => {
    if (value === null || value === undefined) return;
    node.setAttribute(key, value);
  });
  if (text !== null) node.textContent = text;
  return node;
}

function rangeFor(values, fixedMin = null, fixedMax = null) {
  const clean = values.map(numeric).filter((value) => value !== null);
  if (fixedMin !== null && fixedMax !== null) {
    return { min: fixedMin, max: fixedMax };
  }
  if (!clean.length) {
    return { min: 0, max: 1 };
  }
  let min = fixedMin !== null ? fixedMin : Math.min(...clean);
  let max = fixedMax !== null ? fixedMax : Math.max(...clean);
  if (min === max) {
    const pad = Math.max(Math.abs(min) * 0.08, 1);
    min -= pad;
    max += pad;
  } else {
    const pad = (max - min) * 0.08;
    min = fixedMin !== null ? fixedMin : min - pad;
    max = fixedMax !== null ? fixedMax : max + pad;
  }
  return { min, max };
}

function clamp(value, minValue, maxValue) {
  return Math.max(minValue, Math.min(maxValue, value));
}

function xPos(index, count, margin, plotWidth) {
  if (count <= 1) return margin.left + plotWidth / 2;
  return margin.left + (index / (count - 1)) * plotWidth;
}

function yPos(value, range, margin, plotHeight) {
  const ratio = (value - range.min) / (range.max - range.min || 1);
  return margin.top + (1 - ratio) * plotHeight;
}

function widestLabels(series) {
  const longest = [...series].sort((a, b) => b.data.length - a.data.length)[0];
  return (longest?.data || []).map((pointItem, index) => pointItem.label || String(index + 1));
}

function point(label, value, titleLabel = null) {
  return { label, titleLabel: titleLabel || label, value: numeric(value) };
}

function officialPositionRange(record) {
  return record?.recommended_equity_position_range || record?.base_equity_position_range || record?.equity_position_range || "--";
}

function preCapScore(record) {
  return record?.pre_cap_market_position_score ?? record?.base_market_position_score ?? record?.market_position_score;
}

function recordLabel(record) {
  if (record.basis_trade_date) return record.basis_trade_date;
  if (record.scored_at) return String(record.scored_at).slice(0, 10);
  return "--";
}

function recordPointTitle(record) {
  const basis = record.basis_trade_date || "--";
  const scored = record.scored_at ? formatDateTime(record.scored_at) : "--";
  return `基准日 ${basis} · 生成 ${scored}`;
}

function compactLabel(label) {
  return String(label).replace(/^(\d{4})-/, "").replace(" ", "\n");
}

function setText(id, value) {
  const node = document.getElementById(id);
  if (node) node.textContent = value;
}

function setStatus(value) {
  setText("statusLine", value);
}

function setMeter(id, value, max) {
  const node = document.getElementById(id);
  if (!node) return;
  const width = Math.max(0, Math.min(100, (numeric(value) || 0) / max * 100));
  node.style.width = `${width}%`;
}

function renderEmpty(container, text) {
  container.innerHTML = `<div class="empty-state">${escapeHtml(text)}</div>`;
}

function numeric(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function formatNumber(value, digits = 2) {
  const number = numeric(value);
  if (number === null) return "--";
  return number.toLocaleString("zh-CN", {
    minimumFractionDigits: Number.isInteger(number) || digits === 0 ? 0 : digits,
    maximumFractionDigits: digits,
  });
}

function formatDateTime(value) {
  if (!value) return "--";
  return String(value).replace("T", " ").slice(0, 19);
}

function valueWithUnit(value, unit) {
  if (value === "" || value === null || value === undefined) return "--";
  const number = numeric(value);
  const display = number === null ? String(value) : formatNumber(number);
  return `${display}${unit ? ` ${unit}` : ""}`;
}

function scorePercent(score, maxScore) {
  const scoreNumber = numeric(score);
  const maxNumber = numeric(maxScore);
  if (scoreNumber === null || !maxNumber) return null;
  return Math.max(0, Math.min(100, (scoreNumber / maxNumber) * 100));
}

function confidenceLabel(value) {
  if (value === "high") return "高";
  if (value === "medium") return "中";
  if (value === "low") return "低";
  return value || "--";
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
