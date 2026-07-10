import logging
import os
from pathlib import Path

import pandas as pd

from Common.CEnum import AUTYPE, DATA_FIELD, KL_TYPE
from Common.CTime import CTime
from Common.func_util import str2float
from KLine.KLine_Unit import CKLine_Unit

from .CommonStockAPI import CCommonStockApi


logger = logging.getLogger(__name__)

TDX_HISTORY_DIR_ENV = "TDX_HISTORY_DIR"
_MINUTE_INTERVALS = {
    KL_TYPE.K_1M: 1,
    KL_TYPE.K_5M: 5,
    KL_TYPE.K_15M: 15,
    KL_TYPE.K_30M: 30,
    KL_TYPE.K_60M: 60,
}


def resolve_tdx_history_root() -> Path:
    """Return the TongDaXin root directory that contains vipdoc/."""
    configured_path = os.environ.get(TDX_HISTORY_DIR_ENV, "").strip()
    if not configured_path:
        raise RuntimeError(
            "未配置通达信历史数据目录。请设置 TDX_HISTORY_DIR 为包含 vipdoc 目录的通达信安装目录，"
            "例如：export TDX_HISTORY_DIR=/path/to/tdx"
        )

    path = Path(configured_path).expanduser()
    if path.name.lower() == "vipdoc":
        path = path.parent
    vipdoc_path = path / "vipdoc"
    if not path.is_dir() or not vipdoc_path.is_dir():
        raise RuntimeError(
            f"通达信历史数据目录无效：{path}。{TDX_HISTORY_DIR_ENV} 应指向包含 vipdoc 的通达信安装目录。"
        )
    return path.resolve()


def parse_tdx_history_symbol(code: str) -> tuple[str, str]:
    """Normalize an A-share code while preserving the supplied exchange."""
    value = str(code).strip().upper()
    if len(value) == 8 and value[:2] in ("SH", "SZ") and value[2:].isdigit():
        return value[2:], value[:2]
    if len(value) == 9 and value[6] == "." and value[:6].isdigit() and value[7:] in ("SH", "SZ"):
        return value[:6], value[7:]

    symbol = value[:6]
    if not symbol.isdigit():
        raise ValueError(f"无法识别通达信历史数据代码：{code}")
    if symbol.startswith(("5", "6", "9")) or symbol.startswith(("000", "880", "990")):
        return symbol, "SH"
    if symbol.startswith(("0", "2", "3")):
        return symbol, "SZ"
    raise ValueError(f"无法识别通达信历史数据市场：{code}")


def parse_time(value) -> CTime:
    dt = pd.to_datetime(value)
    return CTime(dt.year, dt.month, dt.day, dt.hour, dt.minute, auto=False)


def create_item_dict(row) -> dict:
    return {
        DATA_FIELD.FIELD_TIME: parse_time(row["datetime"]),
        DATA_FIELD.FIELD_OPEN: str2float(row["open"]),
        DATA_FIELD.FIELD_HIGH: str2float(row["high"]),
        DATA_FIELD.FIELD_LOW: str2float(row["low"]),
        DATA_FIELD.FIELD_CLOSE: str2float(row["close"]),
        DATA_FIELD.FIELD_VOLUME: str2float(row.get("volume", 0)),
        DATA_FIELD.FIELD_TURNOVER: str2float(row.get("amount", 0)),
    }


