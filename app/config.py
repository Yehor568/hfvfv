from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./product_hunter.db"

    meta_access_token: str = ""
    meta_api_version: str = "v21.0"
    meta_ad_account_ids: str = ""

    lpcrm_domain: str = ""
    lpcrm_api_key: str = ""

    dashboard_user: str = "admin"
    dashboard_password: str = ""

    @property
    def ad_account_ids(self) -> list[str]:
        return [a.strip().removeprefix("act_") for a in self.meta_ad_account_ids.split(",") if a.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
