#!/usr/bin/env bash
set -euo pipefail

LOG_DIR="/var/log/zbx_lab"
LOG_FILE="$LOG_DIR/run.log"
STATE_FILE="$LOG_DIR/state.env"
MYAPP_LOG="/var/log/myapp/app.log"

DEFAULT_TIMEOUT=120
DEFAULT_LOG_CYCLES=30
DEFAULT_LOG_INTERVAL=2
DEFAULT_WARN_PCT=50
DEFAULT_ERROR_PCT=15

MODE=""
SERVICES=()
BLOCK_PORTS=()
ENABLE_CPU=false
ENABLE_MEM=false
ENABLE_DISK=false
ENABLE_NET=false
ENABLE_LOGS=false
NET_IFACE=""
DISK_FILE="/tmp/zbx_fill"
DISK_SIZE_MB=5000
CPU_WORKERS=4
MEM_WORKERS=2
MEM_BYTES="80%"
NET_DELAY="200ms"
NET_LOSS="5%"
LOG_CYCLES="$DEFAULT_LOG_CYCLES"
LOG_INTERVAL="$DEFAULT_LOG_INTERVAL"
WARN_PCT="$DEFAULT_WARN_PCT"
ERROR_PCT="$DEFAULT_ERROR_PCT"

usage() {
  cat <<'USAGE'
Uso:
  sudo ./zbx_incident_lab.sh apply [opções]
  sudo ./zbx_incident_lab.sh revert [opções]

Opções principais:
  --service <nome>        Para um serviço (systemd) e registra para reverter
  --block-port <porta>    Bloqueia porta TCP (iptables) e registra para reverter
  --cpu                   Gera carga de CPU com stress-ng
  --mem                   Gera pressão de memória com stress-ng
  --disk                  Preenche disco criando arquivo grande
  --net                   Degrada rede via tc netem (delay/loss)
  --logs                  Gera logs sintéticos em /var/log/myapp/app.log

Opções avançadas:
  --timeout <seg>         Timeout para stress-ng (padrão: 120)
  --iface <iface>         Interface de rede para tc (default: rota padrão)
  --disk-file <caminho>   Caminho do arquivo de preenchimento (default: /tmp/zbx_fill)
  --disk-size <mb>        Tamanho em MB do arquivo de preenchimento (default: 5000)
  --cpu-workers <n>       Quantidade de workers CPU (default: 4)
  --mem-workers <n>       Quantidade de workers VM (default: 2)
  --mem-bytes <pct>       Percentual/bytes para vm-bytes (default: 80%)
  --net-delay <tempo>     Delay do netem (default: 200ms)
  --net-loss <pct>        Loss do netem (default: 5%)
  --log-cycles <n>        Quantidade de ciclos de log (default: 30)
  --log-interval <s>      Intervalo entre ciclos (default: 2)
  --warn-pct <0-100>      Percentual de WARN (default: 50)
  --error-pct <0-100>     Percentual de ERROR (default: 15)

Exemplos:
  sudo ./zbx_incident_lab.sh apply --service nginx --block-port 80 --cpu --mem --disk --net
  sudo ./zbx_incident_lab.sh apply --logs --log-cycles 40 --log-interval 1
  sudo ./zbx_incident_lab.sh revert --service nginx --block-port 80 --net --disk
USAGE
}

log() {
  local msg="$1"
  local ts
  ts="$(date --iso-8601=seconds)"
  mkdir -p "$LOG_DIR"
  echo "$ts $msg" | tee -a "$LOG_FILE"
}

require_root() {
  if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    echo "Este script precisa ser executado como root (sudo)." >&2
    exit 1
  fi
}

save_state() {
  local key="$1"
  local value="$2"
  mkdir -p "$LOG_DIR"
  if [[ -f "$STATE_FILE" ]]; then
    sed -i "s|^${key}=.*$|${key}=${value}|" "$STATE_FILE" || true
    if ! grep -q "^${key}=" "$STATE_FILE"; then
      echo "${key}=${value}" >> "$STATE_FILE"
    fi
  else
    echo "${key}=${value}" > "$STATE_FILE"
  fi
}

load_state() {
  if [[ -f "$STATE_FILE" ]]; then
    # shellcheck disable=SC1090
    source "$STATE_FILE"
  fi
}

cleanup_apply() {
  log "Iniciando cleanup automático (apply)."
  if [[ -n "${STOPPED_SERVICES:-}" ]]; then
    for svc in ${STOPPED_SERVICES}; do
      log "Reiniciando serviço: $svc"
      systemctl start "$svc" || true
    done
  fi
  if [[ -n "${BLOCKED_PORTS:-}" ]]; then
    for port in ${BLOCKED_PORTS}; do
      log "Removendo bloqueio de porta: $port"
      if iptables -C INPUT -p tcp --dport "$port" -j DROP 2>/dev/null; then
        iptables -D INPUT -p tcp --dport "$port" -j DROP || true
      fi
    done
  fi
  if [[ -n "${NETEM_IFACE:-}" ]]; then
    log "Removendo netem da interface: $NETEM_IFACE"
    tc qdisc del dev "$NETEM_IFACE" root netem || true
  fi
  if [[ -n "${DISK_FILL_FILE:-}" && -f "$DISK_FILL_FILE" ]]; then
    log "Removendo arquivo de preenchimento: $DISK_FILL_FILE"
    rm -f "$DISK_FILL_FILE" || true
  fi
}

