# 通达信本地缓存数据源 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `web_server.py` 的「通达信历史数据」数据源在无通达信安装、无历史数据时也能工作：自动创建默认 `vipdoc` 目录，本地优先读、本地不足时联网（mootdx）拉缺口并写回本地 `.day/.lc1/.lc5`。

**Architecture:** 新增自包含二进制 IO 模块 `DataAPI/tdx_vipdoc_io.py`（用 `struct` 直编/直解 tdxpy 格式，不依赖 `mootdx.reader.Reader`），新增混合数据源 `DataAPI/TdxCacheAPI.py::CTdxCache`（读本地→不够则用 `CMootdx` 联网→合并→写回→派生级别重采样），`web_server.py` 设默认 `TDX_HISTORY_DIR` 并把 `tdx_history` 源指向 `CTdxCache`。`CMootdx`/`CTdxHistory` 不改动。

**Tech Stack:** Python 3.11（`/opt/homebrew/bin/python3.11`），pandas，mootdx（联网），stdlib `struct`/`fcntl`（二进制与文件锁），unittest+unittest.mock（测试）。

## Global Constraints

- 解释器固定 `/opt/homebrew/bin/python3.11`（`MootdxAPI.py:397` 的错误提示以此为基准）；所有 `pytest`/`python -m unittest` 命令用它。
- 二进制格式逐字核对自 `/opt/homebrew/lib/python3.11/site-packages/tdxpy/reader/daily_bar_reader.py` 与 `lc_min_bar_reader.py`：日线 `<IIIIIfII` 32B/条；分钟 `<HHfffffII` 32B/条；日期 u16 = `(年-2004)*2048+月*100+日`；时间 u16 = `时*60+分`；日线系数表逐字取自 tdxpy `SECURITY_COEFFICIENT`。
- 规范 DataFrame 列顺序固定为 `["datetime","open","high","low","close","amount","volume"]`（与 `MootdxAPI.__normalize_df`、`TdxHistoryAPI.__normalize_df` 一致）。
- `CMootdx`、`CTdxHistory` 现有源文件不改（测试用例 `tests/test_tdx_history_api.py` 中指向 `parse_source` 断言的那一处除外，因 web 源映射会变）。
- 市场仅 SH/SZ；级别仅 day/1m/5m/15m/30m/60m。周/月、BJ 不在范围。
- 写回为「尽力而为」：写盘失败只告警，不阻断出图。

## File Structure

| 文件 | 职责 | 动作 |
|---|---|---|
| `DataAPI/tdx_vipdoc_io.py` | 纯 IO：证券类型分类、日线系数、二进制编/解、原子读写（带文件锁）、分钟重采样 | 新建 |
| `DataAPI/TdxCacheAPI.py` | 混合数据源 `CTdxCache`：本地优先→联网兜底→写回→派生重采样 | 新建 |
| `web_server.py` | 默认 `TDX_HISTORY_DIR`、`parse_source` 指向 `CTdxCache` | 改 |
| `.gitignore` | 忽略 `data/tdx/` | 改 |
| `tests/test_tdx_vipdoc_io.py` | 二进制回环、分类、重采样、并发写 | 新建 |
| `tests/test_tdx_cache_api.py` | 本地优先、增量、覆盖即跳过、派生、错误兜底 | 新建 |
| `tests/test_tdx_history_api.py` | 更新 `parse_source("tdx_history")` 断言 | 改 |

接口契约（跨任务共享，命名固定）：

```python
# tdx_vipdoc_io.py 公开签名（后续任务以此为准）
def classify_security_type(symbol: str, market: str) -> str: ...           # -> "SH_INDEX" / "SH_A_STOCK" / "SZ_INDEX" / "SZ_A_STOCK"
def security_coefficient(security_type: str) -> list[float]: ...          # -> [price_coeff, vol_coeff]
def encode_day(df: pd.DataFrame, security_type: str) -> bytes: ...
def decode_day(content: bytes, security_type: str) -> pd.DataFrame: ...   # 列规范、按系数还原
def encode_minute(df: pd.DataFrame) -> bytes: ...                        # lc1 与 lc5 共用
def decode_minute(content: bytes) -> pd.DataFrame: ...
def read_day(path: Path, security_type: str) -> pd.DataFrame: ...       # 文件缺失返回空 df
def read_minute(path: Path) -> pd.DataFrame: ...
def write_day(path: Path, df: pd.DataFrame, security_type: str) -> None: ...    # 锁+合并+原子写
def write_minute(path: Path, df: pd.DataFrame) -> None: ...
def resample_minutes(df: pd.DataFrame, target_interval: int) -> pd.DataFrame: ...
def normalize_reader_df(df: pd.DataFrame | None) -> pd.DataFrame: ...    # 规范列、清洗（供 CTdxCache 内联用）

# TdxCacheAPI.CTdxCache 公开（被 custom: 机制实例化）
class CTdxCache(CCommonStockApi):
    def __init__(self, code, k_type=KL_TYPE.K_1M, begin_date=None, end_date=None, autype=AUTYPE.NONE): ...
    def get_kl_data(self) -> Iterable[CKLine_Unit]: ...
    def SetBasciInfo(self): ...
    @classmethod
    def do_init(cls): ...
    @classmethod
    def do_close(cls): ...
```

---

### Task 1: 日线二进制编/解 + 证券类型分类

**Files:**
- Create: `DataAPI/tdx_vipdoc_io.py`
- Test: `tests/test_tdx_vipdoc_io.py`

**Interfaces:**
- Produces: `classify_security_type`, `security_coefficient`, `encode_day`, `decode_day`, `read_day`, `write_day`, `normalize_reader_df`（本任务给最小版，后续任务扩展）。

- [ ] **Step 1: Write the failing test**

