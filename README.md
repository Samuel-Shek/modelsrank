# Models Rank 模型榜

[中文](#中文) · [English](#english)

**Website / 网站：** https://modelsrank.org/ （English: https://modelsrank.org/en/）
**Maintainer / 运营者：** Samuel Shek · License / 许可证：MIT (code only / 仅代码)

---

## 中文

### 这是什么

Models Rank（模型榜）是一个中英双语的 AI 大模型榜单。它汇总 Artificial Analysis 等第三方公开评测，把模型的综合能力、完成一道评测题的平均成本和速度放在同一张表里比较。每个模型有一个详情页，标注数据来源和核对日期。网站本身不跑分，每周更新。

这个仓库是网站的源代码：一个 Python 生成器，把数据、文案表和模板生成纯静态 HTML（中文在 `/`，英文在 `/en/`，详情页在 `/m/<slug>/`），同时输出 `robots.txt`、`sitemap.xml`、`llms.txt`、`404.html` 和结构化数据。页面没有外部依赖。

### 目录

| 路径 | 说明 |
| --- | --- |
| `public/build_public_261105.py` | 生成器 |
| `public/template_public_261105.html` | 首页模板 |
| `public/template_model_261105.html` | 模型详情页模板 |
| `public/public_text_261105.json` | 中英文文案表 |
| `public/check_public_261105.py` | 维护者用的上线前检查（需要 Playwright 和 Chrome，并会与维护者的私有底稿比对） |
| `public/published_urls.json` / `url_redirects.json` | 已发布网址清单和改名跳转，防止旧网址变成 404 |
| `public/assets/` | 分享图片及其生成脚本 |
| `example/sample-data.json` | 示例数据，里面的模型和数字都是虚构的 |
| `scripts/build_example.sh` | 用示例数据生成预览站 |
| `scripts/sync_from_private.sh` | 维护者把代码从私有工作仓库同步到这里 |

### 怎么生成

需要 Python 3.10 或更高版本，不需要第三方库。

```bash
scripts/build_example.sh            # 输出到 ./preview
python3 -m http.server -d preview 8000
```

然后打开 http://localhost:8000/ 。示例站用的是虚构数据，只用来看页面结构和生成流程。

### 数据来源

线上数据来自以下公开来源，版权归各自所有者：

- [Artificial Analysis](https://artificialanalysis.ai/)：Intelligence Index 综合分、单任务评测成本、性能基准（速度）。
- [LMArena](https://lmarena.ai/)：文本榜，用于交叉对照。
- 各模型厂商的官方页面、文档和价格页：发布日期、价格、上下文长度、开放范围。

每个数字的具体来源和核对日期都列在网站对应的详情页上。

**本仓库不包含完整数据。** 第三方数据受各来源自己的使用条款约束（例如 Artificial Analysis 的条款限制转载和再分发），所以这里只放代码和虚构的示例数据。想要真实数据，请直接查阅上面的原始来源，并遵守它们的条款。本仓库的 MIT 许可证只适用于代码，不适用于任何第三方数据。

### 纠错与反馈

发现数据错误或有建议，可以在本仓库[开 Issue](https://github.com/Samuel-Shek/modelsrank/issues)，或发邮件到 yunp.shi@gmail.com 。

---

## English

### What it is

Models Rank is a bilingual (Chinese/English) leaderboard of AI models. It compiles public third-party evaluations, mainly Artificial Analysis, and compares intelligence, average cost per evaluation task and speed side by side. Every model has a detail page listing its sources and the date each value was checked. The site runs no benchmarks of its own and is updated weekly.

This repository holds the site's source code: a Python generator that turns data, a text table and templates into static HTML (Chinese at `/`, English at `/en/`, detail pages at `/m/<slug>/`), plus `robots.txt`, `sitemap.xml`, `llms.txt`, `404.html` and structured data. Pages load no external resources.

### Layout

| Path | Purpose |
| --- | --- |
| `public/build_public_261105.py` | Generator |
| `public/template_public_261105.html` | Home page template |
| `public/template_model_261105.html` | Model detail page template |
| `public/public_text_261105.json` | Chinese/English text table |
| `public/check_public_261105.py` | The maintainer's pre-release check (needs Playwright and Chrome, and compares against the maintainer's private working copy) |
| `public/published_urls.json` / `url_redirects.json` | Published URL manifest and rename redirects, so old URLs never turn into 404s |
| `public/assets/` | Social preview image and the script that draws it |
| `example/sample-data.json` | Sample data; every model and number in it is fictional |
| `scripts/build_example.sh` | Builds a preview site from the sample data |
| `scripts/sync_from_private.sh` | How the maintainer syncs code here from the private working repo |

### Build

Requires Python 3.10+ and no third-party packages.

```bash
scripts/build_example.sh            # writes ./preview
python3 -m http.server -d preview 8000
```

Then open http://localhost:8000/. The preview uses fictional data and is only meant to show the page structure and the build.

### Data sources

The live site's data comes from these public sources, which retain their own rights:

- [Artificial Analysis](https://artificialanalysis.ai/): Intelligence Index scores, cost per evaluation task, performance benchmarking (speed).
- [LMArena](https://lmarena.ai/): text leaderboard, used as a cross-check.
- Model vendors' official pages, docs and pricing pages: release dates, prices, context length, availability.

The exact source and check date of every value are listed on the model's detail page on the site.

**The full dataset is not in this repository.** Third-party data is governed by each source's own terms (Artificial Analysis's terms, for example, restrict republishing and redistribution), so this repository contains only code and fictional sample data. For real numbers, consult the original sources above and follow their terms. The MIT license covers the code only, not any third-party data.

### Corrections and feedback

Found a wrong number or have a suggestion? [Open an issue](https://github.com/Samuel-Shek/modelsrank/issues) or email yunp.shi@gmail.com.
