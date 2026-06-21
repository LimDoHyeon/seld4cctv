import omni.ui as ui

from .config import CAR_CRASH_VISIBLE_SEC, SOUND_SOURCE_VISIBLE_SEC


WINDOW_TITLE = "CCTV Sound Event Demo"


def hide_existing_window(title):
    return


class DemoWindow:
    WINDOW_WIDTH = 920
    WINDOW_HEIGHT = 700
    BUTTON_WIDTH = 92

    def __init__(self, app):
        self.app = app
        self.window = None
        self.status_label = None
        self.follow_toggle_button = None
        self.last_status = "Ready"

    def show(self):
        self.destroy()
        hide_existing_window(WINDOW_TITLE)

        self.window = ui.Window(WINDOW_TITLE, width=self.WINDOW_WIDTH, height=self.WINDOW_HEIGHT, visible=True)
        with self.window.frame:
            with ui.VStack(spacing=8, height=0):
                ui.Label(WINDOW_TITLE, height=24)
                with ui.HStack(spacing=6, height=34):
                    ui.Button("+CHAR1", width=self.BUTTON_WIDTH, height=34, clicked_fn=lambda: self._add_character(0))
                    ui.Button("+CHAR2", width=self.BUTTON_WIDTH, height=34, clicked_fn=lambda: self._add_character(1))
                    ui.Button("-CHAR", width=self.BUTTON_WIDTH, height=34, clicked_fn=self._remove_character)
                    for event_type in ("yell", "crash", "explosion", "gun"):
                        ui.Button(
                            event_type,
                            width=self.BUTTON_WIDTH,
                            height=34,
                            clicked_fn=lambda event_type=event_type: self._trigger_event(event_type),
                        )
                with ui.HStack(spacing=6, height=34):
                    self.follow_toggle_button = ui.Button("", width=120, height=34, clicked_fn=self._toggle_follow_auto_track)
                    ui.Button("TOPVIEW", width=self.BUTTON_WIDTH, height=34, clicked_fn=self._bind_follow_view)
                    ui.Button("PERS", width=self.BUTTON_WIDTH, height=34, clicked_fn=self._switch_to_perspective)
                self.status_label = ui.Label(self.last_status, height=24)
                awareness = getattr(self.app, "awareness", None)
                if awareness is not None:
                    awareness.build_embedded_panel()
        self._refresh_follow_toggle_label()

    def destroy(self):
        self.status_label = None
        self.follow_toggle_button = None
        if self.window is not None:
            self.window.visible = False
            self.window = None

    def _set_status(self, message):
        print(f"[cctv_sim] {message}")
        self.last_status = message
        if self.status_label is not None:
            self.status_label.text = message

    def _add_character(self, route_index):
        try:
            path = self.app.characters.add_character_on_route(route_index)
            walk_mode = getattr(self.app.characters, "last_added_walk_mode", None)
            if walk_mode == "route_rect":
                self._set_status(f"Added character: {path} inside MainRoute rectangle")
                return
            if walk_mode == "street":
                self._set_status(f"Added character: {path} in street roaming")
                return

            route_path = getattr(self.app.characters, "last_added_route_path", None)
            if route_path:
                route_name = route_path.rsplit("/", 1)[-1]
                self._set_status(f"Added character: {path} on {route_name}")
            else:
                self._set_status(f"Added character: {path}")
        except Exception as exc:
            self._set_status(f"Add character failed: {exc}")

    def _remove_character(self):
        try:
            path = self.app.characters.remove_character()
            if path:
                self._set_status(f"Removed character: {path}")
            else:
                self._set_status("No character to remove")
        except Exception as exc:
            self._set_status(f"Remove character failed: {exc}")

    def _trigger_event(self, event_type):
        try:
            if event_type == "yell":
                started, message, event_position = self.app.characters.yell_random()
                if started and event_position is not None:
                    self.app.events.register_sound_source("yell", event_position)
                    aim_report = self.app.cctv.aim_at_with_report(event_position)
                    follow_position = self.app.track_event_position_if_enabled(
                        event_position,
                        duration_sec=SOUND_SOURCE_VISIBLE_SEC,
                    )
                    self._record_situation_event(event_type, event_position, aim_report)
                    message = self._message_with_follow_position(
                        f"{message}; CCTV aimed: {aim_report['aimed_count']}",
                        follow_position,
                    )
                self._set_status(message)
                return

            if event_type == "gun":
                started, message, event_position = self.app.characters.gun_random()
                if started and event_position is not None:
                    self.app.start_following_character(self.app.characters.last_action_character_path)
                    self.app.events.register_sound_source("gun", event_position)
                    aim_report = self.app.cctv.aim_at_with_report(event_position)
                    follow_position = self.app.track_event_position_if_enabled(event_position)
                    self._record_situation_event(event_type, event_position, aim_report)
                    message = self._message_with_follow_position(
                        f"{message}; CCTV aimed: {aim_report['aimed_count']}",
                        follow_position,
                    )
                else:
                    self.app.stop_following_character()
                self._set_status(message)
                return

            event = self.app.events.trigger(event_type)
            aim_report = self.app.cctv.aim_at_with_report(event["position"])
            follow_duration = SOUND_SOURCE_VISIBLE_SEC
            if event_type == "crash":
                follow_duration = CAR_CRASH_VISIBLE_SEC
            elif event_type == "explosion":
                follow_duration = max(SOUND_SOURCE_VISIBLE_SEC, 2.0)
            follow_position = self.app.track_event_position_if_enabled(
                event["position"],
                duration_sec=follow_duration,
            )
            self._record_situation_event(event_type, event["position"], aim_report, event.get("path", ""))
            self._set_status(
                self._message_with_follow_position(
                    f"Triggered {event_type}: {event['path']}; CCTV aimed: {aim_report['aimed_count']}",
                    follow_position,
                )
            )
        except Exception as exc:
            self._set_status(f"{event_type} failed: {exc}")

    def _message_with_follow_position(self, message, follow_position):
        if follow_position is None:
            return message
        return (
            f"{message}; "
            f"top-view=({follow_position[0]:.1f}, {follow_position[1]:.1f}, {follow_position[2]:.1f})"
        )

    def _record_situation_event(self, event_type, position, aim_report, path=""):
        awareness = getattr(self.app, "awareness", None)
        if awareness is None:
            return
        try:
            awareness.record_event(
                {
                    "type": event_type,
                    "path": path,
                    "position": position,
                },
                aim_report,
            )
        except Exception as exc:
            print(f"[cctv_sim] situation overview update failed: {exc}")

    def _toggle_follow_auto_track(self):
        enabled = self.app.set_follow_top_camera_auto_track(not self.app.follow_top_camera_auto_track)
        self._refresh_follow_toggle_label()
        state = "ON" if enabled else "OFF"
        self._set_status(f"Top-view auto track: {state}")

    def _bind_follow_view(self):
        try:
            ok, message = self.app.bind_follow_top_camera_viewport()
            self._set_status(message)
        except Exception as exc:
            self._set_status(f"Top-view bind failed: {exc}")

    def _switch_to_perspective(self):
        try:
            ok, message = self.app.switch_follow_camera_to_perspective()
            self._set_status(message)
        except Exception as exc:
            self._set_status(f"Perspective switch failed: {exc}")

    def _refresh_follow_toggle_label(self):
        if self.follow_toggle_button is None:
            return
        state = "ON" if self.app.follow_top_camera_auto_track else "OFF"
        self.follow_toggle_button.text = f"FOLLOW {state}"
