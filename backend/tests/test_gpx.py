"""GPX 읽기와 쓰기. 실제 앱이 내보내는 형식을 본떠 만든 예시로 검증한다."""
from datetime import datetime
from xml.etree import ElementTree

import pytest

from app.services import gpx_service
from app.services.gpx_service import GpxError, GpxPoint, build_gpx, content_disposition, gpx_filename, parse_gpx

NS = 'xmlns="http://www.topografix.com/GPX/1/1"'


def gpx(body: str, version: str = "1.1") -> bytes:
    return f'<?xml version="1.0" encoding="UTF-8"?><gpx version="{version}" creator="test" {NS}>{body}</gpx>'.encode()


SIMPLE = gpx(
    """<metadata><name>메타 이름</name></metadata>
    <trk><name>아침 산책</name><trkseg>
      <trkpt lat="37.5" lon="127.0"><ele>12.5</ele><time>2026-10-31T01:00:00Z</time></trkpt>
      <trkpt lat="37.5001" lon="127.0001"><ele>13</ele><time>2026-10-31T01:00:10Z</time></trkpt>
      <trkpt lat="37.5002" lon="127.0002"><time>2026-10-31T10:00:20+09:00</time></trkpt>
    </trkseg></trk>"""
)


def test_reads_points_in_order_with_altitude_and_local_time():
    parsed = parse_gpx(SIMPLE)
    assert parsed.version == "1.1"
    assert parsed.name == "메타 이름"
    assert [(p.latitude, p.longitude) for p in parsed.points] == [(37.5, 127.0), (37.5001, 127.0001), (37.5002, 127.0002)]
    assert parsed.points[0].altitude == 12.5
    assert parsed.points[2].altitude is None
    # UTC와 +09:00 표기 모두 서비스 현지 시각으로 맞춘다.
    assert parsed.points[0].recorded_at == datetime(2026, 10, 31, 10, 0, 0)
    assert parsed.points[2].recorded_at == datetime(2026, 10, 31, 10, 0, 20)


def test_points_without_time_are_kept():
    parsed = parse_gpx(gpx('<trk><trkseg><trkpt lat="1" lon="2"/><trkpt lat="1.1" lon="2.1"/></trkseg></trk>'))
    assert len(parsed.points) == 2
    assert all(point.recorded_at is None for point in parsed.points)


def test_multiple_tracks_and_segments_keep_their_order():
    parsed = parse_gpx(
        gpx(
            """<trk><trkseg><trkpt lat="1" lon="1"/><trkpt lat="1.1" lon="1"/></trkseg>
                    <trkseg><trkpt lat="2" lon="1"/><trkpt lat="2.1" lon="1"/></trkseg></trk>
               <trk><trkseg/><trkseg><trkpt lat="3" lon="1"/><trkpt lat="3.1" lon="1"/></trkseg></trk>"""
        )
    )
    assert parsed.track_count == 2
    assert [p.latitude for p in parsed.points] == [1, 1.1, 2, 2.1, 3, 3.1]
    segments = [p.segment for p in parsed.points]
    assert segments[0] == segments[1] != segments[2] == segments[3] != segments[4] == segments[5]
    assert any("트랙 2개" in warning for warning in parsed.warnings)


def test_gpx_1_0_and_files_without_namespace_are_read():
    assert parse_gpx(gpx('<trk><trkseg><trkpt lat="1" lon="1"/><trkpt lat="2" lon="2"/></trkseg></trk>', version="1.0")).version == "1.0"
    bare = b'<gpx version="1.1"><trk><trkseg><trkpt lat="1" lon="1"/><trkpt lat="2" lon="2"/></trkseg></trk></gpx>'
    assert len(parse_gpx(bare).points) == 2


