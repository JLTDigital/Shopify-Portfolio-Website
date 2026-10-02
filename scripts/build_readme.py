#!/usr/bin/env python3
"""Build the Readme.md blog.

Existing posts are Medium HTML exports in content/posts. New posts are
Markdown files in that same folder, created in the browser with Decap CMS
(/admin/) or written by hand. Run:

    python3 scripts/build_readme.py
"""

import html
import json
import os
import re
import shutil
import subprocess
from datetime import date, datetime
from urllib.parse import unquote, urlparse

from lxml import html as lxml_html

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE_DIR = os.path.join(ROOT, "content", "posts")
POSTS_DIR = os.path.join(ROOT, "posts")
IMAGE_ROOT = os.path.join(ROOT, "images", "posts")
SITE = "https://jlt.digital"

EMOJI = re.compile(
    "["
    "\U0001F000-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U0001F1E0-\U0001F1FF"
    "\U0000FE00-\U0000FE0F"
    "\U0000200D"
    "]+",
    flags=re.UNICODE,
)


def esc(value):
    if not value:
        return ""
    value = (
        value.replace("\xa0", " ")
        .replace("\u2009", " ")
        .replace("\u200a", " ")
        .replace("\u202f", " ")
        .replace("\u200b", "")
    )
    return html.escape(value, quote=False)


def esc_attr(value):
    return html.escape(value or "", quote=True)


def clean(value):
    if not value:
        return ""
    value = (
        value.replace("\xa0", " ")
        .replace("\u2009", " ")
        .replace("\u200a", " ")
        .replace("\u202f", " ")
        .replace("\u200b", "")
        .replace("\u2011", "-")
    )
    value = re.sub(r"[ \t]+", " ", value)
    return value.strip()


def strip_emoji(value):
    return clean(EMOJI.sub("", value or ""))


def normalize(value):
    value = strip_emoji(value).replace("’", "'").replace("‘", "'")
    value = value.replace("“", '"').replace("”", '"').casefold()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def slugify(value):
    value = strip_emoji(value)
    value = value.replace("’", "").replace("‘", "").replace("'", "")
    value = value.encode("ascii", "ignore").decode("ascii").lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "post"


