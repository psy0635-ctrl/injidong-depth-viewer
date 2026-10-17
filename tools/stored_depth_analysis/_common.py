"""Shared read-only input, pinned baseline and exclusive output boundaries."""
from pathlib import Path, PureWindowsPath
import hashlib, importlib.util, json, os, sys
import numpy as np

CODE_ROOT = Path(__file__).resolve().parents[2]
BASELINE_HASHES = CODE_ROOT / 'tools/mobile_session_intake/baseline_hashes.json'
FLAGS = dict.fromkeys(('geometry_verified','processing_ready','viewer_launched',
    'sdk_values_independently_verified','common_framepacket_fully_validated'), False)

class ComparisonFailure(ValueError):
    def __init__(self, message, details=None):
        self.details = details or {}
        super().__init__(message)

def require(condition, message, details=None):
    if not condition:
        raise ComparisonFailure(message, details)

def file_record(path):
    data = Path(path).read_bytes()
    return {'size_bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}

def write_json_new(path, value):
    with Path(path).open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')

class TrackedReads:
    def __init__(self):
        self.before = {}
    def read(self, path):
        path = Path(path).resolve()
        data = path.read_bytes()
        value = {'size_bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        require(str(path) not in self.before or self.before[str(path)] == value,
                'input changed during read: ' + str(path))
        self.before[str(path)] = value
        return data
    def json(self, path):
        return json.loads(self.read(path).decode('utf-8'))
    def finish(self):
        after = {p: file_record(p) for p in self.before}
        require(after == self.before, 'input/baseline/code preservation mismatch')
        return {'files_before': self.before, 'files_after': after,
                'read_files_preserved': True}

def reserve_output(output, protected):
    raw = Path(output).absolute()
    require(not os.path.lexists(raw), 'output already exists (including link entry)')
    resolved = raw.resolve()
    for item in [CODE_ROOT, *protected]:
        item = Path(item).resolve()
        require(not resolved.is_relative_to(item) and not item.is_relative_to(resolved),
                'output and input/baseline/code overlap: ' + str(item))
    resolved.mkdir(parents=True, exist_ok=False)
    return resolved

def relative_file(root, name):
    require(isinstance(name, str) and name and '\\' not in name and ':' not in name,
            'nonempty relative POSIX path required')
    path, win = Path(name), PureWindowsPath(name)
    require(not path.is_absolute() and not win.drive and not win.root and '..' not in path.parts,
            'relative path without parent traversal required')
    root = Path(root).resolve()
    value = (root / path).resolve()
    require(value.is_relative_to(root), 'resolved input path escapes root')
    return value

def select_metadata(session, frame_id, tracked):
    entries = [json.loads(line) for line in tracked.read(session/'frames.jsonl').decode('utf-8').splitlines() if line.strip()]
    require(all(isinstance(e, dict) and set(e)=={'frame_id','metadata_path'} and
                isinstance(e['frame_id'],str) and e['frame_id'] for e in entries), 'invalid manifest fields')
    require(len({e['frame_id'] for e in entries})==len(entries), 'duplicate manifest frame IDs')
    matches = [e for e in entries if e['frame_id']==frame_id]
    require(len(matches)==1, 'frame_id absent or not unique in manifest')
    path = relative_file(session, matches[0]['metadata_path'])
    metadata = tracked.json(path)
    require(metadata['frame_id']==frame_id, 'manifest and metadata frame_id disagree')
    return path, matches[0], metadata

def load_baseline(root, tracked=None):
    tracked = tracked or TrackedReads()
    root = Path(root).resolve()
    expected = tracked.json(BASELINE_HASHES)
    require(set(expected)=={'src/contract.py','src/session_boundary.py','schemas/frame.schema.json'},
            'unexpected pinned baseline manifest structure')
    for relative, sha in expected.items():
        data = tracked.read(root/relative)
        require(hashlib.sha256(data).hexdigest()==sha, 'pinned ADE-71 baseline mismatch: '+relative)
    for name in ('session_boundary','contract'):
        source = root/'src'/(name+'.py')
        existing = sys.modules.get(name)
        if existing is not None:
            require(Path(existing.__file__).resolve()==source, 'conflicting module: '+name)
            continue
        spec = importlib.util.spec_from_file_location(name, source)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            exec(compile(tracked.read(source),str(source),'exec'),module.__dict__)
        except Exception:
            del sys.modules[name]
            raise
    contract = sys.modules['contract']
    require(Path(contract.ROOT).resolve()==root, 'wrong contract ROOT')
    return contract

def read_depth(metadata_path, metadata, tracked):
    path = relative_file(metadata_path.parent, metadata['storage']['file'])
    tracked.read(path)
    require(file_record(path)['sha256']==metadata['storage']['sha256'], 'depth NPZ hash mismatch')
    with np.load(path, allow_pickle=False) as arrays:
        keys = {metadata['storage']['depth_key'], metadata['storage']['valid_mask_key']}
        if metadata['storage']['target_mask_key']:
            keys.add(metadata['storage']['target_mask_key'])
        require(set(arrays.files)==keys, 'unexpected depth NPZ keys')
        depth = arrays[metadata['storage']['depth_key']]
        valid = arrays[metadata['storage']['valid_mask_key']]
    shape = (metadata['depth']['height'],metadata['depth']['width'])
    require(depth.dtype==np.float32 and valid.dtype==np.bool_ and depth.shape==valid.shape==shape,
            'depth/mask dtype or shape mismatch')
    require(metadata['depth']['unit']=='m' and metadata['depth']['semantics']=='optical_axis_z',
            'only stored optical-axis depth in m is supported')
    return depth, valid

def raw_source(session, metadata_path, metadata, tracked):
    side = tracked.json(metadata_path.parent/'raw_capture.json')
    require(side['frame_id']==metadata['frame_id'] and side['session_id']==metadata['session_id'], 'raw frame identity mismatch')
    require(side['paths_relative_to']=='session_root', 'unknown raw path basis')
    require(relative_file(session,side['metadata_file'])==metadata_path, 'raw sidecar metadata path mismatch')
    require(file_record(metadata_path)['sha256']==side['metadata_sha256'], 'raw sidecar metadata hash mismatch')
    path = relative_file(session,side['raw_file'])
    require(path==relative_file(session,metadata['provenance']['raw_file']), 'raw path mismatch')
    data = tracked.read(path)
    require(hashlib.sha256(data).hexdigest()==side['raw_sha256']==metadata['provenance']['raw_sha256'], 'raw hash mismatch')
    h,w = metadata['depth']['height'],metadata['depth']['width']
    stride = side['raw_stride_bytes']
    require(side['raw_width']==w and side['raw_height']==h and side['raw_bytes_per_pixel']==2 and
            side['raw_byte_order']=='little_endian' and type(stride) is int and stride>=w*2 and stride%2==0,
            'unsupported raw layout')
    require(len(data)==side['raw_data_size_bytes'] and len(data)>=(h-1)*stride+w*2, 'raw byte size mismatch')
    raw = np.ndarray((h,w),dtype='<u2',buffer=data,strides=(stride,2))
    return raw, side, path
