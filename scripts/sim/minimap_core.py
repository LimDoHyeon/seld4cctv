from dataclasses import dataclass
import math

from pxr import Gf, Usd, UsdGeom

from .config import (
    CHARACTER_ROOT_PATH,
    CCTV_ROOT_PATH,
    EGO_VEHICLE_PATHS,
    EVENT_ROOT_PATH,
    MINIMAP_BACKGROUND_FEATURE_LIMIT,
    MINIMAP_BACKGROUND_MAX_AREA_RATIO,
    MINIMAP_BACKGROUND_MIN_PIXEL_SIZE,
    MINIMAP_CCTV_EXTENT_MARGIN,
    MINIMAP_CCTV_MIN_SPAN,
    MINIMAP_EVENT_ROOT_PATH,
    MINIMAP_EXTENT_PADDING,
    MINIMAP_FALLBACK_EXTENT,
    MINIMAP_MAP_HEIGHT,
    MINIMAP_MAP_WIDTH,
    MINIMAP_MAX_MARKERS_PER_TYPE,
    MINIMAP_SCAN_INTERVAL_SEC,
    MINIMAP_UPDATE_INTERVAL_SEC,
    MICROPHONE_ROOT_PATH,
    PEDESTRIAN_ROOT_PATH,
    SOUND_SOURCE_MARKER_ROOT_PATH,
    VEHICLE_ROOT_PATH,
)
from .usd_utils import get_stage


TRACKED_KIND_ORDER = (
    "ego_vehicle",
    "vehicles",
    "pedestrians",
    "sound_sources",
    "listener_or_microphone",
    "events",
)

TRACKED_KIND_LABELS = {
    "ego_vehicle": "Ego vehicle",
    "vehicles": "Vehicles",
    "pedestrians": "Pedestrians",
    "sound_sources": "Sound sources",
    "listener_or_microphone": "Listeners",
    "events": "Events",
}

BACKGROUND_SEARCH_ROOTS = ("/World/Environment", "/World")
BACKGROUND_EXCLUDED_PREFIXES = (
    CCTV_ROOT_PATH,
    CHARACTER_ROOT_PATH,
    PEDESTRIAN_ROOT_PATH,
    SOUND_SOURCE_MARKER_ROOT_PATH,
    MICROPHONE_ROOT_PATH,
    VEHICLE_ROOT_PATH,
    EVENT_ROOT_PATH,
    MINIMAP_EVENT_ROOT_PATH,
    "/World/Sources",
    "/World/Routes",
)

@dataclass(frozen=True)
class MapExtent:
    min_x: float
    max_x: float
    min_y: float
    max_y: float

    @property
    def width(self):
        return max(self.max_x - self.min_x, 1e-6)

    @property
    def height(self):
        return max(self.max_y - self.min_y, 1e-6)


@dataclass(frozen=True)
class CoordinateSystemInfo:
    up_axis: str
    ground_plane: str
    meters_per_unit: float
    world_origin: tuple[float, float, float]
    horizontal_axes: tuple[str, str]
    horizontal_indices: tuple[int, int]


@dataclass(frozen=True)
class StageAnalysisReport:
    coordinate: CoordinateSystemInfo
    extent: MapExtent
    convention_roots: dict[str, bool]
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class TrackedObjectSnapshot:
    kind: str
    prim_path: str
    label: str
    world_position: tuple[float, float, float]
    pixel_position: tuple[float, float]
    clipped: bool
    heading_deg: float | None = None


@dataclass(frozen=True)
class BackgroundFeatureSnapshot:
    kind: str
    prim_path: str
    label: str
    pixel_x: float
    pixel_y: float
    pixel_width: float
    pixel_height: float
    clipped: bool
    draw_priority: int


