"""
Example actions — copy these to scaffold new ones.

Each action is just `Action(name=..., parameters=PydanticModel, handler=async fn)`.
The handler receives a *validated* model instance, not a raw dict.

Spec: docs/classes/ExampleActions.md
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .base import Action


# --- echo --------------------------------------------------------------------
class EchoParams(BaseModel):
    text: str = Field(description="The text to echo back.")


async def _echo(params: EchoParams) -> dict[str, str]:
    return {"echoed": params.text}


echo_action: Action[EchoParams] = Action(
    name="echo",
    description="Echo a string back to the user. Useful for testing the action pipeline.",
    parameters=EchoParams,
    handler=_echo,
)


# --- weather (mock) ----------------------------------------------------------
class WeatherParams(BaseModel):
    city: str = Field(description="City name, e.g. 'London'.")
    units: str = Field(default="celsius", description="'celsius' or 'fahrenheit'.")


async def _weather(params: WeatherParams) -> dict[str, str | float]:
    """Stub — replace with a real API call when you wire one in."""
    sample_temp_c = 18.5
    temp = sample_temp_c if params.units == "celsius" else sample_temp_c * 9 / 5 + 32
    return {
        "city": params.city,
        "temperature": round(temp, 1),
        "units": params.units,
        "summary": f"Mild and partly cloudy in {params.city}.",
        "_note": "stub data — wire a real provider in app/actions/examples.py",
    }


weather_action: Action[WeatherParams] = Action(
    name="get_weather",
    description="Get the current weather for a city. Returns temperature and a short summary.",
    parameters=WeatherParams,
    handler=_weather,
)
