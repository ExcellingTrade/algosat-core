# algosat/config.py
from pathlib import Path
from typing import Optional
from pydantic import PostgresDsn, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    _env_path = Path(__file__).parent / ".env"
    model_config = SettingsConfigDict(
        env_file=str(_env_path),
        env_file_encoding="utf-8",
        extra='ignore'
    )

    # Define individual components to be read from .env
    DB_SCHEME: str = "postgresql+asyncpg"
    DB_USER: str
    DB_PASSWORD: str
    DB_HOST: str
    DB_PORT: int = 5432
    DB_NAME: str

    # This will be constructed by the validator below
    database_url: Optional[PostgresDsn] = None
    poll_interval: int = 10

    @model_validator(mode='after')
    def assemble_db_connection(self) -> 'Settings':
        # Ensure all necessary components are loaded before trying to build the DSN
        # Pydantic will raise an error before this if mandatory fields (DB_USER etc.) are missing
        self.database_url = PostgresDsn.build(
            scheme=self.DB_SCHEME,
            username=self.DB_USER,
            password=self.DB_PASSWORD,
            host=self.DB_HOST,
            port=self.DB_PORT, 
            path=f"{self.DB_NAME}"
        )
        return self

settings = Settings()