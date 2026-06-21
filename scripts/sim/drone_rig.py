import omni.client
from pxr import Gf, Sdf, Usd, UsdGeom

from .config import (
    CRAZYFLIE_ASSET_CANDIDATES,
    FOLLOW_TOP_CAMERA_CAMERA_LOCAL_OFFSET,
    FOLLOW_TOP_CAMERA_CAMERA_ROTATE_XYZ_Y_UP,
    FOLLOW_TOP_CAMERA_CAMERA_ROTATE_XYZ_Z_UP,
    FOLLOW_TOP_CAMERA_CLIPPING_RANGE,
    FOLLOW_TOP_CAMERA_FOCAL_LENGTH,
    FOLLOW_TOP_CAMERA_HORIZONTAL_APERTURE,
    FOLLOW_TOP_CAMERA_NAME,
    FOLLOW_TOP_CAMERA_RIG_NAME,
    FOLLOW_TOP_CAMERA_VIEWPORT_ASPECT,
    FOLLOW_TOP_CAMERA_VISUAL_NAME,
    FOLLOW_TOP_CAMERA_VISUAL_SCALE,
    USER_DEFINED_CRAZYFLIE_PATH,
)
from .usd_utils import ensure_xform, get_or_create_transform_ops, get_stage


def _path_exists(path):
    if not path:
        return False
    try:
        result, _ = omni.client.stat(path)
        return result == omni.client.Result.OK
    except Exception:
        return False


