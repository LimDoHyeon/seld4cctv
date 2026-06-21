import math

from pxr import Gf, Sdf, Usd, UsdGeom

from .config import (
    CCTV_CAMERA_FORWARD_YAW_DEG,
    CCTV_AIM_DURATION_SEC,
    CCTV_APPLY_HOME_ON_SETUP,
    CCTV_EVENT_HOLD_SEC,
    CCTV_HOME_REFERENCE_FORWARD_AXIS,
    CCTV_HOME_REFERENCE_PRIM_SUFFIX,
    CCTV_PLACEMENTS,
    CCTV_RETURN_DURATION_SEC,
    CCTV_ROOT_PATH,
    CCTV_TELE_FOCAL_LENGTH,
    CCTV_VIEW_CAMERA_CLIPPING_RANGE,
    CCTV_VIEW_CAMERA_FOCAL_LENGTH,
    CCTV_VIEW_CAMERA_HORIZONTAL_APERTURE,
    CCTV_VIEW_CAMERA_ROTATE_XYZ,
    CCTV_VIEW_CAMERA_TRANSLATE,
    CCTV_WIDE_FOCAL_LENGTH,
    CCTV_ZOOM_FAR_DISTANCE_M,
    CCTV_ZOOM_NEAR_DISTANCE_M,
    SOUND_DETECTION_RADIUS_M,
)
from .paths import CCTV_USD, as_usd_path
from .usd_utils import (
    as_stage_reference_path,
    get_or_create_transform_ops,
    get_or_create_xform_op,
    get_stage,
)


PERSPECTIVE_CAMERA_PATH = "/OmniverseKit_Persp"


