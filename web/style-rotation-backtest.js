const chartSeries = {
  strategy: { label: "动态轮动", color: "#087c6f", width: 3.2 },
  static6535: { label: "静态65/35", color: "#d87532", width: 2 },
  cashflow: { label: "100% 自由现金流", color: "#7a5aa6", width: 1.9 },
  technology: { label: "100% 科技成长", color: "#b94b3c", width: 1.9 },
  a500: { label: "中证A500", color: "#3d68a5", width: 2 },
  csi300: { label: "沪深300", color: "#778581", width: 1.8 },
};

const state = { raw: null, result: null, visible: new Set(Object.keys(chartSeries)), costBps: 10 };

document.addEventListener("DOMContentLoaded", async () => {
  const range = document.getElementById("costRange");
  range.addEventListener("input", () => {
    state.costBps = Number(range.value);
    document.getElementById("costOutput").textContent = range.value;
    runAndRender();
  });
  window.addEventListener("resize", debounce(renderCharts, 120));
  try {
    const response = await fetch("/data/style-rotation-history.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    state.raw = await response.json();
    buildLegend();
    runAndRender();
  } catch (error) {
    document.getElementById("currentSignal").textContent = `数据读取失败：${error.message}`;
  }
});

function runAndRender() {
  state.result = backtest(state.raw.observations, state.costBps);
  renderSummary();
  renderTable();
  renderCharts();
}

function backtest(rows, costBps) {
  const startIndex = 60;
  const data = rows.slice(startIndex).map((row, index) => ({ ...row, sourceIndex: index + startIndex }));
  const values = {
    strategy: 1,
    static6535: 1,
    cashflow: 1,
    technology: 1,
    a500: 1,
    csi300: 1,
  };
  let techWeight = 0.35;
  let pendingWeight = null;
  let turnover = 0;
  let switches = 0;
  const curve = [];
  const allocations = [];

  for (let k = 0; k < data.length; k += 1) {
    const row = data[k];
    const i = row.sourceIndex;
    if (pendingWeight !== null) {
      const traded = Math.abs(pendingWeight - techWeight);
      values.strategy *= 1 - traded * costBps / 10000;
      turnover += traded;
      if (traded > 0.0001) switches += 1;
      techWeight = pendingWeight;
      pendingWeight = null;
    }

    if (k > 0) {
      const previous = rows[i - 1];
      const cashReturn = row.cashflow / previous.cashflow - 1;
      const techReturn = row.technology / previous.technology - 1;
      values.strategy *= 1 + (1 - techWeight) * cashReturn + techWeight * techReturn;
      values.static6535 *= 1 + 0.65 * cashReturn + 0.35 * techReturn;
      values.cashflow *= 1 + cashReturn;
      values.technology *= 1 + techReturn;
      values.a500 *= row.a500 / previous.a500;
      values.csi300 *= row.csi300 / previous.csi300;
    }

    curve.push({ date: row.date, techWeight, ...values });
    if (isMonthEnd(rows, i)) {
      const signal = evaluateSignal(rows, i);
      pendingWeight = signal.techWeight;
      allocations.push({ date: row.date, techWeight: signal.techWeight, ...signal });
    }
  }

  const metrics = Object.fromEntries(Object.keys(values).map((key) => [key, calculateMetrics(curve, key)]));
  return { curve, allocations, metrics, turnover, switches, current: allocations.at(-1) };
}

function evaluateSignal(rows, i) {
  const technology = rows.map((row) => row.technology);
  const ratio = rows.map((row) => row.technology / row.cashflow);
  const tech = technology[i];
  const ma20 = average(technology.slice(i - 19, i + 1));
  const ma60 = average(technology.slice(i - 59, i + 1));
  const priorRatio60 = ratio.slice(i - 60, i);
  const priorRatio20 = ratio.slice(i - 20, i);
  const high60 = Math.max(...technology.slice(i - 59, i + 1));
  const positive = [tech > ma60, ma20 > ma60, ratio[i] > Math.max(...priorRatio60)];
  const negative = [tech < ma60, ratio[i] < Math.min(...priorRatio20), tech / high60 - 1 <= -0.12];
  const positiveCount = positive.filter(Boolean).length;
  const negativeCount = negative.filter(Boolean).length;
  if (positiveCount >= 2) return { techWeight: 0.55, regime: "进攻", positiveCount, negativeCount };
  if (negativeCount >= 2) return { techWeight: 0.20, regime: "防守", positiveCount, negativeCount };
  return { techWeight: 0.35, regime: "均衡", positiveCount, negativeCount };
}

function isMonthEnd(rows, index) {
  return index === rows.length - 1 || rows[index].date.slice(0, 7) !== rows[index + 1].date.slice(0, 7);
}

function calculateMetrics(curve, key) {
  const series = curve.map((row) => row[key]);
  const returns = series.slice(1).map((value, i) => value / series[i] - 1);
  const years = Math.max(returns.length / 242, 1 / 242);
  const totalReturn = series.at(-1) / series[0] - 1;
  const annualized = Math.pow(1 + totalReturn, 1 / years) - 1;
  const mean = average(returns);
  const volatility = stdev(returns) * Math.sqrt(242);
  const sharpe = volatility ? mean * 242 / volatility : 0;
  let peak = series[0];
  let maxDrawdown = 0;
  let maxDrawdownDate = curve[0].date;
  const drawdown = series.map((value, index) => {
    peak = Math.max(peak, value);
    const current = value / peak - 1;
    if (current < maxDrawdown) {
      maxDrawdown = current;
      maxDrawdownDate = curve[index].date;
    }
    return current;
  });
  return { totalReturn, annualized, volatility, sharpe, maxDrawdown, maxDrawdownDate, drawdown };
}

function renderSummary() {
  const { metrics, turnover, switches, current, curve } = state.result;
  setText("currentAllocation", `现金流 ${weightPct(1 - current.techWeight)} / 科技 ${weightPct(current.techWeight)}`);
  setText("currentSignal", `${current.regime}档 · 上次月末信号 ${current.date}`);
  setText("sampleRange", `${state.raw.sample.first_date} → ${state.raw.sample.last_date}`);
  setText("effectiveRange", `有效回测 ${curve[0].date} → ${curve.at(-1).date}`);
  setText("strategyReturn", pct(metrics.strategy.totalReturn));
  setText("strategyAnnualized", `年化 ${pct(metrics.strategy.annualized)}`);
  setText("excessReturn", points(metrics.strategy.totalReturn - metrics.a500.totalReturn));
  setText("excessAnnualized", `年化超额 ${points(metrics.strategy.annualized - metrics.a500.annualized)}`);
  setText("maxDrawdown", pct(metrics.strategy.maxDrawdown));
  setText("drawdownDate", `发生于 ${metrics.strategy.maxDrawdownDate}`);
  setText("sharpeRatio", number(metrics.strategy.sharpe));
  setText("turnoverSummary", `${switches}次换挡 · 累计单边换手 ${weightPct(turnover)}`);
  setText("sourceLine", `数据：${state.raw.source.provider}，更新至 ${state.raw.sample.last_date}；生成时间 ${state.raw.generated_at.slice(0, 19).replace("T", " ")}`);
  const beatsStatic = metrics.strategy.totalReturn > metrics.static6535.totalReturn;
  const improvesDrawdown = metrics.strategy.maxDrawdown > metrics.static6535.maxDrawdown;
  setText("verdictTitle", beatsStatic && improvesDrawdown ? "轮动规则通过初筛" : "当前轮动规则未通过初筛");
  setText("verdictDetail", `动态轮动相对A500累计多 ${points(metrics.strategy.totalReturn - metrics.a500.totalReturn)}，但相对静态65/35${beatsStatic ? "多" : "少"} ${points(Math.abs(metrics.strategy.totalReturn - metrics.static6535.totalReturn))}，最大回撤${improvesDrawdown ? "收窄" : "扩大"} ${points(Math.abs(metrics.strategy.maxDrawdown - metrics.static6535.maxDrawdown))}。`);
}

function renderTable() {
  const order = [
    ["strategy", "动态轮动", true],
    ["static6535", "静态65/35", false],
    ["cashflow", "100% 自由现金流", false],
    ["technology", "100% 科技成长", false],
    ["a500", "中证A500", false],
    ["csi300", "沪深300", false],
  ];
  document.getElementById("comparisonRows").innerHTML = order.map(([key, label, primary]) => {
    const item = state.result.metrics[key];
    return `<tr class="${primary ? "primary" : ""}"><td>${label}</td><td>${pct(item.totalReturn)}</td><td>${pct(item.annualized)}</td><td>${plainPct(item.volatility)}</td><td>${pct(item.maxDrawdown)}</td><td>${number(item.sharpe)}</td></tr>`;
  }).join("");
}

function buildLegend() {
  const legend = document.getElementById("seriesLegend");
  legend.innerHTML = Object.entries(chartSeries).map(([key, item]) => `<button type="button" data-series="${key}" aria-pressed="true" style="--series-color:${item.color}"><i></i>${item.label}</button>`).join("");
  legend.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-series]");
    if (!button) return;
    const key = button.dataset.series;
    if (state.visible.has(key) && state.visible.size > 1) state.visible.delete(key);
    else state.visible.add(key);
    button.setAttribute("aria-pressed", state.visible.has(key) ? "true" : "false");
    renderEquityChart();
  });
}

