import asyncio
import json
import os
import sys
from datetime import datetime
from bleak import BleakClient, BleakScanner

# UUIDs obtidos diretamente da engenharia reversa do APK Lotus Lantern
SERVICE_UUID = "0000fff0-0000-1000-8000-00805f9b34fb"
WRITE_CHAR_UUID = "0000fff3-0000-1000-8000-00805f9b34fb"

SUPPORTED_PREFIXES = ["ELK-", "ELK~", "LED LIGHT STRIP", "XSL-", "MELK"]
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "last_led_device.json")

MODOS_PREDEFINIDOS = [
    (0x80, "Vermelho Estático"),
    (0x81, "Azul Estático"),
    (0x82, "Verde Estático"),
    (0x83, "Amarelo Estático"),
    (0x84, "Ciano Estático"),
    (0x85, "Roxo Estático"),
    (0x86, "Branco Estático"),
    (0x87, "Vermelho Gradual (Fade)"),
    (0x88, "Verde Gradual (Fade)"),
    (0x89, "Azul Gradual (Fade)"),
    (0x8A, "Amarelo Gradual (Fade)"),
    (0x8B, "7 Cores Fade Cruzado"),
    (0x94, "7 Cores Saltando (Jump)"),
    (0x95, "7 Cores Estroboscópio (Strobe)"),
    (0x96, "Vermelho Estroboscópio"),
    (0x97, "Verde Estroboscópio"),
    (0x98, "Azul Estroboscópio"),
]

def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")

def load_saved_device():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None

def save_device(address: str, name: str):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({"address": address, "name": name}, f, indent=2)
    except Exception as e:
        print(f"Erro ao salvar dispositivo: {e}")

class LotusLanternController:
    def __init__(self, client: BleakClient):
        self.client = client
        self.last_status = "Pronto para receber comandos."

    async def send_raw_command(self, packet: bytes):
        await self.client.write_gatt_char(WRITE_CHAR_UUID, packet, response=False)

    async def turn_on(self, on: bool = True):
        val = 0x01 if on else 0x00
        packet = bytes([0x7E, 0x04, 0x04, val, 0x00, val, 0xFF, 0x00, 0xEF])
        await self.send_raw_command(packet)
        self.last_status = f"LED {'LIGADO' if on else 'DESLIGADO'}."

    async def set_color(self, r: int, g: int, b: int):
        r = max(0, min(255, r))
        g = max(0, min(255, g))
        b = max(0, min(255, b))
        packet = bytes([0x7E, 0x07, 0x05, 0x03, r, g, b, 0x10, 0xEF])
        await self.send_raw_command(packet)
        self.last_status = f"Cor alterada para RGB({r}, {g}, {b})."

    async def set_brightness(self, percent: int):
        percent = max(0, min(100, percent))
        packet = bytes([0x7E, 0x04, 0x01, percent, 0xFF, 0xFF, 0xFF, 0x00, 0xEF])
        await self.send_raw_command(packet)
        self.last_status = f"Brilho definido em {percent}%."

    async def set_mode(self, mode_id: int, mode_name: str = ""):
        packet = bytes([0x7E, 0x05, 0x03, mode_id & 0xFF, 0x03, 0xFF, 0xFF, 0x00, 0xEF])
        await self.send_raw_command(packet)
        nome = f" ({mode_name})" if mode_name else ""
        self.last_status = f"Modo dinâmico 0x{mode_id:02X}{nome} ativado."

    async def set_speed(self, speed_percent: int):
        speed_percent = max(0, min(100, speed_percent))
        packet = bytes([0x7E, 0x04, 0x02, speed_percent, 0xFF, 0xFF, 0xFF, 0x00, 0xEF])
        await self.send_raw_command(packet)
        self.last_status = f"Velocidade do modo definida em {speed_percent}%."

    async def sync_system_time(self):
        now = datetime.now()
        weekday = (now.weekday() + 1) % 7
        packet = bytes([0x7E, 0x07, 0x83, now.hour, now.minute, now.second, weekday, 0xFF, 0xEF])
        await self.send_raw_command(packet)
        self.last_status = f"Relógio sincronizado com o PC: {now.strftime('%H:%M:%S')} (Dia: {weekday})."

    async def set_schedule(self, hour: int, minute: int, turn_on: bool, enabled: bool = True, days_mask: int = 0x7F):
        slot = 0x00 if turn_on else 0x01
        status_byte = (days_mask & 0x7F)
        if enabled:
            status_byte |= 0x80
        packet = bytes([0x7E, 0x08, 0x82, hour, minute, 0x00, slot, status_byte, 0xEF])
        await self.send_raw_command(packet)
        acao = "LIGAR" if turn_on else "DESLIGAR"
        status = "HABILITADO" if enabled else "DESABILITADO"
        self.last_status = f"Agendamento para {acao} às {hour:02d}:{minute:02d} configurado ({status})."


