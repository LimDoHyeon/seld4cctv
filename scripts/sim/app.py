import omni.kit.app

from .awareness import SituationAwarenessManager
from .cctv import CCTVManager
from .characters import CharacterManager
from .events import EventManager
from .follow_top_camera import ensure_follow_top_camera_controller, switch_to_perspective
from .config import FOLLOW_TOP_CAMERA_AUTO_BIND_ON_START, FOLLOW_TOP_CAMERA_AUTO_TRACK_EVENTS
from .minimap_core import compute_stage_overview_extent
from .monitor import CCTVMonitorWindow
from .scene import SceneManager
from .ui import DemoWindow


class DemoApp:
    def __init__(self):
        self.scene = SceneManager()
        self.characters = CharacterManager()
        self.events = EventManager()
        self.cctv = CCTVManager()
        self.awareness = SituationAwarenessManager(self)
        self.window = None
        self.monitor_window = None
        self.subscription = None
        self.follow_top_camera = None
        self.follow_top_camera_auto_track = bool(FOLLOW_TOP_CAMERA_AUTO_TRACK_EVENTS)
        self.follow_target_character_path = None

    def start(self):
        self.stop()

        self.scene.setup()
        self.characters.setup()
        self.events.setup()
        self.cctv.setup()
        self.follow_top_camera = ensure_follow_top_camera_controller()
        if FOLLOW_TOP_CAMERA_AUTO_BIND_ON_START:
            ok, message = self.follow_top_camera.bind_to_active_viewport()
            print(f"[cctv_sim] {message}")
        self.awareness.setup()
        self.window = DemoWindow(self)
        self.window.show()
        self.monitor_window = CCTVMonitorWindow(self)
        self.monitor_window.show()

        self.subscription = omni.kit.app.get_app().get_update_event_stream().create_subscription_to_pop(
            self.on_update,
            name="cctv_sim_demo_app",
        )

    def stop(self):
        if self.subscription is not None:
            self.subscription = None

        if self.window is not None:
            self.window.destroy()
            self.window = None

        if self.monitor_window is not None:
            self.monitor_window.destroy()
            self.monitor_window = None

        if hasattr(self, "characters"):
            self.characters.stop()
        if hasattr(self, "events"):
            self.events.stop()
        if hasattr(self, "cctv"):
            self.cctv.stop()
        if hasattr(self, "awareness"):
            self.awareness.stop()
        self.follow_top_camera = None
        self.follow_target_character_path = None

    def on_update(self, event):
        dt = event.payload.get("dt", 1.0 / 60.0)

        self.characters.update(dt)
        self.events.update(dt)
        self.cctv.update(dt)
        if self.follow_top_camera is not None:
            self.follow_top_camera.update(dt)
        self._update_follow_target_character()
        if hasattr(self, "awareness"):
            self.awareness.update(dt)
        if self.monitor_window is not None:
            self.monitor_window.update(dt)

    def set_follow_top_camera_auto_track(self, enabled):
        self.follow_top_camera_auto_track = bool(enabled)
        return self.follow_top_camera_auto_track

    def bind_follow_top_camera_viewport(self):
        controller = self._ensure_follow_top_camera()
        stage = self.scene._stage if hasattr(self.scene, "_stage") else None
        if stage is None:
            from .usd_utils import get_stage

            stage = get_stage()
        if not controller.has_target_position:
            controller.center_stage_extent(
                compute_stage_overview_extent(stage),
                height=controller.fixed_height,
            )
        ok, message = controller.bind_to_active_viewport()
        if ok:
            return ok, message

        drone_rig = getattr(controller, "drone_rig", None)
        if drone_rig is not None:
            try:
                fallback_ok = drone_rig.look_through_camera()
                if fallback_ok:
                    return True, f"Viewport camera: {controller.camera_path}"
            except Exception as exc:
                return False, f"{message}; fallback failed: {exc}"
        return ok, message

    def switch_follow_camera_to_perspective(self):
        return switch_to_perspective()

    def move_follow_top_camera_to_stage_xy(self, stage_x, stage_y, bind_viewport=False, duration_sec=None):
        controller = self._ensure_follow_top_camera()
        updated = controller.move_toward_stage_xy_with_duration(stage_x, stage_y, duration_sec=duration_sec)
        if bind_viewport:
            controller.bind_to_active_viewport()
        return updated

    def follow_event_position(self, position, bind_viewport=False, duration_sec=None):
        if position is None:
            return None

        controller = self._ensure_follow_top_camera()
        updated = controller.move_toward_world_position_with_duration(position, duration_sec=duration_sec)
        if bind_viewport:
            controller.bind_to_active_viewport()
        return updated

    def focus_event_position_immediate_with_zoom(self, position, bind_viewport=False, duration_sec=None):
        if position is None:
            return None

        controller = self._ensure_follow_top_camera()
        updated = controller.focus_world_position_immediate_with_zoom(position, duration_sec=duration_sec)
        if bind_viewport:
            controller.bind_to_active_viewport()
        return updated

    def track_event_position_if_enabled(self, position, bind_viewport=False, duration_sec=None):
        if not self.follow_top_camera_auto_track:
            return None
        return self.follow_event_position(position, bind_viewport=bind_viewport, duration_sec=duration_sec)

    def start_following_character(self, character_path):
        self.follow_target_character_path = character_path or None
        return self.follow_target_character_path

    def stop_following_character(self, character_path=None):
        if character_path is None or self.follow_target_character_path == character_path:
            self.follow_target_character_path = None
            try:
                self._ensure_follow_top_camera().restore_default_zoom(immediate=False)
            except Exception:
                pass
        return self.follow_target_character_path

    def _ensure_follow_top_camera(self):
        if self.follow_top_camera is None:
            self.follow_top_camera = ensure_follow_top_camera_controller()
        return self.follow_top_camera

    def _update_follow_target_character(self):
        if not self.follow_target_character_path or not self.follow_top_camera_auto_track:
            return

        controller = self.characters.get_controller(self.follow_target_character_path)
        if controller is None or controller.should_remove:
            try:
                self._ensure_follow_top_camera().restore_default_zoom(immediate=False)
            except Exception:
                pass
            self.follow_target_character_path = None
            return

        try:
            self._ensure_follow_top_camera().move_toward_world_position_preserving_zoom(
                controller.get_position(),
            )
        except Exception:
            self.follow_target_character_path = None
