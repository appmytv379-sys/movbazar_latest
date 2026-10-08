import asyncio
import aiohttp
import json
import re
import time
import random
import os
from urllib.parse import urlparse

class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

def get_random_headers():
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/122.0"
    ]
    
    return {
        "User-Agent": random.choice(user_agents),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate",  # Crucial: Removed 'br' to prevent Brotli decode errors
        "Referer": "https://www.moviesbazar.tv/",
        "Origin": "https://www.moviesbazar.tv",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "cross-site",
        "Connection": "keep-alive"
    }

def log(msg, color=Colors.ENDC, symbol="*"):
    time_str = time.strftime("%H:%M:%S")
    print(f"{Colors.BOLD}[{time_str}]{Colors.ENDC} {color}[{symbol}] {msg}{Colors.ENDC}")

async def fetch_url_async(session, url, is_post=False, post_data=None, retries=3):
    for attempt in range(retries):
        headers = get_random_headers()
        try:
            if is_post:
                headers["Content-Type"] = "application/json"
                async with session.post(url, json=post_data, headers=headers, timeout=30) as res:
                    text = await res.text()
                    return {'error': False, 'data': text, 'code': res.status, 'headers': headers}
            else:
                async with session.get(url, headers=headers, timeout=30) as res:
                    text = await res.text()
                    return {'error': False, 'data': text, 'code': res.status, 'headers': headers}
        except Exception as e:
            if attempt == retries - 1:
                return {'error': True, 'data': str(e), 'code': 0, 'headers': headers}
            await asyncio.sleep(1)

def get_category_name(url):
    parts = [p for p in url.split('/') if p]
    return parts[-1].replace('-', ' ').title()

def generate_slug(title):
    if not title: return 'movie'
    slug = re.sub(r'[^A-Za-z0-9]+', '-', title).strip('-').lower()
    return slug if slug else 'movie'

def format_date(raw_date):
    if not raw_date: return ""
    raw_date = str(raw_date).split('T')[0]
    parts = raw_date.split('-')
    if len(parts) == 3 and len(parts[0]) == 4:
        return f"{parts[2]}-{parts[1]}-{parts[0]}" # Output: DD-MM-YYYY
    return raw_date

def extract_movies_recursive(data, movies):
    if isinstance(data, dict):
        if 'title' in data and ('_id' in data or 'id' in data or 'imdbId' in data):
            movies.append(data)
        else:
            for key, value in data.items():
                extract_movies_recursive(value, movies)
    elif isinstance(data, list):
        for item in data:
            extract_movies_recursive(item, movies)
    return movies

async def fetch_imdb_metadata(session, imdb_id, m_type="movie"):
    if not imdb_id: return {}
    imdb_id = str(imdb_id)
    if not imdb_id.startswith('tt'): 
        imdb_id = 'tt' + imdb_id
        
    try:
        stremio_type = "series" if m_type in ["series", "show"] else "movie"
        url = f"https://v3-cinemeta.strem.io/meta/{stremio_type}/{imdb_id}.json"
        async with session.get(url, timeout=10) as res:
            if res.status == 200:
                data = await res.json()
                return data.get("meta", {})
    except: pass
    return {}

