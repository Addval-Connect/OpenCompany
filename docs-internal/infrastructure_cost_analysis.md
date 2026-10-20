# Infrastructure Cost Analysis — OpenCompany Multi-Tenant

> Análisis de capacidad y costos para workflows con procesamiento de PDFs (5 MB máx),
> llamadas LLM (10 por ejecución), arquitectura multi-tenant en AWS, modo cloud,
> sticky cache = 50 entradas.

---

## 1. Arquitectura de Workers Temporal por Namespace

Con `MULTI_TENANT_NAMESPACES=true` + `TEMPORAL_TENANT_WORKER_POOL=true`, por cada
namespace se inicia:

| Componente | Cantidad | RAM estimada |
|---|---|---|
| `TemporalWorkerManager` (machina-tasks) | 1 | ~60–100 MB |
| `TemporalWorkerPool` workers (8 colas) | 8 | ~15–25 MB c/u |
| **Total por namespace (idle)** | — | **~200–330 MB** |

**Colas del pool:** `machina-default` (20 slots), `rest-api` (50), `ai-heavy` (4),
`triggers-poll` (100), `triggers-event` (100), `android` (10),
`browser` (4), `messaging` (20).

---

## 2. RAM por Ejecución Concurrente (PDF workflow)

| Fase | Duración | RAM ocupada |
|---|---|---|
| Dispatch MachinaWorkflow | segundos | ~5–10 MB |
| Actividad pypdf activa (parsing) | ~10–30 seg | ~50 MB peak → ~10 MB |
| Esperando respuesta LLM | 30–120 seg | ~15–20 MB |
| Entre actividades (Temporal scheduling) | ~500 ms | ~5 MB |
| **Promedio sobre 7.5 min** | — | **~30 MB promedio** |

### Anatomía de memoria — PDF 5 MB con pypdf

```
Raw file bytes (pypdf)              =   5 MB
Parse interno pypdf (object tree)   =  10–20 MB   (2–4× file size)
Texto extraído (output)             =   ~1 MB
asyncio.to_thread overhead          =   ~8 MB
Serialización resultado Temporal    =   ~1 MB
──────────────────────────────────────────────
Total por actividad concurrente     =  25–35 MB
Peak (durante parse)                =  hasta 50 MB
```

> **Importante:** `documentParser` no tiene cap en output. `dataSource` usa
> `PDF_MAX_PAGES=20` y `PDF_MAX_PAGE_CHARS=20,000`. Usar `dataSource` para
> workloads de alto volumen.

---

## 3. Limitaciones de CPU

### GIL de Python (constraint principal)

`pypdf` es Python puro — **retiene el GIL** durante text extraction.
Múltiples threads parseando PDFs no corren verdaderamente en paralelo.

```
20 threads pypdf concurrentes → CPU efectiva ≈ 1–2 cores
```

`marker` (ML/GPU) y `unstructured` (subprocesos) bypasean el GIL y escalan linealmente.

### Thread pool de Python (constraint oculto)

`asyncio.to_thread` usa `ThreadPoolExecutor(max_workers = min(32, cpu_count + 4))`:

| vCPUs | Max threads | Max PDF parses concurrentes |
|---|---|---|
| 2 | 6 | 6 |
| 4 | 8 | 8 |
| 8 | 12 | 12 |

**Fix gratuito — override del thread pool en `main.py`:**

```python
import asyncio
from concurrent.futures import ThreadPoolExecutor

loop = asyncio.get_event_loop()
loop.set_default_executor(ThreadPoolExecutor(max_workers=40))
```

Con este override, el thread pool deja de ser el bottleneck.

---

## 4. Tabla de Instancias AWS — Especificaciones y Throughput

| Instancia | vCPU | RAM | Max exec/día | Costo fijo/día (EC2+EBS) | Costo variable/exec | Variable 10K exec/día | Variable 20K exec/día |
|---|---|---|---|---|---|---|---|
| t3.xlarge | 4 | 16 GB | ~18,000 | **$4.13** | $0.0000355 | $0.36 | $0.71 |
| c5.xlarge | 4 | 8 GB | ~20,000 | **$4.21** | $0.0000355 | $0.36 | $0.71 |
| c5.2xlarge | 8 | 16 GB | ~27,000 | **$8.29** | $0.0000355 | $0.36 | $0.71 |
| r5.xlarge | 4 | 32 GB | ~20,000 | **$6.18** | $0.0000355 | $0.36 | $0.71 |

