"""Create a new clearly synthetic intake at an explicit output path; never overwrite."""
import argparse
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from depth_preflight import digest, write_json_new


def create_synthetic(base):
    base.mkdir(parents=True, exist_ok=False)
    raw = np.array([[[1000, 1000], [1000, 0]]], dtype=np.uint16)
    with (base / 'source.npz').open('xb') as stream:
        np.savez_compressed(stream, depth_raw=raw)
    m = json.loads((ROOT / 'examples/synthetic/frame_000001/metadata.json').read_text(encoding='utf-8'))
    m['session_id'] = 'ade71_synthetic_file_boundary'
    m['provenance']['raw_file'] = 'raw/source.npz'
    m['provenance']['raw_sha256'] = digest(base / 'source.npz')
    write_json_new(base / 'basis.json', {
        'basis_format': 'ade71-local-intake-v1', 'notice': 'SYNTHETIC ONLY; local intake sidecar, not core schema',
        'source': {'file': 'source.npz', 'sha256': digest(base / 'source.npz'),
                   'key': 'depth_raw', 'dtype': 'uint16', 'shape': [1, 2, 2]},
        'conversion': {'scale_to_m': .001, 'semantics': 'optical_axis_z', 'invalid_values': [0],
                       'raw_65535_policy': 'unconfirmed', 'raw_65535_evidence': None},
        'evidence_files': {}, 'real_geometry': None,
        'frames': [{'source_frame_index': 0, 'metadata': m, 'target': None}]})
    write_json_new(base / 'expected_points.json', [[0, 0, 1], [.01, 0, 1], [0, .01, 1]])
    return base


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True,
                        help='new synthetic intake directory (must not already exist)')
    base = create_synthetic(parser.parse_args().output)
    print(base)
