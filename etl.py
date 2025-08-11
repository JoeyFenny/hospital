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


CSV_PATH = Path(__file__).parent / "sample_prices_ny.csv"
MIGRATIONS = [Path(__file__).parent / "migrations" / "001_init.sql"]


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
    async with engine.begin() as conn:
        for sql_path in MIGRATIONS:
            sql_text = sql_path.read_text()
            # asyncpg cannot prepare multiple SQL statements at once; split and run individually
            statements = [s.strip() for s in sql_text.split(";") if s.strip()]
            for stmt in statements:
                await conn.exec_driver_sql(stmt)


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