async def scan_and_select_device():
    clear_screen()
    print("=" * 60)
    print("   SELEÇÃO MANUAL DE DISPOSITIVO BLUETOOTH")
    print("=" * 60)
    print("\nEscaneando dispositivos por perto (aguarde 5s)...")
    
    devices = await BleakScanner.discover(timeout=5.0)
    clear_screen()
    print("=" * 60)
    print("   DISPOSITIVOS ENCONTRADOS")
    print("=" * 60)

    if not devices:
        print("\nNenhum dispositivo Bluetooth encontrado.")
        input("\nPressione Enter para sair...")
        return None

    candidates = []
    others = []
    for d in devices:
        name = d.name or "Dispositivo Desconhecido"
        if any(p in name for p in SUPPORTED_PREFIXES):
            candidates.append(d)
        else:
            others.append(d)

    idx = 1
    device_list = []
    if candidates:
        print("\n--- Dispositivos Recomendados (Controladores LED) ---")
        for d in candidates:
            print(f"  [{idx}] {d.name} ({d.address})")
            device_list.append(d)
            idx += 1

    if others:
        print("\n--- Outros Dispositivos Bluetooth Encontrados ---")
        for d in others:
            name = d.name or "Desconhecido"
            print(f"  [{idx}] {name} ({d.address})")
            device_list.append(d)
            idx += 1

    print(f"\n  [0] Digitar Endereço MAC manualmente")

    while True:
        choice = input("\nEscolha o número do seu dispositivo (ou 0 para digitar MAC): ").strip()
        if choice == "0":
            mac = input("Digite o endereço MAC do dispositivo: ").strip()
            return {"address": mac, "name": "Dispositivo Manual"} if mac else None
        if choice.isdigit():
            c_int = int(choice)
            if 1 <= c_int <= len(device_list):
                selected = device_list[c_int - 1]
                return {"address": selected.address, "name": selected.name or "LED Controller"}
        print("Opção inválida, tente novamente.")


async def get_target_device():
    saved = load_saved_device()
    if saved and "address" in saved:
        saved_addr = saved["address"]
        saved_name = saved.get("name", "LED Controller")
        clear_screen()
        print("=" * 60)
        print("   LOTUS LANTERN - CONTROLE DE LED VIA BLUETOOTH (PC)")
        print("=" * 60)
        print(f"\nDispositivo salvo anteriormente: {saved_name} ({saved_addr})")
        print("Procurando conexão rápida...")
        
        # Faz uma busca rápida de 3 segundos para confirmar presença
        device = await BleakScanner.find_device_by_address(saved_addr, timeout=3.0)
        if device:
            print(f"[+] Dispositivo encontrado! Conectando automaticamente...")
            return {"address": device.address, "name": device.name or saved_name}
        else:
            print(f"[-] O dispositivo anterior ({saved_addr}) não foi encontrado nas proximidades.")
            print("Iniciando escaneamento para seleção de dispositivo...")
            await asyncio.sleep(1.5)

    selected = await scan_and_select_device()
    if selected and "address" in selected:
        save_device(selected["address"], selected.get("name", "LED Controller"))
    return selected