@dataclass(frozen=True)
class MinimapSnapshot:
    report: StageAnalysisReport
    background_features: tuple[BackgroundFeatureSnapshot, ...]
    objects_by_kind: dict[str, tuple[TrackedObjectSnapshot, ...]]
    warnings: tuple[str, ...] = ()

    @property
    def total_count(self):
        return sum(len(items) for items in self.objects_by_kind.values())

    def legend_counts(self):
        return {kind: len(self.objects_by_kind.get(kind, ())) for kind in TRACKED_KIND_ORDER}

    def background_counts(self):
        counts = {}
        for feature in self.background_features:
            counts[feature.kind] = counts.get(feature.kind, 0) + 1
        return counts


class WorldToMinimapConverter:
    def __init__(self, report, width=MINIMAP_MAP_WIDTH, height=MINIMAP_MAP_HEIGHT):
        self.report = report
        self.width = float(width)
        self.height = float(height)

    def project_world_position(self, world_position):
        index_x, index_y = self.report.coordinate.horizontal_indices
        horizontal_x = float(world_position[index_x])
        horizontal_y = float(world_position[index_y])
        return self.project_horizontal(horizontal_x, horizontal_y)

    def project_horizontal(self, horizontal_x, horizontal_y):
        extent = self.report.extent
        u = (float(horizontal_x) - extent.min_x) / extent.width
        v = (float(horizontal_y) - extent.min_y) / extent.height
        clipped = u < 0.0 or u > 1.0 or v < 0.0 or v > 1.0
        u = max(0.0, min(u, 1.0))
        v = max(0.0, min(v, 1.0))
        return (u * self.width, (1.0 - v) * self.height), clipped

    def project_horizontal_bounds(self, min_x, max_x, min_y, max_y):
        extent = self.report.extent
        u0 = (float(min_x) - extent.min_x) / extent.width
        u1 = (float(max_x) - extent.min_x) / extent.width
        v0 = (float(min_y) - extent.min_y) / extent.height
        v1 = (float(max_y) - extent.min_y) / extent.height
        clipped = u1 < 0.0 or u0 > 1.0 or v1 < 0.0 or v0 > 1.0
        u0 = max(0.0, min(u0, 1.0))
        u1 = max(0.0, min(u1, 1.0))
        v0 = max(0.0, min(v0, 1.0))
        v1 = max(0.0, min(v1, 1.0))

        pixel_x = min(u0, u1) * self.width
        pixel_width = max(abs(u1 - u0) * self.width, 1.0)
        pixel_y = (1.0 - max(v0, v1)) * self.height
        pixel_height = max(abs(v1 - v0) * self.height, 1.0)
        return pixel_x, pixel_y, pixel_width, pixel_height, clipped


