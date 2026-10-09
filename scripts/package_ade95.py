"""ADE-95 제출 ZIP 생성: 원본 SHA256SUMS 보존, 새 내용 해시와 ZIP 해시 별도 기록."""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True,help='새 제출 ZIP 경로; 덮어쓰기 금지')
    args = parser.parse_args()
    output = args.output.resolve()
    sidecar = output.with_suffix('.zip.sha256')
    if output.exists() or sidecar.exists():
        parser.error('ZIP 또는 외부 체크섬이 이미 있습니다. 새 이름을 사용하세요.')
    files = []
    for folder in ('src','tests','scripts','schemas','examples','docs'):
        files.extend(p for p in (ROOT/folder).rglob('*') if p.is_file())
    # 과거 ADE-66·67 근거와 새 검토 폴더의 JSON을 함께 보존한다.
    # 임시 입력·결과 복사본, 압축 파일, 검토용 실행 스크립트는 넣지 않는다.
    files.extend(p for p in (ROOT/'logs').rglob('*.json') if p.is_file())
    for folder in sorted((ROOT/'outputs').glob('ade95_final*')):
        files.extend(p for p in folder.rglob('*') if p.is_file())
    files.extend(ROOT/name for name in ('README.md','README-viewer.md','VALIDATION.md','SHA256SUMS.txt','requirements.txt',
                                        'requirements-viewer.txt','requirements-viewer.lock.txt',
                                        '인지동_최신기준_규격v1.0.0_20261008.md'))
    files = sorted(set(p for p in files if '__pycache__' not in p.parts and '.venv' not in p.parts
                       and p.suffix not in ('.pyc','.zip','.tmp')),key=lambda p:p.relative_to(ROOT).as_posix())
    hashes = {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    package_info = {'created_at':datetime.now(timezone(timedelta(hours=9))).isoformat(),
                    'scope':'ADE-95 제출 검토 보완: 입력 점군 대조·README·회귀 검사. 사람의 직접 GUI 조작·실기기·팀장 승인·공식 통합은 미확인 또는 미완료.',
                    'file_count_before_package_records':len(files),
                    'excluded':['.venv','__pycache__','*.pyc','임시 파일·입력·결과 복사본','이전 ZIP','이전 렌더링 시도'],
                    'checksum_policy':'원본 SHA256SUMS.txt 보존. ADE95_SHA256SUMS.txt는 자체를 제외한 패키지 내용의 실제 해시를 기록한다.'}
    package_bytes = (json.dumps(package_info,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    hashes['ADE95_PACKAGE_INFO.json'] = hashlib.sha256(package_bytes).hexdigest()
    hash_bytes = ''.join(f'{digest}  {name}\n' for name,digest in sorted(hashes.items())).encode('utf-8')
    output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(output,'x',compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path,'injidong_ade95/'+path.relative_to(ROOT).as_posix())
        archive.writestr('injidong_ade95/ADE95_PACKAGE_INFO.json',package_bytes)
        archive.writestr('injidong_ade95/ADE95_SHA256SUMS.txt',hash_bytes)
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
        names = archive.namelist()
        assert all('.venv' not in n.split('/') and '__pycache__' not in n.split('/') and not n.endswith('.pyc') for n in names)
        for name,digest in hashes.items():
            assert hashlib.sha256(archive.read('injidong_ade95/'+name)).hexdigest()==digest,name
        assert archive.read('injidong_ade95/SHA256SUMS.txt')==(ROOT/'SHA256SUMS.txt').read_bytes()
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    with sidecar.open('x',encoding='utf-8') as stream:
        stream.write(f'{digest}  {output.name}\n')
    print(json.dumps({'zip':str(output),'sha256':digest,'file_count':len(names),
                      'archive_crc_and_content_hashes_verified':True,'sidecar':str(sidecar)},ensure_ascii=False,indent=2))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
