const svgNs = "http://www.w3.org/2000/svg";
const colors = {
  lower_bound: "#9aa8a3",
  midpoint: "#047d73",
  upper_bound: "#2c68a0",
  csi300: "#bf3d2b",
  csi500: "#b7791f",
  shanghai: "#6b7280",
};
const labels = {
  lower_bound: "区间下限",
  midpoint: "区间中位数",
  upper_bound: "区间上限",
  csi300: "沪深300",
  csi500: "中证500",
  shanghai: "上证指数",
};

let payload = null;

document.addEventListener("DOMContentLoaded", async () => {
  try {
    payload = await fetchJson("/api/cycle-engine/backtest");
    renderAll();
  } catch (error) {
    document.getElementById("auditStatus").textContent = `读取失败：${error.message}`;
  }
});

async function fetchJson(url) {
  const response = await fetch(url);
  const body = await response.json();
  if (!response.ok || body.available === false) throw new Error(body.error || response.statusText);
  return body;
}

function renderAll() {
  const sample = payload.sample || {};
  const summary = payload.summary || {};
  const metrics = payload.metrics || {};
  const midpoint = metrics.midpoint || {};
  const audit = payload.audit || {};
  setText("sampleRange", `${sample.start_month || "--"} 至 ${sample.end_month || "--"}`);
  setText("costBps", `${payload.methodology?.cost_bps ?? "--"} bp 单边`);
  setText("auditStatus", audit.passed ? "审计通过 · 无未来状态依赖" : "审计存在问题");
  setText("strategyReturn", formatPct(midpoint.cumulative_return_pct));
  setText("strategyAnnualized", `年化 ${formatPct(midpoint.annualized_return_pct)}`);
  setText("excessReturn", formatPct(summary.midpoint_excess_vs_csi300_pct));
  setText("maxDrawdown", formatPct(midpoint.max_drawdown_pct));
  setText("drawdownDate", `发生于 ${midpoint.max_drawdown_date || "--"}`);
  setText("drawdownImprovement", formatPct(summary.midpoint_max_drawdown_improvement_vs_csi300_pct_points));
  const excess = summary.midpoint_excess_vs_csi300_pct;
  const ddImprovement = summary.midpoint_max_drawdown_improvement_vs_csi300_pct_points;
  setText("verdictTitle", excess >= 0 ? "中位数方案跑赢沪深300" : "中位数方案没有跑赢沪深300，但回撤更小");
  setText("verdictDetail", `样本期 ${sample.start_month || "--"} 至 ${sample.end_month || "--"}，累计超额 ${formatPct(excess)}；最大回撤改善 ${formatPct(ddImprovement)} 个百分点。收益与风险的取舍需要结合上下限方案和后续样本外数据判断。`);
  renderLegend();
  renderComparison(metrics);
  renderMethods();
  renderObservations();
  renderCharts();
  setText("observationCount", `${sample.return_observations || 0} 个收益观察`);
  setText("auditDetail", `${audit.passed ? "通过" : "未通过"}；future_information_dependency_count = ${audit.future_information_dependency_count ?? "--"}。回测结果使用下一月价格计算收益，但状态和仓位只来自信号月及其之前的冻结记录。`);
}

function renderLegend() {
  const container = document.getElementById("equityLegend");
  container.innerHTML = ["lower_bound", "midpoint", "upper_bound", "csi300", "csi500", "shanghai"]
    .map((key) => `<span class="legend-item" style="--legend-color:${colors[key]}">${labels[key]}</span>`)
    .join("");
}

function renderComparison(metrics) {
  const keys = ["lower_bound", "midpoint", "upper_bound", "csi300", "csi500", "shanghai"];
  document.getElementById("comparisonRows").innerHTML = keys
    .map((key) => {
      const item = metrics[key] || {};
      const turnover = item.total_turnover_pct === undefined ? "--" : `${formatNumber(item.total_turnover_pct)}%`;
      return `<tr><td><strong>${labels[key]}</strong></td><td class="${tone(item.cumulative_return_pct)}">${formatPct(item.cumulative_return_pct)}</td><td>${formatPct(item.annualized_return_pct)}</td><td>${formatPct(item.annualized_volatility_pct)}</td><td class="negative">${formatPct(item.max_drawdown_pct)}</td><td>${formatNumber(item.sharpe_ratio)}</td><td>${turnover}</td></tr>`;
    })
    .join("");
  setText("comparisonNote", `成本 ${payload.methodology?.cost_bps ?? "--"} bp · 主基准沪深300`);
}

