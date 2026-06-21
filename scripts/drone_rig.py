import sys
from pathlib import Path


def _resolve_scripts_dir():
    file_value = globals().get("__file__")
    if file_value:
        return Path(file_value).resolve().parent
    return Path.cwd().resolve()


SCRIPTS_DIR = _resolve_scripts_dir()
scripts_dir_str = str(SCRIPTS_DIR)
if scripts_dir_str not in sys.path:
    sys.path.insert(0, scripts_dir_str)

from sim.drone_rig import DroneRig, DroneTargetFollower, cctv_coord_to_world_xy

__all__ = [
    "DroneRig",
    "DroneTargetFollower",
    "cctv_coord_to_world_xy",
]
