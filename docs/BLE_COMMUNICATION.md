# Comunicação BLE e Resiliência - LotusLanternTray

Este documento detalha o ciclo de vida da conexão Bluetooth Low Energy (BLE), estratégias contra falhas no boot do Windows, controle de taxa de pacotes e sincronização de horários.

---

## 1. Ciclo de Vida da Conexão e Auto-Reconexão

```
[ Início da Aplicação ]
          │
          ▼
[ BleakScanner Ativo ] ──(Callback de Detecção / Evento)──► [ Dispositivo Encontrado ]
          ▲                                                              │
          │ (Timeout / Retry a cada 2.5s)                                ▼
          └───────────────────────────────────────────────────── [ BleakClient.connect() ]
                                                                         │
                                                                         ▼
                                                                [ Conectado com Sucesso ]
                                                                         │
                                                        (disconnected_callback disparado)
                                                                         │
                                                                         ▼
                                                           [ Dispara trigger_reconnect() ]
```

### 1.1. Mitigação de Falha no Boot do Windows
* **Problema Identificado:** Quando o aplicativo iniciava com o Windows, o método padrão `BleakScanner.find_device_by_address` falhava porque os serviços Bluetooth do sistema operacional ainda estavam subindo ou o cache de anúncios estava vazio. O app ficava preso em *"Conectando ao led"*.
* **Solução:** Implementado escaneamento ativo contínuo com `BleakScanner(detection_callback=...)` e `asyncio.Event`. O scanner escuta ativamente os pacotes de publicidade (advertisements) do MAC configurado ou do prefixo `ELK-BLEDOM`. Assim que o rádio BLE do Windows captura o primeiro pacote, a conexão é iniciada instantaneamente.
* **Callback de Desconexão:** Se a fita for desligada da tomada ou houver queda de sinal, `_on_disconnected` altera o status para *"Desconectado"* e aciona o loop de reconexão automática (`trigger_reconnect()`).

---

## 2. Taxa de Pacotes (Throttling) e Interferência

### 2.1. O Problema da Saturação do Rádio
Adaptadores Bluetooth de computadores (especialmente placas combinadas Wi-Fi + Bluetooth como Intel AX200/AX211 ou dongles USB) compartilham a mesma antena e faixa de 2.4 GHz entre:
1. **Áudio de Alta Qualidade (A2DP / HSP):** fones Bluetooth (tráfego de áudio constante e sensível a jitter).
2. **Bluetooth Low Energy (GATT):** comandos de controle da fita de LED.

Se o aplicativo enviar comandos contínuos sem controle (ex: 60 pacotes por segundo ao arrastar a roda de cores), o stack do Windows prioriza pacotes BLE ou sofre contenção de canal, provocando **cortes, estalos e chiados no fone**. Além disso, o microcontrolador da fita possui buffer serial limitado e trava com excesso de pacotes.

### 2.2. Implementação do Throttling no App
* **Frequência Atual:** Máximo de **~16 a 17 pacotes por segundo** (intervalo mínimo de **60 ms** entre envios).
* **Buffer de Último Valor (`_pending_color`):**
  - Durante o arraste do cursor na `ColorWheel`, eventos intermediários dentro da janela de 60 ms são descartados.
  - O último valor gerado é armazenado em `_pending_color`.
  - Um `QTimer` dedicado a 60 ms descarrega o valor final pendente caso o mouse pare.
  - No evento `mouseReleaseEvent`, a cor final é imediatamente enviada se houver valor retido.

---

## 3. Sincronização de Relógio e Horários (Timers)

### 3.1. Vulnerabilidade do RTC do Controlador
* As fitas `ELK-BLEDOM` **não possuem bateria de backup (bateria de botão)** em seu RTC interno.
* Se a fita for desligada da tomada ou a chave geral for cortada, o relógio interno do microcontrolador zera para `00:00:00`.

### 3.2. Sequência de Inicialização ao Conectar
Sempre que uma conexão é estabelecida com sucesso:
1. O app envia o comando `0x83` com a hora atual exata do computador (`HH:MM:SS:DiaDaSemana`).
2. Aguarda um delay de segurança de `200 ms`.
3. Inscreve-se na característica de notificação `0000fff4-...` para receber confirmações do hardware.

### 3.3. Fallback Local (`_check_local_schedule`)
Para garantir que a fita sempre ligue e desligue nos horários corretos mesmo se o relógio interno do LED sofrer desvio:
* Um `QTimer` no `app.py` roda a cada **10 segundos**.
* Ele compara a hora atual do Windows com os horários programados nas configurações.
* Se atingir o minuto exato configurado, despacha o comando de Ligar ou Desligar via BLE diretamente, funcionando como redundância 100% confiável.
