"""CLI `raspador`. Extração sem código, com a mesma política da API Python."""

from __future__ import annotations

import json as jsonlib
import logging
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import click
from curl_cffi import CurlError
from curl_cffi.requests.exceptions import RequestException
from playwright.sync_api import Error as PlaywrightError  # sempre presente via scrapling[fetchers]
from scrapling.core.shell import Convertor

from raspador import _ui, http
from raspador.browser import BrowserUnavailable
from raspador.policy import PolicyError
from raspador.robots import RobotsDenied

_BLOCK_STATUS = {401, 403, 407, 429}


def _parse_headers(values: tuple[str, ...]) -> dict[str, str]:
    headers = {}
    for raw in values:
        if ":" not in raw:
            raise click.BadParameter(f"header sem ':' -> {raw!r}; use 'Nome: valor'", param_hint="-H")
        k, v = raw.split(":", 1)
        headers[k.strip()] = v.strip()
    return headers


def _parse_pairs(values: tuple[str, ...], flag: str) -> dict[str, str]:
    out = {}
    for raw in values:
        if "=" not in raw:
            raise click.BadParameter(f"esperado chave=valor -> {raw!r}", param_hint=flag)
        k, v = raw.split("=", 1)
        out[k] = v
    return out


def _parse_cookies(raw: str | None) -> dict[str, str]:
    if not raw:
        return {}
    return dict(part.strip().split("=", 1) for part in raw.split(";") if "=" in part)


def _render(page: Any, out: str, selector: str | None, ai_targeted: bool) -> str:
    """Formato pela extensão: .md Markdown, .html HTML, o resto texto. --ai-targeted sanitiza sempre."""
    suffix = Path(out).suffix.lower() if out != "-" else ".txt"
    if suffix == ".md":
        return page.markdown(css_selector=selector, main_content_only=ai_targeted)
    base = Convertor._sanitize_for_ai(Convertor._strip_noise_tags(page)) if ai_targeted else page
    nodes = base.css(selector) if selector else [base]
    if suffix in {".html", ".htm"}:
        return "\n".join(str(n.html_content) for n in nodes)
    return "\n".join(str(n.get_all_text(separator="\n", strip=True)) for n in nodes)


class _Ctx:
    def __init__(self, color: _ui.ColorMode, verbose: bool, report: str) -> None:
        self.color: _ui.ColorMode = color
        self.verbose = verbose
        self.report = report

    def emit_json(self, **data: Any) -> None:
        click.echo(jsonlib.dumps(data, ensure_ascii=False))

    def fail(
        self,
        exit_code: int,
        code: str,
        message: str,
        *,
        url: str,
        status: int | None = None,
        hint: str | None = None,
        detail: str | None = None,
        policy_err: PolicyError | None = None,
    ) -> None:
        if self.report == "json":
            self.emit_json(
                ok=False,
                status=status,
                url=url,
                output=None,
                bytes=0,
                elapsed_ms=None,
                error={"code": code, "message": message, "hint": hint},
            )
        elif policy_err is not None:
            _ui.policy_error(policy_err, mode=self.color)
        else:
            _ui.error(code, message, hint=hint, detail=detail, mode=self.color, verbose=self.verbose)
        sys.exit(exit_code)


