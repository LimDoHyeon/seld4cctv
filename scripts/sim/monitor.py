from datetime import datetime

import omni.ui as ui

from .config import CCTV_MONITOR_LIVE_ON_START, CCTV_MONITOR_MAX_FPS


WINDOW_TITLE = "CCTV Monitor"


def hide_existing_window(title):
    try:
        window = ui.Workspace.get_window(title)
        if window is not None:
            window.visible = False
    except Exception:
        pass


class CCTVMonitorWindow:
    VIEW_MODE_ENTIRE = "entire"
    VIEW_MODE_SINGLE = "single"

    SLOT_COUNT = 4
    SLOT_WIDTH = 360
    SLOT_HEIGHT = 200
    GRID_WIDTH = SLOT_WIDTH * 2
    GRID_HEIGHT = SLOT_HEIGHT * 2
    TOOLBAR_HEIGHT = 35
    BUTTON_WIDTH = 102
    VIEW_RESOLUTION = (320, 180)
    SINGLE_VIEW_RESOLUTION = (640, 360)
    OVERLAY_MARGIN = 10
    OVERLAY_HEIGHT = 24
    NAME_LABEL_WIDTH = 150
    TIME_LABEL_WIDTH = 104
    STOP_LABEL_WIDTH = 140
    OVERLAY_STYLE = {
        "background_color": 0x99000000,
        "color": 0xFFFFFFFF,
        "font_size": 14,
    }
    STOP_BACKGROUND_STYLE = {
        "background_color": 0xFF000000,
    }
    STOP_LABEL_STYLE = {
        "background_color": 0x00000000,
        "color": 0xFFFFFFFF,
        "font_size": 16,
    }

    def __init__(self, app):
        self.app = app
        self.window = None
        self.name_labels = []
        self.time_labels = []
        self.viewport_widgets = []
        self.camera_views = []
        self.viewport_widget_cls = None
        self.clock_elapsed = 0.0
        self.live_enabled = CCTV_MONITOR_LIVE_ON_START
        self.view_mode = self.VIEW_MODE_ENTIRE
        self.single_view_index = 0
        self.single_swapped = False
        self.entire_swapped = False

    def show(self):
        self.destroy()
        hide_existing_window(WINDOW_TITLE)
        self.viewport_widget_cls = self._load_viewport_widget_cls() if self.live_enabled else None
        self.camera_views = self._load_camera_views()

        self.window = ui.Window(
            WINDOW_TITLE,
            width=self.GRID_WIDTH,
            height=self.GRID_HEIGHT + self.TOOLBAR_HEIGHT,
            visible=True,
            dockPreference=ui.DockPreference.RIGHT_TOP,
        )
        with self.window.frame:
            with ui.VStack(spacing=0, height=0):
                self._build_toolbar()
                if self.view_mode == self.VIEW_MODE_SINGLE:
                    self._build_single_view()
                else:
                    self._build_entire_view()

        self._update_clock(force=True)
        self._dock_window()
        try:
            self.window.visible = True
            self.window.focus()
        except Exception:
            pass

    def destroy(self):
        self._destroy_viewport_widgets()
        self.name_labels = []
        self.time_labels = []
        if self.window is not None:
            self.window.visible = False
            self.window = None

    def _destroy_viewport_widgets(self):
        for widget in self.viewport_widgets:
            try:
                widget.destroy()
            except Exception:
                pass
        self.viewport_widgets = []

    def _dock_window(self):
        for target_name in ("CCTV Sound Event Demo", "Property", "Console"):
            try:
                self.window.deferred_dock_in(target_name, ui.DockPolicy.CURRENT_WINDOW_IS_ACTIVE)
                return
            except Exception:
                continue

    def update(self, dt):
        self.clock_elapsed += dt
        if self.clock_elapsed >= 1.0:
            self._update_clock(force=True)

    def _load_camera_views(self):
        try:
            return self.app.cctv.get_camera_views()
        except Exception as exc:
            print(f"[cctv_sim] CCTV refresh failed: {exc}")
            return []

    def _build_toolbar(self):
        with ui.HStack(spacing=0, height=self.TOOLBAR_HEIGHT):
            ui.Button(
                "PERS",
                width=self.BUTTON_WIDTH,
                height=self.TOOLBAR_HEIGHT,
                clicked_fn=self._open_perspective,
            )
            ui.Button(
                self._live_button_text(),
                width=self.BUTTON_WIDTH,
                height=self.TOOLBAR_HEIGHT,
                clicked_fn=self._toggle_live_feeds,
            )
            ui.Button(
                "ENTIRE",
                width=self.BUTTON_WIDTH,
                height=self.TOOLBAR_HEIGHT,
                clicked_fn=self._show_entire_view,
            )
            for index in range(self.SLOT_COUNT):
                ui.Button(
                    f"CCTV{index + 1}",
                    width=self.BUTTON_WIDTH,
                    height=self.TOOLBAR_HEIGHT,
                    clicked_fn=lambda index=index: self._open_slot(index),
                )

    def _build_entire_view(self):
        for row in range(2):
            with ui.HStack(spacing=0, height=self.SLOT_HEIGHT):
                for column in range(2):
                    index = row * 2 + column
                    view = self.camera_views[index] if index < len(self.camera_views) else None
                    self._build_camera_panel(
                        index,
                        view,
                        self.SLOT_WIDTH,
                        self.SLOT_HEIGHT,
                        self.VIEW_RESOLUTION,
                    )

    def _build_single_view(self):
        index = min(max(self.single_view_index, 0), self.SLOT_COUNT - 1)
        view = self.camera_views[index] if index < len(self.camera_views) else None
        self._build_camera_panel(
            index,
            view,
            self.GRID_WIDTH,
            self.GRID_HEIGHT,
            self.SINGLE_VIEW_RESOLUTION,
        )

    def _build_camera_panel(self, index, view, width, height, resolution):
        camera_path = self._monitor_camera_path(index, view)
        name_text = self._slot_name(index, view)
        path_text = self._slot_path(view, camera_path)

        with ui.ZStack(width=width, height=height):
            if self.live_enabled and camera_path and self.viewport_widget_cls is not None:
                try:
                    widget_kwargs = {
                        "camera_path": camera_path,
                        "resolution": resolution,
                        "width": width,
                        "height": height,
                    }
                    hydra_engine_options = self._monitor_hydra_engine_options()
                    if hydra_engine_options:
                        widget_kwargs["hydra_engine_options"] = hydra_engine_options
                    widget = self.viewport_widget_cls(**widget_kwargs)
                    self.viewport_widgets.append(widget)
                except Exception as exc:
                    ui.Label(f"Live view failed: {exc}", height=height)
            elif not self.live_enabled:
                self._build_stopped_panel(width, height)
            else:
                ui.Label(path_text, height=height)

            with ui.Placer(
                offset_x=self._overlay_left_x(),
                offset_y=self._overlay_top_y(),
                width=self.NAME_LABEL_WIDTH,
                height=self.OVERLAY_HEIGHT,
                stable_size=True,
            ):
                name_label = ui.Label(
                    name_text,
                    width=self.NAME_LABEL_WIDTH,
                    height=self.OVERLAY_HEIGHT,
                    style=self.OVERLAY_STYLE,
                )

            with ui.Placer(
                offset_x=self._overlay_time_x(width),
                offset_y=self._overlay_time_y(height),
                width=self.TIME_LABEL_WIDTH,
                height=self.OVERLAY_HEIGHT,
                stable_size=True,
            ):
                time_label = ui.Label(
                    self._current_time_text(),
                    width=self.TIME_LABEL_WIDTH,
                    height=self.OVERLAY_HEIGHT,
                    style=self.OVERLAY_STYLE,
                )

        self.name_labels.append(name_label)
        self.time_labels.append(time_label)

    def _build_stopped_panel(self, width, height):
        ui.Rectangle(
            width=width,
            height=height,
            style=self.STOP_BACKGROUND_STYLE,
        )
        with ui.Placer(
            offset_x=self._stop_label_x(width),
            offset_y=self._stop_label_y(height),
            width=self.STOP_LABEL_WIDTH,
            height=self.OVERLAY_HEIGHT,
            stable_size=True,
        ):
            ui.Label(
                "LIVE STOPPED",
                width=self.STOP_LABEL_WIDTH,
                height=self.OVERLAY_HEIGHT,
                alignment=ui.Alignment.CENTER,
                style=self.STOP_LABEL_STYLE,
            )

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
            print(f"[cctv_sim] ViewportWidget unavailable: {exc}")
            return None

    def _monitor_hydra_engine_options(self):
        try:
            fps = float(CCTV_MONITOR_MAX_FPS)
        except (TypeError, ValueError):
            return None
        if fps <= 0.0:
            return None
        return {"hydra_tick_rate": int(round(fps))}

    def _slot_name(self, index, view):
        if view is None:
            return f"CCTV {index + 1}"
        return view["name"]

    def _slot_path(self, view, camera_path):
        if view is None:
            return "Not connected"
        if not camera_path:
            return "Camera not found"
        return camera_path

    def _monitor_camera_path(self, index, view):
        if view is None:
            return ""

        live_path = view.get("live_camera_path") or view.get("camera_path") or ""
        outer_path = view.get("outer_camera_path") or ""

        if self.view_mode == self.VIEW_MODE_SINGLE and index == self.single_view_index:
            if self.single_swapped:
                return live_path or outer_path
            return outer_path or live_path

        if self.entire_swapped:
            return live_path or outer_path
        return outer_path or live_path

    def _main_viewport_camera_path(self, view):
        live_path = view.get("live_camera_path") or view.get("camera_path") or ""
        outer_path = view.get("outer_camera_path") or ""
        if self.single_swapped:
            return outer_path or live_path
        return live_path or outer_path

    def _monitor_role_text(self, view):
        if self.single_swapped:
            return "ViewCamera"
        if view.get("outer_camera_path"):
            return "outer"
        return "ViewCamera"

    def _main_role_text(self, view):
        if self.single_swapped and view.get("outer_camera_path"):
            return "outer"
        return "ViewCamera"

    def _open_slot(self, index):
        if index >= len(self.camera_views):
            self._set_status(f"CCTV {index + 1} is not connected")
            return

        view = self.camera_views[index]
        name = view["name"]
        if not view["valid"]:
            self._set_status(f"{name} has no camera")
            return

        same_slot = self.view_mode == self.VIEW_MODE_SINGLE and self.single_view_index == index
        self.single_swapped = not self.single_swapped if same_slot else False
        self.single_view_index = index
        self.view_mode = self.VIEW_MODE_SINGLE

        main_camera_path = self._main_viewport_camera_path(view)
        if main_camera_path:
            ok, message = self.app.cctv.switch_to_camera(main_camera_path)
        else:
            ok, message = False, f"{name} has no viewport camera"

        monitor_role = self._monitor_role_text(view)
        main_role = self._main_role_text(view)
        self._set_status(f"{name}: main={main_role}, monitor={monitor_role}; {message}")
        print(
            f"[cctv_sim] CCTV monitor single {name}: "
            f"main={main_camera_path or '<none>'}, "
            f"monitor={self._monitor_camera_path(index, view) or '<none>'}"
        )
        self.show()

    def _show_entire_view(self):
        same_mode = self.view_mode == self.VIEW_MODE_ENTIRE
        self.view_mode = self.VIEW_MODE_ENTIRE
        self.single_swapped = False
        self.entire_swapped = not self.entire_swapped if same_mode else False

        monitor_role = "ViewCamera" if self.entire_swapped else "outer"
        self._set_status(f"Showing entire CCTV grid: monitor={monitor_role}")
        print(f"[cctv_sim] CCTV monitor entire grid: monitor={monitor_role}")
        self.show()

    def _open_perspective(self):
        ok, message = self.app.cctv.switch_to_perspective()
        self._set_status(message)
        print(f"[cctv_sim] CCTV monitor open PERS: {message}")

    def _toggle_live_feeds(self):
        self.live_enabled = not self.live_enabled
        state = "started" if self.live_enabled else "stopped"
        print(f"[cctv_sim] CCTV live feeds {state}")
        self.show()

    def _live_button_text(self):
        return "STOP" if self.live_enabled else "LIVE"

    def _set_status(self, message):
        print(f"[cctv_sim] {message}")

    def _current_time_text(self):
        return datetime.now().strftime("%H:%M:%S")

    def _overlay_left_x(self):
        return self.OVERLAY_MARGIN

    def _overlay_top_y(self):
        return self.OVERLAY_MARGIN

    def _overlay_time_x(self, width):
        return width - self.OVERLAY_MARGIN - self.TIME_LABEL_WIDTH

    def _overlay_time_y(self, height):
        return height - self.OVERLAY_MARGIN - self.OVERLAY_HEIGHT

    def _stop_label_x(self, width):
        return (width - self.STOP_LABEL_WIDTH) * 0.5

    def _stop_label_y(self, height):
        return (height - self.OVERLAY_HEIGHT) * 0.5

    def _update_clock(self, force=False):
        if not force:
            return

        self.clock_elapsed = 0.0
        text = self._current_time_text()
        for label in self.time_labels:
            label.text = text
