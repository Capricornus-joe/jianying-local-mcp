import uuid

import pytest

from jianying_local_mcp.subtitles import parse_srt


def test_imports_chinese_bom_crlf_multiline_and_preserves_literal_markup():
    content = (
        "\ufeff1\r\n00:00:01,250 --> 00:00:03,500\r\n"
        "中国时空\r\n<b>连接每一刻</b>\t& 最后一行\r\n\r\n"
        "2\r\n00:00:04,000 --> 00:00:05,000\r\n继续前行\r\n"
    )
    segments = parse_srt(content)
    assert len(segments) == 2
    assert segments[0] | {"id": "ignored"} == {
        "id": "ignored", "kind": "text", "track": "字幕", "start": 1.25,
        "duration": 2.25, "text": "中国时空\n<b>连接每一刻</b>\t& 最后一行",
        "font_size": 48, "color": "#FFFFFF", "x": 0, "y": -0.75,
    }
    assert segments[1]["text"] == "继续前行"
    assert uuid.UUID(segments[0]["id"]).version == 4
    assert segments[0]["id"] != segments[1]["id"]


def test_unindexed_cues_large_hours_decimal_fractions_and_custom_placement():
    content = "25:00:00.125 --> 25:00:02.500\n跨日字幕\n\n25:00:03.1 --> 25:00:04.25\n下一句"
    segments = parse_srt(content, track="旁白字幕", offset=1.5, font_size=42, color="#FFCC00", x=0.1, y=-0.5)
    assert segments[0]["start"] == 90001.625
    assert segments[0]["duration"] == 2.375
    assert segments[1]["duration"] == 1.15
    assert {key: segments[0][key] for key in ("track", "font_size", "color", "x", "y")} == {
        "track": "旁白字幕", "font_size": 42, "color": "#FFCC00", "x": 0.1, "y": -0.5,
    }


def test_preserves_overlaps_and_source_order_with_optional_indices():
    segments = parse_srt("7\n00:00:02,000 --> 00:00:05,000\n第一句\n \t\n00:00:01,000 --> 00:00:03,000\n重叠句")
    assert [segment["start"] for segment in segments] == [2, 1]
    assert [segment["text"] for segment in segments] == ["第一句", "重叠句"]


def test_negative_offset_allowed_when_result_starts_at_zero():
    segment = parse_srt("00:00:01,500 --> 00:00:02,500\n正文", offset=-1.5)[0]
    assert segment["start"] == 0
    assert segment["duration"] == 1


@pytest.mark.parametrize("content", [
    "", " \n\t\n", "\ufeff", "1", "1\nnot a timing line\n正文",
    "00:00:00,000 --> 00:00:01,000", "00:00:00,000 --> 00:00:01,000\n \t",
    "00:60:00,000 --> 01:00:01,000\n正文", "00:00:60,000 --> 00:01:01,000\n正文",
    "-01:00:00,000 --> 00:00:01,000\n正文", "00:00:00,1000 --> 00:00:01,000\n正文",
    "00:00:01,000 --> 00:00:01,000\n正文", "00:00:02,000 --> 00:00:01,000\n正文",
    "NaN --> 00:00:01,000\n正文", "00:00:00,000 --> Infinity\n正文",
    "00:00:00,000 --> 00:00:01,000\n正文\n00:00:02,000 --> 00:00:03,000\n下一句",
])
def test_rejects_invalid_srt(content):
    with pytest.raises(ValueError):
        parse_srt(content)


def test_invalid_later_block_does_not_return_partial_success():
    with pytest.raises(ValueError, match="block 2"):
        parse_srt("1\n00:00:00,000 --> 00:00:01,000\n有效正文\n\n2\n错误时间\n无效正文")


@pytest.mark.parametrize("control", ["\x00", "\x01", "\x07", "\x0b", "\x0c", "\r", "\x1b", "\x7f", "\x85"])
def test_rejects_control_characters(control):
    with pytest.raises(ValueError, match="control character"):
        parse_srt(f"00:00:00,000 --> 00:00:01,000\n前{control}后")


@pytest.mark.parametrize("parameter", ["offset", "font_size", "x", "y"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_rejects_nonfinite_numeric_parameters(parameter, value):
    with pytest.raises(ValueError, match="finite number"):
        parse_srt("00:00:01,000 --> 00:00:02,000\n正文", **{parameter: value})


def test_rejects_negative_resulting_start():
    with pytest.raises(ValueError, match="negative"):
        parse_srt("00:00:01,000 --> 00:00:02,000\n正文", offset=-1.01)


def test_rejects_unrepresentable_timestamp():
    hours = "9" * 400
    with pytest.raises(ValueError, match="numeric range"):
        parse_srt(f"{hours}:00:00,000 --> {hours}:00:01,000\n正文")


def test_keeps_script_markup_as_text():
    literal_text = '<script>alert("原样文本")</script>'
    assert parse_srt(f"00:00:00,000 --> 00:00:01,000\n{literal_text}")[0]["text"] == literal_text
