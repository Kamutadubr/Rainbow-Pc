import winreg
from PySide6.QtGui import QColor

def get_taskbar_color(opacity_percent: int = 85, sync_taskbar: bool = True, theme_name: str = "Obsidian") -> QColor:
    """
    Retorna a cor acrílica translúcida personalizada conforme configurações do usuário.
    """
    alpha = max(100, min(255, int((opacity_percent / 100.0) * 255)))

    THEMES = {
        "Obsidian": (16, 17, 21),
        "Midnight": (12, 16, 28),
        "Graphite": (28, 29, 34),
        "OLED Black": (8, 8, 10),
    }

    base_r, base_g, base_b = THEMES.get(theme_name, (16, 17, 21))

    if sync_taskbar:
        try:
            key_dwm = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\DWM")
            val, _ = winreg.QueryValueEx(key_dwm, "ColorizationColor")
            accent_r = (val >> 16) & 0xFF
            accent_g = (val >> 8) & 0xFF
            accent_b = val & 0xFF

            key_pers = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
            color_prevalence, _ = winreg.QueryValueEx(key_pers, "ColorPrevalence")

            if color_prevalence == 1:
                r = int(base_r * 0.7 + accent_r * 0.3)
                g = int(base_g * 0.7 + accent_g * 0.3)
                b = int(base_b * 0.7 + accent_b * 0.3)
                return QColor(r, g, b, alpha)
        except Exception:
            pass

    return QColor(base_r, base_g, base_b, alpha)
