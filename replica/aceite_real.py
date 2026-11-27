"""Aceite na rede real: o raspador contra sites de verdade, com critério verificável por cenário.

Só sites feitos para treino de scraping ou para teste de HTTP (toscrape.com, httpbin.org), em ritmo educado.
Não roda em todo push: site de terceiro muda e cai. Rode à mão (replica/aceite-real.sh) ou pelo job manual do CI.

Resultado por cenário:
  PASS  critério atendido
  FAIL  o raspador fez algo errado
  INCON o site não respondeu (rede, 5xx, robots.txt ilegível): não diz nada sobre o raspador
  SKIP  pré-requisito ausente (Chromium, `claude`); com ACEITE_EXIGE_NAVEGADOR=1 o do Chromium vira FAIL

Saída: tabela no stdout e relatório JSON em $ACEITE_SAIDA (padrão: ./aceite-saida).
Código de saída: 0 se nada FAIL nem INCON; 1 se algum FAIL; 2 se só INCON.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import raspador
from raspador import RobotsDenied, RobotsUnavailable, Spider
from raspador.http import RedirectBlocked

RAIZ = Path(__file__).resolve().parents[1]
SAIDA = Path(os.environ.get("ACEITE_SAIDA", RAIZ / "aceite-saida"))
EXIGE_NAVEGADOR = os.environ.get("ACEITE_EXIGE_NAVEGADOR") == "1"
DELAY = 1.0


class Inconclusivo(Exception):
    """O site de terceiro falhou; o cenário não prova nada sobre o raspador."""


@dataclass
class Resultado:
    id: str
    titulo: str
    status: str = "PASS"
    detalhes: dict = field(default_factory=dict)
    erro: str | None = None
    segundos: float = 0.0


def _exigir(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


# --- A1 + A5: spider paginado, pausa e retomada pelo crawldir, ritmo por domínio -----------------------------------


def a1_retomada_e_ritmo(r: Resultado) -> None:
    """books.toscrape.com, páginas 1 a 6 do catálogo (20 livros cada). A 1ª rodada pausa depois da página 3;
    a 2ª retoma do crawldir. Critérios: 120 livros únicos, nenhum duplicado, nenhuma página buscada nas duas
    rodadas, 1ª rodada `paused`, 2ª `completed`, intervalo entre respostas >= 90% do download_delay."""
    ultima = 6
    vistos: dict[int, list[tuple[str, float]]] = {1: [], 2: []}
    rodada = {"n": 1}

    class Livros(Spider):
        name = "aceite-livros"
        start_urls = ["https://books.toscrape.com/catalogue/page-1.html"]
        allowed_domains = {"books.toscrape.com"}
        download_delay = DELAY

        async def parse(self, response):
            n = rodada["n"]
            vistos[n].append((response.url, time.monotonic()))
            for livro in response.css("article.product_pod"):
                yield {
                    "url": response.urljoin(str(livro.css("h3 a::attr(href)").get() or "")),
                    "titulo": livro.css("h3 a::attr(title)").get(),
                    "preco": livro.css("p.price_color::text").get(),
                }
            pagina = int(response.url.rsplit("page-", 1)[1].split(".")[0])
            if pagina < ultima:
                for href in response.css("li.next a::attr(href)").getall():
                    yield response.follow(href)
            if n == 1 and pagina == 3:
                self.pause()  # depois de enfileirar a página 4: o checkpoint precisa ter o que retomar

    crawldir = Path(tempfile.mkdtemp(prefix="aceite-crawl-"))
    try:
        r1 = Livros(crawldir=crawldir).start()
        if not vistos[1]:
            raise Inconclusivo("nenhuma página respondeu na 1ª rodada (rede ou robots.txt ilegível)")
        rodada["n"] = 2
        r2 = Livros(crawldir=crawldir).start()
    finally:
        shutil.rmtree(crawldir, ignore_errors=True)

    itens = list(r1.items) + list(r2.items)
    urls = [i["url"] for i in itens]
    paginas1 = {u for u, _ in vistos[1]}
    paginas2 = {u for u, _ in vistos[2]}
    tempos = sorted(t for lista in vistos.values() for _, t in lista)
    gaps1 = [b - a for (_, a), (_, b) in zip(vistos[1], vistos[1][1:], strict=False)]
    gaps2 = [b - a for (_, a), (_, b) in zip(vistos[2], vistos[2][1:], strict=False)]
    menor_gap = min(gaps1 + gaps2) if (gaps1 or gaps2) else None
    r.detalhes = {
        "itens_rodada_1": len(r1.items),
        "itens_rodada_2": len(r2.items),
        "unicos": len(set(urls)),
        "duplicados": len(urls) - len(set(urls)),
        "paginas_rodada_1": sorted(paginas1),
        "paginas_rodada_2": sorted(paginas2),
        "paginas_repetidas": sorted(paginas1 & paginas2),
        "rodada_1_paused": r1.paused,
        "rodada_2_completed": r2.completed,
        "menor_intervalo_s": round(menor_gap, 3) if menor_gap is not None else None,
        "duracao_total_s": round(tempos[-1] - tempos[0], 1) if tempos else None,
        "campos_vazios": sum(1 for i in itens if not (i["titulo"] and i["preco"])),
    }
    d = r.detalhes
    _exigir(d["rodada_1_paused"], "a 1ª rodada não terminou como paused")
    _exigir(d["rodada_2_completed"], "a 2ª rodada não completou")
    _exigir(not d["paginas_repetidas"], f"páginas buscadas nas duas rodadas: {d['paginas_repetidas']}")
    _exigir(d["duplicados"] == 0, f"{d['duplicados']} livros duplicados")
    _exigir(d["unicos"] == 20 * ultima, f"esperava {20 * ultima} livros únicos, veio {d['unicos']}")
    _exigir(d["campos_vazios"] == 0, f"{d['campos_vazios']} itens sem título ou preço")
    _exigir(menor_gap is not None and menor_gap >= 0.9 * DELAY, f"intervalo {menor_gap}s < 90% de {DELAY}s")


# --- A2: página que só existe com JavaScript ----------------------------------------------------------------------


def a2_pagina_js(r: Resultado) -> None:
    """quotes.toscrape.com/js monta as citações em JS. Critério: HTTP puro vê 0, o navegador vê 10."""
    url = "https://quotes.toscrape.com/js/"
    p = _get(url)
    sem_js = len(p.css("div.quote"))
    try:
        from raspador.browser import BrowserSession, BrowserUnavailable
    except ImportError as exc:  # extra do navegador ausente
        _sem_navegador(r, exc)
        return
    try:
        with BrowserSession() as b:
            com_js = len(b.fetch(url, wait_selector="div.quote").css("div.quote"))
    except BrowserUnavailable as exc:
        _sem_navegador(r, exc)
        return
    r.detalhes = {"http_div_quote": sem_js, "navegador_div_quote": com_js}
    _exigir(sem_js == 0, f"HTTP puro já viu {sem_js} citações: a página deixou de depender de JS?")
    _exigir(com_js == 10, f"o navegador viu {com_js} citações, esperava 10")


def _sem_navegador(r: Resultado, exc: Exception) -> None:
    r.status = "FAIL" if EXIGE_NAVEGADOR else "SKIP"
    r.erro = f"Chromium indisponível: {type(exc).__name__}"


# --- A3: robots.txt negando -----------------------------------------------------------------------------------------


def a3_robots_nega(r: Resultado) -> None:
    """httpbin.org/robots.txt tem `Disallow: /deny`. Critério: RobotsDenied RSP-R001 (não R002), sem resposta de
    /deny. Que a checagem vem antes do fetch é coberto offline em tests/ (aqui não há como ver o tráfego)."""
    try:
        p = raspador.get("https://httpbin.org/deny")
    except RobotsUnavailable as exc:
        raise Inconclusivo(f"robots.txt do httpbin ilegível: {exc.reason}") from exc
    except RobotsDenied as exc:
        r.detalhes = {"codigo": exc.code, "mensagem": str(exc)}
        _exigir(exc.code == "RSP-R001", f"código {exc.code}, esperava RSP-R001")
        return
    raise AssertionError(f"/deny foi buscado (status {p.status}) apesar do Disallow")


# --- A4: redirect para endereço interno ----------------------------------------------------------------------------


REDIRECTOR = "https://postman-echo.com/redirect-to?url="  # httpbin.org passou a dar 403 para destino interno


def a4_redirect_interno(r: Resultado) -> None:
    """Um site público manda 302 para o serviço de metadados de nuvem, por IP literal e por hostname que resolve
    para ele (nip.io, caminho do DNS). Critério: RedirectBlocked RSP-N002 nos dois. Se o site não redirecionar
    (ou mudar de política), INCON: sem 3xx não há o que provar."""
    alvos = {
        "ip_literal": "http://169.254.169.254/latest/meta-data/",
        "hostname_dns": "http://169.254.169.254.nip.io/latest/meta-data/",
    }
    for nome, alvo in alvos.items():
        try:
            p = raspador.get(REDIRECTOR + alvo)
        except RobotsUnavailable as exc:
            raise Inconclusivo(f"robots.txt do redirecionador ilegível: {exc.reason}") from exc
        except RedirectBlocked as exc:
            r.detalhes[nome] = {"codigo": exc.code, "mensagem": str(exc)}
            _exigir(exc.code == "RSP-N002", f"{nome}: código {exc.code}, esperava RSP-N002")
            continue
        if p.url.startswith(REDIRECTOR) or p.status >= 500:
            raise Inconclusivo(f"{nome}: o redirecionador não redirecionou (status {p.status})")
        raise AssertionError(f"{nome}: o redirect foi seguido (status {p.status}, url {p.url})")


# --- A6: identidade -------------------------------------------------------------------------------------------------


def a6_user_agent(r: Resultado) -> None:
    """httpbin.org/headers devolve os headers recebidos. Critério: User-Agent começa com `raspador/` e nenhum
    header de navegador falso (Sec-Ch-Ua) foi enviado."""
    p = _get("https://httpbin.org/headers")
    recebidos = {k.lower(): v for k, v in json.loads(p.body)["headers"].items()}
    ua = recebidos.get("user-agent", "")
    r.detalhes = {"user_agent": ua, "headers": sorted(recebidos)}
    _exigir(ua.startswith("raspador/"), f"User-Agent {ua!r} não identifica o raspador")
    _exigir(not any(k.startswith("sec-ch-ua") for k in recebidos), "enviou client hints de navegador")


# --- A7: MCP pelo Claude Code real ----------------------------------------------------------------------------------


def a7_mcp_claude(r: Resultado) -> None:
    """replica/c3-claude-code.sh: Claude Code chama `make_request` no `raspador mcp` em stdio."""
    if shutil.which("claude") is None:
        r.status, r.erro = "SKIP", "`claude` fora do PATH"
        return
    proc = subprocess.run(
        ["bash", str(RAIZ / "replica" / "c3-claude-code.sh")], capture_output=True, text=True, timeout=300
    )
    r.detalhes = {"saida": proc.stdout[-500:], "codigo_saida": proc.returncode}
    _exigir(proc.returncode == 0, f"c3-claude-code.sh saiu com {proc.returncode}: {proc.stderr[-300:]}")


# --- execução -----------------------------------------------------------------------------------------------------


def _get(url: str):
    try:
        p = raspador.get(url)
    except RobotsUnavailable as exc:
        raise Inconclusivo(f"robots.txt ilegível: {exc.reason}") from exc
    if p.status >= 500:
        raise Inconclusivo(f"{url} respondeu {p.status}")
    return p


CENARIOS: list[tuple[str, str, Callable[[Resultado], None]]] = [
    ("A1", "spider paginado: pausa, retoma do crawldir, ritmo por domínio", a1_retomada_e_ritmo),
    ("A2", "página só com JS: HTTP vê 0, navegador vê 10", a2_pagina_js),
    ("A3", "robots.txt nega /deny: RSP-R001 sem buscar a página", a3_robots_nega),
    ("A4", "redirect para 169.254.169.254 (IP e hostname): RSP-N002", a4_redirect_interno),
    ("A6", "User-Agent raspador/ e nenhum header de navegador", a6_user_agent),
    ("A7", "Claude Code real chama o raspador mcp", a7_mcp_claude),
]


def main(argv: list[str]) -> int:
    pedidos = {a.upper() for a in argv}
    resultados: list[Resultado] = []
    for cid, titulo, fn in CENARIOS:
        if pedidos and cid not in pedidos:
            continue
        r = Resultado(cid, titulo)
        inicio = time.monotonic()
        try:
            fn(r)
        except Inconclusivo as exc:
            r.status, r.erro = "INCON", str(exc)
        except AssertionError as exc:
            r.status, r.erro = "FAIL", str(exc)
        except Exception as exc:  # erro inesperado do raspador também é FAIL, com o traceback no relatório
            r.status, r.erro = "FAIL", f"{type(exc).__name__}: {exc}"
            r.detalhes["traceback"] = traceback.format_exc()[-2000:]
        r.segundos = round(time.monotonic() - inicio, 1)
        resultados.append(r)
        print(f"{r.status:<5} {cid}  {titulo}  ({r.segundos}s)" + (f"\n      {r.erro}" if r.erro else ""), flush=True)

    SAIDA.mkdir(parents=True, exist_ok=True)
    relatorio = {
        "quando": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "raspador": raspador.__version__,
        "python": sys.version.split()[0],
        "resultados": [asdict(r) for r in resultados],
    }
    (SAIDA / "relatorio.json").write_text(json.dumps(relatorio, ensure_ascii=False, indent=2))
    contagem = {s: sum(r.status == s for r in resultados) for s in ("PASS", "FAIL", "INCON", "SKIP")}
    print(" ".join(f"{k}={v}" for k, v in contagem.items()), f"→ {SAIDA / 'relatorio.json'}")
    if contagem["FAIL"]:
        return 1
    return 2 if contagem["INCON"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
