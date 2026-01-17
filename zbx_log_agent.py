#!/usr/bin/env python3
import argparse
import json
import os
import re
import sys
import time
import urllib.request
from collections import deque
from datetime import datetime, timezone

LOG_DIR = "/var/log/zbx_lab"
AGENT_LOG = f"{LOG_DIR}/agent.log"
DEFAULT_LOG_FILE = "/var/log/myapp/app.log"

LOG_PATTERN = re.compile(
    r"^(?P<ts>\S+)\s+(?P<level>INFO|WARN|ERROR)\s+(?P<msg>.+)$"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Agente simples de monitoramento que acompanha logs e sinaliza "
            "padrões de pré-falha (WARN) e falhas (ERROR)."
        )
    )
    parser.add_argument("--log-file", default=DEFAULT_LOG_FILE, help="Caminho do log monitorado")
    parser.add_argument("--from-start", action="store_true", help="Inicia leitura desde o começo")
    parser.add_argument("--warn-per-min", type=int, default=10, help="Limite de WARN por minuto")
    parser.add_argument("--error-per-min", type=int, default=3, help="Limite de ERROR por minuto")
    parser.add_argument("--warn-to-error-window", type=int, default=120, help="Janela em segundos para WARN->ERROR")
    parser.add_argument("--poll-interval", type=float, default=1.0, help="Intervalo de polling em segundos")
    parser.add_argument("--webhook-url", help="Webhook (ex: Zabbix) para enviar logs ao GPT")
    parser.add_argument(
        "--webhook-timeout",
        type=float,
        default=5.0,
        help="Timeout do webhook em segundos",
    )
    parser.add_argument(
        "--webhook-header",
        action="append",
        default=[],
        help="Header adicional para o webhook (ex: 'Authorization: Bearer <token>')",
    )
    return parser.parse_args()


def ensure_agent_log() -> None:
    os.makedirs(LOG_DIR, exist_ok=True)
    if not os.path.exists(AGENT_LOG):
        with open(AGENT_LOG, "a", encoding="utf-8"):
            pass


def log_agent(message: str) -> None:
    ensure_agent_log()
    ts = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    line = f"{ts} {message}"
    print(line)
    with open(AGENT_LOG, "a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def parse_line(line: str) -> tuple[str, str, str] | None:
    match = LOG_PATTERN.match(line)
    if not match:
        return None
    return match.group("ts"), match.group("level"), match.group("msg")


def parse_headers(header_values: list[str]) -> dict[str, str]:
    headers: dict[str, str] = {}
    for header in header_values:
        if ":" not in header:
            continue
        name, value = header.split(":", 1)
        headers[name.strip()] = value.strip()
    return headers


def send_webhook(
    args: argparse.Namespace,
    payload: dict[str, object],
    event_label: str,
) -> None:
    if not args.webhook_url:
        return
    headers = {"Content-Type": "application/json"}
    headers.update(parse_headers(args.webhook_header))
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        args.webhook_url,
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=args.webhook_timeout) as response:
            raw = response.read().decode("utf-8").strip()
    except Exception as exc:  # noqa: BLE001 - log and continue
        log_agent(f"webhook error ({event_label}): {exc}")
        return

    if not raw:
        return

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        log_agent(f"webhook response ({event_label}): {raw}")
        return

    troubleshooting = data.get("troubleshooting") or data.get("suggestion") or data.get("analysis")
    if troubleshooting:
        log_agent(f"gpt troubleshooting ({event_label}): {troubleshooting}")


def cleanup_old(entries: deque[float], cutoff: float) -> None:
    while entries and entries[0] < cutoff:
        entries.popleft()


def monitor_log(args: argparse.Namespace) -> None:
    warn_times: deque[float] = deque()
    error_times: deque[float] = deque()
    last_warn_ts: float | None = None

    log_agent("agent started log_file={}".format(args.log_file))

    with open(args.log_file, "r", encoding="utf-8") as handle:
        if not args.from_start:
            handle.seek(0, os.SEEK_END)

        while True:
            position = handle.tell()
            line = handle.readline()
            if not line:
                time.sleep(args.poll_interval)
                handle.seek(position)
                continue

            parsed = parse_line(line.strip())
            if not parsed:
                continue

            ts, level, _ = parsed
            send_webhook(
                args,
                {
                    "event_type": "log_line",
                    "timestamp": ts,
                    "level": level,
                    "message": _,
                    "raw": line.strip(),
                    "source": args.log_file,
                },
                "log_line",
            )
            now = time.time()
            cutoff_min = now - 60
            cleanup_old(warn_times, cutoff_min)
            cleanup_old(error_times, cutoff_min)

            if level == "WARN":
                warn_times.append(now)
                last_warn_ts = now
            elif level == "ERROR":
                error_times.append(now)

            if len(warn_times) >= args.warn_per_min:
                log_agent(
                    f"predictive alert: high WARN rate ({len(warn_times)}/min)"
                )
                send_webhook(
                    args,
                    {
                        "event_type": "predictive",
                        "reason": "high_warn_rate",
                        "warn_per_min": len(warn_times),
                        "threshold": args.warn_per_min,
                    },
                    "predictive_warn_rate",
                )

            if len(error_times) >= args.error_per_min:
                log_agent(
                    f"incident detected: high ERROR rate ({len(error_times)}/min)"
                )
                send_webhook(
                    args,
                    {
                        "event_type": "incident",
                        "reason": "high_error_rate",
                        "error_per_min": len(error_times),
                        "threshold": args.error_per_min,
                    },
                    "incident_error_rate",
                )

            if level == "ERROR" and last_warn_ts is not None:
                if now - last_warn_ts <= args.warn_to_error_window:
                    log_agent(
                        "predictive alert: WARN->ERROR pattern detected "
                        f"(window={args.warn_to_error_window}s)"
                    )
                    send_webhook(
                        args,
                        {
                            "event_type": "predictive",
                            "reason": "warn_to_error",
                            "window_seconds": args.warn_to_error_window,
                        },
                        "predictive_warn_to_error",
                    )

            if level == "ERROR":
                log_agent(f"incident detected: {ts} {_}")
                send_webhook(
                    args,
                    {
                        "event_type": "incident",
                        "reason": "error_line",
                        "timestamp": ts,
                        "message": _,
                    },
                    "incident_error_line",
                )


def main() -> None:
    args = parse_args()
    if not os.path.exists(args.log_file):
        print(f"Log file not found: {args.log_file}", file=sys.stderr)
        sys.exit(1)
    monitor_log(args)


if __name__ == "__main__":
    main()
