import json

import httpx
from yaicli.function_schema import OpenAISchema
from pydantic import Field


class Function(OpenAISchema):
    """Query the weather from wttr.in for today and the next two days by city name in English."""

    city: str = Field(description="The city to query the weather of.")
    language: str = Field(
        description="The language of the weather information.",
        default="en",
        examples=["en", "zh", "ja", "ko", "fr", "de", "es", "it"],
    )

    class Config:
        title = "get_weather"

    @classmethod
    def execute(cls, city: str, language: str = "en"):
        """execute the function"""
        url = f"https://wttr.in/{city}"
        params = {
            "format": "j1",
            "lang": language,
        }

        try:
            response = httpx.get(url, params=params, timeout=10)
            data = response.json()
            if data.get("weather"):
                for i in data["weather"]:
                    i.pop("hourly")

            return f"The weather for {city} for today and the next 2 days: {json.dumps(data, ensure_ascii=False)}"
        except Exception as e:
            return f"Failed to get the weather for {city} for today and the next 2 days: {str(e)}"
