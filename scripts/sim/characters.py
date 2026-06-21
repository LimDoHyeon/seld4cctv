import random
from pathlib import Path

from pxr import Gf, Usd, UsdGeom

from .config import (
    CHAR_BASE_ROT_X,
    CHAR_BASE_ROT_Y,
    CHAR_BASE_ROT_Z,
    CHAR_GROUND_CLEARANCE,
    CHAR_SCALE,
    CHARACTER_ROOT_PATH,
    CCTV_PLACEMENTS,
    CCTV_ROOT_PATH,
    GROUND_Z,
    GUN_REPEAT_COUNT,
    GUN_SOURCE_ROOT_PATH,
    ROUTE_RECT_WALK_ENABLED,
    STREET_WALK_CCTV_RADIUS_M,
    STREET_WALK_ENABLED,
    SOURCE_ROOT_PATH,
    YELL_SOURCE_ROOT_PATH,
)
from .animation import find_source_anim_path
from .audio import OneShotSoundPlayer
from .paths import GUNSHOT_WAV, SCREAM_WAV, SHOOTING_MAN_USD, WALKING_MAN_USD, YELLING_MAN_USD
from .locomotion import (
    RouteWalkController,
    build_route_rectangle_walk_area,
    build_street_walk_area,
    get_available_route_paths,
)
from .usd_utils import (
    as_stage_reference_path,
    ensure_xform,
    get_or_create_transform_ops,
    get_stage,
    next_free_path,
)


