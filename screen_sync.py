import time
import math
from typing import Optional, Tuple
from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtGui import QGuiApplication, Qt

class ScreenSyncWorker(QThread):
    """
    Worker que roda em thread dedicada para capturar a tela via Qt Desktop Duplication,
    calcular a cor média/bordas com interpolação suave (EMA) e filtro de deadband.
    Emite colorSampled(r, g, b) apenas quando a cor realmente muda, sem sobrecarregar o BLE.
    """
    colorSampled = Signal(int, int, int)

    def __init__(self, fps: int = 18, smoothing: float = 0.28, deadband: int = 4, mode: str = "average", parent: Optional[QObject] = None):
        super().__init__(parent)
        self.fps = max(10, min(25, fps))
        self.interval = 1.0 / self.fps
        self.smoothing = max(0.05, min(0.9, smoothing))
        self.deadband = deadband  # Limiar mínimo de variação delta RGB
        self.sample_mode = mode   # "average" ou "borders"

        self._running = False
        self._cur_r = 0.0
        self._cur_g = 0.0
        self._cur_b = 0.0
        self._last_sent_rgb = (-1, -1, -1)

    def set_parameters(self, fps: Optional[int] = None, smoothing: Optional[float] = None, deadband: Optional[int] = None, mode: Optional[str] = None):
        if fps is not None:
            self.fps = max(10, min(25, fps))
            self.interval = 1.0 / self.fps
        if smoothing is not None:
            self.smoothing = max(0.05, min(0.9, smoothing))
        if deadband is not None:
            self.deadband = deadband
        if mode is not None:
            self.sample_mode = mode

    def stop(self):
        self._running = False
        self.wait(1500)

    def run(self):
        self._running = True
        self._last_sent_rgb = (-1, -1, -1)

        while self._running:
            t_start = time.perf_counter()
            screen = QGuiApplication.primaryScreen()
            if screen is None:
                time.sleep(0.1)
                continue

            try:
                # Captura otimizada da tela através da API do sistema
                pix = screen.grabWindow(0)
                if pix.isNull():
                    time.sleep(0.05)
                    continue

                w = pix.width()
                h = pix.height()

                if self.sample_mode == "borders":
                    # Amostragem das bordas (onde a luz é refletida na parede)
                    img = pix.toImage()
                    top = img.copy(0, 0, w, max(1, int(h * 0.15))).scaled(1, 1, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
                    left = img.copy(0, 0, max(1, int(w * 0.15)), h).scaled(1, 1, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
                    right = img.copy(max(0, int(w * 0.85)), 0, max(1, int(w * 0.15)), h).scaled(1, 1, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)

                    c_top = top.pixelColor(0, 0)
                    c_left = left.pixelColor(0, 0)
                    c_right = right.pixelColor(0, 0)

                    target_r = (c_top.red() * 2 + c_left.red() + c_right.red()) / 4.0
                    target_g = (c_top.green() * 2 + c_left.green() + c_right.green()) / 4.0
                    target_b = (c_top.blue() * 2 + c_left.blue() + c_right.blue()) / 4.0
                else:
                    # Amostragem geral da tela redimensionada direto para 1x1 com bilinear suave
                    scaled = pix.toImage().scaled(1, 1, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
                    c = scaled.pixelColor(0, 0)
                    target_r = float(c.red())
                    target_g = float(c.green())
                    target_b = float(c.blue())

                # Suavização Orgânica (EMA - Exponential Moving Average)
                if self._last_sent_rgb == (-1, -1, -1):
                    self._cur_r, self._cur_g, self._cur_b = target_r, target_g, target_b
                else:
                    self._cur_r = self._cur_r + self.smoothing * (target_r - self._cur_r)
                    self._cur_g = self._cur_g + self.smoothing * (target_g - self._cur_g)
                    self._cur_b = self._cur_b + self.smoothing * (target_b - self._cur_b)

                out_r = int(round(self._cur_r))
                out_g = int(round(self._cur_g))
                out_b = int(round(self._cur_b))

                # Boost leve de saturação se não for preto puro (evita cores lavadas/acinzentadas)
                max_c = max(out_r, out_g, out_b)
                min_c = min(out_r, out_g, out_b)
                if max_c > 15 and (max_c - min_c) > 10:
                    # Acentua levemente a cor dominante
                    factor = 1.15
                    out_r = min(255, int(out_r * factor))
                    out_g = min(255, int(out_g * factor))
                    out_b = min(255, int(out_b * factor))

                # Filtro de Mudança Mínima (Deadband):
                # Se a cor mudou menos que o limiar delta, NÃO envia nada para não saturar o BLE nem interferir no fone!
                last_r, last_g, last_b = self._last_sent_rgb
                delta = abs(out_r - last_r) + abs(out_g - last_g) + abs(out_b - last_b)

                if delta >= self.deadband or self._last_sent_rgb == (-1, -1, -1):
                    self._last_sent_rgb = (out_r, out_g, out_b)
                    self.colorSampled.emit(out_r, out_g, out_b)

            except Exception:
                pass

            # Mantém ritmo constante respeitando o FPS configurado
            elapsed = time.perf_counter() - t_start
            sleep_time = self.interval - elapsed
            if sleep_time > 0.002:
                time.sleep(sleep_time)
