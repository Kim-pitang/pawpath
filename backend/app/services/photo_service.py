"""산책길 사진 검증과 메타데이터 제거. 이미지를 디코딩하지 않고 파일 구조만 읽는다.

휴대폰 사진의 EXIF에는 촬영 위치(GPS)가 들어 있을 수 있다. 화면에서 다시 인코딩해 보내지만,
API를 직접 부르는 경우에도 위치가 남지 않도록 서버에서 한 번 더 지운다.
"""

MAX_PHOTO_BYTES = 5 * 1024 * 1024
MAX_PHOTOS_PER_WALK = 5

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# 사진 정보와 글을 담는 PNG 조각. 그림에는 영향이 없다.
PNG_DROP = {b"eXIf", b"tEXt", b"zTXt", b"iTXt", b"tIME"}
# 남기는 JPEG APP 조각: APP0(JFIF), APP14(Adobe 색 변환). APP2는 ICC 색 정보일 때만 남긴다.
JPEG_KEEP_APP = {0xE0, 0xEE}
JPEG_STANDALONE = {0x01, *range(0xD0, 0xD8)}


class PhotoError(ValueError):
    """사용자에게 그대로 보여 줄 수 있는 사진 오류."""


BROKEN = "사진 파일이 손상되었거나 끝까지 올라오지 않았어요."


def _keep_jpeg_segment(marker: int, body: bytes) -> bool:
    if marker == 0xFE:
        return False
    if 0xE0 <= marker <= 0xEF:
        return marker in JPEG_KEEP_APP or (marker == 0xE2 and body.startswith(b"ICC_PROFILE\x00"))
    return True


def clean_jpeg(data: bytes) -> bytes:
    """EXIF, XMP, IPTC, 주석과 끝 표시 뒤에 붙은 데이터(썸네일, 보조 이미지)를 뺀다."""
    out = bytearray(b"\xff\xd8")
    i = 2
    length = len(data)
    while i < length:
        if data[i] != 0xFF or i + 1 >= length:
            raise PhotoError(BROKEN)
        marker = data[i + 1]
        if marker == 0xFF:
            i += 1
            continue
        if marker == 0xD9:
            out += b"\xff\xd9"
            return bytes(out)
        if marker in JPEG_STANDALONE:
            out += data[i : i + 2]
            i += 2
            continue
        if i + 4 > length:
            raise PhotoError(BROKEN)
        size = int.from_bytes(data[i + 2 : i + 4], "big")
        end = i + 2 + size
        if size < 2 or end > length:
            raise PhotoError(BROKEN)
        if _keep_jpeg_segment(marker, data[i + 4 : end]):
            out += data[i:end]
        i = end
        if marker == 0xDA:
            # 스캔 데이터는 다음 표시(0xFF 뒤에 0x00이나 재시작 표시가 아닌 값)까지 그대로 옮긴다.
            start = i
            while i + 1 < length and not (data[i] == 0xFF and data[i + 1] != 0x00 and data[i + 1] not in JPEG_STANDALONE):
                i += 1
            out += data[start:i]
    raise PhotoError(BROKEN)


def clean_png(data: bytes) -> bytes:
    out = bytearray(PNG_SIGNATURE)
    i = len(PNG_SIGNATURE)
    first = True
    while i + 12 <= len(data):
        size = int.from_bytes(data[i : i + 4], "big")
        kind = data[i + 4 : i + 8]
        end = i + 12 + size
        if end > len(data) or (first and kind != b"IHDR"):
            raise PhotoError(BROKEN)
        first = False
        if kind not in PNG_DROP:
            out += data[i:end]
        if kind == b"IEND":
            return bytes(out)
        i = end
    raise PhotoError(BROKEN)


def clean_image(data: bytes) -> tuple[str, bytes]:
    """형식을 파일 내용으로 판단하고, 메타데이터를 뺀 사진과 형식을 돌려준다."""
    if not data:
        raise PhotoError("빈 파일이에요.")
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", clean_jpeg(data)
    if data.startswith(PNG_SIGNATURE):
        return "image/png", clean_png(data)
    raise PhotoError("JPG나 PNG 사진만 올릴 수 있어요.")
