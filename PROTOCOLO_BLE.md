# Protocolo de Comunicação BLE - Lotus Lantern / ELK-BLEDOM

Este documento descreve detalhadamente o protocolo de engenharia reversa para controle de fitas de LED e controladores Bluetooth Low Energy (BLE) compatíveis com o aplicativo **Lotus Lantern** (dispositivos identificados tipicamente como `ELK-BLEDOM`, `ELK-BLEDOB`, `MELK`, `LED LIGHT STRIP`, etc.).

---

## 1. Características e Serviços GATT

| Parâmetro | UUID | Função / Permissões |
| :--- | :--- | :--- |
| **Service Principal** | `0000fff0-0000-1000-8000-00805f9b34fb` | Serviço primário do controlador |
| **Write Characteristic** | `0000fff3-0000-1000-8000-00805f9b34fb` | Envio de comandos (**Write Without Response** / Opcode `0x52`) |
| **Read Characteristic** | `0000fff3-0000-1000-8000-00805f9b34fb` | Leitura de estado e configurações salvas |
| **Notify Characteristic** | `0000fff4-0000-1000-8000-00805f9b34fb` | Notificações de resposta de estado / timers |

> **Nota:** Todos os comandos usam pacotes fixos de **9 bytes** delimitados por cabeçalho (`0x7E`) e rodapé (`0xEF`).

---

## 2. Estrutura Geral dos Pacotes

```text
Byte:    [0]   [1]   [2]   [3]   [4]   [5]   [6]   [7]   [8]
Campo:   7E    LEN   CMD   D1    D2    D3    D4    D5    EF
```

- **Byte 0 (`0x7E`)**: Cabeçalho de início de pacote.
- **Byte 1 (`LEN`)**: Comprimento/identificador de tamanho dos dados (varia entre `0x04`, `0x06`, `0x07`).
- **Byte 2 (`CMD`)**: Identificador da instrução (Power, Cor, Brilho, Modo, Relógio, Timer).
- **Bytes 3 a 7 (`D1..D5`)**: Parâmetros específicos do comando e preenchimento (padding).
- **Byte 8 (`0xEF`)**: Rodapé de finalização de pacote.

---

## 3. Comandos Detalhados

### 3.1. Ligar / Desligar (Power)
Liga ou desliga a fita LED.

- **Pacote:** `7E 04 04 [ESTADO] 00 [ESTADO] FF 00 EF`
- **Valores de `ESTADO`:**
  - `0x01`: Ligar
  - `0x00`: Desligar

```python
# Ligar
bytes([0x7E, 0x04, 0x04, 0x01, 0x00, 0x01, 0xFF, 0x00, 0xEF])

# Desligar
bytes([0x7E, 0x04, 0x04, 0x00, 0x00, 0x00, 0xFF, 0x00, 0xEF])
```

---

### 3.2. Controle de Cores RGB Estáticas
Define uma cor personalizada usando canais RGB de 8 bits (0 a 255).

- **Pacote:** `7E 07 05 03 [R] [G] [B] 10 EF`
- **Parâmetros:**
  - `R`: Intensidade do Vermelho (`0x00` a `0xFF`)
  - `G`: Intensidade do Verde (`0x00` a `0xFF`)
  - `B`: Intensidade do Azul (`0x00` a `0xFF`)

```python
# Exemplo: Vermelho Puro (255, 0, 0)
bytes([0x7E, 0x07, 0x05, 0x03, 0xFF, 0x00, 0x00, 0x10, 0xEF])

# Exemplo: Ciano Elétrico (0, 245, 255)
bytes([0x7E, 0x07, 0x05, 0x03, 0x00, 0xF5, 0xFF, 0x10, 0xEF])
```

> **Calibração de Hardware:** Muitos controladores ELK-BLEDOM possuem resistores descalibrados nos canais G (verde) ou B (azul), puxando o vermelho para o rosa/laranja. O aplicativo compensa isso multiplicando os canais `G` e `B` por um fator percentual configurável antes do envio.

---

### 3.3. Controle de Brilho
Ajusta a intensidade geral da iluminação (0% a 100%).

- **Pacote:** `7E 04 01 [BRILHO] FF FF FF 00 EF`
- **Parâmetros:**
  - `[BRILHO]`: Nível de 0 a 100 em formato inteiro/hex (`0x00` a `0x64`).

```python
# Brilho em 100% (100 = 0x64)
bytes([0x7E, 0x04, 0x01, 0x64, 0xFF, 0xFF, 0xFF, 0x00, 0xEF])

# Brilho em 50% (50 = 0x32)
bytes([0x7E, 0x04, 0x01, 0x32, 0xFF, 0xFF, 0xFF, 0x00, 0xEF])
```

---

### 3.4. Modos e Efeitos Dinâmicos
Ativa animações pré-programadas gravadas no microcontrolador.

- **Pacote:** `7E 05 03 [MODO_ID] 03 FF FF 00 EF`
- **IDs de Modos mais comuns:**
  - `0x87`: Vermelho Fade
  - `0x88`: Verde Fade
  - `0x89`: Azul Fade
  - `0x8A`: Amarelo Fade
  - `0x8B`: 7 Cores Fade
  - `0x94`: 7 Cores Jump (Transição seca)
  - `0x95`: 7 Cores Strobe
  - `0x96`: Vermelho Strobe
  - `0x97`: Verde Strobe
  - `0x98`: Azul Strobe

