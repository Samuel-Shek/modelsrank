#!/usr/bin/env python3
"""公开版 AI 模型榜单生成器（261105；同日速度改版：AA 性能基准 v3.0.0 的 taskMin / tps / ttfat，见 patch_speed_v3_261105.py）。

输入（同目录）：
  model-data_261105.json      私有版 261105 内嵌数据的原样副本（只读来源）
  public_text_261105.json     公开版文案表：zh / en（en 为草稿，待 Gemini 网页版终审）
  template_public_261105.html 页面模板（HTML/CSS/JS，零外部资源）
输出：
  AI 模型榜单_公开版_261105.html（中文，同 site/index.html）
  site/index.html（中文）、site/en/index.html（英文静态版：lang/title/meta/canonical/正文初始文字为英文）

用法：python3 build_public_261105.py
      python3 build_public_261105.py --from-private "<私有版 HTML 路径>"   # 先从私有版 HTML 重新抽取数据（只读）
"""
import json, re, sys, datetime, pathlib, math, html, struct, shutil, os, tempfile
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import urlencode, urlsplit
import xml.etree.ElementTree as ET
HERE = pathlib.Path(__file__).resolve().parent
DATA = HERE / 'model-data_261105.json'
TEXT = HERE / 'public_text_261105.json'
TPL = HERE / 'template_public_261105.html'
OUT = HERE / 'AI 模型榜单_公开版_261105.html'
SITE = {'zh': 'https://modelsrank.org/', 'en': 'https://modelsrank.org/en/'}  # 站点 Models Rank；域名 modelsrank.org 已于 2026-11-03 在 Cloudflare 购买

if '--from-private' in sys.argv:
    src = pathlib.Path(sys.argv[sys.argv.index('--from-private') + 1]).read_text(encoding='utf-8')
    m = re.search(r'<script id="model-data" type="application/json">(.*?)</script>', src, re.S)
    DATA.write_text(json.dumps(json.loads(m.group(1).replace('<\\/', '</')), ensure_ascii=False, indent=1), encoding='utf-8')

raw = json.loads(DATA.read_text(encoding='utf-8'))
T = json.loads(TEXT.read_text(encoding='utf-8'))
P, missing = T['parts'], set()
GENERIC = ['分数和性能对应此具体配置；不代表聊天产品的默认设置。',
           '同一型号不同推理档位分别记录。数值仅对应 AA 的测试配置，不代表聊天产品的默认配置。']
HAN = re.compile(r'[\u4e00-\u9fff]')

def tr(s):
    """Map one source string to {zh,en}; None = deliberately dropped. Unknown Chinese text is an error."""
    if s is None or s == '':
        return None
    if not HAN.search(s):
        return s
    if s not in P:
        missing.add(s); return None
    v = P[s]
    return None if v is None else {'zh': v[0], 'en': v[1]}

def tr_note(s):
    if not s:
        return None
    for g in GENERIC:
        s = s.replace(g, '')
    parts = [p.strip() for p in re.split(r'(?<=。)\s+', s.strip()) if p.strip()]
    out = [x for x in (tr(p) for p in parts) if x]
    out = [{'zh': x, 'en': x} if isinstance(x, str) else x for x in out]
    if not out:
        return None
    return {'zh': ''.join(x['zh'] for x in out), 'en': ' '.join(x['en'] for x in out)}

KEEP = ['id', 'base', 'name', 'effort', 'reference', 'primary', 'score', 'cost', 'taskMin', 'tps', 'ttfat', 'estimatedScore',
        'status', 'checked', 'benchmarkVersion', 'kind', 'lifecycle', 'added', 'updated', 'context', 'released', 'legacy',
        'fieldSources', 'fieldChecked', 'sources', 'costStatus', 'costObservations', 'publicAccess']
rows = []
for r in raw['rows']:
    o = {k: r[k] for k in KEEP if k in r}
    o['vendor'] = T['vendors'].get(r['vendor'], r['vendor'])
    o['profile'] = tr(r.get('profile')) if r.get('profile') else None
    if isinstance(o.get('effort'), str) and HAN.search(o['effort']):
        e = tr(o['effort']); o['effort'] = e['en'] if e else ''
    for f in ['note', 'routingNote', 'historyReason']:
        o[f] = tr_note(r.get(f))
    for f in ['priceNote', 'contextExact', 'costNote']:
        o[f] = tr(r.get(f))
    if r.get('availability'):
        a = dict(r['availability']); a['status'] = tr(a['status']); o['availability'] = a
    if r.get('vendorClaims'):
        v = dict(r['vendorClaims']); v['note'] = tr(v['note'])
        v['items'] = [{'benchmark': tr(x['benchmark']), 'value': x['value']} for x in v['items']]
        o['vendorClaims'] = v
    if r.get('supplemental'):
        o['supplemental'] = [{**e, 'benchmark': tr(e['benchmark']), 'configuration': tr(e['configuration']), 'note': tr(e['note']),
                              'published': e.get('published'), 'unit': e.get('unit', '')} for e in r['supplemental']]
    if r.get('arena'):
        a = dict(r['arena']); a['note'] = tr(a.get('note')); o['arena'] = a
    rows.append(o)

srcs = []
for s in raw['sources']:
    if s['id'] not in T['sources']:
        missing.add('source:' + s['id']); continue
    zh, en = T['sources'][s['id']]
    srcs.append({'id': s['id'], 'title': {'zh': zh, 'en': en}, 'url': s['url'], 'checked': s['checked']})

c = raw['crosscheck']
date = raw['date']
pub = {
    'date': date,
    'recentSince': (datetime.date.fromisoformat(date) - datetime.timedelta(days=30)).isoformat(),
    'benchmarkVersion': raw['benchmarkVersion'], 'legacyBenchmarkVersion': raw['legacyBenchmarkVersion'],
    'costDefaultThreshold': raw['costDefaultThreshold'], 'speedDefaultThreshold': raw.get('speedDefaultThreshold'), 'staleAfterDays': raw['staleAfterDays'],
    'rows': rows, 'sources': srcs,
    'vendorNames': {k: {'zh': v[0], 'en': v[1]} for k, v in T['vendorNames'].items()},
    'crosscheck': {'note': {'zh': T['crosscheck'][0], 'en': T['crosscheck'][1]}, 'pageDate': c['pageDate'],
                   'retrieved': c['retrieved'], 'source': c['source'], 'rows': c['rows']},
    'highlights': {'title': {'zh': T['highlights']['title'][0], 'en': T['highlights']['title'][1]},
                   'lines': [{'zh': a, 'en': b} for a, b in T['highlights']['lines']], 'button': T['highlights']['button']},
    'changes': [{'zh': a, 'en': b} for a, b in T['changes']],
    'ui': T['ui'],
    'site': SITE,
}
if missing:
    sys.exit('未映射的文案（请补进 public_text_261105.json）：\n' + '\n'.join(sorted(missing)))

def checked_prefix(value):
    match = re.match(r'^\d{4}-\d{2}-\d{2}', value) if isinstance(value, str) else None
    return match.group(0) if match else value


def clean_checked(o):
    # 公开版只保留核验日期，去掉内部流程备注（如“未完成……核验”）
    if isinstance(o, dict):
        return {k: checked_prefix(v) if k == 'checked' and isinstance(v, str) else clean_checked(v) for k, v in o.items()}
    if isinstance(o, list):
        return [clean_checked(x) for x in o]
    return o
pub = clean_checked(pub)
esc = lambda s: html.escape(str(s), quote=True)
TPL_SRC = TPL.read_text(encoding='utf-8')
UI = T['ui']

