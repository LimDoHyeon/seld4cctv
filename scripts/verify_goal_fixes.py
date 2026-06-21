from pathlib import Path


REPO_ROOT = Path("/home/user/Documents/DT_teamA/omniverse")
SIM_DIR = REPO_ROOT / "cctv_sim" / "scripts" / "sim"


def _read(path):
    return path.read_text(encoding="utf-8")


def _assert_contains(text, needle, label):
    if needle not in text:
        raise AssertionError(f"Missing {label}: {needle}")


def _assert_not_contains(text, needle, label):
    if needle in text:
        raise AssertionError(f"Unexpected {label}: {needle}")


def _extract_block(text, anchor, until):
    start = text.find(anchor)
    if start < 0:
        raise AssertionError(f"Anchor not found: {anchor}")
    end = text.find(until, start)
    if end < 0:
        raise AssertionError(f"End marker not found after {anchor}: {until}")
    return text[start:end]


def main():
    ui_text = _read(SIM_DIR / "ui.py")
    follow_text = _read(SIM_DIR / "follow_top_camera.py")
    config_text = _read(SIM_DIR / "config.py")
    awareness_text = _read(SIM_DIR / "awareness.py")
    minimap_text = _read(SIM_DIR / "minimap_window.py")

    gun_block = _extract_block(ui_text, 'if event_type == "gun":', "event = self.app.events.trigger")
    _assert_contains(
        gun_block,
        "follow_position = self.app.track_event_position_if_enabled(event_position)",
        "gun event track call",
    )
    _assert_not_contains(
        gun_block,
        "focus_event_position_immediate_with_zoom",
        "gun event teleport call",
    )

    _assert_contains(config_text, "FOLLOW_TOP_CAMERA_MOVE_SPEED = 900.0", "move speed config")
    _assert_contains(config_text, "FOLLOW_TOP_CAMERA_CHASE_SPEED = 1400.0", "chase speed config")
    _assert_contains(config_text, "FOLLOW_TOP_CAMERA_MOVE_MAX_TRAVEL_SEC = 2.0", "move max travel config")
    _assert_contains(config_text, "FOLLOW_TOP_CAMERA_CHASE_MAX_TRAVEL_SEC = 0.75", "chase max travel config")

    _assert_contains(
        follow_text,
        '"speed": self.move_speed',
        "default event move speed request",
    )
    _assert_contains(
        follow_text,
        '"max_travel_sec": self.move_max_travel_sec',
        "default event max travel request",
    )
    _assert_contains(
        follow_text,
        '"speed": self.chase_speed',
        "gun chase speed request",
    )
    _assert_contains(
        follow_text,
        '"max_travel_sec": self.chase_max_travel_sec',
        "gun chase max travel request",
    )
    _assert_contains(
        follow_text,
        "self._move_speed = max(base_speed, distance_scaled_speed)",
        "distance-aware speed scaling",
    )
    _assert_not_contains(
        follow_text,
        "self._pending_move_request = request",
        "deferred move queue",
    )
    _assert_contains(
        follow_text,
        "self._move_duration_sec = max(travel_distance / self._move_speed, 1e-3)",
        "speed-based travel duration",
    )
    _assert_contains(
        follow_text,
        "current_stage_x = start_stage_xy[0] + (target_stage_x - start_stage_xy[0]) * progress",
        "non-teleport staged X interpolation",
    )
    _assert_contains(
        follow_text,
        "current_stage_y = start_stage_xy[1] + (target_stage_y - start_stage_xy[1]) * progress",
        "non-teleport staged Y interpolation",
    )

    _assert_contains(awareness_text, 'CCTV_DOT_STYLE = {"background_color": 0xFFFF7A00}', "awareness CCTV color")
    _assert_contains(awareness_text, 'DRONE_DOT_STYLE = {"background_color": 0xFF2F8FFF}', "awareness drone color")
    _assert_contains(minimap_text, 'DRONE_DOT_STYLE = {"background_color": 0xFF2F8FFF}', "minimap drone color")

    print("[verify_goal_fixes] PASS")


if __name__ == "__main__":
    main()
