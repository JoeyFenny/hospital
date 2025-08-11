from pydantic import BaseModel
from typing import Optional


class ProviderResult(BaseModel):
    provider_id: str
    name: str
    city: Optional[str]
    state: Optional[str]
    zip_code: Optional[str]
    ms_drg_definition: str
    average_covered_charges: float
    average_total_payments: Optional[float] = None
    average_medicare_payments: Optional[float] = None
    rating: Optional[int] = None
    distance_km: Optional[float] = None


class AskRequest(BaseModel):
    question: str


class AskResponse(BaseModel):
    answer: str