class CCTVManager:
    def __init__(self):
        self.cctv_paths = []
        self.aim_jobs = {}

    def setup(self):
        try:
            stage = get_stage()
        except RuntimeError:
            return

        if CCTV_USD.exists():
            layer = Sdf.Layer.FindOrOpen(as_usd_path(CCTV_USD))
            if layer is not None:
                layer.Reload(True)

        self.cctv_paths = self._ordered_existing_cctv_paths(stage)
        self.aim_jobs.clear()
        if not self.cctv_paths:
            print(f"[cctv_sim] No existing CCTV prims under {CCTV_ROOT_PATH}; setup skipped")
            return

        valid_count = 0
        invalid_count = 0
        for cctv_path in self.cctv_paths:
            if self._is_valid_cctv(stage, cctv_path):
                valid_count += 1
            else:
                invalid_count += 1
                print(f"[cctv_sim] keeping incomplete CCTV prim: {cctv_path}")

        self._initialize_home_orientations(stage)
        self._initialize_view_cameras(stage)
        print(
            f"[cctv_sim] CCTV ready: {len(self.cctv_paths)} existing "
            f"(valid={valid_count}, incomplete={invalid_count}, created=0, rebuilt=0)"
        )

    def stop(self):
        pass

    def get_camera_views(self):
        stage = get_stage()
        self.cctv_paths = self._discover_cctvs(stage)

        views = []
        for cctv_path in self.cctv_paths:
            live_camera_prim = self._find_view_camera_prim(stage, cctv_path)
            outer_camera_prim = self._find_outer_camera_prim(stage, cctv_path)
            live_camera_path = str(live_camera_prim.GetPath()) if live_camera_prim is not None else ""
            outer_camera_path = str(outer_camera_prim.GetPath()) if outer_camera_prim is not None else ""
            views.append(
                {
                    "name": cctv_path.rsplit("/", 1)[-1],
                    "root_path": cctv_path,
                    "camera_path": live_camera_path,
                    "live_camera_path": live_camera_path,
                    "outer_camera_path": outer_camera_path,
                    "valid": bool(live_camera_path or outer_camera_path),
                    "has_live_camera": bool(live_camera_path),
                    "has_outer_camera": bool(outer_camera_path),
                }
            )
        return views

    def switch_to_camera(self, camera_path):
        if not camera_path:
            return False, "Camera path is empty"

        stage = get_stage()
        camera_prim = stage.GetPrimAtPath(camera_path)
        if not camera_prim.IsValid():
            return False, f"Camera not found: {camera_path}"

        return self._switch_viewport_camera_path(camera_path)

    def switch_to_perspective(self):
        return self._switch_viewport_camera_path(PERSPECTIVE_CAMERA_PATH)

    def _switch_viewport_camera_path(self, camera_path):
        try:
            from omni.kit.viewport.utility import get_active_viewport

            viewport = get_active_viewport()
            if viewport is not None:
                viewport.camera_path = Sdf.Path(camera_path)
                return True, f"Viewport camera: {camera_path}"
        except Exception as exc:
            last_error = exc
        else:
            last_error = None

        try:
            from omni.kit.viewport.utility import get_active_viewport_window

            viewport_window = get_active_viewport_window()
            if viewport_window is not None and hasattr(viewport_window, "viewport_api"):
                viewport_window.viewport_api.camera_path = Sdf.Path(camera_path)
                return True, f"Viewport camera: {camera_path}"
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

    def update(self, dt):
        if not self.aim_jobs:
            return

        stage = get_stage()
        finished_paths = []
        for prim_path, job in list(self.aim_jobs.items()):
            prim = stage.GetPrimAtPath(prim_path)
            if not prim.IsValid():
                finished_paths.append(prim_path)
                continue

            phase = job.get("phase", "aim")
            if phase == "hold":
                job["elapsed"] += dt
                if job["elapsed"] >= job["duration"]:
                    self._start_return_phase(stage, prim, job)
                continue

            job["elapsed"] += dt
            t = min(job["elapsed"] / max(job["duration"], 1e-6), 1.0)
            t = t * t * (3.0 - 2.0 * t)
            self._apply_motion_job(stage, prim, job, t)

            if t >= 1.0:
                if phase == "return":
                    finished_paths.append(prim_path)
                else:
                    job["phase"] = "hold"
                    job["elapsed"] = 0.0
                    job["duration"] = CCTV_EVENT_HOLD_SEC
                    print(
                        f"[cctv_sim] hold aim {prim.GetPath()} "
                        f"for {CCTV_EVENT_HOLD_SEC:.1f}s before return"
                    )

        for prim_path in finished_paths:
            self.aim_jobs.pop(prim_path, None)

    def aim_at(self, target_position, radius=SOUND_DETECTION_RADIUS_M):
        return self.aim_at_with_report(target_position, radius)["aimed_count"]

    def aim_at_with_report(self, target_position, radius=SOUND_DETECTION_RADIUS_M):
        stage = get_stage()
        self.cctv_paths = self._discover_cctvs(stage)

        aimed_count = 0
        cctv_reports = []
        for cctv_path in self.cctv_paths:
            yaw_prim = self._find_yaw_prim(stage, cctv_path)
            name = cctv_path.rsplit("/", 1)[-1]
            if yaw_prim is None:
                cctv_reports.append(
                    {
                        "name": name,
                        "root_path": cctv_path,
                        "status": "not_connected",
                        "reason": "Yaw pivot not found",
                        "radius": float(radius),
                    }
                )
                continue

            origin = self._world_position(yaw_prim)
            dx, dy = self._horizontal_delta(stage, origin, target_position)
            distance = math.sqrt(dx * dx + dy * dy)
            report = {
                "name": name,
                "root_path": cctv_path,
                "yaw_path": str(yaw_prim.GetPath()),
                "position": origin,
                "view_yaw": self._view_world_yaw(yaw_prim),
                "distance": float(distance),
                "radius": float(radius),
            }
            if distance > radius:
                print(
                    f"[cctv_sim] distance {cctv_path}: {distance:.2f} "
                    f"(radius {radius:.2f}) -> OUT"
                )
                report["status"] = "out_of_range"
                cctv_reports.append(report)
                continue

            target_yaw = math.degrees(math.atan2(dy, dx))
            parent_yaw = self._parent_world_yaw(yaw_prim)
            local_yaw = self._normalize_degrees(
                target_yaw - parent_yaw - CCTV_CAMERA_FORWARD_YAW_DEG
            )
            camera_prim = self._find_view_camera_prim(stage, cctv_path)
            target_focal_length = self._target_focal_length(distance)

            print(
                f"[cctv_sim] distance {cctv_path}: {distance:.2f} "
                f"(radius {radius:.2f}) target_yaw={target_yaw:.2f} "
                f"local_yaw={local_yaw:.2f} "
                f"focalLength={target_focal_length:.2f} -> AIM"
            )
            self._queue_aim(stage, cctv_path, yaw_prim, local_yaw, camera_prim, target_focal_length)
            aimed_count += 1
            report.update(
                {
                    "status": "tracking",
                    "target_yaw": float(target_yaw),
                    "local_yaw": float(local_yaw),
                    "focal_length": float(target_focal_length),
                }
            )
            cctv_reports.append(report)

        print(
            f"[cctv_sim] CCTV aimed: {aimed_count} within radius {radius} "
            f"toward ({target_position[0]:.2f}, {target_position[1]:.2f}, {target_position[2]:.2f})"
        )
        return {
            "target_position": tuple(float(value) for value in target_position),
            "radius": float(radius),
            "aimed_count": aimed_count,
            "cctvs": cctv_reports,
        }

    def get_tracking_snapshot(self):
        stage = get_stage()
        self.cctv_paths = self._discover_cctvs(stage)

        rows = []
        for cctv_path in self.cctv_paths:
            name = cctv_path.rsplit("/", 1)[-1]
            yaw_prim = self._find_yaw_prim(stage, cctv_path)
            if yaw_prim is None:
                rows.append(
                    {
                        "name": name,
                        "root_path": cctv_path,
                        "status": "not_connected",
                        "reason": "Yaw pivot not found",
                    }
                )
                continue

            yaw_path = str(yaw_prim.GetPath())
            job = self.aim_jobs.get(yaw_path)
            phase = job.get("phase") if job else "idle"
            rows.append(
                {
                    "name": name,
                    "root_path": cctv_path,
                    "yaw_path": yaw_path,
                    "status": phase,
                    "position": self._world_position(yaw_prim),
                    "current_yaw": self._get_yaw(yaw_prim),
                    "view_yaw": self._view_world_yaw(yaw_prim),
                }
            )
        return rows

    def _create_cctv(self, stage, root_path, placement):
        root_prim = UsdGeom.Xform.Define(stage, root_path).GetPrim()
        self._apply_placement(root_prim, placement)

        rig_prim = UsdGeom.Xform.Define(stage, f"{root_path}/Rig").GetPrim()
        self._apply_rig_axis_correction(stage, rig_prim)
        reference_path = as_stage_reference_path(stage, CCTV_USD)
        rig_prim.GetReferences().ClearReferences()
        rig_prim.GetReferences().AddReference(reference_path)

        if not self._is_valid_cctv(stage, root_path):
            print(
                f"[cctv_sim] CCTV reference added but ViewCamera is missing: "
                f"{root_path} -> {reference_path}"
            )

    def _apply_placement(self, root_prim, placement):
        translate_op, rotate_op, scale_op = get_or_create_transform_ops(UsdGeom.Xformable(root_prim))
        stage = root_prim.GetStage()
        position = self._stage_position(stage, placement.get("position", (0.0, 0.0, 0.0)))
        yaw = float(placement.get("yaw", 0.0))

        translate_op.Set(Gf.Vec3d(*position))
        if self._is_y_up_stage(stage):
            rotate_op.Set(Gf.Vec3f(0.0, yaw, 0.0))
        else:
            rotate_op.Set(Gf.Vec3f(0.0, 0.0, yaw))
        scale = float(placement.get("scale", 1.0))
        scale_op.Set(Gf.Vec3f(scale, scale, scale))

    def _apply_rig_axis_correction(self, stage, rig_prim):
        translate_op, rotate_op, scale_op = get_or_create_transform_ops(UsdGeom.Xformable(rig_prim))
        translate_op.Set(Gf.Vec3d(0.0, 0.0, 0.0))
        if self._is_y_up_stage(stage):
            rotate_op.Set(Gf.Vec3f(-90.0, 0.0, 0.0))
        else:
            rotate_op.Set(Gf.Vec3f(0.0, 0.0, 0.0))
        scale_op.Set(Gf.Vec3f(1.0, 1.0, 1.0))

    def _stage_position(self, stage, position):
        x, y, z = position
        if self._is_y_up_stage(stage):
            return (float(x), float(z), float(y))
        return (float(x), float(y), float(z))

    def _is_y_up_stage(self, stage):
        try:
            return UsdGeom.GetStageUpAxis(stage) == UsdGeom.Tokens.y
        except Exception:
            return False

    def _is_valid_cctv(self, stage, root_path):
        rig_prim = stage.GetPrimAtPath(f"{root_path}/Rig")
        return rig_prim.IsValid() and self._find_view_camera_prim(stage, root_path) is not None

    def _discover_cctvs(self, stage):
        root = stage.GetPrimAtPath(CCTV_ROOT_PATH)
        if not root.IsValid():
            return []
        return [str(child.GetPath()) for child in root.GetChildren()]

    def _ordered_existing_cctv_paths(self, stage):
        discovered_paths = self._discover_cctvs(stage)
        discovered = set(discovered_paths)
        ordered_paths = []

        for index, placement in enumerate(CCTV_PLACEMENTS, 1):
            name = placement.get("name", f"cctv_{index:02d}")
            root_path = f"{CCTV_ROOT_PATH}/{name}"
            if root_path in discovered:
                ordered_paths.append(root_path)

        ordered = set(ordered_paths)
        ordered_paths.extend(path for path in discovered_paths if path not in ordered)
        return ordered_paths

    def _find_yaw_prim(self, stage, cctv_path):
        candidates = (
            f"{cctv_path}/Rig/Geom/YawPivot",
            f"{cctv_path}/Geom/YawPivot",
            f"{cctv_path}/Rig/YawPivot",
            f"{cctv_path}/YawPivot",
            cctv_path,
        )

        for path in candidates:
            prim = stage.GetPrimAtPath(path)
            if prim.IsValid():
                return prim
        return None

    def _find_view_camera_prim(self, stage, cctv_path):
        candidates = (
            f"{cctv_path}/Rig/Geom/YawPivot/Cameras/Cam_01/ViewCamera",
            f"{cctv_path}/Geom/YawPivot/Cameras/Cam_01/ViewCamera",
            f"{cctv_path}/Rig/YawPivot/Cameras/Cam_01/ViewCamera",
            f"{cctv_path}/YawPivot/Cameras/Cam_01/ViewCamera",
            f"{cctv_path}/Rig/Geom/Cameras/Cam_01/ViewCamera",
            f"{cctv_path}/Geom/Cameras/Cam_01/ViewCamera",
            f"{cctv_path}/Rig/ViewCamera",
            f"{cctv_path}/ViewCamera",
        )

        for path in candidates:
            prim = stage.GetPrimAtPath(path)
            if prim.IsValid():
                return prim

        root = stage.GetPrimAtPath(cctv_path)
        if not root.IsValid():
            return None

        for prim in Usd.PrimRange(root):
            if prim.GetTypeName() == "Camera" and prim.GetName() == "ViewCamera":
                return prim

        for prim in Usd.PrimRange(root):
            if prim.GetTypeName() == "Camera":
                return prim

        return None

    def _find_outer_camera_prim(self, stage, cctv_path):
        cctv_name = cctv_path.rsplit("/", 1)[-1]
        digits = "".join(ch for ch in cctv_name if ch.isdigit())
        outer_names = {f"{cctv_name}_outer".lower()}
        if digits:
            outer_names.add(f"cctv{digits}_outer".lower())
            try:
                outer_names.add(f"cctv{int(digits)}_outer".lower())
            except ValueError:
                pass

        direct_candidates = []
        for outer_name in sorted(outer_names):
            direct_candidates.extend(
                (
                    f"{cctv_path}/Rig/{outer_name}",
                    f"{cctv_path}/Rig/Geom/{outer_name}",
                    f"{cctv_path}/{outer_name}",
                )
            )

        for candidate_path in direct_candidates:
            prim = stage.GetPrimAtPath(candidate_path)
            if prim.IsValid() and prim.GetTypeName() == "Camera":
                return prim

        root = stage.GetPrimAtPath(cctv_path)
        if not root.IsValid():
            return None

        for prim in Usd.PrimRange(root):
            if prim.GetTypeName() == "Camera" and prim.GetName().lower() in outer_names:
                return prim

        for prim in Usd.PrimRange(root):
            if prim.GetTypeName() == "Camera" and "outer" in prim.GetName().lower():
                return prim

        return None

    def _initialize_view_cameras(self, stage):
        initialized_count = 0
        for cctv_path in self.cctv_paths:
            camera_prim = self._find_view_camera_prim(stage, cctv_path)
            if camera_prim is None:
                continue
            self._initialize_view_camera(camera_prim)
            initialized_count += 1

        print(f"[cctv_sim] ViewCamera aligned to Cam_01 body: {initialized_count}")

    def _initialize_view_camera(self, camera_prim):
        xformable = UsdGeom.Xformable(camera_prim)
        translate_op, rotate_op = self._get_view_camera_body_transform_ops(xformable)

        translate_op.Set(Gf.Vec3d(*CCTV_VIEW_CAMERA_TRANSLATE))
        rotate_op.Set(Gf.Vec3f(*CCTV_VIEW_CAMERA_ROTATE_XYZ))
        xformable.SetXformOpOrder([translate_op, rotate_op])

        camera = UsdGeom.Camera(camera_prim)
        camera.GetFocalLengthAttr().Set(float(CCTV_VIEW_CAMERA_FOCAL_LENGTH))
        camera.GetHorizontalApertureAttr().Set(float(CCTV_VIEW_CAMERA_HORIZONTAL_APERTURE))
        camera.GetClippingRangeAttr().Set(Gf.Vec2f(*CCTV_VIEW_CAMERA_CLIPPING_RANGE))

    def _get_view_camera_body_transform_ops(self, xformable):
        camera_prim = xformable.GetPrim()
        transform_attr = camera_prim.GetAttribute("xformOp:transform")
        if transform_attr.IsValid():
            transform_attr.Clear()

        translate_op = self._get_or_create_xform_op(
            xformable,
            "xformOp:translate",
            lambda: xformable.AddTranslateOp(),
        )
        rotate_op = self._get_or_create_xform_op(
            xformable,
            "xformOp:rotateXYZ",
            lambda: xformable.AddRotateXYZOp(),
        )
        return translate_op, rotate_op

    def _get_or_create_xform_op(self, xformable, attr_name, add_fn):
        return get_or_create_xform_op(xformable, attr_name, add_fn)

    def _queue_aim(self, stage, cctv_path, prim, target_yaw, camera_prim=None, target_focal_length=None):
        prim_path = str(prim.GetPath())
        existing_job = self.aim_jobs.get(prim_path)
        current_yaw = self._get_yaw(prim)
        home_yaw = (
            existing_job.get("home_yaw")
            if existing_job
            else self._home_yaw_for_cctv(stage, cctv_path, prim, current_yaw)
        )
        delta_yaw = self._normalize_degrees(target_yaw - current_yaw)
        job = {
            "phase": "aim",
            "home_yaw": home_yaw,
            "start_yaw": current_yaw,
            "delta_yaw": delta_yaw,
            "elapsed": 0.0,
            "duration": CCTV_AIM_DURATION_SEC,
        }

        if camera_prim is not None and camera_prim.IsValid() and target_focal_length is not None:
            current_focal_length = self._get_focal_length(camera_prim)
            job["camera_path"] = str(camera_prim.GetPath())
            if existing_job and "home_focal_length" in existing_job:
                job["home_focal_length"] = existing_job["home_focal_length"]
            else:
                job["home_focal_length"] = current_focal_length
            job["start_focal_length"] = current_focal_length
            job["delta_focal_length"] = target_focal_length - current_focal_length

        self.aim_jobs[prim_path] = job
        print(
            f"[cctv_sim] queue aim {prim.GetPath()}: "
            f"{current_yaw:.2f} -> {self._normalize_degrees(current_yaw + delta_yaw):.2f}; "
            f"home={home_yaw:.2f}; return home after {CCTV_EVENT_HOLD_SEC:.1f}s"
        )

    def _initialize_home_orientations(self, stage):
        if not CCTV_APPLY_HOME_ON_SETUP:
            return

        for cctv_path in self.cctv_paths:
            yaw_prim = self._find_yaw_prim(stage, cctv_path)
            if yaw_prim is None:
                continue

            current_yaw = self._get_yaw(yaw_prim)
            home_yaw = self._home_yaw_for_cctv(stage, cctv_path, yaw_prim, current_yaw)
            self._set_yaw(yaw_prim, home_yaw)
            print(
                f"[cctv_sim] home orientation {cctv_path}: "
                f"{current_yaw:.2f} -> {home_yaw:.2f}"
            )

    def _apply_motion_job(self, stage, prim, job, t):
        yaw = job["start_yaw"] + job["delta_yaw"] * t
        self._set_yaw(prim, yaw)

        camera_path = job.get("camera_path")
        if camera_path and "start_focal_length" in job:
            camera_prim = stage.GetPrimAtPath(camera_path)
            if camera_prim.IsValid():
                focal_length = job["start_focal_length"] + job["delta_focal_length"] * t
                self._set_focal_length(camera_prim, focal_length)

    def _start_return_phase(self, stage, prim, job):
        current_yaw = self._get_yaw(prim)
        job["phase"] = "return"
        job["start_yaw"] = current_yaw
        job["delta_yaw"] = self._normalize_degrees(job["home_yaw"] - current_yaw)
        job["elapsed"] = 0.0
        job["duration"] = CCTV_RETURN_DURATION_SEC

        camera_path = job.get("camera_path")
        if camera_path and "home_focal_length" in job:
            camera_prim = stage.GetPrimAtPath(camera_path)
            if camera_prim.IsValid():
                current_focal_length = self._get_focal_length(camera_prim)
                job["start_focal_length"] = current_focal_length
                job["delta_focal_length"] = job["home_focal_length"] - current_focal_length

        print(
            f"[cctv_sim] return aim {prim.GetPath()}: "
            f"{current_yaw:.2f} -> {job['home_yaw']:.2f}"
        )

    def _get_yaw(self, prim):
        xformable = UsdGeom.Xformable(prim)
        for op in xformable.GetOrderedXformOps():
            if op.GetOpName() == "xformOp:rotateXYZ":
                value = op.Get(Usd.TimeCode.Default()) or Gf.Vec3f(0.0, 0.0, 0.0)
                return float(value[2])
        return 0.0

    def _set_yaw(self, prim, yaw_deg):
        xformable = UsdGeom.Xformable(prim)
        rotate_op = get_or_create_xform_op(
            xformable,
            "xformOp:rotateXYZ",
            lambda: xformable.AddRotateXYZOp(),
        )
        current = rotate_op.Get(Usd.TimeCode.Default()) or Gf.Vec3f(0.0, 0.0, 0.0)
        rotate_op.Set(Gf.Vec3f(float(current[0]), float(current[1]), float(yaw_deg)))

    def _get_focal_length(self, camera_prim):
        camera = UsdGeom.Camera(camera_prim)
        value = camera.GetFocalLengthAttr().Get(Usd.TimeCode.Default())
        if value is None:
            return CCTV_WIDE_FOCAL_LENGTH
        return float(value)

    def _set_focal_length(self, camera_prim, focal_length):
        camera = UsdGeom.Camera(camera_prim)
        camera.GetFocalLengthAttr().Set(float(focal_length))

    def _home_yaw_for_cctv(self, stage, cctv_path, yaw_prim, fallback_yaw):
        reference_prim = self._find_home_reference_prim(stage, cctv_path)
        if reference_prim is None:
            return fallback_yaw

        reference_yaw = self._world_forward_yaw(reference_prim, CCTV_HOME_REFERENCE_FORWARD_AXIS)
        if reference_yaw is None:
            return fallback_yaw

        parent_yaw = self._parent_world_yaw(yaw_prim)
        return self._normalize_degrees(reference_yaw - parent_yaw - CCTV_CAMERA_FORWARD_YAW_DEG)

    def _find_home_reference_prim(self, stage, cctv_path):
        suffix = CCTV_HOME_REFERENCE_PRIM_SUFFIX.strip("/")
        candidates = [f"{cctv_path}/{suffix}"]
        if suffix.startswith("Rig/"):
            candidates.append(f"{cctv_path}/{suffix[4:]}")

        for path in candidates:
            prim = stage.GetPrimAtPath(path)
            if prim.IsValid():
                return prim

        return None

    def _world_forward_yaw(self, prim, local_axis):
        matrix = UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
        try:
            direction = matrix.TransformDir(Gf.Vec3d(*local_axis))
        except AttributeError:
            axis = Gf.Vec3d(*local_axis)
            direction = Gf.Vec3d(
                matrix[0][0] * axis[0] + matrix[1][0] * axis[1] + matrix[2][0] * axis[2],
                matrix[0][1] * axis[0] + matrix[1][1] * axis[1] + matrix[2][1] * axis[2],
                matrix[0][2] * axis[0] + matrix[1][2] * axis[1] + matrix[2][2] * axis[2],
            )

        dx = float(direction[0])
        if self._is_y_up_stage(prim.GetStage()):
            dy = float(direction[2])
        else:
            dy = float(direction[1])
        if abs(dx) < 1e-6 and abs(dy) < 1e-6:
            return None
        return math.degrees(math.atan2(dy, dx))

    def _target_focal_length(self, distance):
        near = min(CCTV_ZOOM_NEAR_DISTANCE_M, CCTV_ZOOM_FAR_DISTANCE_M)
        far = max(CCTV_ZOOM_NEAR_DISTANCE_M, CCTV_ZOOM_FAR_DISTANCE_M)
        if far <= near:
            return CCTV_WIDE_FOCAL_LENGTH

        t = (distance - near) / (far - near)
        t = max(0.0, min(t, 1.0))
        return CCTV_WIDE_FOCAL_LENGTH + (CCTV_TELE_FOCAL_LENGTH - CCTV_WIDE_FOCAL_LENGTH) * t

    def _world_position(self, prim):
        matrix = UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
        pos = matrix.ExtractTranslation()
        return (float(pos[0]), float(pos[1]), float(pos[2]))

    def _horizontal_delta(self, stage, origin, target_position):
        dx = float(target_position[0]) - origin[0]
        if self._is_y_up_stage(stage):
            dy = float(target_position[2]) - origin[2]
        else:
            dy = float(target_position[1]) - origin[1]
        return dx, dy

    def _parent_world_yaw(self, prim):
        parent = prim.GetParent()
        if not parent or not parent.IsValid():
            return 0.0

        try:
            matrix = UsdGeom.Xformable(parent).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
            try:
                x_axis = matrix.TransformDir(Gf.Vec3d(1.0, 0.0, 0.0))
            except AttributeError:
                x_axis = Gf.Vec3d(matrix[0][0], matrix[0][1], matrix[0][2])
            if self._is_y_up_stage(prim.GetStage()):
                return math.degrees(math.atan2(float(x_axis[2]), float(x_axis[0])))
            return math.degrees(math.atan2(float(x_axis[1]), float(x_axis[0])))
        except Exception:
            return 0.0

    def _view_world_yaw(self, yaw_prim):
        return self._normalize_degrees(
            self._parent_world_yaw(yaw_prim)
            + self._get_yaw(yaw_prim)
            + CCTV_CAMERA_FORWARD_YAW_DEG
        )

    def _normalize_degrees(self, value):
        return ((value + 180.0) % 360.0) - 180.0
