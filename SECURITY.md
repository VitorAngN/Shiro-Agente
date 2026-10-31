# Política de segurança

## Reportando uma vulnerabilidade

Encontrou uma falha de segurança no SHIRO? **Não abra uma issue pública.**

Use o recurso de [relato privado de vulnerabilidades do GitHub](https://github.com/VitorAngN/Shiro-Agente/security/advisories/new) deste repositório. Descreva:

- o que é possível fazer explorando a falha;
- os passos para reproduzir;
- a versão ou o commit afetado.

## Escopo

O SHIRO é um projeto pessoal e roda localmente no PC de quem o usa. São especialmente relevantes:

- formas de fazer o SHIRO executar ações sem passar pelo motor de políticas;
- prompt injection que leve a ações com efeito (R2 ou acima) sem confirmação;
- vazamento de dados marcados como `local_only` para provedores na nuvem;
- acesso à API local a partir de outro processo ou máquina sem o token.

O modelo de ameaças completo está em [docs/05-seguranca.md](docs/05-seguranca.md).
