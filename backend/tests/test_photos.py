"""산책길 사진: 형식 확인, 위치 정보 제거, 저장과 삭제."""
import pytest

from app import api as api_module
from app.database import SessionLocal
from app.models import SavedWalkPhoto
from app.services.photo_service import MAX_PHOTOS_PER_WALK, PNG_SIGNATURE, PhotoError, clean_image, clean_jpeg, clean_png

POINTS = [{"latitude": 37.5 + i * 0.0003, "longitude": 127.0, "segment": 0} for i in range(4)]


def segment(marker: int, body: bytes) -> bytes:
    return bytes([0xFF, marker]) + (len(body) + 2).to_bytes(2, "big") + body


JFIF = segment(0xE0, b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00")
EXIF = segment(0xE1, b"Exif\x00\x00MM\x00*GPSLatitude=37.4882;GPSLongitude=127.0647")
XMP = segment(0xE1, b"http://ns.adobe.com/xap/1.0/\x00<x:xmpmeta>exif:GPSLatitude</x:xmpmeta>")
ICC = segment(0xE2, b"ICC_PROFILE\x00\x01\x01color-data")
MPF = segment(0xE2, b"MPF\x00secondary-image-index")
IPTC = segment(0xED, b"Photoshop 3.0\x00location: home")
COMMENT = segment(0xFE, b"secret comment")
DQT = segment(0xDB, b"\x00" + bytes(range(64)))
SOF = segment(0xC0, b"\x08\x00\x10\x00\x10\x01\x01\x11\x00")
DHT = segment(0xC4, b"\x00" + bytes(16) + b"\x01")
SCAN = segment(0xDA, b"\x01\x01\x00\x00\x3f\x00") + b"\x12\xff\x00\x34\xff\xd0\x56"
SCAN2 = segment(0xDA, b"\x01\x01\x00\x01\x3f\x00") + b"\x9a\xff\x00\xbc"
TRAILER = b"\xff\xd8" + EXIF + b"GPS-TRAILER-THUMBNAIL\xff\xd9"


def jpeg(*middle: bytes) -> bytes:
    return b"\xff\xd8" + b"".join(middle) + b"\xff\xd9"


def test_jpeg_loses_location_metadata_but_keeps_the_picture():
    original = jpeg(JFIF, EXIF, XMP, ICC, MPF, IPTC, COMMENT, DQT, SOF, DHT, SCAN) + TRAILER
    cleaned = clean_jpeg(original)
    for secret in (b"Exif", b"GPS", b"xmpmeta", b"MPF", b"location: home", b"secret comment", b"TRAILER"):
        assert secret not in cleaned
    assert cleaned == jpeg(JFIF, ICC, DQT, SOF, DHT, SCAN)


def test_progressive_jpeg_keeps_every_scan():
    original = jpeg(JFIF, EXIF, DQT, SOF, DHT, SCAN, DHT, SCAN2)
    assert clean_jpeg(original) == jpeg(JFIF, DQT, SOF, DHT, SCAN, DHT, SCAN2)


def test_fill_bytes_before_markers_are_tolerated():
    original = b"\xff\xd8\xff" + JFIF + DQT + SOF + SCAN + b"\xff\xd9"
    assert clean_jpeg(original).endswith(SCAN + b"\xff\xd9")


def chunk(kind: bytes, data: bytes) -> bytes:
    return len(data).to_bytes(4, "big") + kind + data + b"\x00\x00\x00\x00"


IHDR = chunk(b"IHDR", b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00")
IDAT = chunk(b"IDAT", b"pixels")
IEND = chunk(b"IEND", b"")


def test_png_loses_text_and_exif_chunks():
    original = PNG_SIGNATURE + IHDR + chunk(b"tEXt", b"Comment\x00GPS home") + chunk(b"eXIf", b"MM\x00*GPS") + IDAT + chunk(b"tIME", b"\x07\xea\x0a\x1f\x00\x00\x00") + IEND + b"TRAILER"
    assert clean_png(original) == PNG_SIGNATURE + IHDR + IDAT + IEND


@pytest.mark.parametrize(
    "data, message",
    [
        (b"", "빈 파일"),
        (b"GIF89a....", "JPG나 PNG"),
        (b"RIFF\x00\x00\x00\x00WEBPVP8 ", "JPG나 PNG"),
        (b"<html><script>alert(1)</script></html>", "JPG나 PNG"),
        (jpeg(JFIF, DQT)[:-2], "손상"),
        (b"\xff\xd8\xff\xe0\x00\xff" + b"short", "손상"),
        (b"\xff\xd8\xff\xe0\x00\x01", "손상"),
        (PNG_SIGNATURE + IDAT + IEND, "손상"),
        (PNG_SIGNATURE + IHDR + IDAT, "손상"),
    ],
)
def test_broken_or_unsupported_files_are_refused(data, message):
    with pytest.raises(PhotoError, match=message):
        clean_image(data)


# ---------- API
def saved_walk(client) -> dict:
    return client.post("/api/my-walks", json={"title": "사진 길", "points": POINTS}).json()


def upload(client, walk_id, data, content_type="image/jpeg"):
    return client.post(f"/api/my-walks/{walk_id}/photos", content=data, headers={"Content-Type": content_type})


def test_upload_stores_a_clean_copy_and_serves_it_safely(client):
    walk = saved_walk(client)
    original = jpeg(JFIF, EXIF, DQT, SOF, DHT, SCAN) + TRAILER
    # 형식은 Content-Type이 아니라 파일 내용으로 판단한다.
    response = upload(client, walk["id"], original, content_type="text/html")
    assert response.status_code == 201
    photo = response.json()
    assert photo["content_type"] == "image/jpeg"
    assert set(photo) == {"id", "content_type", "size_bytes", "created_at"}
    served = client.get(f"/api/my-walks/{walk['id']}/photos/{photo['id']}")
    assert served.status_code == 200
    assert served.content == jpeg(JFIF, DQT, SOF, DHT, SCAN)
    assert photo["size_bytes"] == len(served.content)
    assert served.headers["content-type"] == "image/jpeg"
    assert served.headers["x-content-type-options"] == "nosniff"
    assert served.headers["cache-control"].startswith("private")
    detail = client.get(f"/api/my-walks/{walk['id']}").json()
    assert [item["id"] for item in detail["photos"]] == [photo["id"]]


def test_unsupported_and_empty_uploads_get_a_reason(client):
    walk = saved_walk(client)
    assert "JPG나 PNG" in upload(client, walk["id"], b"GIF89a....").json()["detail"]
    assert upload(client, walk["id"], b"").status_code == 422
    assert client.get(f"/api/my-walks/{walk['id']}").json()["photos"] == []


def test_too_large_photo_is_refused(client, monkeypatch):
    monkeypatch.setattr(api_module, "MAX_PHOTO_BYTES", 50)
    response = upload(client, saved_walk(client)["id"], jpeg(JFIF, DQT, SOF, DHT, SCAN) + b"x" * 100)
    assert response.status_code == 413


def test_photo_count_is_limited(client):
    walk = saved_walk(client)
    for _ in range(MAX_PHOTOS_PER_WALK):
        assert upload(client, walk["id"], jpeg(JFIF, SCAN)).status_code == 201
    response = upload(client, walk["id"], jpeg(JFIF, SCAN))
    assert response.status_code == 409
    assert f"{MAX_PHOTOS_PER_WALK}장" in response.json()["detail"]


def test_photos_are_deleted_one_by_one_and_with_the_walk(client):
    walk = saved_walk(client)
    first = upload(client, walk["id"], jpeg(JFIF, SCAN)).json()
    second = upload(client, walk["id"], PNG_SIGNATURE + IHDR + IDAT + IEND).json()
    assert second["content_type"] == "image/png"
    assert client.delete(f"/api/my-walks/{walk['id']}/photos/{first['id']}").status_code == 204
    assert client.get(f"/api/my-walks/{walk['id']}/photos/{first['id']}").status_code == 404
    assert [item["id"] for item in client.get(f"/api/my-walks/{walk['id']}").json()["photos"]] == [second["id"]]
    client.delete(f"/api/my-walks/{walk['id']}")
    with SessionLocal() as db:
        assert db.get(SavedWalkPhoto, second["id"]) is None


def test_photo_must_belong_to_the_walk_in_the_address(client):
    first, second = saved_walk(client), saved_walk(client)
    photo = upload(client, first["id"], jpeg(JFIF, SCAN)).json()
    assert client.get(f"/api/my-walks/{second['id']}/photos/{photo['id']}").status_code == 404
    assert client.delete(f"/api/my-walks/{second['id']}/photos/{photo['id']}").status_code == 404


def test_photos_never_appear_in_shared_views(client):
    walk = saved_walk(client)
    upload(client, walk["id"], jpeg(JFIF, SCAN))
    token = client.post(f"/api/my-walks/{walk['id']}/share", json={"share_memo": True}).json()["share_token"]
    shared = client.get(f"/api/shared/{token}")
    assert "photo" not in shared.text
    assert client.get(f"/api/shared/{token}/photos/1").status_code == 404
    client.patch(f"/api/my-walks/{walk['id']}", json={"visibility": "public"})
    assert "photo" not in client.get("/api/public-walks").text