class CharacterManager:
    def __init__(self):
        self.characters = []
        self.last_added_route_path = None
        self.last_added_walk_mode = None
        self.last_action_character_path = None
        self.last_action_name = None
        self.walk_area = None
        self.escape_walk_area = None
        self.walk_area_kind = None
        self.gunshot_player = OneShotSoundPlayer(GUNSHOT_WAV)
        self.scream_player = OneShotSoundPlayer(SCREAM_WAV)

    def setup(self):
        try:
            stage = get_stage()
        except RuntimeError:
            return
        ensure_xform(stage, CHARACTER_ROOT_PATH)
        self._refresh_walk_areas(stage)

    def stop(self):
        for controller in self.characters:
            controller.stop()
        self.characters = []
        self.last_action_character_path = None
        self.last_action_name = None
        self.gunshot_player.stop()
        self.scream_player.stop()

    def update(self, dt):
        for controller in list(self.characters):
            controller.update(dt)
            if controller.should_remove:
                self._remove_controller(controller, reason="escape timeout")
        self.gunshot_player.update()
        self.scream_player.update()

    def yell_random(self):
        return self._play_action_random(
            "yell",
            YELLING_MAN_USD,
            YELL_SOURCE_ROOT_PATH,
            repeat_count=1,
        )

    def gun_random(self):
        return self._play_action_random(
            "gun",
            SHOOTING_MAN_USD,
            GUN_SOURCE_ROOT_PATH,
            repeat_count=GUN_REPEAT_COUNT,
        )

    def _play_action_random(self, action_name, asset_path, source_root_path, repeat_count=1):
        if not self.characters:
            return False, "No character available", None

        if any(controller.is_busy for controller in self.characters):
            return False, f"{action_name.capitalize()} ignored: action already in progress", None

        stage = get_stage()
        source_anim_path = self._ensure_action_source(stage, asset_path, source_root_path)
        candidates = [controller for controller in self.characters if not controller.is_escaping]
        if not candidates:
            return False, f"{action_name.capitalize()} ignored: no available character", None

        controller = random.choice(candidates)

        if not controller.start_one_shot_action(action_name, source_anim_path, repeat_count=repeat_count):
            return False, f"{action_name.capitalize()} ignored: action already in progress", None

        self.last_action_name = action_name
        self.last_action_character_path = controller.character_path
        return True, f"{action_name.capitalize()} started: {controller.character_path}", controller.get_position()

    def add_character(self, position=None, asset_path=None, route_root_path=None):
        stage = get_stage()
        ensure_xform(stage, CHARACTER_ROOT_PATH)

        asset_path = Path(asset_path) if asset_path is not None else WALKING_MAN_USD
        if not asset_path.exists():
            raise FileNotFoundError(asset_path)

        if route_root_path is None:
            if self.walk_area is None and (ROUTE_RECT_WALK_ENABLED or STREET_WALK_ENABLED):
                self._refresh_walk_areas(stage)
            if self.walk_area is None:
                route_paths = get_available_route_paths(stage)
                if not route_paths:
                    raise RuntimeError("No street walk area or valid route found")
                route_root_path = random.choice(route_paths)

        if position is None:
            if self.walk_area is not None:
                position = self._sample_character_spawn_position()
            else:
                offset = len(self.characters) * 80.0
                position = (offset, 0.0, GROUND_Z + CHAR_GROUND_CLEARANCE)

        prim_path = next_free_path(stage, CHARACTER_ROOT_PATH, "character")
        prim = UsdGeom.Xform.Define(stage, prim_path).GetPrim()

        translate_op, rotate_op, scale_op = get_or_create_transform_ops(UsdGeom.Xformable(prim))
        translate_op.Set(Gf.Vec3d(*position))
        rotate_op.Set(Gf.Vec3f(CHAR_BASE_ROT_X, CHAR_BASE_ROT_Y, CHAR_BASE_ROT_Z))
        scale_op.Set(Gf.Vec3f(CHAR_SCALE, CHAR_SCALE, CHAR_SCALE))

        asset_prim = UsdGeom.Xform.Define(stage, f"{prim_path}/Asset").GetPrim()
        asset_prim.GetReferences().AddReference(as_stage_reference_path(stage, asset_path))

        controller = RouteWalkController(
            stage,
            prim_path,
            f"{prim_path}/Asset",
            route_root_path=route_root_path,
            walk_area=self.walk_area,
            escape_walk_area=self.escape_walk_area,
            gunshot_sound_player=self.gunshot_player,
            scream_sound_player=self.scream_player,
        )
        try:
            controller.start()
        except Exception:
            stage.RemovePrim(prim_path)
            raise

        self.characters.append(controller)
        if self.walk_area is not None:
            self.last_added_walk_mode = self.walk_area_kind or "street"
            self.last_added_route_path = None
            print(f"[CharacterManager] added {prim_path} in {self.last_added_walk_mode} roaming mode")
        else:
            self.last_added_walk_mode = "route"
            self.last_added_route_path = route_root_path
            print(f"[CharacterManager] added {prim_path} on route {route_root_path}")
        return prim_path

    def add_character_on_route(self, route_index, position=None, asset_path=None):
        stage = get_stage()
        if ROUTE_RECT_WALK_ENABLED or STREET_WALK_ENABLED:
            if self.walk_area is None:
                self._refresh_walk_areas(stage)
            if self.walk_area is not None:
                return self.add_character(position=position, asset_path=asset_path)

        route_paths = get_available_route_paths(stage)
        if not route_paths:
            raise RuntimeError("No valid route found under /World/Routes")
        if route_index < 0 or route_index >= len(route_paths):
            raise RuntimeError(f"Route {route_index + 1} not found")
        return self.add_character(
            position=position,
            asset_path=asset_path,
            route_root_path=route_paths[route_index],
        )

    def remove_character(self):
        if not self.characters:
            return None

        controller = self.characters.pop()
        controller.stop()
        stage = get_stage()
        character_path = controller.character_path
        prim = stage.GetPrimAtPath(character_path)
        if prim.IsValid():
            stage.RemovePrim(character_path)
        print(f"[CharacterManager] removed {character_path}")
        return character_path

    def _remove_controller(self, controller, reason="removed"):
        if controller not in self.characters:
            return None

        self.characters.remove(controller)
        if self.last_action_character_path == controller.character_path:
            self.last_action_character_path = None
        controller.stop()
        stage = get_stage()
        character_path = controller.character_path
        prim = stage.GetPrimAtPath(character_path)
        if prim.IsValid():
            stage.RemovePrim(character_path)
        print(f"[CharacterManager] removed {character_path}: {reason}")
        return character_path

    def get_controller(self, character_path):
        for controller in self.characters:
            if controller.character_path == character_path:
                return controller
        return None

    def _refresh_walk_areas(self, stage):
        if ROUTE_RECT_WALK_ENABLED:
            route_area = build_route_rectangle_walk_area(stage)
            if route_area is not None:
                self.walk_area = route_area
                self.escape_walk_area = route_area
                self.walk_area_kind = "route_rect"
                print("[CharacterManager] route rectangle walking enabled")
                return

        if not STREET_WALK_ENABLED:
            self.walk_area = None
            self.escape_walk_area = None
            self.walk_area_kind = None
            return

        full_area = build_street_walk_area(stage)
        self.escape_walk_area = full_area
        if full_area is None:
            self.walk_area = None
            self.walk_area_kind = None
            return

        cctv_points = self._cctv_focus_points(stage)
        limited_area = full_area.limited_to_points(cctv_points, STREET_WALK_CCTV_RADIUS_M) if cctv_points else None
        self.walk_area = limited_area or full_area
        self.walk_area_kind = "street"
        if limited_area is not None:
            print(
                f"[CharacterManager] street walking limited near CCTV: "
                f"focus_points={len(cctv_points)} rects={len(limited_area.rects)} "
                f"radius={STREET_WALK_CCTV_RADIUS_M:.1f}"
            )
        else:
            print("[CharacterManager] CCTV-limited street area unavailable; using full street area")

    def _cctv_focus_points(self, stage):
        points = []

        cctv_root = stage.GetPrimAtPath(CCTV_ROOT_PATH)
        if cctv_root.IsValid():
            bbox_cache = UsdGeom.BBoxCache(
                Usd.TimeCode.Default(),
                [UsdGeom.Tokens.default_, UsdGeom.Tokens.render, UsdGeom.Tokens.proxy],
                useExtentsHint=True,
            )
            for prim in cctv_root.GetChildren():
                try:
                    box = bbox_cache.ComputeWorldBound(prim).ComputeAlignedBox()
                    if box.IsEmpty():
                        continue
                    center = (box.GetMin() + box.GetMax()) * 0.5
                    points.append((float(center[0]), float(center[1]), float(center[2])))
                except Exception:
                    pass

        if not points:
            for placement in CCTV_PLACEMENTS:
                position = placement.get("position")
                if position is not None:
                    points.append(tuple(float(value) for value in position))

        deduped = []
        seen = set()
        for point in points:
            key = (round(point[0], 1), round(point[1], 1))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(point)
        return deduped

    def _sample_character_spawn_position(self):
        point = self.walk_area.sample_point()
        return (
            float(point[0]),
            float(point[1]),
            float(point[2]) + CHAR_GROUND_CLEARANCE,
        )

    def _ensure_action_source(self, stage, asset_path, source_root_path):
        asset_path = Path(asset_path)
        if not asset_path.exists():
            raise FileNotFoundError(asset_path)

        ensure_xform(stage, SOURCE_ROOT_PATH)
        source_prim = UsdGeom.Xform.Define(stage, source_root_path).GetPrim()

        try:
            has_reference = source_prim.HasAuthoredReferences()
        except Exception:
            has_reference = bool(source_prim.GetMetadata("references"))

        if not has_reference:
            source_prim.GetReferences().AddReference(as_stage_reference_path(stage, asset_path))

        UsdGeom.Imageable(source_prim).MakeInvisible()
        return find_source_anim_path(stage, source_root_path)
