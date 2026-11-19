import time
import colorsys
from typing import Optional
from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtGui import QGuiApplication, Qt

class ScreenSyncWorker(QThread):
    """
    Worker que roda em thread dedicada para capturar a tela via Qt Desktop Duplication,
    extrair a cor representativa com realce de saturação e dinâmica de brilho para LED,
    suavização EMA e filtro de deadband.
    """
    colorSampled = Signal(int, int, int)

    def __init__(self, fps: int = 18, smoothing: float = 0.28, deadband: int = 4, mode: str = "borders", parent: Optional[QObject] = None):
        super().__init__(parent)
        self.fps = max(10, min(25, fps))
        self.interval = 1.0 / self.fps
        self.smoothing = max(0.05, min(0.9, smoothing))
        self.deadband = deadband  # Limiar mínimo de variação delta RGB
        self.sample_mode = mode   # "borders" (recomendado para ambilight) ou "average"

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

    def _enhance_color_for_led(self, r: float, g: float, b: float) -> tuple[int, int, int]:
        """
        Corrige o efeito de cor 'lavada' que acontece quando fazemos a média de uma tela.
        Separa e impulsiona a Saturação (S) e o Brilho (V) no espaço HSV para que
        a fita de LED atinja tons vívidos e luminosidade máxima.
        """
        max_val = max(r, g, b)
        if max_val < 6.0:
            return 0, 0, 0

        # Normaliza 0.0 a 1.0
        h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)

        # 1. Boost não-linear de Saturação:
        # Quando a tela mistura cores ou tem elementos claros/cinzas, a saturação média cai.
        # A curva (s ** 0.45) * 1.35 recupera a pureza da cor dominante (ex: vermelho puro).
        if s > 0.04:
            s_boosted = min(1.0, (s ** 0.45) * 1.35)
        else:
            s_boosted = s  # Mantém neutro se for branco/cinza quase puro

        # 2. Boost de Luminosidade / Brilho:
        # Eleva a curva de brilho para que a fita acenda com energia máxima
        v_boosted = min(1.0, (v ** 0.60) * 1.30)

        r_out, g_out, b_out = colorsys.hsv_to_rgb(h, s_boosted, v_boosted)
        return int(round(r_out * 255)), int(round(g_out * 255)), int(round(b_out * 255))

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

                if self.sample_mode == "borders":
                    # Amostragem das bordas onde a fita reflete na parede (ignora o miolo central)
                    # Pega 15% do topo e laterais
                    h_border = max(2, int(h * 0.15))
                    w_border = max(2, int(w * 0.15))

                    top = img.copy(0, 0, w, h_border).scaled(1, 1, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
                    left = img.copy(0, 0, w_border, h).scaled(1, 1, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
                    right = img.copy(max(0, w - w_border), 0, w_border, h).scaled(1, 1, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)

                    c_top = top.pixelColor(0, 0)
                    c_left = left.pixelColor(0, 0)
                    c_right = right.pixelColor(0, 0)

                    # Dá peso maior ao topo e bordas
                    raw_r = (c_top.red() * 2.0 + c_left.red() + c_right.red()) / 4.0
                    raw_g = (c_top.green() * 2.0 + c_left.green() + c_right.green()) / 4.0
                    raw_b = (c_top.blue() * 2.0 + c_left.blue() + c_right.blue()) / 4.0
                else:
                    # Média global de tela cheia
                    scaled = img.scaled(1, 1, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
                    c = scaled.pixelColor(0, 0)
                    raw_r = float(c.red())
                    raw_g = float(c.green())
                    raw_b = float(c.blue())

                # Suavização Orgânica (EMA - Exponential Moving Average) no sinal de entrada
                if self._last_sent_rgb == (-1, -1, -1):
                    self._cur_r, self._cur_g, self._cur_b = raw_r, raw_g, raw_b
                else:
                    self._cur_r = self._cur_r + self.smoothing * (raw_r - self._cur_r)
                    self._cur_g = self._cur_g + self.smoothing * (raw_g - self._cur_g)
                    self._cur_b = self._cur_b + self.smoothing * (raw_b - self._cur_b)

                # Aplica o realce de saturação e escala de luminosidade para o LED
                out_r, out_g, out_b = self._enhance_color_for_led(self._cur_r, self._cur_g, self._cur_b)

                # Filtro de Mudança Mínima (Deadband):
                # Se a cor na parede mudou menos que o limiar delta, NÃO envia nada para não saturar o BLE nem chiar o fone!
                last_r, last_g, last_b = self._last_sent_rgb
                delta = abs(out_r - last_r) + abs(out_g - last_g) + abs(out_b - last_b)

                if delta >= self.deadband or self._last_sent_rgb == (-1, -1, -1):
                    self._last_sent_rgb = (out_r, out_g, out_b)
                    self.colorSampled.emit(out_r, out_g, out_b)

            except Exception:
                pass

            # Mantém cadência precisa respeitando o FPS configurado
            elapsed = time.perf_counter() - t_start
            sleep_time = self.interval - elapsed
            if sleep_time > 0.002:
                time.sleep(sleep_time)