get_default_iface() {
  ip route get 1.1.1.1 2>/dev/null | awk '{for (i=1;i<=NF;i++) if ($i=="dev") {print $(i+1); exit}}'
}

ensure_stress_ng() {
  if ! command -v stress-ng >/dev/null 2>&1; then
    log "stress-ng não encontrado. Instale com: sudo apt install -y stress-ng"
    exit 1
  fi
}

apply_service() {
  local svc="$1"
  if ! systemctl list-unit-files | awk '{print $1}' | grep -q "^${svc}\.service$"; then
    log "Serviço não encontrado: $svc"
    exit 1
  fi
  log "Parando serviço: $svc"
  systemctl stop "$svc"
  STOPPED_SERVICES+="$svc "
}

apply_block_port() {
  local port="$1"
  if ! [[ "$port" =~ ^[0-9]+$ ]]; then
    log "Porta inválida: $port"
    exit 1
  fi
  log "Bloqueando porta TCP: $port"
  if ! iptables -C INPUT -p tcp --dport "$port" -j DROP 2>/dev/null; then
    iptables -I INPUT -p tcp --dport "$port" -j DROP
  fi
  BLOCKED_PORTS+="$port "
}

apply_cpu() {
  ensure_stress_ng
  log "Gerando carga de CPU (${CPU_WORKERS} workers por ${TIMEOUT}s)"
  stress-ng --cpu "$CPU_WORKERS" --timeout "${TIMEOUT}s" --metrics-brief
}

apply_mem() {
  ensure_stress_ng
  log "Gerando pressão de memória (${MEM_WORKERS} workers, vm-bytes ${MEM_BYTES} por ${TIMEOUT}s)"
  stress-ng --vm "$MEM_WORKERS" --vm-bytes "$MEM_BYTES" --timeout "${TIMEOUT}s" --metrics-brief
}

apply_disk() {
  log "Preenchendo disco com arquivo ${DISK_FILE} (${DISK_SIZE_MB} MB)"
  dd if=/dev/zero of="$DISK_FILE" bs=1M count="$DISK_SIZE_MB" status=progress
  DISK_FILL_FILE="$DISK_FILE"
}

apply_net() {
  local iface="$NET_IFACE"
  if [[ -z "$iface" ]]; then
    iface="$(get_default_iface)"
  fi
  if [[ -z "$iface" ]]; then
    log "Não foi possível detectar interface de rede. Use --iface."
    exit 1
  fi
  log "Aplicando netem em $iface (delay ${NET_DELAY}, loss ${NET_LOSS})"
  tc qdisc add dev "$iface" root netem delay "$NET_DELAY" loss "$NET_LOSS"
  NETEM_IFACE="$iface"
}

random_level() {
  local roll
  roll=$((RANDOM % 100))
  if (( roll < ERROR_PCT )); then
    echo "ERROR"
  elif (( roll < ERROR_PCT + WARN_PCT )); then
    echo "WARN"
  else
    echo "INFO"
  fi
}

write_log_line() {
  local level="$1"
  local message="$2"
  local ts
  ts="$(date --iso-8601=seconds)"
  echo "$ts $level $message" >> "$MYAPP_LOG"
}

apply_logs() {
  log "Gerando logs sintéticos em $MYAPP_LOG"
  mkdir -p "$(dirname "$MYAPP_LOG")"
  touch "$MYAPP_LOG"
  for ((i=1; i<=LOG_CYCLES; i++)); do
    local level
    level="$(random_level)"
    case "$level" in
      INFO)
        write_log_line "$level" "normal operation request_id=${i}"
        ;;
      WARN)
        if (( i < LOG_CYCLES / 2 )); then
          write_log_line "$level" "retrying connection host=db01 attempt=$((i % 5 + 1))"
        else
          write_log_line "$level" "timeout increasing host=db01 latency_ms=$((100 + i * 5))"
        fi
        ;;
      ERROR)
        if (( i < LOG_CYCLES - 3 )); then
          write_log_line "$level" "connection refused host=db01"
        else
          write_log_line "$level" "db timeout host=db01"
        fi
        ;;
    esac
    sleep "$LOG_INTERVAL"
  done
  write_log_line "ERROR" "incident: database unavailable host=db01"
  log "Logs sintéticos finalizados"
}

revert_service() {
  local svc="$1"
  log "Reiniciando serviço: $svc"
  systemctl start "$svc" || true
}

revert_block_port() {
  local port="$1"
  log "Removendo bloqueio de porta: $port"
  if iptables -C INPUT -p tcp --dport "$port" -j DROP 2>/dev/null; then
    iptables -D INPUT -p tcp --dport "$port" -j DROP || true
  fi
}