class MinimapTracker:
    def __init__(
        self,
        width=MINIMAP_MAP_WIDTH,
        height=MINIMAP_MAP_HEIGHT,
        update_interval=MINIMAP_UPDATE_INTERVAL_SEC,
        scan_interval=MINIMAP_SCAN_INTERVAL_SEC,
    ):
        self.width = int(width)
        self.height = int(height)
        self.update_interval = max(float(update_interval), 0.01)
        self.scan_interval = max(float(scan_interval), self.update_interval)
        self._update_elapsed = self.update_interval
        self._scan_elapsed = self.scan_interval
        self._stage_signature = None
        self._tracked_paths = None
        self._background_features = ()
        self._last_snapshot = None
        self._last_report = None

    def step(self, dt):
        self._update_elapsed += max(float(dt), 0.0)
        self._scan_elapsed += max(float(dt), 0.0)
        if self._last_snapshot is None or self._update_elapsed >= self.update_interval:
            force_scan = self._tracked_paths is None or self._scan_elapsed >= self.scan_interval
            self._last_snapshot = self.refresh(force_scan=force_scan)
            self._update_elapsed = 0.0
            if force_scan:
                self._scan_elapsed = 0.0
            return self._last_snapshot, True
        return self._last_snapshot, False

    def refresh(self, force_scan=False):
        stage = get_stage()
        stage_signature = self._stage_signature_for(stage)

        if stage_signature != self._stage_signature:
            self._stage_signature = stage_signature
            force_scan = True

        report = analyze_stage(stage)
        self._last_report = report

        if force_scan or self._tracked_paths is None:
            self._tracked_paths = self._scan_target_paths(stage)

        converter = WorldToMinimapConverter(report, self.width, self.height)
        if force_scan or not self._background_features:
            self._background_features = tuple(self._collect_background_features(stage, converter))
        objects_by_kind = {}
        warnings = []

        for kind in TRACKED_KIND_ORDER:
            snapshots = []
            for prim_path in self._tracked_paths.get(kind, ()):
                snapshot = self._snapshot_for_path(stage, prim_path, kind, converter)
                if snapshot is not None:
                    snapshots.append(snapshot)
            objects_by_kind[kind] = tuple(snapshots)

        if not report.convention_roots.get(CCTV_ROOT_PATH, False) and not report.convention_roots.get(MICROPHONE_ROOT_PATH, False):
            warnings.append("Listener root missing: /World/CCTV or /World/Microphones")
        if not report.convention_roots.get(SOUND_SOURCE_MARKER_ROOT_PATH, False):
            warnings.append(f"Sound source root missing: {SOUND_SOURCE_MARKER_ROOT_PATH}")
        if not self._background_features:
            warnings.append("No minimap background features detected in stage geometry scan")
        else:
            background_kinds = {feature.kind for feature in self._background_features}
            if "road" not in background_kinds:
                warnings.append("Road background not detected")
            if "building" not in background_kinds and "city" not in background_kinds:
                warnings.append("City/building background not detected")

        return MinimapSnapshot(
            report=report,
            background_features=self._background_features,
            objects_by_kind=objects_by_kind,
            warnings=tuple(warnings),
        )

    def describe_stage(self):
        return self._last_report

    def _scan_target_paths(self, stage):
        vehicle_paths = self._collect_child_paths(stage, (VEHICLE_ROOT_PATH,))
        ego_paths = self._collect_exact_paths(stage, EGO_VEHICLE_PATHS)
        ego_path_set = set(ego_paths)
        vehicle_paths = [path for path in vehicle_paths if path not in ego_path_set]

        return {
            "ego_vehicle": ego_paths[:1],
            "vehicles": vehicle_paths[:MINIMAP_MAX_MARKERS_PER_TYPE],
            "pedestrians": self._collect_child_paths(
                stage,
                (PEDESTRIAN_ROOT_PATH, CHARACTER_ROOT_PATH),
            )[:MINIMAP_MAX_MARKERS_PER_TYPE],
            "sound_sources": self._collect_child_paths(
                stage,
                (SOUND_SOURCE_MARKER_ROOT_PATH,),
            )[:MINIMAP_MAX_MARKERS_PER_TYPE],
            "listener_or_microphone": self._collect_child_paths(
                stage,
                (MICROPHONE_ROOT_PATH, CCTV_ROOT_PATH),
            )[:MINIMAP_MAX_MARKERS_PER_TYPE],
            "events": self._collect_event_paths(stage)[:MINIMAP_MAX_MARKERS_PER_TYPE],
        }

    def _collect_exact_paths(self, stage, prim_paths):
        collected = []
        for prim_path in prim_paths:
            prim = stage.GetPrimAtPath(prim_path)
            if prim.IsValid():
                collected.append(str(prim.GetPath()))
        return collected

    def _collect_child_paths(self, stage, root_paths):
        collected = []
        seen = set()
        for root_path in root_paths:
            root = stage.GetPrimAtPath(root_path)
            if not root.IsValid():
                continue
            for child in root.GetChildren():
                child_path = str(child.GetPath())
                if child_path in seen:
                    continue
                seen.add(child_path)
                collected.append(child_path)
        collected.sort()
        return collected

    def _collect_event_paths(self, stage):
        root = stage.GetPrimAtPath(MINIMAP_EVENT_ROOT_PATH)
        if not root.IsValid():
            return []

        collected = []
        seen = set()
        for prim in Usd.PrimRange(root):
            if prim == root:
                continue
            if not prim.IsValid():
                continue
            if not self._is_current_event_prim(prim):
                continue
            prim_path = str(prim.GetPath())
            if prim_path in seen:
                continue
            seen.add(prim_path)
            collected.append(prim_path)
        collected.sort()
        return collected

    def _is_current_event_prim(self, prim):
        imageable = UsdGeom.Imageable(prim)
        if imageable:
            try:
                if imageable.ComputeVisibility(Usd.TimeCode.Default()) == UsdGeom.Tokens.invisible:
                    return False
            except Exception:
                pass

        attr = prim.GetAttribute("cctv_sim:is_gt_event")
        if attr.IsValid() and bool(attr.Get()):
            return True

        event_type_attr = prim.GetAttribute("cctv_sim:event_type")
        if event_type_attr.IsValid() and event_type_attr.Get():
            return True

        return False

    def _snapshot_for_path(self, stage, prim_path, kind, converter):
        prim = stage.GetPrimAtPath(prim_path)
        if not prim.IsValid():
            return None

        world_position = compute_world_position(prim)
        pixel_position, clipped = converter.project_world_position(world_position)
        heading_deg = None
        if kind in {"ego_vehicle", "vehicles", "pedestrians", "listener_or_microphone"}:
            heading_deg = compute_heading_deg(prim)
        return TrackedObjectSnapshot(
            kind=kind,
            prim_path=prim_path,
            label=prim.GetName(),
            world_position=world_position,
            pixel_position=pixel_position,
            clipped=clipped,
            heading_deg=heading_deg,
        )

    def _collect_background_features(self, stage, converter):
        bbox_cache = UsdGeom.BBoxCache(
            Usd.TimeCode.Default(),
            [UsdGeom.Tokens.default_],
            useExtentsHint=True,
        )
        features = []
        seen_paths = set()
        for root_path in BACKGROUND_SEARCH_ROOTS:
            root = stage.GetPrimAtPath(root_path)
            if not root.IsValid():
                continue
            for prim in Usd.PrimRange(root):
                if not prim.IsValid():
                    continue
                prim_path = str(prim.GetPath())
                if any(
                    prim_path == prefix or prim_path.startswith(f"{prefix}/")
                    for prefix in BACKGROUND_EXCLUDED_PREFIXES
                ):
                    continue
                if not _is_background_drawable_prim(prim):
                    continue
                try:
                    box = bbox_cache.ComputeWorldBound(prim).ComputeAlignedBox()
                except Exception:
                    continue
                if box.IsEmpty():
                    continue
                kind, draw_priority = _classify_background_prim(
                    prim,
                    box=box,
                    horizontal_indices=converter.report.coordinate.horizontal_indices,
                )
                if kind is None:
                    continue
                if prim_path in seen_paths:
                    continue

                index_x, index_y = converter.report.coordinate.horizontal_indices
                bbox_min = box.GetMin()
                bbox_max = box.GetMax()
                min_x = float(bbox_min[index_x])
                max_x = float(bbox_max[index_x])
                min_y = float(bbox_min[index_y])
                max_y = float(bbox_max[index_y])
                if max_x <= min_x or max_y <= min_y:
                    continue

                pixel_x, pixel_y, pixel_width, pixel_height, clipped = converter.project_horizontal_bounds(
                    min_x=min_x,
                    max_x=max_x,
                    min_y=min_y,
                    max_y=max_y,
                )
                if _should_skip_background_feature(
                    kind=kind,
                    pixel_width=pixel_width,
                    pixel_height=pixel_height,
                    converter=converter,
                ):
                    continue

                seen_paths.add(prim_path)
                features.append(
                    BackgroundFeatureSnapshot(
                        kind=kind,
                        prim_path=prim_path,
                        label=prim.GetName(),
                        pixel_x=pixel_x,
                        pixel_y=pixel_y,
                        pixel_width=pixel_width,
                        pixel_height=pixel_height,
                        clipped=clipped,
                        draw_priority=draw_priority,
                    )
                )

        features.sort(
            key=lambda feature: (
                feature.draw_priority,
                -(feature.pixel_width * feature.pixel_height),
                feature.label,
            )
        )
        return features[:MINIMAP_BACKGROUND_FEATURE_LIMIT]

    def _stage_signature_for(self, stage):
        root_layer = stage.GetRootLayer()
        return getattr(root_layer, "identifier", "") or getattr(root_layer, "realPath", "")


