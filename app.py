import sys
import os
import time
from typing import Optional, Callable
from PySide6.QtCore import Qt, QPropertyAnimation, QParallelAnimationGroup, QEasingCurve, QPoint, Signal, QTimer, QTime
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtGui import (
    QColor, QPainter, QBrush, QPen, QIcon, QPixmap, QFont,
    QGuiApplication
)
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QSlider, QComboBox, QSystemTrayIcon, QMenu,
    QGraphicsDropShadowEffect, QFrame, QTimeEdit, QCheckBox,
    QStackedWidget, QButtonGroup, QGraphicsOpacityEffect, QScrollArea,
    QLineEdit
)

from ble_controller import BleWorker, load_settings, save_settings
from color_wheel import ColorWheel
from theme_helper import get_taskbar_color

# Paleta de Cores com offsets calibrados para compensar a física da fita LED
PRESET_COLORS = [
    ("#FF0000", "Vermelho Puro", 255, 0, 0),
    ("#FF2000", "Laranja Intenso", 255, 18, 0),
    ("#FF5000", "Laranja Solar", 255, 45, 0),
    ("#FFAA00", "Âmbar Dourado", 255, 110, 0),
    ("#00FF00", "Verde Esmeralda", 0, 255, 0),
    ("#00F5FF", "Ciano Elétrico", 0, 245, 255),
    ("#0044FF", "Azul Real", 0, 68, 255),
    ("#7000FF", "Roxo Profundo", 112, 0, 255),
    ("#FF0055", "Magenta Vivo", 255, 0, 85),
    ("#FF8030", "Branco Quente (Warm)", 255, 128, 48),
]

DYNAMIC_MODES = [
    (0x8B, "7 Cores Fade"),
    (0x94, "7 Cores Jump"),
    (0x95, "7 Cores Strobe"),
    (0x87, "Vermelho Fade"),
    (0x88, "Verde Fade"),
    (0x89, "Azul Fade"),
    (0x8A, "Amarelo Fade"),
    (0x96, "Vermelho Strobe"),
    (0x97, "Verde Strobe"),
    (0x98, "Azul Strobe"),
]