def excerpt(value, limit):
    value = clean(value)
    if len(value) <= limit:
        return value
    cut = value[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(".,;:—-") + "…"


def format_date(iso):
    moment = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return moment.strftime("%-d %B %Y"), moment.strftime("%Y-%m-%d")


def inline(el):
    parts = []
    if el.text:
        parts.append(esc(el.text))
    for child in el:
        if not isinstance(child.tag, str) or child.tag in ("script", "style"):
            if child.tail:
                parts.append(esc(child.tail))
            continue
        if child.tag == "br":
            parts.append("<br />")
        elif child.tag == "a":
            href = child.get("href") or ""
            if href.startswith("/s/photos/"):
                href = "https://unsplash.com" + href
            attrs = f' href="{esc_attr(href)}"'
            if href.startswith("http"):
                attrs += ' target="_blank" rel="noopener noreferrer"'
            parts.append(f"<a{attrs}>{inline(child)}</a>")
        elif child.tag in ("strong", "b"):
            parts.append(f"<strong>{inline(child)}</strong>")
        elif child.tag in ("em", "i"):
            parts.append(f"<em>{inline(child)}</em>")
        elif child.tag == "code":
            parts.append(f"<code>{inline(child)}</code>")
        else:
            parts.append(inline(child))
        if child.tail:
            parts.append(esc(child.tail))
    return "".join(parts)


def code_html(el):
    parts = []
    if el.text:
        parts.append(esc(el.text))
    for child in el:
        if not isinstance(child.tag, str):
            if child.tail:
                parts.append(esc(child.tail))
            continue
        if child.tag == "br":
            parts.append("\n")
        elif child.tag == "span":
            classes = [
                item
                for item in (child.get("class") or "").split()
                if item.startswith("hljs")
            ]
            inner = code_html(child)
            if classes:
                parts.append(f'<span class="{" ".join(classes)}">{inner}</span>')
            else:
                parts.append(inner)
        else:
            parts.append(code_html(child))
        if child.tail:
            parts.append(esc(child.tail))
    return "".join(parts)


class PostBuilder:
    def __init__(self, slug):
        self.slug = slug
        self.cache = {}
        self.figure_count = 0
        self.cover = None
        self.warnings = []

    def localize(self, url):
        if not url:
            return ""
        if url in self.cache:
            return self.cache[url]
        ext = os.path.splitext(unquote(urlparse(url).path))[1].lower()
        if ext not in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
            ext = ".jpg"
        if self.cover is None:
            filename = f"cover{ext}"
        else:
            self.figure_count += 1
            filename = f"figure-{self.figure_count:02d}{ext}"
        site_path = f"images/posts/{self.slug}/{filename}"
        dest = os.path.join(ROOT, site_path)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if os.path.isfile(dest) and os.path.getsize(dest) > 0:
            self.cache[url] = site_path
            if self.cover is None:
                self.cover = site_path
            return site_path
        try:
            result = subprocess.run(
                ["curl", "-fsSL", "--retry", "2", "--max-time", "30", "-A", "Mozilla/5.0", "-o", dest, url],
                capture_output=True,
                timeout=40,
            )
            if result.returncode != 0 or not os.path.isfile(dest) or os.path.getsize(dest) == 0:
                raise RuntimeError(result.stderr.decode("utf-8", "replace")[:180] or "download failed")
            self.cache[url] = site_path
        except Exception as error:
            if os.path.isfile(dest) and os.path.getsize(dest) == 0:
                os.remove(dest)
            self.warnings.append(f"image {url}: {error}")
            self.cache[url] = url
        if self.cover is None:
            self.cover = self.cache[url]
        return self.cache[url]

    def render_figure(self, el):
        classes = el.get("class") or ""
        if "graf--iframe" in classes or el.find(".//script") is not None or el.find(".//iframe") is not None:
            return self.render_embed(el)
        img = el.find(".//img")
        if img is None:
            return ""
        src = img.get("src") or ""
        site_path = self.localize(src)
        web_src = site_path if site_path.startswith("http") else f"../{site_path}"
        caption_el = el.find(".//figcaption")
        alt = clean(caption_el.text_content()) if caption_el is not None else ""
        if not alt or alt.lower().startswith("photo by"):
            alt = self.fallback_alt
        width = img.get("data-width")
        height = img.get("data-height")
        size = ""
        if width and height and width.isdigit() and height.isdigit():
            size = f' width="{width}" height="{height}"'
        caption = ""
        if caption_el is not None and clean(caption_el.text_content()):
            caption = f"<figcaption>{inline(caption_el)}</figcaption>"
        figure = (
            f'<figure class="post-figure"><img src="{esc_attr(web_src)}" '
            f'alt="{esc_attr(alt)}"{size} loading="lazy" decoding="async" />{caption}</figure>'
        )
        hero = "graf--leading" in classes or img.get("data-is-featured") == "true"
        if hero and site_path == self.cover:
            self.cover_alt = alt
            return ""
        return figure

    def render_embed(self, el):
        script = el.find(".//script")
        if script is not None and script.get("src"):
            src = re.sub(r"(\.js)+$", "", script.get("src"))
            label = "View the code on GitHub" if "gist.github.com" in src else "Open the embed"
            return (
                f'<p class="post-link"><a href="{esc_attr(src)}" target="_blank" '
                f'rel="noopener noreferrer">{esc(label)}</a></p>'
            )
        iframe = el.find(".//iframe")
        if iframe is not None and iframe.get("src"):
            src = iframe.get("src")
            return (
                f'<p class="post-link"><a href="{esc_attr(src)}" target="_blank" '
                f'rel="noopener noreferrer">Open the embed</a></p>'
            )
        return ""

    def render_mixtape(self, el):
        anchors = el.xpath('./a[contains(@class, "mixtapeEmbed-anchor")]')
        if not anchors:
            return ""
        anchor = anchors[0]
        href = anchor.get("href") or ""
        title = clean("".join(anchor.xpath("./strong/text()"))) or href
        description = clean("".join(anchor.xpath("./em/text()")))
        inner = f"<strong>{esc(title)}</strong>"
        if description:
            inner += f"<br />{esc(description)}"
        return (
            f'<p class="post-link"><a href="{esc_attr(href)}" target="_blank" '
            f'rel="noopener noreferrer">{inner}</a></p>'
        )

    def render_pre(self, el):
        lang = (el.get("data-code-block-lang") or "text").strip().lower()
        lang = re.sub(r"[^a-z0-9#+-]", "", lang) or "text"
        return f'<pre><code class="language-{lang}">{code_html(el).strip()}</code></pre>'

    def render_list(self, el):
        tag = "ol" if el.tag == "ol" else "ul"
        items = []
        for li in el.xpath("./li"):
            if clean(li.text_content()):
                items.append(f"<li>{inline(li)}</li>")
        if not items:
            return ""
        return f"<{tag}>{''.join(items)}</{tag}>"


def parse_post(path):
    document = lxml_html.parse(path)
    title = strip_emoji(document.xpath('string(//h1[contains(@class, "p-name")])'))
    summary = clean(document.xpath('string(//section[contains(@class, "p-summary")])'))
    published = document.xpath("string(//time/@datetime)") or "2020-01-01T00:00:00.000Z"
    medium = document.xpath('string(//a[contains(@class, "p-canonical")]/@href)')
    slug = slugify(title)
    display_date, day = format_date(published)
    builder = PostBuilder(slug)
    builder.cover_alt = title
    builder.fallback_alt = title
    title_key = normalize(title)
    summary_key = normalize(summary)
    body = document.xpath('//section[@data-field="body"]')
    events = []
    first_paragraph = ""
    if body:
        for section in body[0].xpath("./section"):
            inners = section.xpath('.//div[contains(@class, "section-inner")]')
            if not inners:
                continue
            for child in inners[0]:
                if not isinstance(child.tag, str):
                    continue
                classes = child.get("class") or ""
                if child.tag in ("h3", "h4"):
                    heading = strip_emoji(child.text_content())
                    if not heading or normalize(heading) == title_key:
                        continue
                    events.append((child.tag, heading))
                    continue
                if child.tag == "p" and "graf--subtitle" in classes:
                    if normalize(child.text_content()) == summary_key:
                        continue
                rendered = render_block(builder, child, classes)
                if not rendered:
                    continue
                if child.tag == "p" and not first_paragraph:
                    text = clean(child.text_content())
                    if summary_key and normalize(text) == summary_key:
                        continue
                    first_paragraph = text
                events.append(("html", rendered))

    chapters = []
    for kind, value in events:
        if kind == "h3":
            chapters.append({"heading": value, "html": []})
            continue
        if kind == "h4":
            if chapters and chapters[-1]["heading"]:
                chapters[-1]["html"].append(f"<h3>{esc(value)}</h3>")
            else:
                chapters.append({"heading": value, "html": []})
            continue
        if not chapters:
            chapters.append({"heading": None, "html": []})
        chapters[-1]["html"].append(value)

    words = 0
    if body:
        words = len(re.findall(r"\w+", body[0].text_content()))
    minutes = max(1, round(words / 230)) if words else 1
    base = first_paragraph or summary or title
    return {
        "title": title,
        "slug": slug,
        "summary": summary,
        "description": excerpt(base, 155),
        "card": excerpt(base, 220),
        "published": published,
        "day": day,
        "display_date": display_date,
        "minutes": minutes,
        "words": words,
        "medium": medium,
        "cover": builder.cover,
        "cover_alt": builder.cover_alt,
        "chapters": [chapter for chapter in chapters if chapter["html"] or chapter["heading"]],
        "warnings": builder.warnings,
        "source": os.path.basename(path),
    }


def render_block(builder, child, classes):
    if child.tag == "figure" or "graf--figure" in classes:
        return builder.render_figure(child)
    if "mixtapeEmbed" in classes:
        return builder.render_mixtape(child)
    if child.tag == "pre":
        return builder.render_pre(child)
    if child.tag in ("ul", "ol"):
        return builder.render_list(child)
    if child.tag == "blockquote":
        if not clean(child.text_content()):
            return ""
        return f"<blockquote>{inline(child)}</blockquote>"
    if child.tag == "p":
        if not clean(child.text_content()):
            return ""
        return f"<p>{inline(child)}</p>"
    if child.tag in ("script", "hr", "div") and "mixtapeEmbed" not in classes:
        return ""
    text = clean(child.text_content())
    if text:
        builder.warnings.append(f"unhandled <{child.tag}> class={classes[:60]}")
        return f"<p>{esc(text)}</p>"
    return ""


def json_ld(data):
    return json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")


def head(title, description, canonical, image, extra=""):
    image_url = image if image and image.startswith("http") else f"{SITE}/{image or 'images/Profile-pic.jpg'}"
    extra_block = extra if extra.endswith("\n") or not extra else extra + "\n"
    return (
        f"""\t\t<title>{esc(title)}</title>
\t\t<meta charset="utf-8" />
\t\t<meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no" />
\t\t<script src="{{root}}assets/js/smooth-hash.js"></script>
\t\t<meta name="description" content="{esc_attr(description)}" />
\t\t<meta name="author" content="Jonny Taft" />
\t\t<link rel="canonical" href="{esc_attr(canonical)}" />
\t\t<meta property="og:title" content="{esc_attr(title)}" />
\t\t<meta property="og:description" content="{esc_attr(description)}" />
\t\t<meta property="og:type" content="article" />
\t\t<meta property="og:url" content="{esc_attr(canonical)}" />
\t\t<meta property="og:image" content="{esc_attr(image_url)}" />
\t\t<meta name="twitter:card" content="summary_large_image" />
\t\t<link rel="alternate" type="application/rss+xml" title="Readme.md · Jonny Taft" href="{SITE}/rss.xml" />
"""
        + extra_block
        + """\t\t<link rel="icon" href="{root}images/favicon.ico" type="image/x-icon" />
\t\t<link rel="shortcut icon" href="{root}images/favicon.ico" type="image/x-icon" />
\t\t<link rel="stylesheet" href="{root}assets/css/main.css" />
\t\t<link rel="stylesheet" href="{root}assets/css/portfolio.css" />"""
    )


def scripts(root, contact=False):
    block = f"""\t\t<script src="{root}assets/js/jquery.min.js"></script>
\t\t<script src="{root}assets/js/jquery.scrolly.min.js"></script>
\t\t<script src="{root}assets/js/browser.min.js"></script>
\t\t<script src="{root}assets/js/breakpoints.min.js"></script>
\t\t<script src="{root}assets/js/util.js"></script>
\t\t<script src="{root}assets/js/main.js"></script>"""
    if not contact:
        return block
    return block + """
\t\t<script src="https://www.google.com/recaptcha/api.js" async defer></script>
\t\t<script>
\t\t\t(function () {
\t\t\t\tvar form = document.getElementById('contact-form');
\t\t\t\tvar status = document.getElementById('form-status');
\t\t\t\tvar submit = document.getElementById('form-submit');

\t\t\t\tform.addEventListener('submit', function (event) {
\t\t\t\t\tevent.preventDefault();

\t\t\t\t\tvar recaptchaToken = window.grecaptcha ? window.grecaptcha.getResponse() : '';

\t\t\t\t\tif (!recaptchaToken) {
\t\t\t\t\t\tstatus.hidden = false;
\t\t\t\t\t\tstatus.className = 'form-status is-error';
\t\t\t\t\t\tstatus.textContent = 'Please confirm you are not a robot.';
\t\t\t\t\t\treturn;
\t\t\t\t\t}

\t\t\t\t\tstatus.hidden = false;
\t\t\t\t\tstatus.className = 'form-status';
\t\t\t\t\tstatus.textContent = 'Sending…';
\t\t\t\t\tsubmit.disabled = true;
\t\t\t\t\tsubmit.value = 'Sending…';

\t\t\t\t\tfetch('https://formsubmit.co/ajax/mrjltaft@gmail.com', {
\t\t\t\t\t\tmethod: 'POST',
\t\t\t\t\t\theaders: {
\t\t\t\t\t\t\t'Content-Type': 'application/json',
\t\t\t\t\t\t\t'Accept': 'application/json'
\t\t\t\t\t\t},
\t\t\t\t\t\tbody: JSON.stringify({
\t\t\t\t\t\t\tname: document.getElementById('name').value.trim(),
\t\t\t\t\t\t\temail: document.getElementById('email').value.trim(),
\t\t\t\t\t\t\tmessage: document.getElementById('message').value.trim(),
\t\t\t\t\t\t\t_subject: 'Portfolio enquiry from ' + document.getElementById('name').value.trim(),
\t\t\t\t\t\t\t'g-recaptcha-response': recaptchaToken
\t\t\t\t\t\t})
\t\t\t\t\t})
\t\t\t\t\t\t.then(function (response) {
\t\t\t\t\t\t\treturn response.json().then(function (data) {
\t\t\t\t\t\t\t\tif (!response.ok) {
\t\t\t\t\t\t\t\t\tthrow new Error(data.message || 'Unable to send message.');
\t\t\t\t\t\t\t\t}
\t\t\t\t\t\t\t\treturn data;
\t\t\t\t\t\t\t});
\t\t\t\t\t\t})
\t\t\t\t\t\t.then(function () {
\t\t\t\t\t\t\tform.reset();
\t\t\t\t\t\t\tif (window.grecaptcha) {
\t\t\t\t\t\t\t\twindow.grecaptcha.reset();
\t\t\t\t\t\t\t}
\t\t\t\t\t\t\tstatus.className = 'form-status is-success';
\t\t\t\t\t\t\tstatus.textContent = 'Thanks — your message is on its way.';
\t\t\t\t\t\t})
\t\t\t\t\t\t.catch(function () {
\t\t\t\t\t\t\tstatus.className = 'form-status is-error';
\t\t\t\t\t\t\tstatus.textContent = 'Sorry, that did not send. Email me at mrjltaft@gmail.com instead.';
\t\t\t\t\t\t})
\t\t\t\t\t\t.finally(function () {
\t\t\t\t\t\t\tsubmit.disabled = false;
\t\t\t\t\t\t\tsubmit.value = 'Send Message';
\t\t\t\t\t\t});
\t\t\t\t});
\t\t\t})();
\t\t</script>"""


def site_nav(root, current):
    home = f"{root}index.html"

    def item(key, href, label):
        current_attr = ' aria-current="page"' if key == current else ""
        return f'<li><a href="{href}"{current_attr}>{label}</a></li>'

    return (
        "\t\t<nav class=\"site-nav\" aria-label=\"Site\">\n"
        f"\t\t\t<a class=\"site-nav-home\" href=\"{home}\">Jonny Taft</a>\n"
        "\t\t\t<ul>\n"
        f"\t\t\t\t{item('home', home, 'Home')}\n"
        f"\t\t\t\t{item('work', home + '#work', 'Work')}\n"
        f"\t\t\t\t{item('readme', root + 'readme.html', 'Readme.md')}\n"
        "\t\t\t</ul>\n"
        "\t\t</nav>"
    )


def contact_section():
    return """\t\t\t\t<section id="contact">
\t\t\t\t\t<header>
\t\t\t\t\t\t<h2>Get in touch</h2>
\t\t\t\t\t</header>
\t\t\t\t\t<div class="content">
\t\t\t\t\t\t<p><strong>Tell me about the project.</strong> A short note on the brand, the brief, and where you are in the build is enough to start.</p>
\t\t\t\t\t\t<form id="contact-form">
\t\t\t\t\t\t\t<input type="hidden" name="_subject" value="Portfolio enquiry from jlt.digital" />
\t\t\t\t\t\t\t<input type="text" name="_honey" class="honeypot" tabindex="-1" autocomplete="off" />
\t\t\t\t\t\t\t<div class="fields">
\t\t\t\t\t\t\t\t<div class="field half">
\t\t\t\t\t\t\t\t\t<input type="text" name="name" id="name" placeholder="Name" required />
\t\t\t\t\t\t\t\t</div>
\t\t\t\t\t\t\t\t<div class="field half">
\t\t\t\t\t\t\t\t\t<input type="email" name="email" id="email" placeholder="Email" required />
\t\t\t\t\t\t\t\t</div>
\t\t\t\t\t\t\t\t<div class="field">
\t\t\t\t\t\t\t\t\t<textarea name="message" id="message" placeholder="Message" rows="7" required></textarea>
\t\t\t\t\t\t\t\t</div>
\t\t\t\t\t\t\t</div>
\t\t\t\t\t\t\t<div class="recaptcha-wrap">
\t\t\t\t\t\t\t\t<div class="g-recaptcha" data-sitekey="6Lc7upMtAAAAAJnqotbmTeLuz_rk3yrpTHz3i_5C"></div>
\t\t\t\t\t\t\t</div>
\t\t\t\t\t\t\t<p id="form-status" class="form-status" role="status" hidden></p>
\t\t\t\t\t\t\t<ul class="actions">
\t\t\t\t\t\t\t\t<li><input type="submit" id="form-submit" value="Send Message" class="button primary" /></li>
\t\t\t\t\t\t\t</ul>
\t\t\t\t\t\t</form>
\t\t\t\t\t</div>
\t\t\t\t\t<footer>
\t\t\t\t\t\t<ul class="items">
\t\t\t\t\t\t\t<li>
\t\t\t\t\t\t\t\t<h3>Email</h3>
\t\t\t\t\t\t\t\t<a href="mailto:mrjltaft@gmail.com">mrjltaft@gmail.com</a>
\t\t\t\t\t\t\t</li>
\t\t\t\t\t\t\t<li>
\t\t\t\t\t\t\t\t<h3>Based</h3>
\t\t\t\t\t\t\t\t<span>United Kingdom</span>
\t\t\t\t\t\t\t</li>
\t\t\t\t\t\t\t<li>
\t\t\t\t\t\t\t\t<h3>Elsewhere</h3>
\t\t\t\t\t\t\t\t<ul class="icons">
\t\t\t\t\t\t\t\t\t<li><a href="https://www.linkedin.com/in/jonathan-taft-21087771/" class="icon brands fa-linkedin-in" target="_blank" rel="noopener noreferrer"><span class="label">LinkedIn</span></a></li>
\t\t\t\t\t\t\t\t\t<li><a href="https://github.com/JLTDigital" class="icon brands fa-github" target="_blank" rel="noopener noreferrer"><span class="label">GitHub</span></a></li>
\t\t\t\t\t\t\t\t\t<li><a href="https://medium.com/@johnny-taft" class="icon brands fa-medium-m" target="_blank" rel="noopener noreferrer"><span class="label">Medium</span></a></li>
\t\t\t\t\t\t\t\t\t<li><a href="mailto:mrjltaft@gmail.com" class="icon solid fa-envelope"><span class="label">Email</span></a></li>
\t\t\t\t\t\t\t\t</ul>
\t\t\t\t\t\t\t</li>
\t\t\t\t\t\t</ul>
\t\t\t\t\t</footer>
\t\t\t\t</section>"""


def cta_section(contact_href):
    return f"""\t\t\t\t<section>
\t\t\t\t\t<header>
\t\t\t\t\t\t<h2>Let's build something</h2>
\t\t\t\t\t</header>
\t\t\t\t\t<div class="content">
\t\t\t\t\t\t<p><strong>Looking for a developer</strong> who can take a brief from design through to a live, maintainable product? I can help with Shopify themes, React or Vue apps, Node and Express APIs, and the full delivery cycle.</p>
\t\t\t\t\t\t<ul class="actions">
\t\t\t\t\t\t\t<li><a href="{contact_href}" class="button primary large">Get in touch</a></li>
\t\t\t\t\t\t\t<li><a href="https://www.linkedin.com/in/jonathan-taft-21087771/" class="button large" target="_blank" rel="noopener noreferrer">LinkedIn</a></li>
\t\t\t\t\t\t</ul>
\t\t\t\t\t</div>
\t\t\t\t</section>"""


def cover_src(post, root):
    cover = post["cover"] or "images/Profile-pic.jpg"
    if cover.startswith("http"):
        return cover
    return f"{root}{cover}"


def render_post(post, newer, older):
    root = "../"
    canonical = f"{SITE}/posts/{post['slug']}.html"
    image = post["cover"] or "images/Profile-pic.jpg"
    links = []
    if older:
        links.append(f'\t\t<link rel="prev" href="{older["slug"]}.html" />')
    if newer:
        links.append(f'\t\t<link rel="next" href="{newer["slug"]}.html" />')
    published_meta = f'\t\t<meta property="article:published_time" content="{esc_attr(post["published"])}" />\n'
    graph = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "BlogPosting",
                "headline": post["title"],
                "description": post["description"],
                "datePublished": post["published"],
                "dateModified": post["published"],
                "author": {
                    "@type": "Person",
                    "name": "Jonny Taft",
                    "url": SITE + "/",
                },
                "publisher": {"@type": "Person", "name": "Jonny Taft"},
                "image": image if str(image).startswith("http") else f"{SITE}/{image}",
                "mainEntityOfPage": canonical,
                "url": canonical,
                "inLanguage": "en-GB",
                "wordCount": post["words"],
                "timeRequired": f"PT{post['minutes']}M",
            },
            {
                "@type": "BreadcrumbList",
                "itemListElement": [
                    {"@type": "ListItem", "position": 1, "name": "Home", "item": SITE + "/"},
                    {"@type": "ListItem", "position": 2, "name": "Readme.md", "item": SITE + "/readme.html"},
                    {"@type": "ListItem", "position": 3, "name": post["title"], "item": canonical},
                ],
            },
        ],
    }
    ld = f'\t\t<script type="application/ld+json">\n\t\t{json_ld(graph)}\n\t\t</script>\n'
    extra = published_meta + "\n".join(links) + ("\n" if links else "") + ld
    hero = cover_src(post, root)
    chapters = []
    lead = []
    for chapter in post["chapters"]:
        if chapter["heading"] is None and not chapters:
            lead.extend(chapter["html"])
            continue
        heading = chapter["heading"] or "Notes"
        body = "\n".join(chapter["html"])
        chapters.append(
            "\t\t\t\t\t\t<section>\n"
            "\t\t\t\t\t\t\t<header>\n"
            f"\t\t\t\t\t\t\t\t<h3>{esc(heading)}</h3>\n"
            "\t\t\t\t\t\t\t</header>\n"
            "\t\t\t\t\t\t\t<div class=\"content post-body\">\n"
            f"\t\t\t\t\t\t\t\t{body}\n"
            "\t\t\t\t\t\t\t</div>\n"
            "\t\t\t\t\t\t</section>"
        )
    lead_html = "\n".join(f"\t\t\t\t\t\t{block}" for block in lead)
    pager = ['\t\t\t\t\t\t<ul class="actions">']
    if newer:
        pager.append(
            f'\t\t\t\t\t\t\t<li><a href="{newer["slug"]}.html" class="button">Newer post</a></li>'
        )
    if older:
        pager.append(
            f'\t\t\t\t\t\t\t<li><a href="{older["slug"]}.html" class="button">Older post</a></li>'
        )
    pager.append('\t\t\t\t\t\t\t<li><a href="../readme.html" class="button primary">All posts</a></li>')
    pager.append("\t\t\t\t\t\t</ul>")
    if newer:
        pager.append(f'\t\t\t\t\t\t<p>Newer: <a href="{newer["slug"]}.html">{esc(newer["title"])}</a></p>')
    if older:
        pager.append(f'\t\t\t\t\t\t<p>Older: <a href="{older["slug"]}.html">{esc(older["title"])}</a></p>')
    if post["medium"]:
        pager.append(
            f'\t\t\t\t\t\t<p class="post-source">First published on <a href="{esc_attr(post["medium"])}" target="_blank" rel="noopener noreferrer">Medium</a>.</p>'
        )
    page_head = head(
        f'{post["title"]} · Jonny Taft',
        post["description"],
        canonical,
        image,
        extra,
    ).replace("{root}", root)
    return f"""<!DOCTYPE HTML>
<html lang="en">
\t<head>
{page_head}
\t</head>
\t<body class="is-preload">
{site_nav(root, "readme")}
\t\t<div id="wrapper">
\t\t\t\t<section class="intro">
\t\t\t\t\t<header>
\t\t\t\t\t\t<p class="eyebrow"><a href="../readme.html">Readme.md</a> · <time datetime="{post["day"]}">{esc(post["display_date"])}</time> · {post["minutes"]} min read</p>
\t\t\t\t\t\t<h1 class="post-title">{esc(post["title"])}</h1>
\t\t\t\t\t\t<p>{esc(post["card"])}</p>
\t\t\t\t\t\t<ul class="actions">
\t\t\t\t\t\t\t<li><a href="#article" class="button primary">Read post</a></li>
\t\t\t\t\t\t\t<li><a href="../index.html" class="button">Work</a></li>
\t\t\t\t\t\t\t<li><a href="#article" class="arrow scrolly"><span class="label">Next</span></a></li>
\t\t\t\t\t\t</ul>
\t\t\t\t\t</header>
\t\t\t\t\t<div class="content">
\t\t\t\t\t\t<span class="image fill" data-position="center"><img src="{esc_attr(hero)}" alt="{esc_attr(post["cover_alt"])}" /></span>
\t\t\t\t\t</div>
\t\t\t\t</section>
\t\t\t\t<section id="article">
\t\t\t\t\t<header>
\t\t\t\t\t\t<h2>{esc(post["display_date"])}</h2>
\t\t\t\t\t</header>
\t\t\t\t\t<div class="content post-body">
{lead_html}
{chr(10).join(chapters)}
{chr(10).join(pager)}
\t\t\t\t\t</div>
\t\t\t\t</section>
{cta_section("../index.html#contact")}
\t\t\t\t<div class="copyright">&copy; JLT Digital. All rights reserved. <a href="../index.html">Home</a> · <a href="../readme.html">Readme.md</a></div>
\t\t</div>
{scripts(root)}
\t</body>
</html>
"""


