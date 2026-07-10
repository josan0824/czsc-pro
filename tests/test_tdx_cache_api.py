import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from Common.CEnum import KL_TYPE
from Common.CEnum import DATA_FIELD
from Common.CTime import CTime
from DataAPI.TdxCacheAPI import CTdxCache
from DataAPI.TdxHistoryAPI import TDX_HISTORY_DIR_ENV
from DataAPI import tdx_vipdoc_io as io


def _min_df(rows):
    return pd.DataFrame(rows, columns=["datetime", "open", "high", "low", "close", "amount", "volume"])


class TdxCacheLocalFirstTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        (self.root / "vipdoc/sh/minline").mkdir(parents=True)
        (self.root / "vipdoc/sh/lday").mkdir(parents=True)
        self.env_patch = patch.dict(os.environ, {TDX_HISTORY_DIR_ENV: str(self.root)})
        self.env_patch.start()

    def tearDown(self):
        self.env_patch.stop()
        self.temp_dir.cleanup()

    def test_local_covers_range_no_network(self):
        # 本地 1m 已覆盖请求范围 → 不应联网
        io.write_minute(
            self.root / "vipdoc/sh/minline/sh000001.lc1",
            _min_df([
                [pd.Timestamp("2026-07-01 09:31"), 10.0, 10.5, 9.8, 10.2, 100.0, 10],
                [pd.Timestamp("2026-07-01 09:45"), 10.2, 11.0, 10.0, 10.8, 200.0, 20],
            ]),
        )
        with patch("DataAPI.TdxCacheAPI.CMootdx") as mootdx_cls:
            bars = list(CTdxCache("000001.SH", KL_TYPE.K_1M, "2026-07-01", "2026-07-01 09:45").get_kl_data())
            self.assertFalse(mootdx_cls.called, "本地覆盖范围时不应实例化 CMootdx")
        self.assertEqual(2, len(bars))
        self.assertEqual("2026/07/01 09:31", bars[0].time.to_str())

    def test_local_day_covers_range_no_network(self):
        io.write_day(
            self.root / "vipdoc/sh/lday/sh000001.day",
            _min_df([
                [pd.Timestamp("2026-07-01"), 35.0, 35.5, 34.5, 35.2, 100.0, 1000.0],
                [pd.Timestamp("2026-07-02"), 35.2, 36.0, 35.0, 35.8, 200.0, 2000.0],
            ]),
            "SH_INDEX",
        )
        with patch("DataAPI.TdxCacheAPI.CMootdx") as mootdx_cls:
            bars = list(CTdxCache("SH000001", KL_TYPE.K_DAY, "2026-07-01", "2026-07-02").get_kl_data())
            self.assertFalse(mootdx_cls.called)
        self.assertEqual(2, len(bars))
        self.assertAlmostEqual(35.8, bars[-1].close, places=4)


class _FakeKLU:
    def __init__(self, dt, close):
        self.time = dt
        self.open = close
        self.high = close + 0.1
        self.low = close - 0.1
        self.close = close
        self.trade_info = type(
            "_TI", (), {"metric": {DATA_FIELD.FIELD_TURNOVER: 100.0, DATA_FIELD.FIELD_VOLUME: 10.0}}
        )()


class TdxCacheIncrementalTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        (self.root / "vipdoc/sh/minline").mkdir(parents=True)
        self.env_patch = patch.dict(os.environ, {TDX_HISTORY_DIR_ENV: str(self.root)})
        self.env_patch.start()

    def tearDown(self):
        self.env_patch.stop()
        self.temp_dir.cleanup()

    def test_fetches_gap_and_writes_back(self):
        # 本地有 07-01 09:31 一根
        io.write_minute(
            self.root / "vipdoc/sh/minline/sh000001.lc1",
            _min_df([[pd.Timestamp("2026-07-01 09:31"), 10.0, 10.5, 9.8, 10.2, 100.0, 10]]),
        )
        fake_units = [
            _FakeKLU(CTime(2026, 7, 1, 9, 31), 10.9),  # 重拉最后一根（修正 close=10.9）
            _FakeKLU(CTime(2026, 7, 1, 9, 32), 10.4),
        ]

        inst = type("M", (), {})()  # fake CMootdx instance
        inst.get_kl_data = lambda *a, **k: iter(fake_units)
        inst.do_init = lambda *a, **k: None
        inst.do_close = lambda *a, **k: None

        with patch("DataAPI.TdxCacheAPI.CMootdx", return_value=inst) as mootdx_cls:
            bars = list(CTdxCache("000001.SH", KL_TYPE.K_1M, "2026-07-01", "2026-07-01 09:32").get_kl_data())
            self.assertTrue(mootdx_cls.called)
            # 传给 CMootdx 的 begin_date 应为本地最后一根时间（增量）
            _, kwargs = mootdx_cls.call_args
            self.assertEqual(pd.Timestamp("2026-07-01 09:31"), pd.Timestamp(kwargs["begin_date"]))

        self.assertEqual(2, len(bars))
        self.assertAlmostEqual(10.9, bars[0].close, places=4)  # 新值胜出
        self.assertAlmostEqual(10.4, bars[1].close, places=4)
        # 写回后本地文件含两根且 09:31 为新值
        decoded = io.read_minute(self.root / "vipdoc/sh/minline/sh000001.lc1")
        self.assertEqual(2, len(decoded))
        self.assertAlmostEqual(10.9, decoded.iloc[0]["close"], places=4)


if __name__ == "__main__":
    unittest.main()
