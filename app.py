"""
Generative AI-Based GitHub Repository Analysis and Code Understanding System
Backend Flask application.

Features:
- Accepts a public GitHub repository URL
- Fetches repository info + file tree from GitHub REST API
- Sends selected source code to Google Gemini for AI analysis
- Explains individual code files
- Provides a chatbot for Q&A about the analyzed repository
"""

import os
import re
import time
import base64

import requests
from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import HTTPException
from dotenv import load_dotenv
from google import genai
from google.genai import types

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Load API keys from the .env file (never hardcode keys in this file)
load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")       # optional, raises GitHub rate limits
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")   # required for AI features

GITHUB_API = "https://api.github.com"

# Limits so that large repositories do not blow up the prompt / cost
MAX_FILES_FOR_ANALYSIS = 15        # max source files sent for repository analysis
MAX_FILE_SIZE_BYTES = 50_000       # skip files bigger than ~50 KB
MAX_TOTAL_CHARS = 25_000           # total characters of code sent to Gemini

# File extensions we consider "source code"
SOURCE_EXTENSIONS = (
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".c", ".cpp", ".h", ".hpp",
    ".cs", ".go", ".rs", ".rb", ".php", ".swift", ".kt", ".scala", ".sh",
    ".html", ".css", ".scss", ".sql", ".yaml", ".yml", ".json", ".md", ".xml",
)

app = Flask(__name__)

# Initialize the Gemini client once at startup
genai_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None


# ---------------------------------------------------------------------------
# Error handling: always return JSON for /api/* (never an HTML error page)
# ---------------------------------------------------------------------------

@app.errorhandler(HTTPException)
def handle_http_error(err):
    if request.path.startswith("/api/"):
        return jsonify({"error": err.description or err.name}), err.code
    return err


@app.errorhandler(Exception)
def handle_unexpected_error(err):
    if request.path.startswith("/api/"):
        return jsonify({"error": f"Unexpected server error: {err}"}), 500
    return "Internal Server Error", 500


# ---------------------------------------------------------------------------
# Helper: GitHub API calls
# ---------------------------------------------------------------------------

def github_headers():
    """Return headers for GitHub API requests (adds token if provided)."""
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return headers


def parse_repo_url(url):
    """
    Parse a GitHub URL like https://github.com/owner/repo
    Returns (owner, repo) or (None, None) if invalid.
    """
    if not url:
        return None, None
    # Remove whitespace, trailing slashes and '.git'
    url = url.strip().rstrip("/")
    if url.endswith(".git"):
        url = url[:-4]

    pattern = r"^https?://(?:www\.)?github\.com/([\w.\-]+)/([\w.\-]+)"
    match = re.match(pattern, url)
    if match:
        return match.group(1), match.group(2)

    # Also allow "owner/repo" style input
    pattern2 = r"^([\w.\-]+)/([\w.\-]+)$"
    match2 = re.match(pattern2, url)
    if match2:
        return match2.group(1), match2.group(2)

    return None, None


def github_get(path, params=None):
    """Make a GET request to the GitHub API and return parsed JSON."""
    response = requests.get(
        f"{GITHUB_API}{path}",
        headers=github_headers(),
        params=params or {},
        timeout=30,
    )
    if response.status_code == 404:
        raise ValueError("Repository not found. Please check the URL.")
    if response.status_code in (403, 429):
        # Rate limited - tell the user exactly when it resets
        reset_ts = response.headers.get("X-RateLimit-Reset")
        reset_at = ""
        if reset_ts and reset_ts.isdigit():
            import datetime
            reset_at = datetime.datetime.fromtimestamp(int(reset_ts)).strftime("%H:%M:%S")
            reset_at = f" Resets at {reset_at}."
        raise ValueError(
            "GitHub API rate limit exceeded (60 requests/hour without a token)."
            f"{reset_at} "
            "Fix: add a free GITHUB_TOKEN in the .env file for 5000 requests/hour."
        )
    if response.status_code != 200:
        raise ValueError(f"GitHub API error (HTTP {response.status_code}).")
    return response.json()


def get_file_tree(owner, repo, branch=None):
    """
    Get the full file tree of a repository using the Git Trees API.
    Returns a list of dicts: {path, type, size}.
    """
    if not branch:
        repo_info = github_get(f"/repos/{owner}/{repo}")
        branch = repo_info.get("default_branch", "main")

    tree = github_get(f"/repos/{owner}/{repo}/git/trees/{branch}", params={"recursive": "1"})
    entries = []
    for item in tree.get("tree", []):
        entries.append({
            "path": item.get("path", ""),
            "type": item.get("type", "blob"),
            "size": item.get("size", 0),
        })
    return entries, branch


