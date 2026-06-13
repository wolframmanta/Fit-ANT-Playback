#!/usr/bin/env python3
from __future__ import annotations

import os
import struct
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QPainterPath, QPen

DMRL_BLACK = "#000000"
DMRL_BLUE = "#021026"
DMRL_RED = "#CA0600"
DMRL_YELLOW = "#F6FF05"
INK = "#FFFFFF"

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
ICNS_SPECS = (
    (16, "icp4"),
    (32, "icp5"),
    (64, "icp6"),
    (128, "ic07"),
    (256, "ic08"),
    (512, "ic09"),
    (1024, "ic10"),
    (32, "ic11"),
    (64, "ic12"),
    (256, "ic13"),
    (512, "ic14"),
)


def _font(family: str, size: int, weight: QFont.Weight) -> QFont:
    font = QFont(family, size, weight)
    font.setLetterSpacing(QFont.AbsoluteSpacing, 0)
    return font


def render(size: int, path: Path) -> None:
    image = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)

    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.scale(size / 1024, size / 1024)

    outer = QRectF(24, 24, 976, 976)
    clip = QPainterPath()
    clip.addRoundedRect(outer, 190, 190)
    painter.setClipPath(clip)

    painter.fillPath(clip, QColor(DMRL_BLUE))

    lower = QPainterPath()
    lower.moveTo(24, 646)
    lower.lineTo(1000, 492)
    lower.lineTo(1000, 1000)
    lower.lineTo(24, 1000)
    lower.closeSubpath()
    painter.fillPath(lower, QColor(DMRL_BLACK))

    red_band = QPainterPath()
    red_band.moveTo(602, 24)
    red_band.lineTo(1000, 24)
    red_band.lineTo(814, 1000)
    red_band.lineTo(416, 1000)
    red_band.closeSubpath()
    painter.fillPath(red_band, QColor(DMRL_RED))

    yellow_band = QPainterPath()
    yellow_band.moveTo(714, 24)
    yellow_band.lineTo(776, 24)
    yellow_band.lineTo(584, 1000)
    yellow_band.lineTo(520, 1000)
    yellow_band.closeSubpath()
    painter.fillPath(yellow_band, QColor(DMRL_YELLOW))

    edge_pen = QPen(QColor(DMRL_RED), 20)
    painter.setPen(edge_pen)
    painter.drawPath(clip)

    painter.setClipping(False)
    painter.setPen(QColor(0, 0, 0, 125))
    painter.setFont(_font("Avenir Next", 174, QFont.Black))
    painter.drawText(QRectF(82, 244, 852, 212), Qt.AlignLeft | Qt.AlignVCenter, "DMRL")

    painter.setPen(QColor(INK))
    painter.drawText(QRectF(72, 232, 852, 212), Qt.AlignLeft | Qt.AlignVCenter, "DMRL")

    painter.setPen(QColor(DMRL_YELLOW))
    painter.setFont(_font("Avenir Next", 48, QFont.Bold))
    painter.drawText(QRectF(90, 478, 640, 72), Qt.AlignLeft | Qt.AlignVCenter, "VIRTUAL POWER")

    meter = QRectF(102, 714, 456, 154)
    painter.setPen(QPen(QColor(DMRL_YELLOW), 18, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    waveform = QPainterPath()
    waveform.moveTo(meter.left(), meter.bottom() - 42)
    waveform.cubicTo(meter.left() + 74, meter.bottom() - 42, meter.left() + 82, meter.top() + 12, meter.left() + 150, meter.top() + 12)
    waveform.cubicTo(meter.left() + 234, meter.top() + 12, meter.left() + 218, meter.bottom() - 30, meter.left() + 304, meter.bottom() - 30)
    waveform.cubicTo(meter.left() + 370, meter.bottom() - 30, meter.left() + 386, meter.top() + 44, meter.right(), meter.top() + 44)
    painter.drawPath(waveform)

    painter.setPen(Qt.NoPen)
    for index, height in enumerate((48, 82, 126, 68)):
        x = 650 + index * 72
        painter.setBrush(QColor(DMRL_YELLOW if index != 2 else INK))
        painter.drawRoundedRect(QRectF(x, 838 - height, 38, height), 12, 12)

    painter.end()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not image.save(str(path)):
        raise RuntimeError(f"Could not write {path}")


def write_icns(path: Path) -> None:
    chunks: list[bytes] = []
    with tempfile.TemporaryDirectory(prefix="fit-ant-icns-") as tmp:
        tmp_path = Path(tmp)
        for size, icon_type in ICNS_SPECS:
            png_path = tmp_path / f"{icon_type}_{size}.png"
            render(size, png_path)
            data = png_path.read_bytes()
            chunks.append(icon_type.encode("ascii") + struct.pack(">I", len(data) + 8) + data)

    payload = b"".join(chunks)
    path.write_bytes(b"icns" + struct.pack(">I", len(payload) + 8) + payload)


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    _app = QGuiApplication.instance() or QGuiApplication([])
    ASSETS.mkdir(exist_ok=True)

    preview_path = ASSETS / "dmrl_virtual_power_lab_1024.png"
    render(1024, preview_path)
    icon_path = ASSETS / "dmrl_virtual_power_lab.icns"
    write_icns(icon_path)

    print(f"Wrote {preview_path}")
    print(f"Wrote {icon_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