class CTdxHistory(CCommonStockApi):
    """Read local TongDaXin vipdoc historical K-line files."""

    def __init__(self, code, k_type=KL_TYPE.K_1M, begin_date=None, end_date=None, autype=AUTYPE.NONE):
        self.tdx_root = resolve_tdx_history_root()
        self.symbol = None
        self.market = None
        super(CTdxHistory, self).__init__(code, k_type, begin_date, end_date, autype)

    def SetBasciInfo(self):
        self.symbol, self.market = parse_tdx_history_symbol(self.code)
        self.code = f"{self.symbol}.{self.market}"
        self.name = self.code
        self.is_stock = not (
            (self.market == "SH" and self.symbol.startswith(("000", "880", "990")))
            or (self.market == "SZ" and self.symbol.startswith("399"))
        )

    @classmethod
    def do_init(cls):
        pass

    @classmethod
    def do_close(cls):
        pass

    def get_kl_data(self):
        if self.autype != AUTYPE.NONE:
            logger.warning(
                "[tdx_history] local vipdoc data is not adjusted; code=%s requested autype=%s",
                self.code,
                self.autype.name,
            )
        for _, row in self.__fetch_df().iterrows():
            yield CKLine_Unit(create_item_dict(row))

    def __fetch_df(self) -> pd.DataFrame:
        raw_df, source_interval = self.__read_source_df()
        df = self.__normalize_df(raw_df)
        if df.empty:
            raise RuntimeError(f"通达信历史数据未返回 {self.code} {self.k_type.name} K线数据")

        target_interval = _MINUTE_INTERVALS.get(self.k_type)
        if target_interval and source_interval and target_interval != source_interval:
            df = self.__resample_minutes(df, target_interval)

        if self.begin_date:
            begin = pd.to_datetime(self.begin_date, errors="coerce")
            if not pd.isna(begin):
                df = df[df["datetime"] >= begin]
        if self.end_date:
            end = pd.to_datetime(self.end_date, errors="coerce")
            if not pd.isna(end):
                if end == end.normalize():
                    end += pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
                df = df[df["datetime"] <= end]

        df = df.drop_duplicates(subset=["datetime"]).sort_values("datetime").reset_index(drop=True)
        if df.empty:
            raise RuntimeError(f"通达信历史数据在指定日期范围内未返回 {self.code} {self.k_type.name} K线数据")
        logger.info(
            "[tdx_history] loaded rows=%s code=%s k_type=%s root=%s begin=%s end=%s",
            len(df),
            self.code,
            self.k_type.name,
            self.tdx_root,
            self.begin_date,
            self.end_date,
        )
        return df

    def __read_source_df(self):
        reader = self.__make_reader()
        if self.k_type == KL_TYPE.K_DAY:
            df = reader.daily(symbol=self.__reader_symbol())
            if df is None or df.empty:
                self.__raise_missing_file("日线", "lday", "day")
            return df, None

        target_interval = _MINUTE_INTERVALS.get(self.k_type)
        if target_interval is None:
            raise ValueError(f"通达信历史数据不支持 {self.k_type.name} 级别的K线数据")

        if target_interval == 1:
            df = reader.minute(symbol=self.__reader_symbol(), suffix=1)
            if df is None or df.empty:
                self.__raise_missing_file("1分钟", "minline", "lc1")
            return df, 1

        if target_interval == 5:
            df = reader.minute(symbol=self.__reader_symbol(), suffix=5)
            if df is not None and not df.empty:
                return df, 5
            df = reader.minute(symbol=self.__reader_symbol(), suffix=1)
            if df is None or df.empty:
                self.__raise_missing_file("5分钟或1分钟", "fzline", "lc5")
            return df, 1

        df = reader.minute(symbol=self.__reader_symbol(), suffix=1)
        if df is not None and not df.empty:
            return df, 1
        df = reader.minute(symbol=self.__reader_symbol(), suffix=5)
        if df is not None and not df.empty:
            return df, 5
        self.__raise_missing_file(f"{target_interval}分钟聚合所需的1分钟或5分钟", "minline", "lc1")

    def __make_reader(self):
        try:
            from mootdx.reader import Reader
        except ImportError as err:
            raise ImportError("缺少 mootdx 依赖，请先执行：python -m pip install -U mootdx") from err
        return Reader.factory(market="std", tdxdir=str(self.tdx_root))

    def __reader_symbol(self) -> str:
        return f"{self.market.lower()}{self.symbol}"

    def __raise_missing_file(self, label: str, subdir: str, suffix: str):
        expected_path = self.tdx_root / "vipdoc" / self.market.lower() / subdir / f"{self.__reader_symbol()}.{suffix}"
        raise FileNotFoundError(
            f"通达信历史数据未找到 {self.code} 的{label}文件，期望路径：{expected_path}。"
            "请在通达信客户端中下载对应历史数据后重试。"
        )

    @staticmethod
    def __normalize_df(df: pd.DataFrame) -> pd.DataFrame:
        if df is None or df.empty:
            return pd.DataFrame(columns=["datetime", "open", "high", "low", "close", "volume", "amount"])
        out = df.copy()
        out["datetime"] = pd.to_datetime(out.index, errors="coerce")
        for column in ("open", "high", "low", "close", "volume", "amount"):
            if column not in out:
                out[column] = 0
            out[column] = pd.to_numeric(out[column], errors="coerce")
        out = out[["datetime", "open", "high", "low", "close", "volume", "amount"]]
        out = out.dropna(subset=["datetime", "open", "high", "low", "close"])
        out = out[(out["high"] >= out["low"]) & (out["volume"].fillna(0) >= 0)]
        return out.sort_values("datetime").reset_index(drop=True)

    @staticmethod
    def __resample_minutes(df: pd.DataFrame, target_interval: int) -> pd.DataFrame:
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
            return pd.DataFrame(columns=["datetime", "open", "high", "low", "close", "volume", "amount"])
        return pd.concat(parts, ignore_index=True).sort_values("datetime").reset_index(drop=True)
