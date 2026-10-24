"""Same-grid saved RGB association. Never scales, undistorts or aligns inputs."""
from dataclasses import dataclass
import numpy as np
from paths import load_contract

@dataclass(frozen=True)
class ColorCloud:
    points_m: np.ndarray
    pixel_vu: np.ndarray
    pixel_id: np.ndarray
    rgb_u8: np.ndarray
    color_candidate: np.ndarray

def build_color_cloud(frame, rgb_u8):
    contract=load_contract()
    contract.validate_frame(frame)
    if not isinstance(rgb_u8,np.ndarray) or rgb_u8.dtype!=np.uint8 or rgb_u8.shape!=(*frame.depth_m.shape,3):
        raise ValueError('RGB must be same-grid HxWx3 uint8; resizing/BGR inference is forbidden')
    v,u=np.nonzero(frame.valid_mask)
    points=contract.point_cloud_camera(frame)
    pixels=np.column_stack((v,u)).astype(np.int64)
    ids=(v*frame.depth_m.shape[1]+u).astype(np.int64)
    colors=rgb_u8[v,u].copy()
    # No availability mask was supplied. Black is ambiguous (real black or no sample).
    # Preserve the stored RGB and all Depth rows; only the rendering status differs.
    candidates=np.any(colors!=0,axis=1)
    for a in (points,pixels,ids,colors,candidates):a.flags.writeable=False
    return ColorCloud(points,pixels,ids,colors,candidates)

def select_display(cloud, max_points, depth_range=None):
    if type(max_points) is not int or max_points<1:raise ValueError('positive integer sample limit required')
    rows=np.arange(len(cloud.points_m),dtype=np.int64)
    if depth_range is not None:
        bounds=np.asarray(depth_range,dtype=float)
        if bounds.shape!=(2,) or not np.isfinite(bounds).all() or not (0<bounds[0]<bounds[1]):
            raise ValueError('positive finite increasing display Z range required')
        z=cloud.points_m[:,2]
        rows=rows[(z>=bounds[0])&(z<=bounds[1])]
        if not len(rows):raise ValueError('display window contains no points')
    if len(rows)>max_points:
        rows=rows[np.linspace(0,len(rows)-1,max_points,dtype=np.int64)]
    rows.flags.writeable=False
    return rows

def zoom_limits(limits, factor):
    a=np.asarray(limits,dtype=float)
    if a.shape!=(3,2) or not np.isfinite(a).all() or not np.isfinite(factor) or factor<=0:
        raise ValueError('finite 3-axis bounds and positive zoom factor required')
    center=a.mean(axis=1,keepdims=True)
    return center+(a-center)*factor
