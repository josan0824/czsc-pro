import argparse
import hashlib
import html
import json
import re
import requests
import traceback
from datetime import datetime, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import AUTYPE, DATA_SRC, KL_TYPE
from Plot.HtmlPlotDriver import CHtmlPlotDriver


DEFAULT_CODE = "SH000001"
DEFAULT_SOURCE = "mootdx"
CODE_NAME_MAP = {
    "000001.SH": "上证指数",
    "SH000001": "上证指数",
    "000001.SZ": "平安银行",
    "000905.SH": "中证500",
    "SH000905": "中证500",
    "000852.SH": "中证1000",
    "SH000852": "中证1000",
    "000300.SH": "沪深300",
    "SH000300": "沪深300",
    "000016.SH": "上证50",
    "SH000016": "上证50",
    "688111.SH": "金山办公",
    "002475.SZ": "立讯精密",
}
QUICK_CODES = [
    "SH000001",
    "000001.SZ",
    "000905.SH",
    "SH000852",
    "SH000300",
    "SH000016",
    "688111.SH",
    "002475.SZ",
]
QUICK_ITEMS = [{"code": code, "name": resolve_name} for code, resolve_name in [
    ("SH000001", CODE_NAME_MAP["SH000001"]),
    ("000001.SZ", CODE_NAME_MAP["000001.SZ"]),
    ("000905.SH", CODE_NAME_MAP["000905.SH"]),
    ("SH000852", CODE_NAME_MAP["SH000852"]),
    ("SH000300", CODE_NAME_MAP["SH000300"]),
    ("SH000016", CODE_NAME_MAP["SH000016"]),
    ("688111.SH", CODE_NAME_MAP["688111.SH"]),
    ("002475.SZ", CODE_NAME_MAP["002475.SZ"]),
]]

LV_OPTIONS = {
    "1m": KL_TYPE.K_1M,
    "5m": KL_TYPE.K_5M,
    "15m": KL_TYPE.K_15M,
    "30m": KL_TYPE.K_30M,
    "60m": KL_TYPE.K_60M,
    "day": KL_TYPE.K_DAY,
}


def normalize_code(code: str) -> str:
    value = code.strip().upper()
    match = re.fullmatch(r"(SH|SZ|BJ)(\d{6})", value)
    if match:
        return f"{match.group(2)}.{match.group(1)}"
    if re.fullmatch(r"\d{6}", value):
        if value.startswith(("5", "6", "9")):
            return f"{value}.SH"
        if value.startswith(("0", "2", "3")):
            return f"{value}.SZ"
        if value.startswith(("4", "8")):
            return f"{value}.BJ"
    return value


def compact_code(code: str) -> str:
    value = normalize_code(code)
    match = re.fullmatch(r"(\d{6})\.(SH|SZ|BJ)", value)
    if match:
        return f"{match.group(2)}{match.group(1)}"
    return code.strip().upper()


def resolve_security_name(code: str) -> str:
    normalized = normalize_code(code)
    compact = compact_code(code)
    if normalized in CODE_NAME_MAP:
        return CODE_NAME_MAP[normalized]
    if compact in CODE_NAME_MAP:
        return CODE_NAME_MAP[compact]

    code_num = normalized[:6] if re.fullmatch(r"\d{6}\.(SH|SZ|BJ)", normalized) else compact[-6:]
    try:
        response = requests.get(
            "https://searchapi.eastmoney.com/api/suggest/get",
            params={
                "input": code_num,
                "type": "14",
                "token": "D43BF722C8E33BDC906FB84D85E326E8",
            },
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://quote.eastmoney.com/",
            },
            timeout=5,
        )
        response.raise_for_status()
        data = response.json()
        for item in data.get("QuotationCodeTable", {}).get("Data", []) or []:
            if str(item.get("Code", "")).upper() == code_num:
                name = item.get("Name") or item.get("PinYin")
                if name:
                    return str(name)
    except Exception:
        pass
    return normalized


def make_chart_title(code: str) -> str:
    normalized = normalize_code(code)
    name = resolve_security_name(normalized)
    return f"{name} {normalized}" if name != normalized else normalized


def parse_lv(value: str) -> KL_TYPE:
    return LV_OPTIONS.get(value.lower(), KL_TYPE.K_1M)


def parse_source(value: str):
    source = (value or DEFAULT_SOURCE).strip().lower()
    if source in ("mootdx", "tdx", "tongdaxin", "通达信"):
        return DATA_SRC.MOOTDX
    if source in ("eastmoney", "em", "东方财富"):
        return "custom:EastMoneyAPI.CEastMoney"
    raise ValueError(f"不支持的数据源: {value}")


