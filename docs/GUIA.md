# Guia de uso do raspador

O raspador lê páginas da web e entrega o conteúdo em texto, Markdown ou HTML, sempre respeitando as regras
publicadas pelo site. Este guia é para quem quer usar a ferramenta, com ou sem experiência em programação. A
referência técnica completa está no [README](../README.md).

Construído pela equipe [semente.dev](https://semente.dev), by Alexandre Camerini.

## Sumário

1. [O que o raspador faz (e o que ele se recusa a fazer)](#1-o-que-o-raspador-faz-e-o-que-ele-se-recusa-a-fazer)
2. [Instalação](#2-instalação)
3. [Primeiros passos na linha de comando](#3-primeiros-passos-na-linha-de-comando)
4. [Usando conversando com o Claude (MCP)](#4-usando-conversando-com-o-claude-mcp)
5. [Usando em Python](#5-usando-em-python)
6. [Quando algo dá errado](#6-quando-algo-dá-errado)
7. [Uso responsável: o que continua sendo sua responsabilidade](#7-uso-responsável-o-que-continua-sendo-sua-responsabilidade)
8. [Atualizar e desinstalar](#8-atualizar-e-desinstalar)
9. [Segurança e créditos](#9-segurança-e-créditos)

## 1. O que o raspador faz (e o que ele se recusa a fazer)

| Faz | Não faz, de propósito |
|---|---|
| Lê páginas públicas por HTTP ou num navegador (para sites montados por JavaScript) | Disfarçar-se de navegador comum, falsificar impressão digital ou "stealth" |
| Consulta o `robots.txt` antes de cada site e obedece | Ignorar o `robots.txt`: não existe opção para desligar |
| Identifica-se como `raspador/<versão>`, com o seu contato se você informar | Resolver captcha, desafio do Cloudflare ou bloqueio anti-bot |
| No Spider, espera entre requisições e para quando o site começa a bloquear | Trocar de proxy para fugir de bloqueio |
| No MCP e no navegador, recusa endereços internos (`localhost`, rede privada) por padrão | Acessar a sua rede interna pelo MCP sem você pedir (`--allow-private`) |

Quando um site bloqueia, o raspador para e explica o motivo. Se você precisa daqueles dados, o caminho é pedir
acesso ao dono do site ou usar a API oficial dele.

## 2. Instalação

Você precisa do Python 3.12 ou mais novo. No PyPI o pacote se chama `raspador-compliant`. O comando instalado
continua sendo `raspador`.

Para usar só pela linha de comando e pelo Claude, o recomendado é a instalação isolada:

```bash
uv tool install "raspador-compliant[mcp]"
```

Se você não usa o `uv`, o `pipx install "raspador-compliant[mcp]"` faz o mesmo. Para usar como biblioteca dentro de
um projeto Python, use `pip install raspador-compliant` ou `uv add raspador-compliant`.

Páginas que dependem de JavaScript precisam de um navegador. Baixe-o uma vez:

```bash
raspador install
```

Para conferir se deu certo:

```bash
raspador --version
```

> Não instale junto com o pacote `raspador` do PyPI (outro projeto, parado desde 2013). Os dois usam o mesmo nome
> de módulo e um sobrescreve o outro.

Se o terminal disser que o comando `ler` não existe logo depois de atualizar, o shell ainda está chamando a versão
antiga. Rode `hash -r` (zsh e bash) ou abra um terminal novo.

## 3. Primeiros passos na linha de comando

Digite `raspador` sem nada para ver os exemplos. O comando do dia a dia é `ler`.

Ver uma página legível na tela:

```bash
raspador ler https://quotes.toscrape.com/
```

Gravar num arquivo (o formato vem da extensão: `.md`, `.html` ou texto para qualquer outra):

```bash
raspador ler https://quotes.toscrape.com/ -o citacoes.md
```

Pegar só um pedaço da página, com um seletor CSS:

```bash
raspador ler https://quotes.toscrape.com/ -s "span.text"
```

Ler uma página montada por JavaScript (precisa do `raspador install`):

```bash
raspador ler https://quotes.toscrape.com/js/ --js
```

Deixar um contato para o dono do site, o que é educado e reduz a chance de bloqueio:

```bash
raspador ler https://quotes.toscrape.com/ --contact mailto:voce@exemplo.com
```

Como encontrar o seletor CSS: no Chrome ou no Firefox, clique com o botão direito no trecho que interessa, escolha
"Inspecionar" e veja a tag e a classe destacadas (por exemplo, `<span class="text">` vira `span.text`).

Os links na saída já vêm completos (`https://...`), então continuam funcionando fora do site.

Para scripts e automação existem `raspador get` (HTTP) e `raspador fetch` (navegador). Eles aceitam headers,
cookies, proxy e relatório em JSON (`--report json`). Veja `raspador get --help`.

## 4. Usando conversando com o Claude (MCP)

Com o MCP, você pede em português e o Claude usa o raspador por baixo, com as mesmas regras.

Registre uma vez no Claude Code (troque o contato pelo seu):

```bash
claude mcp add --scope user raspador -- raspador mcp --contact mailto:voce@exemplo.com
```

Confira com `claude mcp list`: o `raspador` deve aparecer como conectado. Depois, numa conversa nova:

> Usa o raspador para pegar as citações e os autores da primeira página de quotes.toscrape.com e monta uma tabela.

Se o site proibir no `robots.txt`, o Claude recebe o código `RSP-R001` e explica, em vez de insistir.

O que protege você no MCP:

- Por padrão o servidor só lê (GET). Enviar dados para sites (POST, PUT, DELETE) exige iniciar o servidor com
  `--allow-write`. Sem isso, uma página mal-intencionada não consegue fazer o Claude enviar formulários ou apagar
  coisas em nome do seu IP.
- Páginas devolvidas ao Claude são limpas de conteúdo oculto (por estilo, `hidden`, `aria-hidden`, inputs ocultos,
  metadados e caracteres invisíveis), que é o truque mais comum para esconder instruções maliciosas (prompt
  injection). A limpeza reduz o risco, mas não o elimina: texto escondido por CSS externo ou instrução em texto
  visível passa. Revise o que o Claude propõe fazer depois de ler um site desconhecido.
- A ferramenta `browser_network_request` devolve respostas cruas (por exemplo, o JSON de uma API). Trate esse
  conteúdo como dado, nunca como instrução. O próprio servidor avisa o Claude disso.
- Endereços da sua rede interna são recusados, a menos que você inicie o servidor com `--allow-private`. Só use
  essa opção com intranets suas.
- Tempo de espera, tamanho da resposta e número de sessões têm teto, que o Claude não consegue desligar.

No Claude Desktop, adicione um servidor MCP com o comando `raspador` e os argumentos `mcp --contact mailto:...`.

## 5. Usando em Python

```python
import raspador

page = raspador.get("https://quotes.toscrape.com/", contact="mailto:voce@exemplo.com")
for citacao in page.css("div.quote"):
    print(citacao.css("span.text::text").get(), "-", citacao.css("small.author::text").get())
```

Para percorrer várias páginas com calma, use um Spider. O raspador já espera 1 segundo entre requisições, faz uma
por vez em cada domínio e para se o site começar a bloquear:

```python
from raspador import Spider


class Citacoes(Spider):
    name = "citacoes"
    start_urls = ["https://quotes.toscrape.com/"]
    allowed_domains = {"quotes.toscrape.com"}
    contact = "mailto:voce@exemplo.com"

    async def parse(self, response):
        for q in response.css("div.quote"):
            yield {"texto": q.css("span.text::text").get(), "autor": q.css("small.author::text").get()}
        for href in response.css("li.next a::attr(href)").getall():
            yield response.follow(href)


resultado = Citacoes(crawldir="./crawl-citacoes").start()
resultado.items.to_json("citacoes.json")
```

O `crawldir` guarda o progresso: se o processo parar, rodar de novo continua de onde parou. Navegador, proxy,
sessões e todos os parâmetros estão no [README](../README.md#uso-rápido). Há um exemplo completo em
[examples/citacoes.py](../examples/citacoes.py).

## 6. Quando algo dá errado

Toda falha vem com um código `RSP-...` e uma frase explicando. Use `-v` para ver a causa técnica.

| Você vê | O que significa | O que fazer |
|---|---|---|
| `RSP-R001` | O `robots.txt` do site proíbe essa página para o raspador | Respeite. Peça acesso ao site ou use a API oficial |
| `RSP-R002` | Não deu para ler o `robots.txt` (rede ou erro do servidor) | Tente de novo em alguns minutos: o site fica pausado por 5 min |
| `RSP-H403`, `RSP-H429` | O site bloqueou ou pediu para ir mais devagar | O raspador não contorna bloqueio. Diminua o ritmo ou peça acesso |
| `RSP-P...` | Você pediu uma opção que o raspador recusa por política | A mensagem diz o motivo e a alternativa |
| `RSP-U001`, `RSP-U002` | URL ou seletor CSS inválido | Confira a digitação, incluindo o `https://` |
| `RSP-N002` | O endereço leva a uma rede interna (MCP, navegador ou redirect) | Se for uma intranet sua, use `--allow-private` no MCP |
| `RSP-B001` | O navegador não abriu | Rode `raspador install` |
| `No such command 'ler'` | O terminal está usando uma versão antiga | `hash -r` ou abra um terminal novo |

O código de saída do comando também informa o tipo de problema: 0 é sucesso, 6 é bloqueio (robots.txt ou site) e a
lista completa está no [README](../README.md#cli).

## 7. Uso responsável: o que continua sendo sua responsabilidade

O raspador cuida do comportamento da ferramenta: respeita o `robots.txt`, se identifica e não se disfarça. O ritmo
automático (intervalo mínimo, uma requisição por vez, parada após bloqueios) só existe no Spider: um laço seu em
Python ou muitos pedidos seguidos ao Claude via MCP batem no site na velocidade que você mandar. O raspador também
não decide por você se o uso dos dados é permitido. Antes de raspar, confira:

- **Termos de uso do site.** Alguns proíbem coleta automatizada mesmo quando o `robots.txt` permite.
- **Dados pessoais (LGPD no Brasil, GDPR na Europa).** Nomes, e-mails, telefones e perfis continuam sendo dados
  pessoais mesmo quando estão públicos. Coletar e guardar exige finalidade e base legal. Na dúvida, não colete ou
  anonimize.
- **Direitos autorais.** Ler uma página não dá direito de republicar o conteúdo.
- **Ritmo.** Para mais de algumas páginas, use o Spider. Não reduza o intervalo sem necessidade: o Spider recusa
  menos de 0,5 s.
- **Contato.** Informe o `--contact`: assim o dono do site fala com você antes de bloquear.
- **Arquivos gravados.** O `-o` sobrescreve o arquivo se ele existir. O `audit.jsonl` guarda URLs visitadas, sem
  query string nem senhas. O `crawldir` é diferente: o checkpoint guarda as requisições pendentes, inclusive
  headers e cookies que você passou ao site, num formato (pickle) que executa código ao ser carregado. Trate o
  `crawldir` como segredo, não o commite e **nunca reutilize um `crawldir` recebido de outra pessoa**.

## 8. Atualizar e desinstalar

```bash
uv tool upgrade raspador-compliant          # ou: pipx upgrade raspador-compliant
uv tool uninstall raspador-compliant        # ou: pipx uninstall raspador-compliant
claude mcp remove raspador --scope user     # se registrou o MCP
```

O navegador baixado pelo `raspador install` fica no cache do Playwright (`~/Library/Caches/ms-playwright` no macOS,
`~/.cache/ms-playwright` no Linux) e pode ser apagado à mão.

## 9. Segurança e créditos

Os riscos conhecidos, o que a ferramenta mitiga e como relatar uma vulnerabilidade estão em
[SECURITY.md](../SECURITY.md).

O raspador é construído pela equipe [semente.dev](https://semente.dev), by Alexandre Camerini, sobre o
[Scrapling](https://github.com/D4Vinci/Scrapling), de Karim Shoair. Licença BSD 3-Clause.
