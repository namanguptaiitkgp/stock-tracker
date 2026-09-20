"""One-shot backfill: refresh stock_fundamentals.sector / .industry from
Screener.in for every row that wasn't last written by Screener.

Cleans up the corpus after P1.3 (Screener.in sector extraction) lands so
holdings that previously had yfinance-sourced or null sectors get
upgraded to the more accurate Screener-derived taxonomy. Re-running is
safe (idempotent) — rows where Screener confirms the existing value are
left untouched.

Usage:
    docker exec algo-trader-backend-1 python -m scripts.renormalize_sectors

    # Dry run — log what would change but don't write:
    docker exec algo-trader-backend-1 python -m scripts.renormalize_sectors --dry-run

    # Limit to specific symbols (testing):
    docker exec algo-trader-backend-1 python -m scripts.renormalize_sectors --symbols TCS,INFY,RELIANCE

Output: structured per-row log + an end-of-run summary
    (N updated, M unchanged, K had no Screener data, T errored).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from sqlalchemy import select

from app.db.session import async_session
from app.models.fundamentals import StockFundamentals
from app.services.screener_fetcher import fetch_fundamentals as screener_fetch
from app.services.screener_presets import normalize_sector

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("renormalize_sectors")


async def renormalize(
    dry_run: bool = False,
    symbols: list[str] | None = None,
) -> dict[str, int]:
    """Walk stock_fundamentals, refresh sectors from Screener where the
    current value isn't already Screener-sourced. Returns a counts dict
    suitable for the summary print."""

    counts = {"updated": 0, "unchanged": 0, "no_data": 0, "errored": 0}

    async with async_session() as db:
        q = select(StockFundamentals)
        if symbols:
            q = q.where(StockFundamentals.symbol.in_([s.upper() for s in symbols]))
        rows = (await db.execute(q)).scalars().all()
        logger.info("renormalize: %d rows in scope", len(rows))

        for sf in rows:
            existing_source = (sf.data_sources or {}).get("sector")
            # Skip rows that are already Screener-sourced AND have a non-null
            # sector — they're as good as we can get without re-fetching.
            if existing_source == "screener" and sf.sector:
                counts["unchanged"] += 1
                continue

            try:
                sc = await screener_fetch(sf.symbol)
            except Exception as e:
                logger.warning("%s: screener fetch failed (%s)", sf.symbol, e)
                counts["errored"] += 1
                continue

            if not sc:
                logger.info("%s: no screener payload", sf.symbol)
                counts["no_data"] += 1
                continue

            new_sector = sc.get("sector")
            new_industry = sc.get("industry")

            if not new_sector and not new_industry:
                logger.info("%s: screener returned no sector or industry", sf.symbol)
                counts["no_data"] += 1
                continue

            # Normalize defensively even though screener_fetcher already
            # routes sector through normalize_sector() at extraction time.
            new_sector_norm = normalize_sector(new_sector) if new_sector else None

            sector_changed = new_sector_norm and new_sector_norm != sf.sector
            industry_changed = new_industry and new_industry != sf.industry

            if not sector_changed and not industry_changed:
                # Screener confirms current values — bump provenance to
                # 'screener' without changing the value itself.
                logger.info(
                    "%s: sector=%r industry=%r confirmed by screener",
                    sf.symbol, sf.sector, sf.industry,
                )
                if not dry_run:
                    sources = dict(sf.data_sources or {})
                    sources["sector"] = "screener"
                    sources["industry"] = "screener"
                    sf.data_sources = sources
                counts["unchanged"] += 1
                continue

            old_sector = sf.sector
            old_industry = sf.industry
            logger.info(
                "%s: sector %r -> %r,  industry %r -> %r%s",
                sf.symbol,
                old_sector,
                new_sector_norm if sector_changed else old_sector,
                old_industry,
                new_industry if industry_changed else old_industry,
                " (dry-run)" if dry_run else "",
            )

            if not dry_run:
                sources = dict(sf.data_sources or {})
                if sector_changed:
                    sf.sector = new_sector_norm
                    sources["sector"] = "screener"
                if industry_changed:
                    sf.industry = new_industry
                    sources["industry"] = "screener"
                sf.data_sources = sources

            counts["updated"] += 1

        if not dry_run:
            await db.commit()
            logger.info("renormalize: committed")

    return counts


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--dry-run", action="store_true",
        help="Log what would change but don't write",
    )
    p.add_argument(
        "--symbols",
        help="Comma-separated list of symbols to limit the run (testing)",
    )
    args = p.parse_args()

    syms = [s.strip().upper() for s in args.symbols.split(",")] if args.symbols else None
    counts = asyncio.run(renormalize(dry_run=args.dry_run, symbols=syms))

    print()
    print("─" * 50)
    print(f"  updated:   {counts['updated']}")
    print(f"  unchanged: {counts['unchanged']}")
    print(f"  no_data:   {counts['no_data']}")
    print(f"  errored:   {counts['errored']}")
    print("─" * 50)
    if args.dry_run:
        print("DRY RUN — no rows were written")

    return 0


if __name__ == "__main__":
    sys.exit(main())
