from pxr import Sdf, Usd, UsdSkel

from .config import FPS
from .usd_utils import ensure_attr


def _has_skel_animation_attrs(prim):
    return (
        prim.GetAttribute("translations").IsValid()
        or prim.GetAttribute("rotations").IsValid()
        or prim.GetAttribute("scales").IsValid()
    )


def find_source_anim_path(stage, asset_root_path):
    candidates = (
        f"{asset_root_path}/mixamorig12_Hips/mixamo_com",
        f"{asset_root_path}/mixamorig12_Hips/Take_001",
    )

    for path in candidates:
        prim = stage.GetPrimAtPath(path)
        if prim.IsValid() and _has_skel_animation_attrs(prim):
            return path

    root_prefix = asset_root_path + "/"
    for prim in stage.Traverse():
        path = str(prim.GetPath())
        if path.startswith(root_prefix) and _has_skel_animation_attrs(prim):
            return path

    raise RuntimeError(f"No valid SkelAnimation found under {asset_root_path}")


class LiveSkelAnimPlayer:
    def __init__(self, stage, asset_root_path, fps=FPS):
        self.stage = stage
        self.asset_root_path = asset_root_path
        self.fps = fps

        self.skel_root_path = f"{asset_root_path}/mixamorig12_Hips"
        self.skeleton_path = f"{asset_root_path}/mixamorig12_Hips/Skeleton"
        self.walk_source_anim_path = find_source_anim_path(stage, asset_root_path)
        self.source_anim_path = self.walk_source_anim_path
        self.live_anim_path = f"{asset_root_path}/mixamorig12_Hips/__LiveAnim"

        self.source_prim = None
        self.live_prim = None
        self.start_frame = 0.0
        self.end_frame = 28.0
        self.frame = 0.0
        self.loop = True
        self.remaining_repeats = 1

    def setup(self):
        skel_root = self.stage.GetPrimAtPath(self.skel_root_path)
        if not skel_root.IsValid():
            raise RuntimeError(f"SkelRoot not found: {self.skel_root_path}")

        if self.stage.GetPrimAtPath(self.live_anim_path).IsValid():
            self.stage.RemovePrim(self.live_anim_path)

        live_anim = UsdSkel.Animation.Define(self.stage, self.live_anim_path)
        self.live_prim = live_anim.GetPrim()

        self._bind_animation_source(skel_root)

        skeleton = self.stage.GetPrimAtPath(self.skeleton_path)
        if skeleton.IsValid():
            self._bind_animation_source(skeleton)

        self.play_walk_loop()
        print(f"[LiveSkelAnimPlayer] live anim: {self.live_anim_path}")

    def _bind_animation_source(self, prim):
        binding_api = UsdSkel.BindingAPI.Apply(prim)
        rel = binding_api.CreateAnimationSourceRel()
        rel.ClearTargets(True)
        rel.SetTargets([Sdf.Path(self.live_anim_path)])

    def play_walk_loop(self):
        self.play_clip(self.walk_source_anim_path, loop=True)

    def play_once(self, source_anim_path, repeat_count=1):
        self.play_clip(source_anim_path, loop=False, repeat_count=repeat_count)

    def play_clip(self, source_anim_path, loop=True, repeat_count=1):
        source_prim = self.stage.GetPrimAtPath(source_anim_path)
        if not source_prim.IsValid():
            raise RuntimeError(f"Source animation not found: {source_anim_path}")

        self.source_anim_path = source_anim_path
        self.source_prim = source_prim
        self.loop = loop
        self.remaining_repeats = max(1, int(repeat_count))

        joints_attr = self.source_prim.GetAttribute("joints")
        if joints_attr and joints_attr.IsValid():
            ensure_attr(self.live_prim, joints_attr).Set(joints_attr.Get())

        samples = []
        for attr_name in ("translations", "rotations", "scales"):
            attr = self.source_prim.GetAttribute(attr_name)
            if attr and attr.IsValid():
                samples.extend(attr.GetTimeSamples())

        if samples:
            self.start_frame = float(min(samples))
            self.end_frame = float(max(samples))
        else:
            self.start_frame = 0.0
            self.end_frame = 1.0

        self.frame = self.start_frame
        self.apply_frame(self.frame)
        print(f"[LiveSkelAnimPlayer] source anim: {self.source_anim_path}")

    def apply_frame(self, frame):
        for attr_name in ("translations", "rotations", "scales"):
            src_attr = self.source_prim.GetAttribute(attr_name)
            if not src_attr or not src_attr.IsValid():
                continue

            value = src_attr.Get(Usd.TimeCode(frame))
            if value is None:
                continue

            ensure_attr(self.live_prim, src_attr).Set(value)

    def update(self, dt):
        if self.source_prim is None or self.live_prim is None:
            return False

        self.frame += dt * self.fps

        if self.loop:
            length = max(self.end_frame - self.start_frame, 1.0)
            if self.frame > self.end_frame:
                self.frame = self.start_frame + ((self.frame - self.start_frame) % length)
            self.apply_frame(self.frame)
            return False

        if self.frame >= self.end_frame:
            while self.remaining_repeats > 1 and self.frame >= self.end_frame:
                self.remaining_repeats -= 1
                self.frame = self.start_frame + (self.frame - self.end_frame)

            if self.frame < self.end_frame:
                self.apply_frame(self.frame)
                return False

            self.frame = self.end_frame
            self.apply_frame(self.frame)
            return True

        self.apply_frame(self.frame)
        return False