def render_index(posts):
    root = ""
    description = "Notes from Jonny Taft on Shopify themes, JavaScript, and building for the web. A blog of essays and technical breakdowns from a full stack developer."
    graph = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "Blog",
                "name": "Readme.md",
                "description": description,
                "url": SITE + "/readme.html",
                "inLanguage": "en-GB",
                "author": {"@type": "Person", "name": "Jonny Taft", "url": SITE + "/"},
                "blogPost": [
                    {
                        "@type": "BlogPosting",
                        "headline": post["title"],
                        "url": f"{SITE}/posts/{post['slug']}.html",
                        "datePublished": post["published"],
                    }
                    for post in posts
                ],
            },
            {
                "@type": "BreadcrumbList",
                "itemListElement": [
                    {"@type": "ListItem", "position": 1, "name": "Home", "item": SITE + "/"},
                    {"@type": "ListItem", "position": 2, "name": "Readme.md", "item": SITE + "/readme.html"},
                ],
            },
        ],
    }
    cards = []
    for post in posts:
        image = ""
        if post["cover"]:
            src = cover_src(post, "")
            image = (
                "\t\t\t\t\t\t\t<span class=\"image fit\">"
                f'<img src="{esc_attr(src)}" alt="{esc_attr(post["cover_alt"])}" loading="lazy" decoding="async" />'
                "</span>\n"
            )
        cards.append(
            "\t\t\t\t\t\t<section id=\"" + post["slug"] + "\">\n"
            "\t\t\t\t\t\t\t<header>\n"
            f"\t\t\t\t\t\t\t\t<h3>{esc(post['title'])}</h3>\n"
            f"\t\t\t\t\t\t\t\t<p><time datetime=\"{post['day']}\">{esc(post['display_date'])}</time> · {post['minutes']} min read</p>\n"
            "\t\t\t\t\t\t\t</header>\n"
            "\t\t\t\t\t\t\t<div class=\"content\">\n"
            f"{image}"
            f"\t\t\t\t\t\t\t\t<p>{esc(post['card'])}</p>\n"
            "\t\t\t\t\t\t\t\t<ul class=\"actions\">\n"
            f"\t\t\t\t\t\t\t\t\t<li><a href=\"posts/{post['slug']}.html\" class=\"button primary\">Read post</a></li>\n"
            "\t\t\t\t\t\t\t\t</ul>\n"
            "\t\t\t\t\t\t\t</div>\n"
            "\t\t\t\t\t\t</section>"
        )
    hero = "images/Profile-pic.jpg"
    page_head = head(
        "Readme.md · Jonny Taft",
        description,
        SITE + "/readme.html",
        hero,
        f'\t\t<script type="application/ld+json">\n\t\t{json_ld(graph)}\n\t\t</script>\n',
    ).replace("{root}", root)
    # The index is a collection, not a single article.
    page_head = page_head.replace('content="article"', 'content="website"', 1)
    return f"""<!DOCTYPE HTML>
<html lang="en">
\t<head>
{page_head}
\t</head>
\t<body class="is-preload">
{site_nav("", "readme")}
\t\t<div id="wrapper">
\t\t\t\t<section class="intro">
\t\t\t\t\t<header>
\t\t\t\t\t\t<h1>Readme.md</h1>
\t\t\t\t\t\t<p>Notes on Shopify, JavaScript, and how a storefront actually gets built.</p>
\t\t\t\t\t\t<ul class="actions">
\t\t\t\t\t\t\t<li><a href="#posts" class="button primary">Latest posts</a></li>
\t\t\t\t\t\t\t<li><a href="index.html#work" class="button">View work</a></li>
\t\t\t\t\t\t\t<li><a href="#posts" class="arrow scrolly"><span class="label">Next</span></a></li>
\t\t\t\t\t\t</ul>
\t\t\t\t\t</header>
\t\t\t\t\t<div class="content">
\t\t\t\t\t\t<span class="image fill" data-position="center"><img src="{hero}" alt="Jonny Taft, Shopify developer" /></span>
\t\t\t\t\t</div>
\t\t\t\t</section>
\t\t\t\t<section id="posts">
\t\t\t\t\t<header>
\t\t\t\t\t\t<h2>Latest writing</h2>
\t\t\t\t\t</header>
\t\t\t\t\t<div class="content">
\t\t\t\t\t\t<p><strong>Essays and technical notes</strong> from the work. Shopify themes, JavaScript, and the wider stack — newest first.</p>
{chr(10).join(cards)}
\t\t\t\t\t</div>
\t\t\t\t</section>
{cta_section("#contact")}
{contact_section()}
\t\t\t\t<div class="copyright">&copy; JLT Digital. All rights reserved. <a href="index.html">Home</a></div>
\t\t</div>
{scripts(root, contact=True)}
\t</body>
</html>
"""


