import builtins

from pxr import Gf, Sdf, UsdGeom

from .config import (
    CCTV_AIM_DURATION_SEC,
    CCTV_TELE_FOCAL_LENGTH,
    CCTV_WIDE_FOCAL_LENGTH,
    CCTV_ZOOM_FAR_DISTANCE_M,
    CCTV_ZOOM_NEAR_DISTANCE_M,
    FOLLOW_TOP_CAMERA_CLIPPING_RANGE,
    FOLLOW_TOP_CAMERA_FOCAL_LENGTH,
    FOLLOW_TOP_CAMERA_FRAME_MARGIN,
    FOLLOW_TOP_CAMERA_CHASE_MAX_TRAVEL_SEC,
    FOLLOW_TOP_CAMERA_CHASE_SPEED,
    FOLLOW_TOP_CAMERA_FIXED_HEIGHT,
    FOLLOW_TOP_CAMERA_HORIZONTAL_APERTURE,
    FOLLOW_TOP_CAMERA_MOVE_MAX_TRAVEL_SEC,
    FOLLOW_TOP_CAMERA_MOVE_SPEED,
    FOLLOW_TOP_CAMERA_NAME,
    FOLLOW_TOP_CAMERA_RIG_NAME,
    FOLLOW_TOP_CAMERA_VISUAL_SCALE,
    FOLLOW_TOP_CAMERA_VIEWPORT_ASPECT,
)
from .drone_rig import DroneRig
from .usd_utils import ensure_xform, get_or_create_transform_ops, get_stage


PERSPECTIVE_CAMERA_PATH = "/OmniverseKit_Persp"


def _ensure_world_root(stage):
    world = stage.GetPrimAtPath("/World")
    if world.IsValid():
        return world
    return ensure_xform(stage, "/World")


def resolve_follow_top_camera_root(stage):
    default_prim = stage.GetDefaultPrim()
    if default_prim and default_prim.IsValid():
        return str(default_prim.GetPath())
    return str(_ensure_world_root(stage).GetPath())


def _rig_translate_and_rotate(height):
    stage = get_stage()
    up_axis = UsdGeom.GetStageUpAxis(stage)
    if up_axis == UsdGeom.Tokens.y:
        return (0.0, float(height), 0.0), (-90.0, 0.0, 0.0)
    return (0.0, 0.0, float(height)), (0.0, 0.0, 0.0)


