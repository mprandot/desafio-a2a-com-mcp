# A Ponte: um agente A2A com MCP por dentro

A Hill Valley Tech reserva salas por dois processos. O servidor MCP, na porta 7301, conhece as salas, a política e o conflito. O agente, na porta 7300, descobre essas tools por HTTP e se oferece ao resto da empresa como servidor A2A. Quando a sala está ocupada, o MCP devolve `input_required` e um `requestState`. O agente pausa a Task, guarda o token e só volta ao MCP quando o cliente A2A escolhe.

## Como rodar

A partir de um clone limpo, na raiz do repositório. Python 3.10 ou superior. Os dois processos sobem em terminais separados. O validador só vale com os dois recém-iniciados: reserva criada numa execução muda a seguinte.

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e servidor-mcp -e agente

export REQUEST_STATE_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
python3 -m servidor_mcp
```

Noutro terminal, com o mesmo virtualenv ativo:

```bash
source .venv/bin/activate
python3 -m agente
```

O servidor MCP escuta em `http://127.0.0.1:7301/mcp`. O agente escuta em `http://127.0.0.1:7300`, com o card em `/.well-known/agent-card.json` e o JSON-RPC em `/a2a`. O agente não usa `REQUEST_STATE_SECRET`.

```bash
python3 validador/validar.py --agente http://localhost:7300 --mcp http://localhost:7301
```

Portas e URLs opcionais: `MCP_HOST`, `MCP_PORT`, `AGENTE_HOST`, `AGENTE_PORT`, `AGENTE_PUBLIC_URL`, `MCP_URL`. Os padrões são os que o validador usa.

O segredo acima tem 32 bytes. Não coloque o valor no repositório. Cada terminal do servidor MCP que for reiniciado no meio de um `input_required` precisa da mesma variável, senão o retry não verifica o token.

## Onde a ponte acontece

Em `agente/agente/tarefas.py`, `pausar` recebe o `InputRequiredResult` do MCP e coloca a Task em `TASK_STATE_INPUT_REQUIRED`, com a linha `alternativas:` na ordem do `enum`. O `requestState` fica no objeto da Task e não entra na resposta A2A. Em `retomar`, o `SendMessage` com `escolha=` repete o `tools/call` original: id JSON-RPC novo, os mesmos argumentos, `inputResponses` na chave que veio em `inputRequests` e o `requestState` ecoado sem abertura.

## Decisões técnicas

O `requestState` é selado pelo SDK `mcp` 2.3.0 com AES-256-GCM (`RequestStateSecurity`). O TTL é 600 segundos, dez minutos, dentro da faixa de 5 a 30. A chave é `REQUEST_STATE_SECRET`, lida na subida e recusada se tiver menos de 32 bytes. Não há segredo no código. O servidor não guarda o pedido entre o `input_required` e o retry: o que precisa para reconstruir a reserva viaja no token. Um retry com argumentos diferentes dos que foram selados é rejeitado pelo digest que o SDK amarra ao token, com `-32602`, e esses argumentos não viram reserva.

As reservas ficam numa lista em memória, carregada de `dados/reservas.json` na subida. Morrem com o processo. As Tasks também ficam em memória, uma para cada id, e o token de cada pausa fica nessa Task. O agente não calcula sala livre, política nem alternativa.

## Saída do validador

Processos recém-iniciados. Código de saída 0.

```
trace-id desta execucao: 799653e98c9770a2154c40d6c923164b
procure esse valor no stderr do servidor MCP para conferir a propagacao do traceparent.

PASS 01 tools/list traz as tres tools
PASS 02 toda tool tem inputSchema de objeto
PASS 03 listar_salas devolve structuredContent e o mesmo JSON em texto
PASS 04 _meta sem protocolVersion devolve -32602 e HTTP 400
PASS 05 _meta sem clientCapabilities devolve -32602 e HTTP 400
PASS 06 tool inexistente e recusada, por -32602 ou por isError
PASS 07 resources/read de politica://uso devolve a politica
PASS 08 resources/read de URI inexistente devolve -32602
PASS 09 sala inexistente devolve isError com a mensagem exata
PASS 10 fora da janela devolve isError com a mensagem exata
PASS 11 duracao acima de 2h devolve isError com a mensagem exata
PASS 12 intervalo invertido devolve isError com a mensagem exata
PASS 13 conflito devolve input_required com inputRequests e requestState
PASS 14 a elicitation e form mode e oferece as alternativas na ordem certa
PASS 15 conflito sem a capability elicitation devolve -32021 e HTTP 400
PASS 16 retry com inputResponses e requestState conclui a reserva
PASS 17 requestState adulterado e rejeitado com -32602
PASS 18 argumentos adulterados no retry nao tomam efeito
PASS 19 recusa conclui sem reservar e sem isError
PASS 20 conflito sem alternativa possivel devolve isError com a mensagem exata

PASS 21 agent card responde 200 no well-known com JSON
PASS 22 o card declara a interface JSON-RPC com url e versao 1.0
PASS 23 o card declara a skill reservar-sala
PASS 24 SendMessage com sala livre conclui a Task
PASS 25 o artifact chama reserva e traz a versao da politica
PASS 26 GetTask devolve id, contextId e estado corrente
PASS 27 SendMessage com sala ocupada pausa a Task
PASS 28 a Task pausada lista as alternativas na ordem certa
PASS 29 escolha fora do enum mantem a Task pausada
PASS 30 a continuacao conclui a Task na sala escolhida
PASS 31 SendMessage em Task terminal e recusado
PASS 32 a recusa termina a Task em CANCELED
PASS 33 duas Tasks pausadas ao mesmo tempo concluem cada uma com a sua reserva
PASS 34 nenhuma resposta A2A carrega o requestState
PASS 35 sala inexistente termina a Task em FAILED com a mensagem da tool
PASS 36 o agente e deterministico: o mesmo pedido produz a mesma pausa

resumo: 36 passaram, 0 falharam, de 36 verificacoes
```
