# Raio Transporte — Mobilidade Urbana em isócronos

Bem-vindo ao backend do **UrbanIso** (RaioTransporte), um software que transforma dados de transporte coletivo em conhecimento sobre sua cidade. Aqui calculamos **raios isócronos** — áreas que podem ser alcançadas dentro de um tempo específico usando ônibus, metrô ou a pé — para ajudar pessoas a descobrirem oportunidades de moradia, trabalho e lazer com base na mobilidade real do território. O objetivo do aplicativo é oferecer uma visão prática de como se deslocar, permitindo conhecer melhor os bairros, comparar acessibilidade entre pontos e planejar políticas de mobilidade mais justas.

## Visão Geral

- **Raio de alcance em tempo real**: cálculo de isócronas usando GTFS e algoritmos otimizados para diferentes dias e horários.
- **Monitoramento ao vivo**: streaming NDJSON para acompanhar o progresso dos cálculos em dashboards ou ferramentas GIS.
- **Integração de API**: API REST autenticada para integrar o motor de mobilidade a portais, aplicações mobile ou análises internas.

## Destaques do Projeto

### Explore a cidade de forma inteligente
- Algoritmo baseado em **Connection Scan Algorithm (CSA)**, combinando dados de caminhada e conexões de transporte para gerar isócronas precisas. 【F:mobilidade/transporte/algorithms/raio_alcance.py†L1-L132】
- Suporte a diferentes presets de horários para comparar a acessibilidade em dias úteis, horários de pico e fins de semana. 【F:mobilidade/transporte/views.py†L58-L96】
- API de monitoramento em tempo real com hub de visualização thread-safe, permitindo criar experiências interativas para o usuário final. 【F:mobilidade/transporte/visualization.py†L1-L126】

### Boas práticas de cibersegurança
- **Autenticação com chave estática e comparação em tempo constante** via cabeçalho `X-API-Key`, prevenindo ataques de timing e garantindo que apenas clientes autorizados acessem o endpoint de isócronas. 【F:mobilidade/transporte/authentication.py†L1-L60】
- **Proteções HTTP fortalecidas** com middlewares de segurança do Django, cabeçalhos CORS controlados e suporte a `SECURE_PROXY_SSL_HEADER` para implantação atrás de proxies HTTPS. 【F:mobilidade/mobilidade/settings.py†L78-L146】
- **Caching controlado** das respostas geoespaciais com validação por coordenadas, reduzindo carga sem expor dados sensíveis ou exceder limites de tempo de processamento. 【F:mobilidade/transporte/views.py†L104-L179】

### Outras vantagens
- Código preparado para **implantações em contêineres**, com Dockerfile multi-stage e compatibilidade com AWS Lambda Web Adapter. 【F:mobilidade/Dockerfile†L1-L70】
- Suporte a **PostGIS** e bibliotecas científicas robustas (SciPy, GDAL) para manipular geometrias em alta performance.
- Ferramentas de observabilidade integradas, com logs estruturados que ajudam a auditar métricas de execução e performance.

## Arquitetura em Alto Nível

```text
┌──────────────────────┐
│ Cliente (web/mobile) │
└──────────┬───────────┘
           │ HTTPS + X-API-Key
           ▼
┌──────────────────────────────┐
│ Django REST Framework API    │
│  • /api/raio/ (cálculo)      │
│  • /api/raio/stream/ (NDJSON)│
│  • /api/visualizer/stream/   │
└──────────┬───────────────────┘
           │ consultas GTFS + Geo
┌──────────────────────────────┐
│ Núcleo CSA + Geo Cache       │
│  • Parâmetros de tempo       │
│  • Caminhada + transporte    │
└──────────┬───────────────────┘
           │ PostGIS / SciPy
┌──────────────────────────────┐
│ Banco PostGIS + GTFS import. │
└──────────────────────────────┘
```

## Instalação e Uso

### 1. Pré-requisitos

- Python 3.12 ou Conda
- PostgreSQL com extensão PostGIS habilitada
- GDAL e PROJ instalados (já incluídos no ambiente Conda ou imagem Docker)

### 2. Configuração local com Python

```bash
Clone o repositório

cd RaioTransporte-BackEnd/mobilidade

Opcional: crie um ambiente virtual
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
.venv\Scripts\Activate   # Windows PowerShell

Instale dependências
pip install -r requirements.txt

Configure variáveis sensíveis
cp .env.example .env  # ajuste valores (SECRET_KEY, DATABASE_URL, API_SHARED_SECRET, etc.)

Aplique migrações e rode o servidor
python manage.py migrate
python manage.py runserver 0.0.0.0:8000
```

### 3. Usando Conda (opcional)

```bash
cd RaioTransporte-BackEnd/mobilidade
conda env create -f environment.yml
conda activate mobilidade
```

### 4. Subindo com Docker

```bash
cd RaioTransporte-BackEnd/mobilidade

# Banco PostGIS dedicado
docker compose up -d db

# Build da aplicação
docker build -t raio-transporte-backend .

# Execução em modo desenvolvimento
docker run --rm -it \
  -p 8080:8080 \
  --env-file .env \
  --link mobilidade_postgis:db \
  raio-transporte-backend
```

### 5. Importando dados GTFS
(observação, dependendo da estrutura do seu proovedor de GTFS serão necessárias alterações)

1. Disponibilize o arquivo GTFS na pasta `data/` (crie se necessário).
2. Crie um comando de carga (ex.: `python manage.py carregar_gtfs data/seu_arquivo.zip`).
3. Reindexe caches conforme necessário com `python manage.py clearcache`.

### 6. Testando a API

```bash
# Requisição autenticada para gerar o raio de 30 minutos a partir de um ponto
curl -X POST http://localhost:8000/api/raio/ \
  -H "Content-Type: application/json" \
  -H "X-API-Key: sua-chave" \
  -d '{
    "lat": -23.5505,
    "lon": -46.6333,
    "tempo": 30,
    "presetsDia": "DEFAULT"
  }'
```