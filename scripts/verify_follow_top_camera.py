import importlib
import os
import sys
from pathlib import Path

from pxr import UsdGeom


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
from sim.usd_utils import get_stage


def _assert(condition, message):
    if not condition:
        raise AssertionError(message)


controller = ensure_follow_top_camera_controller()
stage = get_stage()

root_prim = stage.GetPrimAtPath(controller.root_path)
rig_prim = stage.GetPrimAtPath(controller.rig_path)
camera_prim = stage.GetPrimAtPath(controller.camera_path)
camera = UsdGeom.Camera(camera_prim)

_assert(root_prim.IsValid(), f"Root prim missing: {controller.root_path}")
_assert(rig_prim.IsValid(), f"Rig prim missing: {controller.rig_path}")
_assert(camera_prim.IsValid(), f"Camera prim missing: {controller.camera_path}")
_assert(camera, f"Camera schema invalid: {controller.camera_path}")

projection = camera.GetProjectionAttr().Get()
clipping_range = camera.GetClippingRangeAttr().Get()
focal_length = camera.GetFocalLengthAttr().Get()
horizontal_aperture = camera.GetHorizontalApertureAttr().Get()
vertical_aperture = camera.GetVerticalApertureAttr().Get()

_assert(projection == UsdGeom.Tokens.perspective, f"Expected perspective projection, got {projection!r}")
_assert(clipping_range is not None, "Clipping range not set")
_assert(abs(float(horizontal_aperture) - float(controller.horizontal_aperture)) < 1e-6, "Horizontal aperture mismatch")
_assert(abs(float(focal_length) - float(controller.focal_length)) < 1e-6, "Focal length mismatch")
expected_vertical_aperture = controller.horizontal_aperture * (
    float(controller.viewport_aspect[1]) / float(controller.viewport_aspect[0])
)
_assert(
    abs(float(vertical_aperture) - float(expected_vertical_aperture)) < 1e-6,
    "Vertical aperture does not match viewport aspect",
)

translate_before = controller.set_stage_xy(123.0, -456.0)
translate_after = controller.set_world_position((321.0, 654.0, 987.0))

up_axis = UsdGeom.GetStageUpAxis(stage)
if up_axis == UsdGeom.Tokens.y:
    _assert(abs(translate_before[0] - 123.0) < 1e-6, "Y-up stage_x update failed")
    _assert(abs(translate_before[2] + 456.0) < 1e-6, "Y-up stage_y update failed")
    _assert(abs(translate_after[0] - 321.0) < 1e-6, "Y-up world X follow failed")
    _assert(abs(translate_after[2] - 987.0) < 1e-6, "Y-up world Z follow failed")
else:
    _assert(abs(translate_before[0] - 123.0) < 1e-6, "Z-up stage_x update failed")
    _assert(abs(translate_before[1] + 456.0) < 1e-6, "Z-up stage_y update failed")
    _assert(abs(translate_after[0] - 321.0) < 1e-6, "Z-up world X follow failed")
    _assert(abs(translate_after[1] - 654.0) < 1e-6, "Z-up world Y follow failed")

print(f"[verify_follow_top_camera] root={controller.root_path}")
print(f"[verify_follow_top_camera] rig={controller.rig_path}")
print(f"[verify_follow_top_camera] camera={controller.camera_path}")
print(f"[verify_follow_top_camera] projection={projection}")
print(
    "[verify_follow_top_camera] clipping_range="
    f"({float(clipping_range[0]):.3f}, {float(clipping_range[1]):.3f}) "
    f"focal_length={float(focal_length):.3f} "
    f"aspect={controller.viewport_aspect[0]:.3f}:{controller.viewport_aspect[1]:.3f}"
)
print(
    "[verify_follow_top_camera] translate_after="
    f"({translate_after[0]:.3f}, {translate_after[1]:.3f}, {translate_after[2]:.3f})"
)
print("[verify_follow_top_camera] PASS")
