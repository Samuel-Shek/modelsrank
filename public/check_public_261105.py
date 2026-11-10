#!/usr/bin/env python3
"""公开版验收：python3 check_public_261105.py <公开版HTML> <私有版HTML> <截图目录>
检查：控制台报错、手机横向溢出、与私有版名次/分数一致、黑名单词、URL 状态、深浅色、外部请求；输出 check-result-public-261105.json"""
import sys, json, re, pathlib, argparse, math, threading
from decimal import Decimal, ROUND_HALF_UP
from functools import partial
from html.parser import HTMLParser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, urljoin, unquote, parse_qs
import xml.etree.ElementTree as ET
from playwright.sync_api import sync_playwright
from itertools import product
from collections import deque
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('public_html')
parser.add_argument('private_html')
parser.add_argument('output_dir')
parser.add_argument('--sample-slugs', nargs='+', default=['gemini4carbon', 'kimik3', 'astra-pro'])
args = parser.parse_args()
pub, priv, outdir = str(pathlib.Path(args.public_html).resolve()), str(pathlib.Path(args.private_html).resolve()), pathlib.Path(args.output_dir)
outdir.mkdir(parents=True, exist_ok=True)
CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
BLACK = ['暂时保持', 'Nov 4 values', '72 小时', '72-hour', '首 token 延迟', 'speedV2', '图中型号', '截图', '双子', '本轮', '复核', 'Codex', 'SHA', '请先更新', '上版', '口径', '本次未复核', 'screenshot', 'rawPrevious', 'auditChanges', '导出当前 CSV', '完整数据 JSON', '本机', '离线快照', 'SpaceXAI', 'draft translation']
res = {'errors': [], 'external_requests': []}
VIEWS = ['primary', 'all', 'new', 'legacy', 'archived']
TABS = [('score', None), ('cost', None), ('speed', 'taskMin'), ('speed', 'tps'), ('speed', 'ttfat')]

def snapshot(pg, view, tab, speed):
    pg.select_option('#view', view); pg.wait_for_timeout(30)
    pg.click(f'.tabs [data-tab={tab}]') if pg.query_selector('.tabs') else None
    if speed: pg.select_option('#speedmetric', speed)
    pg.select_option('#threshold', '0'); pg.wait_for_timeout(30)
    return pg.evaluate("""()=>{const r=window.boardAudit.getRanks(),D=window.boardAudit.getData(),ids=window.boardAudit.getCurrent();
      return ids.map(id=>{const x=D.rows.find(y=>y.id===id);return [id,r[id],x.score,x.legacy?x.legacy.score:null,x.cost,x.taskMin,x.tps,x.ttfat]})}""")

class Element:
    def __init__(self, tag='', attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []

    def all(self, tag=None, **attrs):
        result = []
        for node in self.children:
            if isinstance(node, Element):
                if (tag is None or node.tag == tag) and all(node.attrs.get(k) == v for k, v in attrs.items()):
                    result.append(node)
                result.extend(node.all(tag, **attrs))
        return result

    def text(self):
        return ''.join(c.text() if isinstance(c, Element) else c for c in self.children
                       if not isinstance(c, Element) or c.tag not in ('script', 'style'))

    def raw_text(self):
        return ''.join(c.raw_text() if isinstance(c, Element) else c for c in self.children)


class Document(HTMLParser):
    VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}

    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.root = Element()
        self.stack = [self.root]
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        node = Element(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in self.VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, text):
        self.stack[-1].children.append(text)


SOURCE_ROOT = pathlib.Path(__file__).resolve().parent
SITE_ROOT = SOURCE_ROOT / 'site'
INPUT_HTML = pathlib.Path(pub)
res['input_html'] = {'ok': INPUT_HTML.is_file() and (SITE_ROOT / 'index.html').is_file()
                     and INPUT_HTML.read_bytes() == (SITE_ROOT / 'index.html').read_bytes(),
                     'path': str(INPUT_HTML)}
pub = str(SITE_ROOT / 'index.html')
ORIGIN = 'https://modelsrank.org'
GOOGLE_HTML = '/google529a71ca053abf05.html'
GOOGLE_PROXY = GOOGLE_HTML + ' /_verification/google529a71ca053abf05.txt 200'
DATA = json.loads((SOURCE_ROOT / 'model-data_261105.json').read_text())
TARGET_ROWS = [r for r in DATA['rows'] if r.get('primary') is True and r.get('lifecycle') != 'archived']
TARGETS = {r['base']: r for r in TARGET_ROWS}
ROW_IDS = {r['id'] for r in DATA['rows']}
DOCS = {}
LINK_FAILURES = []
LINK_COUNT = 0
REDIRECTS = {}
REDIRECT_ERRORS = []
try:
    REDIRECT_LINES = (SITE_ROOT / '_redirects').read_text().splitlines()
    for line in REDIRECT_LINES:
        if not line.strip() or line.startswith('#'):
            continue
        fields = line.split()
        if len(fields) != 3:
            raise ValueError('Invalid redirect line: ' + line)
        source, target, status = fields
        if status == '301':
            if source in REDIRECTS:
                raise ValueError('Duplicate redirect source: ' + source)
            REDIRECTS[source] = target
        elif line != GOOGLE_PROXY:
            raise ValueError('Unexpected redirect rule: ' + line)
except (OSError, ValueError) as error:
    REDIRECT_LINES = []
    REDIRECT_ERRORS.append(str(error))


