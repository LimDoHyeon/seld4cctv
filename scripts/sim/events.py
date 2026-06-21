import random

from pxr import Gf, Sdf, Usd, UsdGeom

from .audio import OneShotSoundPlayer
from .config import (
    CAR_CRASH_ASSET_PREFIX,
    CAR_CRASH_POINTS_ROOT_PATH,
    CAR_CRASH_VISIBLE_SEC,
    EVENT_ROOT_PATH,
    EXPLOSION_LIVE_ROOT_PATH,
    EXPLOSION_POSITION_OFFSET,
    EXPLOSION_SOURCE_ROOT_PATHS,
    EXPLOSION_USD_FPS,
    EXPLOSION_USD_ROTATE_XYZ,
    EXPLOSION_USD_SCALE,
    GROUND_Z,
    SOUND_SOURCE_MARKER_ROOT_PATH,
    SOUND_SOURCE_VISIBLE_SEC,
)
from .paths import CRASH_WAV, EXPLOSION_USD, EXPLOSION_WAV, as_usd_path
from .usd_utils import (
    ensure_xform,
    get_or_create_transform_ops,
    get_stage,
    next_free_path,
)


EVENT_COLORS = {
    "yell": (1.0, 0.86, 0.15),
    "crash": (1.0, 0.35, 0.15),
    "explosion": (1.0, 0.08, 0.02),
    "gun": (0.25, 0.55, 1.0),
}


