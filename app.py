import os
import re
import requests
from urllib.parse import parse_qs, urlparse
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask import Flask, abort, jsonify, request, send_from_directory
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__)
if os.environ.get("RENDER") == "true":
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
CORS(app)
limiter = Limiter(key_func=get_remote_address, app=app, default_limits=[])

SEARCH_API_URL = "https://serpapi.com/search.json"
MAX_SEARCH_RESULTS = 1000
SEARCH_PAGE_SIZE = 10
SEARCH_RESULT_LIMITS = {20, 50, 100, 200, 500, 1000}


def youtube_video_id(url):
    parsed_url = urlparse(url)
    host = parsed_url.hostname
    video_id = None

    if host in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        if parsed_url.path == "/watch":
            video_id = parse_qs(parsed_url.query).get("v", [None])[0]
        else:
            match = re.fullmatch(r"/(?:embed|shorts)/([A-Za-z0-9_-]{11})", parsed_url.path)
            if match:
                video_id = match.group(1)
    elif host in {"youtu.be", "www.youtu.be"}:
        video_id = parsed_url.path.strip("/")

    return video_id if video_id and re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id) else None


def search_result_list(search_data, category):
    result_keys = {
        "all": ("organic_results",),
        "images": ("images_results",),
        "videos": ("video_results",),
        "news": ("news_results",),
        "books": ("organic_results", "books_results"),
    }
    for key in result_keys[category]:
        results = search_data.get(key)
        if isinstance(results, list):
            return results
    return []


def format_search_result(item, category):
    if not isinstance(item, dict):
        return None

    link = item.get("link")
    if not isinstance(link, str) or urlparse(link).scheme not in {"http", "https"}:
        return None

    title = item.get("title", "")
    description = item.get("snippet", item.get("description", ""))
    result = {
        "titre": title if isinstance(title, str) else "",
        "lien": link,
        "description": description if isinstance(description, str) else "",
    }
    if category == "images":
        image = item.get("original") or item.get("thumbnail")
        if not isinstance(image, str) or urlparse(image).scheme != "https":
            return None
        result["image"] = image
    elif category == "videos":
        video_id = youtube_video_id(link)
        if video_id:
            result["video_id"] = video_id
    return result


@app.errorhandler(429)
def limit_exceeded(error):
    return jsonify({"error": "Twòp rechèch. Tanpri tann anvan ou eseye ankò."}), 429


@app.route("/")
def home():
    return send_from_directory(app.root_path, "index.html")


@app.route("/auth-config")
def auth_config():
    supabase_url = os.getenv("SUPABASE_URL", "").strip()
    publishable_key = os.getenv("SUPABASE_PUBLISHABLE_KEY", "").strip()
    if not supabase_url or not publishable_key:
        return jsonify({"error": "Kont yo poko konfigire. Ajoute Supabase URL ak publishable key nan anviwònman aplikasyon an."}), 503
    parsed_url = urlparse(supabase_url)
    if parsed_url.scheme != "https" or not parsed_url.hostname:
        return jsonify({"error": "SUPABASE_URL pa bon. Mete Project URL Supabase la, ki kòmanse ak https://."}), 503
    if publishable_key.startswith("sb_secret_"):
        return jsonify({"error": "SUPABASE_PUBLISHABLE_KEY pa bon. Sèvi ak publishable key la; pa sèvi ak kle sb_secret la."}), 503
    return jsonify({"url": supabase_url, "publishableKey": publishable_key})


@app.route("/<path:filename>")
def frontend_files(filename):
    allowed_files = {
        "style.css",
        "image.jpg",
        "Screenshot_2026-08-14-16-05-10-1.png",
    }
    if filename not in allowed_files:
        abort(404)
    return send_from_directory(app.root_path, filename)

