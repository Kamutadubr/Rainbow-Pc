import asyncio
import json
import os
import threading
from datetime import datetime
from typing import Optional, Callable
from bleak import BleakClient, BleakScanner

SERVICE_UUID = "0000fff0-0000-1000-8000-00805f9b34fb"
WRITE_CHAR_UUID = "0000fff3-0000-1000-8000-00805f9b34fb"
READ_CHAR_UUID = "0000fff3-0000-1000-8000-00805f9b34fb"
NOTIFY_CHAR_UUID = "0000fff4-0000-1000-8000-00805f9b34fb"
SUPPORTED_PREFIXES = ["ELK-", "ELK~", "LED LIGHT STRIP", "XSL-", "MELK"]

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")
LEGACY_CONFIG = os.path.join(os.path.expanduser("~"), "Documents", "last_led_device.json")

def load_settings() -> dict:
    defaults = {
        "address": "",
        "name": "ELK-BLEDOM",
        "power": True,
        "color": [255, 0, 128],
        "brightness": 85,
        "mode": 0x8B,
        "speed": 80,
        "timer_on_enabled": False,
        "timer_on_time": "07:00",
        "timer_off_enabled": False,
        "timer_off_time": "23:30",
        "timer_days_mask": 0x7F,
        # Configurações de Customização
        "opacity": 85,
        "sync_taskbar_color": True,
        "start_with_windows": False,
        "icon_glow": True,
        "accent_theme": "Obsidian",
        # Calibração / Balanço de Cores do LED (R, G, B em %)
        "calib_r": 100,
        "calib_g": 60,
        "calib_b": 75
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                defaults.update(data)
                return defaults
        except Exception:
            pass

    if os.path.exists(LEGACY_CONFIG):
        try:
            with open(LEGACY_CONFIG, "r", encoding="utf-8") as f:
                data = json.load(f)
                if "address" in data and data["address"]:
                    defaults["address"] = data["address"]
                if "name" in data and data["name"]:
                    defaults["name"] = data["name"]
                save_settings(defaults)
        except Exception:
            pass

    return defaults

def save_settings(settings: dict):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
    except Exception:
        pass

class BleWorker:
    """Gerenciador assíncrono em segundo plano para conexão BLE estável."""
    def __init__(self, on_status_changed: Callable[[str, bool], None], on_timer_read: Optional[Callable[[dict], None]] = None):
        self.on_status_changed = on_status_changed
        self.on_timer_read = on_timer_read
        self.settings = load_settings()
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.thread: Optional[threading.Thread] = None
        self.client: Optional[BleakClient] = None
        self.is_connected = False
        self.is_busy = False
        self._running = True

    def start(self):
        self.thread = threading.Thread(target=self._run_event_loop, daemon=True)
        self.thread.start()

    def _run_event_loop(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.create_task(self._auto_connect_loop())
        self.loop.run_forever()

    async def _auto_connect_loop(self):
        await asyncio.sleep(0.3)
        while self._running:
            if not self.is_connected and not self.is_busy:
                await self.try_connect()
            await asyncio.sleep(4)

    def trigger_reconnect(self):
        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self.try_connect(), self.loop)

    async def try_connect(self) -> bool:
        if self.is_busy or self.is_connected:
            return self.is_connected

        self.is_busy = True
        target_addr = self.settings.get("address")
        target_name = self.settings.get("name", "LED")

        # 1. TENTA CONEXÃO DIRETA PELO MAC
        if target_addr:
            try:
                self.on_status_changed(f"Conectando a {target_name}...", False)
                client = BleakClient(target_addr)
                await client.connect(timeout=6.0)
                if client.is_connected:
                    self.client = client
                    self.is_connected = True
                    self.on_status_changed(f"Conectado: {target_name}", True)
                    await self._on_connected_actions()
                    self.is_busy = False
                    return True
            except Exception:
                pass

        # 2. SCAN SE CONEXÃO DIRETA FALHAR
        self.on_status_changed("Procurando LED...", False)
        try:
            devices = await BleakScanner.discover(timeout=4.0)
            target_device = None

            if target_addr:
                for d in devices:
                    if d.address.upper() == target_addr.upper():
                        target_device = d
                        break

            if not target_device:
                for d in devices:
                    d_name = d.name or ""
                    if any(p in d_name for p in SUPPORTED_PREFIXES):
                        target_device = d
                        break

            if not target_device:
                self.on_status_changed("LED não encontrado nas proximidades", False)
                self.is_busy = False
                return False

            dev_name = target_device.name or target_name
            self.on_status_changed(f"Conectando a {dev_name}...", False)

            client = BleakClient(target_device)
            await client.connect(timeout=8.0)

            if client.is_connected:
                self.client = client
                self.is_connected = True
                self.settings["address"] = target_device.address
                self.settings["name"] = dev_name
                save_settings(self.settings)

                self.on_status_changed(f"Conectado: {dev_name}", True)
                await self._on_connected_actions()
                self.is_busy = False
                return True
            else:
                self.is_connected = False
                self.on_status_changed("Falha ao parear com LED", False)
        except Exception:
            self.is_connected = False
            self.on_status_changed("Desconectado", False)
        finally:
            self.is_busy = False

        return False

    async def _on_connected_actions(self):
        """Rotina de inicialização executada assim que conecta com o LED."""
        # 1. Sincroniza o relógio interno
        await self._sync_clock()
        await asyncio.sleep(0.2)

        # 2. Inscreve em notificações na característica FFF4 (se disponível)
        try:
            await self.client.start_notify(NOTIFY_CHAR_UUID, self._on_notification_received)
        except Exception:
            pass

        # 3. Lê os dados atuais salvos no microcontrolador (horários de timer gravados)
        await self._read_hardware_schedule()

    def _on_notification_received(self, sender, data: bytes):
        self._parse_incoming_packet(data)

    async def _read_hardware_schedule(self):
        try:
            data = await self.client.read_gatt_char(READ_CHAR_UUID)
            if data:
                self._parse_incoming_packet(data)
        except Exception:
            pass

    def _parse_incoming_packet(self, data: bytes):
        """
        Interpreta pacote retornado pelo controlador:
        Formato: [7E, 08, 82, HORA, MIN, SEC, ACAO, MASCARA_STATUS, EF, ...]
        """
        if len(data) >= 8 and data[0] == 0x7E:
            if data[2] == 0x82:
                hour = data[3]
                minute = data[4]
                action = data[6]  # 0x00 = Ligar, 0x01 = Desligar
                mask_byte = data[7]
                enabled = bool(mask_byte & 0x80)
                days_mask = mask_byte & 0x7F

                time_str = f"{hour:02d}:{minute:02d}"
                info = {
                    "action": action,
                    "time": time_str,
                    "enabled": enabled,
                    "days_mask": days_mask
                }

                if action == 0x00:
                    self.settings["timer_on_enabled"] = enabled
                    self.settings["timer_on_time"] = time_str
                else:
                    self.settings["timer_off_enabled"] = enabled
                    self.settings["timer_off_time"] = time_str

                self.settings["timer_days_mask"] = days_mask
                save_settings(self.settings)

                if self.on_timer_read:
                    self.on_timer_read(info)

    def send_command(self, packet: bytes):
        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self._async_send(packet), self.loop)

    async def _async_send(self, packet: bytes):
        if not self.is_connected or not self.client:
            return
        try:
            await self.client.write_gatt_char(WRITE_CHAR_UUID, packet, response=False)
        except Exception:
            self.is_connected = False
            self.on_status_changed("Conexão perdida", False)

    async def _sync_clock(self):
        now = datetime.now()
        # No protocolo Lotus/ELK: Segunda = 1, Domingo = 7 (now.weekday() dá Mon=0...Sun=6)
        weekday = now.weekday() + 1
        pkt = bytes([0x7E, 0x06, 0x83, now.hour, now.minute, now.second, weekday, 0x00, 0xEF])
        await self._async_send(pkt)

    def sync_clock(self):
        """Dispara sincronização do relógio em background."""
        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self._sync_clock(), self.loop)

    # Comandos de Alto Nível
    def turn_on(self, on: bool):
        val = 0x01 if on else 0x00
        pkt = bytes([0x7E, 0x04, 0x04, val, 0x00, val, 0xFF, 0x00, 0xEF])
        self.send_command(pkt)
        self.settings["power"] = on
        save_settings(self.settings)

    def set_color(self, r: int, g: int, b: int):
        self.settings["color"] = [r, g, b]
        save_settings(self.settings)

        # Aplica calibração de canais para compensar a fita física
        kr = self.settings.get("calib_r", 100) / 100.0
        kg = self.settings.get("calib_g", 100) / 100.0
        kb = self.settings.get("calib_b", 100) / 100.0

        r_out = max(0, min(255, int(r * kr)))
        g_out = max(0, min(255, int(g * kg)))
        b_out = max(0, min(255, int(b * kb)))

        pkt = bytes([0x7E, 0x07, 0x05, 0x03, r_out, g_out, b_out, 0x10, 0xEF])
        self.send_command(pkt)

    def set_brightness(self, percent: int):
        percent = max(0, min(100, percent))
        pkt = bytes([0x7E, 0x04, 0x01, percent, 0xFF, 0xFF, 0xFF, 0x00, 0xEF])
        self.send_command(pkt)
        self.settings["brightness"] = percent
        save_settings(self.settings)

    def set_mode(self, mode_id: int):
        pkt = bytes([0x7E, 0x05, 0x03, mode_id & 0xFF, 0x03, 0xFF, 0xFF, 0x00, 0xEF])
        self.send_command(pkt)
        self.settings["mode"] = mode_id
        save_settings(self.settings)

    def set_speed(self, speed_percent: int):
        speed_percent = max(0, min(100, speed_percent))
        pkt = bytes([0x7E, 0x04, 0x02, speed_percent, 0xFF, 0xFF, 0xFF, 0x00, 0xEF])
        self.send_command(pkt)
        self.settings["speed"] = speed_percent
        save_settings(self.settings)

    def set_timer(self, hour: int, minute: int, turn_on: bool, enabled: bool = True, days_mask: int = 0x7F):
        slot = 0x00 if turn_on else 0x01
        # No protocolo: bit 7 = ativado (0x80), bits 0-6 = máscara de dias (0x7F = todos os dias)
        status_byte = (days_mask & 0x7F)
        if enabled:
            status_byte |= 0x80
        else:
            status_byte = 0x00

        # Formato correto do comando 82: 7E 07 82 HH MM 00 TT BB EF
        pkt = bytes([0x7E, 0x07, 0x82, hour, minute, 0x00, slot, status_byte, 0xEF])
        self.send_command(pkt)

        time_str = f"{hour:02d}:{minute:02d}"
        if turn_on:
            self.settings["timer_on_enabled"] = enabled
            self.settings["timer_on_time"] = time_str
        else:
            self.settings["timer_off_enabled"] = enabled
            self.settings["timer_off_time"] = time_str
        self.settings["timer_days_mask"] = days_mask
        save_settings(self.settings)
