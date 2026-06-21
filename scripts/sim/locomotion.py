import math
import random
import re

from pxr import Gf, Usd, UsdGeom

from .animation import LiveSkelAnimPlayer
from .config import (
    ARRIVE_DIST,
    CHAR_BASE_ROT_X,
    CHAR_BASE_ROT_Y,
    CHAR_SCALE,
    FPS,
    GUN_ESCAPE_REMOVE_SEC,
    GUN_ESCAPE_SPEED_MULTIPLIER,
    GUNSHOT_FIRE_FRAME,
    GUNSHOT_FRAME_INTERVAL,
    KEEP_CURRENT_CHARACTER_Z,
    ROUTE_ROOT_PATH,
    ROUTES_ROOT_PATH,
    ROUTE_WAYPOINT_PREFIX,
    STREET_WALK_CCTV_RADIUS_M,
    STREET_WALK_ESCAPE_TARGET_ATTEMPTS,
    STREET_WALK_MARGIN_M,
    STREET_WALK_MIN_RECT_SIZE_M,
    STREET_WALK_ROOT_PATH,
    STREET_WALK_SEGMENT_SAMPLE_STEP_M,
    STREET_WALK_TARGET_ATTEMPTS,
    STREET_WALK_TARGET_MAX_DISTANCE_M,
    STREET_WALK_TARGET_MIN_DISTANCE_M,
    WALK_SPEED,
    YAW_OFFSET_DEG,
)
from .usd_utils import get_or_create_transform_ops


def _waypoint_sort_key(prim):
    name = prim.GetName()
    match = re.search(r"(\d+)$", name)
    if match:
        return int(match.group(1))
    return name


def get_prim_world_position(stage, prim, bbox_cache):
    box = bbox_cache.ComputeWorldBound(prim).ComputeAlignedBox()
    try:
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


def get_route_waypoints(stage, route_root_path=ROUTE_ROOT_PATH):
    route_root = stage.GetPrimAtPath(route_root_path)
    if not route_root.IsValid():
        raise RuntimeError(f"Route root not found: {route_root_path}")

    waypoint_prims = [
        prim
        for prim in route_root.GetChildren()
        if prim.GetName().startswith(ROUTE_WAYPOINT_PREFIX)
    ]
    waypoint_prims.sort(key=_waypoint_sort_key)

    if len(waypoint_prims) < 2:
        raise RuntimeError(f"Need at least 2 waypoints under {route_root_path}")

    bbox_cache = UsdGeom.BBoxCache(
        Usd.TimeCode.Default(),
        [UsdGeom.Tokens.default_],
        useExtentsHint=True,
    )
    return [get_prim_world_position(stage, prim, bbox_cache) for prim in waypoint_prims]


def get_available_route_paths(stage, routes_root_path=ROUTES_ROOT_PATH):
    routes_root = stage.GetPrimAtPath(routes_root_path)
    if not routes_root.IsValid():
        return [ROUTE_ROOT_PATH] if stage.GetPrimAtPath(ROUTE_ROOT_PATH).IsValid() else []

    route_paths = []
    for route_prim in routes_root.GetChildren():
        waypoint_count = len(
            [
                child
                for child in route_prim.GetChildren()
                if child.GetName().startswith(ROUTE_WAYPOINT_PREFIX)
            ]
        )
        if waypoint_count >= 2:
            route_paths.append(str(route_prim.GetPath()))

    route_paths.sort()
    return route_paths


