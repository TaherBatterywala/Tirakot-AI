import json
import datetime
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import os
import subprocess
import webbrowser
import fnmatch
from duckduckgo_search import DDGS

def get_current_datetime() -> str:
    """Returns the current local date and time as a clean string."""
    now = datetime.datetime.now()
    return now.strftime("Current time: %I:%M %p, Date: %A, %B %d, %Y")


def calculator_compute(expression: str) -> str:
    """Safely evaluates a math expression using Python and returns the result as a string.
    Supports basic arithmetic: +, -, *, /, **, %, //, sqrt, abs, round.
    """
    try:
        # Sanitize: only allow digits, operators, parentheses, decimal points, and whitespace
        import re as _re
        sanitized = expression.strip()
        
        # Replace common natural language operators
        sanitized = sanitized.replace("×", "*").replace("÷", "/").replace("^", "**")
        sanitized = sanitized.replace("x", "*") if not any(c.isalpha() and c != 'x' for c in sanitized) else sanitized
        
        # Allow only safe characters
        if not _re.match(r'^[\d\s\+\-\*/\.\(\)%]+$', sanitized):
            # Try to handle sqrt, abs, round, pow
            safe_names = {"sqrt": "math.sqrt", "abs": "abs", "round": "round", "pow": "pow", "pi": "math.pi"}
            for name, replacement in safe_names.items():
                sanitized = sanitized.replace(name, replacement)
            # Final safety check - only allow math module, digits, operators
            if _re.search(r'[a-zA-Z_]', sanitized.replace("math.sqrt", "").replace("math.pi", "").replace("abs", "").replace("round", "").replace("pow", "")):
                return f"Could not evaluate expression: contains unsafe characters."
        
        import math
        result = eval(sanitized, {"__builtins__": {}, "math": math, "abs": abs, "round": round, "pow": pow}, {})
        
        # Format the result nicely
        if isinstance(result, float):
            if result == int(result) and abs(result) < 1e15:
                return str(int(result))
            return f"{result:,.6g}"
        return f"{result:,}" if isinstance(result, int) else str(result)
    except ZeroDivisionError:
        return "Error: Division by zero."
    except Exception as e:
        return f"Could not evaluate expression: {str(e)}"


