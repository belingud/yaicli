import shutil
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import Field

from yaicli.function_schema import OpenAISchema, classproperty


class TestClassproperty:
    def test_basic_descriptor(self):
        """Test classproperty works as a class-level property."""

        class MyClass:
            @classproperty
            def value(cls):
                return 42

        assert MyClass.value == 42

    def test_caching(self):
        """Test classproperty caches result after first access."""
        call_count = 0

        class MyClass:
            @classproperty
            def value(cls):
                nonlocal call_count
                call_count += 1
                return "result"

        # Access multiple times
        _ = MyClass.value
        _ = MyClass.value
        _ = MyClass.value
        assert call_count == 1

    def test_per_class_cache(self):
        """Test each subclass gets its own cached value."""

        class Base:
            @classproperty
            def name(cls):
                return cls.__name__

        class ChildA(Base):
            pass

        class ChildB(Base):
            pass

        assert ChildA.name == "ChildA"
        assert ChildB.name == "ChildB"


class TestOpenAISchemaBasic:
    def test_openai_schema_structure(self):
        """Test openai_schema returns correct top-level keys."""

        class MyFunc(OpenAISchema):
            """Do something useful."""

            arg: str = Field(..., description="An argument")

            class Config:
                title = "my_func"

        schema = MyFunc.openai_schema
        assert schema["name"] == "my_func"
        assert schema["description"] == "Do something useful."
        assert "parameters" in schema

    def test_openai_schema_parameters(self):
        """Test openai_schema correctly extracts parameters."""

        class MyFunc(OpenAISchema):
            """Test function."""

            required_arg: str = Field(..., description="Required")
            optional_arg: int = Field(default=0, description="Optional")

            class Config:
                title = "test_func"

        params = MyFunc.openai_schema["parameters"]
        assert "required_arg" in params["properties"]
        assert "optional_arg" in params["properties"]
        assert "required_arg" in params["required"]
        assert "optional_arg" not in params["required"]

    def test_openai_schema_description_from_docstring(self):
        """Test description is extracted from class docstring."""

        class MyFunc(OpenAISchema):
            """Short description from docstring."""

            name: str = Field(...)

            class Config:
                title = "func_with_doc"

        assert MyFunc.openai_schema["description"] == "Short description from docstring."

    def test_openai_schema_fallback_description(self):
        """Test fallback description when no docstring."""

        class NoDocFunc(OpenAISchema):
            name: str = Field(...)

            class Config:
                title = "no_doc_func"

        desc = NoDocFunc.openai_schema["description"]
        assert "NoDocFunc" in desc
        assert "required parameters" in desc

    def test_openai_schema_docstring_param_description(self):
        """Test field descriptions are filled from docstring params."""

        class MyFunc(OpenAISchema):
            """Do something.

            Args:
                name: The name to use
            """

            name: str = Field(...)

            class Config:
                title = "func_docstring_params"

        props = MyFunc.openai_schema["parameters"]["properties"]
        assert props["name"]["description"] == "The name to use"

    def test_openai_schema_field_description_takes_priority(self):
        """Test Field(description=...) is not overwritten by docstring."""

        class MyFunc(OpenAISchema):
            """Do something.

            Args:
                name: docstring desc
            """

            name: str = Field(..., description="field desc")

            class Config:
                title = "priority_func"

        props = MyFunc.openai_schema["parameters"]["properties"]
        assert props["name"]["description"] == "field desc"


class TestAnthropicSchema:
    def test_anthropic_schema_structure(self):
        """Test anthropic_schema returns correct format."""

        class MyFunc(OpenAISchema):
            """A test function."""

            arg: str = Field(..., description="An arg")

            class Config:
                title = "anthro_func"

        schema = MyFunc.anthropic_schema
        assert schema["name"] == "anthro_func"
        assert schema["description"] == "A test function."
        assert "input_schema" in schema
        assert schema["input_schema"]["type"] == "object"

    def test_anthropic_schema_consistency(self):
        """Test anthropic_schema name/description matches openai_schema."""

        class MyFunc(OpenAISchema):
            """Consistent function."""

            val: int = Field(...)

            class Config:
                title = "consistent_func"

        openai = MyFunc.openai_schema
        anthropic = MyFunc.anthropic_schema
        assert openai["name"] == anthropic["name"]
        assert openai["description"] == anthropic["description"]


class TestOpenAISchemaCaching:
    def test_openai_schema_cached(self):
        """Test openai_schema is computed only once per class."""

        class MyFunc(OpenAISchema):
            """Cached func."""

            x: str = Field(...)

            class Config:
                title = "cached_func"

        s1 = MyFunc.openai_schema
        s2 = MyFunc.openai_schema
        assert s1 is s2  # Same object reference, not just equal

    def test_anthropic_schema_cached(self):
        """Test anthropic_schema is computed only once per class."""

        class MyFunc(OpenAISchema):
            """Cached anthro func."""

            x: str = Field(...)

            class Config:
                title = "cached_anthro"

        s1 = MyFunc.anthropic_schema
        s2 = MyFunc.anthropic_schema
        assert s1 is s2


class TestBuiltinFunctionCompat:
    def test_builtin_function_pattern(self):
        """Test the pattern used by builtin functions works correctly."""

        class Function(OpenAISchema):
            """Execute a shell command and return the output (result)."""

            shell_command: str = Field(
                ...,
                json_schema_extra={"example": "ls -la"},
                description="Shell command to execute.",
            )

            class Config:
                title = "execute_shell_command"

            @classmethod
            def execute(cls, shell_command: str) -> str:
                return f"executed: {shell_command}"

        schema = Function.openai_schema
        assert schema["name"] == "execute_shell_command"
        assert "shell command" in schema["description"].lower()
        assert "shell_command" in schema["parameters"]["properties"]
        assert Function.execute(shell_command="ls") == "executed: ls"
