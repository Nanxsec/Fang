import argparse
import queue
import sys
import threading
import time
import urllib.robotparser
from urllib.parse import urljoin, urlparse, urlsplit
import datetime
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; URLParamCrawler/1.0; +https://example.com/bot)"
}

# Extensões de arquivos estáticos que NÃO são páginas de conteúdo
STATIC_EXTENSIONS = (
    ".css", ".js", ".mjs", ".map",
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".bmp", ".avif",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".mp4", ".mp3", ".avi", ".mov", ".webm", ".wav",
    ".zip", ".rar", ".7z", ".gz", ".tar",
    ".xml", ".rss", ".txt",
)

# Trechos de URL que indicam recurso de build/CDN/asset (não é conteúdo navegável)
JUNK_URL_PATTERNS = (
    "/_v/",           # VTEX asset/build system (/_v/public/...)
    "vtexassets.com",  # CDN de assets da VTEX
    "/arquivos/",
    "/dyn/",
    "/api/",
    "/assets/",
    "/static/",
    "sitemap.xml",
    "/fonts/",
)


def is_clean_content_url(url, root_netloc):
    """
    True se a URL for uma página de conteúdo real do domínio alvo:
    - mesmo domínio raiz (não CDN/subdomínio externo tipo vtexassets.com)
    - não é arquivo estático (css/js/imagem/fonte/etc)
    - não bate com padrões conhecidos de build/asset system
    """
    if not same_domain(url, root_netloc):
        return False

    lower_url = url.lower()
    path = urlparse(url).path.lower()

    if path.endswith(STATIC_EXTENSIONS):
        return False

    if any(pattern in lower_url for pattern in JUNK_URL_PATTERNS):
        return False

    return True


def normalize_url(base_url, link):
    """Resolve URL relativa para absoluta e remove fragment (#...)."""
    if not link:
        return None
    absolute = urljoin(base_url, link)
    parsed = urlsplit(absolute)
    cleaned = parsed._replace(fragment="")
    return cleaned.geturl()


def same_domain(url, root_netloc):
    """Verifica se a URL pertence ao mesmo domínio raiz (incluindo subdomínios)."""
    netloc = urlparse(url).netloc.lower()
    root = root_netloc.lower().split(":")[0]
    root_bare = root[4:] if root.startswith("www.") else root
    return netloc == root or netloc == root_bare or netloc.endswith("." + root_bare)


def has_query_params(url):
    return bool(urlparse(url).query)


