"""Metric orthographic review coordinates. Original XYZ and source IDs stay intact."""
import numpy as np

def plane_basis(plane):
    p=np.asarray(plane,dtype=np.float64)
    if p.shape!=(4,) or not np.isfinite(p).all() or np.linalg.norm(p[:3])<1e-15:raise ValueError('finite nonzero plane required')
    p=p/np.linalg.norm(p[:3]);resolved=bool(abs(p[3])>1e-12)
    # dot(normal, camera_origin-origin) = d for origin=-d*normal.
    if (resolved and p[3]<0) or (not resolved and p[np.argmax(abs(p[:3]))]>0):p=-p
    n=p[:3];o=-p[3]*n
    for k,axis in enumerate(np.eye(3)):
        u=axis-np.dot(axis,n)*n
        if np.linalg.norm(u)>=1e-6:break
    u=u/np.linalg.norm(u);v=np.cross(n,u);v=v/np.linalg.norm(v)
    b={'origin_m':o.tolist(),'u_axis':u.tolist(),'v_axis':v.tolist(),'normal':n.tolist(),'oriented_plane_n_d_m':p.tolist(),
       'reference_axis':('camera_X','camera_Y','camera_Z')[k],'camera_side_resolved':resolved,
       'normal_rule':'faces camera origin when plane does not contain camera; d>0. At d~0 use negative largest-absolute normal component and mark side unresolved.',
       'axis_rule':'project camera_X onto plane; if length<1e-6 try camera_Y then camera_Z; v=normal cross u; u cross v=normal',
       'projection_direction':'look along -normal from +normal side; horizontal +u, vertical +v; not gravity',
       'unit':'m','format':'ade71_local_review_plane_basis_v1'}
    _matrix(b)
    return b

def _matrix(basis):
    o=np.asarray(basis['origin_m'],dtype=np.float64)
    a=np.column_stack([basis[k] for k in ('u_axis','v_axis','normal')]).astype(np.float64)
    if o.shape!=(3,) or a.shape!=(3,3) or not np.isfinite(o).all() or not np.isfinite(a).all():raise ValueError('finite3D basis required')
    if not np.allclose(a.T@a,np.eye(3),atol=1e-10,rtol=0) or np.linalg.det(a)<1-1e-10:raise ValueError('orthonormal right-handed basis required')
    return o,a

def _xyz(points):
    p=np.asarray(points,dtype=np.float64)
    if p.ndim!=2 or p.shape[1]!=3 or not np.isfinite(p).all():raise ValueError('finite Nx3 coordinates required')
    return p

def to_plane(points,basis):
    p=_xyz(points);o,a=_matrix(basis)
    result=(p-o)@a;result.flags.writeable=False
    return result

def from_plane(points,basis):
    p=_xyz(points);o,a=_matrix(basis)
    return p@a.T+o

def painter_rows(coords,pixel_id,rows):
    c=_xyz(coords);ids=np.asarray(pixel_id);r=np.asarray(rows)
    if ids.shape!=(len(c),) or r.ndim!=1 or r.dtype!=np.int64 or np.any(r<0) or np.any(r>=len(c)):raise ValueError('matching IDs and valid int64 display rows required')
    ordered=r[np.lexsort((ids[r],c[r,2]))]
    ordered.flags.writeable=False
    return ordered

def save_review_arrays(path,**arrays):
    wanted={'points_m','pixel_id','pixel_vu','rgb_u8','color_candidate','plane_coordinates_m','display_full_rows','draw_order_full_rows'}
    if set(arrays)!=wanted:raise ValueError('exact local review arrays required')
    p=arrays['points_m'];n=len(p)
    specs={'points_m':((n,3),np.float32),'pixel_id':((n,),np.int64),'pixel_vu':((n,2),np.int64),
           'rgb_u8':((n,3),np.uint8),'color_candidate':((n,),np.bool_),'plane_coordinates_m':((n,3),np.float64)}
    for k,(shape,dtype) in specs.items():
        a=arrays[k]
        if not isinstance(a,np.ndarray) or a.shape!=shape or a.dtype!=dtype or not np.isfinite(a).all():raise ValueError('bad review array: '+k)
    if np.any(np.diff(arrays['pixel_id'])<=0) or np.any(arrays['pixel_id']<0):raise ValueError('full original IDs must be nonnegative, unique, ascending')
    rows=arrays['display_full_rows'];order=arrays['draw_order_full_rows']
    for a in (rows,order):
        if a.ndim!=1 or a.dtype!=np.int64 or np.any(a<0) or np.any(a>=n) or len(np.unique(a))!=len(a):raise ValueError('invalid display rows')
    if not np.array_equal(np.sort(rows),np.sort(order)):raise ValueError('2D draw order must be a permutation of common display rows')
    with path.open('xb') as f:np.savez_compressed(f,**arrays)