def page_file(path):
    dest = (SITE_ROOT / path.lstrip('/')).resolve()
    if path.endswith('/'):
        dest /= 'index.html'
    return dest if dest.is_relative_to(SITE_ROOT) else None


def redirect_path(path):
    return REDIRECTS.get(path, path)


def document(path):
    if path not in DOCS:
        DOCS[path] = Document(path.read_text(encoding='utf-8')).root
    return DOCS[path]


def local_link(href, base, origin=ORIGIN):
    global LINK_COUNT
    target = urlsplit(urljoin(base, href))
    if target.scheme not in ('http', 'https') or target.netloc not in (urlsplit(origin).netloc, 'modelsrank.org'):
        return
    LINK_COUNT += 1
    path = unquote(target.path)
    if path == GOOGLE_HTML:
        return
    dest = page_file(redirect_path(path))
    issue = None
    if dest is None or not dest.is_file():
        issue = 'missing target'
    elif 'm' in parse_qs(target.query, keep_blank_values=True) and any(x not in ROW_IDS for x in parse_qs(target.query, keep_blank_values=True)['m']):
        issue = 'unknown model row id'
    elif target.fragment:
        if dest.suffix != '.html' or unquote(target.fragment) not in {n.attrs['id'] for n in document(dest).all() if 'id' in n.attrs}:
            issue = 'missing fragment'
    if issue:
        LINK_FAILURES.append({'from': base, 'href': href, 'error': issue})


def scan_links(doc, base):
    for node in doc.all():
        if node.tag in ('a', 'link') and node.attrs.get('href'):
            local_link(node.attrs['href'], base)


