"""
ETAPA 10 -- Observabilidade (15 min): onde o tempo foi gasto e quanto custou, por nó do grafo.

ESQUELETO:
  ETAPA 10.2 -- medido(): embrulha um nó, mede o tempo e grava uma linha em saidas/metricas.jsonl
  (PRONTO)   -- resumo(): nós percorridos, tempo total, nó mais lento e tokens totais de uma execução
  (ETAPA 10.1 fica em etapa10_governanca.py: o hook do 🆕 B ganha um segundo papel, registrar)

Até você fazer a 10.2, medido() devolve o nó sem mudar nada: o grafo funciona igual.

REFERÊNCIAS NAS AULAS
  aula5/exemplos/11_observabilidade/agente_observavel.py        ler o que aconteceu numa execução (result.new_items)
  aula3/agente_hook2.py, aula3/agente_hook3.py                  RunHooks para enxergar o loop do agente
  aula8/exemplos/03_observabilidade/1_codigo_pronto/passo1_trace.py   trace e spans (o Langfuse do passo 2 é opcional)

Rodar:
    python etapa10_observabilidade.py <thread_id>     # imprime o resumo de uma execução já feita
"""
import functools
import json
import sys
import time
from pathlib import Path

from dados_rh import SAIDAS

ARQUIVO_METRICAS = SAIDAS / "metricas.jsonl"


def medido(nome: str, no):
    # ETAPA 10.2 -- wrapper de medição de tempo e telemetria
    @functools.wraps(no)
    def wrapper(estado: dict) -> dict:
        t0 = time.perf_counter()
        resultado = no(estado)
        duracao = round(time.perf_counter() - t0, 4)

        thread_id = estado.get("thread_id", "")
        registro = {
            "thread_id": thread_id,
            "no": nome,
            "segundos": duracao,
        }

        if isinstance(resultado, dict):
            if "tokens" in resultado:
                registro["tokens"] = resultado["tokens"]
            if "fonte_feriados" in resultado:
                registro["fonte_feriados"] = resultado["fonte_feriados"]

        ARQUIVO_METRICAS.parent.mkdir(parents=True, exist_ok=True)
        with open(ARQUIVO_METRICAS, "a", encoding="utf-8") as f:
            f.write(json.dumps(registro, ensure_ascii=False) + "\n")

        return resultado

    return wrapper


def resumo(thread_id: str) -> dict:
    """Junta as linhas de ARQUIVO_METRICAS de uma execução."""
    if not ARQUIVO_METRICAS.exists():
        return {"erro": "saidas/metricas.jsonl ainda não existe: faça a ETAPA 10.2 e rode o grafo"}
    
    linhas = []
    for l in ARQUIVO_METRICAS.read_text(encoding="utf-8").splitlines():
        texto = l.strip()
        if not texto:
            continue
        try:
            linhas.append(json.loads(texto))
        except json.JSONDecodeError:
            continue

    linhas = [l for l in linhas if l.get("thread_id") == thread_id]
    if not linhas:
        return {"erro": f"nenhuma métrica com thread_id={thread_id!r}"}
    lento = max(linhas, key=lambda l: l.get("segundos", 0))
    return {
        "nos": [l.get("no") for l in linhas],
        "segundos_total": round(sum(l.get("segundos", 0) for l in linhas), 2),
        "mais_lento": (lento.get("no"), lento.get("segundos")),
        "tokens_total": sum(l.get("tokens", 0) or 0 for l in linhas),
    }


if __name__ == "__main__":
    if len(sys.argv) > 1:
        print(json.dumps(resumo(sys.argv[1]), ensure_ascii=False, indent=2))