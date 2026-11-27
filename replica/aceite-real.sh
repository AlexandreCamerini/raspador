#!/usr/bin/env bash
# Aceite na rede real (sites de treino e de teste HTTP). Não roda no sandbox: precisa de DNS e saída para a internet.
#   ./replica/aceite-real.sh            todos os cenários
#   ./replica/aceite-real.sh A1 A3      só os pedidos
# Saída 0: tudo PASS (ou SKIP); 1: algum FAIL; 2: só INCON (site de terceiro fora). Relatório em ./aceite-saida/.
set -euo pipefail
cd "$(dirname "$0")/.."

py="$PWD/.venv/bin/python"
[[ -x "$py" ]] || { echo "falta $py: rode 'uv sync' antes" >&2; exit 2; }

exec "$py" replica/aceite_real.py "$@"
