"""Matplotlib drawing shared by GUI and noninteractive export; arrays are read only."""
import numpy as np
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
from viewer_data import depth_preview


def make_figure():
    figure = Figure(figsize=(12, 7), dpi=110)
    depth_ax = figure.add_axes([.07,.31,.34,.58])
    cloud_ax = figure.add_axes([.52,.31,.43,.58], projection='3d')
    return figure, depth_ax, cloud_ax


def info_text(view):
    m = view.frame.metadata
    h,w = view.frame.depth_m.shape
    notice = 'SYNTHETIC DATA - excluded from real-device accuracy' if m['provenance']['kind']=='synthetic' else 'REAL source metadata - device approval is separate'
    coordinates = ''
    if len(view.display_points_m) <= 3:
        coordinates = '\n'+ '   '.join(f'P{i}=({p[0]:.4g}, {p[1]:.4g}, {p[2]:.4g}) m'
                                        for i,p in enumerate(view.display_points_m))
    return (f"frame_id: {m['frame_id']}   size: {w} x {h}   valid: {view.valid_ratio:.2%}\n"
            f"points: {len(view.points_m)} full / {len(view.display_points_m)} displayed   "
            f"capture_source: {m['capture_source']}   provenance_kind: {m['provenance']['kind']}\n"
            f"{notice}\nCamera coordinates, meters. Volume/weight: not computed.{coordinates}")


def draw_view(figure, depth_ax, cloud_ax, view):
    depth_ax.clear()
    elev, azim = cloud_ax.elev, cloud_ax.azim
    cloud_ax.clear()
    cloud_ax.view_init(elev=elev, azim=azim)
    pixels, bounds = depth_preview(view.frame)
    from matplotlib import colormaps
    cmap = colormaps['viridis'].copy()
    cmap.set_bad('#b7b7b7')
    image = depth_ax.imshow(pixels, cmap=cmap, vmin=bounds[0], vmax=bounds[1],
                            origin='upper', interpolation='nearest')
    depth_ax.set(xlabel='u (right, pixel center)', ylabel='v (down, pixel center)',
                 title=f'Depth Z: {bounds[0]:.6g} to {bounds[1]:.6g} m\nGray = invalid')
    bar = figure.colorbar(image, ax=depth_ax, fraction=.046, pad=.04)
    bar.set_label('Optical-axis depth Z (m)')
    points = view.display_points_m
    cloud_ax.scatter(points[:,0], points[:,1], points[:,2], c=points[:,2],
                     cmap='viridis', vmin=bounds[0], vmax=bounds[1], s=65 if len(points)<=10 else 3)
    if len(points) <= 10:
        for i, point in enumerate(points):
            cloud_ax.text(*point, f'  P{i}', fontsize=9)
    # Camera Y is down; reverse only the viewing axis, never point values/signs.
    spans = np.ptp(points, axis=0).astype(float)
    reference = max(float(spans.max()), .01)
    lengths = np.maximum(spans, reference*.6)
    center = (points.min(axis=0).astype(float)+points.max(axis=0).astype(float))/2
    for setter, mid, length in zip((cloud_ax.set_xlim, cloud_ax.set_ylim, cloud_ax.set_zlim), center, lengths):
        setter(mid-length*.65, mid+length*.65)
    cloud_ax.invert_yaxis()
    cloud_ax.set_box_aspect(lengths)
    from matplotlib.ticker import MaxNLocator
    for axis in (cloud_ax.xaxis, cloud_ax.yaxis, cloud_ax.zaxis):
        axis.set_major_locator(MaxNLocator(3))
    cloud_ax.set(xlabel='X right (m)', ylabel='Y down (m)', zlabel='Z forward (m)',
                 title=f'Camera Point Cloud\nDisplayed {len(points)} / full {len(view.points_m)} points')
    return image, bar


def render_preview(view, stream):
    figure, depth_ax, cloud_ax = make_figure()
    FigureCanvasAgg(figure)
    draw_view(figure, depth_ax, cloud_ax, view)
    figure.suptitle('ADE-95 Stored Depth / Camera Point Cloud', fontsize=15)
    figure.text(.07,.12,info_text(view), fontsize=10, va='bottom')
    figure.savefig(stream, format='png', dpi=140)
    figure.clear()
