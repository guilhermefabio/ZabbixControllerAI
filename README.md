# ZabbixControllerAI

An AI Agent that monitors your service, hardware, and makes diagnostics and troubleshooting on your computer

## 📋 O que é o ZabbixControllerAI?

**ZabbixControllerAI** é um agente inteligente de monitoramento que utiliza IA (OpenAI) para analisar logs de aplicações em tempo real, detectar padrões de pré-falha e incidentes, e fornecer diagnósticos automáticos com recomendações de remediação.

## 🎯 Principais Funcionalidades

### 1. **Monitoramento em Tempo Real de Logs**
- Acompanha continuamente um arquivo de log específico
- Detecta novas linhas conforme são adicionadas
- Analisa padrões de níveis de severidade (INFO, WARN, ERROR)

### 2. **Detecção Inteligente de Eventos**
O agente detecta 4 tipos de eventos críticos:

#### **a) Taxa Alta de WARNs (Alerta Preditivo)**
- Monitora quantas mensagens WARN ocorrem por minuto
- Quando a taxa excede o limite configurado, dispara um alerta preditivo
- Útil para detectar degradação gradual do sistema
- **Padrão**: `[timestamp] WARN [mensagem]`

#### **b) Taxa Alta de ERRORs (Incidente)**
- Detecta quando múltiplos ERRORs ocorrem em curto período
- Indica uma falha em andamento que requer ação imediata
- **Padrão**: `[timestamp] ERROR [mensagem]`

#### **c) Padrão WARN → ERROR (Alerta Preditivo)**
- Identifica quando um WARN é seguido por ERROR em uma janela de tempo configurável
- Indica progressão de problema (degradação → falha)
- Permite ação preventiva antes da falha completa

#### **d) Qualquer Linha ERROR (Incidente)**
- Qualquer ocorrência de ERROR é registrada como incidente
- Fornece contexto imediato para análise

### 3. **Integração com OpenAI para Análise Inteligente**
Quando um evento é detectado, o agente envia os dados para o modelo OpenAI que:
- **Identifica causa raiz provável**: Analisa o erro e logs contextuais
- **Sugere checks imediatos**: Comandos Linux para investigação rápida
- **Propõe mitigação**: Ações para resolver o problema rapidamente
- **Recomenda prevenção**: Como evitar que aconteça novamente
- **Responde em Português (PT-BR)**: Totalmente adaptado para usuários em português

## 🔧 Arquitetura e Fluxo

```
┌─────────────────┐
│  Arquivo Log    │
│ (monitored.log) │
└────────┬────────┘
         │
         ▼
┌────────────────────────┐
│  agent.py              │
│  Monitor em Tempo Real  │
└────────┬───────────────┘
         │
         ├─── Parser (Regex) ───┐
         │                      │
         ▼                      ▼
   ┌──────────┐           ┌──────────┐
   │   WARN   │           │  ERROR   │
   │  Events  │           │  Events  │
   └────┬─────┘           └────┬─────┘
        │                      │
        ▼                      ▼
   ┌────────────────────────────────┐
   │  Detecção de Padrões           │
   │ • Alta taxa WARN/minuto        │
   │ • Alta taxa ERROR/minuto       │
   │ • Padrão WARN→ERROR            │
   │ • Qualquer ERROR isolado       │
   └────────┬─────────────────────┘
            │
            ▼
   ┌──────────────────────┐
   │  System de Cooldown  │
   │  (evita spam)        │
   └────────┬─────────────┘
            │
            ▼
   ┌──────────────────────┐
   │  OpenAI API Call     │
   │  (Análise com IA)    │
   └────────┬─────────────┘
            │
            ├─→ Causa Raiz
            ├─→ Commands Diagnosticar
            ├─→ Mitigação Rápida
            └─→ Prevenção
            │
            ▼
   ┌──────────────────────┐
   │  Agent Log           │
   │  (/var/log/zbx_lab)  │
   └──────────────────────┘
```

## 📊 Formato Esperado de Log

O agente espera logs no seguinte formato:
```
[timestamp] [LEVEL] [message]
```

**Exemplo:**
```
2026-01-17T10:45:23 INFO Application started
2026-01-17T10:46:15 WARN Connection timeout detected
2026-01-17T10:46:30 ERROR Failed to connect to database
```

**Padrão Regex:**
```regex
^(?P<ts>\S+)\s+(?P<level>INFO|WARN|ERROR)\s+(?P<msg>.+)$
```

## 🚀 Como Usar

### 1. **Instalação de Dependências**
```bash
pip install openai
```

### 2. **Configurar Chave OpenAI**
```bash
export OPENAI_API_KEY="seu-api-key-aqui"
```

### 3. **Executar o Agente**

**Monitorar apenas novos eventos:**
```bash
python agent.py --log-file /caminho/do/seu/log.log
```

**Monitorar desde o início do arquivo:**
```bash
python agent.py --log-file /caminho/do/seu/log.log --from-start
```

### 4. **Configuração Avançada**

Todos os parâmetros podem ser customizados:

```bash
python agent.py \
  --log-file /var/log/myapp/app.log \
  --warn-per-min 10 \
  --error-per-min 3 \
  --warn-to-error-window 120 \
  --poll-interval 1.0 \
  --openai-model gpt-4-mini \
  --openai-timeout 10.0 \
  --openai-temperature 0.2 \
  --openai-max-tokens 350 \
  --cooldown-seconds 30 \
  --context-lines 60
```

## 📋 Parâmetros Disponíveis

