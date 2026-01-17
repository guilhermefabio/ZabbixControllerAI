# ZabbixControllerAI
An AI Agent that monitors your service, hardware, and makes diagnostics and troubleshooting on your computer.

## Incident lab (reversible)
Use the incident lab script to simulate alerts and log patterns on a host/VM:

```bash
sudo ./zbx_incident_lab.sh apply --service nginx --block-port 80 --cpu --mem --disk --net
sudo ./zbx_incident_lab.sh apply --logs --log-cycles 40 --log-interval 1
sudo ./zbx_incident_lab.sh revert --service nginx --block-port 80 --net --disk
```

## Log monitoring agent
The log monitoring agent tails your application log and emits predictive alerts when WARN rates spike or
WARN->ERROR patterns appear. It logs to `/var/log/zbx_lab/agent.log`, prints to stdout, and can forward
each log line to a Zabbix webhook that calls GPT for real-time troubleshooting suggestions.

```bash
sudo ./zbx_log_agent.py --log-file /var/log/myapp/app.log
```

Options include thresholds, windows, and a webhook integration:

```bash
sudo ./zbx_log_agent.py --warn-per-min 12 --error-per-min 2 --warn-to-error-window 120
sudo ./zbx_log_agent.py --webhook-url https://zabbix.example/api/webhook \
  --webhook-header "Authorization: Bearer <token>"
```
