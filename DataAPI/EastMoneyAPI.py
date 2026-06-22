import requests
import pandas as pd

from Common.CEnum import AUTYPE, DATA_FIELD, KL_TYPE
from Common.CTime import CTime
from Common.func_util import str2float
from KLine.KLine_Unit import CKLine_Unit

from .CommonStockAPI import CCommonStockApi


def parse_market(code: str):
    value = code.strip().upper()
    if len(value) == 8 and value[:2] in ("SH", "SZ", "BJ"):
        return value[2:], value[:2]
    if len(value) == 9 and value[6] == "." and value[7:] in ("SH", "SZ", "BJ"):
        return value[:6], value[7:]
    symbol = value[:6]
    if symbol.startswith(("0", "2", "3")):
        return symbol, "SZ"
    if symbol.startswith(("4", "8")):
        return symbol, "BJ"
    if symbol.startswith(("5", "6", "9")):
        return symbol, "SH"
    if symbol.startswith("399"):
        return symbol, "SZ"
    if symbol.startswith("000"):
        return symbol, "SH"
    raise ValueError(f"无法识别市场: {code}")


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


class CEastMoney(CCommonStockApi):
    hosts = [
        "https://push2his.eastmoney.com",
        "https://1.push2his.eastmoney.com",
        "https://48.push2his.eastmoney.com",
        "https://67.push2his.eastmoney.com",
        "http://push2his.eastmoney.com",
    ]

    def __init__(self, code, k_type=KL_TYPE.K_1M, begin_date=None, end_date=None, autype=AUTYPE.QFQ):
        self.symbol = None
        self.market = None
        super(CEastMoney, self).__init__(code, k_type, begin_date, end_date, autype)

    def SetBasciInfo(self):
        self.symbol, self.market = parse_market(self.code)
        self.code = f"{self.symbol}.{self.market}"
        self.name = self.code
        self.is_stock = not (
            (self.market == "SH" and self.symbol.startswith("000")) or
            (self.market == "SZ" and self.symbol.startswith("399"))
        )

    def get_kl_data(self):
        df = self.__fetch_df()
        for _, row in df.iterrows():
            yield CKLine_Unit(create_item_dict(row))

    @classmethod
    def do_init(cls):
        pass

    @classmethod
    def do_close(cls):
        pass

    def __fetch_df(self):
        if self.k_type == KL_TYPE.K_1M:
            df = self.__fetch_trends_1m()
        else:
            df = self.__fetch_kline()
        df = self.__normalize_df(df)
        if self.begin_date:
            df = df[df["datetime"] >= pd.to_datetime(self.begin_date)]
        if self.end_date:
            df = df[df["datetime"] <= pd.to_datetime(self.end_date)]
        if df.empty:
            raise Exception(f"东方财富未返回 {self.code} {self.k_type.name} K线数据")
        return df.reset_index(drop=True)

    def __fetch_trends_1m(self):
        params = {
            "fields1": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
            "iscr": "0",
            "ndays": "5",
            "ut": "7eea3edcaed734bea9cbfc24409ed989",
            "secid": self.__secid(),
        }
        data = self.__request("/api/qt/stock/trends2/get", params).get("data") or {}
        rows = data.get("trends") or []
        parsed = [row.split(",") for row in rows]
        return pd.DataFrame(parsed, columns=["datetime", "open", "close", "high", "low", "volume", "amount", "avg"])

    def __fetch_kline(self):
        params = {
            "secid": self.__secid(),
            "ut": "7eea3edcaed734bea9cbfc24409ed989",
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "klt": self.__klt(),
            "fqt": self.__fqt(),
            "beg": self.__format_date(self.begin_date, default="0"),
            "end": self.__format_date(self.end_date, default="20500000"),
        }
        data = self.__request("/api/qt/stock/kline/get", params).get("data") or {}
        rows = data.get("klines") or []
        parsed = [row.split(",") for row in rows]
        return pd.DataFrame(parsed, columns=[
            "datetime", "open", "close", "high", "low", "volume", "amount",
            "amplitude", "pct_chg", "chg", "turnover_rate",
        ])

    def __normalize_df(self, df):
        if df is None or df.empty:
            return pd.DataFrame(columns=["datetime", "open", "high", "low", "close", "volume", "amount"])
        out = df.copy()
        out["datetime"] = pd.to_datetime(out["datetime"], errors="coerce")
        for col in ("open", "high", "low", "close", "volume", "amount"):
            out[col] = pd.to_numeric(out[col], errors="coerce")
        out = out[["datetime", "open", "high", "low", "close", "volume", "amount"]]
        out = out.dropna(subset=["datetime", "open", "high", "low", "close"])
        out = out[out["high"] >= out["low"]]
        return out.drop_duplicates(subset=["datetime"]).sort_values("datetime")

    def __request(self, path, params):
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Connection": "close",
            "Origin": "https://quote.eastmoney.com",
            "Referer": "https://quote.eastmoney.com/",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            ),
        }
        last_error = None
        for trust_env in (False, True):
            session = requests.Session()
            session.trust_env = trust_env
            for host in self.hosts:
                url = f"{host}{path}"
                try:
                    response = session.get(url, params=params, headers=headers, timeout=15)
                    response.raise_for_status()
                    return response.json()
                except Exception as err:
                    last_error = err
            session.close()
        raise last_error

    def __secid(self):
        market_id = 1 if self.market == "SH" else 0
        return f"{market_id}.{self.symbol}"

    def __klt(self):
        mapping = {
            KL_TYPE.K_5M: "5",
            KL_TYPE.K_15M: "15",
            KL_TYPE.K_30M: "30",
            KL_TYPE.K_60M: "60",
            KL_TYPE.K_DAY: "101",
            KL_TYPE.K_WEEK: "102",
            KL_TYPE.K_MON: "103",
        }
        if self.k_type not in mapping:
            raise Exception(f"东方财富不支持 {self.k_type.name} 级别的K线数据")
        return mapping[self.k_type]

    def __fqt(self):
        if self.autype == AUTYPE.QFQ:
            return "1"
        if self.autype == AUTYPE.HFQ:
            return "2"
        return "0"

    @staticmethod
    def __format_date(date_value, default):
        if date_value is None:
            return default
        return str(date_value)[:10].replace("-", "")