`tests/test_tdx_vipdoc_io.py`:
```python
import math
import struct
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from DataAPI import tdx_vipdoc_io as io


def _day_df(rows):
    return pd.DataFrame(
        rows,
        columns=["datetime", "open", "high", "low", "close", "amount", "volume"],
    )


class DayIoTest(unittest.TestCase):
    def test_classify_index_vs_a_stock(self):
        self.assertEqual("SH_INDEX", io.classify_security_type("000001", "SH"))
        self.assertEqual("SH_A_STOCK", io.classify_security_type("688111", "SH"))
        self.assertEqual("SZ_INDEX", io.classify_security_type("399001", "SZ"))
        self.assertEqual("SZ_A_STOCK", io.classify_security_type("000001", "SZ"))

    def test_coefficient_table(self):
        self.assertEqual([0.01, 0.01], io.security_coefficient("SH_A_STOCK"))
        self.assertEqual([0.01, 1.0], io.security_coefficient("SH_INDEX"))
        self.assertEqual([0.01, 0.01], io.security_coefficient("SZ_A_STOCK"))
        self.assertEqual([0.01, 1.0], io.security_coefficient("SZ_INDEX"))

    def test_day_round_trip_a_stock(self):
        df = _day_df([
            [pd.Timestamp("2026-07-01"), 35.0, 35.5, 34.5, 35.2, 1234.5, 1000.0],
            [pd.Timestamp("2026-07-02"), 35.2, 36.0, 35.0, 35.8, 2000.0, 1500.0],
        ])
        content = io.encode_day(df, "SH_A_STOCK")
        decoded = io.decode_day(content, "SH_A_STOCK")
        self.assertEqual(list(decoded.columns), ["datetime", "open", "high", "low", "close", "amount", "volume"])
        self.assertEqual(2, len(decoded))
        self.assertEqual(pd.Timestamp("2026-07-01"), decoded.iloc[0]["datetime"])
        self.assertAlmostEqual(35.0, decoded.iloc[0]["open"], places=4)
        self.assertAlmostEqual(35.8, decoded.iloc[-1]["close"], places=4)
        self.assertAlmostEqual(1000.0, decoded.iloc[0]["volume"], places=4)

    def test_day_round_trip_index_volume_unscaled(self):
        df = _day_df([[pd.Timestamp("2026-07-01"), 3000.0, 3010.0, 2990.0, 3005.0, 1e9, 123456789.0]])
        decoded = io.decode_day(io.encode_day(df, "SH_INDEX"), "SH_INDEX")
        self.assertAlmostEqual(123456789.0, decoded.iloc[0]["volume"], places=0)

    def test_read_day_missing_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(0, len(io.read_day(Path(tmp) / "x.day", "SH_A_STOCK")))

    def test_write_day_merges_and_dedups_keep_new(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sh000001.day"
            io.write_day(path, _day_df([[pd.Timestamp("2026-07-01"), 35.0, 35.5, 34.5, 35.2, 100.0, 1000.0]]), "SH_A_STOCK")
            # 覆盖同日 close 修正 + 追加新日
            io.write_day(path, _day_df([
                [pd.Timestamp("2026-07-01"), 35.0, 35.5, 34.5, 35.9, 100.0, 1000.0],  # 修正
                [pd.Timestamp("2026-07-02"), 36.0, 36.5, 35.8, 36.2, 200.0, 2000.0],
            ]), "SH_A_STOCK")
            decoded = io.read_day(path, "SH_A_STOCK")
            self.assertEqual(2, len(decoded))
            self.assertAlmostEqual(35.9, decoded.iloc[0]["close"], places=4)  # 新值胜出
            self.assertAlmostEqual(36.2, decoded.iloc[1]["close"], places=4)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/opt/homebrew/bin/python3.11 -m pytest tests/test_tdx_vipdoc_io.py -v`
Expected: FAIL — `ModuleNotFoundError: DataAPI.tdx_vipdoc_io`（或函数未定义）。

- [ ] **Step 3: Write minimal implementation**

`DataAPI/tdx_vipdoc_io.py`:
```python
"""通达信 vipdoc 二进制 K 线文件的自包含编/解/读写。

格式逐字核对自 tdxpy.reader.daily_bar_reader / lc_min_bar_reader：
- 日线 .day：32B/条，struct "<IIIIIfII"（日期YYYYMMDD int、开高低收 int、额 float32、量 int、保留 int）。
- 分钟 .lc1/.lc5：32B/条，struct "<HHfffffII"（日期 u16、时间 u16、开高低收额 float32、量 u32、保留 u32）。
日线读取按证券类型乘系数（与 tdxpy SECURITY_COEFFICIENT 一致），分钟无系数。
本模块读写自洽：encode/decode 互逆；写出的文件也能被 mootdx/tdxpy Reader 正常读取。
"""
import fcntl
import struct
from pathlib import Path

import pandas as pd

DAY_RECORD = struct.Struct("<IIIIIfII")
MIN_RECORD = struct.Struct("<HHfffffII")

COLUMNS = ["datetime", "open", "high", "low", "close", "amount", "volume"]

# 与 tdxpy TdxDailyBarReader.SECURITY_COEFFICIENT 对齐（仅取本项目支持的 SH/SZ 指数与 A 股）
SECURITY_COEFFICIENT = {
    "SH_A_STOCK": [0.01, 0.01],
    "SZ_A_STOCK": [0.01, 0.01],
    "SH_INDEX": [0.01, 1.0],
    "SZ_INDEX": [0.01, 1.0],
}


def classify_security_type(symbol: str, market: str) -> str:
    """按代码前缀判定证券类型（决定日线系数）。仅 SH/SZ。"""
    sym = str(symbol)
    if market == "SH":
        if sym.startswith(("000", "880", "990")):
            return "SH_INDEX"
        return "SH_A_STOCK"
    if market == "SZ":
        if sym.startswith("399"):
            return "SZ_INDEX"
        return "SZ_A_STOCK"
    raise ValueError(f"不支持的市场：{market}（仅 SH/SZ）")


def security_coefficient(security_type: str) -> list[float]:
    return SECURITY_COEFFICIENT[security_type]


def normalize_reader_df(df):
    """把任意来源的 K 线 DataFrame 规范为统一列与清洗。"""
    if df is None or df.empty:
        return pd.DataFrame(columns=COLUMNS)
    out = df.copy()
    if "datetime" not in out.columns:
        out["datetime"] = pd.to_datetime(out.index, errors="coerce")
    else:
        out["datetime"] = pd.to_datetime(out["datetime"], errors="coerce")
    for col in ("open", "high", "low", "close", "volume", "amount"):
        if col not in out.columns:
            out[col] = 0
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out[COLUMNS]
    out = out.dropna(subset=["datetime", "open", "high", "low", "close"])
    out = out[(out["high"] >= out["low"]) & (out["volume"].fillna(0) >= 0)]
    return out.drop_duplicates(subset=["datetime"]).sort_values("datetime").reset_index(drop=True)


def encode_day(df: pd.DataFrame, security_type: str) -> bytes:
    price_coeff, vol_coeff = security_coefficient(security_type)
    out = bytearray()
    for row in df.itertuples(index=False):
        dt = row.datetime
        date_int = dt.year * 10000 + dt.month * 100 + dt.day
        out += DAY_RECORD.pack(
            date_int,
            int(round(row.open / price_coeff)),
            int(round(row.high / price_coeff)),
            int(round(row.low / price_coeff)),
            int(round(row.close / price_coeff)),
            float(row.amount or 0.0),
            int(round((row.volume or 0.0) / vol_coeff)),
            0,
        )
    return bytes(out)


def decode_day(content: bytes, security_type: str) -> pd.DataFrame:
    if not content:
        return pd.DataFrame(columns=COLUMNS)
    price_coeff, vol_coeff = security_coefficient(security_type)
    records = []
    for i in range(0, len(content), DAY_RECORD.size):
        date_int, o, h, l, c, amount, vol, _ = DAY_RECORD.unpack_from(content, i)
        date_int = int(date_int)
        date_str = f"{date_int // 10000:04d}-{(date_int // 100) % 100:02d}-{date_int % 100:02d}"
        records.append([pd.Timestamp(date_str), o * price_coeff, h * price_coeff, l * price_coeff, c * price_coeff, amount, vol * vol_coeff])
    return pd.DataFrame(records, columns=COLUMNS)


def _merge_keep_new(old: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    if old.empty:
        merged = new
    elif new.empty:
        merged = old
    else:
        merged = pd.concat([old, new], ignore_index=True)
    return normalize_reader_df(merged)  # drop_duplicates keep=first → 旧在前新在后会保留旧；见下


def read_day(path: Path, security_type: str) -> pd.DataFrame:
    if not Path(path).is_file():
        return pd.DataFrame(columns=COLUMNS)
    return decode_day(Path(path).read_bytes(), security_type)


def _file_lock(path: Path):
    lock_path = Path(str(path) + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    f = open(lock_path, "a+b")
    fcntl.flock(f.fileno(), fcntl.LOCK_EX)
    return f


def write_day(path: Path, df: pd.DataFrame, security_type: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    new = normalize_reader_df(df)
    lock = _file_lock(path)
    try:
        old = read_day(path, security_type)
        # 新数据在后，去重保留最后出现（即新值胜出）
        if old.empty:
            merged = new
        else:
            merged = pd.concat([old, new], ignore_index=True).drop_duplicates(subset=["datetime"], keep="last")
            merged = merged.sort_values("datetime").reset_index(drop=True)
        content = encode_day(merged, security_type)
        _atomic_write(path, content)
    finally:
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()


def _atomic_write(path: Path, content: bytes) -> None:
    tmp = Path(str(path) + ".tmp")
    tmp.write_bytes(content)
    tmp.replace(path)
```

