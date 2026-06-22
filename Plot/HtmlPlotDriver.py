import html
import json
import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from Chan import CChan
from Common.CEnum import BI_DIR, FX_TYPE, KL_TYPE
from Plot.PlotMeta import CChanPlotMeta


def _clean_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_") or "chart"


def _fmt_num(value: float, digits: int = 2) -> str:
    if value is None or not math.isfinite(float(value)):
        return "-"
    return f"{float(value):.{digits}f}"


def _fmt_time(value: Any) -> str:
    return value.to_str() if hasattr(value, "to_str") else str(value or "")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def _fx_label(kind: str) -> str:
    return "顶分型" if kind == "top" else "底分型"


def _dir_label(direction: str) -> str:
    return "向上笔" if direction == "up" else "向下笔"


class CHtmlPlotDriver:
    """Generate an interactive standalone HTML chart for Chan fractals.

    The driver intentionally mirrors the chart part of the chan-stock-buy-sell-point
    report: candlesticks, included K-line boxes, fractal markers and pens.
    """

    def __init__(
        self,
        chan: CChan,
        plot_config: Optional[Union[str, dict, list]] = None,
        plot_para=None,
        active_lv: Optional[KL_TYPE] = None,
        level_nav: Optional[List[Dict[str, str]]] = None,
    ):
        self.chan = chan
        self.plot_config = plot_config or {}
        self.plot_para = plot_para or {}
        self.active_lv = active_lv
        self.level_nav = level_nav
        self.metas = [CChanPlotMeta(chan[lv]) for lv in chan.lv_list]

    def save2html(self, path: Union[str, Path]) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_html(), encoding="utf-8")

    def to_html(self) -> str:
        panels: List[str] = []
        tabs: List[str] = []
        for idx, (lv, meta) in enumerate(zip(self.chan.lv_list, self.metas)):
            chart_id = _clean_id(f"{self.chan.code}_{lv.name}_{idx}")
            is_active = lv == self.active_lv if self.active_lv is not None else idx == 0
            active = " active" if is_active else ""
            label = self._level_label(lv)
            tabs.append(f'<button class="tf-tab{active}" type="button" data-target="{chart_id}">{html.escape(label)}</button>')
            panels.append(
                f'<section id="{chart_id}" class="tf-panel{active}">'
                f"{self._make_chart(meta, label, chart_id)}"
                "</section>"
            )
        if self.level_nav:
            tabs = [
                f'<a class="tf-tab{" active" if item.get("active") else ""}" href="{html.escape(item["href"])}">'
                f'{html.escape(item["label"])}</a>'
                for item in self.level_nav
            ]

        title = html.escape(str(self.chan.code))
        return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} 缠论分型图</title>