SEG_ALGO_OPTIONS = {
    "chan": "chan",
    "chan_v2": "chan_v2",
    "chan_doubao": "chan_doubao",
    "doubao": "chan_doubao",
    "chan_doubao2": "chan_doubao2",
    "doubao2": "chan_doubao2",
    "chan_doubao3": "chan_doubao3",
    "doubao3": "chan_doubao3",
    "douban_v3": "chan_doubao3",
    "doubao_v3": "chan_doubao3",
    "1+1": "1+1",
    "break": "break",
}


def parse_seg_algo(value: str) -> str:
    seg_algo = (value or "chan").strip().lower()
    if seg_algo in SEG_ALGO_OPTIONS:
        return SEG_ALGO_OPTIONS[seg_algo]
    raise ValueError(f"不支持的线段算法: {value}")


def make_config(trigger_step: bool = False, seg_algo: str = "chan") -> CChanConfig:
    return CChanConfig({
        "bi_strict": True,
        "bi_fx_check": "totally",
        "gap_as_kl": True,
        "seg_algo": parse_seg_algo(seg_algo),
        "trigger_step": trigger_step,
        "skip_step": 0,
        "divergence_rate": float("inf"),
        "bsp2_follow_1": False,
        "bsp3_follow_1": False,
        "min_zs_cnt": 0,
        "bs1_peak": False,
        "macd_algo": "peak",
        "bs_type": "1,2,3a,1p,2s,3b",
        "print_warning": True,
        "zs_algo": "normal",
    })


def make_plot_config() -> dict:
    return {
        "plot_kline": True,
        "plot_kline_combine": True,
        "plot_bi": True,
        "plot_seg": True,
        "plot_eigen": True,
        "plot_zs": True,
        "plot_macd": False,
        "plot_mean": False,
        "plot_channel": False,
        "plot_bsp": True,
        "plot_extrainfo": False,
        "plot_demark": False,
        "plot_marker": False,
        "plot_rsi": False,
        "plot_kdj": False,
    }


def make_plot_para() -> dict:
    return {
        "seg": {},
        "bi": {},
        "figure": {"x_range": 0},
        "marker": {},
    }


def build_single_level_chan(code: str, lv: KL_TYPE, begin_time: str, data_src, seg_algo: str = "chan") -> CChan:
    return CChan(
        code=code,
        begin_time=begin_time,
        end_time=None,
        data_src=data_src,
        lv_list=[lv],
        config=make_config(seg_algo=seg_algo),
        autype=AUTYPE.QFQ,
    )


def build_level_nav(code: str, active_lv: KL_TYPE, days: int, source: str, seg_algo: str) -> list[dict[str, str]]:
    labels = {
        "1m": "1分钟",
        "5m": "5分钟",
        "15m": "15分钟",
        "30m": "30分钟",
        "60m": "60分钟",
        "day": "日线",
    }
    items = []
    for lv_key, label in labels.items():
        params = urlencode({
            "code": compact_code(code),
            "lv": lv_key,
            "days": str(days),
            "source": source,
            "seg_algo": seg_algo,
        })
        items.append({
            "label": label,
            "href": f"chart?{params}",
            "active": parse_lv(lv_key) == active_lv,
        })
    return items


def build_chart_html(code: str, lv_key: str, days: int, source: str = DEFAULT_SOURCE, seg_algo: str = "chan") -> str:
    normalized_code = normalize_code(code)
    lv = parse_lv(lv_key)
    data_src = parse_source(source)
    seg_algo = parse_seg_algo(seg_algo)
    days = max(5, min(days, 3650))
    begin_time = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    if data_src == DATA_SRC.MOOTDX:
        from DataAPI.MootdxAPI import CMootdx

        CMootdx.do_close()
    chan = build_single_level_chan(normalized_code, lv, begin_time, data_src, seg_algo=seg_algo)
    html_text = CHtmlPlotDriver(
        chan,
        plot_config=make_plot_config(),
        plot_para=make_plot_para(),
        active_lv=lv,
        level_nav=build_level_nav(normalized_code, lv, days, source, seg_algo),
    ).to_html()
    chart_title = make_chart_title(normalized_code)
    escaped_code = html.escape(str(chan.code))
    escaped_title = html.escape(chart_title)
    html_text = html_text.replace(f"<title>{escaped_code} 缠论分型图</title>", f"<title>{escaped_title} 缠论分型图</title>", 1)
    html_text = html_text.replace(f"<h1>{escaped_code} 缠论分型图</h1>", f"<h1>{escaped_title} 缠论分型图</h1>", 1)
    return html_text


def sign_chart_html(html_text: str) -> str:
    return hashlib.sha256(html_text.encode("utf-8")).hexdigest()