class StreetWalkArea:
    def __init__(self, rects, label="street", root_path=STREET_WALK_ROOT_PATH):
        self.rects = rects
        self.label = label
        self.root_path = root_path

    @property
    def is_valid(self):
        return bool(self.rects)

    def sample_start(self, fallback_position=None):
        if fallback_position is not None and self.contains_xy(fallback_position[0], fallback_position[1]):
            return tuple(float(value) for value in fallback_position)
        if fallback_position is not None:
            return self.sample_nearest_point(fallback_position)
        return self.sample_point()

    def sample_next_target(self, current_position, escape=False, previous_target=None, previous_heading=None):
        best_candidate = None
        best_score = -1e9
        attempts = max(
            1,
            int(STREET_WALK_ESCAPE_TARGET_ATTEMPTS if escape else STREET_WALK_TARGET_ATTEMPTS),
        )

        for _ in range(attempts):
            candidate = self.sample_point(current_z=current_position[2])
            distance = self._distance_xy(current_position, candidate)
            if not escape:
                if distance < STREET_WALK_TARGET_MIN_DISTANCE_M:
                    continue
                if distance > STREET_WALK_TARGET_MAX_DISTANCE_M:
                    continue

            if not escape and not self.segment_is_walkable(current_position, candidate):
                continue

            if escape:
                score = distance
            else:
                score = self._target_score(
                    current_position,
                    candidate,
                    distance,
                    previous_target=previous_target,
                    previous_heading=previous_heading,
                )
            if score > best_score:
                best_score = score
                best_candidate = candidate

        if best_candidate is not None:
            return best_candidate

        return self.sample_nearby_target(current_position)

    def sample_nearby_target(self, current_position):
        containing_rects = [
            rect
            for rect in self.rects
            if self._point_in_rect(current_position[0], current_position[1], rect, margin=0.0)
        ]
        rect = random.choice(containing_rects or self.rects)
        return self._sample_from_rect(rect, current_z=current_position[2])

    def sample_point(self, current_z=None):
        rect = random.choice(self.rects)
        return self._sample_from_rect(rect, current_z=current_z)

    def sample_nearest_point(self, position):
        rect = min(
            self.rects,
            key=lambda candidate: self._distance_xy(
                position,
                (
                    (candidate["min_x"] + candidate["max_x"]) * 0.5,
                    (candidate["min_y"] + candidate["max_y"]) * 0.5,
                    position[2],
                ),
            ),
        )
        min_x, min_y, max_x, max_y = self._rect_inner_bounds(rect)
        return (
            min(max(float(position[0]), min_x), max_x),
            min(max(float(position[1]), min_y), max_y),
            float(position[2]),
        )

    def limited_to_points(self, focus_points, radius=STREET_WALK_CCTV_RADIUS_M):
        radius = max(float(radius), STREET_WALK_MIN_RECT_SIZE_M)
        rects = []
        seen = set()

        for rect in self.rects:
            for point in focus_points:
                clipped = self._clip_rect_near_point(rect, point, radius)
                if clipped is None:
                    continue
                key = (
                    round(clipped["min_x"], 3),
                    round(clipped["min_y"], 3),
                    round(clipped["max_x"], 3),
                    round(clipped["max_y"], 3),
                )
                if key in seen:
                    continue
                seen.add(key)
                rects.append(clipped)

        return StreetWalkArea(rects, label=self.label, root_path=self.root_path) if rects else None

    def contains_xy(self, x, y):
        return any(self._point_in_rect(x, y, rect) for rect in self.rects)

    def segment_is_walkable(self, start, end):
        distance = self._distance_xy(start, end)
        if distance <= 1e-6:
            return True

        step = max(float(STREET_WALK_SEGMENT_SAMPLE_STEP_M), 1.0)
        sample_count = max(2, int(math.ceil(distance / step)) + 1)
        for index in range(sample_count + 1):
            t = index / sample_count
            x = start[0] + (end[0] - start[0]) * t
            y = start[1] + (end[1] - start[1]) * t
            if not self.contains_xy(x, y):
                return False
        return True

    def _sample_from_rect(self, rect, current_z=None):
        min_x, min_y, max_x, max_y = self._rect_inner_bounds(rect)
        if rect.get("polygon"):
            for _ in range(64):
                x = random.uniform(min_x, max_x)
                y = random.uniform(min_y, max_y)
                if self._point_in_rect(x, y, rect, margin=0.0):
                    z = float(current_z) if current_z is not None else float(rect["ground_z"])
                    return (x, y, z)

        z = float(current_z) if current_z is not None else float(rect["ground_z"])
        return (
            random.uniform(min_x, max_x),
            random.uniform(min_y, max_y),
            z,
        )

    def _point_in_rect(self, x, y, rect, margin=None):
        if margin is None:
            margin = self._rect_margin(rect)
        if rect.get("polygon"):
            return (
                rect["min_x"] <= x <= rect["max_x"]
                and rect["min_y"] <= y <= rect["max_y"]
                and _point_in_polygon(x, y, rect["polygon"])
            )
        return (
            rect["min_x"] + margin <= x <= rect["max_x"] - margin
            and rect["min_y"] + margin <= y <= rect["max_y"] - margin
        )

    def _rect_margin(self, rect):
        width = rect["max_x"] - rect["min_x"]
        height = rect["max_y"] - rect["min_y"]
        return max(0.0, min(float(STREET_WALK_MARGIN_M), width * 0.35, height * 0.35))

    def _rect_inner_bounds(self, rect):
        margin = self._rect_margin(rect)
        min_x = rect["min_x"] + margin
        max_x = rect["max_x"] - margin
        min_y = rect["min_y"] + margin
        max_y = rect["max_y"] - margin
        if min_x > max_x:
            min_x, max_x = rect["min_x"], rect["max_x"]
        if min_y > max_y:
            min_y, max_y = rect["min_y"], rect["max_y"]
        return min_x, min_y, max_x, max_y

    def _clip_rect_near_point(self, rect, point, radius):
        fx = float(point[0])
        fy = float(point[1])
        min_x = max(rect["min_x"], fx - radius)
        max_x = min(rect["max_x"], fx + radius)
        min_y = max(rect["min_y"], fy - radius)
        max_y = min(rect["max_y"], fy + radius)
        if max_x - min_x < STREET_WALK_MIN_RECT_SIZE_M:
            return None
        if max_y - min_y < STREET_WALK_MIN_RECT_SIZE_M:
            return None

        return {
            "min_x": min_x,
            "min_y": min_y,
            "max_x": max_x,
            "max_y": max_y,
            "ground_z": rect["ground_z"],
            "path": rect.get("path", ""),
        }

    def _distance_xy(self, a, b):
        dx = b[0] - a[0]
        dy = b[1] - a[1]
        return math.sqrt(dx * dx + dy * dy)

    def _target_score(self, current_position, candidate, distance, previous_target=None, previous_heading=None):
        distance_score = distance / max(float(STREET_WALK_TARGET_MAX_DISTANCE_M), 1.0)
        heading_score = 0.0
        if previous_heading is not None and distance > 1e-6:
            dx = (candidate[0] - current_position[0]) / distance
            dy = (candidate[1] - current_position[1]) / distance
            heading_score = max(-1.0, min(1.0, dx * previous_heading[0] + dy * previous_heading[1]))

        return_penalty = 0.0
        if previous_target is not None:
            previous_distance = self._distance_xy(candidate, previous_target)
            if previous_distance < STREET_WALK_TARGET_MIN_DISTANCE_M:
                return_penalty = 1.0

        return distance_score * 0.65 + heading_score * 0.30 + random.random() * 0.10 - return_penalty