def format_movie_data(raw_data, parsed_details, stremio_data, detail_html, category_name, fetch_headers, movie_url):
    imdb_id = str(parsed_details.get('imdbId') or raw_data.get('imdbId') or stremio_data.get('id') or "")
    movie_id = parsed_details.get('_id') or raw_data.get('_id') or raw_data.get('id') or imdb_id.replace('tt', '')
    
    raw_title = str(parsed_details.get('title') or raw_data.get('title') or stremio_data.get('name') or "Unknown Title")
    year = str(parsed_details.get('releaseYear') or raw_data.get('releaseYear') or stremio_data.get('releaseInfo') or "")
    
    if not year:
        year_match = re.search(r'\((\d{4})\)', raw_title)
        if year_match: year = year_match.group(1)
    elif len(year) > 4:
        year = year[:4]
            
    clean_title = re.sub(r'\s*\(\d{4}\)', '', raw_title).strip()
    title = f"{clean_title} ({year})" if year else clean_title
        
    # Check if a video link exists to ensure the movie is actually playable
    watch_links = parsed_details.get('watchLink') or []
    play_list = parsed_details.get('playList') or []
    streaming_links = watch_links + play_list
    
    unescaped_html = detail_html.replace('\\"', '"').replace('\\/', '/')
    
    if not streaming_links:
        wl_match = re.search(r'"watchLink"\s*:\s*(\[\{.*?\}\])', unescaped_html)
        pl_match = re.search(r'"playList"\s*:\s*(\[\{.*?\}\])', unescaped_html)
        if wl_match:
            try: streaming_links.extend(json.loads(wl_match.group(1)))
            except: pass
        if pl_match and not streaming_links:
            try: streaming_links.extend(json.loads(pl_match.group(1)))
            except: pass
            
    has_video = False
    valid_extensions = ('.m3u8', '.mp4', '.mkv')
    
    for link in streaming_links:
        if isinstance(link, dict) and link.get('source'):
            if any(ext in str(link.get('source')).lower() for ext in valid_extensions):
                has_video = True
                break

    if not has_video:
        streams = re.findall(r'(https:\/\/[^"\'\s]+\.(?:m3u8|mp4|mkv)[^"\'\s]*)', unescaped_html, re.IGNORECASE)
        if streams: has_video = True

    # If no video is found anywhere, return None to skip saving this movie
    if not has_video:
        return None

    # Format the rest of the metadata perfectly
    director = parsed_details.get('director') or raw_data.get('director') or stremio_data.get('director') or "Unknown"
    if isinstance(director, list):
        director = ", ".join([str(d.get('name', d)) if isinstance(d, dict) else str(d) for d in director]) if director else "Unknown"

    genre = parsed_details.get('genre') or raw_data.get('genre') or stremio_data.get('genres') or ["Unknown"]
    if isinstance(genre, str): genre = [g.strip() for g in genre.split(',')]
    elif isinstance(genre, list): genre = [str(g.get('name', g)) if isinstance(g, dict) else str(g) for g in genre]

    rating = str(parsed_details.get('imdbRating') or raw_data.get('imdbRating') or "0")
    if rating == "0" or rating == "0.0" or rating == "":
        rating = str(stremio_data.get('imdbRating') or "0")

    try: imdb_votes = int(str(parsed_details.get('imdbVotes') or raw_data.get('imdbVotes') or 0).replace(',', ''))
    except: imdb_votes = 0

    language = parsed_details.get('language') or raw_data.get('language') or "Unknown"
    if isinstance(language, list): language = ", ".join(language) if language else "Unknown"
    if language != "Unknown": language = language.title()

    poster_url = parsed_details.get('thumbnail') or raw_data.get('thumbnail') or raw_data.get('posterUrl') or stremio_data.get('poster') or ""
    if not poster_url:
        thm_match = re.search(r'property="og:image"\s+content="([^"]+)"', detail_html, re.IGNORECASE)
        if thm_match: poster_url = thm_match.group(1)

    slider_url = parsed_details.get('backdrop') or raw_data.get('backdrop') or stremio_data.get('background') or poster_url
    
    if poster_url and poster_url.startswith('/'): poster_url = "https://www.moviesbazar.tv" + poster_url
    if slider_url and slider_url.startswith('/'): slider_url = "https://www.moviesbazar.tv" + slider_url

    storyline = parsed_details.get('storyline') or raw_data.get('storyline') or stremio_data.get('description') or "No storyline available."
    storyline = re.sub(r'<[^>]+>', '', str(storyline)).strip() 

    release_date = parsed_details.get('fullReleaseDate') or raw_data.get('fullReleaseDate') or parsed_details.get('releaseDate') or raw_data.get('releaseDate') or stremio_data.get('released') or ""

    return {
        "id": str(movie_id),
        "category": category_name,
        "director": director,
        "genre": genre,
        "imdbRating": rating,
        "imdbVotes": imdb_votes,
        "language": language,
        "posterUrl": poster_url,
        "releaseDate": format_date(release_date),
        "sliderUrl": slider_url,
        "status": "on",
        "storyline": storyline,
        "streamUrl": movie_url,          # BEST STRATEGY: Save the main page URL instead of temp M3U8
        "streamType": "live_fetch",      # UNIQUE IDENTIFIER: Generic type for future websites too
        "title": title,
        "headers": {
            "referer": "https://www.moviesbazar.tv/",
            "origin": "https://www.moviesbazar.tv",
            "user_agent": fetch_headers.get("User-Agent", ""),
            "sec-ch-ua-platform": "\"Windows\"",
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "cross-site"
        }
    }

