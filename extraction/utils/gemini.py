from google import genai
from google.genai.types import (
    GenerateContentConfig,
    ThinkingConfig,
    ThinkingLevel,
)
import os
from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()

client = genai.Client(
    vertexai=True,
    project=os.environ.get("PROJECT"),
    location="global",
)


async def llm_call_with_struct_output(
    prompt: str,
    response_schema: BaseModel,
    MODEL_ID="gemini-3-flash-preview",
):
    response = await client.aio.models.generate_content(
        model=MODEL_ID,
        contents=prompt,
        config=GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=response_schema,
            thinking_config=ThinkingConfig(thinking_level=ThinkingLevel.LOW),
        ),
    )

    extracted = response.parsed.model_dump()

    return extracted
