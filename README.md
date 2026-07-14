# Fang

Crawler paralelo que vasculha um site inteiro e fisga só as URLs com parâmetros que importam.

Fang percorre um domínio de forma recursiva, seguindo todos os links que encontra, usa `sitemap.xml` para acelerar a descoberta, respeita `robots.txt` (incluindo `Crawl-delay`), e no final filtra o resultado para entregar apenas URLs de conteúdo real — sem lixo de CSS, JS, fontes ou assets de CDN.

## Por que usar

Sites grandes escondem parâmetros de URL em milhares de páginas (`?id=`, `?map=`, `?page=`, `.php?id=`). Encontrar isso manualmente é lento. Fang faz isso automaticamente, em paralelo, e entrega uma lista limpa e organizada — útil para mapeamento de superfície, QA, SEO técnico ou levantamento de parâmetros para testes.

## Recursos

- Crawling paralelo com múltiplas threads (rápido mesmo em sites grandes)
- Descoberta via `sitemap.xml`, incluindo sitemap index aninhado
- Respeita `robots.txt`, incluindo a diretiva `Crawl-delay`
- Filtro automático de arquivos estáticos e CDNs de assets (CSS, JS, fontes, imagens, build systems)
- Deduplicação inteligente: agrupa URLs com o mesmo padrão de parâmetro (`?id=1`, `?id=2`, `?id=3`...) e mostra uma amostra em vez de centenas de linhas repetidas
- Salva progresso parcial se o processo for interrompido com `Ctrl+C`
- Gera dois arquivos de saída: uma amostra deduplicada e a lista completa

## Requisitos

- Python 3.8 ou superior
- Dependências: `requests`, `beautifulsoup4`

```bash
pip install requests beautifulsoup4
```

## Instalação

```bash
git clone <url-do-repositorio>
cd fang
pip install -r requirements.txt
```

## Uso básico

```bash
python3 fang.py cisco.com
```

Você pode passar o domínio com ou sem esquema — `cisco.com` e `https://cisco.com` funcionam da mesma forma.

## Exemplos

Crawling rápido com mais threads e limite maior de páginas:

```bash
python3 fang.py cisco.com --max-pages 500 --workers 30
```

Ignorando `robots.txt` (use apenas com autorização explícita do site):

```bash
python3 fang.py cisco.com --ignore-robots
```

Sem deduplicação, mostrando todas as URLs encontradas:

```bash
python3 fang.py cisco.com --sample-per-pattern 0
```

Execução silenciosa, sem log de progresso no terminal:

```bash
python3 fang.py cisco.com --quiet
```

## Opções disponíveis

| Opção | Padrão | Descrição |
|---|---|---|
| `site` | — | Domínio ou URL inicial (obrigatório). Ex: `cisco.com` ou `https://cisco.com` |
| `--max-pages` | `200` | Número máximo de páginas a visitar durante o crawling |
| `--workers` | `20` | Número de threads paralelas usadas para requisições |
| `--timeout` | `10` | Timeout de cada requisição HTTP, em segundos |
| `--output` | `urls_com_parametros.txt` | Nome do arquivo de saída com a amostra deduplicada |
| `--ignore-robots` | desativado | Ignora as regras do `robots.txt` do site |
| `--no-sitemap` | desativado | Desativa a busca por `sitemap.xml` |
| `--sample-per-pattern` | `10` | Máximo de URLs mantidas por padrão de parâmetro repetido. Use `0` para desativar a deduplicação e ver a lista completa |
| `--quiet` | desativado | Não imprime o progresso do crawling no terminal |

## Saída

Ao final da execução, Fang gera dois arquivos:

- **`urls_com_parametros.txt`** — amostra deduplicada, pronta para leitura e análise rápida
- **`urls_com_parametros_completo.txt`** — lista completa, sem nenhuma URL descartada

Além disso, o terminal mostra um resumo com os padrões de parâmetro mais frequentes encontrados no site:

```
Principais padrões encontrados (caminho + parâmetros -> quantidade):
     48x  /produto  [id]
     12x  /busca  [q, page]
      3x  /faq  [map]
```

## Como funciona

1. Fang recebe o domínio inicial e monta a URL de partida
2. Busca o `robots.txt` do site e carrega as regras de permissão e o `Crawl-delay`, se houver
3. Busca o `sitemap.xml` (e sitemaps aninhados) para semear a fila de páginas a visitar
4. Distribui as URLs entre várias threads, que baixam as páginas em paralelo
5. Cada página baixada é analisada em busca de novos links (`<a>`, `<link>`, `<form>`)
6. Cada link novo passa por um filtro: precisa ser do mesmo domínio, não pode ser um arquivo estático (CSS, JS, imagem, fonte) e não pode bater com padrões conhecidos de CDN/build system
7. Links aprovados voltam para a fila e o processo se repete até não haver mais páginas novas ou o limite `--max-pages` ser atingido
8. No final, o conjunto de URLs coletadas é filtrado para manter apenas as que possuem parâmetros na query string, agrupadas por padrão e salvas em disco

## Interrompendo a execução

É seguro apertar `Ctrl+C` a qualquer momento. Fang finaliza as threads em andamento e salva o progresso já coletado até aquele ponto, avisando que o resultado é parcial.

## Aviso

Fang faz requisições reais ao site informado. Use apenas em domínios que você tem autorização para varrer. Respeite os limites definidos pelo próprio site em seu `robots.txt` e ajuste `--workers` e `--timeout` para não sobrecarregar o servidor de terceiros.

## Licença

Defina a licença do seu projeto aqui (MIT, Apache 2.0, etc).
