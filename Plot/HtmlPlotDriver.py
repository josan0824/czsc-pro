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
.chan-chart-svg text {{
  paint-order:stroke; stroke:#111827; stroke-width:3px; stroke-linejoin:round;
}}
.chan-chart-svg line,.chan-chart-svg rect,.chan-chart-svg polygon {{
  vector-effect:non-scaling-stroke;
}}
.ma-layer {{ display:none; }}
.ma-layer.active {{ display:inline; }}
.fractal-detail-layer {{ display:none; }}
.fractal-detail-layer.active {{ display:inline; }}
.chart-price-label {{ cursor:pointer; opacity:.82; pointer-events:all; }}
.crosshair-price-text {{ stroke-width:1px; }}
.chart-bsp-label {{ vector-effect:non-scaling-stroke; }}
.chart-pen-line {{ cursor:pointer; }}
.fractal-range-box {{ pointer-events:none; }}
.fractal-ref-box {{ pointer-events:none; }}
.chart-fractal-marker.fx-ref-active {{ filter:drop-shadow(0 0 4px rgba(245,158,11,.95)); }}
.chart-price-label.fx-ref-active {{ fill:#fef08a; font-weight:700; }}
.chart-fractal-marker:hover {{ filter:drop-shadow(0 0 3px rgba(247,144,9,.85)); }}
.tooltip {{
  position:absolute; z-index:5; display:none; min-width:190px; padding:8px 10px;
  border:1px solid #344054; border-radius:4px; background:rgba(15,23,42,.96);
  box-shadow:0 10px 28px rgba(0,0,0,.28); color:#e5e7eb; font-size:12px;
  pointer-events:none;
}}
.legend {{ display:flex; gap:14px; flex-wrap:wrap; color:#98a2b3; font-size:12px; margin-top:8px; }}
.swatch {{ display:inline-block; width:10px; height:10px; margin-right:5px; vertical-align:-1px; }}
.logic-source {{ display:none; }}
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
        <p>如果连续出现同类分型，系统会保留极值更强的那个：顶分型优先保留高点更高者，底分型优先保留低点更低者。</p>
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
        <p>当前 <code>bi_fx_check=totally</code>，使用最严格的完全分离检查。它要求两个端点分型的三根合并 K 区间完全错开。</p>
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
      <div><strong>gap_as_kl=True</strong><span>当端点跨度不足时，只检查候选区间内是否存在有效破格缺口。向上笔要求向上跳空的缺口上沿严格高于前一笔起点顶；向下笔要求向下跳空的缺口下沿严格低于前一笔起点底。</span></div>
    </div>
    <div class="logic-example">
      <strong>笔的例子：</strong>严格模式下成笔要求跨度至少为 4。若两个端点合并 K 索引差不足，当前 <code>gap_as_kl=True</code> 时不会把每个缺口都补成一根 K；只有第一个满足反向突破前一笔起点极值的缺口，才允许候选笔跳过跨度和 <code>bi_fx_check</code> 区间重叠限制。
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
      <div><strong>边界规则</strong><span>等于前一笔起点极值不算突破；连续多个缺口不累计、不拆成多笔；缺口是否回补不影响已经命中的候选成笔检查。</span></div>
    </div>
  </section>
  <section class="logic-tab-panel" data-logic-panel="report">
    <h2>6. 表格与图上标注口径</h2>
    <p>报告里的图形和表格是为了复核计算过程，不是额外再跑一套规则。图上的三角形、虚线框、笔线和表格行都来自同一份分型与笔数据。</p>
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
            if not bi.is_sure:
                notes.append("最后一笔为虚笔或尚未完全确认，后续新K线可能改写终点")
            endpoint_map.setdefault(int(bi.begin_klc_idx), []).append(f"第{i + 1}笔起点")
            endpoint_map.setdefault(int(bi.end_klc_idx), []).append(f"第{i + 1}笔终点")
            pen_rows.append({
                "idx": i + 1,
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
        return fx_rows, pen_rows

    def _make_detail_tables(self, meta: CChanPlotMeta, chart_id: str, label: str) -> tuple[str, str]:
        fx_rows, pen_rows = self._build_report_rows(meta)
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
        return fx_section, pen_section

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
            svg.append(
                f'<line x1="{seg["x1"]:.1f}" y1="{seg["y1"]:.1f}" x2="{seg["x2"]:.1f}" y2="{seg["y2"]:.1f}" '
                f'stroke="#69a35f" stroke-width="2.4" opacity=".72" stroke-linecap="round"{dash}/>'
            )

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
        fx_table, pen_table = self._make_detail_tables(meta, chart_id, label)

        return f"""
{fx_table}
<div class="chart-shell">
  <div class="chart-toolbar">
    <strong>{html.escape(label)}</strong>
    <button id="zoom-in-{chart_id}" title="放大" type="button">+</button>
    <span id="zoom-label-{chart_id}" class="zoom-label">-</span>
    <button id="zoom-out-{chart_id}" title="缩小" type="button">-</button>
    <button id="reset-{chart_id}" title="重置视图" type="button">重置</button>
    <button id="clear-{chart_id}" title="清理分型标记" type="button">清理</button>
    <button id="ma-toggle-{chart_id}" class="ma-toggle" title="显示/隐藏均线" type="button" aria-pressed="false">均线</button>
    <span class="chart-help">滚轮缩放 · 拖拽平移 · 双击十字星 · 悬停查看 OHLC</span>
  </div>
  <div id="wrap-{chart_id}" class="chart-wrap">
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
    <span><i class="swatch" style="background:#ef4444"></i>买点</span>
    <span><i class="swatch" style="background:#22c55e"></i>卖点</span>
  </div>
</div>
{pen_table}
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
var maLayer = document.getElementById('ma-layer-{chart_id}');
var maToggle = document.getElementById('ma-toggle-{chart_id}');
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
function updateViewBox() {{
  viewW = Math.max(minViewW, Math.min(maxViewW, viewW));
  originX = Math.max(0, Math.min(Math.max(0, totalWidth - viewW), originX));
  autoFitY();
  svg.setAttribute('viewBox', originX.toFixed(1) + ' ' + originY.toFixed(1) + ' ' + viewW.toFixed(1) + ' ' + viewH.toFixed(1));
  updateZoomLabel();
  updateCrosshair();
}}
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
}}, {{signal:eventSignal}});
window.addEventListener('mouseup', function() {{
  isPanning = false; svg.style.cursor = 'grab';
}}, {{signal:eventSignal}});
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
document.getElementById('clear-{chart_id}').addEventListener('click', function() {{
  if (fractalRangeLayer) fractalRangeLayer.replaceChildren();
  if (fractalRefLayer) fractalRefLayer.replaceChildren();
  panelRoot.querySelectorAll('[data-fx-row].fx-ref-active').forEach(function(node) {{
    node.classList.remove('fx-ref-active');
  }});
}});
maToggle.addEventListener('click', function() {{
  var active = maLayer.classList.toggle('active');
  maToggle.classList.toggle('active', active);
  maToggle.setAttribute('aria-pressed', active ? 'true' : 'false');
}});
panelRoot.querySelectorAll('[data-fx-row].chart-price-label,[data-fx-row].chart-fractal-marker').forEach(function(node) {{
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
  line.addEventListener('click', function(e) {{
    e.stopPropagation();
    highlightPenRow(line.getAttribute('data-pen-row'));
  }});
}});
panelRoot.querySelectorAll('tr[data-target-idx]').forEach(function(row) {{
  row.addEventListener('click', function() {{
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
}})();
</script>
"""