def get_file_content(owner, repo, path, branch):
    """Download the text content of a single file."""
    url = f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}"
    response = requests.get(url, headers=github_headers(),
                            params={"ref": branch}, timeout=30)
    if response.status_code != 200:
        return None
    data = response.json()
    if isinstance(data, dict) and data.get("content"):
        # GitHub returns base64 encoded content
        try:
            decoded = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
            return decoded
        except Exception:
            return None
    return None


def select_important_files(entries):
    """
    Pick the most important source files for analysis.
    Priority: README, main/app entry points, then other source files.
    """
    files = [e for e in entries if e["type"] == "blob"]

    def score(entry):
        path = entry["path"].lower()
        name = os.path.basename(path)
        s = 0
        if name in ("readme.md", "readme"):
            s += 100
        if name in ("main.py", "app.py", "index.js", "index.py", "manage.py"):
            s += 90
        if name in ("requirements.txt", "package.json", "pyproject.toml", "setup.py"):
            s += 80
        if path.count("/") <= 1:            # prefer top-level files
            s += 10
        if name.startswith("test"):         # tests are less important for overview
            s -= 20
        if entry["path"].endswith(SOURCE_EXTENSIONS):
            s += 5
        return s

    files.sort(key=score, reverse=True)
    return files[:MAX_FILES_FOR_ANALYSIS]


def build_code_bundle(owner, repo, files, branch):
    """Concatenate selected file contents into one text bundle for Gemini."""
    parts = []
    total = 0
    included = []
    for entry in files:
        path = entry["path"]
        if entry.get("size", 0) > MAX_FILE_SIZE_BYTES:
            continue
        content = get_file_content(owner, repo, path, branch)
        if content is None:
            continue
        block = f"### FILE: {path}\n```\n{content}\n```\n"
        if total + len(block) > MAX_TOTAL_CHARS:
            break
        parts.append(block)
        total += len(block)
        included.append(path)
    return "\n".join(parts), included


# ---------------------------------------------------------------------------
# Helper: Gemini AI call
# ---------------------------------------------------------------------------

# Try several models in order; some may be at high demand (503), retired (404)
# or out of free-tier daily quota (429). Fast models are tried first.
GEMINI_MODELS = [
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash",
    "gemini-3.6-flash",
    "gemini-3.7-flash",
    "gemini-3.8-flash",
    "gemini-2.5-flash",
]

# Hard cap for one AI request so we always finish before the host/gunicorn
# timeout. If we exceed it we raise a clean, JSON-friendly error instead of
# letting the worker get killed (which returns an HTML error page).
AI_DEADLINE_SECONDS = 75


def generate_ai(contents, system_instruction="", temperature=0.3, max_output_tokens=2048):
    """
    Call Gemini with automatic model fallback and short retries.
    Works with both plain-string prompts and multi-turn Content lists.
    """
    if genai_client is None:
        raise ValueError("GEMINI_API_KEY is not set. Add it to the .env file.")

    deadline = time.time() + AI_DEADLINE_SECONDS
    last_error = None
    detail = ""
    for model in GEMINI_MODELS:
        for attempt in range(2):
            if time.time() > deadline:
                break
            try:
                response = genai_client.models.generate_content(
                    model=model,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction or None,
                        temperature=temperature,
                        max_output_tokens=max_output_tokens,
                    ),
                )
                return (response.text or "").strip()
            except Exception as exc:  # depends on network / demand / key
                last_error = exc
                message = str(exc)
                if not detail:
                    detail = f"{model}: {message[:200]}"
                # Daily quota exhausted for this model - move to the next one
                if "429" in message or "RESOURCE_EXHAUSTED" in message:
                    break
                # Temporary errors (503 demand, 404 retired model) - tiny retry
                if ("503" in message or "404" in message
                        or "UNAVAILABLE" in message or "NOT_FOUND" in message):
                    time.sleep(1)
                    continue
                break  # permanent error (bad key, bad request...) - stop trying
        if time.time() > deadline:
            break
    # Friendly summary instead of a long raw API error
    raise ValueError(
        "All AI models are busy or out of quota right now. "
        "Please try again in a few minutes. (Details: "
        f"{detail or str(last_error)}"
        ")"
    )


def ask_gemini(prompt, system_instruction=""):
    """Send a text prompt to Gemini and return the text response."""
    return generate_ai(prompt, system_instruction=system_instruction)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def home():
    """Serve the main dashboard page."""
    return render_template("index.html")


