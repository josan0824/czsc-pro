import types
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd

from Common.CEnum import KL_TYPE
from DataAPI import tdx_vipdoc_io as io
from DataAPI.TdxHistoryAPI import TDX_HISTORY_DIR_ENV
from DataAPI.TqSdkAPI import CTqSdk, TQSDK_KLINE_DURATIONS, load_tqsdk_credentials, normalize_tqsdk_symbol
from DataAPI.TqSdkAPI import _latest_a_share_minute_ceiling
from web_server import QUICK_ITEMS_BY_SOURCE, TQSDK_DATA_SOURCE, index_html, parse_source


def make_minute_df(rows):
    return pd.DataFrame(rows, columns=io.COLUMNS)


def write_exported_1min_csv(root: Path, code: str, rows: list[list]):
    first_time = pd.Timestamp(rows[0][0])
    path = (
        root
        / "vipdoc"
        / f"{first_time:%Y-%m}_1min"
        / f"{first_time:%Y%m%d}_1min"
        / f"{code.lower()}.csv"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        rows,
        columns=["datetime", "open", "high", "low", "close", "amount", "volume"],
    ).to_csv(path, index=False, encoding="utf-8-sig")


def make_fake_tqsdk_module():
    module = types.ModuleType("tqsdk")
    module.tafunc = types.SimpleNamespace(
        time_to_datetime=lambda value: pd.to_datetime(value, unit="ns", utc=True).tz_convert("Asia/Shanghai")
    )
    return module


def timestamp_ns(local_time: str) -> int:
    return pd.Timestamp(local_time, tz="Asia/Shanghai").value