function renderMethods() {
  const method = payload.methodology || {};
  const list = [
    `信号时点：${method.signal_timing || "--"}。`,
    `执行时点：${method.execution_timing || "--"}。`,
    method.execution_limitation || "--",
    `策略收益：${method.strategy_return_definition || "--"}；现金收益按 ${method.cash_return || "--"} 处理。`,
    `${method.initial_position_cost || "--"} 单边成本参数为 ${method.cost_bps ?? "--"} bp。`,
  ];
  document.getElementById("methodList").innerHTML = list.map((item) => `<li>${escapeHtml(item)}</li>`).join("");
}

function renderObservations() {
  const rows = Array.isArray(payload.observations) ? payload.observations.slice().reverse() : [];
  document.getElementById("observationRows").innerHTML = rows
    .map((item) => {
      const strategies = item.strategies || {};
      return `<tr><td>${escapeHtml(item.signal_month || "--")}</td><td>${escapeHtml(item.stable_state || "--")}</td><td>${escapeHtml(item.execution_proxy_month || "--")}</td><td>${formatPct(item.benchmark_returns_pct?.csi300)}</td><td>${formatPct(strategies.lower_bound?.net_return_pct)}</td><td>${formatPct(strategies.midpoint?.net_return_pct)}</td><td>${formatPct(strategies.upper_bound?.net_return_pct)}</td><td>${formatPct(strategies.midpoint?.position_pct)}</td></tr>`;
    })
    .join("");
}

function renderCharts() {
  const series = payload.series || {};
  drawChart("equityChart", ["lower_bound", "midpoint", "upper_bound", "csi300", "csi500", "shanghai"].map((key) => ({ key, points: (series.strategies?.[key] || series.benchmarks?.[key] || []).map((item) => ({ date: item.date, value: item.nav })) })), { min: 0, ySuffix: "x", title: "累计净值" });
  const midpointDrawdown = toDrawdown(series.strategies?.midpoint || []);
  const csi300Drawdown = toDrawdown(series.benchmarks?.csi300 || []);
  drawChart("drawdownChart", [
    { key: "midpoint", points: midpointDrawdown },
    { key: "csi300", points: csi300Drawdown },
  ], { ySuffix: "%", percent: true, title: "回撤" });
  drawChart("positionChart", ["lower_bound", "midpoint", "upper_bound"].map((key) => ({ key, points: (series.positions?.[key] || []).map((item) => ({ date: item.date, value: item.position_pct })) })), { min: 0, max: 100, ySuffix: "%", percent: false, title: "权益仓位" });
}

function toDrawdown(points) {
  let peak = 0;
  return points.map((item) => {
    peak = Math.max(peak, Number(item.nav));
    return { date: item.date, value: peak ? (Number(item.nav) / peak - 1) * 100 : 0 };
  });
}

