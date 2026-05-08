import os

bind = f"0.0.0.0:{os.environ.get('PORT', '5000')}"
worker_class = "eventlet"
workers = 1
threads = 2
timeout = 120
keepalive = 5

preload_app = True
graceful_timeout = 30
max_requests = 1000
max_requests_jitter = 50

accesslog = "-"
errorlog = "-"
loglevel = "info"