def render_sitemap(posts):
    urls = [
        (f"{SITE}/", "2026-10-01", "1.0"),
        (f"{SITE}/readme.html", "2026-10-01", "0.9"),
    ]
    urls.extend((f"{SITE}/posts/{post['slug']}.html", post["day"], "0.8") for post in posts)
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for loc, lastmod, priority in urls:
        lines.append("\t<url>")
        lines.append(f"\t\t<loc>{loc}</loc>")
        lines.append(f"\t\t<lastmod>{lastmod}</lastmod>")
        lines.append(f"\t\t<priority>{priority}</priority>")
        lines.append("\t</url>")
    lines.append("</urlset>")
    return "\n".join(lines) + "\n"


def render_rss(posts):
    items = []
    for post in posts:
        link = f"{SITE}/posts/{post['slug']}.html"
        items.append(
            "\t\t<item>\n"
            f"\t\t\t<title>{esc(post['title'])}</title>\n"
            f"\t\t\t<link>{link}</link>\n"
            f"\t\t\t<guid>{link}</guid>\n"
            f"\t\t\t<pubDate>{datetime.fromisoformat(post['published'].replace('Z', '+00:00')).strftime('%a, %d %b %Y %H:%M:%S +0000')}</pubDate>\n"
            f"\t\t\t<description>{esc(post['description'])}</description>\n"
            "\t\t</item>"
        )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
