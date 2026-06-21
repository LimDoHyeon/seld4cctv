import importlib
import builtins
import os
import sys
from pathlib import Path

PROJECT_DIR_NAME = "cctv_sim"


def _is_scripts_dir(path):
    return (path / "sim" / "app.py").exists()


def _scripts_dir_from_root(root_value):
    if not root_value:
        return None

    root = Path(root_value).expanduser().resolve()
    if _is_scripts_dir(root):
        return root

    scripts_dir = root / "scripts"
    if _is_scripts_dir(scripts_dir):
        return scripts_dir

    return None


def _resolve_scripts_dir():
    file_value = globals().get("__file__")
    if file_value:
        scripts_dir = Path(file_value).resolve().parent
        if _is_scripts_dir(scripts_dir):
            return scripts_dir

    for root_override in (globals().get("CCTV_SIM_ROOT"), os.environ.get("CCTV_SIM_ROOT")):
        scripts_dir = _scripts_dir_from_root(root_override)
        if scripts_dir is not None:
            return scripts_dir

    cwd = Path.cwd().resolve()
    for base in (cwd, *cwd.parents):
        for candidate in (
            base / "scripts",
            base / PROJECT_DIR_NAME / "scripts",
        ):
            if _is_scripts_dir(candidate):
                return candidate

    raise RuntimeError(
        "Unable to locate cctv_sim/scripts. Set CCTV_SIM_ROOT before exec(), "
        "run from the omniverse tree, or run the script with __file__ defined."
    )


SCRIPTS_DIR = _resolve_scripts_dir()

scripts_dir_str = str(SCRIPTS_DIR)
if scripts_dir_str in sys.path:
    sys.path.remove(scripts_dir_str)
sys.path.insert(0, scripts_dir_str)

importlib.invalidate_caches()

for attr_name in ("demo_app", "_cctv_sim_demo_app"):
    try:
        previous_app = globals().get(attr_name)
        if previous_app is None:
            previous_app = getattr(builtins, attr_name, None)
        if previous_app is not None:
            previous_app.stop()
            print(f"[start_demo] previous {attr_name} stopped")
    except Exception as e:
        print(f"[start_demo] failed to stop previous {attr_name}:", e)

MODULE_NAMES = (
    "sim.usd_utils",
    "sim.paths",
    "sim.config",
    "sim.animation",
    "sim.locomotion",
    "sim.scene",
    "sim.cctv",
    "sim.characters",
    "sim.events",
    "sim.minimap_core",
    "sim.minimap_window",
    "sim.monitor",
    "sim.ui",
    "sim.app",
)

for module_name in reversed(MODULE_NAMES):
    sys.modules.pop(module_name, None)
sys.modules.pop("sim", None)

from sim.app import DemoApp
import sim.events as _loaded_events

demo_app = DemoApp()
demo_app.start()

globals()["demo_app"] = demo_app
setattr(builtins, "demo_app", demo_app)
setattr(builtins, "_cctv_sim_demo_app", demo_app)

print(f"[start_demo] scripts dir: {SCRIPTS_DIR}")
print(f"[start_demo] sim.events: {_loaded_events.__file__}")
print("[start_demo] demo_app started")
