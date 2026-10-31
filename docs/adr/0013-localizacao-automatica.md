# ADR-0013 · Localização automática para o clima

- **Status:** Aceito
- **Data:** 2026-10-31

## Contexto

A ferramenta de clima exigia configurar `general.city` no `shiro.toml`. Para o dono do projeto, editar arquivo de configuração só para isso é atrito desnecessário: ele espera que a SHIRO descubra onde está.

Opções avaliadas no PC de referência:

- o **serviço de localização do Windows** está ativo e autorizado, e dá coordenadas precisas (Wi-Fi), mas exige APIs do Windows Runtime e devolve uma precisão maior do que o clima precisa;
- a **geolocalização por IP** pelo GeoJS funciona por HTTPS, sem chave, e devolve cidade, estado, coordenadas e fuso.

## Decisão

1. A cidade é decidida nesta ordem: a dita no pedido ("como tá o tempo em Curitiba?"), a de `general.city` e, por fim, a **detectada pelo IP**.
2. A detecção usa o GeoJS (`https://get.geojs.io/v1/ip/geo.json`) e guarda o resultado em `<dados>/location.json`, com validade de **24 horas**.
3. `general.location = "off"` desliga a detecção. Com `general.city` preenchida, ela nunca roda.
4. A ferramenta de clima passa a ser `local_only`: a localização não entra em contexto enviado para a nuvem (ameaça A-03).
5. "Como tá o tempo?", "vai chover hoje?" e frases parecidas entram no **Tier 0**, sem passar pelo modelo.

## Alternativas consideradas

| Alternativa | Por que não |
|---|---|
| Exigir `general.city` | Atrito; o dono do projeto pediu detecção automática |
| Serviço de localização do Windows | Mais preciso do que o necessário (dado mais sensível) e exige dependências de Windows Runtime. Fica como evolução, se a precisão por IP incomodar |
| ip-api.com | O plano gratuito é só HTTP, sem criptografia |
| Perguntar a cidade na primeira vez e salvar | Bom complemento futuro; hoje a detecção resolve sem interação |

## Consequências

- ✅ O clima funciona sem configuração.
- ✅ Uma consulta ao GeoJS por dia, no máximo.
- ⚠️ A precisão é de cidade e às vezes aponta a cidade do provedor de internet. Mitigação: `general.city` sobrescreve.
- ⚠️ O GeoJS recebe o IP público, como qualquer site acessado. O resultado fica só no PC, na pasta de dados, fora do repositório.
