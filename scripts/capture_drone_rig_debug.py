import asyncio
import builtins
from pathlib import Path
import sys

import omni.kit.app
import omni.usd
from omni.kit.widget.viewport.capture import FileCapture
from omni.kit.viewport.utility import get_active_viewport, get_active_viewport_window


REPO_ROOT = Path("/home/user/Documents/DT_teamA")
sys.path.insert(0, str(REPO_ROOT / "omniverse" / "cctv_sim"))

OUTPUT_DIR = REPO_ROOT / "pictures"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
PERSPECTIVE_PATH = OUTPUT_DIR / "codex_drone_rig_perspective.png"
TOPVIEW_PATH = OUTPUT_DIR / "codex_drone_rig_topview.png"
STAGE_PATH = REPO_ROOT / "omniverse" / "cctv_sim" / "assets" / "city" / "World_CityDemopack.usd"


def _exec_script(script_path):
    namespace = {
        "__name__": "__main__",
        "__file__": str(script_path),
    }
    exec(compile(script_path.read_text(encoding="utf-8"), str(script_path), "exec"), namespace)
    return namespace


def _set_active_viewport_camera(camera_path):
    viewport = get_active_viewport()
    if viewport is not None:
        viewport.camera_path = camera_path
        return True

    viewport_window = get_active_viewport_window()
    if viewport_window is not None and hasattr(viewport_window, "viewport_api"):
        viewport_window.viewport_api.camera_path = camera_path
        return True
    return False


async def _capture(output_path):
    viewport_window = get_active_viewport_window()
    if viewport_window is None or not hasattr(viewport_window, "viewport_api"):
        raise RuntimeError("Active viewport window is unavailable")
    viewport_api = viewport_window.viewport_api
    viewport_api.resolution = (1280, 720)
    await viewport_api.wait_for_rendered_frames(6)
    capture = viewport_api.schedule_capture(FileCapture(str(output_path)))
    await capture.wait_for_result()
    for _ in range(4):
        await omni.kit.app.get_app().next_update_async()
    if not output_path.is_file():
        raise RuntimeError(f"Viewport capture did not create {output_path}")


async def main():
    start_demo_script = REPO_ROOT / "omniverse" / "cctv_sim" / "scripts" / "start_demo.py"
    opened = omni.usd.get_context().open_stage(str(STAGE_PATH))
    print(f"[capture_drone_rig_debug] open_stage={opened}")

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
        raise RuntimeError("DroneRig not available")

    demo_app.switch_follow_camera_to_perspective()
    demo_app.move_follow_top_camera_to_stage_xy(-2200.0, 8400.0, bind_viewport=False, duration_sec=1.5)
    for _ in range(90):
        await omni.kit.app.get_app().next_update_async()

    _set_active_viewport_camera("/OmniverseKit_Persp")
    print(f"[capture_drone_rig_debug] rig={rig.describe()}")
    print(f"[capture_drone_rig_debug] camera_invisible={rig.is_camera_invisible()}")
    await _capture(PERSPECTIVE_PATH)

    ok, message = demo_app.bind_follow_top_camera_viewport()
    print(f"[capture_drone_rig_debug] {message}")
    await _capture(TOPVIEW_PATH)

    print(f"[capture_drone_rig_debug] perspective={PERSPECTIVE_PATH}")
    print(f"[capture_drone_rig_debug] topview={TOPVIEW_PATH}")
    omni.kit.app.get_app().post_quit()


asyncio.ensure_future(main())
