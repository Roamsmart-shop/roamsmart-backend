# limiter.py
import os
import sys
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_limiter.errors import RateLimitExceeded
from flask import jsonify

print("[DEBUG] Loading limiter module...")

# Create limiter instance (without app first)
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://",
    strategy="fixed-window",
)

print("[DEBUG] Limiter instance created successfully")

def init_limiter(app):
    """Initialize limiter with Flask app"""
    print("[DEBUG] Initializing limiter with app...")
    
    # Configure Redis if available
    redis_url = os.environ.get('REDIS_URL')
    print(f"[DEBUG] Redis URL from env: {redis_url if redis_url else 'NOT SET'}")
    
    if redis_url:
        try:
            limiter.storage_uri = redis_url
            print(f"[DEBUG] ✅ Rate limiter configured with Redis: {redis_url}")
        except Exception as e:
            print(f"[DEBUG] ❌ Failed to configure Redis: {e}")
            print("[DEBUG] Falling back to memory storage")
            limiter.storage_uri = "memory://"
    else:
        print("[DEBUG] ⚠️ No Redis URL, using memory storage")
        limiter.storage_uri = "memory://"
    
    # Initialize with app
    limiter.init_app(app)
    print("[DEBUG] ✅ Limiter initialized with app")
    
    # Register error handler
    @app.errorhandler(RateLimitExceeded)
    def ratelimit_handler(e):
        print(f"[DEBUG] Rate limit exceeded: {e}")
        return jsonify({
            'success': False,
            'error': 'Too many requests. Please try again later.',
            'retry_after': 60
        }), 429
    
    print("[DEBUG] ✅ Rate limit error handler registered")
    return limiter