import json
import math
import os
from pathlib import Path

import pandas as pd

from Common.CEnum import AUTYPE, DATA_FIELD, KL_TYPE
from Common.CTime import CTime
from Common.func_util import str2float
from KLine.KLine_Unit import CKLine_Unit

from .CommonStockAPI import CCommonStockApi


def parse_tdx_symbol(symbol):
    s = symbol.upper().strip()
    if len(s) == 8 and s[:2] in ("SH", "SZ"):
        s = f"{s[2:]}.{s[:2]}"

    if len(s) == 9 and s[6] == ".":
        code, suffix = s[:6], s[7:]
        if suffix == "SZ":
            return 0, code, suffix
        if suffix == "SH":
            return 1, code, suffix

    code = s[:6]
    if code.startswith(("0", "2", "3")):
        return 0, code, "SZ"
    if code.startswith(("5", "6", "9")):
        return 1, code, "SH"
    if code.startswith("399"):
        return 0, code, "SZ"
    if code.startswith("000"):
        return 1, code, "SH"

    raise ValueError(f"无法识别通达信市场: {symbol}")


def parse_time(value):
    dt = pd.to_datetime(value)
    return CTime(dt.year, dt.month, dt.day, dt.hour, dt.minute, auto=False)


def create_item_dict(row):
    return {
        DATA_FIELD.FIELD_TIME: parse_time(row["datetime"]),
        DATA_FIELD.FIELD_OPEN: str2float(row["open"]),
        DATA_FIELD.FIELD_HIGH: str2float(row["high"]),
        DATA_FIELD.FIELD_LOW: str2float(row["low"]),
        DATA_FIELD.FIELD_CLOSE: str2float(row["close"]),
        DATA_FIELD.FIELD_VOLUME: str2float(row.get("volume", 0)),
        DATA_FIELD.FIELD_TURNOVER: str2float(row.get("amount", 0)),
    }


