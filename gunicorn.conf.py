# Gunicorn settings loaded automatically from the project root.
# Keeps the worker alive long enough for the Gemini analysis to finish,
# even if the hosting start command does not pass --timeout explicitly.
workers = 2
timeout = 180
graceful_timeout = 30
keepalive = 5