def print_main_screen(controller: LotusLanternController):
    clear_screen()
    print("=" * 55)
    print("              PAINEL DE CONTROLE LED")
    print("=" * 55)
    print(f" Status Atual: [ {controller.last_status} ]")
    print("=" * 55)
    print(" [1] 💡 Ligar Luz")
    print(" [2] 🌑 Desligar Luz")
    print(" [3] 🎨 Mudar Cor (RGB ou Paleta Rápida)")
    print(" [4] ☀️ Ajustar Brilho (0% a 100%)")
    print(" [5] 🎭 Modos e Efeitos Dinâmicos (Fade, Jump, Strobe)")
    print(" [6] ⏩ Ajustar Velocidade do Efeito (0% a 100%)")
    print(" [7] ⏰ Programar Horário (Timer de Ligar / Desligar)")
    print(" [8] 🕒 Sincronizar Relógio Interno")
    print(" [9] 🔄 Esquecer dispositivo salvo e reconectar")
    print(" [0] 🚪 Sair")
    print("=" * 55)


async def handle_color_menu(controller: LotusLanternController):
    clear_screen()
    print("=" * 55)
    print("                 SELEÇÃO DE COR")
    print("=" * 55)
    print(" [1] Vermelho     [2] Verde       [3] Azul")
    print(" [4] Amarelo      [5] Ciano       [6] Roxo/Magenta")
    print(" [7] Laranja      [8] Branco")
    print(" [9] Digitar RGB customizado (ex: 255 100 50)")
    print(" [0] Voltar ao Menu Principal")
    print("=" * 55)
    
    escolha = input("\nEscolha uma opção: ").strip()
    presets = {
        "1": (255, 0, 0),
        "2": (0, 255, 0),
        "3": (0, 0, 255),
        "4": (255, 255, 0),
        "5": (0, 255, 255),
        "6": (255, 0, 255),
        "7": (255, 80, 0),
        "8": (255, 255, 255),
    }

    if escolha in presets:
        r, g, b = presets[escolha]
        await controller.set_color(r, g, b)
    elif escolha == "9":
        val = input("Digite R, G e B separados por espaço (0-255, ex: 255 120 0): ").strip()
        try:
            parts = [int(p) for p in val.split()]
            if len(parts) == 3:
                await controller.set_color(parts[0], parts[1], parts[2])
            else:
                controller.last_status = "Erro: formato inválido (devem ser 3 números)."
        except ValueError:
            controller.last_status = "Erro: entrada não numérica."


async def handle_mode_menu(controller: LotusLanternController):
    clear_screen()
    print("=" * 55)
    print("           EFEITOS E MODOS DINÂMICOS")
    print("=" * 55)
    for i, (m_id, m_name) in enumerate(MODOS_PREDEFINIDOS, 1):
        print(f" [{i:02d}] {m_name}")
    print(" [0] Voltar ao Menu Principal")
    print("=" * 55)

    opc = input("\nEscolha um modo dinâmico: ").strip()
    if opc.isdigit():
        num = int(opc)
        if 1 <= num <= len(MODOS_PREDEFINIDOS):
            m_id, m_name = MODOS_PREDEFINIDOS[num - 1]
            await controller.set_mode(m_id, m_name)


