"""Read-only mobile ZIP -> validated saved Depth; no RGB/IMU geometry approval."""
from dataclasses import dataclass
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
import tempfile
import zipfile

import numpy as np
from PIL import Image
from paths import ROOT, REPOSITORY, CODE, load_contract
from safe_zip import MobileInputError, ZipLimits, checked_parts, extract_checked, inspect_zip, require

# Reuse the existing mutually exclusive RGB-index selection and strict JSON helpers.
_spec=importlib.util.spec_from_file_location('mobile_index_compat',REPOSITORY/'tools/mobile_session_intake/check_mobile_session.py')
compat=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(compat)
NOTICE='저장된 Depth 기반 검토 화면입니다. RGB 정렬·IMU 자세·물리 정확도는 미검증 상태입니다.'
sys.path.insert(0,str(CODE/'src'))


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def reference(root, name):
    parts=checked_parts(name)
    candidate=root.joinpath(*parts)
    require(candidate.resolve().is_relative_to(root.resolve()),'INVALID_SESSION','세션 밖 파일 참조입니다.')
    compat.require_unlinked(candidate)
    require(candidate.is_file(),'INVALID_SESSION',f'필수 파일이 없습니다: {name}')
    return candidate


def check_hash(path, expected):
    require(isinstance(expected,str) and len(expected)==64 and digest(path)==expected,
            'HASH_MISMATCH', f'파일 SHA-256이 다릅니다: {path.name}')


def inspect_npz(path, metadata, limits):
    """Check nested ZIP and NPY headers BEFORE numpy can allocate array buffers."""
    shape=(metadata['depth']['height'],metadata['depth']['width'])
    require(all(type(v) is int and v>0 for v in shape) and math.prod(shape)<=limits.max_pixels,
            'LIMIT_EXCEEDED','Depth 픽셀 수 제한을 초과했습니다.')
    storage=metadata['storage']
    expected={'depth_m.npy':np.dtype('float32'),'valid_mask.npy':np.dtype('bool')}
    if storage['target_mask_key'] is not None:expected['target_mask.npy']=np.dtype('bool')
    with zipfile.ZipFile(path) as z:
        members=inspect_zip(z,limits)
        require({i.filename for i in members}==set(expected),'INVALID_ARRAY','NPZ 배열 이름이 다릅니다.')
        for info in members:
            with z.open(info) as stream:
                version=np.lib.format.read_magic(stream)
                require(version in ((1,0),(2,0)),'INVALID_ARRAY','미지원 NPY 헤더입니다.')
                read_header=(np.lib.format.read_array_header_1_0 if version==(1,0)
                             else np.lib.format.read_array_header_2_0)
                actual,fortran,dtype=read_header(stream,max_header_size=10000)
                require(not dtype.hasobject and dtype==expected[info.filename] and actual==shape,
                        'INVALID_ARRAY','NPZ 배열 shape/dtype 또는 객체 배열이 잘못됐습니다.')
                require(math.prod(actual)*dtype.itemsize+stream.tell()==info.file_size,
                        'INVALID_ARRAY','NPY 헤더와 실제 바이트 크기가 다릅니다.')


@dataclass
class LoadedMobileSession:
    owner: object
    session_dir: Path
    session_id: str
    frames: tuple
    report: dict

    @property
    def frame_ids(self):return [f.metadata['frame_id'] for f in self.frames]

    def select(self,index,display_limit=50000):
        require(type(index) is int and 0<=index<len(self.frames),'FRAME_SELECTION','프레임을 선택하세요.')
        require(type(display_limit) is int and display_limit>0,'FRAME_SELECTION','표시 점 수는 양수여야 합니다.')
        from viewer_data import FrameView
        frame=self.frames[index]
        points=load_contract().point_cloud_camera(frame)
        points.flags.writeable=False
        rows=np.linspace(0,len(points)-1,min(len(points),display_limit),dtype=np.int64)
        display=points[rows].copy();display.flags.writeable=False
        return FrameView(frame,points,display)

    def file_inventory(self):
        return {p.relative_to(self.session_dir).as_posix():digest(p)
                for p in sorted(self.session_dir.rglob('*')) if p.is_file()}

    def close(self):
        self.frames=()
        self.owner.cleanup()


