"""Synthetic fixture builder, not volume computation; dimensions define the oracle."""
from pathlib import Path
import copy,json
import numpy as np

def cuboid(contract):
    m=json.loads((Path(contract.ROOT)/'examples/synthetic/frame_000001/metadata.json').read_text(encoding='utf-8'))
    m=copy.deepcopy(m)
    m.update(frame_id='synthetic_volume_cuboid',session_id='synthetic_volume_dev')
    m['provenance'].update(raw_unit=None,raw_scale_to_m=None)
    m['provenance']['synthetic_config']='known cuboid 0.02m x 0.03m x 0.01m; analytic cell-center top samples'
    m['depth'].update(height=3,width=2)
    m['intrinsics'].update(height=3,width=2,fx=100.,fy=100.,cx=-.5,cy=2.5)
    m['storage'].update(target_mask_key='target_mask',sha256='0'*64)
    m['target_mask_info']={'source':'synthetic known full cuboid top','version':'dev1'}
    m['support_plane']={'frame':'camera','normal':[0.,0.,-1.],'offset_m':1.01,'method':'synthetic known plane','evidence':'analytic cuboid dimensions; not SDK evidence'}
    m['volume_request']={'method':'height_integration','assumptions_confirmed':True,
        'assumption_evidence':'synthetic known footprint; full top observed; solid columns, no cavities/overhangs',
        'plane_basis':{'origin_m':[0.,0.,1.01],'u_axis':[1.,0.,0.],'v_axis':[0.,-1.,0.]},
        'footprint_polygon_uv_m':[[0.,0.],[.02,0.],[.02,.03],[0.,.03]],'grid_pitch_m':.01}
    depth=np.ones((3,2),dtype=np.float32); mask=np.ones((3,2),dtype=bool)
    frame=contract.FramePacket(m,depth,mask,mask.copy())
    # Analytic physical cell centers, not point count or production integration output.
    points=np.array([[.005,.0-.025,1.],[.015,-.025,1.],[.005,-.015,1.],[.015,-.015,1.],[.005,-.005,1.],[.015,-.005,1.]],dtype=np.float64)
    pixels=np.array([[0,0],[0,1],[1,0],[1,1],[2,0],[2,1]],dtype=np.int64)
    assumptions={'known_footprint':True,'entire_top_observed':True,'solid_single_valued_columns':True,'no_cavities_or_overhangs':True}
    return frame,points,pixels,assumptions
