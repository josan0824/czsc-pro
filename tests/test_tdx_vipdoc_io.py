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