def analyze_stage(stage):
    up_axis_token = _safe_up_axis(stage)
    up_axis = "Y" if up_axis_token == UsdGeom.Tokens.y else "Z"
    horizontal_axes = ("X", "Z") if up_axis == "Y" else ("X", "Y")
    horizontal_indices = (0, 2) if up_axis == "Y" else (0, 1)

    coordinate = CoordinateSystemInfo(
        up_axis=up_axis,
        ground_plane=f"{horizontal_axes[0]}-{horizontal_axes[1]}",
        meters_per_unit=_safe_meters_per_unit(stage),
        world_origin=(0.0, 0.0, 0.0),
        horizontal_axes=horizontal_axes,
        horizontal_indices=horizontal_indices,
    )

    extent = _compute_map_extent(stage, horizontal_indices, prefer_cctv_extent=True)
    convention_roots = {
        VEHICLE_ROOT_PATH: stage.GetPrimAtPath(VEHICLE_ROOT_PATH).IsValid(),
        CHARACTER_ROOT_PATH: stage.GetPrimAtPath(CHARACTER_ROOT_PATH).IsValid(),
        PEDESTRIAN_ROOT_PATH: stage.GetPrimAtPath(PEDESTRIAN_ROOT_PATH).IsValid(),
        SOUND_SOURCE_MARKER_ROOT_PATH: stage.GetPrimAtPath(SOUND_SOURCE_MARKER_ROOT_PATH).IsValid(),
        MICROPHONE_ROOT_PATH: stage.GetPrimAtPath(MICROPHONE_ROOT_PATH).IsValid(),
        CCTV_ROOT_PATH: stage.GetPrimAtPath(CCTV_ROOT_PATH).IsValid(),
        EVENT_ROOT_PATH: stage.GetPrimAtPath(EVENT_ROOT_PATH).IsValid(),
    }

    notes = [
        f"Up-axis={coordinate.up_axis}, ground={coordinate.ground_plane}, metersPerUnit={coordinate.meters_per_unit:.4f}",
        f"Extent={coordinate.horizontal_axes[0]}[{extent.min_x:.1f}, {extent.max_x:.1f}] "
        f"{coordinate.horizontal_axes[1]}[{extent.min_y:.1f}, {extent.max_y:.1f}]",
    ]
    return StageAnalysisReport(
        coordinate=coordinate,
        extent=extent,
        convention_roots=convention_roots,
        notes=tuple(notes),
    )