> 注：`normalize_reader_df` 内 `drop_duplicates(keep="first")` 用于纯规范清洗场景；`write_day` 单独用 `keep="last"` 以保证新值覆盖。两个路径独立，互不干扰。

- [ ] **Step 4: Run test to verify it passes**

Run: `/opt/homebrew/bin/python3.11 -m pytest tests/test_tdx_vipdoc_io.py -v`
Expected: PASS（6 用例全过）。

- [ ] **Step 5: Commit**

```bash
git add DataAPI/tdx_vipdoc_io.py tests/test_tdx_vipdoc_io.py
git commit -m "feat: 新增 tdx_vipdoc_io 日线编/解/读写与证券类型分类"
```

---

### Task 2: 分钟二进制编/解 + 读写

**Files:**
- Modify: `DataAPI/tdx_vipdoc_io.py`
- Test: `tests/test_tdx_vipdoc_io.py`（追加用例）

**Interfaces:**
- Produces: `encode_minute`, `decode_minute`, `read_minute`, `write_minute`。

- [ ] **Step 1: Write the failing test**

追加到 `tests/test_tdx_vipdoc_io.py` 末尾（`if __name__` 之前）：
```python
class MinuteIoTest(unittest.TestCase):
    def _min_df(self, rows):
        return pd.DataFrame(rows, columns=["datetime", "open", "high", "low", "close", "amount", "volume"])

    def test_minute_round_trip_lc1(self):
        df = self._min_df([
            [pd.Timestamp("2026-07-01 09:31"), 10.0, 10.5, 9.8, 10.2, 1000.0, 100],
            [pd.Timestamp("2026-07-01 09:32"), 10.2, 10.6, 10.1, 10.4, 1100.0, 110],
        ])
        content = io.encode_minute(df)
        decoded = io.decode_minute(content)
        self.assertEqual(list(decoded.columns), ["datetime", "open", "high", "low", "close", "amount", "volume"])
        self.assertEqual(2, len(decoded))
        self.assertEqual(pd.Timestamp("2026-07-01 09:31"), decoded.iloc[0]["datetime"])
        self.assertAlmostEqual(10.2, decoded.iloc[0]["close"], places=4)
        self.assertEqual(110, int(decoded.iloc[1]["volume"]))

    def test_minute_date_time_encoding_matches_tdxpy(self):
        # 日期 u16 = (年-2004)*2048 + 月*100 + 日；时间 u16 = 时*60+分
        df = self._min_df([[pd.Timestamp("2026-07-01 09:31"), 1, 1, 1, 1, 0, 0]])
        date_u16, time_u16 = struct.unpack("<HH", io.encode_minute(df)[:4])
        self.assertEqual((2026 - 2004) * 2048 + 7 * 100 + 1, date_u16)
        self.assertEqual(9 * 60 + 31, time_u16)

    def test_read_minute_missing_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(0, len(io.read_minute(Path(tmp) / "x.lc1")))

    def test_write_minute_appends_and_dedups_keep_new(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sh000001.lc1"
            io.write_minute(path, self._min_df([[pd.Timestamp("2026-07-01 09:31"), 10.0, 10.5, 9.8, 10.2, 1000.0, 100]]))
            io.write_minute(path, self._min_df([
                [pd.Timestamp("2026-07-01 09:31"), 10.0, 10.5, 9.8, 10.9, 1000.0, 100],  # 修正 close
                [pd.Timestamp("2026-07-01 09:32"), 10.2, 10.6, 10.1, 10.4, 1100.0, 110],
            ]))
            decoded = io.read_minute(path)
            self.assertEqual(2, len(decoded))
            self.assertAlmostEqual(10.9, decoded.iloc[0]["close"], places=4)
            self.assertAlmostEqual(10.4, decoded.iloc[1]["close"], places=4)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/opt/homebrew/bin/python3.11 -m pytest tests/test_tdx_vipdoc_io.py::MinuteIoTest -v`
Expected: FAIL — `AttributeError: module 'DataAPI.tdx_vipdoc_io' has no attribute 'encode_minute'`。

- [ ] **Step 3: Write minimal implementation**

追加到 `DataAPI/tdx_vipdoc_io.py`：
```python
def _encode_tdx_date(dt) -> int:
    return (dt.year - 2004) * 2048 + dt.month * 100 + dt.day


def _encode_tdx_time(dt) -> int:
    return dt.hour * 60 + dt.minute


def _decode_tdx_date(num: int):
    month = (num % 2048) // 100
    year = num // 2048 + 2004
    day = (num % 2048) % 100
    return year, month, day


def encode_minute(df: pd.DataFrame) -> bytes:
    out = bytearray()
    for row in df.itertuples(index=False):
        dt = row.datetime
        out += MIN_RECORD.pack(
            _encode_tdx_date(dt),
            _encode_tdx_time(dt),
            float(row.open or 0.0),
            float(row.high or 0.0),
            float(row.low or 0.0),
            float(row.close or 0.0),
            float(row.amount or 0.0),
            int(row.volume or 0.0),
            0,
        )
    return bytes(out)


def decode_minute(content: bytes) -> pd.DataFrame:
    if not content:
        return pd.DataFrame(columns=COLUMNS)
    records = []
    for i in range(0, len(content), MIN_RECORD.size):
        dnum, tnum, o, h, l, c, amount, vol, _ = MIN_RECORD.unpack_from(content, i)
        year, month, day = _decode_tdx_date(int(dnum))
        hour, minute = int(tnum) // 60, int(tnum) % 60
        records.append([pd.Timestamp(year=year, month=month, day=day, hour=hour, minute=minute), o, h, l, c, amount, vol])
    return pd.DataFrame(records, columns=COLUMNS)


def read_minute(path: Path) -> pd.DataFrame:
    if not Path(path).is_file():
        return pd.DataFrame(columns=COLUMNS)
    return decode_minute(Path(path).read_bytes())


def write_minute(path: Path, df: pd.DataFrame) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    new = normalize_reader_df(df)
    lock = _file_lock(path)
    try:
        old = read_minute(path)
        if old.empty:
            merged = new
        else:
            merged = pd.concat([old, new], ignore_index=True).drop_duplicates(subset=["datetime"], keep="last")
            merged = merged.sort_values("datetime").reset_index(drop=True)
        _atomic_write(path, encode_minute(merged))
    finally:
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/opt/homebrew/bin/python3.11 -m pytest tests/test_tdx_vipdoc_io.py -v`
Expected: PASS（全部用例）。

