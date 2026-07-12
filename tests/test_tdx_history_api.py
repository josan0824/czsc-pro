import os
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from Common.CEnum import KL_TYPE
from DataAPI.TdxHistoryAPI import CTdxHistory, TDX_HISTORY_DIR_ENV, resolve_tdx_history_root
from web_server import TDX_HISTORY_DATA_SOURCE, parse_source


def _tdx_date(year: int, month: int, day: int) -> int:
    return (year - 2004) * 2048 + month * 100 + day


def _write_lc1(path: Path, rows: list[tuple]):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"".join(
        struct.pack(
            "<HHfffffII",
            _tdx_date(year, month, day),
            hour * 60 + minute,
            open_price,
            high_price,
            low_price,
            close_price,
            amount,
            volume,
            0,
        )
        for year, month, day, hour, minute, open_price, high_price, low_price, close_price, amount, volume in rows
    ))


def _write_day(path: Path, rows: list[tuple]):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"".join(
        struct.pack(
            "<IIIIIfII",
            year * 10000 + month * 100 + day,
            round(open_price * 100),
            round(high_price * 100),
            round(low_price * 100),
            round(close_price * 100),
            amount,
            volume,
            0,
        )
        for year, month, day, open_price, high_price, low_price, close_price, amount, volume in rows
    ))


class TdxHistoryApiTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.env_patch = patch.dict(os.environ, {TDX_HISTORY_DIR_ENV: str(self.root)})
        self.env_patch.start()

    def tearDown(self):
        self.env_patch.stop()
        self.temp_dir.cleanup()

    def test_reads_shanghai_lc1_and_filters_dates(self):
        _write_lc1(
            self.root / "vipdoc/sh/minline/sh000001.lc1",
            [
                (2026, 7, 1, 9, 31, 10.0, 10.5, 9.8, 10.2, 1000.0, 100),
                (2026, 7, 2, 9, 31, 11.0, 11.5, 10.8, 11.2, 1100.0, 110),
            ],
        )

        bars = list(CTdxHistory("000001.SH", KL_TYPE.K_1M, "2026-07-02", "2026-07-02").get_kl_data())

        self.assertEqual(1, len(bars))
        self.assertEqual("2026/07/02 09:31", bars[0].time.to_str())
        self.assertEqual(11.0, bars[0].open)
        self.assertAlmostEqual(11.2, bars[0].close, places=6)

    def test_resamples_without_crossing_lunch_break(self):
        _write_lc1(
            self.root / "vipdoc/sh/minline/sh000001.lc1",
            [
                (2026, 7, 1, 9, 31, 10.0, 10.5, 9.8, 10.2, 100.0, 10),
                (2026, 7, 1, 9, 45, 10.2, 11.0, 10.0, 10.8, 200.0, 20),
                (2026, 7, 1, 9, 46, 10.8, 11.2, 10.7, 11.0, 300.0, 30),
                (2026, 7, 1, 10, 0, 11.0, 11.5, 10.9, 11.4, 400.0, 40),
                (2026, 7, 1, 11, 30, 11.4, 11.8, 11.3, 11.6, 500.0, 50),
                (2026, 7, 1, 13, 1, 11.6, 12.0, 11.5, 11.9, 600.0, 60),
                (2026, 7, 1, 13, 15, 11.9, 12.2, 11.7, 12.1, 700.0, 70),
            ],
        )

        bars = list(CTdxHistory("SH000001", KL_TYPE.K_15M).get_kl_data())

        self.assertEqual(
            ["2026/07/01 09:45", "2026/07/01 10:00", "2026/07/01 11:30", "2026/07/01 13:15"],
            [bar.time.to_str() for bar in bars],
        )
        self.assertEqual(10.0, bars[0].open)
        self.assertEqual(11.0, bars[0].high)
        self.assertAlmostEqual(9.8, bars[0].low, places=6)
        self.assertAlmostEqual(10.8, bars[0].close, places=6)

    def test_reads_daily_file(self):
        _write_day(
            self.root / "vipdoc/sh/lday/sh000001.day",
            [(2026, 7, 1, 35.0, 35.5, 34.5, 35.2, 1234.5, 1000)],
        )

        bars = list(CTdxHistory("SH000001", KL_TYPE.K_DAY).get_kl_data())

        self.assertEqual(1, len(bars))
        self.assertEqual("2026/07/01", bars[0].time.to_str())
        self.assertAlmostEqual(35.2, bars[0].close, places=6)

    def test_requires_a_configured_vipdoc_root(self):
        with patch.dict(os.environ, {TDX_HISTORY_DIR_ENV: ""}):
            with self.assertRaisesRegex(RuntimeError, "TDX_HISTORY_DIR"):
                resolve_tdx_history_root()

    def test_web_source_maps_to_tdx_cache(self):
        self.assertEqual(parse_source(""), "custom:TdxCacheAPI.CTdxCache")
        self.assertEqual(parse_source("tdx_history"), "custom:TdxCacheAPI.CTdxCache")
        self.assertEqual(parse_source("通达信历史数据"), "custom:TdxCacheAPI.CTdxCache")


if __name__ == "__main__":
    unittest.main()
