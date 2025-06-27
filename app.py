from flask import Flask, request, render_template
import asyncio
import httpx
from urllib.parse import urljoin, urlparse
from selectolax.parser import HTMLParser

app = Flask(__name__)

visited = set()
found_in = []

async def fetch(client, url):
    try:
        r = await client.get(url, follow_redirects=True, timeout=10)
        return url, r.status_code, r.text
    except Exception as e:
        print(f"[ERROR] {url} => {e}")
        return url, 0, ""

def extract_links(html, base_url):
    tree = HTMLParser(html)
    for node in tree.css("a[href]"):
        href = node.attributes.get("href")
        if href:
            yield urljoin(base_url, href)

async def crawl(site_url, target_link):
    domain = urlparse(site_url).netloc
    visited.clear()
    found_in.clear()

    async with httpx.AsyncClient(verify=False) as client:
        queue = [(site_url, site_url)]

        while queue:
            from_page, current_url = queue.pop()
            if current_url in visited:
                continue
            visited.add(current_url)

            url, status, html = await fetch(client, current_url)
            if status != 200:
                continue

            for link in extract_links(html, current_url):
                if link == target_link:
                    found_in.append(current_url)

                parsed = urlparse(link)
                if (parsed.netloc == "" or parsed.netloc == domain) and link not in visited:
                    queue.append((current_url, link))

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        site_url = request.form["site_url"]
        target = request.form["target_link"]
        asyncio.run(crawl(site_url, target))
        return render_template("index.html", results=found_in, target=target)

    return render_template("index.html", results=None, target=None)

if __name__ == "__main__":
    app.run(debug=True)