def validate_session(root,limits,progress):
    contract=load_contract()
    s=compat.read_json(reference(root,'session.json'))
    require(type(s) is dict and s.get('manifest_version')=='1.0.0' and s.get('status')=='complete',
            'INVALID_SESSION','저장 완료된 1.0.0 모바일 세션이 필요합니다.')
    sid=s.get('session_id')
    require(isinstance(sid,str) and bool(sid.strip()),'INVALID_SESSION','session_id가 없습니다.')
    checked_parts(sid)
    source=s.get('sources',{})
    rgb_source=source.get('rgb')
    require(source.get('depth')=='intel_realsense_d405' and source.get('imu')=='android_phone_sensors'
            and rgb_source in ('intel_realsense_d405_color','android_phone_back_camera'),
            'INVALID_SESSION','지원하지 않는 모바일 센서 출처입니다.')
    files=s.get('files')
    require(type(files) is dict,'INVALID_SESSION','session.files 객체가 필요합니다.')
    selection={'candidate_keys':[key for key in compat.RGB_INDEX_NAMES if key in files],
               'candidate_entries':[{'name':p.name} for p in root.iterdir()
                                    if p.name.casefold() in compat.RGB_INDEX_NAMES.values()]}
    # Explicit D405 profile alias in this local selector argument only; original JSON is untouched.
    selector_files=dict(files)
    rgb_key='rgb_images' if rgb_source=='intel_realsense_d405_color' else 'phone_rgb_images'
    require(rgb_key in selector_files and (rgb_key=='phone_rgb_images' or 'phone_rgb_images' not in selector_files),
            'INVALID_SESSION','RGB 폴더 선언이 센서 형식과 다릅니다.')
    if rgb_key=='rgb_images':selector_files['phone_rgb_images']=selector_files.pop('rgb_images')
    rgb_index=compat.select_rgb_index(root,selector_files,selection)
    entries=list(compat.rows(reference(root,files['depth_index'])))
    require(bool(entries),'INVALID_SESSION','Depth 프레임이 없습니다.')
    require(len(entries)<=limits.max_frames,'LIMIT_EXCEEDED','프레임 수 제한 초과입니다.')
    frames=[];seen=set();paths=set();pixels=0;raw_counts={}
    for index,entry in enumerate(entries):
        require(type(entry) is dict and set(entry)=={'frame_id','metadata_path'},'INVALID_SESSION','프레임 색인이 잘못됐습니다.')
        fid=entry['frame_id'];require(isinstance(fid,str) and fid not in seen,'INVALID_SESSION','중복/잘못된 frame_id입니다.')
        seen.add(fid)
        mp=reference(root,entry['metadata_path'])
        require(mp not in paths,'INVALID_SESSION','중복 metadata 참조입니다.');paths.add(mp)
        m=compat.read_json(mp);contract.validate_json(m,'frame')
        require(m['session_id']==sid and m['frame_id']==fid and m['source_path']=='mobile_device',
                'INVALID_SESSION','세션/프레임 ID가 색인과 다릅니다.')
        require(m['depth']['unit']=='m' and m['depth']['semantics']=='optical_axis_z',
                'INVALID_ARRAY','m 단위 Z Depth만 지원합니다.')
        arrays=reference(mp.parent,m['storage']['file']);check_hash(arrays,m['storage']['sha256'])
        inspect_npz(arrays,m,limits)
        pixels+=m['depth']['width']*m['depth']['height']
        require(pixels<=limits.max_total_pixels,'LIMIT_EXCEEDED','세션 총 픽셀 수 제한 초과입니다.')
        raw=reference(root,m['provenance']['raw_file']);check_hash(raw,m['provenance']['raw_sha256'])
        require(m['provenance']['raw_unit']=='Z16' and raw.stat().st_size>=m['depth']['width']*m['depth']['height']*2,
                'INVALID_ARRAY','Z16 원본 크기/단위가 잘못됐습니다.')
        evidence=mp.parent/'raw_capture.json'
        if evidence.exists():
            r=compat.read_json(evidence)
            require(r['session_id']==sid and r['frame_id']==fid and r['paths_relative_to']=='session_root',
                    'INVALID_SESSION','raw_capture ID/경로 기준이 다릅니다.')
            require(reference(root,r['metadata_file'])==mp and reference(root,r['raw_file'])==raw,
                    'INVALID_SESSION','raw_capture 파일 연결이 다릅니다.')
            check_hash(mp,r['metadata_sha256']);check_hash(raw,r['raw_sha256'])
            require(r['raw_data_size_bytes']==raw.stat().st_size and r['raw_bytes_per_pixel']==2
                    and r['raw_width']==m['depth']['width'] and r['raw_height']==m['depth']['height']
                    and type(r['raw_stride_bytes']) is int and r['raw_stride_bytes']>=r['raw_width']*2
                    and r['raw_stride_bytes']*r['raw_height']==raw.stat().st_size,
                    'INVALID_ARRAY','raw_capture 크기/stride가 다릅니다.')
        frame=contract.load_frame(mp)
        for a in (frame.depth_m,frame.valid_mask,frame.target_mask):
            if a is not None:a.flags.writeable=False
        frames.append(frame)
        # Observation of the saved convention; never remove 65535 or claim its physical meaning.
        raw_counts[fid]=int(np.count_nonzero(np.frombuffer(raw.read_bytes(),dtype='<u2')==65535))
        progress(f'Depth 검사 {index+1}/{len(entries)}: {fid}')
    rgb_rows=list(compat.rows(rgb_index));warnings=[];image_paths=set()
    for row in rgb_rows:
        require(row['session_id']==sid and row['frame_id'] in seen,'INVALID_SESSION','RGB ID 연결이 잘못됐습니다.')
        image=reference(root,row['file']);check_hash(image,row['sha256'])
        require(image not in image_paths,'INVALID_SESSION','중복 RGB 파일 참조입니다.');image_paths.add(image)
        compat.stamp(row['time'])
        with Image.open(image) as im:
            require(im.format=='PNG' and im.width*im.height<=limits.max_pixels,
                    'LIMIT_EXCEEDED','PNG 형식/픽셀 한도 오류입니다.')
            require(im.size==(row['width'],row['height']) and row['encoding']=='RGB8'
                    and im.mode in ('RGB','RGBA'),'INVALID_SESSION','RGB 파일/인덱스 크기·형식이 다릅니다.')
            im.load()
            if im.mode!='RGB':warnings.append({'file':row['file'],'declared':'RGB8','decoded':im.mode,
                                               'common_contract_match':False})
    imu_count=0;sample_ids=set()
    sensors={'TYPE_ACCELEROMETER':('accel_m_s2',True),'TYPE_LINEAR_ACCELERATION':('accel_m_s2',False),
             'TYPE_GYROSCOPE':('gyro_rad_s',False),'TYPE_ROTATION_VECTOR':('orientation_xyzw',False)}
    for row in compat.rows(reference(root,files['imu_samples'])):
        sample=row['sample_id']
        require(row['session_id']==sid and row['schema_version']=='1.0.0' and isinstance(sample,str)
                and sample.startswith(sid+'_') and sample not in sample_ids,'INVALID_SESSION','IMU ID가 잘못됐습니다.')
        sample_ids.add(sample);compat.stamp(row['time'])
        require(row['sensor_type'] in sensors,'INVALID_SESSION','미지원 IMU 센서입니다.')
        field,gravity=sensors[row['sensor_type']]
        require(row['gravity_included'] is gravity,'INVALID_SESSION','IMU 중력 표기가 다릅니다.')
        for key in ('accel_m_s2','gyro_rad_s','orientation_xyzw'):
            if key==field:compat.vector(row[key],4 if key=='orientation_xyzw' else 3)
            else:require(row[key] is None,'INVALID_SESSION','IMU 센서와 벡터가 다릅니다.')
        imu_count+=1
    counts={'depth_frames':len(frames),rgb_key:len(rgb_rows),'imu_samples':imu_count}
    require(s.get('counts')==counts and all(type(v) is int and v>0 for v in s['counts'].values()),
            'INVALID_SESSION','세션 counts와 실제 파일/행 수가 다릅니다.')
    report={'scope':'saved_depth_single_camera_review','counts':counts,'rgb_index':selection,
            'rgb_format_warnings':warnings,'raw_65535_word_counts':raw_counts,
            'common_contract_fully_validated':False,'physical_accuracy_verified':False,
            'rgb_alignment_verified':False,'imu_pose_applied':False,'notice':NOTICE}
    return sid,tuple(frames),report


