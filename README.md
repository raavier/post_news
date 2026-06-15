# post_news

App de **custo zero** que monitora novidades de produtos de tecnologia (release
notes e blogs, via RSS/Atom), gera um **post para o LinkedIn em português** —
com **card de imagem** e, opcionalmente, um **carrossel em PDF** — e deixa você
**revisar e aprovar** antes de publicar na sua conta pessoal.

Tudo roda dentro do GitHub (Actions + Issues) — sem servidor, sem custo recorrente.

## Como funciona

```
Feeds (RSS/Atom) configurados em feeds.json
        │  (cron diário)
        ▼
  detect.yml  ──►  Gemini (texto PT-BR)  +  card PNG e carrossel PDF (HTML/CSS, local)
        │
        ▼
  Cria uma GitHub Issue (label: pending-approval)  ──►  você recebe a notificação
        │
        │  você revisa, edita o texto se quiser, e adiciona a label "approved"
        │  (opcional: label "carrossel" para publicar o PDF em vez da imagem)
        ▼
  publish.yml  ──►  posta no LinkedIn  ──►  comenta a fonte na issue e fecha
```

- **Gerência e aprovação**: as [Issues](../../issues) do repositório são o seu painel.
  Cada novidade vira uma issue com o texto, o card e o carrossel.
- **Notificação**: as notificações nativas do GitHub (e-mail/app) avisam quando há rascunho novo.
- **Aprovar**: adicione a label `approved`. **Publicar como carrossel**: adicione também `carrossel`.
  **Descartar**: feche a issue.
- **Editar**: edite o corpo da issue (entre os marcadores `POST:START`/`POST:END`) antes de aprovar.

## Geração de conteúdo (algoritmo do LinkedIn 2026)

O texto é otimizado para **tempo de leitura (dwell time)** — o principal sinal do feed em 2026:

- Prende a atenção e **entrega o valor sem depender de link** (a fonte vai no 1º comentário, não no corpo).
- **70–150 palavras**, com um detalhe concreto e quebras de linha (escaneável).
- **Sem hashtags** e **sem isca mecânica** de engajamento; termina com uma **pergunta aberta** genuína.

Os prompts ficam em `prompts/` (`post_template.md`, `revise_template.md`, `carousel_template.md`).

### Formatos visuais (renderizados localmente, custo 0 e sem rede)

A identidade visual é compartilhada em `render.py` (tema claro + acento coral, termos-chave
destacados via `[[termo]]`, e cards de código com *syntax highlighting* do Pygments).
A renderização é HTML/CSS → **WeasyPrint** (PDF); para o PNG, o PDF de 1 página é
rasterizado com **PyMuPDF**.

- **Card único (PNG, 1200×627)** — formato padrão do post.
- **Carrossel (PDF, 1080×1350, 3–10 slides adaptativos)** — formato de maior alcance, publicado
  como **documento** no LinkedIn quando a issue tem a label `carrossel`. O número de slides
  **varia conforme o conteúdo** (não é fixo); slides podem incluir um trecho de código.

## Componentes

| Arquivo | Função |
|---|---|
| `src/post_news/feed.py` | Descobre/parseia os feeds RSS/Atom e deduplica |
| `src/post_news/generate.py` | Gera o texto PT-BR e os slides do carrossel (JSON) via Gemini |
| `src/post_news/render.py` | Tema HTML/CSS comum; HTML→PDF (WeasyPrint) e PDF→PNG (PyMuPDF) |
| `src/post_news/image.py` | Renderiza o card único (PNG) |
| `src/post_news/carousel.py` | Renderiza o carrossel (PDF multipágina) |
| `src/post_news/github_issues.py` | Cria/atualiza issues e faz o parse do rascunho |
| `src/post_news/linkedin.py` | Sobe imagem/documento e publica o post no LinkedIn |
| `src/post_news/run_detect.py` | Orquestra a detecção (usado pelo `detect.yml`) |
| `src/post_news/run_publish.py` | Publica uma issue aprovada (usado pelo `publish.yml`) |
| `src/post_news/run_regenerate.py` | Regera o texto de uma issue (usado pelo `regenerate.yml`) |
| `src/post_news/run_revise.py` | Revisa o texto via comentário `/revisar` (usado pelo `revise.yml`) |
| `scripts/linkedin_oauth.py` | Obtém token + URN do LinkedIn (passo único, local) |

## Dependências

`requirements.txt`: `requests`, `weasyprint`, `pymupdf`, `pygments`.

> O WeasyPrint depende de bibliotecas nativas (Pango/Cairo). No CI, o `detect.yml`
> as instala no runner (`apt-get install libpango-1.0-0 libpangoft2-1.0-0`). Para rodar
> a renderização localmente, instale-as no seu SO (veja a documentação do WeasyPrint).

## Setup (passo único)