```python
# Ativar 7 Cores Fade (0x8B)
bytes([0x7E, 0x05, 0x03, 0x8B, 0x03, 0xFF, 0xFF, 0x00, 0xEF])
```

---

### 3.5. Velocidade dos Efeitos
Controla a taxa de atualização/velocidade do modo dinâmico ativo (0% a 100%).

- **Pacote:** `7E 04 02 [VELOCIDADE] FF FF FF 00 EF`
- **Parâmetros:**
  - `[VELOCIDADE]`: Nível de 0 a 100 em formato inteiro/hex (`0x00` a `0x64`).

```python
# Velocidade em 80% (80 = 0x50)
bytes([0x7E, 0x04, 0x02, 0x50, 0xFF, 0xFF, 0xFF, 0x00, 0xEF])
```

---

## 4. Sistema de Tempo, Relógio e Agendamento

O chip do controlador **não possui bateria RTC interna**. Para que o agendador funcione, a hora atual do computador/celular deve ser sincronizada antes de gravar qualquer timer.

### 4.1. Sincronização do Relógio (Clock Sync)
Envia o horário de parede e o dia da semana atual para o relógio volátil do chip.

- **Pacote:** `7E 06 83 [HH] [MM] [SS] [WW] 00 EF`
- **Parâmetros:**
  - `HH`: Hora atual (0 a 23 / `0x00` a `0x17`)
  - `MM`: Minuto atual (0 a 59 / `0x00` a `0x3B`)
  - `SS`: Segundo atual (0 a 59 / `0x00` a `0x3B`)
  - `WW`: Dia da semana (1 a 7, onde **1 = Segunda-feira ... 7 = Domingo**)
  - `00`: Byte fixo de padding

```python
# Exemplo: Sábado (WW=6), 19:30:00
bytes([0x7E, 0x06, 0x83, 19, 30, 0, 6, 0x00, 0xEF])
```

---

### 4.2. Agendamento / Timers de Hardware
Grava um evento programado para ligar ou desligar a fita automaticamente em um determinado horário.

- **Pacote:** `7E 07 82 [HH] [MM] 00 [TT] [BB] EF`
- **Parâmetros:**
  - `HH`: Hora programada (0 a 23)
  - `MM`: Minuto programado (0 a 59)
  - `00`: Padding fixo
  - `TT`: Tipo de ação:
    - `0x00`: Ligar (ON)
    - `0x01`: Desligar (OFF)
  - `BB`: Máscara de dias e ativação:
    - **Bit 7 (`0x80`)**: Habilita o timer (`1` = Ativo, `0` = Desativado)
    - **Bits 0 a 6**: Dias da semana repetidos:
      - Bit 0 (`0x01`): Segunda-feira
      - Bit 1 (`0x02`): Terça-feira
      - Bit 2 (`0x04`): Quarta-feira
      - Bit 3 (`0x08`): Quinta-feira
      - Bit 4 (`0x10`): Sexta-feira
      - Bit 5 (`0x20`): Sábado
      - Bit 6 (`0x40`): Domingo
      - Todos os dias: `0x7F` (127)
      - Todos os dias + Habilitado: `0x80 | 0x7F = 0xFF` (255)

```python
# Ligar todos os dias às 19:00 (Habilitado: 0xFF)
bytes([0x7E, 0x07, 0x82, 19, 0, 0x00, 0x00, 0xFF, 0xEF])

# Desligar todos os dias às 02:00 (Habilitado: 0xFF)
bytes([0x7E, 0x07, 0x82, 2, 0, 0x00, 0x01, 0xFF, 0xEF])

# Desativar timer de Ligar
bytes([0x7E, 0x07, 0x82, 0, 0, 0x00, 0x00, 0x00, 0xEF])
```

---

## 5. Resposta e Notificações (Notify / Read)

Ao ler a característica `READ_CHAR_UUID` ou receber notificação em `NOTIFY_CHAR_UUID`, o dispositivo pode retornar dados de status e timers salvos:

```text
Formato: [0x7E, 0x08, 0x82, HORA, MIN, SEC, ACAO, MASCARA_STATUS, 0xEF, ...]
```
- `data[2] == 0x82`: Identifica pacote de agendamento retornado.
- `data[3]`: Hora configurada.
- `data[4]`: Minuto configurado.
- `data[6]`: Ação (`0x00` = Ligar, `0x01` = Desligar).
- `data[7]`: Byte de status/dias (Bit 7 indica se está ativo; bits 0-6 representam os dias).

---

## 6. Boas Práticas e Recomendações de Implementação

1. **Write Without Response:** Comandos BLE devem ser enviados com `response=False` para evitar esperas bloqueantes e rejeição pelo firmware.
2. **Taxa de Atualização (Throttle):** Não exceder 15-20 comandos por segundo (~50ms a 60ms de intervalo mínimo) para não engasgar o buffer de recepção do rádio.
3. **Persistência de Conexão:** Como o hardware não possui RTC físico permanente, interrupções longas de energia na fita apagam a hora gravada. É recomendável enviar a sincronização de relógio (`0x83`) automaticamente em cada conexão estabelecida e manter um fallback em software (no próprio aplicativo cliente) para garantir o acionamento pontual dos timers.
