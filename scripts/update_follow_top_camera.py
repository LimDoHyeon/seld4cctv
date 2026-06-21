import importlib
import os
import sys
from pathlib import Path


PROJECT_DIR_NAME = "cctv_sim"


def _is_scripts_dir(path):
    return (path / "sim" / "follow_top_camera.py").exists()


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
        for candidate in (base / "scripts", base / PROJECT_DIR_NAME / "scripts"):
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

for module_name in ("sim.follow_top_camera", "sim.usd_utils", "sim.config"):
    sys.modules.pop(module_name, None)
sys.modules.pop("sim", None)

from sim.follow_top_camera import ensure_follow_top_camera_controller


stage_x = float(globals().get("FOLLOW_TOP_CAMERA_STAGE_X", 0.0))
stage_y = float(globals().get("FOLLOW_TOP_CAMERA_STAGE_Y", 0.0))
bind_viewport = bool(globals().get("FOLLOW_TOP_CAMERA_BIND_VIEWPORT", False))

controller = ensure_follow_top_camera_controller()
updated_position = controller.set_stage_xy(stage_x, stage_y)

if bind_viewport:
    ok, message = controller.bind_to_active_viewport()
    print(f"[update_follow_top_camera] {message}")

print(
    "[update_follow_top_camera] updated rig translate="
    f"({updated_position[0]:.2f}, {updated_position[1]:.2f}, {updated_position[2]:.2f}) "
    f"for stage_xy=({stage_x:.2f}, {stage_y:.2f})"
)
