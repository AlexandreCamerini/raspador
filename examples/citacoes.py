"""Crawl real de verificação: quotes.toscrape.com, site público feito para treino de scraping.

Aceite: robots.txt consultado, 3 páginas no máximo, itens com texto/autor/tags, auditoria em JSONL.

    uv run python examples/citacoes.py
"""

from pathlib import Path

from raspador import Spider

SAIDA = Path(__file__).resolve().parent / "saida"
MAX_PAGINAS = 3


class Citacoes(Spider):
    name = "citacoes"
    start_urls = ["https://quotes.toscrape.com/"]
    allowed_domains = {"quotes.toscrape.com"}
    download_delay = 1.0
    audit_path = SAIDA / "audit.jsonl"

    paginas = 0

    async def parse(self, response):
        self.paginas += 1
        for q in response.css("div.quote"):
            yield {
                "texto": q.css("span.text::text").get(),
                "autor": q.css("small.author::text").get(),
                "tags": q.css("a.tag::text").getall(),
                "url": response.url,
            }
        if self.paginas < MAX_PAGINAS:
            for href in response.css("li.next a::attr(href)").getall():
                yield response.follow(href)


if __name__ == "__main__":
    SAIDA.mkdir(exist_ok=True)
    resultado = Citacoes().start()
    resultado.items.to_json(SAIDA / "citacoes.json")
    print(f"itens: {len(resultado.items)}  páginas: {len({i['url'] for i in resultado.items})}")