- [ ] **Step 5: Commit**

```bash
git add DataAPI/tdx_vipdoc_io.py tests/test_tdx_vipdoc_io.py
git commit -m "feat: tdx_vipdoc_io 增加分钟编/解/读写"
```

---

### Task 3: 分钟重采样（由 1m 派生 5m/15m/30m/60m）

**Files:**
- Modify: `DataAPI/tdx_vipdoc_io.py`
- Test: `tests/test_tdx_vipdoc_io.py`（追加用例）

**Interfaces:**
- Produces: `resample_minutes(df, target_interval) -> df`。逻辑逐字取自 `TdxHistoryAPI.__resample_minutes`（午休不跨段、按交易日分组、桶聚合），保持现有 `test_resamples_without_crossing_lunch_break` 行为一致。

- [ ] **Step 1: Write the failing test**

追加到 `tests/test_tdx_vipdoc_io.py`：
```python
class ResampleTest(unittest.TestCase):
    def _min_df(self, rows):
        return pd.DataFrame(rows, columns=["datetime", "open", "high", "low", "close", "amount", "volume"])

    def test_resample_15m_no_lunch_cross(self):
        df = self._min_df([
            [pd.Timestamp("2026-07-01 09:31"), 10.0, 10.5, 9.8, 10.2, 100.0, 10],
            [pd.Timestamp("2026-07-01 09:45"), 10.2, 11.0, 10.0, 10.8, 200.0, 20],
            [pd.Timestamp("2026-07-01 09:46"), 10.8, 11.2, 10.7, 11.0, 300.0, 30],
            [pd.Timestamp("2026-07-01 10:00"), 11.0, 11.5, 10.9, 11.4, 400.0, 40],
            [pd.Timestamp("2026-07-01 11:30"), 11.4, 11.8, 11.3, 11.6, 500.0, 50],
            [pd.Timestamp("2026-07-01 13:01"), 11.6, 12.0, 11.5, 11.9, 600.0, 60],
            [pd.Timestamp("2026-07-01 13:15"), 11.9, 12.2, 11.7, 12.1, 700.0, 70],
        ])
        out = io.resample_minutes(df, 15)
        self.assertEqual(
            ["2026-07-01 09:45", "2026-07-01 10:00", "2026-07-01 11:30", "2026-07-01 13:15"],
            [t.strftime("%Y-%m-%d %H:%M") for t in out["datetime"]],
        )
        self.assertAlmostEqual(10.0, out.iloc[0]["open"], places=4)
        self.assertAlmostEqual(11.0, out.iloc[0]["high"], places=4)
        self.assertAlmostEqual(10.8, out.iloc[0]["close"], places=4)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/opt/homebrew/bin/python3.11 -m pytest tests/test_tdx_vipdoc_io.py::ResampleTest -v`
Expected: FAIL — `AttributeError: ... has no attribute 'resample_minutes'`。

- [ ] **Step 3: Write minimal implementation**

追加到 `DataAPI/tdx_vipdoc_io.py`（逐字移植 `TdxHistoryAPI.__resample_minutes` 的静态实现，仅改输出列名一致性已满足）：
```python
def resample_minutes(df: pd.DataFrame, target_interval: int) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=COLUMNS)
    parts = []
    sessions = ((9, 30, 11, 30), (13, 0, 15, 0))
    for trading_day, day_df in df.groupby(df["datetime"].dt.normalize(), sort=True):
        for start_hour, start_minute, end_hour, end_minute in sessions:
            session_start = trading_day + pd.Timedelta(hours=start_hour, minutes=start_minute)
            session_end = trading_day + pd.Timedelta(hours=end_hour, minutes=end_minute)
            session_df = day_df[(day_df["datetime"] >= session_start) & (day_df["datetime"] <= session_end)].copy()
            if session_df.empty:
                continue
            elapsed_minutes = (session_df["datetime"] - session_start).dt.total_seconds() / 60
            buckets = ((elapsed_minutes - 1) // target_interval + 1).astype(int).clip(lower=1)
            session_df["bucket_end"] = session_start + pd.to_timedelta(buckets * target_interval, unit="min")
            aggregated = session_df.groupby("bucket_end", sort=True).agg(
                open=("open", "first"),
                high=("high", "max"),
                low=("low", "min"),
                close=("close", "last"),
                volume=("volume", "sum"),
                amount=("amount", "sum"),
            ).reset_index()
            parts.append(aggregated.rename(columns={"bucket_end": "datetime"}))
    if not parts:
        return pd.DataFrame(columns=COLUMNS)
    return pd.concat(parts, ignore_index=True)[COLUMNS].sort_values("datetime").reset_index(drop=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/opt/homebrew/bin/python3.11 -m pytest tests/test_tdx_vipdoc_io.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add DataAPI/tdx_vipdoc_io.py tests/test_tdx_vipdoc_io.py
git commit -m "feat: tdx_vipdoc_io 增加分钟重采样（午休不跨段）"
```

---

### Task 4: CTdxCache 本地优先（覆盖即不联网）

**Files:**
- Create: `DataAPI/TdxCacheAPI.py`
- Test: `tests/test_tdx_cache_api.py`

**Interfaces:**
- Consumes: `tdx_vipdoc_io`（read/write/decode/resample/normalize_reader_df/classify_security_type）、`TdxHistoryAPI.resolve_tdx_history_root`、`MootdxAPI.CMootdx`（联网兜底，本任务 mock）、`CommonStockAPI.CCommonStockApi`、`TdxHistoryAPI` 的代码/市场解析逻辑（复用 `parse_tdx_history_symbol`）。
- Produces: `CTdxCache` 类骨架 + `get_kl_data` 本地优先路径。

- [ ] **Step 1: Write the failing test**

