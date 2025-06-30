from flask import Flask, render_template, request, jsonify
import httpx
from selectolax.parser import HTMLParser
from urllib.parse import urljoin, urlparse
import asyncio
import threading
from collections import deque

app = Flask(__name__)

# Estado global compartido
progreso = {"actual": 0, "total": 0, "scanning_active": False}
resultados = []
visited = set()
queue = deque()

async def fetch(client, url):
    try:
        r = await client.get(url, follow_redirects=True, timeout=12)
        return r.text if r.status_code == 200 else None
    except:
        return None

def extract_links(html, base_url):
    tree = HTMLParser(html)
    for node in tree.css("a[href]"):
        href = node.attributes.get("href")
        if not href or href.startswith(("javascript:","mailto:","#")):
            continue
        yield urljoin(base_url, href)

async def crawler(start_url, target_url):
    global progreso, resultados, visited, queue

    visited.clear()
    queue = deque([start_url])
    resultados.clear()
    progreso.update(actual=0, total=1, scanning_active=True)
    base_domain = urlparse(start_url).netloc
    target_filename = target_url.split("/")[-1].split("?")[0].lower()

    async with httpx.AsyncClient(verify=False, timeout=20) as client:
        while queue and progreso["scanning_active"]:
            url = queue.popleft()
            if url in visited:
                continue
            visited.add(url)

            progreso["actual"] = len(visited)
            progreso["total"]  = len(visited) + len(queue)

            html = await fetch(client, url)
            if html:
                html_lower = html.lower()
                # si encontramos el link o su nombre
                if target_url.lower() in html_lower or target_filename in html_lower:
                    resultados.append({
                        "pagina": url,
                        "metodo": "enlace exacto o nombre",
                        "enlace": target_url
                    })

                for link in extract_links(html, url):
                    p = urlparse(link)
                    if (p.netloc == "" or p.netloc == base_domain) \
                       and link not in visited and link not in queue:
                        queue.append(link)

    progreso["scanning_active"] = False

def start_crawler(site, target):
    asyncio.run(crawler(site, target))

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/iniciar", methods=["POST"])
def iniciar():
    if progreso["scanning_active"]:
        return jsonify({"error": "Ya hay un escaneo en progreso"}), 400

    site   = request.form["site"].rstrip("/")
    target = request.form["target"].strip()
    threading.Thread(target=start_crawler, args=(site, target), daemon=True).start()
    return "", 204

@app.route("/progreso")
def get_progreso():
    return jsonify({
        "actual": progreso["actual"],
        "total": progreso["total"],
        "crawling_active": progreso["scanning_active"]
    })


@app.route("/resultados")
def get_resultados():
    # devuelve sólo la lista de páginas encontradas
    return jsonify([r["pagina"] for r in resultados])

# === Aquí los dos endpoints que pedías ===

@app.route("/resultados-parciales")
def resultados_parciales():
    return jsonify({
        "hits": resultados,               # lista de dicts con detalle
        "count": len(resultados),         # cuántos va encontrando
        "actual": progreso["actual"],     # páginas procesadas
        "total": progreso["total"],       # páginas totales en cola+procesadas
        "scanning": progreso["scanning_active"]
    })

@app.route("/detener", methods=["POST"])
def detener():
    # detiene el loop del crawler
    progreso["scanning_active"] = False
    queue.clear()
    return jsonify({"status": "detenido", 
                    "processed": progreso["actual"], 
                    "remaining": len(queue)})

if __name__ == "__main__":
    app.run(debug=True, port=5007)
