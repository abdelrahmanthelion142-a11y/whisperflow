from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import SecretStr


class Settings(BaseSettings):
    POSTGRES_URL: SecretStr
    JWT_SECRET: SecretStr
    JWT_ALG: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    DATABASE_PASSWORD: SecretStr

    OPENAI_API_KEY: SecretStr = SecretStr("test-openai-api-key")
    MAX_FILE_SIZE_MB: int = 20
    MAX_AUDIO_DURATION_SECS: int = 240
    ALLOWED_EXTENSIONS: set[str] = {
        ".mp3",
        ".wav",
        ".m4a",
        ".webm",
        ".ogg",
        ".mp4",
    }

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()  # type:ignore
