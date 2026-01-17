# Importação de módulos padrão do Python para manipulação de argumentos CLI
import argparse
# Módulo para trabalhar com dados em formato JSON
import json
# Módulo para operações do sistema operacional (arquivos, diretórios, variáveis de ambiente)
import os
# Módulo para trabalhar com expressões regulares (pattern matching em strings)
import re
# Módulo para funções do sistema (ex: sys.exit(), sys.stderr)
import sys
# Módulo para operações com tempo (sleep, timestamps)
import time
# Importa 'deque' - uma fila de dupla extremidade eficiente para operações de append/pop
from collections import deque
# Importa funções para trabalhar com datas e fusos horários
from datetime import datetime, timezone
# Importa dicas de tipo para melhor documentação do código
from typing import Deque, Dict, Optional, Tuple

# Importa cliente da API OpenAI para chamar modelos de IA
from openai import OpenAI

# Define o diretório padrão para armazenar logs do agente
LOG_DIR = "/var/log/zbx_lab"
# Construir o caminho completo do arquivo de log do agente
AGENT_LOG = f"{LOG_DIR}/agent.log"
# Caminho padrão do arquivo de log da aplicação que será monitorado
DEFAULT_LOG_FILE = "/var/log/myapp/app.log"

# Expressão regular para fazer parse das linhas de log
# Captura: timestamp (ts), nível de log (INFO|WARN|ERROR), e mensagem (msg)
LOG_PATTERN = re.compile(r"^(?P<ts>\S+)\s+(?P<level>INFO|WARN|ERROR)\s+(?P<msg>.+)$")


# Função que define e retorna os argumentos de linha de comando aceitos pelo agente
def parse_args() -> argparse.Namespace:
    # Cria um parser para argumentos de CLI com descrição do programa
    parser = argparse.ArgumentParser(
        description=(
            "Agente simples de monitoramento que acompanha logs e sinaliza padrões "
            "de pré-falha (WARN) e falhas (ERROR). Integra direto com OpenAI."
        )
    )
    # Argumento opcional: caminho do arquivo de log a ser monitorado (padrão: DEFAULT_LOG_FILE)
    parser.add_argument("--log-file", default=DEFAULT_LOG_FILE, help="Caminho do log monitorado")
    # Flag: se presente, começa a leitura desde o início do arquivo (senão começa do final)
    parser.add_argument("--from-start", action="store_true", help="Inicia leitura desde o começo")
    # Argumento opcional: número máximo de mensagens WARN permitidas por minuto antes de alertar
    parser.add_argument("--warn-per-min", type=int, default=10, help="Limite de WARN por minuto")
    # Argumento opcional: número máximo de mensagens ERROR permitidas por minuto antes de alertar
    parser.add_argument("--error-per-min", type=int, default=3, help="Limite de ERROR por minuto")
    # Argumento opcional: janela de tempo (em segundos) para detectar padrão WARN seguido de ERROR
    parser.add_argument("--warn-to-error-window", type=int, default=120, help="Janela em segundos para WARN->ERROR")
    # Argumento opcional: intervalo em segundos entre verificações/leituras do arquivo de log
    parser.add_argument("--poll-interval", type=float, default=1.0, help="Intervalo de polling em segundos")

    # Argumento opcional: qual modelo OpenAI usar (padrão: gpt-4.1-mini)
    parser.add_argument("--openai-model", default="gpt-4.1-mini", help="Modelo OpenAI (default: gpt-4.1-mini)")
    # Argumento opcional: tempo máximo (segundos) para aguardar resposta da OpenAI
    parser.add_argument("--openai-timeout", type=float, default=10.0, help="Timeout OpenAI em segundos")
    # Argumento opcional: temperatura do modelo (controla aleatoriedade: 0.2 = mais determinístico)
    parser.add_argument("--openai-temperature", type=float, default=0.2, help="Temperature (default: 0.2)")
    # Argumento opcional: número máximo de tokens (palavras) que a OpenAI pode gerar na resposta
    parser.add_argument("--openai-max-tokens", type=int, default=350, help="Max tokens de resposta (default: 350)")

    # Argumento opcional: tempo mínimo em segundos entre chamadas à OpenAI do mesmo tipo de evento
    # Evita sobrecarregar a API chamando múltiplas vezes para eventos semelhantes
    parser.add_argument(
        "--cooldown-seconds",
        type=float,
        default=30.0,
        help="Cooldown mínimo entre chamadas OpenAI por tipo de evento (default: 30s)",
    )
    # Argumento opcional: quantas linhas recentes de log enviar como contexto para a OpenAI
    parser.add_argument(
        "--context-lines",
        type=int,
        default=60,
        help="Qtd de linhas recentes de log enviadas como contexto (default: 60)",
    )

    # Faz o parse dos argumentos reais passados na linha de comando e retorna o objeto
    return parser.parse_args()