async def process_single_movie(session, url, raw_movie_data, category_name, semaphore):
    async with semaphore:
        detail_res = await fetch_url_async(session, url)
        if detail_res['error'] or detail_res['code'] != 200:
            return None
            
        detail_html = detail_res['data']
        unescaped_html = detail_html.replace('\\"', '"').replace('\\/', '/')
        
        parsed_details = {}
        md_match = re.search(r'"movieDetails"\s*:\s*(\{.*?\})\s*,\s*"(?:suggestions|userIp|similarMovies)"', unescaped_html)
        if md_match:
            try: parsed_details = json.loads(md_match.group(1))
            except: pass
            
        if not parsed_details:
            next_data_match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', detail_html, re.DOTALL)
            if next_data_match:
                try:
                    full_next_json = json.loads(next_data_match.group(1))
                    next_movies = []
                    extract_movies_recursive(full_next_json, next_movies)
                    if next_movies: parsed_details = next_movies[0]
                except: pass
        
        imdb_id = parsed_details.get('imdbId') or raw_movie_data.get('imdbId') or ""
        m_type = parsed_details.get('type') or raw_movie_data.get('type') or "movie"
        stremio_data = await fetch_imdb_metadata(session, imdb_id, m_type)

        formatted_movie = format_movie_data(raw_movie_data, parsed_details, stremio_data, detail_html, category_name, detail_res['headers'], url)
        
        if formatted_movie:
             log(f"Verified & Saved: {formatted_movie['title']}", Colors.GREEN, "✓")
             return formatted_movie
        else:
             title_debug = parsed_details.get('title') or "Unknown"
             log(f"No Video found for: {title_debug} - SKIPPING", Colors.WARNING, "!")
             return None