def attach_chart_signature(html_text: str, signature: str) -> str:
    marker = "</head>"
    meta = f'<meta name="chan-chart-signature" content="{html.escape(signature)}">\n'
    if marker in html_text:
        return html_text.replace(marker, meta + marker, 1)
    return html_text


def build_chart_payload(code: str, lv_key: str, days: int, source: str = DEFAULT_SOURCE, seg_algo: str = "chan") -> tuple[str, str]:
    html_text = build_chart_html(code, lv_key, days, source, seg_algo)
    signature = sign_chart_html(html_text)
    return attach_chart_signature(html_text, signature), signature


def error_html(message: str, detail: str = "") -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>生成失败</title>
<style>
body {{
  margin:0;
  background:#f6f7f9;
  color:#101828;
  font:14px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
}}
main {{ max-width:880px; margin:48px auto; padding:0 18px; }}
.panel {{ background:#fff; border:1px solid #d0d5dd; border-radius:6px; padding:18px; }}
h1 {{ margin:0 0 8px; font-size:20px; }}
pre {{ white-space:pre-wrap; word-break:break-word; background:#f8fafc; border:1px solid #eaecf0; padding:12px; }}
</style>
</head>
<body>
<main>
  <div class="panel">
    <h1>图表生成失败</h1>
    <p>{html.escape(message)}</p>
    {f"<pre>{html.escape(detail)}</pre>" if detail else ""}
  </div>
</main>
</body>
</html>"""


def index_html(host: str, port: int) -> str:
    quick_items = json.dumps(QUICK_ITEMS, ensure_ascii=False)
    default_query = urlencode({"code": DEFAULT_CODE, "lv": "1m", "days": "30", "source": DEFAULT_SOURCE, "seg_algo": "chan"})
    chart_url = f"chart?{default_query}"
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>缠论图表服务</title>
<style>
:root {{
  --ink:#101828;
  --muted:#667085;
  --line:#d0d5dd;
  --panel:#ffffff;
  --bg:#f5f7fa;
  --accent:#175cd3;
  --accent-soft:#eff8ff;
  --danger:#d92d20;
  --danger-soft:#fef3f2;
}}
* {{ box-sizing:border-box; }}
body {{
  margin:0;
  background:var(--bg);
  color:var(--ink);
  font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
}}
.app {{
  min-height:100vh;
  display:grid;
  grid-template-rows:auto 1fr;
}}
.topbar {{
  display:flex;
  align-items:center;
  gap:14px;
  padding:12px 14px;
  background:#fff;
  border-bottom:1px solid var(--line);
}}
.brand {{
  min-width:148px;
  font-weight:700;
  font-size:16px;
}}
.query {{
  display:flex;
  align-items:center;
  gap:8px;
  flex:1;
  min-width:0;
}}
input, select, button {{
  height:34px;
  border:1px solid var(--line);
  border-radius:4px;
  background:#fff;
  color:var(--ink);
  font:inherit;
}}
input {{
  width:150px;
  padding:0 10px;
  text-transform:uppercase;
}}
select {{ padding:0 8px; }}
button {{
  padding:0 12px;
  cursor:pointer;
}}
button.primary {{
  border-color:var(--accent);
  background:var(--accent);
  color:#fff;
}}
button.auto-refresh {{
  margin-left:38px;
  border-color:var(--danger);
  background:#fff;
  color:var(--danger);
  font-weight:700;
}}
button.auto-refresh.active {{
  background:var(--danger);
  color:#fff;
}}
button.quick.active {{
  border-color:var(--accent);
  background:var(--accent-soft);
  color:var(--accent);
}}
.quick-list {{
  display:flex;
  align-items:center;
  gap:6px;
  padding:8px 14px;
  background:#fff;
  border-bottom:1px solid var(--line);
}}
.quick-buttons {{
  display:flex;
  gap:6px;
  flex:1;
  min-width:0;
  flex-wrap:wrap;
}}
.quick-list button {{ height:30px; padding:0 10px; font-size:12px; }}
.logic-button {{
  flex:0 0 auto;
  border-color:#1570ef;
  background:var(--accent-soft);
  color:var(--accent);
  font-weight:700;
}}
.status {{
  margin-left:auto;
  color:var(--muted);
  font-size:12px;
  white-space:nowrap;
}}
.frame-wrap {{
  min-height:0;
  padding:10px;
}}
iframe {{
  width:100%;
  height:calc(100vh - 112px);
  min-height:560px;
  display:block;
  border:1px solid var(--line);
  border-radius:6px;
  background:#fff;
}}
.logic-modal {{
  position:fixed;
  inset:0;
  z-index:30;
  display:none;
  align-items:flex-start;
  justify-content:center;
  padding:7vh 18px 24px;
  background:rgba(16,24,40,.44);
}}
.logic-modal.active {{ display:flex; }}
.logic-dialog {{
  width:min(1080px,100%);
  max-height:86vh;
  display:grid;
  grid-template-rows:auto 1fr;
  overflow:hidden;
  border:1px solid #d0d5dd;
  border-radius:8px;
  background:#fff;
  box-shadow:0 24px 72px rgba(16,24,40,.24);
}}
.logic-dialog-head {{
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:12px;
  padding:14px 16px;
  border-bottom:1px solid #eaecf0;
}}
.logic-dialog-title {{
  margin:0;
  font-size:16px;
  line-height:1.3;
}}
.logic-close {{
  width:32px;
  min-width:32px;
  padding:0;
  font-size:20px;
  line-height:1;
}}
.logic-dialog-body {{
  overflow:auto;
  padding:18px 20px 22px;
}}
.logic-dialog-body h1 {{ margin:0 0 8px; font-size:21px; line-height:1.3; }}
.logic-dialog-body h2 {{ margin:0 0 10px; font-size:18px; line-height:1.35; }}
.logic-dialog-body h3 {{ margin:0 0 7px; font-size:14px; line-height:1.35; }}
.logic-dialog-body p,.logic-dialog-body li {{ color:#344054; }}
.logic-dialog-body code {{ background:#f2f4f7; padding:1px 4px; border-radius:3px; }}
.logic-guide {{ color:#101828; }}
.logic-intro {{
  max-width:900px;
  margin-bottom:14px;
}}
.logic-intro p {{
  margin:0;
  color:#475467;
}}
.logic-tabs {{
  position:sticky;
  top:-18px;
  z-index:2;
  display:flex;
  gap:6px;
  flex-wrap:wrap;
  margin:0 -20px 16px;
  padding:10px 20px;
  border-top:1px solid #f2f4f7;
  border-bottom:1px solid #eaecf0;
  background:rgba(255,255,255,.96);
}}
.logic-tab {{
  height:32px;
  border-color:#d0d5dd;
  background:#fff;
  color:#344054;
  font-size:13px;
  font-weight:700;
}}
.logic-tab.active {{
  border-color:#175cd3;
  background:#eff8ff;
  color:#175cd3;
}}
.logic-tab-panel {{ display:none; }}
.logic-tab-panel.active {{ display:block; }}
.logic-grid {{
  display:grid;
  grid-template-columns:repeat(2,minmax(0,1fr));
  gap:10px;
  margin:12px 0;
}}
.logic-card {{
  border:1px solid #e4e7ec;
  border-radius:6px;
  padding:12px;
  background:#fcfcfd;
}}
.logic-card p {{ margin:0 0 8px; }}
.logic-card p:last-child {{ margin-bottom:0; }}
.logic-rule-table {{
  display:grid;
  gap:8px;
  margin:12px 0;
}}
.logic-rule-table > div {{
  display:grid;
  grid-template-columns:110px 1fr;
  gap:12px;
  padding:10px 12px;
  border:1px solid #e4e7ec;
  border-radius:6px;
  background:#f9fafb;
}}
.logic-rule-table strong {{
  color:#101828;
}}
.logic-rule-table span {{
  color:#344054;
}}
.logic-example {{
  margin:12px 0;
  padding:11px 12px;
  border-left:3px solid #175cd3;
  border-radius:4px;
  background:#eff8ff;
  color:#344054;
}}
.logic-dialog-body pre {{
  margin:8px 0 0;
  padding:10px;
  overflow:auto;
  border:1px solid #e4e7ec;
  border-radius:6px;
  background:#101828;
  color:#e4e7ec;
  font-size:12px;
}}
.logic-dialog-body pre code {{
  padding:0;
  background:transparent;
  color:inherit;
}}
@media (max-width:800px) {{
  .topbar {{
    align-items:stretch;
    flex-direction:column;
  }}
  .query {{ flex-wrap:wrap; }}
  button.auto-refresh {{ margin-left:0; }}
  .status {{ margin-left:0; }}
  .quick-list {{ align-items:flex-start; }}
  .logic-button {{ margin-left:auto; }}
  iframe {{ height:calc(100vh - 190px); }}
  .logic-grid {{ grid-template-columns:1fr; }}
  .logic-rule-table > div {{ grid-template-columns:1fr; gap:4px; }}
}}
</style>
</head>
<body>
<div class="app">
  <header>
    <div class="topbar">
      <div class="brand">缠论图表服务</div>
      <form class="query" id="query-form">
        <input id="code-input" name="code" value="{DEFAULT_CODE}" autocomplete="off" spellcheck="false">
        <select id="lv-select" name="lv">
          <option value="1m" selected>1分钟</option>
          <option value="5m">5分钟</option>
          <option value="15m">15分钟</option>
          <option value="30m">30分钟</option>
          <option value="60m">60分钟</option>
          <option value="day">日线</option>
        </select>
        <select id="days-select" name="days">
          <option value="5">5天</option>
          <option value="20">20天</option>
          <option value="30" selected>30天</option>
          <option value="60">60天</option>
          <option value="120">120天</option>
          <option value="250">250天</option>
        </select>
        <select id="source-select" name="source">
          <option value="mootdx" selected>通达信</option>
          <option value="eastmoney">东方财富</option>
        </select>
        <select id="seg-algo-select" name="seg_algo" title="切换线段划分算法">
          <option value="chan" selected>线段 chan</option>
          <option value="chan_v2">线段 v2.0</option>
          <option value="chan_doubao">线段 doubao</option>
          <option value="chan_doubao2">线段 doubao2</option>
          <option value="chan_doubao3">线段 doubao3</option>
          <option value="1+1">线段 1+1</option>
          <option value="break">线段 break</option>
        </select>
        <button class="primary" type="submit">查询</button>
        <button class="auto-refresh" id="auto-refresh-btn" type="button" aria-pressed="false" title="开市时间每10秒重新请求当前图表">自动刷新</button>
        <span class="status" id="status">入口：http://{html.escape(host)}:{port}/</span>
      </form>
    </div>
    <nav class="quick-list">
      <div class="quick-buttons" id="quick-list"></div>
      <button class="logic-button" id="logic-open" type="button">划分逻辑</button>
    </nav>
  </header>
  <main class="frame-wrap">
    <iframe id="chart-frame" title="缠论图表" src="{chart_url}"></iframe>
  </main>
</div>
<div class="logic-modal" id="logic-modal" aria-hidden="true">
  <section class="logic-dialog" role="dialog" aria-modal="true" aria-labelledby="logic-title">
    <div class="logic-dialog-head">
      <h2 class="logic-dialog-title" id="logic-title">划分逻辑</h2>
      <button class="logic-close" id="logic-close" type="button" aria-label="关闭">×</button>
    </div>
    <div class="logic-dialog-body" id="logic-body">
      <p>图表加载完成后可查看当前代码生成的划分逻辑。</p>
    </div>
  </section>
</div>
<script>
var quickItems = {quick_items};
var form = document.getElementById('query-form');
var codeInput = document.getElementById('code-input');
var lvSelect = document.getElementById('lv-select');
var daysSelect = document.getElementById('days-select');
var sourceSelect = document.getElementById('source-select');
var segAlgoSelect = document.getElementById('seg-algo-select');
var frame = document.getElementById('chart-frame');
var quickList = document.getElementById('quick-list');
var statusEl = document.getElementById('status');
var autoRefreshBtn = document.getElementById('auto-refresh-btn');
var logicOpenBtn = document.getElementById('logic-open');
var logicModal = document.getElementById('logic-modal');
var logicCloseBtn = document.getElementById('logic-close');
var logicBody = document.getElementById('logic-body');
var autoRefreshEnabled = false;
var autoRefreshTimer = null;
var chartLoading = false;
var chartUpdating = false;
var lastChartSignature = null;
var chartPatchAckTimer = null;
var lastDataFetchText = '';

function buildUrl(code, cacheBust) {{
  var params = new URLSearchParams();
  params.set('code', String(code || '').trim().toUpperCase());
  params.set('lv', lvSelect.value);
  params.set('days', daysSelect.value);
  params.set('source', sourceSelect.value);
  params.set('seg_algo', segAlgoSelect.value);
  if (cacheBust) params.set('_ts', Date.now());
  return 'chart?' + params.toString();
}}
function buildFragmentUrl(cacheBust) {{
  var params = new URLSearchParams();
  params.set('code', String(codeInput.value || '').trim().toUpperCase());
  params.set('lv', lvSelect.value);
  params.set('days', daysSelect.value);
  params.set('source', sourceSelect.value);
  params.set('seg_algo', segAlgoSelect.value);
  if (lastChartSignature) params.set('known_sig', lastChartSignature);
  if (cacheBust) params.set('_ts', Date.now());
  return 'chart-fragment?' + params.toString();
}}
function currentChartUrl(cacheBust) {{
  var url;
  try {{
    url = new URL(frame.contentWindow.location.href);
  }} catch (err) {{
    url = new URL(frame.src, window.location.href);
  }}
  if (!url.pathname.endsWith('/chart') && url.pathname !== '/chart') {{
    return buildUrl(codeInput.value, cacheBust);
  }}
  if (cacheBust) url.searchParams.set('_ts', Date.now());
  return 'chart?' + url.searchParams.toString();
}}
function setActive(code) {{
  var normalized = normalizeCode(code);
  quickList.querySelectorAll('button').forEach(function(btn) {{
    btn.classList.toggle('active', normalizeCode(btn.dataset.code) === normalized);
  }});
}}
function normalizeCode(code) {{
  var value = String(code || '').trim().toUpperCase();
  var prefixed = value.match(/^(SH|SZ|BJ)(\\d{{6}})$/);
  if (prefixed) return prefixed[2] + '.' + prefixed[1];
  if (/^\\d{{6}}$/.test(value)) {{
    if (/^[569]/.test(value)) return value + '.SH';
    if (/^[023]/.test(value)) return value + '.SZ';
    if (/^[48]/.test(value)) return value + '.BJ';
  }}
  return value;
}}
function loadChart(code) {{
  var value = String(code || codeInput.value || '').trim().toUpperCase();
  if (!value) return;
  codeInput.value = value;
  setActive(value);
  statusEl.textContent = '正在加载 ' + value + ' ...';
  chartLoading = true;
  frame.src = buildUrl(value, true);
}}
function formatFetchTime(value) {{
  var date = value ? new Date(value) : new Date();
  if (Number.isNaN(date.getTime())) date = new Date();
  var pad = function(num) {{ return String(num).padStart(2, '0'); }};
  return date.getFullYear() + '-' + pad(date.getMonth() + 1) + '-' + pad(date.getDate()) +
    ' ' + pad(date.getHours()) + ':' + pad(date.getMinutes()) + ':' + pad(date.getSeconds());
}}
function updateFetchTime(value) {{
  lastDataFetchText = formatFetchTime(value);
}}
function chartStatus(prefix) {{
  var text = prefix + ' ' + codeInput.value + ' · ' + lvSelect.options[lvSelect.selectedIndex].text +
    ' · ' + segAlgoSelect.options[segAlgoSelect.selectedIndex].text;
  if (lastDataFetchText) text += ' · 最新获取：' + lastDataFetchText;
  return text;
}}
function readFrameSignature() {{
  try {{
    var meta = frame.contentDocument && frame.contentDocument.querySelector('meta[name="chan-chart-signature"]');
    return meta ? meta.getAttribute('content') : null;
  }} catch (err) {{
    return null;
  }}
}}
function canPatchFrame() {{
  try {{
    return Boolean(frame.contentWindow && frame.contentDocument && frame.contentDocument.getElementById('report-page'));
  }} catch (err) {{
    return false;
  }}
}}
function patchChartFrame(htmlText, signature) {{
  if (!canPatchFrame()) return false;
  if (chartPatchAckTimer) {{
    clearTimeout(chartPatchAckTimer);
    chartPatchAckTimer = null;
  }}
  frame.contentWindow.postMessage({{
    type: 'chan-chart-update',
    html: htmlText,
    signature: signature,
    generatedAt: lastDataFetchText
  }}, window.location.origin);
  chartPatchAckTimer = setTimeout(function() {{
    chartPatchAckTimer = null;
    chartUpdating = false;
    statusEl.textContent = '局部更新超时，请手动查询';
  }}, 5000);
  return true;
}}
function refreshChartIncremental() {{
  if (chartLoading || chartUpdating) return;
  chartUpdating = true;
  statusEl.textContent = '增量检查中 ' + codeInput.value + ' ...';
  fetch(buildFragmentUrl(true), {{cache: 'no-store'}})
    .then(function(resp) {{
      if (!resp.ok) throw new Error('HTTP ' + resp.status);
      return resp.json();
    }})
    .then(function(data) {{
      if (!data.changed) {{
        lastChartSignature = data.signature || lastChartSignature;
        updateFetchTime(data.generatedAt);
        chartUpdating = false;
        statusEl.textContent = chartStatus('暂无新增数据');
        return;
      }}
      if (!patchChartFrame(data.html, data.signature)) {{
        chartLoading = true;
        frame.src = currentChartUrl(true);
        chartUpdating = false;
        return;
      }}
      lastChartSignature = data.signature || lastChartSignature;
      updateFetchTime(data.generatedAt);
    }})
    .catch(function(err) {{
      chartUpdating = false;
      statusEl.textContent = '增量刷新失败：' + err.message;
    }});
}}
function getShanghaiTimeParts() {{
  var parts = new Intl.DateTimeFormat('en-GB', {{
    timeZone: 'Asia/Shanghai',
    weekday: 'short',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false
  }}).formatToParts(new Date());
  var result = {{}};
  parts.forEach(function(part) {{ result[part.type] = part.value; }});
  return result;
}}
function isMarketOpen() {{
  var parts = getShanghaiTimeParts();
  if (parts.weekday === 'Sat' || parts.weekday === 'Sun') return false;
  var minutes = Number(parts.hour) * 60 + Number(parts.minute);
  var morning = minutes >= 9 * 60 + 30 && minutes <= 11 * 60 + 30;
  var afternoon = minutes >= 13 * 60 && minutes <= 15 * 60;
  return morning || afternoon;
}}
function autoRefreshTick() {{
  if (!autoRefreshEnabled) return;
  if (!isMarketOpen()) {{
    statusEl.textContent = '自动刷新已开启 · 非开市时间';
    return;
  }}
  if (chartLoading || chartUpdating) return;
  statusEl.textContent = '自动刷新中 ' + codeInput.value + ' ...';
  refreshChartIncremental();
}}
function setAutoRefresh(enabled) {{
  autoRefreshEnabled = enabled;
  autoRefreshBtn.classList.toggle('active', enabled);
  autoRefreshBtn.setAttribute('aria-pressed', enabled ? 'true' : 'false');
  autoRefreshBtn.textContent = enabled ? '停止刷新' : '自动刷新';
  if (autoRefreshTimer) {{
    clearInterval(autoRefreshTimer);
    autoRefreshTimer = null;
  }}
  if (enabled) {{
    statusEl.textContent = isMarketOpen() ? '自动刷新已开启 · 每10秒增量刷新' : '自动刷新已开启 · 非开市时间';
    autoRefreshTimer = setInterval(autoRefreshTick, 10000);
  }} else {{
    statusEl.textContent = '自动刷新已关闭';
  }}
}}
function syncControlsFromFrame() {{
  try {{
    var url = new URL(frame.contentWindow.location.href);
    var code = url.searchParams.get('code');
    var lv = url.searchParams.get('lv');
    var days = url.searchParams.get('days');
    var source = url.searchParams.get('source');
    var segAlgo = url.searchParams.get('seg_algo');
    if (code) {{
      codeInput.value = code.toUpperCase();
      setActive(code);
    }}
    if (lv && Array.prototype.some.call(lvSelect.options, function(option) {{ return option.value === lv; }})) {{
      lvSelect.value = lv;
    }}
    if (days && Array.prototype.some.call(daysSelect.options, function(option) {{ return option.value === days; }})) {{
      daysSelect.value = days;
    }}
    if (source && Array.prototype.some.call(sourceSelect.options, function(option) {{ return option.value === source; }})) {{
      sourceSelect.value = source;
    }}
    if (segAlgo && Array.prototype.some.call(segAlgoSelect.options, function(option) {{ return option.value === segAlgo; }})) {{
      segAlgoSelect.value = segAlgo;
    }}
  }} catch (err) {{}}
}}
function getLogicHtmlFromFrame() {{
  try {{
    var source = frame.contentDocument && frame.contentDocument.getElementById('logic-content');
    if (source && source.innerHTML.trim()) return source.innerHTML;
  }} catch (err) {{}}
  return '<h1>当前分型与笔划分逻辑</h1><p>当前图表还没有完成加载，请稍后再打开。</p>';
}}
function initLogicTabs() {{
  var tabs = logicBody.querySelectorAll('.logic-tab[data-logic-tab]');
  var panels = logicBody.querySelectorAll('.logic-tab-panel[data-logic-panel]');
  if (!tabs.length || !panels.length) return;
  function activate(name) {{
    tabs.forEach(function(tab) {{
      tab.classList.toggle('active', tab.getAttribute('data-logic-tab') === name);
    }});
    panels.forEach(function(panel) {{
      panel.classList.toggle('active', panel.getAttribute('data-logic-panel') === name);
    }});
  }}
  tabs.forEach(function(tab) {{
    tab.addEventListener('click', function() {{
      activate(tab.getAttribute('data-logic-tab'));
    }});
  }});
  var active = logicBody.querySelector('.logic-tab.active[data-logic-tab]');
  activate(active ? active.getAttribute('data-logic-tab') : tabs[0].getAttribute('data-logic-tab'));
}}
function openLogicModal() {{
  logicBody.innerHTML = getLogicHtmlFromFrame();
  initLogicTabs();
  logicModal.classList.add('active');
  logicModal.setAttribute('aria-hidden', 'false');
  logicCloseBtn.focus();
}}
function closeLogicModal() {{
  logicModal.classList.remove('active');
  logicModal.setAttribute('aria-hidden', 'true');
  logicOpenBtn.focus();
}}
quickItems.forEach(function(item) {{
  var btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'quick';
  btn.dataset.code = item.code;
  btn.title = item.code;
  btn.textContent = item.name;
  btn.addEventListener('click', function() {{ loadChart(item.code); }});
  quickList.appendChild(btn);
}});
form.addEventListener('submit', function(e) {{
  e.preventDefault();
  loadChart(codeInput.value);
}});
segAlgoSelect.addEventListener('change', function() {{
  loadChart(codeInput.value);
}});
frame.addEventListener('load', function() {{
  chartLoading = false;
  chartUpdating = false;
  if (chartPatchAckTimer) {{
    clearTimeout(chartPatchAckTimer);
    chartPatchAckTimer = null;
  }}
  lastChartSignature = readFrameSignature() || lastChartSignature;
  updateFetchTime();
  syncControlsFromFrame();
  statusEl.textContent = chartStatus('已加载');
}});
window.addEventListener('message', function(event) {{
  var data = event.data || {{}};
  if (data.type === 'chan-chart-updated') {{
    chartLoading = false;
    chartUpdating = false;
    if (chartPatchAckTimer) {{
      clearTimeout(chartPatchAckTimer);
      chartPatchAckTimer = null;
    }}
    lastChartSignature = data.signature || lastChartSignature;
    statusEl.textContent = chartStatus('已增量更新');
  }}
}});
autoRefreshBtn.addEventListener('click', function() {{
  setAutoRefresh(!autoRefreshEnabled);
}});
logicOpenBtn.addEventListener('click', openLogicModal);
logicCloseBtn.addEventListener('click', closeLogicModal);
logicModal.addEventListener('click', function(e) {{
  if (e.target === logicModal) closeLogicModal();
}});
window.addEventListener('keydown', function(e) {{
  if (e.key === 'Escape' && logicModal.classList.contains('active')) closeLogicModal();
}});
setActive('{DEFAULT_CODE}');
</script>
</body>
</html>"""


class ChanChartHandler(BaseHTTPRequestHandler):
    server_version = "ChanChartHTTP/1.0"

    @staticmethod
    def normalize_path(path: str) -> str:
        if path == "/chan-chart":
            return "/"
        if path.startswith("/chan-chart/"):
            stripped = path[len("/chan-chart"):]
            return stripped or "/"
        return path

    def do_GET(self):
        parsed = urlparse(self.path)
        path = self.normalize_path(parsed.path)
        if path in ("", "/"):
            self.respond_html(index_html(self.server.server_address[0] or "127.0.0.1", self.server.server_address[1]))
            return
        if path == "/chart":
            self.handle_chart(parsed.query)
            return
        if path == "/chart-fragment":
            self.handle_chart_fragment(parsed.query)
            return
        if path == "/healthz":
            self.respond_json({"ok": True})
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

    def handle_chart(self, query: str):
        params = parse_qs(query)
        code = (params.get("code") or [DEFAULT_CODE])[0]
        lv = (params.get("lv") or ["1m"])[0]
        source = (params.get("source") or [DEFAULT_SOURCE])[0]
        seg_algo = (params.get("seg_algo") or ["chan"])[0]
        try:
            days = int((params.get("days") or ["30"])[0])
        except ValueError:
            days = 30
        try:
            html_text, _signature = build_chart_payload(code, lv, days, source, seg_algo)
            self.respond_html(html_text)
        except Exception as err:
            detail = traceback.format_exc()
            self.respond_html(error_html(str(err), detail), status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def handle_chart_fragment(self, query: str):
        params = parse_qs(query)
        code = (params.get("code") or [DEFAULT_CODE])[0]
        lv = (params.get("lv") or ["1m"])[0]
        source = (params.get("source") or [DEFAULT_SOURCE])[0]
        seg_algo = (params.get("seg_algo") or ["chan"])[0]
        known_sig = (params.get("known_sig") or [""])[0]
        try:
            days = int((params.get("days") or ["30"])[0])
        except ValueError:
            days = 30
        try:
            html_text, signature = build_chart_payload(code, lv, days, source, seg_algo)
            body = {
                "changed": signature != known_sig,
                "signature": signature,
                "generatedAt": datetime.now().isoformat(timespec="seconds"),
            }
            if body["changed"]:
                body["html"] = html_text
            self.respond_json(body)
        except Exception as err:
            detail = traceback.format_exc()
            self.respond_json(
                {"changed": False, "error": str(err), "detail": detail},
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def respond_html(self, body: str, status: HTTPStatus = HTTPStatus.OK):
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def respond_json(self, body: dict, status: HTTPStatus = HTTPStatus.OK):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        print(f"[{self.log_date_time_string()}] {self.address_string()} {fmt % args}")


def main():
    parser = argparse.ArgumentParser(description="Run the Chan interactive chart web service.")
    parser.add_argument("--host", default="127.0.0.1", help="bind host, use 0.0.0.0 for external access")
    parser.add_argument("--port", type=int, default=8000, help="bind port")
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), ChanChartHandler)
    print(f"Chan chart server: http://{args.host}:{args.port}/")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