# Função que garante que o diretório de logs do agente existe e está acessível
def ensure_agent_log() -> None:
    # Cria o diretório LOG_DIR se não existir (exist_ok=True evita erro se já existir)
    os.makedirs(LOG_DIR, exist_ok=True)
    # Se o arquivo de log do agente não existe, cria um arquivo vazio
    if not os.path.exists(AGENT_LOG):
        # Abre em modo append e fecha imediatamente, apenas para criar o arquivo
        with open(AGENT_LOG, "a", encoding="utf-8"):
            pass


# Função que escreve mensagens de log com timestamp no arquivo de log do agente
def log_agent(message: str) -> None:
    # Garante que o arquivo de log existe antes de tentar escrever
    ensure_agent_log()
    # Obtém a data/hora atual em ISO 8601 (fuso horário local) sem microssegundos
    ts = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    # Monta a linha de log com timestamp + mensagem
    line = f"{ts} {message}"
    # Imprime a mensagem no console (stdout)
    print(line)
    # Abre arquivo de log em modo append (adiciona ao final) e escreve a linha
    with open(AGENT_LOG, "a", encoding="utf-8") as handle:
        handle.write(line + "\n")


# Função que extrai timestamp, nível de log e mensagem de uma linha de log
def parse_line(line: str) -> Optional[Tuple[str, str, str]]:
    # Tenta fazer match da linha com a expressão regular LOG_PATTERN
    match = LOG_PATTERN.match(line)
    # Se não fizer match (linha não segue o padrão), retorna None
    if not match:
        return None
    # Se faz match, retorna uma tupla com (timestamp, level, message)
    return match.group("ts"), match.group("level"), match.group("msg")


# Função que remove elementos antigos de uma deque (fila) com base em um timestamp de corte
def cleanup_old(entries: Deque[float], cutoff: float) -> None:
    # Enquanto houver elementos na deque E o primeiro elemento for menor que o cutoff
    # (ou seja, for mais antigo que cutoff), remove o elemento do início
    while entries and entries[0] < cutoff:
        entries.popleft()



