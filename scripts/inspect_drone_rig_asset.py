import asyncio
import builtins
from pathlib import Path
import sys

import omni.kit.app
import omni.usd
from pxr import Gf, Usd, UsdGeom


REPO_ROOT = Path("/home/user/Documents/DT_teamA")
sys.path.insert(0, str(REPO_ROOT / "omniverse" / "cctv_sim"))
STAGE_PATH = REPO_ROOT / "omniverse" / "cctv_sim" / "assets" / "city" / "World_CityDemopack.usd"
START_DEMO_PATH = REPO_ROOT / "omniverse" / "cctv_sim" / "scripts" / "start_demo.py"


def _exec_script(script_path):
    namespace = {
        "__name__": "__main__",
        "__file__": str(script_path),
    }
    exec(compile(script_path.read_text(encoding="utf-8"), str(script_path), "exec"), namespace)
    return namespace


def _visibility_of(prim):
    if not prim.IsA(UsdGeom.Imageable):
        return "n/a"
    visibility = UsdGeom.Imageable(prim).GetVisibilityAttr().Get()
    return "inherited" if visibility is None else str(visibility)


async def main():
    opened = omni.usd.get_context().open_stage(str(STAGE_PATH))
    print(f"[inspect_drone_rig_asset] open_stage={opened}")

    for _ in range(240):
        await omni.kit.app.get_app().next_update_async()
        stage = omni.usd.get_context().get_stage()
        if stage is not None and stage.GetPrimAtPath("/World").IsValid():
            break
    else:
        raise RuntimeError("Stage did not finish loading")

    _exec_script(START_DEMO_PATH)
    for _ in range(180):
        await omni.kit.app.get_app().next_update_async()

    demo_app = getattr(builtins, "demo_app", None)
    if demo_app is None:
        raise RuntimeError("demo_app not available")

    rig = demo_app.follow_top_camera.drone_rig
    if rig is None:
        raise RuntimeError("DroneRig not available")

    stage = omni.usd.get_context().get_stage()
    visual_prim = stage.GetPrimAtPath(rig.get_visual_path())
    print(f"[inspect_drone_rig_asset] visual_path={rig.get_visual_path()} valid={visual_prim.IsValid()} active={visual_prim.IsActive()}")
    print(f"[inspect_drone_rig_asset] visual_visibility={_visibility_of(visual_prim)}")
    print(f"[inspect_drone_rig_asset] resolved_asset={rig.get_resolved_asset_path()}")
    bbox_cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), [UsdGeom.Tokens.default_, UsdGeom.Tokens.render])
    visual_bound = bbox_cache.ComputeWorldBound(visual_prim)
    visual_range = visual_bound.ComputeAlignedBox()
    visual_size = visual_range.GetSize()
    visual_center = visual_range.GetMidpoint()
    print(
        "[inspect_drone_rig_asset] "
        f"visual_world_center=({visual_center[0]:.3f}, {visual_center[1]:.3f}, {visual_center[2]:.3f}) "
        f"visual_world_size=({visual_size[0]:.3f}, {visual_size[1]:.3f}, {visual_size[2]:.3f})"
    )

    rig_prim = stage.GetPrimAtPath(str(rig.rig_path))
    rig_xform = UsdGeom.Xformable(rig_prim)
    local_transform = rig_xform.GetLocalTransformation()
    rig_translation = local_transform.ExtractTranslation()
    print(
        "[inspect_drone_rig_asset] "
        f"rig_translation=({rig_translation[0]:.3f}, {rig_translation[1]:.3f}, {rig_translation[2]:.3f})"
    )

    total = 0
    meshes = 0
    active_meshes = 0
    visible_meshes = 0
    sample_lines = []

    for prim in Usd.PrimRange(visual_prim):
        if not prim.IsValid():
            continue
        total += 1
        is_mesh = prim.GetTypeName() == "Mesh"
        if is_mesh:
            meshes += 1
            if prim.IsActive():
                active_meshes += 1
            if _visibility_of(prim) != "invisible":
                visible_meshes += 1
            if len(sample_lines) < 20:
                sample_lines.append(
                    f"{prim.GetPath()} active={prim.IsActive()} visibility={_visibility_of(prim)}"
                )

    print(
        "[inspect_drone_rig_asset] "
        f"total_prims={total} meshes={meshes} active_meshes={active_meshes} visible_meshes={visible_meshes}"
    )
    for line in sample_lines:
        print(f"[inspect_drone_rig_asset] mesh_sample={line}")

    omni.kit.app.get_app().post_quit()


asyncio.ensure_future(main())
