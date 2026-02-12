"""Lightweight replacement for instructor.OpenAISchema.

Only provides openai_schema and anthropic_schema classproperties,
which is all yaicli needs for function calling schema generation.
"""

from typing import Any, Callable, Generic, TypeVar

from docstring_parser import parse
from pydantic import BaseModel, ConfigDict

R_co = TypeVar("R_co", covariant=True)


class classproperty(Generic[R_co]):
    """Descriptor for class-level properties with per-class caching."""

    def __init__(self, method: Callable[[Any], R_co]) -> None:
        self.cproperty = method
        self.attr_name = ""

    def __set_name__(self, owner: type, name: str) -> None:
        self.attr_name = f"_classproperty_cache_{name}"

    def __get__(self, instance: object, cls: type[Any]) -> R_co:
        cache_attr = self.attr_name
        if cache_attr:
            try:
                return getattr(cls, cache_attr)
            except AttributeError:
                pass
        value = self.cproperty(cls)
        if cache_attr:
            # Store cache directly on the subclass to avoid recomputation
            type.__setattr__(cls, cache_attr, value)
        return value


class OpenAISchema(BaseModel):
    """Base class for function-calling schemas.

    Subclasses should define fields with pydantic Field() and a docstring
    describing the function. The openai_schema and anthropic_schema
    classproperties generate the appropriate JSON schema for each provider.
    """

    model_config = ConfigDict(ignored_types=(classproperty,))

    @classproperty
    def openai_schema(cls) -> dict[str, Any]:
        """Return the schema in OpenAI function-calling format."""
        schema = cls.model_json_schema()
        docstring = parse(cls.__doc__ or "")
        parameters = {k: v for k, v in schema.items() if k not in ("title", "description")}
        for param in docstring.params:
            if (name := param.arg_name) in parameters.get("properties", {}) and (description := param.description):
                if "description" not in parameters["properties"][name]:
                    parameters["properties"][name]["description"] = description

        parameters["required"] = sorted(k for k, v in parameters.get("properties", {}).items() if "default" not in v)

        if "description" not in schema:
            if docstring.short_description:
                schema["description"] = docstring.short_description
            else:
                schema["description"] = (
                    f"Correctly extracted `{cls.__name__}` with all "
                    f"the required parameters with correct types"
                )

        return {
            "name": schema["title"],
            "description": schema["description"],
            "parameters": parameters,
        }

    @classproperty
    def anthropic_schema(cls) -> dict[str, Any]:
        """Return the schema in Anthropic tool-use format."""
        openai = cls.openai_schema
        return {
            "name": openai["name"],
            "description": openai["description"],
            "input_schema": cls.model_json_schema(),
        }
