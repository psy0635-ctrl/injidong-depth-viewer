"""Bounded ZIP inspection and exclusive extraction; never calls extractall."""
from dataclasses import dataclass
from pathlib import Path
import re
import stat
import unicodedata
import zipfile


class MobileInputError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(f'{code}: {message}')


def require(ok, code, message):
    if not ok:
        raise MobileInputError(code, message)


@dataclass(frozen=True)
class ZipLimits:
    max_archive_bytes: int = 128 * 1024**2
    max_members: int = 4096
    max_member_bytes: int = 32 * 1024**2
    max_total_bytes: int = 256 * 1024**2
    max_ratio: float = 200.0
    max_frames: int = 128
    max_pixels: int = 4_000_000
    max_total_pixels: int = 16_000_000


def checked_parts(name, directory=False):
    require(isinstance(name,str) and bool(name), 'UNSAFE_ZIP', '빈 경로입니다.')
    raw = name[:-1] if directory and name.endswith('/') else name
    require(len(raw) <= 1024 and '\\' not in raw and not raw.startswith('/'),
            'UNSAFE_ZIP', f'상대 POSIX 경로가 필요합니다: {name!r}')
    parts = raw.split('/')
    for part in parts:
        require(bool(part) and part not in ('.','..') and len(part) <= 200
                and not part.endswith((' ','.')) and unicodedata.normalize('NFC',part)==part
                and not re.search(r'~[0-9]',part)
                and not any(ord(c)<32 or c in '<>:"|?*' for c in part)
                and not re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])',
                                     part.split('.')[0],re.I),
                'UNSAFE_ZIP', f'위험하거나 모호한 Windows 경로입니다: {name!r}')
    return parts


def inspect_zip(archive, limits):
    members = archive.infolist()
    require(len(members)<=limits.max_members, 'LIMIT_EXCEEDED', 'ZIP 항목 수 제한을 초과했습니다.')
    explicit = set()
    tree = {}
    total = 0
    for info in members:
        require(info.orig_filename==info.filename, 'UNSAFE_ZIP', 'NUL 경로를 지원하지 않습니다.')
        parts=checked_parts(info.filename,info.is_dir())
        key='/'.join(parts).casefold()
        require(key not in explicit, 'UNSAFE_ZIP', f'중복/대소문자 충돌: {info.filename}')
        explicit.add(key)
        mode=info.external_attr>>16
        require(stat.S_IFMT(mode) in (0,stat.S_IFDIR,stat.S_IFREG)
                and not (info.external_attr & 0x400), 'UNSAFE_ZIP', '링크/특수 ZIP 항목을 거부했습니다.')
        require(not info.flag_bits & 1 and info.compress_type in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED),
                'UNSUPPORTED_ZIP', '암호화 또는 미지원 ZIP 압축 방식입니다.')
        require(info.file_size>=0 and info.compress_size>=0 and info.file_size<=limits.max_member_bytes,
                'LIMIT_EXCEEDED', 'ZIP 개별 파일 크기 제한을 초과했습니다.')
        require(not info.file_size or info.file_size/max(1,info.compress_size)<=limits.max_ratio,
                'LIMIT_EXCEEDED', 'ZIP 압축률 제한을 초과했습니다.')
        require(not info.is_dir() or info.file_size==0, 'UNSAFE_ZIP', '폴더에 파일 본문이 있습니다.')
        require(stat.S_IFMT(mode)!=stat.S_IFDIR or info.is_dir(), 'UNSAFE_ZIP', '폴더 타입/이름이 다릅니다.')
        total+=info.file_size
        require(total<=limits.max_total_bytes,'LIMIT_EXCEEDED','총 해제 크기 제한을 초과했습니다.')
        for n in range(1,len(parts)+1):
            prefix='/'.join(parts[:n]);folded=prefix.casefold()
            kind='dir' if n<len(parts) or info.is_dir() else 'file'
            previous=tree.get(folded)
            require(previous is None or previous==(prefix,kind), 'UNSAFE_ZIP',
                    f'파일/폴더 또는 대소문자 경로 충돌: {prefix}')
            tree[folded]=(prefix,kind)
    return members


def extract_checked(archive, destination, limits, progress=lambda message:None):
    members=inspect_zip(archive,limits)
    total=0
    for index,info in enumerate(members):
        target=destination.joinpath(*checked_parts(info.filename,info.is_dir()))
        if info.is_dir():
            target.mkdir(parents=True,exist_ok=True)
            continue
        target.parent.mkdir(parents=True,exist_ok=True)
        written=0
        with archive.open(info) as src, target.open('xb') as dst:
            while chunk:=src.read(1024*1024):
                written+=len(chunk);total+=len(chunk)
                require(written<=info.file_size and written<=limits.max_member_bytes
                        and total<=limits.max_total_bytes,'LIMIT_EXCEEDED','실제 해제 크기 제한 초과입니다.')
                dst.write(chunk)
        require(written==info.file_size,'INVALID_ZIP','ZIP 본문 길이가 다릅니다.')
        progress(f'파일 검사/해제 {index+1}/{len(members)}')
