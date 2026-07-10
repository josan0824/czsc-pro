"""通达信 vipdoc 二进制 K 线文件的自包含编/解/读写。

格式逐字核对自 tdxpy.reader.daily_bar_reader / lc_min_bar_reader：
- 日线 .day：32B/条，struct "<IIIIIfII"（日期 YYYYMMDD int、开高低收 int、额 float32、量 int、保留 int）。
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
        records.append([
            pd.Timestamp(date_str),
            o * price_coeff,
            h * price_coeff,
            l * price_coeff,
            c * price_coeff,
            amount,
            vol * vol_coeff,
        ])
    return pd.DataFrame(records, columns=COLUMNS)


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


def _atomic_write(path: Path, content: bytes) -> None:
    tmp = Path(str(path) + ".tmp")
    tmp.write_bytes(content)
    tmp.replace(path)


def write_day(path: Path, df: pd.DataFrame, security_type: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    new = normalize_reader_df(df)
    lock = _file_lock(path)
    try:
        old = read_day(path, security_type)
        if old.empty:
            merged = new
        else:
            merged = pd.concat([old, new], ignore_index=True).drop_duplicates(
                subset=["datetime"], keep="last"
            )
            merged = merged.sort_values("datetime").reset_index(drop=True)
        _atomic_write(path, encode_day(merged, security_type))
    finally:
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()


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
        records.append([
            pd.Timestamp(year=year, month=month, day=day, hour=hour, minute=minute),
            o, h, l, c, amount, vol,
        ])
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
            merged = pd.concat([old, new], ignore_index=True).drop_duplicates(
                subset=["datetime"], keep="last"
            )
            merged = merged.sort_values("datetime").reset_index(drop=True)
        _atomic_write(path, encode_minute(merged))
    finally:
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()
