#!/usr/bin/env python3
from __future__ import annotations

import logging
import os
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QIcon, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from fit_ant_playback_core.ant_usb import AntUsbBroadcaster
from fit_ant_playback_core.fit_parser import FitFileParser, fitdecode_available
from fit_ant_playback_core.models import PowerCadenceRecord
from fit_ant_playback_core.playback_engine import FitPlaybackEngine, ManualBroadcastEngine
from fit_ant_playback_core.ride_simulator import (
    COURSE_TYPES,
    VARIABILITY_LEVELS,
    RideSimulationConfig,
    RideSimulationError,
    RideSimulationResult,
    calculate_normalized_power,
    generate_ride,
)
from fit_ant_playback_core.workout_parser import WorkoutFileParser, is_workout_file

DMRL_BLACK = "#000000"
DMRL_BLUE = "#021026"
DMRL_RED = "#CA0600"
DMRL_YELLOW = "#F6FF05"
INK = "#F4F7FA"
MUTED = "#9BA8B7"
PANEL = "#07162E"
PANEL_ALT = "#0A1E3D"
BORDER = "#1D3358"
GOOD = "#42D66D"
WARN = "#FFB700"
DMRL_FULL_NAME = "Dirty Mitten Racing League"
DMRL_SHORT_NAME = "Dirty Mitten"
DMRL_WEBSITE = "https://www.dirtymittenracing.com"
CREATOR_NAME = "The.Colonel"
CREATOR_WEBSITE = "https://lonewolfracing.cc"
LEGAL_DISCLAIMER_TITLE = "Testing and Diagnostics Only"
LEGAL_DISCLAIMER_TEXT = (
    "DMRL Virtual Power Lab is intended for controlled testing, diagnostics, "
    "development, demos, and equipment validation."
)
LEGAL_DISCLAIMER_DETAIL = (
    "Do not use this tool to cheat, falsify ride data, evade platform rules, "
    "or gain an unfair advantage in Zwift, TrainerRoad, Xert, or any other "
    "online racing, e-sports, training, leaderboard, ranking, achievement, "
    "or competition system.\n\n"
    "Only connect this tool to systems you are authorized to test, and follow "
    "the terms, event rules, and sporting standards that apply to those systems."
)


