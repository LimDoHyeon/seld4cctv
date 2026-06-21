import omni.usd
from pxr import UsdGeom

from .config import (
    CCTV_ROOT_PATH,
    CHARACTER_ROOT_PATH,
    EVENT_ROOT_PATH,
    MICROPHONE_ROOT_PATH,
    PEDESTRIAN_ROOT_PATH,
    SOUND_SOURCE_MARKER_ROOT_PATH,
    SOURCE_ROOT_PATH,
    VEHICLE_ROOT_PATH,
)
from .usd_utils import ensure_xform


class SceneManager:
    def setup(self):
        stage = omni.usd.get_context().get_stage()
        if stage is None:
            print("[cctv_sim] No active stage. Open or create a stage before adding demo objects.")
            return

        had_world = stage.GetPrimAtPath("/World").IsValid()
        ensure_xform(stage, "/World")
        for path in (
            CHARACTER_ROOT_PATH,
            EVENT_ROOT_PATH,
            CCTV_ROOT_PATH,
            SOURCE_ROOT_PATH,
            SOUND_SOURCE_MARKER_ROOT_PATH,
            MICROPHONE_ROOT_PATH,
            VEHICLE_ROOT_PATH,
            PEDESTRIAN_ROOT_PATH,
        ):
            ensure_xform(stage, path)

        if not had_world:
            try:
                UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
            except Exception as exc:
                print(f"[cctv_sim] Failed to set stage up-axis: {exc}")
