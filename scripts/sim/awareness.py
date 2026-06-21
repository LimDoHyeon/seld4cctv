from datetime import datetime
import math

import omni.ui as ui
from pxr import Gf, Sdf, UsdGeom

from .config import (
    AWARENESS_CCTV_LINK_OPACITY,
    AWARENESS_CCTV_LINK_WIDTH_M,
    AWARENESS_EVENT_HISTORY_LIMIT,
    AWARENESS_EVENT_MARKER_OPACITY,
    AWARENESS_EVENT_UI_OPACITY,
    AWARENESS_EVENT_VISIBLE_SEC,
    AWARENESS_LINK_HEIGHT_M,
    AWARENESS_MAP_CAMERA_APERTURE_SCALE,
    AWARENESS_MAP_CAMERA_CLIPPING_RANGE,
    AWARENESS_MAP_CAMERA_HEIGHT_M,
    AWARENESS_MAP_CAMERA_PATH,
    AWARENESS_MAP_HEIGHT,
    AWARENESS_MAP_VIEWPORT_FPS,
    AWARENESS_MAP_WIDTH,
    AWARENESS_MARKER_RADIUS_M,
    AWARENESS_PULSE_MAX_RADIUS_M,
    AWARENESS_PULSE_FILL_HEIGHT_M,
    AWARENESS_PULSE_FILL_OPACITY,
    AWARENESS_PULSE_MIN_RADIUS_M,
    AWARENESS_PULSE_PERIOD_SEC,
    AWARENESS_ROOT_PATH,
    AWARENESS_PANEL_REFRESH_SEC,
    SOUND_DETECTION_RADIUS_M,
)
from .usd_utils import ensure_xform, get_or_create_transform_ops, get_stage, next_free_path


WINDOW_TITLE = "Situation Overview"

EVENT_COLORS = {
    "yell": (1.0, 0.86, 0.15),
    "crash": (1.0, 0.35, 0.15),
    "explosion": (1.0, 0.08, 0.02),
    "gun": (0.25, 0.55, 1.0),
}

EVENT_UI_COLORS = {
    "yell": (AWARENESS_EVENT_UI_OPACITY << 24) | 0x00FFD54F,
    "crash": (AWARENESS_EVENT_UI_OPACITY << 24) | 0x00FF7043,
    "explosion": (AWARENESS_EVENT_UI_OPACITY << 24) | 0x00FF2D2D,
    "gun": (AWARENESS_EVENT_UI_OPACITY << 24) | 0x004DA3FF,
}

STATUS_UI_COLORS = {
    "tracking": 0xFF35C66B,
    "aim": 0xFF35C66B,
    "hold": 0xFF35C66B,
    "return": 0xFFFFC857,
    "returning": 0xFFFFC857,
    "out_of_range": 0xFF9EA7B3,
    "idle": 0xFF6CA6FF,
    "not_connected": 0xFFFF5C5C,
}


def hide_existing_window(title):
    return