def ui(k, lg, **values):
    v = UI[k][lg]
    if not isinstance(v, str) or not v.strip():
        raise ValueError('Missing UI translation: ' + k + '/' + lg)
    for key, value in {'date': date, **values}.items():
        v = v.replace('{' + key + '}', str(value))
    return v

def static_lang(html, lg):
    """Pre-render the data-i18n* text in the static body for language lg (same strings the JS applyLang() writes)."""
    head, sep, tail = html.partition('<script id="model-data"')
    # plain text elements (no child tags)
    head = re.sub(r'(<(\w+)\b[^>]*\bdata-i18n="([^"]+)"[^>]*>)([^<]*)(</\2>)', lambda m: m.group(1) + esc(ui(m.group(3), lg)).replace('&quot;', '"') + m.group(5), head)
    # html elements
    head = re.sub(r'(<(\w+)\b[^>]*\bdata-i18n-html="([^"]+)"[^>]*>)(.*?)(</\2>)', lambda m: m.group(1) + ui(m.group(3), lg) + m.group(5), head, flags=re.S)
    def attr(tagattr, target):
        def f(m):
            tag = m.group(0); k = re.search(tagattr + r'="([^"]+)"', tag).group(1)
            return re.sub(r'(?<![\w-])' + target + r'="[^"]*"', target + '="' + esc(ui(k, lg)) + '"', tag, count=1)
        return f
    head = re.sub(r'<[^>]*\bdata-i18n-ph="[^"]+"[^>]*>', attr('data-i18n-ph', 'placeholder'), head)
    head = re.sub(r'<[^>]*\bdata-i18n-aria="[^"]+"[^>]*>', attr('data-i18n-aria', 'aria-label'), head)
    head = re.sub(r'<[^>]*\bdata-i18n-title="[^"]+"[^>]*>', attr('data-i18n-title', 'title'), head)
    if lg == 'en':
        head = head.replace('<button id="lang" class="pill" aria-label="Switch language">EN</button>', '<button id="lang" class="pill" aria-label="切换到中文">中文</button>')
        head = re.sub(r'(<button id="theme"[^>]*>)[^<]*(</button>)', lambda m: m.group(1) + ui('theme.light', 'en') + m.group(2), head)
    return head + sep + tail

def localized(value, lg):
    return value.get(lg, value.get('zh', '')) if isinstance(value, dict) else str(value or '')

def profile(row, lg):
    return localized(row.get('profile'), lg) or row.get('effort') or ui('cfg.default', lg)

def label(row, lg):
    return row['name'] + ' · ' + profile(row, lg)

def is_number(value):
    return type(value) in (int, float) and math.isfinite(value)

def default_rows(lg):
    selected = [r for r in pub['rows'] if r.get('status') == 'complete'
                and is_number(r.get('score')) and r.get('benchmarkVersion') == pub['benchmarkVersion']
                and r.get('lifecycle') != 'archived' and r['score'] >= 0 and r.get('primary')]
    # Browser parity checks guard differences between Unicode and locale sorting.
    return sorted(selected, key=lambda r: (-r['score'], label(r, lg)))

def number(value, digits=0):
    if not is_number(value):
        return '—'
    # Match toFixed rounding on the stored binary number, including half ties.
    rounded = Decimal(value).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)
    return format(rounded, f'.{digits}f')

def money(value):
    return '—' if not is_number(value) else '<$0.01' if value < .01 else '$' + number(value, 2)

def render_default_rows(selected, lg):
    result, last, rank = [], None, 0
    for position, r in enumerate(selected, 1):
        if r['score'] != last:
            rank = position
        last = r['score']
        badges = ''
        if r.get('added') or r.get('updated'):
            badges += '<span class="badge new">' + esc(ui('badge.new' if r.get('added') else 'badge.updated', lg)) + '</span>'
        if r.get('kind') == 'restricted':
            badges += '<span class="badge warn">' + esc(ui('badge.notSale' if r.get('publicAccess') is False else 'badge.restricted', lg)) + '</span>'
        release = '<span class="release-date">' + esc(ui('released', lg) + ' ' + r['released']) + '</span>' if r.get('released') else ''
        vendor = localized(pub['vendorNames'].get(r['vendor'], r['vendor']), lg)
        cells = [f'<td class="rankcol"><span class="rank {"toprank" if rank <= 3 else ""}">{rank}</span></td>',
                 f'<td class="modelcol">{model_link(r, lg)}<span class="sub">{esc(profile(r, lg))} · {esc(vendor)}</span>{release}{badges}</td>']
        for key, value, unit in [('score', number(r.get('score')), None),
                                 ('cost', money(r.get('cost')), 'unit.conflict' if r.get('costStatus') == 'source_conflict' else 'unit.cost'),
                                 ('taskMin', number(r.get('taskMin'), 1), 'unit.task'),
                                 ('tps', number(r.get('tps')), 'unit.tps'),
                                 ('ttfat', number(r.get('ttfat'), 2), 'unit.sec')]:
            units = '<span class="units">' + esc(ui(unit, lg)) + '</span>' if unit else ''
            cells.append(f'<td class="datacell" data-label="{esc(ui("col." + key, lg))}"><div class="numcell {"selected" if key == "score" else ""}">{esc(value)}</div>{units}</td>')
        result.append(f'<tr data-id="{esc(r["id"])}">' + ''.join(cells) + '</tr>')
    return ''.join(result)

def json_text(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).replace('</', '<\\/')

def source_citations(lg):
    unique = {}
    for source in sorted(pub['sources'], key=lambda s: s['checked']):
        unique[source['url']] = source
    return [{'@type': 'CreativeWork', 'name': localized(s['title'], lg), 'url': s['url']}
            for s in unique.values()]

def build_jsonld(lg, selected):
    language = 'zh-CN' if lg == 'zh' else 'en'
    graph = [
        {'@type': 'WebSite', '@id': SITE['zh'] + '#website', 'name': 'Models Rank',
         'url': SITE['zh'], 'inLanguage': language, 'description': ui('seo.dataset.description', lg)},
        {'@type': 'Dataset', '@id': SITE[lg] + '#dataset', 'name': ui('seo.dataset.name', lg),
         'description': ui('seo.dataset.description', lg), 'url': SITE[lg], 'inLanguage': language,
         'dateModified': pub['date'], 'creator': {'@type': 'Organization', 'name': 'Models Rank', 'url': SITE['zh']},
         'citation': source_citations(lg)},
        {'@type': 'ItemList', '@id': SITE[lg] + '#ranking', 'name': ui('seo.itemlist.name', lg),
         'numberOfItems': len(selected[:20]), 'itemListOrder': 'https://schema.org/ItemListOrderDescending',
         'itemListElement': [{'@type': 'ListItem', 'position': i, 'name': label(row, lg),
                              'url': detail_url(row['base'], lg)}
                             for i, row in enumerate(selected[:20], 1)]}]
    if ABOUT_STATE['source_repo']:
        graph[0]['sameAs'] = ABOUT_STATE['source_repo']
    if ABOUT_STATE['ready']:
        graph[0]['publisher'] = {'@id': SITE['zh'] + '#operator'}
        graph[1]['creator'] = {'@id': SITE['zh'] + '#operator'}
        graph[1]['license'] = ABOUT_URLS[lg] + '#data-license'
        graph.append(operator_entity(lg))
    return {'@context': 'https://schema.org', '@graph': graph}

