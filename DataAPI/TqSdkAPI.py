"""TqSdk adapter for the supported Shanghai-listed index symbols."""

import logging
import os
from datetime import datetime
from pathlib import Path

import pandas as pd

from Common.CEnum import AUTYPE, DATA_FIELD, KL_TYPE
from Common.CTime import CTime
from Common.func_util import str2float
from KLine.KLine_Unit import CKLine_Unit

from .CommonStockAPI import CCommonStockApi
from .TdxHistoryAPI import TDX_HISTORY_DIR_ENV
from . import tdx_vipdoc_io as io


logger = logging.getLogger(__name__)


TQSDK_INDEX_SYMBOLS = {
    "000016": "SSE.000016",
    "000300": "SSE.000300",
    "000852": "SSE.000852",
    "000905": "SSE.000905",
}
TQSDK_INDEX_NAMES = {
    "000016": "上证50",
    "000300": "沪深300",
    "000852": "中证1000",
    "000905": "中证500",
}
TQSDK_KLINE_DURATIONS = {
    KL_TYPE.K_1M: 60,
    KL_TYPE.K_5M: 5 * 60,
    KL_TYPE.K_15M: 15 * 60,
    KL_TYPE.K_30M: 30 * 60,
    KL_TYPE.K_60M: 60 * 60,
    KL_TYPE.K_DAY: 24 * 60 * 60,
}
TQSDK_NATIVE_K_TYPES = {
    KL_TYPE.K_DAY: KL_TYPE.K_DAY,
}
_MAX_KLINE_LENGTH = 10_000
TQSDK_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "tqsdk.config"
TQSDK_DEFAULT_TDX_ROOT = Path(__file__).resolve().parents[1] / "data" / "tdx"


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


def _drop_datetime_timezone(value):
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is not None:
        return timestamp.tz_localize(None)
    return timestamp


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


def _resolve_tqsdk_cache_root() -> Path:
    configured_path = os.environ.get(TDX_HISTORY_DIR_ENV, "").strip()
    path = Path(configured_path).expanduser() if configured_path else TQSDK_DEFAULT_TDX_ROOT
    if path.name.lower() == "vipdoc":
        path = path.parent
    for subdir in ("sh/lday", "sh/minline", "sh/fzline", "sz/lday", "sz/minline", "sz/fzline"):
        (path / "vipdoc" / subdir).mkdir(parents=True, exist_ok=True)
    return path.resolve()


def _tqsdk_cache_symbol(tqsdk_symbol: str) -> tuple[str, str]:
    symbol = normalize_tqsdk_symbol(tqsdk_symbol)
    return symbol.split(".", 1)[1], "SH"