> EBS base incluido: 50 GB gp3 = $0.133/día (OS + app + Temporal binary + DBs).
> Precios estimados US East (N. Virginia), Linux, on-demand, agosto 2025.

### Throughput máximo diario (Little's Law)

```
Ejecuciones/día = Slots concurrentes × (1440 min / duración promedio)
```

Con 4 GB RAM dedicada a ejecuciones, duración promedio 7.5 min:

| RAM dedicada | Slots (÷30 MB avg) | Exec/día @ 5 min | Exec/día @ 10 min |
|---|---|---|---|
| 1 GB | 33 | ~9,504 | ~4,752 |
| 2 GB | 68 | ~19,584 | ~9,792 |
| 4 GB | 136 | ~39,168 | ~19,584 |
| 8 GB | 273 | ~78,624 | ~39,312 |

> **Atención:** El queue slot limit (`machina-default` = 20 por namespace) es el
> verdadero cuello de botella hasta que se ajuste `TEMPORAL_MACHINA_DEFAULT_CONCURRENCY`.

### Configuración recomendada por RAM

```bash
# .env — ajustar según RAM dedicada
TEMPORAL_MACHINA_DEFAULT_CONCURRENCY=33   # 1 GB
TEMPORAL_MACHINA_DEFAULT_CONCURRENCY=68   # 2 GB
TEMPORAL_MACHINA_DEFAULT_CONCURRENCY=136  # 4 GB
TEMPORAL_MACHINA_DEFAULT_CONCURRENCY=273  # 8 GB
```

---

## 5. Análisis CPU por Instancia

| Instancia | vCPUs | PDF parses efectivos (con pool override) | Exec/día (4 GB RAM, 7.5 min) | Bottleneck |
|---|---|---|---|---|
| 2 cores | 2 | ~6–8 | ~13,000–16,000 | GIL + thread pool |
| **c5.xlarge** | **4** | **~10–14** | **~18,000–22,000** | **Thread pool cap** |
| c5.2xlarge | 8 | ~16–20 | ~24,000–30,000 | GIL (retorno decreciente) |

**Salto 2→4 cores:** significativo (~35% más throughput).
**Salto 4→8 cores:** solo ~30% con pypdf (GIL limita). Vale la pena solo con
10+ namespaces o usando `marker`/`unstructured`.

---

## 6. Costos Variables por Ejecución (solo infraestructura, sin LLM tokens)

| Componente | $/exec | 10K exec/día | 10K exec/mes |
|---|---|---|---|
| Network egress total (LLM calls + cliente) | $0.0000114 | $0.11 | $3.42 |
| Network egress LLM (solo requests API) | $0.0000070 | $0.07 | $2.16 |
| CloudWatch logs (~10 KB/exec) | $0.0000050 | $0.05 | $1.50 |
| EBS workspace (retención 1 día, 6 MB/exec) | $0.0000164 | $0.16 | $4.92 |
| EBS I/O | $0.0000020 | $0.02 | $0.60 |
| Temporal history (SQLite) | $0.0000007 | $0.01 | $0.18 |
| **Total variable infra** | **$0.0000355** | **$0.36** | **$10.62** |

### Detalle Network Egress LLM

```
Por ejecución (10 llamadas LLM):
  Outbound (request payload): 10 × 2,000 tokens × 4 bytes = ~80 KB
  Inbound (response):         GRATIS en AWS
  AWS egress rate:            $0.09/GB

20K exec/día = 1.6 GB outbound = $0.14/día
```

---

## 7. Análisis Fijo vs Variable — 10,000 Ejecuciones/Día (c5.xlarge)

### Costos fijos (corren 24/7)

| Componente | $/día | $/mes |
|---|---|---|
| EC2 c5.xlarge (on-demand) | $4.08 | $122.40 |
| EBS 50 GB gp3 | $0.13 | $4.00 |
| **Total fijo** | **$4.21** | **$126.40** |

### Costos variables (10,000 ejecuciones)

| Componente | $/día | $/mes |
|---|---|---|
| Network egress | $0.11 | $3.42 |
| CloudWatch logs | $0.05 | $1.50 |
| EBS workspace (1 día retención) | $0.16 | $4.92 |
| EBS I/O | $0.02 | $0.60 |
| Temporal history | $0.01 | $0.18 |
| **Total variable** | **$0.36** | **$10.62** |