function renderCharts() {
  if (!state.result) return;
  renderEquityChart();
  renderDrawdownChart();
  renderAllocationChart();
}

function renderEquityChart() {
  const visible = Object.keys(chartSeries).filter((key) => state.visible.has(key));
  renderLineChart("equityChart", state.result.curve, visible.map((key) => ({ key, ...chartSeries[key] })), {
    yAccessor: (row, key) => row[key],
    yFormat: (value) => value.toFixed(2),
    axisLabel: "累计净值（起点=1）",
  });
}

function renderDrawdownChart() {
  const data = state.result.curve.map((row, i) => ({
    date: row.date,
    strategy: state.result.metrics.strategy.drawdown[i],
    a500: state.result.metrics.a500.drawdown[i],
  }));
  renderLineChart("drawdownChart", data, [
    { key: "strategy", label: "动态轮动", color: chartSeries.strategy.color, width: 2.6 },
    { key: "a500", label: "中证A500", color: chartSeries.a500.color, width: 1.8 },
  ], { yAccessor: (row, key) => row[key], yFormat: (value) => pct(value), axisLabel: "回撤", fixedMax: 0 });
}

function renderAllocationChart() {
  const container = document.getElementById("allocationChart");
  const data = state.result.curve;
  const width = Math.max(container.clientWidth, 320);
  const height = 270;
  const margin = { top: 12, right: 14, bottom: 36, left: 50 };
  const plotW = width - margin.left - margin.right;
  const plotH = height - margin.top - margin.bottom;
  const x = (i) => margin.left + i / Math.max(data.length - 1, 1) * plotW;
  const y = (value) => margin.top + (0.65 - value) / 0.55 * plotH;
  const path = data.map((row, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(row.techWeight).toFixed(1)}`).join(" ");
  const ticks = [0.2, 0.35, 0.55];
  container.innerHTML = `<svg viewBox="0 0 ${width} ${height}" aria-hidden="true">
    <rect class="frame" x="${margin.left}" y="${margin.top}" width="${plotW}" height="${plotH}" />
    ${ticks.map((tick) => `<line class="grid" x1="${margin.left}" x2="${width - margin.right}" y1="${y(tick)}" y2="${y(tick)}" /><text x="${margin.left - 9}" y="${y(tick) + 4}" text-anchor="end">${weightPct(tick)}</text>`).join("")}
    <path d="${path}" fill="none" stroke="${chartSeries.technology?.color || "#d87532"}" stroke-width="2.4" stroke-linejoin="round" />
    ${dateTicks(data, x, height - 12)}
    <text class="axis-title" transform="translate(14 ${margin.top + plotH / 2}) rotate(-90)" text-anchor="middle">科技目标仓位</text>
  </svg>`;
}

function renderLineChart(containerId, data, series, options) {
  const container = document.getElementById(containerId);
  const width = Math.max(container.clientWidth, 320);
  const compact = container.classList.contains("compact");
  const height = compact ? 270 : 420;
  const margin = { top: 14, right: 16, bottom: 38, left: 62 };
  const plotW = width - margin.left - margin.right;
  const plotH = height - margin.top - margin.bottom;
  const values = data.flatMap((row) => series.map((item) => options.yAccessor(row, item.key))).filter(Number.isFinite);
  let min = Math.min(...values);
  let max = Math.max(...values);
  const padding = Math.max((max - min) * 0.08, 0.01);
  min -= padding;
  max += padding;
  if (Number.isFinite(options.fixedMin)) min = options.fixedMin;
  if (Number.isFinite(options.fixedMax)) max = options.fixedMax;
  const x = (i) => margin.left + i / Math.max(data.length - 1, 1) * plotW;
  const y = (value) => margin.top + (max - value) / Math.max(max - min, 1e-9) * plotH;
  const yTicks = Array.from({ length: 5 }, (_, i) => min + i / 4 * (max - min));
  const paths = series.map((item) => {
    const d = data.map((row, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(options.yAccessor(row, item.key)).toFixed(1)}`).join(" ");
    return `<path d="${d}" fill="none" stroke="${item.color}" stroke-width="${item.width}" stroke-linejoin="round" stroke-linecap="round" />`;
  }).join("");
  container.style.position = "relative";
  container.innerHTML = `<svg viewBox="0 0 ${width} ${height}">
    <rect class="frame" x="${margin.left}" y="${margin.top}" width="${plotW}" height="${plotH}" />
    ${yTicks.map((tick) => `<line class="grid" x1="${margin.left}" x2="${width - margin.right}" y1="${y(tick)}" y2="${y(tick)}" /><text x="${margin.left - 9}" y="${y(tick) + 4}" text-anchor="end">${options.yFormat(tick)}</text>`).join("")}
    ${paths}
    <line class="guide" x1="0" x2="0" y1="${margin.top}" y2="${height - margin.bottom}" visibility="hidden" />
    ${dateTicks(data, x, height - 12)}
    <text class="axis-title" transform="translate(14 ${margin.top + plotH / 2}) rotate(-90)" text-anchor="middle">${options.axisLabel}</text>
    <rect class="hit" x="${margin.left}" y="${margin.top}" width="${plotW}" height="${plotH}" />
  </svg><div class="chart-tooltip" hidden></div>`;
  const svg = container.querySelector("svg");
  const hit = container.querySelector(".hit");
  const guide = container.querySelector(".guide");
  const tooltip = container.querySelector(".chart-tooltip");
  hit.addEventListener("pointermove", (event) => {
    const rect = svg.getBoundingClientRect();
    const localX = (event.clientX - rect.left) * width / rect.width;
    const index = Math.max(0, Math.min(data.length - 1, Math.round((localX - margin.left) / plotW * (data.length - 1))));
    guide.setAttribute("x1", x(index));
    guide.setAttribute("x2", x(index));
    guide.setAttribute("visibility", "visible");
    tooltip.innerHTML = `<strong>${data[index].date}</strong>${series.map((item) => `<span><b style="color:${item.color}">${item.label}</b><em>${options.yFormat(options.yAccessor(data[index], item.key))}</em></span>`).join("")}`;
    tooltip.hidden = false;
    const left = Math.min(Math.max(event.clientX - container.getBoundingClientRect().left + 12, 4), container.clientWidth - 190);
    tooltip.style.left = `${left}px`;
    tooltip.style.top = `${Math.max(event.clientY - container.getBoundingClientRect().top - 24, 4)}px`;
  });
  hit.addEventListener("pointerleave", () => { guide.setAttribute("visibility", "hidden"); tooltip.hidden = true; });
}