def test_extensions_from_fitness_apps_do_not_change_the_data():
    """가민과 스트라바 형식처럼 심박 확장 태그가 붙어도 좌표와 시각만 읽는다."""
    data = b"""<?xml version="1.0" encoding="UTF-8"?>
    <gpx creator="StravaGPX" version="1.1" xmlns="http://www.topografix.com/GPX/1/1"
         xmlns:gpxtpx="http://www.garmin.com/xmlschemas/TrackPointExtension/v1">
      <metadata><time>2026-10-01T00:00:00Z</time></metadata>
      <trk><name>Morning Walk</name><type>walking</type><trkseg>
        <trkpt lat="37.5" lon="127"><ele>10</ele><time>2026-10-31T01:00:00Z</time>
          <extensions><gpxtpx:TrackPointExtension><gpxtpx:hr>90</gpxtpx:hr><time>1999-01-01T00:00:00Z</time><ele>999</ele></gpxtpx:TrackPointExtension></extensions>
        </trkpt>
        <trkpt lat="37.6" lon="127"><time>2026-10-31T01:00:05Z</time></trkpt>
      </trkseg></trk></gpx>"""
    parsed = parse_gpx(data)
    assert parsed.name == "Morning Walk"
    assert parsed.points[0].altitude == 10
    assert parsed.points[0].recorded_at == datetime(2026, 10, 31, 10, 0, 0)


def test_route_only_files_are_read_with_a_warning():
    parsed = parse_gpx(gpx('<rte><name>계획</name><rtept lat="1" lon="1"/><rtept lat="1.1" lon="1"/></rte>'))
    assert len(parsed.points) == 2
    assert any("rte" in warning for warning in parsed.warnings)


@pytest.mark.parametrize("bad", ['lat="91" lon="1"', 'lat="1" lon="181"', 'lat="NaN" lon="1"', 'lat="inf" lon="1"', 'lat="abc" lon="1"', 'lon="1"'])
def test_invalid_coordinates_are_dropped_and_reported(bad):
    parsed = parse_gpx(gpx(f'<trk><trkseg><trkpt lat="1" lon="1"/><trkpt {bad}/><trkpt lat="2" lon="2"/></trkseg></trk>'))
    assert [p.latitude for p in parsed.points] == [1, 2]
    assert parsed.invalid_point_count == 1
    assert any("잘못된" in warning for warning in parsed.warnings)


def test_unreadable_time_keeps_the_point_and_warns():
    parsed = parse_gpx(gpx('<trk><trkseg><trkpt lat="1" lon="1"><time>어제</time></trkpt><trkpt lat="2" lon="2"/></trkseg></trk>'))
    assert parsed.points[0].recorded_at is None
    assert any("시각" in warning for warning in parsed.warnings)


@pytest.mark.parametrize(
    "data, message",
    [
        (b"", "빈 파일"),
        (b"   \n ", "빈 파일"),
        (b"not xml at all", "형식"),
        (b"<gpx version='1.1'><trk>", "형식"),
        (b'<kml version="1.1"></kml>', "GPX 파일이 아니에요"),
        (b'<gpx version="2.0"></gpx>', "버전"),
        (b"<gpx></gpx>", "좌표가 없어요"),
        (gpx(""), "좌표가 없어요"),
        (gpx('<wpt lat="1" lon="1"/><wpt lat="2" lon="2"/>'), "장소 표시\\(waypoint\\) 2개만"),
        (gpx('<trk><trkseg><trkpt lat="undefined" lon="undefined"/><trkpt lat="x" lon="y"/></trkseg></trk>'), "올바르지 않은 지점만 있어요\\(2개\\)"),
        (gpx('<trk><trkseg><trkpt lat="1" lon="1"/></trkseg></trk>'), "2개 이상"),
        ('<?xml version="1.0" encoding="EUC-KR"?><gpx version="1.1"></gpx>'.encode(), "형식"),
    ],
)
def test_wrong_files_get_a_clear_error(data, message):
    with pytest.raises(GpxError, match=message):
        parse_gpx(data)