def _run_fetch(
    ctx: _Ctx, url: str, output: str, css_selector: str | None, ai_targeted: bool, do_fetch: Callable[[], Any]
) -> None:
    """Busca, trata erros e grava a saída; comum a get/post/put/delete e fetch (navegador)."""
    started = time.monotonic()
    try:
        page = do_fetch()
    except PolicyError as e:
        ctx.fail(_ui.EXIT_POLICY, e.code, str(e), url=url, policy_err=e)
        return
    except RobotsDenied as e:
        ctx.fail(
            _ui.EXIT_BLOCKED,
            e.code,
            f"o robots.txt não permite {url} para o raspador.",
            url=url,
            hint="o raspador sempre respeita o robots.txt; peça acesso ao dono do site.",
        )
        return
    except (http.RedirectBlocked, http.ResponseTooLarge) as e:
        ctx.fail(_ui.EXIT_NETWORK, e.code, str(e).split(": ", 1)[1], url=url)
        return
    except BrowserUnavailable as e:
        ctx.fail(
            _ui.EXIT_NETWORK,
            e.code,
            "não foi possível abrir o Chromium.",
            url=url,
            hint="instale com pip install 'raspador[browser]' e raspador install.",
            detail=repr(e.__cause__),
        )
        return
    except PlaywrightError as e:
        ctx.fail(
            _ui.EXIT_NETWORK,
            "RSP-B002",
            "o navegador não conseguiu carregar a página (tempo esgotado ou erro de rede).",
            url=url,
            hint="se o conteúdo vem por JavaScript, aumente --timeout ou confira o --wait-selector.",
            detail=repr(e),
        )
        return
    except (CurlError, RequestException, OSError) as e:  # rede; bug do raspador cai fora e sai com 1
        ctx.fail(
            _ui.EXIT_NETWORK,
            "RSP-N001",
            "falha de rede ao acessar o endereço.",
            url=url,
            hint="confira o endereço e a conexão; use -v para ver a causa.",
            detail=repr(e),
        )
        return
    elapsed = time.monotonic() - started
    if page.status >= 400:
        blocked = page.status in _BLOCK_STATUS
        hint = (
            "o raspador não tenta contornar bloqueios. Peça acesso ou use a API oficial do site." if blocked else None
        )
        ctx.fail(
            _ui.EXIT_BLOCKED if blocked else _ui.EXIT_NETWORK,
            f"RSP-H{page.status}",
            f"o servidor respondeu HTTP {page.status} em {url}.",
            url=url,
            status=page.status,
            hint=hint,
        )
        return
    content = _render(page, output, css_selector, ai_targeted)
    empty = bool(css_selector) and not content.strip()
    try:
        if output == "-":
            click.echo(content, nl=not content.endswith("\n"))
        else:
            Path(output).write_text(content, encoding="utf-8")
    except OSError as e:
        ctx.fail(_ui.EXIT_FILE, "RSP-F003", f"não foi possível gravar {output}: {e.strerror}.", url=url)
        return
    size = len(content.encode("utf-8"))
    if ctx.report == "json":
        ctx.emit_json(
            ok=not empty,
            status=page.status,
            url=page.url,
            output=None if output == "-" else output,
            bytes=size,
            elapsed_ms=int(elapsed * 1000),
            error=None,
        )
    elif output != "-":
        _ui.result_line(
            page.status, page.url, output, size, elapsed, empty_selector=css_selector if empty else None, mode=ctx.color
        )
    sys.exit(_ui.EXIT_EMPTY if empty else _ui.EXIT_OK)


def _fetch_command(method: str):
    def command(
        *,
        url: str,
        output: str,
        css_selector: str | None,
        header: tuple[str, ...],
        cookies: str | None,
        timeout: int,
        proxy: str | None,
        param: tuple[str, ...],
        follow_redirects: bool,
        verify: bool,
        ai_targeted: bool,
        contact: str | None,
        color: _ui.ColorMode,
        verbose: bool,
        report: str,
        data: str | None = None,
        json_body: str | None = None,
    ) -> None:
        ctx = _Ctx(color, verbose, report)
        # O logger do upstream imprime "INFO: Fetched ..." no stderr; fora do formato da CLI.
        logging.getLogger("scrapling").setLevel(logging.DEBUG if verbose else logging.WARNING)
        if report == "json" and output == "-":
            raise click.UsageError("--report json precisa de um arquivo como OUTPUT; com '-' o stdout já é o conteúdo.")
        kwargs: dict[str, Any] = {"timeout": timeout, "follow_redirects": follow_redirects, "verify": verify}
        if header:
            kwargs["headers"] = _parse_headers(header)
        if cookies:
            kwargs["cookies"] = _parse_cookies(cookies)
        if param:
            kwargs["params"] = _parse_pairs(param, "-p")
        if proxy:
            kwargs["proxy"] = proxy
        if data:
            kwargs["data"] = data
        if json_body:
            try:
                kwargs["json"] = jsonlib.loads(json_body)
            except ValueError as e:
                raise click.BadParameter(f"JSON inválido: {e}", param_hint="-j") from e
        _run_fetch(
            ctx, url, output, css_selector, ai_targeted, lambda: getattr(http, method)(url, contact=contact, **kwargs)
        )

    command.__name__ = method
    return command


def _common_options(with_body: bool):
    def decorate(f):
        opts = [
            click.argument("url"),
            click.argument("output"),
            click.option("-s", "--css-selector", help="Extrai só o que casar com o seletor CSS (todos os matches)."),
            click.option("-H", "--header", multiple=True, help="Header 'Nome: valor' (pode repetir)."),
            click.option("--cookies", help="Cookies 'a=1; b=2'."),
            click.option("--timeout", default=30, show_default=True, help="Timeout em segundos."),
            click.option("--proxy", help="Proxy fixo 'http://usuario:senha@host:porta'."),
            click.option("-p", "--param", multiple=True, help="Query string chave=valor (pode repetir)."),
            click.option("--follow-redirects/--no-follow-redirects", default=True, show_default=True),
            click.option("--verify/--no-verify", default=True, show_default=True, help="Verificar o certificado TLS."),
            click.option("--ai-targeted", is_flag=True, help="Só o conteúdo principal, sem elementos ocultos."),
            click.option("--contact", help="E-mail ou URL que vai no User-Agent para o dono do site falar com você."),
            click.option("--color", type=click.Choice(["auto", "always", "never"]), default="auto", show_default=True),
            click.option("-v", "--verbose", is_flag=True, help="Mostra a causa técnica dos erros."),
            click.option(
                "--report",
                type=click.Choice(["text", "json"]),
                default="text",
                show_default=True,
                help="json: um objeto de resultado no stdout.",
            ),
        ]
        if with_body:
            opts += [
                click.option("-d", "--data", help="Corpo form-encoded 'a=1&b=2'."),
                click.option("-j", "--json", "json_body", help="Corpo JSON."),
            ]
        for opt in reversed(opts):
            f = opt(f)
        return f

    return decorate


