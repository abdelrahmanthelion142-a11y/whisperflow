from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import SecretStr, Secret, PostgresDsn


class Settings(BaseSettings):
    POSTGRES_URL: SecretStr
    JWT_SECRET: SecretStr
    JWT_ALG : str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES : int = 30
    DATABASE_PASSWORD : SecretStr

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")



settings = Settings() #type:ignore
