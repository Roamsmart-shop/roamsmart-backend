# asgi.py - Place this in your backend root
import os
from app import app
from socketio import ASGIApp
import socketio

# Create Socket.IO server (ASGI mode)
sio = socketio.AsyncServer(
    cors_allowed_origins="*",
    async_mode='asgi',
    logger=True,
    engineio_logger=True
)

# Wrap Flask app
asgi_app = ASGIApp(sio, app)

# Export for uvicorn
application = asgi_app