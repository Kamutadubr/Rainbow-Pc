# LotusLanternTray (Rainbow-Pc) 🌈

Aplicativo moderno em Python (PySide6) para a bandeja do sistema (System Tray) do Windows 11 para controlar fitas de LED Bluetooth compatíveis com o aplicativo **Lotus Lantern** (controladores `ELK-BLEDOM`, `MELK`, etc.) sem depender do celular.

---

## 🧭 Índice de Documentação

Para manter o código e o contexto organizados e modulares, a documentação técnica foi estruturada em arquivos específicos:

| Documento | Assunto / Conteúdo |
| :--- | :--- |
| 📡 [PROTOCOLO_BLE.md](file:///C:/Users/Administrator/Documents/LotusLanternTray/PROTOCOLO_BLE.md) | Engenharia reversa completa dos comandos GATT (Pacotes de 9 bytes, Cores, Brilho, Efeitos, Timers e Clock). |
| 🏗️ [docs/ARCHITECTURE.md](file:///C:/Users/Administrator/Documents/LotusLanternTray/docs/ARCHITECTURE.md) | Arquitetura de concorrência (`QThread` + `asyncio`), modelo IPC de instância única e integração com o registro do Windows. |
| 📶 [docs/BLE_COMMUNICATION.md](file:///C:/Users/Administrator/Documents/LotusLanternTray/docs/BLE_COMMUNICATION.md) | Scanner BLE ativo com callback de eventos (solução para boot frio do Windows), limites de pacotes/segundo (evitando chiado no fone) e reconexão. |
| 🎨 [docs/UI_COMPONENTS.md](file:///C:/Users/Administrator/Documents/LotusLanternTray/docs/UI_COMPONENTS.md) | Design Fluent Obsidian, dimensões fixas (340x535), `ColorWheel` com gradiente cônico/radial e `SmartTimeEdit` com auto-formatação. |
| 🚀 [docs/ROADMAP.md](file:///C:/Users/Administrator/Documents/LotusLanternTray/docs/ROADMAP.md) | Especificação técnica para sincronização Ambilight (15-20 FPS, deadband, suavização EMA) e pontes para Google Home / SmartThings. |

---

## ⚡ Inicialização Rápida

### Pré-requisitos
* Windows 10 ou 11 com Bluetooth ativado.
* Python 3.10+ instalado.
* Fita LED compatível com Lotus Lantern (`ELK-BLEDOM`).

### Instalação de Dependências
```bash
pip install -r requirements.txt # ou: pip install PySide6 bleak
```

### Executar
```bash
pythonw app.py
```
*(ou utilize o arquivo `Init.bat` para iniciar silenciosamente em segundo plano)*