def get_local_weather(city: str = "") -> str:
    """
    Fetches current weather using wttr.in JSON API.
    Returns clean plain-English text (no HTML, no emoji, no unicode symbols).
    """
    try:
        encoded = urllib.parse.quote(city.strip()) if city.strip() else ""
        url = f"https://wttr.in/{encoded}?format=j1"
        req = urllib.request.Request(url, headers={"User-Agent": "curl/7.68.0"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        cur = data["current_condition"][0]
        temp = cur["temp_C"]
        feels = cur["FeelsLikeC"]
        desc = cur["weatherDesc"][0]["value"]
        humid = cur["humidity"]
        wind = cur["windspeedKmph"]

        areas = data.get("nearest_area", [{}])
        if areas and areas[0]:
            area = areas[0].get("areaName", [{}])[0].get("value", city or "your location")
            region = areas[0].get("region", [{}])[0].get("value", "")
        else:
            area, region = city or "your location", ""

        loc = f"{area}, {region}" if region else area
        return (
            f"{loc}: {desc}, {temp} degrees Celsius "
            f"(feels like {feels}), Humidity {humid} percent, Wind {wind} km/h"
        )
    except Exception:
        return "Weather data is currently unavailable. The system may be offline."


def get_top_news() -> str:
    """
    Fetches the top 3 headlines from BBC News RSS feed.
    Safe offline fallback included.
    """
    try:
        url = "http://feeds.bbci.co.uk/news/rss.xml"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as r:
            xml_data = r.read()

        root = ET.fromstring(xml_data)
        items = root.findall(".//item")[:3]
        headlines = []
        for i, item in enumerate(items, 1):
            title = item.find("title").text
            headlines.append(f"{i}. {title}")

        if not headlines:
            return "No news headlines found at this time."
        return "\n".join(headlines)
    except Exception:
        return "Recent news headlines are currently unavailable (system is offline)."


def scrape_bing_news(query: str) -> list:
    """Helper to scrape Bing News Search to extract real-time articles."""
    articles = []
    try:
        import urllib.request
        import urllib.parse
        import re
        import html
        
        url = 'https://www.bing.com/news/search?q=' + urllib.parse.quote(query)
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
        
        with urllib.request.urlopen(req, timeout=6) as response:
            html_content = response.read().decode('utf-8')
            
        hrefs = re.findall(r'<a\s+[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html_content, re.DOTALL)
        for link, inner_html in hrefs:
            if "http" not in link or "bing.com" in link:
                continue
                
            title = None
            title_match = re.search(r'class="[^"]*(?:news_title|na_t|ns_hd_h2|b_promtxt)[^"]*">(.*?)</div>', inner_html, re.DOTALL)
            if title_match:
                title = title_match.group(1)
            else:
                title_match_h2 = re.search(r'<h2[^>]*>(.*?)</h2>', inner_html, re.DOTALL)
                if title_match_h2:
                    title = title_match_h2.group(1)
                    
            if not title and ("news_title" in inner_html or "na_t" in inner_html or "ns_hd_h2" in inner_html):
                title = re.sub(r'<[^>]+>', '', inner_html).strip()
                
            if title:
                title = re.sub(r'<[^>]+>', '', title).strip()
                title = html.unescape(title)
                
                snippet = ""
                snippet_match = re.search(r'class="[^"]*(?:key-point|snippet|desc)[^"]*">(.*?)</div>', inner_html, re.DOTALL)
                if snippet_match:
                    snippet = re.sub(r'<[^>]+>', '', snippet_match.group(1)).strip()
                    snippet = html.unescape(snippet)
                    
                if not any(a['link'] == link for a in articles):
                    articles.append({
                        "title": title,
                        "snippet": snippet,
                        "link": link
                    })
    except Exception as e:
        print(f"[Bing News Scraper failed]: {e}")
    return articles


def web_search(query: str) -> str:
    """Queries DuckDuckGo search (both news and text) to extract live results cleanly and reliably, with fallback to Bing."""
    results = []
    
    # Clean query for news search by removing conversational/search fluff
    clean_news_query = query.lower()
    fluff_words = ["current status", "current situation", "latest updates", "right now", "today", "status", "news", "recent"]
    for word in fluff_words:
        clean_news_query = clean_news_query.replace(word, "")
    clean_news_query = " ".join(clean_news_query.split())
    
    # 1. Fetch real-time Bing News articles (very robust and bypasses DDG news rate-limiting)
    news_articles = scrape_bing_news(clean_news_query if clean_news_query else query)
    for r in news_articles[:3]:
        results.append(f"News Title: {r['title']}\nSnippet: {r['snippet']}\nLink: {r['link']}")
        
    # 2. Fetch standard text search results from DDG/Bing
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            ddg_results = list(ddgs.text(query, max_results=3))
            for r in ddg_results:
                title = r.get("title", "")
                snippet = r.get("body", "")
                link = r.get("href", "")
                if not any(link in res for res in results):
                    results.append(f"Title: {title}\nSnippet: {snippet}\nLink: {link}")
    except Exception as e:
        print(f"[DDGS search failed, trying Bing fallback]: {e}")
        
    # Fallback to standard Bing scraper if we have no results yet or DDG failed
    if len(results) < 3:
        try:
            import urllib.request
            import urllib.parse
            import re
            import base64
            import html as _html
            
            url = 'https://www.bing.com/search?q=' + urllib.parse.quote(query)
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
            
            with urllib.request.urlopen(req, timeout=8) as response:
                html_content = response.read().decode('utf-8')
                
            pattern = r'<h2[^>]*><a[^>]+href="([^"]+)"[^>]*>(.*?)</a></h2><div class="b_caption"><p[^>]*>(.*?)</p>'
            matches = re.findall(pattern, html_content, re.DOTALL)
            
            for link, title, snippet in matches[:3]:
                if "/ck/a?!" in link:
                    u_match = re.search(r'u=a1([^&"]+)', link)
                    if u_match:
                        b64_url = u_match.group(1)
                        b64_url += "=" * ((4 - len(b64_url) % 4) % 4)
                        try:
                            link = base64.b64decode(b64_url).decode('utf-8')
                        except Exception:
                            pass
                            
                title = re.sub(r'<[^>]+>', '', title).strip()
                snippet = re.sub(r'<[^>]+>', '', snippet).strip()
                title = _html.unescape(title)
                snippet = _html.unescape(snippet)
                
                if not any(link in res for res in results):
                    results.append(f"Title: {title}\nSnippet: {snippet}\nLink: {link}")
        except Exception as e:
            print(f"[Bing standard scraper failed]: {e}")
            
    if not results:
        return "No results found on search engine."
        
    return "\n\n".join(results)


def launch_browser_app(browser_name: str, url: str = None) -> bool:
    """Finds and launches a specific browser with an optional URL on Windows."""
    name = browser_name.lower().strip()
    paths = []
    
    if "brave" in name:
        paths = [
            r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
            r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
            os.path.expandvars(r"%LocalAppData%\BraveSoftware\Brave-Browser\Application\brave.exe")
        ]
    elif "chrome" in name:
        paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe")
        ]
    elif "firefox" in name:
        paths = [
            r"C:\Program Files\Mozilla Firefox\firefox.exe",
            r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe"
        ]
    elif "edge" in name:
        paths = [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"
        ]

    for p in paths:
        if os.path.exists(p):
            cmd = f'"{p}"'
            if url:
                cmd += f' "{url}"'
            subprocess.Popen(cmd, shell=True)
            return True
            
    try:
        if url:
            webbrowser.open(url)
            return True
        else:
            subprocess.Popen(name, shell=True)
            return True
    except Exception:
        return False


def execute_system_command(target: str) -> str:
    """Runs a generic Windows command, shell verb, or application name."""
    target_clean = target.strip('" ')
    target_lower = target_clean.lower()
    
    # Check if it's a direct path on the filesystem (e.g. D:\Folder or C:\file.txt)
    expanded = os.path.expandvars(target_clean)
    if os.path.exists(expanded):
        try:
            if hasattr(os, "startfile"):
                os.startfile(expanded)
            else:
                subprocess.Popen(f'start "" "{expanded}"', shell=True)
            return f"Successfully opened path: {target_clean}"
        except Exception as e:
            return f"Failed to open path {target_clean}: {str(e)}"
            
    # Comprehensive alias mapping
    mapping = {
        "calc": "calc.exe",
        "calculator": "calc.exe",
        "camera": "start microsoft.windows.camera:",
        "explorer": "explorer.exe",
        "file explorer": "explorer.exe",
        "this pc": "explorer.exe",
        "paint": "mspaint.exe",
        "notepad": "notepad.exe",
        "vscode": "code",
        "vs code": "code",
        "visual studio code": "code",
        "spotify": "start spotify:",
        "settings": "start ms-settings:",
        "discord": "start discord:",
        "chrome": "chrome.exe",
        "brave": "brave.exe",
        "edge": "msedge.exe",
        "cmd": "cmd.exe",
        "powershell": "powershell.exe",
        "task manager": "taskmgr.exe",
        "control panel": "control.exe",
        "microsoft store": "start ms-windows-store:",
        "store": "start ms-windows-store:"
    }
    
    # Check static mapping first
    if target_lower in mapping:
        cmd = mapping[target_lower]
        try:
            if cmd.startswith("start "):
                subprocess.Popen(cmd, shell=True)
            else:
                subprocess.Popen(cmd, shell=True)
            return f"Successfully executed system command: {target_clean}"
        except Exception as e:
            try:
                if hasattr(os, "startfile"):
                    os.startfile(cmd)
                    return f"Successfully executed system command: {target_clean}"
            except Exception:
                pass
            return f"Failed to execute system command {target_clean}: {str(e)}"
            
    # Check if target is a known browser app
    for b in ["brave", "chrome", "firefox", "edge", "msedge"]:
        if b in target_lower:
            if launch_browser_app(b):
                return f"Successfully launched browser: {b}"
                
    # Try dynamic Start Menu shortcut lookup for any installed app (dynamic & not hardcoded)
    try:
        start_menu_paths = [
            os.path.expandvars(r"%ProgramData%\Microsoft\Windows\Start Menu\Programs"),
            os.path.expandvars(r"%AppData%\Microsoft\Windows\Start Menu\Programs")
        ]
        shortcut_matches = []
        for base_path in start_menu_paths:
            if os.path.exists(base_path):
                for root, _, files in os.walk(base_path):
                    for file in files:
                        if file.lower().endswith(".lnk"):
                            file_clean = file.lower()[:-4]
                            if target_lower in file_clean or file_clean in target_lower:
                                shortcut_matches.append(os.path.join(root, file))
        if shortcut_matches:
            os.startfile(shortcut_matches[0])
            return f"Successfully executed system command: {target} (via Start Menu)"
    except Exception as e:
        print(f"[Start Menu shortcut lookup failed]: {e}")
        
    cmd = target
    try:
        if cmd.startswith("start "):
            subprocess.Popen(cmd, shell=True)
            return f"Successfully executed system command: {target}"
            
        # Try running directly via shell (works for batch files, CMD apps on Path like code.cmd)
        try:
            subprocess.Popen(cmd, shell=True)
            return f"Successfully executed system command: {target}"
        except Exception:
            pass
            
        # Fallback to os.startfile
        if hasattr(os, "startfile"):
            os.startfile(cmd)
            return f"Successfully executed system command: {target}"
            
        return f"Successfully executed system command: {target}"
    except Exception as e:
        try:
            # Fallback to general start shell command
            subprocess.Popen(f"start {cmd}", shell=True)
            return f"Started command via shell fallback: {target}"
        except Exception as e2:
            return f"Failed to execute system command: {str(e)}"


def advanced_open(app_or_url: str, context: str = None) -> str:
    """Maps inputs to open desktop apps or direct URLs inside browser."""
    clean_target = app_or_url.strip()
    
    parts = clean_target.split(None, 1)
    if len(parts) == 2:
        browser_candidate = parts[0].lower()
        url_candidate = parts[1].strip()
        if browser_candidate in ["brave", "chrome", "firefox", "edge"]:
            # If the candidate looks like a search query rather than a direct URL
            if " " in url_candidate or "." not in url_candidate:
                url_candidate = f"https://www.google.com/search?q={urllib.parse.quote(url_candidate)}"
            elif not (url_candidate.startswith("http://") or url_candidate.startswith("https://")):
                url_candidate = f"https://{url_candidate}"
            if launch_browser_app(browser_candidate, url_candidate):
                return f"Successfully launched {browser_candidate} at URL: {url_candidate}"
                
    if clean_target.startswith("http://") or clean_target.startswith("https://") or "." in clean_target:
        # Open URL
        url = clean_target if (clean_target.startswith("http://") or clean_target.startswith("https://")) else f"https://{clean_target}"
        webbrowser.open(url)
        return f"Successfully opened URL: {url}"
    else:
        # Fallback to system command executor
        return execute_system_command(clean_target)


def create_vscode_file(filename: str, code: str) -> str:
    """Writes code content to local workspace directory and launches in VSCode."""
    try:
        # Save to current workspace directory
        filepath = os.path.abspath(filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(code)
        
        # Spawn VSCode process
        subprocess.Popen(f"code \"{filepath}\"", shell=True)
        return f"Successfully created file {filename} and launched VSCode."
    except Exception as e:
        return f"Failed to create VSCode file: {str(e)}"


def send_whatsapp(contact_name: str, text: str) -> str:
    """Stages an automated WhatsApp message using deep-linked web string protocols."""
    try:
        # Open WhatsApp Web or Desktop with text pre-filled
        encoded_text = urllib.parse.quote(text)
        whatsapp_url = f"https://web.whatsapp.com/send?text={encoded_text}"
        # We can also attempt local app deep link: whatsapp://send?text=...
        webbrowser.open(whatsapp_url)
        return f"Successfully staged WhatsApp message to {contact_name or 'contact'} with content: '{text}'"
    except Exception as e:
        return f"Failed to stage WhatsApp message: {str(e)}"


def locate_and_open_file(filename: str, directory_path: str) -> str:
    """Recursively searches for a file in target directory and opens it if found."""
    try:
        if not os.path.exists(directory_path):
            return f"Directory path does not exist: {directory_path}"
        
        match_filepath = None
        for root, dirs, files in os.walk(directory_path):
            for f in files:
                if fnmatch.fnmatch(f.lower(), f"*{filename.lower()}*"):
                    match_filepath = os.path.join(root, f)
                    break
            if match_filepath:
                break
        
        if match_filepath:
            os.startfile(match_filepath) if hasattr(os, "startfile") else webbrowser.open(match_filepath)
            return f"Successfully located and opened file: {match_filepath}"
        else:
            return f"File '{filename}' not found under '{directory_path}'."
    except Exception as e:
        return f"Failed to locate or open file: {str(e)}"


def append_local_note(note_content: str) -> str:
    """Appends note content directly to a notes.md file in the local workspace directory."""
    try:
        filepath = os.path.abspath("notes.md")
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %I:%M %p")
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(f"\n## Note added on {timestamp}\n{note_content}\n")
        return f"Successfully appended note to {filepath}"
    except Exception as e:
        return f"Failed to append note: {str(e)}"
