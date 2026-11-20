import time
import colorsys
from typing import Optional, Dict
from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtGui import QGuiApplication, Qt

class ScreenSyncWorker(QThread):
    """
    Worker que roda em thread dedicada para capturar a tela via Qt Desktop Duplication.
    
    Aprimoramentos de Fluidez e Controle de Zonas:
    1. Pesos customizáveis por zona: Topo, Laterais, Centro e Base (Fundo).
    2. Suporte a presets rápidos (ex: "Fita no Teto", "Bordas Monitor", "Tela Inteira").
    3. Curva contínua de saturação e brilho HSV (sem degraus secos ou saltos bruscos).
    4. Normalização proporcional de pico (escala com o slider de brilho do usuário).
    5. Suavização EMA como ÚLTIMA etapa de saída, garantindo transições aveludadas e orgânicas.
    """
    colorSampled = Signal(int, int, int)

    def __init__(self, fps: int = 18, smoothing: float = 0.22, deadband: int = 3,
                 weights: Optional[Dict[str, int]] = None, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.fps = max(10, min(25, fps))
        self.interval = 1.0 / self.fps
        self.smoothing = max(0.05, min(0.9, smoothing))
        self.deadband = deadband
        self.brightness_factor = 1.0

        # Pesos padrão: se não informado, foco forte no Topo (ideal para fita no teto)
        # Valores de 0 a 100
        self.w_top = 80
        self.w_sides = 20
        self.w_center = 30
        self.w_bottom = 0

        if weights:
            self.set_zone_weights(
                weights.get("top", 80),
                weights.get("sides", 20),
                weights.get("center", 30),
                weights.get("bottom", 0)
            )

        self._running = False
        self._target_r = 0.0
        self._target_g = 0.0
        self._target_b = 0.0
        self._last_sent_rgb = (-1, -1, -1)

    def set_zone_weights(self, top: int, sides: int, center: int, bottom: int):
        """Define os pesos percentuais de cada região da tela (0 a 100)."""
        self.w_top = max(0, min(100, top))
        self.w_sides = max(0, min(100, sides))
        self.w_center = max(0, min(100, center))
        self.w_bottom = max(0, min(100, bottom))

    def set_brightness_factor(self, percent: int):
        """Atualiza a escala de brilho do Ambilight baseada no slider (0 a 100%)."""
        self.brightness_factor = max(0.05, min(100, percent)) / 100.0

    def set_parameters(self, fps: Optional[int] = None, smoothing: Optional[float] = None, deadband: Optional[int] = None):
        if fps is not None:
            self.fps = max(10, min(25, fps))
            self.interval = 1.0 / self.fps
        if smoothing is not None:
            self.smoothing = max(0.05, min(0.9, smoothing))
        if deadband is not None:
            self.deadband = deadband

    def stop(self):
        self._running = False
        self.wait(1500)

    def _calculate_instant_color(self, r: float, g: float, b: float) -> tuple[float, float, float]:
        """Calcula a cor instantânea desejada usando curvas contínuas (sem degraus secos)."""
        max_raw = max(r, g, b)
        if max_raw < 5.0:
            return 0.0, 0.0, 0.0

        h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)

        # 1. Curva contínua de Saturação:
        s_curved = min(1.0, (s ** 0.45) * 1.40) if s > 0.02 else 0.0

        # 2. Curva de Dinâmica de Brilho:
        v_curved = min(1.0, (v ** 0.78) * 1.15)

        r_n, g_n, b_n = colorsys.hsv_to_rgb(h, s_curved, v_curved)

        # 3. Normalização proporcional de pico:
        peak = max(r_n, g_n, b_n)
        if peak > 0.02:
            gain = 1.0 + (1.0 / peak - 1.0) * (v_curved ** 0.5)
            r_n = min(1.0, r_n * gain)
            g_n = min(1.0, g_n * gain)
            b_n = min(1.0, b_n * gain)

        final_r = r_n * 255.0 * self.brightness_factor
        final_g = g_n * 255.0 * self.brightness_factor
        final_b = b_n * 255.0 * self.brightness_factor

        return final_r, final_g, final_b

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
                pix = screen.grabWindow(0)
                if pix.isNull():
                    time.sleep(0.05)
                    continue

                w = pix.width()
                h = pix.height()
                img = pix.toImage()

                # Dimensões das zonas
                h_b = max(2, int(h * 0.22))
                w_b = max(2, int(w * 0.20))

                total_weight = self.w_top + self.w_sides + self.w_center + self.w_bottom
                if total_weight <= 0:
                    total_weight = 1

                sum_r = 0.0
                sum_g = 0.0
                sum_b = 0.0

                # 1. ZONA DO TOPO (Ideal para fita no teto)
                if self.w_top > 0:
                    c_top = img.copy(0, 0, w, h_b).scaled(1, 1, Qt.IgnoreAspectRatio, Qt.SmoothTransformation).pixelColor(0, 0)
                    sum_r += c_top.red() * self.w_top
                    sum_g += c_top.green() * self.w_top
                    sum_b += c_top.blue() * self.w_top

                # 2. ZONAS LATERAIS (Esquerda + Direita)
                if self.w_sides > 0:
                    c_left = img.copy(0, 0, w_b, h).scaled(1, 1, Qt.IgnoreAspectRatio, Qt.SmoothTransformation).pixelColor(0, 0)
                    c_right = img.copy(max(0, w - w_b), 0, w_b, h).scaled(1, 1, Qt.IgnoreAspectRatio, Qt.SmoothTransformation).pixelColor(0, 0)
                    sum_r += (c_left.red() + c_right.red()) * 0.5 * self.w_sides
                    sum_g += (c_left.green() + c_right.green()) * 0.5 * self.w_sides
                    sum_b += (c_left.blue() + c_right.blue()) * 0.5 * self.w_sides

                # 3. ZONA CENTRAL (Centro da cena / foco de visão)
                if self.w_center > 0:
                    c_center = img.copy(w_b, h_b, max(1, w - 2*w_b), max(1, h - 2*h_b)).scaled(1, 1, Qt.IgnoreAspectRatio, Qt.SmoothTransformation).pixelColor(0, 0)
                    sum_r += c_center.red() * self.w_center
                    sum_g += c_center.green() * self.w_center
                    sum_b += c_center.blue() * self.w_center

                # 4. ZONA DA BASE / CHÃO (Fundo da tela)
                if self.w_bottom > 0:
                    c_bottom = img.copy(0, max(0, h - h_b), w, h_b).scaled(1, 1, Qt.IgnoreAspectRatio, Qt.SmoothTransformation).pixelColor(0, 0)
                    sum_r += c_bottom.red() * self.w_bottom
                    sum_g += c_bottom.green() * self.w_bottom
                    sum_b += c_bottom.blue() * self.w_bottom

                raw_r = sum_r / total_weight
                raw_g = sum_g / total_weight
                raw_b = sum_b / total_weight

                # 1. Calcula a cor alvo processada
                target_r, target_g, target_b = self._calculate_instant_color(raw_r, raw_g, raw_b)

                # 2. Suavização Orgânica (EMA) realizada no sinal FINAL de saída
                if self._last_sent_rgb == (-1, -1, -1):
                    self._target_r, self._target_g, self._target_b = target_r, target_g, target_b
                else:
                    self._target_r = self._target_r + self.smoothing * (target_r - self._target_r)
                    self._target_g = self._target_g + self.smoothing * (target_g - self._target_g)
                    self._target_b = self._target_b + self.smoothing * (target_b - self._target_b)

                out_r = max(0, min(255, int(round(self._target_r))))
                out_g = max(0, min(255, int(round(self._target_g))))
                out_b = max(0, min(255, int(round(self._target_b))))

                # 3. Filtro Deadband
                last_r, last_g, last_b = self._last_sent_rgb
                delta = abs(out_r - last_r) + abs(out_g - last_g) + abs(out_b - last_b)

                if delta >= self.deadband or self._last_sent_rgb == (-1, -1, -1):
                    self._last_sent_rgb = (out_r, out_g, out_b)
                    self.colorSampled.emit(out_r, out_g, out_b)

            except Exception:
                pass

            elapsed = time.perf_counter() - t_start
            sleep_time = self.interval - elapsed
            if sleep_time > 0.002:
                time.sleep(sleep_time)