def auxiliary_files():
    agents = ['*', 'GPTBot', 'OAI-SearchBot', 'ClaudeBot', 'PerplexityBot', 'Google-Extended']
    robots = '\n\n'.join('User-agent: ' + a + '\nAllow: /' for a in agents) + '\n\nSitemap: ' + SITE['zh'] + 'sitemap.xml\n'
    ns, xhtml = 'http://www.sitemaps.org/schemas/sitemap/0.9', 'http://www.w3.org/1999/xhtml'
    ET.register_namespace('', ns)
    ET.register_namespace('xhtml', xhtml)
    root = ET.Element(f'{{{ns}}}urlset')
    page_pairs = [SITE] + ([ABOUT_URLS] if ABOUT_STATE['ready'] else []) + [{lg: detail_url(slug, lg) for lg in SITE} for slug in INDEXABLE_BASES]
    for pair, lg in ((pair, lg) for pair in page_pairs for lg in SITE):
        url = pair[lg]
        entry = ET.SubElement(root, f'{{{ns}}}url')
        ET.SubElement(entry, f'{{{ns}}}loc').text = url
        for language, target in [('zh-CN', pair['zh']), ('en', pair['en']), ('x-default', pair['zh'])]:
            ET.SubElement(entry, f'{{{xhtml}}}link', rel='alternate', hreflang=language, href=target)
    error = ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
             '<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">'
             '<title>' + esc(ui('seo.notfound', 'zh') + ' / ' + ui('seo.notfound', 'en')) + '</title>'
             '<style>body{background:#0b1018;color:#eef3fa;font:20px/1.6 system-ui;margin:12vh 8vw}a{color:#67d9d0;margin-right:2em}</style>'
             '</head><body><h1>' + esc(ui('seo.notfound', 'zh')) + ' / <span lang="en">' + esc(ui('seo.notfound', 'en')) + '</span></h1>'
             '<a href="/">' + esc(ui('seo.home', 'zh')) + '</a><a lang="en" href="/en/">' + esc(ui('seo.home', 'en')) + '</a><footer>' + about_footer('zh') + ' · ' + about_footer('en') + ' · ' + source_footer('zh') + ' · ' + source_footer('en') + '</footer></body></html>\n')
    def plain(value):
        return html.unescape(re.sub(r'<[^>]+>', '', value))
    lines = ['# Models Rank', '']
    for lg in SITE:
        lines.extend(['> ' + ui('seo.dataset.description', lg), '', ui('seo.updated', lg), ''])
    lines.extend(['## ' + ui('method.h', 'zh') + ' / ' + ui('method.h', 'en'), ''])
    for key in ['method.score', 'seo.cost', 'method.speed', 'seo.scope']:
        for lg in SITE:
            lines.extend([plain(ui(key, lg)), ''])
    lines.extend(['## ' + ui('seo.pages', 'zh') + ' / ' + ui('seo.pages', 'en'), ''])
    lines.extend(f'- [{ui("seo.page", lg)}]({url})' for lg, url in SITE.items())
    lines.extend(f'- [{about_copy("link", lg)}]({url})' for lg, url in ABOUT_URLS.items())
    lines.extend(['- [Sitemap](' + SITE['zh'] + 'sitemap.xml)', '', '## ' + ui('seo.sources', 'zh') + ' / ' + ui('seo.sources', 'en'), ''])
    for sid in SELECTED_SOURCE_IDS:
        source = SOURCE_INDEX[sid]
        lines.append(f'- [{localized(source["title"], "en")}]({source["url"]})')
    lines.extend(['', '## ' + ui('detail.pages', 'zh') + ' / ' + ui('detail.pages', 'en'), ''])
    for lg in SITE:
        lines.extend([ui('detail.scope', lg), ''])
    for slug, row in DETAIL_INDEX.items():
        for lg in SITE:
            lines.append(f'- [{row["name"]} ({lg})]({detail_url(slug, lg)})')
    return {'robots.txt': robots, 'sitemap.xml': ET.tostring(root, encoding='unicode', xml_declaration=True) + '\n',
            '404.html': error, 'llms.txt': '\n'.join(lines) + '\n'}

def validate_png(path, size=(1200, 630)):
    data = path.read_bytes()
    if data[:8] != b'\x89PNG\r\n\x1a\n' or data[12:16] != b'IHDR' or len(data) < 24 or struct.unpack('>II', data[16:24]) != size:
        raise ValueError('Expected a %s x %s PNG: %s' % (*size, path))

def detail_eligible(row):
    return row.get('primary') is True and row.get('lifecycle') != 'archived'


def build_detail_index():
    result = {}
    for row in pub['rows']:
        if not detail_eligible(row):
            continue
        slug = row.get('base')
        if not isinstance(slug, str) or not re.fullmatch(r'[a-z0-9-]+', slug):
            raise ValueError('Invalid detail slug: ' + row['id'])
        if slug in result:
            raise ValueError('Duplicate detail slug: ' + slug)
        result[slug] = row
    return dict(sorted(result.items()))


def detail_path(slug, lg):
    return ('/en' if lg == 'en' else '') + '/m/' + slug + '/'


def detail_url(slug, lg):
    return SITE['zh'].rstrip('/') + detail_path(slug, lg)


def model_link(row, lg):
    if row.get('lifecycle') != 'archived' and row.get('base') in DETAIL_INDEX:
        return (f'<a class="modelbtn" href="{detail_path(row["base"], lg)}" '
                f'data-detail="{esc(row["id"])}">{esc(row["name"])}</a>')
    return f'<button class="modelbtn" data-detail="{esc(row["id"])}">{esc(row["name"])}</button>'


def current_score(row):
    return (row.get('lifecycle') != 'archived' and row.get('status') == 'complete' and is_number(row.get('score'))
            and row['score'] >= 0 and row.get('benchmarkVersion') == pub['benchmarkVersion'])


def page_noindex(page):
    return page['archived'] or (not current_score(page['row'])
        and not is_number((page['row'].get('legacy') or {}).get('score')))


def representative_date(row):
    def parsed(value):
        if not isinstance(value, str):
            return None
        try:
            return datetime.date.fromisoformat(checked_prefix(value))
        except ValueError:
            return None
    return (parsed(row.get('updated')) or parsed(row.get('checked'))
            or max(parsed(row.get('added')) or datetime.date.min,
                   parsed(row.get('released')) or datetime.date.min))


def build_page_plan():
    # A missing manifest is an error: only the reviewed published baseline can initialize it.
    previous = json.loads(MANIFEST.read_text(encoding='utf-8'))
    if (not isinstance(previous, list)
            or any(not isinstance(p, str) or not re.fullmatch(r'/(?:en/)?m/[a-z0-9-]+/', p) for p in previous)
            or previous != sorted(set(previous))):
        raise ValueError('Invalid published URL manifest')
    redirects = json.loads((HERE / 'url_redirects.json').read_text(encoding='utf-8'))
    if not isinstance(redirects, dict):
        raise ValueError('Invalid URL redirect mapping')
    for source, target in redirects.items():
        if any(not isinstance(s, str) or not re.fullmatch(r'[a-z0-9-]+', s) for s in (source, target)):
            raise ValueError('Invalid redirect slug')
        if source in DETAIL_INDEX:
            raise ValueError('Redirect source has an active primary: ' + source)
    grouped = {}
    for row in pub['rows']:
        grouped.setdefault(row.get('base'), []).append(row)
    published_bases = {p.split('/')[-2] for p in previous}
    archives = {}
    for slug in sorted(published_bases - DETAIL_INDEX.keys() - redirects.keys()):
        candidates = grouped.get(slug, [])
        pools = [[r for r in candidates if r.get('primary') is True and r.get('lifecycle') == 'archived'],
                 [r for r in candidates if r.get('lifecycle') == 'archived'], candidates]
        pool = next((p for p in pools if p), [])
        if pool:
            archives[slug] = max(pool, key=lambda r: (representative_date(r), r['id']))
    pages = {slug: {'row': row, 'archived': False} for slug, row in DETAIL_INDEX.items()}
    pages.update({slug: {'row': row, 'archived': True} for slug, row in archives.items()})
    pages = dict(sorted(pages.items()))
    resolved = {}
    for source in sorted(redirects):
        target, visited = source, set()
        while target in redirects:
            if target in visited:
                raise ValueError('Redirect cycle: ' + source)
            visited.add(target)
            target = redirects[target]
        if target not in pages:
            raise ValueError('Redirect destination has no detail page: ' + target)
        resolved[source] = target
    generated = {detail_path(slug, lg) for slug in pages for lg in SITE}
    redirected = {detail_path(slug, lg) for slug in resolved for lg in SITE}
    lost = set(previous) - generated - redirected
    if lost:
        raise ValueError('Published detail URLs would disappear:\n' + '\n'.join(sorted(lost)))
    return archives, pages, resolved, sorted(set(previous) | generated | redirected)


