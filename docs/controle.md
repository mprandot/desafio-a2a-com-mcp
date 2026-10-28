# Controle do desafio A Ponte

Documento vivo do desenvolvimento. Não substitui o `README.md` da entrega.
Os commits ficam para depois do review: o código está na árvore de trabalho, ainda sem commit.

## Decisão de stack

Os dois processos são Python 3.10+ (desenvolvimento em 3.13).

- Servidor MCP: pacote `mcp==2.3.0`, spec `2026-07-28`, `MCPServer` em Streamable HTTP stateless com resposta JSON.
- Agente: o mesmo pacote só como cliente MCP. O A2A v1.0 é JSON-RPC escrito no agente, sem SDK de LLM.
- `requestState`: AEAD AES-256-GCM do SDK (`RequestStateSecurity`), TTL de 600 segundos. A chave vem de `REQUEST_STATE_SECRET` (mínimo 32 bytes). Sem segredo no código.
- Argumentos divergentes no retry são rejeitados pelo digest que o SDK amarra ao token. Esse é um dos caminhos aceitos pelo validador.
- Tasks do agente ficam em memória, por id. O `requestState` opaco fica nesse objeto e não sai em resposta A2A.

## Arquitetura

- `servidor-mcp/servidor_mcp/dominio.py`: salas, reservas em memória, política, alternativas.
- `servidor-mcp/servidor_mcp/app.py`: tools, resource, MRTR, log no stderr.
- `agente/agente/host_mcp.py`: cliente MCP. `tools/list` e leitura de `politica://uso` na subida. `call_tool(..., allow_input_required=True)`. Sem callback que responda a elicitation.
- `agente/agente/tarefas.py`: máquina da Task. `pausar` transforma `input_required` em `TASK_STATE_INPUT_REQUIRED`. `retomar` devolve o `requestState` ao servidor com id JSON-RPC novo.
- `agente/agente/http_a2a.py`: card em `/.well-known/agent-card.json` e `POST /a2a`.

O agente não lê `salas.json` nem `reservas.json` e não calcula conflito, política nem alternativas.

## Critérios de aceite

Todos obrigatórios. A evidência entra na seção de verificação depois da execução.

### Servidor MCP

- [x] Sobe na porta 7301 em Streamable HTTP e responde a `tools/list` com as três tools.
- [x] Toda tool tem `inputSchema` que é um objeto JSON Schema válido.
- [x] `listar_salas` devolve `structuredContent` conforme o `outputSchema` declarado e o mesmo JSON serializado em bloco de texto.
- [x] Request sem `io.modelcontextprotocol/protocolVersion` ou sem `io.modelcontextprotocol/clientCapabilities` recebe `-32602` com HTTP 400.
- [x] `tools/call` de tool inexistente é recusado, por `-32602` ou por `isError`.
- [x] `resources/read` de `politica://uso` devolve o conteúdo de `dados/politica-de-uso.md`, e de URI inexistente devolve `-32602`.
- [x] Sala inexistente, janela violada, duração acima do limite e intervalo invertido devolvem `isError: true` com as mensagens exatas do enunciado.
- [x] O stderr do processo registra método, id e `traceparent` de cada request.

### MRTR

- [x] Reserva em intervalo ocupado devolve `resultType` igual a `input_required`, com uma única entrada em `inputRequests`, em form mode, e um `requestState` presente.
- [x] O `requestedSchema` é plano e restringe a escolha às alternativas calculadas pela regra do enunciado, na ordem definida.
- [x] O mesmo pedido, vindo de cliente que não declarou elicitation em form mode, recebe `-32021` com `data.requiredCapabilities` e HTTP 400.
- [x] O retry com `inputResponses` e `requestState` conclui a reserva e devolve `resultType` igual a `complete`.
- [x] `requestState` adulterado recebe `-32602`.
- [x] Um retry com argumentos adulterados não produz reserva com os valores adulterados.
- [x] Um retry com `requestState` válido conclui a reserva mesmo que o processo do servidor MCP tenha sido reiniciado entre o `input_required` e o retry.
- [x] A chave de integridade vem de `REQUEST_STATE_SECRET`, com no mínimo 32 bytes, e não há segredo hardcoded no código.
- [x] Recusa com `action` igual a `decline` conclui sem reservar e sem `isError`.

### Agente como host MCP

- [x] O log do servidor MCP mostra um `tools/list` antes do primeiro `tools/call` do agente.
- [x] O log do servidor MCP mostra o `traceparent` com o mesmo trace-id enviado pelo validador no header da chamada A2A.
- [x] Os requests do agente declaram a capability de elicitation em form mode.