def compute_world_position(prim):
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
    position = matrix.ExtractTranslation()
    return (float(position[0]), float(position[1]), float(position[2]))


def compute_heading_deg(prim):
    try:
        matrix = UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
        axis = matrix.TransformDir(Gf.Vec3d(1.0, 0.0, 0.0))
        if _safe_up_axis(prim.GetStage()) == UsdGeom.Tokens.y:
            horizontal_y = float(axis[2])
        else:
            horizontal_y = float(axis[1])
        horizontal_x = float(axis[0])
        if abs(horizontal_x) < 1e-6 and abs(horizontal_y) < 1e-6:
            return None
        return math.degrees(math.atan2(horizontal_y, horizontal_x))
    except Exception:
        return None


def _classify_background_prim(prim, box=None, horizontal_indices=None):
    name = prim.GetName().lower()
    path = str(prim.GetPath()).lower()
    material_tokens = " ".join(_background_material_tokens(prim))
    text = f"{path}/{name} {material_tokens}"

    if any(token in text for token in ("ground", "terrain", "landscape")):
        return "ground", 0
    if any(
        token in text
        for token in (
            "road",
            "street",
            "streetnetwork",
            "asphalt",
            "lane",
            "lanes_",
            "crosswalk",
            "centerline",
            "stripes",
            "marking",
            "markings",
            "mat_asphalt",
        )
    ):
        return "road", 1
    if any(token in text for token in ("sidewalk", "pavement", "walkway", "pedestrian", "mat_sidewalk")):
        return "sidewalk", 2
    if any(token in text for token in ("curb", "kerb", "mat_curb")):
        return "curb", 3
    if any(
        token in text
        for token in ("building", "tower", "block", "assembly", "facade", "skyscraper", "mat_building")
    ):
        return "building", 4
    if any(token in text for token in ("mark", "stripe", "yellow_", "white_", "arrow")):
        return "lane_marking", 5
    if _looks_like_road_surface(box, horizontal_indices) and any(
        token in text
        for token in (
            "citydemolargestreets",
            "large_streets",
            "streetsegment",
            "street_geo",
            "traffic",
            "intersection",
            "junction",
            "ce_context_city_large_streets",
        )
    ):
        return "road", 1
    if any(
        token in text
        for token in (
            "/environment/citydemo",
            "context_city",
            "citydemolargestreets",
            "citydemopack",
            "city/",
        )
    ):
        return "city", 4
    if _looks_like_road_surface(box, horizontal_indices):
        return "road", 1
    return None, 99


