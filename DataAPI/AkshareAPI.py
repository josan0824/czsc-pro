import akshare as ak
import pandas as pd
import requests
from requests import RequestException

from Common.CEnum import AUTYPE, DATA_FIELD, KL_TYPE
from Common.CTime import CTime
from Common.func_util import kltype_lt_day, str2float
from KLine.KLine_Unit import CKLine_Unit

from .CommonStockAPI import CCommonStockApi


def create_item_dict(row, autype):
    """将DataFrame行转换为K线单元所需的字典格式"""
    item = {}
    # 解析日期 - 处理多种格式
    date_val = row['日期'] if '日期' in row else row['时间']
    if isinstance(date_val, pd.Timestamp):
        year, month, day = date_val.year, date_val.month, date_val.day
        hour, minute = date_val.hour, date_val.minute
    elif isinstance(date_val, str):
        date_str = date_val
        if len(date_str) >= 16 and "-" in date_str and ":" in date_str:
            dt = pd.to_datetime(date_str)
            year, month, day = dt.year, dt.month, dt.day
            hour, minute = dt.hour, dt.minute
        elif len(date_str) == 10:  # 格式: 2021-09-13
            year = int(date_str[:4])
            month = int(date_str[5:7])
            day = int(date_str[8:10])
            hour = minute = 0
        else:  # 格式: 20210913
            year = int(date_str[:4])
            month = int(date_str[4:6])
            day = int(date_str[6:8])
            hour = minute = 0
    else:
        # 尝试转换
        dt = pd.to_datetime(date_val)
        year, month, day = dt.year, dt.month, dt.day
        hour, minute = dt.hour, dt.minute

    item[DATA_FIELD.FIELD_TIME] = CTime(year, month, day, hour, minute)
    item[DATA_FIELD.FIELD_OPEN] = str2float(row['开盘'])
    item[DATA_FIELD.FIELD_HIGH] = str2float(row['最高'])
    item[DATA_FIELD.FIELD_LOW] = str2float(row['最低'])
    item[DATA_FIELD.FIELD_CLOSE] = str2float(row['收盘'])
    item[DATA_FIELD.FIELD_VOLUME] = str2float(row['成交量'])
    item[DATA_FIELD.FIELD_TURNOVER] = str2float(row.get('成交额', 0))

    # 换手率可能不存在
    if '换手率' in row:
        item[DATA_FIELD.FIELD_TURNRATE] = str2float(row['换手率'])

    return item


