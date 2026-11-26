# Componentes de saída do raspador (CLI e API Python)

Data: 2026-11-26. Entrada: `replica/recon.md`, `replica/architecture.md`, `tokens.json`.

## Adaptação do replica-design

O raspador não tem interface gráfica. O "design system" dele é o que aparece no terminal e nas exceções:

- **Componentes** = primitivos de saída: ajuda, erro, aviso, resultado, progresso, resumo, log, JSON, códigos de saída e exceção Python.
- **Tokens** = papéis de terminal em `tokens.json`.
- **Não se aplica** = `tokens.css`, Tailwind, rota `/design`, ícones, fontes e screenshots. O terminal é do usuário.
- **Primitivos em código** = o módulo `raspador/_ui.py`, feito no M2 junto com a CLI (S11). Hoje o projeto ainda não tem o esqueleto do M0.

## Regras gerais

1. **O significado vai em palavras, nunca só na cor** (WCAG 1.4.1). Toda marcação tem texto (`ERRO`, `POLÍTICA`, `aviso:`, `ok`).
2. **Sem matiz ANSI em texto.** Medido: nenhuma das 16 cores do xterm passa 4.5:1 ao mesmo tempo em fundo claro e escuro. Verde, amarelo e ciano ficam entre 1.1 e 2.2:1 no fundo claro (ver `_evidence_ansi_xterm`). As marcações usam **vídeo reverso + negrito** (SGR `1;7`): o contraste vira o do tema do usuário (21:1 e 16.7:1 nos temas de referência, contrast.py sem falha).
3. **Quando há estilo:** só se stdout ou stderr for TTY, se `NO_COLOR` não estiver definido e se `TERM` não for `dumb`. `--color auto|always|never` sobrescreve; `FORCE_COLOR` equivale a `always`. Num pipe ou no CI, sai texto puro.
4. **stdout é para dados, stderr é para pessoas.** O conteúdo extraído, quando `OUT` é `-`, e o `--json` vão para stdout. Todo o resto vai para stderr. `raspador get URL - | grep` nunca recebe log misturado.
5. **ASCII seguro.** Se a codificação de stdout ou stderr não for UTF-8, usar o `ascii_fallback` (`->`, `...`). Sem emoji, sem spinner braille (leitor de tela lê cada quadro).
6. **Idioma.** Mensagens em PT-BR. Cada erro tem um **código estável** (`RSP-…`), para buscar e citar sem depender do texto.
7. **Hora** sempre em UTC, ISO 8601 com `Z`.
8. **Texto escrito do zero.** Nenhuma mensagem, help ou exemplo copiado do Scrapling.

## Componentes

```
Ajuda (--help)
  variantes  raiz (raspador --help), por comando (raspador get --help)
  estrutura  uso numa linha; descrição em uma frase; argumentos; opções agrupadas
             (Requisição, Saída, Rede); 1 a 2 exemplos reais; linha final
             "Política: veja raspador --policy" quando o comando faz fetch
  estados    padrão; comando desconhecido -> erro RSP-U001 com sugestão "você quis dizer"
             (distância de edição <= 2)
  tokens     text; enfase no nome do comando
  a11y       largura <= 80 colunas; sem tabela desenhada com caracteres de caixa
  usado em   S10, S11, S12, S13
```

```
Mensagem de erro
  formato    raspador: [ERRO] RSP-<área><nnn>: <o que aconteceu, uma frase>
               dica: <o que fazer, uma frase>              (opcional)
               detalhe: <causa técnica, ex.: exceção curl>  (só com -v)
  áreas      U uso/CLI, N rede, H HTTP, R robots, P política, F arquivo, B navegador
  estados    rede (timeout, DNS, TLS), HTTP 4xx/5xx, arquivo sem permissão, crawldir inseguro
  tokens     tag-erro; text
  saída      stderr; código de saída da tabela abaixo
  a11y       a tag é texto; a mensagem não depende da cor; sem traceback por padrão
             (-v ou RASPADOR_DEBUG=1 mostra)
  usado em   S01, S02, S07, S10, S11, S13
  exemplo    raspador: [ERRO] RSP-H403: o servidor recusou o acesso (HTTP 403) em loja.exemplo.com.br
               dica: o raspador não tenta contornar bloqueios. Peça acesso ou use a API oficial do site.
```