`tests/test_tdx_cache_api.py`:
```python
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from Common.CEnum import KL_TYPE
from DataAPI.TdxCacheAPI import CTdxCache
from DataAPI.TdxHistoryAPI import TDX_HISTORY_DIR_ENV
from DataAPI import tdx_vipdoc_io as io


def _min_df(rows):
    return pd.DataFrame(rows, columns=["datetime", "open", "high", "low", "close", "amount", "volume"])


class TdxCacheLocalFirstTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        (self.root / "vipdoc/sh/minline").mkdir(parents=True)
        (self.root / "vipdoc/sh/lday").mkdir(parents=True)
        self.env_patch = patch.dict(os.environ, {TDX_HISTORY_DIR_ENV: str(self.root)})
        self.env_patch.start()

    def tearDown(self):
        self.env_patch.stop()
        self.temp_dir.cleanup()

    def test_local_covers_range_no_network(self):
        # 本地 1m 已覆盖请求范围 → 不应联网
        io.write_minute(
            self.root / "vipdoc/sh/minline/sh000001.lc1",
            _min_df([
                [pd.Timestamp("2026-07-01 09:31"), 10.0, 10.5, 9.8, 10.2, 100.0, 10],
                [pd.Timestamp("2026-07-01 09:45"), 10.2, 11.0, 10.0, 10.8, 200.0, 20],
            ]),
        )
        with patch("DataAPI.TdxCacheAPI.CMootdx") as mootdx_cls:
            bars = list(CTdxHistory("000001.SH", KL_TYPE.K_1M, "2026-07-01", "2026-07-01").get_kl_data()) if False else \
                   list(CTdxCache("000001.SH", KL_TYPE.K_1M, "2026-07-01", "2026-07-01").get_kl_data())
            self.assertFalse(mootdx_cls.called, "本地覆盖范围时不应实例化 CMootdx")
        self.assertEqual(2, len(bars))
        self.assertEqual("2026/07/01 09:31", bars[0].time.to_str())

    def test_local_day_covers_range_no_network(self):
        io.write_day(
            self.root / "vipdoc/sh/lday/sh000001.day",
            _min_df([
                [pd.Timestamp("2026-07-01"), 35.0, 35.5, 34.5, 35.2, 100.0, 1000.0],
                [pd.Timestamp("2026-07-02"), 35.2, 36.0, 35.0, 35.8, 200.0, 2000.0],
            ]),
            "SH_INDEX",
        )
        with patch("DataAPI.TdxCacheAPI.CMootdx") as mootdx_cls:
            bars = list(CTdxCache("SH000001", KL_TYPE.K_DAY, "2026-07-01", "2026-07-02").get_kl_data())
            self.assertFalse(mootdx_cls.called)
        self.assertEqual(2, len(bars))
        self.assertAlmostEqual(35.8, bars[-1].close, places=4)


if __name__ == "__main__":
    unittest.main()
```

> 注：用 `SH000001`（上证指数）便于日线系数用 `SH_INDEX`，且 `CMootdx` 对指数 1m 可能空数据——本任务全程不联网，规避该问题。

- [ ] **Step 2: Run test to verify it fails**

Run: `/opt/homebrew/bin/python3.11 -m pytest tests/test_tdx_cache_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'DataAPI.TdxCacheAPI'`。

- [ ] **Step 3: Write minimal implementation**

`DataAPI/TdxCacheAPI.py`:
```python
"""通达信本地缓存混合数据源：本地优先 → 联网兜底 → 写回 → 派生重采样。"""
import logging
from typing import Iterable

import pandas as pd

from Common.CEnum import AUTYPE, DATA_FIELD, KL_TYPE
from Common.CTime import CTime
from Common.func_util import str2float
from KLine.KLine_Unit import CKLine_Unit

from .CommonStockAPI import CCommonStockApi
from .MootdxAPI import CMootdx
from .TdxHistoryAPI import resolve_tdx_history_root, parse_tdx_history_symbol
from . import tdx_vipdoc_io as io

logger = logging.getLogger(__name__)

_NATIVE_INTERVALS = {
    KL_TYPE.K_1M: 1,
    KL_TYPE.K_5M: 5,
    KL_TYPE.K_15M: 15,
    KL_TYPE.K_30M: 30,
    KL_TYPE.K_60M: 60,
}


def _to_klu(row):
    dt = row["datetime"]
    return CKLine_Unit({
        DATA_FIELD.FIELD_TIME: CTime(dt.year, dt.month, dt.day, dt.hour, dt.minute, auto=False),
        DATA_FIELD.FIELD_OPEN: str2float(row["open"]),
        DATA_FIELD.FIELD_HIGH: str2float(row["high"]),
        DATA_FIELD.FIELD_LOW: str2float(row["low"]),
        DATA_FIELD.FIELD_CLOSE: str2float(row["close"]),
        DATA_FIELD.FIELD_VOLUME: str2float(row.get("volume", 0)),
        DATA_FIELD.FIELD_TURNOVER: str2float(row.get("amount", 0)),
    })


class CTdxCache(CCommonStockApi):
    """本地 vipdoc 优先，不足时联网（CMootdx）补齐并写回，派生级别由 1m 重采样。"""

    def __init__(self, code, k_type=KL_TYPE.K_1M, begin_date=None, end_date=None, autype=AUTYPE.NONE):
        self.tdx_root = resolve_tdx_history_root()
        self.symbol = None
        self.market = None
        self.security_type = None
        super(CTdxCache, self).__init__(code, k_type, begin_date, end_date, autype)

    def SetBasciInfo(self):
        self.symbol, self.market = parse_tdx_history_symbol(self.code)
        self.code = f"{self.symbol}.{self.market}"
        self.name = self.code
        self.security_type = io.classify_security_type(self.symbol, self.market)
        self.is_stock = self.security_type.endswith("A_STOCK")

    @classmethod
    def do_init(cls):
        pass

    @classmethod
    def do_close(cls):
        pass

    def _native_k_type(self):
        if self.k_type == KL_TYPE.K_DAY:
            return KL_TYPE.K_DAY
        if self.k_type == KL_TYPE.K_5M:
            return KL_TYPE.K_5M
        return KL_TYPE.K_1M  # 1m/15m/30m/60m 都用 1m 作后端

    def _native_path(self, native_k_type):
        market = self.market.lower()
        sym = f"{market}{self.symbol}"
        if native_k_type == KL_TYPE.K_DAY:
            return self.tdx_root / "vipdoc" / market / "lday" / f"{sym}.day"
        if native_k_type == KL_TYPE.K_5M:
            return self.tdx_root / "vipdoc" / market / "fzline" / f"{sym}.lc5"
        return self.tdx_root / "vipdoc" / market / "minline" / f"{sym}.lc1"

    def _read_local(self, native_k_type):
        path = self._native_path(native_k_type)
        if native_k_type == KL_TYPE.K_DAY:
            return io.read_day(path, self.security_type)
        return io.read_minute(path)

    def _write_local(self, native_k_type, df):
        path = self._native_path(native_k_type)
        try:
            if native_k_type == KL_TYPE.K_DAY:
                io.write_day(path, df, self.security_type)
            else:
                io.write_minute(path, df)
        except Exception as err:
            logger.warning("[tdx_cache] 写回失败 path=%s err=%s（不影响本次出图）", path, err)

    def _coverage_ceiling(self):
        if self.end_date:
            end = pd.to_datetime(self.end_date, errors="coerce")
            if pd.isna(end):
                return pd.Timestamp.now()
            if end == end.normalize():
                return end + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
            return end
        return pd.Timestamp.now()

    def get_kl_data(self):
        if self.autype != AUTYPE.NONE:
            logger.warning("[tdx_cache] 本地缓存为未复权数据 code=%s autype=%s", self.code, self.autype.name)

        native_k = self._native_k_type()
        native_df = self._read_local(native_k)
        ceiling = self._coverage_ceiling()
        last_local = native_df["datetime"].max() if not native_df.empty else None
        need_fetch = native_df.empty or (last_local is not None and last_local < ceiling)

        if not need_fetch:
            merged = native_df
        else:
            online = self._fetch_online(native_k, last_local)
            if online.empty and native_df.empty:
                raise RuntimeError(f"通达信缓存数据源未返回 {self.code} {self.k_type.name} 数据（本地与联网均空）")
            merged = io.normalize_reader_df(pd.concat([native_df, online], ignore_index=True)) if not native_df.empty else online
            if not online.empty:
                self._write_local(native_k, merged)

        df = self._derive_if_needed(native_k, merged)
        df = self._apply_range(df)
        for _, row in df.iterrows():
            yield _to_klu(row)

    def _fetch_online(self, native_k, last_local):
        # 占位：Task 5 实现。本任务因覆盖即跳过，不会进入此分支。
        return pd.DataFrame(columns=io.COLUMNS)

    def _derive_if_needed(self, native_k, merged):
        if self.k_type == native_k:
            return merged
        target = _NATIVE_INTERVALS.get(self.k_type)
        if target is None:
            return merged
        return io.resample_minutes(merged, target)

    def _apply_range(self, df):
        if df.empty:
            return df
        if self.begin_date:
            begin = pd.to_datetime(self.begin_date, errors="coerce")
            if not pd.isna(begin):
                df = df[df["datetime"] >= begin]
        if self.end_date:
            end = pd.to_datetime(self.end_date, errors="coerce")
            if not pd.isna(end):
                if end == end.normalize():
                    end = end + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
                df = df[df["datetime"] <= end]
        return df.reset_index(drop=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/opt/homebrew/bin/python3.11 -m pytest tests/test_tdx_cache_api.py -v`
