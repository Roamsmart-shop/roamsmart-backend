# gunicorn_config.py
import multiprocessing
import os

bind = f"0.0.0.0:{os.environ.get('PORT', '5000')}"
workers = multiprocessing.cpu_count() * 2 + 1
threads = 2
worker_class = 'sync'
timeout = 120
keepalive = 5
max_requests = 1000
max_requests_jitter = 50
graceful_timeout = 30

# Logging
accesslog = 'logs/access.log'
errorlog = 'logs/error.log'
loglevel = 'info'

# For better performance
preload_app = True
daemon = False
pidfile = 'roamsmart.pid'

# SSL (if using)
certfile = '/etc/ssl/certs/roamsmart.crt'
keyfile = '/etc/ssl/private/roamsmart.key'