def build_street_walk_area(stage, root_path=STREET_WALK_ROOT_PATH):
    root = stage.GetPrimAtPath(root_path)
    if not root.IsValid():
        return None

    bbox_cache = UsdGeom.BBoxCache(
        Usd.TimeCode.Default(),
        [UsdGeom.Tokens.default_, UsdGeom.Tokens.render, UsdGeom.Tokens.proxy],
        useExtentsHint=True,
    )

    prims = [prim for prim in Usd.PrimRange(root) if prim != root]
    leaf_prims = [prim for prim in prims if not list(prim.GetChildren())]
    rects = _collect_walk_rects(bbox_cache, leaf_prims)
    source = "leaf"

    if not rects:
        rects = _collect_walk_rects(bbox_cache, prims)
        source = "descendant"

    if not rects:
        rect = _walk_rect_from_prim(bbox_cache, root)
        rects = [rect] if rect is not None else []
        source = "root"

    print(f"[StreetWalkArea] root={root_path} source={source} walkable_rects={len(rects)}")
    return StreetWalkArea(rects, label="street", root_path=root_path) if rects else None


def build_route_rectangle_walk_area(stage, route_root_path=ROUTE_ROOT_PATH):
    try:
        waypoints = get_route_waypoints(stage, route_root_path)
    except Exception as exc:
        print(f"[RouteRectWalkArea] unavailable: {route_root_path}; {exc}")
        return None

    if len(waypoints) < 4:
        print(f"[RouteRectWalkArea] need 4 waypoints under {route_root_path}; found {len(waypoints)}")
        return None

    polygon = _ordered_polygon([(point[0], point[1]) for point in waypoints[:4]])
    min_x = min(point[0] for point in polygon)
    max_x = max(point[0] for point in polygon)
    min_y = min(point[1] for point in polygon)
    max_y = max(point[1] for point in polygon)
    if max_x - min_x < STREET_WALK_MIN_RECT_SIZE_M or max_y - min_y < STREET_WALK_MIN_RECT_SIZE_M:
        print(f"[RouteRectWalkArea] rectangle too small: {route_root_path}")
        return None

    ground_z = sum(float(point[2]) for point in waypoints[:4]) / 4.0
    area = StreetWalkArea(
        [
            {
                "min_x": float(min_x),
                "min_y": float(min_y),
                "max_x": float(max_x),
                "max_y": float(max_y),
                "ground_z": float(ground_z),
                "path": route_root_path,
                "polygon": polygon,
            }
        ],
        label="route rectangle",
        root_path=route_root_path,
    )
    print(
        f"[RouteRectWalkArea] route={route_root_path} "
        f"bounds=({min_x:.1f}, {min_y:.1f})-({max_x:.1f}, {max_y:.1f})"
    )
    return area


