"""Reuse the repository's pinned baseline and exclusive-output boundaries."""
from pathlib import Path
import hashlib
import importlib.util
import sys

REPOSITORY = Path(__file__).resolve().parents[2]
COMMON_PATH = REPOSITORY / 'tools/stored_depth_analysis/_common.py'
NAME = '_stored_depth_boundary_for_synthetic_volume'
if NAME in sys.modules:
    common = sys.modules[NAME]
    if Path(common.__file__).resolve() != COMMON_PATH:
        raise RuntimeError('conflicting shared boundary module')
else:
    spec = importlib.util.spec_from_file_location(NAME, COMMON_PATH)
    common = importlib.util.module_from_spec(spec)
    sys.modules[NAME] = common
    try:
        exec(compile(COMMON_PATH.read_bytes(), str(COMMON_PATH), 'exec'), common.__dict__)
    except Exception:
        del sys.modules[NAME]
        raise

TrackedReads = common.TrackedReads
reserve_output = common.reserve_output
newjson = common.write_json_new
record = common.file_record
require = common.require
FLAGS = common.FLAGS

# Volume results and deterministic fixtures also read these two unchanged ADE-71 files.
# The three existing baseline pins remain in the shared baseline_hashes.json.
EXTRA_BASELINE_HASHES = {
    'schemas/processing.schema.json': 'b5090a9f3a2f294836ca0a318b24fdf4ba2c695045e3f5c531564f5b9bd9e4ae',
    'examples/synthetic/frame_000001/metadata.json': '806e0df67e2489612be6aabe9af80b3dc84ad08ff62b6804ec59d2ead0ee0bf7',
}

def load_contract(root, tracked=None):
    root = Path(root).resolve()
    tracked = tracked if tracked is not None else TrackedReads()
    tracked.read(COMMON_PATH)
    for relative, expected in EXTRA_BASELINE_HASHES.items():
        require(hashlib.sha256(tracked.read(root / relative)).hexdigest() == expected,
                'pinned synthetic-volume baseline mismatch: ' + relative)
    return common.load_baseline(root, tracked)

def import_paths():
    return {name: str(Path(sys.modules[name].__file__).resolve())
            for name in ('contract', 'session_boundary', NAME)}
