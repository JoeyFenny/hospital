import os
from pydantic import BaseModel


class Settings(BaseModel):
    database_url: str = os.getenv(
        "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/hospital"
    )
    openai_api_key: str | None = os.getenv("OPENAI_API_KEY")
    app_name: str = os.getenv("APP_NAME", "Healthcare Cost Navigator")


settings = Settings()