@click.group(context_settings={"help_option_names": ["-h", "--help"], "max_content_width": 80})
@click.version_option(package_name="raspador")
def main() -> None:
    """Raspagem web que respeita o site: robots.txt sempre, User-Agent identificado, sem evasão anti-bot.

    \b
    Exemplos:
      raspador get https://exemplo.com.br/noticia noticia.md
      raspador get https://exemplo.com.br/lista - -s "article h2"

    Política: o raspador recusa opções de disfarce e explica o motivo (códigos RSP-P...).
    """


for _method in ("get", "post", "put", "delete"):
    main.command(name=_method, help=f"{_method.upper()} em URL e grava em OUTPUT (.md, .html ou texto; '-' = stdout).")(
        _common_options(with_body=_method in {"post", "put"})(_fetch_command(_method))
    )


@main.command(name="fetch")
@click.argument("url")
@click.argument("output")
@click.option("-s", "--css-selector", help="Extrai só o que casar com o seletor CSS (todos os matches).")
@click.option("--wait-selector", help="Espera este seletor aparecer antes de ler a página.")
@click.option("--network-idle", is_flag=True, help="Espera a rede ficar ociosa.")
@click.option("--disable-resources", is_flag=True, help="Não carrega imagens, fontes, mídia e CSS.")
@click.option("--timeout", default=30, show_default=True, help="Timeout em segundos.")
@click.option("--locale", help="Locale do navegador, ex.: pt-BR.")
@click.option("--proxy", help="Proxy fixo 'http://host:porta'.")
@click.option("--ai-targeted", is_flag=True, help="Só o conteúdo principal, sem elementos ocultos.")
@click.option("--contact", help="E-mail ou URL que vai no User-Agent para o dono do site falar com você.")
@click.option("--color", type=click.Choice(["auto", "always", "never"]), default="auto", show_default=True)
@click.option("-v", "--verbose", is_flag=True, help="Mostra a causa técnica dos erros.")
@click.option("--report", type=click.Choice(["text", "json"]), default="text", show_default=True)
def fetch_cmd(
    url: str,
    output: str,
    css_selector: str | None,
    wait_selector: str | None,
    network_idle: bool,
    disable_resources: bool,
    timeout: int,
    locale: str | None,
    proxy: str | None,
    ai_targeted: bool,
    contact: str | None,
    color: _ui.ColorMode,
    verbose: bool,
    report: str,
) -> None:
    """Abre URL num Chromium (JavaScript renderizado) e grava em OUTPUT. Requer raspador[browser]."""
    from raspador import browser

    ctx = _Ctx(color, verbose, report)
    logging.getLogger("scrapling").setLevel(logging.DEBUG if verbose else logging.WARNING)
    if report == "json" and output == "-":
        raise click.UsageError("--report json precisa de um arquivo como OUTPUT; com '-' o stdout já é o conteúdo.")
    kwargs: dict[str, Any] = {
        "timeout": timeout * 1000,
        "network_idle": network_idle,
        "disable_resources": disable_resources,
    }
    if wait_selector:
        kwargs["wait_selector"] = wait_selector
    session_kw = {k: v for k, v in {"locale": locale, "proxy": proxy}.items() if v}
    _run_fetch(
        ctx, url, output, css_selector, ai_targeted, lambda: browser.fetch(url, contact=contact, **session_kw, **kwargs)
    )


@main.command()
@click.option("--force", is_flag=True, help="Reinstala mesmo se já existir.")
def install(force: bool) -> None:
    """Instala o Chromium do Playwright (só necessário para o navegador, M3).

    Não roda `scrapling install`, que baixa as ferramentas de impressão digital do modo stealth.
    """
    args = [sys.executable, "-m", "playwright", "install", *(["--force"] if force else []), "chromium"]
    sys.exit(subprocess.run(args, check=False).returncode)
