# Segurança do raspador

O raspador é construído pela equipe [semente.dev](https://semente.dev), by Alexandre Camerini. Este documento diz o
que a ferramenta protege, o que ela não protege e como relatar um problema.

Nenhum software é livre de risco, e este documento não afirma isso. Ele lista o que foi verificado, o que foi
corrigido e o que continua em aberto, com base na auditoria de 2026-11-28 sobre a versão 0.1.1 e nas correções publicadas na 0.1.2.

## Como relatar uma vulnerabilidade

Use o relato privado do GitHub: aba **Security** do repositório → **Report a vulnerability**
(<https://github.com/AlexandreCamerini/raspador/security/advisories/new>). Não abra issue pública com detalhes de
uma falha ainda não corrigida.

Inclua a versão (`raspador --version`), o comando ou trecho de código e o que aconteceu. Correções saem numa versão
nova no PyPI e são registradas aqui e no [DECISIONS.md](DECISIONS.md).

| Versão | Recebe correção de segurança |
|---|---|
| 0.1.x (mais recente) | sim |
| anteriores | não |

## Modelo de ameaça

O raspador evita acidente e configuração errada, não sabotagem. Quem importa `scrapling` direto passa por cima de
toda a camada de política. Os riscos considerados são:

- **Para quem usa:** vazamento de credenciais, acesso não intencional à rede interna, conteúdo malicioso de um site
  manipulando o Claude (prompt injection via MCP), arquivos gravados com permissão larga demais.
- **Para quem publica:** pacote adulterado na cadeia de build e publicação, e segredos no repositório.
- **Para o site raspado:** carga excessiva e coleta contra a vontade do dono.

## O que está protegido (verificado)

Cada item foi conferido no código e, quando possível, por teste automatizado.

- **Sem segredos no repositório.** O histórico inteiro foi varrido atrás de tokens do PyPI e do GitHub, chaves da
  AWS, chaves privadas e senhas, e nada real foi encontrado. A publicação usa Trusted Publishing (OIDC): não existe
  token de PyPI guardado no GitHub.
- **CI e publicação.**
  - Todos os workflows rodam com `permissions: contents: read` e não usam `pull_request_target`.
  - Nenhuma expressão do evento é interpolada em `run:`.
  - `id-token: write` só existe nos jobs de publicação, que ficam atrás dos environments `testpypi` e `pypi`.
  - Um PR de fork não publica nem lê segredos.
  - As actions estão fixadas por SHA, atualizadas toda semana pelo Dependabot (`.github/dependabot.yml`), e o
    `twine` e o backend de build (`hatchling`) estão fixados por versão exata.
- **robots.txt obrigatório.** Não há opção para desligá-lo (`RSP-P004`). Um robots.txt ilegível fecha o site por
  5 minutos em vez de liberar tudo.
- **Sem evasão.** Opções de disfarce (impersonate, stealth, solver, impressão digital, headers de navegador falsos)
  dão `RSP-P002` ou `RSP-P003`. O User-Agent é sempre `raspador/<versão>`.
- **Credenciais de proxy mascaradas** em erros, logs do `scrapling` e do `raspador`, auditoria, estatísticas e
  metadados do checkpoint. Na CLI, use `RASPADOR_PROXY` em vez de `--proxy` para a senha não aparecer no `ps`.
- **`Authorization` e cookies retirados** quando um redirect leva para outro host.
- **Saída controlada.** Variáveis `HTTPS_PROXY` e `NO_PROXY` do ambiente não desviam o tráfego. Só `http` e `https`
  são aceitos, inclusive em redirects: `file://` e `ftp://` dão `RSP-U001`.
- **Rede interna.**
  - No MCP e no navegador, `localhost`, rede privada e metadados de nuvem (169.254.169.254) são recusados.
  - Formas disfarçadas de IP (decimal, hexadecimal, IPv4 mapeado em IPv6, NAT64, CGNAT) também são recusadas.
  - Em redirects, vale o mesmo para qualquer uso.
- **Navegador.** Service workers são bloqueados. Requisições internas da página, popups e WebSockets passam pela
  mesma guarda. Scripts injetados, flags extras do Chromium e User-Agent customizado são recusados.
- **Sem execução de código arbitrário** no raspador: não há `eval`, `exec`, `pickle` próprio nem `shell=True`. O
  único `subprocess` é o `raspador install`, com lista de argumentos.
- **Diretórios e arquivos.** O `crawldir` novo nasce com permissão 0700 e tem lock exclusivo. Um `crawldir` de outro
  usuário ou com escrita para terceiros é recusado (`RSP-F001`).

## Corrigido na 0.1.2

| Item | Antes | Agora |
|---|---|---|
| Escrita via MCP | O modelo podia pedir POST, PUT e DELETE com corpo, induzido por uma página lida antes | Só GET por padrão; escrita exige `raspador mcp --allow-write` (`RSP-M006`) |
| Conteúdo oculto no MCP | Passavam `hidden`, `input type=hidden`, `<meta>`, tags Unicode (ASCII smuggling) e controles bidi | Removidos em Markdown, HTML e texto |
| Limites no MCP | O modelo podia pedir `max_chars=0` (sem corte), `timeout` sem teto e abrir sessões HTTP sem limite | `max_chars` de 1 a 500 mil, `timeout` de 1 a 120 s, até 10 sessões HTTP (`RSP-M004`) |
| `crawldir` legível por outros | Um diretório existente com 0755 era aceito, e o checkpoint guarda headers e cookies do site | Recusado com `RSP-F001` e a instrução `chmod 700` |
| `audit.jsonl` | Criado com 0644 | Criado com 0600 |
| `--report json` | A URL saía com usuário e senha, se houvesse | Mascarada |
| Cadeia de publicação | Actions por tag mutável, `twine` e `hatchling` sem versão exata | Fixados por SHA e por versão |

## Riscos que continuam (na 0.1.2)

### Médios

- **DNS rebinding.** A guarda de rede interna consulta o DNS uma vez e o curl (ou o Chromium) consulta de novo ao
  conectar. Um domínio que muda de IP público para interno entre as duas consultas passa. Afeta principalmente o MCP,
  onde a URL pode ser sugerida por uma página. A correção exige fixar o IP resolvido ou um proxy de saída local.
- **Prompt injection não é eliminada.** A limpeza remove o conteúdo oculto conhecido, mas texto escondido por CSS
  externo, fora da tela ou na cor do fundo passa, e instrução em texto visível também. A ferramenta
  `browser_network_request` devolve conteúdo cru de propósito. Revise o que o Claude propõe depois de ler um site
  desconhecido e mantenha a confirmação de ferramentas ligada no cliente MCP.
- **Limites de tamanho conferidos depois do download.** O teto de 20 MiB é checado com a resposta já em memória, e
  o robots.txt não tem teto próprio. Um servidor hostil (ou uma bomba de compressão) pode fazer o processo usar
  muita memória antes da recusa.
- **Checkpoint em pickle.** O `crawldir` guarda as requisições pendentes, com headers e cookies, no formato pickle
  do Scrapling, que executa código ao ser carregado. Nunca reutilize um `crawldir` recebido de outra pessoa e não o
  commite.
- **Dependências do Scrapling.** O `scrapling[fetchers]` instala o patchright e os comandos `scrapling` e
  `scrapling-mcp`, que têm stealth. O raspador importa o patchright só por tipos e nunca navega com ele. Não
  configure o `scrapling-mcp` no lugar do `raspador mcp`. Quem instala por `pip` recebe as dependências
  transitivas sem o `uv.lock`; instale num ambiente isolado (`uv tool install` ou `pipx`).

### Baixos

- **`-o` sobrescreve** o arquivo de saída sem perguntar e segue links simbólicos. O caminho é sempre escolhido por
  você.
- **Sem ritmo fora do Spider.** Intervalo mínimo, uma requisição por vez e parada após bloqueios só existem no
  Spider. Um laço em Python ou muitos pedidos via MCP batem no site na velocidade pedida.
- **`save_state` do navegador** grava cookies e localStorage e só depois ajusta a permissão para 0600. Há uma janela
  curta com a permissão padrão.
- **Mensagens de erro mantêm a query string** da URL. Usuário e senha na URL são mascarados; um token passado como
  `?access_token=` não é.
- **Download do Chromium** (`raspador install`) vem dos servidores do Playwright e o host pode ser trocado por
  variável de ambiente (`PLAYWRIGHT_DOWNLOAD_HOST`). Não confirmamos se o Playwright verifica hash do download.
- **Duas buscas em paralelo na mesma sessão de navegador** compartilham o host-alvo isento da checagem de DNS.
- **robots.txt com 4xx** que não seja 401/403, inclusive 429, é tratado como ausente (tudo permitido), como no
  Scrapy.
- **`policy_override`** no Spider remove os limites de intervalo e concorrência, e só fica registrado se houver
  `audit_path` ou `crawldir`.

## O que continua sendo responsabilidade de quem usa

A ferramenta cuida do comportamento técnico. A decisão sobre o uso é sua.

- **Termos de uso** do site podem proibir coleta automatizada mesmo quando o robots.txt permite. O robots.txt não é
  autorização legal.
- **Dados pessoais (LGPD, GDPR).** O raspador não filtra dado pessoal. Coletar e guardar nomes, e-mails ou perfis,
  mesmo públicos, exige finalidade e base legal.
- **Direitos autorais.** Ler uma página não dá direito de republicar o conteúdo.
- **Contato.** O User-Agent só leva o seu contato se você passar `--contact`. Passe: o dono do site consegue falar
  com você antes de bloquear.
- **Rede interna.** `--allow-private` desliga a guarda de rede interna do MCP e do navegador. Use só com intranets
  suas.

## O que não foi verificado

- Os testes que precisam de Chromium ou de porta local não rodaram no ambiente da auditoria; as guardas do navegador
  foram conferidas só no código. No CI do GitHub eles rodam.
- Vulnerabilidades conhecidas nas dependências (pip-audit / OSV): não verificado manualmente. Os alertas do
  Dependabot estão ligados desde 2026-11-28 e passam a avisar sobre dependências com falha conhecida.
- Configurações do GitHub: proteção dos environments `pypi` e `testpypi`, proteção de branch e de tag. O relato
  privado de vulnerabilidades está ligado desde 2026-11-28.
- Se o pacote publicado no PyPI é idêntico ao build da tag `v0.1.1`.
