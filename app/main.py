from __future__ import annotations

import math
from typing import List

import orjson
import pgeocode
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import ORJSONResponse
from sqlalchemy import and_, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .database import get_session
from .models import Procedure, Provider, Rating
from .nl import extract_params_with_openai, is_scope_relevant
from .schemas import AskRequest, AskResponse, ProviderResult


def _orjson_dumps(v, *, default):
    return orjson.dumps(v, default=default).decode()


app = FastAPI(title=settings.app_name, default_response_class=ORJSONResponse)


nomi = pgeocode.Nominatim("us")


def haversine_sql(lat_lit: float, lon_lit: float, lat_col, lon_col):
    # Haversine distance in kilometers between (lat_lit, lon_lit) and (lat_col, lon_col)
    lat1 = func.radians(literal(lat_lit))
    lon1 = func.radians(literal(lon_lit))
    lat2 = func.radians(lat_col)
    lon2 = func.radians(lon_col)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = func.pow(func.sin(dlat / 2.0), 2) + func.cos(lat1) * func.cos(lat2) * func.pow(func.sin(dlon / 2.0), 2)
    c = 2.0 * func.atan2(func.sqrt(a), func.sqrt(1.0 - a))
    return 6371.0 * c


def geocode_zip(zip_code: str) -> tuple[float, float]:
    rec = nomi.query_postal_code(zip_code)
    if rec is None or (isinstance(rec.latitude, float) and math.isnan(rec.latitude)):
        raise HTTPException(status_code=400, detail="Invalid or unsupported ZIP code for geocoding")
    return float(rec.latitude), float(rec.longitude)


@app.get("/providers", response_model=List[ProviderResult])
async def get_providers(
    drg: str = Query(..., description="DRG code or text to search in ms_drg_definition"),
    zip: str = Query(..., min_length=5, max_length=5, description="Base ZIP code"),
    radius_km: int = Query(40, ge=1, le=500, description="Search radius in kilometers"),
    session: AsyncSession = Depends(get_session),
):
    lat, lon = geocode_zip(zip)
    distance_expr = haversine_sql(lat, lon, Provider.latitude, Provider.longitude)

    drg_like = f"%{drg}%"

    stmt = (
        select(
            Provider.provider_id,
            Provider.name,
            Provider.city,
            Provider.state,
            Provider.zip_code,
            Procedure.ms_drg_definition,
            Procedure.average_covered_charges,
            Procedure.average_total_payments,
            Procedure.average_medicare_payments,
            Rating.rating,
            distance_expr.label("distance_km"),
        )
        .join(Procedure, Procedure.provider_id == Provider.provider_id)
        .join(Rating, Rating.provider_id == Provider.provider_id, isouter=True)
        .where(
            and_(
                Procedure.ms_drg_definition.ilike(drg_like),
                Provider.latitude.isnot(None),
                Provider.longitude.isnot(None),
                distance_expr <= radius_km,
            )
        )
        .order_by(Procedure.average_covered_charges.asc())
        .limit(100)
    )

    rows = (await session.execute(stmt)).all()
    results: List[ProviderResult] = []
    for row in rows:
        results.append(
            ProviderResult(
                provider_id=row.provider_id,
                name=row.name,
                city=row.city,
                state=row.state,
                zip_code=row.zip_code,
                ms_drg_definition=row.ms_drg_definition,
                average_covered_charges=float(row.average_covered_charges) if row.average_covered_charges is not None else None,  # type: ignore
                average_total_payments=float(row.average_total_payments) if row.average_total_payments is not None else None,  # type: ignore
                average_medicare_payments=float(row.average_medicare_payments) if row.average_medicare_payments is not None else None,  # type: ignore
                rating=row.rating,
                distance_km=float(row.distance_km) if row.distance_km is not None else None,  # type: ignore
            )
        )
    return results


@app.post("/ask", response_model=AskResponse)
async def ask(body: AskRequest, session: AsyncSession = Depends(get_session)):
    q = body.question.strip()
    if not is_scope_relevant(q):
        return AskResponse(
            answer=(
                "I can only help with hospital pricing and quality information. Please ask about medical procedures, costs, or hospital ratings."
            )
        )

    params = extract_params_with_openai(q)
    if not params.zip_code:
        raise HTTPException(status_code=400, detail="Please include a 5-digit ZIP code in your question.")
    lat, lon = geocode_zip(params.zip_code)
    radius_km = params.radius_km or 40
    distance_expr = haversine_sql(lat, lon, Provider.latitude, Provider.longitude)

    drg_like = f"%{params.drg_query or ''}%" if params.drg_query else "%"

    base = (
        select(
            Provider.provider_id,
            Provider.name,
            Provider.city,
            Provider.state,
            Provider.zip_code,
            Procedure.ms_drg_definition,
            Procedure.average_covered_charges,
            Rating.rating,
            distance_expr.label("distance_km"),
        )
        .join(Procedure, Procedure.provider_id == Provider.provider_id)
        .join(Rating, Rating.provider_id == Provider.provider_id, isouter=True)
        .where(
            and_(
                Procedure.ms_drg_definition.ilike(drg_like),
                Provider.latitude.isnot(None),
                Provider.longitude.isnot(None),
                distance_expr <= radius_km,
            )
        )
    )

    if params.intent == "best_rated":
        stmt = base.order_by(
            Rating.rating.desc().nullslast(),
            Procedure.average_covered_charges.asc().nullslast(),
        ).limit(500)
        rows = (await session.execute(stmt)).all()
        if not rows:
            return AskResponse(answer="No matching hospitals found within the radius.")
        # Deduplicate by provider to avoid repeating the same hospital across many DRGs
        unique_rows = []
        seen_provider_ids = set()
        for r in rows:
            if r.provider_id in seen_provider_ids:
                continue
            seen_provider_ids.add(r.provider_id)
            unique_rows.append(r)
            if len(unique_rows) >= params.top_k:
                break
        parts = [
            f"{r.name} (rating: {r.rating if r.rating is not None else 'N/A'})"
            for r in unique_rows
        ]
        return AskResponse(answer="; ".join(parts))

    if params.intent == "average_cost":
        stmt = (
            select(
                func.avg(Procedure.average_covered_charges).label("avg_cost"),
                func.count().label("count"),
            )
            .join(Procedure, Procedure.provider_id == Provider.provider_id)
            .where(
                and_(
                    Procedure.ms_drg_definition.ilike(drg_like),
                    Provider.latitude.isnot(None),
                    Provider.longitude.isnot(None),
                    distance_expr <= radius_km,
                )
            )
        )
        row = (await session.execute(stmt)).one_or_none()
        if not row or row.avg_cost is None:
            return AskResponse(answer="No matching hospitals found to compute an average.")
        return AskResponse(
            answer=f"Average covered charges: ${float(row.avg_cost):,.0f} across {int(row.count)} hospitals."
        )

    # default and 'cheapest'
    stmt = base.order_by(Procedure.average_covered_charges.asc().nullslast()).limit(params.top_k)
    rows = (await session.execute(stmt)).all()
    if not rows:
        return AskResponse(answer="No matching hospitals found within the radius.")
    best = rows[0]
    return AskResponse(
        answer=f"Based on data, {best.name} at ${float(best.average_covered_charges):,.0f} average covered charges."
    )


@app.get("/")
async def root():
    return {"status": "ok"}