### Agente como servidor A2A

- [x] `GET /.well-known/agent-card.json` responde 200 com um card v1.0 válido.
- [x] O card declara a interface JSON-RPC com a URL do endpoint e a versão de protocolo 1.0, e uma skill de id `reservar-sala`.
- [x] `SendMessage` com sala livre termina a Task em `TASK_STATE_COMPLETED` com o artifact `reserva`.
- [x] O artifact traz a reserva criada e o campo `politica` com o valor lido do resource.
- [x] `GetTask` devolve `id`, `contextId`, estado corrente e o artifact quando existir.
- [x] `SendMessage` referenciando Task em estado terminal é recusado com erro.
- [x] `SendMessage` pedindo uma sala inexistente termina a Task em `TASK_STATE_FAILED`, com a mensagem exata da tool visível no histórico.

### A ponte

- [x] `SendMessage` pedindo sala ocupada deixa a Task em `TASK_STATE_INPUT_REQUIRED` com a linha `alternativas:` listando os ids na ordem do `enum`.
- [x] A continuação com `escolha=<id>` conclui a Task em `TASK_STATE_COMPLETED` com a reserva na sala escolhida.
- [x] A continuação com `escolha=recusar` termina a Task em `TASK_STATE_CANCELED`.
- [x] Escolha fora do `enum` mantém a Task em `TASK_STATE_INPUT_REQUIRED`.
- [x] Duas Tasks pausadas ao mesmo tempo concluem cada uma com a sua reserva, sem trocar de `requestState`.
- [x] O `requestState` não aparece em nenhuma resposta A2A.

### Validação e entrega

- [x] `python3 validador/validar.py` passa nas 36 verificações, com os dois processos recém-iniciados, e termina com código de saída 0.
- [x] `dados/`, `validador/` e `exemplos/` não foram alterados.
- [x] O agente é determinístico: o mesmo pedido, enviado duas vezes, produz o mesmo resultado, e não há dependência de SDK de provedor de LLM no `pyproject.toml`.
- [x] O README tem as quatro seções exigidas, e os comandos funcionam a partir de um clone limpo.

## Entregas

Commits suspensos até o review. Cada bloco abaixo é uma entrega já construída na árvore.

1. Controle, regra `.cursor/rules/desafio-a-ponte.mdc` e `.env.example`.
2. Transporte Streamable HTTP, `listar_salas`, resource, stderr e `_meta` obrigatório.
3. `consultar_disponibilidade` e as mensagens de política.
4. `reservar_sala` no caminho livre.
5. `input_required`, enum, sem alternativa, `-32021` e chave de ambiente.
6. Retry accept/decline, token adulterado, argumentos selados, retry após restart.
7. Cliente MCP cru e `python -m agente.ciclo`.
8. Agent Card, `SendMessage`, `GetTask`, artifact, `FAILED` e `traceparent`.
9. Ponte: pausa, escolha, recusa, escolha inválida e duas Tasks.
10. README com a saída do validador.

## Verificação

Validador em processos recém-iniciados: 36 PASS, código de saída 0. A saída integral está no README. Trace-id dessa execução: `799653e98c9770a2154c40d6c923164b`. Ele aparece no stderr do MCP em `tools/call` do agente, com span-id novo a cada request (`4293bb5e1ee1875e`, `d7ef25bc14b124b2`, `6dc29ba6448a773f`, `1d6d22761906b7da`).

O log do MCP abre com `tools/list` id `1` e `resources/read` id `2`, da subida do agente, antes de qualquer `tools/call` dele. Os ids de retry da ponte são distintos do `tools/call` inicial.

Retry depois de matar e subir de novo o servidor MCP, com o mesmo `REQUEST_STATE_SECRET`: o `input_required` de `sala-garagem` 14:00–15:00, retomado com `sala-fusca`, concluiu `res-0003` com `resultType` `complete`. O valor do segredo não foi gravado no repositório.

`dados/`, `validador/` e `exemplos/` não foram alterados. Os `pyproject.toml` dependem só de `mcp==2.3.0`.

No Windows, a mesma subida usa `.\.venv\Scripts\python.exe` no lugar de `python3`, com o virtualenv já ativo no terminal. O README fica no formato que o avaliador executa (`python3` e `source`).

## Desvios

Nenhum. O SDK sela o `requestState` e rejeita argumento divergente com `-32602`. Não foi preciso reescrever o protocolo.

## Commits

Aguardando review. Nada foi commitado.
