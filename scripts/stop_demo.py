import builtins
import omni.timeline
import omni.usd
import omni.ui as ui
from pxr import UsdGeom


def _clear_children(stage, root_path):
    root = stage.GetPrimAtPath(root_path)
    if not root.IsValid():
        return 0

    child_paths = [child.GetPath() for child in root.GetChildren()]
    for path in child_paths:
        stage.RemovePrim(path)
    return len(child_paths)

def _stop_app(app, label):
    if app is None:
        return
    try:
        app.stop()
        print(f"[stop_demo] {label} stopped")
    except Exception as e:
        print(f"[stop_demo] failed to stop {label}:", e)


def _hide_window(title):
    try:
        window = ui.Workspace.get_window(title)
        if window is not None:
            window.visible = False
            print(f"[stop_demo] hidden window: {title}")
    except Exception as e:
        print(f"[stop_demo] failed to hide window {title}:", e)


def _clear_legacy_explosion_markers(stage):
    root = stage.GetPrimAtPath("/World/Events")
    if not root.IsValid():
        return 0

    removed = 0
    keep_paths = {"/World/Events/Explosion"}
    for child in list(root.GetChildren()):
        path = str(child.GetPath())
        if path in keep_paths:
            continue
        event_type_attr = child.GetAttribute("cctv_sim:event_type")
        event_type = event_type_attr.Get() if event_type_attr.IsValid() else None
        if (
            path in {"/World/Events/ExplosionVDB", "/World/Events/ExplosionUSD"}
            or event_type == "explosion"
            or child.GetName().startswith("explosion")
        ):
            stage.RemovePrim(child.GetPath())
            removed += 1
    return removed


def _hide_explosion_source_prims(stage):
    hidden = 0
    for root_path in ("/World/Explosion", "/World/Events/Explosion"):
        root = stage.GetPrimAtPath(root_path)
        if not root.IsValid():
            continue
        for child in root.GetChildren():
            UsdGeom.Imageable(child).MakeInvisible()
            hidden += 1
    return hidden


_stop_app(globals().get("demo_app"), "globals demo_app")
_stop_app(getattr(builtins, "demo_app", None), "builtins demo_app")
_stop_app(getattr(builtins, "_cctv_sim_demo_app", None), "builtins _cctv_sim_demo_app")

globals()["demo_app"] = None
setattr(builtins, "demo_app", None)
setattr(builtins, "_cctv_sim_demo_app", None)

_hide_window("CCTV Sound Event Demo")
_hide_window("CCTV Monitor")
_hide_window("Stage Minimap")

timeline = omni.timeline.get_timeline_interface()
timeline.stop()
timeline.set_current_time(0.0)

stage = omni.usd.get_context().get_stage()
if stage is not None:
    removed_characters = _clear_children(stage, "/World/Characters")
    removed_sources = _clear_children(stage, "/World/Sources")
    removed_explosions = _clear_legacy_explosion_markers(stage)
    hidden_explosions = _hide_explosion_source_prims(stage)
    print(f"[stop_demo] removed {removed_characters} Characters child prim(s)")
    print(f"[stop_demo] removed {removed_sources} Sources child prim(s)")
    print(f"[stop_demo] removed {removed_explosions} legacy Explosion marker prim(s)")
    print(f"[stop_demo] hidden {hidden_explosions} Explosion source prim(s)")
    cctv_root = stage.GetPrimAtPath("/World/CCTV")
    preserved_cctvs = len(list(cctv_root.GetChildren())) if cctv_root.IsValid() else 0
    print(f"[stop_demo] preserved {preserved_cctvs} CCTV child prim(s)")

print("[stop_demo] done")
