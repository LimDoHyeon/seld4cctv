# City Demo route setup from moved debug tile markers
# Run from Omniverse Script Editor:
# from pathlib import Path
# SCRIPT = Path.cwd().parent / "cctv_sim" / "scripts" / "setup_citydemo_route_from_tiles.py"
# globals()["__file__"] = SCRIPT
# exec(compile(SCRIPT.read_text(encoding="utf-8"), str(SCRIPT), "exec"), globals())
#
# This script bakes /World/DebugMarkers/wp_XX_tile positions into dedicated route waypoints:
#   /World/Routes/MainRoute/wp_01
#   /World/Routes/MainRoute/wp_02
#   /World/Routes/MainRoute/wp_03
#   /World/Routes/MainRoute/wp_04
#
# The walking demo should read /World/Routes/MainRoute, not DebugMarkers.

import omni.usd
from pxr import Gf, Usd, UsdGeom

stage = omni.usd.get_context().get_stage()
if stage is None:
    raise RuntimeError("No USD stage is open. Open the City Demo stage first.")

DEBUG_ROOT = "/World/DebugMarkers"
ROUTES_ROOT = "/World/Routes"
ROUTE_PATH = "/World/Routes/MainRoute"

MARKER_NAMES = [
    "wp_01_tile",
    "wp_02_tile",
    "wp_03_tile",
    "wp_04_tile",
]

# Set True while editing route positions. Set False for a cleaner final demo.
ROUTE_DEBUG_VISIBLE = True

# If True, hide the old temporary /World/DebugMarkers group after baking.
HIDE_OLD_DEBUG_MARKERS = False

# Visual helper size under each waypoint. This visual is not used by the route controller.
DEBUG_TILE_SIZE = 180.0
DEBUG_TILE_THICKNESS = 20.0
DEBUG_PIN_SIZE = 50.0
DEBUG_PIN_HEIGHT = 220.0


def ensure_xform(path):
    prim = stage.GetPrimAtPath(path)
    if prim.IsValid():
        return prim
    return UsdGeom.Xform.Define(stage, path).GetPrim()


def remove_if_exists(path):
    if stage.GetPrimAtPath(path).IsValid():
        stage.RemovePrim(path)


def set_xform_translate(path, position):
    prim = ensure_xform(path)
    xform = UsdGeom.Xformable(prim)
    xform.ClearXformOpOrder()
    xform.AddTranslateOp().Set(Gf.Vec3d(*position))
    return prim


def create_debug_cube(path, local_position, scale, color):
    if stage.GetPrimAtPath(path).IsValid():
        stage.RemovePrim(path)

    cube = UsdGeom.Cube.Define(stage, path)
    cube.CreateSizeAttr(1.0)
    cube.CreateDisplayColorAttr([Gf.Vec3f(*color)])

    xform = UsdGeom.Xformable(cube.GetPrim())
    xform.ClearXformOpOrder()
    xform.AddTranslateOp().Set(Gf.Vec3d(*local_position))
    xform.AddScaleOp().Set(Gf.Vec3f(*scale))
    return cube.GetPrim()


def get_tile_ground_waypoint(marker_path):
    prim = stage.GetPrimAtPath(marker_path)
    if not prim.IsValid():
        raise RuntimeError(f"Marker not found: {marker_path}")

    bbox_cache = UsdGeom.BBoxCache(
        Usd.TimeCode.Default(),
        [UsdGeom.Tokens.default_],
        useExtentsHint=True,
    )
    box = bbox_cache.ComputeWorldBound(prim).ComputeAlignedBox()
    bbox_min = box.GetMin()
    bbox_max = box.GetMax()
    center = (bbox_min + bbox_max) * 0.5

    # The waypoint itself is the ground contact point. Z-up city stage.
    return (float(center[0]), float(center[1]), float(bbox_min[2]))


def set_visibility(path, visible):
    prim = stage.GetPrimAtPath(path)
    if not prim.IsValid():
        return
    imageable = UsdGeom.Imageable(prim)
    if visible:
        imageable.MakeVisible()
    else:
        imageable.MakeInvisible()


# Create clean route hierarchy.
ensure_xform("/World")
ensure_xform(ROUTES_ROOT)
remove_if_exists(ROUTE_PATH)
ensure_xform(ROUTE_PATH)

waypoints = []
for idx, marker_name in enumerate(MARKER_NAMES, 1):
    marker_path = f"{DEBUG_ROOT}/{marker_name}"
    waypoint = get_tile_ground_waypoint(marker_path)
    waypoints.append(waypoint)

    wp_path = f"{ROUTE_PATH}/wp_{idx:02d}"
    set_xform_translate(wp_path, waypoint)

    # Optional visible helper under the waypoint. The route controller reads the parent Xform only.
    create_debug_cube(
        f"{wp_path}/debug_tile",
        local_position=(0.0, 0.0, DEBUG_TILE_THICKNESS * 0.5 + 3.0),
        scale=(DEBUG_TILE_SIZE, DEBUG_TILE_SIZE, DEBUG_TILE_THICKNESS),
        color=(0.0, 0.25, 1.0),
    )
    create_debug_cube(
        f"{wp_path}/debug_pin",
        local_position=(0.0, 0.0, DEBUG_TILE_THICKNESS + DEBUG_PIN_HEIGHT * 0.5 + 10.0),
        scale=(DEBUG_PIN_SIZE, DEBUG_PIN_SIZE, DEBUG_PIN_HEIGHT),
        color=(0.0, 0.75, 1.0),
    )

set_visibility(ROUTE_PATH, ROUTE_DEBUG_VISIBLE)

if HIDE_OLD_DEBUG_MARKERS:
    set_visibility(DEBUG_ROOT, False)

print("[setup_citydemo_route_from_tiles] route baked")
print("Route root:", ROUTE_PATH)
print("Loop order: wp_01 -> wp_02 -> wp_03 -> wp_04 -> wp_01 -> ...")
print("\nWAYPOINTS = [")
for wp in waypoints:
    print(f"    ({wp[0]:.3f}, {wp[1]:.3f}, {wp[2]:.6f}),")
print("]")
print("\nTip: The final walking demo reads /World/Routes/MainRoute, not /World/DebugMarkers.")
print("Tip: To hide route helpers later, run: UsdGeom.Imageable(stage.GetPrimAtPath('/World/Routes/MainRoute')).MakeInvisible()")