def resource_path(*parts: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base.joinpath(*parts)


class UiBridge(QObject):
    playback_update = Signal(object, float, int)
    playback_finished = Signal()
    playback_error = Signal(str)
    manual_update = Signal(int, int)
    manual_error = Signal(str)
    log_message = Signal(str)


class QtLogHandler(logging.Handler):
    def __init__(self, bridge: UiBridge) -> None:
        super().__init__()
        self.bridge = bridge

    def emit(self, record: logging.LogRecord) -> None:
        self.bridge.log_message.emit(self.format(record))


class MetricCard(QFrame):
    def __init__(self, label: str, value: str = "-", unit: str = "", *, accent: bool = False) -> None:
        super().__init__()
        self.setObjectName("metricCardAccent" if accent else "metricCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(4)

        self.label = QLabel(label.upper())
        self.label.setObjectName("metricLabel")
        self.value = QLabel(value)
        self.value.setObjectName("metricValueAccent" if accent else "metricValue")
        self.unit = QLabel(unit)
        self.unit.setObjectName("metricUnit")

        layout.addWidget(self.label)
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(self.value)
        row.addWidget(self.unit, 0, Qt.AlignBottom)
        row.addStretch(1)
        layout.addLayout(row)

    def set_metric(self, value: str, unit: str | None = None) -> None:
        self.value.setText(value)
        if unit is not None:
            self.unit.setText(unit)


class TimelineWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[PowerCadenceRecord] = []
        self.current_index = 0
        self.setMinimumHeight(220)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_records(self, records: list[PowerCadenceRecord]) -> None:
        self.records = records
        self.current_index = 0
        self.update()

    def set_current_index(self, index: int) -> None:
        self.current_index = max(0, min(index, len(self.records) - 1)) if self.records else 0
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(18, 18, -18, -24)

        painter.fillRect(self.rect(), QColor(PANEL))
        painter.setPen(QPen(QColor(BORDER), 1))
        painter.drawRoundedRect(rect, 10, 10)

        if len(self.records) < 2:
            painter.setPen(QColor(MUTED))
            painter.drawText(rect, Qt.AlignCenter, "Load or generate a ride to preview power and cadence")
            painter.end()
            return

        powers = [record.power for record in self.records]
        cadences = [record.cadence for record in self.records]
        max_power = max(max(powers), 1)
        max_cadence = max(max(cadences), 1)
        duration = max(self.records[-1].timestamp, 1.0)

        grid_pen = QPen(QColor("#17345F"), 1)
        painter.setPen(grid_pen)
        for fraction in (0.25, 0.5, 0.75):
            y = rect.top() + rect.height() * fraction
            painter.drawLine(rect.left(), y, rect.right(), y)

        power_path = QPainterPath()
        cadence_path = QPainterPath()
        for index, record in enumerate(self.records):
            x = rect.left() + (record.timestamp / duration) * rect.width()
            power_y = rect.bottom() - (record.power / max_power) * rect.height()
            cadence_y = rect.bottom() - (record.cadence / max_cadence) * rect.height()
            if index == 0:
                power_path.moveTo(QPointF(x, power_y))
                cadence_path.moveTo(QPointF(x, cadence_y))
            else:
                power_path.lineTo(QPointF(x, power_y))
                cadence_path.lineTo(QPointF(x, cadence_y))

        fill_path = QPainterPath(power_path)
        fill_path.lineTo(QPointF(rect.right(), rect.bottom()))
        fill_path.lineTo(QPointF(rect.left(), rect.bottom()))
        fill_path.closeSubpath()
        painter.fillPath(fill_path, QColor(246, 255, 5, 34))

        painter.setPen(QPen(QColor(DMRL_YELLOW), 2.4))
        painter.drawPath(power_path)
        painter.setPen(QPen(QColor("#7DB2FF"), 1.8))
        painter.drawPath(cadence_path)

        if self.current_index < len(self.records):
            record = self.records[self.current_index]
            cursor_x = rect.left() + (record.timestamp / duration) * rect.width()
            painter.setPen(QPen(QColor(DMRL_RED), 2))
            painter.drawLine(cursor_x, rect.top(), cursor_x, rect.bottom())

        painter.setPen(QColor(MUTED))
        painter.drawText(QRectF(rect.left(), rect.bottom() + 4, rect.width(), 18), Qt.AlignLeft, "Power")
        painter.setPen(QColor("#7DB2FF"))
        painter.drawText(QRectF(rect.left() + 58, rect.bottom() + 4, rect.width(), 18), Qt.AlignLeft, "Cadence")
        painter.end()


class DmrlMark(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(178, 66)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)

        painter.setPen(QPen(QColor(DMRL_RED), 2))
        painter.setBrush(QColor(DMRL_BLUE))
        painter.drawRoundedRect(rect, 8, 8)

        bands = (
            (QColor(DMRL_RED), 106, 130, 78, 102),
            (QColor(DMRL_YELLOW), 135, 150, 107, 122),
            (QColor(DMRL_RED), 156, 180, 128, 152),
        )
        for color, top_left, top_right, bottom_left, bottom_right in bands:
            band = QPainterPath()
            band.moveTo(rect.left() + top_left, rect.top())
            band.lineTo(rect.left() + top_right, rect.top())
            band.lineTo(rect.left() + bottom_right, rect.bottom())
            band.lineTo(rect.left() + bottom_left, rect.bottom())
            band.closeSubpath()
        painter.fillPath(band, color)

        painter.setPen(QColor(INK))
        font = QFont("Avenir Next", 23, QFont.Black)
        painter.setFont(font)
        painter.drawText(rect.adjusted(14, 0, -54, 0), Qt.AlignLeft | Qt.AlignVCenter, "DMRL")
        painter.end()


class KitHeading(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(92)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(0, 0, -1, -1)

        painter.setPen(QPen(QColor("#152640"), 1))
        painter.setBrush(QColor(DMRL_BLUE))
        painter.drawRoundedRect(rect, 8, 8)

        lower = QPainterPath()
        lower.moveTo(rect.left(), rect.center().y() + 12)
        lower.lineTo(rect.right(), rect.center().y() - 18)
        lower.lineTo(rect.right(), rect.bottom())
        lower.lineTo(rect.left(), rect.bottom())
        lower.closeSubpath()
        painter.fillPath(lower, QColor(DMRL_BLACK))

        red_band = QPainterPath()
        red_band.moveTo(rect.right() - 260, rect.top())
        red_band.lineTo(rect.right(), rect.top())
        red_band.lineTo(rect.right() - 88, rect.bottom())
        red_band.lineTo(rect.right() - 352, rect.bottom())
        red_band.closeSubpath()
        painter.fillPath(red_band, QColor(DMRL_RED))

        yellow_band = QPainterPath()
        yellow_band.moveTo(rect.right() - 142, rect.top())
        yellow_band.lineTo(rect.right() - 104, rect.top())
        yellow_band.lineTo(rect.right() - 198, rect.bottom())
        yellow_band.lineTo(rect.right() - 236, rect.bottom())
        yellow_band.closeSubpath()
        painter.fillPath(yellow_band, QColor(DMRL_YELLOW))

        painter.setPen(QPen(QColor(DMRL_YELLOW), 2))
        painter.drawLine(rect.left() + 18, rect.bottom() - 17, rect.right() - 18, rect.bottom() - 17)

        painter.setPen(QColor("#FFFFFF"))
        title_rect = rect.adjusted(22, 5, -250, -28)
        title_font = QFont("Avenir Next", 29, QFont.Black)
        while QFontMetrics(title_font).horizontalAdvance(DMRL_FULL_NAME.upper()) > title_rect.width() and title_font.pointSize() > 20:
            title_font.setPointSize(title_font.pointSize() - 1)
        painter.setFont(title_font)
        painter.drawText(title_rect, Qt.AlignLeft | Qt.AlignVCenter, DMRL_FULL_NAME.upper())

        painter.setPen(QColor(DMRL_YELLOW))
        sub_font = QFont("Avenir Next", 10, QFont.Bold)
        sub_font.setLetterSpacing(QFont.AbsoluteSpacing, 1.6)
        painter.setFont(sub_font)
        painter.drawText(rect.adjusted(24, 54, -22, -10), Qt.AlignLeft | Qt.AlignVCenter, "VIRTUAL POWER LAB")

        painter.setPen(QColor(DMRL_BLACK))
        badge_font = QFont("Avenir Next", 15, QFont.Black)
        painter.setFont(badge_font)
        painter.drawText(rect.adjusted(rect.width() - 155, 24, -22, -24), Qt.AlignCenter, "DMRL")
        painter.end()


class DmrlQtApp(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("DMRL Virtual Power Lab")
        icon_path = resource_path("assets", "dmrl_virtual_power_lab.icns")
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        self.resize(1280, 820)
        self.setMinimumSize(1080, 720)

        self.records: list[PowerCadenceRecord] = []
        self.broadcaster: AntUsbBroadcaster | None = None
        self.playback_engine: FitPlaybackEngine | None = None
        self.manual_engine: ManualBroadcastEngine | None = None
        self.playback_speed = 1.0
        self.is_playing = False
        self.is_paused = False
        self.manual_broadcasting = False
        self.current_index = 0
        self._manual_lock = threading.Lock()
        self._manual_power = 300
        self._manual_cadence = 85

        self.bridge = UiBridge()
        self.bridge.playback_update.connect(self._on_playback_update)
        self.bridge.playback_finished.connect(self._on_playback_finished)
        self.bridge.playback_error.connect(self._on_playback_error)
        self.bridge.manual_update.connect(self._on_manual_update)
        self.bridge.manual_error.connect(self._on_manual_error)
        self.bridge.log_message.connect(self._append_log)

        self.logger = logging.getLogger("fit_ant_playback")
        self._configure_logging()
        self._build_ui()
        self._apply_styles()
        self._sync_controls()
        self._append_log("DMRL Virtual Power Lab ready")
        if not fitdecode_available():
            self._append_log("WARNING: fitdecode is not installed; FIT activity loading is disabled")

    def _configure_logging(self) -> None:
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        for handler in list(self.logger.handlers):
            if isinstance(handler, QtLogHandler):
                self.logger.removeHandler(handler)
        handler = QtLogHandler(self.bridge)
        handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        self.logger.addHandler(handler)

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        shell = QHBoxLayout(root)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)

        shell.addWidget(self._build_nav(), 0)

        main = QWidget()
        main_layout = QVBoxLayout(main)
        main_layout.setContentsMargins(24, 18, 24, 18)
        main_layout.setSpacing(16)
        shell.addWidget(main, 1)

        main_layout.addLayout(self._build_header())
        main_layout.addLayout(self._build_metrics())

        self.timeline = TimelineWidget()
        main_layout.addWidget(self.timeline, 1)

        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_file_page())
        self.pages.addWidget(self._build_simulator_page())
        self.pages.addWidget(self._build_manual_page())
        self.pages.addWidget(self._build_logs_page())
        self.pages.addWidget(self._build_about_page())
        main_layout.addWidget(self.pages, 0)

    def _build_nav(self) -> QWidget:
        nav = QFrame()
        nav.setObjectName("nav")
        nav.setFixedWidth(236)
        layout = QVBoxLayout(nav)
        layout.setContentsMargins(18, 22, 18, 22)
        layout.setSpacing(12)

        brand = DmrlMark()
        subtitle = QLabel(DMRL_SHORT_NAME)
        subtitle.setObjectName("brandSub")
        layout.addWidget(brand)
        layout.addWidget(subtitle)
        tool_name = QLabel("Virtual Power Lab")
        tool_name.setObjectName("navFooter")
        layout.addWidget(tool_name)
        layout.addSpacing(18)

        self.nav_buttons: list[QPushButton] = []
        for index, label in enumerate(("File Playback", "Ride Simulator", "Manual Power", "Device & Logs", "About")):
            button = QPushButton(label)
            button.setObjectName("navButton")
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, i=index: self._select_page(i))
            layout.addWidget(button)
            self.nav_buttons.append(button)
        self.nav_buttons[0].setChecked(True)

        layout.addStretch(1)
        footer = QLabel("ANT+ Bike Power\nDevelopment Utility")
        footer.setObjectName("navFooter")
        layout.addWidget(footer)
        return nav

    def _build_header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        header.setSpacing(16)
        title_block = QVBoxLayout()
        title_block.setSpacing(8)
        title_block.addWidget(KitHeading())
        self.source_label = QLabel("No source loaded")
        self.source_label.setObjectName("sourceLabel")
        title_block.addWidget(self.source_label)
        header.addLayout(title_block, 1)

        status_block = QVBoxLayout()
        status_block.setSpacing(8)
        self.device_status = QLabel("ANT+ DISCONNECTED")
        self.device_status.setObjectName("statusPill")
        status_block.addWidget(self.device_status)

        self.connect_button = QPushButton("Connect ANT+")
        self.connect_button.setObjectName("primaryButton")
        self.connect_button.clicked.connect(self._connect_ant)
        status_block.addWidget(self.connect_button)
        status_block.addStretch(1)
        header.addLayout(status_block, 0)
        return header

    def _build_metrics(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)
        self.power_card = MetricCard("Power", "---", "W", accent=True)
        self.cadence_card = MetricCard("Cadence", "---", "RPM")
        self.elapsed_card = MetricCard("Elapsed", "00:00", "")
        self.avg_card = MetricCard("Average", "0", "W")
        self.np_card = MetricCard("NP", "0", "W")
        self.vi_card = MetricCard("VI", "-", "")
        for card in (
            self.power_card,
            self.cadence_card,
            self.elapsed_card,
            self.avg_card,
            self.np_card,
            self.vi_card,
        ):
            row.addWidget(card, 1)
        return row

    def _build_file_page(self) -> QWidget:
        page = self._page_frame("Choose Source")
        layout = QGridLayout(page)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(12)

        self.file_path = QLineEdit()
        self.file_path.setReadOnly(True)
        self.file_path.setPlaceholderText("Select a FIT, ZWO, ERG, MRC, XML, or XERT file")
        browse = QPushButton("Browse")
        browse.clicked.connect(self._browse_file)
        self.browse_button = browse

        self.ftp_spin = QSpinBox()
        self.ftp_spin.setRange(1, 2000)
        self.ftp_spin.setValue(250)
        self.ftp_spin.setSuffix(" FTP")

        self.speed_combo = QComboBox()
        self.speed_combo.addItems(["0.5x", "1.0x", "1.5x", "2.0x", "4.0x"])
        self.speed_combo.setCurrentText("1.0x")
        self.speed_combo.currentTextChanged.connect(self._on_speed_change)

        self.play_button = QPushButton("Play")
        self.play_button.setObjectName("successButton")
        self.play_button.clicked.connect(self._play)
        self.pause_button = QPushButton("Pause")
        self.pause_button.clicked.connect(self._pause)
        self.stop_button = QPushButton("Stop")
        self.stop_button.setObjectName("dangerButton")
        self.stop_button.clicked.connect(self._stop)

        layout.addWidget(QLabel("Input file"), 0, 0)
        layout.addWidget(self.file_path, 0, 1, 1, 4)
        layout.addWidget(browse, 0, 5)
        layout.addWidget(QLabel("Workout FTP"), 1, 0)
        layout.addWidget(self.ftp_spin, 1, 1)
        layout.addWidget(QLabel("Playback speed"), 1, 2)
        layout.addWidget(self.speed_combo, 1, 3)
        layout.addWidget(self.play_button, 1, 4)
        layout.addWidget(self.pause_button, 1, 5)
        layout.addWidget(self.stop_button, 1, 6)
        return page

    def _build_simulator_page(self) -> QWidget:
        page = self._page_frame("Ride Simulator")
        layout = QGridLayout(page)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(12)

        self.course_combo = QComboBox()
        self.course_combo.addItems(list(COURSE_TYPES))
        self.course_combo.setCurrentText("Rolling Course")
        self.variability_combo = QComboBox()
        self.variability_combo.addItems(list(VARIABILITY_LEVELS.keys()))
        self.variability_combo.setCurrentText("Moderate")
        self.duration_spin = QDoubleSpinBox()
        self.duration_spin.setRange(1, 600)
        self.duration_spin.setValue(45)
        self.duration_spin.setSuffix(" min")
        self.duration_spin.setDecimals(1)
        self.avg_power_spin = QSpinBox()
        self.avg_power_spin.setRange(1, 2000)
        self.avg_power_spin.setValue(220)
        self.avg_power_spin.setSuffix(" W avg")
        self.np_spin = QSpinBox()
        self.np_spin.setRange(1, 2500)
        self.np_spin.setValue(245)
        self.np_spin.setSuffix(" W NP")
        self.weight_spin = QDoubleSpinBox()
        self.weight_spin.setRange(1, 300)
        self.weight_spin.setValue(75)
        self.weight_spin.setSuffix(" kg")
        self.weight_spin.setDecimals(1)
        self.sim_cadence_spin = QSpinBox()
        self.sim_cadence_spin.setRange(40, 130)
        self.sim_cadence_spin.setValue(88)
        self.sim_cadence_spin.setSuffix(" RPM")
        generate = QPushButton("Generate Ride")
        generate.setObjectName("successButton")
        generate.clicked.connect(self._generate_simulated_ride)
        self.generate_button = generate

        controls = [
            ("Course", self.course_combo),
            ("Variability", self.variability_combo),
            ("Duration", self.duration_spin),
            ("Avg Power", self.avg_power_spin),
            ("Target NP", self.np_spin),
            ("Weight", self.weight_spin),
            ("Cadence", self.sim_cadence_spin),
        ]
        for index, (label, widget) in enumerate(controls):
            row = index // 4
            col = (index % 4) * 2
            layout.addWidget(QLabel(label), row, col)
            layout.addWidget(widget, row, col + 1)
        layout.addWidget(generate, 2, 6, 1, 2)

        self.sim_summary = QLabel("Generated rides load into File Playback and use the shared broadcast controls.")
        self.sim_summary.setObjectName("summaryText")
        layout.addWidget(self.sim_summary, 3, 0, 1, 8)
        return page

    def _build_manual_page(self) -> QWidget:
        page = self._page_frame("Manual Power")
        layout = QGridLayout(page)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(12)

        self.manual_power_spin = QSpinBox()
        self.manual_power_spin.setRange(0, 2000)
        self.manual_power_spin.setValue(300)
        self.manual_power_spin.setSuffix(" W")
        self.manual_power_spin.valueChanged.connect(lambda value: self._set_manual_state(power=value))
        self.manual_cadence_spin = QSpinBox()
        self.manual_cadence_spin.setRange(0, 200)
        self.manual_cadence_spin.setValue(85)
        self.manual_cadence_spin.setSuffix(" RPM")
        self.manual_cadence_spin.valueChanged.connect(lambda value: self._set_manual_state(cadence=value))
        self.manual_weight_spin = QDoubleSpinBox()
        self.manual_weight_spin.setRange(1, 300)
        self.manual_weight_spin.setValue(75)
        self.manual_weight_spin.setSuffix(" kg")
        self.manual_wkg_spin = QDoubleSpinBox()
        self.manual_wkg_spin.setRange(0, 30)
        self.manual_wkg_spin.setDecimals(2)
        self.manual_wkg_spin.setSingleStep(0.1)
        self.manual_wkg_spin.setSuffix(" W/kg")
        apply_wkg = QPushButton("Apply W/kg")
        apply_wkg.clicked.connect(self._apply_wkg)
        self.manual_start_button = QPushButton("Start Manual Broadcast")
        self.manual_start_button.setObjectName("successButton")
        self.manual_start_button.clicked.connect(self._start_manual)
        self.manual_stop_button = QPushButton("Stop Manual")
        self.manual_stop_button.setObjectName("dangerButton")
        self.manual_stop_button.clicked.connect(self._stop_manual)

        layout.addWidget(QLabel("Power"), 0, 0)
        layout.addWidget(self.manual_power_spin, 0, 1)
        layout.addWidget(QLabel("Cadence"), 0, 2)
        layout.addWidget(self.manual_cadence_spin, 0, 3)
        layout.addWidget(QLabel("Weight"), 1, 0)
        layout.addWidget(self.manual_weight_spin, 1, 1)
        layout.addWidget(QLabel("W/kg"), 1, 2)
        layout.addWidget(self.manual_wkg_spin, 1, 3)
        layout.addWidget(apply_wkg, 1, 4)
        quick_row = QHBoxLayout()
        quick_row.setSpacing(8)
        for watts in (0, 150, 200, 250, 283, 300, 350, 400, 500, 600, 800, 1000):
            button = QPushButton(str(watts))
            button.setObjectName("quickButton")
            button.clicked.connect(lambda _checked=False, w=watts: self.manual_power_spin.setValue(w))
            quick_row.addWidget(button)
        layout.addLayout(quick_row, 2, 0, 1, 7)
        layout.addWidget(self.manual_start_button, 3, 0, 1, 2)
        layout.addWidget(self.manual_stop_button, 3, 2, 1, 2)
        return page

    def _build_logs_page(self) -> QWidget:
        page = self._page_frame("Device & Logs")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        layout.addWidget(self.log_text, 1)
        return page

    def _build_about_page(self) -> QWidget:
        page = self._page_frame("About")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        title = QLabel("DMRL Virtual Power Lab")
        title.setObjectName("aboutTitle")
        layout.addWidget(title)

        about = QLabel(
            f"{DMRL_FULL_NAME}<br>"
            f"Created by {CREATOR_NAME}<br><br>"
            f'<a href="{DMRL_WEBSITE}">{DMRL_WEBSITE}</a><br>'
            f'<a href="{CREATOR_WEBSITE}">{CREATOR_WEBSITE}</a>'
        )
        about.setObjectName("aboutText")
        about.setOpenExternalLinks(True)
        about.setTextFormat(Qt.RichText)
        layout.addWidget(about)

        disclaimer = QLabel(
            "Testing and diagnostics only. Do not use this tool to cheat, falsify ride data, "
            "or gain an unfair advantage in online racing, e-sports, training, leaderboard, "
            "ranking, achievement, or competition systems."
        )
        disclaimer.setObjectName("summaryText")
        disclaimer.setWordWrap(True)
        layout.addWidget(disclaimer)
        layout.addStretch(1)
        return page

    def _page_frame(self, title: str) -> QFrame:
        frame = QFrame()
        frame.setObjectName("pageFrame")
        frame.setAccessibleName(title)
        return frame

    def _select_page(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        for button_index, button in enumerate(self.nav_buttons):
            button.setChecked(button_index == index)

    def _browse_file(self) -> None:
        filepath, _ = QFileDialog.getOpenFileName(
            self,
            "Select Activity or Workout File",
            "",
            "Supported Files (*.fit *.zwo *.erg *.mrc *.xml *.xert);;FIT Files (*.fit);;Workout Files (*.zwo *.erg *.mrc *.xml *.xert);;All Files (*.*)",
        )
        if filepath:
            self._load_input_file(filepath)

    def _load_input_file(self, filepath: str) -> None:
        try:
            path = Path(filepath)
            if path.suffix.lower() == ".fit":
                parser = FitFileParser()
                records = parser.parse(path)
                source_type = "FIT activity"
            elif is_workout_file(path):
                parser = WorkoutFileParser(ftp=self.ftp_spin.value())
                result = parser.parse(path)
                records = result.records
                source_type = result.format_name
            else:
                raise ValueError(f"Unsupported file type: {path.suffix or '(none)'}")

            if not records:
                QMessageBox.warning(self, "No Data", "No power or cadence data found in the selected file.")
                return
            self.file_path.setText(str(path))
            self._set_records(records, f"{path.name} ({source_type})")
            self._append_log(f"Loaded {len(records)} records from {path.name} ({source_type})")
        except Exception as exc:
            self._append_log(f"Error loading file: {exc}")
            QMessageBox.critical(self, "Load Error", str(exc))

    def _set_records(self, records: list[PowerCadenceRecord], source_label: str) -> None:
        self.records = records
        self.current_index = 0
        self.source_label.setText(source_label)
        self.timeline.set_records(records)

        powers = [record.power for record in records if record.power > 0]
        cadences = [record.cadence for record in records if record.cadence > 0]
        avg_power = sum(powers) / len(powers) if powers else 0.0
        avg_cadence = sum(cadences) / len(cadences) if cadences else 0.0
        normalized_power = calculate_normalized_power([record.power for record in records])
        variability_index = normalized_power / avg_power if avg_power > 0 else 0.0

        self.power_card.set_metric("---", "W")
        self.cadence_card.set_metric("---", "RPM")
        self.elapsed_card.set_metric(f"00:00 / {self._format_time(records[-1].timestamp)}")
        self.avg_card.set_metric(f"{avg_power:.0f}", "W")
        self.np_card.set_metric(f"{normalized_power:.0f}", "W")
        self.vi_card.set_metric(f"{variability_index:.2f}" if variability_index else "-", "")
        self._sync_controls()

    def _generate_simulated_ride(self) -> None:
        if self.is_playing or self.is_paused:
            QMessageBox.warning(self, "Playback Active", "Stop playback before generating a new ride.")
            return

        try:
            config = RideSimulationConfig(
                course_type=self.course_combo.currentText(),  # type: ignore[arg-type]
                duration_minutes=self.duration_spin.value(),
                average_power=self.avg_power_spin.value(),
                normalized_power=self.np_spin.value(),
                weight_kg=self.weight_spin.value(),
                preferred_cadence=self.sim_cadence_spin.value(),
                variability=VARIABILITY_LEVELS[self.variability_combo.currentText()],
            )
            result = generate_ride(config)
        except (KeyError, RideSimulationError, ValueError) as exc:
            self._append_log(f"Simulation error: {exc}")
            QMessageBox.critical(self, "Simulation Error", str(exc))
            return

        self._set_records(result.records, f"Simulated ride: {config.course_type}")
        self.file_path.setText(f"Generated: {config.course_type}")
        self._update_sim_summary(config, result)
        self._select_page(0)
        self._append_log(
            "Generated simulated ride: "
            f"{config.course_type}, {config.duration_minutes:g} min, "
            f"{result.average_power:.0f} W avg, {result.normalized_power:.0f} W NP, "
            f"VI {result.variability_index:.2f}"
        )

    def _update_sim_summary(
        self,
        config: RideSimulationConfig,
        result: RideSimulationResult,
    ) -> None:
        self.sim_summary.setText(
            "Loaded simulated course: "
            f"{config.course_type} | {result.average_power:.0f} W avg | "
            f"{result.normalized_power:.0f} W NP | VI {result.variability_index:.2f} | "
            f"{result.watts_per_kg:.2f} W/kg"
        )

    def _apply_wkg(self) -> None:
        watts = max(0, min(2000, int(round(self.manual_weight_spin.value() * self.manual_wkg_spin.value()))))
        self.manual_power_spin.setValue(watts)
        self._append_log(f"Manual power set to {watts} W from W/kg input")

    def _connect_ant(self) -> None:
        if self.broadcaster and self.broadcaster.running:
            self._stop(log=False)
            self._stop_manual(log=False)
            self.broadcaster.stop()
            self.broadcaster = None
            self.device_status.setText("ANT+ DISCONNECTED")
            self._append_log("ANT+ disconnected")
            self._sync_controls()
            return

        is_root = os.name == "nt" or not hasattr(os, "geteuid") or os.geteuid() == 0
        if not is_root:
            self._append_log("WARNING: ANT+ USB access may require admin privileges on macOS")
            self._append_log("If connection fails, restart with sudo or grant USB permissions")

        self._append_log("Connecting to ANT+ USB stick...")
        self.broadcaster = AntUsbBroadcaster(logger=self.logger)
        if self.broadcaster.start():
            self.device_status.setText("ANT+ CONNECTED")
            self._append_log("ANT+ connected successfully")
            self._append_log(f"Broadcasting Bike Power Device ID {self.broadcaster.DEVICE_NUMBER}")
        else:
            detail = self.broadcaster.last_error if self.broadcaster else None
            self.device_status.setText("ANT+ FAILED")
            self._append_log(f"Failed to connect to ANT+ stick: {detail or 'unknown error'}")
            QMessageBox.critical(
                self,
                "ANT+ Connection Failed",
                "Could not connect to the ANT+ USB stick.\n\n"
                f"{detail or ''}\n\n"
                "Make sure the stick is plugged in and no other app is using it.",
            )
            self.broadcaster = None
        self._sync_controls()

    def _on_speed_change(self, speed_text: str) -> None:
        self.playback_speed = float(speed_text.replace("x", ""))
        if self.playback_engine:
            self.playback_engine.set_speed(self.playback_speed)
        self._append_log(f"Playback speed set to {speed_text}")

    def _play(self) -> None:
        if self.manual_broadcasting:
            QMessageBox.warning(self, "Manual Broadcast Active", "Stop manual broadcasting before playback.")
            return
        if not self.records:
            QMessageBox.warning(self, "No Source", "Load a file or generate a ride first.")
            return
        if not self.broadcaster or not self.broadcaster.running:
            QMessageBox.warning(self, "ANT+ Not Connected", "Connect ANT+ before playback.")
            return

        if self.playback_engine and self.is_paused:
            self.playback_engine.resume()
            self.is_paused = False
            self.is_playing = True
            self._append_log("Playback resumed")
        else:
            self.playback_engine = FitPlaybackEngine(
                records=self.records,
                broadcast=self._broadcast_playback_record,
                on_update=lambda record, total, index: self.bridge.playback_update.emit(record, total, index),
                on_finished=self.bridge.playback_finished.emit,
                on_error=lambda exc: self.bridge.playback_error.emit(str(exc)),
                speed=self.playback_speed,
            )
            self.current_index = 0
            self.is_playing = True
            self.is_paused = False
            self.playback_engine.start()
            self._append_log("Playback started")
        self._sync_controls()

    def _broadcast_playback_record(self, record: PowerCadenceRecord) -> None:
        if not self.broadcaster or not self.broadcaster.running:
            raise RuntimeError("ANT+ disconnected")
        self.broadcaster.broadcast_power_cadence(record.power, record.cadence)

    def _pause(self) -> None:
        if not self.playback_engine:
            return
        self.playback_engine.pause()
        self.is_paused = True
        self.is_playing = True
        self._append_log("Playback paused")
        self._sync_controls()

    def _stop(self, *, log: bool = True) -> None:
        if self.playback_engine:
            self.playback_engine.stop()
            self.playback_engine = None
        self.is_playing = False
        self.is_paused = False
        self.current_index = 0
        self.timeline.set_current_index(0)
        self.power_card.set_metric("---", "W")
        self.cadence_card.set_metric("---", "RPM")
        if self.records:
            self.elapsed_card.set_metric(f"00:00 / {self._format_time(self.records[-1].timestamp)}")
        else:
            self.elapsed_card.set_metric("00:00")
        if log:
            self._append_log("Playback stopped")
        self._sync_controls()

    def _on_playback_update(self, record: PowerCadenceRecord, total_duration: float, index: int) -> None:
        self.current_index = index
        self.power_card.set_metric(str(record.power), "W")
        self.cadence_card.set_metric(str(record.cadence), "RPM")
        self.elapsed_card.set_metric(f"{self._format_time(record.timestamp)} / {self._format_time(total_duration)}")
        self.timeline.set_current_index(index)

    def _on_playback_finished(self) -> None:
        self._append_log("Playback finished")
        self._stop(log=False)

    def _on_playback_error(self, message: str) -> None:
        self._append_log(f"Playback error: {message}")
        QMessageBox.critical(self, "Playback Error", message)
        self._stop(log=False)

    def _set_manual_state(self, *, power: int | None = None, cadence: int | None = None) -> None:
        with self._manual_lock:
            if power is not None:
                self._manual_power = max(0, min(2000, int(power)))
            if cadence is not None:
                self._manual_cadence = max(0, min(200, int(cadence)))

    def _get_manual_state(self) -> tuple[int, int]:
        with self._manual_lock:
            return self._manual_power, self._manual_cadence

    def _start_manual(self) -> None:
        if self.is_playing:
            QMessageBox.warning(self, "Playback Active", "Stop playback before starting manual broadcast.")
            return
        if not self.broadcaster or not self.broadcaster.running:
            QMessageBox.warning(self, "ANT+ Not Connected", "Connect ANT+ before manual broadcast.")
            return

        self._set_manual_state(power=self.manual_power_spin.value(), cadence=self.manual_cadence_spin.value())
        self.manual_engine = ManualBroadcastEngine(
            get_values=self._get_manual_state,
            broadcast=self._broadcast_manual_values,
            on_update=lambda power, cadence: self.bridge.manual_update.emit(power, cadence),
            on_error=lambda exc: self.bridge.manual_error.emit(str(exc)),
        )
        self.manual_broadcasting = True
        self.manual_engine.start()
        self._append_log("Manual broadcast started")
        self._sync_controls()

    def _stop_manual(self, *, log: bool = True) -> None:
        if self.manual_engine:
            self.manual_engine.stop()
            self.manual_engine = None
        self.manual_broadcasting = False
        self.power_card.set_metric("---", "W")
        self.cadence_card.set_metric("---", "RPM")
        if log:
            self._append_log("Manual broadcast stopped")
        self._sync_controls()

    def _broadcast_manual_values(self, power: int, cadence: int) -> None:
        if not self.broadcaster or not self.broadcaster.running:
            raise RuntimeError("ANT+ disconnected")
        self.broadcaster.broadcast_power_cadence(power, cadence)

    def _on_manual_update(self, power: int, cadence: int) -> None:
        self.power_card.set_metric(str(power), "W")
        self.cadence_card.set_metric(str(cadence), "RPM")

    def _on_manual_error(self, message: str) -> None:
        self._append_log(f"Manual broadcast error: {message}")
        QMessageBox.critical(self, "Manual Broadcast Error", message)
        self._stop_manual(log=False)

    def _append_log(self, message: str) -> None:
        timestamp = time.strftime("%H:%M:%S")
        self.log_text.append(f"[{timestamp}] {message}")

    def _sync_controls(self) -> None:
        connected = bool(self.broadcaster and self.broadcaster.running)
        playback_active = self.is_playing or self.is_paused
        has_records = bool(self.records)

        self.connect_button.setText("Disconnect" if connected else "Connect ANT+")
        if connected:
            self.device_status.setText("ANT+ CONNECTED")
            self.device_status.setProperty("state", "connected")
        elif self.device_status.text() == "ANT+ FAILED":
            self.device_status.setProperty("state", "failed")
        else:
            self.device_status.setText("ANT+ DISCONNECTED")
            self.device_status.setProperty("state", "disconnected")
        self.device_status.style().unpolish(self.device_status)
        self.device_status.style().polish(self.device_status)

        self.play_button.setEnabled(has_records and connected and not self.manual_broadcasting and not self.is_playing)
        if self.is_paused:
            self.play_button.setEnabled(True)
            self.play_button.setText("Resume")
        else:
            self.play_button.setText("Play")
        self.pause_button.setEnabled(bool(self.playback_engine and self.is_playing and not self.is_paused))
        self.stop_button.setEnabled(playback_active)

        self.browse_button.setEnabled(not playback_active)
        self.ftp_spin.setEnabled(not playback_active)
        self.generate_button.setEnabled(not playback_active)
        self.manual_start_button.setEnabled(connected and not playback_active and not self.manual_broadcasting)
        self.manual_stop_button.setEnabled(self.manual_broadcasting)

    @staticmethod
    def _format_time(seconds: float) -> str:
        seconds_int = max(0, int(round(seconds)))
        hours = seconds_int // 3600
        minutes = (seconds_int % 3600) // 60
        secs = seconds_int % 60
        if hours:
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
        return f"{minutes:02d}:{secs:02d}"

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            f"""
            QMainWindow {{
                background: {DMRL_BLACK};
                color: {INK};
                font-family: "Avenir Next", "Inter", "Helvetica Neue", Arial, sans-serif;
            }}
            QWidget {{
                color: {INK};
                font-size: 14px;
            }}
            #nav {{
                background: {DMRL_BLACK};
                border-right: 1px solid {DMRL_RED};
            }}
            #brandSub {{
                color: {DMRL_YELLOW};
                font-size: 13px;
                font-weight: 800;
                text-transform: uppercase;
            }}
            #aboutTitle {{
                color: {DMRL_YELLOW};
                font-size: 24px;
                font-weight: 900;
            }}
            #aboutText {{
                color: {INK};
                font-size: 14px;
                font-weight: 700;
                line-height: 1.45;
            }}
            #aboutText a {{
                color: {DMRL_YELLOW};
            }}
            #navFooter {{
                color: {MUTED};
                font-size: 12px;
                line-height: 1.35;
            }}
            #navButton {{
                background: transparent;
                border: 1px solid transparent;
                border-radius: 6px;
                color: {MUTED};
                font-weight: 700;
                padding: 11px 12px;
                text-align: left;
            }}
            #navButton:hover {{
                background: {PANEL_ALT};
                border-color: {BORDER};
                color: {INK};
            }}
            #navButton:checked {{
                background: {DMRL_RED};
                border-color: {DMRL_RED};
                color: white;
            }}
            #sourceLabel {{
                background: #050D19;
                border-left: 3px solid {DMRL_YELLOW};
                border-radius: 4px;
                color: {MUTED};
                font-size: 13px;
                font-weight: 800;
                padding: 7px 10px;
            }}
            #statusPill {{
                background: {PANEL_ALT};
                border: 1px solid {BORDER};
                border-radius: 6px;
                color: {WARN};
                font-size: 12px;
                font-weight: 900;
                padding: 9px 12px;
            }}
            #statusPill[state="connected"] {{
                border-color: {GOOD};
                color: {GOOD};
            }}
            #statusPill[state="failed"] {{
                border-color: {DMRL_RED};
                color: {DMRL_RED};
            }}
            #metricCard, #metricCardAccent, #pageFrame {{
                background: {PANEL};
                border: 1px solid {BORDER};
                border-radius: 8px;
            }}
            #metricCardAccent {{
                border-color: {DMRL_YELLOW};
                background: {PANEL_ALT};
            }}
            #metricLabel {{
                color: {MUTED};
                font-size: 11px;
                font-weight: 900;
            }}
            #metricValue, #metricValueAccent {{
                color: {INK};
                font-size: 30px;
                font-weight: 900;
            }}
            #metricValueAccent {{
                color: {DMRL_YELLOW};
            }}
            #metricUnit {{
                color: {MUTED};
                font-size: 12px;
                font-weight: 800;
            }}
            QLabel {{
                color: {INK};
                font-weight: 700;
            }}
            #summaryText {{
                color: {MUTED};
                font-size: 13px;
                font-weight: 600;
            }}
            QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTextEdit {{
                background: #091B35;
                border: 1px solid {BORDER};
                border-radius: 6px;
                color: {INK};
                padding: 8px 10px;
                selection-background-color: {DMRL_RED};
            }}
            QTextEdit {{
                font-family: Menlo, Monaco, Consolas, monospace;
                font-size: 12px;
            }}
            QPushButton {{
                background: #10284F;
                border: 1px solid #23446F;
                border-radius: 6px;
                color: {INK};
                font-weight: 800;
                padding: 9px 13px;
            }}
            QPushButton:hover {{
                background: #173967;
                border-color: #376396;
            }}
            QPushButton:disabled {{
                background: #07111F;
                border-color: #15243A;
                color: #526174;
            }}
            #primaryButton {{
                background: {DMRL_YELLOW};
                border-color: {DMRL_YELLOW};
                color: {DMRL_BLACK};
            }}
            #successButton {{
                background: {DMRL_RED};
                border-color: {DMRL_RED};
                color: white;
            }}
            #dangerButton {{
                background: #2A0B12;
                border-color: {DMRL_RED};
                color: #FFB4B0;
            }}
            #quickButton {{
                min-width: 42px;
                padding: 7px 8px;
            }}
            """
        )

    def show_legal_disclaimer(self) -> None:
        message = QMessageBox(self)
        message.setWindowTitle(LEGAL_DISCLAIMER_TITLE)
        message.setIcon(QMessageBox.Icon.Warning)
        message.setText(LEGAL_DISCLAIMER_TEXT)
        message.setInformativeText(LEGAL_DISCLAIMER_DETAIL)
        message.setStandardButtons(QMessageBox.StandardButton.Ok)
        message.setDefaultButton(QMessageBox.StandardButton.Ok)
        message.exec()
        self._append_log("Startup disclaimer acknowledged")

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        self._stop(log=False)
        self._stop_manual(log=False)
        if self.broadcaster:
            self.broadcaster.stop()
        event.accept()


def main() -> None:
    if not fitdecode_available():
        print("Warning: fitdecode library not installed")
        print("FIT file loading will not work until you run: pip install fitdecode")

    app = QApplication(sys.argv)
    window = DmrlQtApp()
    window.show()
    QTimer.singleShot(250, window.show_legal_disclaimer)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