### 1. Chave do Gemini
Crie uma API key gratuita no [Google AI Studio](https://aistudio.google.com/apikey).

### 2. App do LinkedIn + token
1. Crie um app em https://www.linkedin.com/developers/apps
2. Adicione os produtos **"Share on LinkedIn"** e **"Sign In with LinkedIn using OpenID Connect"**.
3. Em **Auth**, adicione a Redirect URL `http://localhost:8000/callback`.
4. Rode o helper localmente para obter o token e o seu URN:
   ```bash
   pip install -r requirements.txt
   LINKEDIN_CLIENT_ID=xxx LINKEDIN_CLIENT_SECRET=yyy python scripts/linkedin_oauth.py
   ```
   Ele imprime `LINKEDIN_ACCESS_TOKEN` e `LINKEDIN_AUTHOR_URN`.

### 3. Secrets do repositório
Em **Settings → Secrets and variables → Actions → Secrets**, crie:
- `GEMINI_API_KEY`
- `LINKEDIN_ACCESS_TOKEN`
- `LINKEDIN_AUTHOR_URN`

(Opcional, em **Variables**: `GEMINI_MODEL`, `LINKEDIN_VERSION`.)

#### Fallback de geração (opcional)
Se o Gemini falhar (ex.: 429/cota), o texto pode ser gerado por um **endpoint LLM
compatível com OpenAI** configurado como fallback — **só** quando o Gemini falha e com
**teto de chamadas por execução** (controle de custo). As variáveis correspondentes ficam
em `src/post_news/config.py`; sem elas, o fallback permanece desligado.

> ⚠️ **Token do LinkedIn expira em ~60 dias.** Quando expirar, rode o helper de novo
> (ou implemente a renovação via refresh token) e atualize o secret.

### 4. Ative os workflows
Os workflows ficam disponíveis na aba **Actions** assim que estão no repositório. As
labels (`pending-approval`, `approved`, `rejected`, `published`, `carrossel`) são criadas
automaticamente na primeira execução.

## Testar localmente

```bash
pip install -r requirements.txt
export PYTHONPATH=src

# 1. Feeds (não precisa de credenciais): mostra feeds resolvidos, entradas e dedupe
python -m post_news.feed

# 2. Card e carrossel de teste (precisa das libs nativas do WeasyPrint)
python -m post_news.image "Novo recurso de tabelas gerenciadas"
python -m post_news.carousel "Novo recurso de tabelas gerenciadas"

# 3. Plano de detecção, sem criar issue (não chama o Gemini)
python -m post_news.run_detect --dry-run --limit 1
```

## Operação

- **Rodar a detecção manualmente**: Actions → workflow de detecção (`detect.yml`) → *Run workflow*
  (há opções de `dry_run` e `limit`).
- **Backfill (recuperar histórico recente)**: no mesmo *Run workflow*, marque `backfill`
  e ajuste `days` (padrão 14) e `per_brand` (padrão 5). Cria até N issues por marca dos
  últimos D dias, **ignorando o baseline**; o restante é marcado como visto. Use uma vez
  ao adicionar feeds novos para "puxar" as novidades recentes sem enxurrada.
- **Publicar**: abra a issue do rascunho, ajuste o texto se quiser, e adicione a label `approved`.
  Para sair como **carrossel** (PDF), adicione **também** a label `carrossel` (antes/junto de
  `approved`); sem ela, publica como imagem única. A fonte entra como **1º comentário** do post
  (config. `LINK_PLACEMENT`).
- **Revisar o texto comentando na issue**: comente `/revisar <seu ajuste>` na própria issue
  (ex.: `/revisar deixa mais técnico e tira a pergunta do final`). O modelo reescreve o post
  **atual** aplicando seu comentário e responde com o novo texto. Pode repetir quantas vezes
  quiser — cada `/revisar` parte do texto mais recente. O card e a fonte são preservados.
- **Regerar o texto** do zero (com o prompt padrão): Actions → workflow de regeneração (`regenerate.yml`).
- O estado fica em `state/seen.json` (chaves vistas + marcas já baselined).

## Adicionar/editar feeds (multi-marca)

As fontes ficam em **`feeds.json`** na raiz — edite pela interface do GitHub (sem mexer em código).
Cada item:

```json
{
  "brand": "GitHub Copilot",        // nome do produto: card, título e texto do post
  "tag": "GitHub",                  // badge curto no card (opcional)
  "feed_url": "https://github.com/github/copilot/releases.atom",
  "page_url": null,                  // alternativa: descobre o RSS a partir da página
  "feed_candidates": []              // URLs candidatas (fallback)
}
```

- Use `feed_url` quando souber a URL do RSS/Atom; senão `page_url` (auto-descoberta) + `feed_candidates`.
- **Dica**: repositórios do GitHub têm sempre um feed Atom em `.../releases.atom`.
- O campo `hashtags` ainda é aceito por compatibilidade, mas **não é usado** nos posts (a geração
  passou a não usar hashtags com a atualização para o algoritmo de 2026).
- Ao adicionar uma marca nova, a primeira execução faz **baseline** dela (marca o histórico
  como visto, sem criar issues) — só os lançamentos seguintes viram posts. Sem enxurrada.

## Notas

- **Multi-marca**: as fontes são definidas em `feeds.json`. A mesma novidade que aparece em
  mais de um feed gera **uma única** issue (dedupe por título + data).
- **Custo zero**: GitHub Actions (free tier), Issues, Gemini (free tier) e renderização local
  das imagens; publicação via LinkedIn Consumer tier (`w_member_social`).