def _latest_a_share_minute_ceiling(now: pd.Timestamp | None = None) -> pd.Timestamp:
    now = pd.Timestamp.now() if now is None else pd.Timestamp(now)
    current_day = now.normalize()
    previous_day = current_day - pd.Timedelta(days=1)
    while previous_day.weekday() >= 5:
        previous_day -= pd.Timedelta(days=1)
    previous_close = previous_day + pd.Timedelta(hours=14, minutes=59)

    if now.weekday() >= 5:
        return previous_close

    morning_open = current_day + pd.Timedelta(hours=9, minutes=30)
    morning_close = current_day + pd.Timedelta(hours=11, minutes=29)
    afternoon_open = current_day + pd.Timedelta(hours=13)
    market_close = current_day + pd.Timedelta(hours=14, minutes=59)

    if now < morning_open:
        return previous_close
    if now <= morning_close:
        return now.floor("min")
    if now < afternoon_open:
        return morning_close
    if now <= market_close:
        return now.floor("min")
    return market_close


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
    """本地 vipdoc 优先，不足时通过 TqSdk 补齐并写回本地缓存。"""

    api = None

    def __init__(self, code, k_type=KL_TYPE.K_1M, begin_date=None, end_date=None, autype=AUTYPE.NONE):
        self.symbol = None
        self.tdx_root = _resolve_tqsdk_cache_root()
        self.cache_symbol = None
        self.cache_market = None
        self.security_type = None
        self.cache_name = None
        self._exported_minute_df = None
        super(CTqSdk, self).__init__(code, k_type, begin_date, end_date, autype)

    def SetBasciInfo(self):
        self.symbol = normalize_tqsdk_symbol(self.code)
        self.code = self.symbol
        self.name = self.symbol
        self.cache_symbol, self.cache_market = _tqsdk_cache_symbol(self.symbol)
        self.security_type = io.classify_security_type(self.cache_symbol, self.cache_market)
        self.cache_name = TQSDK_INDEX_NAMES.get(self.cache_symbol, self.symbol)
        self.is_stock = False

    @classmethod
    def do_init(cls):
        pass

    @classmethod
    def _ensure_api(cls):
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
                DATA_FIELD.FIELD_TURNOVER: str2float(row.get("amount", 0)),
            })

    def __fetch_df(self) -> pd.DataFrame:
        native_k = self.__native_k_type()
        native_df = self.__read_local(native_k)
        ceiling = self.__coverage_ceiling(native_k)
        last_local = native_df["datetime"].max() if not native_df.empty else None
        need_fetch = native_df.empty or (last_local is not None and last_local < ceiling)

        if self.begin_date and not native_df.empty:
            begin = pd.to_datetime(self.begin_date, errors="coerce")
            if not pd.isna(begin):
                first_local = native_df["datetime"].min()
                if begin == begin.normalize():
                    need_fetch = need_fetch or first_local.normalize() > begin.normalize()
                else:
                    need_fetch = need_fetch or first_local > begin

        if not need_fetch:
            merged = native_df
            if native_k == KL_TYPE.K_1M and not merged.empty and not self.__has_prefixed_exported_csv():
                self.__write_local(native_k, merged)
        else:
            try:
                online = self.__fetch_online_df(native_k, last_local)
            except Exception as err:
                if native_df.empty:
                    raise
                logger.warning("[tqsdk] 联网失败 code=%s err=%s，回退本地数据", self.code, err)
                online = pd.DataFrame(columns=io.COLUMNS)
            if online.empty and native_df.empty:
                raise RuntimeError(f"天勤数据源未返回 {self.symbol} {self.k_type.name} 数据（本地与联网均空）")
            if native_df.empty:
                merged = online
            else:
                merged = (
                    pd.concat([native_df, online], ignore_index=True)
                    .drop_duplicates(subset=["datetime"], keep="last")
                    .sort_values("datetime")
                    .reset_index(drop=True)
                )
            if not online.empty:
                self.__write_local(native_k, merged)

        frame = self.__derive_if_needed(native_k, merged)
        frame = self.__apply_range(frame)
        if frame.empty:
            raise RuntimeError(f"天勤未返回 {self.symbol} 在请求范围内的 {self.k_type.name} K线数据")
        return frame

    def __native_k_type(self):
        return TQSDK_NATIVE_K_TYPES.get(self.k_type, KL_TYPE.K_1M)

    def __native_path(self, native_k_type):
        market = self.cache_market.lower()
        sym = f"{market}{self.cache_symbol}"
        if native_k_type == KL_TYPE.K_DAY:
            return self.tdx_root / "vipdoc" / market / "lday" / f"{sym}.day"
        if native_k_type == KL_TYPE.K_5M:
            return self.tdx_root / "vipdoc" / market / "fzline" / f"{sym}.lc5"
        return self.tdx_root / "vipdoc" / market / "minline" / f"{sym}.lc1"

    def __read_local(self, native_k_type):
        path = self.__native_path(native_k_type)
        if native_k_type == KL_TYPE.K_DAY:
            return io.read_day(path, self.security_type)

        exported_1m = self.__read_exported_1m()
        return io.resample_minutes(exported_1m, 5) if native_k_type == KL_TYPE.K_5M else exported_1m

    def __read_exported_1m(self):
        if self._exported_minute_df is None:
            self._exported_minute_df = io.read_exported_minute_csv(
                self.tdx_root / "vipdoc", f"{self.cache_market.lower()}{self.cache_symbol}"
            )
            if not self._exported_minute_df.empty:
                logger.info("[tqsdk] loaded exported 1m csv code=%s rows=%s", self.code, len(self._exported_minute_df))
        return self._exported_minute_df

    def __has_prefixed_exported_csv(self) -> bool:
        code = f"{self.cache_market.lower()}{self.cache_symbol}"
        pattern = f"????-??_1min/????????_1min/{code}.csv"
        return any((self.tdx_root / "vipdoc").glob(pattern))

    def __write_local(self, native_k_type, df):
        path = self.__native_path(native_k_type)
        try:
            if native_k_type == KL_TYPE.K_DAY:
                io.write_day(path, df, self.security_type)
                path_label = path
            elif native_k_type == KL_TYPE.K_1M:
                written_paths = io.write_exported_minute_csv(
                    self.tdx_root / "vipdoc",
                    f"{self.cache_market.lower()}{self.cache_symbol}",
                    self.cache_name,
                    df,
                )
                path_label = ", ".join(str(path) for path in written_paths)
            else:
                io.write_minute(path, df)
                path_label = path
            logger.info("[tqsdk] wrote local cache path=%s rows=%s", path_label, len(df))
        except Exception as err:
            logger.warning("[tqsdk] 写回失败 path=%s err=%s（不影响本次出图）", path, err)

    def __coverage_ceiling(self, native_k_type):
        if native_k_type == KL_TYPE.K_DAY:
            if self.end_date:
                end = pd.to_datetime(self.end_date, errors="coerce")
                return pd.Timestamp.now().normalize() if pd.isna(end) else end.normalize()
            return pd.Timestamp.now().normalize()
        if self.end_date:
            end = pd.to_datetime(self.end_date, errors="coerce")
            if pd.isna(end):
                return pd.Timestamp.now()
            if end == end.normalize():
                return end + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
            return end
        return _latest_a_share_minute_ceiling()

    def __fetch_online_df(self, native_k_type, last_local) -> pd.DataFrame:
        self.__class__._ensure_api()
        duration = TQSDK_KLINE_DURATIONS.get(native_k_type)
        if duration is None:
            raise ValueError(f"天勤数据源不支持 {native_k_type.name} 级别的K线数据")

        frame = self.__class__.api.get_kline_serial(
            self.symbol,
            duration_seconds=duration,
            data_length=_MAX_KLINE_LENGTH,
        )
        frame = frame.copy()
        if frame.empty:
            return pd.DataFrame(columns=io.COLUMNS)

        try:
            from tqsdk import tafunc
        except ImportError as err:
            raise ImportError("缺少 tqsdk 依赖，请先安装：python -m pip install -U tqsdk") from err

        frame["datetime"] = pd.to_numeric(frame["datetime"], errors="coerce")
        frame = frame[frame["datetime"].notna() & (frame["datetime"] > 0)].copy()
        if frame.empty:
            return pd.DataFrame(columns=io.COLUMNS)
        frame["datetime"] = frame["datetime"].map(tafunc.time_to_datetime)
        frame["datetime"] = frame["datetime"].map(_drop_datetime_timezone)
        if native_k_type == KL_TYPE.K_DAY:
            frame["datetime"] = frame["datetime"].map(lambda value: pd.Timestamp(value).normalize())
        if "amount" not in frame.columns:
            frame["amount"] = 0.0
        frame = io.normalize_reader_df(frame)

        fetch_begin = last_local if last_local is not None else self.begin_date
        if fetch_begin is not None:
            begin = _match_datetime_timezone(fetch_begin, frame["datetime"])
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
        return frame

    def __derive_if_needed(self, native_k_type, frame):
        if self.k_type == native_k_type:
            return frame
        target_interval = {
            KL_TYPE.K_15M: 15,
            KL_TYPE.K_30M: 30,
            KL_TYPE.K_60M: 60,
        }.get(self.k_type)
        if target_interval is None:
            return frame
        return io.resample_minutes(frame, target_interval)

    def __apply_range(self, frame):
        if frame.empty:
            return frame
        if self.begin_date:
            begin = pd.to_datetime(self.begin_date, errors="coerce")
            if not pd.isna(begin):
                frame = frame[frame["datetime"] >= begin]
        if self.end_date:
            end = pd.to_datetime(self.end_date, errors="coerce")
            if not pd.isna(end):
                if end == end.normalize():
                    end = end + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
                frame = frame[frame["datetime"] <= end]
        return frame.reset_index(drop=True)
