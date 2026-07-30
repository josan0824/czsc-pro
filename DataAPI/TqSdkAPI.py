"""TqSdk adapter for the supported Shanghai-listed index symbols."""

import os
from datetime import datetime
from pathlib import Path

import pandas as pd

from Common.CEnum import AUTYPE, DATA_FIELD, KL_TYPE
from Common.CTime import CTime
from Common.func_util import str2float
from KLine.KLine_Unit import CKLine_Unit

from .CommonStockAPI import CCommonStockApi


TQSDK_INDEX_SYMBOLS = {
    "000016": "SSE.000016",
    "000300": "SSE.000300",
    "000852": "SSE.000852",
    "000905": "SSE.000905",
}
TQSDK_KLINE_DURATIONS = {
    KL_TYPE.K_1M: 60,
    KL_TYPE.K_5M: 5 * 60,
    KL_TYPE.K_15M: 15 * 60,
    KL_TYPE.K_30M: 30 * 60,
    KL_TYPE.K_60M: 60 * 60,
    KL_TYPE.K_DAY: 24 * 60 * 60,
}
_MAX_KLINE_LENGTH = 10_000
TQSDK_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "tqsdk.config"


def normalize_tqsdk_symbol(code: str) -> str:
    """Normalize a supported index code to the TqSdk SSE symbol format."""
    value = str(code).strip().upper()
    if value.startswith("SSE."):
        code_number = value[4:]
    elif value.startswith("SSE"):
        code_number = value[3:]
    elif len(value) == 8 and value[:2] == "SH":
        code_number = value[2:]
    elif len(value) == 9 and value[6:] == ".SH":
        code_number = value[:6]
    else:
        code_number = value

    symbol = TQSDK_INDEX_SYMBOLS.get(code_number)
    if not symbol:
        supported = ", ".join(TQSDK_INDEX_SYMBOLS.values())
        raise ValueError(f"天勤数据源仅支持以下指数：{supported}；当前代码：{code}")
    return symbol


def _to_ctime(value: datetime) -> CTime:
    return CTime(value.year, value.month, value.day, value.hour, value.minute, value.second, auto=False)


def _match_datetime_timezone(value, datetime_series: pd.Series):
    timestamp = pd.to_datetime(value, errors="coerce")
    if pd.isna(timestamp):
        return None

    series_tz = getattr(datetime_series.dtype, "tz", None)
    timestamp_tz = getattr(timestamp, "tzinfo", None)
    if series_tz is not None:
        if timestamp_tz is None:
            return timestamp.tz_localize(series_tz)
        return timestamp.tz_convert(series_tz)
    if timestamp_tz is not None:
        return timestamp.tz_localize(None)
    return timestamp


def load_tqsdk_credentials() -> tuple[str, str]:
    """Load project credentials first, then allow deployment env vars to override them."""
    values: dict[str, str] = {}
    if TQSDK_CONFIG_PATH.is_file():
        for raw_line in TQSDK_CONFIG_PATH.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() in {"TQ_ACCOUNT", "TQ_PASSWORD"}:
                values[key.strip()] = value.strip().strip('"').strip("'")

    account = os.environ.get("TQ_ACCOUNT", values.get("TQ_ACCOUNT", "")).strip()
    password = os.environ.get("TQ_PASSWORD", values.get("TQ_PASSWORD", ""))
    return account, password


class CTqSdk(CCommonStockApi):
    """Load the latest bounded K-line window from TqSdk."""

    api = None

    def __init__(self, code, k_type=KL_TYPE.K_1M, begin_date=None, end_date=None, autype=AUTYPE.NONE):
        self.symbol = None
        super(CTqSdk, self).__init__(code, k_type, begin_date, end_date, autype)

    def SetBasciInfo(self):
        self.symbol = normalize_tqsdk_symbol(self.code)
        self.code = self.symbol
        self.name = self.symbol
        self.is_stock = False

    @classmethod
    def do_init(cls):
        if cls.api is not None:
            return

        account, password = load_tqsdk_credentials()
        if not account or not password:
            raise RuntimeError(
                "天勤数据源需要在 config/tqsdk.config 中配置 TQ_ACCOUNT 和 TQ_PASSWORD，"
                "或设置同名环境变量。"
            )

        try:
            from tqsdk import TqApi, TqAuth
        except ImportError as err:
            raise ImportError("缺少 tqsdk 依赖，请先安装：python -m pip install -U tqsdk") from err

        cls.api = TqApi(auth=TqAuth(account, password))

    @classmethod
    def do_close(cls):
        if cls.api is not None:
            cls.api.close()
        cls.api = None

    def get_kl_data(self):
        for _, row in self.__fetch_df().iterrows():
            yield CKLine_Unit({
                DATA_FIELD.FIELD_TIME: _to_ctime(row["datetime"]),
                DATA_FIELD.FIELD_OPEN: str2float(row["open"]),
                DATA_FIELD.FIELD_HIGH: str2float(row["high"]),
                DATA_FIELD.FIELD_LOW: str2float(row["low"]),
                DATA_FIELD.FIELD_CLOSE: str2float(row["close"]),
                DATA_FIELD.FIELD_VOLUME: str2float(row["volume"]),
                DATA_FIELD.FIELD_TURNOVER: 0.0,
            })

    def __fetch_df(self) -> pd.DataFrame:
        duration = TQSDK_KLINE_DURATIONS.get(self.k_type)
        if duration is None:
            raise ValueError(f"天勤数据源不支持 {self.k_type.name} 级别的K线数据")

        frame = self.__class__.api.get_kline_serial(
            self.symbol,
            duration_seconds=duration,
            data_length=_MAX_KLINE_LENGTH,
        )
        frame = frame.copy()
        if frame.empty:
            raise RuntimeError(f"天勤未返回 {self.symbol} {self.k_type.name} K线数据")

        try:
            from tqsdk import tafunc
        except ImportError as err:
            raise ImportError("缺少 tqsdk 依赖，请先安装：python -m pip install -U tqsdk") from err

        frame["datetime"] = pd.to_numeric(frame["datetime"], errors="coerce")
        frame = frame[frame["datetime"].notna() & (frame["datetime"] > 0)].copy()
        if frame.empty:
            raise RuntimeError(f"天勤未返回 {self.symbol} {self.k_type.name} K线数据")
        frame["datetime"] = frame["datetime"].map(tafunc.time_to_datetime)
        for column in ("open", "high", "low", "close", "volume"):
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frame = frame.dropna(subset=["datetime", "open", "high", "low", "close"])
        frame = frame[(frame["high"] >= frame["low"]) & (frame["volume"].fillna(0) >= 0)]

        if self.begin_date:
            begin = _match_datetime_timezone(self.begin_date, frame["datetime"])
            if begin is not None:
                frame = frame[frame["datetime"] >= begin]
        if self.end_date:
            end = pd.to_datetime(self.end_date, errors="coerce")
            if not pd.isna(end):
                if end == end.normalize():
                    end += pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
                end = _match_datetime_timezone(end, frame["datetime"])
                if end is not None:
                    frame = frame[frame["datetime"] <= end]

        frame = frame.drop_duplicates(subset=["datetime"]).sort_values("datetime").reset_index(drop=True)
        if frame.empty:
            raise RuntimeError(f"天勤未返回 {self.symbol} 在请求范围内的 {self.k_type.name} K线数据")
        return frame