class TqSdkApiTest(unittest.TestCase):
    def test_normalizes_all_supported_index_codes(self):
        self.assertEqual("SSE.000016", normalize_tqsdk_symbol("SH000016"))
        self.assertEqual("SSE.000300", normalize_tqsdk_symbol("000300.SH"))
        self.assertEqual("SSE.000852", normalize_tqsdk_symbol("SSE.000852"))
        self.assertEqual("SSE.000905", normalize_tqsdk_symbol("000905"))

    def test_rejects_unsupported_symbols(self):
        with self.assertRaisesRegex(ValueError, "仅支持"):
            normalize_tqsdk_symbol("SH000001")

    def test_supports_chart_timeframes(self):
        self.assertEqual(60, TQSDK_KLINE_DURATIONS[KL_TYPE.K_1M])
        self.assertEqual(24 * 60 * 60, TQSDK_KLINE_DURATIONS[KL_TYPE.K_DAY])

    def test_loads_credentials_from_project_config(self):
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "tqsdk.config"
            config_path.write_text("# test credentials\nTQ_ACCOUNT=config-account\nTQ_PASSWORD=config-password\n")
            with patch("DataAPI.TqSdkAPI.TQSDK_CONFIG_PATH", config_path), patch.dict("os.environ", {}, clear=True):
                self.assertEqual(("config-account", "config-password"), load_tqsdk_credentials())

    def test_environment_credentials_override_project_config(self):
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "tqsdk.config"
            config_path.write_text("TQ_ACCOUNT=config-account\nTQ_PASSWORD=config-password\n")
            with patch("DataAPI.TqSdkAPI.TQSDK_CONFIG_PATH", config_path), patch.dict(
                "os.environ", {"TQ_ACCOUNT": "env-account", "TQ_PASSWORD": "env-password"}, clear=True
            ):
                self.assertEqual(("env-account", "env-password"), load_tqsdk_credentials())

    def test_web_source_and_quick_codes(self):
        self.assertEqual(TQSDK_DATA_SOURCE, parse_source("tqsdk"))
        self.assertEqual(TQSDK_DATA_SOURCE, parse_source("天勤"))
        self.assertEqual(
            {"SSE.000016", "SSE.000300", "SSE.000852", "SSE.000905"},
            {item["code"] for item in QUICK_ITEMS_BY_SOURCE["tqsdk"]},
        )
        self.assertEqual(4, len(QUICK_ITEMS_BY_SOURCE["default"]))

    def test_index_page_includes_tqsdk_option_and_source_specific_items(self):
        page = index_html("127.0.0.1", 8000)
        self.assertIn('option value="tqsdk" selected>天勤', page)
        self.assertIn('option value="30" selected>30天', page)
        self.assertIn('value="SSE.000905"', page)
        self.assertIn('"tqsdk": [{"code": "SSE.000905"', page)
        self.assertNotIn('"code": "688111.SH"', page)

    def test_converts_tqsdk_kline_rows_to_chart_units(self):
        class FakeApi:
            def __init__(self):
                self.calls = []

            def get_kline_serial(self, symbol, duration_seconds, data_length):
                self.calls.append((symbol, duration_seconds, data_length))
                return pd.DataFrame([{
                    "datetime": 1785337860000000000,
                    "open": 5200.0,
                    "high": 5210.0,
                    "low": 5190.0,
                    "close": 5205.0,
                    "volume": 123.0,
                }])

        previous_api = CTqSdk.api
        fake_api = FakeApi()
        CTqSdk.api = fake_api
        try:
            with TemporaryDirectory() as temp_dir, patch.dict(
                "os.environ", {TDX_HISTORY_DIR_ENV: temp_dir}
            ), patch.dict("sys.modules", {"tqsdk": make_fake_tqsdk_module()}):
                bars = list(CTqSdk("SSE.000905", KL_TYPE.K_1M).get_kl_data())
        finally:
            CTqSdk.api = previous_api

        self.assertEqual([("SSE.000905", 60, 10000)], fake_api.calls)
        self.assertEqual(1, len(bars))
        self.assertEqual("2026/07/29 23:11", bars[0].time.to_str())
        self.assertEqual(5200.0, bars[0].open)
        self.assertEqual(5210.0, bars[0].high)
        self.assertEqual(5190.0, bars[0].low)
        self.assertEqual(5205.0, bars[0].close)

    def test_filters_tz_aware_tqsdk_rows_with_naive_date_bounds(self):
        class FakeApi:
            def get_kline_serial(self, symbol, duration_seconds, data_length):
                return pd.DataFrame([
                    {
                        "datetime": timestamp_ns("2026-03-31 15:00:00"),
                        "open": 1.0,
                        "high": 1.0,
                        "low": 1.0,
                        "close": 1.0,
                        "volume": 1.0,
                    },
                    {
                        "datetime": timestamp_ns("2026-04-01 09:31:00"),
                        "open": 2.0,
                        "high": 2.0,
                        "low": 2.0,
                        "close": 2.0,
                        "volume": 2.0,
                    },
                    {
                        "datetime": timestamp_ns("2026-04-02 00:00:00"),
                        "open": 3.0,
                        "high": 3.0,
                        "low": 3.0,
                        "close": 3.0,
                        "volume": 3.0,
                    },
                ])

        previous_api = CTqSdk.api
        CTqSdk.api = FakeApi()
        try:
            with TemporaryDirectory() as temp_dir, patch.dict(
                "os.environ", {TDX_HISTORY_DIR_ENV: temp_dir}
            ), patch.dict("sys.modules", {"tqsdk": make_fake_tqsdk_module()}):
                bars = list(
                    CTqSdk(
                        "SSE.000905",
                        KL_TYPE.K_1M,
                        begin_date="2026-04-01",
                        end_date="2026-04-01",
                    ).get_kl_data()
                )
        finally:
            CTqSdk.api = previous_api

        self.assertEqual(1, len(bars))
        self.assertEqual("2026/04/01 09:31", bars[0].time.to_str())
        self.assertEqual(2.0, bars[0].open)

    def test_reads_local_tdx_cache_before_tqsdk_api(self):
        class FakeApi:
            def __init__(self):
                self.calls = []

            def get_kline_serial(self, symbol, duration_seconds, data_length):
                self.calls.append((symbol, duration_seconds, data_length))
                raise AssertionError("local cache should satisfy this request")

        with TemporaryDirectory() as temp_dir, patch.dict("os.environ", {TDX_HISTORY_DIR_ENV: temp_dir}):
            root = Path(temp_dir)
            write_exported_1min_csv(
                root,
                "sh000905",
                [
                    [pd.Timestamp("2026-07-01 09:31"), 10.0, 10.5, 9.8, 10.2, 100.0, 10],
                    [pd.Timestamp("2026-07-01 09:32"), 10.2, 10.9, 10.1, 10.8, 200.0, 20],
                ],
            )

            previous_api = CTqSdk.api
            fake_api = FakeApi()
            CTqSdk.api = fake_api
            try:
                bars = list(
                    CTqSdk(
                        "SSE.000905",
                        KL_TYPE.K_1M,
                        begin_date="2026-07-01",
                        end_date="2026-07-01 09:32",
                    ).get_kl_data()
                )
            finally:
                CTqSdk.api = previous_api

        self.assertEqual([], fake_api.calls)
        self.assertEqual(["2026/07/01 09:31", "2026/07/01 09:32"], [bar.time.to_str() for bar in bars])
        self.assertAlmostEqual(10.8, bars[-1].close, places=4)

    def test_bare_000300_csv_is_standardized_to_prefixed_csv_without_fetch(self):
        class FakeApi:
            def __init__(self):
                self.calls = []

            def get_kline_serial(self, symbol, duration_seconds, data_length):
                self.calls.append((symbol, duration_seconds, data_length))
                raise AssertionError("bare local csv should satisfy this request")

        with TemporaryDirectory() as temp_dir, patch.dict("os.environ", {TDX_HISTORY_DIR_ENV: temp_dir}):
            root = Path(temp_dir)
            write_exported_1min_csv(
                root,
                "000300",
                [[pd.Timestamp("2026-07-01 09:31"), 10.0, 10.5, 9.8, 10.2, 100.0, 10]],
            )

            previous_api = CTqSdk.api
            fake_api = FakeApi()
            CTqSdk.api = fake_api
            try:
                bars = list(
                    CTqSdk(
                        "SSE.000300",
                        KL_TYPE.K_1M,
                        begin_date="2026-07-01",
                        end_date="2026-07-01 09:31",
                    ).get_kl_data()
                )
            finally:
                CTqSdk.api = previous_api

            prefixed_csv_exists = (root / "vipdoc/2026-07_1min/20260701_1min/sh000300.csv").is_file()

        self.assertEqual([], fake_api.calls)
        self.assertEqual("2026/07/01 09:31", bars[0].time.to_str())
        self.assertTrue(prefixed_csv_exists)

    def test_legacy_lc1_does_not_block_tqsdk_csv_write(self):
        class FakeApi:
            def __init__(self):
                self.calls = []

            def get_kline_serial(self, symbol, duration_seconds, data_length):
                self.calls.append((symbol, duration_seconds, data_length))
                return pd.DataFrame([{
                    "datetime": timestamp_ns("2026-07-01 09:31:00"),
                    "open": 10.0,
                    "high": 10.5,
                    "low": 9.8,
                    "close": 10.2,
                    "volume": 10.0,
                }])

        with TemporaryDirectory() as temp_dir, patch.dict(
            "os.environ", {TDX_HISTORY_DIR_ENV: temp_dir}
        ), patch.dict("sys.modules", {"tqsdk": make_fake_tqsdk_module()}):
            root = Path(temp_dir)
            io.write_minute(
                root / "vipdoc/sh/minline/sh000300.lc1",
                make_minute_df([[pd.Timestamp("2026-07-01 09:31"), 1.0, 1.0, 1.0, 1.0, 0.0, 1]]),
            )

            previous_api = CTqSdk.api
            fake_api = FakeApi()
            CTqSdk.api = fake_api
            try:
                bars = list(
                    CTqSdk(
                        "SSE.000300",
                        KL_TYPE.K_1M,
                        begin_date="2026-07-01",
                        end_date="2026-07-01 09:31",
                    ).get_kl_data()
                )
            finally:
                CTqSdk.api = previous_api

            csv_path = root / "vipdoc/2026-07_1min/20260701_1min/sh000300.csv"
            csv_exists = csv_path.is_file()
            cached = io.read_exported_minute_csv(root / "vipdoc", "sh000300")

        self.assertEqual([("SSE.000300", 60, 10000)], fake_api.calls)
        self.assertTrue(csv_exists)
        self.assertEqual("2026/07/01 09:31", bars[0].time.to_str())
        self.assertAlmostEqual(10.2, cached.iloc[0]["close"], places=4)

    def test_after_close_uses_local_1500_csv_without_tqsdk_fetch(self):
        self.assertEqual(
            pd.Timestamp("2026-07-30 14:59"),
            _latest_a_share_minute_ceiling(pd.Timestamp("2026-07-30 16:15")),
        )
        self.assertEqual(
            pd.Timestamp("2026-07-29 14:59"),
            _latest_a_share_minute_ceiling(pd.Timestamp("2026-07-30 08:45")),
        )
        self.assertEqual(
            pd.Timestamp("2026-07-31 14:59"),
            _latest_a_share_minute_ceiling(pd.Timestamp("2026-08-01 10:00")),
        )

        class FakeApi:
            def __init__(self):
                self.calls = []

            def get_kline_serial(self, symbol, duration_seconds, data_length):
                self.calls.append((symbol, duration_seconds, data_length))
                raise AssertionError("15:00 local bar should satisfy an after-close request")

        with TemporaryDirectory() as temp_dir, patch.dict("os.environ", {TDX_HISTORY_DIR_ENV: temp_dir}):
            root = Path(temp_dir)
            write_exported_1min_csv(
                root,
                "sh000905",
                [[pd.Timestamp("2026-07-30 14:59"), 10.0, 10.5, 9.8, 10.2, 100.0, 10]],
            )

            previous_api = CTqSdk.api
            fake_api = FakeApi()
            CTqSdk.api = fake_api
            try:
                with patch("DataAPI.TqSdkAPI.pd.Timestamp.now", return_value=pd.Timestamp("2026-07-30 16:15")):
                    bars = list(CTqSdk("SSE.000905", KL_TYPE.K_1M, begin_date="2026-07-30").get_kl_data())
            finally:
                CTqSdk.api = previous_api

        self.assertEqual([], fake_api.calls)
        self.assertEqual(1, len(bars))
        self.assertEqual("2026/07/30 14:59", bars[0].time.to_str())

    def test_fetches_tqsdk_rows_and_writes_tdx_cache(self):
        class FakeApi:
            def __init__(self):
                self.calls = []

            def get_kline_serial(self, symbol, duration_seconds, data_length):
                self.calls.append((symbol, duration_seconds, data_length))
                return pd.DataFrame([
                    {
                        "datetime": timestamp_ns("2026-07-01 09:31:00"),
                        "open": 10.0,
                        "high": 10.1,
                        "low": 9.8,
                        "close": 10.2,
                        "volume": 10.0,
                    },
                    {
                        "datetime": timestamp_ns("2026-07-01 09:32:00"),
                        "open": 10.2,
                        "high": 10.9,
                        "low": 10.1,
                        "close": 10.8,
                        "volume": 20.0,
                    },
                ])

        with TemporaryDirectory() as temp_dir, patch.dict(
            "os.environ", {TDX_HISTORY_DIR_ENV: temp_dir}
        ), patch.dict("sys.modules", {"tqsdk": make_fake_tqsdk_module()}):
            previous_api = CTqSdk.api
            fake_api = FakeApi()
            CTqSdk.api = fake_api
            try:
                bars = list(
                    CTqSdk(
                        "SSE.000905",
                        KL_TYPE.K_1M,
                        begin_date="2026-07-01",
                        end_date="2026-07-01 09:32",
                    ).get_kl_data()
                )
            finally:
                CTqSdk.api = previous_api

            csv_path = Path(temp_dir) / "vipdoc/2026-07_1min/20260701_1min/sh000905.csv"
            csv_exists = csv_path.is_file()
            cached = io.read_exported_minute_csv(Path(temp_dir) / "vipdoc", "sh000905")

        self.assertEqual([("SSE.000905", 60, 10000)], fake_api.calls)
        self.assertEqual(["2026/07/01 09:31", "2026/07/01 09:32"], [bar.time.to_str() for bar in bars])
        self.assertAlmostEqual(10.2, bars[0].high, places=4)
        self.assertTrue(csv_exists)
        self.assertEqual(2, len(cached))
        self.assertAlmostEqual(10.2, cached.iloc[0]["high"], places=4)
        self.assertEqual(pd.Timestamp("2026-07-01 09:32"), cached.iloc[-1]["datetime"])
        self.assertAlmostEqual(10.8, cached.iloc[-1]["close"], places=4)

    def test_exported_snapshot_does_not_block_tqsdk_latest_fetch(self):
        class FakeApi:
            def __init__(self):
                self.calls = []

            def get_kline_serial(self, symbol, duration_seconds, data_length):
                self.calls.append((symbol, duration_seconds, data_length))
                return pd.DataFrame([{
                    "datetime": timestamp_ns("2026-07-01 09:31:00"),
                    "open": 11.0,
                    "high": 11.5,
                    "low": 10.8,
                    "close": 11.2,
                    "volume": 30.0,
                }])

        with TemporaryDirectory() as temp_dir, patch.dict(
            "os.environ", {TDX_HISTORY_DIR_ENV: temp_dir}
        ), patch.dict("sys.modules", {"tqsdk": make_fake_tqsdk_module()}):
            root = Path(temp_dir)
            write_exported_1min_csv(
                root,
                "sh000905",
                [[pd.Timestamp("2026-04-28 15:00"), 10.0, 10.5, 9.8, 10.2, 100.0, 10]],
            )

            previous_api = CTqSdk.api
            fake_api = FakeApi()
            CTqSdk.api = fake_api
            try:
                bars = list(
                    CTqSdk(
                        "SSE.000905",
                        KL_TYPE.K_1M,
                        begin_date="2026-04-28",
                        end_date="2026-07-01 09:31",
                    ).get_kl_data()
                )
            finally:
                CTqSdk.api = previous_api

            cached = io.read_exported_minute_csv(root / "vipdoc", "sh000905")

        self.assertEqual([("SSE.000905", 60, 10000)], fake_api.calls)
        self.assertEqual("2026/07/01 09:31", bars[-1].time.to_str())
        self.assertEqual(2, len(cached))
        self.assertEqual(pd.Timestamp("2026-04-28 15:00"), cached.iloc[0]["datetime"])
        self.assertEqual(pd.Timestamp("2026-07-01 09:31"), cached.iloc[-1]["datetime"])

    def test_empty_tqsdk_serial_is_reported_as_no_data(self):
        class FakeApi:
            def get_kline_serial(self, symbol, duration_seconds, data_length):
                return pd.DataFrame([{
                    "datetime": float("nan"),
                    "open": float("nan"),
                    "high": float("nan"),
                    "low": float("nan"),
                    "close": float("nan"),
                    "volume": float("nan"),
                }])

        previous_api = CTqSdk.api
        CTqSdk.api = FakeApi()
        try:
            with TemporaryDirectory() as temp_dir, patch.dict(
                "os.environ", {TDX_HISTORY_DIR_ENV: temp_dir}
            ), patch.dict("sys.modules", {"tqsdk": make_fake_tqsdk_module()}):
                with self.assertRaisesRegex(RuntimeError, "未返回"):
                    list(CTqSdk("SSE.000905", KL_TYPE.K_1M).get_kl_data())
        finally:
            CTqSdk.api = previous_api


if __name__ == "__main__":
    unittest.main()
