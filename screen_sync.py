import time
import colorsys
from typing import Optional
from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtGui import QGuiApplication, Qt

class ScreenSyncWorker(QThread):
    """
    Worker que roda em thread dedicada para capturar a tela via Qt Desktop Duplication.
    
    Aprimoramentos de Fluidez:
    1. Amostragem combinada (bordas com 70% de peso + centro com 30% de peso) para evitar
       que barras de abas e cantos do Windows sequestrem a cor real da cena.
    2. Curva contínua de saturação e brilho HSV (sem degraus secos ou saltos bruscos).
    3. Normalização proporcional de pico (escala com o slider de brilho do usuário).
    4. Suavização EMA como ÚLTIMA etapa de saída, garantindo transições aveludadas e orgânicas.
    """
    colorSampled = Signal(int, int, int)

    def __init__(self, fps: int = 18, smoothing: float = 0.22, deadband: int = 3, mode: str = "smart", parent: Optional[QObject] = None):
        super().__init__(parent)
        self.fps = max(10, min(25, fps))
        self.interval = 1.0 / self.fps
        # Fator de suavização EMA (0.22 dá uma transição muito aveludada sem delay perceptível)
        self.smoothing = max(0.05, min(0.9, smoothing))
        self.deadband = deadband  # Limiar mínimo de variação delta RGB
        self.sample_mode = mode   # "smart" (bordas + centro ponderado) ou "borders" ou "average"
        self.brightness_factor = 1.0  # Controlado pelo slider de brilho (0.0 a 1.0)

        self._running = False
        # O estado EMA agora guarda a cor FINAL pós-processamento!
        self._target_r = 0.0
        self._target_g = 0.0
        self._target_b = 0.0
        self._last_sent_rgb = (-1, -1, -1)

    def set_brightness_factor(self, percent: int):
        """Atualiza a escala de brilho do Ambilight baseada no slider (0 a 100%)."""
        self.brightness_factor = max(0.05, min(100, percent)) / 100.0

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

    def _calculate_instant_color(self, r: float, g: float, b: float) -> tuple[float, float, float]:
        """
        Calcula a cor instantânea desejada usando curvas contínuas (sem 'ifs' que causam saltos secos).
        """
        max_raw = max(r, g, b)
        if max_raw < 5.0:
            return 0.0, 0.0, 0.0

        # Converte para espaço perceptual HSV
        h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)

        # 1. Curva contínua de Saturação (curva suave de potência):
        # Transforma cores diluídas da tela em tons vivos na parede sem estourar
        s_curved = min(1.0, (s ** 0.45) * 1.40) if s > 0.02 else 0.0

        # 2. Curva de Dinâmica de Brilho:
        # Cenas escuras preservam contraste; cenas claras ganham punch
        v_curved = min(1.0, (v ** 0.78) * 1.15)

        r_n, g_n, b_n = colorsys.hsv_to_rgb(h, s_curved, v_curved)

        # 3. Normalização proporcional de pico:
        # Se for uma cor com brilho, empurra o canal dominante em direção ao teto de forma suave
        peak = max(r_n, g_n, b_n)
        if peak > 0.02:
            gain = 1.0 + (1.0 / peak - 1.0) * (v_curved ** 0.5)
            r_n = min(1.0, r_n * gain)
            g_n = min(1.0, g_n * gain)
            b_n = min(1.0, b_n * gain)

        # Aplica o slider de brilho do usuário
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

                # Amostragem Inteligente (Smart):
                # Combina as bordas com o centro para nunca ficar cego ou sequestrado por barras de título
                h_b = max(2, int(h * 0.18))
                w_b = max(2, int(w * 0.18))

                top = img.copy(0, 0, w, h_b).scaled(1, 1, Qt.IgnoreAspectRatio, Qt.SmoothTransformation).pixelColor(0, 0)
                left = img.copy(0, 0, w_b, h).scaled(1, 1, Qt.IgnoreAspectRatio, Qt.SmoothTransformation).pixelColor(0, 0)
                right = img.copy(max(0, w - w_b), 0, w_b, h).scaled(1, 1, Qt.IgnoreAspectRatio, Qt.SmoothTransformation).pixelColor(0, 0)
                center = img.copy(w_b, h_b, max(1, w - 2*w_b), max(1, h - 2*h_b)).scaled(1, 1, Qt.IgnoreAspectRatio, Qt.SmoothTransformation).pixelColor(0, 0)

                # Ponderação: Topo 30%, Laterais 20% cada, Centro 30%
                raw_r = top.red() * 0.30 + left.red() * 0.20 + right.red() * 0.20 + center.red() * 0.30
                raw_g = top.green() * 0.30 + left.green() * 0.20 + right.green() * 0.20 + center.green() * 0.30
                raw_b = top.blue() * 0.30 + left.blue() * 0.20 + right.blue() * 0.20 + center.blue() * 0.30

                # 1. Calcula a cor alvo processada (com realce de saturação e pico)
                target_r, target_g, target_b = self._calculate_instant_color(raw_r, raw_g, raw_b)

                # 2. Suavização Orgânica (EMA) realizada no sinal FINAL de saída:
                # É isso que elimina completamente a sensação irritante de 'troca errada/nervosa'
                if self._last_sent_rgb == (-1, -1, -1):
                    self._target_r, self._target_g, self._target_b = target_r, target_g, target_b
                else:
                    self._target_r = self._target_r + self.smoothing * (target_r - self._target_r)
                    self._target_g = self._target_g + self.smoothing * (target_g - self._target_g)
                    self._target_b = self._target_b + self.smoothing * (target_b - self._target_b)

                out_r = max(0, min(255, int(round(self._target_r))))
                out_g = max(0, min(255, int(round(self._target_g))))
                out_b = max(0, min(255, int(round(self._target_b))))

                # 3. Filtro Deadband: só transmite via BLE se houver mudança real
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
