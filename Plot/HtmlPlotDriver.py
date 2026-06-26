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


def _seg_dir_label(direction: str) -> str:
    return "向上线段" if direction == "up" else "向下线段"


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
main {{ max-width:1557px; margin:0 auto; padding:16px; }}
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
.chart-shell {{ background:#101826; border:1px solid #263244; border-radius:8px; padding:10px; }}
.chart-toolbar {{ display:flex; align-items:center; gap:6px; flex-wrap:wrap; margin-bottom:8px; }}
.chart-toolbar button {{
  min-width:34px; height:30px; padding:0 10px; border:1px solid #344054;
  border-radius:4px; background:#151f30; color:#d0d5dd; cursor:pointer;
}}
.chart-toolbar button:hover {{ background:#1d2939; }}
.chart-toolbar button.active {{
  border-color:#f59e0b;
  background:#2a2433;
  color:#fef3c7;
}}
.chart-toolbar strong {{ color:#f2f4f7; }}
.zoom-label {{ color:#98a2b3; font-size:13px; min-width:62px; text-align:center; }}
.chart-help {{ margin-left:auto; color:#7d89a1; font-size:12px; }}
.chart-wrap {{
  position:relative; overflow:hidden; height:clamp(420px,72vh,820px);
  border:1px solid #263244; border-radius:6px; background:#111827; touch-action:none;
}}
.chan-chart-svg {{ width:100%; height:100%; display:block; background:#111827; cursor:grab; }}
.chan-chart-svg line,.chan-chart-svg rect,.chan-chart-svg polygon,.chan-chart-svg circle,.chan-chart-svg text {{
  pointer-events:none;
}}
.chan-chart-svg text {{
  paint-order:stroke; stroke:#111827; stroke-width:3px; stroke-linejoin:round;
}}
.chan-chart-svg line,.chan-chart-svg rect,.chan-chart-svg polygon,.chan-chart-svg circle {{
  vector-effect:non-scaling-stroke;
}}
.ma-layer {{ display:none; }}
.ma-layer.active {{ display:inline; }}
.kline-layer {{ display:none; }}
.kline-layer.active {{ display:inline; }}
.eigen-layer {{ display:none; }}
.eigen-layer.active {{ display:inline; }}
.fractal-detail-layer {{ display:none; }}
.fractal-detail-layer.active {{ display:inline; }}
.chart-wrap.is-panning .fractal-detail-layer,
.chart-wrap.is-panning .chart-price-label,
.chart-wrap.is-panning .chart-note-label,
.chart-wrap.is-panning .chart-bsp-label,
.chart-wrap.is-zooming .fractal-detail-layer,
.chart-wrap.is-zooming .chart-price-label,
.chart-wrap.is-zooming .chart-note-label,
.chart-wrap.is-zooming .chart-bsp-label,
.chart-wrap.is-zooming .fractal-range-box,
.chart-wrap.is-zooming .fractal-ref-box {{ display:none; }}
.chan-chart-svg .chart-price-label {{ cursor:pointer; opacity:.82; pointer-events:all; }}
.crosshair-price-text {{ stroke-width:1px; }}
.chart-bsp-label {{ vector-effect:non-scaling-stroke; }}
.chan-chart-svg .chart-pen-line,
.chan-chart-svg .chart-pen-hit,
.chan-chart-svg .chart-seg-line,
.chan-chart-svg .chart-seg-hit,
.chan-chart-svg .chart-fractal-marker {{ pointer-events:all; }}
.chart-pen-line,.chart-seg-line {{ cursor:pointer; }}
.fractal-range-box {{ pointer-events:none; }}
.fractal-ref-box {{ pointer-events:none; }}
.chart-fractal-marker.fx-ref-active {{ filter:drop-shadow(0 0 4px rgba(245,158,11,.95)); }}
.chart-price-label.fx-ref-active {{ fill:#fef08a; font-weight:700; }}
.chart-fractal-marker:hover {{ filter:drop-shadow(0 0 3px rgba(247,144,9,.85)); }}
.chart-seg-line.focused-seg {{ filter:drop-shadow(0 0 5px rgba(132,204,22,.9)); }}
.tooltip {{
  position:absolute; z-index:5; display:none; min-width:190px; padding:8px 10px;
  border:1px solid #344054; border-radius:4px; background:rgba(15,23,42,.96);
  box-shadow:0 10px 28px rgba(0,0,0,.28); color:#e5e7eb; font-size:12px;
  pointer-events:none;
}}
.legend {{ display:flex; gap:14px; flex-wrap:wrap; color:#98a2b3; font-size:12px; margin-top:8px; }}
.swatch {{ display:inline-block; width:10px; height:10px; margin-right:5px; vertical-align:-1px; }}
.logic-source {{ display:none; }}
.logic-table-wrap {{
  overflow:auto;
  border:1px solid #d0d5dd;
  border-radius:6px;
  margin:12px 0 16px;
  background:#fff;
}}
.logic-compare-table {{
  width:100%;
  min-width:1120px;
  border-collapse:collapse;
  font-size:13px;
  line-height:1.55;
}}
.logic-compare-table th {{
  position:sticky;
  top:0;
  z-index:1;
  background:#eef2f6;
  color:#101828;
  text-align:left;
  border-bottom:1px solid #d0d5dd;
  padding:8px 10px;
  white-space:nowrap;
}}
.logic-compare-table td {{
  border-bottom:1px solid #e4e7ec;
  padding:9px 10px;
  vertical-align:top;
  color:#344054;
}}
.logic-compare-table td:first-child {{
  width:88px;
  color:#101828;
  font-weight:700;
  white-space:nowrap;
}}
.logic-compare-table code {{
  background:#f2f4f7;
  padding:1px 4px;
  border-radius:3px;
}}
.report-section {{
  margin-top:14px; background:var(--panel); border:1px solid var(--line); border-radius:6px;
  padding:14px; overflow:hidden;
}}
.section-head {{ display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:10px; }}
.section-head h2 {{ margin:0; font-size:17px; line-height:1.3; }}
.section-actions {{ display:flex; align-items:center; gap:8px; color:var(--muted); font-size:12px; }}
.goto-control {{
  display:flex;
  align-items:center;
  gap:6px;
}}
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
.data-table tr.focused-row {{ outline:2px solid #1570ef; outline-offset:-2px; background:#eff8ff; }}
.note-cell {{ min-width:380px; line-height:1.55; }}
.note-cell ol {{ margin:0; padding-left:18px; }}
.fx-note-ref {{
  display:inline;
  height:auto;
  min-width:0;
  padding:1px 5px;
  border:1px solid #f59e0b;
  border-radius:3px;
  background:#fffbeb;
  color:#9a3412;
  font:inherit;
  font-weight:700;
  cursor:pointer;
}}
.fx-note-ref:hover {{ background:#fef3c7; }}
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
  .goto-control {{ width:100%; }}
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
    </div>
  </header>
  {"".join(panels)}
  <section id="logic-content" class="logic-source">
    {self._logic_content_html()}
  </section>
</main>
<script>
(function() {{
function runScripts(scope) {{
  Array.prototype.slice.call(scope.querySelectorAll('script')).forEach(function(oldScript) {{
    var newScript = document.createElement('script');
    Array.prototype.slice.call(oldScript.attributes).forEach(function(attr) {{
      newScript.setAttribute(attr.name, attr.value);
    }});
    newScript.text = oldScript.textContent;
    oldScript.parentNode.replaceChild(newScript, oldScript);
  }});
}}
function bindTimeframeTabs(root) {{
  root.querySelectorAll('.tf-tab').forEach(function(tab) {{
    tab.addEventListener('click', function() {{
      if (tab.tagName === 'A') return;
      root.querySelectorAll('.tf-tab').forEach(function(x) {{ x.classList.remove('active'); }});
      root.querySelectorAll('.tf-panel').forEach(function(x) {{ x.classList.remove('active'); }});
      tab.classList.add('active');
      var panel = root.querySelector('#' + CSS.escape(tab.getAttribute('data-target')));
      if (panel) panel.classList.add('active');
    }});
  }});
}}
function setSignature(signature) {{
  if (!signature) return;
  var meta = document.querySelector('meta[name="chan-chart-signature"]');
  if (!meta) {{
    meta = document.createElement('meta');
    meta.setAttribute('name', 'chan-chart-signature');
    document.head.appendChild(meta);
  }}
  meta.setAttribute('content', signature);
}}
function applyChartHtml(htmlText, signature) {{
  var viewState = window.__chanCaptureViews ? window.__chanCaptureViews() : null;
  var parser = new DOMParser();
  var nextDoc = parser.parseFromString(htmlText, 'text/html');
  var nextMain = nextDoc.getElementById('report-page');
  var currentMain = document.getElementById('report-page');
  if (!nextMain || !currentMain) return false;
  var nextTitle = nextDoc.querySelector('title');
  if (nextTitle) document.title = nextTitle.textContent;
  setSignature(signature);
  if (window.__chanChartAbortControllers) {{
    window.__chanChartAbortControllers.forEach(function(controller) {{
      try {{ controller.abort(); }} catch (err) {{}}
    }});
    window.__chanChartAbortControllers = [];
  }}
  currentMain.replaceWith(nextMain);
  bindTimeframeTabs(nextMain);
  runScripts(nextMain);
  if (viewState && window.__chanRestoreViews) window.__chanRestoreViews(viewState);
  return true;
}}
bindTimeframeTabs(document);
window.addEventListener('message', function(event) {{
  if (event.origin !== window.location.origin) return;
  var data = event.data || {{}};
  if (data.type !== 'chan-chart-update' || !data.html) return;
  if (applyChartHtml(data.html, data.signature)) {{
    window.parent.postMessage({{
      type: 'chan-chart-updated',
      signature: data.signature || ''
    }}, window.location.origin);
  }}
}});
}})();
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
    def _note_html(notes: List[Any]) -> str:
        def render_note(note: Any) -> str:
            if isinstance(note, dict) and "html" in note:
                return str(note["html"])
            return html.escape(str(note))

        return "<ol>" + "".join(f"<li>{render_note(note)}</li>" for note in notes) + "</ol>"

    @staticmethod
    def _fx_note_ref(row: Dict[str, Any], prefix: str = "") -> str:
        text = f'{prefix}{row["date"]} {_fx_label(row["kind"])} #{row["idx"]} {_fmt_num(row["price"])}'
        title = f'高亮 {row["date"]} {_fx_label(row["kind"])}'
        return (
            f'<button class="fx-note-ref" type="button" data-fx-ref="{row["idx"]}" '
            f'title="{html.escape(title)}">{html.escape(text)}</button>'
        )

    @staticmethod
    def _time_input_type(label: str) -> str:
        return "date" if label in ("日线", "周线", "月线") else "datetime-local"

    @staticmethod
    def _logic_content_html() -> str:
        return """
<div class="logic-guide">
  <div class="logic-intro">
    <h1>当前分型与笔划分逻辑</h1>
    <p>本说明按本报告的实际计算链路展开：原始 K 线先做包含处理，随后在合并 K 线上识别顶底分型，再按成笔条件筛选为有效端点，最后生成笔列表和图上标注。</p>
  </div>
  <div class="logic-tabs" role="tablist" aria-label="划分逻辑章节">
    <button class="logic-tab active" type="button" data-logic-tab="include">包含处理</button>
    <button class="logic-tab" type="button" data-logic-tab="fractal">分型识别</button>
    <button class="logic-tab" type="button" data-logic-tab="filter">分型过滤</button>
    <button class="logic-tab" type="button" data-logic-tab="pen">笔构造</button>
    <button class="logic-tab" type="button" data-logic-tab="gap">缺口处理</button>
    <button class="logic-tab" type="button" data-logic-tab="segment">段划分</button>
    <button class="logic-tab" type="button" data-logic-tab="segment-v2">线段v2.0</button>
    <button class="logic-tab" type="button" data-logic-tab="segment-doubao">线段-豆包</button>
    <button class="logic-tab" type="button" data-logic-tab="segment-doubao2">线段-豆包2</button>
    <button class="logic-tab" type="button" data-logic-tab="segment-doubao3">线段-豆包3</button>
    <button class="logic-tab" type="button" data-logic-tab="report">表格口径</button>
  </div>
  <section class="logic-tab-panel active" data-logic-panel="include">
    <h2>1. K线包含处理</h2>
    <p>本级别原始 K 线进入计算后，会先合并相邻的包含关系。后续的分型识别不是直接拿原始 K 线做三根比较，而是拿合并后的 K 线，也就是代码中的 <code>CKLine</code>。</p>
    <div class="logic-grid">
      <div class="logic-card">
        <h3>什么时候算包含</h3>
        <p>若两根相邻 K 线的高低点区间互相包含，例如 A 的高点大于等于 B 的高点且 A 的低点小于等于 B 的低点，或反过来 B 包住 A，就会进入合并流程。</p>
        <p>合并后的 K 线会保留内部原始 K 线列表，所以表格里仍能回看它覆盖了哪些原始 K。</p>
      </div>
      <div class="logic-card">
        <h3>方向决定合并后的高低</h3>
        <p>上升方向合并时：高点取更高值，低点也取更高值；下降方向合并时：高点取更低值，低点也取更低值。</p>
        <pre><code>向上合并: high = max(high1, high2), low = max(low1, low2)
向下合并: high = min(high1, high2), low = min(low1, low2)</code></pre>
      </div>
    </div>
    <div class="logic-example">
      <strong>例子：</strong>若当前方向向上，前一根范围是 10.00-12.00，后一根范围是 11.00-11.80，后一根被包含。合并后不是简单保留 10.00-12.00，而是保留 11.00-12.00，因为上升包含处理会把低点抬高。这样做的目的，是减少包含关系造成的分型假信号。
    </div>
  </section>
  <section class="logic-tab-panel" data-logic-panel="fractal">
    <h2>2. 原始分型识别</h2>
    <p>包含处理完成后，系统逐根检查合并 K 线的前、中、后三根。只有中间这根合并 K 与左右两根构成明确高低关系时，才会标记为顶分型或底分型。</p>
    <div class="logic-rule-table">
      <div><strong>顶分型</strong><span>pre.high &lt; self.high，next.high &lt; self.high，并且 pre.low &lt; self.low，next.low &lt; self.low。中间合并 K 的高点和低点都高于两侧。</span></div>
      <div><strong>底分型</strong><span>pre.high &gt; self.high，next.high &gt; self.high，并且 pre.low &gt; self.low，next.low &gt; self.low。中间合并 K 的高点和低点都低于两侧。</span></div>
    </div>
    <div class="logic-grid">
      <div class="logic-card">
        <h3>分型价格</h3>
        <p>顶分型价格取中间合并 K 的 high，底分型价格取中间合并 K 的 low。这是图上三角形旁边的价格，也是笔端点价格的来源。</p>
      </div>
      <div class="logic-card">
        <h3>分型最高/最低</h3>
        <p>为了判断两个分型是否重叠，表格中的“分型最高/分型最低”按前、中、后三个合并 K 及其内部原始 K 取极值，不只看中间 K。</p>
      </div>
    </div>
    <div class="logic-example">
      <strong>例子：</strong>某顶分型的中间 K 高点是 4233.43，但前后两根合并 K 的最低点可能分别是 4231.26、4231.56。用于完全区间验证时，顶分型下沿要看三根合并 K 的最低值，而不是只看 4233.43 这根中间 K。
    </div>
  </section>
  <section class="logic-tab-panel" data-logic-panel="filter">
    <h2>3. 分型过滤与有效端点</h2>
    <p>原始分型只说明图形上出现了顶或底，但不代表它一定能成为笔端点。能进入笔列表的分型才会被标记为“有效”，其他会在原始分型列表里显示为“已过滤”。</p>
    <div class="logic-grid">
      <div class="logic-card">
        <h3>同类分型归并</h3>
        <p>如果一笔已经成立后又出现同方向更极端分型，系统会尝试更新上一笔终点：顶分型优先更高者，底分型优先更低者。但更新后仍必须用原笔起点和新终点重新校验成笔条件。</p>
      </div>
      <div class="logic-card">
        <h3>顶底必须交替</h3>
        <p>一笔的两个端点必须一顶一底。顶到顶、底到底不会直接构成新笔，除非它替代了上一端点并使整体结构继续成立。</p>
      </div>
      <div class="logic-card">
        <h3>跨度必须足够</h3>
        <p>当前 <code>bi_strict=True</code>，严格模式下端点之间的合并 K 跨度至少需要达到 4。若中间合并 K 数量不足，即使价格形态看起来像反向分型，也不会成笔。</p>
      </div>
      <div class="logic-card">
        <h3>区间必须通过验证</h3>
        <p>当前 <code>bi_fx_check=totally</code>，使用最严格的完全分离检查。它要求两个端点分型的三根合并 K 区间完全错开；即使是成笔后的终点更新，也要用最终起点和新终点复验。终点更新不能借用缺口后反向豁免跳过该检查，区间重合时不能成为有效端点。</p>
      </div>
    </div>
  </section>
  <section class="logic-tab-panel" data-logic-panel="pen">
    <h2>4. 笔构造规则</h2>
    <p>笔由相邻有效分型端点构成。底分型到顶分型是向上笔，顶分型到底分型是向下笔。构造时会依次检查方向、跨度、端点区间和最后一笔是否确认。</p>
    <div class="logic-rule-table">
      <div><strong>顶到底</strong><span>顶分型的三根合并 K 最低点必须高于底分型的三根合并 K 最高点：<code>top_self_low &gt; bottom_item_high</code>。</span></div>
      <div><strong>底到顶</strong><span>底分型的三根合并 K 最高点必须低于顶分型的三根合并 K 最低点：<code>bottom_cur_high &lt; top_item_low</code>。</span></div>
    </div>
    <div class="logic-example">
      <strong>例子：</strong>顶分型 A 的三根合并 K 最低值是 4231.26，底分型 B 的三根合并 K 最高值是 4231.16。因为 4231.26 &gt; 4231.16，在 <code>totally</code> 模式下价格区间刚好完全分离，所以这组顶到底可以通过区间验证。若 B 的最高值等于或高于 4231.26，就会被视为区间未完全分离。
    </div>
    <div class="logic-example">
      <strong>虚笔说明：</strong>最后一笔可能随最新 K 线变化而调整。如果终点还没完全确认，表格状态会显示“未确认”，后续行情可能改写最后一个端点。
    </div>
  </section>
  <section class="logic-tab-panel" data-logic-panel="gap">
    <h2>5. 缺口处理</h2>
    <p>当前算法没有把缺口作为分型的独立确认条件。缺口主要影响两个位置：一是笔在跨度不足时是否允许破格成笔，二是 <code>seg_algo=chan</code> 线段算法里的特征序列分型确认。</p>
    <div class="logic-grid">
      <div class="logic-card">
        <h3>缺口如何识别</h3>
        <p>相邻合并 K 之间如果价格区间没有重叠，就认为两者之间有缺口。代码用原始 K 极值区间判断：前一合并 K 的内部最低/最高，与后一合并 K 的内部最低/最高不重叠。</p>
        <pre><code>has_gap = not has_overlap(
  prev_min_low, prev_max_high,
  next_min_low, next_max_high,
  equal=True
)</code></pre>
      </div>
      <div class="logic-card">
        <h3>当前页面配置</h3>
        <p>当前图表服务没有显式设置 <code>gap_as_kl</code>，因此走 <code>CChanConfig</code> 默认值 <code>gap_as_kl=True</code>。</p>
        <p>实际效果：缺口不会累计增加 K 线数量，只在反向跳空严格突破前一笔起点极值时，豁免该候选笔的最小跨度限制。</p>
      </div>
    </div>
    <div class="logic-rule-table">
      <div><strong>gap_as_kl=False</strong><span>端点跨度只按合并 K 索引差计算：<code>span = end_idx - begin_idx</code>。即使中间有缺口，也不会降低成笔所需的实际合并 K 数量。</span></div>
      <div><strong>gap_as_kl=True</strong><span>检查候选区间内是否存在有效破格缺口。向上笔要求向上跳空的缺口上沿严格高于前一笔起点顶；向下笔要求向下跳空的缺口下沿严格低于前一笔起点底。</span></div>
    </div>
    <div class="logic-example">
      <strong>笔的例子：</strong>严格模式下成笔要求跨度至少为 4。当前 <code>gap_as_kl=True</code> 时不会把每个缺口都补成一根 K；只有第一个满足反向突破前一笔起点极值的缺口，才允许候选笔跳过跨度和 <code>bi_fx_check</code> 区间重叠限制。
    </div>
    <div class="logic-grid">
      <div class="logic-card">
        <h3>缺口与分型</h3>
        <p>分型识别仍然只看前、中、后三根合并 K 的高低关系。缺口只会通过价格断层自然改变这些高低关系，不会额外生成或取消分型。</p>
      </div>
      <div class="logic-card">
        <h3>缺口与成笔验证</h3>
        <p>缺口破格会影响 <code>satisfy_bi_span</code> 和 <code>bi_fx_check</code>。有效反向跳空突破前一笔起点极值后，即使端点分型三 K 区间重叠或共用 K，也允许成笔；但仍必须通过顶底交替、同类极值替换和 <code>bi_end_is_peak</code> 等端点极值条件。</p>
      </div>
      <div class="logic-card">
        <h3>缺口后的反向分型</h3>
        <p>缺口破格笔成立后，缺口区间不作为后续反向分型的禁区。紧接着从缺口笔终点发起的反向候选笔，如果跨度和端点极值满足要求，即使三 K 区间与前一缺口区间重合，也允许跳过 <code>bi_fx_check</code>；该豁免只作用于缺口笔之后的第一条反向候选，不会连续借用同一个缺口生成多笔。</p>
      </div>
      <div class="logic-card">
        <h3>缺口与线段</h3>
        <p>默认 <code>seg_algo=chan</code> 使用特征序列。若特征序列分型的中间元素与前一元素之间有缺口，会标记 <code>gap=True</code>；此时线段结束不会直接确认，而是继续查找反向分型作为确认。</p>
      </div>
      <div class="logic-card">
        <h3>线段算法差异</h3>
        <p><code>seg_algo=chan</code> 会走 <code>CEigen.gap</code> 分支；其他线段算法如 <code>1+1</code> 或 <code>break</code> 主要按笔高低突破关系划分，不使用这套特征序列缺口确认逻辑。</p>
      </div>
    </div>
    <div class="logic-example">
      <strong>线段的例子：</strong>上升线段寻找下降笔构成的特征序列顶分型时，如果中间特征元素形成顶分型，同时它和前一个特征元素之间出现向上断开的价格区间，系统会先标记缺口。此时不能只凭这个特征序列分型立刻确认线段结束，还要看后面是否出现反向分型证据。
    </div>
    <div class="logic-rule-table">
      <div><strong>缺口与中枢</strong><span>中枢没有单独的缺口规则。中枢创建、延伸、合并仍按笔或线段区间是否重叠判断。缺口只会通过笔/线段的高低区间间接影响是否能形成重叠。</span></div>
      <div><strong>边界规则</strong><span>等于前一笔起点极值不算突破；连续多个缺口不累计、不拆成多笔；缺口是否回补不取消已经成立的缺口笔；后续反向分型按上一笔终点重新判定，缺口区间不作为禁区。</span></div>
    </div>
  </section>
  <section class="logic-tab-panel" data-logic-panel="segment">
    <h2>6. 段划分逻辑</h2>
    <p>段是在已经生成的笔列表上继续划分出来的更高一级结构。页面上方可以切换 <code>seg_algo</code>；默认 <code>chan</code> 使用当前稳定的特征序列逻辑，<code>chan_v2</code> 会按线段v2.0口径保留第一、第二特征元素的缺口关系，因此画出的线段可能不同。</p>
    <div class="logic-grid">
      <div class="logic-card">
        <h3>输入对象</h3>
        <p>线段只读取有效笔序列。图上灰白线是笔，绿色粗线是段；段的起止点来自笔的起止点，不会绕过笔直接连接原始 K 线分型。</p>
      </div>
      <div class="logic-card">
        <h3>基本方向</h3>
        <p>上升段由向上推进的笔结构构成，下降段由向下推进的笔结构构成。段的划分会跟随笔的确认和改写而调整，最后一段可能随最新笔变化。</p>
      </div>
      <div class="logic-card">
        <h3>特征序列</h3>
        <p><code>seg_algo=chan</code> 会把相反方向的笔抽成特征序列，再在特征序列上寻找顶/底分型，用来判断当前段是否结束。</p>
      </div>
      <div class="logic-card">
        <h3>确认与未确认</h3>
        <p>线段结束不是只看某一笔的高低点突破，还要看特征序列分型是否确认。若证据不足，图上最后一段可能处于可改写状态。</p>
      </div>
    </div>
    <div class="logic-rule-table">
      <div><strong>上升段结束</strong><span>从下降笔组成的特征序列中寻找顶分型；出现有效特征序列顶分型后，才具备结束上升段的条件。</span></div>
      <div><strong>下降段结束</strong><span>从上升笔组成的特征序列中寻找底分型；出现有效特征序列底分型后，才具备结束下降段的条件。</span></div>
    </div>
    <div class="logic-grid">
      <div class="logic-card">
        <h3>段与缺口</h3>
        <p>线段层面的缺口使用特征序列元素之间的价格断层判断。若特征序列分型的中间元素与前一元素之间存在缺口，会先标记 <code>gap=True</code>。</p>
      </div>
      <div class="logic-card">
        <h3>有缺口时的确认</h3>
        <p>当特征序列分型带缺口时，系统不会仅凭该分型立刻确认线段结束，而是继续等待后续反向分型或补充结构来确认。</p>
      </div>
      <div class="logic-card">
        <h3>与笔缺口不同</h3>
        <p>笔上的 <code>gap_as_kl</code> 规则用于判断候选笔是否可破格成笔；段上的缺口用于特征序列确认，两者作用层级不同。</p>
      </div>
      <div class="logic-card">
        <h3>中枢关系</h3>
        <p>中枢按笔或段的区间重叠生成、延伸和合并。段改变后，段级别中枢也会随段的起止区间重新计算。</p>
      </div>
    </div>
    <div class="logic-example">
      <strong>例子：</strong>一段上升走势中，后续下降笔构成的特征序列出现顶分型，但该顶分型中间元素与前一元素之间有缺口，此时不会立即确认上升段结束；只有后续走势给出反向确认后，段终点才会落定。
    </div>
  </section>
  <section class="logic-tab-panel" data-logic-panel="segment-v2">
    <h2>7. 线段v2.0</h2>
    <p>本节说明页面选择 <code>seg_algo=chan_v2</code> 时，线段是怎样从笔列表一步一步画出来的。线段v2.0 不直接读取原始 K 线高低点，也不跳过笔去连接普通分型；它的输入是已经生成的有效笔序列，核心证据是“当前疑似线段里的反向笔组成的特征序列”。</p>
    <div class="logic-grid">
      <div class="logic-card">
        <h3>当前代码入口</h3>
        <p>页面下拉选择 <code>线段 v2.0</code> 后，服务端传入 <code>seg_algo=chan_v2</code>，最终由 <code>CSegListChanV2</code> 计算。</p>
        <pre><code>update()
  do_init()
  cal_seg_sure()
    CEigenFXV2.add()
    treat_fx_eigen()
  collect_left_seg()</code></pre>
      </div>
      <div class="logic-card">
        <h3>输入是什么</h3>
        <p>输入是笔列表，也就是图上的灰白笔线。笔已经完成 K 线包含、顶底分型识别、成笔过滤、缺口破格等前置步骤。线段v2.0 不会重新做这些前置判断。</p>
      </div>
      <div class="logic-card">
        <h3>输出是什么</h3>
        <p>输出是图上的粗段线和线段列表。线段起点、终点都取自笔端点；确认段用实线，尾部证据不足的段用虚线或未确认状态显示。</p>
      </div>
      <div class="logic-card">
        <h3>最小门槛</h3>
        <p>一条确认线段至少要覆盖三笔，并且起止方向、起止价格要符合上升段或下降段的基本方向约束。不满足时，即使临时收集成段，也会标为未确认。</p>
      </div>
    </div>
    <h3>名词定义</h3>
    <div class="logic-rule-table">
      <div><strong>笔</strong><span>由有效顶底分型连接出来的基础走势单元。页面上灰白细线就是笔。</span></div>
      <div><strong>线段</strong><span>由连续笔组成的更高一级走势单元。页面上粗线就是线段，表格中会列出起止笔、起止价格、笔数和状态。</span></div>
      <div><strong>向上线段</strong><span>从底部笔端点开始，向上推进到顶部笔端点。它是否结束，要观察其中的下降笔。</span></div>
      <div><strong>向下线段</strong><span>从顶部笔端点开始，向下推进到底部笔端点。它是否结束，要观察其中的上升笔。</span></div>
      <div><strong>特征序列</strong><span>判断当前线段是否结束时抽取的一组反向笔。上升段取下降笔，下降段取上升笔。</span></div>
      <div><strong>特征序列元素</strong><span>特征序列里的一项，通常对应一根反向笔，包含高点、低点、对应笔索引和确认状态。</span></div>
      <div><strong>特征序列分型</strong><span>特征序列内部三元素形成的顶/底结构。它不是原始 K 线分型，而是“反向笔序列”上的分型。</span></div>
      <div><strong>缺口</strong><span>特征序列分型中，中间元素和前一元素之间出现价格断层。缺口会改变线段结束的确认路径。</span></div>
      <div><strong>确认线段</strong><span>证据充分、可作为后续中枢和买卖点计算依据的线段。表格状态显示为“有效”。</span></div>
      <div><strong>未确认线段</strong><span>尾部走势已经形成候选段，但证据仍可能被后续新笔改写。表格状态显示为“未确认”。</span></div>
    </div>
    <h3>方向与特征序列</h3>
    <div class="logic-grid">
      <div class="logic-card">
        <h3>上升段怎么判断结束</h3>
        <p>假设当前线段向上，笔序列可以抽象成 <code>U1, D2, U3, D4, U5, D6...</code>。系统取 <code>D2, D4, D6...</code> 作为特征序列。只有这些下降笔在特征序列里形成有效顶分型，才具备结束上升段的条件。</p>
      </div>
      <div class="logic-card">
        <h3>下降段怎么判断结束</h3>
        <p>假设当前线段向下，笔序列可以抽象成 <code>D1, U2, D3, U4, D5, U6...</code>。系统取 <code>U2, U4, U6...</code> 作为特征序列。只有这些上升笔在特征序列里形成有效底分型，才具备结束下降段的条件。</p>
      </div>
      <div class="logic-card">
        <h3>为什么看反向笔</h3>
        <p>线段结束本质上是原方向被反向结构破坏。上升段要看下跌笔是否形成足够强的反向结构；下降段要看上升笔是否形成足够强的反向结构。</p>
      </div>
      <div class="logic-card">
        <h3>图上怎么核对</h3>
        <p>打开图表上的“特征”按钮，会显示特征序列框。红色/蓝色框对应不同方向的特征序列元素，你可以对照线段列表查看是哪几笔触发了结束确认。</p>
      </div>
    </div>
    <h3>包含处理</h3>
    <div class="logic-rule-table">
      <div><strong>为什么要包含处理</strong><span>特征序列元素之间可能互相包含。如果不处理，局部重叠会制造假分型或抹掉真实缺口。</span></div>
      <div><strong>v2.0 的核心差异</strong><span><code>CEigenFXV2</code> 对第一、第二特征元素不先做普通包含合并，而是先保留它们的相对关系，尤其保留缺口/无缺口判断。</span></div>
      <div><strong>默认 chan 的差异</strong><span>默认 <code>chan</code> 会更早尝试合并第一、第二特征元素；这可能提前抹掉 v2.0 很关心的缺口关系。</span></div>
      <div><strong>重置机制</strong><span>如果第二元素出现后发现前两个元素不可能形成有效分型，算法会从后一批特征元素重新开始扫描，而不是硬凑线段。</span></div>
    </div>
    <h3>完整确认流程</h3>
    <div class="logic-rule-table">
      <div><strong>1. 清理尾部</strong><span>每次重算先删除末尾未确认线段；如果最后确认段依赖的特征序列尾元素仍未确认，也会回退，避免用过期证据画段。</span></div>
      <div><strong>2. 确定扫描起点</strong><span>没有线段时从第 0 笔开始；已有确认段时，从最后一段终点后一笔开始继续扫描。</span></div>
      <div><strong>3. 同时观察两套序列</strong><span>首段方向未定时，会同时维护“上升段结束用的下降特征序列”和“下降段结束用的上升特征序列”。</span></div>
      <div><strong>4. 首段方向预判</strong><span>不是谁先出分型就立即定方向，而是等某一侧已经出现第二特征元素后，结合当前笔方向排除另一侧，降低首段误判。</span></div>
      <div><strong>5. 收集特征元素</strong><span>遇到与当前疑似线段方向相反的笔，就加入对应特征序列。上升候选段收下降笔，下降候选段收上升笔。</span></div>
      <div><strong>6. 形成三元素</strong><span>特征序列至少需要三组元素，才可能判断顶/底分型。少于三组时不会确认线段结束。</span></div>
      <div><strong>7. 判断特征分型</strong><span>上升段结束看下降特征序列顶分型；下降段结束看上升特征序列底分型。</span></div>
      <div><strong>8. 判断缺口</strong><span>分型中间元素和前一元素之间如果有缺口，不能立即确认，需要进入二次确认路径。</span></div>
      <div><strong>9. 无缺口路径</strong><span>无缺口且实际突破条件成立时，分型峰值笔可作为线段候选终点，进入添加线段流程。</span></div>
      <div><strong>10. 有缺口路径</strong><span>有缺口时，算法继续向后寻找反向特征序列分型。只有后续反向证据成立，才确认前一线段结束。</span></div>
      <div><strong>11. 添加线段</strong><span>候选终点通过 <code>add_new_seg()</code> 写入线段列表。若特征序列和证据笔都确认，则线段为有效；否则为未确认。</span></div>
      <div><strong>12. 递归继续</strong><span>如果本次线段确认成立，就从新线段终点后一笔继续扫描下一段，直到没有足够证据。</span></div>
      <div><strong>13. 收集尾段</strong><span>剩余走势不够确认新段时，通用尾段逻辑会收集为未确认线段，让图上能看到当前候选走势。</span></div>
    </div>
    <h3>缺口确认</h3>
    <div class="logic-grid">
      <div class="logic-card">
        <h3>无缺口例子</h3>
        <p>上升段中，下降特征序列为 <code>D2, D4, D6</code>。若 <code>D4</code> 构成顶分型，且 <code>D2</code> 与 <code>D4</code> 之间没有缺口，系统可以把上升段终点落在 <code>D4</code> 对应的峰值笔附近。</p>
      </div>
      <div class="logic-card">
        <h3>有缺口例子</h3>
        <p>仍以上升段为例，若 <code>D4</code> 与 <code>D2</code> 之间跳空，当前顶分型只表示“可能结束”。系统继续看后续走势中是否出现反向确认，而不是立刻画出确认段。</p>
      </div>
      <div class="logic-card">
        <h3>为什么缺口不能忽略</h3>
        <p>缺口表示特征序列第一、第二元素之间并没有正常重叠过渡。它可能只是走势过快造成的中间状态，必须等待后续证据确认是否真的破坏原线段。</p>
      </div>
      <div class="logic-card">
        <h3>代码里的体现</h3>
        <p><code>CEigenFX.can_be_end()</code> 会检查特征序列缺口。无缺口可直接返回确认；有缺口时会进入后续反向分型查找逻辑。</p>
      </div>
    </div>
    <h3>复杂场景举例</h3>
    <div class="logic-rule-table">
      <div><strong>例 1：不足三笔</strong><span>只有 <code>U1, D2</code> 时不能构成线段。图上最多是笔，或者尾部候选，不应当出现确认段。</span></div>
      <div><strong>例 2：三笔但无重叠</strong><span><code>U1, D2, U3</code> 虽然有三笔，但前三笔价格区间没有重叠时，反向线段证据不足，不能确认破坏。</span></div>
      <div><strong>例 3：包含导致分型消失</strong><span><code>D2, D4, D6</code> 看起来像顶分型，但经过特征序列包含处理后，中间元素被合并或结构改变，则不能确认上升段结束。</span></div>
      <div><strong>例 4：无缺口标准确认</strong><span>下降特征序列形成顶分型，第一、第二元素无缺口，且实际突破条件成立，上升段可确认结束。</span></div>
      <div><strong>例 5：有缺口待确认</strong><span>下降特征序列形成顶分型，但第一、第二元素有缺口，此时只进入待确认，图上后续段可能仍是未确认状态。</span></div>
      <div><strong>例 6：笔破坏但线段未破坏</strong><span>一根反向笔跌破上升段内部低点，但后续没有走出完整反向线段，不能单靠这一笔终结原线段。</span></div>
      <div><strong>例 7：强反向后震荡</strong><span>大阴线后多笔都在该阴线范围内震荡，特征序列无法形成有效分型，原线段继续延伸或只显示未确认尾段。</span></div>
      <div><strong>例 8：后续创新高</strong><span>上升段疑似被破坏后，价格又突破原高点，说明此前反向结构证据不足，中间走势可能被视为原上升段内部波动。</span></div>
      <div><strong>例 9：缺口后反向确认</strong><span>有缺口分型先出现，后面又形成反向特征序列分型，才把原线段终点落定到前面的候选位置。</span></div>
      <div><strong>例 10：尾部未确认</strong><span>最后几笔已经像新段，但证据不足。线段表会显示“未确认”，后续新 K 线可能让这段延长、删除或改写方向。</span></div>
    </div>
    <h3>如何判断图上是不是按这个规则画的</h3>
    <div class="logic-rule-table">
      <div><strong>第一步</strong><span>先看笔列表。线段只能由这些有效笔组成，不能跨过笔直接连接 K 线高低点。</span></div>
      <div><strong>第二步</strong><span>在线段列表里找到某一段的起止笔，确认它至少覆盖三笔，方向和起止价格符合上升/下降段。</span></div>
      <div><strong>第三步</strong><span>打开“特征”按钮，看该段结束前的反向笔是否组成了三组特征序列元素。</span></div>
      <div><strong>第四步</strong><span>检查特征序列是否形成顶/底分型。上升段结束看下降特征序列顶分型，下降段结束看上升特征序列底分型。</span></div>
      <div><strong>第五步</strong><span>检查第一、第二特征元素之间是否有缺口。有缺口时，不能只凭当前分型确认，要看后续反向确认。</span></div>
      <div><strong>第六步</strong><span>看线段状态。有效段表示证据已确认；未确认段表示只是尾部候选，后续行情可能改写。</span></div>
      <div><strong>第七步</strong><span>如果同一批笔在 <code>chan</code> 和 <code>chan_v2</code> 下画法不同，重点检查第一、第二特征元素是否被合并，以及缺口是否被保留下来。</span></div>
    </div>
    <div class="logic-example">
      <strong>一句话复核：</strong>线段v2.0 先以有效笔为原料，再抽取当前线段的反向笔组成特征序列；特征序列形成有效分型且缺口确认路径通过后，才把线段终点画出来。证据不足时，图上只应出现未确认尾段，而不是确认段。
    </div>
  </section>
  <section class="logic-tab-panel" data-logic-panel="segment-doubao">
    <h2>8. 线段-豆包</h2>
    <p><code>seg_algo=chan_doubao</code> 是在默认 <code>chan</code> 特征序列线段算法上增加的端点替换实验模式。它不改变前置的包含处理、分型过滤、成笔规则，也不改变特征序列确认主干；只在候选线段终点落定时，加一条“同类型极值不能跨过反向有效笔端点替换”的规则。</p>
    <div class="logic-grid">
      <div class="logic-card">
        <h3>总览</h3>
        <p>输入仍然是已经确认出来的有效笔列表。系统先按 <code>chan</code> 的方式寻找线段结束证据，再在本次确认窗口内检查候选终点是否允许替换为同方向更极端端点。</p>
        <p>如果候选终点和后续同方向极值之间已经出现反向有效笔端点，前一个候选终点视为锁定，后续更极端端点不能回头替代它。</p>
      </div>
      <div class="logic-card">
        <h3>当前代码入口</h3>
        <p>页面选择 <code>线段 doubao</code> 后，配置值会传入 <code>seg_algo=chan_doubao</code>，最终由 <code>CSegListChanDoubao</code> 计算线段。</p>
        <pre><code>update()
  do_init()
  cal_seg_sure()
  extend_confirmed_seg_extremes()
  collect_left_seg()</code></pre>
      </div>
      <div class="logic-card">
        <h3>不改变的部分</h3>
        <p>它不重新定义 K 线包含、顶底分型、成笔、笔缺口、笔列表和中枢计算。线段端点仍然只能取自笔端点，不会直接连到原始 K 线的普通高低点。</p>
      </div>
      <div class="logic-card">
        <h3>核心差异</h3>
        <p>默认 <code>chan</code> 在特征序列确认后直接使用特征序列峰值笔作为线段终点；<code>chan_doubao</code> 会先用同类型替换规则检查该终点是否可以往后移动，但移动不能跨过反向有效笔。</p>
      </div>
    </div>
    <h3>名字解释</h3>
    <div class="logic-rule-table">
      <div><strong>有效笔序列</strong><span>已经通过分型过滤、跨度、区间分离、缺口破格等规则生成的笔列表。线段算法只读取这份笔序列。</span></div>
      <div><strong>线段</strong><span>由连续笔构成的更高一级结构。线段起点是第一笔的起点，终点是最后一笔的终点；已确认线段至少三笔。</span></div>
      <div><strong>特征序列</strong><span>判断当前线段是否结束时抽取的反向笔集合。上升段取下降笔作为特征序列；下降段取上升笔作为特征序列。</span></div>
      <div><strong>特征序列分型</strong><span>特征序列内部形成的顶/底分型。它是默认 <code>chan</code> 判断线段结束的核心证据。</span></div>
      <div><strong>候选终点</strong><span><code>fx_eigen.GetPeakBiIdx()</code> 给出的峰值笔。它是默认 <code>chan</code> 会尝试作为线段结束点的笔。</span></div>
      <div><strong>确认窗口</strong><span>从候选终点到确认证据笔 <code>last_evidence_bi</code> 之间的笔区间；如果没有证据笔，则到当前笔列表尾部。</span></div>
      <div><strong>同类型端点</strong><span>和候选终点方向相同的笔端点。下降终点看更低低点，向上终点看更高高点。</span></div>
      <div><strong>反向有效笔端点</strong><span>确认窗口内第一根方向不同的有效笔端点。它一旦出现，就表示前一个同类端点已经不能继续被后面的同类极值替换。</span></div>
      <div><strong>更极端</strong><span>下降笔用 <code>_low()</code> 比较，更低才算更极端；上升笔用 <code>_high()</code> 比较，更高才算更极端。</span></div>
      <div><strong>锁定</strong><span>两个同类端点之间出现反向有效笔端点后，前一个同类端点固定为当前段终点，不允许后续更低底或更高顶回头替换。</span></div>
    </div>
    <h3>完整划分流程</h3>
    <div class="logic-rule-table">
      <div><strong>1. 清理尾部</strong><span>每次更新先执行 <code>do_init()</code>。继承自 <code>chan</code> 的逻辑会删除末尾未确认线段；如果最后一个已确认线段依赖的特征序列尾元素仍未确认，也会回退重算。</span></div>
      <div><strong>2. 确定扫描起点</strong><span>如果当前没有线段，从第 0 笔开始扫描；如果已有确认线段，则从最后一段终点的下一笔开始继续扫描。</span></div>
      <div><strong>3. 构造特征序列</strong><span>沿笔列表向后扫描。遇到下降笔且当前不在上升段尾部禁用状态时，加入上升段结束用的下降特征序列；遇到上升笔且当前不在下降段尾部禁用状态时，加入下降段结束用的上升特征序列。</span></div>
      <div><strong>4. 首段方向预判</strong><span>第一段还没有方向时，不是谁先形成分型就立即决定方向。代码会看上升/下降两套特征序列是否已经出现第二个元素，并据此清理另一套临时序列。</span></div>
      <div><strong>5. 发现特征分型</strong><span>当某套特征序列形成有效特征分型后，进入 <code>treat_fx_eigen()</code>。这一步仍然沿用 <code>chan</code> 的特征序列确认入口。</span></div>
      <div><strong>6. 判断是否能结束</strong><span>执行 <code>fx_eigen.can_be_end(bi_lst)</code>。返回 <code>True</code> 表示找到正常确认；返回 <code>None</code> 表示扫到尾部也没有新的反向证据，生成未确认或尾部候选；返回其他结果则说明当前分型证据不足，要从特征序列第二元素位置继续扫描。</span></div>
      <div><strong>7. 取默认候选终点</strong><span>当返回 <code>True</code> 或 <code>None</code> 时，先取 <code>fx_eigen.GetPeakBiIdx()</code> 作为默认候选终点。这一步与默认 <code>chan</code> 一致。</span></div>
      <div><strong>8. 确定确认窗口</strong><span>如果 <code>fx_eigen</code> 上存在 <code>last_evidence_bi</code>，窗口结束点取该证据笔；否则窗口结束点取当前笔列表最后一笔。</span></div>
      <div><strong>9. 执行豆包替换</strong><span>从候选终点开始，按同方向笔逐根向后扫描。只要后续同方向端点更极端，就替换候选终点；一旦遇到第一根反向有效笔，立即停止扫描。</span></div>
      <div><strong>10. 添加新线段</strong><span>用替换后的终点执行 <code>add_new_seg()</code>。如果 <code>can_be_end</code> 返回 <code>True</code> 且特征序列所有笔都确认，则新线段为已确认；否则为未确认。</span></div>
      <div><strong>11. 递归继续确认</strong><span>如果本次线段已确认，则从新线段终点的下一笔继续调用 <code>cal_seg_sure()</code>，尝试确认后续线段。</span></div>
      <div><strong>12. 后处理已确认段</strong><span>所有确认流程完成后，执行 <code>extend_confirmed_seg_extremes()</code>。它只检查已确认段和后一段之间是否还有可替换的同方向极值，并且同样不能跨过反向有效笔端点。</span></div>
      <div><strong>13. 重置被影响区间</strong><span>如果第 12 步确实发生替换，会重置当前段和下一段的起止笔、笔列表、趋势线和中枢列表，再重新检查线段合法性。</span></div>
      <div><strong>14. 收集剩余尾段</strong><span>最后执行 <code>collect_left_seg()</code>。如果末尾还有未纳入确认线段的笔，会按尾段规则收集为未确认线段；豆包模式的尾段同样使用“遇到反向有效笔就停止”的替换规则。</span></div>
    </div>
    <h3>豆包替换规则细节</h3>
    <div class="logic-grid">
      <div class="logic-card">
        <h3>替换函数</h3>
        <p>核心函数是 <code>_replace_until_opposite_fx()</code>。它要求扫描起点方向必须等于目标方向，否则不替换。</p>
        <pre><code>candidate = begin_bi
for bi in begin_next ... window_end:
  if bi.dir != target_dir:
    break
  if bi is more extreme:
    candidate = bi</code></pre>
      </div>
      <div class="logic-card">
        <h3>为什么遇到反向就停</h3>
        <p>你的新规则认为：同类型分型之间如果夹了一个反向分型端点，前一个同类端点对应的线段已经被反向结构确认，不能再被后面的同类极值回头改写。</p>
      </div>
      <div class="logic-card">
        <h3>下降段例子</h3>
        <p>A 顶到 B 底形成候选下降段。如果 B 后面没有反向上笔，且出现更低 C 底，可以把终点替换到 C；如果 B 和 C 中间先出现了反向上笔，则 B 锁定，C 不能替换 B。</p>
      </div>
      <div class="logic-card">
        <h3>上升段例子</h3>
        <p>A 底到 B 顶形成候选上升段。如果 B 后面没有反向下笔，且出现更高 C 顶，可以把终点替换到 C；如果中间先出现了反向下笔，则 B 锁定。</p>
      </div>
    </div>
    <h3>边界与注意事项</h3>
    <div class="logic-rule-table">
      <div><strong>旧模式不变</strong><span>只有选择 <code>chan_doubao</code> 时使用本规则。<code>chan</code>、<code>chan_v2</code>、<code>1+1</code>、<code>break</code> 的计算入口不受影响。</span></div>
      <div><strong>不能跨笔端点</strong><span>本规则只看有效笔端点方向，不直接读取原始 K 线内部的普通高低点；未成为有效笔端点的分型不会直接改变线段终点。</span></div>
      <div><strong>不能跨反向端点</strong><span>这是当前豆包模式最重要的限制。即使后面同方向端点更极端，只要中间出现过反向有效笔端点，就不能替换。</span></div>
      <div><strong>确认逻辑仍归 chan</strong><span>线段是否结束，仍由特征序列分型和 <code>can_be_end()</code> 决定；豆包规则只负责在可结束窗口内选择更合适的线段终点。</span></div>
      <div><strong>未确认尾段可能变化</strong><span>最后一段如果状态是未确认，后续新笔仍可能导致它被删除、重算或改写；已确认段只会在后处理窗口内按上述规则有限调整。</span></div>
      <div><strong>输出更保守</strong><span>相比“直接在窗口内取最高/最低”的方案，当前规则更保守。因为有效笔通常顶底交替，反向端点会很快锁定前一个同类端点。</span></div>
    </div>
  </section>
  <section class="logic-tab-panel" data-logic-panel="segment-doubao2">
    <h2>9. 线段-豆包2</h2>
    <p><code>seg_algo=chan_doubao2</code> 按 <code>docs/豆包生成规则.doc</code> 的执行流程实现，是一套独立于 <code>chan_doubao</code> 端点替换模式的线段划分算法。它仍然只读取已经生成的有效笔列表，但完整重走特征序列包含、缺口确认和反向线段校验。</p>
    <div class="logic-grid">
      <div class="logic-card">
        <h3>当前代码入口</h3>
        <p>页面选择 <code>线段 doubao2</code> 后，配置值会传入 <code>seg_algo=chan_doubao2</code>，最终由 <code>CSegListChanDoubao2</code> 计算线段。</p>
        <pre><code>update()
  do_init()
  cal_bi_sure()
  collect_left_seg()</code></pre>
      </div>
      <div class="logic-card">
        <h3>线段门槛</h3>
        <p>确认段至少需要三笔。相邻线段方向严格交替，后一线段从前一线段终点后一笔开始延续；剩余不足确认条件的走势交给尾段收集逻辑生成未确认段。</p>
      </div>
      <div class="logic-card">
        <h3>特征序列</h3>
        <p>判断向上线段是否结束时收集下降笔；判断向下线段是否结束时收集上升笔。未确认结束前，右侧走势仍先归入当前线段的扫描窗口。</p>
      </div>
      <div class="logic-card">
        <h3>线段破坏</h3>
        <p>单笔反向冲击不能直接确认原线段终结。算法必须从候选终点后一笔开始看到三笔交替且前三笔价格区间重叠，才认为反向线段成立。</p>
      </div>
    </div>
    <h3>包含处理</h3>
    <div class="logic-rule-table">
      <div><strong>第 1、2 元素</strong><span>仅允许左包右合并，禁止右包左合并，用来保留顶底两侧特征序列的原始关系。</span></div>
      <div><strong>第 2 元素之后</strong><span>左包右、右包左都允许合并，处理顺序从左到右。</span></div>
      <div><strong>向上线段</strong><span>特征序列是下降笔，包含合并取“低低”：高点取较小值，低点也取较小值。</span></div>
      <div><strong>向下线段</strong><span>特征序列是上升笔，包含合并取“高高”：高点取较大值，低点也取较大值。</span></div>
    </div>
    <h3>确认流程</h3>
    <div class="logic-rule-table">
      <div><strong>1. 起段</strong><span>从当前未归属的第一笔开始，线段方向取该笔方向。</span></div>
      <div><strong>2. 收集特征</strong><span>向后遍历笔列表，只把反向笔加入当前线段的特征序列。</span></div>
      <div><strong>3. 合并特征</strong><span>每加入新特征元素后，按豆包2包含规则重新得到合并后的特征序列。</span></div>
      <div><strong>4. 判断分型</strong><span>向上线段要求特征序列形成顶分型；向下线段要求特征序列形成底分型。</span></div>
      <div><strong>5. 无缺口</strong><span>第 1、2 特征元素无价格缺口时，分型只是必要条件；还要校验候选终点后是否走出完整反向三笔线段。</span></div>
      <div><strong>6. 有缺口</strong><span>第一组分型只作为预警，不能直接终结原线段；后续再出现一组特征分型，并且预警终点后反向三笔成立，才确认原线段结束。</span></div>
      <div><strong>7. 生成线段</strong><span>确认后生成当前段，并从确认终点后一笔继续扫描下一段。</span></div>
      <div><strong>8. 收尾</strong><span>如果后续无法确认新段，则保留已有确认段，再由通用尾段逻辑收集最后未确认走势。</span></div>
    </div>
    <div class="logic-example">
      <strong>实现口径：</strong><code>chan_doubao2</code> 不是 <code>chan_doubao</code> 的小改版；它按文档伪代码把“缺口预警 + 二次确认 + 反向三笔重叠”作为核心确认链路。
    </div>
  </section>
  <section class="logic-tab-panel" data-logic-panel="segment-doubao3">
    <h2>10. 线段-豆包3</h2>
    <p><code>seg_algo=chan_doubao3</code> 按 <code>docs/新豆包规则 和代码.doc</code> 的 TypeScript 流程实现。它是独立算法，不覆盖 <code>chan_doubao2</code>；页面参数也支持 <code>doubao3</code>、<code>doubao_v3</code> 和 <code>douban_v3</code> 别名。</p>
    <div class="logic-grid">
      <div class="logic-card">
        <h3>当前代码入口</h3>
        <p>选择 <code>线段 doubao3</code> 后，配置值进入 <code>CSegListChanDoubao3</code>。算法先按新文档生成计划线段，再映射成项目可承载的 <code>CSeg</code>。</p>
        <pre><code>update()
  do_init()
  _compute_plan()
  _merge_same_direction()
  _apply_plan()</code></pre>
      </div>
      <div class="logic-card">
        <h3>分型方向</h3>
        <p>向上线段的特征序列是下降笔，寻找底分型；向下线段的特征序列是上升笔，寻找顶分型。这一点和旧 <code>chan_doubao2</code> 不同。</p>
      </div>
      <div class="logic-card">
        <h3>第 1、2 元素</h3>
        <p>第 1、2 特征元素只允许左包右。若右包左，不合并也不追加右侧元素，继续保留第 1 个元素参与后续判断。</p>
      </div>
      <div class="logic-card">
        <h3>端点适配</h3>
        <p>新文档模型允许相邻线段共享同一笔端点。项目内部线段必须连续分段，因此实现会把文档端点映射到上一段的 <code>endpoint - 1</code>，下一段从文档端点开始。</p>
      </div>
    </div>
    <h3>确认流程</h3>
    <div class="logic-rule-table">
      <div><strong>1. 构造特征序列</strong><span>从当前搜索起点到笔列表末尾，抽取当前线段反向笔作为特征元素。</span></div>
      <div><strong>2. 包含处理</strong><span>第 1、2 元素仅左包右；第 2 元素之后双向合并。向上线段取低低，向下线段取高高。</span></div>
      <div><strong>3. 找第一分型</strong><span>处理后的特征序列里取第一组有效分型。向上线段找底分型，向下线段找顶分型。</span></div>
      <div><strong>4. 无缺口</strong><span>第一分型无缺口时，先认为当前线段终结，终结类型记为 <code>doubao3_no_gap</code>。</span></div>
      <div><strong>5. 有缺口</strong><span>第一分型有缺口时，从该分型后一笔开始构建反向线段的特征序列；若反向序列出现分型，原线段才确认终结，终结类型记为 <code>doubao3_with_gap</code>。</span></div>
      <div><strong>6. 反向确认</strong><span>生成当前计划线段后，再检查文档端点开始是否存在三笔交替且前三笔价格区间重叠。若不成立，则停止继续向后划分。</span></div>
      <div><strong>7. 尾段</strong><span>特征元素不足、包含后不足、找不到分型或有缺口无法确认时，剩余部分生成未确认尾段，原因记为 <code>doubao3_initial</code>。</span></div>
      <div><strong>8. 同向合并</strong><span>计划线段生成后，如果出现连续同方向线段，会按新文档流程先合并再写入项目线段列表。</span></div>
    </div>
    <div class="logic-example">
      <strong>核心区别：</strong><code>chan_doubao3</code> 按新文档规则执行；它和 <code>chan_doubao2</code> 的主要差异在分型方向、第 1/2 元素包含处理、无缺口先终结后确认、以及同向线段后处理合并。
    </div>
  </section>
  <section class="logic-tab-panel" data-logic-panel="report">
    <h2>11. 表格与图上标注口径</h2>
    <p>报告里的图形和表格是为了复核计算过程，不是额外再跑一套规则。图上的三角形、虚线框、笔线和表格行都来自同一份分型与笔数据。</p>
    <h3>线段算法参数对比</h3>
    <p>页面上方的 <code>seg_algo</code> 会影响线段、线段中枢、线段买卖点以及图上的段线。分型列表和笔列表仍由前置分型/成笔逻辑生成，但段相关标注会按所选算法重新计算。</p>
    <div class="logic-table-wrap">
      <table class="logic-compare-table">
        <thead>
          <tr>
            <th>参数</th>
            <th>当前含义</th>
            <th>核心划分逻辑</th>
            <th>缺口与确认方式</th>
            <th>适用场景</th>
            <th>注意事项</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><code>chan</code></td>
            <td>默认线段算法，当前系统稳定口径。</td>
            <td>基于已经生成的笔继续划分线段。上升线段抽取下降笔作为特征序列，下降线段抽取上升笔作为特征序列；在特征序列上寻找顶/底分型来确认线段结束。</td>
            <td>特征序列分型中间元素与前一元素有缺口时标记 <code>gap=True</code>，不会立即确认线段结束，会继续查找反向分型作为二次确认；无缺口时更容易直接确认。</td>
            <td>适合日常查看、复核当前系统历史结果、保持与已有中枢和买卖点输出一致。</td>
            <td>第一、第二特征元素会先走当前包含处理，某些线段 v2.0 强调的缺口关系可能被合并逻辑改写；复杂中间态主要表现为虚线段。</td>
          </tr>
          <tr>
            <td><code>chan_v2</code></td>
            <td>线段 v2.0 口径的独立实验算法。</td>
            <td>保留 <code>chan</code> 的特征序列主干，但第一、第二特征序列元素不先做包含合并，优先保留两者之间的缺口/无缺口关系，再进入后续分型和确认流程。</td>
            <td>当第一、第二特征元素形成的特征序列分型带缺口时，需要后续反向确认；缺口关系不会因为一开始的包含合并被抹掉，更贴近“有缺口需要二次确认、线段只能被线段破坏”的解释口径。</td>
            <td>适合对照线段 v2.0 文档、检查缺口导致的线段端点变化、分析为什么同一批笔在不同算法下段线不同。</td>
            <td>这是新增算法，输出可能不同于默认 <code>chan</code>；下游线段中枢、线段买卖点也会随之变化，建议与 <code>chan</code> 并行对照。</td>
          </tr>
          <tr>
            <td><code>chan_doubao</code></td>
            <td>候选线段端点极值替换模式。</td>
            <td>保留 <code>chan</code> 的特征序列确认主干。候选终点遇到同方向更极端有效笔端点时，只有两者之间尚未出现反向有效笔端点，才允许替换。</td>
            <td>确认段的缺口和特征序列确认逻辑不变；一旦两个同类端点之间出现反向分型端点，前一个同类端点即视为锁定，后续更极端端点不再回头替换它。</td>
            <td>适合观察主跌/主升过程中，未被反向分型打断的同类极值是否应继续延伸。</td>
            <td>输出会比直接取窗口最高/最低更保守；同类型极值不能跨过中间反向分型端点做替换，适合与 <code>chan</code> 对照使用。</td>
          </tr>
          <tr>
            <td><code>chan_doubao2</code></td>
            <td>按豆包生成规则文档实现的独立划分算法。</td>
            <td>从当前起始笔确定线段方向，收集反向笔作为特征序列；按第 1、2 元素仅左包右、第 2 元素后双向包含的规则合并，再用顶/底分型判断候选结束。</td>
            <td>无缺口时，分型后仍需反向三笔交替且价格重叠来确认；有缺口时，第一组分型只预警，等待第二组分型和反向线段成立后再确认。</td>
            <td>适合专门对照 <code>docs/豆包生成规则.doc</code> 的伪代码结果，观察缺口预警、二次确认和反向线段破坏对段线的影响。</td>
            <td>这是文档规则实验实现，结果可能和 <code>chan</code>/<code>chan_v2</code>/<code>chan_doubao</code> 都不同；下游线段中枢和买卖点会跟随重算。</td>
          </tr>
          <tr>
            <td><code>chan_doubao3</code></td>
            <td>按新豆包规则文档实现的独立划分算法。</td>
            <td>按 <code>docs/新豆包规则 和代码.doc</code> 的 TypeScript 流程生成计划线段：向上线段找底分型，向下线段找顶分型；第 1、2 特征元素仅左包右且右包左时保留左元素。</td>
            <td>无缺口分型先终结当前线段；有缺口时等待反向特征序列出现分型。随后检查文档端点处是否存在反向三笔交替且前三笔价格区间重叠。</td>
            <td>适合对照新豆包规则，尤其检查它相对 <code>chan_doubao2</code> 在分型方向、包含处理、端点共享和同向合并上的差异。</td>
            <td>项目内部不支持相邻段共享同一笔端点，因此实现会把文档端点映射成上一段 <code>endpoint - 1</code>、下一段从文档端点开始。</td>
          </tr>
          <tr>
            <td><code>1+1</code></td>
            <td>保留的都业华 1+1 终结算法入口。</td>
            <td>不走当前默认的特征序列主流程，而是按 1+1 终结思路处理线段结束。它更偏“笔序列终结关系”的划分方式，和 <code>chan</code> 的特征序列分型确认不同。</td>
            <td>不使用 <code>CEigen.gap</code> 这套特征序列缺口二次确认逻辑，因此缺口对线段结束的影响不会按 <code>chan</code>/<code>chan_v2</code> 的方式表达。</td>
            <td>主要用于历史对照、临时排查不同线段算法对结果的影响。</td>
            <td>代码中已有提示该算法 deprecated / no longer maintained，不建议作为默认实盘口径；结果需要谨慎解释。</td>
          </tr>
          <tr>
            <td><code>break</code></td>
            <td>保留的按线段破坏定义划分的旧算法入口。</td>
            <td>更偏向按笔对前线段高低点的突破关系来判断线段破坏和新段生成，而不是先抽取反向笔形成特征序列分型。</td>
            <td>主要关注笔高低突破关系，不使用 <code>chan</code> 的特征序列缺口确认分支；缺口如果改变了笔的高低点，可能间接影响结果，但没有独立缺口状态。</td>
            <td>适合做“突破式划段”和默认特征序列划段的差异比较。</td>
            <td>代码中也标注 deprecated / no longer maintained；在复杂包含、缺口、中间态场景下，解释力弱于当前重点维护的 <code>chan</code>/<code>chan_v2</code>。</td>
          </tr>
        </tbody>
      </table>
    </div>
    <div class="logic-grid">
      <div class="logic-card">
        <h3>原始分型列表</h3>
        <p>列出所有识别出来的顶/底分型。“有效”表示被某条笔用作起点或终点；“已过滤”表示未进入最终笔结构。</p>
      </div>
      <div class="logic-card">
        <h3>分型最高/最低</h3>
        <p>这两列用于观察顶底是否重合，采用前中后三个合并 K 覆盖的原始 K 极值，并显示对应发生时间。</p>
      </div>
      <div class="logic-card">
        <h3>图上三角形</h3>
        <p>实心三角形表示有效分型，虚线空心三角形表示被过滤的原始分型。K 线数量较多时会隐藏完整分型标注，避免遮挡行情。</p>
      </div>
      <div class="logic-card">
        <h3>点击联动</h3>
        <p>点击图上的分型数字或三角形，会在原始分型列表内滚动到对应行，并在图上画出该分型覆盖区间。点击“清理”才会移除这些虚线框。</p>
      </div>
    </div>
  </section>
</div>
"""

    def _build_report_rows(self, meta: CChanPlotMeta) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
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
            if bi.gap_break:
                gap_direction = "向上跳空" if bi.gap_break["direction"] == "up" else "向下跳空"
                cmp_symbol = "&gt;" if bi.gap_break["direction"] == "up" else "&lt;"
                notes.append({
                    "html": (
                        f'缺口破格：合并K {bi.gap_break["prev_klc_idx"]} 到 '
                        f'{bi.gap_break["next_klc_idx"]} 出现{gap_direction}，'
                        f'突破价 {_fmt_num(bi.gap_break["gap_value"])} '
                        f'{cmp_symbol} 前一笔起点极值 {_fmt_num(bi.gap_break["threshold"])}；'
                        f'豁免最小跨度与分型区间重叠限制，端点极值等其他校验仍需通过。'
                    )
                })
            if getattr(bi, "gap_retrace", None):
                previous_gap = bi.gap_retrace["previous_gap"]
                gap_direction = "向上跳空" if previous_gap["direction"] == "up" else "向下跳空"
                notes.append({
                    "html": (
                        f'缺口后反向成笔：上一笔为{gap_direction}破格笔，当前笔从该缺口笔终点发起；'
                        f'缺口区间只作为背景标记，不再豁免 <code>bi_fx_check</code>；'
                        f'当前笔仍必须通过最终顶底分型三K区间检查、跨度和端点极值。'
                    )
                })
            if not bi.is_sure:
                notes.append("最后一笔为虚笔或尚未完全确认，后续新K线可能改写终点")
            endpoint_map.setdefault(int(bi.begin_klc_idx), []).append(f"第{i + 1}笔起点")
            endpoint_map.setdefault(int(bi.end_klc_idx), []).append(f"第{i + 1}笔终点")
            pen_rows.append({
                "idx": i + 1,
                "source_idx": int(bi.idx),
                "direction": direction,
                "begin_klc_idx": int(bi.begin_klc_idx),
                "end_klc_idx": int(bi.end_klc_idx),
                "begin_x": int(bi.begin_x),
                "end_x": int(bi.end_x),
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

        pen_by_source_idx = {row["source_idx"]: row for row in pen_rows}
        seg_rows: List[Dict[str, Any]] = []
        for i, seg in enumerate(meta.seg_list):
            direction = "up" if seg.dir == BI_DIR.UP else "down"
            begin_bi_idx = int(seg.begin_bi_idx)
            end_bi_idx = int(seg.end_bi_idx)
            component_pens = [
                pen_by_source_idx[bi_idx]
                for bi_idx in range(begin_bi_idx, end_bi_idx + 1)
                if bi_idx in pen_by_source_idx
            ]
            begin_pen = component_pens[0] if component_pens else None
            end_pen = component_pens[-1] if component_pens else None
            begin_date = begin_pen["begin_date"] if begin_pen else ""
            begin_kind = begin_pen["begin_kind"] if begin_pen else ("bottom" if direction == "up" else "top")
            end_date = end_pen["end_date"] if end_pen else ""
            end_kind = end_pen["end_kind"] if end_pen else ("top" if direction == "up" else "bottom")
            amp = abs(float(seg.end_y) - float(seg.begin_y))
            kl_cnt = int(seg.end_x - seg.begin_x + 1)
            notes: List[Any] = [
                (
                    f"线段由第{begin_bi_idx + 1}笔至第{end_bi_idx + 1}笔构成，"
                    f"共{len(component_pens)}笔；{_seg_dir_label(direction)}从"
                    f"{_fx_label(begin_kind)} {_fmt_num(seg.begin_y)} 推进到"
                    f"{_fx_label(end_kind)} {_fmt_num(seg.end_y)}。"
                ),
                (
                    "线段构造过程：先生成有效笔序列，再在反向笔组成的特征序列上确认段结束；"
                    "相邻线段首尾相接，线段端点取自笔端点，不直接连接原始K线。"
                ),
            ]
            if component_pens:
                pen_parts = []
                for pen in component_pens:
                    pen_parts.append(
                        f'第{pen["idx"]}笔：{_dir_label(pen["direction"])}，'
                        f'{_fx_label(pen["begin_kind"])} {html.escape(pen["begin_date"])} '
                        f'{_fmt_num(pen["begin_price"])} → '
                        f'{_fx_label(pen["end_kind"])} {html.escape(pen["end_date"])} '
                        f'{_fmt_num(pen["end_price"])}，'
                        f'跨度{pen["kl_cnt"]}根，状态{html.escape(pen["status"])}'
                    )
                notes.append({"html": "<br>".join(pen_parts)})
            if not seg.is_sure:
                notes.append("最后线段未确认，后续新笔可能继续改写线段终点或方向。")
            seg_rows.append({
                "idx": i + 1,
                "direction": direction,
                "begin_bi_idx": begin_bi_idx,
                "end_bi_idx": end_bi_idx,
                "begin_x": int(seg.begin_x),
                "end_x": int(seg.end_x),
                "begin_date": begin_date,
                "begin_kind": begin_kind,
                "begin_price": float(seg.begin_y),
                "end_date": end_date,
                "end_kind": end_kind,
                "end_price": float(seg.end_y),
                "bi_cnt": len(component_pens),
                "kl_cnt": kl_cnt,
                "amp": amp,
                "status": "有效" if seg.is_sure else "未确认",
                "notes": notes,
                "target_idx": int(seg.end_x),
            })

        fx_rows: List[Dict[str, Any]] = []
        for klc_pos, klc in enumerate(meta.klc_list):
            if klc.type not in (FX_TYPE.TOP, FX_TYPE.BOTTOM):
                continue
            kind = "top" if klc.type == FX_TYPE.TOP else "bottom"
            is_valid = int(klc.idx) in endpoint_map
            date = _fmt_time(klc.klu_list[len(klc.klu_list) // 2].time) if klc.klu_list else _fmt_time(klc.time_begin)
            price = float(klc.high if klc.type == FX_TYPE.TOP else klc.low)
            fx_klus = []
            for neighbor_pos in (klc_pos - 1, klc_pos, klc_pos + 1):
                if 0 <= neighbor_pos < len(meta.klc_list):
                    fx_klus.extend(list(meta.klc_list[neighbor_pos].klu_list))
            if not fx_klus:
                fx_klus = list(klc.klu_list)
            high_klu = max(fx_klus, key=lambda x: float(x.high)) if fx_klus else None
            low_klu = min(fx_klus, key=lambda x: float(x.low)) if fx_klus else None
            fx_high = float(high_klu.high) if high_klu else float(klc.high)
            fx_low = float(low_klu.low) if low_klu else float(klc.low)
            notes = [
                f"识别到{_fx_label(kind)}形态：分型价格{_fmt_num(price)}，分型最高{_fmt_num(fx_high)}，分型最低{_fmt_num(fx_low)}",
            ]
            fx_rows.append({
                "idx": len(fx_rows) + 1,
                "klc_idx": int(klc.idx),
                "date": date,
                "kind": kind,
                "price": price,
                "high": fx_high,
                "high_time": _fmt_time(high_klu.time) if high_klu else "",
                "low": fx_low,
                "low_time": _fmt_time(low_klu.time) if low_klu else "",
                "status": "有效" if is_valid else "已过滤",
                "notes": notes,
                "target_idx": int((klc.begin_idx + klc.end_idx) / 2),
            })
        valid_rows = [row for row in fx_rows if row["status"] == "有效"]
        row_by_klc_idx = {row["klc_idx"]: row for row in fx_rows}

        def totally_check_result(start: Dict[str, Any], end: Dict[str, Any]) -> tuple[Optional[bool], str]:
            if start["kind"] == "top" and end["kind"] == "bottom":
                ok = start["low"] > end["high"]
                expr = f'{_fmt_num(start["low"])} &gt; {_fmt_num(end["high"])}'
                meaning = "顶分型三K最低 &gt; 底分型三K最高"
            elif start["kind"] == "bottom" and end["kind"] == "top":
                ok = start["high"] < end["low"]
                expr = f'{_fmt_num(start["high"])} &lt; {_fmt_num(end["low"])}'
                meaning = "底分型三K最高 &lt; 顶分型三K最低"
            else:
                return None, "同类分型不能直接做顶底成笔区间验证"
            return ok, f'{meaning}：{expr}，结果：{"通过" if ok else "不通过"}'

        def totally_check_html(start: Dict[str, Any], end: Dict[str, Any]) -> str:
            return totally_check_result(start, end)[1]

        def containing_pen(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            return next(
                (
                    pen for pen in pen_rows
                    if pen["begin_x"] < row["target_idx"] < pen["end_x"]
                ),
                None,
            )

        def pen_desc_html(pen: Dict[str, Any]) -> str:
            begin_row = row_by_klc_idx.get(pen["begin_klc_idx"])
            end_row = row_by_klc_idx.get(pen["end_klc_idx"])
            begin_ref = self._fx_note_ref(begin_row) if begin_row else html.escape(pen["begin_date"])
            end_ref = self._fx_note_ref(end_row) if end_row else html.escape(pen["end_date"])
            return f'第{pen["idx"]}笔（{_dir_label(pen["direction"])}）：起点 {begin_ref}，终点 {end_ref}'

        for row in fx_rows:
            prev_valid = next((item for item in reversed(valid_rows) if item["idx"] < row["idx"]), None)
            next_valid = next((item for item in valid_rows if item["idx"] > row["idx"]), None)
            prev_same = next((item for item in reversed(fx_rows[: row["idx"] - 1]) if item["kind"] == row["kind"]), None)
            next_same = next((item for item in fx_rows[row["idx"]:] if item["kind"] == row["kind"]), None)
            pen_inside = containing_pen(row)
            notes = row["notes"]
            if row["status"] == "有效":
                notes.append("作为" + "、".join(endpoint_map[int(row["klc_idx"])]) + "保留为有效笔端点")
                if prev_valid:
                    relation = "同类端点更新" if prev_valid["kind"] == row["kind"] else "顶底交替"
                    notes.append({
                        "html": (
                            f'前一有效端点：{self._fx_note_ref(prev_valid)}；当前处理关系：'
                            f'{html.escape(relation)}。'
                        )
                    })
                endpoint_roles = endpoint_map.get(int(row["klc_idx"]), [])
                end_pen = next((pen for pen in pen_rows if pen["end_klc_idx"] == row["klc_idx"]), None)
                if end_pen and any("终点" in role for role in endpoint_roles):
                    begin_row = row_by_klc_idx.get(end_pen["begin_klc_idx"])
                    if begin_row:
                        notes.append({
                            "html": (
                                f'最终端点复验：作为第{end_pen["idx"]}笔终点时，必须用该笔起点 '
                                f'{self._fx_note_ref(begin_row)} 与当前端点重新检查；'
                                f'{totally_check_html(begin_row, row)}。'
                                f'终点更新路径不借用缺口后反向豁免。'
                            )
                        })
                if prev_same and prev_same["status"] != "有效":
                    better = row["price"] >= prev_same["price"] if row["kind"] == "top" else row["price"] <= prev_same["price"]
                    if better:
                        notes.append({
                            "html": (
                                f'同类候选被当前有效端点替代：{self._fx_note_ref(prev_same)}；'
                                f'原因：当前{_fx_label(row["kind"])}极值更强。'
                            )
                        })
                if next_same and next_same["status"] == "有效":
                    notes.append({
                        "html": (
                            f'后续同类有效端点会继续修正当前方向：{self._fx_note_ref(next_same)}。'
                        )
                    })
            else:
                if pen_inside:
                    notes.append({
                        "html": (
                            f'最终结构定位：当前分型落在 {pen_desc_html(pen_inside)} 的内部，'
                            f'不是该笔的起点或终点。'
                        )
                    })
                if prev_valid is None:
                    notes.append("未成为笔端点：首笔形成前的候选分型，后续仍需等待反向有效分型确认")
                elif prev_valid["kind"] == row["kind"]:
                    current_more_extreme = row["price"] >= prev_valid["price"] if row["kind"] == "top" else row["price"] <= prev_valid["price"]
                    if current_more_extreme:
                        reason = (
                            f'当前{_fx_label(row["kind"])}价格 {_fmt_num(row["price"])} '
                            f'比前一有效同类 {_fmt_num(prev_valid["price"])} 更极端，但最终笔端点没有改写到当前分型；'
                            f'这说明它在 <code>CBiList.update_bi_sure</code> 流程中没有成功成为上一笔的新端点，'
                            f'随后被最终笔结构归入笔内部波动。'
                        )
                    else:
                        reason = (
                            f'前一有效同类分型价格 {_fmt_num(prev_valid["price"])} '
                            f'比当前 {_fmt_num(row["price"])} 更极端，按同类极值规则当前候选较弱。'
                        )
                    notes.append({
                        "html": (
                            f'未成为笔端点：与前一有效同类分型比较；'
                            f'影响分型：{self._fx_note_ref(prev_valid)}；原因：{reason}'
                        )
                    })
                    if next_valid and next_valid["kind"] != row["kind"]:
                        span_to_next = abs(next_valid["klc_idx"] - row["klc_idx"])
                        notes.append({
                            "html": (
                                f'若尝试用当前分型连接后续反向有效端点 {self._fx_note_ref(next_valid)}：'
                                f'合并K跨度={span_to_next}，严格模式要求 ≥ 4；'
                                f'{totally_check_html(row, next_valid)}。最终仍未采用当前分型作为该笔起点。'
                            )
                        })
                else:
                    span = abs(row["klc_idx"] - prev_valid["klc_idx"])
                    span_ok = span >= 4
                    totally_ok, totally_text = totally_check_result(prev_valid, row)
                    notes.append({
                        "html": (
                            f'未成为笔端点：与前一有效反向分型 {self._fx_note_ref(prev_valid)} '
                            f'做候选成笔检查；合并K跨度={span}，严格模式要求 ≥ 4，'
                            f'结果：{"通过" if span_ok else "不通过"}；'
                            f'{totally_text}。'
                        )
                    })
                    if span_ok and totally_ok and next_valid and next_valid["kind"] == row["kind"]:
                        next_stronger = next_valid["price"] >= row["price"] if row["kind"] == "top" else next_valid["price"] <= row["price"]
                        strength_text = "极值更强" if next_stronger else "最终结构采用"
                        notes.append({
                            "html": (
                                f'关键原因：上面的候选成笔检查已通过，因此当前分型不是因为与 '
                                f'{self._fx_note_ref(prev_valid)} 价格区间重叠而过滤；'
                                f'后续出现同类有效端点 {self._fx_note_ref(next_valid)}，'
                                f'其价格 {_fmt_num(next_valid["price"])} 相对当前 {_fmt_num(row["price"])} {strength_text}，'
                                f'最终笔结构选择后续端点作为该方向终点，当前分型退化为笔内部候选。'
                            )
                        })
                if next_valid:
                    notes.append({
                        "html": (
                            f'后续最终采用的有效端点：{self._fx_note_ref(next_valid)}。'
                            f'因此当前分型只作为从前一有效端点到该有效端点过程中的中间分型记录。'
                        )
                    })
        return fx_rows, pen_rows, seg_rows

    def _make_detail_tables(self, meta: CChanPlotMeta, chart_id: str, label: str) -> tuple[str, str, str]:
        fx_rows, pen_rows, seg_rows = self._build_report_rows(meta)
        input_type = self._time_input_type(label)
        input_title = "选择交易日期" if input_type == "date" else "选择交易日期和分钟"

        fx_body = []
        for row in fx_rows:
            row_class = "clickable" if row["status"] == "有效" else "clickable invalid"
            fx_body.append(
                f'<tr class="{row_class}" data-fx-row="{row["idx"]}" data-target-idx="{row["target_idx"]}">'
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
            pen_begin = row["target_idx"] - row["kl_cnt"] + 1
            pen_body.append(
                f'<tr class="clickable" data-pen-row="{row["idx"]}" data-pen-begin="{pen_begin}" data-pen-end="{row["target_idx"]}" data-target-idx="{row["target_idx"]}">'
                f'<td>{row["idx"]}</td>'
                f'<td class="pen-direction-cell">{_dir_label(row["direction"])}</td>'
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

        seg_body = []
        for row in seg_rows:
            seg_body.append(
                f'<tr class="clickable" data-seg-row="{row["idx"]}" data-seg-begin="{row["begin_x"]}" data-seg-end="{row["end_x"]}" data-target-idx="{row["target_idx"]}">'
                f'<td>{row["idx"]}</td>'
                f'<td class="seg-direction-cell">{_seg_dir_label(row["direction"])}</td>'
                f'<td>第{row["begin_bi_idx"] + 1}笔</td>'
                f'<td>第{row["end_bi_idx"] + 1}笔</td>'
                f'<td>{html.escape(row["begin_date"])}</td>'
                f'<td>{_fx_label(row["begin_kind"])}</td>'
                f'<td>{_fmt_num(row["begin_price"])}</td>'
                f'<td>{html.escape(row["end_date"])}</td>'
                f'<td>{_fx_label(row["end_kind"])}</td>'
                f'<td>{_fmt_num(row["end_price"])}</td>'
                f'<td>{row["bi_cnt"]}</td>'
                f'<td>{_fmt_num(row["amp"])}</td>'
                f'<td>{html.escape(row["status"])}</td>'
                f'<td class="note-cell">{self._note_html(row["notes"])}</td>'
                '</tr>'
            )

        fx_section = f"""
<section class="report-section">
  <div class="section-head">
    <h2>原始分型列表（形态{len(fx_rows)}个，有效{sum(1 for row in fx_rows if row["status"] == "有效")}个）</h2>
    <div class="section-actions">
      <label for="goto-{chart_id}">定位时间</label>
      <div class="goto-control">
        <input id="goto-{chart_id}" type="{input_type}" title="{input_title}">
        <button id="goto-btn-{chart_id}" type="button">确定</button>
      </div>
      <button class="collapse-btn" type="button" data-collapse="fx-table-{chart_id}">收起</button>
    </div>
  </div>
  <div id="fx-table-{chart_id}" class="table-wrap">
    <table class="data-table">
      <thead><tr><th>#</th><th>日期</th><th>类型</th><th>分型价格</th><th>分型最高</th><th>分型最低</th><th>状态</th><th>备注</th></tr></thead>
      <tbody>{"".join(fx_body) if fx_body else '<tr><td colspan="8">暂无分型</td></tr>'}</tbody>
    </table>
  </div>
</section>
"""
        pen_section = f"""
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
        seg_section = f"""
<section class="report-section">
  <div class="section-head">
    <h2>线段列表（共{len(seg_rows)}段，有效{sum(1 for row in seg_rows if row["status"] == "有效")}段）</h2>
    <div class="section-actions">
      <button class="collapse-btn" type="button" data-collapse="seg-table-{chart_id}">收起</button>
    </div>
  </div>
  <div id="seg-table-{chart_id}" class="table-wrap">
    <table class="data-table">
      <thead><tr><th>#</th><th>方向</th><th>起始笔</th><th>结束笔</th><th>起点日期</th><th>起点类型</th><th>起点价格</th><th>终点日期</th><th>终点类型</th><th>终点价格</th><th>笔数</th><th>价差</th><th>状态</th><th>备注</th></tr></thead>
      <tbody>{"".join(seg_body) if seg_body else '<tr><td colspan="14">暂无线段</td></tr>'}</tbody>
    </table>
  </div>
</section>
"""
        return fx_section, pen_section, seg_section

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

        valid_fractal_idx = set()
        for bi in meta.bi_list:
            valid_fractal_idx.add(int(bi.begin_klc_idx))
            valid_fractal_idx.add(int(bi.end_klc_idx))

        fractals = []
        for klc_pos, klc in enumerate(meta.klc_list):
            if klc.type not in (FX_TYPE.TOP, FX_TYPE.BOTTOM):
                continue
            box_start = klc.begin_idx
            box_end = klc.end_idx
            box_high = float(klc.high)
            box_low = float(klc.low)
            for neighbor_pos in (klc_pos - 1, klc_pos + 1):
                if 0 <= neighbor_pos < len(meta.klc_list):
                    neighbor = meta.klc_list[neighbor_pos]
                    box_start = min(box_start, neighbor.begin_idx)
                    box_end = max(box_end, neighbor.end_idx)
                    box_high = max(box_high, float(neighbor.high))
                    box_low = min(box_low, float(neighbor.low))
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
                "valid": int(klc.idx) in valid_fractal_idx,
                "row": len(fractals) + 1,
                "boxX": round(left + box_start * bar_w - 1, 1),
                "boxY": round(yp(box_high) - 1, 1),
                "boxW": round((box_end - box_start + 1) * bar_w + 1, 1),
                "boxH": round(max(5, yp(box_low) - yp(box_high) + 2), 1),
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
                "row": i + 1,
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
                "display": bool(getattr(seg, "display_only", False)),
                "row": i + 1,
            })
        display_seg_count = sum(1 for seg in segments if seg["display"])

        show_eigen = bool(self.plot_config.get("plot_eigen", False))
        eigen_boxes = []
        if show_eigen:
            for i, eigenfx in enumerate(meta.eigenfx_lst):
                kind = "top" if eigenfx.fx == FX_TYPE.TOP else "bottom"
                for j, ele in enumerate(eigenfx.ele):
                    eigen_boxes.append({
                        "i": i,
                        "part": j + 1,
                        "kind": kind,
                        "gap": bool(eigenfx.gap),
                        "x": round(left + ele.begin_x * bar_w, 1),
                        "y": round(yp(ele.end_y), 1),
                        "w": round(max(bar_w, (ele.end_x - ele.begin_x + 1) * bar_w), 1),
                        "h": round(max(5, yp(ele.begin_y) - yp(ele.end_y)), 1),
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
        label_pad = base_price_range * 0.087
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

        def moving_average(period: int) -> List[Optional[float]]:
            values: List[Optional[float]] = []
            closes: List[float] = []
            for bar in bars:
                closes.append(float(bar.close))
                if len(closes) < period:
                    values.append(None)
                else:
                    values.append(sum(closes[-period:]) / period)
            return values

        ma_defs = [
            (5, "#d8dee9"),
            (10, "#f59e0b"),
            (20, "#b43ac4"),
            (60, "#58a766"),
        ]
        ma_series = []
        for period, color in ma_defs:
            values = moving_average(period)
            points = [
                f"{left + i * bar_w + bar_w / 2:.1f},{yp(value):.1f}"
                for i, value in enumerate(values)
                if value is not None
            ]
            latest = next((value for value in reversed(values) if value is not None), None)
            ma_series.append({
                "period": period,
                "color": color,
                "points": " ".join(points),
                "latest": latest,
            })

        svg: List[str] = [
            f'<svg id="svg-{chart_id}" class="chan-chart-svg" xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="{max(left, total_width - width)} 0 {width} {height}" preserveAspectRatio="none">'
        ]
        svg.append(f'<rect x="{left}" y="{top}" width="{total_width-left-right}" height="{plot_h}" fill="#111827" stroke="#263244"/>')
        for i in range(9):
            y = top + plot_h * i / 8
            price = y_high - y_range * i / 8
            svg.append(f'<line x1="{left}" y1="{y:.1f}" x2="{total_width-right}" y2="{y:.1f}" stroke="#223044" stroke-width=".8" opacity=".78"/>')
            svg.append(f'<text class="chart-axis-label" x="{left-6}" y="{y:.1f}" text-anchor="end" fill="#7d89a1" font-size="10" dominant-baseline="middle">{_fmt_num(price, 2)}</text>')

        svg.append(f'<g id="ma-layer-{chart_id}" class="ma-layer">')
        legend_x = left + 8
        legend_y = top + 14
        for ma in ma_series:
            if ma["latest"] is None:
                continue
            text = f'MA{ma["period"]}: {_fmt_num(ma["latest"])}'
            svg.append(
                f'<text class="chart-axis-label" x="{legend_x:.1f}" y="{legend_y:.1f}" '
                f'fill="{ma["color"]}" font-size="10" font-weight="700">{html.escape(text)}</text>'
            )
            legend_x += max(56, len(text) * 6.2)

        for ma in ma_series:
            if ma["points"]:
                svg.append(
                    f'<polyline points="{ma["points"]}" fill="none" stroke="{ma["color"]}" '
                    f'stroke-width="1.05" opacity=".9" stroke-linejoin="round" stroke-linecap="round"/>'
                )
        svg.append("</g>")

        svg.append(f'<g id="kline-layer-{chart_id}" class="kline-layer active">')
        for i, bar in enumerate(bars):
            x = left + i * bar_w
            cx = x + bar_w / 2
            up = float(bar.close) >= float(bar.open)
            color = "#d64b3c" if up else "#58a766"
            body_top = yp(max(float(bar.open), float(bar.close)))
            body_bottom = yp(min(float(bar.open), float(bar.close)))
            svg.append(f'<line x1="{cx:.1f}" y1="{yp(bar.high):.1f}" x2="{cx:.1f}" y2="{yp(bar.low):.1f}" stroke="{color}" stroke-width="1.1" opacity=".95"/>')
            if body_bottom - body_top < 1:
                svg.append(f'<line x1="{x+1:.1f}" y1="{body_top:.1f}" x2="{x+bar_w-2:.1f}" y2="{body_top:.1f}" stroke="{color}" stroke-width="1.5"/>')
            else:
                svg.append(f'<rect x="{x+1:.1f}" y="{body_top:.1f}" width="{max(1, bar_w-2)}" height="{body_bottom-body_top:.1f}" fill="{color}" opacity=".92"/>')

        for klc in meta.klc_list:
            if klc.end_idx <= klc.begin_idx:
                continue
            stroke = "#d64b3c" if klc.type == FX_TYPE.TOP else "#4c6fff" if klc.type == FX_TYPE.BOTTOM else "#58a766"
            x = left + klc.begin_idx * bar_w - 1
            w = (klc.end_idx - klc.begin_idx + 1) * bar_w + 1
            y = yp(klc.high) - 1
            h = max(5, yp(klc.low) - yp(klc.high) + 2)
            svg.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
                f'fill="none" stroke="{stroke}" stroke-width="1" stroke-dasharray="4 3" opacity=".62" rx="1"/>'
            )
        svg.append("</g>")

        for zs in zs_rects:
            color = "#f59e0b" if zs["level"].startswith("bi") else "#ef4444"
            width_px = 1.5 if zs["level"] == "bi" else 2.4
            dash = "" if zs["sure"] else ' stroke-dasharray="7 4"'
            opacity = ".88" if zs["level"] in ("bi", "seg") else ".52"
            svg.append(
                f'<rect x="{zs["x"]:.1f}" y="{zs["y"]:.1f}" width="{zs["w"]:.1f}" height="{zs["h"]:.1f}" '
                f'fill="none" stroke="{color}" stroke-width="{width_px}" opacity="{opacity}" rx="1"{dash}/>'
            )
            if zs["level"] in ("bi", "seg"):
                svg.append(
                    f'<text class="chart-note-label" x="{zs["x"] + 4:.1f}" y="{zs["y"] - 4:.1f}" fill="{color}" font-size="10">'
                    f'ZS {_fmt_num(zs["low"])}-{_fmt_num(zs["high"])}</text>'
                )

        for pen in pens:
            dash = "" if pen["sure"] else ' stroke-dasharray="5 4"'
            svg.append(
                f'<line class="chart-pen-hit" data-pen-row="{pen["row"]}" x1="{pen["x1"]:.1f}" y1="{pen["y1"]:.1f}" x2="{pen["x2"]:.1f}" y2="{pen["y2"]:.1f}" '
                f'stroke="transparent" stroke-width="10" stroke-linecap="round"{dash}/>'
            )
            svg.append(
                f'<line class="chart-pen-line" data-pen-row="{pen["row"]}" x1="{pen["x1"]:.1f}" y1="{pen["y1"]:.1f}" x2="{pen["x2"]:.1f}" y2="{pen["y2"]:.1f}" '
                f'stroke="#cbd5e1" stroke-width="1.25" opacity=".72" stroke-linecap="round"{dash}/>'
            )

        for seg in segments:
            dash = "" if seg["sure"] else ' stroke-dasharray="7 5"'
            seg_color = "#2dd4bf" if seg["display"] else "#69a35f"
            seg_width = "4.6" if seg["display"] else "2.4"
            seg_opacity = "1" if seg["display"] else ".72"
            svg.append(
                f'<line class="chart-seg-hit" data-seg-row="{seg["row"]}" data-display-seg="{1 if seg["display"] else 0}" x1="{seg["x1"]:.1f}" y1="{seg["y1"]:.1f}" x2="{seg["x2"]:.1f}" y2="{seg["y2"]:.1f}" '
                f'stroke="transparent" stroke-width="18" stroke-linecap="round"{dash}/>'
            )
            svg.append(
                f'<line class="chart-seg-line" data-seg-row="{seg["row"]}" data-display-seg="{1 if seg["display"] else 0}" x1="{seg["x1"]:.1f}" y1="{seg["y1"]:.1f}" x2="{seg["x2"]:.1f}" y2="{seg["y2"]:.1f}" '
                f'stroke="{seg_color}" stroke-width="{seg_width}" opacity="{seg_opacity}" stroke-linecap="round"{dash}/>'
            )
            if seg["display"]:
                svg.append(
                    f'<circle class="chart-seg-endpoint" cx="{seg["x1"]:.1f}" cy="{seg["y1"]:.1f}" r="3.8" fill="{seg_color}" opacity=".95"/>'
                )
                svg.append(
                    f'<circle class="chart-seg-endpoint" cx="{seg["x2"]:.1f}" cy="{seg["y2"]:.1f}" r="3.8" fill="{seg_color}" opacity=".95"/>'
                )

        svg.append(f'<g id="eigen-layer-{chart_id}" class="eigen-layer">')
        for box in eigen_boxes:
            color = "#ef4444" if box["kind"] == "top" else "#38bdf8"
            dash = ' stroke-dasharray="6 4"' if box["gap"] else ""
            svg.append(
                f'<rect x="{box["x"]:.1f}" y="{box["y"]:.1f}" width="{box["w"]:.1f}" height="{box["h"]:.1f}" '
                f'fill="{color}" fill-opacity=".12" stroke="{color}" stroke-width="1.25" opacity=".82" rx="1"{dash}/>'
            )
            svg.append(
                f'<text class="chart-note-label" x="{box["x"] + 3:.1f}" y="{box["y"] + 10:.1f}" '
                f'fill="{color}" font-size="9">E{box["i"]}.{box["part"]}</text>'
            )
        svg.append("</g>")

        svg.append(f'<g id="fractal-range-layer-{chart_id}"></g>')
        svg.append(f'<g id="fractal-ref-layer-{chart_id}"></g>')
        svg.append(f'<g id="fractal-detail-layer-{chart_id}" class="fractal-detail-layer">')
        for idx, fx in enumerate(fractals):
            x, y, price = fx["x"], fx["y"], fx["price"]
            valid = bool(fx["valid"])
            stroke_extra = '' if valid else ' stroke-dasharray="2 2" stroke-width="1" opacity=".92"'
            if fx["kind"] == "top":
                fill = "#4c6fff" if valid else "none"
                stroke = "#4c6fff" if valid else "#8fb1ff"
                svg.append(
                    f'<polygon class="chart-fractal-marker" data-fx="{idx}" data-fx-row="{fx["row"]}" points="{x:.1f},{y:.1f} {x-1.8:.1f},{y-3.2:.1f} {x+1.8:.1f},{y-3.2:.1f}" fill="{fill}" stroke="{stroke}"{stroke_extra}/>'
                )
                svg.append(f'<text class="chart-price-label" data-fx-row="{fx["row"]}" x="{x:.1f}" y="{y-5:.1f}" text-anchor="middle" fill="#cbd5e1" font-size="3.6">{_fmt_num(price)}</text>')
            else:
                fill = "#f59e0b" if valid else "none"
                stroke = "#f59e0b" if valid else "#fbbf24"
                svg.append(
                    f'<polygon class="chart-fractal-marker" data-fx="{idx}" data-fx-row="{fx["row"]}" points="{x:.1f},{y:.1f} {x-1.8:.1f},{y+3.2:.1f} {x+1.8:.1f},{y+3.2:.1f}" fill="{fill}" stroke="{stroke}"{stroke_extra}/>'
                )
                svg.append(f'<text class="chart-price-label" data-fx-row="{fx["row"]}" x="{x:.1f}" y="{y+6:.1f}" text-anchor="middle" fill="#cbd5e1" font-size="3.6">{_fmt_num(price)}</text>')
        svg.append("</g>")

        svg.append("<defs>")
        for bsp in bs_points:
            color = "#ef4444" if bsp["buy"] else "#22c55e"
            svg.append(
                f'<marker id="arrow-{chart_id}-{bsp["i"]}" markerWidth="7" markerHeight="7" refX="3.5" refY="3.5" orient="auto">'
                f'<path d="M0,0 L7,3.5 L0,7 Z" fill="{color}"/></marker>'
            )
        svg.append("</defs>")
        for bsp in bs_points:
            color = "#ef4444" if bsp["buy"] else "#22c55e"
            arrow_start_y = bsp["labelY"]
            text_gap = 9 if bsp["seg"] else 7
            text_y = arrow_start_y + text_gap if bsp["buy"] else arrow_start_y - text_gap
            point_y = bsp["y"]
            arrow_end_y = point_y + (4 if bsp["buy"] else -4)
            fontsize = 10 if bsp["seg"] else 9
            svg.append(
                f'<line x1="{bsp["x"]:.1f}" y1="{arrow_start_y:.1f}" x2="{bsp["x"]:.1f}" y2="{arrow_end_y:.1f}" '
                f'stroke="{color}" stroke-width="1.15" opacity=".9" marker-end="url(#arrow-{chart_id}-{bsp["i"]})"/>'
            )
            svg.append(
                f'<text class="chart-bsp-label" x="{bsp["x"]:.1f}" y="{text_y:.1f}" text-anchor="middle" fill="{color}" '
                f'font-size="{fontsize}" font-weight="700" dominant-baseline="middle">'
                f'{html.escape(bsp["text"])}</text>'
            )

        svg.append(f'<rect id="focused-band-{chart_id}" x="{left}" y="{top}" width="{bar_w}" height="{plot_h}" fill="#60a5fa" opacity=".14" style="display:none;pointer-events:none"/>')
        svg.append(f'<line id="focused-{chart_id}" x1="{left}" y1="{top}" x2="{left}" y2="{height-bottom}" stroke="#93c5fd" stroke-width="1.6" stroke-dasharray="5 4" style="display:none;pointer-events:none"/>')
        svg.append(f'<line id="selected-{chart_id}" x1="{left}" y1="{top}" x2="{left}" y2="{height-bottom}" stroke="#94a3b8" stroke-width="1.2" stroke-dasharray="4 3" style="display:none;pointer-events:none"/>')
        svg.append(
            f'<g id="crosshair-{chart_id}" style="display:none;pointer-events:none">'
            f'<line id="crosshair-v-{chart_id}" x1="{left}" y1="{top}" x2="{left}" y2="{height-bottom}" stroke="#94a3b8" stroke-width="1" stroke-dasharray="3 3" opacity=".75"/>'
            f'<line id="crosshair-h-{chart_id}" x1="{left}" y1="{top}" x2="{total_width-right}" y2="{top}" stroke="#94a3b8" stroke-width="1" stroke-dasharray="3 3" opacity=".75"/>'
            f'<rect id="crosshair-price-bg-{chart_id}" x="{left}" y="{top-9}" width="54" height="18" rx="3" fill="#334155" opacity=".96"/>'
            f'<text id="crosshair-price-text-{chart_id}" class="crosshair-price-text" x="{left+27}" y="{top}" text-anchor="middle" fill="#fff" font-size="10" dominant-baseline="middle">-</text>'
            "</g>"
        )
        svg.append("</svg>")
        fx_table, pen_table, seg_table = self._make_detail_tables(meta, chart_id, label)

        return f"""
{fx_table}
<div class="chart-shell" data-seg-count="{len(segments)}" data-display-seg-count="{display_seg_count}">
  <div class="chart-toolbar">
    <strong>{html.escape(label)}</strong>
    <button id="zoom-in-{chart_id}" title="放大" type="button">+</button>
    <span id="zoom-label-{chart_id}" class="zoom-label">-</span>
    <button id="zoom-out-{chart_id}" title="缩小" type="button">-</button>
    <button id="reset-{chart_id}" title="重置视图" type="button">重置</button>
    <button id="clear-{chart_id}" title="清理分型标记" type="button">清理</button>
    <button id="kline-toggle-{chart_id}" class="kline-toggle active" title="显示/隐藏K线" type="button" aria-pressed="true">K线</button>
    <button id="ma-toggle-{chart_id}" class="ma-toggle" title="显示/隐藏均线" type="button" aria-pressed="false">均线</button>
    <button id="eigen-toggle-{chart_id}" class="eigen-toggle" title="显示/隐藏线段特征序列" type="button" aria-pressed="false">特征</button>
    <span class="chart-help">滚轮/↑↓缩放 · 拖拽平移 · 双击十字星 · 悬停查看 OHLC</span>
  </div>
  <div id="wrap-{chart_id}" class="chart-wrap" tabindex="0" aria-label="{html.escape(label)} K线图">
    {"".join(svg)}
    <div id="tooltip-{chart_id}" class="tooltip"></div>
  </div>
  <div class="legend">
    <span><i class="swatch" style="background:#d64b3c"></i>上涨K线</span>
    <span><i class="swatch" style="background:#58a766"></i>下跌K线</span>
    <span><i class="swatch" style="background:#4c6fff"></i>顶分型</span>
    <span><i class="swatch" style="background:#f59e0b"></i>底分型/中枢</span>
    <span><i class="swatch" style="background:#cbd5e1"></i>笔</span>
    <span><i class="swatch" style="background:#69a35f"></i>段</span>
    <span><i class="swatch" style="background:#ef4444"></i>顶特征序列</span>
    <span><i class="swatch" style="background:#38bdf8"></i>底特征序列</span>
    <span><i class="swatch" style="background:#ef4444"></i>买点</span>
    <span><i class="swatch" style="background:#22c55e"></i>卖点</span>
  </div>
</div>
{pen_table}
{seg_table}
<script>
(function() {{
var eventController = new AbortController();
window.__chanChartAbortControllers = window.__chanChartAbortControllers || [];
window.__chanChartAbortControllers.push(eventController);
var eventSignal = eventController.signal;
var data = {{
  bars:{_json(bar_data)},
  fractals:{_json(fractals)},
  pens:{_json(pens)},
  segments:{_json(segments)},
  eigenBoxes:{_json(eigen_boxes)},
  zs:{_json(zs_rects)},
  bsPoints:{_json(bs_points)},
  totalBars:{len(bars)}
}};
var svg = document.getElementById('svg-{chart_id}');
var wrap = document.getElementById('wrap-{chart_id}');
var tip = document.getElementById('tooltip-{chart_id}');
var selected = document.getElementById('selected-{chart_id}');
var focused = document.getElementById('focused-{chart_id}');
var focusedBand = document.getElementById('focused-band-{chart_id}');
var klineLayer = document.getElementById('kline-layer-{chart_id}');
var klineToggle = document.getElementById('kline-toggle-{chart_id}');
var maLayer = document.getElementById('ma-layer-{chart_id}');
var maToggle = document.getElementById('ma-toggle-{chart_id}');
var eigenLayer = document.getElementById('eigen-layer-{chart_id}');
var eigenToggle = document.getElementById('eigen-toggle-{chart_id}');
var fractalDetailLayer = document.getElementById('fractal-detail-layer-{chart_id}');
var fractalRangeLayer = document.getElementById('fractal-range-layer-{chart_id}');
var fractalRefLayer = document.getElementById('fractal-ref-layer-{chart_id}');
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
var fractalDetailMaxBars = 138;
var minViewW = Math.max(minVisibleBars * barW, 180);
var maxViewW = Math.max(totalWidth, minViewW);
var crosshairEnabled = false;
var crosshairPoint = null;
var isPanning = false, panStartX = 0, panStartY = 0, panOriginX = 0, panOriginY = 0;
var panFrame = null, pendingPanOriginX = originX, pendingPanOriginY = originY;
var zoomFrame = null, zoomEndTimer = null, pendingZoomFactor = 1, pendingZoomRx = 0.5, pendingZoomRy = 0.5;
var hoverFrame = null, pendingHoverEvent = null, lastTipIdx = -1;
window.__chanChartViews = window.__chanChartViews || {{}};

function rect() {{
  var r = svg.getBoundingClientRect();
  return r.width && r.height ? r : {{left:0,top:0,width:{width},height:{height}}};
}}
function viewHeightForWidth(w) {{
  var r = rect();
  return Math.max(120, Math.min(chartH, w * r.height / r.width));
}}
function priceToY(price) {{
  return top + plotH - ((price - yLow) / yRange) * plotH;
}}
function autoFitY() {{
  var start = Math.max(0, Math.floor((originX - left) / barW) - 2);
  var end = Math.min(data.bars.length - 1, Math.ceil((originX + viewW - left) / barW) + 2);
  var high = -Infinity, low = Infinity;
  for (var i = start; i <= end; i++) {{
    high = Math.max(high, data.bars[i].h);
    low = Math.min(low, data.bars[i].l);
  }}
  if (!isFinite(high) || !isFinite(low) || high <= low) {{
    originY = 0;
    viewH = chartH;
    return;
  }}
  var yTop = priceToY(high);
  var yBottom = priceToY(low);
  var visibleH = Math.max(48, yBottom - yTop);
  var pad = Math.max(18, visibleH * 0.16);
  viewH = Math.max(96, Math.min(chartH, visibleH + pad * 2));
  originY = Math.max(0, Math.min(chartH - viewH, yTop - pad));
}}
function applyViewBox(light) {{
  viewW = Math.max(minViewW, Math.min(maxViewW, viewW));
  originX = Math.max(0, Math.min(Math.max(0, totalWidth - viewW), originX));
  autoFitY();
  svg.setAttribute('viewBox', originX.toFixed(1) + ' ' + originY.toFixed(1) + ' ' + viewW.toFixed(1) + ' ' + viewH.toFixed(1));
  if (!light) {{
    updateZoomLabel();
    updateCrosshair();
  }}
  rememberView();
}}
function updateViewBox() {{
  applyViewBox(false);
}}
function updateViewBoxFast() {{
  applyViewBox(true);
}}
function currentViewState() {{
  var pinnedRight = Math.abs((originX + viewW) - totalWidth) <= barW * 2;
  return {{
    originX: originX,
    viewW: viewW,
    pinnedRight: pinnedRight,
    totalWidth: totalWidth,
    barW: barW
  }};
}}
function rememberView() {{
  window.__chanChartViews['{chart_id}'] = currentViewState();
}}
function restoreView(state) {{
  if (!state) return false;
  viewW = Number(state.viewW) || viewW;
  if (state.pinnedRight) {{
    originX = Math.max(0, totalWidth - viewW);
  }} else {{
    var oldTotalWidth = Number(state.totalWidth) || totalWidth;
    var delta = totalWidth - oldTotalWidth;
    originX = (Number(state.originX) || originX) + delta;
  }}
  updateViewBox();
  return true;
}}
window.__chanViewControllers = window.__chanViewControllers || {{}};
window.__chanViewControllers['{chart_id}'] = {{
  capture: currentViewState,
  restore: restoreView
}};
window.__chanCaptureViews = function() {{
  var views = {{}};
  Object.keys(window.__chanViewControllers || {{}}).forEach(function(id) {{
    try {{ views[id] = window.__chanViewControllers[id].capture(); }} catch (err) {{}}
  }});
  return views;
}};
window.__chanRestoreViews = function(views) {{
  Object.keys(views || {{}}).forEach(function(id) {{
    var controller = window.__chanViewControllers && window.__chanViewControllers[id];
    if (controller && controller.restore) {{
      try {{ controller.restore(views[id]); }} catch (err) {{}}
    }}
  }});
}};
function resetView() {{
  var r = rect();
  var targetBars = Math.min(data.totalBars, Math.max(120, Math.round(r.width / 7.8)));
  viewW = Math.max(minViewW, Math.min(maxViewW, targetBars * barW));
  originX = Math.max(0, totalWidth - viewW);
  updateViewBox();
}}
function updateZoomLabel() {{
  var visibleBars = Math.max(1, Math.round(viewW / barW));
  document.getElementById('zoom-label-{chart_id}').textContent = visibleBars + '根';
  fractalDetailLayer.classList.toggle('active', visibleBars <= fractalDetailMaxBars);
  updateLabelScale();
}}
function updateLabelScale() {{
  var r = rect();
  var scale = Math.max(0.36, Math.min(1, viewW / 780));
  var axisScale = Math.max(0.62, Math.min(1, viewW / 900));
  var axisSize = (10 * axisScale).toFixed(2);
  var priceSize = Math.max(2.8, Math.min(3.6, 3.6 * scale)).toFixed(2);
  var noteSize = (10 * scale).toFixed(2);
  var bspSize = Math.max(7, Math.min(12, 10 * viewW / Math.max(1, r.width))).toFixed(2);
  panelRoot.querySelectorAll('.chart-axis-label').forEach(function(node) {{ node.setAttribute('font-size', axisSize); }});
  panelRoot.querySelectorAll('.chart-price-label').forEach(function(node) {{ node.setAttribute('font-size', priceSize); }});
  panelRoot.querySelectorAll('.chart-note-label').forEach(function(node) {{ node.setAttribute('font-size', noteSize); }});
  panelRoot.querySelectorAll('.chart-bsp-label').forEach(function(node) {{ node.setAttribute('font-size', bspSize); }});
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
  var r = rect();
  var xScale = viewW / Math.max(1, r.width);
  var yScale = viewH / Math.max(1, r.height);
  var labelText = price.toFixed(2);
  var fontSize = Math.max(3.5, Math.min(7, 6 * xScale));
  var labelW = Math.max(28, Math.min(48, labelText.length * 3.8 + 9)) * xScale;
  var labelH = 11 * yScale;
  var margin = 20 * xScale;
  var labelX = Math.max(originX + margin, left + 2 * xScale);
  if (labelX + labelW > originX + viewW - 4 * xScale) labelX = originX + viewW - labelW - 4 * xScale;
  crosshairV.setAttribute('x1', x.toFixed(1));
  crosshairV.setAttribute('x2', x.toFixed(1));
  crosshairV.setAttribute('y1', originY.toFixed(1));
  crosshairV.setAttribute('y2', (originY + viewH).toFixed(1));
  crosshairH.setAttribute('x1', originX.toFixed(1));
  crosshairH.setAttribute('x2', (originX + viewW).toFixed(1));
  crosshairH.setAttribute('y1', y.toFixed(1));
  crosshairH.setAttribute('y2', y.toFixed(1));
  crosshairBg.setAttribute('x', labelX.toFixed(1));
  crosshairBg.setAttribute('y', (y - labelH / 2).toFixed(1));
  crosshairBg.setAttribute('width', labelW.toFixed(1));
  crosshairBg.setAttribute('height', labelH.toFixed(1));
  crosshairBg.setAttribute('rx', (2 * xScale).toFixed(1));
  crosshairText.setAttribute('x', (labelX + labelW / 2).toFixed(1));
  crosshairText.setAttribute('y', y.toFixed(1));
  crosshairText.setAttribute('font-size', fontSize.toFixed(1));
  crosshairText.textContent = labelText;
}}
function zoomAt(factor, rx, ry) {{
  var oldW = viewW, oldH = viewH;
  viewW = Math.max(minViewW, Math.min(maxViewW, viewW * factor));
  originX += rx * (oldW - viewW);
  originY += ry * (oldH - viewH);
  updateViewBox();
}}
function zoomAtFast(factor, rx, ry) {{
  var oldW = viewW, oldH = viewH;
  viewW = Math.max(minViewW, Math.min(maxViewW, viewW * factor));
  originX += rx * (oldW - viewW);
  originY += ry * (oldH - viewH);
  updateViewBoxFast();
}}
function focusChart() {{
  if (document.activeElement !== wrap) wrap.focus({{preventScroll:true}});
}}
function nearestBar(clientX) {{
  var r = rect();
  if (!data.bars.length || !r.width) return -1;
  var x = (clientX - r.left) / r.width * viewW + originX;
  var firstX = data.bars[0].x;
  var idx = Math.round((x - firstX) / barW);
  if (idx < 0 || idx >= data.bars.length) return -1;
  return Math.abs(data.bars[idx].x - x) <= barW * 1.5 ? idx : -1;
}}
function schedulePanFrame() {{
  if (panFrame !== null) return;
  panFrame = window.requestAnimationFrame(function() {{
    panFrame = null;
    originX = pendingPanOriginX;
    originY = pendingPanOriginY;
    updateViewBoxFast();
  }});
}}
function finishPan() {{
  if (!isPanning) return;
  isPanning = false;
  wrap.classList.remove('is-panning');
  if (panFrame !== null) {{
    window.cancelAnimationFrame(panFrame);
    panFrame = null;
    originX = pendingPanOriginX;
    originY = pendingPanOriginY;
  }}
  updateViewBox();
}}
function scheduleWheelZoom(factor, rx, ry) {{
  pendingZoomFactor *= factor;
  pendingZoomRx = rx;
  pendingZoomRy = ry;
  wrap.classList.add('is-zooming');
  hideTip();
  if (zoomFrame === null) {{
    zoomFrame = window.requestAnimationFrame(function() {{
      var factorToApply = pendingZoomFactor;
      var rxToApply = pendingZoomRx;
      var ryToApply = pendingZoomRy;
      zoomFrame = null;
      pendingZoomFactor = 1;
      zoomAtFast(factorToApply, rxToApply, ryToApply);
    }});
  }}
  if (zoomEndTimer !== null) window.clearTimeout(zoomEndTimer);
  zoomEndTimer = window.setTimeout(function() {{
    zoomEndTimer = null;
    if (zoomFrame !== null) {{
      window.cancelAnimationFrame(zoomFrame);
      zoomFrame = null;
      var factorToApply = pendingZoomFactor;
      var rxToApply = pendingZoomRx;
      var ryToApply = pendingZoomRy;
      pendingZoomFactor = 1;
      zoomAtFast(factorToApply, rxToApply, ryToApply);
    }}
    wrap.classList.remove('is-zooming');
    updateViewBox();
  }}, 90);
}}
function showTip(idx, clientX, clientY) {{
  if (idx < 0 || idx >= data.bars.length) {{ tip.style.display = 'none'; return; }}
  var b = data.bars[idx];
  if (idx !== lastTipIdx) {{
    selected.setAttribute('x1', b.x.toFixed(1));
    selected.setAttribute('x2', b.x.toFixed(1));
    selected.style.display = 'block';
    tip.innerHTML = '<div><b>' + b.dt + '</b></div>' +
      '<div>开盘: ' + b.o.toFixed(2) + ' | 最高: ' + b.h.toFixed(2) + '</div>' +
      '<div>收盘: ' + b.c.toFixed(2) + ' | 最低: ' + b.l.toFixed(2) + '</div>';
    lastTipIdx = idx;
  }}
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
function hideTip() {{
  lastTipIdx = -1;
  tip.style.display = 'none';
}}
function handleHover(e) {{
  if (!e) return;
  var p = svgPoint(e);
  if (crosshairEnabled) {{ crosshairPoint = p; updateCrosshair(); }}
  var idx = nearestBar(e.clientX);
  if (idx >= 0 && p.y >= top && p.y <= chartH - bottom) showTip(idx, e.clientX, e.clientY);
  else hideTip();
}}
function scheduleHover(e) {{
  pendingHoverEvent = e;
  if (hoverFrame !== null) return;
  hoverFrame = window.requestAnimationFrame(function() {{
    var eventToHandle = pendingHoverEvent;
    hoverFrame = null;
    pendingHoverEvent = null;
    handleHover(eventToHandle);
  }});
}}
function focusBar(idx, shouldScroll) {{
  idx = Math.max(0, Math.min(data.bars.length - 1, Number(idx) || 0));
  var b = data.bars[idx];
  var desiredW = Math.min(maxViewW, Math.max(minViewW, 96 * barW));
  viewW = desiredW;
  originX = b.x - viewW * 0.5;
  updateViewBox();
  selected.setAttribute('x1', b.x.toFixed(1));
  selected.setAttribute('x2', b.x.toFixed(1));
  selected.style.display = 'block';
  focused.setAttribute('x1', b.x.toFixed(1));
  focused.setAttribute('x2', b.x.toFixed(1));
  focused.style.display = 'block';
  focusedBand.setAttribute('x', (b.x - barW / 2).toFixed(1));
  focusedBand.setAttribute('width', barW.toFixed(1));
  focusedBand.style.display = 'block';
  if (shouldScroll) wrap.scrollIntoView({{behavior:'smooth', block:'center'}});
}}
function focusPen(beginIdx, endIdx) {{
  beginIdx = Math.max(0, Math.min(data.bars.length - 1, Number(beginIdx) || 0));
  endIdx = Math.max(beginIdx, Math.min(data.bars.length - 1, Number(endIdx) || beginIdx));
  var beginBar = data.bars[beginIdx], endBar = data.bars[endIdx];
  var penW = Math.max(minViewW, (endBar.x - beginBar.x) + 28 * barW);
  viewW = Math.min(maxViewW, penW);
  originX = (beginBar.x + endBar.x) * 0.5 - viewW * 0.5;
  updateViewBox();
  selected.setAttribute('x1', beginBar.x.toFixed(1));
  selected.setAttribute('x2', beginBar.x.toFixed(1));
  selected.style.display = 'block';
  focused.setAttribute('x1', endBar.x.toFixed(1));
  focused.setAttribute('x2', endBar.x.toFixed(1));
  focused.style.display = 'block';
  focusedBand.setAttribute('x', (beginBar.x - barW / 2).toFixed(1));
  focusedBand.setAttribute('width', Math.max(barW, endBar.x - beginBar.x + barW).toFixed(1));
  focusedBand.style.display = 'block';
}}
function focusRange(beginIdx, endIdx, padBars) {{
  beginIdx = Math.max(0, Math.min(data.bars.length - 1, Number(beginIdx) || 0));
  endIdx = Math.max(beginIdx, Math.min(data.bars.length - 1, Number(endIdx) || beginIdx));
  padBars = Number(padBars) || 28;
  var beginBar = data.bars[beginIdx], endBar = data.bars[endIdx];
  var rangeW = Math.max(minViewW, (endBar.x - beginBar.x) + padBars * barW);
  viewW = Math.min(maxViewW, rangeW);
  originX = (beginBar.x + endBar.x) * 0.5 - viewW * 0.5;
  updateViewBox();
  selected.setAttribute('x1', beginBar.x.toFixed(1));
  selected.setAttribute('x2', beginBar.x.toFixed(1));
  selected.style.display = 'block';
  focused.setAttribute('x1', endBar.x.toFixed(1));
  focused.setAttribute('x2', endBar.x.toFixed(1));
  focused.style.display = 'block';
  focusedBand.setAttribute('x', (beginBar.x - barW / 2).toFixed(1));
  focusedBand.setAttribute('width', Math.max(barW, endBar.x - beginBar.x + barW).toFixed(1));
  focusedBand.style.display = 'block';
}}
function findBarByTime(value) {{
  value = String(value || '').trim();
  if (!value) return -1;
  var normalized = value.replace('T', ' ').replace(/[年月]/g, '/').replace(/[日]/g, '').replace(/-/g, '/').replace(/\\s+/g, ' ');
  var best = -1;
  for (var i = 0; i < data.bars.length; i++) {{
    var dt = data.bars[i].dt.replace(/-/g, '/');
    if (dt.indexOf(normalized) >= 0 || normalized.indexOf(dt) >= 0) return i;
    if (dt.slice(0, 10) === normalized.slice(0, 10)) best = i;
  }}
  return best;
}}
function highlightFxRow(rowId) {{
  var row = panelRoot.querySelector('tr[data-fx-row="' + rowId + '"]');
  var tableWrap = document.getElementById('fx-table-{chart_id}');
  if (!row || !tableWrap) return;
  panelRoot.querySelectorAll('tr.focused-row').forEach(function(x) {{ x.classList.remove('focused-row'); }});
  row.classList.add('focused-row');
  tableWrap.style.display = '';
  var rowTop = row.offsetTop;
  tableWrap.scrollTop = Math.max(0, rowTop - tableWrap.clientHeight * 0.42);
}}
function highlightPenRow(rowId) {{
  var row = panelRoot.querySelector('tr[data-pen-row="' + rowId + '"]');
  var tableWrap = document.getElementById('pen-table-{chart_id}');
  if (!row || !tableWrap) return;
  panelRoot.querySelectorAll('tr.focused-row').forEach(function(x) {{ x.classList.remove('focused-row'); }});
  clearSegHighlight();
  panelRoot.querySelectorAll('.chart-pen-line.focused-pen').forEach(function(x) {{
    x.classList.remove('focused-pen');
    x.setAttribute('stroke-width', '1.25');
    x.setAttribute('opacity', '.72');
  }});
  row.classList.add('focused-row');
  var penLine = panelRoot.querySelector('.chart-pen-line[data-pen-row="' + rowId + '"]');
  if (penLine) {{
    penLine.classList.add('focused-pen');
    penLine.setAttribute('stroke-width', '2.6');
    penLine.setAttribute('opacity', '1');
  }}
  tableWrap.style.display = '';
  tableWrap.scrollTop = Math.max(0, row.offsetTop - tableWrap.clientHeight * 0.42);
}}
function clearSegHighlight() {{
  panelRoot.querySelectorAll('.chart-seg-line.focused-seg').forEach(function(x) {{
    x.classList.remove('focused-seg');
    x.setAttribute('stroke-width', '2.4');
    x.setAttribute('opacity', '.72');
  }});
}}
function highlightSegRow(rowId) {{
  var row = panelRoot.querySelector('tr[data-seg-row="' + rowId + '"]');
  var tableWrap = document.getElementById('seg-table-{chart_id}');
  if (!row || !tableWrap) return;
  panelRoot.querySelectorAll('tr.focused-row').forEach(function(x) {{ x.classList.remove('focused-row'); }});
  panelRoot.querySelectorAll('.chart-pen-line.focused-pen').forEach(function(x) {{
    x.classList.remove('focused-pen');
    x.setAttribute('stroke-width', '1.25');
    x.setAttribute('opacity', '.72');
  }});
  clearSegHighlight();
  row.classList.add('focused-row');
  var segLine = panelRoot.querySelector('.chart-seg-line[data-seg-row="' + rowId + '"]');
  if (segLine) {{
    segLine.classList.add('focused-seg');
    segLine.setAttribute('stroke-width', '4.2');
    segLine.setAttribute('opacity', '1');
  }}
  tableWrap.style.display = '';
  tableWrap.scrollTop = Math.max(0, row.offsetTop - tableWrap.clientHeight * 0.42);
}}
function markFractalRange(rowId) {{
  var fx = data.fractals.find(function(item) {{ return String(item.row) === String(rowId); }});
  if (!fx || !fractalRangeLayer) return;
  var color = fx.kind === 'top' ? '#4c6fff' : '#f59e0b';
  var rectNode = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
  rectNode.setAttribute('class', 'fractal-range-box');
  rectNode.setAttribute('x', fx.boxX);
  rectNode.setAttribute('y', fx.boxY);
  rectNode.setAttribute('width', fx.boxW);
  rectNode.setAttribute('height', fx.boxH);
  rectNode.setAttribute('fill', 'none');
  rectNode.setAttribute('stroke', color);
  rectNode.setAttribute('stroke-width', '1.3');
  rectNode.setAttribute('stroke-dasharray', '3 2');
  rectNode.setAttribute('opacity', '.95');
  rectNode.setAttribute('rx', '1');
  fractalRangeLayer.appendChild(rectNode);
}}
function highlightFractalOnChart(rowId) {{
  var fx = data.fractals.find(function(item) {{ return String(item.row) === String(rowId); }});
  if (!fx || !fractalRefLayer) return;
  panelRoot.querySelectorAll('[data-fx-row].fx-ref-active').forEach(function(node) {{
    node.classList.remove('fx-ref-active');
  }});
  panelRoot.querySelectorAll('[data-fx-row="' + rowId + '"].chart-price-label,[data-fx-row="' + rowId + '"].chart-fractal-marker').forEach(function(node) {{
    node.classList.add('fx-ref-active');
  }});
  fractalRefLayer.replaceChildren();
  var color = fx.kind === 'top' ? '#60a5fa' : '#fbbf24';
  var rectNode = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
  rectNode.setAttribute('class', 'fractal-ref-box');
  rectNode.setAttribute('x', fx.boxX);
  rectNode.setAttribute('y', fx.boxY);
  rectNode.setAttribute('width', fx.boxW);
  rectNode.setAttribute('height', fx.boxH);
  rectNode.setAttribute('fill', color);
  rectNode.setAttribute('fill-opacity', '.10');
  rectNode.setAttribute('stroke', color);
  rectNode.setAttribute('stroke-width', '1.8');
  rectNode.setAttribute('stroke-dasharray', '2 2');
  rectNode.setAttribute('rx', '1');
  fractalRefLayer.appendChild(rectNode);
}}
function handleFractalPick(rowId) {{
  highlightFxRow(rowId);
  markFractalRange(rowId);
  highlightFractalOnChart(rowId);
}}

wrap.addEventListener('wheel', function(e) {{
  e.preventDefault();
  focusChart();
  var r = rect();
  scheduleWheelZoom(
    e.deltaY < 0 ? 0.70 : 1.43,
    Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)),
    Math.max(0, Math.min(1, (e.clientY - r.top) / r.height))
  );
}}, {{passive:false}});
wrap.addEventListener('mousedown', function(e) {{
  if (e.button !== 0) return;
  if (e.target && e.target.closest && e.target.closest('.chart-price-label,.chart-fractal-marker,.chart-pen-line,.chart-pen-hit,.chart-seg-line,.chart-seg-hit')) return;
  focusChart();
  isPanning = true; panStartX = e.clientX; panStartY = e.clientY; panOriginX = originX; panOriginY = originY;
  pendingPanOriginX = originX; pendingPanOriginY = originY;
  wrap.classList.add('is-panning');
  hideTip();
  svg.style.cursor = 'grabbing';
}});
window.addEventListener('mousemove', function(e) {{
  if (isPanning) {{
    var r = rect();
    pendingPanOriginX = panOriginX + (panStartX - e.clientX) / r.width * viewW;
    pendingPanOriginY = panOriginY + (panStartY - e.clientY) / r.height * viewH;
    schedulePanFrame();
    return;
  }}
  scheduleHover(e);
}}, {{signal:eventSignal}});
window.addEventListener('mouseup', function() {{
  finishPan();
  svg.style.cursor = 'grab';
}}, {{signal:eventSignal}});
wrap.addEventListener('mouseleave', function() {{
  pendingHoverEvent = null;
  if (hoverFrame !== null) {{ window.cancelAnimationFrame(hoverFrame); hoverFrame = null; }}
  hideTip();
  finishPan();
}});
wrap.addEventListener('keydown', function(e) {{
  if (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') return;
  e.preventDefault();
  hideTip();
  zoomAt(e.key === 'ArrowUp' ? 0.70 : 1.43, 0.5, 0.5);
}});
wrap.addEventListener('dblclick', function(e) {{
  e.preventDefault();
  focusChart();
  if (crosshairEnabled) {{
    crosshairEnabled = false; crosshairPoint = null; crosshair.style.display = 'none';
  }} else {{
    crosshairEnabled = true; crosshairPoint = svgPoint(e); crosshair.style.display = 'block'; updateCrosshair();
  }}
}});
document.getElementById('zoom-in-{chart_id}').addEventListener('click', function() {{ zoomAt(0.5, 0.5, 0.5); }});
document.getElementById('zoom-out-{chart_id}').addEventListener('click', function() {{ zoomAt(2, 0.5, 0.5); }});
document.getElementById('reset-{chart_id}').addEventListener('click', function() {{ hideTip(); resetView(); }});
document.getElementById('clear-{chart_id}').addEventListener('click', function() {{
  if (fractalRangeLayer) fractalRangeLayer.replaceChildren();
  if (fractalRefLayer) fractalRefLayer.replaceChildren();
  panelRoot.querySelectorAll('[data-fx-row].fx-ref-active').forEach(function(node) {{
    node.classList.remove('fx-ref-active');
  }});
  clearSegHighlight();
}});
klineToggle.addEventListener('click', function() {{
  var active = klineLayer.classList.toggle('active');
  klineToggle.classList.toggle('active', active);
  klineToggle.setAttribute('aria-pressed', active ? 'true' : 'false');
}});
maToggle.addEventListener('click', function() {{
  var active = maLayer.classList.toggle('active');
  maToggle.classList.toggle('active', active);
  maToggle.setAttribute('aria-pressed', active ? 'true' : 'false');
}});
eigenToggle.addEventListener('click', function() {{
  var active = eigenLayer.classList.toggle('active');
  eigenToggle.classList.toggle('active', active);
  eigenToggle.setAttribute('aria-pressed', active ? 'true' : 'false');
}});
panelRoot.querySelectorAll('[data-fx-row].chart-price-label,[data-fx-row].chart-fractal-marker').forEach(function(node) {{
  node.addEventListener('mousedown', function(e) {{
    e.stopPropagation();
  }});
  node.addEventListener('click', function(e) {{
    e.stopPropagation();
    handleFractalPick(node.getAttribute('data-fx-row'));
  }});
}});
panelRoot.querySelectorAll('.fx-note-ref[data-fx-ref]').forEach(function(btn) {{
  btn.addEventListener('click', function(e) {{
    e.preventDefault();
    e.stopPropagation();
    highlightFractalOnChart(btn.getAttribute('data-fx-ref'));
  }});
}});
panelRoot.querySelectorAll('.chart-pen-line[data-pen-row],.chart-pen-hit[data-pen-row]').forEach(function(line) {{
  line.addEventListener('mousedown', function(e) {{
    e.stopPropagation();
  }});
  line.addEventListener('click', function(e) {{
    e.stopPropagation();
    highlightPenRow(line.getAttribute('data-pen-row'));
  }});
}});
panelRoot.querySelectorAll('.chart-seg-line[data-seg-row],.chart-seg-hit[data-seg-row]').forEach(function(line) {{
  line.addEventListener('mousedown', function(e) {{
    e.stopPropagation();
  }});
  line.addEventListener('click', function(e) {{
    e.stopPropagation();
    var rowId = line.getAttribute('data-seg-row');
    var row = panelRoot.querySelector('tr[data-seg-row="' + rowId + '"]');
    highlightSegRow(rowId);
    if (row) focusRange(row.getAttribute('data-seg-begin'), row.getAttribute('data-seg-end'), 36);
  }});
}});
panelRoot.querySelectorAll('tr[data-target-idx]').forEach(function(row) {{
  row.addEventListener('click', function() {{
    if (row.hasAttribute('data-seg-row')) {{
      highlightSegRow(row.getAttribute('data-seg-row'));
      focusRange(row.getAttribute('data-seg-begin'), row.getAttribute('data-seg-end'), 36);
      return;
    }}
    panelRoot.querySelectorAll('tr.focused-row').forEach(function(x) {{ x.classList.remove('focused-row'); }});
    row.classList.add('focused-row');
    focusBar(row.getAttribute('data-target-idx'), false);
  }});
}});
panelRoot.querySelectorAll('tr[data-pen-row] .pen-direction-cell').forEach(function(cell) {{
  cell.addEventListener('click', function(e) {{
    e.stopPropagation();
    var row = cell.closest('tr[data-pen-row]');
    if (!row) return;
    panelRoot.querySelectorAll('tr.focused-row').forEach(function(x) {{ x.classList.remove('focused-row'); }});
    row.classList.add('focused-row');
    highlightPenRow(row.getAttribute('data-pen-row'));
    focusPen(row.getAttribute('data-pen-begin'), row.getAttribute('data-pen-end'));
  }});
}});
panelRoot.querySelectorAll('tr[data-seg-row] .seg-direction-cell').forEach(function(cell) {{
  cell.addEventListener('click', function(e) {{
    e.stopPropagation();
    var row = cell.closest('tr[data-seg-row]');
    if (!row) return;
    highlightSegRow(row.getAttribute('data-seg-row'));
    focusRange(row.getAttribute('data-seg-begin'), row.getAttribute('data-seg-end'), 36);
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
window.addEventListener('resize', updateZoomLabel, {{signal:eventSignal}});
resetView();
rememberView();
}})();
</script>
"""