async def handle_schedule_menu(controller: LotusLanternController):
    clear_screen()
    print("=" * 55)
    print("           PROGRAMAR HORÁRIO (TIMER)")
    print("=" * 55)
    print(" [1] Programar Horário para LIGAR")
    print(" [2] Programar Horário para DESLIGAR")
    print(" [3] Desativar Agendamento de Ligar")
    print(" [4] Desativar Agendamento de Desligar")
    print(" [0] Voltar ao Menu Principal")
    print("=" * 55)

    opc = input("\nEscolha uma opção: ").strip()
    if opc in ["1", "2"]:
        turn_on = (opc == "1")
        tipo = "LIGAR" if turn_on else "DESLIGAR"
        hora_str = input(f"Digite a hora para {tipo} (formato HH:MM, ex: 07:30 ou 23:45): ").strip()
        try:
            hora, minuto = map(int, hora_str.split(":"))
            if not (0 <= hora <= 23 and 0 <= minuto <= 59):
                controller.last_status = "Erro: hora ou minuto fora do limite válido."
                return
        except ValueError:
            controller.last_status = "Erro: formato de hora inválido. Use HH:MM."
            return

        print("\nRepetir em quais dias?")
        print(" [1] Todos os dias")
        print(" [2] Segunda a Sexta")
        print(" [3] Fim de Semana (Sáb e Dom)")
        dia_opc = input("Opção de repetição [1]: ").strip() or "1"
        if dia_opc == "2":
            mask = 0x02 | 0x04 | 0x08 | 0x10 | 0x20
        elif dia_opc == "3":
            mask = 0x01 | 0x40
        else:
            mask = 0x7F

        await controller.sync_system_time()
        await asyncio.sleep(0.3)
        await controller.set_schedule(hora, minuto, turn_on=turn_on, enabled=True, days_mask=mask)

    elif opc in ["3", "4"]:
        turn_on = (opc == "3")
        await controller.set_schedule(0, 0, turn_on=turn_on, enabled=False)


async def interactive_loop(controller: LotusLanternController):
    while True:
        print_main_screen(controller)
        cmd = input("Digite a opção desejada: ").strip()

        if cmd == "1":
            await controller.turn_on(True)
        elif cmd == "2":
            await controller.turn_on(False)
        elif cmd == "3":
            await handle_color_menu(controller)
        elif cmd == "4":
            clear_screen()
            print("=" * 55)
            print("                 AJUSTE DE BRILHO")
            print("=" * 55)
            b_str = input("Digite o nível de brilho (0 a 100): ").strip()
            if b_str.isdigit():
                await controller.set_brightness(int(b_str))
            else:
                controller.last_status = "Erro: valor de brilho inválido."
        elif cmd == "5":
            await handle_mode_menu(controller)
        elif cmd == "6":
            clear_screen()
            print("=" * 55)
            print("           AJUSTE DE VELOCIDADE DO EFEITO")
            print("=" * 55)
            s_str = input("Digite a velocidade do efeito (0 a 100): ").strip()
            if s_str.isdigit():
                await controller.set_speed(int(s_str))
            else:
                controller.last_status = "Erro: valor de velocidade inválido."
        elif cmd == "7":
            await handle_schedule_menu(controller)
        elif cmd == "8":
            await controller.sync_system_time()
        elif cmd == "9":
            if os.path.exists(CONFIG_FILE):
                os.remove(CONFIG_FILE)
            clear_screen()
            print("Dispositivo salvo esquecido com sucesso! Reinicie o script para escolher outro.")
            input("Pressione Enter para sair...")
            break
        elif cmd == "0":
            clear_screen()
            print("Encerrando conexão com o LED. Até mais!")
            break
        else:
            controller.last_status = "Opção inválida, tente novamente."


async def main():
    target = await get_target_device()
    if not target:
        return

    address = target["address"]
    name = target.get("name", "LED Controller")
    
    clear_screen()
    print(f"Conectando a {name} ({address})...")

    try:
        async with BleakClient(address) as client:
            controller = LotusLanternController(client)
            # Sincroniza o relógio automaticamente logo ao conectar
            await controller.sync_system_time()
            controller.last_status = f"Conectado a {name} e relógio sincronizado!"
            await interactive_loop(controller)
    except Exception as e:
        clear_screen()
        print(f"[ERRO DE CONEXÃO]: {e}")
        print("\nDicas:")
        print(" 1. Verifique se o app Lotus Lantern no celular está fechado (BLE suporta 1 conexão por vez).")
        print(" 2. Verifique se o Bluetooth do Windows está ativado.")
        print(" 3. Se trocou de dispositivo ou ele mudou de endereço, delete 'last_led_device.json'.")

if __name__ == "__main__":
    asyncio.run(main())
