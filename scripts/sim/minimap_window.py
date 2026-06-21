import math

import omni.kit.app
import omni.ui as ui
from pxr import Gf, Sdf, UsdGeom

from .config import (
    CCTV_ROOT_PATH,
    MINIMAP_CAMERA_CLIPPING_RANGE,
    MINIMAP_CAMERA_PATH,
    MINIMAP_MAP_HEIGHT,
    MINIMAP_MAP_WIDTH,
    MINIMAP_MAX_FPS,
    MINIMAP_UPDATE_INTERVAL_SEC,
    MINIMAP_WINDOW_HEIGHT,
    MINIMAP_WINDOW_TITLE,
    MINIMAP_WINDOW_WIDTH,
)
from .usd_utils import get_or_create_transform_ops, get_stage


def hide_existing_window(title):
    return


class MinimapWindow:
    MAP_WIDTH = MINIMAP_MAP_WIDTH
    MAP_HEIGHT = MINIMAP_MAP_HEIGHT
    STATUS_WIDTH = 240
    PANEL_STYLE = {"background_color": 0xFF11151A}
    MAP_STYLE = {"background_color": 0xFF020703}
    MAP_GRID_STYLE = {"background_color": 0x6633FF66}
    HEADER_STYLE = {"color": 0xFFFFFFFF, "font_size": 18}
    LABEL_STYLE = {"color": 0xFFE9EEF5, "font_size": 14}
    MUTED_LABEL_STYLE = {"color": 0xFF9EA7B3, "font_size": 13}
    BADGE_STYLE = {"background_color": 0xFF313A45, "color": 0xFFFFFFFF, "font_size": 13}
    CCTV_DOT_STYLE = {"background_color": 0xFFFF7A00}
    DRONE_DOT_STYLE = {"background_color": 0xFF2F8FFF}
    CCTV_CONE_STYLE = {"background_color": 0x263CFFD8}
    WARNING_STYLE = {"color": 0xFFFFB347, "font_size": 12}
    MAP_CONE_LENGTH = 82.0
    MAP_CONE_STEPS = 8
    MAP_CONE_START_DIAMETER = 10.0
    MAP_CONE_END_DIAMETER = 58.0
    CAMERA_HEIGHT = 8000.0
    CAMERA_APERTURE_SCALE = 10.0

    def __init__(self, app):
        self.app = app
        self.window = None
        self.viewport_widget_cls = None
        self.viewport_widgets = []
        self.is_y_up = False
        self.map_camera_path = MINIMAP_CAMERA_PATH
        self.map_bounds = None
        self.cctv_rows = []
        self.drone_position = None
        self.panel_refresh_elapsed = float(MINIMAP_UPDATE_INTERVAL_SEC)
        self.summary_frame = None
        self.map_overlay_frame = None
        self.status_frame = None
        self.error_text = ""
        self._snapshot_signature = None

    def setup(self):
        try:
            stage = get_stage()
        except RuntimeError:
            return

        self.is_y_up = self._is_y_up_stage(stage)
        self.viewport_widget_cls = self._load_viewport_widget_cls()
        self._refresh_scene_state(force_reframe=True)

    def show(self):
        self.destroy()
        hide_existing_window(MINIMAP_WINDOW_TITLE)
        self.setup()
        self.window = ui.Window(
            MINIMAP_WINDOW_TITLE,
            width=MINIMAP_WINDOW_WIDTH,
            height=MINIMAP_WINDOW_HEIGHT,
            visible=True,
            dockPreference=ui.DockPreference.RIGHT_BOTTOM,
        )
        self.window.frame.set_build_fn(self._build_standalone)
        self.window.frame.rebuild()

    def destroy(self):
        self._destroy_viewport_widgets()
        self.summary_frame = None
        self.map_overlay_frame = None
        self.status_frame = None
        if self.window is not None:
            self.window.visible = False
            self.window = None

    def update(self, dt):
        self.panel_refresh_elapsed += max(float(dt), 0.0)
        if self.panel_refresh_elapsed < float(MINIMAP_UPDATE_INTERVAL_SEC):
            return None

        self.panel_refresh_elapsed = 0.0
        changed = self._refresh_scene_state(force_reframe=False)
        if not changed:
            return None

        self._rebuild_live_frames()
        return None

    def build_embedded_panel(self):
        self._destroy_viewport_widgets()
        self.summary_frame = None
        self.map_overlay_frame = None
        self.status_frame = None
        self.setup()
        with ui.VStack(spacing=8, height=0, style=self.PANEL_STYLE):
            ui.Label("Stage Minimap", height=28, style=self.HEADER_STYLE)
            self.summary_frame = ui.Frame(height=24)
            self._build_frame(self.summary_frame, self._build_summary)
            with ui.HStack(spacing=10, height=self.MAP_HEIGHT):
                self._build_map()
                self.status_frame = ui.Frame(width=self.STATUS_WIDTH, height=self.MAP_HEIGHT)
                self._build_frame(self.status_frame, self._build_status)

    def _build_standalone(self):
        with ui.VStack(spacing=8, height=0, style=self.PANEL_STYLE):
            self.build_embedded_panel()

    def _refresh_scene_state(self, force_reframe=False):
        try:
            stage = get_stage()
        except RuntimeError as exc:
            self.error_text = str(exc)
            return False

        self.is_y_up = self._is_y_up_stage(stage)
        self.cctv_rows = self._load_cctv_rows(stage)
        self.drone_position = self._load_drone_position()
        new_bounds = self._compute_map_bounds(self.cctv_rows, self.drone_position)
        bounds_changed = force_reframe or new_bounds != self.map_bounds
        self.map_bounds = new_bounds
        self._setup_map_camera(stage)
        signature = self._snapshot_signature_for()
        changed = signature != self._snapshot_signature or bounds_changed
        self._snapshot_signature = signature
        self.error_text = ""
        return changed

    def _snapshot_signature_for(self):
        return (
            self.map_bounds,
            tuple(
                (
                    row.get("name"),
                    row.get("status"),
                    None if row.get("position") is None else tuple(round(float(v), 1) for v in row.get("position")),
                    None if row.get("view_yaw") is None else round(float(row.get("view_yaw")), 1),
                )
                for row in self.cctv_rows
            ),
            None if self.drone_position is None else tuple(round(float(v), 1) for v in self.drone_position),
        )

    def _build_frame(self, frame, build_fn):
        try:
            frame.set_build_fn(build_fn)
            frame.rebuild()
            return True
        except Exception:
            try:
                with frame:
                    build_fn()
                return True
            except Exception as exc:
                self.error_text = str(exc)
                print(f"[cctv_sim] minimap frame build failed: {exc}")
                return False

    def _rebuild_live_frames(self):
        if self.summary_frame is not None:
            self._build_frame(self.summary_frame, self._build_summary)
        if self.map_overlay_frame is not None:
            self._build_frame(self.map_overlay_frame, self._build_map_overlay_frame)
        if self.status_frame is not None:
            self._build_frame(self.status_frame, self._build_status)
        if self.window is not None:
            self.window.frame.rebuild()

    def _build_summary(self):
        drone_state = "active" if self.drone_position is not None else "offline"
        ui.Label(
            f"CCTV {len(self.cctv_rows)} | drone {drone_state}",
            height=24,
            style=self.LABEL_STYLE,
        )

    def _build_map(self):
        with ui.ZStack(width=self.MAP_WIDTH, height=self.MAP_HEIGHT):
            self._build_map_background()
            self.map_overlay_frame = ui.Frame(width=self.MAP_WIDTH, height=self.MAP_HEIGHT)
            self._build_frame(self.map_overlay_frame, self._build_map_overlay_frame)

    def _build_map_background(self):
        if self.viewport_widget_cls is not None:
            try:
                widget_kwargs = {
                    "camera_path": self.map_camera_path,
                    "resolution": (self.MAP_WIDTH, self.MAP_HEIGHT),
                    "width": self.MAP_WIDTH,
                    "height": self.MAP_HEIGHT,
                }
                hydra_options = self._map_hydra_engine_options()
                if hydra_options:
                    widget_kwargs["hydra_engine_options"] = hydra_options
                widget = self.viewport_widget_cls(**widget_kwargs)
                self.viewport_widgets.append(widget)
                return
            except Exception as exc:
                print(f"[cctv_sim] minimap viewport unavailable, using radar fallback: {exc}")

        ui.Rectangle(width=self.MAP_WIDTH, height=self.MAP_HEIGHT, style=self.MAP_STYLE)
        self._build_map_reticle()

    def _build_map_overlay_frame(self):
        with ui.ZStack(width=self.MAP_WIDTH, height=self.MAP_HEIGHT):
            self._build_map_overlay()

    def _build_map_overlay(self):
        bounds = self._map_bounds()
        for row in self.cctv_rows:
            self._build_cctv_view_cone(row, bounds)

        for row in self.cctv_rows:
            position = row.get("position")
            if position is None:
                continue
            x, y = self._map_point(position, bounds)
            self._build_ui_circle(x, y, 14, self.CCTV_DOT_STYLE)
            name = row.get("name", "CCTV")
            with ui.Placer(
                offset_x=self._clamp(x + 10, 0, self.MAP_WIDTH - 70),
                offset_y=self._clamp(y - 10, 0, self.MAP_HEIGHT - 18),
                width=70,
                height=18,
                stable_size=True,
            ):
                ui.Label(name, width=70, height=18, style=self.MUTED_LABEL_STYLE)

        if self.drone_position is not None:
            x, y = self._map_point(self.drone_position, bounds)
            self._build_ui_circle(x, y, 18, self.DRONE_DOT_STYLE)
            with ui.Placer(
                offset_x=self._clamp(x + 12, 0, self.MAP_WIDTH - 72),
                offset_y=self._clamp(y - 12, 0, self.MAP_HEIGHT - 20),
                width=72,
                height=20,
                stable_size=True,
            ):
                ui.Label("DRONE", width=72, height=20, style=self.LABEL_STYLE)

        with ui.Placer(offset_x=8, offset_y=8, width=120, height=24, stable_size=True):
            ui.Label(
                "CCTV + DRONE",
                width=120,
                height=24,
                alignment=ui.Alignment.CENTER,
                style=self.BADGE_STYLE,
            )

    def _build_status(self):
        with ui.VStack(spacing=4, width=self.STATUS_WIDTH, height=self.MAP_HEIGHT):
            ui.Label("Tracking", height=24, style=self.HEADER_STYLE)
            if self.error_text:
                ui.Label(self.error_text, height=20, style=self.WARNING_STYLE)
            if self.drone_position is not None:
                ui.Label(
                    f"Drone ({self.drone_position[0]:.1f}, {self.drone_position[1]:.1f}, {self.drone_position[2]:.1f})",
                    height=20,
                    style=self.LABEL_STYLE,
                )
            else:
                ui.Label("Drone unavailable", height=20, style=self.MUTED_LABEL_STYLE)

            if not self.cctv_rows:
                ui.Label("No CCTV prims found under /World/CCTV.", height=20, style=self.MUTED_LABEL_STYLE)
                return

            for row in self.cctv_rows:
                distance = row.get("distance")
                distance_text = "-" if distance is None else f"{float(distance):.0f}m"
                ui.Label(
                    f"{row.get('name', 'CCTV')}  {self._status_text(row.get('status', 'idle'))}  {distance_text}",
                    height=20,
                    style=self.MUTED_LABEL_STYLE,
                )

    def _load_cctv_rows(self, stage):
        manager = getattr(self.app, "cctv", None)
        if manager is not None:
            try:
                rows = manager.get_tracking_snapshot()
                if rows:
                    return rows
            except Exception as exc:
                print(f"[cctv_sim] minimap CCTV snapshot failed: {exc}")

        root = stage.GetPrimAtPath(CCTV_ROOT_PATH)
        if not root.IsValid():
            return []

        rows = []
        for child in root.GetChildren():
            if not child.IsValid():
                continue
            position = self._world_position(child)
            rows.append(
                {
                    "name": child.GetName(),
                    "root_path": str(child.GetPath()),
                    "status": "idle",
                    "position": position,
                }
            )
        return rows

    def _load_drone_position(self):
        controller = getattr(self.app, "follow_top_camera", None)
        if controller is None:
            return None
        try:
            stage_xy, height = controller.get_current_stage_xy_height()
        except Exception:
            return None

        if self.is_y_up:
            return (float(stage_xy[0]), float(height), float(stage_xy[1]))
        return (float(stage_xy[0]), float(stage_xy[1]), float(height))

    def _compute_map_bounds(self, rows, drone_position):
        points = []
        for row in rows:
            position = row.get("position")
            if position is not None:
                points.append(self._horizontal_point(position))
        if drone_position is not None:
            points.append(self._horizontal_point(drone_position))

        if not points:
            return (-200.0, -200.0, 200.0, 200.0)

        min_x = min(point[0] for point in points)
        max_x = max(point[0] for point in points)
        min_y = min(point[1] for point in points)
        max_y = max(point[1] for point in points)
        span = max(max_x - min_x, max_y - min_y, 1.0)
        padding = max(60.0, span * 0.18)
        return self._fit_bounds_to_map_aspect((min_x - padding, min_y - padding, max_x + padding, max_y + padding))

    def _fit_bounds_to_map_aspect(self, bounds):
        min_x, min_y, max_x, max_y = bounds
        width = max(max_x - min_x, 1.0)
        height = max(max_y - min_y, 1.0)
        target_aspect = self.MAP_WIDTH / max(self.MAP_HEIGHT, 1)
        current_aspect = width / height
        center_x = (min_x + max_x) * 0.5
        center_y = (min_y + max_y) * 0.5

        if current_aspect < target_aspect:
            width = height * target_aspect
        else:
            height = width / target_aspect

        return (
            center_x - width * 0.5,
            center_y - height * 0.5,
            center_x + width * 0.5,
            center_y + height * 0.5,
        )

    def _map_bounds(self):
        return self.map_bounds or (-200.0, -200.0, 200.0, 200.0)

    def _setup_map_camera(self, stage):
        min_x, min_y, max_x, max_y = self._map_bounds()
        center_x = (min_x + max_x) * 0.5
        center_y = (min_y + max_y) * 0.5
        width = max(max_x - min_x, 1.0)
        height = max(max_y - min_y, 1.0)

        camera = UsdGeom.Camera.Define(stage, Sdf.Path(self.map_camera_path))
        camera.CreateProjectionAttr().Set(UsdGeom.Tokens.orthographic)
        camera.CreateHorizontalApertureAttr().Set(float(width) * self.CAMERA_APERTURE_SCALE)
        camera.CreateVerticalApertureAttr().Set(float(height) * self.CAMERA_APERTURE_SCALE)
        camera.CreateHorizontalApertureOffsetAttr().Set(0.0)
        camera.CreateVerticalApertureOffsetAttr().Set(0.0)
        camera.CreateClippingRangeAttr().Set(Gf.Vec2f(*MINIMAP_CAMERA_CLIPPING_RANGE))

        xform = UsdGeom.Xformable(camera.GetPrim())
        translate_op, rotate_op, scale_op = get_or_create_transform_ops(xform)
        if self.is_y_up:
            translate_op.Set(Gf.Vec3d(center_x, self.CAMERA_HEIGHT, center_y))
            rotate_op.Set(Gf.Vec3f(-90.0, 0.0, 0.0))
        else:
            translate_op.Set(Gf.Vec3d(center_x, center_y, self.CAMERA_HEIGHT))
            rotate_op.Set(Gf.Vec3f(0.0, 0.0, 0.0))
        scale_op.Set(Gf.Vec3f(1.0, 1.0, 1.0))

    def _load_viewport_widget_cls(self):
        try:
            from omni.kit.widget.viewport import ViewportWidget

            return ViewportWidget
        except Exception:
            pass

        try:
            manager = omni.kit.app.get_app().get_extension_manager()
            manager.set_extension_enabled_immediate("omni.kit.widget.viewport", True)
            from omni.kit.widget.viewport import ViewportWidget

            return ViewportWidget
        except Exception as exc:
            print(f"[cctv_sim] minimap viewport widget unavailable: {exc}")
            return None

    def _map_hydra_engine_options(self):
        try:
            fps = float(MINIMAP_MAX_FPS)
        except (TypeError, ValueError):
            return None
        if fps <= 0.0:
            return None
        return {"hydra_tick_rate": int(round(fps))}

    def _destroy_viewport_widgets(self):
        for widget in list(self.viewport_widgets):
            try:
                destroy = getattr(widget, "destroy", None)
                if destroy is not None:
                    destroy()
            except Exception:
                pass
        self.viewport_widgets = []

    def _build_cctv_view_cone(self, row, bounds):
        position = row.get("position")
        view_yaw = row.get("view_yaw")
        if position is None or view_yaw is None:
            return

        start_x, start_y = self._map_point(position, bounds)
        angle = math.radians(float(view_yaw))
        target_world = self._offset_horizontal_position(position, math.cos(angle), math.sin(angle), 1000.0)
        target_x, target_y = self._map_point(target_world, bounds, clamp=False)
        direction_x = target_x - start_x
        direction_y = target_y - start_y
        direction_len = math.sqrt(direction_x * direction_x + direction_y * direction_y)
        if direction_len < 1e-6:
            return

        direction_x /= direction_len
        direction_y /= direction_len

        for index in range(1, self.MAP_CONE_STEPS + 1):
            t = index / self.MAP_CONE_STEPS
            center_x = start_x + direction_x * self.MAP_CONE_LENGTH * t
            center_y = start_y + direction_y * self.MAP_CONE_LENGTH * t
            diameter = self.MAP_CONE_START_DIAMETER + (self.MAP_CONE_END_DIAMETER - self.MAP_CONE_START_DIAMETER) * t
            if not self._circle_fits_map(center_x, center_y, diameter):
                continue
            self._build_ui_circle(center_x, center_y, diameter, self.CCTV_CONE_STYLE)

    def _build_map_reticle(self):
        grid_width = 1
        for x in range(50, self.MAP_WIDTH, 50):
            with ui.Placer(offset_x=x, offset_y=0, width=grid_width, height=self.MAP_HEIGHT, stable_size=True):
                ui.Rectangle(width=grid_width, height=self.MAP_HEIGHT, style=self.MAP_GRID_STYLE)
        for y in range(40, self.MAP_HEIGHT, 40):
            with ui.Placer(offset_x=0, offset_y=y, width=self.MAP_WIDTH, height=grid_width, stable_size=True):
                ui.Rectangle(width=self.MAP_WIDTH, height=grid_width, style=self.MAP_GRID_STYLE)

    def _build_ui_circle(self, center_x, center_y, diameter, style):
        circle_cls = getattr(ui, "Circle", None)
        widget_cls = circle_cls or ui.Rectangle
        widget_style = dict(style)
        if circle_cls is None:
            widget_style["border_radius"] = diameter * 0.5

        with ui.Placer(
            offset_x=center_x - diameter * 0.5,
            offset_y=center_y - diameter * 0.5,
            width=diameter,
            height=diameter,
            stable_size=True,
        ):
            widget_cls(width=diameter, height=diameter, style=widget_style)

    def _map_point(self, position, bounds, clamp=True):
        min_x, min_y, max_x, max_y = bounds
        x, y = self._horizontal_point(position)
        nx = (x - min_x) / max(max_x - min_x, 1e-6)
        ny = (y - min_y) / max(max_y - min_y, 1e-6)
        map_x = nx * self.MAP_WIDTH
        map_y = (1.0 - ny) * self.MAP_HEIGHT
        if not clamp:
            return map_x, map_y
        return (
            self._clamp(map_x, 0, self.MAP_WIDTH),
            self._clamp(map_y, 0, self.MAP_HEIGHT),
        )

    def _horizontal_point(self, position):
        if self.is_y_up:
            return (float(position[0]), float(position[2]))
        return (float(position[0]), float(position[1]))

    def _offset_horizontal_position(self, position, dx, dy, distance):
        if self.is_y_up:
            return (
                float(position[0]) + dx * distance,
                float(position[1]),
                float(position[2]) + dy * distance,
            )
        return (
            float(position[0]) + dx * distance,
            float(position[1]) + dy * distance,
            float(position[2]),
        )

    def _circle_fits_map(self, center_x, center_y, diameter):
        radius = diameter * 0.5
        return (
            center_x + radius >= 0
            and center_x - radius <= self.MAP_WIDTH
            and center_y + radius >= 0
            and center_y - radius <= self.MAP_HEIGHT
        )

    def _status_text(self, status):
        return {
            "tracking": "TRACKING",
            "aim": "AIMING",
            "hold": "HOLDING",
            "return": "RETURN",
            "returning": "RETURN",
            "out_of_range": "OUT",
            "not_connected": "OFFLINE",
            "idle": "IDLE",
        }.get(status, str(status).upper())

    def _clamp(self, value, min_value, max_value):
        return max(min_value, min(max_value, value))

    def _world_position(self, prim):
        matrix = UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(UsdGeom.XformCache().GetTime())
        position = matrix.ExtractTranslation()
        return (float(position[0]), float(position[1]), float(position[2]))

    def _is_y_up_stage(self, stage):
        try:
            return UsdGeom.GetStageUpAxis(stage) == UsdGeom.Tokens.y
        except Exception:
            return False
