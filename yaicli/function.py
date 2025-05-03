import importlib.util
import sys
from typing import Dict, Any, List, Optional, Set
from datetime import datetime

from yaicli.const import FUNCTIONS_DIR


class FunctionManager:
    """Manager for loading and executing functions from the local config directory."""

    # 单例实例
    _instance = None

    def __init__(self):
        """Initialize and load functions if needed."""
        # 只在首次创建时初始化
        if not hasattr(self, "_initialized"):
            self._initialized = True
            self._functions: Dict[str, Any] = {}
            self._function_specs: List[Dict[str, Any]] = []
            self._last_loaded_time: Optional[datetime] = None
            self._load_functions()

    def _load_functions(self) -> None:
        """Load function modules from the functions directory."""
        if not FUNCTIONS_DIR.exists():
            return

        self._functions.clear()
        self._function_specs.clear()
        self._last_loaded_time = datetime.now()

        for py_file in FUNCTIONS_DIR.glob("*.py"):
            if py_file.name.startswith("_"):
                continue

            module_name = f"user_functions.{py_file.stem}"

            try:
                spec = importlib.util.spec_from_file_location(module_name, py_file)
                if not spec or not spec.loader:
                    continue

                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)

                if hasattr(module, "Function"):
                    self._functions[py_file.stem] = module.Function

                    # Create function spec for API
                    function_spec = {
                        "type": "function",
                        "function": {
                            "name": py_file.stem,
                            "description": module.Function.__doc__ or "",
                        },
                    }

                    # Add parameter schema if available
                    if hasattr(module.Function, "model_json_schema"):
                        schema = module.Function.model_json_schema()
                        if "properties" in schema:
                            function_spec["function"]["parameters"] = {
                                "type": "object",
                                "properties": schema.get("properties", {}),
                                "required": schema.get("required", []),
                            }

                    self._function_specs.append(function_spec)
            except Exception:
                pass  # Skip failed imports

    def reload_functions(self) -> None:
        """Reload all functions from the functions directory."""
        self._load_functions()

    def reload_if_changed(self) -> bool:
        """Reload functions only if any file has been modified since last load."""
        if not FUNCTIONS_DIR.exists() or not self._last_loaded_time:
            return False

        latest_mtime = max(
            [f.stat().st_mtime for f in FUNCTIONS_DIR.glob("*.py") if not f.name.startswith("_")], default=0
        )

        if latest_mtime > self._last_loaded_time.timestamp():
            self.reload_functions()
            return True

        return False

    @property
    def functions(self) -> Dict[str, Any]:
        """Get all loaded functions."""
        return self._functions

    @property
    def function_specs(self) -> List[Dict[str, Any]]:
        """Get all function specifications for API requests."""
        return self._function_specs

    def get_function(self, name: str) -> Optional[Any]:
        """Get a function by name."""
        return self._functions.get(name)

    def execute_function(self, name: str, **kwargs) -> Any:
        """Execute a function with the given arguments."""
        function_cls = self.get_function(name)
        if not function_cls:
            raise ValueError(f"Function {name} does not exist")

        try:
            return function_cls.execute(**kwargs)
        except Exception as e:
            raise ValueError(f"Error executing function {name}: {str(e)}")

    def get_available_function_names(self) -> Set[str]:
        """Get the names of all available functions."""
        return set(self._functions.keys())


# 创建模块级别的单例
_function_manager = None


def get_function_manager() -> FunctionManager:
    """Get the singleton instance of FunctionManager."""
    global _function_manager
    if _function_manager is None:
        _function_manager = FunctionManager()
    return _function_manager
