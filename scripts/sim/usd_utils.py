import os
from pathlib import Path

import omni.usd
from pxr import Sdf, UsdGeom


_XFORM_OP_VALUE_TYPES = {
    "xformOp:translate": Sdf.ValueTypeNames.Double3,
    "xformOp:rotateXYZ": Sdf.ValueTypeNames.Double3,
    "xformOp:scale": Sdf.ValueTypeNames.Double3,
}


def get_stage():
    stage = omni.usd.get_context().get_stage()
    if stage is None:
        raise RuntimeError("No active USD stage")
    return stage


def ensure_xform(stage, path):
    prim = stage.GetPrimAtPath(path)
    if prim and prim.IsValid():
        return prim
    return UsdGeom.Xform.Define(stage, Sdf.Path(path)).GetPrim()


def _get_ordered_xform_op(xformable, attr_name):
    for op in xformable.GetOrderedXformOps():
        if op.GetOpName() == attr_name:
            return op
    return None


def _xform_op_order_has_token(xformable, attr_name):
    order = xformable.GetXformOpOrderAttr().Get()
    if not order:
        return False
    return any(str(token) == attr_name for token in order)


def _append_xform_op_order(xformable, xform_op):
    ordered_ops = list(xformable.GetOrderedXformOps())
    if any(op.GetOpName() == xform_op.GetOpName() for op in ordered_ops):
        return

    ordered_ops.append(xform_op)
    xformable.SetXformOpOrder(ordered_ops)


def get_or_create_xform_op(xformable, attr_name, add_fn):
    ordered_op = _get_ordered_xform_op(xformable, attr_name)
    if ordered_op is not None:
        return ordered_op

    attr = xformable.GetPrim().GetAttribute(attr_name)
    if attr and attr.IsValid():
        op = UsdGeom.XformOp(attr)
        _append_xform_op_order(xformable, op)
        return op

    if _xform_op_order_has_token(xformable, attr_name):
        value_type = _XFORM_OP_VALUE_TYPES.get(attr_name)
        if value_type is None:
            raise RuntimeError(f"Unsupported xform op in xformOpOrder: {attr_name}")
        attr = xformable.GetPrim().CreateAttribute(attr_name, value_type, custom=False)
        return UsdGeom.XformOp(attr)

    return add_fn()


def get_or_create_transform_ops(xformable):
    translate_op = get_or_create_xform_op(
        xformable,
        "xformOp:translate",
        lambda: xformable.AddTranslateOp(),
    )
    rotate_op = get_or_create_xform_op(
        xformable,
        "xformOp:rotateXYZ",
        lambda: xformable.AddRotateXYZOp(),
    )
    scale_op = get_or_create_xform_op(
        xformable,
        "xformOp:scale",
        lambda: xformable.AddScaleOp(),
    )
    xformable.SetXformOpOrder([translate_op, rotate_op, scale_op])
    return translate_op, rotate_op, scale_op


def ensure_attr(dst_prim, src_attr):
    attr = dst_prim.GetAttribute(src_attr.GetName())
    if attr and attr.IsValid():
        return attr
    return dst_prim.CreateAttribute(src_attr.GetName(), src_attr.GetTypeName(), custom=False)


def as_stage_reference_path(stage, asset_path):
    asset_path = Path(asset_path).resolve()
    root_layer = stage.GetRootLayer()
    layer_path = getattr(root_layer, "realPath", "") or root_layer.identifier

    if layer_path and not layer_path.startswith("anon:") and "://" not in layer_path:
        try:
            layer_dir = Path(layer_path).resolve().parent
            return Path(os.path.relpath(str(asset_path), str(layer_dir))).as_posix()
        except Exception:
            pass

    return str(asset_path).replace("\\", "/")


def next_free_path(stage, root_path, prefix):
    index = 1
    while True:
        path = f"{root_path}/{prefix}_{index:02d}"
        prim = stage.GetPrimAtPath(path)
        if not prim or not prim.IsValid():
            return path
        index += 1
