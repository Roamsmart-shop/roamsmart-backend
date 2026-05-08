import os

# Bind to the port Railway provides, default to 5000 locally
bind = f"0.0.0.0:{os.environ.get('PORT', '5000')}"

# Use eventlet for async concurrency
worker_class = "eventlet"
workers = 1
threads = 2
timeout = 120
keepalive = 5

# Performance and stability
preload_app = True
graceful_timeout = 30
max_requests = 1000
max_requests_jitter = 50

# Logging (stdout/stderr so Railway captures logs)
accesslog = "-"
errorlog = "-"
loglevel = "info"

# No SSL here — Railway handles HTTPS at the proxy level