# Função que chama a API OpenAI para analisar um evento detectado nos logs
def openai_analyze(
    client: OpenAI,  # Cliente OpenAI já inicializado
    args: argparse.Namespace,  # Argumentos de configuração do agente
    event_label: str,  # Rótulo do tipo de evento (ex: "incident_high_error_rate")
    payload: Dict[str, object],  # Dados do evento a ser analisado
    context_lines: Deque[str],  # Últimas linhas de log como contexto
) -> Optional[str]:  # Retorna a análise da OpenAI ou None se não disponível
    # Obtém a chave de API OpenAI da variável de ambiente, ou string vazia se não existir
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    # Se não houver chave de API configurada, avisa e retorna None (OpenAI desabilitado)
    if not api_key:
        log_agent("openai disabled: OPENAI_API_KEY not set")
        return None

    # Define o prompt de sistema que instruí o modelo como se comportar
    system_prompt = (
        "Você é um engenheiro SRE/AIOps. Receberá um evento de logs e um contexto recente. "
        "Responda em PT-BR, objetivo e prático, com:\n"
        "1) provável causa raiz (hipóteses ordenadas)\n"
        "2) checks imediatos (comandos Linux curtos)\n"
        "3) mitigação rápida\n"
        "4) prevenção\n"
        "Se faltar info, diga qual info faltou e quais logs/metricas coletar."
    )

    # Monta o conteúdo da mensagem do usuário como um dicionário estruturado
    user_content = {
        "event_label": event_label,  # Tipo de evento
        "event": payload,  # Dados do evento
        "recent_log_context": list(context_lines),  # Últimas linhas de log
    }

    # Tenta fazer a chamada à API OpenAI
    try:
        # Envia a requisição ao modelo OpenAI com as configurações especificadas
        resp = client.chat.completions.create(
            model=args.openai_model,  # Qual modelo usar
            messages=[
                {"role": "system", "content": system_prompt},  # Instrução do sistema
                {"role": "user", "content": json.dumps(user_content, ensure_ascii=False)},  # Conteúdo do usuário em JSON
            ],
            temperature=args.openai_temperature,  # Controla criatividade (0.2 = mais determinístico)
            max_tokens=args.openai_max_tokens,  # Tamanho máximo da resposta
        )
        # Extrai o texto da resposta (remove espaços em branco extras)
        msg = (resp.choices[0].message.content or "").strip()
        # Retorna a mensagem se não vazia, senão retorna None
        return msg or None
    # Se houver qualquer erro na API
    except Exception as exc:
        # Registra o erro no log do agente
        log_agent(f"openai error ({event_label}): {exc}")
        # Retorna None indicando que não houve análise
        return None


# Função que verifica se é permitido fazer uma chamada à OpenAI (baseado em cooldown)
def should_call_openai(last_call: Dict[str, float], key: str, cooldown: float) -> bool:
    # Obtém o tempo atual em Unix timestamp (segundos desde 1970)
    now = time.time()
    # Obtém o timestamp da última chamada deste tipo de evento (ou None se não houver)
    prev = last_call.get(key)
    # Se nunca foi chamado OU tempo desde última chamada >= cooldown, é permitido chamar
    if prev is None or (now - prev) >= cooldown:
        # Registra o tempo da nova chamada
        last_call[key] = now
        # Retorna True indicando que é permitido chamar
        return True
    # Caso contrário, o cooldown ainda não expirou, então não é permitido
    return False



