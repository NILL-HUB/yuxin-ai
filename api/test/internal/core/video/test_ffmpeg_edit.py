"""ffmpeg 编辑命令构造与 SRT 生成（纯函数，不依赖真实 ffmpeg）。"""
import pytest

from internal.core.video.ffmpeg_edit import (
    build_concat_command,
    build_subtitle_command,
    build_trim_command,
    format_srt_timestamp,
    render_srt,
)


def test_format_srt_timestamp_uses_comma_millis():
    # SRT 规范用逗号分隔毫秒（不是点），写错播放器会不认
    assert format_srt_timestamp(0) == "00:00:00,000"
    assert format_srt_timestamp(1.5) == "00:00:01,500"
    assert format_srt_timestamp(3661.234) == "01:01:01,234"


def test_format_srt_timestamp_clamps_negative_to_zero():
    assert format_srt_timestamp(-3) == "00:00:00,000"


def test_format_srt_timestamp_rounds_to_millis():
    # 避免浮点噪声产生 1,2345 这类非法四位毫秒
    assert format_srt_timestamp(1.2345) in {"00:00:01,234", "00:00:01,235"}


def test_render_srt_produces_valid_blocks():
    srt = render_srt([
        {"start": 0.0, "end": 1.5, "text": "第一句"},
        {"start": 1.5, "end": 3.0, "text": "第二句"},
    ])
    assert srt == (
        "1\n00:00:00,000 --> 00:00:01,500\n第一句\n\n"
        "2\n00:00:01,500 --> 00:00:03,000\n第二句\n\n"
    )


def test_render_srt_skips_empty_text_and_renumbers():
    srt = render_srt([
        {"start": 0.0, "end": 1.0, "text": "有"},
        {"start": 1.0, "end": 2.0, "text": "   "},
        {"start": 2.0, "end": 3.0, "text": "也有"},
    ])
    # 空文本块必须丢弃，且序号连续（不能留 1,3）
    assert "1\n00:00:00,000" in srt
    assert "2\n00:00:02,000" in srt
    assert "3\n" not in srt


def test_render_srt_rejects_empty_cues():
    with pytest.raises(ValueError, match="字幕内容为空"):
        render_srt([])
    with pytest.raises(ValueError, match="字幕内容为空"):
        render_srt([{"start": 0, "end": 1, "text": "  "}])


def test_render_srt_rejects_end_before_start():
    with pytest.raises(ValueError, match="结束时间必须晚于开始时间"):
        render_srt([{"start": 2.0, "end": 1.0, "text": "倒挂"}])


def test_build_trim_command_uses_stream_copy_by_default():
    # -c copy 是无损且秒级的关键；顺序必须是 -ss 在 -i 之前（快速定位）
    cmd = build_trim_command(
        "ffmpeg", source="/in/a.mp4", output="/out/b.mp4", start_sec=1.0, end_sec=3.0
    )
    assert cmd[0] == "ffmpeg"
    assert "-ss" in cmd and cmd[cmd.index("-ss") + 1] == "1.000"
    assert cmd.index("-ss") < cmd.index("-i")
    assert "-t" in cmd and cmd[cmd.index("-t") + 1] == "2.000"
    assert "-c" in cmd and cmd[cmd.index("-c") + 1] == "copy"
    assert cmd[-1] == "/out/b.mp4"


def test_build_trim_command_reencode_drops_copy():
    cmd = build_trim_command(
        "ffmpeg", source="/in/a.mp4", output="/out/b.mp4",
        start_sec=0.0, end_sec=1.0, reencode=True,
    )
    assert "copy" not in cmd
    assert "libx264" in cmd


def test_build_trim_command_requires_positive_duration():
    with pytest.raises(ValueError, match="结束时间必须晚于开始时间"):
        build_trim_command(
            "ffmpeg", source="/in/a.mp4", output="/out/b.mp4", start_sec=5.0, end_sec=5.0
        )


def test_build_trim_command_end_none_means_to_the_end():
    cmd = build_trim_command(
        "ffmpeg", source="/in/a.mp4", output="/out/b.mp4", start_sec=2.0, end_sec=None
    )
    assert "-t" not in cmd
    assert cmd[cmd.index("-ss") + 1] == "2.000"


def test_build_concat_command_uses_concat_demuxer():
    cmd = build_concat_command("ffmpeg", list_file="/tmp/list.txt", output="/out/m.mp4")
    assert cmd[0] == "ffmpeg"
    assert cmd[cmd.index("-f") + 1] == "concat"
    assert cmd[cmd.index("-i") + 1] == "/tmp/list.txt"
    assert "-c" in cmd and cmd[cmd.index("-c") + 1] == "copy"
    assert cmd[-1] == "/out/m.mp4"


def test_build_subtitle_command_burns_srt_with_libass():
    cmd = build_subtitle_command(
        "ffmpeg", source="/in/a.mp4", output="/out/b.mp4", srt_path="/tmp/c.srt"
    )
    assert cmd[0] == "ffmpeg"
    # subtitles 滤镜依赖 libass（已实测镜像内可用）
    vf_index = cmd.index("-vf")
    assert cmd[vf_index + 1].startswith("subtitles=")
    assert "c.srt" in cmd[vf_index + 1]
    assert "libx264" in cmd
    assert cmd[-1] == "/out/b.mp4"


def test_build_subtitle_command_escapes_windows_style_path_colon():
    # ffmpeg 滤镜参数里 ':' 是分隔符，绝对路径必须转义，否则滤镜解析失败
    cmd = build_subtitle_command(
        "ffmpeg", source="/in/a.mp4", output="/out/b.mp4", srt_path="C:/tmp/c.srt"
    )
    vf = cmd[cmd.index("-vf") + 1]
    assert "C\\:/tmp/c.srt" in vf