class FollowTopCameraController:
    def __init__(
        self,
        fixed_height=FOLLOW_TOP_CAMERA_FIXED_HEIGHT,
        clipping_range=FOLLOW_TOP_CAMERA_CLIPPING_RANGE,
        focal_length=FOLLOW_TOP_CAMERA_FOCAL_LENGTH,
        horizontal_aperture=FOLLOW_TOP_CAMERA_HORIZONTAL_APERTURE,
        frame_margin=FOLLOW_TOP_CAMERA_FRAME_MARGIN,
        move_speed=FOLLOW_TOP_CAMERA_MOVE_SPEED,
        chase_speed=FOLLOW_TOP_CAMERA_CHASE_SPEED,
        move_max_travel_sec=FOLLOW_TOP_CAMERA_MOVE_MAX_TRAVEL_SEC,
        chase_max_travel_sec=FOLLOW_TOP_CAMERA_CHASE_MAX_TRAVEL_SEC,
    ):
        self.fixed_height = float(fixed_height)
        self.current_height = float(fixed_height)
        self.clipping_range = (float(clipping_range[0]), float(clipping_range[1]))
        self.default_focal_length = float(focal_length)
        self.focal_length = float(focal_length)
        self.horizontal_aperture = float(horizontal_aperture)
        self.frame_margin = max(float(frame_margin), 1.0)
        self.move_speed = max(float(move_speed), 1e-3)
        self.chase_speed = max(float(chase_speed), self.move_speed)
        self.move_max_travel_sec = max(float(move_max_travel_sec), 1e-3)
        self.chase_max_travel_sec = max(float(chase_max_travel_sec), 1e-3)
        self.viewport_aspect = (
            float(FOLLOW_TOP_CAMERA_VIEWPORT_ASPECT[0]),
            float(FOLLOW_TOP_CAMERA_VIEWPORT_ASPECT[1]),
        )
        self.root_path = ""
        self.rig_path = ""
        self.camera_path = ""
        self.drone_rig = None
        self.has_target_position = False
        self.target_stage_xy = None
        self.target_height_meters = float(fixed_height)
        self._move_start_stage_xy = None
        self._move_start_height_meters = float(fixed_height)
        self._move_elapsed = 0.0
        self._move_duration_sec = 0.0
        self._move_speed = self.move_speed
        self._zoom_start_focal_length = float(focal_length)
        self._zoom_target_focal_length = None
        self._zoom_elapsed = 0.0
        self._zoom_duration_sec = max(float(CCTV_AIM_DURATION_SEC), 1e-3)
        self._active_event_remaining_sec = None

    def setup(self):
        stage = get_stage()
        self.root_path = resolve_follow_top_camera_root(stage)
        self.rig_path = f"{self.root_path.rstrip('/')}/{FOLLOW_TOP_CAMERA_RIG_NAME}"
        self.camera_path = f"{self.rig_path}/{FOLLOW_TOP_CAMERA_NAME}"
        self.drone_rig = DroneRig(
            rig_path=self.rig_path,
            fixed_altitude=self.fixed_height,
            visual_scale=FOLLOW_TOP_CAMERA_VISUAL_SCALE,
            camera_name=FOLLOW_TOP_CAMERA_NAME,
            focal_length=self.default_focal_length,
            horizontal_aperture=self.horizontal_aperture,
            clipping_range=self.clipping_range,
            viewport_aspect=self.viewport_aspect,
        ).create()
        self.camera_path = self.drone_rig.get_camera_path()

        rig_prim = ensure_xform(stage, self.rig_path)
        rig_translate_op, rig_rotate_op, rig_scale_op = get_or_create_transform_ops(UsdGeom.Xformable(rig_prim))
        current_rig_translate = rig_translate_op.Get()
        if current_rig_translate is None:
            current_rig_translate = Gf.Vec3d(*self._initial_rig_translate())
            rig_translate_op.Set(current_rig_translate)
        rig_rotate_op.Set(Gf.Vec3f(*self._rig_rotate()))
        rig_scale_op.Set(Gf.Vec3f(1.0, 1.0, 1.0))

        camera = UsdGeom.Camera.Get(stage, Sdf.Path(self.camera_path))
        self._configure_camera(camera)
        return self.describe()

    def _configure_camera(self, camera):
        vertical_aperture = self._vertical_aperture()
        camera.CreateProjectionAttr().Set(UsdGeom.Tokens.perspective)
        camera.CreateClippingRangeAttr().Set(Gf.Vec2f(*self.clipping_range))
        camera.CreateHorizontalApertureAttr().Set(self.horizontal_aperture)
        camera.CreateVerticalApertureAttr().Set(vertical_aperture)
        camera.CreateFocalLengthAttr().Set(self.focal_length)

    def set_stage_xy(self, stage_x, stage_y, height=None):
        target_height_meters = float(self.fixed_height if height is None else height)
        target_height_stage_units = self._stage_units_from_meters(target_height_meters)
        return self._set_stage_xy_with_stage_height(stage_x, stage_y, target_height_stage_units, target_height_meters)

    def move_toward_stage_xy(self, stage_x, stage_y, height=None, immediate=False):
        return self.move_toward_stage_xy_with_duration(stage_x, stage_y, height=height, duration_sec=None, immediate=immediate)

    def move_toward_stage_xy_with_duration(self, stage_x, stage_y, height=None, duration_sec=None, immediate=False):
        target_height_meters = float(self.fixed_height if height is None else height)
        if immediate:
            self.restore_default_zoom(immediate=True)
            self.clear_motion_target()
            updated = self.set_stage_xy(stage_x, stage_y, height=target_height_meters)
            self._set_active_event_duration(duration_sec)
            return updated

        current_stage_xy, current_height_meters = self.get_current_stage_xy_height()
        if not self._requires_motion(current_stage_xy, current_height_meters, stage_x, stage_y, target_height_meters):
            self.has_target_position = True
            self._set_active_event_duration(duration_sec)
            self.queue_arrival_zoom(target_height_meters)
            return current_stage_xy[0], current_stage_xy[1], current_height_meters

        request = {
            "stage_x": float(stage_x),
            "stage_y": float(stage_y),
            "height_meters": target_height_meters,
            "duration_sec": duration_sec,
            "speed": self.move_speed,
            "max_travel_sec": self.move_max_travel_sec,
        }
        if self._is_zoomed_in():
            self.restore_default_zoom(immediate=False)

        return self._start_move_request(request, current_stage_xy=current_stage_xy, current_height_meters=current_height_meters)

    def _set_stage_xy_with_stage_height(self, stage_x, stage_y, height_stage_units, height_meters):
        if not self.rig_path:
            self.setup()

        self.current_height = float(height_meters)
        if self.drone_rig is not None:
            self.drone_rig.set_altitude(self.current_height)
            self.drone_rig.set_position_xy(stage_x, stage_y)
            self.has_target_position = True
            return self.drone_rig.get_position_xy_altitude()

        stage = get_stage()
        rig_prim = stage.GetPrimAtPath(self.rig_path)
        if not rig_prim.IsValid():
            self.setup()
            rig_prim = stage.GetPrimAtPath(self.rig_path)

        translate_op, rotate_op, scale_op = get_or_create_transform_ops(UsdGeom.Xformable(rig_prim))
        target_height = float(height_stage_units)
        up_axis = UsdGeom.GetStageUpAxis(stage)
        if up_axis == UsdGeom.Tokens.y:
            updated = Gf.Vec3d(float(stage_x), target_height, float(stage_y))
        else:
            updated = Gf.Vec3d(float(stage_x), float(stage_y), target_height)

        translate_op.Set(updated)
        rotate_op.Set(Gf.Vec3f(*self._rig_rotate()))
        scale_op.Set(Gf.Vec3f(1.0, 1.0, 1.0))
        self.has_target_position = True
        return tuple(float(component) for component in updated)

    def get_current_stage_xy_height(self):
        if not self.rig_path:
            self.setup()

        stage = get_stage()
        rig_prim = stage.GetPrimAtPath(self.rig_path)
        if not rig_prim.IsValid():
            self.setup()
            rig_prim = stage.GetPrimAtPath(self.rig_path)

        translate_op, _, _ = get_or_create_transform_ops(UsdGeom.Xformable(rig_prim))
        current = translate_op.Get()
        if current is None:
            current = Gf.Vec3d(*self._initial_rig_translate())

        up_axis = UsdGeom.GetStageUpAxis(stage)
        if up_axis == UsdGeom.Tokens.y:
            stage_x = float(current[0])
            stage_y = float(current[2])
            height_stage_units = float(current[1])
        else:
            stage_x = float(current[0])
            stage_y = float(current[1])
            height_stage_units = float(current[2])

        return (stage_x, stage_y), self._meters_from_stage_units(height_stage_units)

    def set_world_position(self, world_position):
        stage = get_stage()
        up_axis = UsdGeom.GetStageUpAxis(stage)
        if up_axis == UsdGeom.Tokens.y:
            return self.set_stage_xy(world_position[0], world_position[2])
        return self.set_stage_xy(world_position[0], world_position[1])

    def move_toward_world_position(self, world_position, immediate=False):
        return self.move_toward_world_position_with_duration(
            world_position,
            duration_sec=None,
            immediate=immediate,
        )

    def move_toward_world_position_with_duration(self, world_position, duration_sec=None, immediate=False):
        stage = get_stage()
        up_axis = UsdGeom.GetStageUpAxis(stage)
        if up_axis == UsdGeom.Tokens.y:
            return self.move_toward_stage_xy_with_duration(
                world_position[0],
                world_position[2],
                duration_sec=duration_sec,
                immediate=immediate,
            )
        return self.move_toward_stage_xy_with_duration(
            world_position[0],
            world_position[1],
            duration_sec=duration_sec,
                immediate=immediate,
            )

    def move_toward_world_position_preserving_zoom(self, world_position, duration_sec=None):
        stage = get_stage()
        up_axis = UsdGeom.GetStageUpAxis(stage)
        if up_axis == UsdGeom.Tokens.y:
            return self._move_toward_stage_xy_preserving_zoom_with_duration(
                world_position[0],
                world_position[2],
                height=self.fixed_height,
                duration_sec=duration_sec,
            )
        return self._move_toward_stage_xy_preserving_zoom_with_duration(
            world_position[0],
            world_position[1],
            height=self.fixed_height,
            duration_sec=duration_sec,
        )

    def focus_world_position_immediate_with_zoom(self, world_position, duration_sec=None):
        stage = get_stage()
        up_axis = UsdGeom.GetStageUpAxis(stage)
        if up_axis == UsdGeom.Tokens.y:
            return self._focus_stage_xy_immediate_with_zoom(
                world_position[0],
                world_position[2],
                height=self.fixed_height,
                duration_sec=duration_sec,
            )
        return self._focus_stage_xy_immediate_with_zoom(
            world_position[0],
            world_position[1],
            height=self.fixed_height,
            duration_sec=duration_sec,
        )

    def bind_to_active_viewport(self):
        if not self.camera_path:
            self.setup()
        return switch_viewport_camera(self.camera_path)

    def frame_stage_extent(self, extent):
        center_x = (float(extent.min_x) + float(extent.max_x)) * 0.5
        center_y = (float(extent.min_y) + float(extent.max_y)) * 0.5
        width = max(float(extent.max_x) - float(extent.min_x), 1.0)
        height = max(float(extent.max_y) - float(extent.min_y), 1.0)
        required_height_stage_units = self._height_for_extent(width, height)
        required_height_meters = self._meters_from_stage_units(required_height_stage_units)
        return self._set_stage_xy_with_stage_height(
            center_x,
            center_y,
            required_height_stage_units,
            required_height_meters,
        )

    def center_stage_extent(self, extent, height=None):
        center_x = (float(extent.min_x) + float(extent.max_x)) * 0.5
        center_y = (float(extent.min_y) + float(extent.max_y)) * 0.5
        return self.set_stage_xy(center_x, center_y, height=height)

    def restore_default_view(self):
        self.current_height = float(self.fixed_height)
        self.has_target_position = False
        self.clear_motion_target()
        self.restore_default_zoom(immediate=True)

    def clear_motion_target(self):
        self.target_stage_xy = None
        self.target_height_meters = float(self.current_height)
        self._move_start_stage_xy = None
        self._move_start_height_meters = float(self.current_height)
        self._move_elapsed = 0.0
        self._move_duration_sec = 0.0

    def restore_default_zoom(self, immediate=False):
        target_focal_length = float(self.default_focal_length)
        if immediate:
            self._zoom_target_focal_length = None
            self._zoom_elapsed = 0.0
            self._set_focal_length(target_focal_length)
            return target_focal_length

        current_focal_length = self.get_current_focal_length()
        if abs(current_focal_length - target_focal_length) <= 1e-6:
            self._zoom_target_focal_length = None
            self._zoom_elapsed = 0.0
            return current_focal_length

        self._zoom_start_focal_length = current_focal_length
        self._zoom_target_focal_length = target_focal_length
        self._zoom_elapsed = 0.0
        return target_focal_length

    def queue_arrival_zoom(self, height_meters=None):
        zoom_distance = float(self.current_height if height_meters is None else height_meters)
        target_focal_length = self._target_zoom_focal_length(zoom_distance)
        current_focal_length = self.get_current_focal_length()
        if abs(current_focal_length - target_focal_length) <= 1e-6:
            self._zoom_target_focal_length = None
            self._zoom_elapsed = 0.0
            return target_focal_length

        self._zoom_start_focal_length = current_focal_length
        self._zoom_target_focal_length = target_focal_length
        self._zoom_elapsed = 0.0
        return target_focal_length

    def update(self, dt):
        updated = None
        step_dt = max(float(dt), 0.0)

        if self.target_stage_xy is not None:
            self._move_elapsed += step_dt
            progress = min(self._move_elapsed / max(self._move_duration_sec, 1e-3), 1.0)

            start_stage_xy = self._move_start_stage_xy or self.get_current_stage_xy_height()[0]
            start_height_meters = float(self._move_start_height_meters)
            target_stage_x, target_stage_y = self.target_stage_xy
            current_stage_x = start_stage_xy[0] + (target_stage_x - start_stage_xy[0]) * progress
            current_stage_y = start_stage_xy[1] + (target_stage_y - start_stage_xy[1]) * progress
            current_height_meters = start_height_meters + (self.target_height_meters - start_height_meters) * progress
            updated = self.set_stage_xy(current_stage_x, current_stage_y, height=current_height_meters)

            if progress >= 1.0:
                arrived_height_meters = float(self.target_height_meters)
                self.clear_motion_target()
                self.queue_arrival_zoom(arrived_height_meters)

        if self._active_event_remaining_sec is not None:
            self._active_event_remaining_sec -= step_dt
            if self._active_event_remaining_sec <= 0.0:
                self._active_event_remaining_sec = None
                self.restore_default_zoom(immediate=False)

        if self._zoom_target_focal_length is not None:
            self._zoom_elapsed += step_dt
            progress = min(self._zoom_elapsed / self._zoom_duration_sec, 1.0)
            eased = progress * progress * (3.0 - 2.0 * progress)
            focal_length = self._zoom_start_focal_length + (
                self._zoom_target_focal_length - self._zoom_start_focal_length
            ) * eased
            self._set_focal_length(focal_length)
            if progress >= 1.0:
                self._set_focal_length(self._zoom_target_focal_length)
                self._zoom_target_focal_length = None
                self._zoom_elapsed = 0.0

        return updated

    def describe(self):
        return {
            "root_path": self.root_path,
            "rig_path": self.rig_path,
            "camera_path": self.camera_path,
            "fixed_height_meters": self.fixed_height,
            "current_height_meters": self.current_height,
            "fixed_height_stage_units": self._stage_units_from_meters(self.fixed_height),
            "current_height_stage_units": self._stage_units_from_meters(self.current_height),
            "default_focal_length": self.default_focal_length,
            "current_focal_length": self.get_current_focal_length(),
            "focal_length": self.focal_length,
            "active_event_remaining_sec": self._active_event_remaining_sec,
            "horizontal_aperture": self.horizontal_aperture,
            "viewport_aspect": self.viewport_aspect,
            "clipping_range": self.clipping_range,
        }

    def _initial_rig_translate(self):
        translate, _ = _rig_translate_and_rotate(self._stage_units_from_meters(self.fixed_height))
        return translate

    def _rig_rotate(self):
        _, rotate = _rig_translate_and_rotate(self.fixed_height)
        return rotate

    def _vertical_aperture(self):
        aspect_x = max(float(self.viewport_aspect[0]), 1.0)
        aspect_y = max(float(self.viewport_aspect[1]), 1.0)
        return self.horizontal_aperture * (aspect_y / aspect_x)

    def _height_for_extent(self, width, height):
        framed_width = max(float(width) * self.frame_margin, 1.0)
        framed_height = max(float(height) * self.frame_margin, 1.0)
        vertical_aperture = max(self._vertical_aperture(), 1e-6)
        distance_x = framed_width * self.focal_length / max(self.horizontal_aperture, 1e-6)
        distance_y = framed_height * self.focal_length / vertical_aperture
        return max(distance_x, distance_y, self._stage_units_from_meters(self.fixed_height))

    def _stage_units_from_meters(self, meters):
        stage = get_stage()
        meters_per_unit = UsdGeom.GetStageMetersPerUnit(stage)
        meters_per_unit = max(float(meters_per_unit), 1e-9)
        return float(meters) / meters_per_unit

    def _meters_from_stage_units(self, stage_units):
        stage = get_stage()
        meters_per_unit = max(float(UsdGeom.GetStageMetersPerUnit(stage)), 1e-9)
        return float(stage_units) * meters_per_unit

    def get_current_focal_length(self):
        if not self.camera_path:
            self.setup()

        stage = get_stage()
        camera_prim = stage.GetPrimAtPath(self.camera_path)
        if not camera_prim.IsValid():
            self.setup()
            camera_prim = stage.GetPrimAtPath(self.camera_path)
        if not camera_prim.IsValid():
            return float(self.default_focal_length)

        camera = UsdGeom.Camera(camera_prim)
        value = camera.GetFocalLengthAttr().Get()
        if value is None:
            return float(self.default_focal_length)
        return float(value)

    def _set_focal_length(self, focal_length):
        if not self.camera_path:
            self.setup()

        stage = get_stage()
        camera_prim = stage.GetPrimAtPath(self.camera_path)
        if not camera_prim.IsValid():
            self.setup()
            camera_prim = stage.GetPrimAtPath(self.camera_path)
        if not camera_prim.IsValid():
            return None

        UsdGeom.Camera(camera_prim).GetFocalLengthAttr().Set(float(focal_length))
        self.focal_length = float(focal_length)
        return self.focal_length

    def _target_zoom_focal_length(self, distance_meters):
        near = min(float(CCTV_ZOOM_NEAR_DISTANCE_M), float(CCTV_ZOOM_FAR_DISTANCE_M))
        far = max(float(CCTV_ZOOM_NEAR_DISTANCE_M), float(CCTV_ZOOM_FAR_DISTANCE_M))
        if far <= near:
            return float(CCTV_WIDE_FOCAL_LENGTH)

        t = (float(distance_meters) - near) / (far - near)
        t = max(0.0, min(t, 1.0))
        return float(CCTV_WIDE_FOCAL_LENGTH) + (float(CCTV_TELE_FOCAL_LENGTH) - float(CCTV_WIDE_FOCAL_LENGTH)) * t

    def _requires_motion(self, current_stage_xy, current_height_meters, stage_x, stage_y, target_height_meters):
        return (
            abs(float(stage_x) - float(current_stage_xy[0])) > 1e-3
            or abs(float(stage_y) - float(current_stage_xy[1])) > 1e-3
            or abs(float(target_height_meters) - float(current_height_meters)) > 1e-6
        )

    def _is_zoomed_in(self):
        return abs(self.get_current_focal_length() - float(self.default_focal_length)) > 1e-6 or (
            self._zoom_target_focal_length is not None and abs(float(self._zoom_target_focal_length) - float(self.default_focal_length)) > 1e-6
        )

    def _set_active_event_duration(self, duration_sec):
        if duration_sec is None:
            self._active_event_remaining_sec = None
            return
        self._active_event_remaining_sec = max(float(duration_sec), 0.0)

    def _move_toward_stage_xy_preserving_zoom_with_duration(self, stage_x, stage_y, height=None, duration_sec=None):
        target_height_meters = float(self.fixed_height if height is None else height)
        current_stage_xy, current_height_meters = self.get_current_stage_xy_height()
        if not self._requires_motion(current_stage_xy, current_height_meters, stage_x, stage_y, target_height_meters):
            self.has_target_position = True
            self._set_active_event_duration(duration_sec)
            if not self._is_zoomed_in():
                self.queue_arrival_zoom(target_height_meters)
            return current_stage_xy[0], current_stage_xy[1], current_height_meters

        request = {
            "stage_x": float(stage_x),
            "stage_y": float(stage_y),
            "height_meters": target_height_meters,
            "duration_sec": duration_sec,
            "speed": self.chase_speed,
            "max_travel_sec": self.chase_max_travel_sec,
        }
        return self._start_move_request(request, current_stage_xy=current_stage_xy, current_height_meters=current_height_meters)

    def _focus_stage_xy_immediate_with_zoom(self, stage_x, stage_y, height=None, duration_sec=None):
        target_height_meters = float(self.fixed_height if height is None else height)
        self.clear_motion_target()
        updated = self.set_stage_xy(stage_x, stage_y, height=target_height_meters)
        self._set_active_event_duration(duration_sec)
        self.queue_arrival_zoom(target_height_meters)
        return updated

    def _start_move_request(self, request, current_stage_xy=None, current_height_meters=None):
        if current_stage_xy is None or current_height_meters is None:
            current_stage_xy, current_height_meters = self.get_current_stage_xy_height()

        self._move_start_stage_xy = current_stage_xy
        self._move_start_height_meters = current_height_meters
        self.target_stage_xy = (float(request["stage_x"]), float(request["stage_y"]))
        self.target_height_meters = float(request["height_meters"])
        base_speed = max(float(request.get("speed", self.move_speed)), 1e-3)
        horizontal_distance = (
            (self.target_stage_xy[0] - current_stage_xy[0]) ** 2
            + (self.target_stage_xy[1] - current_stage_xy[1]) ** 2
        ) ** 0.5
        height_distance = abs(self.target_height_meters - current_height_meters)
        travel_distance = max(horizontal_distance, height_distance)
        max_travel_sec = max(float(request.get("max_travel_sec", 0.0)), 1e-3)
        distance_scaled_speed = travel_distance / max_travel_sec
        self._move_speed = max(base_speed, distance_scaled_speed)
        self._move_elapsed = 0.0
        self._move_duration_sec = max(travel_distance / self._move_speed, 1e-3)
        self.has_target_position = True
        self._set_active_event_duration(request.get("duration_sec"))
        return self.target_stage_xy[0], self.target_stage_xy[1], self.target_height_meters