class DroneRig:
    def __init__(
        self,
        rig_path=f"/World/{FOLLOW_TOP_CAMERA_RIG_NAME}",
        crazyflie_asset_path=None,
        fixed_altitude=20.0,
        visual_scale=FOLLOW_TOP_CAMERA_VISUAL_SCALE,
        camera_name=FOLLOW_TOP_CAMERA_NAME,
        visual_name=FOLLOW_TOP_CAMERA_VISUAL_NAME,
        focal_length=FOLLOW_TOP_CAMERA_FOCAL_LENGTH,
        horizontal_aperture=FOLLOW_TOP_CAMERA_HORIZONTAL_APERTURE,
        clipping_range=FOLLOW_TOP_CAMERA_CLIPPING_RANGE,
        viewport_aspect=FOLLOW_TOP_CAMERA_VIEWPORT_ASPECT,
    ):
        self.stage = None
        self.rig_path = Sdf.Path(rig_path)
        self.visual_path = self.rig_path.AppendChild(visual_name)
        self.camera_path = self.rig_path.AppendChild(camera_name)
        self.crazyflie_asset_path = crazyflie_asset_path or USER_DEFINED_CRAZYFLIE_PATH
        self.fixed_altitude = float(fixed_altitude)
        self.visual_scale = float(visual_scale)
        self.focal_length = float(focal_length)
        self.horizontal_aperture = float(horizontal_aperture)
        self.clipping_range = (float(clipping_range[0]), float(clipping_range[1]))
        self.viewport_aspect = (float(viewport_aspect[0]), float(viewport_aspect[1]))
        self._translate_op = None
        self._rotate_op = None
        self._scale_op = None
        self._visual_scale_op = None
        self._asset_unit_scale = 1.0
        self._x = 0.0
        self._y = 0.0
        self._yaw_deg = 0.0
        self._resolved_asset_path = None

    def create(self):
        self.stage = get_stage()
        if self.stage is None:
            raise RuntimeError("No active USD stage found.")
        self._create_rig_root()
        self._create_crazyflie_visual()
        self._make_visual_only(str(self.visual_path))
        self._restore_visual_visibility()
        self._create_top_view_camera()
        self.set_position_xy(self._x, self._y)
        self.set_yaw_deg(self._yaw_deg)
        self.set_visual_scale(self.visual_scale)
        return self

    def _create_rig_root(self):
        rig_prim = ensure_xform(self.stage, str(self.rig_path))
        rig_xform = UsdGeom.Xformable(rig_prim)
        self._translate_op, self._rotate_op, self._scale_op = get_or_create_transform_ops(rig_xform)
        self._scale_op.Set(Gf.Vec3f(1.0, 1.0, 1.0))

    def _create_crazyflie_visual(self):
        visual_prim = ensure_xform(self.stage, str(self.visual_path))
        visual_xform = UsdGeom.Xformable(visual_prim)
        _, _, self._visual_scale_op = get_or_create_transform_ops(visual_xform)
        asset_path = self._resolve_crazyflie_asset_path()
        if asset_path is None:
            raise FileNotFoundError(
                "Could not resolve Crazyflie asset path. "
                "Set crazyflie_asset_path explicitly or update candidate paths."
            )

        refs = visual_prim.GetReferences()
        refs.ClearReferences()
        refs.AddReference(asset_path)
        self._resolved_asset_path = asset_path
        self._asset_unit_scale = self._compute_asset_unit_scale(asset_path)
        print(f"[DroneRig] Crazyflie visual referenced from: {asset_path}")

    def _resolve_crazyflie_asset_path(self):
        if self.crazyflie_asset_path:
            return self.crazyflie_asset_path

        for candidate in CRAZYFLIE_ASSET_CANDIDATES:
            if _path_exists(candidate):
                return candidate

        if CRAZYFLIE_ASSET_CANDIDATES:
            print("[DroneRig] Crazyflie asset candidates were not confirmed via omni.client.stat; using first candidate")
            return CRAZYFLIE_ASSET_CANDIDATES[0]
        return None

    def _create_top_view_camera(self):
        camera = UsdGeom.Camera.Define(self.stage, self.camera_path)
        camera_prim = camera.GetPrim()
        camera_xform = UsdGeom.Xformable(camera_prim)
        translate_op, rotate_op, scale_op = get_or_create_transform_ops(camera_xform)

        stage_up_axis = UsdGeom.GetStageUpAxis(self.stage)
        if stage_up_axis == UsdGeom.Tokens.y:
            local_offset = Gf.Vec3d(
                self._meters_to_stage_units(FOLLOW_TOP_CAMERA_CAMERA_LOCAL_OFFSET[0]),
                self._meters_to_stage_units(FOLLOW_TOP_CAMERA_CAMERA_LOCAL_OFFSET[2]),
                self._meters_to_stage_units(FOLLOW_TOP_CAMERA_CAMERA_LOCAL_OFFSET[1]),
            )
            rotate_xyz = Gf.Vec3f(*FOLLOW_TOP_CAMERA_CAMERA_ROTATE_XYZ_Y_UP)
        else:
            local_offset = Gf.Vec3d(
                self._meters_to_stage_units(FOLLOW_TOP_CAMERA_CAMERA_LOCAL_OFFSET[0]),
                self._meters_to_stage_units(FOLLOW_TOP_CAMERA_CAMERA_LOCAL_OFFSET[1]),
                self._meters_to_stage_units(FOLLOW_TOP_CAMERA_CAMERA_LOCAL_OFFSET[2]),
            )
            rotate_xyz = Gf.Vec3f(*FOLLOW_TOP_CAMERA_CAMERA_ROTATE_XYZ_Z_UP)

        translate_op.Set(local_offset)
        rotate_op.Set(rotate_xyz)
        scale_op.Set(Gf.Vec3f(1.0, 1.0, 1.0))
        camera.GetFocalLengthAttr().Set(self.focal_length)
        camera.GetClippingRangeAttr().Set(Gf.Vec2f(*self.clipping_range))
        camera.GetHorizontalApertureAttr().Set(self.horizontal_aperture)
        camera.GetVerticalApertureAttr().Set(self._vertical_aperture())

        imageable = UsdGeom.Imageable(camera_prim)
        if imageable:
            imageable.MakeInvisible()

    def _restore_visual_visibility(self):
        visual_prim = self.stage.GetPrimAtPath(self.visual_path)
        if not visual_prim or not visual_prim.IsValid():
            return

        for prim in Usd.PrimRange(visual_prim):
            if not prim.IsValid() or not prim.IsA(UsdGeom.Imageable):
                continue
            try:
                UsdGeom.Imageable(prim).MakeVisible()
            except Exception:
                pass

    def _vertical_aperture(self):
        aspect_x = max(self.viewport_aspect[0], 1.0)
        aspect_y = max(self.viewport_aspect[1], 1.0)
        return self.horizontal_aperture * (aspect_y / aspect_x)

    def _compute_asset_unit_scale(self, asset_path):
        try:
            asset_stage = Usd.Stage.Open(asset_path)
            if asset_stage is None:
                return 1.0
            asset_meters_per_unit = max(float(UsdGeom.GetStageMetersPerUnit(asset_stage)), 1e-9)
            stage_meters_per_unit = max(float(UsdGeom.GetStageMetersPerUnit(self.stage)), 1e-9)
            return asset_meters_per_unit / stage_meters_per_unit
        except Exception as exc:
            print(f"[DroneRig] Failed to inspect asset units for {asset_path}: {exc}")
            return 1.0

    def _make_visual_only(self, root_path):
        root = self.stage.GetPrimAtPath(root_path)
        if not root or not root.IsValid():
            print(f"[DroneRig] Visual root not found: {root_path}")
            return

        deactivate_keywords = (
            "joint",
            "collision",
            "collider",
            "articulation",
            "sensor",
            "physics",
        )
        false_attrs = (
            "physics:rigidBodyEnabled",
            "physics:collisionEnabled",
            "physxRigidBody:rigidBodyEnabled",
            "physxCollision:collisionEnabled",
        )
        true_attrs = ("physxRigidBody:disableGravity",)

        deactivated_count = 0
        for prim in Usd.PrimRange(root):
            if not prim.IsValid():
                continue

            type_name = prim.GetTypeName().lower()
            name = prim.GetName().lower()
            path = str(prim.GetPath()).lower()
            should_deactivate = any(keyword in type_name or keyword in name or keyword in path for keyword in deactivate_keywords)

            if should_deactivate and prim.GetPath() != root.GetPath():
                prim.SetActive(False)
                deactivated_count += 1
                continue

            for attr_name in false_attrs:
                attr = prim.GetAttribute(attr_name)
                if attr and attr.IsValid():
                    try:
                        attr.Set(False)
                    except Exception as exc:
                        print(f"[DroneRig] Failed to set {attr_name} on {prim.GetPath()}: {exc}")

            for attr_name in true_attrs:
                attr = prim.GetAttribute(attr_name)
                if attr and attr.IsValid():
                    try:
                        attr.Set(True)
                    except Exception as exc:
                        print(f"[DroneRig] Failed to set {attr_name} on {prim.GetPath()}: {exc}")

        print(f"[DroneRig] visual-only cleanup complete: deactivated={deactivated_count}")

    def set_position_xy(self, x, y):
        self._x = float(x)
        self._y = float(y)
        if self._translate_op is None:
            raise RuntimeError("DroneRig is not created yet.")

        stage_up_axis = UsdGeom.GetStageUpAxis(self.stage)
        altitude_units = self._meters_to_stage_units(self.fixed_altitude)
        if stage_up_axis == UsdGeom.Tokens.y:
            self._translate_op.Set(Gf.Vec3d(self._x, altitude_units, self._y))
        else:
            self._translate_op.Set(Gf.Vec3d(self._x, self._y, altitude_units))

    def set_altitude(self, altitude):
        self.fixed_altitude = float(altitude)
        self.set_position_xy(self._x, self._y)

    def set_yaw_deg(self, yaw_deg):
        self._yaw_deg = float(yaw_deg)
        if self._rotate_op is None:
            raise RuntimeError("DroneRig is not created yet.")

        stage_up_axis = UsdGeom.GetStageUpAxis(self.stage)
        if stage_up_axis == UsdGeom.Tokens.y:
            self._rotate_op.Set(Gf.Vec3f(0.0, self._yaw_deg, 0.0))
        else:
            self._rotate_op.Set(Gf.Vec3f(0.0, 0.0, self._yaw_deg))

    def set_visual_scale(self, scale):
        self.visual_scale = float(scale)
        if self._visual_scale_op is None:
            raise RuntimeError("DroneRig is not created yet.")
        applied_scale = self.visual_scale * self._asset_unit_scale
        self._visual_scale_op.Set(Gf.Vec3f(applied_scale, applied_scale, applied_scale))

    def get_camera_path(self):
        return str(self.camera_path)

    def get_visual_path(self):
        return str(self.visual_path)

    def get_translate_op(self):
        return self._translate_op

    def get_resolved_asset_path(self):
        return self._resolved_asset_path

    def get_position_xy_altitude(self):
        if self._translate_op is None:
            raise RuntimeError("DroneRig is not created yet.")

        value = self._translate_op.Get()
        if value is None:
            return self._x, self._y, self.fixed_altitude

        stage_up_axis = UsdGeom.GetStageUpAxis(self.stage)
        meters_per_unit = max(float(UsdGeom.GetStageMetersPerUnit(self.stage)), 1e-9)
        if stage_up_axis == UsdGeom.Tokens.y:
            return float(value[0]), float(value[2]), float(value[1]) * meters_per_unit
        return float(value[0]), float(value[1]), float(value[2]) * meters_per_unit

    def _meters_to_stage_units(self, meters):
        meters_per_unit = max(float(UsdGeom.GetStageMetersPerUnit(self.stage)), 1e-9)
        return float(meters) / meters_per_unit

    def is_camera_invisible(self):
        camera_prim = self.stage.GetPrimAtPath(self.camera_path)
        if not camera_prim or not camera_prim.IsValid():
            return False
        visibility = UsdGeom.Imageable(camera_prim).GetVisibilityAttr().Get()
        return visibility == UsdGeom.Tokens.invisible

    def look_through_camera(self):
        last_error = None
        try:
            from omni.kit.viewport.utility import get_active_viewport

            viewport = get_active_viewport()
            if viewport is not None:
                viewport.camera_path = self.get_camera_path()
                print(f"[DroneRig] Viewport camera set to: {self.camera_path}")
                return True
        except Exception as exc:
            last_error = exc

        try:
            from omni.kit.viewport.utility import get_active_viewport_window

            viewport_window = get_active_viewport_window()
            if viewport_window is not None and hasattr(viewport_window, "viewport_api"):
                viewport_window.viewport_api.camera_path = self.get_camera_path()
                print(f"[DroneRig] Viewport camera set to: {self.camera_path}")
                return True
        except Exception as exc:
            last_error = exc

        try:
            import omni.kit.viewport_legacy as viewport_legacy

            viewport_interface = viewport_legacy.get_viewport_interface()
            viewport_window = viewport_interface.get_viewport_window()
            viewport_window.set_active_camera(self.get_camera_path())
            print(f"[DroneRig] Viewport camera set to: {self.camera_path}")
            return True
        except Exception as exc:
            last_error = exc

        print(f"[DroneRig] Failed to set active viewport camera: {last_error}")
        return False

    def describe(self):
        return {
            "rig_path": str(self.rig_path),
            "visual_path": str(self.visual_path),
            "camera_path": str(self.camera_path),
            "crazyflie_asset_path": self._resolved_asset_path,
            "fixed_altitude": self.fixed_altitude,
            "visual_scale": self.visual_scale,
            "asset_unit_scale": self._asset_unit_scale,
            "x": self._x,
            "y": self._y,
            "yaw_deg": self._yaw_deg,
            "camera_invisible": self.is_camera_invisible(),
        }


class DroneTargetFollower:
    def __init__(self, drone_rig, smoothing=0.2):
        self.drone_rig = drone_rig
        self.smoothing = float(smoothing)
        self.current_x = 0.0
        self.current_y = 0.0

    def update_target(self, target_x, target_y):
        target_x = float(target_x)
        target_y = float(target_y)
        self.current_x = (1.0 - self.smoothing) * self.current_x + self.smoothing * target_x
        self.current_y = (1.0 - self.smoothing) * self.current_y + self.smoothing * target_y
        self.drone_rig.set_position_xy(self.current_x, self.current_y)
        return self.current_x, self.current_y


def cctv_coord_to_world_xy(cctv_x, cctv_y):
    """
    Placeholder world-coordinate converter for future CCTV estimator integration.

    The current follow-camera pipeline already works in stage/world XY coordinates,
    so this returns the input unchanged until a dedicated conversion layer is added.
    """
    return float(cctv_x), float(cctv_y)
