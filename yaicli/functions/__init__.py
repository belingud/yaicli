
import shutil
from pathlib import Path
from typing import Any

from ..console import get_console
from ..const import FUNCTIONS_DIR
from ..utils import option_callback

console = get_console()


@option_callback
def install_functions(cls, _: Any) -> None:
    """Install buildin functions"""
    cur_dir = Path(__file__).absolute().parent
    buildin_dir = cur_dir / "buildin"
    buildin_funcs = [Path(path) for path in buildin_dir.glob("*.py")]
    console.print("Installing buildin functions...")
    if not FUNCTIONS_DIR.exists():
        FUNCTIONS_DIR.mkdir(parents=True)
    for file in buildin_funcs:
        if (FUNCTIONS_DIR / file.name).exists():
            # Skip if function already exists
            console.print(f"Function {file.name} already exists, skipping.")
            continue
        shutil.copy(file, FUNCTIONS_DIR, follow_symlinks=True)
        console.print(f"Installed {FUNCTIONS_DIR}/{file.name}")


@option_callback
def print_functions(cls, _: Any) -> None:
    """List all available buildin functions"""
    if not FUNCTIONS_DIR.exists():
        console.print("No installed functions found.")
        return
    for file in FUNCTIONS_DIR.glob("*.py"):
        if file.name.startswith("_"):
            continue
        console.print(file)
