"""기본 합성 원본을 보존하면서 ADE-95 탐색용 3프레임 세션을 생성한다."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from contract import iter_frames, normalize_depth


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'examples/viewer_multiframe', help='새 세션 폴더; 기존 경로 거부')
    args = parser.parse_args()
    destination = args.output.resolve()
    if destination.exists() or destination.is_relative_to(ROOT / 'examples/synthetic'):
        parser.error('output must be new and outside original synthetic session')
    template = next(iter_frames(ROOT / 'examples/synthetic')).metadata
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.mkdir()
    manifest = []
    for index, raw_values in enumerate(([[1000,1000],[1000,0]],
                                        [[1500,2000],[2500,0]],
                                        [[2000,1000],[3000,0]]), 1):
        folder = destination / f'frame_{index:06d}'
        folder.mkdir()
        raw = np.array(raw_values, dtype=np.uint16)
        depth, mask = normalize_depth(raw, .001)
        with (folder / 'arrays.npz').open('xb') as stream:
            np.savez(stream, depth_m=depth, valid_mask=mask)
        metadata = copy.deepcopy(template)
        metadata.update(session_id='ade95_synthetic_multiframe', frame_id=f'ade95_synthetic_{index:06d}')
        metadata['storage']['sha256'] = hashlib.sha256((folder / 'arrays.npz').read_bytes()).hexdigest()
        metadata['capture_time']['ns'] = str(index * 1_000_000_000)
        metadata['provenance']['synthetic_seed'] = 95
        metadata['provenance']['synthetic_config'] = f'ADE-95 deterministic frame {index}; raw_mm={raw_values}; scale_to_m=0.001; no target or support plane'
        with (folder / 'metadata.json').open('x', encoding='utf-8') as stream:
            json.dump(metadata, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write('\n')
        manifest.append({'frame_id':metadata['frame_id'], 'metadata_path':f'{folder.name}/metadata.json'})
    with (destination / 'frames.jsonl').open('x', encoding='utf-8') as stream:
        for entry in manifest:
            stream.write(json.dumps(entry, allow_nan=False)+'\n')
    frames = list(iter_frames(destination))
    print(f'Generated {len(frames)} SYNTHETIC frames: {destination}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
