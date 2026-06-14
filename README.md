# post_news

App de **custo zero** que monitora as novidades da documentação da **Databricks**
(release notes de **AWS** e **Azure**), gera um **post para o LinkedIn em português**
(com imagem), e deixa você **revisar e aprovar** antes de publicar na sua conta pessoal.

Tudo roda dentro do GitHub (Actions + Issues) — sem servidor, sem custo recorrente.

## Como funciona

```
RSS Databricks (AWS + Azure)
        │  (cron diário)
        ▼
  detect.yml  ──►  Gemini (texto PT-BR)  +  Pollinations (imagem do card)
        │
        ▼
  Cria uma GitHub Issue (label: pending-approval)  ──►  você recebe a notificação
        │
        │  você revisa, edita o texto se quiser, e adiciona a label "approved"
        ▼
  publish.yml  ──►  posta no LinkedIn  ──►  comenta a URL na issue e fecha
```

- **Gerência e aprovação**: as [Issues](../../issues) do repositório são o seu painel.
  Cada novidade vira uma issue com o texto e a imagem.
- **Notificação**: as notificações nativas do GitHub (e-mail/app) avisam quando há rascunho novo.
- **Aprovar**: adicione a label `approved`. **Descartar**: feche a issue.
- **Editar**: edite o corpo da issue (entre os marcadores `POST:START`/`POST:END`) antes de aprovar.

## Componentes

| Arquivo | Função |
|---|---|
| `src/post_news/feed.py` | Descobre/parseia os feeds RSS (AWS+Azure) e deduplica |
| `src/post_news/generate.py` | Gera o texto PT-BR via Gemini (template em `prompts/post_template.md`) |
| `src/post_news/image.py` | Gera o card via Pollinations (URL pública e determinística) |
| `src/post_news/github_issues.py` | Cria/atualiza issues e faz o parse do rascunho |
| `src/post_news/linkedin.py` | Sobe a imagem e publica o post no LinkedIn |
| `src/post_news/run_detect.py` | Orquestra a detecção (usado pelo `detect.yml`) |
| `src/post_news/run_publish.py` | Publica uma issue aprovada (usado pelo `publish.yml`) |
| `scripts/linkedin_oauth.py` | Obtém token + URN do LinkedIn (passo único, local) |

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

#### Fallback de geração via Databricks (opcional)
Se o Gemini falhar (ex.: 429/cota), o texto pode ser gerado pelos endpoints
OpenAI-compatible do Databricks Model Serving — **só** quando o Gemini falha e com
**teto por execução**. Em **Secrets**: `DATABRICKS_TOKEN` (seu PAT). Em **Variables**:
- `DATABRICKS_BASE_URL` → ex.: `https://adb-116288240407984.4.azuredatabricks.net/serving-endpoints`
- `DATABRICKS_MODEL` → ex.: `databricks-claude-haiku-4-5` (bom custo-benefício; Sonnet/Opus é exagero para um post curto)
- `DATABRICKS_MAX_CALLS` → teto de chamadas por execução (controle de custo).

Custo aproximado com o Haiku: ~US$0,003 por post. Logo `DATABRICKS_MAX_CALLS` ≈ 3× o
limite em centavos por run (20 ≈ US$0,06; 100 ≈ US$0,30). Sem o `DATABRICKS_TOKEN`, o fallback fica desligado.

> ⚠️ **Token do LinkedIn expira em ~60 dias.** Quando expirar, rode o helper de novo
> (ou implemente a renovação via refresh token) e atualize o secret.

### 4. Ative os workflows
Os workflows `Detectar novidades Databricks` e `Publicar no LinkedIn` já ficam
disponíveis na aba **Actions**. As labels são criadas automaticamente na primeira execução.

## Testar localmente

```bash
pip install -r requirements.txt
export PYTHONPATH=src

# 1. Feeds (não precisa de credenciais): mostra feeds resolvidos, entradas e dedupe
python -m post_news.feed

# 2. Imagem (não precisa de credenciais): gera a URL e baixa um PNG de teste
python -m post_news.image "Databricks lança modo real-time no Lakeflow"

# 3. Texto + post completo, sem criar issue (precisa de GEMINI_API_KEY)
GEMINI_API_KEY=xxx python -m post_news.run_detect --dry-run --limit 1
```

## Operação

- **Rodar a detecção manualmente**: Actions → *Detectar novidades Databricks* → *Run workflow*
  (há opções de `dry_run` e `limit`).
- **Backfill (recuperar histórico recente)**: no mesmo *Run workflow*, marque `backfill`
  e ajuste `days` (padrão 14) e `per_brand` (padrão 5). Cria até N issues por marca dos
  últimos D dias, **ignorando o baseline**; o restante é marcado como visto. Use uma vez
  ao adicionar feeds novos para "puxar" as novidades recentes sem enxurrada.
- **Publicar**: abra a issue do rascunho, ajuste o texto se quiser, e adicione a label `approved`.
  O link da documentação entra como **1º comentário** do post (config. `LINK_PLACEMENT`).
- **Revisar o texto comentando na issue**: comente `/revisar <seu ajuste>` na própria issue
  (ex.: `/revisar deixa mais técnico e tira a pergunta do final`). O Gemini reescreve o post
  **atual** aplicando seu comentário e responde com o novo texto. Pode repetir quantas vezes
  quiser — cada `/revisar` parte do texto mais recente. O card e a fonte são preservados.
- **Regerar o texto** do zero (com o prompt padrão): Actions → *Regerar texto de uma issue*.
- O estado fica em `state/seen.json` (chaves vistas + marcas já baselined).

## Adicionar/editar feeds (multi-marca)

As fontes ficam em **`feeds.json`** na raiz — edite pela interface do GitHub (sem mexer em código).
Cada item:

```json
{
  "brand": "GitHub Copilot",        // nome do produto: card, título e texto do post
  "tag": "GitHub",                  // badge curto no card (opcional)
  "feed_url": "https://github.blog/changelog/label/copilot/feed/",
  "page_url": null,                  // alternativa: descobre o RSS a partir da página
  "feed_candidates": [],             // URLs candidatas (fallback)
  "hashtags": ["#GitHubCopilot", "#AI", "#DevTools"]
}
```

- Use `feed_url` quando souber a URL do RSS/Atom; senão `page_url` (auto-descoberta) + `feed_candidates`.
- **Dica**: repositórios do GitHub têm sempre um feed Atom em `.../releases.atom`.
- Ao adicionar uma marca nova, a primeira execução faz **baseline** dela (marca o histórico
  como visto, sem criar issues) — só os lançamentos seguintes viram posts. Sem enxurrada.

## Notas

- Monitoramos **AWS + Azure**; a mesma novidade que aparece nas duas docs gera
  **uma única** issue (dedupe por título + data).
- A marcação da Databricks é feita por texto + hashtag `#Databricks`. A menção por
  entidade (`@Databricks`) exige o URN da organização e pode ser adicionada depois.
- Sem custo: GitHub Actions (free tier), Issues, Pollinations e Gemini (free tiers),
  LinkedIn Consumer tier (`w_member_social`).