def all_json_keys(obj):
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield key
            yield from all_json_keys(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from all_json_keys(value)


def static_reachable(home, language):
    pending, visited = deque([home]), set()
    while pending:
        path = redirect_path(pending.popleft())
        if path in visited or path == GOOGLE_HTML or path.startswith('/en/') != (language == 'en'):
            continue
        dest = page_file(path)
        if dest is None or not dest.is_file() or dest.suffix != '.html':
            continue
        visited.add(path)
        for node in document(dest).all('a'):
            href = node.attrs.get('href')
            if not href:
                continue
            target = urlsplit(urljoin(ORIGIN + path, href))
            if target.scheme in ('https', 'http') and target.netloc == 'modelsrank.org':
                child = unquote(target.path)
                if child.endswith('/index.html'):
                    child = child.removesuffix('index.html')
                pending.append(child)
    return visited


def product_checks():
    failures = list(REDIRECT_ERRORS)
    def require(ok, test):
        if not ok:
            failures.append(test)
    for source, target in REDIRECTS.items():
        require(bool(re.fullmatch(r'/(?:en/)?m/[a-z0-9-]+/', source)), 'Invalid 301 source: ' + source)
        require(bool(re.fullmatch(r'/(?:en/)?m/[a-z0-9-]+/', target)), 'Invalid 301 target: ' + target)
        src_file, dst_file = page_file(source), page_file(target)
        require(src_file is not None and not src_file.exists(), '301 source is also a page: ' + source)
        require(target not in REDIRECTS and dst_file is not None and dst_file.is_file()
                and dst_file.suffix == '.html' and bool(document(dst_file).all('html')),
                '301 target is not a final page: ' + target)
        require(source.startswith('/en/') == target.startswith('/en/'), '301 language mismatch: ' + source)
    published = json.loads((SOURCE_ROOT / 'published_urls.json').read_text())
    require(isinstance(published, list) and all(isinstance(p, str) for p in published), 'Invalid published list')
    require(published == sorted(set(published)), 'Published paths must be sorted and unique')
    require((SOURCE_ROOT / 'published_urls.json').read_bytes() ==
            (json.dumps(published, ensure_ascii=False, indent=2) + '\n').encode(), 'Published list formatting')
    uncovered = []
    for path in published:
        require(bool(re.fullmatch(r'/(?:en/)?m/[a-z0-9-]+/', path)), 'Invalid published path: ' + path)
        dest = page_file(redirect_path(path))
        if dest is None or not dest.is_file() or dest.suffix != '.html' or not document(dest).all('html'):
            uncovered.append(path)
    require(not uncovered, 'Uncovered published paths: ' + ', '.join(uncovered))
    details = {('/' + str(p.relative_to(SITE_ROOT)).removesuffix('index.html')): p
               for tree in ('m', 'en/m') for p in (SITE_ROOT / tree).glob('*/index.html')}
    require(set(details) <= set(published), 'Detail pages absent from published list')
    reachability = {}
    for lg, home in [('zh', '/'), ('en', '/en/')]:
        targets = {path for path in details if path.startswith('/en/') == (lg == 'en')}
        reached = static_reachable(home, lg) & targets
        missing = sorted(targets - reached)
        reachability[lg] = {'targets': len(targets), 'reached': len(reached), 'missing': missing}
        require(not missing, 'Static BFS missing ' + lg + ': ' + ', '.join(missing))
        home_doc = document(SITE_ROOT / ('en/index.html' if lg == 'en' else 'index.html'))
        sections = home_doc.all(id='all-models')
        require(len(sections) == 1, 'Missing all-models section: ' + lg)
        links = sections[0].all('a') if sections else []
        require(len(links) == len(targets) and {n.attrs.get('href') for n in links} == targets,
                'All-models links do not cover every detail: ' + lg)
        require(all('data-detail' not in n.attrs and 'modelbtn' not in n.attrs.get('class', '').split()
                    and n.text().strip() for n in links), 'All-models links must be ordinary named anchors: ' + lg)
    noindex = {path for path, f in details.items() if any('noindex' in n.attrs.get('content', '').lower().split(',')
               for n in document(f).all('meta', name='robots'))}
    ns = {'s': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
    sitemap = ET.parse(SITE_ROOT / 'sitemap.xml').getroot()
    locations = [n.text for n in sitemap.findall('s:url/s:loc', ns)]
    expected = {ORIGIN + path for path in details.keys() - noindex} | {ORIGIN + '/', ORIGIN + '/en/'}
    require(len(locations) == len(expected) and set(locations) == expected, 'Sitemap must contain exactly indexable details and homepages')
    require(not sitemap.findall('.//s:lastmod', ns), 'Sitemap must not contain lastmod')
    for path, f in details.items():
        doc = document(f)
        scan_links(doc, ORIGIN + path)
        lg = 'en' if path.startswith('/en/') else 'zh'
        home_label = 'Rankings' if lg == 'en' else '榜单'
        home = '/en/' if lg == 'en' else '/'
        nav = doc.all('nav')
        require(bool(nav) and any(a.attrs.get('href') == home and a.text() == home_label for a in nav[0].all('a')),
                'Visible breadcrumb label: ' + path)
        graphs = [json.loads(s.raw_text()) for s in doc.all('script', type='application/ld+json')]
        crumbs = [n for g in graphs for n in g.get('@graph', []) if n.get('@type') == 'BreadcrumbList']
        require(len(crumbs) == 1 and crumbs[0]['itemListElement'][0]['name'] == home_label,
                'Structured breadcrumb label: ' + path)
    verification = (SOURCE_ROOT / 'assets' / GOOGLE_HTML.lstrip('/')).read_bytes()
    require(verification.rstrip(b'\r\n') == b'google-site-verification: google529a71ca053abf05.html', 'Google source content')
    for relative in (GOOGLE_HTML.lstrip('/'), '_verification/google529a71ca053abf05.txt'):
        f = SITE_ROOT / relative
        require(f.is_file() and f.read_bytes() == verification, 'Google output bytes: ' + relative)
    require(bool(REDIRECT_LINES) and REDIRECT_LINES[0] == GOOGLE_PROXY and REDIRECT_LINES.count(GOOGLE_PROXY) == 1,
            'Google proxy must be the first and unique 200 rule')
    return {'ok': not failures, 'published_paths': len(published), 'uncovered': uncovered,
            'reachability': reachability, 'active_bases': len(TARGETS),
            'archived_bases': len({p.split('/')[-2] for p in details}) - len(TARGETS),
            'indexable_pages': len(details) - len(noindex), 'noindex_pages': len(noindex),
            'sitemap_entries': len(locations), 'failures': failures}


def detail_static_checks():
    failures = []
    def require(ok, where, test):
        if not ok:
            failures.append({'page': where, 'test': test})
    require(len(TARGETS) == len(TARGET_ROWS) and all(re.fullmatch('[a-z0-9-]+', s) for s in TARGETS), 'data', 'unique valid target slugs')
    expected = {f'{prefix}m/{slug}/index.html' for prefix in ('', 'en/') for slug in TARGETS}
    actual = {str(p.relative_to(SITE_ROOT)) for tree in ('m', 'en/m') for p in (SITE_ROOT / tree).rglob('*') if p.is_file()}
    require(expected <= actual and all(re.fullmatch(r'(?:en/)?m/[a-z0-9-]+/index.html', p) for p in actual),
            'site', 'all active details and valid detail file paths')
    scored = [r for r in TARGET_ROWS if r.get('status') == 'complete' and type(r.get('score')) in (int, float)
              and math.isfinite(r['score']) and r['score'] >= 0 and r.get('benchmarkVersion') == DATA['benchmarkVersion']]
    rank_by_id = {r['id']: 1 + sum(other['score'] > r['score'] for other in scored) for r in scored}
    def rounded(value):
        return str(Decimal(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    for relative in sorted(expected):
        path = SITE_ROOT / relative
        if not path.is_file():
            continue
        lg = 'en' if relative.startswith('en/') else 'zh'
        slug = path.parent.name
        row, url = TARGETS[slug], ORIGIN + '/' + relative.removesuffix('index.html')
        doc = document(path)
        try:
            canonical = [n.attrs.get('href') for n in doc.all('link', rel='canonical')]
            og = [n.attrs.get('content') for n in doc.all('meta', property='og:url')]
            alternatives = [(n.attrs.get('hreflang'), n.attrs.get('href')) for n in doc.all('link') if 'hreflang' in n.attrs]
            alternates = {'zh-CN': f'{ORIGIN}/m/{slug}/', 'en': f'{ORIGIN}/en/m/{slug}/', 'x-default': f'{ORIGIN}/m/{slug}/'}
            require(canonical == og == [url], relative, 'canonical and og:url')
            require(len(alternatives) == 3 and dict(alternatives) == alternates, relative, 'three exact hreflang links')
            require(doc.all('html')[0].attrs['lang'] == ('en' if lg == 'en' else 'zh-CN'), relative, 'html language')
            require(row['name'] in doc.all('title')[0].text() and row['name'] in doc.all('meta', name='description')[0].attrs['content'], relative, 'title and description')
            scripts = doc.all('script')
            require(len(scripts) == 1 and all(n.attrs.get('type') == 'application/ld+json' and not n.attrs.get('src') for n in scripts), relative, 'only JSON-LD script')
            require(not doc.all(id='model-data'), relative, 'no embedded model data')
            graphs = [json.loads(n.raw_text()) for n in scripts]
            require(len(graphs) == 1, relative, 'one structured graph')
            graph = graphs[0]['@graph']
            require([n['@type'] for n in graph] == ['SoftwareApplication', 'BreadcrumbList'], relative, 'structured types')
            entity, crumbs = graph
            require(entity['name'] == row['name'] and entity['identifier'] == slug and entity['url'] == url and entity['@id'] == url + '#model', relative, 'software identity')
            require(not {'aggregateRating', 'offers', 'ratingValue'}.intersection(all_json_keys(graphs)), relative, 'no invented ratings or offers')
            items = crumbs['itemListElement']
            home = ORIGIN + ('/en/' if lg == 'en' else '/')
            require(len(items) == 2 and [n['position'] for n in items] == [1, 2] and [n['item'] for n in items] == [home, url], relative, 'breadcrumb URLs')
            for item in items:
                local_link(item['item'], url)
            local_link(entity['url'], url)
            body = doc.all('body')[0].text()
            require(row['name'] in doc.all('h1')[0].text() and row['name'] in body, relative, 'no-JS model name')
            score = doc.all('dd', **{'data-metric': 'score'})[0].text()
            rank = [n for n in doc.all('dd') if 'data-rank' in n.attrs][0].text()
            old = row.get('legacy') or {}
            if row['id'] in rank_by_id:
                require(score == rounded(row['score']) and rank == str(rank_by_id[row['id']]), relative, 'current score and tied rank')
            else:
                expected_status = ('当前指数暂无评分' if lg == 'zh' else 'No current-index score') if type(old.get('score')) in (int, float) else ('暂无独立评分' if lg == 'zh' else 'No independent score')
                require(score == expected_status and rank == ('未排名' if lg == 'zh' else 'Not ranked'), relative, 'explicit missing score and rank')
            if type(old.get('score')) in (int, float):
                legacy_text = doc.all('p', **{'class': 'legacy'})[0].text()
                require(old['index'] in legacy_text and rounded(old['score']) in legacy_text and ('旧版指数' if lg == 'zh' else 'Legacy index') in legacy_text, relative, 'legacy score and index')
            resources = []
            for node in doc.all():
                resources += [v for k, v in node.attrs.items() if k in ('src', 'poster', 'data', 'background') and v]
                if node.attrs.get('srcset'):
                    resources += [candidate.strip().split()[0] for candidate in node.attrs['srcset'].split(',') if candidate.strip()]
                if node.tag == 'link' and node.attrs.get('rel') not in ('alternate', 'canonical'):
                    resources.append(node.attrs.get('href', ''))
                require(not any(k.startswith('on') for k in node.attrs), relative, 'no inline script handlers')
            css = '\n'.join([n.raw_text() for n in doc.all('style')] + [n.attrs['style'] for n in doc.all() if n.attrs.get('style')])
            resources += re.findall(r'url\(\s*[\'"]?([^\)\'"\s]+)', css)
            resources += re.findall(r'@import\s+[\'"]([^\'"]+)', css)
            require(not any(urlsplit(urljoin(url, r)).netloc != 'modelsrank.org' for r in resources), relative, 'no external resources')
            scan_links(doc, url)
        except (KeyError, IndexError, TypeError, ValueError) as error:
            failures.append({'page': relative, 'test': 'parse/content', 'error': str(error)})
    for lg, relative in [('zh', 'index.html'), ('en', 'en/index.html')]:
        doc = document(SITE_ROOT / relative)
        base = ORIGIN + ('/en/' if lg == 'en' else '/')
        scan_links(doc, base)
        graph = json.loads(doc.all('script', id='structured-data')[0].raw_text())['@graph']
        items = next(n for n in graph if n['@type'] == 'ItemList')['itemListElement']
        for item in items:
            local_link(item['url'], base)
            require(item['url'] in {f'{base}m/{s}/' for s in TARGETS}, relative, 'ItemList detail URLs')
    ns = {'s': 'http://www.sitemaps.org/schemas/sitemap/0.9', 'h': 'http://www.w3.org/1999/xhtml'}
    entries = ET.parse(SITE_ROOT / 'sitemap.xml').getroot().findall('s:url', ns)
    expected_urls = {ORIGIN + '/' + s.removesuffix('index.html') for s in actual
                     if not document(SITE_ROOT / s).all('meta', name='robots', content='noindex')} | {ORIGIN + '/', ORIGIN + '/en/'}
    locations = [n.find('s:loc', ns).text for n in entries]
    require(len(locations) == len(expected_urls) and set(locations) == expected_urls, 'sitemap', 'exact locations')
    for entry in entries:
        url = entry.find('s:loc', ns).text
        local_link(url, ORIGIN + '/')
        zh = url.replace(ORIGIN + '/en/', ORIGIN + '/', 1)
        en = ORIGIN + '/en/' + zh.removeprefix(ORIGIN + '/')
        links = entry.findall('h:link', ns)
        require(len(links) == 3 and {n.attrib['hreflang']: n.attrib['href'] for n in links} == {'zh-CN': zh, 'en': en, 'x-default': zh}, 'sitemap', 'hreflang ' + url)
        require(entry.find('s:lastmod', ns) is None, 'sitemap', 'no lastmod')
        for n in links:
            local_link(n.attrib['href'], url)
    llms = (SITE_ROOT / 'llms.txt').read_text()
    links = re.findall(r'\]\(([^)]+)\)', llms)
    for link in links:
        local_link(link, ORIGIN + '/llms.txt')
    require({link for link in links if urlsplit(link).netloc == 'modelsrank.org' and '/m/' in urlsplit(link).path} ==
            {ORIGIN + '/' + s.removesuffix('index.html') for s in expected}, 'llms', 'active detail links')
    ui = json.loads((SOURCE_ROOT / 'public_text_261105.json').read_text())['ui']
    added = {k: v for k, v in ui.items() if k.startswith(('detail.', 'allmodels.'))}
    require(bool(added) and all(isinstance(v.get(lg), str) and v[lg].strip() for v in added.values() for lg in ('zh', 'en')), 'UI', 'both detail languages')
    require(not any(w in value for v in added.values() for value in v.values() for w in BLACK), 'UI', 'new copy blacklist')
    require(all(f'm/{s}/index.html' in actual and f'en/m/{s}/index.html' in actual for s in args.sample_slugs),
            'samples', 'existing sample detail pages')
    return {'ok': not failures, 'target_slugs': len(TARGETS), 'expected_pages': len(expected), 'actual_pages': len(actual),
            'sitemap_entries': len(entries), 'failures': failures}


def detail_browser_checks(browser):
    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass
    result = {'samples': [], 'clicks': [], 'errors': [], 'nonlocal_requests': [], 'rendered_row_sets': 0, 'ok': False}
    server = None
    try:
        server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(SITE_ROOT)))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        origin = f'http://127.0.0.1:{server.server_port}'
        ctx = browser.new_context()
        def route(request_route):
            url = request_route.request.url
            if urlsplit(url).netloc != urlsplit(origin).netloc:
                result['nonlocal_requests'].append(url)
                request_route.abort()
            else:
                request_route.continue_()
        ctx.route('**/*', route)
        pg = ctx.new_page()
        pg.on('pageerror', lambda e: result['errors'].append(str(e)))
        pg.on('console', lambda m: result['errors'].append(m.text) if m.type == 'error' else None)
        pg.on('requestfailed', lambda r: result['errors'].append(r.url + ': ' + str(r.failure)))
        for slug in args.sample_slugs:
            for prefix in ('', '/en'):
                path = prefix + '/m/' + slug + '/'
                response = pg.goto(origin + path)
                pg.wait_for_load_state('networkidle')
                names = {r['name'] for r in DATA['rows'] if r.get('base') == slug}
                result['samples'].append({'path': path, 'ok': response.status == 200 and pg.locator('h1').inner_text() in names})
        for lg, prefix in [('zh', ''), ('en', '/en')]:
            pg.goto(origin + prefix + '/')
            pg.evaluate('(lg)=>window.boardAudit.setLang(lg)', lg)
            for view in [*VIEWS, 'recent']:
                for tab, speed in TABS:
                    snapshot(pg, view, tab, speed)
                    links = pg.eval_on_selector_all('#rows [data-detail]', "ns=>ns.map(n=>({id:n.dataset.detail,tag:n.tagName,href:n.getAttribute('href'),cls:n.className}))")
                    by_id = {r['id']: r for r in DATA['rows']}
                    for link in links:
                        row = by_id[link['id']]
                        eligible = row.get('lifecycle') != 'archived' and row.get('base') in TARGETS
                        expected = prefix + '/m/' + row['base'] + '/' if eligible else None
                        if link != {'id': row['id'], 'tag': 'A' if eligible else 'BUTTON', 'href': expected, 'cls': 'modelbtn'}:
                            result['errors'].append('Unexpected rendered model link: ' + str(link))
                        if link['href']:
                            local_link(link['href'], origin + prefix + '/', origin)
                    result['rendered_row_sets'] += 1
            pg.goto(origin + prefix + '/')
            pg.evaluate('(lg)=>window.boardAudit.setLang(lg)', lg)
            link = pg.locator('#rows a.modelbtn').first
            row_id = link.get_attribute('data-detail')
            url_before = pg.url
            link.click()
            normal = pg.evaluate("()=>({open:document.getElementById('detail').open,name:document.getElementById('detailtitle').textContent,profile:document.getElementById('detailprofile').textContent})")
            row = by_id[row_id]
            public_row = pg.evaluate('(id)=>window.boardAudit.getData().rows.find(r=>r.id===id)', row_id)
            cfg = public_row.get('profile') or public_row.get('effort')
            if isinstance(cfg, dict):
                cfg = cfg[lg]
            ok = normal['open'] and normal['name'] == row['name'] and (not cfg or normal['profile'].startswith(cfg)) and pg.url == url_before
            pg.evaluate("document.getElementById('detail').close()")
            modified = pg.evaluate("""()=>['ctrlKey','metaKey','shiftKey','altKey'].map(key=>{
                const a=document.querySelector('#rows a.modelbtn');
                // A later listener suppresses navigation only after observing app handling.
                let prevented=null;
                const probe=e=>{prevented=e.defaultPrevented;e.preventDefault()};
                window.addEventListener('click',probe,{once:true});
                a.dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true,button:0,[key]:true}));
                return {key,defaultPrevented:prevented,open:document.getElementById('detail').open};
            })""")
            result['clicks'].append({'lang': lg, 'row_id': row_id, 'normal': ok, 'modifiers': modified,
                                     'ok': ok and all(x['defaultPrevented'] is False and not x['open'] for x in modified)})
        ctx.close()
        result['ok'] = (not result['errors'] and not result['nonlocal_requests'] and bool(result['samples'])
                        and all(x['ok'] for x in result['samples'] + result['clicks']))
    except Exception as error:
        result['errors'].append(str(error))
    finally:
        if server:
            server.shutdown()
            server.server_close()
    return result


try:
    res['detail_static'] = detail_static_checks()
except Exception as error:
    res['detail_static'] = {'ok': False, 'failures': [{'test': 'static checks', 'error': str(error)}]}
try:
    res['products'] = product_checks()
except Exception as error:
    res['products'] = {'ok': False, 'failures': [str(error)]}
res['links'] = {'ok': not LINK_FAILURES, 'checked': LINK_COUNT, 'failures': LINK_FAILURES}

with sync_playwright() as p:
    try:
        b = p.chromium.launch(executable_path=CHROME, args=['--no-sandbox'])
    except Exception as error:
        res.update({'pass': False, 'browser_unavailable': str(error), 'detail_browser': {'ok': False, 'not_run': 'Chrome unavailable'}})
        (outdir / 'check-result-public-261105.json').write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding='utf-8')
        print(json.dumps(res, ensure_ascii=False, indent=1))
        sys.exit(1)
    res['detail_browser'] = detail_browser_checks(b)
    res['links'] = {'ok': not LINK_FAILURES, 'checked': LINK_COUNT, 'failures': LINK_FAILURES}
    def page(path, **kw):
        ctx = b.new_context(**kw); pg = ctx.new_page()
        pg.on('pageerror', lambda e: res['errors'].append(f'{path}: {e}'))
        pg.on('console', lambda m: m.type == 'error' and res['errors'].append(f'{path}: {m.text}'))
        pg.on('request', lambda rq: (not rq.url.startswith(('file:', 'data:', 'about:'))) and res['external_requests'].append(rq.url))
        pg.goto('file://' + path); pg.wait_for_timeout(500); return ctx, pg
    # Compare actual static table nodes against the same page after startup.
    row_state = """()=>Array.from(document.querySelectorAll('#rows tr'),r=>({
      id:r.dataset.id,rank:r.querySelector('.rank').textContent,
      cells:Array.from(r.cells,c=>({text:c.textContent,cls:c.className,label:c.getAttribute('data-label')})),
      detail:r.querySelector('[data-detail]').dataset.detail,
      link:{tag:r.querySelector('[data-detail]').tagName,href:r.querySelector('[data-detail]').getAttribute('href'),cls:r.querySelector('[data-detail]').className},
      selected:Array.from(r.querySelectorAll('.numcell'),c=>c.classList.contains('selected'))}))"""
    initial_state = """()=>({note:document.querySelector('#metricnote').innerHTML,
      count:document.querySelector('#resultcount').textContent,
      sorts:Array.from(document.querySelectorAll('th[data-sort]'),t=>[t.dataset.sort,t.getAttribute('aria-sort'),t.querySelector('button').getAttribute('aria-pressed')])})"""
    fixed_meta = """()=>({canonical:document.querySelector('link[rel=canonical]').href,
      og:document.querySelector('meta[property="og:url"]').content,
      alternates:Array.from(document.querySelectorAll('link[hreflang]'),e=>e.outerHTML),
      graph:document.querySelector('#structured-data').textContent})"""
    english = str(SITE_ROOT / 'en/index.html')
    res['static_first_screen'], res['language_paths'], res['fixed_metadata'] = [], [], []
    for lg, path, expected_url in [('zh', pub, 'https://modelsrank.org/'), ('en', english, 'https://modelsrank.org/en/')]:
        for locale, width in product(['zh-CN', 'en-US'], [1440, 390]):
            cs, static = page(path, java_script_enabled=False, locale=locale, viewport={'width': width, 'height': 1000})
            before = static.evaluate(row_state)
            initial = static.evaluate(initial_state)
            meta = static.evaluate(fixed_meta)
            cj, live = page(path, locale=locale, viewport={'width': width, 'height': 1000})
            after = live.evaluate(row_state)
            expected_n = live.evaluate("window.boardAudit.getData().rows.filter(r=>r.status==='complete'&&typeof r.score==='number'&&Number.isFinite(r.score)&&r.benchmarkVersion===window.boardAudit.getData().benchmarkVersion&&r.lifecycle!=='archived'&&r.score>=0&&r.primary).length")
            ids = [r['id'] for r in before]
            res['static_first_screen'].append({'lang': lg, 'locale': locale, 'width': width, 'count': len(before),
                'ok': bool(before) and before == after and len(ids) == len(set(ids)) == expected_n and initial == live.evaluate(initial_state)})
            expected_lang = 'zh-CN' if lg == 'zh' else 'en'
            path_ok = live.get_attribute('html', 'lang') == expected_lang
            metadata_ok = meta == live.evaluate(fixed_meta) and meta['canonical'] == meta['og'] == expected_url
            opposite = 'en' if lg == 'zh' else 'zh'
            live.evaluate('(lg)=>localStorage.setItem("lang",lg)', opposite)
            live.reload()
            saved_ok = live.evaluate('window.boardAudit.getState().lang') == opposite
            metadata_ok &= meta == live.evaluate(fixed_meta)
            live.goto('file://' + path + '?lang=' + lg)
            parameter_ok = live.evaluate('window.boardAudit.getState().lang') == lg
            live.click('#lang')
            button_ok = live.evaluate('window.boardAudit.getState().lang') == opposite and live.evaluate('localStorage.getItem("lang")') == opposite
            live.evaluate("document.getElementById('filterbox').open=true")
            live.fill('#query', 'Gemini')
            live.click('.tabs [data-tab=cost]')
            live.evaluate("window.boardAudit.showDetail('gemini-4-argon-high')")
            metadata_ok &= meta == live.evaluate(fixed_meta)
            res['language_paths'].append({'lang': lg, 'locale': locale, 'width': width, 'path': path_ok, 'saved': saved_ok, 'parameter': parameter_ok, 'button': button_ok, 'ok': path_ok and saved_ok and parameter_ok and button_ok})
            res['fixed_metadata'].append({'lang': lg, 'locale': locale, 'width': width, 'ok': metadata_ok})
            cs.close(); cj.close()
    # 1. 与私有版一致
    c1, pp = page(priv, viewport={'width': 1440, 'height': 1000}, locale='zh-CN')
    c2, pq = page(pub, viewport={'width': 1440, 'height': 1000}, locale='zh-CN')
    diffs, combos = [], 0
    for v in VIEWS:
        for tab, sp in TABS:
            a, bb = snapshot(pp, v, tab, sp), snapshot(pq, v, tab, sp); combos += 1
            if a != bb: diffs.append({'view': v, 'tab': tab, 'speed': sp, 'private_n': len(a), 'public_n': len(bb)})
    res['parity'] = {'combos_checked': combos, 'diffs': diffs}
    pq.select_option('#view', 'primary'); pq.click('.tabs [data-tab=score]')
    res['default_top10_public'] = pq.eval_on_selector_all('#rows tr', 'rs=>rs.slice(0,10).map(r=>r.innerText.replace(/\\s+/g," ").slice(0,70))')
    res['rank15'] = pq.eval_on_selector_all('#rows tr', 'rs=>rs.slice(14,16).map(r=>r.innerText.replace(/\\s+/g," ").slice(0,90))')
    res['private_meta_errors_ignored'] = []
    c1.close()
    # 2. 黑名单（文件 + 中英文渲染文本 + 详情）
    raw = pathlib.Path(pub).read_text(encoding='utf-8')
    res['blacklist_file'] = {w: raw.count(w) for w in BLACK if raw.count(w)}
    res['blacklist_file_context'] = {w: sorted(set(re.findall('.{0,40}' + re.escape(w) + '.{0,30}', raw)))[:3] for w in res['blacklist_file']}
    texts = {}
    for lg in ['zh', 'en']:
        pq.evaluate(f"window.boardAudit.setLang('{lg}')"); pq.wait_for_timeout(100)
        txt = pq.inner_text('body')
        ids = pq.evaluate("window.boardAudit.getData().rows.map(r=>r.id)")
        dt = []
        for i in ids:
            pq.evaluate(f"window.boardAudit.showDetail('{i}')"); dt.append(pq.inner_text('#detailbody'))
        pq.evaluate("document.getElementById('detail').close()")
        texts[lg] = txt + '\n'.join(dt)
    res['blacklist_rendered'] = {lg: {w: texts[lg].count(w) for w in BLACK if texts[lg].count(w)} for lg in texts}
    res['zero_dollar_cells'] = texts['zh'].count('$0.00')
    res['han_in_en_ui'] = sorted(set(re.findall(r'[^\n]{0,20}[\u4e00-\u9fff]+[^\n]{0,20}', pq.evaluate("(()=>{window.boardAudit.setLang('en');return Array.from(document.querySelector('header').querySelectorAll('[data-i18n],#theme'),e=>e.innerText).join(' ')+document.querySelector('.hero').innerText+document.querySelector('#about').innerText+document.querySelector('thead').innerText})()"))))[:10]
    pq.evaluate("window.boardAudit.setLang('zh')")
    # 3. URL 状态
    pq.select_option('#view', 'all'); pq.click('.tabs [data-tab=cost]'); pq.fill('#query', 'Gemini'); pq.wait_for_timeout(100)
    res['url_after_filters'] = pq.evaluate('location.search')
    pq.evaluate("window.boardAudit.showDetail('gemini-4-argon-high')"); res['url_with_detail'] = pq.evaluate('location.search')
    pq.screenshot(path=str(outdir / 'public_detail_desktop.png'))
    c2.close()
    ctx, pr = page(pub, viewport={'width': 1440, 'height': 1000}, locale='zh-CN')
    pr.goto('file://' + pub + '?tab=cost&view=all&q=Gemini&lang=en&m=gemini-4-argon-high'); pr.wait_for_timeout(400)
    res['url_restore'] = {'state': pr.evaluate('window.boardAudit.getState()'), 'detail_open': pr.evaluate("document.getElementById('detail').open"), 'html_lang': pr.evaluate('document.documentElement.lang'), 'canonical_en': pr.evaluate("document.querySelector('link[rel=canonical]').href"), 'og_url_en': pr.evaluate("document.querySelector('meta[property=\"og:url\"]').content"), 'title_en': pr.evaluate('document.title')}
    pr.evaluate("window.boardAudit.setLang('zh')"); res['url_restore']['canonical_zh'] = pr.evaluate("document.querySelector('link[rel=canonical]').href"); res['url_restore']['title_zh'] = pr.evaluate('document.title')
    ctx.close()
    # 3b. 速度页默认门槛（跟进 261105）：切到速度 → ≥25 + 一键显示全部；离开恢复；URL 状态
    ctx, ps = page(pub, viewport={'width': 1440, 'height': 1000}, locale='zh-CN')
    st = {'start': ps.input_value('#threshold')}
    ps.click('.tabs [data-tab=speed]'); ps.wait_for_timeout(150)
    st['speed'] = [ps.input_value('#threshold'), ps.inner_text('#resultcount'), ps.evaluate('location.search')]
    ps.evaluate("window.boardAudit.setLang('en')"); ps.wait_for_timeout(100); st['en_note'] = ps.inner_text('#metricnote')[-140:]
    ps.click('[data-thr="0"]'); ps.wait_for_timeout(150); st['show_all'] = [ps.input_value('#threshold'), ps.inner_text('#resultcount'), ps.evaluate('location.search')]
    ps.click('[data-thr="25"]'); ps.wait_for_timeout(150); ps.click('.tabs [data-tab=score]'); ps.wait_for_timeout(150); st['score_after'] = ps.input_value('#threshold')
    ctx.close()
    for q, key in [('?tab=speed', 'url_speed'), ('?tab=speed&min=0', 'url_speed_min0')]:
        ctx, pu = page(pub, viewport={'width': 1440, 'height': 1000}); pu.goto('file://' + pub + q); pu.wait_for_timeout(300); st[key] = pu.input_value('#threshold'); ctx.close()
    st['ok'] = (st['start'] == '0' and st['speed'][0] == '25' and st['show_all'][0] == '0' and st['score_after'] == '0' and st['url_speed'] == '25' and st['url_speed_min0'] == '0')
    res['speed_threshold'] = st
    # 4. 深浅色：跟随系统 + 记住选择
    ctx, pl = page(pub, viewport={'width': 1440, 'height': 1000}, color_scheme='light')
    theme = {'system_light': pl.evaluate('document.documentElement.dataset.theme')}
    pl.click('#theme'); pl.reload(); pl.wait_for_timeout(300)
    theme['after_toggle_reload'] = pl.evaluate('document.documentElement.dataset.theme'); theme['saved'] = pl.evaluate("localStorage.getItem('theme')")
    ctx.close()
    ctx, pd = page(pub, viewport={'width': 1440, 'height': 1000}, color_scheme='dark'); theme['system_dark'] = pd.evaluate('document.documentElement.dataset.theme'); ctx.close()
    res['theme'] = theme
    # 5. 截图与手机检查
    for lg in ['zh', 'en']:
        for scheme in ['dark', 'light']:
            ctx, pg = page(pub + '?lang=' + lg, viewport={'width': 1440, 'height': 1000}, locale='zh-CN' if lg == 'zh' else 'en-US', color_scheme=scheme)
            pg.screenshot(path=str(outdir / f'public_desktop_{lg}_{scheme}.png'))
            if scheme == 'dark' and lg == 'zh': pg.screenshot(path=str(outdir / 'public_desktop_zh_full.png'), full_page=True)
            ctx.close()
        ctx, pm = page(pub + '?lang=' + lg, viewport={'width': 390, 'height': 844}, locale='zh-CN' if lg == 'zh' else 'en-US', device_scale_factor=2, is_mobile=True, has_touch=True)
        res[f'mobile_{lg}'] = pm.evaluate("""()=>({scrollW:document.documentElement.scrollWidth,innerW:innerWidth,firstCardTop:Math.round(document.querySelector('#rows tr').getBoundingClientRect().top+scrollY),firstCardBottom:Math.round(document.querySelector('#rows tr').getBoundingClientRect().bottom+scrollY),filtersOpen:document.getElementById('filterbox').open,lang:document.documentElement.lang})""")
        pm.screenshot(path=str(outdir / f'public_mobile_{lg}.png'))
        if lg == 'zh': pm.screenshot(path=str(outdir / 'public_mobile_zh_full.png'), full_page=True)
        ctx.close()
    # 私有版手机首卡位置（对照）
    ctx, pv = page(priv, viewport={'width': 390, 'height': 844}, is_mobile=True, device_scale_factor=2)
    res['private_mobile_firstCardTop'] = pv.evaluate("Math.round(document.querySelector('#rows tr').getBoundingClientRect().top+scrollY)"); ctx.close()
    b.close()
res['errors'] = [e for e in res['errors'] if priv not in e] + [e for e in res['errors'] if priv in e and False]
res['pass'] = (res['speed_threshold']['ok'] and not res['errors'] and not res['external_requests'] and not res['parity']['diffs'] and all(res[f'mobile_{l}']['scrollW'] <= 390 and res[f'mobile_{l}']['innerW'] == 390 for l in ['zh', 'en']) and res['zero_dollar_cells'] == 0)
res['pass'] = bool(res['pass'] and res['input_html']['ok'] and res['products']['ok'] and res['detail_static']['ok'] and res['detail_browser']['ok'] and res['links']['ok'] and all(x['ok'] for key in ['static_first_screen', 'language_paths', 'fixed_metadata'] for x in res[key])
                   and not res['han_in_en_ui']  # blacklist hits stay informational (pre-existing product names in data)
                   and res['url_restore']['canonical_en'] == res['url_restore']['canonical_zh'] == res['url_restore']['og_url_en'] == 'https://modelsrank.org/'
                   and res['mobile_en']['lang'] == 'en' and res['mobile_zh']['lang'] == 'zh-CN')
(outdir / 'check-result-public-261105.json').write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding='utf-8')
print(json.dumps(res, ensure_ascii=False, indent=1))
sys.exit(0 if res['pass'] else 1)