def render_all_models(lg):
    groups = {key: [] for key in ('current', 'legacy', 'unscored', 'archived')}
    for slug, page in DETAIL_PAGES.items():
        row = page['row']
        key = ('archived' if page['archived'] else 'current' if current_score(row)
               else 'legacy' if is_number((row.get('legacy') or {}).get('score')) else 'unscored')
        groups[key].append((slug, row))
    output = '<section id="all-models" class="section" aria-labelledby="all-models-heading">'
    output += '<h2 id="all-models-heading" data-i18n="allmodels.heading">' + esc(ui('allmodels.heading', lg)) + '</h2>'
    for key, entries in groups.items():
        if not entries:
            continue
        output += f'<h3 data-i18n="allmodels.{key}">' + esc(ui('allmodels.' + key, lg)) + '</h3><ul>'
        for slug, row in entries:
            output += f'<li><a href="{detail_path(slug, lg)}" data-model-slug="{slug}">{esc(row["name"])}</a></li>'
        output += '</ul>'
    return output + '</section>'


def primary_score_ranks(lg):
    ranks, last, rank = {}, None, 0
    for position, row in enumerate(default_rows(lg), 1):
        if row['score'] != last:
            rank = position
        ranks[row['id']], last = rank, row['score']
    return ranks


def other_configurations(row):
    return sorted((r for r in pub['rows'] if r.get('base') == row['base'] and r['id'] != row['id']
                   and r.get('lifecycle') != 'archived'
                   and (current_score(r) or is_number((r.get('legacy') or {}).get('score')))),
                  key=lambda r: (not current_score(r), r['id']))


def detail_localized(value, lg):
    if isinstance(value, dict):
        if not isinstance(value.get(lg), str) or not value[lg].strip():
            raise ValueError('Missing detail translation: ' + lg)
        return value[lg]
    return str(value) if value is not None else ''


def model_source_ids(row, configs):
    ids = set()
    for r in [row, *configs]:
        ids.update(r.get('sources', []))
        ids.update(s for s in r.get('fieldSources', {}).values() if s)
        if r.get('availability', {}).get('source'):
            ids.add(r['availability']['source'])
    unknown = ids - SOURCE_INDEX.keys()
    if unknown:
        raise ValueError('Unknown model sources: ' + ', '.join(sorted(unknown)))
    return sorted(ids)


def selected_source_ids():
    """Use raw metadata only for selection; public titles come from SOURCE_INDEX."""
    categories = ['intelligence', 'performance', 'methodology', 'board', 'arena']
    candidates = {key: [] for key in categories}
    cutoff = datetime.date.fromisoformat(date)
    for source in raw['sources']:
        if source.get('historical'):
            continue
        url = urlsplit(source['url'])
        host, path = url.hostname, url.path.rstrip('/')
        category = None
        if host in ('artificialanalysis.ai', 'www.artificialanalysis.ai'):
            category = {'/methodology/intelligence-benchmarking': 'intelligence',
                        '/methodology/performance-benchmarking': 'performance',
                        '/methodology': 'methodology'}.get(path)
            if path == '/leaderboards/models' and (source['id'].startswith('aa-board-') or source['id'] == 'aa-current-board'):
                category = 'board'
        elif host in ('arena.ai', 'www.arena.ai') and path in ('/leaderboard/text', '/leaderboard/chat/text'):
            category = 'arena'
        if category is None:
            continue
        checked = datetime.date.fromisoformat(checked_prefix(source['checked']))
        published = datetime.date.fromisoformat(source['published']) if source.get('published') else datetime.date.min
        suffix = re.search(r'-(\d{8})([a-z]*)$', source['id'])
        snapshot = datetime.datetime.strptime(suffix[1], '%Y%m%d').date() if suffix else published
        if max(checked, published, snapshot) > cutoff:
            continue
        candidates[category].append(((checked, snapshot, suffix[2] if suffix else '', source['id']), source['id']))
    result, seen = [], set()
    for category in categories:
        if not candidates[category]:
            print('WARNING llms: missing source category: ' + category, file=sys.stderr)
            continue
        sid = max(candidates[category])[1]
        source = SOURCE_INDEX[sid]
        for lg in SITE:
            detail_localized(source['title'], lg)
        if source['url'] not in seen:
            result.append(sid)
            seen.add(source['url'])
    return result


def build_detail_jsonld(row, lg, description, source_ids):
    url = detail_url(row['base'], lg)
    entity = {'@type': 'SoftwareApplication', '@id': url + '#model', 'name': row['name'],
              'identifier': row['base'], 'url': url, 'description': description,
              'applicationCategory': 'Artificial Intelligence',
              'creator': {'@type': 'Organization', 'name': detail_localized(pub['vendorNames'].get(row['vendor'], row['vendor']), lg)},
              'citation': [{'@type': 'CreativeWork', 'name': detail_localized(SOURCE_INDEX[s]['title'], lg),
                            'url': SOURCE_INDEX[s]['url']} for s in source_ids]}
    if row.get('released'):
        entity['datePublished'] = row['released']
    return {'@context': 'https://schema.org', '@graph': [entity,
        {'@type': 'BreadcrumbList', 'itemListElement': [
            {'@type': 'ListItem', 'position': 1, 'name': ui('detail.breadcrumb.home', lg), 'item': SITE[lg]},
            {'@type': 'ListItem', 'position': 2, 'name': row['name'], 'item': url}]}]}


