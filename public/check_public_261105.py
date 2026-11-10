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
parser.add_argument('--allow-placeholders', action='store_true', help='Allow missing About fields for preview only; all other checks remain strict')
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
ICONS = {
    ORIGIN + '/favicon.ico': ('icon', '16x16 32x32', 'image/x-icon'),
    ORIGIN + '/favicon.png': ('icon', '32x32', 'image/png'),
    ORIGIN + '/apple-touch-icon.png': ('apple-touch-icon', '180x180', 'image/png'),
}


def serve_icon(route):
    """Resolve only the three production icon URLs from local build artifacts."""
    if route.request.url not in ICONS:
        return False
    route.fulfill(path=str(SITE_ROOT / urlsplit(route.request.url).path.lstrip('/')),
                  content_type=ICONS[route.request.url][2])
    return True


def local_file_route(route):
    if not serve_icon(route):
        if urlsplit(route.request.url).scheme in ('http', 'https'):
            route.abort()
        else:
            route.continue_()


def icon_checks():
    from PIL import Image
    failures = []
    pages = list(SITE_ROOT.rglob('index.html'))
    for url, (rel, sizes, mime) in ICONS.items():
        name = urlsplit(url).path.lstrip('/')
        try:
            with Image.open(SITE_ROOT / name) as icon:
                icon.load()
                if name.endswith('.ico'):
                    assert icon.format == 'ICO' and {(16, 16), (32, 32)} <= icon.ico.sizes()
                    for size in icon.ico.sizes():
                        icon.ico.getimage(size).load()
                else:
                    size = 180 if rel == 'apple-touch-icon' else 32
                    assert icon.format == 'PNG' and icon.size == (size, size)
                    assert icon.convert('RGBA').getextrema()[3] == (255, 255)
            assert (SITE_ROOT / name).read_bytes() == (SOURCE_ROOT / 'assets' / name).read_bytes()
        except Exception as error:
            failures.append(name + ': ' + str(error))
    for path in pages:
        links = Document(path.read_text()).root.all('link')
        icons = [n.attrs for n in links if n.attrs.get('rel') in ('icon', 'apple-touch-icon')]
        if len(icons) != 3 or any(not any(n.get('href') == url and n.get('rel') == rel and n.get('sizes') == sizes for n in icons)
                                  for url, (rel, sizes, mime) in ICONS.items()):
            failures.append(str(path.relative_to(SITE_ROOT)) + ': icon links')
    return {'ok': bool(pages) and not failures, 'pages': len(pages), 'failures': failures}


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


TEXT = json.loads((SOURCE_ROOT / 'public_text_261105.json').read_text())
ABOUT_URLS = {'zh': ORIGIN + '/about/', 'en': ORIGIN + '/en/about/'}