class CMootdx(CCommonStockApi):
    client = None
    current_server = None
    default_server = ("110.41.147.114", 7709)
    servers = [
        ("110.41.147.114", 7709),
        ("8.129.13.54", 7709),
        ("120.24.149.49", 7709),
        ("124.70.176.52", 7709),
        ("47.100.236.28", 7709),
        ("101.133.214.242", 7709),
        ("119.97.185.59", 7709),
    ]

    def __init__(self, code, k_type=KL_TYPE.K_1M, begin_date=None, end_date=None, autype=AUTYPE.NONE):
        self.market = None
        self.market_id = None
        self.symbol = None
        self.is_index = False
        super(CMootdx, self).__init__(code, k_type, begin_date, end_date, autype)

    def get_kl_data(self):
        df = self.__fetch_bars()
        df = self.__normalize_df(df)
        for _, row in df.iterrows():
            yield CKLine_Unit(create_item_dict(row))

    def SetBasciInfo(self):
        self.market_id, self.symbol, self.market = parse_tdx_symbol(self.code)
        self.code = f"{self.symbol}.{self.market}"
        self.name = self.code
        self.is_index = (
            (self.market == "SH" and self.symbol.startswith(("000", "880", "990"))) or
            (self.market == "SZ" and self.symbol.startswith("399"))
        )
        self.is_stock = not self.is_index

    @classmethod
    def do_init(cls):
        if cls.client is None:
            cls.__connect(cls.default_server)

    @classmethod
    def do_close(cls):
        if cls.client is not None and hasattr(cls.client, "close"):
            cls.client.close()
        cls.client = None
        cls.current_server = None

    def __fetch_bars(self):
        last_error = None
        for server in self.servers:
            try:
                self.__class__.__connect(server)
                df = self.__fetch_bars_from_current_server()
                if df is not None and not df.empty:
                    return df
            except Exception as err:
                last_error = err

        if self.is_index and self.k_type == KL_TYPE.K_1M:
            detail = f"最后错误：{last_error}" if last_error else "所有服务器均返回空数据。"
            raise Exception(
                f"通达信线上接口未返回{self.code}的1分钟指数K线。{detail}"
                "如需近一个月上证指数1分钟数据，请使用本地通达信 vipdoc/minline 的 lc1 文件或其他指数分钟数据源。"
            )
        if last_error:
            raise last_error
        return pd.DataFrame()

    def __fetch_bars_from_current_server(self):
        frequency = self.__convert_type()
        chunks = []
        for page in range(self.__max_pages()):
            start = page * 800
            try:
                df = self.__request_bars(frequency=frequency, start=start)
            except Exception:
                if chunks:
                    break
                if self.k_type == KL_TYPE.K_1M and frequency == 8:
                    df = self.__request_bars(frequency=7, start=start)
                else:
                    raise
            if (df is None or df.empty) and chunks:
                break
            if (df is None or df.empty) and self.k_type == KL_TYPE.K_1M and frequency == 8:
                df = self.__request_bars(frequency=7, start=start)
            if df is None or df.empty:
                break
            chunks.append(df)
            if len(df) < 800:
                break
            if self.begin_date:
                normalized = self.__normalize_df(pd.concat(chunks, ignore_index=False))
                if not normalized.empty and normalized["datetime"].min() <= pd.to_datetime(self.begin_date):
                    break

        if not chunks:
            return pd.DataFrame()
        return pd.concat(chunks, ignore_index=False)

    def __max_pages(self):
        if not self.begin_date:
            return 10
        begin = pd.to_datetime(self.begin_date, errors="coerce")
        if pd.isna(begin):
            return 10
        days = max(1, (pd.Timestamp.now().normalize() - begin.normalize()).days + 1)
        per_day = {
            KL_TYPE.K_1M: 240,
            KL_TYPE.K_5M: 48,
            KL_TYPE.K_15M: 16,
            KL_TYPE.K_30M: 8,
            KL_TYPE.K_60M: 4,
            KL_TYPE.K_DAY: 1,
            KL_TYPE.K_WEEK: 1 / 5,
            KL_TYPE.K_MON: 1 / 22,
        }.get(self.k_type, 240)
        return max(1, min(10, math.ceil(days * per_day / 800) + 1))

    def __request_bars(self, frequency, start):
        if self.is_index:
            return self.client.index(symbol=self.symbol, frequency=frequency, start=start, offset=800)
        return self.client.bars(symbol=self.symbol, frequency=frequency, start=start, offset=800)

    def __normalize_df(self, df):
        if df is None or df.empty:
            return pd.DataFrame(columns=["datetime", "open", "high", "low", "close", "volume", "amount"])

        out = df.copy()
        out.columns = [str(col).lower() for col in out.columns]

        if "datetime" not in out.columns:
            if "date" in out.columns:
                out["datetime"] = pd.to_datetime(out["date"])
            else:
                out["datetime"] = pd.to_datetime(out.index)
        else:
            out["datetime"] = pd.to_datetime(out["datetime"])
        out = out.reset_index(drop=True)

        if "volume" not in out.columns and "vol" in out.columns:
            out["volume"] = out["vol"]
        if "amount" not in out.columns:
            out["amount"] = 0

        for col in ("open", "high", "low", "close", "volume", "amount"):
            if col not in out.columns:
                out[col] = pd.NA
            out[col] = pd.to_numeric(out[col], errors="coerce")

        out = out[["datetime", "open", "high", "low", "close", "volume", "amount"]]
        out = out.dropna(subset=["datetime", "open", "high", "low", "close"])
        out = out[out["high"] >= out["low"]]
        out = out[out["volume"].fillna(0) >= 0]
        out = out.drop_duplicates(subset=["datetime"]).sort_values("datetime")

        if self.begin_date:
            out = out[out["datetime"] >= pd.to_datetime(self.begin_date)]
        if self.end_date:
            out = out[out["datetime"] <= pd.to_datetime(self.end_date)]

        return out.reset_index(drop=True)

    def __convert_type(self):
        _dict = {
            KL_TYPE.K_1M: 8,
            KL_TYPE.K_5M: 0,
            KL_TYPE.K_15M: 1,
            KL_TYPE.K_30M: 2,
            KL_TYPE.K_60M: 3,
            KL_TYPE.K_DAY: 9,
            KL_TYPE.K_WEEK: 5,
            KL_TYPE.K_MON: 6,
        }
        if self.k_type not in _dict:
            raise Exception(f"mootdx不支持{self.k_type}级别的K线数据")
        return _dict[self.k_type]

    @classmethod
    def __ensure_mootdx_config(cls):
        project_root = Path(__file__).resolve().parent.parent
        config_dir = project_root / ".mootdx"
        config_dir.mkdir(exist_ok=True)
        config_path = config_dir / "config.json"
        if not config_path.exists():
            config = {
                "SERVER": {
                    "HQ": [["默认通达信行情", cls.default_server[0], cls.default_server[1]]],
                    "EX": [],
                    "GP": [],
                },
                "BESTIP": {"HQ": list(cls.default_server), "EX": "", "GP": ""},
                "TDXDIR": "C:/new_tdx",
            }
            config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        os.environ["HOME"] = str(project_root)

    @classmethod
    def __connect(cls, server):
        if cls.client is not None and cls.current_server == server:
            return
        if cls.client is not None and hasattr(cls.client, "close"):
            cls.client.close()
        cls.__ensure_mootdx_config()
        try:
            from mootdx.quotes import Quotes
        except ImportError as err:
            raise ImportError("缺少 mootdx 依赖，请先执行：/opt/homebrew/bin/python3.11 -m pip install -U mootdx") from err
        cls.client = Quotes.factory(
            market="std",
            server=server,
            bestip=False,
            multithread=True,
            heartbeat=True,
            timeout=3,
        )
        cls.current_server = server