| Parâmetro | Padrão | Descrição |
|-----------|--------|-----------|
| `--log-file` | `/var/log/myapp/app.log` | Caminho do arquivo de log a monitorar |
| `--from-start` | false | Se deve ler desde o início do arquivo |
| `--warn-per-min` | 10 | Limite de WARNs por minuto para alertar |
| `--error-per-min` | 3 | Limite de ERRORs por minuto para alertar |
| `--warn-to-error-window` | 120 | Janela em segundos para padrão WARN→ERROR |
| `--poll-interval` | 1.0 | Intervalo em segundos entre verificações |
| `--openai-model` | `gpt-4-mini` | Modelo OpenAI a usar |
| `--openai-timeout` | 10.0 | Timeout em segundos para chamadas OpenAI |
| `--openai-temperature` | 0.2 | Temperatura do modelo (0.2 = mais determinístico) |
| `--openai-max-tokens` | 350 | Máximo de tokens na resposta |
| `--cooldown-seconds` | 30 | Tempo mínimo entre chamadas OpenAI por tipo de evento |
| `--context-lines` | 60 | Número de linhas recentes de log como contexto |

## 📁 Estrutura de Arquivos

```
ZabbixControllerAI/
├── agent.py              # Agente principal de monitoramento
├── main.py               # Ponto de entrada (placeholder)
├── pyproject.toml        # Dependências do projeto
├── LICENSE              # Licença
├── README.md            # Este arquivo
└── zbx_incident_lab.sh  # Script shell auxiliar
```

## 📝 Logs do Agente

O agente registra todas as suas atividades em:
```
/var/log/zbx_lab/agent.log
```

**Exemplo de saída:**
```
2026-01-17T10:45:23 agent started log_file=/var/log/myapp/app.log model=gpt-4-mini
2026-01-17T10:46:15 predictive alert: high WARN rate (12/min)
2026-01-17T10:46:16 openai (predictive_high_warn_rate): [Análise da IA...]
2026-01-17T10:46:30 incident detected: 2026-01-17T10:46:30 ERROR Failed to connect to database
2026-01-17T10:46:31 openai (incident_error_line): [Análise da IA...]
```

## 🔐 Sistema de Cooldown

Para evitar sobrecarregar a API OpenAI:
- Cada tipo de evento tem seu próprio timer de cooldown
- Chamadas repetidas ao mesmo tipo de evento dentro do cooldown são ignoradas
- O padrão é 30 segundos entre chamadas do mesmo tipo
- Possibilita análise frequente sem desperdício de API

## 🎯 Padrões de Detecção

### Taxa Alta de WARNs (Preditivo)
```
Detecção: count(WARN) >= warn-per-min (padrão: 10) em 60 segundos
→ Indica degradação gradual
→ OpenAI sugere ações preventivas
```

### Taxa Alta de ERRORs (Incidente)
```
Detecção: count(ERROR) >= error-per-min (padrão: 3) em 60 segundos
→ Indica falha em andamento
→ OpenAI sugere resolução imediata
```

### Padrão WARN → ERROR (Preditivo)
```
Detecção: WARN detectado + ERROR dentro de warn-to-error-window (padrão: 120s)
→ Indica progressão de problema
→ OpenAI sugere prevenção
```

### Qualquer ERROR (Incidente)
```
Detecção: Qualquer linha com ERROR (com cooldown)
→ Documentação de incidente
→ Análise imediata por IA
```

## 🔌 Integração com Zabbix (Roadmap)

Atualmente, o agente registra eventos em logs. A integração futura com Zabbix permitirá:
- Enviar eventos detectados diretamente para Zabbix API
- Criar problemas (problems) no Zabbix
- Adicionar comentários com análise da IA
- Atualizar status de severity baseado em análise
- Integrar com ações automáticas do Zabbix

## 💡 Exemplos de Casos de Uso

### 1. **Detecção de Memory Leak**
```
[Log mostra WARNs crescentes sobre memória]
Agent detecta → Taxa alta de WARN
OpenAI analisa → Identifica memory leak
OpenAI sugere → Commands para inspecionar, limites, reinício agendado
```

### 2. **Falha de Banco de Dados**
```
[Erro de conexão]
Agent detecta → ERROR: "Failed to connect to database"
OpenAI analisa → Verifica conectividade, firewall, credenciais
OpenAI sugere → Commands de diagnóstico, reconexão, fallback
```

### 3. **Degradação Progressiva**
```
[WARNs aumentam → ERROR disparado]
Agent detecta → Padrão WARN→ERROR
OpenAI analisa → Identifica ponto de falha
OpenAI sugere → Ações preventivas para próxima vez
```

## 🛠️ Desenvolvimento

### Estrutura do Código

**agent.py** contém:
- `parse_args()` - Processamento de argumentos CLI
- `ensure_agent_log()` - Garantir arquivo de log
- `log_agent()` - Escrever logs com timestamp
- `parse_line()` - Extrair dados de linhas de log via regex
- `cleanup_old()` - Manter deques com dados recentes apenas
- `openai_analyze()` - Chamar IA para análise
- `should_call_openai()` - Implementar cooldown
- `monitor_log()` - Loop principal de monitoramento
- `main()` - Ponto de entrada

### Estruturas de Dados

- **Deques**: Filas eficientes para armazenar timestamps de eventos últimos 60 segundos
- **Dicionários**: Rastreamento de última chamada OpenAI por tipo de evento
- **Regex**: Pattern matching para parse de logs

## 📚 Dependências

```
openai>=1.0.0
```

## 📄 Licença

Veja arquivo LICENSE para detalhes.

## 🤝 Contribuições

Contribuições são bem-vindas! Por favor:
1. Faça fork do repositório
2. Crie uma branch para sua feature
3. Commit suas mudanças
4. Push para a branch
5. Abra um Pull Request

---

**Desenvolvido com ❤️ para monitoramento inteligente**
