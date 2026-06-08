"""CLI for scraping and projecting ONPE second-round results."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from pprint import pprint

import pandas as pd

from onpe_client import BASE_URL, ONPEClient, ONPEClientError
from projection import bootstrap_projection, project_results
from scraper import scrape_geography


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Mini proyector electoral ONPE Peru 2026"
    )
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--scrape", action="store_true", help="Scrape ONPE data")
    action.add_argument("--project", action="store_true", help="Project from a CSV")

    parser.add_argument("--input-csv", help="Input CSV for --project")
    parser.add_argument(
        "--include-foreign",
        action="store_true",
        help="Include foreign geography when scraping",
    )
    parser.add_argument(
        "--max-level",
        choices=["departamento", "provincia", "distrito"],
        default="distrito",
        help="Maximum geography level to scrape",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.2,
        help="Minimum seconds between API requests",
    )
    parser.add_argument(
        "--save-raw-json",
        action="store_true",
        help="Save raw endpoint JSON responses under raw/",
    )
    parser.add_argument(
        "--base-url",
        default=BASE_URL,
        help="ONPE API base URL",
    )
    parser.add_argument(
        "--non-json-retries",
        type=int,
        default=4,
        help="Retries when ONPE returns HTML instead of JSON",
    )
    parser.add_argument(
        "--bootstrap",
        type=int,
        default=0,
        help="Run bootstrap simulations with this number of draws",
    )
    parser.add_argument(
        "--foreign-fallback",
        choices=["none", "continent", "national", "manual"],
        default="none",
        help="Fallback policy for foreign rows with zero counted actas",
    )
    parser.add_argument(
        "--foreign-continent-min-actas",
        type=int,
        default=10,
        help="Minimum counted actas required for continent fallback",
    )
    parser.add_argument(
        "--foreign-continent-min-countries",
        type=int,
        default=2,
        help="Minimum countries with data required for continent fallback",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.scrape:
        client = ONPEClient(
            base_url=args.base_url,
            sleep_seconds=args.sleep,
            save_raw_json=args.save_raw_json,
            non_json_retries=args.non_json_retries,
        )
        try:
            df = scrape_geography(
                client=client,
                include_peru=True,
                include_foreign=args.include_foreign,
                max_level=args.max_level,
                foreign_max_level="provincia",
            )
        except ONPEClientError as exc:
            raise SystemExit(f"ONPE API error: {exc}") from None
        print(f"Rows scraped: {len(df)}")
        print(f"Snapshot CSV: {df.attrs.get('output_path')}")
        return

    if args.project:
        if not args.input_csv:
            parser.error("--input-csv is required with --project")
        input_path = Path(args.input_csv)
        df = pd.read_csv(
            input_path,
            dtype={
                "departamento_ubigeo": "string",
                "provincia_ubigeo": "string",
                "distrito_ubigeo": "string",
            },
        )
        project_results(
            df,
            include_foreign=True,
            foreign_fallback=args.foreign_fallback,
            foreign_continent_min_actas=args.foreign_continent_min_actas,
            foreign_continent_min_countries=args.foreign_continent_min_countries,
        )
        if args.bootstrap:
            bootstrap = bootstrap_projection(
                df,
                n_sim=args.bootstrap,
                include_foreign=True,
                foreign_fallback=args.foreign_fallback,
                foreign_continent_min_actas=args.foreign_continent_min_actas,
                foreign_continent_min_countries=args.foreign_continent_min_countries,
            )
            print("Bootstrap summary:")
            pprint(bootstrap)


if __name__ == "__main__":
    main()
