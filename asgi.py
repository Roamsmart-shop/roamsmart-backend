# asgi.py
import os
import sys

# Add the current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Import the Flask app
try:
    from app import app
    print("[ASGI] Flask app imported successfully")
except Exception as e:
    print(f"[ASGI] Error importing app: {e}")
    raise

# Create ASGI app
try:
    from socketio import ASGIApp
    import socketio
    
    sio = socketio.AsyncServer(
        cors_allowed_origins="*",
        async_mode='asgi'
    )
    
    asgi_app = ASGIApp(sio, app)
    application = asgi_app
    print("[ASGI] ASGI app created successfully")
except Exception as e:
    print(f"[ASGI] Error creating ASGI app: {e}")
    # Fallback to just the Flask app
    application = app