def switch_viewport_camera(camera_path):
    def _assign_camera_path(target, attr_name):
        errors = []
        for value in (str(camera_path), Sdf.Path(str(camera_path))):
            try:
                setattr(target, attr_name, value)
                return True, None
            except Exception as exc:
                errors.append(exc)
        return False, errors[-1] if errors else None

    try:
        from omni.kit.viewport.utility import get_active_viewport

        viewport = get_active_viewport()
        if viewport is not None:
            ok, error = _assign_camera_path(viewport, "camera_path")
            if ok:
                return True, f"Viewport camera: {camera_path}"
            last_error = error
    except Exception as exc:
        last_error = exc
    else:
        last_error = locals().get("last_error", None)

    try:
        from omni.kit.viewport.utility import get_active_viewport_window

        viewport_window = get_active_viewport_window()
        if viewport_window is not None and hasattr(viewport_window, "viewport_api"):
            ok, error = _assign_camera_path(viewport_window.viewport_api, "camera_path")
            if ok:
                return True, f"Viewport camera: {camera_path}"
            last_error = error
    except Exception as exc:
        last_error = exc

    try:
        import omni.kit.viewport_legacy as viewport_legacy

        viewport_interface = viewport_legacy.get_viewport_interface()
        viewport_window = viewport_interface.get_viewport_window()
        viewport_window.set_active_camera(camera_path)
        return True, f"Viewport camera: {camera_path}"
    except Exception as exc:
        last_error = exc

    return False, f"Unable to switch viewport camera: {last_error}"