def test_external_entity_is_rejected_and_the_file_is_not_read(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP-SECRET")
    payload = f"""<?xml version="1.0"?><!DOCTYPE gpx [<!ENTITY xxe SYSTEM "file://{secret}">]>
    <gpx version="1.1"><trk><name>&xxe;</name><trkseg><trkpt lat="1" lon="1"/><trkpt lat="2" lon="2"/></trkseg></trk></gpx>"""
    with pytest.raises(GpxError, match="DOCTYPE"):
        parse_gpx(payload.encode())


def test_entity_bomb_and_external_dtd_are_rejected():
    bomb = b"""<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]><gpx version="1.1">&b;</gpx>"""
    with pytest.raises(GpxError, match="DOCTYPE"):
        parse_gpx(bomb)
    with pytest.raises(GpxError, match="DOCTYPE"):
        parse_gpx(b'<!DOCTYPE gpx SYSTEM "http://example.com/evil.dtd"><gpx version="1.1"></gpx>')


def test_doctype_hidden_in_utf16_is_still_rejected():
    payload = '<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE gpx [<!ENTITY x "y">]><gpx version="1.1"></gpx>'
    with pytest.raises(GpxError, match="DOCTYPE"):
        parse_gpx(payload.encode("utf-16"))


def test_too_large_file_and_too_many_points_are_rejected(monkeypatch):
    with pytest.raises(GpxError, match="너무 커요"):
        parse_gpx(b" " * 0 + b"<" * (gpx_service.MAX_GPX_BYTES + 1))
    monkeypatch.setattr(gpx_service, "MAX_POINTS", 2)
    with pytest.raises(GpxError, match="너무 많아요"):
        parse_gpx(gpx('<trk><trkseg><trkpt lat="1" lon="1"/><trkpt lat="2" lon="2"/><trkpt lat="3" lon="3"/></trkseg></trk>'))


# ---------- 내보내기
POINTS = [
    GpxPoint(0, 37.5, 127.0, 12.5, datetime(2026, 10, 31, 10, 0, 0)),
    GpxPoint(0, 37.5001234, 127.0001234, None, datetime(2026, 10, 31, 10, 0, 10)),
    GpxPoint(3, 37.51, 127.01, 20.0, datetime(2026, 10, 31, 10, 5, 0)),
    GpxPoint(3, 37.5101, 127.0101, None, None),
]


def test_export_follows_the_gpx_1_1_structure_in_utc():
    root = ElementTree.fromstring(build_gpx("강변 산책", POINTS))
    gpx_ns = "{http://www.topografix.com/GPX/1/1}"
    assert root.tag == f"{gpx_ns}gpx"
    assert root.attrib["version"] == "1.1"
    assert root.attrib["creator"] == "PawPath"
    assert root.find(f"{gpx_ns}metadata/{gpx_ns}name").text == "강변 산책"
    track = root.find(f"{gpx_ns}trk")
    assert track.find(f"{gpx_ns}name").text == "강변 산책"
    segments = track.findall(f"{gpx_ns}trkseg")
    assert len(segments) == 2
    first = segments[0].findall(f"{gpx_ns}trkpt")[0]
    assert (first.attrib["lat"], first.attrib["lon"]) == ("37.5", "127.0")
    # 표준 순서대로 ele가 time보다 앞이고, 시각은 UTC다.
    assert [child.tag for child in first] == [f"{gpx_ns}ele", f"{gpx_ns}time"]
    assert first.find(f"{gpx_ns}time").text == "2026-10-31T01:00:00Z"


def test_file_without_a_version_is_read_with_a_warning():
    """실제 기기 파일 중에 버전 표기를 빠뜨린 것이 있다."""
    parsed = parse_gpx(b'<gpx><trk><trkseg><trkpt lat="52.33" lon="5.54"><speed>1.2</speed></trkpt><trkpt lat="52.331" lon="5.541"/></trkseg></trk></gpx>')
    assert len(parsed.points) == 2
    assert any("버전 표기" in warning for warning in parsed.warnings)


def test_utf8_bom_is_accepted():
    data = "\ufeff".encode() + gpx('<trk><trkseg><trkpt lat="1" lon="1"/><trkpt lat="2" lon="2"/></trkseg></trk>')
    assert len(parse_gpx(data).points) == 2


def test_export_keeps_full_precision_without_exponents():
    points = [GpxPoint(0, 37.123456789012, 127.98765432101, 48.962041, None), GpxPoint(0, 0.00001, -0.00002, 1e-05, None)]
    text = build_gpx("정밀도", points).decode()
    assert 'lat="0.00001"' in text and "e-0" not in text
    again = parse_gpx(text.encode()).points
    assert [(p.latitude, p.longitude, p.altitude) for p in again] == [(p.latitude, p.longitude, p.altitude) for p in points]


def test_export_starts_with_a_utf8_declaration():
    assert build_gpx("산책", POINTS).startswith(b'<?xml version="1.0" encoding="UTF-8"?>')


def test_export_then_import_keeps_the_route_and_times():
    parsed = parse_gpx(build_gpx("왕복", POINTS))
    assert [(p.latitude, p.longitude) for p in parsed.points] == [(p.latitude, p.longitude) for p in POINTS]
    assert [p.recorded_at for p in parsed.points] == [p.recorded_at for p in POINTS]
    assert [p.altitude for p in parsed.points] == [p.altitude for p in POINTS]
    assert parsed.points[0].segment == parsed.points[1].segment != parsed.points[2].segment == parsed.points[3].segment


def test_sub_second_time_survives_the_round_trip():
    points = [GpxPoint(0, 1, 1, None, datetime(2026, 1, 1, 9, 0, 0, 250000)), GpxPoint(0, 2, 2, None, datetime(2026, 1, 1, 9, 0, 1))]
    assert parse_gpx(build_gpx("초", points)).points[0].recorded_at == points[0].recorded_at


def test_special_characters_in_the_name_are_escaped():
    name = '<script>&"\'\x07 강아지 🐕'
    parsed = parse_gpx(build_gpx(name, POINTS))
    assert parsed.name == '<script>&"\' 강아지 🐕'


def test_shared_export_has_no_times_or_altitude():
    text = build_gpx("공유", POINTS, include_details=False).decode()
    assert "<time>" not in text and "<ele>" not in text
    assert len(parse_gpx(text.encode()).points) == len(POINTS)


@pytest.mark.parametrize(
    "title, expected",
    [
        ("My Walk", "pawpath_my-walk_20261031.gpx"),
        ('a/b\\c:d*e?f"g<h>i|j', "pawpath_a-b-c-d-e-f-g-h-i-j_20261031.gpx"),
        ("../../etc/passwd", "pawpath_etc-passwd_20261031.gpx"),
        ("망원 초록길!", "pawpath_망원-초록길_20261031.gpx"),
        ("!!!", "pawpath_walk_20261031.gpx"),
        ("x" * 100, f"pawpath_{'x' * 40}_20261031.gpx"),
    ],
)
def test_filename_reflects_the_title_without_special_characters(title, expected):
    assert gpx_filename(title, datetime(2026, 10, 31)) == expected


@pytest.mark.parametrize(
    "title, fallback",
    [("망원 초록길", "pawpath_walk_20261031.gpx"), ("Morning <Walk> 양재천", "pawpath_morning-walk_20261031.gpx")],
)
def test_content_disposition_is_ascii_safe_for_korean_names(title, fallback):
    header = content_disposition(title, datetime(2026, 10, 31))
    header.encode("ascii")
    assert f'filename="{fallback}"' in header
    assert "filename*=UTF-8''pawpath_" in header


def test_content_disposition_keeps_the_korean_name_and_blocks_header_injection():
    assert "%EB%A7%9D%EC%9B%90" in content_disposition("망원 초록길", None)
    header = content_disposition("줄\r\n바꿈: 공격", None)
    assert "\n" not in header and "\r" not in header