def render_detail(row, lg, archived=False):
    configs = [] if archived else other_configurations(row)
    source_ids = model_source_ids(row, configs)
    cfg = detail_localized(row.get('profile'), lg) or row.get('effort') or ui('cfg.default', lg)
    legacy = row.get('legacy') or {}
    state = 'archived' if archived else 'scored' if current_score(row) else 'legacy' if is_number(legacy.get('score')) else 'unscored'
    description = ui('detail.desc.' + state, lg, name=row['name'], profile=cfg,
                     index=pub['benchmarkVersion'], score=number(row.get('score')))
    missing = ui('detail.missing', lg)

    def source_link(sid):
        source = SOURCE_INDEX[sid]
        return f'<a href="{esc(source["url"])}">{esc(detail_localized(source["title"], lg))}</a>'

    def metric(r, key, heading, value):
        sid = r.get('fieldSources', {}).get(key)
        checked = r.get('fieldChecked', {}).get(key) or r.get('checked') or missing
        return (f'<div><dt>{esc(heading)}</dt><dd data-metric="{key}"><strong>{esc(value)}</strong></dd>'
                f'<dd><small>{esc(ui("checked", lg))} · {esc(checked)}</small>'
                + (f'<small>{source_link(sid)}</small>' if sid else '') + '</dd></div>')

    def metrics(r, main=False):
        old = r.get('legacy') or {}
        score = number(r['score']) if current_score(r) else ui('detail.notcurrent' if is_number(old.get('score')) else 'detail.unscored', lg)
        index = pub['benchmarkVersion']
        if archived:
            score = number(r.get('score')) if is_number(r.get('score')) else ui('detail.unscored', lg)
            index = r.get('benchmarkVersion') or ui('detail.version.missing', lg)
        cells = [metric(r, 'score', ui('d.score', lg, idx=index), score)]
        if main and not archived:
            rank = primary_score_ranks(lg).get(r['id'], ui('detail.unranked', lg))
            cells.append(f'<div><dt>{esc(ui("detail.rank", lg))}</dt><dd data-rank>{esc(rank)}</dd></div>')
        for key, value, unit in [('cost', money(r.get('cost')), 'unit.cost'),
                                 ('taskMin', number(r.get('taskMin'), 1), 'unit.task'),
                                 ('tps', number(r.get('tps')), 'unit.tps'),
                                 ('ttfat', number(r.get('ttfat'), 2), 'unit.sec')]:
            cells.append(metric(r, key, ui('col.' + key, lg) + ' · ' + ui(unit, lg), value))
        if r.get('costStatus') == 'source_conflict':
            cells.append(f'<div><dt>{esc(ui("col.cost", lg))}</dt><dd>{esc(ui("unit.conflict", lg))}</dd></div>')
        output = '<dl class="stats">' + ''.join(cells) + '</dl>'
        if is_number(old.get('score')):
            output += '<p class="legacy">' + esc(ui('d.legacy', lg, v=old.get('index') or ui('detail.version.missing', lg))) + ' ' + esc(ui('d.legacyBody', lg, s=number(old['score']), c=money(old.get('cost')), date=old.get('checked') or missing, idx=pub['benchmarkVersion'])) + '</p>'
        return output

    def notes(r):
        content = []
        for key, heading in [('note', None), ('routingNote', 'd.version'), ('priceNote', 'd.price'), ('costNote', 'd.costnote')]:
            if r.get(key):
                prefix = '<strong>' + esc(ui(heading, lg)) + '</strong>' if heading else ''
                content.append('<p>' + prefix + esc(detail_localized(r[key], lg)) + '</p>')
        a = r.get('availability')
        if a:
            content.append('<p><strong>' + esc(ui('d.availability', lg)) + '</strong>' + esc(detail_localized(a['status'], lg))
                           + (f' {source_link(a["source"])}' if a.get('source') else '')
                           + '<small>' + esc(ui('checked', lg)) + ' · ' + esc(a.get('checked') or missing) + '</small></p>')
        return '<div class="notes">' + ''.join(content) + '</div>'

    vendor = detail_localized(pub['vendorNames'].get(row['vendor'], row['vendor']), lg)
    body = f'<p class="muted">{esc(vendor)}</p><h1>{esc(row["name"])}</h1>'
    if archived:
        body += '<p class="badge">' + esc(ui('allmodels.archived', lg)) + '</p>'
    body += f'<p>{esc(ui("detail.configuration.archived" if archived else "detail.configuration", lg))} · {esc(cfg)}</p>'
    body += metrics(row, True)
    facts = [('d.context', row.get('context') or missing), ('released', row.get('released') or missing),
             ('detail.date', date), ('detail.index', (row.get('benchmarkVersion') or ui('detail.version.missing', lg)) if archived else pub['benchmarkVersion'])]
    body += '<dl class="stats">' + ''.join(f'<div><dt>{esc(ui(k, lg))}</dt><dd>{esc(v)}</dd></div>' for k, v in facts) + '</dl>'
    if row.get('contextExact'):
        body += '<p>' + esc(detail_localized(row['contextExact'], lg)) + '</p>'
    body += notes(row) + '<p>' + ui('d.speedNote', lg) + '</p><p>' + esc(ui('d.conditions', lg)) + '</p>'
    if configs:
        body += '<section><h2>' + esc(ui('detail.other', lg)) + '</h2>'
        for is_current in (True, False):
            group = [r for r in configs if current_score(r) == is_current]
            if not group:
                continue
            body += '<h3>' + esc(ui('detail.current' if is_current else 'detail.legacy', lg)) + '</h3>'
            for r in group:
                prof = detail_localized(r.get('profile'), lg) or r.get('effort') or ui('cfg.default', lg)
                body += f'<article><h3>{esc(prof)}</h3>' + metrics(r) + notes(r) + '</article>'
        body += '</section>'
    body += '<section><h2>' + esc(ui('d.sources', lg)) + '</h2><ul class="sources">'
    body += ''.join(f'<li>{source_link(s)}<small>{esc(ui("checked", lg))} · {esc(SOURCE_INDEX[s]["checked"])}</small></li>' for s in source_ids) + '</ul></section>'
    other = 'en' if lg == 'zh' else 'zh'
    home = '/en/' if lg == 'en' else '/'
    nav = f'<span><a href="{home}">{esc(ui("detail.breadcrumb.home", lg))}</a> / {esc(row["name"])}</span>'
    nav += f'<a lang="{"en" if other == "en" else "zh-CN"}" href="{detail_path(row["base"], other)}">{"English" if other == "en" else "中文"}</a>'
    params = {'lang': lg, 'm': row['id']}
    if state == 'legacy':
        params['view'] = 'legacy'
    target = home + '?' + urlencode(params) + ('#watch' if state == 'unscored' else '')
    footer = f'<a href="{home}">{esc(ui("detail.back", lg))}</a><a href="{esc(target)}">{esc(ui("detail.view", lg))}</a>'
    if archived:
        footer = f'<a href="{home}">{esc(ui("detail.back", lg))}</a>'
    footer += about_footer(lg) + source_footer(lg)
    replacements = {'HTML_LANG': 'zh-CN' if lg == 'zh' else 'en', 'TITLE': esc(ui('detail.title.archived' if archived else 'detail.title', lg, name=row['name'])),
                    'ROBOTS_META': '<meta name="robots" content="noindex">' if page_noindex({'row': row, 'archived': archived}) else '',
                    'DESC': esc(description), 'URL_SELF': detail_url(row['base'], lg),
                    'URL_ZH': detail_url(row['base'], 'zh'), 'URL_EN': detail_url(row['base'], 'en'),
                    'OG_LOCALE': 'zh_CN' if lg == 'zh' else 'en_US', 'OG_LOCALE_ALT': 'en_US' if lg == 'zh' else 'zh_CN',
                    'JSON_LD': json_text(build_detail_jsonld(row, lg, description, source_ids)),
                    'NAV': nav, 'BODY': body, 'FOOTER': footer}
    output = MODEL_TPL
    for key, value in replacements.items():
        output = output.replace('{{' + key + '}}', value)
    if re.search(r'\{\{[A-Z_]+\}\}', output):
        raise ValueError('Unfilled detail template')
    return output