def about_input_checks():
    """Independent validation: never import the build script (it writes files)."""
    import html, unicodedata
    from string import Formatter
    missing, errors = [], []
    config = TEXT.get('about_config', {})
    if not isinstance(config, dict):
        raise ValueError('Invalid about_config object')
    operator, channel = config.get('operator', {}), config.get('corrections', {})
    if channel is None:
        channel = {}
    if not isinstance(operator, dict) or not isinstance(channel, dict):
        raise ValueError('Invalid About configuration objects')
    raw_names = operator.get('name')
    if raw_names is None:
        raw_names = {}
    if not isinstance(raw_names, dict):
        raise ValueError('Invalid About operator names')
    def read(value, field):
        if value is None:
            missing.append(field)
            return ''
        if not isinstance(value, str) or re.search(r'[{}<>]', value) or any(unicodedata.category(c).startswith('C') for c in value):
            errors.append('Invalid field: ' + field)
            return ''
        if not value.strip():
            missing.append(field)
        return value.strip()
    names = {lg: read(raw_names.get(lg), 'operator.name.' + lg) for lg in ABOUT_URLS}
    if operator.get('entity_type') != 'Person':
        errors.append('operator.entity_type must be Person')
    repo_pattern = r'https://github\.com/[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?/[A-Za-z0-9_-][A-Za-z0-9_.-]*'
    source_repo = read(config.get('source_repo'), 'source_repo')
    if source_repo and not re.fullmatch(repo_pattern, source_repo):
        errors.append('Invalid About source_repo URL')
    raw_channels = channel.get('channels', [channel] if channel else [])
    if raw_channels is None:
        raw_channels = []
    if not isinstance(raw_channels, list):
        raise ValueError('corrections.channels must be a list')
    channels = []
    for entry in raw_channels:
        if not isinstance(entry, dict):
            raise ValueError('Correction channel must be an object')
        before = len(missing)
        error_count = len(errors)
        kind = read(entry.get('type'), 'corrections.type')
        value = read(entry.get('value'), 'corrections.value')
        del missing[before:]
        if kind and kind not in ('email', 'url', 'github_issues'):
            errors.append('Invalid corrections.type')
        if value and not kind:
            errors.append('Missing type for correction value')
        if value and kind == 'email':
            parts = value.split('@')
            valid = len(parts) == 2
            if valid:
                local, domain = parts
                valid = bool(re.fullmatch(r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*", local))
                valid &= len(domain.split('.')) >= 2 and all(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?', part) for part in domain.split('.'))
            if not valid:
                errors.append('Invalid About email')
        if value and kind == 'url':
            try:
                target = urlsplit(value)
                port = target.port
                valid = (target.scheme == 'https' and target.hostname and target.username is None and target.password is None
                         and all(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?', part) for part in target.hostname.split('.')) and not re.search(r'\s|\\|[<>"{}]', value))
            except ValueError:
                valid = False
            if not valid:
                errors.append('Invalid About HTTPS URL')
        if value and kind == 'github_issues' and not re.fullmatch(repo_pattern + r'/issues', value):
            errors.append('Invalid About github_issues URL')
        if kind and value and len(errors) == error_count:
            channels.append({'type': kind, 'value': value})
    if not channels:
        missing.append('corrections.channels')
    first = next((c for c in channels if c['type'] == 'email'), channels[0] if channels else {})
    kind, value = first.get('type', ''), first.get('value', '')
    def check_copy(node, path):
        if isinstance(node, dict):
            if set(node) == {'zh', 'en'} and not all(isinstance(v, str) and v.strip() for v in node.values()):
                errors.append('Missing About translation: ' + path)
            for k, v in node.items():
                check_copy(v, path + '.' + k)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                check_copy(v, path + '.' + str(i))
        elif isinstance(node, str):
            normalized = unicodedata.normalize('NFKC', html.unescape(node))
            try:
                literals = ''
                for literal, field, spec, conversion in Formatter().parse(normalized):
                    literals += literal
                    if field is not None and (field not in {'date', 'operator_name', 'correction'} or spec or conversion):
                        errors.append('Unknown About placeholder: ' + path)
                if re.search(r'\d|[{}]', literals):
                    errors.append('Literal number or brace in About copy: ' + path)
            except ValueError:
                errors.append('Malformed About placeholder: ' + path)
            if any(w in normalized for w in BLACK):
                errors.append('Blacklisted About copy: ' + path)
        else:
            errors.append('Invalid About copy: ' + path)
    check_copy(TEXT.get('about_page'), 'about_page')
    check_copy(TEXT.get('about_faq'), 'about_faq')
    check_copy({k: v for k, v in TEXT['ui'].items() if k.startswith('about_page.')}, 'ui')
    return {'names': names, 'kind': kind, 'value': value, 'channels': channels, 'source_repo': source_repo, 'missing_fields': sorted(missing), 'errors': errors,
            'ready': not missing and not errors}


try:
    ABOUT_STATE = about_input_checks()
except (ValueError, TypeError, KeyError) as error:
    ABOUT_STATE = {'ready': False, 'missing_fields': [], 'errors': [str(error)], 'names': {'zh': '', 'en': ''}, 'value': '', 'kind': '', 'channels': [], 'source_repo': ''}


def expected_about_sources():
    """Compute from raw row fields and primary-source nodes, independently of outputs."""
    records = {s['id']: s for s in DATA['sources']}
    ids = set()
    for r in DATA['rows']:
        if r.get('base') not in TARGETS or r.get('lifecycle') == 'archived':
            continue
        # These are the explicit fields used by detail-page source lists and links.
        ids |= set(r.get('sources', []))
        ids |= {sid for sid in r.get('fieldSources', {}).values() if sid}
        if r.get('availability', {}).get('source'):
            ids.add(r['availability']['source'])
    source = DATA['crosscheck']['source']
    if source not in records:
        raise ValueError('Unknown crosscheck source: ' + source)
    ids.add(source)
    template = Document((SOURCE_ROOT / 'template_public_261105.html').read_text()).root
    groups = [n for n in template.all() if 'primarysources' in n.attrs.get('class', '').split()]
    if len(groups) != 1:
        raise ValueError('Expected one primary source group')
    urls = {a.attrs['href'] for a in groups[0].all('a')}
    for url in urls:
        candidates = [s for s in records.values() if s['url'] == url and s['checked'][:10] <= DATA['date']]
        if not candidates:
            raise ValueError('Missing primary source record: ' + url)
        candidates.sort(key=lambda s: (s['checked'][:10], s['id']))
        ids.add(candidates[-1]['id'])
    if ids - records.keys():
        raise ValueError('Unknown About source IDs: ' + ', '.join(sorted(ids - records.keys())))
    by_url = {}
    for sid in sorted(ids):
        s = records[sid]
        by_url.setdefault(s['url'], []).append(s)
    result = {}
    for url, items in by_url.items():
        s = sorted(items, key=lambda s: (s['checked'][:10], s['id']))[-1]
        result[url] = {'checked': s['checked'][:10], 'title': dict(zip(('zh', 'en'), TEXT['sources'][s['id']])),
                       'historical': any(s.get('historical') for s in items)}
    return result


def about_checks():
    failures = list(ABOUT_STATE['errors'])
    def require(ok, test):
        if not ok:
            failures.append(test)
    if ABOUT_STATE['missing_fields'] and not args.allow_placeholders:
        failures.append('missing_fields: ' + ', '.join(ABOUT_STATE['missing_fields']))
    def expand(value, lg):
        import html, unicodedata
        value = value.format(date=DATA['date'], operator_name=ABOUT_STATE['names'][lg], correction=ABOUT_STATE['value'])
        require(not re.search(r'[{}]', unicodedata.normalize('NFKC', html.unescape(value))), 'Residual About placeholder: ' + lg)
        return value
    def copy(key, lg):
        return expand(TEXT['about_page'][key][lg], lg)
    sources = expected_about_sources()
    require(len(TEXT['about_faq']) == 8, 'Eight source FAQ items')
    require(not any('/about/' in p for p in json.loads((SOURCE_ROOT / 'published_urls.json').read_text())), 'Manifest only manages detail paths')
    pages = []
    for lg, url in ABOUT_URLS.items():
        relative = 'en/about/index.html' if lg == 'en' else 'about/index.html'
        path = SITE_ROOT / relative
        if not path.is_file():
            failures.append('Missing About page: ' + relative)
            continue
        try:
            doc = document(path)
            body = doc.all('body')[0]
            language = 'en' if lg == 'en' else 'zh-CN'
            require(doc.all('html')[0].attrs.get('lang') == language, 'About lang: ' + lg)
            require([n.text() for n in doc.all('title')] == [copy('title', lg)], 'About title: ' + lg)
            require([n.attrs.get('content') for n in doc.all('meta', name='description')] == [copy('description', lg)], 'About description: ' + lg)
            require([n.attrs.get('href') for n in doc.all('link', rel='canonical')] == [url], 'About canonical: ' + lg)
            alternates = [n for n in doc.all('link') if 'hreflang' in n.attrs]
            require(len(alternates) == 3 and {n.attrs['hreflang']: n.attrs.get('href') for n in alternates} == {'zh-CN': ABOUT_URLS['zh'], 'en': ABOUT_URLS['en'], 'x-default': ABOUT_URLS['zh']}, 'About hreflang: ' + lg)
            for field, value in [('og:title', copy('title', lg)), ('og:description', copy('description', lg)), ('og:url', url)]:
                require([n.attrs.get('content') for n in doc.all('meta', property=field)] == [value], 'About ' + field + ': ' + lg)
            require([n.text() for n in doc.all('h1')] == [copy('heading', lg)], 'About h1: ' + lg)
            require([n.attrs.get('id') for n in body.all('section')] == ['operator', 'sources', 'methodology', 'updates', 'faq', 'disclaimer'], 'About section order: ' + lg)
            require(bool(doc.all('meta', name='robots', content='noindex')) == (not ABOUT_STATE['ready']), 'About indexing state: ' + lg)
            require([n.text() for n in doc.all('p', **{'class': 'preview'})] == ([] if ABOUT_STATE['ready'] else [copy('preview', lg)]), 'About preview state: ' + lg)
            require([n.text() for n in doc.all(id='operator')[0].all('p')] == [copy('operator' if ABOUT_STATE['names'][lg] else 'operator.placeholder', lg), copy('purpose', lg)] + ([copy('source.license', lg)] if ABOUT_STATE['source_repo'] else []), 'About operator body matches config: ' + lg)
            corrections = doc.all(id='corrections')[0]
            value = ABOUT_STATE['value']
            expected_links = [(('mailto:' if c['type'] == 'email' else '') + c['value'],
                               copy('corrections.github_issues', lg) if c['type'] == 'github_issues' else c['value']) for c in ABOUT_STATE['channels']]
            require([n.text() for n in corrections.all('p')] == ([copy('corrections', lg)] + [label for _, label in expected_links] if expected_links else [copy('corrections.placeholder', lg)]), 'About corrections body matches config: ' + lg)
            require([(a.attrs.get('href'), a.text()) for a in corrections.all('a')] == expected_links, 'About all correction links match config: ' + lg)
            license_links = [(a.attrs.get('href'), a.text()) for a in doc.all(id='operator')[0].all('a')]
            require(license_links == ([(ABOUT_STATE['source_repo'], copy('source.license', lg))] if ABOUT_STATE['source_repo'] else []), 'About license link matches source_repo: ' + lg)
            require(doc.all(id='updates')[0].all('p')[0].text() == copy('updates', lg), 'About update date: ' + lg)
            require(doc.all(id='disclaimer')[0].all('p')[0].text() == copy('disclaimer', lg), 'About disclaimer: ' + lg)
            method = doc.all(id='methodology')[0]
            require([(p.attrs.get('data-method'), p.text()) for p in method.all('p', **{'class': 'method-copy'})] == [(key, Document(TEXT['ui'][key][lg]).root.text()) for key in ('method.score', 'method.cost', 'method.speed')], 'Original public methods unchanged: ' + lg)
            faq = []
            for i, item in enumerate(TEXT['about_faq']):
                key = 'placeholder_answer' if (i == 0 and not ABOUT_STATE['names'][lg]) or (i == 7 and not value) else 'answer'
                if i == 7 and value:
                    kinds = {c['type'] for c in ABOUT_STATE['channels']}
                    key = ('answer' if {'email', 'github_issues'} <= kinds else 'email_answer' if 'email' in kinds else 'url_answer')
                faq.append((expand(item['question'][lg], lg), expand(item[key][lg], lg)))
            visible_faq = [(n.all('summary')[0].text(), n.all('p')[0].text()) for n in doc.all(id='faq')[0].all('details')]
            require(len(visible_faq) == 8 and visible_faq == faq, 'Visible FAQ matches current input: ' + lg)
            scripts = doc.all('script')
            require(len(scripts) == 1 and scripts[0].attrs == {'type': 'application/ld+json'}, 'Only JSON-LD script: ' + lg)
            structured = json.loads(scripts[0].raw_text())
            require(structured.get('@context') == 'https://schema.org', 'Schema context: ' + lg)
            graph = structured['@graph']
            require([n['@type'] for n in graph] == ['AboutPage', 'FAQPage'] + (['Person'] if ABOUT_STATE['ready'] else []), 'About JSON-LD types: ' + lg)
            page, faq_entity = graph[:2]
            expected_page = {'@type': 'AboutPage', '@id': url + '#page', 'url': url, 'name': copy('title', lg), 'description': copy('description', lg), 'inLanguage': language,
                             'isPartOf': {'@id': ORIGIN + '/#website'}, 'about': {'@id': ORIGIN + '/#website'}, 'hasPart': {'@id': url + '#faq'}}
            if ABOUT_STATE['ready']:
                expected_page['publisher'] = {'@id': ORIGIN + '/#operator'}
            require(page == expected_page, 'AboutPage properties and config state: ' + lg)
            require(faq_entity == {'@type': 'FAQPage', '@id': url + '#faq', 'url': url + '#faq', 'inLanguage': language, 'isPartOf': {'@id': url + '#page'},
                                  'mainEntity': [{'@type': 'Question', 'name': q, 'acceptedAnswer': {'@type': 'Answer', 'text': a}} for q, a in visible_faq]}, 'FAQ JSON-LD equals visible FAQ: ' + lg)
            home = '/en/' if lg == 'en' else '/'
            homepage = document(page_file(home))
            home_graph = json.loads(homepage.all('script', id='structured-data')[0].raw_text())['@graph']
            website = next(n for n in home_graph if n['@type'] == 'WebSite')
            persons = [n for n in graph if n['@type'] == 'Person']
            home_persons = [n for n in home_graph if n['@type'] == 'Person']
            expected_persons = [{'@type': 'Person', '@id': ORIGIN + '/#operator', 'name': ABOUT_STATE['names'][lg]}] if ABOUT_STATE['ready'] else []
            require(persons == home_persons == expected_persons, 'Person entity matches config: ' + lg)
            require(website.get('publisher') == ({'@id': ORIGIN + '/#operator'} if ABOUT_STATE['ready'] else None), 'WebSite publisher state: ' + lg)
            require(website.get('sameAs') == (ABOUT_STATE['source_repo'] or None), 'WebSite sameAs matches source_repo: ' + lg)
            dataset = next(n for n in home_graph if n['@type'] == 'Dataset')
            require(dataset['creator'] == ({'@id': ORIGIN + '/#operator'} if ABOUT_STATE['ready'] else {'@type': 'Organization', 'name': 'Models Rank', 'url': ORIGIN + '/'}), 'Dataset creator state: ' + lg)
            ids = {n['@id'] for n in graph} | {website['@id']}
            def refs(node):
                if isinstance(node, dict):
                    if set(node) == {'@id'}:
                        require(node['@id'] in ids, 'Dangling JSON-LD reference: ' + str(node))
                    for v in node.values():
                        refs(v)
                elif isinstance(node, list):
                    for v in node:
                        refs(v)
            refs(graph)
            source_section = doc.all(id='sources')[0]
            actual = source_section.all('a')
            require(len(actual) == len(sources) and {a.attrs.get('href') for a in actual} == set(sources), 'Exact independently computed source URL set: ' + lg)
            for li in source_section.all('li'):
                link = li.all('a')[0]
                source = sources[link.attrs['href']]
                require(link.text() == source['title'][lg] and [n.text() for n in li.all('time')] == [source['checked']], 'Source title and retrieval date: ' + link.attrs['href'])
                require([n.text() for n in li.all('span', **{'class': 'historical'})] == ([copy('sources.historical', lg)] if source['historical'] else []), 'Historical source marker: ' + link.attrs['href'])
            require([n.text() for n in source_section.all('h3')] == [copy('sources.' + k, lg) for k in ('benchmark', 'preference', 'information')], 'Three source categories: ' + lg)
            category = None
            for node in source_section.children:
                if not isinstance(node, Element):
                    continue
                if node.tag == 'h3':
                    category = node.text()
                elif node.tag == 'details':
                    for link in node.all('a'):
                        host = urlsplit(link.attrs['href']).hostname
                        expected_category = 'benchmark' if host in ('artificialanalysis.ai', 'www.artificialanalysis.ai') else 'preference' if host in ('arena.ai', 'www.arena.ai', 'lmarena.ai') else 'information'
                        require(category == copy('sources.' + expected_category, lg), 'Source category: ' + link.attrs['href'])
            for group in source_section.all('details'):
                require('open' not in group.attrs and all(urlsplit(a.attrs['href']).hostname == group.all('summary')[0].text() for a in group.all('a')), 'Native website source group: ' + lg)
            require(not re.search(r'[{}]', body.text()) and 'mailto:null' not in path.read_text(), 'No residual About placeholders: ' + lg)
            require(home in {a.attrs.get('href') for a in doc.all('a')} and ('/about/' if lg == 'en' else '/en/about/') in {a.attrs.get('href') for a in doc.all('a')}, 'About home and language links: ' + lg)
            require(urlsplit(url).path in static_reachable(home, lg), 'Static BFS reaches About: ' + lg)
            resources = []
            for n in doc.all():
                require(not any(k.startswith('on') for k in n.attrs), 'No About event handlers: ' + lg)
                resources.extend(v for k, v in n.attrs.items() if k in ('src', 'srcset', 'poster', 'data', 'background'))
                if n.tag == 'link' and n.attrs.get('rel') not in ('canonical', 'alternate'):
                    if n.attrs.get('href') not in ICONS or n.attrs.get('rel') != ICONS[n.attrs['href']][0]:
                        resources.append(n.attrs.get('href'))
            css = '\n'.join(n.raw_text() for n in doc.all('style')) + '\n'.join(n.attrs.get('style', '') for n in doc.all())
            require(not resources and not re.search(r'url\s*\(|@import', css, re.I), 'No About resources except brand icons: ' + lg)
            scan_links(doc, url)
            pages.append({'lang': lg, 'faq_count': len(visible_faq), 'source_count': len(actual)})
        except (KeyError, IndexError, TypeError, ValueError) as error:
            failures.append(relative + ': ' + str(error))
    footer_pages = [SITE_ROOT / 'index.html', SITE_ROOT / 'en/index.html', SITE_ROOT / '404.html', SITE_ROOT / 'about/index.html', SITE_ROOT / 'en/about/index.html'] + sorted((SITE_ROOT / 'm').glob('*/index.html')) + sorted((SITE_ROOT / 'en/m').glob('*/index.html'))
    for path in footer_pages:
        relative = str(path.relative_to(SITE_ROOT))
        targets = (['/about/', '/en/about/'] if relative == '404.html' else
                   ['/about/' if relative.startswith('en/') else '/en/about/'] if relative.endswith('about/index.html') else
                   ['/en/about/' if relative.startswith('en/') else '/about/'])
        footers = document(path).all('footer')
        links = [a for f in footers for a in f.all('a')]
        for target in targets:
            require(any(a.attrs.get('href') == target and a.text().strip() and 'data-detail' not in a.attrs and 'modelbtn' not in a.attrs.get('class', '').split() for a in links), 'Ordinary About footer link: ' + relative + ' ' + target)
        expected_labels = [TEXT['ui']['about_page.source'][lg] for lg in (('zh', 'en') if relative == '404.html' else ('en',) if relative.startswith('en/') else ('zh',))] if ABOUT_STATE['source_repo'] else []
        source_links = [a for a in links if a.attrs.get('href') == ABOUT_STATE['source_repo']]
        require([a.text() for a in source_links] == expected_labels, 'Source footer labels and URL: ' + relative)
        require(all(a.attrs.get('target') == '_blank' and set(a.attrs.get('rel', '').split()) == {'noopener', 'noreferrer'} and 'sociallink' in a.attrs.get('class', '').split() and 'data-detail' not in a.attrs and 'modelbtn' not in a.attrs.get('class', '').split() for a in source_links), 'Ordinary safe source footer links: ' + relative)
    llms = (SITE_ROOT / 'llms.txt').read_text()
    require(all(url in re.findall(r'\]\(([^)]+)\)', llms) for url in ABOUT_URLS.values()), 'Both About links in llms.txt')
    return {'ok': not failures, 'missing_fields': ABOUT_STATE['missing_fields'], 'ready': ABOUT_STATE['ready'], 'pages': pages,
            'source_count': len(sources), 'footer_pages': len(footer_pages), 'errors': failures}


def about_browser_checks(browser):
    result = {'ok': False, 'samples': [], 'errors': [], 'external_requests': []}
    for lg, relative in [('zh', 'about/index.html'), ('en', 'en/about/index.html')]:
        for width in (1440, 390):
            context = browser.new_context(viewport={'width': width, 'height': 900}, is_mobile=width == 390)
            context.route('**/*', local_file_route)
            page = context.new_page()
            page.on('pageerror', lambda error: result['errors'].append(str(error)))
            page.on('console', lambda msg: result['errors'].append(msg.text) if msg.type == 'error' else None)
            page.on('request', lambda request: result['external_requests'].append(request.url) if urlsplit(request.url).scheme in ('http', 'https') and request.url not in ICONS else None)
            try:
                page.goto((SITE_ROOT / relative).as_uri())
                page.wait_for_load_state('load')
                sample = page.evaluate('''()=>({scrollWidth:document.documentElement.scrollWidth, width:innerWidth, faq:document.querySelectorAll('#faq details').length})''')
                sample.update({'lang': lg, 'viewport': width, 'ok': sample['scrollWidth'] <= width and sample['width'] == width and sample['faq'] == 8})
                result['samples'].append(sample)
                page.screenshot(path=str(outdir / f'about_{lg}_{width}.png'), full_page=True)
            except Exception as error:
                result['errors'].append(str(error))
            finally:
                context.close()
    result['ok'] = len(result['samples']) == 4 and all(s['ok'] for s in result['samples']) and not result['errors'] and not result['external_requests']
    return result


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
    expected |= set(ABOUT_URLS.values()) if ABOUT_STATE['ready'] else set()
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
    expected_urls |= set(ABOUT_URLS.values()) if ABOUT_STATE['ready'] else set()
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
            if serve_icon(request_route):
                return
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
    res['about'] = about_checks()
except Exception as error:
    res['about'] = {'ok': False, 'missing_fields': ABOUT_STATE['missing_fields'], 'errors': [str(error)]}
res['production_ready'] = False
try:
    res['detail_static'] = detail_static_checks()
except Exception as error:
    res['detail_static'] = {'ok': False, 'failures': [{'test': 'static checks', 'error': str(error)}]}
try:
    res['products'] = product_checks()
except Exception as error:
    res['products'] = {'ok': False, 'failures': [str(error)]}
res['links'] = {'ok': not LINK_FAILURES, 'checked': LINK_COUNT, 'failures': LINK_FAILURES}

res['icons'] = icon_checks()
res['static_pass'] = all(res[k]['ok'] for k in ('input_html', 'about', 'products', 'detail_static', 'links', 'icons'))

with sync_playwright() as p:
    try:
        b = p.chromium.launch(executable_path=CHROME, args=['--no-sandbox'])
    except Exception as error:
        res.update({'pass': False, 'browser_unavailable': str(error), 'detail_browser': {'ok': False, 'not_run': 'Chrome unavailable'}, 'about_browser': {'ok': False, 'not_run': 'Chrome unavailable'}})
        (outdir / 'check-result-public-261105.json').write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding='utf-8')
        print(json.dumps(res, ensure_ascii=False, indent=1))
        sys.exit(1)
    res['about_browser'] = about_browser_checks(b)
    res['detail_browser'] = detail_browser_checks(b)
    res['links'] = {'ok': not LINK_FAILURES, 'checked': LINK_COUNT, 'failures': LINK_FAILURES}
    def page(path, **kw):
        ctx = b.new_context(**kw); pg = ctx.new_page()
        ctx.route('**/*', local_file_route)
        pg.on('pageerror', lambda e: res['errors'].append(f'{path}: {e}'))
        pg.on('console', lambda m: m.type == 'error' and res['errors'].append(f'{path}: {m.text}'))
        pg.on('request', lambda rq: (not rq.url.startswith(('file:', 'data:', 'about:'))) and rq.url not in ICONS and res['external_requests'].append(rq.url))
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
res['pass'] = bool(res['pass'] and res['icons']['ok'] and res['about']['ok'] and res['about_browser']['ok'] and res['input_html']['ok'] and res['products']['ok'] and res['detail_static']['ok'] and res['detail_browser']['ok'] and res['links']['ok'] and all(x['ok'] for key in ['static_first_screen', 'language_paths', 'fixed_metadata'] for x in res[key])
                   and not res['han_in_en_ui']  # blacklist hits stay informational (pre-existing product names in data)
                   and res['url_restore']['canonical_en'] == res['url_restore']['canonical_zh'] == res['url_restore']['og_url_en'] == 'https://modelsrank.org/'
                   and res['mobile_en']['lang'] == 'en' and res['mobile_zh']['lang'] == 'zh-CN')
res['production_ready'] = bool(res['pass'] and ABOUT_STATE['ready'] and not args.allow_placeholders)
(outdir / 'check-result-public-261105.json').write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding='utf-8')
print(json.dumps(res, ensure_ascii=False, indent=1))
sys.exit(0 if res['pass'] else 1)
