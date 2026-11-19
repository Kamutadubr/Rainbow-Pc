# Arquitetura do Sistema - LotusLanternTray (Rainbow-Pc)

Este documento resume a arquitetura de software, modelo de concorrência e integrações com o sistema operacional Windows.

---

## 1. Visão Geral dos Componentes

O aplicativo é dividido em três camadas principais:

```
[ Interface Gráfica (PySide6) ]
          │   ▲
          │   │  Qt Signals / Slots
          ▼   │
[ BleWorker (QThread + Asyncio Loop) ]
          │
          │  Bleak (GATT Writes)
          ▼
[ Controlador BLE (ELK-BLEDOM) ]
```

1. **Camada de Apresentação (`app.py`):**
   - Janela pop-up sem bordas (`Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool`).
   - Ícone de bandeja do sistema (`QSystemTrayIcon`).
   - Componentes customizados (`ColorWheel`, `SmartTimeEdit`, `AnimatedStackedWidget`).
   - Gerenciamento de eventos de foco e animação suave de fade/slide.

2. **Camada de Comunicação BLE (`ble_controller.py`):**
   - Roda em uma `QThread` separada gerenciando um `asyncio.AbstractEventLoop`.
   - Utiliza a biblioteca `bleak` para comunicação Bluetooth Low Energy.
   - Comunica status e leituras para a UI via `Signal(str, bool)` e `Signal(dict)`.

3. **Camada de Persistência (`settings.json`):**
   - Salva estado de cor, brilho, velocidade, calibração RGB, horários e preferências de inicialização.

---

## 2. Modelo de Concorrência e Threads

* **Thread Principal (Qt GUI):**
  - Processa eventos do usuário, cliques e animações a 60 FPS.
  - Nunca executa chamadas bloqueantes de rede ou Bluetooth.
* **Worker Thread (`BleWorker`):**
  - Herda de `QThread`. Inicia um loop de eventos `asyncio` próprio (`asyncio.new_event_loop()`).
  - Todas as chamadas para a fita (ligar, cor, brilho, timer) são despachadas via `asyncio.run_coroutine_threadsafe(coro, self.loop)`.
  - Envio sem espera de confirmação (`write_gatt_char(..., response=False)`), garantindo latência inferior a 5ms por comando.

---

## 3. Mecanismo de Instância Única (IPC)

Para evitar conflitos com dois processos disputando a mesma conexão BLE com a fita:
* Utiliza `QLocalServer` com a chave nomeada: `LotusLanternTray_SingleInstance_IPC`.
* Ao iniciar:
  - Tenta abrir conexão com `QLocalSocket`.
  - Se o servidor já existir, envia a mensagem `"SHOW"` para o processo em execução (fazendo a janela abrir) e encerra o novo processo imediatamente com `sys.exit(0)`.
  - Se não existir, assume o papel de servidor e começa a escutar conexões locais.

---

## 4. Integração com o Windows

### 4.1. Inicialização Automática no Boot (Autostart)
* Chave de Registro do Windows:
  `HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run`
* Nome do Valor: `LotusLanternTray`
* Comando: Caminho absoluto para inicialização com `pythonw.exe` ou `Init.bat`, garantindo execução sem console aberto.

### 4.2. Posicionamento Dinâmico na Bandeja
* O pop-up não possui barra de título tradicional.
* No clique do ícone da bandeja, calcula a geometria do ícone (`tray_icon.geometry()`) e posiciona a janela imediatamente acima da barra de tarefas (alinhada à direita).
* Ao perder foco (`QEvent.ActivationChange`), a janela recolhe suavemente com animação de slide/fade.