# Função principal que monitora o arquivo de log continuamente
def monitor_log(args: argparse.Namespace) -> None:
    # Deque que armazena os timestamps dos eventos WARN ocorridos no último minuto
    warn_times: Deque[float] = deque()
    # Deque que armazena os timestamps dos eventos ERROR ocorridos no último minuto
    error_times: Deque[float] = deque()
    # Armazena o timestamp do último evento WARN detectado (usado para padrão WARN->ERROR)
    last_warn_ts: Optional[float] = None

    # Deque com tamanho máximo que armazena as últimas linhas de log como contexto
    # Usa max(10, ...) para garantir um mínimo de 10 linhas de contexto
    recent_lines: Deque[str] = deque(maxlen=max(10, int(args.context_lines)))
    # Dicionário que armazena o timestamp da última chamada à OpenAI para cada tipo de evento
    # Usado para implementar o sistema de cooldown
    last_openai_call: Dict[str, float] = {}

    # Inicializa o cliente OpenAI com timeout configurado
    client = OpenAI(timeout=args.openai_timeout)

    # Registra no log do agente que ele foi iniciado e com quais configurações
    log_agent(f"agent started log_file={args.log_file} model={args.openai_model}")

    # Abre o arquivo de log do aplicativo para leitura
    with open(args.log_file, "r", encoding="utf-8") as handle:
        # Se não usar a flag --from-start, move o cursor até o final do arquivo
        # Isso faz o agente monitorar apenas novas linhas adicionadas ao log
        if not args.from_start:
            handle.seek(0, os.SEEK_END)

        # Loop infinito que continuamente monitora o arquivo de log
        while True:
            # Guarda a posição atual do cursor no arquivo
            position = handle.tell()
            # Tenta ler a próxima linha do arquivo
            line = handle.readline()
            # Se não há nova linha (arquivo não mudou)
            if not line:
                # Aguarda antes de verificar novamente (evita usar 100% de CPU)
                time.sleep(args.poll_interval)
                # Volta o cursor para a posição anterior
                handle.seek(position)
                # Volta ao topo do loop para verificar novamente
                continue

            # Remove espaços em branco do início e final da linha (newline, tabs, etc)
            raw = line.strip()
            # Adiciona a linha aos logs recentes (deque removerá automaticamente a mais antiga se cheia)
            recent_lines.append(raw)

            # Tenta fazer parse da linha usando a expressão regular
            parsed = parse_line(raw)
            # Se a linha não segue o padrão esperado, ignora e continua
            if not parsed:
                continue

            # Desempacota os valores extraídos da linha
            ts, level, msg = parsed
            # Obtém o tempo atual em Unix timestamp
            now = time.time()
            # Calcula o timestamp para remover eventos com mais de 60 segundos de idade
            cutoff_min = now - 60
            # Remove eventos WARN antigos da deque para manter apenas último minuto
            cleanup_old(warn_times, cutoff_min)
            # Remove eventos ERROR antigos da deque para manter apenas último minuto
            cleanup_old(error_times, cutoff_min)

            # Se a linha é um aviso (WARN)
            if level == "WARN":
                # Registra o timestamp deste WARN na deque
                warn_times.append(now)
                # Atualiza o timestamp do último WARN (para detecção de padrão WARN->ERROR)
                last_warn_ts = now
            # Se a linha é um erro (ERROR)
            elif level == "ERROR":
                # Registra o timestamp deste ERROR na deque
                error_times.append(now)

            # ALERTA PREDITIVO: Taxa alta de WARNs detectada
            # Se o número de WARNs no último minuto >= limite configurado
            if len(warn_times) >= args.warn_per_min:
                # Monta o payload com detalhes do evento para enviar à OpenAI
                payload = {
                    "event_type": "predictive",  # Tipo de evento (preditivo = pre-falha)
                    "reason": "high_warn_rate",  # Razão específica (taxa alta de WARNs)
                    "timestamp": ts,  # Timestamp da linha que trigger o alerta
                    "warn_per_min": len(warn_times),  # Número de WARNs detectados no último minuto
                    "threshold": args.warn_per_min,  # Limite configurado
                    "source": args.log_file,  # Arquivo de origem dos logs
                }
                # Registra o alerta preditivo no log do agente
                log_agent(f"predictive alert: high WARN rate ({len(warn_times)}/min)")
                # Verifica se é permitido chamar a OpenAI (respeitando cooldown para evitar chamadas excessivas)
                if should_call_openai(last_openai_call, "predictive_high_warn_rate", args.cooldown_seconds):
                    # Chama OpenAI para analisar o evento e sugerir ações preventivas
                    analysis = openai_analyze(client, args, "predictive_high_warn_rate", payload, recent_lines)
                    # Se houver resposta da OpenAI, registra no log do agente
                    if analysis:
                        log_agent(f"openai (predictive_high_warn_rate): {analysis}")

            # ALERTA DE INCIDENTE: Taxa alta de ERRORs detectada
            # Se o número de ERRORs no último minuto >= limite configurado
            if len(error_times) >= args.error_per_min:
                # Monta o payload com detalhes do evento para enviar à OpenAI
                payload = {
                    "event_type": "incident",  # Tipo de evento (incidente = falha)
                    "reason": "high_error_rate",  # Razão específica (taxa alta de ERRORs)
                    "timestamp": ts,  # Timestamp da linha que trigger o alerta
                    "error_per_min": len(error_times),  # Número de ERRORs detectados no último minuto
                    "threshold": args.error_per_min,  # Limite configurado
                    "source": args.log_file,  # Arquivo de origem dos logs
                }
                # Registra o alerta de incidente no log do agente
                log_agent(f"incident detected: high ERROR rate ({len(error_times)}/min)")
                # Verifica se é permitido chamar a OpenAI (respeitando cooldown)
                if should_call_openai(last_openai_call, "incident_high_error_rate", args.cooldown_seconds):
                    # Chama OpenAI para analisar o evento e sugerir ações de remediação
                    analysis = openai_analyze(client, args, "incident_high_error_rate", payload, recent_lines)
                    # Se houver resposta da OpenAI, registra no log do agente
                    if analysis:
                        log_agent(f"openai (incident_high_error_rate): {analysis}")

            # ALERTA PREDITIVO: Padrão WARN seguido de ERROR dentro de uma janela de tempo
            # Se a linha atual é ERROR E houve um WARN no passado recente
            if level == "ERROR" and last_warn_ts is not None:
                # Se o tempo entre WARN e ERROR é menor ou igual à janela configurada
                if (now - last_warn_ts) <= args.warn_to_error_window:
                    # Monta o payload com detalhes do padrão detectado
                    payload = {
                        "event_type": "predictive",  # Tipo de evento (preditivo = padrão de degradação)
                        "reason": "warn_to_error",  # Razão específica (padrão WARN->ERROR detectado)
                        "timestamp": ts,  # Timestamp do ERROR que completou o padrão
                        "window_seconds": args.warn_to_error_window,  # Janela de tempo considerada para o padrão
                        "source": args.log_file,  # Arquivo de origem dos logs
                    }
                    # Registra o alerta preditivo de padrão WARN->ERROR (indica degradação progressiva)
                    log_agent(f"predictive alert: WARN->ERROR pattern detected (window={args.warn_to_error_window}s)")
                    # Verifica se é permitido chamar a OpenAI (respeitando cooldown)
                    if should_call_openai(last_openai_call, "predictive_warn_to_error", args.cooldown_seconds):
                        # Chama OpenAI para analisar o padrão e sugerir ações preventivas
                        analysis = openai_analyze(client, args, "predictive_warn_to_error", payload, recent_lines)
                        # Se houver resposta da OpenAI, registra no log do agente
                        if analysis:
                            log_agent(f"openai (predictive_warn_to_error): {analysis}")

            # ALERTA DE INCIDENTE: Qualquer linha de ERROR (com proteção de cooldown)
            # Se a linha atual é um ERROR
            if level == "ERROR":
                # Monta o payload com todos os detalhes da linha de ERROR
                payload = {
                    "event_type": "incident",  # Tipo de evento (incidente = falha)
                    "reason": "error_line",  # Razão específica (qualquer linha ERROR é um incidente)
                    "timestamp": ts,  # Timestamp da linha de ERROR
                    "level": level,  # Nível de log (ERROR)
                    "message": msg,  # Mensagem extraída da linha (sem timestamp)
                    "raw": raw,  # Linha completa não processada
                    "source": args.log_file,  # Arquivo de origem dos logs
                }
                # Registra o alerta de incidente no log do agente
                log_agent(f"incident detected: {ts} {msg}")
                # Verifica se é permitido chamar a OpenAI (respeitando cooldown para evitar spam)
                if should_call_openai(last_openai_call, "incident_error_line", args.cooldown_seconds):
                    # Chama OpenAI para analisar o ERROR e sugerir ações de resolução
                    analysis = openai_analyze(client, args, "incident_error_line", payload, recent_lines)
                    # Se houver resposta da OpenAI, registra no log do agente
                    if analysis:
                        log_agent(f"openai (incident_error_line): {analysis}")



# Função principal que inicia o agente de monitoramento
def main() -> None:
    # Faz parse dos argumentos de linha de comando
    args = parse_args()
    # Se o arquivo de log a ser monitorado não existe
    if not os.path.exists(args.log_file):
        # Imprime mensagem de erro no stderr (saída de erro do sistema)
        print(f"Log file not found: {args.log_file}", file=sys.stderr)
        # Encerra o programa com código de erro 1 (indica falha na execução)
        sys.exit(1)
    # Se o arquivo existe, inicia o monitoramento contínuo do log
    monitor_log(args)


# Ponto de entrada do programa - garante que main() só é executado
# quando este arquivo é executado diretamente como script principal
# (não quando importado como módulo em outro arquivo Python)
if __name__ == "__main__":
    main()