def switch_to_perspective():
    return switch_viewport_camera(PERSPECTIVE_CAMERA_PATH)


def install_follow_top_camera_controller(
    fixed_height=FOLLOW_TOP_CAMERA_FIXED_HEIGHT,
    clipping_range=FOLLOW_TOP_CAMERA_CLIPPING_RANGE,
    focal_length=FOLLOW_TOP_CAMERA_FOCAL_LENGTH,
    horizontal_aperture=FOLLOW_TOP_CAMERA_HORIZONTAL_APERTURE,
    frame_margin=FOLLOW_TOP_CAMERA_FRAME_MARGIN,
):
    controller = FollowTopCameraController(
        fixed_height=fixed_height,
        clipping_range=clipping_range,
        focal_length=focal_length,
        horizontal_aperture=horizontal_aperture,
        frame_margin=frame_margin,
    )
    controller.setup()
    setattr(builtins, "follow_top_camera_controller", controller)
    return controller


def get_installed_follow_top_camera_controller():
    return getattr(builtins, "follow_top_camera_controller", None)


def ensure_follow_top_camera_controller(
    fixed_height=FOLLOW_TOP_CAMERA_FIXED_HEIGHT,
    clipping_range=FOLLOW_TOP_CAMERA_CLIPPING_RANGE,
    focal_length=FOLLOW_TOP_CAMERA_FOCAL_LENGTH,
    horizontal_aperture=FOLLOW_TOP_CAMERA_HORIZONTAL_APERTURE,
    frame_margin=FOLLOW_TOP_CAMERA_FRAME_MARGIN,
):
    controller = get_installed_follow_top_camera_controller()
    if controller is None:
        controller = install_follow_top_camera_controller(
            fixed_height=fixed_height,
            clipping_range=clipping_range,
            focal_length=focal_length,
            horizontal_aperture=horizontal_aperture,
            frame_margin=frame_margin,
        )
    else:
        controller.setup()
    return controller