@app.route("/api/analyze", methods=["POST"])
def analyze():
    """
    Feature 2 + Feature 3:
    Fetch repository info, file tree and generate an AI project overview.
    """
    data = request.get_json(silent=True) or {}
    owner, repo = parse_repo_url(data.get("url", ""))
    if not owner:
        return jsonify({"error": "Invalid GitHub repository URL."}), 400

    try:
        # 1. Basic repository information
        info = github_get(f"/repos/{owner}/{repo}")

        # 2. File / folder structure
        entries, branch = get_file_tree(owner, repo)

        # 3. Programming languages
        languages = github_get(f"/repos/{owner}/{repo}/languages")

        # 4. Pick important files and their content
        important = select_important_files(entries)
        code_bundle, included = build_code_bundle(owner, repo, important, branch)

        # Tree text for the prompt (limit to 200 entries)
        tree_lines = [f"{e['path']}/" if e["type"] == "tree" else e["path"]
                      for e in entries[:200]]
        tree_text = "\n".join(tree_lines)

        # 5. Ask Gemini for the full analysis
        prompt = f"""
You are a senior software engineer reviewing a GitHub repository.
Repository: {info.get('full_name')}
Description: {info.get('description') or 'No description provided'}
Primary languages (from GitHub): {languages}
Default branch: {branch}

FILE STRUCTURE:
{tree_text}

SELECTED SOURCE FILES:
{code_bundle if code_bundle else "(no source files could be fetched)"}

Write a clear, beginner-friendly analysis in Markdown with EXACTLY these sections:
## Project Overview
## Purpose of the Project
## Programming Languages and Frameworks
## Main Functionalities
## Project Architecture
## Explanation of Important Files
## Key Dependencies
## Possible Improvements
"""
        analysis = ask_gemini(
            prompt,
            system_instruction="You explain code simply for beginners. Use short sentences and Markdown.",
        )

        return jsonify({
            "repo": {
                "name": info.get("full_name"),
                "description": info.get("description"),
                "stars": info.get("stargazers_count", 0),
                "forks": info.get("forks_count", 0),
                "owner": info.get("owner", {}).get("login"),
                "branch": branch,
                "html_url": info.get("html_url"),
                "language": info.get("language"),
            },
            "languages": languages,
            "tree": entries[:300],
            "files": included,
            "analysis": analysis,
        })

    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": f"Unexpected error: {exc}"}), 500


@app.route("/api/explain", methods=["POST"])
def explain():
    """
    Feature 4: Explain a single source code file step by step.
    """
    data = request.get_json(silent=True) or {}
    owner, repo = parse_repo_url(data.get("url", ""))
    file_path = (data.get("file") or "").strip()

    if not owner or not file_path:
        return jsonify({"error": "Repository URL and file path are required."}), 400

    try:
        info = github_get(f"/repos/{owner}/{repo}")
        branch = info.get("default_branch", "main")

        content = get_file_content(owner, repo, file_path, branch)
        if content is None:
            return jsonify({"error": "File not found or could not be read."}), 404
        if len(content) > MAX_FILE_SIZE_BYTES * 2:
            content = content[: MAX_FILE_SIZE_BYTES * 2] + "\n... (truncated)"

        prompt = f"""
Explain the following source file from the GitHub repository
{info.get('full_name')} in simple English for a beginner.

FILE: {file_path}

CODE:
```
{content}
```

Write a Markdown response with these sections:
## What This File Does
## Important Functions and Classes
## Step-by-Step Logic
## Key Takeaway
"""
        explanation = ask_gemini(
            prompt,
            system_instruction="You are a friendly coding tutor. Explain code step by step, simply.",
        )
        return jsonify({"file": file_path, "explanation": explanation})

    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": f"Unexpected error: {exc}"}), 500


@app.route("/api/chat", methods=["POST"])
def chat():
    """
    Feature 5: Chatbot that answers questions about the analyzed repository.
    The frontend sends the previous analysis summary as context.
    """
    data = request.get_json(silent=True) or {}
    question = (data.get("question") or "").strip()
    context = (data.get("context") or "").strip()
    history = data.get("history") or []  # list of {role, content}

    if not question:
        return jsonify({"error": "Please enter a question."}), 400

    # Build a short conversation for multi-turn context
    contents = []
    for msg in history[-6:]:  # keep only the last 6 messages
        contents.append(
            types.Content(
                role="user" if msg.get("role") == "user" else "model",
                parts=[types.Part(text=msg.get("content", ""))],
            )
        )
    contents.append(types.Content(role="user", parts=[types.Part(text=question)]))

    system = (
        "You are a helpful assistant that answers questions about a GitHub "
        "repository that was analyzed. Answer simply and concisely in Markdown.\n\n"
        f"REPOSITORY ANALYSIS CONTEXT:\n{context[:15000]}\n\n"
        "If the answer is not in the context, say you do not have that information."
    )

    try:
        answer = generate_ai(
            contents,
            system_instruction=system,
            temperature=0.4,
            max_output_tokens=1024,
        )
        return jsonify({"answer": answer})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": f"AI request failed: {exc}"}), 500


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # PORT comes from the hosting platform (Render/Railway) or defaults to 5000
    port = int(os.environ.get("PORT", 5000))
    # host 0.0.0.0 so the app is reachable from outside (needed for hosting)
    app.run(host="0.0.0.0", port=port, debug=True, threaded=True)


