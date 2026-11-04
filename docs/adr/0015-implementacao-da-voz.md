# ADR-0015 · Implementação da voz (marco 1b)

- **Status:** Aceito · escolha final de modelos depende do `shiro voice bench` no PC de referência
- **Data:** 2026-11-01
- **Complementa:** [ADR-0004](0004-pipeline-de-voz-local.md), [ADR-0010](0010-hardware-gpu-4gb.md) e [ADR-0012](0012-identidade-da-shiro.md)

## Contexto

O ADR-0004 definiu um pipeline de voz local: atalho, VAD, faster-whisper e texto para fala em processo separado. O ADR-0012 trocou a voz masculina do Piper por uma voz feminina, com Kokoro `pf_dora` como candidata. Faltava decidir como cada peça é implementada no Windows, sem gastar a GPU de 4 GB, que fica com o modelo de linguagem.

O que foi verificado antes de decidir:

- o faster-whisper 1.2 já traz o **Silero VAD v6 em ONNX** (`silero_vad_v6.onnx`). Ele roda quadro a quadro (512 amostras a 16 kHz) com estado recorrente `h`/`c`, sem PyTorch;
- o **kokoro-onnx** (MIT) roda o Kokoro-82M (pesos Apache-2.0) só com onnxruntime. As vozes pt-BR são `pf_dora`, `pm_alex` e `pm_santa`. A fonetização usa **espeak-ng e phonemizer, ambos GPL-3**;
- a versão int8 do modelo tem 88 MB. Num processador modesto, ela sintetiza em tempo real (fator ~0,9);
- o PC de referência já tem a voz **Microsoft Maria Desktop (pt-BR)** no SAPI 5, sem download.

## Decisão

1. **Ativação:** um atalho global com `RegisterHotKey` (padrão `ctrl+alt+space`), registrado numa thread com laço de mensagens próprio, e um atalho de parar (`ctrl+alt+shift+s`). O Enter no terminal também fala, e o texto digitado vai direto ao agente.
2. **Modo alternado (toggle):** um toque começa a ouvir. A frase termina quando o VAD detecta silêncio, ou com um segundo toque.
3. **VAD:** o Silero v6 do faster-whisper, quadro a quadro. A fala começa depois de 3 quadros seguidos acima do limiar (~100 ms) e guarda 300 ms antes do início. Ela termina após 700 ms abaixo de *limiar − 0,15*; essa histerese impede que pausas entre palavras cortem a frase. Há também um limite de 15 s e um prazo de 6 s para começar.
4. **STT:** faster-whisper na CPU, int8, `beam_size` 1, sem o VAD interno (o áudio já vem recortado). Um prompt inicial com "Shiro" e os nomes dos apps ajuda no vocabulário. Frases que o Whisper inventa no silêncio ("Legendas pela comunidade Amara.org", "Obrigado.") são descartadas. O modelo padrão é `small`; o `base` fica como alternativa se a latência incomodar. O `shiro voice bench` decide.
5. **TTS:**
   - **Kokoro `pf_dora`** num **processo separado** (`shiro.infrastructure.voice.kokoro_worker`). A conversa é por stdin/stdout: uma linha JSON de pedido, depois cabeçalho JSON e PCM de 16 bits. O processo principal nunca importa espeak-ng nem phonemizer.
   - O `kokoro-onnx` fica num **grupo de dependências do uv** instalado por padrão (`default-groups`), fora dos metadados do pacote `shiro`.
   - O modelo é baixado das releases do kokoro-onnx por `shiro voice setup`, com **SHA-256 fixado**.
   - **Reserva:** a voz do Windows pelo SAPI 5, renderizada em memória e tocada pelo mesmo player. Sem Kokoro, a SHIRO fala com a Maria e avisa.
6. **Fala por frases:** a resposta é dividida em frases. Enquanto uma toca, a próxima é sintetizada. Antes da síntese, o texto é ajustado para soar falado ("23h59" → "23 e 59", "%" → "por cento").
7. **Parar nunca cancela uma ação no meio.** O atalho de parar silencia a fala e encerra a escuta. Se o agente já está executando, a ação termina e a resposta só aparece na tela.
8. **Confirmação por voz:** "sim" ou "não", com até duas tentativas, e sem resposta conta como **não**. A confirmação **física** (R3) continua só no teclado: uma voz pode vir de um vídeo ou de outra pessoa.
9. **Lembretes e avisos de prazo** são falados quando a SHIRO está livre, ou logo depois da interação em andamento.
10. **Teste sem tocar áudio:** `shiro voice bench` gera as frases com as vozes disponíveis, transcreve com os modelos pedidos e mede o seguinte, sem usar o alto-falante:
    - **comando preservado:** o roteador gera a mesma chamada a partir do texto original e da transcrição;
    - **erro de palavras;**
    - **latências.**

## Alternativas consideradas

| Alternativa | Por que não |
|---|---|
| Pacote `silero-vad` | Puxa PyTorch (centenas de MB) para algo que o faster-whisper já traz em ONNX |
| VAD por energia | Frágil com ventilador, teclado e música |
| Segurar a tecla para falar | `RegisterHotKey` não avisa quando a tecla é solta. Um gancho de teclado de baixo nível é mais invasivo e parece keylogger para antivírus |
| Pacote `kokoro` (PyTorch) | ~2 GB de dependências; o ONNX entrega a mesma voz |
| Importar o kokoro-onnx no processo principal | Mistura código GPL-3 ao processo do SHIRO (MIT) |
| Piper | Voz masculina no pt-BR disponível; trocada pela identidade feminina (ADR-0012) |
| Só SAPI | Funciona sem download, mas a voz é mais robótica; fica como reserva |
| Whisper na GPU | A GPU de 4 GB é do modelo de linguagem (ADR-0010) |

## Consequências

- A voz funciona sem internet depois do `shiro voice setup`, e nenhum áudio sai do PC.
- A primeira execução baixa cerca de 500 MB (Whisper `small`, mais 120 MB do Kokoro).
- **O SHIRO baixa o Whisper por conta própria** (httpx), em `<dados>/models/whisper`, e não pelo cliente do Hugging Face. No PC de referência, o `huggingface_hub` 2.4 travou com 0 bytes no `model.bin`, com e sem Xet, enquanto um download direto pelo mesmo Python fazia 8 MB/s. Cada arquivo é conferido com o hash publicado pela API do Hugging Face: SHA-256 nos arquivos grandes (LFS), SHA-1 de blob do git nos pequenos.
- No Linux do CI não há PortAudio: o `sounddevice` só é importado quando o áudio é usado. Os testes da sessão usam dublês de microfone, detector, Whisper, voz e player. O protocolo do Kokoro é testado com um processo dublê de verdade.
- Ainda não há cancelamento de eco: a SHIRO não ouve enquanto fala, a menos que o usuário a interrompa com o atalho.
- Medição no PC de referência ([benchmark](../benchmarks/2026-11-01-voz.md)): o Whisper `small` acertou 9 de 10 comandos com as duas vozes, com transcrição mediana de 2,4 s. O `base` leva 0,8 s, mas acertou só 5 de 10 com a voz menos clara. O padrão fica `small`.
- Pendências com voz humana:
  - testar `shiro voice listen` com a voz do usuário;
  - comparar `pf_dora` com a Maria ouvindo as duas;
  - ajustar `end_silence_ms` ao jeito de falar do usuário.