class RobotsChecker:
    """Carrega e consulta o robots.txt do domínio uma única vez, de forma thread-safe."""

    def __init__(self, session, base_url, timeout, user_agent, respect_robots=True):
        self.respect_robots = respect_robots
        self.rp = None
        if not respect_robots:
            return
        parsed = urlparse(base_url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        self.rp = urllib.robotparser.RobotFileParser()
        try:
            resp = session.get(robots_url, timeout=timeout)
            if resp.status_code == 200:
                self.rp.parse(resp.text.splitlines())
            else:
                # sem robots.txt (404 etc) -> permite tudo
                self.rp.parse([])
        except requests.RequestException:
            self.rp.parse([])
        self.user_agent = user_agent

    def can_fetch(self, url):
        if not self.respect_robots or self.rp is None:
            return True
        try:
            return self.rp.can_fetch(self.user_agent, url)
        except Exception:
            return True


class Crawler:
    def __init__(self, start_url, max_pages=200, workers=20, timeout=10,
                 respect_robots=True, verbose=True):
        self.start_url = start_url
        self.max_pages = max_pages
        self.workers = workers
        self.timeout = timeout
        self.verbose = verbose

        parsed_start = urlparse(start_url)
        self.root_netloc = parsed_start.netloc

        self.visited = set()
        self.visited_lock = threading.Lock()

        self.all_urls_found = set()
        self.found_lock = threading.Lock()

        self.q = queue.Queue()
        self.q.put(start_url)
        with self.visited_lock:
            self.visited.add(start_url)

        # sessão com pool de conexões grande, compartilhada entre threads (thread-safe no requests)
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        adapter = HTTPAdapter(pool_connections=workers, pool_maxsize=workers, max_retries=1)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

        self.robots = RobotsChecker(
            self.session, start_url, timeout,
            DEFAULT_HEADERS["User-Agent"], respect_robots=respect_robots
        )

        self.pages_done = 0
        self.pages_done_lock = threading.Lock()
        self.stop_flag = threading.Event()

    def _limit_reached(self):
        with self.pages_done_lock:
            return self.pages_done >= self.max_pages

    def _worker(self):
        while not self.stop_flag.is_set():
            try:
                url = self.q.get(timeout=1)
            except queue.Empty:
                return

            try:
                if self._limit_reached():
                    self.stop_flag.set()
                    continue

                if not self.robots.can_fetch(url):
                    if self.verbose:
                        print(f"[ROBOTS-BLOQUEADO] {url}")
                    continue

                try:
                    resp = self.session.get(url, timeout=self.timeout, allow_redirects=True)
                except requests.RequestException as e:
                    if self.verbose:
                        print(f"[ERRO] {url} -> {e}", file=sys.stderr)
                    continue

                content_type = resp.headers.get("Content-Type", "")
                if "text/html" not in content_type:
                    continue

                with self.pages_done_lock:
                    self.pages_done += 1
                    done_count = self.pages_done

                if self.verbose:
                    print(f"\033[1m[\033[m\033[1;35m{datetime.datetime.now().strftime('%H:%M:%S')}\033[m\033[1m]\033[m \033[1m[\033[m\033[1;32mCRAWL]\033[m \033[1m(\033[m\033[1;31m{done_count}/{self.max_pages}\033[m\033[1m)\033[m {url} -> \033[32m{resp.status_code}\033[m")

                if resp.status_code >= 400:
                    continue

                soup = BeautifulSoup(resp.text, "html.parser")
                links = []
                for tag in soup.find_all(["a", "link"], href=True):
                    links.append(tag["href"])
                for tag in soup.find_all(["form"], action=True):
                    links.append(tag["action"])

                for href in links:
                    new_url = normalize_url(url, href)
                    if not new_url or not new_url.startswith(("http://", "https://")):
                        continue

                    is_clean = is_clean_content_url(new_url, self.root_netloc)

                    # só guarda no resultado final se for URL de conteúdo limpa
                    if is_clean:
                        with self.found_lock:
                            self.all_urls_found.add(new_url)

                    # só enfileira para crawling se for do domínio e não for asset estático
                    # (mesmo que tenha caído em algum JUNK_URL_PATTERN, ainda pode valer
                    # seguir o link se for mesmo domínio e não for arquivo estático,
                    # mas por padrão seguimos apenas URLs limpas para não desperdiçar requisições)
                    if is_clean:
                        with self.visited_lock:
                            if new_url not in self.visited and len(self.visited) < self.max_pages * 3:
                                self.visited.add(new_url)
                                self.q.put(new_url)
            finally:
                self.q.task_done()

    def run(self):
        threads = []
        for _ in range(self.workers):
            t = threading.Thread(target=self._worker, daemon=True)
            t.start()
            threads.append(t)

        # espera até a fila esvaziar (todos processados) ou até o limite ser atingido
        while any(t.is_alive() for t in threads):
            if self.stop_flag.is_set():
                break
            time.sleep(0.2)
            if self.q.unfinished_tasks == 0:
                break

        self.stop_flag.set()
        for t in threads:
            t.join(timeout=2)

        return self.all_urls_found, self.pages_done


def main():
    parser = argparse.ArgumentParser(description="Crawler paralelo que coleta URLs com parâmetros de um site.")
    parser.add_argument("site", help="Domínio ou URL inicial, ex: cisco.com ou https://cisco.com")
    parser.add_argument("--max-pages", type=int, default=200, help="Número máximo de páginas a visitar (padrão: 200)")
    parser.add_argument("--workers", type=int, default=20, help="Número de threads paralelas (padrão: 20)")
    parser.add_argument("--timeout", type=int, default=10, help="Timeout de cada requisição em segundos")
    parser.add_argument("--output", default="urls_com_parametros.txt", help="Arquivo de saída")
    parser.add_argument("--ignore-robots", action="store_true", help="Ignora as regras do robots.txt")
    parser.add_argument("--quiet", action="store_true", help="Não imprime o progresso do crawling")
    args = parser.parse_args()

    site = args.site
    if not site.startswith(("http://", "https://")):
        site = "https://" + site

    print(f"Iniciando crawling paralelo em: {site}")
    print(f"Workers: {args.workers} | Max pages: {args.max_pages} | Respeitar robots.txt: {not args.ignore_robots}\n")

    start_time = time.time()

    crawler = Crawler(
        site,
        max_pages=args.max_pages,
        workers=args.workers,
        timeout=args.timeout,
        respect_robots=not args.ignore_robots,
        verbose=not args.quiet,
    )
    all_urls, pages_done = crawler.run()

    elapsed = time.time() - start_time

    urls_com_parametros = sorted(u for u in all_urls if has_query_params(u))

    print("\n" + "=" * 60)
    print(f"Tempo total: {elapsed:.1f}s")
    print(f"Páginas visitadas: {pages_done}")
    print(f"URLs únicas encontradas: {len(all_urls)}")
    print(f"URLs com parâmetros: {len(urls_com_parametros)}")
    print("=" * 60 + "\n")

    for u in urls_com_parametros:
        print(u)

    with open(args.output, "w", encoding="utf-8") as f:
        for u in urls_com_parametros:
            f.write(u + "\n")

    print(f"\nResultado salvo em: {args.output}")


if __name__ == "__main__":
    main()
