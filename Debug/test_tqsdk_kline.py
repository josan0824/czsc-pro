#!/usr/bin/env python3
"""Fetch and print a small K-line series from TqSdk."""

import argparse
import os
import time

from tqsdk import TqApi, TqAuth, tafunc


def format_kline_time(timestamp: int) -> str:
    return tafunc.time_to_datetime(timestamp).strftime("%Y-%m-%d %H:%M:%S")


def main() -> None:
    parser = argparse.ArgumentParser(description="Print a TqSdk K-line series")
    parser.add_argument("--symbol", default="CFFEX.IC2609")
    parser.add_argument("--duration", type=int, default=60, help="bar duration in seconds")
    parser.add_argument("--data-length", type=int, default=5, help="number of bars to request")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--print-limit", type=int, default=5, help="number of latest rows to print")
    args = parser.parse_args()

    account = os.getenv("TQ_ACCOUNT")
    password = os.getenv("TQ_PASSWORD")
    if not account or not password:
        raise RuntimeError("Set TQ_ACCOUNT and TQ_PASSWORD before running this script.")

    api = TqApi(auth=TqAuth(account, password))
    try:
        # This is one continuously updated DataFrame containing multiple bars.
        klines = api.get_kline_serial(args.symbol, args.duration, data_length=args.data_length)
        deadline = time.time() + args.timeout

        while api.wait_update(deadline=deadline):
            populated = klines.dropna(subset=["datetime"])
            if populated.empty:
                continue
            print_kline_table(populated, args)
            return

        raise TimeoutError(f"No K-line data for {args.symbol} within {args.timeout:g} seconds.")
    finally:
        api.close()


def print_kline_table(klines, args) -> None:
    populated = klines.dropna(subset=["datetime"])
    if populated.empty:
        raise RuntimeError(f"No K-line rows returned for {args.symbol}.")

    columns = ["id", "datetime", "open", "high", "low", "close", "volume"]
    optional_columns = [column for column in ("open_oi", "close_oi") if column in populated.columns]
    output = populated.loc[:, columns + optional_columns].tail(args.print_limit).copy()
    output["datetime"] = output["datetime"].map(format_kline_time)
    print(f"{args.symbol}: fetched {len(populated)} bars, {args.duration}-second duration")
    print(output.to_string(index=False))


if __name__ == "__main__":
    main()
