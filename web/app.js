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
  opportunity: "#2c68a0",
  shanghai: "#b7791f",
  penalty: "#bf3d2b",
};

const svgNs = "http://www.w3.org/2000/svg";

let state = {
  history: null,
  records: [],
  latest: null,
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
  const payload = await fetchJson("/api/history");
  state.history = payload.history;
  state.records = normalizeRecords(payload.history.records || []);
  state.latest = state.records[state.records.length - 1] || null;
  setStatus(state.latest ? "已更新" : "无评分记录");
  await loadResearchApiStatus();
  renderAll();
}

async function loadResearchApiStatus() {
  try {
    const payload = await fetchJson("/api/research/latest");
    const results = payload.results || {};
    const availableCount = Object.values(results).filter((item) => item && item.available).length;
    setText("apiStatus", `${availableCount} / ${Object.keys(results).length} 可用 · ${formatDateTime(payload.generated_at)}`);
  } catch (error) {
    setText("apiStatus", `不可用：${error.message}`);
  }
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
  renderSummary();
  renderOverviewChart();
  renderModuleSelect();
  renderModuleGrid();
  renderModuleDetails();
  renderHistoryTable();
}

function renderSummary() {
  const latest = state.latest;
  if (!latest) {
    setText("modelLine", "暂无评分历史");
    ["positionScore", "opportunityScore", "crowdingPenalty", "marketRegime"].forEach((id) => setText(id, "--"));
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
  setText("positionRange", `权益 ${latest.equity_position_range || "--"}`);
  setMeter("positionMeter", latest.market_position_score, 100);
  setMeter("opportunityMeter", latest.market_opportunity_score, 100);
  setMeter("crowdingMeter", latest.crowding_penalty, 30);
  setText("recordCount", `${state.records.length} 条记录`);
  setText("historyUpdated", state.history?.updated_at ? `更新 ${formatDateTime(state.history.updated_at)}` : "--");
}

function renderOverviewChart() {
  const records = state.records;
  const container = document.getElementById("overviewChart");
  if (!records.length) {
    renderEmpty(container, "暂无评分历史");
    return;
  }

  const labels = records.map(recordLabel);
  renderLineChart(
    container,
    [
      {
        name: "仓位参考分",
        color: chartColors.position,
        axis: "left",
        data: records.map((record, index) => point(labels[index], record.market_position_score)),
      },
      {
        name: "市场机会分",
        color: chartColors.opportunity,
        axis: "left",
        data: records.map((record, index) => point(labels[index], record.market_opportunity_score)),
      },
      {
        name: "拥挤惩罚",
        color: chartColors.penalty,
        axis: "left",
        data: records.map((record, index) => point(labels[index], record.crowding_penalty)),
      },
      {
        name: "上证指数",
        color: chartColors.shanghai,
        axis: "right",
        data: records.map((record, index) => point(labels[index], record.shanghai_composite)),
      },
    ],
    {
      leftMin: 0,
      leftMax: 100,
      rightLabel: "上证",
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
    const values = state.records.map((record) => numeric(record.modules?.[key]?.metrics?.[metricKey]?.value));
    renderLineChart(
      card.querySelector(".metric-chart"),
      [
        {
          name: meta.label || metricKey,
          color: moduleColors[key] || chartColors.position,
          axis: "left",
          data: values.map((value, index) => point(labels[index], value)),
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
    tbody.innerHTML = `<tr><td colspan="8" class="empty-state">暂无评分历史</td></tr>`;
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
          <td class="score-up">${formatNumber(record.market_position_score)}</td>
          <td>${formatNumber(record.shanghai_composite)}</td>
          <td>${escapeHtml(record.equity_position_range || "--")}</td>
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
    class: "chart-svg",
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

  activeSeries.forEach((item) => {
    const range = item.axis === "right" ? rightRange : leftRange;
    const points = item.data.map((pointItem, index) => {
      const value = numeric(pointItem.value);
      return {
        x: xPos(index, item.data.length, margin, plotWidth),
        y: yPos(value, range, margin, plotHeight),
        value,
        label: pointItem.label,
      };
    });

    if (points.length > 1) {
      const d = points.map((itemPoint, index) => `${index === 0 ? "M" : "L"} ${itemPoint.x} ${itemPoint.y}`).join(" ");
      svg.appendChild(
        createSvg("path", {
          d,
          fill: "none",
          stroke: item.color,
          "stroke-width": options.compact ? 2.2 : 2.8,
          "stroke-linecap": "round",
          "stroke-linejoin": "round",
        }),
      );
    }

    points.forEach((itemPoint) => {
      const circle = createSvg("circle", {
        cx: itemPoint.x,
        cy: itemPoint.y,
        r: options.compact ? 3.2 : 4,
        fill: item.color,
      });
      circle.appendChild(createSvg("title", {}, `${item.name} ${itemPoint.label}: ${formatNumber(itemPoint.value)}`));
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
  Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, value));
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

function point(label, value) {
  return { label, value: numeric(value) };
}

function recordLabel(record) {
  const basis = record.basis_trade_date || "--";
  const scored = record.scored_at ? String(record.scored_at).slice(11, 19) : "";
  return `${basis} ${scored}`.trim();
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
