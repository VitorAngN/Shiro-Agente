# ADR-0012 · Identidade da SHIRO: persona, voz e visual

- **Status:** Aceito
- **Data:** 2026-10-31
- **Substitui em parte:** [ADR-0004](0004-pipeline-de-voz-local.md) (a voz `pt_BR-faber-medium`, que é masculina)

## Contexto

Até aqui o SHIRO era tratado como um assistente sem identidade definida. O dono do projeto definiu:

- a SHIRO é **ela**;
- fala em tom **neutro**, com uma **gíria de netrunner de vez em quando**;
- estética **cyberpunk**, com aparência própria em estilo **anime** e **cabelo branco**. O nome combina: 白 (*shiro*) significa "branco" em japonês.

Isso afeta três partes do sistema: o prompt da persona, a voz do TTS e a identidade visual (terminal, bandeja e, depois, o painel).

## Decisão

### 1. Persona

- Identidade feminina: ela fala de si no feminino ("estou pronta").
- Tom neutro, direto e calmo; respostas de no máximo duas frases, porque são faladas.
- Gíria de netrunner **rara** ("na escuta", "link estável", "rodando quente", "sem rastro"), **nunca** em confirmações, erros, recusas ou avisos de segurança. Clareza vem antes do estilo.
- A persona fica no início do pedido e não muda durante a sessão, para preservar o cache de prefixo (ADR-0011).

### 2. Voz

- A voz `pt_BR-faber-medium` do ADR-0004 é masculina e deixa de ser o padrão.
- **Candidata principal:** Kokoro-82M, voz `pf_dora` (feminina, pt-BR), licença Apache 2.0, modelo de ~330 MB.
- Para português, o Kokoro usa o **espeak-ng (GPL)** na fonetização. Vale a regra do ADR-0004: o TTS roda como **processo separado**, sem importar código GPL no processo do SHIRO.
- O spike do marco 1b decide em definitivo, comparando latência na CPU (i5-10300H) e naturalidade com vozes femininas disponíveis para o Piper. A porta `TextToSpeech` torna a troca uma questão de configuração (`voice.tts.engine` e `voice.tts.voice`).

### 3. Visual

Detalhes em [08 · Identidade](../08-identidade.md).

- **Personagem:** cabelo branco longo com franja, olhos ciano com um anel de interface vermelho no olho direito, fone com LED vermelho, jaqueta grafite de gola alta com o emblema 白.
- **Paleta:** grafite de fundo, branco, **vermelho sinal** (identidade e microfone ativo), **ciano HUD** (sistema ok) e **âmbar** (pede confirmação).
- **Regra de significado:** o vermelho aceso quer dizer microfone ativo, tanto no LED do fone dela quanto no ícone da bandeja. Cor nunca é o único sinal: cada estado também muda de forma.
- **Design original:** não é baseado em nenhum personagem existente. Arte final, se encomendada ou gerada, segue o esboço conceitual e evita traços característicos de personagens conhecidos.

## Alternativas consideradas

| Alternativa | Por que não |
|---|---|
| Personalidade marcante (sarcástica, "parceira de equipe") | O dono preferiu tom neutro. Gíria fica como tempero raro, não como estilo |
| Manter o Piper `faber` | Voz masculina, incompatível com a identidade |
| Voz feminina na nuvem | Contraria o RNF-05: áudio e texto falado não saem do PC |
| Visual genérico de "assistente" (onda sonora, microfone) | Sem identidade; o projeto ganhou uma personagem |

## Consequências

- ✅ Identidade coerente em texto, voz e interface.
- ✅ O LED vermelho vira um indicador de privacidade com significado, não só enfeite.
- ⚠️ O Kokoro traz um modelo maior que o Piper e depende do espeak-ng instalado no Windows. Mitigação: o spike do 1b mede o custo e mantém o Piper como alternativa.
- ⚠️ O modelo local pode exagerar na gíria ou esquecer o feminino. Mitigação: casos de estilo no conjunto de avaliação.
- 📌 O esboço vetorial em `docs/assets/shiro-conceito.svg` é referência, não arte final.
