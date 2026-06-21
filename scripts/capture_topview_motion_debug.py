import asyncio
import builtins
from pathlib import Path
import sys

import omni.kit.app
import omni.usd
from omni.kit.widget.viewport.capture import FileCapture
from omni.kit.viewport.utility import get_active_viewport_window


REPO_ROOT = Path("/home/user/Documents/DT_teamA")
sys.path.insert(0, str(REPO_ROOT / "omniverse" / "cctv_sim"))

OUTPUT_DIR = REPO_ROOT / "pictures"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
BEFORE_PATH = OUTPUT_DIR / "codex_topview_motion_before.png"
AFTER_PATH = OUTPUT_DIR / "codex_topview_motion_after.png"
STAGE_PATH = REPO_ROOT / "omniverse" / "cctv_sim" / "assets" / "city" / "World_CityDemopack.usd"


def _exec_script(script_path):
    namespace = {
        "__name__": "__main__",
        "__file__": str(script_path),
    }
    exec(compile(script_path.read_text(encoding="utf-8"), str(script_path), "exec"), namespace)
    return namespace


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
    print(f"[capture_topview_motion_debug] open_stage={opened}")

    for _ in range(180):
        await omni.kit.app.get_app().next_update_async()
        stage = omni.usd.get_context().get_stage()
        if stage is not None and stage.GetPrimAtPath("/World").IsValid():
            break
    else:
        raise RuntimeError("Stage did not finish loading")

    _exec_script(start_demo_script)
    for _ in range(30):
        await omni.kit.app.get_app().next_update_async()

    demo_app = getattr(builtins, "demo_app", None)
    if demo_app is None:
        raise RuntimeError("demo_app not available")

    ok, message = demo_app.bind_follow_top_camera_viewport()
    print(f"[capture_topview_motion_debug] {message}")
    controller = demo_app.follow_top_camera
    print(f"[capture_topview_motion_debug] before_state={controller.describe()}")
    await _capture(BEFORE_PATH)

    demo_app.move_follow_top_camera_to_stage_xy(-2200.0, 8400.0, bind_viewport=False)
    for _ in range(90):
        await omni.kit.app.get_app().next_update_async()

    print(f"[capture_topview_motion_debug] after_state={controller.describe()}")
    await _capture(AFTER_PATH)
    print(f"[capture_topview_motion_debug] before={BEFORE_PATH}")
    print(f"[capture_topview_motion_debug] after={AFTER_PATH}")
    omni.kit.app.get_app().post_quit()


asyncio.ensure_future(main())
