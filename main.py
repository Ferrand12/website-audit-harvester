import argparse
import csv
import sys
from pathlib import Path

from src.exporters.export import export_csv, export_json
from src.pipeline.runner import run_pipeline
from src.scoring.rubric import print_summary
from src.utils.logging import setup_logging
from src.utils.verify import run_verify_command


def main() -> None:
    parser = argparse.ArgumentParser(description="Website Audit Harvester")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Default run command (no subcommand needed for backwards compatibility)
    parser.add_argument("--input", help="CSV file with a 'url' column")
    parser.add_argument("--output", default="out", help="Output directory")
    parser.add_argument("--strategy", default="mobile", choices=["mobile", "desktop"])
    parser.add_argument("--config", default="config/config.yaml", help="Config file")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--max-urls", type=int, default=None)
    parser.add_argument("--cache", action="store_true", default=True, help="Enable caching (default)")
    parser.add_argument("--no-cache", action="store_true", help="Disable caching")
    parser.add_argument("--cache-dir", default=None, help="Cache directory (default: out/cache)")
    parser.add_argument("--resume", action="store_true", help="Skip URLs already in leads.json")
    parser.add_argument("--force", action="store_true", help="Ignore cache and resume, re-run all")

    # Verify subcommand
    verify_parser = subparsers.add_parser("verify", help="Verify leads.json integrity")
    verify_parser.add_argument("--input", "-i", required=True, help="Path to leads.json")
    verify_parser.add_argument("--report", "-r", help="Path to save verification report")

    args = parser.parse_args()

    # Handle verify command
    if args.command == "verify":
        exit_code = run_verify_command(args.input, args.report)
        sys.exit(exit_code)

    # Handle main run command
    if not args.input:
        parser.error("--input is required for the main command")

    logger = setup_logging(args.output)

    with open(args.input, newline="") as f:
        urls = [row["url"] for row in csv.DictReader(f)]

    if args.max_urls:
        urls = urls[: args.max_urls]

    logger.info("Loaded %d URLs from %s", len(urls), args.input)

    use_cache = args.cache and not args.no_cache
    leads = run_pipeline(
        urls,
        args.strategy,
        args.concurrency,
        config_path=args.config,
        output_dir=args.output,
        use_cache=use_cache,
        cache_dir=args.cache_dir,
        resume=args.resume,
        force=args.force,
    )

    out = Path(args.output)
    export_json(leads, out / "leads.json")
    export_csv(leads, out / "leads.csv")
    logger.info("Exported results to %s", out)

    print_summary(leads)


if __name__ == "__main__":
    main()
