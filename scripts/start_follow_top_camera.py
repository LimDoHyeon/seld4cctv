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


fixed_height = float(globals().get("FOLLOW_TOP_CAMERA_FIXED_HEIGHT_OVERRIDE", 50.0))
clipping_range = globals().get("FOLLOW_TOP_CAMERA_CLIPPING_RANGE_OVERRIDE", (0.1, 100000.0))
bind_viewport = bool(globals().get("FOLLOW_TOP_CAMERA_BIND_VIEWPORT", True))
initial_stage_xy = globals().get("FOLLOW_TOP_CAMERA_INITIAL_STAGE_XY", (0.0, 0.0))

controller = ensure_follow_top_camera_controller(
    fixed_height=fixed_height,
    clipping_range=clipping_range,
)
controller.set_stage_xy(initial_stage_xy[0], initial_stage_xy[1])

if bind_viewport:
    ok, message = controller.bind_to_active_viewport()
    print(f"[start_follow_top_camera] {message}")

print(f"[start_follow_top_camera] scripts dir: {SCRIPTS_DIR}")
print(f"[start_follow_top_camera] root_path={controller.root_path}")
print(f"[start_follow_top_camera] rig_path={controller.rig_path}")
print(f"[start_follow_top_camera] camera_path={controller.camera_path}")
print(
    "[start_follow_top_camera] stage_xy="
    f"({float(initial_stage_xy[0]):.2f}, {float(initial_stage_xy[1]):.2f}) "
    f"height={controller.fixed_height:.2f} focal_length={controller.focal_length:.2f}"
)
