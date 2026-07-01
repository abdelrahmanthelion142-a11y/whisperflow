from openai import AsyncOpenAI
from app.core.config import settings

llm_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY.get_secret_value())
