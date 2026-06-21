# cctv_sim/scripts/reset_stage.py

import omni.usd
import omni.timeline

try:
    if "demo_app" in globals() and demo_app is not None:
        demo_app.stop()
        print("[reset_stage] demo_app stopped")
except Exception as e:
    print("[reset_stage] failed to stop demo_app:", e)

globals()["demo_app"] = None

timeline = omni.timeline.get_timeline_interface()
timeline.stop()
timeline.set_current_time(0.0)

stage = omni.usd.get_context().get_stage()

for path in [
    "/World/Characters",
    "/World/Sources",
    "/World/CCTV",
    "/World/Events",
]:
    prim = stage.GetPrimAtPath(path)
    if prim.IsValid():
        stage.RemovePrim(path)
        print("[reset_stage] removed:", path)

print("[reset_stage] done")