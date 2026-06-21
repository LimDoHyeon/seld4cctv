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

from scripts.sim.minimap_core import compute_stage_overview_extent

OUTPUT_DIR = REPO_ROOT / "pictures"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
TOPVIEW_CAPTURE_PATH = OUTPUT_DIR / "codex_topview_capture.png"
PERSPECTIVE_CAPTURE_PATH = OUTPUT_DIR / "codex_perspective_capture.png"
CITYDEMOPACK_STAGE_PATH = REPO_ROOT / "omniverse" / "cctv_sim" / "assets" / "city" / "World_CityDemopack.usd"


def _exec_script(script_path, extra_globals=None):
    namespace = {
        "__name__": "__main__",
        "__file__": str(script_path),
    }
    if extra_globals:
        namespace.update(extra_globals)
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


async def _capture_active_viewport(output_path):
    viewport_window = get_active_viewport_window()
    if viewport_window is None or not hasattr(viewport_window, "viewport_api"):
        raise RuntimeError("Active viewport window is unavailable")

    viewport_api = viewport_window.viewport_api
    viewport_api.resolution = (1280, 720)
    await viewport_api.wait_for_rendered_frames(6)
    capture = viewport_api.schedule_capture(FileCapture(str(output_path)))
    await capture.wait_for_result()

    for _ in range(4):
        await asyncio.sleep(0)
        await omni.kit.app.get_app().next_update_async()

    if not output_path.is_file():
        raise RuntimeError(f"Viewport capture did not create {output_path}")


async def main():
    start_demo_script = REPO_ROOT / "omniverse" / "cctv_sim" / "scripts" / "start_demo.py"
    if not CITYDEMOPACK_STAGE_PATH.is_file():
        raise FileNotFoundError(CITYDEMOPACK_STAGE_PATH)

    opened = omni.usd.get_context().open_stage(str(CITYDEMOPACK_STAGE_PATH))
    print(f"[capture_topview_debug] open_stage={opened} path={CITYDEMOPACK_STAGE_PATH}")

    usd_context = omni.usd.get_context()
    for _ in range(180):
        await omni.kit.app.get_app().next_update_async()
        stage = usd_context.get_stage()
        if stage is not None and stage.GetPrimAtPath("/World").IsValid():
            break
    else:
        raise RuntimeError("Stage did not finish loading")

    _exec_script(start_demo_script)
    await omni.kit.app.get_app().next_update_async()
    for _ in range(30):
        await omni.kit.app.get_app().next_update_async()

    demo_app = getattr(builtins, "demo_app", None) or globals().get("demo_app")
    if demo_app is None:
        raise RuntimeError("demo_app not available after start_demo")

    overview_extent = compute_stage_overview_extent(usd_context.get_stage())
    print(
        "[capture_topview_debug] overview_extent="
        f"({overview_extent.min_x:.1f}, {overview_extent.max_x:.1f}, "
        f"{overview_extent.min_y:.1f}, {overview_extent.max_y:.1f})"
    )

    ok, message = demo_app.switch_follow_camera_to_perspective()
    print(f"[capture_topview_debug] {message}")
    await _capture_active_viewport(PERSPECTIVE_CAPTURE_PATH)

    ok, message = demo_app.bind_follow_top_camera_viewport()
    print(f"[capture_topview_debug] {message}")
    follow_controller = getattr(demo_app, "follow_top_camera", None)
    if follow_controller is not None:
        print(f"[capture_topview_debug] follow_top_camera={follow_controller.describe()}")
    await _capture_active_viewport(TOPVIEW_CAPTURE_PATH)

    print(f"[capture_topview_debug] perspective={PERSPECTIVE_CAPTURE_PATH}")
    print(f"[capture_topview_debug] topview={TOPVIEW_CAPTURE_PATH}")
    omni.kit.app.get_app().post_quit()


asyncio.ensure_future(main())
