"""Generate a small synthetic mobile ZIP; no device/physics/alignment approval."""
import argparse, copy, hashlib, io, json, zipfile
from pathlib import Path
import numpy as np
from PIL import Image

SID = 'synthetic_mobile_demo'


def create_archive(destination):
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError(destination)
    template = Path(__file__).resolve().parents[2] / 'examples/synthetic/frame_000001/metadata.json'
    base = json.loads(template.read_text(encoding='utf-8'))
    members, index, images = {}, [], []
    h, w = 24, 32
    v, u = np.indices((h, w))
    for number in (1, 2):
        fid = f'synthetic_{number:04d}'
        raw = (2000 + u + v + number).astype('<u2')
        valid = np.ones((h, w), dtype=bool)
        valid[:, 0] = False
        raw[:, 0] = 0
        depth = (raw.astype(np.float64) * .0001).astype(np.float32)
        blob = io.BytesIO()
        np.savez(blob, depth_m=depth, valid_mask=valid)
        arrays = blob.getvalue()
        m = copy.deepcopy(base)
        m.update(frame_id=fid, session_id=SID, source_path='mobile_device', capture_source='synthetic')
        m['provenance'].update(kind='synthetic', raw_file=f'raw/{fid}.bin', raw_sha256=hashlib.sha256(raw.tobytes()).hexdigest(), raw_unit='Z16', raw_scale_to_m=.0001, synthetic_seed=20261024, synthetic_config='small synthetic plane; no real-device accuracy')
        m['storage'].update(file='arrays.npz', sha256=hashlib.sha256(arrays).hexdigest(), depth_key='depth_m', valid_mask_key='valid_mask', target_mask_key=None)
        m['depth'].update(height=h, width=w, unit='m', dtype='float32', semantics='optical_axis_z')
        m['intrinsics'].update(height=h, width=w, fx=100., fy=100., cx=15.5, cy=11.5, model='rectified_pinhole', calibration_id='synthetic_demo_only')
        stamp = {'ns':str(1_000_000_000+number*250_000_000), 'clock_domain':'synthetic_clock', 'origin':'synthetic'}
        m['capture_time'] = stamp
        m['host_receive_time'] = {'ns':None, 'clock_domain':None, 'origin':None}
        m['pose'] = m['imu'] = m['target_mask_info'] = m['support_plane'] = m['volume_request'] = None
        m['sync'] = {'status':'unverified','offset_ns':None,'uncertainty_ns':None,'tolerance_ns':None,'evidence':None}
        rgb = np.stack(((u*7)%256, (v*10)%256, ((u+v)*5)%256),axis=2).astype(np.uint8)
        png = io.BytesIO(); Image.fromarray(rgb).save(png,format='PNG')
        image_bytes = png.getvalue()
        image_file = f'rgb/{fid}.png'
        images.append({'frame_id':fid,'session_id':SID,'file':image_file,'sha256':hashlib.sha256(image_bytes).hexdigest(),'width':w,'height':h,'encoding':'RGB8','image_kind':'original_rgb','time':stamp,'pair_status':'unverified','pair_evidence':None,'aligned_to_depth':False,'alignment_method':None,'calibration_id':None,'provenance_kind':'synthetic'})
        members[f'{fid}/metadata.json'] = json.dumps(m,allow_nan=False).encode()
        members[f'{fid}/arrays.npz'] = arrays
        members[f'raw/{fid}.bin'] = raw.tobytes()
        members[image_file] = image_bytes
        index.append({'frame_id':fid,'metadata_path':f'{fid}/metadata.json'})
    imu = {'schema_version':'1.0.0','session_id':SID,'sample_id':SID+'_imu_1','sensor_type':'TYPE_ACCELEROMETER','gravity_included':True,'accel_m_s2':[0.,9.8,0.],'gyro_rad_s':None,'orientation_xyzw':None,'time':stamp}
    session = {'manifest_version':'1.0.0','session_id':SID,'status':'complete','sources':{'rgb':'intel_realsense_d405_color','depth':'intel_realsense_d405','imu':'android_phone_sensors'},'counts':{'depth_frames':2,'rgb_images':2,'imu_samples':1},'files':{'depth_index':'frames.jsonl','images_index':'images.jsonl','rgb_images':'rgb/','imu_samples':'imu.jsonl','depth_arrays':'<frame_id>/arrays.npz','raw_depth':'raw/'},'rgb_depth_alignment':{'status':'unverified','aligned_to_depth':False,'evidence':None},'provenance_kind':'synthetic','notice':'Synthetic file/GUI test only; no physical or alignment validation'}
    members['session.json'] = json.dumps(session).encode()
    members['frames.jsonl'] = ''.join(json.dumps(r)+'\n' for r in index).encode()
    members['images.jsonl'] = ''.join(json.dumps(r)+'\n' for r in images).encode()
    members['imu.jsonl'] = (json.dumps(imu)+'\n').encode()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination,'x',zipfile.ZIP_DEFLATED) as z:
        for name,data in members.items():
            info=zipfile.ZipInfo(SID+'/'+name,date_time=(2026,10,24,0,0,0))
            info.compress_type=zipfile.ZIP_DEFLATED
            z.writestr(info,data)
    return {'session_id':SID,'zip_size_bytes':destination.stat().st_size,'zip_sha256':hashlib.sha256(destination.read_bytes()).hexdigest(),'synthetic':True}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    print(json.dumps(create_archive(args.output)))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
