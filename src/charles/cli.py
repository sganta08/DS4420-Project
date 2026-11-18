"""Command-line entry point for data collection and building."""

import argparse
import logging
from datetime import date, timedelta

from .build import build_all
from .http import create_session
from .noaa import fetch_noaa
from .usgs import fetch_continuous, fetch_daily, fetch_peaks


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )


def _print_check(name: str, frame) -> None:
    latest = ""
    if "time" in frame.columns and not frame.empty:
        latest = str(frame["time"].iloc[-1])
    elif "DATE" in frame.columns and not frame.empty:
        latest = str(frame["DATE"].iloc[-1])
    print(f"{name}: rows={len(frame)} columns={list(frame.columns)} latest={latest}")


def check_apis() -> None:
    """Print small API verification summaries."""
    session = create_session()
    end = date.today()
    start = end - timedelta(days=7)
    daily = fetch_daily(start.isoformat(), end.isoformat(), session)
    discharge, gage = fetch_continuous(start.isoformat(), end.isoformat(), session)
    peaks = fetch_peaks(session=session)
    noaa = fetch_noaa(start.isoformat(), end.isoformat(), session)
    _print_check("USGS daily", daily)
    _print_check("USGS continuous discharge", discharge)
    _print_check("USGS continuous gage", gage)
    _print_check("USGS peaks", peaks)
    _print_check("NOAA Logan", noaa)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Charles River flood data tools")
    parser.add_argument("-v", "--verbose", action="store_true", help="enable debug logging")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("check")

    usgs = subcommands.add_parser("usgs")
    usgs.add_argument("--start")
    usgs.add_argument("--end")
    noaa = subcommands.add_parser("noaa")
    noaa.add_argument("--start")
    noaa.add_argument("--end")
    subcommands.add_parser("build")
    subcommands.add_parser("all")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)
    if args.command == "check":
        check_apis()
    elif args.command == "usgs":
        session = create_session()
        fetch_daily(args.start or "1931-08-04", args.end, session)
        fetch_continuous(args.start or "1976-01-01", args.end, session)
        fetch_peaks(session=session)
    elif args.command == "noaa":
        fetch_noaa(args.start or "1936-01-01", args.end)
    elif args.command == "build":
        build_all()
    elif args.command == "all":
        session = create_session()
        fetch_daily(session=session)
        fetch_continuous(session=session)
        fetch_peaks(session=session)
        fetch_noaa(session=session)
        build_all()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
