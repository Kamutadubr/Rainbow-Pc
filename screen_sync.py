import time
from typing import Optional
from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtGui import QGuiApplication, Qt

class ScreenSyncWorker(QThread):
    """
    Worker que roda em thread dedicada para capturar a tela via Qt Desktop Duplication.
    
    Aplica:
    1. Amostragem inteligente das bordas da tela (onde a luz projeta na parede).
    2. Subtração do componente acromático comum (remove a contaminação de branco/cinza que torna o vermelho rosa).
    3. Normalização pelo pico: Estica o canal mais forte até 255 multiplicado pelo slider de brilho do usuário.
    4. Suavização EMA e filtro de deadband (sem saturação de BLE).
    """
    colorSampled = Signal(int, int, int)

    def __init__(self, fps: int = 18, smoothing: float = 0.28, deadband: int = 4, mode: str = "borders", parent: Optional[QObject] = None):
        super().__init__(parent)
        self.fps = max(10, min(25, fps))
        self.interval = 1.0 / self.fps
        self.smoothing = max(0.05, min(0.9, smoothing))
        self.deadband = deadband  # Limiar mínimo de variação delta RGB
        self.sample_mode = mode   # "borders" ou "average"
        self.brightness_factor = 1.0  # Controlado pelo slider de brilho (0.0 a 1.0)

        self._running = False
        self._cur_r = 0.0
        self._cur_g = 0.0
        self._cur_b = 0.0
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

    def _process_color_and_brightness(self, r: float, g: float, b: float) -> tuple[int, int, int]:
        """
        1. Remove o branco parasita que dilui o vermelho em rosa.
        2. Normaliza multiplicando igualmente a média para que a cor atinja o pico máximo de brilho.
        3. Aplica o fator do slider de brilho.
        """
        max_c = max(r, g, b)
        min_c = min(r, g, b)

        # Se for tela escura / quase preta, desliga os LEDs para preto verdadeiro
        if max_c < 4.0:
            return 0, 0, 0

        chroma = max_c - min_c

        # Se a tela for predominantemente monocromática/branca (ex: Bloco de Notas ou Word em tela cheia)
        if chroma < 8.0:
            scale = 255.0 / max_c
            r_out = r * scale
            g_out = g * scale
            b_out = b * scale
        else:
            # Há uma cor dominante presente (ex: janela vermelha, azul, etc).
            # O que transforma Vermelho em Rosa na física do LED é ter Verde e Azul misturados!
            # Subtraímos 92% da base branca (min_c) para deixar apenas os fótons puros da cor dominante.
            white_base = min_c * 0.92
            r_pure = max(0.0, r - white_base)
            g_pure = max(0.0, g - white_base)
            b_pure = max(0.0, b - white_base)

            # Normalização pelo pico: multiplica todos os canais para que o mais forte alcance 255.0!
            pure_max = max(r_pure, g_pure, b_pure)
            if pure_max > 0:
                scale = 255.0 / pure_max
                r_out = r_pure * scale
                g_out = g_pure * scale
                b_out = b_pure * scale
            else:
                r_out, g_out, b_out = r, g, b

        # Aplica proporcionalmente o slider de brilho configurado pelo usuário
        final_r = int(round(r_out * self.brightness_factor))
        final_g = int(round(g_out * self.brightness_factor))
        final_b = int(round(b_out * self.brightness_factor))

        return max(0, min(255, final_r)), max(0, min(255, final_g)), max(0, min(255, final_b))

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
                    # Pega as bordas onde a fita reflete na parede
                    h_border = max(2, int(h * 0.15))
                    w_border = max(2, int(w * 0.15))

                    top = img.copy(0, 0, w, h_border).scaled(1, 1, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
                    left = img.copy(0, 0, w_border, h).scaled(1, 1, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
                    right = img.copy(max(0, w - w_border), 0, w_border, h).scaled(1, 1, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)

                    c_top = top.pixelColor(0, 0)
                    c_left = left.pixelColor(0, 0)
                    c_right = right.pixelColor(0, 0)

                    # Topo tem peso duplo porque a barra superior é mais larga
                    raw_r = (c_top.red() * 2.0 + c_left.red() + c_right.red()) / 4.0
                    raw_g = (c_top.green() * 2.0 + c_left.green() + c_right.green()) / 4.0
                    raw_b = (c_top.blue() * 2.0 + c_left.blue() + c_right.blue()) / 4.0
                else:
                    scaled = img.scaled(1, 1, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
                    c = scaled.pixelColor(0, 0)
                    raw_r = float(c.red())
                    raw_g = float(c.green())
                    raw_b = float(c.blue())

                # Suavização Orgânica (EMA)
                if self._last_sent_rgb == (-1, -1, -1):
                    self._cur_r, self._cur_g, self._cur_b = raw_r, raw_g, raw_b
                else:
                    self._cur_r = self._cur_r + self.smoothing * (raw_r - self._cur_r)
                    self._cur_g = self._cur_g + self.smoothing * (raw_g - self._cur_g)
                    self._cur_b = self._cur_b + self.smoothing * (raw_b - self._cur_b)

                # Processa a remoção do branco + esticamento para o brilho máximo
                out_r, out_g, out_b = self._process_color_and_brightness(self._cur_r, self._cur_g, self._cur_b)

                # Filtro Deadband: não polui o Bluetooth se a cor final na parede não mudou
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