def _background_material_tokens(prim):
    tokens = []
    current = prim
    depth = 0
    while current and current.IsValid() and depth < 4:
        relationship = current.GetRelationship("material:binding")
        if relationship.IsValid():
            try:
                for target in relationship.GetTargets():
                    target_text = str(target).lower()
                    tokens.append(target_text)
                    tokens.extend(part for part in target_text.replace("/", " ").split() if part)
            except Exception:
                pass
        current = current.GetParent()
        depth += 1
    return tokens
def _is_background_drawable_prim(prim):
    try:
        if prim.IsA(UsdGeom.Gprim):
            return True
    except Exception:
        pass

    type_name = prim.GetTypeName()
    return type_name in {"Mesh", "Cube", "Sphere", "Cylinder", "Capsule", "Cone"}


def _should_skip_background_feature(kind, pixel_width, pixel_height, converter):
    if pixel_width < MINIMAP_BACKGROUND_MIN_PIXEL_SIZE or pixel_height < MINIMAP_BACKGROUND_MIN_PIXEL_SIZE:
        return True

    if kind in {"ground", "road", "sidewalk"}:
        return False

    feature_area = float(pixel_width) * float(pixel_height)
    total_area = max(float(converter.width) * float(converter.height), 1.0)
    if feature_area / total_area > MINIMAP_BACKGROUND_MAX_AREA_RATIO:
        return True

    return False


def _looks_like_road_surface(box, horizontal_indices):
    if box is None or horizontal_indices is None or box.IsEmpty():
        return False

    bbox_min = box.GetMin()
    bbox_max = box.GetMax()
    dimensions = [float(bbox_max[i] - bbox_min[i]) for i in range(3)]
    up_index = next((index for index in range(3) if index not in horizontal_indices), None)
    if up_index is None:
        return False

    horizontal_spans = sorted(
        (dimensions[horizontal_indices[0]], dimensions[horizontal_indices[1]]),
        reverse=True,
    )
    longest_span, shortest_span = horizontal_spans
    vertical_span = dimensions[up_index]

    # Road meshes in the city demo are typically broad and flat, even when their names
    # are not road-like. Keep the thresholds loose enough for referenced street tiles.
    return (
        longest_span >= 60.0
        and shortest_span >= 10.0
        and vertical_span <= 20.0
        and vertical_span <= shortest_span * 0.35
    )


def compute_stage_overview_extent(stage):
    up_axis_token = _safe_up_axis(stage)
    horizontal_indices = (0, 2) if up_axis_token == UsdGeom.Tokens.y else (0, 1)
    return _compute_map_extent(stage, horizontal_indices, prefer_cctv_extent=False)