```
PolicyError (o componente mais importante)
  formato    raspador: [POLÍTICA] RSP-P<nnn>: a opção <nome>=<valor> não é permitida.
               motivo: <por quê, em uma frase>
               em vez disso: <alternativa concreta, ou "não há alternativa no raspador">
  códigos    P001 kwarg fora da allowlist        P002 opção de evasão (impersonate, stealth, solve_cloudflare...)
             P003 header proibido ou User-Agent sem "raspador/"
             P004 tentativa de desligar robots    P005 delay ou slots fora do limite sem policy_override
             P006 ProxyRotator em spider          P007 classe stealth/remota em configure_sessions
             P008 redirect ou start_request fora de allowed_domains (aviso, não erro: o request é descartado)
  Python     class PolicyError(ValueError): code, option, value, reason, alternative
             str(e) = as três linhas acima, sem estilo; repr curto com code e option
  estados    erro (P001-P007); aviso por request descartado (P008, resumido no final do crawl)
  tokens     tag-politica; enfase em <nome>=<valor>
  a11y       a mensagem nomeia a opção exata e a alternativa; nunca "operação não permitida" genérico
  registro   toda ocorrência vira linha no log de auditoria (C6)
  usado em   S01, S02, S03, S04, S07, S08, S11, S13
  exemplo    raspador: [POLÍTICA] RSP-P002: a opção impersonate='chrome' não é permitida.
               motivo: imitar a impressão digital de um navegador é evasão de detecção.
               em vez disso: não há alternativa no raspador; o User-Agent identificado é obrigatório.
```

```
Aviso
  formato    raspador: aviso: <frase>
  casos      robots negou N URLs; domínio parado após N bloqueios; checkpoint encontrado (retomando);
             item sem campos; encoding presumido
  regra      avisos repetidos agrupados: o 1º sai na hora, os demais viram contagem no resumo final
  tokens     tag-aviso
  usado em   S07, S08, S11
```

```
Linha de resultado (CLI extract)
  formato    ok  <status>  <url>  -> <arquivo> (<tamanho legível>, <duração>)
  estados    sucesso; seletor sem match -> "ok  200  <url>  -> <arquivo> (vazio: o seletor '<s>' não encontrou nada)"
             com código de saída 4; saída para '-' -> não imprime a linha (stdout é dado)
  tokens     tag-ok; enfase no status e no arquivo; link na URL
  usado em   S11
```

```
Progresso do crawl
  TTY        uma linha em stderr, reescrita no máximo 1x/s:
             <spider>  <n> páginas  <n> itens  <n> na fila  <req/s>  <tempo>
  não-TTY    uma linha de log INFO a cada 30 s com os mesmos campos
  desligar   --no-progress; automático com TERM=dumb ou NO_COLOR + não-TTY
  estados    rodando; pausando ("pausando, salvando checkpoint..." após Ctrl+C); retomado
  a11y       sem spinner; o leitor de tela recebe no máximo 1 atualização por segundo
  usado em   S07, S08
```

```
Resumo do crawl (fim de execução)
  formato    bloco de texto alinhado, sem caracteres de caixa:
             concluído | pausado | interrompido por erro
             páginas        152      itens         140
             status         200: 150 · 404: 2
             robots negou   3        domínios parados  0
             duração        2 min 14 s
             saída          quotes.json (140 itens)
  pausado    acrescenta: "para retomar: rode de novo com crawldir=<caminho>"
  vazio      "nenhum item coletado." + motivo provável (robots negou tudo, seletor, domínio parado)
  dados      os mesmos campos de CrawlStats; a Python API devolve o objeto, a CLI imprime o bloco
  usado em   S07, S08, S09
```

