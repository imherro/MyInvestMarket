import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ChartRenderingContractTest(unittest.TestCase):
    def test_a_fear_page_shows_level_components_and_history_without_position_side_effect(self) -> None:
        index_html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        risk_html = (ROOT / "web" / "risk.html").read_text(encoding="utf-8")
        dashboard_js = (ROOT / "web" / "dashboard.js").read_text(encoding="utf-8")
        styles = (ROOT / "web" / "dashboard.css").read_text(encoding="utf-8")

        self.assertIn("fear-band", index_html)
        self.assertIn('id="fearChart"', index_html)
        self.assertIn('id="fearScore"', index_html)
        self.assertIn('id="componentRows"', risk_html)
        self.assertIn('id="riskList"', risk_html)
        self.assertIn('getJson("/api/dashboard")', dashboard_js)
        self.assertIn("不是买入分", index_html)
        self.assertIn(".fear-meter", styles)

    def test_allocation_history_uses_stacked_bar_chart(self) -> None:
        app_js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")
        allocation_start = app_js.index("function renderAllocationPolicy()")
        allocation_body = app_js[allocation_start : app_js.index("function sleevesToHistoryMap", allocation_start)]

        self.assertIn("renderStackedAllocationChart(chart, history, sleeves)", allocation_body)
        self.assertNotIn("renderLineChart(chart, series", allocation_body)
        self.assertIn("function renderStackedAllocationChart", app_js)
        self.assertIn("allocation-stack-segment", app_js)
        self.assertIn(".allocation-stack-segment", styles)

    def test_overview_chart_deemphasizes_shanghai_and_emphasizes_position_score(self) -> None:
        app_js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        overview_start = app_js.index("function renderOverviewChart()")
        overview_body = app_js[overview_start : app_js.index("function renderModuleSelect", overview_start)]

        self.assertIn('name: "股票账户仓位分"', overview_body)
        self.assertIn('weight: "bold"', overview_body)
        self.assertIn('name: "上证指数"', overview_body)
        self.assertIn('style: "background-dashed"', overview_body)
        self.assertIn("points: false", overview_body)
        self.assertIn("backgroundFirst: true", overview_body)
        self.assertIn('"stroke-dasharray": isBackground ? "7 8" : null', app_js)


if __name__ == "__main__":
    unittest.main()