def load_mobile_zip(archive_path,cache_root,limits=None,progress=lambda message:None):
    limits=limits or ZipLimits();owner=None
    try:
        archive_path=Path(archive_path);compat.require_unlinked(archive_path)
        require(archive_path.is_file(),'INVALID_ZIP','ZIP 파일을 선택하세요.')
        require(archive_path.stat().st_size<=limits.max_archive_bytes,'LIMIT_EXCEEDED','ZIP 파일 크기 제한 초과입니다.')
        cache=Path(cache_root).absolute()
        require(not cache.resolve().is_relative_to(ROOT),'INVALID_SESSION','캐시는 프로그램 입력 폴더 밖으로 지정하세요.')
        cache.mkdir(parents=True,exist_ok=True);compat.require_unlinked(cache)
        owner=tempfile.TemporaryDirectory(prefix='mobile_pending_',dir=cache)
        work=Path(owner.name);snapshot=work/'input.zip'
        copied=0;h=hashlib.sha256()
        with archive_path.open('rb') as src,snapshot.open('xb') as dst:
            while chunk:=src.read(1024*1024):
                copied+=len(chunk)
                require(copied<=limits.max_archive_bytes,'LIMIT_EXCEEDED','ZIP 실제 수신 크기 제한 초과입니다.')
                h.update(chunk);dst.write(chunk)
        extracted=work/'extracted';extracted.mkdir()
        with zipfile.ZipFile(snapshot) as z:extract_checked(z,extracted,limits,progress)
        roots=list(extracted.rglob('session.json'))
        require(len(roots)==1,'INVALID_SESSION','session.json이 정확히 하나인 세션 ZIP이 필요합니다.')
        root=roots[0].parent
        require(len(root.relative_to(extracted).parts)<=1,'INVALID_SESSION','ZIP 루트 또는 단일 외피 폴더만 지원합니다.')
        require(all(p.is_relative_to(root) for p in extracted.rglob('*') if p.is_file()),
                'INVALID_SESSION','세션 밖의 추가 파일이 있습니다.')
        sid,frames,report=validate_session(root,limits,progress)
        require(digest(archive_path)==h.hexdigest(),'INPUT_CHANGED','검사 중 원본 ZIP이 변경됐습니다.')
        report.update(archive_path=str(archive_path.resolve()),zip_size_bytes=copied,zip_sha256=h.hexdigest(),
                      file_sha256={p.relative_to(root).as_posix():digest(p) for p in sorted(root.rglob('*')) if p.is_file()})
        session=LoadedMobileSession(owner,root,sid,frames,report)
        owner=None
        return session
    except MobileInputError:raise
    except (zipfile.BadZipFile,EOFError,RuntimeError,NotImplementedError) as exc:
        raise MobileInputError('INVALID_ZIP',f'ZIP 손상 또는 지원되지 않는 입력입니다: {exc}') from exc
    except (OSError,ValueError,KeyError,TypeError,OverflowError,IndexError) as exc:
        raise MobileInputError('INVALID_SESSION',f'파일/세션 검사 실패: {exc}') from exc
    finally:
        if owner is not None:owner.cleanup()