function dateTicks(data, x, y) {
  const count = window.innerWidth < 620 ? 3 : 5;
  return Array.from({ length: count }, (_, i) => {
    const index = Math.round(i / (count - 1) * (data.length - 1));
    return `<text x="${x(index)}" y="${y}" text-anchor="${i === 0 ? "start" : i === count - 1 ? "end" : "middle"}">${data[index].date.slice(0, 7)}</text>`;
  }).join("");
}

function average(values) { return values.reduce((sum, value) => sum + value, 0) / Math.max(values.length, 1); }
function stdev(values) { const mean = average(values); return Math.sqrt(average(values.map((value) => (value - mean) ** 2))); }
function pct(value, digits = 1) { return `${value >= 0 ? "+" : ""}${(value * 100).toFixed(digits)}%`; }
function weightPct(value) { return `${(value * 100).toFixed(0)}%`; }
function plainPct(value, digits = 1) { return `${(value * 100).toFixed(digits)}%`; }
function points(value, digits = 1) { return `${(value * 100).toFixed(digits)}个百分点`; }
function number(value) { return Number.isFinite(value) ? value.toFixed(2) : "--"; }
function setText(id, value) { document.getElementById(id).textContent = value; }
function debounce(fn, wait) { let timer; return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), wait); }; }
