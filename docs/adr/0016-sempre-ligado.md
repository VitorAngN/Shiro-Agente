# ADR-0016 · Sempre ligado: bandeja, "Ei, Shiro" e início com o Windows

- **Status:** Aceito
- **Data:** 2026-11-01
- **Complementa:** [ADR-0008](0008-processo-de-usuario-no-windows.md) e [ADR-0015](0015-implementacao-da-voz.md)

## Contexto

A Fase 2 transforma o SHIRO em parte do PC: um ícone na bandeja, que inicia sozinho e atende "Ei, Shiro". Três pontos pediam decisão:

1. **Palavra de ativação.** O ADR-0004 previa o openWakeWord com um modelo próprio. Na prática:
   - o pacote `openwakeword` no PyPI parou na 0.4 (2023);
   - as versões novas exigem `tflite-runtime`, que não tem build para Python 3.12 no Linux;
   - o pacote puxa scipy e scikit-learn;
   - treinar "Ei, Shiro" exige baixar vários GB de dados negativos e horas de GPU.
2. **Confirmação física sem terminal.** Na bandeja não há teclado de terminal para as ações R3.
3. **Início no logon.** Criar tarefa com gatilho de logon pode exigir elevação em algumas contas.

Medido antes de decidir (frases sintetizadas, sem microfone):

- o pipeline do openWakeWord rodado direto em ONNX deu as mesmas notas do pacote (diferença máxima 0,0055):
  - "Hey Jarvis" → 0,999;
  - frases em português → 0,000;
  - custo: ~4 ms por bloco de 80 ms.

## Decisão

1. **Dois motores de palavra de ativação** (`voice.wake_word.engine`):
   - **`whisper` (padrão):**
     - o Silero VAD recorta cada fala de até 8 s, e um Whisper `base` (2 threads) confere se ela começa com "Ei/Oi/Ok Shiro" ou "Shiro". Grafias como "Xiro" e "Chiro" também valem;
     - se o pedido veio junto ("Ei Shiro, abre o Spotify"), a fala é transcrita de novo com o Whisper principal e vai direto ao agente;
     - funciona **com o nome de verdade, sem treino**. Custo: CPU por fala ouvida enquanto a escuta está ligada.
   - **`openwakeword`:**
     - os três modelos ONNX (melspectrograma → embedding → classificador) rodam pelo onnxruntime que o SHIRO já usa, **sem o pacote**;
     - os modelos vêm da release v0.5.1 com SHA-256 fixado;
     - aceita modelo embutido (`hey_jarvis`, para testar) ou um `.onnx` treinado. É o caminho leve para quando houver um modelo "Ei, Shiro" (guia em `docs/guias/treinar-ei-shiro.md`).
2. **A escuta contínua é opcional.** O padrão continua `activation = "push_to_talk"`. Ela só liga com `wake_word`/`both` ou pelo menu da bandeja, e fica em pausa enquanto a SHIRO ouve, pensa ou fala.
3. **Janela de continuação:** com a palavra de ativação ligada, depois de responder a SHIRO ouve por `follow_up_window_s` (5 s) sem precisar ser chamada de novo. Sem fala, a janela fecha em silêncio, sem bipe de erro.
4. **Bandeja com `pystray` (LGPL-3, usado como biblioteca):**
   - ícone desenhado na hora com a paleta: branco pronta, vermelho ouvindo, âmbar pensando, ciano falando, cinza com a escuta pausada;
   - menu: falar, parar, ligar ou desligar "Ei, Shiro", liberar a GPU (Modo Desempenho), iniciar com o Windows, abrir registros, sair;
   - lembretes e o resumo do dia (RF-39) aparecem como notificação do Windows.
5. **Confirmação física na bandeja:** uma janela "Sim/Não" do Windows, com **"Não" como padrão**. Voz nunca confirma R3.
6. **`shiro-tray`** é um script de GUI: roda sem janela de console, e a saída da sessão vai para o log.
7. **Instância única:**
   - no Windows, mutex nomeado `Local\SHIRO-Agente`;
   - em outros sistemas, trava de arquivo.
   Vale para `shiro voice` e para a bandeja: dois SHIROs no mesmo microfone brigariam.
8. **Início no logon:** `shiro autostart on` (ou o menu) cria a tarefa `SHIRO` no Agendador:
   - logon do usuário + 30 s;
   - `LeastPrivilege`, só com o usuário conectado;
   - reinicia até 3 vezes se falhar;
   - sem limite de tempo.
   Se o Windows negar a tarefa, cai para a chave `Run` do registro do usuário. O XML leva o nome do usuário, então é gerado num arquivo temporário e nunca vai para o repositório.
9. **Modo Desempenho, primeira versão:** "Liberar a GPU" descarrega o modelo do Ollama (`keep_alive = 0`). Ele volta no próximo pedido.

## Alternativas consideradas

| Alternativa | Por que não |
|---|---|
| Pacote `openwakeword` | Preso na 0.4 no Python 3.12, puxa scipy e scikit-learn; o pipeline cabe em ~100 linhas de ONNX |
| Só openWakeWord com "Hey Jarvis" até treinar | A assistente se chama Shiro; o motor Whisper resolve o nome hoje |
| Porcupine | Proprietário e com cota (ADR-0004) |
| Whisper transcrevendo tudo o tempo todo | Gasto alto de CPU; o VAD e o limite de 8 s filtram a maior parte das falas |
| Confirmação física por voz na bandeja | Voz pode vir de vídeo ou de outra pessoa (ADR-0015) |
| Atalho na pasta Inicializar | Sem reinício em caso de falha nem atraso no logon |

## Consequências

- "Ei, Shiro" funciona sem treino, ao custo de CPU quando há conversa por perto. Com um modelo treinado, basta `engine = "openwakeword"` e `model = "caminho/ei_shiro.onnx"`.
- Os modelos embutidos do openWakeWord (CC BY-NC-SA 4.0) servem só para uso não comercial. O SHIRO é pessoal.
- A bandeja não tem console: diagnóstico é pelo log ("Abrir registros") ou rodando `shiro tray` num terminal.
- `shiro voice bench --wake` mede a palavra de ativação com frases sintetizadas, sem tocar nada. No PC de referência, com o Whisper `base` conferindo:
  - voz Maria: 6 de 6;
  - voz Kokoro: 6 de 6, depois de aceitar como o Whisper escreve o chamado ("Aishiro", "Aiciru", "E Shiro,");
  - nenhum alarme falso nas 3 frases que não chamam (inclusive "Eu falei com a Shiro ontem").
  - Tempo: ~0,8 s para ignorar uma fala e ~3 s para entender "Ei Shiro, abre o Spotify" (duas transcrições).