\t<channel>
\t\t<title>Readme.md · Jonny Taft</title>
\t\t<link>{SITE}/readme.html</link>
\t\t<description>Notes from Jonny Taft on Shopify themes, JavaScript, and building for the web.</description>
\t\t<language>en-gb</language>
{chr(10).join(items)}
\t</channel>
</rss>
"""


def load_markdown_tools():
    try:
        import markdown
        import yaml
    except ImportError as error:
        raise SystemExit(
            "Markdown posts need the Markdown and PyYAML packages.\n"
            "Install them with: python3 -m pip install -r requirements.txt"
        ) from error
    return markdown, yaml


def split_front_matter(text):
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    _, yaml_mod = load_markdown_tools()
    meta = yaml_mod.safe_load(parts[1]) or {}
    if not isinstance(meta, dict):
        raise SystemExit("Post front matter must be a set of fields")
    return meta, parts[2].lstrip("\n")


def normalize_published(value):
    if isinstance(value, datetime):
        text = value.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    elif isinstance(value, date):
        text = value.strftime("%Y-%m-%dT00:00:00.000Z")
    else:
        text = clean(str(value or ""))
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            text = text + "T00:00:00.000Z"
        elif text.endswith("+00:00"):
            text = text[:-6] + "Z"
    if not text:
        text = "2020-01-01T00:00:00.000Z"
    datetime.fromisoformat(text.replace("Z", "+00:00"))
    return text


def normalize_cover(value):
    if isinstance(value, list):
        value = value[0] if value else ""
    if isinstance(value, dict):
        value = value.get("image") or value.get("src") or ""
    value = clean(str(value or ""))
    if not value:
        return None
    if value.startswith("http://") or value.startswith("https://"):
        return value
    return value.lstrip("/")


def rewrite_post_urls(fragment):
    def replace(match):
        attr, quote, url = match.group(1), match.group(2), match.group(3)
        if url.startswith("/") and not url.startswith("//"):
            url = ".." + url
        elif url.startswith("images/"):
            url = "../" + url
        return f"{attr}={quote}{url}{quote}"

    return re.sub(r"\b(src|href)=([\"'])([^\"']+)\2", replace, fragment)


def markdown_figure(el):
    if el.tag != "p":
        return ""
    images = [child for child in el if isinstance(child.tag, str) and child.tag == "img"]
    if len(images) != 1 or len(list(el)) != 1:
        return ""
    if clean(el.text or "") or clean(images[0].tail or ""):
        return ""
    image = images[0]
    src = image.get("src") or ""
    if src.startswith("/") and not src.startswith("//"):
        src = ".." + src
    elif src.startswith("images/"):
        src = "../" + src
    alt = image.get("alt") or ""
    return (
        f'<figure class="post-figure"><img src="{esc_attr(src)}" alt="{esc_attr(alt)}" '
        'loading="lazy" decoding="async" /></figure>'
    )


def chapters_from_markdown(html_body, title_key):
    if not html_body.strip():
        return [], "", 0
    wrapper = lxml_html.fragment_fromstring(html_body, create_parent="div")
    events = []
    first_paragraph = ""
    for child in wrapper:
        if not isinstance(child.tag, str):
            continue
        if child.tag in ("h1", "h2"):
            heading = strip_emoji(child.text_content())
            if heading and normalize(heading) != title_key:
                events.append(("h2", heading))
            continue
        if child.tag in ("h3", "h4", "h5", "h6"):
            heading = strip_emoji(child.text_content())
            if heading:
                events.append(("h3", heading))
            continue
        figure = markdown_figure(child)
        if figure:
            events.append(("html", figure))
            continue
        rendered = rewrite_post_urls(lxml_html.tostring(child, encoding="unicode", method="html"))
        if child.tag == "p" and not first_paragraph:
            first_paragraph = clean(child.text_content())
        if clean(child.text_content()) or child.xpath(".//img|.//pre|.//iframe"):
            events.append(("html", rendered))

    chapters = []
    for kind, value in events:
        if kind == "h2":
            chapters.append({"heading": value, "html": []})
            continue
        if kind == "h3":
            if chapters and chapters[-1]["heading"]:
                chapters[-1]["html"].append(f"<h3>{esc(value)}</h3>")
            else:
                chapters.append({"heading": value, "html": []})
            continue
        if not chapters:
            chapters.append({"heading": None, "html": []})
        chapters[-1]["html"].append(value)
    words = len(re.findall(r"\w+", wrapper.text_content()))
    return chapters, first_paragraph, words


def parse_markdown(path):
    markdown_mod, _yaml_mod = load_markdown_tools()
    meta, body = split_front_matter(open(path, encoding="utf-8").read().lstrip("\ufeff"))
    if meta.get("draft") is True:
        return None
    title = strip_emoji(str(meta.get("title") or ""))
    if not title:
        raise SystemExit(f"{os.path.basename(path)}: add a title")
    summary = clean(str(meta.get("summary") or meta.get("description") or ""))
    published = normalize_published(meta.get("date"))
    explicit = clean(str(meta.get("slug") or ""))
    slug = slugify(explicit) if explicit else slugify(os.path.splitext(os.path.basename(path))[0].replace("-", " "))
    display_date, day = format_date(published)
    html_body = markdown_mod.markdown(
        body,
        extensions=["fenced_code", "tables", "sane_lists"],
    )
    chapters, first_paragraph, words = chapters_from_markdown(html_body, normalize(title))
    minutes = max(1, round(words / 230)) if words else 1
    base = summary or first_paragraph or title
    cover = normalize_cover(meta.get("cover"))
    warnings = []
    if cover and not cover.startswith("http") and not os.path.isfile(os.path.join(ROOT, cover)):
        warnings.append(f"cover not found: {cover}")
    return {
        "title": title,
        "slug": slug,
        "summary": summary,
        "description": excerpt(base, 155),
        "card": excerpt(base, 220),
        "published": published,
        "day": day,
        "display_date": display_date,
        "minutes": minutes,
        "words": words,
        "medium": "",
        "cover": cover,
        "cover_alt": title,
        "chapters": [chapter for chapter in chapters if chapter["html"] or chapter["heading"]],
        "warnings": warnings,
        "source": os.path.basename(path),
    }


def update_home(posts):
    path = os.path.join(ROOT, "index.html")
    raw = open(path, "rb").read()
    newline = "\r\n" if b"\r\n" in raw else "\n"
    document = raw.decode("utf-8").replace("\r\n", "\n")
    start = "<!-- latest-posts:start -->"
    end = "<!-- latest-posts:end -->"
    items = [
        f'\t\t\t\t\t\t\t\t<li><a href="posts/{post["slug"]}.html">{esc(post["title"])}</a></li>'
        for post in posts[:3]
    ]
    block = start + "\n" + "\n".join(items) + "\n\t\t\t\t\t\t\t\t" + end
    pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.S)
    if not pattern.search(document):
        raise SystemExit("index.html is missing the latest-posts markers")
    updated = pattern.sub(block, document, count=1)
    if updated == document:
        return
    if newline == "\r\n":
        updated = updated.replace("\n", "\r\n")
    with open(path, "wb") as handle:
        handle.write(updated.encode("utf-8"))


def main():
    names = sorted(os.listdir(SOURCE_DIR))
    posts = [parse_post(os.path.join(SOURCE_DIR, name)) for name in names if name.endswith(".html")]
    posts.extend(
        post
        for post in (
            parse_markdown(os.path.join(SOURCE_DIR, name))
            for name in names
            if name.endswith(".md") or name.endswith(".markdown")
        )
        if post
    )
    posts.sort(key=lambda post: post["published"], reverse=True)
    slugs = [post["slug"] for post in posts]
    if len(slugs) != len(set(slugs)):
        raise SystemExit(f"Duplicate slugs: {slugs}")

    os.makedirs(POSTS_DIR, exist_ok=True)
    for name in os.listdir(POSTS_DIR):
        if name.endswith(".html"):
            os.remove(os.path.join(POSTS_DIR, name))
    if os.path.isdir(IMAGE_ROOT):
        for name in os.listdir(IMAGE_ROOT):
            target = os.path.join(IMAGE_ROOT, name)
            if name not in slugs and os.path.isdir(target):
                shutil.rmtree(target)

    for index, post in enumerate(posts):
        newer = posts[index - 1] if index > 0 else None
        older = posts[index + 1] if index + 1 < len(posts) else None
        destination = os.path.join(POSTS_DIR, f"{post['slug']}.html")
        with open(destination, "w", encoding="utf-8") as handle:
            handle.write(render_post(post, newer, older))
        lxml_html.fromstring(open(destination, encoding="utf-8").read())
        print(f"{post['display_date']}  {post['slug']}  ({post['minutes']} min)")
        for warning in post["warnings"]:
            print(f"  ! {warning}")

    with open(os.path.join(ROOT, "readme.html"), "w", encoding="utf-8") as handle:
        handle.write(render_index(posts))
    with open(os.path.join(POSTS_DIR, "index.html"), "w", encoding="utf-8") as handle:
        handle.write(
            """<!DOCTYPE HTML>
<html lang="en">
\t<head>
\t\t<meta charset="utf-8" />
\t\t<title>Readme.md · Jonny Taft</title>
\t\t<link rel="canonical" href="https://jlt.digital/readme.html" />
\t\t<meta http-equiv="refresh" content="0; url=../readme.html" />
\t</head>
\t<body>
\t\t<p><a href="../readme.html">Readme.md</a></p>
\t</body>
</html>
"""
        )
    with open(os.path.join(ROOT, "sitemap.xml"), "w", encoding="utf-8") as handle:
        handle.write(render_sitemap(posts))
    with open(os.path.join(ROOT, "rss.xml"), "w", encoding="utf-8") as handle:
        handle.write(render_rss(posts))
    robots = os.path.join(ROOT, "robots.txt")
    with open(robots, "w", encoding="utf-8") as handle:
        handle.write(
            "User-agent: *\n"
            "Allow: /\n"
            "Disallow: /content/\n"
            "Disallow: /admin/\n"
            f"Sitemap: {SITE}/sitemap.xml\n"
        )
    update_home(posts)
    print(f"Wrote {len(posts)} posts, readme.html, index.html, sitemap.xml, rss.xml")


if __name__ == "__main__":
    main()