function drawChart(containerId, series, options = {}) {
  const container = document.getElementById(containerId);
  if (!container || !series.some((item) => item.points.length)) return;
  container.innerHTML = "";
  const width = 1180;
  const height = containerId === "equityChart" ? 400 : 280;
  const margin = { top: 18, right: 24, bottom: 42, left: 52 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const allPoints = series.flatMap((item) => item.points).filter((item) => Number.isFinite(Number(item.value)));
  let min = options.min ?? Math.min(...allPoints.map((item) => Number(item.value)));
  let max = options.max ?? Math.max(...allPoints.map((item) => Number(item.value)));
  if (options.percent) { min = Math.min(-5, min); max = 0; }
  if (max <= min) max = min + 1;
  const dates = series.find((item) => item.points.length)?.points || [];
  const x = (index) => margin.left + (index / Math.max(dates.length - 1, 1)) * plotWidth;
  const y = (value) => margin.top + (1 - (Number(value) - min) / (max - min)) * plotHeight;
  const svg = createSvg("svg", { viewBox: `0 0 ${width} ${height}`, role: "img" });
  svg.appendChild(createSvg("title", {}, options.title || "回测图表"));
  const ticks = options.percent ? [-50, -25, 0] : [min, min + (max - min) / 2, max];
  ticks.forEach((value) => {
    const safeValue = Math.max(min, Math.min(max, value));
    svg.appendChild(createSvg("line", { class: "grid-line", x1: margin.left, y1: y(safeValue), x2: width - margin.right, y2: y(safeValue) }));
    svg.appendChild(createSvg("text", { class: "tick-label", x: 8, y: y(safeValue) + 4 }, `${formatNumber(safeValue)}${options.ySuffix || ""}`));
  });
  svg.appendChild(createSvg("line", { class: "axis-line", x1: margin.left, y1: height - margin.bottom, x2: width - margin.right, y2: height - margin.bottom }));
  const labelStep = Math.max(1, Math.ceil(dates.length / 7));
  dates.forEach((item, index) => {
    if (index % labelStep !== 0 && index !== dates.length - 1) return;
    svg.appendChild(createSvg("text", { class: "tick-label", x: x(index), y: height - 12, "text-anchor": "middle" }, item.date));
  });
  const rendered = [];
  series.forEach((item) => {
    const points = item.points.map((point, index) => ({ x: x(index), y: y(point.value), date: point.date, value: point.value })).filter((point) => Number.isFinite(point.y));
    if (points.length < 2) return;
    const path = createSvg("path", { class: `series-line ${item.key === "midpoint" ? "primary" : ""}`, stroke: colors[item.key] || "#047d73", d: smoothPath(points) });
    svg.appendChild(path);
    rendered.push({ key: item.key, points });
  });
  const hover = createSvg("g", { class: "chart-hover", "aria-hidden": "true" });
  const line = createSvg("line", { class: "hover-line", x1: margin.left, y1: margin.top, x2: margin.left, y2: height - margin.bottom });
  const dot = createSvg("circle", { class: "hover-dot", fill: colors.midpoint, cx: margin.left, cy: margin.top, r: 5 });
  hover.appendChild(line); hover.appendChild(dot); svg.appendChild(hover);
  hover.style.display = "none";
  container.appendChild(svg);
  const tooltip = document.createElement("div");
  tooltip.className = "chart-tooltip";
  tooltip.hidden = true;
  container.appendChild(tooltip);
  const update = (event) => {
    const bounds = svg.getBoundingClientRect();
    const svgX = ((event.clientX - bounds.left) / Math.max(bounds.width, 1)) * width;
    const index = Math.max(0, Math.min(dates.length - 1, Math.round(((svgX - margin.left) / plotWidth) * Math.max(dates.length - 1, 1))));
    const point = rendered.find((item) => item.points[index])?.points[index];
    if (!point) return;
    line.setAttribute("x1", x(index)); line.setAttribute("x2", x(index));
    dot.setAttribute("cx", x(index)); dot.setAttribute("cy", y(point.value)); dot.setAttribute("fill", colors[rendered.find((item) => item.points[index])?.key] || colors.midpoint);
    hover.style.display = "";
    tooltip.hidden = false;
    tooltip.innerHTML = `<strong>${escapeHtml(dates[index].date)}</strong><br>${rendered.map((item) => `${labels[item.key]}：${formatNumber(item.points[index]?.value)}${options.ySuffix || ""}`).join("<br>")}`;
    tooltip.style.left = `${Math.min(container.clientWidth - 180, Math.max(8, event.offsetX + 12))}px`;
    tooltip.style.top = "10px";
  };
  container.addEventListener("pointermove", update);
  container.addEventListener("pointerleave", () => { hover.style.display = "none"; tooltip.hidden = true; });
}

function createSvg(tag, attributes, textContent) {
  const element = document.createElementNS(svgNs, tag);
  Object.entries(attributes || {}).forEach(([key, value]) => { if (value !== null && value !== undefined) element.setAttribute(key, String(value)); });
  if (textContent !== undefined) element.textContent = textContent;
  return element;
}

function smoothPath(points) {
  if (!points.length) return "";
  return points.map((point, index) => `${index ? "L" : "M"} ${point.x} ${point.y}`).join(" ");
}

function setText(id, value) { const node = document.getElementById(id); if (node) node.textContent = value; }
function formatNumber(value) { return value === null || value === undefined || !Number.isFinite(Number(value)) ? "--" : Number(value).toFixed(2); }
function formatPct(value) { return value === null || value === undefined || !Number.isFinite(Number(value)) ? "--" : `${Number(value).toFixed(2)}%`; }
function tone(value) { return Number(value) >= 0 ? "positive" : "negative"; }
function escapeHtml(value) { return String(value ?? "").replace(/[&<>\"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" }[char])); }