revert_net() {
  local iface="$1"
  if [[ -z "$iface" ]]; then
    iface="$(get_default_iface)"
  fi
  if [[ -z "$iface" ]]; then
    log "Interface não detectada para remover netem. Use --iface."
    exit 1
  fi
  log "Removendo netem da interface: $iface"
  tc qdisc del dev "$iface" root netem || true
}

revert_disk() {
  if [[ -f "$DISK_FILE" ]]; then
    log "Removendo arquivo de preenchimento: $DISK_FILE"
    rm -f "$DISK_FILE"
  fi
}

parse_args() {
  if [[ $# -lt 1 ]]; then
    usage
    exit 1
  fi

  MODE="$1"
  shift

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --service)
        SERVICES+=("$2")
        shift 2
        ;;
      --block-port)
        BLOCK_PORTS+=("$2")
        shift 2
        ;;
      --cpu)
        ENABLE_CPU=true
        shift
        ;;
      --mem)
        ENABLE_MEM=true
        shift
        ;;
      --disk)
        ENABLE_DISK=true
        shift
        ;;
      --net)
        ENABLE_NET=true
        shift
        ;;
      --logs)
        ENABLE_LOGS=true
        shift
        ;;
      --timeout)
        TIMEOUT="$2"
        shift 2
        ;;
      --iface)
        NET_IFACE="$2"
        shift 2
        ;;
      --disk-file)
        DISK_FILE="$2"
        shift 2
        ;;
      --disk-size)
        DISK_SIZE_MB="$2"
        shift 2
        ;;
      --cpu-workers)
        CPU_WORKERS="$2"
        shift 2
        ;;
      --mem-workers)
        MEM_WORKERS="$2"
        shift 2
        ;;
      --mem-bytes)
        MEM_BYTES="$2"
        shift 2
        ;;
      --net-delay)
        NET_DELAY="$2"
        shift 2
        ;;
      --net-loss)
        NET_LOSS="$2"
        shift 2
        ;;
      --log-cycles)
        LOG_CYCLES="$2"
        shift 2
        ;;
      --log-interval)
        LOG_INTERVAL="$2"
        shift 2
        ;;
      --warn-pct)
        WARN_PCT="$2"
        shift 2
        ;;
      --error-pct)
        ERROR_PCT="$2"
        shift 2
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        echo "Opção desconhecida: $1" >&2
        usage
        exit 1
        ;;
    esac
  done
}

main() {
  require_root
  TIMEOUT="$DEFAULT_TIMEOUT"
  parse_args "$@"

  case "$MODE" in
    apply)
      log "Modo apply iniciado"
      trap cleanup_apply EXIT

      STOPPED_SERVICES=""
      BLOCKED_PORTS=""
      NETEM_IFACE=""
      DISK_FILL_FILE=""

      for svc in "${SERVICES[@]}"; do
        apply_service "$svc"
      done
      for port in "${BLOCK_PORTS[@]}"; do
        apply_block_port "$port"
      done
      if [[ "$ENABLE_CPU" == true ]]; then
        apply_cpu
      fi
      if [[ "$ENABLE_MEM" == true ]]; then
        apply_mem
      fi
      if [[ "$ENABLE_DISK" == true ]]; then
        apply_disk
      fi
      if [[ "$ENABLE_NET" == true ]]; then
        apply_net
      fi
      if [[ "$ENABLE_LOGS" == true ]]; then
        apply_logs
      fi

      save_state "STOPPED_SERVICES" "$STOPPED_SERVICES"
      save_state "BLOCKED_PORTS" "$BLOCKED_PORTS"
      save_state "NETEM_IFACE" "$NETEM_IFACE"
      save_state "DISK_FILL_FILE" "$DISK_FILL_FILE"

      log "Modo apply concluído"
      ;;
    revert)
      log "Modo revert iniciado"
      load_state

      for svc in "${SERVICES[@]}"; do
        revert_service "$svc"
      done
      for port in "${BLOCK_PORTS[@]}"; do
        revert_block_port "$port"
      done
      if [[ "$ENABLE_NET" == true ]]; then
        revert_net "$NET_IFACE"
      fi
      if [[ "$ENABLE_DISK" == true ]]; then
        revert_disk
      fi

      if [[ -n "${STOPPED_SERVICES:-}" ]]; then
        for svc in ${STOPPED_SERVICES}; do
          revert_service "$svc"
        done
      fi
      if [[ -n "${BLOCKED_PORTS:-}" ]]; then
        for port in ${BLOCKED_PORTS}; do
          revert_block_port "$port"
        done
      fi
      if [[ -n "${NETEM_IFACE:-}" ]]; then
        revert_net "$NETEM_IFACE"
      fi
      if [[ -n "${DISK_FILL_FILE:-}" ]]; then
        DISK_FILE="$DISK_FILL_FILE"
        revert_disk
      fi

      log "Modo revert concluído"
      ;;
    *)
      echo "Modo inválido: $MODE" >&2
      usage
      exit 1
      ;;
  esac
}

main "$@"
