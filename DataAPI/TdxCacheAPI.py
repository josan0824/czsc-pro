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

    def _coverage_ceiling(self, native_k):
        """本地需覆盖到的最晚时刻。日级按日期比较（日线存为午夜），分钟级按时间戳比较。"""
        if native_k == KL_TYPE.K_DAY:
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
        return pd.Timestamp.now()

    def get_kl_data(self):
        if self.autype != AUTYPE.NONE:
            logger.warning("[tdx_cache] 本地缓存为未复权数据 code=%s autype=%s", self.code, self.autype.name)

        native_k = self._native_k_type()
        native_df = self._read_local(native_k)
        ceiling = self._coverage_ceiling(native_k)
        last_local = native_df["datetime"].max() if not native_df.empty else None
        need_fetch = native_df.empty or (last_local is not None and last_local < ceiling)

        if not need_fetch:
            merged = native_df
        else:
            online = self._fetch_online(native_k, last_local)
            if online.empty and native_df.empty:
                raise RuntimeError(f"通达信缓存数据源未返回 {self.code} {self.k_type.name} 数据（本地与联网均空）")
            # 合并：同时间戳保留联网新值（online 在后，keep="last"）
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
                self._write_local(native_k, merged)

        df = self._derive_if_needed(native_k, merged)
        df = self._apply_range(df)
        for _, row in df.iterrows():
            yield _to_klu(row)

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