class EventManager:
    def __init__(self):
        self.events = []
        self.visible_crash_path = None
        self.visible_crash_remaining = 0.0
        self.crash_sound_player = OneShotSoundPlayer(CRASH_WAV)
        self.explosion_sound_player = OneShotSoundPlayer(EXPLOSION_WAV)
        self.explosion_timing = None
        self.active_explosions = []
        self.active_sound_sources = []

    def setup(self):
        try:
            stage = get_stage()
        except RuntimeError:
            return

        ensure_xform(stage, EVENT_ROOT_PATH)
        ensure_xform(stage, EXPLOSION_LIVE_ROOT_PATH)
        ensure_xform(stage, SOUND_SOURCE_MARKER_ROOT_PATH)
        self.explosion_timing = self._load_explosion_usd_timing()
        print(
            f"[cctv_sim] explosion USD ready: {EXPLOSION_USD} "
            f"frames={self.explosion_timing['start']:.1f}-{self.explosion_timing['end']:.1f} "
            f"fps={self.explosion_timing['fps']:.1f} "
            f"samples={self.explosion_timing['sample_count']}"
        )

        self._cleanup_legacy_crash_artifacts(stage)
        self._cleanup_legacy_explosion_markers(stage)
        self._hide_car_crash_assets(stage)
        self._hide_explosion_source_prims(stage)
        self._clear_live_explosions(stage)
        self._clear_sound_sources(stage)

    def stop(self):
        try:
            stage = get_stage()
            self._hide_car_crash_assets(stage)
            self._hide_explosion_source_prims(stage)
            self._clear_live_explosions(stage)
            self._clear_sound_sources(stage)
        except Exception:
            pass
        self.crash_sound_player.stop()
        self.explosion_sound_player.stop()

    def update(self, dt):
        stage = get_stage()

        if self.visible_crash_remaining > 0.0:
            self.visible_crash_remaining -= dt
            if self.visible_crash_remaining <= 0.0:
                self._hide_visible_car_crash(stage)

        self.crash_sound_player.update()
        self.explosion_sound_player.update()
        self._update_active_explosions(stage, dt)
        self._update_sound_sources(stage, dt)

    def register_sound_source(self, event_type, position, duration_sec=SOUND_SOURCE_VISIBLE_SEC):
        stage = get_stage()
        ensure_xform(stage, SOUND_SOURCE_MARKER_ROOT_PATH)
        return self._create_sound_source_marker(stage, event_type, position, duration_sec)

    def trigger(self, event_type, position=None):
        if event_type not in EVENT_COLORS:
            raise ValueError(f"Unknown event type: {event_type}")

        stage = get_stage()
        ensure_xform(stage, EVENT_ROOT_PATH)

        if event_type == "crash":
            return self._trigger_car_crash(stage, position)
        if event_type == "explosion":
            return self._trigger_explosion(stage, position)

        if position is None:
            position = (
                random.uniform(-150.0, 150.0),
                random.uniform(-150.0, 150.0),
                GROUND_Z + 12.0,
            )

        return self._create_event_marker(stage, event_type, position)

    def _trigger_car_crash(self, stage, position=None):
        crash_prim = self._choose_car_crash_asset(stage)
        self._hide_car_crash_assets(stage, except_path=str(crash_prim.GetPath()))
        UsdGeom.Imageable(crash_prim).MakeVisible()
        self.visible_crash_path = str(crash_prim.GetPath())
        self.visible_crash_remaining = CAR_CRASH_VISIBLE_SEC
        self.crash_sound_player.stop()
        self.crash_sound_player.play()

        position = self._prim_world_position(crash_prim)
        sound_source_path = self._create_sound_source_marker(
            stage,
            "crash",
            position,
            CAR_CRASH_VISIBLE_SEC,
        )
        event = {"type": "crash", "path": str(crash_prim.GetPath()), "position": position}
        event["sound_source_path"] = sound_source_path
        crash_prim.CreateAttribute("cctv_sim:event_type", Sdf.ValueTypeNames.String).Set("crash")
        crash_prim.CreateAttribute("cctv_sim:is_gt_event", Sdf.ValueTypeNames.Bool).Set(True)
        self.events.append(event)

        print(
            f"[cctv_sim] crash asset visible: {crash_prim.GetPath()} "
            f"position=({position[0]:.2f}, {position[1]:.2f}, {position[2]:.2f}) "
            f"duration={CAR_CRASH_VISIBLE_SEC:.1f}s"
        )
        return event

    def _trigger_explosion(self, stage, position=None):
        ensure_xform(stage, EXPLOSION_LIVE_ROOT_PATH)
        print("[cctv_sim] explosion trigger loads USD reference")

        if self.explosion_timing is None:
            self.explosion_timing = self._load_explosion_usd_timing()

        source_prim = None
        if position is None:
            source_prim = self._choose_explosion_source_prim(stage)
            if source_prim is not None:
                position = self._prim_bottom_center_position(source_prim)

        if position is None:
            position = (
                random.uniform(-150.0, 150.0),
                random.uniform(-150.0, 150.0),
                GROUND_Z,
            )

        position = self._apply_explosion_position_offset(position)

        self._clear_live_explosions(stage)
        self._sync_explosion_stage_timing(stage, self.explosion_timing)

        live_path = next_free_path(stage, EXPLOSION_LIVE_ROOT_PATH, "explosion")
        self._create_explosion_usd(stage, live_path, position)
        sound_source_path = self._create_sound_source_marker(
            stage,
            "explosion",
            position,
            max(SOUND_SOURCE_VISIBLE_SEC, 2.0),
        )
        self.explosion_sound_player.stop()
        self.explosion_sound_player.play()
        self._start_timeline_playback(self.explosion_timing)

        source_path = str(source_prim.GetPath()) if source_prim is not None else ""
        event = {
            "type": "explosion",
            "path": live_path,
            "source_path": source_path,
            "position": position,
            "sound_source_path": sound_source_path,
        }
        self.events.append(event)
        self.active_explosions = [
            {
                "path": live_path,
                "frame": self.explosion_timing["start"],
                "start": self.explosion_timing["start"],
                "end": self.explosion_timing["end"],
                "fps": self.explosion_timing["fps"],
            }
        ]

        print(
            f"[cctv_sim] explosion USD started: {live_path} "
            f"source={source_path or '<random>'} "
            f"position=({position[0]:.2f}, {position[1]:.2f}, {position[2]:.2f}) "
            f"frames={self.explosion_timing['start']:.1f}-{self.explosion_timing['end']:.1f} "
            f"samples={self.explosion_timing['sample_count']}"
        )
        return event

    def _apply_explosion_position_offset(self, position):
        return tuple(
            float(position[index]) + float(EXPLOSION_POSITION_OFFSET[index])
            for index in range(3)
        )

    def _create_event_marker(self, stage, event_type, position):
        if event_type == "explosion":
            raise RuntimeError("Explosion events must use USD animation playback, not sphere markers")

        prim_path = next_free_path(stage, EVENT_ROOT_PATH, event_type)
        sphere = UsdGeom.Sphere.Define(stage, prim_path)
        sphere.CreateRadiusAttr(12.0)
        sphere.CreateDisplayColorAttr([Gf.Vec3f(*EVENT_COLORS[event_type])])

        xform = UsdGeom.Xformable(sphere.GetPrim())
        xform.AddTranslateOp().Set(Gf.Vec3d(*position))

        prim = sphere.GetPrim()
        prim.CreateAttribute("cctv_sim:event_type", Sdf.ValueTypeNames.String).Set(event_type)
        prim.CreateAttribute("cctv_sim:is_gt_event", Sdf.ValueTypeNames.Bool).Set(True)

        event = {"type": event_type, "path": prim_path, "position": position}
        self.events.append(event)
        return event

    def _create_sound_source_marker(self, stage, event_type, position, duration_sec):
        duration_sec = max(float(duration_sec), 0.1)
        prim_path = next_free_path(stage, SOUND_SOURCE_MARKER_ROOT_PATH, event_type)
        sphere = UsdGeom.Sphere.Define(stage, prim_path)
        sphere.CreateRadiusAttr(8.0)
        sphere.CreateDisplayColorAttr([Gf.Vec3f(*EVENT_COLORS.get(event_type, EVENT_COLORS["yell"]))])

        xform = UsdGeom.Xformable(sphere.GetPrim())
        xform.AddTranslateOp().Set(Gf.Vec3d(*position))

        prim = sphere.GetPrim()
        prim.CreateAttribute("cctv_sim:sound_source_type", Sdf.ValueTypeNames.String).Set(event_type)
        prim.CreateAttribute("cctv_sim:is_sound_source", Sdf.ValueTypeNames.Bool).Set(True)
        UsdGeom.Imageable(prim).MakeVisible()
        self.active_sound_sources.append(
            {
                "path": prim_path,
                "remaining": duration_sec,
            }
        )
        print(
            f"[cctv_sim] sound source active: {prim_path} "
            f"position=({position[0]:.2f}, {position[1]:.2f}, {position[2]:.2f}) "
            f"duration={duration_sec:.1f}s"
        )
        return prim_path

    def _choose_car_crash_asset(self, stage):
        candidates = self._get_car_crash_assets(stage)
        if not candidates:
            raise RuntimeError(
                f"No crash assets found under {CAR_CRASH_POINTS_ROOT_PATH} "
                f"with prefix {CAR_CRASH_ASSET_PREFIX}"
            )

        prim = random.choice(candidates)
        print(f"[cctv_sim] crash asset selected: {prim.GetPath()}")
        return prim

    def _get_car_crash_assets(self, stage):
        root = stage.GetPrimAtPath(CAR_CRASH_POINTS_ROOT_PATH)
        if not root.IsValid():
            return []

        candidates = [
            prim
            for prim in root.GetChildren()
            if prim.GetName().startswith(CAR_CRASH_ASSET_PREFIX)
        ]
        candidates.sort(key=lambda prim: prim.GetName())
        return candidates

    def _hide_car_crash_assets(self, stage, except_path=None):
        for prim in self._get_car_crash_assets(stage):
            if except_path is not None and str(prim.GetPath()) == except_path:
                continue
            UsdGeom.Imageable(prim).MakeInvisible()
        if except_path is None:
            self.visible_crash_path = None
            self.visible_crash_remaining = 0.0

    def _get_explosion_source_prims(self, stage):
        candidates = []
        for root_path in EXPLOSION_SOURCE_ROOT_PATHS:
            root = stage.GetPrimAtPath(root_path)
            if not root.IsValid():
                continue

            children = list(root.GetChildren())
            named_children = [
                prim
                for prim in children
                if prim.GetName().lower().startswith("explosion")
            ]
            candidates.extend(named_children or children)

        candidates.sort(key=lambda prim: str(prim.GetPath()))
        return candidates

    def _choose_explosion_source_prim(self, stage):
        candidates = self._get_explosion_source_prims(stage)
        if not candidates:
            return None

        prim = self._get_selected_explosion_source(candidates) or random.choice(candidates)
        UsdGeom.Imageable(prim).MakeInvisible()
        prim.CreateAttribute("cctv_sim:event_type", Sdf.ValueTypeNames.String).Set("explosion")
        prim.CreateAttribute("cctv_sim:is_gt_event", Sdf.ValueTypeNames.Bool).Set(True)
        print(f"[cctv_sim] explosion source selected: {prim.GetPath()}")
        return prim

    def _get_selected_explosion_source(self, candidates):
        try:
            import omni.usd

            selected_paths = omni.usd.get_context().get_selection().get_selected_prim_paths()
        except Exception:
            return None

        for selected_path in selected_paths:
            for candidate in candidates:
                candidate_path = str(candidate.GetPath())
                if selected_path == candidate_path or selected_path.startswith(f"{candidate_path}/"):
                    return candidate
        return None

    def _load_explosion_usd_timing(self):
        if not EXPLOSION_USD.exists():
            raise FileNotFoundError(EXPLOSION_USD)

        layer = Sdf.Layer.FindOrOpen(as_usd_path(EXPLOSION_USD))
        if layer is None:
            raise RuntimeError(f"Unable to open explosion USD: {EXPLOSION_USD}")

        fps = self._safe_float(
            layer.timeCodesPerSecond or layer.framesPerSecond,
            EXPLOSION_USD_FPS,
        )
        start = self._safe_float(layer.startTimeCode, 0.0)
        end = self._safe_float(layer.endTimeCode, start)
        sample_count = 0

        if end <= start:
            scanned_range = self._scan_explosion_usd_time_range()
            if scanned_range is not None:
                start, end, sample_count = scanned_range
            else:
                start = 0.0
                end = fps
        else:
            scanned_range = self._scan_explosion_usd_time_range()
            if scanned_range is not None:
                _, _, sample_count = scanned_range

        return {"start": start, "end": end, "fps": fps, "sample_count": sample_count}

    def _safe_float(self, value, fallback):
        try:
            if value is None:
                return float(fallback)
            return float(value)
        except (TypeError, ValueError):
            return float(fallback)

    def _scan_explosion_usd_time_range(self):
        try:
            source_stage = Usd.Stage.Open(as_usd_path(EXPLOSION_USD))
        except Exception:
            return None
        if source_stage is None:
            return None

        samples = []
        for prim in source_stage.Traverse():
            for attr in prim.GetAttributes():
                samples.extend(attr.GetTimeSamples())
        if not samples:
            return None

        return float(min(samples)), float(max(samples)), len(samples)

    def _sync_explosion_stage_timing(self, stage, timing):
        if timing is None:
            return

        try:
            stage.SetTimeCodesPerSecond(timing["fps"])
            stage.SetStartTimeCode(min(float(stage.GetStartTimeCode()), timing["start"]))
            stage.SetEndTimeCode(max(float(stage.GetEndTimeCode()), timing["end"]))
        except Exception as exc:
            print(f"[cctv_sim] explosion stage timing update skipped: {exc}")

    def _create_explosion_usd(self, stage, live_path, position):
        root = UsdGeom.Xform.Define(stage, live_path).GetPrim()
        translate_op, rotate_op, scale_op = get_or_create_transform_ops(UsdGeom.Xformable(root))
        translate_op.Set(Gf.Vec3d(*position))
        rotate_op.Set(Gf.Vec3f(*EXPLOSION_USD_ROTATE_XYZ))
        scale_op.Set(Gf.Vec3f(EXPLOSION_USD_SCALE, EXPLOSION_USD_SCALE, EXPLOSION_USD_SCALE))

        asset_prim = stage.DefinePrim(f"{live_path}/Asset")
        asset_prim.GetReferences().ClearReferences()
        asset_prim.GetReferences().AddReference(as_usd_path(EXPLOSION_USD))

        root.CreateAttribute("cctv_sim:event_type", Sdf.ValueTypeNames.String).Set("explosion")
        root.CreateAttribute("cctv_sim:is_gt_event", Sdf.ValueTypeNames.Bool).Set(True)
        UsdGeom.Imageable(root).MakeVisible()
        print(f"[cctv_sim] explosion USD referenced: {EXPLOSION_USD} -> {live_path}/Asset")

    def _update_active_explosions(self, stage, dt):
        if not self.active_explosions:
            return

        finished = []
        for explosion in self.active_explosions:
            explosion["frame"] += dt * explosion["fps"]
            if explosion["frame"] >= explosion["end"]:
                finished.append(explosion)
                continue
            if not self._timeline_is_playing():
                self._set_timeline_frame(explosion["frame"], explosion["fps"])

        for explosion in finished:
            prim = stage.GetPrimAtPath(explosion["path"])
            if prim.IsValid():
                stage.RemovePrim(prim.GetPath())
                print(f"[cctv_sim] explosion USD finished: {explosion['path']}")
            self.active_explosions.remove(explosion)
        if finished:
            self.explosion_sound_player.stop()
            self._pause_timeline()

    def _start_timeline_playback(self, timing):
        self._enable_timeline_animation_playback()
        self._set_timeline_frame(timing["start"], timing["fps"])

        try:
            import omni.timeline

            timeline = omni.timeline.get_timeline_interface()
            start_seconds = float(timing["start"]) / max(float(timing["fps"]), 1e-6)
            end_seconds = float(timing["end"]) / max(float(timing["fps"]), 1e-6)

            timeline.pause()
            timeline.set_time_codes_per_second(float(timing["fps"]))
            timeline.set_start_time(start_seconds)
            timeline.set_end_time(end_seconds)
            timeline.set_looping(False)
            timeline.set_current_time(start_seconds)
            timeline.play()
            print(
                f"[cctv_sim] timeline playing: "
                f"{start_seconds:.3f}s-{end_seconds:.3f}s fps={timing['fps']:.1f}"
            )
        except Exception as exc:
            print(f"[cctv_sim] explosion timeline play skipped: {exc}")

    def _enable_timeline_animation_playback(self):
        try:
            import carb.settings

            settings = carb.settings.get_settings()
            settings.set_bool("/app/player/playAnimations", True)
        except Exception as exc:
            print(f"[cctv_sim] playAnimations setting skipped: {exc}")

    def _timeline_is_playing(self):
        try:
            import omni.timeline

            return bool(omni.timeline.get_timeline_interface().is_playing())
        except Exception:
            return False

    def _pause_timeline(self):
        try:
            import omni.timeline

            omni.timeline.get_timeline_interface().pause()
        except Exception as exc:
            print(f"[cctv_sim] explosion timeline pause skipped: {exc}")

    def _set_timeline_frame(self, frame, fps):
        try:
            import omni.timeline

            timeline = omni.timeline.get_timeline_interface()
            timeline.set_current_time(float(frame) / max(float(fps), 1e-6))
        except Exception as exc:
            print(f"[cctv_sim] explosion timeline update skipped: {exc}")

    def _clear_live_explosions(self, stage):
        root = stage.GetPrimAtPath(EXPLOSION_LIVE_ROOT_PATH)
        if root.IsValid():
            for child in list(root.GetChildren()):
                stage.RemovePrim(child.GetPath())
        self.active_explosions = []
        self.explosion_sound_player.stop()

    def _update_sound_sources(self, stage, dt):
        if not self.active_sound_sources:
            return

        expired = []
        for marker in self.active_sound_sources:
            marker["remaining"] -= dt
            if marker["remaining"] <= 0.0:
                expired.append(marker)

        for marker in expired:
            prim = stage.GetPrimAtPath(marker["path"])
            if prim.IsValid():
                stage.RemovePrim(prim.GetPath())
                print(f"[cctv_sim] sound source cleared: {marker['path']}")
            self.active_sound_sources.remove(marker)

    def _clear_sound_sources(self, stage):
        root = stage.GetPrimAtPath(SOUND_SOURCE_MARKER_ROOT_PATH)
        if root.IsValid():
            for child in list(root.GetChildren()):
                stage.RemovePrim(child.GetPath())
        self.active_sound_sources = []

    def _hide_explosion_source_prims(self, stage):
        for prim in self._get_explosion_source_prims(stage):
            UsdGeom.Imageable(prim).MakeInvisible()

    def _hide_visible_car_crash(self, stage):
        if not self.visible_crash_path:
            return

        prim = stage.GetPrimAtPath(self.visible_crash_path)
        if prim.IsValid():
            UsdGeom.Imageable(prim).MakeInvisible()
            print(f"[cctv_sim] crash asset hidden: {self.visible_crash_path}")

        self.visible_crash_path = None
        self.visible_crash_remaining = 0.0
        self.crash_sound_player.stop()

    def _cleanup_legacy_crash_artifacts(self, stage):
        for path in ("/World/Vehicles/CrashScene", "/World/Vehicles/CrashPairs"):
            prim = stage.GetPrimAtPath(path)
            if prim.IsValid():
                stage.RemovePrim(path)
                print(f"[cctv_sim] removed legacy crash artifact: {path}")

    def _cleanup_legacy_explosion_markers(self, stage):
        root = stage.GetPrimAtPath(EVENT_ROOT_PATH)
        if not root.IsValid():
            return

        keep_paths = {
            path
            for path in (*EXPLOSION_SOURCE_ROOT_PATHS, EXPLOSION_LIVE_ROOT_PATH)
            if path.startswith(f"{EVENT_ROOT_PATH}/")
        }
        for child in list(root.GetChildren()):
            path = str(child.GetPath())
            if path in keep_paths:
                continue
            event_type_attr = child.GetAttribute("cctv_sim:event_type")
            event_type = event_type_attr.Get() if event_type_attr.IsValid() else None
            if (
                path == "/World/Events/ExplosionVDB"
                or event_type == "explosion"
                or child.GetName().startswith("explosion")
            ):
                stage.RemovePrim(child.GetPath())
                print(f"[cctv_sim] removed legacy explosion marker: {path}")

    def _prim_bottom_center_position(self, prim):
        bbox_cache = UsdGeom.BBoxCache(
            Usd.TimeCode.Default(),
            [UsdGeom.Tokens.default_],
            useExtentsHint=True,
        )
        try:
            box = bbox_cache.ComputeWorldBound(prim).ComputeAlignedBox()
            if not box.IsEmpty():
                bbox_min = box.GetMin()
                bbox_max = box.GetMax()
                center = (bbox_min + bbox_max) * 0.5
                return (float(center[0]), float(center[1]), float(bbox_min[2]))
        except Exception:
            pass

        return self._prim_world_position(prim)

    def _prim_world_position(self, prim):
        bbox_cache = UsdGeom.BBoxCache(
            Usd.TimeCode.Default(),
            [UsdGeom.Tokens.default_],
            useExtentsHint=True,
        )
        try:
            box = bbox_cache.ComputeWorldBound(prim).ComputeAlignedBox()
            if not box.IsEmpty():
                bbox_min = box.GetMin()
                bbox_max = box.GetMax()
                center = (bbox_min + bbox_max) * 0.5
                return (float(center[0]), float(center[1]), float(center[2]))
        except Exception:
            pass

        matrix = UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
        pos = matrix.ExtractTranslation()
        return (float(pos[0]), float(pos[1]), float(pos[2]))