<style>
:root {{
  --ink:#101828;
  --muted:#667085;
  --line:#d0d5dd;
  --bg:#f6f7f9;
  --panel:#ffffff;
  --red:#b42318;
  --blue:#175cd3;
  --green:#067647;
  --orange:#f79009;
}}
* {{ box-sizing:border-box; }}
body {{
  margin:0;
  background:var(--bg);
  color:var(--ink);
  font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
}}
main {{ max-width:1440px; margin:0 auto; padding:16px; }}
header {{ display:flex; align-items:flex-end; justify-content:space-between; gap:12px; margin-bottom:12px; }}
h1 {{ margin:0; font-size:20px; line-height:1.25; font-weight:700; }}
.meta {{ color:var(--muted); font-size:12px; }}
.tf-tabs {{ display:flex; gap:6px; flex-wrap:wrap; }}
.tf-tab {{
  display:inline-flex; align-items:center; height:30px; padding:0 12px;
  border:1px solid var(--line); border-radius:4px; background:#fff;
  color:var(--ink); cursor:pointer; text-decoration:none;
}}
.tf-tab.active {{ border-color:#1570ef; color:#175cd3; background:#eff8ff; }}
.tf-panel {{ display:none; }}
.tf-panel.active {{ display:block; }}
.chart-shell {{ background:var(--panel); border:1px solid var(--line); border-radius:6px; padding:10px; }}
.chart-toolbar {{ display:flex; align-items:center; gap:6px; flex-wrap:wrap; margin-bottom:8px; }}
.chart-toolbar button {{
  min-width:34px; height:30px; padding:0 10px; border:1px solid var(--line);
  border-radius:4px; background:#fff; color:var(--ink); cursor:pointer;
}}
.chart-toolbar button:hover {{ background:#f8fafc; }}
.zoom-label {{ color:var(--muted); font-size:13px; min-width:62px; text-align:center; }}
.chart-help {{ margin-left:auto; color:#98a2b3; font-size:12px; }}
.chart-wrap {{
  position:relative; overflow:hidden; height:clamp(420px,72vh,820px);
  border:1px solid #e4e7ec; border-radius:4px; background:#fafafa; touch-action:none;
}}
.chan-chart-svg {{ width:100%; height:100%; display:block; background:#fafafa; cursor:grab; }}
.chan-chart-svg text {{
  vector-effect:non-scaling-stroke; paint-order:stroke; stroke:#fafafa;
  stroke-width:2px; stroke-linejoin:round;
}}
.chan-chart-svg line,.chan-chart-svg rect,.chan-chart-svg polygon {{
  vector-effect:non-scaling-stroke;
}}
.chart-fractal-marker:hover {{ filter:drop-shadow(0 0 3px rgba(247,144,9,.85)); }}
.tooltip {{
  position:absolute; z-index:5; display:none; min-width:190px; padding:8px 10px;
  border:1px solid #d9dee7; border-radius:4px; background:rgba(255,255,255,.96);
  box-shadow:0 8px 24px rgba(16,24,40,.14); color:var(--ink); font-size:12px;
  pointer-events:none;
}}
.legend {{ display:flex; gap:14px; flex-wrap:wrap; color:var(--muted); font-size:12px; margin-top:8px; }}
.swatch {{ display:inline-block; width:10px; height:10px; margin-right:5px; vertical-align:-1px; }}
.logic-link {{
  display:inline-flex; align-items:center; height:30px; padding:0 12px; margin-left:8px;
  border:1px solid #b2ddff; border-radius:4px; background:#eff8ff; color:#175cd3;
  text-decoration:none; font-size:13px;
}}
.report-section {{
  margin-top:14px; background:var(--panel); border:1px solid var(--line); border-radius:6px;
  padding:14px; overflow:hidden;
}}
.section-head {{ display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:10px; }}
.section-head h2 {{ margin:0; font-size:17px; line-height:1.3; }}
.section-actions {{ display:flex; align-items:center; gap:8px; color:var(--muted); font-size:12px; }}
.section-actions input {{
  height:30px; min-width:178px; border:1px solid var(--line); border-radius:4px; padding:0 8px;
  color:var(--ink); background:#fff;
}}
.section-actions button {{
  height:30px; padding:0 12px; border:1px solid #2e698c; border-radius:4px; background:#2e698c;
  color:#fff; cursor:pointer;
}}
.section-actions .collapse-btn {{
  border:0; background:transparent; color:#344054; padding:0 4px;
}}
.table-wrap {{ overflow:auto; max-height:430px; border:1px solid #e4e7ec; }}
.data-table {{ width:100%; min-width:1040px; border-collapse:collapse; font-size:13px; }}
.data-table th {{
  position:sticky; top:0; z-index:1; background:#eef2f6; color:#101828; text-align:left;
  border-bottom:1px solid #d0d5dd; padding:7px 8px; white-space:nowrap;
}}
.data-table td {{ border-bottom:1px solid #d0d5dd; padding:7px 8px; vertical-align:top; }}
.data-table tr.clickable {{ cursor:pointer; }}
.data-table tr.clickable:hover {{ background:#f8fafc; }}
.data-table tr.invalid {{ background:#fff1ef; color:#7a271a; }}
.data-table tr.selected-row {{ outline:2px solid #2e698c; outline-offset:-2px; background:#eff8ff; }}
.note-cell {{ min-width:380px; line-height:1.55; }}
.note-cell ol {{ margin:0; padding-left:18px; }}
.detail-page {{ display:none; min-height:100vh; }}
.detail-page.active {{ display:block; }}
.detail-panel {{ max-width:980px; margin:0 auto; background:#fff; border:1px solid var(--line); border-radius:6px; padding:22px; }}
.detail-panel h1 {{ margin-bottom:12px; }}
.detail-panel h2 {{ margin:20px 0 8px; font-size:17px; }}
.detail-panel p,.detail-panel li {{ color:#344054; }}
.detail-panel code {{ background:#f2f4f7; padding:1px 4px; border-radius:3px; }}
.back-link {{
  display:inline-flex; align-items:center; height:30px; padding:0 12px; margin-bottom:14px;
  border:1px solid var(--line); border-radius:4px; color:#101828; background:#fff; text-decoration:none;
}}
@media (max-width:760px) {{
  main {{ padding:10px; }}
  header {{ display:block; }}
  .tf-tabs {{ margin-top:8px; }}
  .chart-help {{ flex-basis:100%; margin-left:0; }}
  .chart-wrap {{ height:520px; }}
  .section-head {{ display:block; }}
  .section-actions {{ margin-top:8px; flex-wrap:wrap; }}
  .logic-link {{ margin:8px 0 0; }}
}}
</style>
</head>
<body>
<main id="report-page">
  <header>
    <div>
      <h1>{title} 缠论分型图</h1>
      <div class="meta">K线 · 分型 · 笔；滚轮缩放，拖拽平移，双击切换十字星。</div>
    </div>
    <div>
      <nav class="tf-tabs">{"".join(tabs)}</nav>
      <a class="logic-link" href="#logic" id="logic-open">划分逻辑</a>
    </div>
  </header>
  {"".join(panels)}
</main>
<main id="logic-page" class="detail-page">
  <section class="detail-panel">
    <a class="back-link" href="#" id="logic-back">返回图表</a>
    <h1>当前分型与笔划分逻辑</h1>
    <p>本页说明当前 HTML 报告使用的机械化计算口径，便于对照“原始分型列表”和“笔列表”复核每一步。</p>
    <h2>1. K线包含处理</h2>
    <p>先按相邻 K 线高低点关系合并包含关系，合并后的 K 线保留起止时间、最高价、最低价和内部原始 K 线区间。后续分型识别均基于合并后的 K 线。</p>
    <h2>2. 原始分型识别</h2>
    <p>每根合并 K 线与前后合并 K 线比较：中间 K 线高点和低点均高于两侧时识别为顶分型；中间 K 线高点和低点均低于两侧时识别为底分型。表格中的“分型价格、最高、最低”来自该合并 K 线及其内部原始 K 线。</p>
    <h2>3. 分型过滤</h2>
    <p>原始分型进入笔构造时需要满足顶底交替、分型占用区间和独立 K 线间隔要求。连续同类分型会按极值归并：顶分型保留高点更高者，底分型保留低点更低者；反向分型若区间重叠或间隔不足，会优先按成笔条件过滤。</p>
    <h2>4. 笔构造</h2>
    <p>有效笔由一组相邻有效分型端点构成。底分型到顶分型为向上笔，顶分型到底分型为向下笔。当前配置为 <code>bi_strict=True</code>、<code>bi_fx_check=totally</code>，因此端点之间需满足严格合并 K 线跨度和完全区间验证。</p>
    <h2>5. 表格备注口径</h2>
    <p>原始分型列表中“有效”表示该分型最终被某条笔的起点或终点采用；“已过滤”表示它未成为笔端点。备注会列出识别形态、成笔采用、同类极值或间隔/区间过滤等可审计原因。点击表格行可定位到对应 K 线。</p>
  </section>
</main>
<script>
document.querySelectorAll('.tf-tab').forEach(function(tab) {{
  tab.addEventListener('click', function() {{
    if (tab.tagName === 'A') return;
    document.querySelectorAll('.tf-tab').forEach(function(x) {{ x.classList.remove('active'); }});
    document.querySelectorAll('.tf-panel').forEach(function(x) {{ x.classList.remove('active'); }});
    tab.classList.add('active');
    var panel = document.getElementById(tab.getAttribute('data-target'));
    if (panel) panel.classList.add('active');
  }});
}});
var reportPage = document.getElementById('report-page');
var logicPage = document.getElementById('logic-page');
document.getElementById('logic-open').addEventListener('click', function(e) {{
  e.preventDefault();
  reportPage.style.display = 'none';
  logicPage.classList.add('active');
  window.scrollTo(0, 0);
}});
document.getElementById('logic-back').addEventListener('click', function(e) {{
  e.preventDefault();
  logicPage.classList.remove('active');
  reportPage.style.display = '';
  window.scrollTo(0, 0);
}});
</script>
</body>
</html>
"""

    @staticmethod
    def _level_label(lv: KL_TYPE) -> str:
        mapping = {
            KL_TYPE.K_1M: "1分钟",
            KL_TYPE.K_5M: "5分钟",
            KL_TYPE.K_15M: "15分钟",
            KL_TYPE.K_30M: "30分钟",
            KL_TYPE.K_60M: "60分钟",
            KL_TYPE.K_DAY: "日线",
            KL_TYPE.K_WEEK: "周线",
            KL_TYPE.K_MON: "月线",
        }
        return mapping.get(lv, lv.name)

    @staticmethod
    def _note_html(notes: List[str]) -> str:
        return "<ol>" + "".join(f"<li>{html.escape(note)}</li>" for note in notes) + "</ol>"

    def _build_report_rows(self, meta: CChanPlotMeta) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        endpoint_map: Dict[int, List[str]] = {}
        pen_rows: List[Dict[str, Any]] = []
        for i, bi in enumerate(meta.bi_list):
            direction = "up" if bi.dir == BI_DIR.UP else "down"
            begin_kind = "bottom" if bi.begin_klc_fx == FX_TYPE.BOTTOM else "top"
            end_kind = "top" if bi.end_klc_fx == FX_TYPE.TOP else "bottom"
            kl_cnt = int(bi.end_x - bi.begin_x + 1)
            amp = abs(float(bi.end_y) - float(bi.begin_y))
            notes = [
                f"成笔：{_fx_label(begin_kind)}到{_fx_label(end_kind)}且K线间隔通过，保留为有效笔",
                f"跨度：端点原始K线 {bi.begin_x} 至 {bi.end_x}，共 {kl_cnt} 根；价差 {amp:.2f}",
            ]
            if not bi.is_sure:
                notes.append("最后一笔为虚笔或尚未完全确认，后续新K线可能改写终点")
            endpoint_map.setdefault(int(bi.begin_klc_idx), []).append(f"第{i + 1}笔起点")
            endpoint_map.setdefault(int(bi.end_klc_idx), []).append(f"第{i + 1}笔终点")
            pen_rows.append({
                "idx": i + 1,
                "direction": direction,
                "begin_date": _fmt_time(bi.begin_time),
                "begin_kind": begin_kind,
                "begin_price": float(bi.begin_y),
                "end_date": _fmt_time(bi.end_time),
                "end_kind": end_kind,
                "end_price": float(bi.end_y),
                "kl_cnt": kl_cnt,
                "amp": amp,
                "status": "有效" if bi.is_sure else "未确认",
                "notes": notes,
                "target_idx": int(bi.end_x),
            })

        fx_rows: List[Dict[str, Any]] = []
        last_valid: Optional[Dict[str, Any]] = None
        for klc in meta.klc_list:
            if klc.type not in (FX_TYPE.TOP, FX_TYPE.BOTTOM):
                continue
            kind = "top" if klc.type == FX_TYPE.TOP else "bottom"
            is_valid = int(klc.idx) in endpoint_map
            date = _fmt_time(klc.klu_list[len(klc.klu_list) // 2].time) if klc.klu_list else _fmt_time(klc.time_begin)
            price = float(klc.high if klc.type == FX_TYPE.TOP else klc.low)
            high_klu = max(klc.klu_list, key=lambda x: float(x.high)) if klc.klu_list else None
            low_klu = min(klc.klu_list, key=lambda x: float(x.low)) if klc.klu_list else None
            notes = [
                f"识别到{_fx_label(kind)}形态：分型价格{_fmt_num(price)}，高点{_fmt_num(float(klc.high))}，低点{_fmt_num(float(klc.low))}",
            ]
            if is_valid:
                notes.append("作为" + "、".join(endpoint_map[int(klc.idx)]) + "保留")
                if last_valid and last_valid["kind"] == kind:
                    better = price >= float(last_valid["price"]) if kind == "top" else price <= float(last_valid["price"])
                    if better:
                        notes.append(f"同类分型归并后，当前{_fx_label(kind)}极值更强，替代前一同类端点")
                    else:
                        notes.append(f"同类分型归并后仍被保留，因后续笔结构需要该端点")
                elif last_valid:
                    notes.append(f"与前一有效{_fx_label(last_valid['kind'])}交替，满足笔端点方向要求")
                last_valid = {"kind": kind, "price": price, "date": date}
            else:
                if last_valid is None:
                    notes.append("未成为笔端点：首笔形成前的候选分型被缓存或被后续更合适端点替换")
                elif last_valid["kind"] == kind:
                    notes.append(f"未成为笔端点：与前一有效{_fx_label(kind)}同类，按极值规则保留更强者")
                else:
                    notes.append(f"未成为笔端点：与前一有效{_fx_label(last_valid['kind'])}之间未通过严格跨度或完全区间验证")
                notes.append("当前报告未记录逐步回溯日志，以上备注按最终有效笔端点反推常见过滤路径")
            fx_rows.append({
                "idx": len(fx_rows) + 1,
                "date": date,
                "kind": kind,
                "price": price,
                "high": float(klc.high),
                "high_time": _fmt_time(high_klu.time) if high_klu else "",
                "low": float(klc.low),
                "low_time": _fmt_time(low_klu.time) if low_klu else "",
                "status": "有效" if is_valid else "已过滤",
                "notes": notes,
                "target_idx": int((klc.begin_idx + klc.end_idx) / 2),
            })
        return fx_rows, pen_rows

    def _make_detail_tables(self, meta: CChanPlotMeta, chart_id: str) -> str:
        fx_rows, pen_rows = self._build_report_rows(meta)

        fx_body = []
        for row in fx_rows:
            row_class = "clickable" if row["status"] == "有效" else "clickable invalid"
            fx_body.append(
                f'<tr class="{row_class}" data-target-idx="{row["target_idx"]}">'
                f'<td>{row["idx"]}</td>'
                f'<td>{html.escape(row["date"])}</td>'
                f'<td>{_fx_label(row["kind"])}</td>'
                f'<td>{_fmt_num(row["price"])}（{html.escape(row["date"])}）</td>'
                f'<td>{_fmt_num(row["high"])}（{html.escape(row["high_time"])}）</td>'
                f'<td>{_fmt_num(row["low"])}（{html.escape(row["low_time"])}）</td>'
                f'<td>{html.escape(row["status"])}</td>'
                f'<td class="note-cell">{self._note_html(row["notes"])}</td>'
                '</tr>'
            )

        pen_body = []
        for row in pen_rows:
            pen_body.append(
                f'<tr class="clickable" data-target-idx="{row["target_idx"]}">'
                f'<td>{row["idx"]}</td>'
                f'<td>{_dir_label(row["direction"])}</td>'
                f'<td>{html.escape(row["begin_date"])}</td>'
                f'<td>{_fx_label(row["begin_kind"])}</td>'
                f'<td>{_fmt_num(row["begin_price"])}</td>'
                f'<td>{html.escape(row["end_date"])}</td>'
                f'<td>{_fx_label(row["end_kind"])}</td>'
                f'<td>{_fmt_num(row["end_price"])}</td>'
                f'<td>{row["kl_cnt"]}</td>'
                f'<td>{_fmt_num(row["amp"])}</td>'
                f'<td>{html.escape(row["status"])}</td>'
                f'<td class="note-cell">{self._note_html(row["notes"])}</td>'
                '</tr>'
            )

        return f"""
<section class="report-section">
  <div class="section-head">
    <h2>原始分型列表（形态{len(fx_rows)}个，有效{sum(1 for row in fx_rows if row["status"] == "有效")}个）</h2>
    <div class="section-actions">
      <label for="goto-{chart_id}">定位时间</label>
      <input id="goto-{chart_id}" type="text" placeholder="年/月/日 --:--">
      <button id="goto-btn-{chart_id}" type="button">确定</button>
      <button class="collapse-btn" type="button" data-collapse="fx-table-{chart_id}">收起</button>
    </div>
  </div>
  <div id="fx-table-{chart_id}" class="table-wrap">
    <table class="data-table">
      <thead><tr><th>#</th><th>日期</th><th>类型</th><th>分型价格</th><th>最高</th><th>最低</th><th>状态</th><th>备注</th></tr></thead>
      <tbody>{"".join(fx_body) if fx_body else '<tr><td colspan="8">暂无分型</td></tr>'}</tbody>
    </table>
  </div>
</section>
<section class="report-section">
  <div class="section-head">
    <h2>笔列表（候选{len(pen_rows)}笔，有效{sum(1 for row in pen_rows if row["status"] == "有效")}笔）</h2>
    <div class="section-actions">
      <button class="collapse-btn" type="button" data-collapse="pen-table-{chart_id}">收起</button>
    </div>
  </div>
  <div id="pen-table-{chart_id}" class="table-wrap">
    <table class="data-table">
      <thead><tr><th>#</th><th>方向</th><th>起点日期</th><th>起点类型</th><th>起点价格</th><th>终点日期</th><th>终点类型</th><th>终点价格</th><th>K线间隔</th><th>价差</th><th>状态</th><th>备注</th></tr></thead>
      <tbody>{"".join(pen_body) if pen_body else '<tr><td colspan="12">暂无笔</td></tr>'}</tbody>
    </table>
  </div>
</section>
"""

    def _make_chart(self, meta: CChanPlotMeta, label: str, chart_id: str) -> str:
        bars = list(meta.klu_iter())
        if len(bars) < 2:
            return '<div class="chart-shell"><p class="meta">当前级别没有足够 K 线生成图表。</p></div>'

        width, height = 1120, 560
        left, top, bottom, right = 58, 12, 30, 18
        bar_w = 8
        total_width = left + len(bars) * bar_w + right
        high = max(float(b.high) for b in bars)
        low = min(float(b.low) for b in bars)
        base_price_range = high - low if high > low else 1.0
        all_bs_points = list(meta.bs_point_lst) + list(meta.seg_bsp_lst)
        for bsp in all_bs_points:
            if bsp.is_buy:
                low = min(low, float(bsp.y) - base_price_range * 0.22)
            else:
                high = max(high, float(bsp.y) + base_price_range * 0.22)
        price_range = high - low if high > low else 1.0
        y_high = high + price_range * 0.08
        y_low = low - price_range * 0.08
        y_range = y_high - y_low
        plot_h = height - top - bottom

        def yp(price: float) -> float:
            return top + plot_h - (float(price) - y_low) / y_range * plot_h

        bar_data = []
        for i, bar in enumerate(bars):
            x = left + i * bar_w + bar_w / 2
            bar_data.append({
                "i": i,
                "dt": bar.time.to_str(),
                "o": float(bar.open),
                "h": float(bar.high),
                "l": float(bar.low),
                "c": float(bar.close),
                "x": round(x, 1),
            })

        fractals = []
        for klc in meta.klc_list:
            if klc.type not in (FX_TYPE.TOP, FX_TYPE.BOTTOM):
                continue
            x = left + (klc.begin_idx + klc.end_idx) * bar_w / 2 + bar_w / 2
            price = float(klc.high if klc.type == FX_TYPE.TOP else klc.low)
            fractals.append({
                "kind": "top" if klc.type == FX_TYPE.TOP else "bottom",
                "begin": int(klc.begin_idx),
                "end": int(klc.end_idx),
                "price": price,
                "x": round(x, 1),
                "y": round(yp(price), 1),
                "date": klc.klu_list[len(klc.klu_list) // 2].time.to_str() if klc.klu_list else "",
            })

        pens = []
        for i, bi in enumerate(meta.bi_list):
            pens.append({
                "i": i,
                "begin": int(bi.begin_x),
                "end": int(bi.end_x),
                "x1": round(left + bi.begin_x * bar_w + bar_w / 2, 1),
                "y1": round(yp(bi.begin_y), 1),
                "x2": round(left + bi.end_x * bar_w + bar_w / 2, 1),
                "y2": round(yp(bi.end_y), 1),
                "sure": bool(bi.is_sure),
                "direction": "up" if bi.end_y >= bi.begin_y else "down",
            })

        segments = []
        for i, seg in enumerate(meta.seg_list):
            segments.append({
                "i": i,
                "begin": int(seg.begin_x),
                "end": int(seg.end_x),
                "x1": round(left + seg.begin_x * bar_w + bar_w / 2, 1),
                "y1": round(yp(seg.begin_y), 1),
                "x2": round(left + seg.end_x * bar_w + bar_w / 2, 1),
                "y2": round(yp(seg.end_y), 1),
                "sure": bool(seg.is_sure),
                "direction": "up" if seg.end_y >= seg.begin_y else "down",
            })

        def collect_zs_rects(zs_list, level: str) -> List[Dict[str, Any]]:
            rects: List[Dict[str, Any]] = []
            for i, zs in enumerate(zs_list):
                if getattr(zs, "is_onebi_zs", False):
                    continue
                rects.append({
                    "i": i,
                    "level": level,
                    "x": round(left + zs.begin * bar_w, 1),
                    "y": round(yp(zs.high), 1),
                    "w": round(max(bar_w, zs.w * bar_w), 1),
                    "h": round(max(5, yp(zs.low) - yp(zs.high)), 1),
                    "low": float(zs.low),
                    "high": float(zs.high),
                    "sure": bool(zs.is_sure),
                })
                for j, sub_zs in enumerate(zs.sub_zs_lst):
                    rects.append({
                        "i": j,
                        "level": f"{level}-sub",
                        "x": round(left + sub_zs.begin * bar_w, 1),
                        "y": round(yp(sub_zs.high), 1),
                        "w": round(max(bar_w, sub_zs.w * bar_w), 1),
                        "h": round(max(5, yp(sub_zs.low) - yp(sub_zs.high)), 1),
                        "low": float(sub_zs.low),
                        "high": float(sub_zs.high),
                        "sure": bool(sub_zs.is_sure),
                    })
            return rects

        zs_rects = collect_zs_rects(meta.zs_lst, "bi") + collect_zs_rects(meta.segzs_lst, "seg")

        bs_points = []
        label_pad = base_price_range * 0.13
        for i, bsp in enumerate(all_bs_points):
            is_buy = bool(bsp.is_buy)
            label_price = float(bsp.y - label_pad if is_buy else bsp.y + label_pad)
            bs_points.append({
                "i": i,
                "x": round(left + bsp.x * bar_w + bar_w / 2, 1),
                "bar": int(bsp.x),
                "y": round(yp(float(bsp.y)), 1),
                "labelY": round(yp(label_price), 1),
                "text": bsp.desc(),
                "buy": is_buy,
                "seg": bool(bsp.is_seg),
            })

        svg: List[str] = [
            f'<svg id="svg-{chart_id}" class="chan-chart-svg" xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="{max(left, total_width - width)} 0 {width} {height}" preserveAspectRatio="none">'
        ]
        svg.append(f'<rect x="{left}" y="{top}" width="{total_width-left-right}" height="{plot_h}" fill="#fafafa" stroke="#e4e7ec"/>')
        for i in range(9):
            y = top + plot_h * i / 8
            price = y_high - y_range * i / 8
            svg.append(f'<line x1="{left}" y1="{y:.1f}" x2="{total_width-right}" y2="{y:.1f}" stroke="#eaecf0"/>')
            svg.append(f'<text x="{left-6}" y="{y:.1f}" text-anchor="end" fill="#667085" font-size="10" dominant-baseline="middle">{_fmt_num(price, 2)}</text>')

        for i, bar in enumerate(bars):
            x = left + i * bar_w
            cx = x + bar_w / 2
            up = float(bar.close) >= float(bar.open)
            color = "#b42318" if up else "#175cd3"
            body_top = yp(max(float(bar.open), float(bar.close)))
            body_bottom = yp(min(float(bar.open), float(bar.close)))
            svg.append(f'<line x1="{cx:.1f}" y1="{yp(bar.high):.1f}" x2="{cx:.1f}" y2="{yp(bar.low):.1f}" stroke="{color}" stroke-width="1"/>')
            if body_bottom - body_top < 1:
                svg.append(f'<line x1="{x:.1f}" y1="{body_top:.1f}" x2="{x+bar_w-1:.1f}" y2="{body_top:.1f}" stroke="{color}" stroke-width="1.5"/>')
            else:
                svg.append(f'<rect x="{x:.1f}" y="{body_top:.1f}" width="{bar_w-1}" height="{body_bottom-body_top:.1f}" fill="{color}"/>')

        for klc in meta.klc_list:
            if klc.end_idx <= klc.begin_idx:
                continue
            stroke = "#b42318" if klc.type == FX_TYPE.TOP else "#175cd3" if klc.type == FX_TYPE.BOTTOM else "#12b76a"
            x = left + klc.begin_idx * bar_w - 1
            w = (klc.end_idx - klc.begin_idx + 1) * bar_w + 1
            y = yp(klc.high) - 1
            h = max(5, yp(klc.low) - yp(klc.high) + 2)
            svg.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
                f'fill="none" stroke="{stroke}" stroke-width="1.2" stroke-dasharray="4 2" opacity=".75" rx="1"/>'
            )

        for zs in zs_rects:
            color = "#f79009" if zs["level"].startswith("bi") else "#d92d20"
            width_px = 2.0 if zs["level"] == "bi" else 4.0
            dash = "" if zs["sure"] else ' stroke-dasharray="7 4"'
            opacity = ".88" if zs["level"] in ("bi", "seg") else ".52"
            svg.append(
                f'<rect x="{zs["x"]:.1f}" y="{zs["y"]:.1f}" width="{zs["w"]:.1f}" height="{zs["h"]:.1f}" '
                f'fill="none" stroke="{color}" stroke-width="{width_px}" opacity="{opacity}" rx="1"{dash}/>'
            )
            if zs["level"] in ("bi", "seg"):
                svg.append(
                    f'<text x="{zs["x"] + 4:.1f}" y="{zs["y"] - 4:.1f}" fill="{color}" font-size="10">'
                    f'ZS {_fmt_num(zs["low"])}-{_fmt_num(zs["high"])}</text>'
                )

        for pen in pens:
            dash = "" if pen["sure"] else ' stroke-dasharray="5 4"'
            svg.append(
                f'<line x1="{pen["x1"]:.1f}" y1="{pen["y1"]:.1f}" x2="{pen["x2"]:.1f}" y2="{pen["y2"]:.1f}" '
                f'stroke="#111827" stroke-width="1.4" opacity=".84" stroke-linecap="round"{dash}/>'
            )

        for seg in segments:
            dash = "" if seg["sure"] else ' stroke-dasharray="7 5"'
            svg.append(
                f'<line x1="{seg["x1"]:.1f}" y1="{seg["y1"]:.1f}" x2="{seg["x2"]:.1f}" y2="{seg["y2"]:.1f}" '
                f'stroke="#067647" stroke-width="3.2" opacity=".76" stroke-linecap="round"{dash}/>'
            )

        for idx, fx in enumerate(fractals):
            x, y, price = fx["x"], fx["y"], fx["price"]
            if fx["kind"] == "top":
                svg.append(
                    f'<polygon class="chart-fractal-marker" data-fx="{idx}" points="{x:.1f},{y:.1f} {x-5:.1f},{y-9:.1f} {x+5:.1f},{y-9:.1f}" fill="#175cd3"/>'
                )
                svg.append(f'<text x="{x:.1f}" y="{y-12:.1f}" text-anchor="middle" fill="#344054" font-size="9">{_fmt_num(price)}</text>')
            else:
                svg.append(
                    f'<polygon class="chart-fractal-marker" data-fx="{idx}" points="{x:.1f},{y:.1f} {x-5:.1f},{y+9:.1f} {x+5:.1f},{y+9:.1f}" fill="#f79009"/>'
                )
                svg.append(f'<text x="{x:.1f}" y="{y+20:.1f}" text-anchor="middle" fill="#344054" font-size="9">{_fmt_num(price)}</text>')

        svg.append("<defs>")
        for bsp in bs_points:
            color = "#d92d20" if bsp["buy"] else "#067647"
            svg.append(
                f'<marker id="arrow-{chart_id}-{bsp["i"]}" markerWidth="7" markerHeight="7" refX="3.5" refY="3.5" orient="auto">'
                f'<path d="M0,0 L7,3.5 L0,7 Z" fill="{color}"/></marker>'
            )
        svg.append("</defs>")
        for bsp in bs_points:
            color = "#d92d20" if bsp["buy"] else "#067647"
            arrow_start_y = bsp["labelY"]
            text_gap = 16 if bsp["seg"] else 14
            text_y = arrow_start_y + text_gap if bsp["buy"] else arrow_start_y - text_gap
            point_y = bsp["y"]
            arrow_end_y = point_y + (6 if bsp["buy"] else -6)
            fontsize = 17 if bsp["seg"] else 15
            svg.append(
                f'<line x1="{bsp["x"]:.1f}" y1="{arrow_start_y:.1f}" x2="{bsp["x"]:.1f}" y2="{arrow_end_y:.1f}" '
                f'stroke="{color}" stroke-width="1.3" marker-end="url(#arrow-{chart_id}-{bsp["i"]})"/>'
            )
            svg.append(
                f'<text x="{bsp["x"]:.1f}" y="{text_y:.1f}" text-anchor="middle" fill="{color}" '
                f'font-size="{fontsize}" font-weight="700" dominant-baseline="middle">'
                f'{html.escape(bsp["text"])}</text>'
            )

        svg.append(f'<line id="selected-{chart_id}" x1="{left}" y1="{top}" x2="{left}" y2="{height-bottom}" stroke="#1f6f8b" stroke-width="1.4" stroke-dasharray="4 3" style="display:none;pointer-events:none"/>')
        svg.append(
            f'<g id="crosshair-{chart_id}" style="display:none;pointer-events:none">'
            f'<line id="crosshair-v-{chart_id}" x1="{left}" y1="{top}" x2="{left}" y2="{height-bottom}" stroke="#475467" stroke-width="1" stroke-dasharray="3 3"/>'
            f'<line id="crosshair-h-{chart_id}" x1="{left}" y1="{top}" x2="{total_width-right}" y2="{top}" stroke="#475467" stroke-width="1" stroke-dasharray="3 3"/>'
            f'<rect id="crosshair-price-bg-{chart_id}" x="{left}" y="{top-9}" width="54" height="18" rx="3" fill="#344054" opacity=".96"/>'
            f'<text id="crosshair-price-text-{chart_id}" x="{left+27}" y="{top}" text-anchor="middle" fill="#fff" font-size="10" dominant-baseline="middle">-</text>'
            "</g>"
        )
        svg.append("</svg>")
        detail_tables = self._make_detail_tables(meta, chart_id)

        return f"""
<div class="chart-shell">
  <div class="chart-toolbar">
    <strong>{html.escape(label)}</strong>
    <button id="zoom-in-{chart_id}" title="放大" type="button">+</button>
    <span id="zoom-label-{chart_id}" class="zoom-label">-</span>
    <button id="zoom-out-{chart_id}" title="缩小" type="button">-</button>
    <button id="reset-{chart_id}" title="重置视图" type="button">重置</button>
    <span class="chart-help">滚轮缩放 · 拖拽平移 · 双击十字星 · 悬停查看 OHLC</span>
  </div>
  <div id="wrap-{chart_id}" class="chart-wrap">
    {"".join(svg)}
    <div id="tooltip-{chart_id}" class="tooltip"></div>
  </div>
  <div class="legend">
    <span><i class="swatch" style="background:#b42318"></i>上涨K线</span>
    <span><i class="swatch" style="background:#175cd3"></i>下跌K线/顶分型</span>
    <span><i class="swatch" style="background:#f79009"></i>底分型</span>
    <span><i class="swatch" style="background:#111827"></i>笔</span>
    <span><i class="swatch" style="background:#067647"></i>段</span>
    <span><i class="swatch" style="background:#f79009"></i>中枢</span>
    <span><i class="swatch" style="background:#d92d20"></i>买点</span>
    <span><i class="swatch" style="background:#067647"></i>卖点</span>
  </div>
</div>
{detail_tables}
<script>
(function() {{
var data = {{
  bars:{_json(bar_data)},
  fractals:{_json(fractals)},
  pens:{_json(pens)},
  segments:{_json(segments)},
  zs:{_json(zs_rects)},
  bsPoints:{_json(bs_points)},
  totalBars:{len(bars)}
}};
var svg = document.getElementById('svg-{chart_id}');
var wrap = document.getElementById('wrap-{chart_id}');
var tip = document.getElementById('tooltip-{chart_id}');
var selected = document.getElementById('selected-{chart_id}');
var crosshair = document.getElementById('crosshair-{chart_id}');
var crosshairV = document.getElementById('crosshair-v-{chart_id}');
var crosshairH = document.getElementById('crosshair-h-{chart_id}');
var crosshairBg = document.getElementById('crosshair-price-bg-{chart_id}');
var crosshairText = document.getElementById('crosshair-price-text-{chart_id}');
var panelRoot = document.getElementById('{chart_id}');
var left = {left}, right = {right}, top = {top}, bottom = {bottom}, barW = {bar_w}, chartH = {height};
var totalWidth = {total_width};
var yHigh = {y_high}, yLow = {y_low}, yRange = {y_range}, plotH = {plot_h};
var viewW = {width}, viewH = chartH, originX = Math.max(left, totalWidth - viewW), originY = 0;
var minVisibleBars = Math.min(data.totalBars, 24);
var minViewW = Math.max(minVisibleBars * barW, 180);
var maxViewW = Math.max(totalWidth, minViewW);
var crosshairEnabled = false;
var crosshairPoint = null;
var isPanning = false, panStartX = 0, panStartY = 0, panOriginX = 0, panOriginY = 0;

function rect() {{
  var r = svg.getBoundingClientRect();
  return r.width && r.height ? r : {{left:0,top:0,width:{width},height:{height}}};
}}
function viewHeightForWidth(w) {{
  var r = rect();
  return Math.max(120, Math.min(chartH, w * r.height / r.width));
}}
function updateViewBox() {{
  viewW = Math.max(minViewW, Math.min(maxViewW, viewW));
  viewH = viewHeightForWidth(viewW);
  originX = Math.max(0, Math.min(Math.max(0, totalWidth - viewW), originX));
  originY = Math.max(0, Math.min(Math.max(0, chartH - viewH), originY));
  svg.setAttribute('viewBox', originX.toFixed(1) + ' ' + originY.toFixed(1) + ' ' + viewW.toFixed(1) + ' ' + viewH.toFixed(1));
  updateZoomLabel();
  updateCrosshair();
}}
function resetView() {{
  var r = rect();
  viewW = Math.max(minViewW, Math.min(maxViewW, Math.min(totalWidth, chartH * r.width / r.height)));
  viewH = viewHeightForWidth(viewW);
  originX = Math.max(0, totalWidth - viewW);
  originY = Math.max(0, (chartH - viewH) / 2);
  updateViewBox();
}}
function updateZoomLabel() {{
  document.getElementById('zoom-label-{chart_id}').textContent = Math.max(1, Math.round(viewW / barW)) + '根';
}}
function priceAtY(y) {{
  return yHigh - ((y - top) / plotH) * yRange;
}}
function svgPoint(e) {{
  var r = rect();
  return {{
    x: Math.max(left, Math.min(totalWidth - right, (e.clientX - r.left) / r.width * viewW + originX)),
    y: Math.max(top, Math.min(chartH - bottom, (e.clientY - r.top) / r.height * viewH + originY))
  }};
}}
function updateCrosshair() {{
  if (!crosshairEnabled || !crosshairPoint) return;
  var x = crosshairPoint.x, y = crosshairPoint.y, price = priceAtY(y);
  var labelW = Math.max(52, Math.min(92, String(price.toFixed(2)).length * 7 + 14));
  var labelX = Math.max(originX + 4, left);
  if (labelX + labelW > originX + viewW - 4) labelX = originX + viewW - labelW - 4;
  crosshairV.setAttribute('x1', x.toFixed(1));
  crosshairV.setAttribute('x2', x.toFixed(1));
  crosshairV.setAttribute('y1', originY.toFixed(1));
  crosshairV.setAttribute('y2', (originY + viewH).toFixed(1));
  crosshairH.setAttribute('x1', originX.toFixed(1));
  crosshairH.setAttribute('x2', (originX + viewW).toFixed(1));
  crosshairH.setAttribute('y1', y.toFixed(1));
  crosshairH.setAttribute('y2', y.toFixed(1));
  crosshairBg.setAttribute('x', labelX.toFixed(1));
  crosshairBg.setAttribute('y', (y - 9).toFixed(1));
  crosshairBg.setAttribute('width', labelW.toFixed(1));
  crosshairText.setAttribute('x', (labelX + labelW / 2).toFixed(1));
  crosshairText.setAttribute('y', y.toFixed(1));
  crosshairText.textContent = price.toFixed(2);
}}
function zoomAt(factor, rx, ry) {{
  var oldW = viewW, oldH = viewH;
  viewW = Math.max(minViewW, Math.min(maxViewW, viewW * factor));
  viewH = viewHeightForWidth(viewW);
  originX += rx * (oldW - viewW);
  originY += ry * (oldH - viewH);
  updateViewBox();
}}
function nearestBar(clientX) {{
  var r = rect();
  var mx = clientX - r.left;
  var best = -1, bestDist = Infinity;
  for (var i = 0; i < data.bars.length; i++) {{
    var px = (data.bars[i].x - originX) / viewW * r.width;
    var d = Math.abs(mx - px);
    if (d < bestDist) {{ best = i; bestDist = d; }}
  }}
  var one = barW / viewW * r.width;
  return bestDist <= one * 1.5 ? best : -1;
}}
function showTip(idx, clientX, clientY) {{
  if (idx < 0 || idx >= data.bars.length) {{ tip.style.display = 'none'; return; }}
  var b = data.bars[idx];
  selected.setAttribute('x1', b.x.toFixed(1));
  selected.setAttribute('x2', b.x.toFixed(1));
  selected.style.display = 'block';
  tip.innerHTML = '<div><b>' + b.dt + '</b></div>' +
    '<div>开盘: ' + b.o.toFixed(2) + ' | 最高: ' + b.h.toFixed(2) + '</div>' +
    '<div>收盘: ' + b.c.toFixed(2) + ' | 最低: ' + b.l.toFixed(2) + '</div>';
  tip.style.display = 'block';
  var wr = wrap.getBoundingClientRect();
  var x = clientX - wr.left + 12;
  var y = clientY - wr.top - 10;
  if (x + 210 > wr.width) x = clientX - wr.left - 220;
  if (x < 4) x = 4;
  if (y < 4) y = 4;
  if (y + 78 > wr.height) y = wr.height - 82;
  tip.style.left = x + 'px';
  tip.style.top = y + 'px';
}}
function focusBar(idx, shouldScroll) {{
  idx = Math.max(0, Math.min(data.bars.length - 1, Number(idx) || 0));
  var b = data.bars[idx];
  var desiredW = Math.min(maxViewW, Math.max(minViewW, 96 * barW));
  viewW = desiredW;
  viewH = viewHeightForWidth(viewW);
  originX = b.x - viewW * 0.5;
  originY = Math.max(0, (chartH - viewH) / 2);
  updateViewBox();
  selected.setAttribute('x1', b.x.toFixed(1));
  selected.setAttribute('x2', b.x.toFixed(1));
  selected.style.display = 'block';
  if (shouldScroll) wrap.scrollIntoView({{behavior:'smooth', block:'center'}});
}}
function findBarByTime(value) {{
  value = String(value || '').trim();
  if (!value) return -1;
  var normalized = value.replace(/[年月]/g, '/').replace(/[日]/g, '').replace(/-/g, '/').replace(/\\s+/g, ' ');
  var best = -1;
  for (var i = 0; i < data.bars.length; i++) {{
    var dt = data.bars[i].dt.replace(/-/g, '/');
    if (dt.indexOf(normalized) >= 0 || normalized.indexOf(dt) >= 0) return i;
    if (dt.slice(0, 10) === normalized.slice(0, 10)) best = i;
  }}
  return best;
}}

wrap.addEventListener('wheel', function(e) {{
  e.preventDefault();
  var r = rect();
  zoomAt(e.deltaY < 0 ? 0.70 : 1.43, Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)), Math.max(0, Math.min(1, (e.clientY - r.top) / r.height)));
}}, {{passive:false}});
wrap.addEventListener('mousedown', function(e) {{
  if (e.button !== 0) return;
  isPanning = true; panStartX = e.clientX; panStartY = e.clientY; panOriginX = originX; panOriginY = originY;
  svg.style.cursor = 'grabbing';
}});
window.addEventListener('mousemove', function(e) {{
  if (isPanning) {{
    var r = rect();
    originX = panOriginX + (panStartX - e.clientX) / r.width * viewW;
    originY = panOriginY + (panStartY - e.clientY) / r.height * viewH;
    updateViewBox();
    return;
  }}
  var p = svgPoint(e);
  if (crosshairEnabled) {{ crosshairPoint = p; updateCrosshair(); }}
  var idx = nearestBar(e.clientX);
  if (idx >= 0 && p.y >= top && p.y <= chartH - bottom) showTip(idx, e.clientX, e.clientY);
  else tip.style.display = 'none';
}});
window.addEventListener('mouseup', function() {{
  isPanning = false; svg.style.cursor = 'grab';
}});
wrap.addEventListener('mouseleave', function() {{ tip.style.display = 'none'; }});
wrap.addEventListener('dblclick', function(e) {{
  e.preventDefault();
  if (crosshairEnabled) {{
    crosshairEnabled = false; crosshairPoint = null; crosshair.style.display = 'none';
  }} else {{
    crosshairEnabled = true; crosshairPoint = svgPoint(e); crosshair.style.display = 'block'; updateCrosshair();
  }}
}});
document.getElementById('zoom-in-{chart_id}').addEventListener('click', function() {{ zoomAt(0.5, 0.5, 0.5); }});
document.getElementById('zoom-out-{chart_id}').addEventListener('click', function() {{ zoomAt(2, 0.5, 0.5); }});
document.getElementById('reset-{chart_id}').addEventListener('click', function() {{ tip.style.display = 'none'; resetView(); }});
panelRoot.querySelectorAll('tr[data-target-idx]').forEach(function(row) {{
  row.addEventListener('click', function() {{
    panelRoot.querySelectorAll('tr.selected-row').forEach(function(x) {{ x.classList.remove('selected-row'); }});
    row.classList.add('selected-row');
    focusBar(row.getAttribute('data-target-idx'), true);
  }});
}});
panelRoot.querySelectorAll('.collapse-btn').forEach(function(btn) {{
  btn.addEventListener('click', function() {{
    var target = document.getElementById(btn.getAttribute('data-collapse'));
    if (!target) return;
    var hidden = target.style.display === 'none';
    target.style.display = hidden ? '' : 'none';
    btn.textContent = hidden ? '收起' : '展开';
  }});
}});
document.getElementById('goto-btn-{chart_id}').addEventListener('click', function() {{
  var idx = findBarByTime(document.getElementById('goto-{chart_id}').value);
  if (idx >= 0) focusBar(idx, true);
}});
document.getElementById('goto-{chart_id}').addEventListener('keydown', function(e) {{
  if (e.key === 'Enter') document.getElementById('goto-btn-{chart_id}').click();
}});
window.addEventListener('resize', updateZoomLabel);
resetView();
}})();
</script>
"""
