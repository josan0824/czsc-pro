#!/usr/bin/env python3
"""Authenticate with TqSdk and verify a quote subscription."""

import argparse
import os
import time

from tqsdk import TqApi, TqAuth


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify a TqSdk quote subscription")
    parser.add_argument("--symbol", default="SHFE.ni2607")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument(
        "--watch", action="store_true", help="keep printing updates instead of exiting after one quote"
    )
    args = parser.parse_args()

    account = os.getenv("TQ_ACCOUNT")
    password = os.getenv("TQ_PASSWORD")
    if not account or not password:
        raise RuntimeError("Set TQ_ACCOUNT and TQ_PASSWORD before running this script.")

    api = TqApi(auth=TqAuth(account, password))
    try:
        quote = api.get_quote(args.symbol)
        deadline = None if args.watch else time.time() + args.timeout

        while True:
            if not api.wait_update(deadline=deadline):
                raise TimeoutError(f"No quote update for {args.symbol} within {args.timeout:g} seconds.")

            print(quote.datetime, quote.last_price, flush=True)
            if not args.watch and quote.datetime:
                return
    finally:
        api.close()


if __name__ == "__main__":
    main()
