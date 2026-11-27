#!/usr/bin/env bash
# C3: Claude Code real chamando o `raspador mcp` em stdio. Aceite: a resposta traz a primeira frase da página.
# O prompt vai pelo stdin porque --allowedTools é variádico e engoliria um prompt posicional.
set -euo pipefail
cd "$(dirname "$0")/.."

exe="$PWD/.venv/bin/raspador"
[[ -x "$exe" ]] || { echo "falta $exe: rode 'uv sync' antes" >&2; exit 2; }

cfg=$(printf '{"mcpServers":{"raspador":{"command":"%s","args":["mcp"]}}}' "$exe")
prompt="Use a ferramenta mcp__raspador__make_request para buscar https://example.com e responda só com a primeira frase do texto da página."

saida=$(printf '%s' "$prompt" | claude -p --model haiku --strict-mcp-config --mcp-config "$cfg" \
  --allowedTools=mcp__raspador__make_request)
echo "$saida"

# o example.com atual não tem <h1>: o corpo começa num <p> "This domain is for use in ..."
if grep -qi "This domain is for use" <<<"$saida"; then
  echo "C3: OK"
else
  echo "C3: FALHOU (resposta acima)" >&2
  exit 1
fi