# About is deliberately self-contained here; the checker validates inputs independently.
ABOUT_URLS = {lg: url + 'about/' for lg, url in SITE.items()}
ABOUT_FIELDS = {'date', 'operator_name', 'correction', 'aa_terms', 'repo'}
ABOUT_BLACK = ['暂时保持', 'Nov 4 values', '72 小时', '72-hour', '首 token 延迟', 'speedV2', '图中型号', '截图', '双子', '本轮', '复核', 'Codex', 'SHA', '请先更新', '上版', '口径', '本次未复核', 'screenshot', 'rawPrevious', 'auditChanges', '导出当前 CSV', '完整数据 JSON', '本机', '离线快照', 'SpaceXAI', 'draft translation']

def validate_about():
    from string import Formatter
    import unicodedata
    config = T.get('about_config', {})
    if not isinstance(config, dict):
        raise ValueError('about_config must be an object')
    op, channel = config.get('operator', {}), config.get('corrections', {})
    if channel is None:
        channel = {}
    if not isinstance(op, dict) or not isinstance(channel, dict):
        raise ValueError('About operator/corrections must be objects')
    names = op.get('name')
    if names is None:
        names = {}
    if not isinstance(names, dict):
        raise ValueError('About operator.name must be an object or null')
    missing = []
    def field(value, key):
        if value is None:
            missing.append(key)
            return ''
        if not isinstance(value, str) or any(unicodedata.category(c).startswith('C') for c in value) or re.search(r'[{}<>]', value):
            raise ValueError('Invalid About field: ' + key)
        value = value.strip()
        if not value:
            missing.append(key)
        return value
    names = {lg: field(names.get(lg), 'operator.name.' + lg) for lg in SITE}
    if op.get('entity_type') != 'Person':
        raise ValueError('About operator.entity_type must be Person')
    repo_pattern = r'https://github\.com/[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?/[A-Za-z0-9_-][A-Za-z0-9_.-]*'
    source_repo = field(config.get('source_repo'), 'source_repo')
    if source_repo and not re.fullmatch(repo_pattern, source_repo):
        raise ValueError('Invalid About source_repo URL')
    raw_channels = channel.get('channels', [channel] if channel else [])
    if raw_channels is None:
        raw_channels = []
    if not isinstance(raw_channels, list):
        raise ValueError('About corrections.channels must be a list')
    channels = []
    for entry in raw_channels:
        if not isinstance(entry, dict):
            raise ValueError('About correction channel must be an object')
        before = len(missing)
        kind = field(entry.get('type'), 'corrections.type')
        value = field(entry.get('value'), 'corrections.value')
        del missing[before:]
        if kind and kind not in ('email', 'url', 'github_issues'):
            raise ValueError('Invalid About corrections.type')
        if value and not kind:
            raise ValueError('About correction value needs an email or url type')
        if value and kind == 'email' and not re.fullmatch(r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+", value):
            raise ValueError('Invalid About email')
        if value and kind == 'url':
            u = urlsplit(value)
            try:
                port = u.port
            except ValueError:
                raise ValueError('Invalid About HTTPS URL')
            if u.scheme != 'https' or not u.hostname or u.username is not None or u.password is not None or re.search(r'\s|\\|[<>"{}]', value) or not all(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?', part) for part in u.hostname.split('.')):
                raise ValueError('Invalid About HTTPS URL')
        if value and kind == 'github_issues' and not re.fullmatch(repo_pattern + r'/issues', value):
            raise ValueError('Invalid About github_issues URL')
        if kind and value:
            channels.append({'type': kind, 'value': value})
    if not channels:
        missing.append('corrections.channels')
    first = next((c for c in channels if c['type'] == 'email'), channels[0] if channels else {})
    kind, value = first.get('type', ''), first.get('value', '')
    def copy_check(node, path):
        if isinstance(node, dict):
            if set(node) == {'zh', 'en'}:
                if not all(isinstance(v, str) and v.strip() for v in node.values()):
                    raise ValueError('Missing About translation: ' + path)
            for key, val in node.items():
                copy_check(val, path + '.' + key)
        elif isinstance(node, list):
            for i, val in enumerate(node):
                copy_check(val, path + '.' + str(i))
        elif isinstance(node, str):
            value = unicodedata.normalize('NFKC', html.unescape(node))
            literals = []
            for literal, name, spec, conv in Formatter().parse(value):
                literals.append(literal)
                if name is not None and (name not in ABOUT_FIELDS or spec or conv):
                    raise ValueError('Unknown About placeholder: ' + path)
            literal = ''.join(literals)
            if re.search(r'\d', literal) or re.search(r'[{}]', literal):
                raise ValueError('Literal number or brace in About copy: ' + path)
            if any(w in value for w in ABOUT_BLACK):
                raise ValueError('Blacklisted About copy: ' + path)
        else:
            raise ValueError('Invalid About copy: ' + path)
    copy_check(T['about_page'], 'about_page')
    copy_check(T['about_faq'], 'about_faq')
    # Also cover future About keys added to the existing UI table.
    copy_check({k: v for k, v in UI.items() if k.startswith('about_page.')}, 'ui')
    if len(T['about_faq']) != 8:
        raise ValueError('About requires eight FAQ items')
    return {'names': names, 'kind': kind, 'value': value, 'channels': channels, 'source_repo': source_repo,
            'missing_fields': sorted(missing), 'ready': not missing}


def about_copy(key, lg, **links):
    value = T['about_page'][key][lg]
    # Escape copy before inserting caller-built, escaped anchor elements.
    return expand_about(esc(value) if links else value, lg, **links)


def expand_about(value, lg, **fields):
    import unicodedata
    result = value.format(date=date, operator_name=ABOUT_STATE['names'][lg], correction=ABOUT_STATE['value'], **fields)
    if re.search(r'[{}]', unicodedata.normalize('NFKC', html.unescape(result))):
        raise ValueError('Unfilled About placeholder')
    return result


def about_faq(lg):
    result = []
    for i, item in enumerate(T['about_faq']):
        answer = 'answer'
        if (i == 0 and not ABOUT_STATE['names'][lg]) or (i == 7 and not ABOUT_STATE['value']):
            answer = 'placeholder_answer'
        elif i == 7:
            kinds = {c['type'] for c in ABOUT_STATE['channels']}
            answer = ('answer' if {'email', 'github_issues'} <= kinds else
                      'email_answer' if 'email' in kinds else 'url_answer')
        result.append({'question': expand_about(item['question'][lg], lg), 'answer': expand_about(item[answer][lg], lg)})
    return result


def collect_about_source_usage():
    from html.parser import HTMLParser
    class PrimaryLinks(HTMLParser):
        def __init__(self):
            super().__init__()
            self.depth, self.urls = 0, set()
        def handle_starttag(self, tag, attrs):
            a = dict(attrs)
            if tag == 'div':
                if self.depth or 'primarysources' in a.get('class', '').split():
                    self.depth += 1
            if self.depth and tag == 'a' and a.get('href'):
                self.urls.add(a['href'])
        def handle_endtag(self, tag):
            if tag == 'div' and self.depth:
                self.depth -= 1
    ids = set()
    for row in pub['rows']:
        if row.get('base') in DETAIL_INDEX and row.get('lifecycle') != 'archived':
            ids.update(model_source_ids(row, []))
    crosscheck = pub['crosscheck']['source']
    if crosscheck not in SOURCE_INDEX:
        raise ValueError('Unknown crosscheck source: ' + crosscheck)
    ids.add(crosscheck)
    parser = PrimaryLinks()
    parser.feed(TPL_SRC)
    for url in sorted(parser.urls):
        candidates = [s for s in pub['sources'] if s['url'] == url and s['checked'] <= date]
        if not candidates:
            raise ValueError('No dated source for homepage primary URL: ' + url)
        ids.add(max(candidates, key=lambda s: (s['checked'], s['id']))['id'])
    if ids - SOURCE_INDEX.keys():
        raise ValueError('Unknown About sources: ' + ', '.join(sorted(ids - SOURCE_INDEX.keys())))
    return sorted(ids)


def group_about_sources():
    raw_index = {s['id']: s for s in raw['sources']}
    records = {}
    for sid in collect_about_source_usage():
        source = SOURCE_INDEX[sid]
        records.setdefault(source['url'], []).append(source)
    groups = {k: {} for k in ('benchmark', 'preference', 'information')}
    for url, sources in sorted(records.items()):
        host = urlsplit(url).hostname
        category = ('benchmark' if host in ('artificialanalysis.ai', 'www.artificialanalysis.ai')
                    else 'preference' if host in ('arena.ai', 'www.arena.ai', 'lmarena.ai') else 'information')
        source = max(sources, key=lambda s: (s['checked'], s['id']))
        groups[category].setdefault(host, []).append({**source, 'historical': any(raw_index[s['id']].get('historical') for s in sources)})
    return groups


def render_about_sources(lg):
    result = ''
    for category, sites in ABOUT_SOURCES.items():
        result += '<h3>' + esc(about_copy('sources.' + category, lg)) + '</h3>'
        for host, sources in sorted(sites.items()):
            result += '<details class="source-group"><summary>' + esc(host) + '</summary><ul>'
            for s in sources:
                result += '<li><a href="' + esc(s['url']) + '">' + esc(localized(s['title'], lg)) + '</a><small>' + esc(about_copy('sources.retrieved', lg)) + ' · <time>' + esc(s['checked']) + '</time>'
                if s['historical']:
                    result += ' · <span class="historical">' + esc(about_copy('sources.historical', lg)) + '</span>'
                result += '</small></li>'
            result += '</ul></details>'
    return result


def operator_entity(lg):
    return {'@type': 'Person', '@id': SITE['zh'] + '#operator', 'name': ABOUT_STATE['names'][lg]}


def source_footer(lg):
    if not ABOUT_STATE['source_repo']:
        return ''
    return ('<a class="sociallink" data-i18n="about_page.source" href="' + esc(ABOUT_STATE['source_repo'])
            + '" target="_blank" rel="noopener noreferrer">' + esc(ui('about_page.source', lg)) + '</a>')


def about_footer(lg):
    return '<a href="' + ('/en/about/' if lg == 'en' else '/about/') + '">' + esc(about_copy('link', lg)) + '</a>'


def render_about(lg):
    language, home = ('en', '/en/') if lg == 'en' else ('zh-CN', '/')
    other = 'zh' if lg == 'en' else 'en'
    faq = about_faq(lg)
    title, desc, url = about_copy('title', lg), about_copy('description', lg), ABOUT_URLS[lg]
    body = '<h1>' + esc(about_copy('heading', lg)) + '</h1>'
    if not ABOUT_STATE['ready']:
        body += '<p class="preview">' + esc(about_copy('preview', lg)) + '</p>'
    def section(sid, heading, content):
        return '<section id="' + sid + '"><h2>' + esc(about_copy(heading, lg)) + '</h2>' + content + '</section>'
    def paragraph(key):
        return '<p>' + esc(about_copy(key, lg)) + '</p>'
    body += section('operator', 'operator.heading', paragraph('operator' if ABOUT_STATE['names'][lg] else 'operator.placeholder') + paragraph('purpose') + ('<p><a href="' + esc(ABOUT_STATE['source_repo']) + '">' + esc(about_copy('source.license', lg)) + '</a></p>' if ABOUT_STATE['source_repo'] else ''))
    body += section('sources', 'sources.heading', paragraph('sources.intro') + render_about_sources(lg))
    # Existing public HTML strings are reused exactly, with no migration or parameterization.
    body += section('methodology', 'method.heading', paragraph('method.intro') + ''.join('<p class="method-copy" data-method="' + k + '">' + UI[k][lg] + '</p>' for k in ('method.score', 'method.cost', 'method.speed')))
    aa_terms = '<a href="https://artificialanalysis.ai/terms-of-use">' + esc(about_copy('data_license.aa_terms', lg)) + '</a>'
    repo = esc(about_copy('data_license.repo', lg))
    if ABOUT_STATE['source_repo']:
        repo = '<a href="' + esc(ABOUT_STATE['source_repo']) + '">' + repo + '</a>'
    body += section('data-license', 'data_license.heading', '<p>' + about_copy('data_license', lg, aa_terms=aa_terms, repo=repo) + '</p>')
    corrections = '<h3>' + esc(about_copy('corrections.heading', lg)) + '</h3>'
    if ABOUT_STATE['channels']:
        corrections += paragraph('corrections')
        for channel in ABOUT_STATE['channels']:
            href = ('mailto:' if channel['type'] == 'email' else '') + channel['value']
            label = about_copy('corrections.github_issues', lg) if channel['type'] == 'github_issues' else channel['value']
            corrections += '<p><a class="correction" href="' + esc(href) + '">' + esc(label) + '</a></p>'
    else:
        corrections += paragraph('corrections.placeholder')
    body += section('updates', 'updates.heading', paragraph('updates') + '<div id="corrections">' + corrections + '</div>')
    body += section('faq', 'faq.heading', ''.join('<details class="faq-item"><summary>' + esc(f['question']) + '</summary><p>' + esc(f['answer']) + '</p></details>' for f in faq))
    body += section('disclaimer', 'disclaimer.heading', paragraph('disclaimer'))
    page = {'@type': 'AboutPage', '@id': url + '#page', 'url': url, 'name': title, 'description': desc, 'inLanguage': language,
            'isPartOf': {'@id': SITE['zh'] + '#website'}, 'about': {'@id': SITE['zh'] + '#website'}, 'hasPart': {'@id': url + '#faq'}}
    graph = [page, {'@type': 'FAQPage', '@id': url + '#faq', 'url': url + '#faq', 'inLanguage': language,
                    'isPartOf': {'@id': url + '#page'}, 'mainEntity': [{'@type': 'Question', 'name': f['question'], 'acceptedAnswer': {'@type': 'Answer', 'text': f['answer']}} for f in faq]}]
    if ABOUT_STATE['ready']:
        graph.append(operator_entity(lg))
        page['publisher'] = {'@id': SITE['zh'] + '#operator'}
    nav = '<a href="' + home + '">' + esc(ui('detail.breadcrumb.home', lg)) + '</a><a lang="' + ('en' if other == 'en' else 'zh-CN') + '" href="' + ('/en/about/' if other == 'en' else '/about/') + '">' + ('English' if other == 'en' else '中文') + '</a>'
    replacements = {'HTML_LANG': language, 'TITLE': esc(title), 'DESC': esc(desc), 'ROBOTS_META': '' if ABOUT_STATE['ready'] else '<meta name="robots" content="noindex">',
                    'URL_SELF': url, 'URL_ZH': ABOUT_URLS['zh'], 'URL_EN': ABOUT_URLS['en'], 'OG_LOCALE': 'zh_CN' if lg == 'zh' else 'en_US',
                    'OG_LOCALE_ALT': 'en_US' if lg == 'zh' else 'zh_CN', 'JSON_LD': json_text({'@context': 'https://schema.org', '@graph': graph}),
                    'NAV': nav, 'BODY': body, 'FOOTER': '<a href="' + home + '">' + esc(ui('detail.back', lg)) + '</a>' + about_footer(other) + source_footer(lg)}
    output = ABOUT_TPL
    for key, value in replacements.items():
        output = output.replace('{{' + key + '}}', value)
    if re.search(r'\{\{[A-Z_]+\}\}', output):
        raise ValueError('Unfilled About template')
    return output


def validate_output_paths(paths):
    # Validate before any cleanup/write. Never follow a generated-tree symlink.
    for path in paths:
        if not path.is_relative_to(HERE):
            raise ValueError('Output outside public: ' + str(path))
        for part in [path, *path.parents]:
            if part == HERE:
                break
            if part.is_symlink():
                raise ValueError('Symlink output: ' + str(part))
            if part != path and part.exists() and not part.is_dir():
                raise ValueError('Non-directory parent: ' + str(part))
        if path.exists() and not path.is_file():
            raise ValueError('Non-file output: ' + str(path))
    for tree in (HERE / 'site/m', HERE / 'site/en/m'):
        if tree.is_symlink() or (tree.exists() and not tree.is_dir()):
            raise ValueError('Invalid detail directory: ' + str(tree))
        if tree.exists() and any(p.is_symlink() for p in tree.rglob('*')):
            raise ValueError('Symlink in detail directory: ' + str(tree))

def render(lg):
    o = 'en' if lg == 'en' else 'zh'
    html = (TPL_SRC.replace('{{HTML_LANG}}', 'en' if o == 'en' else 'zh-CN')
            .replace('{{TITLE}}', esc(ui('meta.title', o))).replace('{{DESC}}', esc(ui('meta.desc', o)))
            .replace('{{URL_SELF}}', SITE[o]).replace('{{URL_ZH}}', SITE['zh']).replace('{{URL_EN}}', SITE['en'])
            .replace('{{OG_LOCALE}}', 'en_US' if o == 'en' else 'zh_CN').replace('{{OG_LOCALE_ALT}}', 'zh_CN' if o == 'en' else 'en_US')
            .replace('{{DATA}}', payload))
    selected = default_rows(o)
    html = static_lang(html, o)
    html = (html.replace('{{DEFAULT_ROWS}}', render_default_rows(selected, o))
            .replace('{{ALL_MODELS}}', render_all_models(o))
            .replace('{{ABOUT_LINK}}', about_footer(o))
            .replace('{{SOURCE_LINK}}', source_footer(o))
            .replace('{{METRIC_NOTE}}', ui('note.score', o, idx=pub['benchmarkVersion']))
            .replace('{{RESULT_COUNT}}', esc(ui('result', o, n=len(selected), valid=len(selected), scope=ui('view.primary', o))))
            .replace('{{OG_IMAGE_ALT}}', esc(ui('seo.image.alt', o)))
            .replace('{{JSON_LD}}', '<script id="structured-data" type="application/ld+json">' + json_text(build_jsonld(o, selected)) + '</script>'))
    assert '{{' not in html.split('<script id="model-data"')[0]
    return html

MODEL_TPL = (HERE / 'template_model_261105.html').read_text(encoding='utf-8')
MANIFEST = HERE / 'published_urls.json'
DETAIL_INDEX = build_detail_index()
ARCHIVE_INDEX, DETAIL_PAGES, REDIRECT_TARGETS, NEXT_PATHS = build_page_plan()
INDEXABLE_BASES = [slug for slug, page in DETAIL_PAGES.items() if not page_noindex(page)]
SOURCE_INDEX = {s['id']: s for s in pub['sources']}
SELECTED_SOURCE_IDS = selected_source_ids()
ABOUT_TPL = (HERE / 'template_about_261105.html').read_text(encoding='utf-8')
ABOUT_STATE = validate_about()
if ABOUT_STATE['missing_fields']:
    print('WARNING about: missing_fields: ' + ', '.join(ABOUT_STATE['missing_fields']), file=sys.stderr)
ABOUT_SOURCES = group_about_sources()
pub['detailSlugs'] = list(DETAIL_INDEX)
payload = json_text(pub)
zh_html, en_html = render('zh'), render('en')
SITE_DIR = HERE / 'site'
# Finish all translations, validation and rendering in memory before removing old pages.
outputs = {OUT: zh_html.encode(), SITE_DIR / 'index.html': zh_html.encode(),
           SITE_DIR / 'en/index.html': en_html.encode()}
for slug, page in DETAIL_PAGES.items():
    for lg in SITE:
        outputs[SITE_DIR / detail_path(slug, lg).lstrip('/') / 'index.html'] = render_detail(page['row'], lg, page['archived']).encode()
for lg in SITE:
    outputs[SITE_DIR / ('en/about/index.html' if lg == 'en' else 'about/index.html')] = render_about(lg).encode()
for name, content in auxiliary_files().items():
    outputs[SITE_DIR / name] = content.encode()
image_source = HERE / 'assets/og.png'
validate_png(image_source)
outputs[SITE_DIR / 'og.png'] = image_source.read_bytes()
for icon_name, size in [('favicon.png', 32), ('apple-touch-icon.png', 180), ('favicon.ico', None)]:
    icon_source = HERE / 'assets' / icon_name
    icon_bytes = icon_source.read_bytes()
    if size is not None:
        validate_png(icon_source, (size, size))
    else:
        if len(icon_bytes) < 6 or icon_bytes[:4] != b'\x00\x00\x01\x00':
            raise ValueError('Expected an ICO: ' + str(icon_source))
        count = struct.unpack_from('<H', icon_bytes, 4)[0]
        if len(icon_bytes) < 6 + count * 16 or not {(16, 16), (32, 32)} <= {
                (icon_bytes[6 + i * 16] or 256, icon_bytes[7 + i * 16] or 256) for i in range(count)}:
            raise ValueError('Expected a 16/32 ICO directory: ' + str(icon_source))
    outputs[SITE_DIR / icon_name] = icon_bytes
verification_name = 'google529a71ca053abf05'
verification = (HERE / 'assets' / (verification_name + '.html')).read_bytes()
if verification.rstrip(b'\r\n') != b'google-site-verification: google529a71ca053abf05.html':
    raise ValueError('Unexpected Google verification content')
outputs[SITE_DIR / (verification_name + '.html')] = verification
outputs[SITE_DIR / '_verification' / (verification_name + '.txt')] = verification
redirect_lines = [f'/{verification_name}.html /_verification/{verification_name}.txt 200']
redirect_lines.extend(f'{detail_path(source, lg)} {detail_path(target, lg)} 301'
                      for source, target in REDIRECT_TARGETS.items() for lg in SITE)
outputs[SITE_DIR / '_redirects'] = ('\n'.join(redirect_lines) + '\n').encode()
manifest_bytes = (json.dumps(NEXT_PATHS, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
validate_output_paths([*outputs, MANIFEST])
# Reserve and validate the same-directory temporary path before any cleanup.
with tempfile.NamedTemporaryFile(dir=HERE, prefix='.published_urls.', suffix='.tmp', delete=False) as temp:
    manifest_temp = pathlib.Path(temp.name)
try:
    validate_output_paths([MANIFEST, manifest_temp])
    for tree in (SITE_DIR / 'm', SITE_DIR / 'en/m'):
        if tree.exists():
            shutil.rmtree(tree)
    for path, content in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    # Commit the cumulative manifest only after every output has been written.
    manifest_temp.write_bytes(manifest_bytes)
    os.replace(manifest_temp, MANIFEST)
finally:
    manifest_temp.unlink(missing_ok=True)
print(f'OK rows={len(rows)} sources={len(srcs)} active={len(DETAIL_INDEX)} archived={len(ARCHIVE_INDEX)} '
      f'indexable={len(INDEXABLE_BASES)} detail_pages={len(DETAIL_PAGES) * 2} files={len(outputs)}')