```
Linha de log
  texto      2026-11-26T14:03:12Z INFO  raspador.spider[quotes] <mensagem>
  json       {"ts":"...Z","level":"INFO","logger":"raspador.spider","spider":"quotes","msg":"...", ...campos}
  níveis     DEBUG (cada request), INFO (início/fim/progresso não-TTY), WARNING (avisos), ERROR
  controle   M2: o logger do upstream fica em WARNING na CLI (DEBUG com -v). --log-level, --log-format
             text|json e RASPADOR_LOG_LEVEL ficam para o M3, com o progresso do crawl.
  regra      nunca logar valor de Cookie, Authorization nem query com token: substituir por "***"
  usado em   S07, S08, S11, S13
```

```
Saída JSON (--report json)   [desvio: --json já é o corpo JSON de post/put, como no upstream]
  formato    um objeto por comando em stdout: {"ok":bool,"status":int,"url":str,"output":str|null,
             "bytes":int,"elapsed_ms":int,"error":{"code","message","hint"}|null}
  regra      com --report json, a linha de resultado e o erro humano não saem; o código de saída continua valendo.
             --report json com OUTPUT '-' é erro de uso (código 2): o stdout já é o conteúdo.
  usado em   S11
```

```
Códigos de saída
  0  sucesso
  1  erro inesperado (bug; mostra "rode com -v e abra um issue")
  2  uso incorreto (click)
  3  PolicyError
  4  sucesso sem conteúdo (seletor vazio, crawl sem itens)
  5  rede ou HTTP (timeout, DNS, 4xx/5xx final)
  6  bloqueio: domínio parado ou robots negou o alvo
  7  arquivo ou permissão (crawldir inseguro, OUT sem escrita)
  130 interrompido por Ctrl+C (crawl salva checkpoint antes)
  usado em   S10, S11, S12, S13
```

```
Linha do log de auditoria (C6)
  formato    JSONL, append, UTC:
             {"ts","run_id","spider","event":"robots_denied|policy_error|policy_override|domain_stopped|blocked_retry",
              "domain","url","code","detail"}
  regra      sem corpo de resposta, cookies nem dados pessoais; URL sem query sensível
  usado em   S07, S08 (M1)
```

```
Erro de ferramenta MCP (M4)
  formato    resultado de ferramenta com isError=true e texto:
             "<código>: <mensagem>. <dica>"   (mesmos códigos RSP-*)
  regra      PolicyError nunca vira retry automático no agente: a dica diz que não existe contorno
  usado em   S13
```

## Estados que o recon pediu e onde estão

| estado do recon | componente |
| --- | --- |
| sucesso | linha de resultado, resumo |
| HTTP 4xx/5xx | erro `RSP-H…`, código de saída 5 |
| timeout | erro `RSP-N…`, código de saída 5 |
| bloqueado | erro `RSP-H403`/`H429`, aviso de domínio parado, código de saída 6 |
| seleção vazia | linha de resultado vazia, código de saída 4 |
| JS não renderizado | dica em `RSP-H…` sugerindo `raspador fetch` (M3) |
| pausado e retomado | progresso pausando, resumo pausado, aviso de checkpoint encontrado |

## Critérios de aceite (testes do M2)

- Com `NO_COLOR=1` ou sem TTY, a saída não tem nenhum byte `\x1b`.
- Toda `PolicyError` tem `code`, `option`, `reason` e `alternative` não vazios. `str(e)` contém as três linhas.
- `raspador get URL -` com erro: stdout vazio; stderr com `RSP-`; código de saída correto.
- Linhas de log com Cookie ou Authorization saem mascaradas.
- Com `LANG=C` (não UTF-8), a saída não tem caractere fora do ASCII nas marcações.
- `contrast.py replica/design/tokens.json` com 0 falhas (já passa).