def _compute_map_extent(stage, horizontal_indices, prefer_cctv_extent=True):
    cctv_extent = _compute_cctv_extent(stage, horizontal_indices) if prefer_cctv_extent else None
    if cctv_extent is not None:
        return cctv_extent

    bbox_cache = UsdGeom.BBoxCache(
        Usd.TimeCode.Default(),
        [UsdGeom.Tokens.default_],
        useExtentsHint=True,
    )
    candidate_paths = (
        "/World/Environment",
        "/World/Routes",
        CCTV_ROOT_PATH,
        VEHICLE_ROOT_PATH,
        CHARACTER_ROOT_PATH,
        PEDESTRIAN_ROOT_PATH,
        SOUND_SOURCE_MARKER_ROOT_PATH,
        EVENT_ROOT_PATH,
    )
    ranges = []
    for prim_path in candidate_paths:
        prim = stage.GetPrimAtPath(prim_path)
        if not prim.IsValid():
            continue
        try:
            box = bbox_cache.ComputeWorldBound(prim).ComputeAlignedBox()
        except Exception:
            continue
        if box.IsEmpty():
            continue
        bbox_min = box.GetMin()
        bbox_max = box.GetMax()
        index_x, index_y = horizontal_indices
        ranges.append(
            (
                float(bbox_min[index_x]),
                float(bbox_max[index_x]),
                float(bbox_min[index_y]),
                float(bbox_max[index_y]),
            )
        )

    if not ranges:
        return MapExtent(
            min_x=float(MINIMAP_FALLBACK_EXTENT["min_x"]),
            max_x=float(MINIMAP_FALLBACK_EXTENT["max_x"]),
            min_y=float(MINIMAP_FALLBACK_EXTENT["min_y"]),
            max_y=float(MINIMAP_FALLBACK_EXTENT["max_y"]),
        )

    min_x = min(item[0] for item in ranges) - MINIMAP_EXTENT_PADDING
    max_x = max(item[1] for item in ranges) + MINIMAP_EXTENT_PADDING
    min_y = min(item[2] for item in ranges) - MINIMAP_EXTENT_PADDING
    max_y = max(item[3] for item in ranges) + MINIMAP_EXTENT_PADDING
    return MapExtent(min_x=min_x, max_x=max_x, min_y=min_y, max_y=max_y)


def _compute_cctv_extent(stage, horizontal_indices):
    root = stage.GetPrimAtPath(CCTV_ROOT_PATH)
    if not root.IsValid():
        return None

    cctv_positions = []
    for child in root.GetChildren():
        if not child.IsValid():
            continue
        position = compute_world_position(child)
        index_x, index_y = horizontal_indices
        cctv_positions.append((float(position[index_x]), float(position[index_y])))

    if not cctv_positions:
        return None

    min_x = min(position[0] for position in cctv_positions)
    max_x = max(position[0] for position in cctv_positions)
    min_y = min(position[1] for position in cctv_positions)
    max_y = max(position[1] for position in cctv_positions)

    min_x -= MINIMAP_CCTV_EXTENT_MARGIN
    max_x += MINIMAP_CCTV_EXTENT_MARGIN
    min_y -= MINIMAP_CCTV_EXTENT_MARGIN
    max_y += MINIMAP_CCTV_EXTENT_MARGIN

    width = max_x - min_x
    height = max_y - min_y
    if width < MINIMAP_CCTV_MIN_SPAN:
        half_expand = (MINIMAP_CCTV_MIN_SPAN - width) * 0.5
        min_x -= half_expand
        max_x += half_expand
    if height < MINIMAP_CCTV_MIN_SPAN:
        half_expand = (MINIMAP_CCTV_MIN_SPAN - height) * 0.5
        min_y -= half_expand
        max_y += half_expand

    return MapExtent(min_x=min_x, max_x=max_x, min_y=min_y, max_y=max_y)


def _safe_up_axis(stage):
    try:
        return UsdGeom.GetStageUpAxis(stage)
    except Exception:
        return UsdGeom.Tokens.z


def _safe_meters_per_unit(stage):
    try:
        return float(UsdGeom.GetStageMetersPerUnit(stage))
    except Exception:
        return 1.0