class CAkshare(CCommonStockApi):
    """使用 akshare 获取A股数据"""

    def __init__(self, code, k_type=KL_TYPE.K_DAY, begin_date=None, end_date=None, autype=AUTYPE.QFQ):
        super(CAkshare, self).__init__(code, k_type, begin_date, end_date, autype)

    def get_kl_data(self):
        """获取K线数据"""
        # 转换复权类型
        adjust_dict = {
            AUTYPE.QFQ: "qfq",
            AUTYPE.HFQ: "hfq",
            AUTYPE.NONE: ""
        }
        adjust = adjust_dict.get(self.autype, "qfq")

        # 转换周期类型
        period = self.__convert_type()

        # 格式化日期
        start_date = self.__format_date(self.begin_date, intraday=kltype_lt_day(self.k_type), is_start=True)
        end_date = self.__format_date(self.end_date, intraday=kltype_lt_day(self.k_type), is_start=False)

        # 获取数据
        if self.is_stock:
            if kltype_lt_day(self.k_type):
                df = ak.stock_zh_a_hist_min_em(
                    symbol=self.code,
                    period=period,
                    start_date=start_date,
                    end_date=end_date,
                    adjust=adjust,
                )
            else:
                # 个股数据
                df = ak.stock_zh_a_hist(
                    symbol=self.code,
                    period=period,
                    start_date=start_date,
                    end_date=end_date,
                    adjust=adjust
                )
        else:
            if kltype_lt_day(self.k_type):
                df = self.__get_index_min_data(period, start_date, end_date)
            else:
                # 指数数据
                df = ak.stock_zh_index_daily(symbol=self.__akshare_index_code())
                # 筛选日期范围
                df['日期'] = df['date'].astype(str)
                df = df.rename(columns={
                    'date': '日期',
                    'open': '开盘',
                    'high': '最高',
                    'low': '最低',
                    'close': '收盘',
                    'volume': '成交量'
                })
                if 'amount' in df.columns:
                    df['成交额'] = df['amount']
                else:
                    df['成交额'] = 0
                df = df[(df['日期'] >= start_date) & (df['日期'] <= end_date)]

        # 遍历每一行生成K线单元
        for _, row in df.iterrows():
            yield CKLine_Unit(create_item_dict(row, self.autype))

    def SetBasciInfo(self):
        """设置基本信息"""
        self.market = self.__parse_market(self.code)
        self.code = self.__normalize_code(self.code)
        self.name = self.code
        code_num = self.__code_num()
        self.is_stock = not (
            (self.market == "SH" and code_num.startswith("000")) or
            (self.market == "SZ" and code_num.startswith("399"))
        )

    @classmethod
    def do_init(cls):
        """初始化 (akshare不需要登录)"""
        pass

    @classmethod
    def do_close(cls):
        """关闭 (akshare不需要登出)"""
        pass

    def __convert_type(self):
        """转换K线周期类型"""
        _dict = {
            KL_TYPE.K_1M: '1',
            KL_TYPE.K_5M: '5',
            KL_TYPE.K_15M: '15',
            KL_TYPE.K_30M: '30',
            KL_TYPE.K_60M: '60',
            KL_TYPE.K_DAY: 'daily',
            KL_TYPE.K_WEEK: 'weekly',
            KL_TYPE.K_MON: 'monthly',
        }
        if self.k_type not in _dict:
            raise Exception(f"akshare不支持{self.k_type}级别的K线数据")
        return _dict[self.k_type]

    @staticmethod
    def __normalize_code(code):
        code = code.strip()
        if len(code) == 9 and code[6] == "." and code[7:].upper() in ("SH", "SZ", "BJ"):
            return code[:6]
        if len(code) == 8 and code[:2].lower() in ("sh", "sz", "bj"):
            return code[2:]
        return code

    def __code_num(self):
        return self.code[-6:] if len(self.code) >= 6 else self.code

    def __akshare_index_code(self):
        suffix = self.market.lower() if self.market else ("sz" if self.__code_num().startswith("399") else "sh")
        return f"{suffix}{self.__code_num()}"

    def __eastmoney_secid(self):
        market_id = 0 if self.market == "SZ" else 1
        return f"{market_id}.{self.__code_num()}"

    def __get_index_min_data(self, period, start_date, end_date):
        if period == "1":
            path = "/api/qt/stock/trends2/get"
            params = {
                "fields1": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13",
                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
                "iscr": "0",
                "ndays": "5",
                "ut": "7eea3edcaed734bea9cbfc24409ed989",
                "secid": self.__eastmoney_secid(),
            }
            data = self.__eastmoney_get(path, params).get("data") or {}
            rows = data.get("trends") or []
            df = pd.DataFrame([row.split(",") for row in rows])
            if df.empty:
                return pd.DataFrame(columns=["时间", "开盘", "收盘", "最高", "最低", "成交量", "成交额", "均价"])
            df.columns = ["时间", "开盘", "收盘", "最高", "最低", "成交量", "成交额", "均价"]
            numeric_columns = ["开盘", "收盘", "最高", "最低", "成交量", "成交额", "均价"]
        else:
            path = "/api/qt/stock/kline/get"
            params = {
                "secid": self.__eastmoney_secid(),
                "ut": "7eea3edcaed734bea9cbfc24409ed989",
                "fields1": "f1,f2,f3,f4,f5,f6",
                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
                "klt": period,
                "fqt": "1",
                "beg": "0",
                "end": "20500000",
            }
            data = self.__eastmoney_get(path, params).get("data") or {}
            rows = data.get("klines") or []
            df = pd.DataFrame([row.split(",") for row in rows])
            if df.empty:
                return pd.DataFrame(columns=[
                    "时间", "开盘", "收盘", "最高", "最低", "涨跌幅", "涨跌额", "成交量", "成交额", "振幅", "换手率"
                ])
            df.columns = ["时间", "开盘", "收盘", "最高", "最低", "成交量", "成交额", "振幅", "涨跌幅", "涨跌额", "换手率"]
            df = df[["时间", "开盘", "收盘", "最高", "最低", "涨跌幅", "涨跌额", "成交量", "成交额", "振幅", "换手率"]]
            numeric_columns = ["开盘", "收盘", "最高", "最低", "涨跌幅", "涨跌额", "成交量", "成交额", "振幅", "换手率"]

        df.index = pd.to_datetime(df["时间"], errors="coerce")
        df = df[start_date:end_date]
        df.reset_index(drop=True, inplace=True)
        for column in numeric_columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")
        df["时间"] = pd.to_datetime(df["时间"], errors="coerce").astype(str)
        return df

    @staticmethod
    def __eastmoney_get(path, params):
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Connection": "close",
            "Host": "push2his.eastmoney.com",
            "Origin": "https://quote.eastmoney.com",
            "Referer": "https://quote.eastmoney.com/",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
        }
        urls = [
            f"https://push2his.eastmoney.com{path}",
            f"http://push2his.eastmoney.com{path}",
            f"https://1.push2his.eastmoney.com{path}",
            f"https://48.push2his.eastmoney.com{path}",
            f"https://67.push2his.eastmoney.com{path}",
        ]
        last_error = None
        for trust_env in (False, True):
            session = requests.Session()
            session.trust_env = trust_env
            try:
                session.get("https://quote.eastmoney.com/", headers=headers, timeout=10)
            except RequestException:
                pass
            for url in urls:
                request_headers = dict(headers)
                request_headers["Host"] = url.split("//", 1)[1].split("/", 1)[0]
                for _ in range(2):
                    try:
                        response = session.get(url, params=params, headers=request_headers, timeout=15)
                        response.raise_for_status()
                        return response.json()
                    except RequestException as err:
                        last_error = err
            session.close()
        raise last_error

    @staticmethod
    def __format_date(date_value, intraday, is_start):
        if date_value is None:
            if intraday:
                return "1979-09-01 09:32:00" if is_start else "2222-01-01 09:32:00"
            return "19900101" if is_start else "20991231"

        date_text = str(date_value)
        if not intraday:
            return date_text[:10].replace("-", "")

        if " " in date_text:
            return date_text
        return f"{date_text} {'09:30:00' if is_start else '15:00:00'}"

    @staticmethod
    def __parse_market(code):
        code = code.strip()
        if len(code) == 9 and code[6] == "." and code[7:].upper() in ("SH", "SZ", "BJ"):
            return code[7:].upper()
        if len(code) == 8 and code[:2].lower() in ("sh", "sz", "bj"):
            return code[:2].upper()
        return None