@app.route("/search")
@limiter.limit("10 per minute")
@limiter.limit("100 per day")
def recherche():
    q = request.args.get("query", "").strip()
    category = request.args.get("category", "all")
    language = request.args.get("language", "fr")
    requested_limit = request.args.get("limit", "100")
    if not q:
        return jsonify({"error": "Écris un terme à rechercher."}), 400
    if category not in {"all", "images", "videos", "news", "books"}:
        return jsonify({"error": "Kategori rechèch sa a pa disponib."}), 400
    if language not in {"fr", "ht"}:
        return jsonify({"error": "Langue de recherche non disponible."}), 400
    try:
        result_limit = int(requested_limit)
    except ValueError:
        return jsonify({"error": "Nombre de résultats non valide."}), 400
    if result_limit not in SEARCH_RESULT_LIMITS:
        return jsonify({"error": "Chwazi 20, 50, 100, 200, 500 oswa 1 000 rezilta."}), 400

    api_key = os.getenv("SERPAPI_API_KEY")
    if not api_key:
        return jsonify({"error": "Kle SerpApi a pa konfigire."}), 500

    search_request = {
        "api_key": api_key,
        "engine": "google",
        "q": f"{q} Haïti",
        "hl": language,
    }
    if category == "images":
        search_request["engine"] = "google_images"
    elif category == "news":
        search_request["engine"] = "google_news"
    elif category == "videos":
        search_request["engine"] = "google_videos"
    elif category == "books":
        search_request["engine"] = "google_books"

    try:
        results = []
        seen_links = set()
        page_count = (result_limit + SEARCH_PAGE_SIZE - 1) // SEARCH_PAGE_SIZE
        for page in range(page_count):
            page_request = dict(search_request)
            if category == "images":
                page_request["ijn"] = page
            else:
                page_request["start"] = page * SEARCH_PAGE_SIZE

            response = requests.get(SEARCH_API_URL, params=page_request, timeout=15)
            response.raise_for_status()
            search_data = response.json()
            if not isinstance(search_data, dict):
                raise requests.RequestException("SerpApi returned an invalid response.")
            if search_data.get("error"):
                provider_error = str(search_data["error"]).lower()
                if any(term in provider_error for term in ("invalid api key", "invalid key", "api_key")):
                    message = "Kle SerpApi a pa valab. Verifye SERPAPI_API_KEY nan Render."
                elif any(term in provider_error for term in ("quota", "rate limit", "monthly searches", "account limit", "plan")):
                    message = "Limit oswa kredi SerpApi yo fini. Verifye kont SerpApi a."
                elif category in {"books", "videos", "news"} and any(term in provider_error for term in ("not available", "not supported", "unauthorized")):
                    message = "Kont oswa plan SerpApi a pa pèmèt kategori sa a."
                else:
                    message = "SerpApi pa t kapab bay rezilta pou kategori sa a."
                app.logger.error("SerpApi returned an error for category %s", category)
                return jsonify({"error": message}), 502

            page_results = search_result_list(search_data, category)
            for item in page_results:
                formatted = format_search_result(item, category)
                if formatted and formatted["lien"] not in seen_links:
                    seen_links.add(formatted["lien"])
                    results.append(formatted)
                    if len(results) >= result_limit:
                        break
            if len(results) >= result_limit or not page_results:
                break
            if category != "images" and len(page_results) < SEARCH_PAGE_SIZE:
                break

        return jsonify(results)
    except requests.Timeout:
        app.logger.warning("SerpApi timed out for category %s", category)
        return jsonify({"error": "SerpApi pran twòp tan pou reponn. Eseye ankò."}), 504
    except requests.HTTPError as error:
        status_code = error.response.status_code if error.response is not None else None
        app.logger.exception("SerpApi HTTP error for category %s", category)
        if status_code == 429:
            message = "Limit oswa kredi SerpApi yo fini. Verifye kont SerpApi a."
        elif status_code in {401, 403}:
            message = "SerpApi pa aksepte kle a oswa plan an pa pèmèt rechèch sa a."
        else:
            message = "SerpApi pa disponib kounye a. Eseye ankò pita."
        return jsonify({"error": message}), 502
    except requests.RequestException:
        app.logger.exception("Échec de la recherche SerpApi")
        return jsonify({"error": "Pa ka konekte ak SerpApi kounye a. Eseye ankò pita."}), 502

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=False,
    )