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


if __name__ == "__main__":
    unittest.main()
