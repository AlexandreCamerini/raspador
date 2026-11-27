# raspador

Raspagem web que respeita o site, construída sobre o [Scrapling](https://github.com/D4Vinci/Scrapling) 0.5.1.

- O robots.txt é sempre respeitado. Na CLI, no MCP e nos spiders não há como desligá-lo (`RSP-P004`). A regra usada
  é a do grupo `raspador` ou, se ele não existir, a do grupo `*`.
- Toda requisição se identifica com o User-Agent `raspador/<versão>`, e você pode acrescentar um contato
  (`--contact`).
- Não há evasão anti-bot: nada de imitar navegador, impressão digital TLS, solver de Cloudflare, stealth ou
  rotação de proxy para fugir de bloqueio.

As opções que o Scrapling oferece para disfarce não existem no raspador. Se você tentar usá-las, recebe um erro
`RSP-P...` que diz o motivo e o que fazer em vez disso. O raspador usa uma allowlist (o que não está na lista é
recusado) porque o upstream repassa ao curl qualquer opção que não conhece.

> Em sites com anti-bot (Cloudflare, desafios JavaScript, bloqueio por impressão digital), o raspador falha onde o
> Scrapling passaria. É intencional. Na CLI e no MCP, a falha vem com o código (`RSP-H403`, por exemplo) e o aviso
> de que o raspador não contorna bloqueios. Na API Python, o 403 volta como resposta normal (`page.status`). Se
> você precisa desses dados, peça acesso ou use a API oficial do site.

> Modelo de ameaça: o raspador evita acidente e configuração errada, não sabotagem. Quem importa `scrapling`
> direto passa por cima desta camada.

## Instalação

Requer Python 3.12 ou mais novo. O pacote ainda não está no PyPI: instale a partir do checkout.

```bash
uv tool install ".[mcp]"      # CLI + servidor MCP (inclui o navegador)
raspador install              # baixa o Chromium; só é necessário para fetch/navegador
```

| Extra | O que traz |
|---|---|
| (nenhum) | HTTP, parser, spiders, CLI e navegador. O Playwright já vem com o `scrapling[fetchers]`, que também instala o patchright; o raspador não usa o patchright |
| `browser` | fixa o Playwright na série 1.64, a mesma revisão de Chromium do upstream |
| `mcp` | SDK do MCP para o `raspador mcp`, com o mesmo pin do Playwright |

Para usar como biblioteca num projeto: `uv add /caminho/para/raspador` (ou `pip install -e /caminho/para/raspador`).

## Uso rápido

### CLI

```bash
raspador get https://exemplo.com.br/noticia noticia.md          # markdown
raspador get https://exemplo.com.br/lista - -s "article h2"      # só o seletor, no stdout
raspador fetch https://exemplo.com.br/app pagina.html           # Chromium, com JavaScript
raspador get https://exemplo.com.br/ x.md --contact mailto:voce@exemplo.com
```

O formato de saída vem da extensão: `.md` gera markdown, `.html` gera HTML e qualquer outra extensão gera texto.
`-` escreve texto no stdout. `--report json` imprime um objeto de resultado, para scripts.

Para usar proxy com credencial, passe a URL pela variável `RASPADOR_PROXY`, e não por `--proxy`, para que a senha
não fique no histórico do shell nem no `ps`.

| Saída | Significado |
|---|---|
| 0 | ok |
| 1 | bug do raspador |
| 2 | uso errado (URL, seletor, proxy inválido) |
| 3 | política: opção recusada (`RSP-P...`) |
| 4 | seletor não encontrou nada |
| 5 | rede: falha de conexão, robots.txt ilegível (`RSP-R002`), Chromium não abriu, redirect interno, resposta grande demais, HTTP 4xx/5xx que não é bloqueio |
| 6 | bloqueado: robots.txt nega (`RSP-R001`), 401/403/407/429 |
| 7 | não foi possível gravar o arquivo de saída |

### Python

```python
import raspador

page = raspador.get("https://exemplo.com.br/noticia", contact="mailto:voce@exemplo.com")
titulo = page.css("h1::text").get()
print(page.markdown(main_content_only=True))

with raspador.http_session(contact="mailto:voce@exemplo.com") as s:   # cookies e conexões entre chamadas
    s.get("https://exemplo.com.br/a")
    s.get("https://exemplo.com.br/b")
```

`async_http_session` é a versão assíncrona. O parser é o do Scrapling: `css`, `xpath`, `find_similar`,
`re`, `follow` e seletor adaptativo (`raspador.Selector`).

### Navegador

```python
from raspador import browser

with browser.BrowserSession(contact="mailto:voce@exemplo.com") as b:
    page = b.fetch("https://exemplo.com.br/app", wait_selector="#conteudo")
```

O Chromium é o do Playwright, sem patch de stealth. A URL pedida é checada contra endereço interno, com resolução de
DNS. Dentro da página, requisições para `localhost`, `*.localhost`, IP interno literal ou hostname que resolve
para IP interno são abortadas (uma consulta de DNS por host na sessão). A mesma guarda vale para popups e
WebSockets, e service workers ficam bloqueados. Se a navegação terminar em outro host, a URL final passa pela mesma
checagem. Para uma intranet sua, `BrowserSession(allow_private=True)` (no MCP, `--allow-private`) desliga essa
guarda. O robots.txt é checado antes de abrir a aba e de novo na URL final, se ela
mudou. `BrowserSession(check_robots=False)` pula a checagem prévia: é o
que o spider usa, porque o engine já consultou o robots.txt antes.

### Spider

```python
from raspador import Spider


class Noticias(Spider):
    name = "noticias"
    start_urls = ["https://exemplo.com.br/"]
    contact = "mailto:voce@exemplo.com"
    allowed_domains = {"exemplo.com.br"}

    async def parse(self, response):
        for item in response.css("article"):
            yield {"titulo": item.css("h2::text").get()}
        for href in response.css("a.proxima::attr(href)").getall():
            yield response.follow(href)


resultado = Noticias(crawldir="./crawl-noticias").start()   # crawldir: retoma de onde parou
resultado.items.to_json("noticias.json")
```

Padrões: `download_delay = 1.0` (o mínimo é 0,5 s, abaixo disso o raspador recusa), 1 requisição simultânea por
domínio e autothrottle ligado. Redirects são seguidos salto a salto, com domínio e robots.txt checados em cada um.
Depois de `max_consecutive_blocks` respostas de bloqueio seguidas (401, 403, 407, 429, 444, 500, 502, 503 e 504,
retries incluídos), o domínio para.

Durante a execução, recusas da política, robots.txt negado ou ilegível e domínios parados vão para `audit.jsonl`,
no `crawldir` ou em `audit_path`. Sem nenhum dos dois, nada é gravado. Recusas na definição da classe (P004, P005)
são lançadas antes do spider existir e não entram no arquivo. O arquivo registra a URL sem query string, fragmento
nem credencial.

### Proxy

Um proxy fixo por sessão serve para geolocalização: `raspador.get(url, proxy="http://host:porta")` ou
`RASPADOR_PROXY`. Para vários proxies, use o `ProxyPool` com afinidade estática: cada domínio registrável (eTLD+1)
sai sempre pela mesma entrada.

```python
from raspador import ProxyEntry, ProxyPool, Spider

pool = ProxyPool(
    [ProxyEntry("http://u:senha@br.proxy:8080", label="br1", group="brasil"),
     ProxyEntry("http://u:senha@us.proxy:8080", label="us1", group="eua")],
    affinity={"loja.com.br": "brasil"},   # domínio -> grupo ou label
    default_group="eua",
)

class Precos(Spider):
    name = "precos"
    proxy_pool = pool
    ...
```

Por política, o pool não tem failover: se um proxy cai, o request falha, sem trocar de proxy e sem sair direto.
O pool não aceita credencial do site nem `verify=False`, porque atende todos os domínios. Nas sessões do pool só
passam `accept*` e `user-agent`. Em cada request passam também `referer`, `origin`, `content-type`, `cache-control`,
`pragma`, `if-none-match`, `if-modified-since` e `range`. Qualquer outro header (`Authorization`, `Cookie`,
`X-Api-Key`...), `cookies=`, `cert=` ou usuário e senha na URL dão `RSP-P010`, antes de qualquer envio, inclusive
do robots.txt. A senha do proxy é mascarada em erros,
nos logs do `scrapling` e do `raspador`, na auditoria, nas estatísticas e no checkpoint. O motivo de cada uma dessas decisões está em
[replica/plano-seguranca-proxypool.md](replica/plano-seguranca-proxypool.md).

### MCP (Claude Code, Claude Desktop)

```bash
claude mcp add raspador -- raspador mcp --contact mailto:voce@exemplo.com
```

O servidor oferece estas ferramentas, todas sem evasão: `make_request`, `open_request_session`,
`session_make_request`, `browser_open`, `browser_fetch`, `browser_network_requests`, `browser_network_request`,
`list_sessions` e `close_session`. As páginas devolvidas por `make_request`, `session_make_request` e
`browser_fetch` são sanitizadas: os elementos ocultos, via comum de prompt injection, são removidos. Já o
`browser_network_request` devolve o corpo da resposta cru, por exemplo o JSON de uma API, e deve ser tratado como
conteúdo não confiável. A primeira URL de cada chamada é recusada se apontar para `localhost` ou rede privada, a
menos que o servidor seja iniciado com `--allow-private`. Dentro do navegador vale a mesma guarda descrita acima.

## Códigos de erro

| Código | Significado |
|---|---|
| RSP-P001 | opção fora da allowlist |
| RSP-P002 | opção de evasão (impersonate, stealth, solver, impressão digital) |
| RSP-P003 | header de disfarce, nome de header fora do padrão HTTP, ou credencial em header que vazaria (`Proxy-Authorization`) |
| RSP-P004 | tentativa de desligar o robots.txt |
| RSP-P005 | `download_delay` abaixo de 0,5 s ou `concurrent_requests_per_domain` fora de 1 a 4, sem `policy_override` |
| RSP-P006 | rotação de proxy, proxy por request, pool com navegador, ou dois proxies para o mesmo domínio na mesma execução |
| RSP-P007 | sessão criada com os padrões de disfarce do upstream (use `http.spider_session()`) |
| RSP-P009 | CDP remoto público (navegador de terceiros) |
| RSP-P010 | regra do ProxyPool (esquema, TLS, credencial do site na sessão do pool) |
| RSP-R001 | o robots.txt nega a URL |
| RSP-R002 | o robots.txt não pôde ser lido (rede, proxy ou 5xx); o site fica fechado por 5 min |
| RSP-U001 / U002 / U003 | URL, seletor CSS ou proxy inválido |
| RSP-N001 / N002 / N003 | falha de rede, redirect para endereço interno, resposta maior que o limite (20 MiB) |
| RSP-B001 / B002 | o Chromium não abriu, ou a página não carregou |
| RSP-F001 … F004 | crawldir inseguro ou em uso, falha ao gravar, arquivo de estado do navegador ausente |
| RSP-M001 … M005 | MCP: sessão inexistente, histórico desligado, requisição fora do histórico, limite de navegadores, filtro de rede inválido |
| RSP-H\<status\> | o servidor respondeu HTTP 4xx/5xx |

## Limites conhecidos

- O Scrapling está fixado em `==0.5.1`. O raspador depende de detalhes internos dele (sessões, engine do spider),
  e por isso atualizar a versão exige rodar os testes de contrato (`tests/test_contract_upstream.py`).
- O ProxyPool v1 é só HTTP: não funciona com sessão de navegador no mesmo spider e não tem failover.
- No navegador, a guarda contra rede interna resolve o DNS uma vez e o Chromium resolve de novo ao conectar:
  DNS rebinding entre as duas consultas não é coberto. O Playwright só entrega à guarda a primeira URL de um
  redirect, então um subrecurso (`<img src>` que responde 302 para 169.254.169.254) chega ao destino interno; na
  navegação principal, a URL final é recusada (`RSP-N002`), mas a requisição já saiu. Fechar isso exige um proxy
  de egress local que resolva e fixe o IP, o que ainda não existe.
- Com ProxyPool, um token na query string (`params={"access_token": ...}`) não é detectável e sai pelo proxy.
- Um robots.txt com 4xx que não seja 401/403, inclusive 429, é tratado como ausente (tudo permitido), como no Scrapy.
- A integração com Scrapy (`raspador.integrations.scrapy`) não é testada no CI, porque o Scrapy não está nas
  dependências.
- A paridade de funcionalidades com o Scrapling e o que ficou de fora de propósito estão em
  [replica/parity.md](replica/parity.md).

## Desenvolvimento

```bash
uv sync
uv run ruff check src tests && uv run ruff format --check src tests
uv run pyright
uv run playwright install chromium
uv run pytest -q -rs
```

Os testes que precisam de Chromium ou de porta local pulam sozinhos quando o ambiente não permite, e a saída diz o
motivo. Os bugs encontrados e corrigidos estão em [replica/bugs.md](replica/bugs.md).

## Licença

BSD 3-Clause ([LICENSE](LICENSE)). O raspador redistribui o Scrapling como dependência; a licença dele está em
[NOTICE](NOTICE).