class SituationAwarenessManager:
    MAP_WIDTH = AWARENESS_MAP_WIDTH
    MAP_HEIGHT = AWARENESS_MAP_HEIGHT
    STATUS_WIDTH = 390
    ROW_HEIGHT = 24
    PANEL_STYLE = {"background_color": 0xFF11151A}
    MAP_STYLE = {"background_color": 0xFF020703}
    MAP_GRID_STYLE = {"background_color": 0x6633FF66}
    LABEL_STYLE = {"color": 0xFFE9EEF5, "font_size": 14}
    MUTED_LABEL_STYLE = {"color": 0xFF9EA7B3, "font_size": 13}
    HEADER_STYLE = {"color": 0xFFFFFFFF, "font_size": 18}
    SMALL_HEADER_STYLE = {"color": 0xFFFFFFFF, "font_size": 15}
    BADGE_STYLE = {"background_color": 0xFF313A45, "color": 0xFFFFFFFF, "font_size": 13}
    CCTV_DOT_STYLE = {"background_color": 0xFFFF7A00}
    EVENT_DOT_STYLE = {"background_color": (AWARENESS_EVENT_UI_OPACITY << 24) | 0x00FF4D4D}
    DRONE_DOT_STYLE = {"background_color": 0xFF2F8FFF}
    CCTV_CONE_STYLE = {"background_color": 0x263CFFD8}
    DRONE_RING_STYLE = {"background_color": 0x2A2F8FFF}
    TRACKING_LINE_COLOR = (0.18, 1.0, 0.42)
    PULSE_FILL_COLOR = (1.0, 0.08, 0.03)
    PULSE_RING_COLOR = (1.0, 0.0, 0.0)
    MAP_CONE_LENGTH = 82.0
    MAP_CONE_STEPS = 8
    MAP_CONE_START_DIAMETER = 10.0
    MAP_CONE_END_DIAMETER = 58.0

    def __init__(self, app):
        self.app = app
        self.window = None
        self.timeline = []
        self.cctv_rows = []
        self.active_visuals = []
        self.last_event = None
        self.is_y_up = False
        self.marker_root_path = f"{AWARENESS_ROOT_PATH}/EventMarkers"
        self.link_root_path = f"{AWARENESS_ROOT_PATH}/Links"
        self.links_visible = False
        self.map_bounds = None
        self.panel_refresh_elapsed = 0.0
        self.map_camera_path = AWARENESS_MAP_CAMERA_PATH
        self.viewport_widget_cls = None
        self.viewport_widgets = []
        self.event_seq = 0
        self.summary_frame = None
        self.map_overlay_frame = None
        self.status_frame = None
        self.timeline_frame = None
        self._last_drone_signature = None

    def setup(self):
        try:
            stage = get_stage()
        except RuntimeError:
            return

        self.is_y_up = self._is_y_up_stage(stage)
        ensure_xform(stage, AWARENESS_ROOT_PATH)
        ensure_xform(stage, self.marker_root_path)
        ensure_xform(stage, self.link_root_path)
        self._clear_children(stage, self.marker_root_path)
        self._clear_children(stage, self.link_root_path)
        self.active_visuals = []
        self.timeline = []
        self.last_event = None
        self.cctv_rows = self._load_cctv_rows()
        self.map_bounds = self._compute_static_map_bounds(self.cctv_rows)
        self.viewport_widget_cls = self._load_viewport_widget_cls()
        self._setup_map_camera(stage)
        self.links_visible = False
        self._last_drone_signature = self._drone_signature()

    def stop(self):
        self.destroy()
        try:
            stage = get_stage()
            prim = stage.GetPrimAtPath(AWARENESS_ROOT_PATH)
            if prim.IsValid():
                stage.RemovePrim(AWARENESS_ROOT_PATH)
        except Exception:
            pass
        self.active_visuals = []
        self.timeline = []
        self.last_event = None
        self.links_visible = False
        self.map_bounds = None
        self.panel_refresh_elapsed = 0.0
        self.event_seq = 0
        self._last_drone_signature = None

    def destroy(self):
        self._destroy_viewport_widgets()
        self._clear_dynamic_frames()
        if self.window is not None:
            self.window.visible = False
            self.window = None
        hide_existing_window(WINDOW_TITLE)

    def update(self, dt):
        try:
            stage = get_stage()
        except RuntimeError:
            return

        self._update_event_visuals(stage, dt)
        self._update_live_panel(dt)
        self._clear_tracking_links_after_return(stage)

    def record_event(self, event, aim_report):
        if event is None:
            return

        try:
            stage = get_stage()
        except RuntimeError:
            return

        event_type = str(event.get("type", "event"))
        position = event.get("position")
        if position is None:
            return

        position = tuple(float(value) for value in position)
        color = EVENT_COLORS.get(event_type, (1.0, 0.3, 0.3))
        cctv_rows = list(aim_report.get("cctvs", [])) if aim_report else []
        aimed_count = int(aim_report.get("aimed_count", 0)) if aim_report else 0
        radius = float(aim_report.get("radius", SOUND_DETECTION_RADIUS_M)) if aim_report else SOUND_DETECTION_RADIUS_M

        self.event_seq += 1
        self.last_event = {
            "id": self.event_seq,
            "type": event_type,
            "path": event.get("path", ""),
            "position": position,
            "aimed_count": aimed_count,
            "radius": radius,
            "time": self._time_text(),
        }
        self.timeline.append(self.last_event)
        if len(self.timeline) > AWARENESS_EVENT_HISTORY_LIMIT:
            self.timeline = self.timeline[-AWARENESS_EVENT_HISTORY_LIMIT:]

        self.cctv_rows = cctv_rows or self._load_cctv_rows()
        if self.map_bounds is None:
            self.map_bounds = self._compute_static_map_bounds(self.cctv_rows)
        self._create_event_visual(stage, self.last_event, color)
        self._clear_children(stage, self.link_root_path)
        self.links_visible = self._create_tracking_links(stage, position, self.cctv_rows) > 0
        self.refresh_panel()

    def refresh_panel(self):
        if self._rebuild_dynamic_frames():
            return

        host_window = getattr(self.app, "window", None)
        if host_window is not None:
            try:
                host_window.show()
            except Exception as exc:
                print(f"[cctv_sim] situation overview refresh failed: {exc}")

    def refresh_live_panel(self):
        if not self._rebuild_frame(self.map_overlay_frame, self._build_map_overlay_frame):
            return
        self._rebuild_frame(self.status_frame, self._build_status_frame)
        self._rebuild_frame(self.summary_frame, self._build_summary)

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
                print(f"[cctv_sim] situation frame build failed: {exc}")
                return False

    def _rebuild_dynamic_frames(self):
        frames = (
            (self.summary_frame, self._build_summary),
            (self.map_overlay_frame, self._build_map_overlay_frame),
            (self.status_frame, self._build_status_frame),
            (self.timeline_frame, self._build_timeline_frame),
        )
        for frame, _ in frames:
            if frame is None:
                return False

        rebuilt = True
        for frame, build_fn in frames:
            rebuilt = self._rebuild_frame(frame, build_fn) and rebuilt
        return rebuilt

    def _rebuild_frame(self, frame, build_fn):
        if frame is None:
            return False
        try:
            frame.set_build_fn(build_fn)
            frame.rebuild()
            return True
        except Exception:
            return False

    def _clear_dynamic_frames(self):
        self.summary_frame = None
        self.map_overlay_frame = None
        self.status_frame = None
        self.timeline_frame = None

    def build_embedded_panel(self):
        self._destroy_viewport_widgets()
        self._clear_dynamic_frames()
        with ui.VStack(spacing=8, height=0, style=self.PANEL_STYLE):
            ui.Label("Stage Minimap", height=28, style=self.HEADER_STYLE)
            self.summary_frame = ui.Frame(height=24)
            self._build_frame(self.summary_frame, self._build_summary)
            with ui.HStack(spacing=10, height=self.MAP_HEIGHT):
                self._build_map()
                self.status_frame = ui.Frame(width=self.STATUS_WIDTH, height=self.MAP_HEIGHT)
                self._build_frame(self.status_frame, self._build_status_frame)
            self.timeline_frame = ui.Frame(height=0)
            self._build_frame(self.timeline_frame, self._build_timeline_frame)

    def show(self):
        self.refresh_panel()

    def _build_summary(self):
        drone_text = self._drone_summary_text()
        if self.last_event is None:
            ui.Label(
                f"No active event. Trigger yell, crash, explosion, or gun. {drone_text}",
                height=24,
                style=self.MUTED_LABEL_STYLE,
            )
            return

        event_type = self.last_event["type"].upper()
        position = self.last_event["position"]
        summary = (
            f"{self.last_event['time']}  {event_type}  "
            f"aimed {self.last_event['aimed_count']} CCTV(s)  "
            f"({position[0]:.1f}, {position[1]:.1f}, {position[2]:.1f})  {drone_text}"
        )
        ui.Label(summary, height=24, style=self.LABEL_STYLE)

    def _build_map(self):
        with ui.ZStack(width=self.MAP_WIDTH, height=self.MAP_HEIGHT):
            self._build_map_background()
            self.map_overlay_frame = ui.Frame(width=self.MAP_WIDTH, height=self.MAP_HEIGHT)
            self._build_frame(self.map_overlay_frame, self._build_map_overlay_frame)

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

        self._build_drone_overlay(bounds)

        if self.last_event is not None:
            x, y = self._map_point(self.last_event["position"], bounds)
            self._build_ui_circle(x, y, 18, self.EVENT_DOT_STYLE)

    def _build_drone_overlay(self, bounds):
        drone_position = self._follow_top_camera_world_position()
        if drone_position is None:
            return

        x, y = self._map_point(drone_position, bounds)
        self._build_ui_circle(x, y, 22, self.DRONE_RING_STYLE)
        self._build_ui_circle(x, y, 12, self.DRONE_DOT_STYLE)

    def _build_status_frame(self):
        with ui.VStack(spacing=4, width=self.STATUS_WIDTH, height=self.MAP_HEIGHT):
            self._build_drone_status()
            self._build_cctv_status()

    def _build_drone_status(self):
        ui.Label("Drone Follow Camera", height=24, style=self.SMALL_HEADER_STYLE)
        auto_track = "ON" if bool(getattr(self.app, "follow_top_camera_auto_track", False)) else "OFF"
        style = dict(self.BADGE_STYLE)
        style["background_color"] = 0xFF49B4FF if auto_track == "ON" else 0xFF586474
        ui.Label(f"AUTO {auto_track}", width=96, height=self.ROW_HEIGHT, alignment=ui.Alignment.CENTER, style=style)
        drone_position = self._follow_top_camera_world_position()
        if drone_position is None:
            ui.Label("Top-view rig unavailable.", height=22, style=self.MUTED_LABEL_STYLE)
            return
        ui.Label(
            f"({drone_position[0]:.1f}, {drone_position[1]:.1f}, {drone_position[2]:.1f})",
            height=22,
            style=self.MUTED_LABEL_STYLE,
        )

    def _build_timeline_frame(self):
        with ui.VStack(spacing=4, height=0):
            self._build_timeline()

    def _build_map_reticle(self):
        grid_width = 1

        for x in range(50, self.MAP_WIDTH, 50):
            with ui.Placer(offset_x=x, offset_y=0, width=grid_width, height=self.MAP_HEIGHT, stable_size=True):
                ui.Rectangle(width=grid_width, height=self.MAP_HEIGHT, style=self.MAP_GRID_STYLE)
        for y in range(40, self.MAP_HEIGHT, 40):
            with ui.Placer(offset_x=0, offset_y=y, width=self.MAP_WIDTH, height=grid_width, stable_size=True):
                ui.Rectangle(width=self.MAP_WIDTH, height=grid_width, style=self.MAP_GRID_STYLE)

        with ui.Placer(offset_x=self.MAP_WIDTH * 0.5, offset_y=0, width=grid_width, height=self.MAP_HEIGHT, stable_size=True):
            ui.Rectangle(width=grid_width, height=self.MAP_HEIGHT, style=self.MAP_GRID_STYLE)
        with ui.Placer(offset_x=0, offset_y=self.MAP_HEIGHT * 0.5, width=self.MAP_WIDTH, height=grid_width, stable_size=True):
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

    def _build_cctv_status(self):
        ui.Label("CCTV Status", height=24, style=self.SMALL_HEADER_STYLE)
        if not self.cctv_rows:
            ui.Label("No CCTV prims found under /World/CCTV.", height=24, style=self.MUTED_LABEL_STYLE)
            return

        for row in self.cctv_rows:
            with ui.HStack(spacing=6, height=self.ROW_HEIGHT):
                ui.Label(row.get("name", "CCTV"), width=96, height=self.ROW_HEIGHT, style=self.LABEL_STYLE)
                self._build_status_badge(row)
                ui.Label(self._distance_text(row), width=82, height=self.ROW_HEIGHT, style=self.MUTED_LABEL_STYLE)
                ui.Label(self._reason_text(row), height=self.ROW_HEIGHT, style=self.MUTED_LABEL_STYLE)

    def _build_status_badge(self, row):
        status = row.get("status", "idle")
        text = self._status_text(status)
        color = STATUS_UI_COLORS.get(status, 0xFF9EA7B3)
        style = dict(self.BADGE_STYLE)
        style["background_color"] = color
        ui.Label(text, width=96, height=self.ROW_HEIGHT, alignment=ui.Alignment.CENTER, style=style)

    def _build_timeline(self):
        ui.Label("Event Timeline", height=24, style=self.SMALL_HEADER_STYLE)
        if not self.timeline:
            ui.Label("Timeline is empty.", height=24, style=self.MUTED_LABEL_STYLE)
            return

        for event in reversed(self.timeline[-AWARENESS_EVENT_HISTORY_LIMIT:]):
            color = EVENT_UI_COLORS.get(event["type"], 0xFFFF4D4D)
            style = {"color": color, "font_size": 13}
            path_text = self._short_path(event.get("path") or "<character>")
            ui.Label(
                f"{event['time']}  {event['type']}  aimed {event['aimed_count']}  {path_text}",
                height=22,
                style=style,
            )

    def _load_cctv_rows(self):
        try:
            rows = self.app.cctv.get_tracking_snapshot()
        except Exception as exc:
            print(f"[cctv_sim] situation CCTV snapshot failed: {exc}")
            return []

        for row in rows:
            row.setdefault("radius", SOUND_DETECTION_RADIUS_M)
            row.setdefault("status", "idle")
        return rows

    def _create_event_visual(self, stage, event, color):
        event_type = event["type"]
        position = event["position"]
        visual_path = next_free_path(stage, self.marker_root_path, f"{event_type}_marker")
        ensure_xform(stage, visual_path)

        marker_position = self._with_vertical_offset(position, AWARENESS_LINK_HEIGHT_M + AWARENESS_MARKER_RADIUS_M)
        sphere = UsdGeom.Sphere.Define(stage, f"{visual_path}/Marker")
        sphere.CreateRadiusAttr(AWARENESS_MARKER_RADIUS_M)
        sphere.CreateDisplayColorAttr([Gf.Vec3f(*color)])
        try:
            sphere.CreateDisplayOpacityAttr([float(AWARENESS_EVENT_MARKER_OPACITY)])
        except Exception:
            pass
        sphere_xform = UsdGeom.Xformable(sphere.GetPrim())
        sphere_xform.AddTranslateOp().Set(Gf.Vec3d(*marker_position))

        self._create_curve(
            stage,
            f"{visual_path}/Stem",
            [self._with_vertical_offset(position, 1.0), marker_position],
            color,
            2.0,
            opacity=AWARENESS_EVENT_MARKER_OPACITY,
        )
        self._create_circle_curve(
            stage,
            f"{visual_path}/ImpactRing",
            position,
            AWARENESS_PULSE_MIN_RADIUS_M,
            self.PULSE_RING_COLOR,
            3.0,
            opacity=AWARENESS_EVENT_MARKER_OPACITY,
        )
        pulse_fill_path = f"{visual_path}/PulseFill"
        self._create_pulse_fill_disk(stage, pulse_fill_path, position, AWARENESS_PULSE_MIN_RADIUS_M)
        self._create_circle_curve(
            stage,
            f"{visual_path}/PulseRing",
            position,
            AWARENESS_PULSE_MIN_RADIUS_M,
            self.PULSE_RING_COLOR,
            2.0,
            opacity=AWARENESS_EVENT_MARKER_OPACITY,
        )

        self.active_visuals.append(
            {
                "path": visual_path,
                "pulse_path": f"{visual_path}/PulseRing",
                "pulse_fill_path": pulse_fill_path,
                "position": position,
                "event_id": event.get("id"),
                "age": 0.0,
            }
        )

    def _create_tracking_links(self, stage, target_position, rows):
        target = self._with_vertical_offset(target_position, AWARENESS_LINK_HEIGHT_M)
        created_count = 0
        for index, row in enumerate(rows, 1):
            if row.get("status") != "tracking":
                continue
            origin = row.get("position")
            if origin is None:
                continue
            origin = self._with_vertical_offset(origin, AWARENESS_LINK_HEIGHT_M)
            self._create_curve(
                stage,
                f"{self.link_root_path}/tracking_{index:02d}",
                [origin, target],
                self.TRACKING_LINE_COLOR,
                AWARENESS_CCTV_LINK_WIDTH_M,
                opacity=AWARENESS_CCTV_LINK_OPACITY,
            )
            created_count += 1
        return created_count

    def _update_live_panel(self, dt):
        self.panel_refresh_elapsed += dt
        if self.panel_refresh_elapsed < AWARENESS_PANEL_REFRESH_SEC:
            return

        self.panel_refresh_elapsed = 0.0
        self._merge_live_cctv_rows()
        current_drone_signature = self._drone_signature()
        if (
            self.links_visible
            or getattr(getattr(self.app, "cctv", None), "aim_jobs", {})
            or current_drone_signature != self._last_drone_signature
        ):
            self._last_drone_signature = current_drone_signature
            self.refresh_live_panel()

    def _merge_live_cctv_rows(self):
        try:
            live_rows = self.app.cctv.get_tracking_snapshot()
        except Exception as exc:
            print(f"[cctv_sim] live CCTV direction update failed: {exc}")
            return

        live_by_path = {row.get("root_path"): row for row in live_rows}
        for row in self.cctv_rows:
            live = live_by_path.get(row.get("root_path"))
            if not live:
                continue

            for key in ("position", "current_yaw", "view_yaw", "yaw_path"):
                if key in live:
                    row[key] = live[key]

            live_status = live.get("status", "idle")
            if live_status != "idle" or row.get("status") not in ("out_of_range", "not_connected"):
                row["status"] = live_status

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

    def _update_event_visuals(self, stage, dt):
        minimap_dirty = False
        for visual in list(self.active_visuals):
            visual["age"] += dt
            if visual["age"] >= AWARENESS_EVENT_VISIBLE_SEC:
                prim = stage.GetPrimAtPath(visual["path"])
                if prim.IsValid():
                    stage.RemovePrim(visual["path"])
                self.active_visuals.remove(visual)
                if self.last_event is not None and self.last_event.get("id") == visual.get("event_id"):
                    self.last_event = None
                    minimap_dirty = True
                continue

            cycle = (visual["age"] % AWARENESS_PULSE_PERIOD_SEC) / max(AWARENESS_PULSE_PERIOD_SEC, 1e-6)
            radius = AWARENESS_PULSE_MIN_RADIUS_M + (AWARENESS_PULSE_MAX_RADIUS_M - AWARENESS_PULSE_MIN_RADIUS_M) * cycle
            self._set_circle_points(stage, visual["pulse_path"], visual["position"], radius)
            self._set_pulse_fill_radius(stage, visual.get("pulse_fill_path"), radius)

        if minimap_dirty:
            self.refresh_panel()

    def _clear_tracking_links_after_return(self, stage):
        if not self.links_visible:
            return

        aim_jobs = getattr(getattr(self.app, "cctv", None), "aim_jobs", {})
        if aim_jobs:
            return

        self._clear_children(stage, self.link_root_path)
        self.links_visible = False
        self.cctv_rows = self._load_cctv_rows()
        self.refresh_panel()

    def _create_curve(self, stage, path, points, color, width, opacity=1.0):
        curve = UsdGeom.BasisCurves.Define(stage, Sdf.Path(path))
        curve.CreateTypeAttr(UsdGeom.Tokens.linear)
        curve.CreateCurveVertexCountsAttr([len(points)])
        curve.CreatePointsAttr([Gf.Vec3f(*point) for point in points])
        curve.CreateWidthsAttr([float(width)] * len(points))
        curve.CreateDisplayColorAttr([Gf.Vec3f(*color)])
        try:
            curve.CreateDisplayOpacityAttr([float(opacity)])
        except Exception:
            pass
        return curve

    def _create_circle_curve(self, stage, path, center, radius, color, width, opacity=1.0):
        return self._create_curve(stage, path, self._circle_points(center, radius), color, width, opacity=opacity)

    def _create_pulse_fill_disk(self, stage, path, center, radius):
        cylinder = UsdGeom.Cylinder.Define(stage, Sdf.Path(path))
        cylinder.CreateRadiusAttr(float(radius))
        cylinder.CreateHeightAttr(float(AWARENESS_PULSE_FILL_HEIGHT_M))
        axis = UsdGeom.Tokens.y if self.is_y_up else UsdGeom.Tokens.z
        try:
            cylinder.CreateAxisAttr(axis)
        except Exception:
            pass
        cylinder.CreateDisplayColorAttr([Gf.Vec3f(*self.PULSE_FILL_COLOR)])
        try:
            cylinder.CreateDisplayOpacityAttr([float(AWARENESS_PULSE_FILL_OPACITY)])
        except Exception:
            pass

        xform = UsdGeom.Xformable(cylinder.GetPrim())
        xform.AddTranslateOp().Set(Gf.Vec3d(*self._with_vertical_offset(center, AWARENESS_PULSE_FILL_HEIGHT_M * 0.5)))
        return cylinder

    def _set_pulse_fill_radius(self, stage, path, radius):
        if not path:
            return
        prim = stage.GetPrimAtPath(path)
        if not prim.IsValid():
            return
        UsdGeom.Cylinder(prim).GetRadiusAttr().Set(float(radius))

    def _set_circle_points(self, stage, path, center, radius):
        prim = stage.GetPrimAtPath(path)
        if not prim.IsValid():
            return
        curve = UsdGeom.BasisCurves(prim)
        curve.GetPointsAttr().Set([Gf.Vec3f(*point) for point in self._circle_points(center, radius)])

    def _circle_points(self, center, radius, segments=72):
        points = []
        cx, cy, cz = center
        for index in range(segments + 1):
            angle = math.tau * index / segments
            dx = math.cos(angle) * radius
            dy = math.sin(angle) * radius
            if self.is_y_up:
                points.append((cx + dx, cy + 1.0, cz + dy))
            else:
                points.append((cx + dx, cy + dy, cz + 1.0))
        return points

    def _map_bounds(self):
        if self.map_bounds is not None:
            return self.map_bounds
        self.map_bounds = self._compute_static_map_bounds(self.cctv_rows)
        return self.map_bounds

    def _compute_static_map_bounds(self, rows):
        points = []
        for row in rows:
            position = row.get("position")
            if position is not None:
                points.append(self._horizontal_point(position))

        drone_position = self._follow_top_camera_world_position()
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

    def _build_map_background(self):
        if self.viewport_widget_cls is not None:
            try:
                widget_kwargs = {
                    "camera_path": self.map_camera_path,
                    "resolution": (self.MAP_WIDTH, self.MAP_HEIGHT),
                    "width": self.MAP_WIDTH,
                    "height": self.MAP_HEIGHT,
                }
                hydra_engine_options = self._map_hydra_engine_options()
                if hydra_engine_options:
                    widget_kwargs["hydra_engine_options"] = hydra_engine_options
                widget = self.viewport_widget_cls(**widget_kwargs)
                self.viewport_widgets.append(widget)
                return
            except Exception as exc:
                print(f"[cctv_sim] minimap viewport unavailable, using radar fallback: {exc}")

        ui.Rectangle(width=self.MAP_WIDTH, height=self.MAP_HEIGHT, style=self.MAP_STYLE)
        self._build_map_reticle()

    def _setup_map_camera(self, stage):
        bounds = self._map_bounds()
        min_x, min_y, max_x, max_y = bounds
        center_x = (min_x + max_x) * 0.5
        center_y = (min_y + max_y) * 0.5
        width = max(max_x - min_x, 1.0)
        height = max(max_y - min_y, 1.0)

        camera = UsdGeom.Camera.Define(stage, Sdf.Path(self.map_camera_path))
        camera.CreateProjectionAttr().Set(UsdGeom.Tokens.orthographic)
        camera.CreateHorizontalApertureAttr().Set(self._camera_aperture_from_world_size(width))
        camera.CreateVerticalApertureAttr().Set(self._camera_aperture_from_world_size(height))
        camera.CreateHorizontalApertureOffsetAttr().Set(0.0)
        camera.CreateVerticalApertureOffsetAttr().Set(0.0)
        camera.CreateClippingRangeAttr().Set(Gf.Vec2f(*AWARENESS_MAP_CAMERA_CLIPPING_RANGE))

        xform = UsdGeom.Xformable(camera.GetPrim())
        translate_op, rotate_op, scale_op = get_or_create_transform_ops(xform)
        if self.is_y_up:
            translate_op.Set(Gf.Vec3d(center_x, AWARENESS_MAP_CAMERA_HEIGHT_M, center_y))
            rotate_op.Set(Gf.Vec3f(-90.0, 0.0, 0.0))
        else:
            translate_op.Set(Gf.Vec3d(center_x, center_y, AWARENESS_MAP_CAMERA_HEIGHT_M))
            rotate_op.Set(Gf.Vec3f(0.0, 0.0, 0.0))
        scale_op.Set(Gf.Vec3f(1.0, 1.0, 1.0))

    def _load_viewport_widget_cls(self):
        try:
            from omni.kit.widget.viewport import ViewportWidget
            return ViewportWidget
        except Exception:
            pass

        try:
            import omni.kit.app

            manager = omni.kit.app.get_app().get_extension_manager()
            manager.set_extension_enabled_immediate("omni.kit.widget.viewport", True)
            from omni.kit.widget.viewport import ViewportWidget
            return ViewportWidget
        except Exception as exc:
            print(f"[cctv_sim] minimap viewport widget unavailable: {exc}")
            return None

    def _destroy_viewport_widgets(self):
        for widget in list(self.viewport_widgets):
            try:
                destroy = getattr(widget, "destroy", None)
                if destroy is not None:
                    destroy()
            except Exception:
                pass
        self.viewport_widgets = []

    def _map_hydra_engine_options(self):
        try:
            fps = float(AWARENESS_MAP_VIEWPORT_FPS)
        except (TypeError, ValueError):
            return None
        if fps <= 0.0:
            return None
        return {"hydra_tick_rate": int(round(fps))}

    def _camera_aperture_from_world_size(self, world_size):
        return float(world_size) * float(AWARENESS_MAP_CAMERA_APERTURE_SCALE)

    def _map_point(self, position, bounds, clamp=True):
        min_x, min_y, max_x, max_y = bounds
        x, y = self._horizontal_point(position)
        nx = (x - min_x) / max(max_x - min_x, 1e-6)
        ny = (y - min_y) / max(max_y - min_y, 1e-6)
        map_x = nx * self.MAP_WIDTH
        map_y = (1.0 - ny) * self.MAP_HEIGHT
        if not clamp:
            return map_x, map_y
        return (self._clamp(map_x, 0, self.MAP_WIDTH), self._clamp(map_y, 0, self.MAP_HEIGHT))

    def _horizontal_point(self, position):
        if self.is_y_up:
            return (float(position[0]), float(position[2]))
        return (float(position[0]), float(position[1]))

    def _offset_horizontal_position(self, position, dx, dy, distance):
        if self.is_y_up:
            return (float(position[0]) + dx * distance, float(position[1]), float(position[2]) + dy * distance)
        return (float(position[0]) + dx * distance, float(position[1]) + dy * distance, float(position[2]))

    def _with_vertical_offset(self, position, offset):
        if self.is_y_up:
            return (float(position[0]), float(position[1]) + offset, float(position[2]))
        return (float(position[0]), float(position[1]), float(position[2]) + offset)

    def _follow_top_camera_world_position(self):
        controller = getattr(self.app, "follow_top_camera", None)
        if controller is None:
            return None

        try:
            stage_xy, height = controller.get_current_stage_xy_height()
        except Exception:
            return None

        stage = get_stage()
        if self._is_y_up_stage(stage):
            return (float(stage_xy[0]), float(height), float(stage_xy[1]))
        return (float(stage_xy[0]), float(stage_xy[1]), float(height))

    def _drone_summary_text(self):
        drone_position = self._follow_top_camera_world_position()
        if drone_position is None:
            return "drone unavailable"
        return f"drone=({drone_position[0]:.1f}, {drone_position[1]:.1f}, {drone_position[2]:.1f})"

    def _drone_signature(self):
        drone_position = self._follow_top_camera_world_position()
        if drone_position is None:
            return None
        return tuple(round(float(value), 1) for value in drone_position)

    def _clear_children(self, stage, root_path):
        root = stage.GetPrimAtPath(root_path)
        if not root.IsValid():
            return
        for child in list(root.GetChildren()):
            stage.RemovePrim(child.GetPath())

    def _is_y_up_stage(self, stage):
        try:
            return UsdGeom.GetStageUpAxis(stage) == UsdGeom.Tokens.y
        except Exception:
            return False

    def _status_text(self, status):
        return {
            "tracking": "TRACKING",
            "aim": "AIMING",
            "hold": "HOLDING",
            "return": "RETURN",
            "returning": "RETURN",
            "out_of_range": "OUT",
            "idle": "IDLE",
            "not_connected": "NO LINK",
        }.get(status, str(status).upper())

    def _distance_text(self, row):
        distance = row.get("distance")
        if distance is None:
            return "-"
        return f"{float(distance):.1f}m"

    def _reason_text(self, row):
        status = row.get("status", "idle")
        if status == "tracking":
            focal = row.get("focal_length")
            if focal is not None:
                return f"focal {float(focal):.1f}"
            return "event in range"
        if status == "out_of_range":
            return "outside radius"
        return row.get("reason", "")

    def _short_path(self, value, max_length=42):
        text = str(value)
        if len(text) <= max_length:
            return text
        parts = [part for part in text.split("/") if part]
        if len(parts) >= 2:
            text = "/" + "/".join(parts[-2:])
        if len(text) <= max_length:
            return text
        return "..." + text[-(max_length - 3):]

    def _time_text(self):
        return datetime.now().strftime("%H:%M:%S")

    def _clamp(self, value, minimum, maximum):
        return max(minimum, min(maximum, value))

    def _circle_fits_map(self, center_x, center_y, diameter):
        radius = diameter * 0.5
        return radius <= center_x <= self.MAP_WIDTH - radius and radius <= center_y <= self.MAP_HEIGHT - radius