Expected: PASS（2 用例）。

- [ ] **Step 5: Commit**

```bash
git add DataAPI/TdxCacheAPI.py tests/test_tdx_cache_api.py
git commit -m "feat: 新增 CTdxCache 本地优先读取路径"
```

---

### Task 5: CTdxCache 联网兜底 + 写回（增量补齐）

**Files:**
- Modify: `DataAPI/TdxCacheAPI.py`（实现 `_fetch_online`）
- Test: `tests/test_tdx_cache_api.py`（追加用例）

**Interfaces:**
- Produces: `_fetch_online` 用 `CMootdx` 拉原生级别缺口（`begin_date=last_local`），重建为规范 df 返回。

- [ ] **Step 1: Write the failing test**

追加到 `tests/test_tdx_cache_api.py`：
```python
class _FakeKLU:
    def __init__(self, dt, close):
        self.time = dt  # CTime-like with year/month/day/hour/minute
        self.open = close
        self.high = close + 0.1
        self.low = close - 0.1
        self.close = close
        class _TI:
            metric = {FIELD_TURNOVER: 100.0, FIELD_VOLUME: 10.0}
        self.trade_info = _TI()


class TdxCacheIncrementalTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        (self.root / "vipdoc/sh/minline").mkdir(parents=True)
        self.env_patch = patch.dict(os.environ, {TDX_HISTORY_DIR_ENV: str(self.root)})
        self.env_patch.start()

    def tearDown(self):
        self.env_patch.stop()
        self.temp_dir.cleanup()

    def test_fetches_gap_and_writes_back(self):
        from Common.CEnum import DATA_FIELD as FIELD_TURNOVER_MOD  # alias unused; real import below
        from Common.CEnum import DATA_FIELD
        # 本地有 07-01 09:31 一根
        io.write_minute(
            self.root / "vipdoc/sh/minline/sh000001.lc1",
            _min_df([[pd.Timestamp("2026-07-01 09:31"), 10.0, 10.5, 9.8, 10.2, 100.0, 10]]),
        )
        fake_units = [
            _FakeKLU(CTime(2026, 7, 1, 9, 31), 10.9),  # 重拉最后一根（修正 close=10.9）
            _FakeKLU(CTime(2026, 7, 1, 9, 32), 10.4),
        ]

        inst = type("M", (), {})()  # fake CMootdx instance
        inst.get_kl_data = lambda *a, **k: iter(fake_units)
        inst.do_init = lambda *a, **k: None
        inst.do_close = lambda *a, **k: None

        with patch("DataAPI.TdxCacheAPI.CMootdx", return_value=inst) as mootdx_cls:
            bars = list(CTdxCache("000001.SH", KL_TYPE.K_1M, "2026-07-01", "2026-07-01 09:32").get_kl_data())
            self.assertTrue(mootdx_cls.called)
            # 传给 CMootdx 的 begin_date 应为本地最后一根时间（增量）
            _, kwargs = mootdx_cls.call_args
            self.assertEqual(pd.Timestamp("2026-07-01 09:31"), pd.Timestamp(kwargs["begin_date"]))

        self.assertEqual(2, len(bars))
        self.assertAlmostEqual(10.9, bars[0].close, places=4)  # 新值胜出
        self.assertAlmostEqual(10.4, bars[1].close, places=4)
        # 写回后本地文件含两根且 09:31 为新值
        decoded = io.read_minute(self.root / "vipdoc/sh/minline/sh000001.lc1")
        self.assertEqual(2, len(decoded))
        self.assertAlmostEqual(10.9, decoded.iloc[0]["close"], places=4)
```

> 测试需在文件顶部 `from Common.CEnum import DATA_FIELD` 与 `from Common.CTime import CTime`。导入在 Step 3 一并处理；本步先写测试体。

- [ ] **Step 2: Run test to verify it fails**

Run: `/opt/homebrew/bin/python3.11 -m pytest tests/test_tdx_cache_api.py::TdxCacheIncrementalTest -v`
Expected: FAIL — `_fetch_online` 返回空 df → `_FakeKLU` 未被使用 → 断言失败。

- [ ] **Step 3: Write minimal implementation**

在 `tests/test_tdx_cache_api.py` 顶部 import 区补：
```python
from Common.CEnum import DATA_FIELD
from Common.CTime import CTime
```
（删除测试体内那两行多余的 `FIELD_TURNOVER_MOD` alias 与重复 import，保持 `_FakeKLU.trade_info.metric` 用 `DATA_FIELD.FIELD_TURNOVER`/`FIELD_VOLUME`。）

把 `_FakeKLU._TI.metric` 改为实例属性而非类属性，避免跨用例污染：
```python
class _FakeKLU:
    def __init__(self, dt, close):
        self.time = dt
        self.open = close
        self.high = close + 0.1
        self.low = close - 0.1
        self.close = close
        self.trade_info = type("_TI", (), {"metric": {DATA_FIELD.FIELD_TURNOVER: 100.0, DATA_FIELD.FIELD_VOLUME: 10.0}})()
```