def _ordered_polygon(points):
    center_x = sum(point[0] for point in points) / len(points)
    center_y = sum(point[1] for point in points) / len(points)
    return sorted(points, key=lambda point: math.atan2(point[1] - center_y, point[0] - center_x))


def _point_in_polygon(x, y, polygon):
    inside = False
    count = len(polygon)
    j = count - 1
    for i in range(count):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        intersects = (yi > y) != (yj > y)
        if intersects:
            denom = yj - yi
            if abs(denom) < 1e-9:
                j = i
                continue
            x_intersection = (xj - xi) * (y - yi) / denom + xi
            if x < x_intersection:
                inside = not inside
        j = i
    return inside


def _collect_walk_rects(bbox_cache, prims):
    rects = []
    seen = set()
    for prim in prims:
        rect = _walk_rect_from_prim(bbox_cache, prim)
        if rect is None:
            continue
        key = (
            round(rect["min_x"], 3),
            round(rect["min_y"], 3),
            round(rect["max_x"], 3),
            round(rect["max_y"], 3),
        )
        if key in seen:
            continue
        seen.add(key)
        rects.append(rect)
    return rects


def _walk_rect_from_prim(bbox_cache, prim):
    try:
        box = bbox_cache.ComputeWorldBound(prim).ComputeAlignedBox()
    except Exception:
        return None

    try:
        if box.IsEmpty():
            return None
    except Exception:
        pass

    bbox_min = box.GetMin()
    bbox_max = box.GetMax()
    min_x = float(bbox_min[0])
    max_x = float(bbox_max[0])
    min_y = float(bbox_min[1])
    max_y = float(bbox_max[1])
    width = max_x - min_x
    height = max_y - min_y
    if width < STREET_WALK_MIN_RECT_SIZE_M or height < STREET_WALK_MIN_RECT_SIZE_M:
        return None

    return {
        "min_x": min_x,
        "min_y": min_y,
        "max_x": max_x,
        "max_y": max_y,
        "ground_z": float(bbox_max[2]),
        "path": str(prim.GetPath()),
    }


def get_world_position(prim):
    matrix = UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
    pos = matrix.ExtractTranslation()
    return [float(pos[0]), float(pos[1]), float(pos[2])]


