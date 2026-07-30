import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd

from Common.CEnum import KL_TYPE
from DataAPI.TqSdkAPI import CTqSdk, TQSDK_KLINE_DURATIONS, load_tqsdk_credentials, normalize_tqsdk_symbol
from web_server import QUICK_ITEMS_BY_SOURCE, TQSDK_DATA_SOURCE, index_html, parse_source


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
        self.assertIn('option value="tqsdk">天勤', page)
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
            with self.assertRaisesRegex(RuntimeError, "未返回"):
                list(CTqSdk("SSE.000905", KL_TYPE.K_1M).get_kl_data())
        finally:
            CTqSdk.api = previous_api


if __name__ == "__main__":
    unittest.main()