在 `DataAPI/TdxCacheAPI.py` 实现 `_fetch_online`：
```python
    def _fetch_online(self, native_k, last_local):
        fetch_begin = last_local if last_local is not None else self.begin_date
        try:
            client = CMootdx(self.code, native_k, begin_date=fetch_begin, end_date=self.end_date, autype=AUTYPE.NONE)
        except Exception as err:
            logger.warning("[tdx_cache] 联网初始化失败 code=%s err=%s", self.code, err)
            return pd.DataFrame(columns=io.COLUMNS)
        try:
            client.do_init()
            rows = []
            for klu in client.get_kl_data():
                t = klu.time
                rows.append({
                    "datetime": pd.Timestamp(year=t.year, month=t.month, day=t.day, hour=t.hour, minute=t.minute),
                    "open": float(klu.open),
                    "high": float(klu.high),
                    "low": float(klu.low),
                    "close": float(klu.close),
                    "amount": float(klu.trade_info.metric.get(DATA_FIELD.FIELD_TURNOVER) or 0.0),
                    "volume": float(klu.trade_info.metric.get(DATA_FIELD.FIELD_VOLUME) or 0.0),
                })
            return io.normalize_reader_df(pd.DataFrame(rows, columns=io.COLUMNS))
        finally:
            try:
                client.do_close()
            except Exception:
                pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/opt/homebrew/bin/python3.11 -m pytest tests/test_tdx_cache_api.py -v`
Expected: PASS（含 Task 4 的 2 用例 + 本任务 1 用例）。

- [ ] **Step 5: Commit**

```bash
git add DataAPI/TdxCacheAPI.py tests/test_tdx_cache_api.py
git commit -m "feat: CTdxCache 联网兜底增量补齐并写回本地"
```

---

### Task 6: CTdxCache 派生级别（15m/30m/60m 由 1m 重采样）

**Files:**
- Modify: `tests/test_tdx_cache_api.py`（追加用例）

**Interfaces:**
- Consumes: Task 3 `resample_minutes`、Task 4 `_derive_if_needed`。

- [ ] **Step 1: Write the failing test**

追加到 `tests/test_tdx_cache_api.py`：
```python
class TdxCacheDerivedTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        (self.root / "vipdoc/sh/minline").mkdir(parents=True)
        self.env_patch = patch.dict(os.environ, {TDX_HISTORY_DIR_ENV: str(self.root)})
        self.env_patch.start()

    def tearDown(self):
        self.env_patch.stop()
        self.temp_dir.cleanup()

    def test_15m_derived_from_cached_1m_no_network(self):
        io.write_minute(
            self.root / "vipdoc/sh/minline/sh000001.lc1",
            _min_df([
                [pd.Timestamp("2026-07-01 09:31"), 10.0, 10.5, 9.8, 10.2, 100.0, 10],
                [pd.Timestamp("2026-07-01 09:45"), 10.2, 11.0, 10.0, 10.8, 200.0, 20],
                [pd.Timestamp("2026-07-01 10:00"), 11.0, 11.5, 10.9, 11.4, 400.0, 40],
            ]),
        )
        with patch("DataAPI.TdxCacheAPI.CMootdx") as mootdx_cls:
            bars = list(CTdxCache("000001.SH", KL_TYPE.K_15M, "2026-07-01", "2026-07-01").get_kl_data())
            self.assertFalse(mootdx_cls.called)
        self.assertEqual(["2026/07/01 09:45", "2026/07/01 10:00"], [b.time.to_str() for b in bars])
        self.assertAlmostEqual(10.0, bars[0].open, places=4)
        self.assertAlmostEqual(10.8, bars[0].close, places=4)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/opt/homebrew/bin/python3.11 -m pytest tests/test_tdx_cache_api.py::TdxCacheDerivedTest -v`
Expected: FAIL —— 若 Task 4/5 正确，此用例可能直接通过。若失败，说明派生路径有缺陷，进入 Step 3 修。

- [ ] **Step 3: Fix only if Step 2 failed**

预期 `_derive_if_needed` 对 `K_15M` 返回 `resample_minutes(merged, 15)`。若失败多为 `K_15M` 未命中 `_NATIVE_INTERVALS` 或 `native_k` 仍为 `K_1M` 导致 `_derive_if_needed` 第二分支缺。检查并补全分支，确保 `self.k_type != native_k` 时走 `resample_minutes`。

- [ ] **Step 4: Run test to verify it passes**

Run: `/opt/homebrew/bin/python3.11 -m pytest tests/test_tdx_cache_api.py::TdxCacheDerivedTest -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add tests/test_tdx_cache_api.py
git commit -m "test: CTdxCache 派生级别由缓存1m重采样"
```

---

### Task 7: CTdxCache 联网失败用本地兜底

**Files:**
- Modify: `DataAPI/TdxCacheAPI.py`（`get_kl_data` 的 `need_fetch` 分支加 try/except）
- Test: `tests/test_tdx_cache_api.py`（追加用例）

- [ ] **Step 1: Write the failing test**

追加到 `tests/test_tdx_cache_api.py`：
```python
class TdxCacheOnlineFallbackTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        (self.root / "vipdoc/sh/lday").mkdir(parents=True)
        self.env_patch = patch.dict(os.environ, {TDX_HISTORY_DIR_ENV: str(self.root)})
        self.env_patch.start()

    def tearDown(self):
        self.env_patch.stop()
        self.temp_dir.cleanup()

    def test_online_fails_uses_local(self):
        io.write_day(
            self.root / "vipdoc/sh/lday/sh000001.day",
            _min_df([[pd.Timestamp("2026-07-01"), 35.0, 35.5, 34.5, 35.2, 100.0, 1000.0]]),
            "SH_INDEX",
        )
        broken = type("M", (), {"get_kl_data": staticmethod(lambda: (_ for _ in ()).throw(RuntimeError("net down"))),
                                 "do_init": staticmethod(lambda: None), "do_close": staticmethod(lambda: None)})()
        with patch("DataAPI.TdxCacheAPI.CMootdx", return_value=broken):
            bars = list(CTdxCache("SH000001", KL_TYPE.K_DAY, "2026-07-01", "2026-07-08").get_kl_data())
        self.assertEqual(1, len(bars))
        self.assertAlmostEqual(35.2, bars[0].close, places=4)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/opt/homebrew/bin/python3.11 -m pytest tests/test_tdx_cache_api.py::TdxCacheOnlineFallbackTest -v`
Expected: FAIL — `_fetch_online` 内 `get_kl_data` 抛 `RuntimeError` 未捕获，向上冒泡。

- [ ] **Step 3: Write minimal implementation**

把 `get_kl_data` 中 `need_fetch` 分支改为对 `_fetch_online` 整体兜底：
```python
        if not need_fetch:
            merged = native_df
        else:
            try:
                online = self._fetch_online(native_k, last_local)
            except Exception as err:
                logger.warning("[tdx_cache] 联网失败 code=%s err=%s，回退本地数据", self.code, err)
                online = pd.DataFrame(columns=io.COLUMNS)
            if online.empty and native_df.empty:
                raise RuntimeError(f"通达信缓存数据源未返回 {self.code} {self.k_type.name} 数据（本地与联网均空）")
            merged = io.normalize_reader_df(pd.concat([native_df, online], ignore_index=True)) if not native_df.empty else online
            if not online.empty:
                self._write_local(native_k, merged)
```

