# ADR-0004 · Pipeline de voz 100% local

- **Status:** Aceito · local de execução do STT definido pelo [ADR-0010](0010-hardware-gpu-4gb.md) (CPU) · voz substituída pelo [ADR-0012](0012-identidade-da-shiro.md) (feminina)
- **Data:** 2026-10-30

## Contexto

Voz é a principal forma de falar com o SHIRO. Requisitos: português do Brasil, baixa latência, funcionamento offline e nenhum áudio saindo do PC (RNF-05). A GPU é compartilhada com o LLM local.

## Decisão

| Etapa | Escolha | Observações |
|---|---|---|
| Ativação (Fase 1) | **Atalho de teclado** (push-to-talk) | Zero falso disparo; permite validar o resto do pipeline primeiro |
| Ativação (Fase 2) | **openWakeWord** com modelo próprio "Ei, Shiro" | Ver seção sobre a palavra de ativação abaixo |
| Detecção de fala | **Silero VAD** | Leve, roda na CPU, decide quando a frase terminou |
| Fala → texto | **faster-whisper** | Começa com o modelo `small` em int8; o spike da Fase 1 compara `small`, `medium` e `large-v3-turbo` em pt-BR e decide GPU ou CPU |
| Texto → fala | **Piper**, voz `pt_BR-faber-medium` | Voz masculina em pt-BR, modelo ONNX pequeno, roda na CPU; outras vozes pt_BR podem ser testadas |

### Palavra de ativação

- "Shiro" sozinho tem só duas sílabas. Palavras curtas tendem a gerar mais falsos disparos, então a hipótese inicial é usar a frase **"Ei, Shiro"**. Ela será validada contra as metas do RNF-04.
- O pipeline oficial de treino do openWakeWord está com dependências antigas e quebra em ambientes atuais. Opções para treinar: o serviço hospedado em openwakeword.com, notebooks da comunidade atualizados para 2026, ou o **ViolaWake** (Apache 2.0, testado em Windows, treino com ~200 amostras gravadas).
- Modelos treinados com o conjunto ACAV100M herdam licença **não comercial**. Para uso pessoal não há problema.
- Enquanto o SHIRO fala, a detecção ignora o próprio áudio, para não se ativar sozinho. Cancelamento de eco fica para o futuro; com fone de ouvido o problema não existe.

### Licença do Piper

O pacote Python `piper-tts` é **GPL**, e o repositório do SHIRO é **MIT**. Para manter a fronteira de licença clara, o Piper **não é importado**: o adaptador `PiperProcessTTS` chama um executável do Piper como **processo separado** e lê o áudio pela saída padrão. O mesmo vale para o `espeak-ng` (GPL), usado pelo Piper na fonetização. A licença do executável escolhido e o `MODEL_CARD` da voz são conferidos na Fase 1.

A porta `TextToSpeech` isola essa decisão: trocar de motor de voz não muda o núcleo.

## Alternativas consideradas

| Alternativa | Por que não |
|---|---|
| STT/TTS na nuvem | Viola o RNF-05 e adiciona latência de rede |
| APIs de voz em tempo real (fala-para-fala) | Excelentes em naturalidade, mas mandam todo o áudio para a nuvem e prendem o projeto a um fornecedor |
| Porcupine (Picovoice) para wake word | Proprietário e com cota; contra o princípio local-first e aberto |
| Wake word desde o início | Falsos disparos atrapalhariam a validação do pipeline inteiro |

## Consequências

- ✅ Áudio nunca sai do PC; voz funciona offline.
- ✅ Cada etapa é uma porta: trocar Piper ou Whisper é configuração.
- ⚠️ STT e LLM disputam a VRAM. Mitigação: spike de medição e STT em CPU como alternativa.
- ⚠️ Treinar a palavra de ativação dá trabalho. Mitigação: push-to-talk até a Fase 2.
- ⚠️ A voz do Piper é menos natural que vozes comerciais na nuvem. Aceitável pelo ganho em privacidade e latência.
