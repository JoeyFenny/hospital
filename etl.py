from __future__ import annotations

import asyncio
import csv
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set

import pandas as pd
import pgeocode
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.models import Procedure, Provider, Rating
from app.database import Base

# Alembic programmatic API
from alembic.config import Config as AlembicConfig
from alembic import command as alembic_command


CSV_PATH = Path(__file__).parent / "sample_prices_ny.csv"


def clean_money(value: Any) -> float | None:
    if value is None:
        return None
    s = str(value)
    if s.strip() == "" or s.strip().lower() == "nan":
        return None
    s = re.sub(r"[^0-9.\-]", "", s)
    try:
        return float(s)
    except Exception:
        return None


def stable_rating_from_provider_id(provider_id: str) -> int:
    # Deterministic pseudo-random rating in [1, 10]
    h = 0
    for ch in provider_id:
        h = (h * 131 + ord(ch)) % 1000003
    return (h % 10) + 1


async def apply_migrations(engine: AsyncEngine):
    # Decide whether to upgrade or stamp based on existing schema
    async with engine.begin() as conn:
        has_alembic_version = False
        has_providers_table = False
        # Use to_regclass which returns NULL if relation doesn't exist
        res = await conn.exec_driver_sql("SELECT to_regclass('public.alembic_version')")
        row = res.fetchone()
        has_alembic_version = bool(row and row[0])

        res2 = await conn.exec_driver_sql("SELECT to_regclass('public.providers')")
        row2 = res2.fetchone()
        has_providers_table = bool(row2 and row2[0])

    # Configure Alembic
    proj_root = Path(__file__).parent
    alembic_ini = proj_root / "alembic.ini"
    cfg = AlembicConfig(str(alembic_ini))
    cfg.set_main_option("script_location", "alembic")
    cfg.set_main_option("sqlalchemy.url", settings.database_url)

    if has_alembic_version:
        # Normal upgrade path
        await asyncio.to_thread(alembic_command.upgrade, cfg, "head")
    else:
        if has_providers_table:
            # Schema already applied from raw SQL; record current head
            await asyncio.to_thread(alembic_command.stamp, cfg, "head")
        else:
            # Fresh DB; apply migrations
            await asyncio.to_thread(alembic_command.upgrade, cfg, "head")


async def load_csv(engine: AsyncEngine):
    nomi = pgeocode.Nominatim("us")
    provider_seen: Set[str] = set()

    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        # Stream in chunks to reduce memory
        chunks = pd.read_csv(CSV_PATH, dtype=str, chunksize=5000, encoding="latin1", on_bad_lines="skip")
        for chunk in chunks:
            # Normalize columns
            chunk = chunk.rename(columns={c: c.strip() for c in chunk.columns})
            # Fill NaNs with None-like
            chunk = chunk.where(pd.notnull(chunk), None)

            providers_to_upsert: List[Dict[str, Any]] = []
            procedures_to_upsert: List[Dict[str, Any]] = []
            ratings_to_upsert: List[Dict[str, Any]] = []

            for _, row in chunk.iterrows():
                # Map CSV column names to our schema
                prov_id = (row.get("Rndrng_Prvdr_CCN") or "").strip()
                if not prov_id:
                    continue
                if prov_id not in provider_seen:
                    provider_seen.add(prov_id)
                    zip_code = (row.get("Rndrng_Prvdr_Zip5") or "").strip()
                    rec = nomi.query_postal_code(zip_code) if zip_code else None
                    lat = float(rec.latitude) if rec is not None and pd.notna(rec.latitude) else None
                    lon = float(rec.longitude) if rec is not None and pd.notna(rec.longitude) else None
                    providers_to_upsert.append(
                        {
                            "provider_id": prov_id,
                            "name": (row.get("Rndrng_Prvdr_Org_Name") or "").strip(),
                            "city": (row.get("Rndrng_Prvdr_City") or None),
                            "state": (row.get("Rndrng_Prvdr_State_Abrvtn") or None),
                            "zip_code": zip_code or None,
                            "latitude": lat,
                            "longitude": lon,
                        }
                    )
                    ratings_to_upsert.append({"provider_id": prov_id, "rating": stable_rating_from_provider_id(prov_id)})

                drg_code = (row.get("DRG_Cd") or "").strip()
                drg_desc = (row.get("DRG_Desc") or "").strip()
                ms_drg_def = (f"{drg_code} - {drg_desc}").strip(" -") if (drg_code or drg_desc) else ""
                if not ms_drg_def:
                    continue
                procedures_to_upsert.append(
                    {
                        "provider_id": prov_id,
                        "ms_drg_definition": ms_drg_def,
                        "total_discharges": int((row.get("Tot_Dschrgs") or 0)) or None,
                        "average_covered_charges": clean_money(row.get("Avg_Submtd_Cvrd_Chrg")),
                        "average_total_payments": clean_money(row.get("Avg_Tot_Pymt_Amt")),
                        "average_medicare_payments": clean_money(row.get("Avg_Mdcr_Pymt_Amt")),
                    }
                )

            # Bulk upsert providers
            if providers_to_upsert:
                stmt = pg_insert(Provider.__table__).values(providers_to_upsert)
                stmt = stmt.on_conflict_do_nothing(index_elements=[Provider.provider_id])
                await session.execute(stmt)

            # Bulk upsert ratings
            if ratings_to_upsert:
                stmt = pg_insert(Rating.__table__).values(ratings_to_upsert)
                stmt = stmt.on_conflict_do_update(
                    index_elements=[Rating.provider_id], set_={"rating": stmt.excluded.rating}
                )
                await session.execute(stmt)

            # Bulk upsert procedures
            if procedures_to_upsert:
                stmt = pg_insert(Procedure.__table__).values(procedures_to_upsert)
                stmt = stmt.on_conflict_do_update(
                    constraint="uq_procedure_per_provider_drg",
                    set_={
                        "total_discharges": stmt.excluded.total_discharges,
                        "average_covered_charges": stmt.excluded.average_covered_charges,
                        "average_total_payments": stmt.excluded.average_total_payments,
                        "average_medicare_payments": stmt.excluded.average_medicare_payments,
                    },
                )
                await session.execute(stmt)

            await session.commit()


async def main():
    print(f"Using DATABASE_URL={settings.database_url}")
    if not CSV_PATH.exists():
        raise SystemExit(f"CSV file not found at {CSV_PATH}")
    engine = create_async_engine(settings.database_url, pool_pre_ping=True, future=True)
    await apply_migrations(engine)
    await load_csv(engine)
    await engine.dispose()
    print("ETL complete.")


if __name__ == "__main__":
    asyncio.run(main())