class SmartTimeEdit(QLineEdit):
    """
    Campo de texto inteligente para horários:
    - Permite digitar 1900 -> 19:00, 1745 -> 17:45, 17,45 -> 17:45, 19:00 -> 19:00
    - Preenche com zeros à direita quando tem menos dígitos:
      '190' -> 19:00, '195' -> 19:50, '12' -> 12:00, '7' -> 07:00
    """
    timeChanged = Signal(QTime)

    def __init__(self, initial_time_str="00:00", parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setMaxLength(8)
        self.setPlaceholderText("00:00")
        self._current_time = QTime(0, 0)
        self.setTime(initial_time_str)
        self.editingFinished.connect(self._format_and_emit)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self._format_and_emit()

    def setTime(self, val):
        if isinstance(val, QTime):
            self._current_time = val
            self.setText(val.toString("HH:mm"))
        elif isinstance(val, str):
            try:
                parts = val.replace(",", ":").split(":")
                h = int(parts[0])
                m = int(parts[1]) if len(parts) > 1 else 0
                self._current_time = QTime(max(0, min(23, h)), max(0, min(59, m)))
            except Exception:
                self._current_time = QTime(0, 0)
            self.setText(self._current_time.toString("HH:mm"))

    def time(self) -> QTime:
        return self._current_time

    def _format_and_emit(self):
        raw = self.text().strip().replace(",", ":").replace(".", ":").replace("-", ":")
        if not raw:
            self.setText(self._current_time.toString("HH:mm"))
            return

        h = 0
        m = 0

        if ":" in raw:
            parts = [p.strip() for p in raw.split(":") if p.strip()]
            try:
                if len(parts) >= 2:
                    h_val = int(parts[0])
                    m_str = parts[1]
                    if len(m_str) == 1:
                        m_str += "0"
                    m_val = int(m_str[:2])
                elif len(parts) == 1:
                    h_val = int(parts[0])
                    m_val = 0
                else:
                    h_val, m_val = 0, 0
                h = max(0, min(23, h_val))
                m = max(0, min(59, m_val))
            except Exception:
                self.setText(self._current_time.toString("HH:mm"))
                return
        else:
            digits = "".join(ch for ch in raw if ch.isdigit())
            if not digits:
                self.setText(self._current_time.toString("HH:mm"))
                return

            if len(digits) >= 4:
                try:
                    h = max(0, min(23, int(digits[:2])))
                    m = max(0, min(59, int(digits[2:4])))
                except Exception:
                    h, m = 0, 0
            elif len(digits) == 3:
                # Exemplo do usuário: 190 -> 19:00, 195 -> 19:50
                try:
                    h = max(0, min(23, int(digits[:2])))
                    m = max(0, min(59, int(digits[2] + "0")))
                except Exception:
                    h, m = 0, 0
            elif len(digits) == 2:
                # Exemplo do usuário: 12 -> 12:00
                try:
                    h = max(0, min(23, int(digits[:2])))
                    m = 0
                except Exception:
                    h, m = 0, 0
            elif len(digits) == 1:
                # 7 -> 07:00
                try:
                    h = max(0, min(23, int(digits)))
                    m = 0
                except Exception:
                    h, m = 0, 0

        self._current_time = QTime(h, m)
        formatted = self._current_time.toString("HH:mm")
        self.setText(formatted)
        self.timeChanged.emit(self._current_time)


class AnimatedStackedWidget(QStackedWidget):
    """QStackedWidget com transição suave de Fade e Slide estilo Windows 11 Fluent."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._fade_anim = None
        self._pos_anim = None
        self._anim_group = None

    def slide_to_index(self, new_idx: int):
        cur_idx = self.currentIndex()
        if new_idx == cur_idx:
            return

        next_widget = self.widget(new_idx)
        if not next_widget:
            self.setCurrentIndex(new_idx)
            return

        direction = 1 if new_idx > cur_idx else -1
        offset = 14 * direction

        # Configura opacidade e posição inicial
        opacity_effect = QGraphicsOpacityEffect(next_widget)
        next_widget.setGraphicsEffect(opacity_effect)
        opacity_effect.setOpacity(0.0)

        orig_pos = next_widget.pos()
        start_pos = QPoint(orig_pos.x() + offset, orig_pos.y())
        next_widget.move(start_pos)

        self.setCurrentIndex(new_idx)

        # Animação combinada de fade-in + micro slide
        self._fade_anim = QPropertyAnimation(opacity_effect, b"opacity")
        self._fade_anim.setDuration(180)
        self._fade_anim.setStartValue(0.0)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.setEasingCurve(QEasingCurve.OutCubic)

        self._pos_anim = QPropertyAnimation(next_widget, b"pos")
        self._pos_anim.setDuration(180)
        self._pos_anim.setStartValue(start_pos)
        self._pos_anim.setEndValue(orig_pos)
        self._pos_anim.setEasingCurve(QEasingCurve.OutCubic)

        self._anim_group = QParallelAnimationGroup(self)
        self._anim_group.addAnimation(self._fade_anim)
        self._anim_group.addAnimation(self._pos_anim)

        def on_finished():
            next_widget.setGraphicsEffect(None)
            next_widget.move(orig_pos)

        self._anim_group.finished.connect(on_finished)
        self._anim_group.start()

class ModernCard(QFrame):
    """Container estilizado estilo Obsidian / macOS Popover."""
    def __init__(self, flyout_window=None, parent=None):
        super().__init__(parent)
        self.setObjectName("cardContainer")
        self.flyout = flyout_window

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        op = 85
        sync_tb = True
        thm = "Obsidian"
        if self.flyout and hasattr(self.flyout, 'settings'):
            op = self.flyout.settings.get("opacity", 85)
            sync_tb = self.flyout.settings.get("sync_taskbar_color", True)
            thm = self.flyout.settings.get("accent_theme", "Obsidian")

        bg_color = get_taskbar_color(opacity_percent=op, sync_taskbar=sync_tb, theme_name=thm)
        painter.setBrush(QBrush(bg_color))
        # Borda sutil de vidro fosco (subtle translucent border)
        painter.setPen(QPen(QColor(255, 255, 255, 28), 1))
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 18, 18)

class FlyoutWindow(QWidget):
    statusSignal = Signal(str, bool)
    timerReadSignal = Signal(dict)

    def __init__(self, ble_worker: BleWorker, on_icon_refresh: Optional[Callable] = None):
        super().__init__()
        self.ble = ble_worker
        self.settings = self.ble.settings
        self.on_icon_refresh = on_icon_refresh
        self.is_showing = False
        self._last_hide_time = 0.0

        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool |
            Qt.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(340, 535)

        self._init_ui()
        self._init_animations()
        self.statusSignal.connect(self._update_status_ui)
        self.timerReadSignal.connect(self._apply_hardware_timer_ui)

        # Timer local caso o firmware do LED perca a hora ou descarte timers
        self._sched_timer = QTimer(self)
        self._sched_timer.setInterval(10000)  # Checa a cada 10s
        self._sched_timer.timeout.connect(self._check_local_schedule)
        self._sched_timer.start()
        self._last_triggered_minute = ""

    def _init_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(10, 10, 10, 10)

        self.card = ModernCard(self, self)
        shadow = QGraphicsDropShadowEffect(self.card)
        shadow.setBlurRadius(30)
        shadow.setColor(QColor(0, 0, 0, 180))
        shadow.setOffset(0, 8)
        self.card.setGraphicsEffect(shadow)

        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(18, 18, 18, 18)
        card_layout.setSpacing(14)

        # 1. HEADER (Design limpo e tipografia moderna)
        header_layout = QHBoxLayout()
        header_layout.setSpacing(10)

        # Ícone de status sutil
        self.indicator_dot = QFrame()
        self.indicator_dot.setFixedSize(8, 8)
        self.indicator_dot.setStyleSheet("background: #00E676; border-radius: 4px;")

        status_col = QVBoxLayout()
        status_col.setSpacing(2)

        self.lbl_title = QLabel("Lotus Lantern")
        self.lbl_title.setStyleSheet("color: #FFFFFF; font-size: 15px; font-weight: 700; font-family: 'Segoe UI Variable Display', 'Segoe UI', sans-serif; letter-spacing: -0.2px;")

        self.lbl_status = QLabel("Conectando ao LED...")
        self.lbl_status.setStyleSheet("color: #8C8E9A; font-size: 11px; font-family: 'Segoe UI', sans-serif; font-weight: 500;")
        self.lbl_status.setCursor(Qt.PointingHandCursor)
        self.lbl_status.setToolTip("Clique para forçar reconexão")
        self.lbl_status.mousePressEvent = lambda ev: self.ble.trigger_reconnect()

        status_col.addWidget(self.lbl_title)
        status_col.addWidget(self.lbl_status)

        header_layout.addWidget(self.indicator_dot)
        header_layout.addLayout(status_col)
        header_layout.addStretch()

        # Botão Power Minimalista Estilo Fluent Control Center
        self.btn_power = QPushButton("\uE7E8")
        self.btn_power.setFixedSize(34, 34)
        self.btn_power.setCursor(Qt.PointingHandCursor)
        self.btn_power.clicked.connect(self._toggle_power)
        self._update_power_button_style(self.settings.get("power", True))
        header_layout.addWidget(self.btn_power)

        card_layout.addLayout(header_layout)

        # 2. SEGMENTED PILL TABS (Estilo iOS / macOS Control Center)
        tab_container = QFrame()
        tab_container.setStyleSheet("""
            QFrame {
                background: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(255, 255, 255, 0.07);
                border-radius: 10px;
                padding: 2px;
            }
        """)
        tab_layout = QHBoxLayout(tab_container)
        tab_layout.setContentsMargins(3, 3, 3, 3)
        tab_layout.setSpacing(4)
        self.tab_group = QButtonGroup(self)

        self.tab_color_btn = QPushButton("Cores")
        self.tab_mode_btn = QPushButton("Efeitos")
        self.tab_timer_btn = QPushButton("Horários")
        self.tab_config_btn = QPushButton("Ajustes")

        pill_style = """
            QPushButton {
                background: transparent;
                color: #8E909B;
                border: none;
                border-radius: 7px;
                padding: 6px 10px;
                font-size: 11px;
                font-weight: 600;
                font-family: 'Segoe UI', sans-serif;
            }
            QPushButton:hover {
                color: #FFFFFF;
                background: rgba(255, 255, 255, 0.05);
            }
            QPushButton:checked {
                background: rgba(255, 255, 255, 0.12);
                color: #FFFFFF;
                font-weight: 700;
            }
        """

        for i, b in enumerate([self.tab_color_btn, self.tab_mode_btn, self.tab_timer_btn, self.tab_config_btn]):
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(pill_style)
            self.tab_group.addButton(b, i)
            tab_layout.addWidget(b)

        self.tab_group.buttonClicked.connect(self._on_tab_changed)
        self.tab_color_btn.setChecked(True)
        card_layout.addWidget(tab_container)

        # 3. STACKED WIDGET COM TRANSIÇÃO ANIMADA
        self.stack = AnimatedStackedWidget(self)
        self.stack.setFixedHeight(385)

        # --- ABA 1: CORES ---
        tab_color_widget = QWidget()
        color_vbox = QVBoxLayout(tab_color_widget)
        color_vbox.setContentsMargins(0, 0, 0, 0)
        color_vbox.setSpacing(10)

        # Cartão central de gradiente com visual moderno
        center_card = QFrame()
        center_card.setStyleSheet("""
            QFrame {
                background: rgba(255, 255, 255, 0.03);
                border: 1px solid rgba(255, 255, 255, 0.06);
                border-radius: 16px;
            }
        """)
        center_layout = QVBoxLayout(center_card)
        center_layout.setContentsMargins(12, 10, 12, 10)
        center_layout.setSpacing(8)

        # Barra de status da cor atual (preview + hex pill)
        info_row = QHBoxLayout()
        info_row.setSpacing(8)

        self.preview_dot = QFrame()
        self.preview_dot.setFixedSize(14, 14)
        cur_c = self.settings.get("color", [255, 0, 128])
        hex_cur = f"#{cur_c[0]:02X}{cur_c[1]:02X}{cur_c[2]:02X}"
        self.preview_dot.setStyleSheet(f"background: {hex_cur}; border-radius: 7px; border: 1.5px solid rgba(255, 255, 255, 0.4);")

        self.lbl_color_hex = QLabel(hex_cur)
        self.lbl_color_hex.setStyleSheet("color: #FFFFFF; font-size: 11px; font-weight: 700; font-family: 'Segoe UI', monospace; letter-spacing: 0.5px;")

        info_row.addWidget(self.preview_dot)
        info_row.addWidget(self.lbl_color_hex)
        info_row.addStretch()
        center_layout.addLayout(info_row)

        # Seletor de Cores Roda Cromática
        wheel_box = QHBoxLayout()
        wheel_box.addStretch()
        self.wheel = ColorWheel()
        self.wheel.setColor(QColor(*cur_c))
        self.wheel.colorChanged.connect(self._on_wheel_color_changed)
        wheel_box.addWidget(self.wheel)
        wheel_box.addStretch()
        center_layout.addLayout(wheel_box)

        color_vbox.addWidget(center_card)

        # Grid / Carrossel em Pílula de Cores Rápidas
        palette_card = QFrame()
        palette_card.setStyleSheet("""
            QFrame {
                background: rgba(255, 255, 255, 0.04);
                border: 1px solid rgba(255, 255, 255, 0.06);
                border-radius: 12px;
            }
        """)
        palette_layout = QVBoxLayout(palette_card)
        palette_layout.setContentsMargins(8, 6, 8, 6)
        palette_layout.setSpacing(4)

        row1 = QHBoxLayout()
        row1.setSpacing(6)
        row1.addStretch()
        for hex_val, tip, pr, pg, pb in PRESET_COLORS[:5]:
            btn_p = self._create_preset_btn(hex_val, tip, pr, pg, pb)
            row1.addWidget(btn_p)
        row1.addStretch()
        palette_layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(6)
        row2.addStretch()
        for hex_val, tip, pr, pg, pb in PRESET_COLORS[5:]:
            btn_p = self._create_preset_btn(hex_val, tip, pr, pg, pb)
            row2.addWidget(btn_p)
        row2.addStretch()
        palette_layout.addLayout(row2)

        color_vbox.addWidget(palette_card)
        color_vbox.addSpacing(6)

        # Controle de Brilho - exclusivo da aba Cores
        bright_card = QFrame()
        bright_card.setStyleSheet("background: rgba(255, 255, 255, 0.04); border-radius: 12px; border: 1px solid rgba(255, 255, 255, 0.06); padding: 8px 12px;")
        br_layout = QVBoxLayout(bright_card)
        br_layout.setContentsMargins(4, 4, 4, 4)
        br_layout.setSpacing(6)

        br_title_row = QHBoxLayout()
        lbl_br_title = QLabel("Brilho")
        lbl_br_title.setStyleSheet("color: #8C8E9A; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; font-family: 'Segoe UI';")
        self.lbl_br_val = QLabel(f"{self.settings.get('brightness', 85)}%")
        self.lbl_br_val.setStyleSheet("color: #FFFFFF; font-size: 12px; font-weight: 700; font-family: 'Segoe UI';")
        br_title_row.addWidget(lbl_br_title)
        br_title_row.addStretch()
        br_title_row.addWidget(self.lbl_br_val)
        br_layout.addLayout(br_title_row)

        self.slider_bright = QSlider(Qt.Horizontal)
        self.slider_bright.setRange(0, 100)
        self.slider_bright.setValue(self.settings.get("brightness", 85))
        self.slider_bright.setStyleSheet(self._slider_style())
        self.slider_bright.valueChanged.connect(self._on_brightness_changed)
        br_layout.addWidget(self.slider_bright)

        color_vbox.addWidget(bright_card)
        color_vbox.addSpacing(6)
        self.stack.addWidget(tab_color_widget)

        # --- ABA 2: EFEITOS DINÂMICOS ---
        tab_mode_widget = QWidget()
        mode_vbox = QVBoxLayout(tab_mode_widget)
        mode_vbox.setContentsMargins(4, 6, 4, 0)
        mode_vbox.setSpacing(12)

        lbl_mode_title = QLabel("Efeito Selecionado")
        lbl_mode_title.setStyleSheet("color: #8C8E9A; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; font-family: 'Segoe UI';")
        mode_vbox.addWidget(lbl_mode_title)

        self.cmb_mode = QComboBox()
        self.cmb_mode.setStyleSheet("""
            QComboBox {
                background: rgba(255, 255, 255, 0.06);
                color: #FFFFFF;
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 10px;
                padding: 8px 12px;
                font-size: 13px;
                font-family: 'Segoe UI', sans-serif;
            }
            QComboBox:hover {
                background: rgba(255, 255, 255, 0.09);
                border: 1px solid rgba(255, 255, 255, 0.18);
            }
            QComboBox::drop-down {
                border: none;
                width: 24px;
            }
            QComboBox QAbstractItemView {
                background: #18191E;
                color: #FFF;
                selection-background-color: rgba(255, 255, 255, 0.12);
                border: 1px solid rgba(255, 255, 255, 0.15);
                border-radius: 8px;
                padding: 4px;
            }
        """)
        for m_id, m_name in DYNAMIC_MODES:
            self.cmb_mode.addItem(m_name, m_id)

        # Seleciona o modo salvo
        saved_mode = self.settings.get("mode", 0x8B)
        idx = self.cmb_mode.findData(saved_mode)
        if idx >= 0:
            self.cmb_mode.setCurrentIndex(idx)

        mode_vbox.addWidget(self.cmb_mode)

        # Botão de confirmação/aplicação do efeito
        self.btn_apply_mode = QPushButton("Aplicar Efeito")
        self.btn_apply_mode.setCursor(Qt.PointingHandCursor)
        self.btn_apply_mode.setStyleSheet("""
            QPushButton {
                background: rgba(255, 255, 255, 0.10);
                color: #FFFFFF;
                border: 1px solid rgba(255, 255, 255, 0.18);
                border-radius: 10px;
                padding: 8px 16px;
                font-size: 12px;
                font-weight: 600;
                font-family: 'Segoe UI', sans-serif;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.18);
                border: 1px solid rgba(255, 255, 255, 0.3);
            }
            QPushButton:pressed {
                background: rgba(255, 255, 255, 0.08);
            }
        """)
        self.btn_apply_mode.clicked.connect(self._apply_current_mode)
        mode_vbox.addWidget(self.btn_apply_mode)

        lbl_spd = QLabel("Velocidade")
        lbl_spd.setStyleSheet("color: #8C8E9A; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; font-family: 'Segoe UI'; margin-top: 6px;")
        mode_vbox.addWidget(lbl_spd)

        self.slider_speed = QSlider(Qt.Horizontal)
        self.slider_speed.setRange(1, 100)
        self.slider_speed.setValue(self.settings.get("speed", 80))
        self.slider_speed.setStyleSheet(self._slider_style())
        self.slider_speed.valueChanged.connect(self._on_speed_changed)
        mode_vbox.addWidget(self.slider_speed)

        mode_vbox.addStretch()
        self.stack.addWidget(tab_mode_widget)

        # --- ABA 3: HORÁRIOS / TIMERS ---
        tab_timer_widget = QWidget()
        timer_vbox = QVBoxLayout(tab_timer_widget)
        timer_vbox.setContentsMargins(4, 4, 4, 0)
        timer_vbox.setSpacing(10)

        # Card de agendamento Ligar
        on_frame = QFrame()
        on_frame.setStyleSheet("background: rgba(255, 255, 255, 0.04); border-radius: 10px; border: 1px solid rgba(255, 255, 255, 0.06); padding: 6px;")
        on_box = QHBoxLayout(on_frame)
        on_box.setContentsMargins(8, 4, 8, 4)

        self.chk_on = QCheckBox("Ligar às")
        self.chk_on.setStyleSheet("color: #FFFFFF; font-size: 13px; font-weight: 600; font-family: 'Segoe UI';")
        self.chk_on.setChecked(self.settings.get("timer_on_enabled", False))

        self.time_on = SmartTimeEdit(self.settings.get("timer_on_time", "07:00"))
        self.time_on.setFixedWidth(74)
        self.time_on.setStyleSheet(self._time_style())

        on_box.addWidget(self.chk_on)
        on_box.addStretch()
        on_box.addWidget(self.time_on)
        timer_vbox.addWidget(on_frame)

        # Card de agendamento Desligar
        off_frame = QFrame()
        off_frame.setStyleSheet("background: rgba(255, 255, 255, 0.04); border-radius: 10px; border: 1px solid rgba(255, 255, 255, 0.06); padding: 6px;")
        off_box = QHBoxLayout(off_frame)
        off_box.setContentsMargins(8, 4, 8, 4)

        self.chk_off = QCheckBox("Desligar às")
        self.chk_off.setStyleSheet("color: #FFFFFF; font-size: 13px; font-weight: 600; font-family: 'Segoe UI';")
        self.chk_off.setChecked(self.settings.get("timer_off_enabled", False))

        self.time_off = SmartTimeEdit(self.settings.get("timer_off_time", "23:30"))
        self.time_off.setFixedWidth(74)
        self.time_off.setStyleSheet(self._time_style())

        off_box.addWidget(self.chk_off)
        off_box.addStretch()
        off_box.addWidget(self.time_off)
        timer_vbox.addWidget(off_frame)

        self.btn_save_timer = QPushButton("Salvar e Sincronizar")
        self.btn_save_timer.setCursor(Qt.PointingHandCursor)
        self.btn_save_timer.setStyleSheet("""
            QPushButton {
                background: rgba(255, 255, 255, 0.12);
                color: #FFFFFF;
                border: 1px solid rgba(255, 255, 255, 0.15);
                border-radius: 10px;
                padding: 10px;
                font-size: 12px;
                font-weight: 600;
                font-family: 'Segoe UI';
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.2);
                border: 1px solid rgba(255, 255, 255, 0.25);
            }
        """)
        self.btn_save_timer.clicked.connect(self._save_timer_settings)
        timer_vbox.addWidget(self.btn_save_timer)

        timer_vbox.addStretch()
        self.stack.addWidget(tab_timer_widget)

        # --- ABA 4: CONFIGURAÇÕES E CUSTOMIZAÇÕES ---
        tab_config_widget = QWidget()
        tab_config_widget.setStyleSheet("background: transparent;")

        # Scroll area para a aba de configurações
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QScrollBar:vertical {
                background: transparent;
                width: 4px;
                border-radius: 2px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: rgba(255,255,255,0.2);
                border-radius: 2px;
                min-height: 20px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
        """)

        scroll_container = QWidget()
        scroll_container.setStyleSheet("background: transparent;")
        cfg_vbox = QVBoxLayout(scroll_container)
        cfg_vbox.setContentsMargins(4, 4, 4, 0)
        cfg_vbox.setSpacing(10)

        # 1. Opacidade da Janela
        op_card = QFrame()
        op_card.setStyleSheet("QFrame { background: rgba(255, 255, 255, 0.04); border-radius: 10px; border: 1px solid rgba(255, 255, 255, 0.06); }")
        op_layout = QVBoxLayout(op_card)
        op_layout.setContentsMargins(12, 10, 12, 10)
        op_layout.setSpacing(6)

        op_title_row = QHBoxLayout()
        lbl_op_title = QLabel("Opacidade do Fundo")
        lbl_op_title.setStyleSheet("color: #FFFFFF; font-size: 12px; font-weight: 600; font-family: 'Segoe UI';")
        self.lbl_op_val = QLabel(f"{self.settings.get('opacity', 85)}%")
        self.lbl_op_val.setStyleSheet("color: #8C8E9A; font-size: 11px; font-weight: 700; font-family: 'Segoe UI';")
        op_title_row.addWidget(lbl_op_title)
        op_title_row.addStretch()
        op_title_row.addWidget(self.lbl_op_val)
        op_layout.addLayout(op_title_row)

        self.slider_opacity = QSlider(Qt.Horizontal)
        self.slider_opacity.setRange(40, 100)
        self.slider_opacity.setValue(self.settings.get("opacity", 85))
        self.slider_opacity.setStyleSheet(self._slider_style())
        self.slider_opacity.valueChanged.connect(self._on_opacity_changed)
        op_layout.addWidget(self.slider_opacity)
        cfg_vbox.addWidget(op_card)

        # 2. Tema Base de Cor
        theme_card = QFrame()
        theme_card.setStyleSheet("QFrame { background: rgba(255, 255, 255, 0.04); border-radius: 10px; border: 1px solid rgba(255, 255, 255, 0.06); }")
        th_layout = QHBoxLayout(theme_card)
        th_layout.setContentsMargins(12, 10, 12, 10)

        lbl_th_title = QLabel("Tema Escuro")
        lbl_th_title.setStyleSheet("color: #FFFFFF; font-size: 12px; font-weight: 600; font-family: 'Segoe UI';")
        th_layout.addWidget(lbl_th_title)
        th_layout.addStretch()

        self.cmb_theme = QComboBox()
        self.cmb_theme.setStyleSheet("""
            QComboBox {
                background: rgba(255, 255, 255, 0.08);
                color: #FFFFFF;
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 8px;
                padding: 4px 10px;
                font-size: 11px;
                font-weight: 600;
                font-family: 'Segoe UI';
            }
            QComboBox QAbstractItemView {
                background: #18191E;
                color: #FFF;
                selection-background-color: rgba(255, 255, 255, 0.15);
                border: 1px solid rgba(255, 255, 255, 0.15);
                border-radius: 6px;
            }
        """)
        for th in ["Obsidian", "Midnight", "Graphite", "OLED Black"]:
            self.cmb_theme.addItem(th)
        cur_th = self.settings.get("accent_theme", "Obsidian")
        idx_th = self.cmb_theme.findText(cur_th)
        if idx_th >= 0:
            self.cmb_theme.setCurrentIndex(idx_th)
        self.cmb_theme.currentTextChanged.connect(self._on_theme_changed)
        th_layout.addWidget(self.cmb_theme)
        cfg_vbox.addWidget(theme_card)

        # 3. Calibração de LED (compensação de cores por canal)
        calib_card = QFrame()
        calib_card.setStyleSheet("QFrame { background: rgba(255, 255, 255, 0.04); border-radius: 10px; border: 1px solid rgba(255, 255, 255, 0.06); }")
        calib_layout = QVBoxLayout(calib_card)
        calib_layout.setContentsMargins(12, 10, 12, 10)
        calib_layout.setSpacing(8)

        lbl_calib_title = QLabel("Calibração de LED")
        lbl_calib_title.setStyleSheet("color: #8C8E9A; font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; font-family: 'Segoe UI';")
        calib_layout.addWidget(lbl_calib_title)

        # Verde
        g_row = QHBoxLayout()
        lbl_g = QLabel("Verde")
        lbl_g.setStyleSheet("color: #FFFFFF; font-size: 11px; font-weight: 600; font-family: 'Segoe UI'; min-width: 40px;")
        self.lbl_g_val = QLabel(f"{self.settings.get('calib_g', 100)}%")
        self.lbl_g_val.setStyleSheet("color: #8C8E9A; font-size: 11px; font-weight: 700; font-family: 'Segoe UI'; min-width: 36px;")
        g_row.addWidget(lbl_g)
        g_row.addStretch()
        g_row.addWidget(self.lbl_g_val)
        calib_layout.addLayout(g_row)

        self.slider_cal_g = QSlider(Qt.Horizontal)
        self.slider_cal_g.setRange(0, 100)
        self.slider_cal_g.setValue(self.settings.get("calib_g", 100))
        self.slider_cal_g.setStyleSheet(self._slider_style())
        self.slider_cal_g.valueChanged.connect(self._on_calib_g_changed)
        calib_layout.addWidget(self.slider_cal_g)

        # Azul
        b_row = QHBoxLayout()
        lbl_b = QLabel("Azul")
        lbl_b.setStyleSheet("color: #FFFFFF; font-size: 11px; font-weight: 600; font-family: 'Segoe UI'; min-width: 40px;")
        self.lbl_b_val = QLabel(f"{self.settings.get('calib_b', 100)}%")
        self.lbl_b_val.setStyleSheet("color: #8C8E9A; font-size: 11px; font-weight: 700; font-family: 'Segoe UI'; min-width: 36px;")
        b_row.addWidget(lbl_b)
        b_row.addStretch()
        b_row.addWidget(self.lbl_b_val)
        calib_layout.addLayout(b_row)

        self.slider_cal_b = QSlider(Qt.Horizontal)
        self.slider_cal_b.setRange(0, 100)
        self.slider_cal_b.setValue(self.settings.get("calib_b", 100))
        self.slider_cal_b.setStyleSheet(self._slider_style())
        self.slider_cal_b.valueChanged.connect(self._on_calib_b_changed)
        calib_layout.addWidget(self.slider_cal_b)

        cfg_vbox.addWidget(calib_card)

        # 4. Toggles de Sistema
        toggle_card = QFrame()
        toggle_card.setStyleSheet("QFrame { background: rgba(255, 255, 255, 0.04); border-radius: 10px; border: 1px solid rgba(255, 255, 255, 0.06); }")
        tgl_layout = QVBoxLayout(toggle_card)
        tgl_layout.setContentsMargins(12, 10, 12, 10)
        tgl_layout.setSpacing(8)

        self.chk_sync_tb = QCheckBox("Harmonizar cor com a Barra de Tarefas")
        self.chk_sync_tb.setStyleSheet("color: #FFFFFF; font-size: 11px; font-weight: 500; font-family: 'Segoe UI';")
        self.chk_sync_tb.setChecked(self.settings.get("sync_taskbar_color", True))
        self.chk_sync_tb.toggled.connect(self._on_sync_taskbar_toggled)
        tgl_layout.addWidget(self.chk_sync_tb)

        self.chk_startup = QCheckBox("Iniciar junto com o Windows")
        self.chk_startup.setStyleSheet("color: #FFFFFF; font-size: 11px; font-weight: 500; font-family: 'Segoe UI';")
        self.chk_startup.setChecked(self.settings.get("start_with_windows", False))
        self.chk_startup.toggled.connect(self._on_startup_toggled)
        tgl_layout.addWidget(self.chk_startup)

        cfg_vbox.addWidget(toggle_card)
        cfg_vbox.addStretch()

        scroll_area.setWidget(scroll_container)

        cfg_outer = QVBoxLayout(tab_config_widget)
        cfg_outer.setContentsMargins(0, 0, 0, 0)
        cfg_outer.setSpacing(0)
        cfg_outer.addWidget(scroll_area)

        self.stack.addWidget(tab_config_widget)

        card_layout.addWidget(self.stack)
        root_layout.addWidget(self.card)

    def _slider_style(self) -> str:
        return """
            QSlider::groove:horizontal {
                height: 5px;
                background: rgba(255, 255, 255, 0.12);
                border-radius: 2.5px;
            }
            QSlider::sub-page:horizontal {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #8E909B, stop:1 #FFFFFF);
                border-radius: 2.5px;
            }
            QSlider::handle:horizontal {
                background: #FFFFFF;
                border: 1px solid rgba(0, 0, 0, 0.2);
                width: 15px;
                height: 15px;
                margin: -5px 0;
                border-radius: 7.5px;
            }
            QSlider::handle:horizontal:hover {
                transform: scale(1.15);
            }
        """

    def _time_style(self) -> str:
        return """
            QLineEdit, QTimeEdit {
                background: rgba(255, 255, 255, 0.08);
                color: #FFF;
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 8px;
                padding: 4px 6px;
                font-size: 13px;
                font-weight: 600;
                font-family: 'Segoe UI';
            }
            QLineEdit:focus, QTimeEdit:focus {
                border: 1px solid rgba(255, 255, 255, 0.35);
                background: rgba(255, 255, 255, 0.12);
            }
        """

    def _on_calib_g_changed(self, val: int):
        self.lbl_g_val.setText(f"{val}%")
        self.settings["calib_g"] = val
        save_settings(self.settings)
        # Reenvia a cor atual com a nova calibração aplicada
        cur_c = self.settings.get("color", [255, 0, 128])
        self.ble.set_color(cur_c[0], cur_c[1], cur_c[2])

    def _on_calib_b_changed(self, val: int):
        self.lbl_b_val.setText(f"{val}%")
        self.settings["calib_b"] = val
        save_settings(self.settings)
        cur_c = self.settings.get("color", [255, 0, 128])
        self.ble.set_color(cur_c[0], cur_c[1], cur_c[2])

    def _on_opacity_changed(self, val: int):
        self.lbl_op_val.setText(f"{val}%")
        self.settings["opacity"] = val
        save_settings(self.settings)
        self.card.update()

    def _on_theme_changed(self, theme_name: str):
        self.settings["accent_theme"] = theme_name
        save_settings(self.settings)
        self.card.update()

    def _on_sync_taskbar_toggled(self, checked: bool):
        self.settings["sync_taskbar_color"] = checked
        save_settings(self.settings)
        self.card.update()

    def _on_startup_toggled(self, checked: bool):
        self.settings["start_with_windows"] = checked
        save_settings(self.settings)
        self._set_windows_startup(checked)

    def _set_windows_startup(self, enable: bool):
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        app_name = "LotusLanternTray"
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
            if enable:
                bat_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Init.bat")
                cmd = f'"{bat_path}"'
                winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, cmd)
            else:
                try:
                    winreg.DeleteValue(key, app_name)
                except FileNotFoundError:
                    pass
            winreg.CloseKey(key)
        except Exception:
            pass

    def _init_animations(self):
        # Animação de ABRIR (slide up)
        self.anim_show = QPropertyAnimation(self, b"pos")
        self.anim_show.setDuration(220)
        self.anim_show.setEasingCurve(QEasingCurve.OutCubic)

        # Animação de FECHAR (slide down + fade out)
        self.anim_hide_pos = QPropertyAnimation(self, b"pos")
        self.anim_hide_pos.setDuration(180)
        self.anim_hide_pos.setEasingCurve(QEasingCurve.InCubic)

        self.anim_hide_opacity = QPropertyAnimation(self, b"windowOpacity")
        self.anim_hide_opacity.setDuration(160)
        self.anim_hide_opacity.setEasingCurve(QEasingCurve.InCubic)
        self.anim_hide_opacity.setStartValue(1.0)
        self.anim_hide_opacity.setEndValue(0.0)

        self.anim_hide_group = QParallelAnimationGroup()
        self.anim_hide_group.addAnimation(self.anim_hide_pos)
        self.anim_hide_group.addAnimation(self.anim_hide_opacity)
        self.anim_hide_group.finished.connect(self._on_hide_done)

    def _update_power_button_style(self, on: bool):
        if on:
            self.btn_power.setStyleSheet("""
                QPushButton {
                    background: rgba(255, 255, 255, 0.08);
                    color: #FFFFFF;
                    font-family: 'Segoe Fluent Icons', 'Segoe MDL2 Assets';
                    font-size: 13px;
                    border: 1px solid rgba(255, 255, 255, 0.12);
                    border-radius: 8px;
                    padding-bottom: 1px;
                }
                QPushButton:hover {
                    background: rgba(255, 255, 255, 0.14);
                    border: 1px solid rgba(255, 255, 255, 0.22);
                    color: #FFFFFF;
                }
                QPushButton:pressed {
                    background: rgba(255, 255, 255, 0.05);
                }
            """)
        else:
            self.btn_power.setStyleSheet("""
                QPushButton {
                    background: transparent;
                    color: #555761;
                    font-family: 'Segoe Fluent Icons', 'Segoe MDL2 Assets';
                    font-size: 13px;
                    border: 1px solid rgba(255, 255, 255, 0.05);
                    border-radius: 8px;
                    padding-bottom: 1px;
                }
                QPushButton:hover {
                    background: rgba(255, 255, 255, 0.06);
                    color: #8E909B;
                    border: 1px solid rgba(255, 255, 255, 0.1);
                }
                QPushButton:pressed {
                    background: rgba(255, 255, 255, 0.03);
                }
            """)

    def _toggle_power(self):
        current = self.settings.get("power", True)
        new_state = not current
        self.ble.turn_on(new_state)
        self._update_power_button_style(new_state)
        if self.on_icon_refresh:
            self.on_icon_refresh()

    def _on_tab_changed(self, btn):
        idx = self.tab_group.id(btn)
        self.stack.slide_to_index(idx)

    def _create_preset_btn(self, hex_val: str, tip: str, pr: int, pg: int, pb: int) -> QPushButton:
        btn = QPushButton()
        btn.setFixedSize(22, 22)
        btn.setToolTip(tip)
        btn.setCursor(Qt.PointingHandCursor)
        # Ícone circular perfeito gerado via QPixmap sem borda ou artefatos de fundo do botão
        pix = QPixmap(22, 22)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(hex_val))
        p.drawEllipse(1, 1, 20, 20)
        p.end()

        btn.setIcon(QIcon(pix))
        btn.setIconSize(pix.size())
        btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                padding: 0px;
                margin: 0px;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.12);
                border-radius: 11px;
            }
        """)
        btn.clicked.connect(lambda checked=False, h=hex_val, r=pr, g=pg, b=pb: self._on_preset_clicked(h, r, g, b))
        return btn

    def _on_wheel_color_changed(self, color: QColor):
        r, g, b = color.red(), color.green(), color.blue()
        hex_code = f"#{r:02X}{g:02X}{b:02X}"
        self.lbl_color_hex.setText(hex_code)
        self.preview_dot.setStyleSheet(f"background: {hex_code}; border-radius: 7px; border: 1.5px solid rgba(255, 255, 255, 0.4);")
        self.ble.set_color(r, g, b)
        if self.on_icon_refresh:
            self.on_icon_refresh()

    def _on_preset_clicked(self, hex_color: str, pr: int, pg: int, pb: int):
        c = QColor(hex_color)
        self.wheel.setColor(c)
        self.lbl_color_hex.setText(hex_color.upper())
        self.preview_dot.setStyleSheet(f"background: {hex_color}; border-radius: 7px; border: 1.5px solid rgba(255, 255, 255, 0.4);")
        self.ble.set_color(pr, pg, pb)
        if self.on_icon_refresh:
            self.on_icon_refresh()
        if self.on_icon_refresh:
            self.on_icon_refresh()

    def _on_brightness_changed(self, val: int):
        self.lbl_br_val.setText(f"{val}%")
        self.ble.set_brightness(val)

    def _apply_current_mode(self):
        mode_id = self.cmb_mode.currentData()
        if mode_id:
            self.ble.set_mode(mode_id)
            # Feedback visual sutil no botão
            original_text = self.btn_apply_mode.text()
            self.btn_apply_mode.setText("✓ Efeito Aplicado")
            self.btn_apply_mode.setStyleSheet("""
                QPushButton {
                    background: rgba(0, 230, 118, 0.2);
                    color: #69F0AE;
                    border: 1px solid rgba(0, 230, 118, 0.4);
                    border-radius: 10px;
                    padding: 8px 16px;
                    font-size: 12px;
                    font-weight: 600;
                    font-family: 'Segoe UI', sans-serif;
                }
            """)
            QTimer.singleShot(1200, self._reset_apply_mode_btn)

    def _reset_apply_mode_btn(self):
        self.btn_apply_mode.setText("Aplicar Efeito")
        self.btn_apply_mode.setStyleSheet("""
            QPushButton {
                background: rgba(255, 255, 255, 0.10);
                color: #FFFFFF;
                border: 1px solid rgba(255, 255, 255, 0.18);
                border-radius: 10px;
                padding: 8px 16px;
                font-size: 12px;
                font-weight: 600;
                font-family: 'Segoe UI', sans-serif;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.18);
                border: 1px solid rgba(255, 255, 255, 0.3);
            }
            QPushButton:pressed {
                background: rgba(255, 255, 255, 0.08);
            }
        """)

    def _on_speed_changed(self, val: int):
        self.ble.set_speed(val)

    def _save_timer_settings(self):
        # Garante que qualquer texto ainda não formatado seja parseado antes de salvar
        self.time_on._format_and_emit()
        self.time_off._format_and_emit()

        # 1. Sincroniza o relógio interno do microcontrolador primeiro
        self.ble.sync_clock()

        # 2. Envia os pacotes de timer de hardware
        if self.chk_on.isChecked():
            t = self.time_on.time()
            self.ble.set_timer(t.hour(), t.minute(), turn_on=True, enabled=True)
        else:
            self.ble.set_timer(0, 0, turn_on=True, enabled=False)

        if self.chk_off.isChecked():
            t = self.time_off.time()
            self.ble.set_timer(t.hour(), t.minute(), turn_on=False, enabled=True)
        else:
            self.ble.set_timer(0, 0, turn_on=False, enabled=False)

        # Feedback visual no botão
        self.btn_save_timer.setText("✓ Horários Salvos e Sincronizados!")
        self.btn_save_timer.setStyleSheet("""
            QPushButton {
                background: rgba(0, 230, 118, 0.2);
                color: #69F0AE;
                border: 1px solid rgba(0, 230, 118, 0.4);
                border-radius: 10px;
                padding: 10px;
                font-size: 12px;
                font-weight: 600;
                font-family: 'Segoe UI';
            }
        """)
        QTimer.singleShot(2500, self._reset_save_timer_btn)

        # Feedback temporário no status no topo
        self.lbl_status.setText("Horários sincronizados!")
        self.lbl_status.setStyleSheet("color: #69F0AE; font-size: 11px; font-weight: 600; font-family: 'Segoe UI';")
        QTimer.singleShot(3000, self._restore_status_text)

    def _reset_save_timer_btn(self):
        self.btn_save_timer.setText("Salvar e Sincronizar")
        self.btn_save_timer.setStyleSheet("""
            QPushButton {
                background: rgba(255, 255, 255, 0.12);
                color: #FFFFFF;
                border: 1px solid rgba(255, 255, 255, 0.15);
                border-radius: 10px;
                padding: 10px;
                font-size: 12px;
                font-weight: 600;
                font-family: 'Segoe UI';
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.2);
                border: 1px solid rgba(255, 255, 255, 0.25);
            }
        """)

    def _restore_status_text(self):
        if self.ble.is_connected:
            name = self.settings.get("name", "ELK-BLEDOM")
            self.lbl_status.setText(f"Conectado: {name}")
            self.lbl_status.setStyleSheet("color: #69F0AE; font-size: 11px; font-weight: 600; font-family: 'Segoe UI';")
        else:
            self.lbl_status.setText("Desconectado")
            self.lbl_status.setStyleSheet("color: #8C8E9A; font-size: 11px; font-family: 'Segoe UI';")

    def _check_local_schedule(self):
        """Fallback garantido: se o app estiver aberto no PC na bandeja, ele liga/desliga no minuto certo."""
        now = QTime.currentTime()
        cur_min_str = now.toString("HH:mm")

        if cur_min_str == self._last_triggered_minute:
            return

        # Checa Ligar
        if self.chk_on.isChecked():
            t_on = self.time_on.time().toString("HH:mm")
            if cur_min_str == t_on:
                self._last_triggered_minute = cur_min_str
                self.ble.turn_on(True)
                self._update_power_button_style(True)
                if self.on_icon_refresh:
                    self.on_icon_refresh()
                return

        # Checa Desligar
        if self.chk_off.isChecked():
            t_off = self.time_off.time().toString("HH:mm")
            if cur_min_str == t_off:
                self._last_triggered_minute = cur_min_str
                self.ble.turn_on(False)
                self._update_power_button_style(False)
                if self.on_icon_refresh:
                    self.on_icon_refresh()
                return

    def _apply_hardware_timer_ui(self, info: dict):
        action = info.get("action")
        time_str = info.get("time", "00:00")
        enabled = info.get("enabled", False)

        try:
            h, m = map(int, time_str.split(":"))
            qtime = QTime(h, m)
            if action == 0x00:
                self.chk_on.setChecked(enabled)
                self.time_on.setTime(qtime)
            elif action == 0x01:
                self.chk_off.setChecked(enabled)
                self.time_off.setTime(qtime)
        except Exception:
            pass

    def _update_status_ui(self, message: str, is_connected: bool):
        self.lbl_status.setText(message)
        if is_connected:
            self.indicator_dot.setStyleSheet("background: #00E676; border-radius: 4px; box-shadow: 0 0 8px #00E676;")
            self.lbl_status.setStyleSheet("color: #69F0AE; font-size: 11px; font-weight: 600; font-family: 'Segoe UI';")
        else:
            self.indicator_dot.setStyleSheet("background: #FF5252; border-radius: 4px;")
            self.lbl_status.setStyleSheet("color: #8C8E9A; font-size: 11px; font-family: 'Segoe UI';")
        if self.on_icon_refresh:
            self.on_icon_refresh()

    def toggle_popup(self):
        if self.is_showing:
            self.hide_popup()
        else:
            # Evita reabrir se acabou de fechar por perda de foco (race condition com ícone da bandeja)
            if time.time() - self._last_hide_time < 0.35:
                return
            self.show_popup()

    def show_popup(self):
        screen = QGuiApplication.primaryScreen()
        avail = screen.availableGeometry()

        w = self.width()
        h = self.height()

        target_x = avail.right() - w - 8
        target_y = avail.bottom() - h - 4
        start_y = target_y + 18

        self.setWindowOpacity(1.0)
        self.move(target_x, start_y)
        self.show()
        self.raise_()
        self.activateWindow()

        self.anim_hide_group.stop()
        self.anim_show.stop()
        self.anim_show.setStartValue(QPoint(target_x, start_y))
        self.anim_show.setEndValue(QPoint(target_x, target_y))
        self.anim_show.start()
        self.is_showing = True

    def hide_popup(self):
        if not self.is_showing:
            return
        self.is_showing = False
        self._last_hide_time = time.time()

        cur_pos = self.pos()
        end_pos = QPoint(cur_pos.x(), cur_pos.y() + 20)

        self.anim_show.stop()
        self.anim_hide_pos.setStartValue(cur_pos)
        self.anim_hide_pos.setEndValue(end_pos)
        self.anim_hide_opacity.setStartValue(1.0)
        self.anim_hide_opacity.setEndValue(0.0)
        self.anim_hide_group.start()

    def _on_hide_done(self):
        self.hide()
        self.setWindowOpacity(1.0)

    def changeEvent(self, event):
        if event.type() == event.Type.ActivationChange:
            if not self.isActiveWindow() and self.is_showing:
                self.hide_popup()
        super().changeEvent(event)

def create_tray_icon(is_connected: bool = True, power_on: bool = True, rgb_color: tuple = (255, 0, 128)) -> QIcon:
    """
    Ícone rigorosamente padronizado no design nativo do Windows 11 (Segoe Fluent Icons).
    Canvas 16x16 com linha nítida de 1px e proporções exatas da bandeja do Windows.
    """
    pixmap = QPixmap(16, 16)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, False)  # Pixel-crisp 1px nativo do Windows

    if not is_connected:
        # Estado Desconectado: Desenho fino na cor neutra dos ícones do sistema (#D6D8E1)
        pen = QPen(QColor(160, 164, 175), 1)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)

        # Cúpula da lâmpada
        painter.drawRect(3, 2, 9, 8)
        # Base/Rosca
        painter.drawLine(5, 11, 10, 11)
        painter.drawLine(6, 13, 9, 13)

        # Pequeno badge de desconexão (ponto vermelho no canto inferior)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(235, 60, 60))
        painter.drawRect(12, 11, 3, 3)

    elif not power_on:
        # Conectado, Luz Desligada: Contorno branco nítido idêntico ao ícone de monitor de rede
        pen = QPen(QColor(238, 240, 246), 1)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)

        # Cúpula da lâmpada
        painter.drawRect(3, 1, 9, 9)
        # Rosca
        painter.drawLine(5, 11, 10, 11)
        painter.drawLine(6, 13, 9, 13)

    else:
        # Conectado e Ligado: Preenchimento com a cor viva do LED e contorno nativo do Windows
        c = QColor(rgb_color[0], rgb_color[1], rgb_color[2])

        # Preenchimento interno com a cor do LED
        painter.fillRect(4, 2, 8, 8, c)

        # Contorno nítido de 1px branco nativo
        pen = QPen(QColor(245, 247, 252), 1)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)

        painter.drawRect(3, 1, 9, 9)
        # Rosca
        painter.drawLine(5, 11, 10, 11)
        painter.drawLine(6, 13, 9, 13)

    painter.end()
    return QIcon(pixmap)

def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    # Prevenção de Múltiplas Instâncias via IPC (QLocalServer / QLocalSocket)
    SERVER_NAME = "LotusLanternTray_SingleInstance_IPC"
    test_socket = QLocalSocket()
    test_socket.connectToServer(SERVER_NAME)
    if test_socket.waitForConnected(300):
        # Outra instância já está em execução -> avisa para abrir o painel e encerra esta
        test_socket.write(b"SHOW\n")
        test_socket.waitForBytesWritten(300)
        test_socket.disconnectFromServer()
        sys.exit(0)

    # Remove socket órfão de travamentos anteriores se existir
    QLocalServer.removeServer(SERVER_NAME)
    local_server = QLocalServer()
    local_server.listen(SERVER_NAME)

    def on_ble_status(msg: str, connected: bool):
        if flyout:
            flyout.statusSignal.emit(msg, connected)

    def on_timer_read(info: dict):
        if flyout:
            flyout.timerReadSignal.emit(info)

    ble_worker = BleWorker(on_status_changed=on_ble_status, on_timer_read=on_timer_read)
    ble_worker.start()

    tray_icon = QSystemTrayIcon(app)
    tray_icon.setToolTip("Lotus Lantern - Controle LED")

    def refresh_tray_icon():
        is_conn = ble_worker.is_connected
        pwr = ble_worker.settings.get("power", True)
        color = tuple(ble_worker.settings.get("color", [255, 0, 128]))
        tray_icon.setIcon(create_tray_icon(is_conn, pwr, color))

    global flyout
    flyout = FlyoutWindow(ble_worker, on_icon_refresh=refresh_tray_icon)
    refresh_tray_icon()

    def handle_incoming_instance():
        client_conn = local_server.nextPendingConnection()
        if client_conn:
            client_conn.waitForReadyRead(200)
            data = client_conn.readAll().data()
            if b"SHOW" in data:
                flyout.show_popup()
            client_conn.disconnectFromServer()

    local_server.newConnection.connect(handle_incoming_instance)

    menu = QMenu()
    act_open = menu.addAction("Abrir Painel")
    act_open.triggered.connect(flyout.toggle_popup)
    act_reconnect = menu.addAction("Reconectar LED")
    act_reconnect.triggered.connect(lambda: ble_worker.trigger_reconnect())
    menu.addSeparator()
    act_quit = menu.addAction("Sair")
    act_quit.triggered.connect(app.quit)

    tray_icon.setContextMenu(menu)

    def on_tray_activated(reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            flyout.toggle_popup()

    tray_icon.activated.connect(on_tray_activated)
    tray_icon.show()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
