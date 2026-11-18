# Generative AI-Based GitHub Repository Analysis and Code Understanding System

A beginner-friendly web application that analyzes any **public GitHub repository**
using **Google Gemini** and explains its structure, source code, functionalities
and architecture in simple English.

## Live Demo

**https://gitinsight-ai-ke93.onrender.com/**

## Features

1. **GitHub Repository Input** – enter a repo URL, validate it, click *Analyze*.
2. **Repository Analysis** – fetches repo details, file tree, languages and important files via the GitHub REST API.
3. **AI-Based Code Understanding** – Gemini generates: project overview, purpose, important files, languages/frameworks, functionalities, architecture, dependencies and improvements.
4. **AI Code Explanation** – select/type any file and get a step-by-step explanation of its functions, classes and logic.
5. **AI Chatbot** – ask questions like *"What is the purpose of this project?"* or *"Explain the main.py file."*

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | HTML, CSS, JavaScript |
| Backend | Python Flask |
| Generative AI | Google Gemini API (`gemini-2.0-flash`) |
| Repository Data | GitHub REST API |

No database, no React/Node.js.

## Project Structure

```
github-ai-analyzer/
    app.py
    requirements.txt
    .env
    templates/
        index.html
    static/
        style.css
        script.js
    README.md
```

## Setup Instructions

### Step 1 – Get a free Google Gemini API key

1. Open <https://aistudio.google.com/apikey>.
2. Sign in with your Google account.
3. Click **Create API key** → copy the key (starts with `AIza...`).
4. The free tier is enough for this project.

### Step 2 – (Optional) Get a GitHub token

Not required, but it raises the API rate limit (60 → 500 requests/hour):

1. Go to <https://github.com/settings/tokens>.
2. Click **Generate new token (classic)**, give it no scopes, copy it.

### Step 3 – Install dependencies

```bash
cd github-ai-analyzer
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS/Linux

pip install -r requirements.txt
```

### Step 4 – Configure your keys

Edit the `.env` file:

```
GEMINI_API_KEY=your_real_key_here
GITHUB_TOKEN=your_token_here   # optional, may stay empty
```

> API keys are read only on the server. **Never** put them in frontend code.

### Step 5 – Run the application

```bash
python app.py
```

Open <http://127.0.0.1:5000> in your browser.

## Sample Repository URLs for Testing

- `https://github.com/pallets/flask` (Python web framework)
- `https://github.com/torvalds/linux` (huge repo – good test of the size limits)
- `https://github.com/public-apis/public-apis` (Markdown-heavy)
- `https://github.com/vinta/awesome-python`

## How It Works

```
Browser ──► Flask (app.py)
              ├── GitHub REST API  → repo info, file tree, file contents
              └── Gemini API       → overview, file explanation, chat answers
Browser ◄── JSON + Markdown rendered with marked.js
```

Safety limits applied: max 15 files, 50 KB per file, 60,000 characters of code
per analysis, so large repositories stay fast and cheap.

## Error Handling

- Invalid GitHub URL → friendly error message
- Repository not found (404) → "Repository not found"
- GitHub rate limit (403) → advice to add a `GITHUB_TOKEN`
- Missing Gemini key → instruction to edit `.env`
- Large files/repos → automatically truncated/skipped