### Resumen

| | $/día | $/mes | % del total |
|---|---|---|---|
| Fijo | $4.21 | $126.40 | **92.1%** |
| Variable | $0.36 | $10.62 | **7.9%** |
| **Total infra** | **$4.57** | **$137.02** | 100% |
| **Costo por ejecución** | — | — | **$0.000457** |

---

## 8. Impacto del Volumen sobre el Costo por Ejecución

El costo fijo se amortiza con más volumen (c5.xlarge):

| Exec/día | Fijo/día | Variable/día | Total/día | **$/exec** | Utilización |
|---|---|---|---|---|---|
| 2,500 | $4.21 | $0.09 | $4.30 | **$0.00172** | 12.5% |
| 5,000 | $4.21 | $0.18 | $4.39 | **$0.00088** | 25% |
| **10,000** | **$4.21** | **$0.36** | **$4.57** | **$0.00046** | **50%** |
| 15,000 | $4.21 | $0.53 | $4.74 | **$0.00032** | 75% |
| 20,000 | $4.21 | $0.71 | $4.92 | **$0.00025** | 100% |

> A 2,500 exec/día pagas **7× más por ejecución** que a 20,000 — misma instancia.

---

## 9. Costos Variables con Riesgo de Crecimiento Descontrolado

### Workspace disk growth (el más peligroso)

Si no hay cleanup automático de `~/.opencompany/workspaces/`:

| Retención | Almacenamiento acumulado (20K exec/día) | Costo EBS/mes |
|---|---|---|
| 1 día | ~123 GB | ~$10 |
| 7 días | ~861 GB | ~$69 |
| 30 días | ~3.7 TB | ~$296 |

**Mitigación:** TTL automático post-ejecución o mover a S3 Glacier.

### Temporal history (SQLite `temporal.db`)

A 20K ejecuciones/día × ~50 KB historia Temporal:

| Tiempo | Tamaño temporal.db | Costo EBS |
|---|---|---|
| 1 semana | ~7 GB | ~$0.56/mes |
| 1 mes | ~30 GB | ~$2.40/mes |
| 6 meses | ~180 GB | ~$14.40/mes |

**Mitigación:** job periódico de `workflow delete` o migrar a Temporal Cloud en producción.

---

## 10. Recomendación de Instancia

| Caso de uso | Instancia | Justificación |
|---|---|---|
| Single tenant, pypdf | **c5.xlarge** | Sweet spot — GIL limita beneficio de 8 cores |
| Multi-tenant (5+ namespaces) | **c5.2xlarge** | Cada namespace compite por el event loop |
| Multi-tenant + marker/unstructured | **c5.2xlarge** | ML/subprocesos usan todos los cores |
| Muchos tenants, RAM prioritaria | **r5.xlarge** | 32 GB permite 15–20 namespaces con cache=50 |
| Budget / bajo volumen | **t3.xlarge** | Burstable, bueno para cargas intermitentes |

### Savings Plan 1 año (sin pago anticipado, ~30% descuento)

| Instancia | On-demand/día | Savings Plan/día | Ahorro/mes |
|---|---|---|---|
| t3.xlarge | $4.00 | ~$2.80 | ~$36 |
| c5.xlarge | $4.08 | ~$2.85 | ~$37 |
| c5.2xlarge | $8.16 | ~$5.70 | ~$74 |
| r5.xlarge | $6.05 | ~$4.25 | ~$54 |

---

## 11. Estrategia Multi-Tenant

Con `TEMPORAL_TENANT_WORKER_POOL=true`, por cada tenant namespace:

```
RAM idle por namespace (cache=50):
  10 Workers × 12 MB  =  120 MB
  50 cache entries × 5 MB  =  250 MB
  Total  =  ~370 MB/namespace

Namespaces en 8 GB (con overhead OS):
  7.3 GB disponibles / 370 MB  ≈  19 namespaces máx (idle)
```

**Regla práctica por RAM total:**

| RAM instancia | Namespaces seguros (cache=50) | Exec concurrentes totales |
|---|---|---|
| 8 GB | 5–7 | ~100 |
| 16 GB | 10–15 | ~200 |
| 32 GB | 20–25 | ~400 |

El costo fijo de infra se divide entre todos los tenants:
- c5.xlarge + 5 tenants = **$0.84/día por tenant** (fijo)

---

## 12. Resumen Ejecutivo

