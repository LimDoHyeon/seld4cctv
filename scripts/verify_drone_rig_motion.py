import asyncio
import builtins
from pathlib import Path
import sys

import omni.kit.app
import omni.usd


REPO_ROOT = Path("/home/user/Documents/DT_teamA")
sys.path.insert(0, str(REPO_ROOT / "omniverse" / "cctv_sim"))


def _exec_script(script_path):
    namespace = {
        "__name__": "__main__",
        "__file__": str(script_path),
    }
    exec(compile(script_path.read_text(encoding="utf-8"), str(script_path), "exec"), namespace)
    return namespace


async def main():
    stage_path = REPO_ROOT / "omniverse" / "cctv_sim" / "assets" / "city" / "World_CityDemopack.usd"
    start_demo_script = REPO_ROOT / "omniverse" / "cctv_sim" / "scripts" / "start_demo.py"

    opened = omni.usd.get_context().open_stage(str(stage_path))
    print(f"[verify_drone_rig_motion] open_stage={opened}")

    for _ in range(240):
        await omni.kit.app.get_app().next_update_async()
        stage = omni.usd.get_context().get_stage()
        if stage is not None and stage.GetPrimAtPath("/World").IsValid():
            break
    else:
        raise RuntimeError("Stage did not finish loading")

    _exec_script(start_demo_script)
    for _ in range(180):
        await omni.kit.app.get_app().next_update_async()

    demo_app = getattr(builtins, "demo_app", None)
    if demo_app is None:
        raise RuntimeError("demo_app not available")

    controller = demo_app.follow_top_camera
    rig = controller.drone_rig
    if rig is None:
        raise RuntimeError("DroneRig was not created")

    print(f"[verify_drone_rig_motion] initial={rig.describe()}")

    targets = (
        (-2200.0, 8400.0),
        (-1800.0, 7600.0),
    )
    for index, (stage_x, stage_y) in enumerate(targets, start=1):
        demo_app.move_follow_top_camera_to_stage_xy(stage_x, stage_y, bind_viewport=False, duration_sec=1.5)
        for frame_index in range(70):
            await omni.kit.app.get_app().next_update_async()
            if frame_index in (0, 15, 30, 45, 60):
                print(
                    f"[verify_drone_rig_motion] move{index}_frame_{frame_index}="
                    f"{rig.get_position_xy_altitude()} camera_invisible={rig.is_camera_invisible()}"
                )

    print(f"[verify_drone_rig_motion] final={rig.describe()}")
    omni.kit.app.get_app().post_quit()


asyncio.ensure_future(main())