> 同时把 `_fetch_online` 内 `client.get_kl_data()` 的抛错向上传（不吞），让本层统一兜底。即 `_fetch_online` 不再 catch `get_kl_data` 异常（构造失败仍返回空并告警，保持现状）。

- [ ] **Step 4: Run test to verify it passes**

Run: `/opt/homebrew/bin/python3.11 -m pytest tests/test_tdx_cache_api.py -v`
Expected: PASS（全部用例）。

- [ ] **Step 5: Commit**

```bash
git add DataAPI/TdxCacheAPI.py tests/test_tdx_cache_api.py
git commit -m "feat: CTdxCache 联网失败时回退本地数据"
```

---

### Task 8: web_server 接线（默认目录 + 源映射 + .gitignore）

**Files:**
- Modify: `web_server.py:37, 152-160, 1532-1543`
- Modify: `.gitignore`
- Modify: `tests/test_tdx_history_api.py:123-125`

**Interfaces:**
- Produces: `TDX_HISTORY_DATA_SOURCE = "custom:TdxCacheAPI.CTdxCache"`；`main()` 默认 `TDX_HISTORY_DIR=<repo>/data/tdx` 并建子目录。

- [ ] **Step 1: Write the failing test**

在 `tests/test_tdx_history_api.py` 的 `TdxHistoryApiTest` 中新增：
```python
    def test_web_source_maps_to_tdx_cache(self):
        self.assertEqual(parse_source("tdx_history"), "custom:TdxCacheAPI.CTdxCache")
        self.assertEqual(parse_source("通达信历史数据"), "custom:TdxCacheAPI.CTdxCache")
```
并把旧的 `test_web_source_maps_to_local_history_adapter` 删除（或改为断言 `TDX_HISTORY_DATA_SOURCE == "custom:TdxCacheAPI.CTdxCache"`，二者等价，保留其一即可）。

- [ ] **Step 2: Run test to verify it fails**

Run: `/opt/homebrew/bin/python3.11 -m pytest tests/test_tdx_history_api.py -v`
Expected: FAIL — `parse_source("tdx_history")` 仍返回旧 `custom:TdxHistoryAPI.CTdxHistory`。

- [ ] **Step 3: Write minimal implementation**

`web_server.py:37`：
```python
TDX_HISTORY_DATA_SOURCE = "custom:TdxCacheAPI.CTdxCache"
```

`web_server.py` `main()`（约 1540-1543）改为：
```python
    args = parser.parse_args()

    tdx_dir = args.tdx_history_dir or os.environ.get("TDX_HISTORY_DIR")
    if not tdx_dir:
        tdx_dir = str(Path(__file__).resolve().parent / "data" / "tdx")
    os.environ["TDX_HISTORY_DIR"] = tdx_dir
    for sub in ("sh/lday", "sh/minline", "sh/fzline", "sz/lday", "sz/minline", "sz/fzline"):
        (Path(tdx_dir) / "vipdoc" / sub).mkdir(parents=True, exist_ok=True)

    server = ThreadingHTTPServer((args.host, args.port), ChanChartHandler)
```

`.gitignore` 末尾追加：
```
data/tdx/
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/opt/homebrew/bin/python3.11 -m pytest tests/test_tdx_history_api.py tests/test_tdx_cache_api.py tests/test_tdx_vipdoc_io.py -v`
Expected: PASS（三套全过）。

- [ ] **Step 5: Commit**

```bash
git add web_server.py .gitignore tests/test_tdx_history_api.py
git commit -m "feat: web_server 默认TDX_HISTORY_DIR并指向CTdxCache数据源"
```

---

### Task 9: 端到端冒烟（真实联网，手动 verify）

**Files:** 无代码改动，仅运行验证。

- [ ] **Step 1: 启动服务**

Run: `/opt/homebrew/bin/python3.11 web_server.py --port 8000 &`
预期：打印 `Chan chart server: http://127.0.0.1:8000/`，`data/tdx/vipdoc/{sh,sz}/...` 目录被创建。

- [ ] **Step 2: 触发一次日线请求（联网首次写回）**

浏览器或 curl：`http://127.0.0.1:8000/?code=SH000001&lv=day&days=30&source=tdx_history`
预期：返回图表 HTML；`data/tdx/vipdoc/sh/lday/sh000001.day` 被创建且非空。

- [ ] **Step 3: 再次请求，确认命中本地不联网**

关闭网络或观察日志：再次请求同参数 → 日志无 `[mootdx] fetch start`，响应更快；本地文件不变。

- [ ] **Step 4: 触发 15m 派生**

`http://127.0.0.1:8000/?code=SH000001&lv=15m&days=5&source=tdx_history`
预期：联网拉 1m 写回 `sh000001.lc1`，再重采样出 15m 图。

- [ ] **Step 5: 停服并记录**

`kill %1`。若全部通过，无需提交（无代码改动）；若发现 bug，开新任务修复后再来。

---

## Self-Review

**Spec 覆盖：**
- 二进制写盘器 → Task 1（日线）+ Task 2（分钟）。✓
- 证券类型系数（A股/指数）→ Task 1 `classify_security_type`/`security_coefficient`/两个回环用例。✓
- 本地优先读 → Task 4。✓
- 联网兜底（CMootdx）→ Task 5 `_fetch_online`。✓
- 增量补齐（begin_date=last_local，重拉最后一根拾取修正，去重新值胜出）→ Task 5 测试断言 `begin_date==last_local` 与 `close==10.9`。✓
- 写回（整文件重写、合并去重）→ `write_day/write_minute`（Task 1/2）+ Task 5 验证写回内容。✓
- 派生级别由 1m 重采样 → Task 3 + Task 6。✓
- 错误兜底（联网失败用本地、本地空则抛错）→ Task 7。✓
- 默认目录 + 自动建子目录 → Task 8。✓
- `parse_source` 指向 CTdxCache → Task 8。✓
- `.gitignore` → Task 8。✓
- 文件锁防并发写 → `write_day/write_minute` 内 `_file_lock`（Task 1/2）。✓（并发用例未单列测试，但锁已就位；如需显式测试可加，YAGNI 暂不加。）
- 端到端冒烟 → Task 9。✓

**占位符扫描：** 无 TBD/TODO/"实现稍后"。Task 5 Step 1 有意保留两句说明性注释，Step 3 已给出确切替换代码。✓

**类型/命名一致性：** `COLUMNS`、`classify_security_type`、`security_coefficient`、`encode_day/decode_day/read_day/write_day`、`encode_minute/decode_minute/read_minute/write_minute`、`resample_minutes`、`normalize_reader_df` 在 Task 1 定义后，Task 2-8 引用一致。`CTdxCache._fetch_online/_native_k_type/_native_path/_read_local/_write_local/_coverage_ceiling/_derive_if_needed/_apply_range` 跨任务一致。`TDX_HISTORY_DATA_SOURCE` 在 Task 8 改值，`test_tdx_history_api.py` 同步更新。✓