```
Costo infra por ejecución (10K exec/día, c5.xlarge):  $0.000457
Costo infra mensual (10K exec/día):                    $137
  └─ 92% fijo (instancia + EBS)
  └─ 8% variable (network + logs + storage)

El modelo LLM consumido es el verdadero costo variable:
  Haiku 4.5:   $0.0045/exec  →  $45/día a 10K exec
  Sonnet 4.6:  $0.0165/exec  →  $165/día a 10K exec
  Sonnet 5.5:  $0.0110/exec  →  $110/día a 10K exec
  Opus 5.5:    $0.0220/exec  →  $220/día a 10K exec

La infraestructura es <3% del costo total en todos los casos.
```

---

*Precios estimados, US East (N. Virginia), agosto 2025. Verificar en
[AWS Pricing Calculator](https://aws.amazon.com/ec2/pricing/on-demand/)
antes de comprometer recursos.*

---

## 13. Análisis LLM — Modelos de Bajo Costo via OpenRouter

> Mezcla: **80% JEV + 20% DeepSeek Flash** a precio plano **$0.042/1M tokens (in/out)**.
> Base: 10 llamadas LLM/ejecución × (2,000 tokens input + 500 output) = **25,000 tokens/exec**.

```
Costo por ejecución = 25,000 × $0.042 / 1,000,000 = $0.00105
```

### Costo LLM por volumen diario

| Exec/día | Tokens/día | LLM $/día | LLM $/mes |
|---|---|---|---|
| 2,500 | 62.5M | $2.63 | $78.75 |
| 5,000 | 125M | $5.25 | $157.50 |
| **10,000** | **250M** | **$10.50** | **$315.00** |
| 15,000 | 375M | $15.75 | $472.50 |
| 20,000 | 500M | $21.00 | $630.00 |

### Costo total mensual — Infra + LLM (c5.xlarge)

| Exec/día | Infra/mes | LLM/mes | **Total/mes** | **$/exec total** |
|---|---|---|---|---|
| 2,500 | $129 | $79 | **$208** | **$0.00277** |
| 5,000 | $131 | $158 | **$289** | **$0.00193** |
| **10,000** | **$132** | **$315** | **$447** | **$0.00149** |
| 15,000 | $134 | $473 | **$607** | **$0.00135** |
| 20,000 | $137 | $630 | **$767** | **$0.00128** |

### Comparativa vs modelos Claude (10,000 exec/día)

| Modelo | $/exec LLM | LLM/mes | Total con infra/mes | Factor |
|---|---|---|---|---|
| **JEV/DeepSeek $0.042/MTok** | **$0.00105** | **$315** | **$447** | 1× (base) |
| Claude Haiku 4.5 ($1/$5) | $0.0450 | $13,500 | $13,632 | 30× más caro |
| Claude Sonnet 5.5 ($2/$10) | $0.0900 | $27,000 | $27,132 | 61× más caro |
| Claude Sonnet 4.6 ($3/$15) | $0.1350 | $40,500 | $40,632 | 91× más caro |
| Claude Opus 5.5 ($4/$20) | $0.1800 | $54,000 | $54,132 | 121× más caro |

### Distribución del costo a 10,000 exec/día

```
Infra fija:     $132/mes   (29.5%)
LLM tokens:     $315/mes   (70.5%)
─────────────────────────────────
Total:          $447/mes
```

A **$0.042/1M tokens** el LLM es el mayor costo pero la infra sigue siendo relevante
(~30%). Con modelos Claude la infra representaría menos del 1% del total.

### Impacto en la estrategia de pricing

A este precio de LLM conviene **maximizar la utilización de la instancia** para reducir
el costo fijo por ejecución:

| Utilización | Infra/exec | LLM/exec | **Total/exec** |
|---|---|---|---|
| 25% (2,500/día) | $0.00172 | $0.00105 | **$0.00277** |
| 50% (5,000/día) | $0.00088 | $0.00105 | **$0.00193** |
| **100% (10,000/día)** | **$0.00046** | **$0.00105** | **$0.00151** |
| **Máximo (20,000/día)** | **$0.00025** | **$0.00105** | **$0.00130** |

A utilización máxima, el costo de infra por ejecución baja a $0.00025 —
el LLM ($0.00105) domina y es **4× el costo de infra**. Escalar la instancia
solo tiene sentido si el volumen supera la capacidad máxima actual.
