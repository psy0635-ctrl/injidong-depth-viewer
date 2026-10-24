"""Metric camera-coordinate planes. No registration or core metadata mutation."""
import numpy as np

def normalize_plane(plane):
    a=np.asarray(plane,dtype=np.float64)
    if a.shape!=(4,) or not np.isfinite(a).all():raise ValueError('finite plane [nx,ny,nz,d] required')
    length=np.linalg.norm(a[:3])
    if length<=1e-15:raise ValueError('zero plane normal')
    a=a/length
    if a[np.argmax(np.abs(a[:3]))]>0:a=-a
    return a

def _points(points):
    a=np.asarray(points,dtype=np.float64)
    if a.ndim!=2 or a.shape[1]!=3 or len(a)<6 or not np.isfinite(a).all():
        raise ValueError('at least6 finite Nx3 points required')
    s=np.linalg.svd(a-a.mean(axis=0),compute_uv=False)
    if s[0]<1e-9 or s[1]/s[0]<1e-6:raise ValueError('coincident or collinear points')
    return a

def _tls(points):
    a=_points(points);center=a.mean(axis=0)
    _,_,vh=np.linalg.svd(a-center,full_matrices=False)
    n=vh[-1]
    return normalize_plane(np.r_[n,-n@center])

def fit_robust(points,*,threshold_m,seed,trials,max_scoring_points=6000):
    a=_points(points)
    if not np.isfinite(threshold_m) or threshold_m<=0 or type(trials) is not int or trials<1:
        raise ValueError('positive finite threshold and trial count required')
    if type(max_scoring_points) is not int or max_scoring_points<6:raise ValueError('scoring cap must be at least6')
    sampled=a[np.linspace(0,len(a)-1,min(len(a),max_scoring_points),dtype=np.int64)]
    rng=np.random.default_rng(seed);best=None;best_key=(-1,-np.inf)
    for _ in range(trials):
        p=sampled[rng.choice(len(sampled),3,replace=False)]
        n=np.cross(p[1]-p[0],p[2]-p[0]);length=np.linalg.norm(n)
        if length<1e-12:continue
        n=n/length;plane=normalize_plane(np.r_[n,-n@p[0]])
        residual=np.abs(sampled@plane[:3]+plane[3]);inside=residual<=threshold_m
        count=int(inside.sum())
        key=(count,-float(np.median(residual[inside])) if count else -np.inf)
        if key>best_key:best_key=key;best=plane
    if best is None:raise ValueError('no nondegenerate consensus plane')
    for _ in range(8):
        inside=np.abs(a@best[:3]+best[3])<=threshold_m
        if inside.sum()<max(6,len(a)*.5):raise ValueError('no majority plane in selected candidates')
        refined=_tls(a[inside])
        new_inside=np.abs(a@refined[:3]+refined[3])<=threshold_m
        best=refined
        if np.array_equal(inside,new_inside):break
    residual=a@best[:3]+best[3]
    inside=np.abs(residual)<=threshold_m
    return {'plane':best.tolist(),'fit_point_count':len(a),'inlier_count':int(inside.sum()),
            'inlier_ratio':float(inside.mean()),'threshold_m':float(threshold_m),'seed':int(seed),
            'trials':trials,'RANSAC_scoring_count':len(sampled),'refinement':'orthogonal TLS on training consensus only',
            'all_fit_residuals':residual_stats(residual,threshold_m),
            'inlier_residuals':residual_stats(residual[inside],threshold_m)}

def compare_planes(first,second):
    a=normalize_plane(first);b=normalize_plane(second)
    if a[:3]@b[:3]<0:b=-b
    cosine=float(np.clip(a[:3]@b[:3],-1,1))
    return {'normal_angle_deg':float(np.rad2deg(np.arccos(cosine))),
            'd_delta_m':float(b[3]-a[3]),'first_normalized':a.tolist(),'second_sign_aligned':b.tolist(),
            'd_delta_interpretation':'difference of normalized camera-origin plane coefficients; not uniform floor height when normals differ'}

def ray_intersections(plane,rays):
    p=normalize_plane(plane);r=np.asarray(rays,dtype=np.float64)
    if r.ndim!=2 or r.shape[1]!=3 or not len(r) or not np.isfinite(r).all():raise ValueError('finite Nx3 rays required')
    denominator=r@p[:3]
    if np.any(np.abs(denominator)<1e-12):raise ValueError('ray parallel to plane')
    return r*(-p[3]/denominator)[:,None]

def residual_stats(residuals,threshold_m):
    r=np.asarray(residuals,dtype=np.float64)
    if r.ndim!=1 or not len(r) or not np.isfinite(r).all() or not np.isfinite(threshold_m) or threshold_m<=0:
        raise ValueError('nonempty finite metric residuals and positive threshold required')
    absolute=np.abs(r);inside=absolute<=threshold_m
    return {'count':len(r),'signed_median_m':float(np.median(r)),'signed_mean_m':float(np.mean(r)),
            'signed_q05_m':float(np.quantile(r,.05)),'signed_q95_m':float(np.quantile(r,.95)),
            'absolute_median_m':float(np.median(absolute)),'rmse_m':float(np.sqrt(np.mean(r*r))),
            'absolute_q90_m':float(np.quantile(absolute,.9)),'absolute_q95_m':float(np.quantile(absolute,.95)),
            'absolute_q99_m':float(np.quantile(absolute,.99)),
            'inlier_count':int(inside.sum()),'inlier_ratio':float(inside.mean()),'threshold_m':float(threshold_m)}