async def scrape_category_async(base_cat_url, session):
    category_name = get_category_name(base_cat_url)
    log(f"STARTING ASYNC SCRAPE: {category_name}", Colors.HEADER, "🚀")
    
    res = await fetch_url_async(session, base_cat_url)
    html = res['data']
    
    api_match = re.search(r'"apiUrl"\s*:\s*"([^"]+)"', html)
    api_path = api_match.group(1).strip('/') if api_match else urlparse(base_cat_url).path.replace('/browse/', '').strip('/')
    
    initial_filter = {"genre": "all", "dateSort": -1}
    filter_match = re.search(r'"initialFilter"\s*:\s*(\{.*?\})', html)
    if filter_match:
        try: initial_filter = json.loads(filter_match.group(1).replace('\\"', '"'))
        except: pass

    # Dynamically find current API URL
    api_base_match = re.search(r'(https://moviesbazar-api-[a-zA-Z0-9-]+\.vercel\.app)', html)
    base_api_url = api_base_match.group(1) if api_base_match else "https://moviesbazar-api-v17.vercel.app"

    api_url = f"{base_api_url}/{api_path}" if api_path.startswith('api/v1/movies/') else f"{base_api_url}/api/v1/movies/{api_path}"
    log(f"Detected Dynamic API: {api_url}", Colors.CYAN, "i")
    
    unique_links = {}
    current_page = 1
    has_more = True
    fails = 0
    
    while has_more:
        log(f"Fetching API Page {current_page} for {category_name}...", Colors.BLUE, "↻")
        skip = (current_page - 1) * 40
        payload = {
            "limit": 40,
            "page": random.randint(100, 9999), 
            "skip": skip,
            "bodyData": { "filterData": initial_filter }
        }
        
        api_res = await fetch_url_async(session, api_url, is_post=True, post_data=payload)
        
        if api_res['error'] or api_res['code'] != 200:
            fails += 1
            log(f"API HTTP {api_res['code']}. Retrying...", Colors.WARNING, "!")
            if fails >= 2: has_more = False
            await asyncio.sleep(2)
            continue
            
        try:
            api_json = json.loads(api_res['data'])
            movie_array = []
            extract_movies_recursive(api_json, movie_array)
            
            added = 0
            for movie in movie_array:
                m_id = movie.get('_id') or movie.get('id') or str(movie.get('imdbId', '')).replace('tt', '')
                if not m_id: continue
                title_slug = generate_slug(movie.get('title'))
                m_type = movie.get('type', 'movie')
                movie_url = f"https://www.moviesbazar.tv/watch/{m_type}/{title_slug}/{m_id}"
                
                if movie_url not in unique_links:
                    unique_links[movie_url] = movie
                    added += 1
                    
            if added > 0:
                log(f"Found {added} new links. Total pending: {len(unique_links)}", Colors.GREEN, "✓")
                current_page += 1
                fails = 0
            else:
                log("End of pagination reached.", Colors.WARNING, "!")
                has_more = False
        except Exception as e:
            log(f"API parse error: {e}", Colors.FAIL, "X")
            has_more = False

    if not unique_links:
        log("No links found. Skipping.", Colors.WARNING, "!")
        return

    log(f"⚡ Launching High-Speed Concurrent Extraction for {len(unique_links)} movies...", Colors.HEADER, "⚡")
    output_filename = f"{category_name.replace(' ', '_').lower()}.json"
    
    concurrency_limit = 20 
    semaphore = asyncio.Semaphore(concurrency_limit)
    
    final_movies_list = []
    items_list = list(unique_links.items())
    batch_size = 200 
    
    for i in range(0, len(items_list), batch_size):
        batch = items_list[i:i+batch_size]
        log(f"Processing batch {i//batch_size + 1} ({len(batch)} items)...", Colors.CYAN, "⚙")
        
        batch_tasks = [process_single_movie(session, url, data, category_name, semaphore) for url, data in batch]
        results = await asyncio.gather(*batch_tasks)
        
        valid_results = [res for res in results if res is not None]
        final_movies_list.extend(valid_results)
        
        with open(output_filename, 'w', encoding='utf-8') as f:
            json.dump(final_movies_list, f, indent=4, ensure_ascii=False)
            
        log(f"💾 BATCH AUTO-SAVED! Total secured: {len(final_movies_list)}/{len(unique_links)}", Colors.WARNING, "💾")

    log(f"✅ {category_name} COMPLETELY SCRAPED! Final count: {len(final_movies_list)}", Colors.GREEN, "🎉")
    print("\n" + "="*50 + "\n")

async def main():
    target_categories = [
        "https://www.moviesbazar.tv/browse/recently-added",
        "https://www.moviesbazar.tv/browse/latest/hollywood",
        "https://www.moviesbazar.tv/browse/latest/bollywood",
        "https://www.moviesbazar.tv/browse/listings/trending-content",
        "https://www.moviesbazar.tv/browse/top-rated",
        "https://www.moviesbazar.tv/browse/latest/south"
    ]
    
    print(f"{Colors.BOLD}{Colors.HEADER}⚡ MoviesBazar ULTRA-FAST ASYNC Scraper Initialized ⚡{Colors.ENDC}")
    print("="*50 + "\n")
    
    connector = aiohttp.TCPConnector(limit=50)
    async with aiohttp.ClientSession(connector=connector) as session:
        for url in target_categories:
            await scrape_category_async(url, session)
            await asyncio.sleep(2) 

    log("ALL CATEGORIES CONCURRENTLY SCRAPED SUCCESSFULLY!", Colors.HEADER, "🏆")

if __name__ == "__main__":
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    asyncio.run(main())