class RouteWalkController:
    def __init__(
        self,
        stage,
        character_path,
        asset_root_path,
        route_root_path=ROUTE_ROOT_PATH,
        walk_area=None,
        escape_walk_area=None,
        gunshot_sound_player=None,
        scream_sound_player=None,
    ):
        self.stage = stage
        self.character_path = character_path
        self.asset_root_path = asset_root_path
        self.route_root_path = route_root_path
        self.walk_area = walk_area
        self.escape_walk_area = escape_walk_area or walk_area

        self.translate_op = None
        self.rotate_op = None
        self.scale_op = None
        self.position = [0.0, 0.0, 0.0]
        self.waypoints = []
        self.current_index = 0
        self.next_index = 1
        self.walk_mode = "route"
        self.target_position = None
        self.previous_target_position = None
        self.current_heading = None
        self.anim_player = LiveSkelAnimPlayer(stage, asset_root_path)
        self.current_action = None
        self.current_action_elapsed_frames = 0.0
        self.gunshot_sound_player = gunshot_sound_player
        self.scream_sound_player = scream_sound_player
        self._gunshot_frames = []
        self._next_gunshot_index = 0
        self.escape_active = False
        self.escape_elapsed = 0.0
        self.speed_multiplier = 1.0
        self.remove_requested = False

    def start(self):
        character_prim = self.stage.GetPrimAtPath(self.character_path)
        if not character_prim.IsValid():
            raise RuntimeError(f"Character not found: {self.character_path}")

        self.translate_op, self.rotate_op, self.scale_op = get_or_create_transform_ops(
            UsdGeom.Xformable(character_prim)
        )
        self.anim_player.setup()

        current_pos = get_world_position(character_prim)
        if self.walk_area is not None and self.walk_area.is_valid:
            self._start_street_walk(current_pos)
        else:
            self._start_route_walk(current_pos)

    def _start_street_walk(self, current_pos):
        start_pos = self.walk_area.sample_start(current_pos)
        root_z = current_pos[2] if KEEP_CURRENT_CHARACTER_Z else start_pos[2]

        self.walk_mode = "street"
        self.position = [start_pos[0], start_pos[1], root_z]
        self._choose_next_street_target(self.walk_area)

        yaw = self.compute_yaw(self.position, self.target_position)
        self.apply_transform(yaw)

        print(f"[RouteWalkController] started: {self.character_path}")
        print(f"[RouteWalkController] mode: {self.walk_area.label} roaming")
        print(f"[RouteWalkController] walkable root: {self.walk_area.root_path}")

    def _start_route_walk(self, current_pos):
        self.walk_mode = "route"
        self.waypoints = get_route_waypoints(self.stage, self.route_root_path)

        start_wp = self.waypoints[0]
        root_z = current_pos[2] if KEEP_CURRENT_CHARACTER_Z else start_wp[2]

        self.position = [start_wp[0], start_wp[1], root_z]
        self.current_index = 0
        self.next_index = 1

        yaw = self.compute_yaw(self.position, self.waypoints[self.next_index])
        self.apply_transform(yaw)

        print(f"[RouteWalkController] started: {self.character_path}")
        print(f"[RouteWalkController] route: {self.route_root_path}")
        print(f"[RouteWalkController] waypoints: {len(self.waypoints)}")

    def stop(self):
        self._stop_action_audio(self.current_action)
        self.current_action = None
        self.current_action_elapsed_frames = 0.0
        self._gunshot_frames = []
        self._next_gunshot_index = 0
        self.escape_active = False
        self.escape_elapsed = 0.0

    @property
    def is_yelling(self):
        return self.current_action == "yell"

    @property
    def is_busy(self):
        return self.current_action is not None

    @property
    def is_escaping(self):
        return self.escape_active

    @property
    def should_remove(self):
        return self.remove_requested

    def start_one_shot_action(self, action_name, source_anim_path, repeat_count=1):
        if self.is_busy or self.escape_active:
            return False

        repeat_count = max(1, int(repeat_count))
        self.anim_player.play_once(source_anim_path, repeat_count=repeat_count)
        self.current_action = action_name
        self.current_action_elapsed_frames = 0.0
        self._setup_action_audio(action_name, repeat_count)
        print(f"[RouteWalkController] {action_name} started: {self.character_path}")
        return True

    def _setup_action_audio(self, action_name, repeat_count):
        self._gunshot_frames = []
        self._next_gunshot_index = 0

        if action_name == "yell":
            if self.scream_sound_player is not None:
                self.scream_sound_player.stop()
                self.scream_sound_player.play()
            return

        if action_name != "gun":
            return

        self._gunshot_frames = [
            GUNSHOT_FIRE_FRAME + GUNSHOT_FRAME_INTERVAL * index
            for index in range(repeat_count)
        ]
        if self.gunshot_sound_player is not None:
            self.gunshot_sound_player.load()

    def _stop_action_audio(self, action_name):
        if action_name == "yell" and self.scream_sound_player is not None:
            self.scream_sound_player.stop()

    def _trigger_scheduled_gunshots(self, previous_frame, current_frame):
        if self.gunshot_sound_player is None:
            return

        while self._next_gunshot_index < len(self._gunshot_frames):
            fire_frame = self._gunshot_frames[self._next_gunshot_index]
            if not previous_frame < fire_frame <= current_frame:
                break
            if self.gunshot_sound_player.play():
                fire_time = fire_frame / FPS
                print(
                    f"[RouteWalkController] gunshot sound "
                    f"{self._next_gunshot_index + 1}/{len(self._gunshot_frames)} "
                    f"at frame {fire_frame:.1f} ({fire_time:.3f}s)"
                )
            self._next_gunshot_index += 1

    def start_yell(self, source_anim_path):
        return self.start_one_shot_action("yell", source_anim_path)

    def get_position(self):
        return (float(self.position[0]), float(self.position[1]), float(self.position[2]))

    def compute_yaw(self, current, target):
        dx = target[0] - current[0]
        dy = target[1] - current[1]
        return math.degrees(math.atan2(dy, dx))

    def apply_transform(self, yaw_deg):
        self.translate_op.Set(Gf.Vec3d(self.position[0], self.position[1], self.position[2]))
        self.rotate_op.Set(Gf.Vec3f(CHAR_BASE_ROT_X, CHAR_BASE_ROT_Y, yaw_deg + YAW_OFFSET_DEG))
        self.scale_op.Set(Gf.Vec3f(CHAR_SCALE, CHAR_SCALE, CHAR_SCALE))

    def update(self, dt):
        if self.is_busy:
            action_name = self.current_action
            previous_frame = self.current_action_elapsed_frames
            finished = self.anim_player.update(dt)
            self.current_action_elapsed_frames += dt * FPS
            self._trigger_scheduled_gunshots(previous_frame, self.current_action_elapsed_frames)
            if finished:
                self._stop_action_audio(action_name)
                self.current_action = None
                self.current_action_elapsed_frames = 0.0
                self._gunshot_frames = []
                self._next_gunshot_index = 0
                if action_name == "gun":
                    self._begin_escape()
                else:
                    self.anim_player.play_walk_loop()
                print(f"[RouteWalkController] {action_name} finished: {self.character_path}")
            return

        self.anim_player.update(dt)

        if self.escape_active:
            self.escape_elapsed += dt
            if self.escape_elapsed >= GUN_ESCAPE_REMOVE_SEC:
                self.remove_requested = True
                return

        if self.walk_mode == "street":
            self._update_street_walk(dt)
        else:
            self._update_route_walk(dt)

    def _begin_escape(self):
        self.escape_active = True
        self.escape_elapsed = 0.0
        self.speed_multiplier = float(GUN_ESCAPE_SPEED_MULTIPLIER)
        self.anim_player.play_walk_loop()
        self.target_position = None
        print(
            f"[RouteWalkController] escape started: {self.character_path} "
            f"speed={self.speed_multiplier:.1f}x remove_after={GUN_ESCAPE_REMOVE_SEC:.1f}s"
        )

    def _update_street_walk(self, dt):
        walk_area = self._active_walk_area()
        if walk_area is None or not walk_area.is_valid:
            return

        if self.target_position is None:
            self._choose_next_street_target(walk_area)

        dx = self.target_position[0] - self.position[0]
        dy = self.target_position[1] - self.position[1]
        dist = math.sqrt(dx * dx + dy * dy)

        if dist <= ARRIVE_DIST:
            self.position[0] = self.target_position[0]
            self.position[1] = self.target_position[1]
            if not KEEP_CURRENT_CHARACTER_Z:
                self.position[2] = self.target_position[2]

            self.previous_target_position = self.target_position
            self._choose_next_street_target(walk_area)
            dx = self.target_position[0] - self.position[0]
            dy = self.target_position[1] - self.position[1]
            dist = max(math.sqrt(dx * dx + dy * dy), 1e-6)

        self._move_toward(self.target_position, dx, dy, dist, dt)

    def _choose_next_street_target(self, walk_area):
        self.target_position = walk_area.sample_next_target(
            self.position,
            escape=self.escape_active,
            previous_target=self.previous_target_position,
            previous_heading=self.current_heading,
        )

    def _active_walk_area(self):
        if self.escape_active and self.escape_walk_area is not None:
            return self.escape_walk_area
        return self.walk_area

    def _update_route_walk(self, dt):
        if len(self.waypoints) < 2:
            return

        target = self.waypoints[self.next_index]
        dx = target[0] - self.position[0]
        dy = target[1] - self.position[1]
        dist = math.sqrt(dx * dx + dy * dy)

        if dist <= ARRIVE_DIST:
            self.position[0] = target[0]
            self.position[1] = target[1]

            if not KEEP_CURRENT_CHARACTER_Z:
                self.position[2] = target[2]

            self.current_index = self.next_index
            self.next_index = (self.next_index + 1) % len(self.waypoints)

            target = self.waypoints[self.next_index]
            dx = target[0] - self.position[0]
            dy = target[1] - self.position[1]
            dist = max(math.sqrt(dx * dx + dy * dy), 1e-6)

        self._move_toward(target, dx, dy, dist, dt)

    def _move_toward(self, target, dx, dy, dist, dt):
        if dist > 1e-6:
            self.current_heading = (dx / dist, dy / dist)

        step = WALK_SPEED * self.speed_multiplier * dt
        if step >= dist:
            self.position[0] = target[0]
            self.position[1] = target[1]
        else:
            self.position[0] += dx / dist * step
            self.position[1] += dy / dist * step

        if not KEEP_CURRENT_CHARACTER_Z:
            self.position[2] = target[2]

        yaw = self.compute_yaw(self.position, target)
        self.apply_transform(yaw)
