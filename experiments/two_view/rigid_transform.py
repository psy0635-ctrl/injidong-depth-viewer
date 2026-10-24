"""Local exploratory rigid transforms, metres. No robot pose or core metadata is produced."""
import json
import numpy as np

def validate_transform(value):
    t=np.asarray(value,dtype=np.float64)
    if t.shape!=(4,4) or not np.isfinite(t).all():raise ValueError('finite 4x4 transform required')
    if not np.allclose(t[3],[0,0,0,1],rtol=0,atol=1e-12):raise ValueError('invalid homogeneous last row')
    r=t[:3,:3]
    if not np.allclose(r.T@r,np.eye(3),rtol=0,atol=1e-8) or not np.isclose(np.linalg.det(r),1,rtol=0,atol=1e-8):raise ValueError('proper orthonormal rotation required')
    return t

def apply_transform(points,value):
    t=validate_transform(value);p=np.asarray(points)
    if p.ndim!=2 or p.shape[1]!=3 or p.dtype.kind not in 'fi' or not np.isfinite(p).all():raise ValueError('finite numeric Nx3 points required')
    return np.asarray(p,dtype=np.float64)@t[:3,:3].T+t[:3,3]

def inverse_transform(value):
    t=validate_transform(value);v=np.eye(4);v[:3,:3]=t[:3,:3].T;v[:3,3]=-v[:3,:3]@t[:3,3]
    return validate_transform(v)

def load_transform(path):
    def pairs(items):
        d={}
        for k,v in items:
            if k in d:raise ValueError('duplicate transform JSON key')
            d[k]=v
        return d
    def bad(v):raise ValueError('nonfinite JSON token '+v)
    with open(path,encoding='utf-8') as f:d=json.load(f,object_pairs_hook=pairs,parse_constant=bad)
    if d['format']!='injidong_local_two_view_exploration' or d['format_version']!='1.0.0' or d['schema_version']!='1.0.0':raise ValueError('unsupported local format')
    if d['direction']!='p_target = R @ p_source + t' or d['unit']!='m':raise ValueError('unsupported direction/unit')
    return d,validate_transform(d['matrix_source_to_target'])

def nearest(query,reference):
    q=np.asarray(query,dtype=float);r=np.asarray(reference,dtype=float)
    if q.ndim!=2 or r.ndim!=2 or q.shape[1]!=3 or r.shape[1]!=3 or not len(r) or not np.isfinite(q).all() or not np.isfinite(r).all():raise ValueError('finite Nx3 sets and nonempty reference required')
    ids=[];dist=[]
    for start in range(0,len(q),128):
        delta=q[start:start+128,None,:]-r[None,:,:]
        squared=np.einsum('ijk,ijk->ij',delta,delta)
        k=squared.argmin(axis=1);ids.append(k);dist.append(np.sqrt(squared[np.arange(len(k)),k]))
    return (np.concatenate(dist),np.concatenate(ids)) if ids else (np.empty(0),np.empty(0,dtype=np.int64))

def weighted_rigid(source,target,weights):
    x=np.asarray(source,dtype=float);y=np.asarray(target,dtype=float);w=np.asarray(weights,dtype=float)
    if x.shape!=y.shape or x.ndim!=2 or x.shape[1]!=3 or len(x)<3 or w.shape!=(len(x),) or not np.isfinite(x).all() or not np.isfinite(y).all() or not np.isfinite(w).all() or np.any(w<0) or w.sum()<=0:raise ValueError('invalid paired rigid fit')
    w=w/w.sum();xc=w@x;yc=w@y
    u,s,vt=np.linalg.svd(((x-xc)*w[:,None]).T@(y-yc))
    if s[1]<1e-15:raise ValueError('collinear/degenerate rigid fit')
    d=np.eye(3);d[2,2]=np.sign(np.linalg.det(vt.T@u.T));r=vt.T@d@u.T
    t=np.eye(4);t[:3,:3]=r;t[:3,3]=yc-r@xc
    return validate_transform(t)

def angle_rad(r):return float(np.arccos(np.clip((np.trace(r)-1)/2,-1,1)))

def axis_rotation(axis,angle):
    angle=float(angle)
    a=np.asarray(axis,dtype=float);a=a/np.linalg.norm(a);x,y,z=a
    k=np.array([[0,-z,y],[z,0,-x],[-y,x,0]])
    return np.eye(3)+np.sin(angle)*k+(1-np.cos(angle))*(k@k)

def align_normals(source,target):
    a=np.asarray(source,dtype=np.float64);b=np.asarray(target,dtype=np.float64)
    a=a/np.linalg.norm(a);b=b/np.linalg.norm(b)
    v=np.cross(a,b);s=np.linalg.norm(v);c=float(a@b)
    if s<1e-12:
        if c>0:return np.eye(3)
        raise ValueError('antiparallel normals need explicit axis')
    return axis_rotation(v/s,np.arctan2(s,c))

def icp(source_groups,target_groups,initial,threshold_m,max_iterations=40,trim_fraction=.85):
    t=validate_transform(initial).copy();history=[];previous=None;stable=0
    if not np.isfinite(threshold_m) or threshold_m<=0:raise ValueError('positive correspondence threshold required')
    for iteration in range(max_iterations):
        xs=[];ys=[];ws=[];counts={};all_dist=[]
        for name,x in source_groups.items():
            moved=apply_transform(x,t);d,j=nearest(moved,target_groups[name]);keep=d<=threshold_m
            if keep.sum()<10:raise ValueError('too few correspondences in '+name)
            keep&=d<=np.quantile(d[keep],trim_fraction)
            counts[name]=int(keep.sum());xs.append(moved[keep]);ys.append(target_groups[name][j[keep]]);ws.append(np.full(keep.sum(),1/keep.sum()));all_dist.extend(d[keep])
        delta=weighted_rigid(np.concatenate(xs),np.concatenate(ys),np.concatenate(ws));t=validate_transform(delta@t)
        rmse=float(np.sqrt(np.mean(np.square(all_dist))));step=float(np.linalg.norm(delta[:3,3]));ang=angle_rad(delta[:3,:3])
        history.append({'iteration':iteration+1,'pre_update_pair_rmse_m':rmse,'translation_step_m':step,'rotation_step_rad':ang,'retained_pairs':counts})
        stable=stable+1 if previous is not None and abs(previous-rmse)<1e-8 else 0;previous=rmse
        if (step<1e-6 and ang<1e-5) or stable>=3:return t,history,'increment_or_three_stable_rmse_steps'
    return t,history,'max_iterations'
