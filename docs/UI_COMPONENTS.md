# Interface do Usuário e Componentes Customizados

Este documento registra os padrões visuais, regras de layout, dimensões fixas e funcionamento dos componentes de UI desenvolvidos em PySide6.

---

## 1. Diretrizes de Design Visual (Estilo Fluent Obsidian)

O aplicativo segue os princípios de design do Windows 11 (Fluent Design) com paleta escura sofisticada:

| Elemento | Cor / Valor Hex | Descrição |
| :--- | :--- | :--- |
| **Fundo da Janela** | `#0F1117` | Obsidian / Preto fosco profundo com cantos arredondados (16px) |
| **Cards de Seção** | `#181B22` | Superfície interna ligeiramente elevada com borda translúcida |
| **Bordas** | `rgba(255, 255, 255, 0.08)` | Linhas de contorno discretas de 1px |
| **Botões de Navegação** | `#202531` (ativo: `#4F80FF`) | Abas com destaque azul acentuado quando selecionadas |
| **Textos Principais** | `#FFFFFF` | Tipografia Segoe UI Variable / Segoe UI |
| **Textos Secundários** | `#8E909B` | Labels de menor destaque |

---

## 2. Dimensões Fixas e Grid do Layout

Para evitar quebras de alinhamento e cortes de scrollbars:
* **Tamanho Total da Janela (Pop-up):** `340px` (largura) x `535px` (altura).
* **Altura Fixa do `AnimatedStackedWidget`:** `385px`.
* **Dimensão da Roda Cromática (`ColorWheel`):** `155px` x `155px`.
* **Margens Internas:** `14px` no card principal, espaçamento de `8px` entre grupos.

---

## 3. Componentes Customizados

### 3.1. `ColorWheel` (`color_wheel.py`)
Componente vetorial renderizado com `QPainter` e aceleração por antialiasing:
* **Pintura:**
  - Gradiente Cônico (`QConicalGradient`) de 0 a 360° para variação de Matiz (Hue).
  - Gradiente Radial (`QRadialGradient`) do centro para as bordas para variação de Saturação (Saturation).
* **Cursor Seletor:**
  - Anel duplo de alto contraste (borda externa escura + anel interno branco) preenchido com a cor selecionada.
* **Throttling Integrado:**
  - Timer interno de `60 ms` para limitar emissões contínuas do sinal `colorChanged(QColor)`.

### 3.2. `SmartTimeEdit` (`app.py`)
Campo de entrada inteligente derivado de `QLineEdit` para facilidade ao digitar horários:
* **Gatilhos de Auto-Formatação:**
  - Ao pressionar `Enter` / `Return`.
  - Ao perder o foco (`focusOutEvent`, quando o usuário clica em outro lugar da tela).
  - Programaticamente antes de salvar configurações.
* **Regras de Parsing:**
  - `1900` ➔ `19:00`
  - `1745` ou `17,45` ➔ `17:45`
  - `195` ➔ `19:50` (completa dezenas de minutos com zero à direita)
  - `190` ➔ `19:00`
  - `12` ➔ `12:00` (horas redondas)
  - `7` ➔ `07:00`
  - Validação estrita: Horas entre `00-23` e minutos entre `00-59`.

### 3.3. `AnimatedStackedWidget` (`app.py`)
Substituto do `QStackedWidget` padrão com transição de páginas:
* Realiza animação combinada de deslocamento horizontal suave (`slide`) e opacidade (`fade`) com curvas de interpolação `QEasingCurve.OutCubic`.

---

## 4. Estrutura das Abas

1. **Aba 1: Cores (`tab_color_widget`):**
   - Roda cromática interativa (`ColorWheel`).
   - Indicador de cor atual em Hexadecimal (`#RRGGBB`) e ponto de pré-visualização.
   - Presets rápidos de cores comuns (Vermelho, Verde, Azul, Ciano, Roxo, Branco Quente, etc.).
   - Slider de Brilho Geral (`0% a 100%`).
2. **Aba 2: Efeitos (`tab_mode_widget`):**
   - Seletor suspenso (`QComboBox`) com 29 efeitos integrados do chip (Jump, Fade, Strobe, Rainbow).
   - Slider de Velocidade de Transição (`1% a 100%`).
   - Botão com animação e feedback tátil de aplicação.
3. **Aba 3: Horários (`tab_timer_widget`):**
   - Checkbox e campo `SmartTimeEdit` para Horário de Ligar.
   - Checkbox e campo `SmartTimeEdit` para Horário de Desligar.
   - Botão "Salvar e Sincronizar" com feedback visual de 2.5s (`✓ Horários Salvos e Sincronizados!`).
4. **Aba 4: Ajustes (`tab_config_widget`):**
   - ScrollArea transparente com sliders de calibragem individual RGB (Hardware balance: R, G, B de 0 a 100%).
   - Slider de Opacidade visual da janela do app (`40% a 100%`).
   - Checkbox para Inicialização com o Windows (registro no `HKCU`).
   - Indicador de status de conexão e botão para Reconectar / Procurar Fita.
