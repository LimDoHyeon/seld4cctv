import sys
from pathlib import Path


def _is_scripts_dir(path):
    return (path / "sim" / "drone_rig.py").exists()


def _resolve_scripts_dir():
    file_value = globals().get("__file__")
    if file_value:
        scripts_dir = Path(file_value).resolve().parent
        if _is_scripts_dir(scripts_dir):
            return scripts_dir

    cwd = Path.cwd().resolve()
    for base in (cwd, *cwd.parents):
        for candidate in (base / "scripts", base / "cctv_sim" / "scripts"):
            if _is_scripts_dir(candidate):
                return candidate

    raise RuntimeError("Unable to locate cctv_sim/scripts.")


SCRIPTS_DIR = _resolve_scripts_dir()
scripts_dir_str = str(SCRIPTS_DIR)
if scripts_dir_str not in sys.path:
    sys.path.insert(0, scripts_dir_str)

from sim.drone_rig import DroneRig, DroneTargetFollower, cctv_coord_to_world_xy


drone = DroneRig(
    rig_path="/World/DroneRig",
    crazyflie_asset_path=None,
    fixed_altitude=80.0,
    visual_scale=5.0,
).create()

drone.set_position_xy(0.0, 0.0)
drone.set_yaw_deg(0.0)
drone.look_through_camera()

follower = DroneTargetFollower(drone, smoothing=0.2)
target_x, target_y = cctv_coord_to_world_xy(120.0, -35.0)
smoothed_x, smoothed_y = follower.update_target(target_x=target_x, target_y=target_y)

print("[test_create_drone_rig] DroneRig created")
print(f"[test_create_drone_rig] description={drone.describe()}")
print(f"[test_create_drone_rig] follower_xy=({smoothed_x:.2f}, {smoothed_y:.2f})")
