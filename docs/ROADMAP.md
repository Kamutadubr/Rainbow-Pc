# Roadmap e Novas Funcionalidades - LotusLanternTray

Este documento reúne o planejamento técnico, especificações e arquitetura proposta para novos recursos.

---

## 1. Módulo Ambilight (Sincronização de Luz com a Tela)

### 1.1. Objetivo
Sincronizar a cor e brilho da fita LED em tempo real com a imagem exibida no monitor do computador (ideal para jogos, vídeos e imersão).

### 1.2. Diretrizes Técnicas de Implementação
Para garantir que o Ambilight funcione sem travar o jogo/vídeo e **sem causar chiados ou cortes no fone Bluetooth**:

1. **Taxa de Atualização Alvo:**
   - **15 a 20 FPS** (intervalo de `50 ms` a `66 ms` entre quadros).
   - *Nunca* utilizar 60 FPS no BLE para evitar saturação do adaptador Bluetooth compartilhado com fones de ouvido.
2. **Captura Acelerada da Tela (Zero Overhead de CPU/GPU):**
   - Utilizar a API `Desktop Duplication API` do Windows via biblioteca Python `dxcam` (ou `mss` como fallback).
   - Capturar apenas o monitor principal e redimensionar imediatamente para uma matriz minúscula (ex: `16x16` ou `32x32` pixels) via interpolação bilinear ou amostragem de bordas.
3. **Filtro de Diferença Mínima (Deadband):**
   - Calcular a distância euclidiana ou diferença absoluta entre a cor atual do frame e a última cor enviada:
     $$\Delta C = |R_2 - R_1| + |G_2 - G_1| + |B_2 - B_1|$$
   - Se $\Delta C < \text{limiar}$ (ex: 8), **nenhum pacote BLE é enviado**. Em cenas estáticas ou vídeos lentos, o tráfego BLE cai para quase 0 pacotes/s.
4. **Suavização Orgânica (Exponential Moving Average - EMA):**
   - Aplicar um fator de suavização $\alpha \approx 0.3$ para que transições bruscas de cena não causem cintilação ("flickering") incômoda na parede:
     $$C_{\text{final}} = \alpha \cdot C_{\text{novo}} + (1 - \alpha) \cdot C_{\text{anterior}}$$
5. **Integração na UI:**
   - Adicionar botão alternador "Ambilight" na aba de Efeitos ou como modo dedicado.
   - Tecla de atalho global opcional para ligar/desligar a sincronização.

---

## 2. Integração com Casa Inteligente (SmartThings / Google Home)

Como a fita `ELK-BLEDOM` é estritamente Bluetooth Low Energy (sem Wi-Fi nem chip de rádio proprietário de automação residencial), as opções viáveis de integração são:

### 2.1. Abordagem A: Ponte Local via PC (LotusLantern Bridge)
* **Como funciona:** O próprio aplicativo no PC expõe um pequeno servidor HTTP local ou cliente MQTT.
* **SmartThings / Google Home:** Integra-se via Home Assistant, webhook local ou serviço de ponte (ex: virtual switch no SmartThings ou emulador de lâmpada Philips Hue via `ha-bridge`).
* **Vantagem:** Custo zero de hardware adicional.
* **Desvantagem:** Depende do computador estar ligado.

### 2.2. Abordagem B: Microcontrolador ESP32 como Gateway BLE ➔ Wi-Fi (Recomendado)
* **Como funciona:** Um módulo ESP32 de baixo custo (~R$ 25) fica conectado à tomada no mesmo cômodo. Ele roda firmware aberto (como ESPHome ou OpenMQTTGateway) e conecta-se via BLE na fita usando o protocolo documentado em `PROTOCOLO_BLE.md`.
* **SmartThings / Google Home:** O ESP32 expõe a lâmpada via Matter, Home Assistant ou diretamente por integração de nuvem.
* **Vantagem:** A fita vira um dispositivo smart autônomo, funcionando 24/7 mesmo com o computador desligado.
