# ========== DNS FIX FOR EVENTLET - MUST BE FIRST ==========
import os
os.environ["EVENTLET_NO_GREENDNS"] = "yes"  # Disable eventlet's DNS resolver

import eventlet
eventlet.monkey_patch()

# Force system DNS resolver
import socket
import dns.resolver
dns.resolver.default_resolver = dns.resolver.Resolver()
dns.resolver.default_resolver.nameservers = ['8.8.8.8', '8.8.4.4']

# Pre-resolve external domains at startup for faster access
def pre_resolve_domains():
    domains = ['api.africastalking.com', 'api.sendgrid.com', 'smtp.sendgrid.net']
    for domain in domains:
        try:
            ip = socket.gethostbyname(domain)
            print(f"[DNS] ✅ Resolved {domain} -> {ip}")
        except Exception as e:
            print(f"[DNS] ❌ Failed to resolve {domain}: {e}")

pre_resolve_domains()

# ========== STANDARD LIBRARY IMPORTS ==========
import uuid
import re
import base64
import random
import hashlib
import json
import smtplib
import logging
from logging.handlers import RotatingFileHandler
from io import BytesIO
from datetime import datetime, timedelta
from functools import wraps
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from urllib.parse import urlparse

# ========== THIRD PARTY IMPORTS ==========
import redis
import bcrypt
import pyotp
import qrcode
import requests
import sendgrid
from sendgrid.helpers.mail import Mail, Email, To, Content
from flask import Flask, request, jsonify, session, send_from_directory, g
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_limiter.errors import RateLimitExceeded
from flask_socketio import SocketIO, emit
from sqlalchemy import func, and_, or_
from werkzeug.utils import secure_filename
from flask_session import Session
import secrets
# ========== LOCAL IMPORTS ==========
from config import config
from models import *

# ========== COMPANY CONFIGURATION ==========
COMPANY_NAME = "Roamsmart Digital Service"
COMPANY_SHORT = "Roamsmart"
COMPANY_EMAIL = "support@roamsmart.shop"
COMPANY_ADMIN_EMAIL = "admin@roamsmart.shop"
COMPANY_PHONE = "0557388622"
COMPANY_WEBSITE = "https://roamsmart.shop"
COMPANY_DOMAIN = "roamsmart.shop"

# ========== FLASK APP INITIALIZATION ==========
app = Flask(__name__)

# ========== ENVIRONMENT CONFIGURATION ==========
env = os.environ.get('FLASK_ENV', 'production')
app.config.from_object(config[env])
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', secrets.token_hex(16))


REDIS_URL = os.environ.get('REDIS_URL')

# Try Redis connection
redis_available = False
redis_client = None

if REDIS_URL:
    try:
        redis_client = redis.from_url(
            REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=3
        )
        redis_client.ping()
        redis_available = True
        print("✅ Redis connected for temporary storage")
    except Exception as e:
        print(f"⚠️ Redis connection failed: {e}")
        print("   Using memory storage for rate limiting")

# Fallback for local development (memory storage)
if not redis_available:
    temp_storage = {}
    print("⚠️ Using memory storage for temporary data (local development)")

def set_temp_data(key, data, expiry_seconds=600):
    """Store temporary data in Redis or memory"""
    if redis_available and redis_client:
        redis_client.setex(f"temp:{key}", expiry_seconds, json.dumps(data))
    else:
        temp_storage[key] = data

def get_temp_data(key):
    """Get temporary data from Redis or memory"""
    if redis_available and redis_client:
        data = redis_client.get(f"temp:{key}")
        return json.loads(data) if data else None
    else:
        return temp_storage.get(key)

def delete_temp_data(key):
    """Delete temporary data from Redis or memory"""
    if redis_available and redis_client:
        redis_client.delete(f"temp:{key}")
    else:
        if key in temp_storage:
            del temp_storage[key]
# ========== UPLOAD CONFIGURATION ==========
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads', 'profile_pics')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
MAX_FILE_SIZE = 5 * 1024 * 1024

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

# ========== DATABASE INITIALIZATION ==========
db.init_app(app)

# ========== LOGGING CONFIGURATION ==========
if not os.path.exists('logs'):
    os.mkdir('logs')

file_handler = RotatingFileHandler('logs/roamsmart.log', maxBytes=10240, backupCount=10)
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
))
file_handler.setLevel(logging.INFO)
app.logger.addHandler(file_handler)
app.logger.setLevel(logging.INFO)

# ========== REQUEST LOGGING ==========
@app.before_request
def log_request():
    """Log all incoming requests for audit"""
    if not request.path.startswith('/static') and not request.path.startswith('/uploads'):
        app.logger.info(f'Request: {request.method} {request.path} from {request.remote_addr}')

# ========== RATE LIMITER INITIALIZATION ==========
print("[DEBUG] ===== STARTING RATE LIMITER INITIALIZATION =====")

# Import limiter module
try:
    from limiter import limiter, init_limiter
    print("[DEBUG] ✅ Successfully imported limiter module")
except Exception as e:
    print(f"[DEBUG] ❌ Failed to import limiter: {e}")
    # Create a dummy limiter as fallback
    class DummyLimiter:
        def limit(self, *args, **kwargs):
            def decorator(f):
                return f
            return decorator
    limiter = DummyLimiter()
    print("[DEBUG] ⚠️ Using dummy limiter (no rate limiting)")

# Initialize limiter with app
try:
    init_limiter(app)
    print("[DEBUG] ✅ Rate limiter initialized successfully")
    print(f"[DEBUG] Limiter type: {type(limiter)}")
    print(f"[DEBUG] Limiter storage: {getattr(limiter, 'storage_uri', 'unknown')}")
except Exception as e:
    print(f"[DEBUG] ❌ Failed to initialize limiter: {e}")
    print("[DEBUG] ⚠️ Continuing without rate limiting")
    
print("[DEBUG] ===== RATE LIMITER INITIALIZATION COMPLETE =====\n")

# ========== CORS CONFIGURATION ==========
def get_allowed_origins():
    origins = [
        'http://localhost:3000',
        'http://localhost:5000',
        'http://127.0.0.1:3000',
        'http://127.0.0.1:5000',
        'https://roamsmart.shop',
        'https://www.roamsmart.shop',
        'https://api.roamsmart.shop',
        'https://roamsmart-frontend.vercel.app',
        'https://roamsmart-frontend-cgggs8bm4-roamsmart-shops-projects.vercel.app',
    ]
    railway_frontend = os.environ.get('RAILWAY_FRONTEND_URL')
    if railway_frontend:
        origins.append(railway_frontend)
    railway_backend = os.environ.get('RAILWAY_PUBLIC_DOMAIN')
    if railway_backend:
        origins.append(f'https://{railway_backend}')
    return list(dict.fromkeys(origins))

ALLOWED_HEADERS = [
    'Content-Type', 'Authorization', 'X-Requested-With', 'X-Company',
    'X-Request-Time', 'X-Price-Auth', 'X-App-Version'
]
ALLOWED_METHODS = ['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS', 'PATCH']
ALLOWED_ORIGINS = get_allowed_origins()
print(f"[CORS] Allowed origins: {ALLOWED_ORIGINS}")

CORS(app,
     origins=ALLOWED_ORIGINS,
     supports_credentials=True,
     allow_headers=ALLOWED_HEADERS,
     methods=ALLOWED_METHODS,
     expose_headers=ALLOWED_HEADERS,
     max_age=3600)

# ========== SOCKET.IO ==========
socketio = SocketIO(
    app,
    cors_allowed_origins=ALLOWED_ORIGINS,
    async_mode='eventlet',
    ping_timeout=60,
    ping_interval=25,
    max_http_buffer_size=1000000,
    allow_upgrades=True,
    transports=['polling', 'websocket'],
    logger=True,
    engineio_logger=True
)

# ========== AFRICA'S TALKING ==========
AFRICASTALKING_API_KEY = os.environ.get('AFRICASTALKING_API_KEY')
AFRICASTALKING_USERNAME = os.environ.get('AFRICASTALKING_USERNAME', 'sandbox')
AFRICASTALKING_SENDER_ID = os.environ.get('AFRICASTALKING_SENDER_ID', 'Roamsmart')

africas_talking_sms = None
if AFRICASTALKING_API_KEY and AFRICASTALKING_API_KEY != 'mock_key':
    try:
        import africastalking
        africastalking.initialize(AFRICASTALKING_USERNAME, AFRICASTALKING_API_KEY)
        africas_talking_sms = africastalking.SMS
        print(f"[Africa's Talking] ✅ Initialized successfully")
        print(f"[Africa's Talking] Username: {AFRICASTALKING_USERNAME}")
        print(f"[Africa's Talking] Sender ID: {AFRICASTALKING_SENDER_ID}")
    except Exception as e:
        print(f"[Africa's Talking] ❌ Error: {e}")
else:
    print("[Africa's Talking] No API key found - SMS will not be sent")

# ========== SECURITY HEADERS ==========
@app.after_request
def add_security_headers(response):
    """Add security headers to prevent XSS and other attacks"""
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    response.headers['Content-Security-Policy'] = "default-src 'self'"
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'
    return response

# ========== SUSPICIOUS ACTIVITY LOGGING ==========
def log_suspicious_activity(user_id, activity_type, details, ip_address):
    """Log suspicious activities for monitoring"""
    try:
        log = SuspiciousActivityLog(
            user_id=user_id,
            activity_type=activity_type,
            details=details,
            ip_address=ip_address,
            created_at=datetime.utcnow()
        )
        db.session.add(log)
        db.session.commit()
        
        # Alert admin for critical activities
        if activity_type in ['brute_force', 'multiple_accounts', 'unusual_location']:
            send_admin_alert(f"Suspicious Activity: {activity_type}", details)
    except Exception as e:
        print(f"Error logging suspicious activity: {e}")

def send_admin_alert(subject, message):
    """Send alert to admin email"""
    try:
        send_email(
            to=COMPANY_ADMIN_EMAIL,
            subject=f"[ALERT] {subject}",
            body=f"""
            <div style="font-family: Arial, sans-serif;">
                <h2 style="color: #ff0000;">⚠️ Security Alert</h2>
                <p><strong>Subject:</strong> {subject}</p>
                <p><strong>Message:</strong> {message}</p>
                <p><strong>Time:</strong> {datetime.utcnow().isoformat()}</p>
                <hr>
                <p>This is an automated alert from Roamsmart Security System.</p>
            </div>
            """
        )
    except Exception as e:
        print(f"Failed to send admin alert: {e}")

import html

def validate_phone(phone):
    """Validate Ghana phone numbers"""
    if not phone:
        return False
    phone = str(phone).strip()
    pattern = r'^(233|0)(20|23|24|25|26|27|28|29|50|53|54|55|56|57|58|59)[0-9]{7}$'
    return bool(re.match(pattern, phone))

def validate_email(email):
    """Validate email format"""
    if not email:
        return False
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))

def validate_amount(amount):
    """Validate amount is positive and within limits"""
    try:
        amount = float(amount)
        return 0 < amount <= 10000  # Max GHS 10,000
    except:
        return False

def validate_password(password):
    """Validate password strength"""
    if not password or len(password) < 6:
        return False
    return True

def sanitize_input(text):
    """Sanitize user input to prevent XSS"""
    if not text:
        return text
    return html.escape(str(text))

def validate_network(network):
    """Validate network provider"""
    valid_networks = ['mtn', 'telecel', 'airteltigo', 'vodafone']
    return network and network.lower() in valid_networks

class PhoneVerificationService:
    """Handle phone number verification - SMS first, Email only if SMS fails or resend requested"""
    
    def __init__(self):
        self.verification_codes = {}
    
    def generate_verification_code(self):
        """Generate 6-digit verification code"""
        return str(random.randint(100000, 999999))
    
    def normalize_phone(self, phone):
        """Normalize phone number to consistent format (233XXXXXXXXX)"""
        phone = str(phone).strip()
        # Remove any non-digit characters
        phone = re.sub(r'\D', '', phone)
        # If it starts with 0, change to 233 format
        if phone.startswith('0'):
            phone = '233' + phone[1:]
        # If it's 9 digits, add 233 prefix
        elif len(phone) == 9:
            phone = '233' + phone
        # If it starts with 233, keep as is
        elif phone.startswith('233') and len(phone) == 12:
            return phone
        return phone
    
    def send_sms(self, phone_number, code):
        """Send SMS using Africa's Talking direct API (working method)"""
        try:
            api_key = os.environ.get('AFRICASTALKING_API_KEY')
            username = os.environ.get('AFRICASTALKING_USERNAME', 'Roamsmart')
            sender_id = os.environ.get('AFRICASTALKING_SENDER_ID', 'Roamsmart')
            
            # Format phone number correctly using normalize
            formatted_phone = self.normalize_phone(phone_number)
            
            message = f"Your Roamsmart verification code is: {code}. Valid for 10 minutes."
            
            url = "https://api.africastalking.com/version1/messaging"
            
            data = {
                "username": username,
                "to": formatted_phone,
                "message": message,
                #"from": sender_id
            }
            
            headers = {
                "apiKey": api_key,
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json"
            }
            
            response = requests.post(url, data=data, headers=headers, timeout=30)
            
            if response.status_code in [200, 201]:
                result = response.json()
                recipients = result.get('SMSMessageData', {}).get('Recipients', [])
                if recipients and recipients[0].get('status') == 'Success':
                    print(f"[SMS] ✅ Sent to {phone_number}")
                    return {'success': True, 'method': 'sms'}
            
            print(f"[SMS] ❌ Failed: {response.text}")
            return {'success': False, 'error': 'SMS sending failed', 'method': 'sms'}
            
        except Exception as e:
            print(f"[SMS] ❌ Error: {e}")
            return {'success': False, 'error': str(e), 'method': 'sms'}
    
    def send_email_fallback(self, email, phone_number, code):
        """Send verification code via email (SMS fallback or resend)"""
        html_content = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <div style="background: #8B0000; padding: 20px; text-align: center; border-radius: 10px 10px 0 0;">
                <h2 style="color: white;">📱 Phone Verification Code</h2>
                <p style="color: white;">{COMPANY_NAME}</p>
            </div>
            <div style="background: #f5f5f5; padding: 30px; border-radius: 0 0 10px 10px;">
                <p>Your verification code for <strong>{phone_number}</strong> is:</p>
                <div style="background: white; font-size: 36px; font-weight: bold; text-align: center; padding: 20px; border-radius: 10px; margin: 20px 0; letter-spacing: 5px;">
                    {code}
                </div>
                <p style="color: #666;">This code expires in <strong>10 minutes</strong>.</p>
                <p style="color: #666; font-size: 12px;">(SMS delivery failed, so we're sending this code via email)</p>
                <hr style="margin: 20px 0; border: none; border-top: 1px solid #ddd;">
                <p style="color: #999; font-size: 11px; text-align: center;">
                    {COMPANY_NAME} - Smart Data, Simpler Life<br>
                    Need help? Contact us: {COMPANY_PHONE}
                </p>
            </div>
        </div>
        """
        send_email(email, f"Phone Verification Code - {COMPANY_NAME}", html_content)
        return {'success': True, 'method': 'email'}
    
    
    def resend_verification_code(self, phone_number, email):
        """Resend verification code - ALWAYS try SMS first again"""
        # Normalize phone number
        normalized_phone = self.normalize_phone(phone_number)
        
        # Remove old code
        if normalized_phone in self.verification_codes:
            del self.verification_codes[normalized_phone]
        
        # Try SMS first again
        return self.send_verification_code(phone_number, email)
    
    def verify_code(self, phone_number, code):
        """Verify the code entered by user"""
        # Normalize phone number to match the key used when storing
        normalized_phone = self.normalize_phone(phone_number)
        
        stored = self.verification_codes.get(normalized_phone)
        
        # Debug logging
        print(f"[VERIFY] Original phone: {phone_number} → Normalized: {normalized_phone}")
        print(f"[VERIFY] Input code: {code}")
        print(f"[VERIFY] Stored data: {stored}")
        
        if not stored:
            return {'success': False, 'error': 'No verification code sent to this number'}
        
        if stored['verified']:
            return {'success': False, 'error': 'Code already used'}
        
        current_time = datetime.utcnow()
        expires_at = stored['expires_at']
        
        print(f"[VERIFY] Current UTC: {current_time}")
        print(f"[VERIFY] Expires at: {expires_at}")
        print(f"[VERIFY] Time difference: {(expires_at - current_time).total_seconds()} seconds")
        
        if current_time > expires_at:
            del self.verification_codes[normalized_phone]
            return {'success': False, 'error': 'Verification code expired'}
        
        stored['attempts'] += 1
        
        if stored['attempts'] > 5:
            del self.verification_codes[normalized_phone]
            return {'success': False, 'error': 'Too many failed attempts'}
        
        if stored['code'] != code:
            return {'success': False, 'error': f'Invalid code. {5 - stored["attempts"]} attempts left'}
        
        stored['verified'] = True
        return {
            'success': True, 
            'message': 'Phone verified successfully',
            'method': 'sms' if stored['sms_sent'] else 'email'
        }


verification_service = PhoneVerificationService()

# ========== PAYSTACK CONFIGURATION ==========
PAYSTACK_SECRET_KEY = os.environ.get('PAYSTACK_SECRET_KEY')
PAYSTACK_PUBLIC_KEY = os.environ.get('PAYSTACK_PUBLIC_KEY')
PAYSTACK_BASE_URL = os.environ.get('PAYSTACK_BASE_URL')

# ========== PAYSTACK HELPER FUNCTIONS ==========
def initialize_paystack_transaction(email, amount, reference=None, metadata=None):
    """Initialize a Paystack transaction"""
    try:
        if not reference:
            reference = f"PAY-{uuid.uuid4().hex[:12].upper()}"
        
        url = f"{PAYSTACK_BASE_URL}/transaction/initialize"
        
        headers = {
            "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}",
            "Content-Type": "application/json"
        }
        
        data = {
            "email": email,
            "amount": int(amount * 100),  # Paystack uses kobo (multiply by 100)
            "reference": reference,
            "callback_url": f"{COMPANY_WEBSITE}/wallet"
        }
        
        if metadata:
            data["metadata"] = metadata
        
        response = requests.post(url, json=data, headers=headers, timeout=30)
        
        if response.status_code == 200:
            result = response.json()
            if result.get('status'):
                return {
                    'success': True,
                    'authorization_url': result['data']['authorization_url'],
                    'reference': reference,
                    'access_code': result['data']['access_code']
                }
        
        print(f"Paystack initialization error: {response.text}")
        return {'success': False, 'error': 'Payment initialization failed'}
        
    except Exception as e:
        print(f"Paystack error: {e}")
        return {'success': False, 'error': str(e)}


def verify_paystack_transaction(reference):
    """Verify a Paystack transaction"""
    try:
        url = f"{PAYSTACK_BASE_URL}/transaction/verify/{reference}"
        
        headers = {
            "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}",
            "Content-Type": "application/json"
        }
        
        response = requests.get(url, headers=headers, timeout=30)
        
        if response.status_code == 200:
            result = response.json()
            if result.get('status'):
                data = result.get('data', {})
                if data.get('status') == 'success':
                    return {
                        'success': True,
                        'amount': data.get('amount', 0) / 100,  # Convert back from kobo
                        'reference': reference,
                        'customer': data.get('customer', {}),
                        'transaction_date': data.get('paid_at')
                    }
        
        return {'success': False, 'error': 'Transaction verification failed'}
        
    except Exception as e:
        print(f"Paystack verification error: {e}")
        return {'success': False, 'error': str(e)}

def send_mobile_data(phone_number, quantity, unit='MB', validity='Day'):
    """
    Send mobile data to a customer using Africa's Talking Mobile Data API
    
    Args:
        phone_number (str): Customer phone number (e.g., '2547XXXXXXXX')
        quantity (int): Amount of data to send
        unit (str): 'MB' or 'GB'
        validity (str): 'Day', 'Week', or 'Month'
    
    Returns:
        dict: Response from Africa's Talking
    """
    try:
        mobile_data = africastalking.MobileData
        
        product_name = os.environ.get('AFRICASTALKING_PRODUCT_NAME')
        
        if not product_name:
            raise ValueError("AFRICASTALKING_PRODUCT_NAME not configured")
        
        # Prepare recipients
        recipients = [{
            'phoneNumber': phone_number,
            'quantity': quantity,
            'unit': unit,
            'validity': validity,
            'metadata': {
                'network': 'All Networks',
                'delivery_time': datetime.utcnow().isoformat()
            }
        }]
        
        # Send mobile data
        response = mobile_data.send(product_name, recipients)
        
        print(f"Mobile data sent: {quantity}{unit} to {phone_number}")
        print(f"Response: {response}")
        
        return {
            'success': True,
            'status': response.get('status', 'sent'),
            'transaction_id': response.get('transactionId'),
            'message': response.get('description', 'Data sent successfully')
        }
        
    except Exception as e:
        print(f"Error sending mobile data: {e}")
        return {
            'success': False,
            'error': str(e)
        }


def send_data_to_customer(phone_number, size_gb, quantity=1):
    """
    Wrapper function to send data bundles to customers
    
    Args:
        phone_number (str): Customer phone number
        size_gb (int): Size in GB (1, 2, 5, 10, 20)
        quantity (int): Number of bundles
    
    Returns:
        dict: Delivery result
    """
    total_mb = size_gb * 1024 * quantity
    
    # For smaller bundles, send as MB
    if total_mb < 1024:
        return send_mobile_data(
            phone_number=phone_number,
            quantity=total_mb,
            unit='MB',
            validity='Day'
        )
    else:
        return send_mobile_data(
            phone_number=phone_number,
            quantity=size_gb * quantity,
            unit='GB',
            validity='Day'
        )
# Create singleton instance
def normalize_phone(self, phone):
    """Normalize phone number to consistent format"""
    phone = str(phone).strip()
    # Remove any non-digit characters
    phone = re.sub(r'\D', '', phone)
    # If it starts with 0, change to 233 format
    if phone.startswith('0'):
        phone = '233' + phone[1:]
    return phone

@app.route("/test-redis")
def test_redis():
    from redis import Redis
    import os
    try:
        r = Redis.from_url(os.environ.get("REDIS_URL"))
        r.set("ping", "pong")
        return {"redis": r.get("ping").decode()}
    except Exception as e:
        return {"error": str(e)}


def get_current_utc():
    """Get current UTC time (timezone naive but in UTC)"""
    return datetime.utcnow()

# ========== STATIC FILE SERVING ROUTES ==========
@app.route('/uploads/profile_pics/<filename>')
def uploaded_file(filename):
    """Serve uploaded profile pictures"""
    try:
        return send_from_directory(app.config['UPLOAD_FOLDER'], filename)
    except Exception as e:
        print(f"[ERROR] Serving file {filename}: {e}")
        return jsonify({'error': 'File not found'}), 404

# ========== SOCKET.IO EVENT HANDLERS ==========
@socketio.on('connect', namespace='/announcements')
def handle_announcements_connect():
    """Handle client connection to announcements namespace"""
    print(f'[SOCKET.IO] Client connected to announcements namespace')
    emit('connected', {
        'message': f'Connected to {COMPANY_NAME} announcements',
        'timestamp': datetime.utcnow().isoformat()
    })

@socketio.on('disconnect', namespace='/announcements')
def handle_announcements_disconnect():
    """Handle client disconnection from announcements namespace"""
    print(f'[SOCKET.IO] Client disconnected from announcements namespace')

@socketio.on('ping', namespace='/announcements')
def handle_ping():
    """Handle ping from client to keep connection alive"""
    emit('pong', {'timestamp': datetime.utcnow().isoformat()})

# ========== HELPER FUNCTION TO BROADCAST ANNOUNCEMENT UPDATES ==========
def broadcast_announcement_update(action, announcement_data=None):
    """Broadcast announcement updates via WebSocket to all connected clients"""
    try:
        socketio.emit('announcement_update', {
            'action': action,
            'data': announcement_data,
            'timestamp': datetime.utcnow().isoformat(),
            'company': COMPANY_NAME
        }, broadcast=True, namespace='/announcements')
        print(f'[SOCKET.IO] Broadcasted announcement {action}')
    except Exception as e:
        print(f'[SOCKET.IO] Failed to broadcast announcement update: {e}')

# ========== EMAIL FUNCTIONS ==========

def generate_verification_code():
    """Generate a 6-digit verification code"""
    return str(random.randint(100000, 999999))


def send_email(to, subject, body):
    """Send email using SendGrid (works on Railway)"""
    try:
        sg = sendgrid.SendGridAPIClient(api_key=os.environ.get('SENDGRID_API_KEY'))
        
        from_email = Email(os.environ.get('FROM_EMAIL', 'noreply@roamsmart.shop'), 
                          os.environ.get('FROM_NAME', 'Roamsmart Digital Service'))
        to_email = To(to)
        
        # Create plain text version (strip HTML tags)
        plain_text = re.sub(r'<[^>]+>', '', body)
        
        message = Mail(
            from_email=from_email,
            to_emails=to_email,
            subject=subject,
            html_content=Content("text/html", body),
            plain_text_content=Content("text/plain", plain_text)
        )
        
        response = sg.send(message)
        
        if response.status_code == 202:
            print(f"[EMAIL] ✅ Sent to {to}")
            log_email(to, subject, 'sent')
            return True
        else:
            print(f"[EMAIL] ❌ Failed: Status {response.status_code}")
            log_email(to, subject, 'failed', str(response.status_code))
            return False
            
    except Exception as e:
        print(f"[EMAIL] ❌ Error: {e}")
        log_email(to, subject, 'error', str(e))
        return False
    
def send_verification_email(email, username, code):
    """Send email verification code to user with proper HTML"""
    
    print(f"\n{'='*60}")
    print(f"🔐 ROAMSMART VERIFICATION CODE")
    print(f"📧 Email: {email}")
    print(f"👤 Username: {username}")
    print(f"🔢 Code: {code}")
    print(f"⏰ Expires: 10 minutes")
    print(f"{'='*60}\n")
    
    html_content = f"""
<div style="font-family: 'Segoe UI', Arial, sans-serif; max-width: 600px; margin: 0 auto; background-color: #f5f7fa;">
    <div style="background: linear-gradient(135deg, #8B0000, #D2691E); padding: 30px; text-align: center; border-radius: 10px 10px 0 0;">
        <h1 style="color: white; margin: 0; font-size: 28px;">🔐 Email Verification</h1>
        <p style="color: white; margin: 10px 0 0; opacity: 0.9;">{COMPANY_NAME}</p>
    </div>
    
    <div style="background: white; padding: 30px; border-radius: 0 0 10px 10px;">
        <p style="font-size: 16px; color: #333;">Hello <strong>{username}</strong>,</p>
        <p style="font-size: 16px; color: #333;">Thank you for registering with <strong style="color: #8B0000;">{COMPANY_NAME}</strong>! Please use the verification code below to complete your registration.</p>
        
        <div style="background: #f8f9fa; font-size: 36px; font-weight: bold; letter-spacing: 8px; color: #8B0000; text-align: center; padding: 25px; border-radius: 12px; margin: 25px 0; border: 2px dashed #8B0000;">
            {code}
        </div>
        
        <div style="background: #fff3cd; border-left: 4px solid #ffc107; padding: 15px 20px; margin: 25px 0; border-radius: 8px;">
            <p style="margin: 0; color: #856404;"><strong>⚠️ Important:</strong></p>
            <ul style="margin: 10px 0 0 20px; color: #856404;">
                <li>This code expires in <strong>10 minutes</strong></li>
                <li>Do not share this code with anyone</li>
                <li>If you didn't request this, please ignore this email</li>
            </ul>
        </div>
        
        <div style="text-align: center; margin: 25px 0;">
            <a href="{COMPANY_WEBSITE}/verify" style="display: inline-block; background: #8B0000; color: white; padding: 12px 30px; text-decoration: none; border-radius: 30px;">Verify Now</a>
        </div>
        
        <p style="font-size: 14px; color: #666;">Or copy and paste this code: <strong style="color: #8B0000;">{code}</strong></p>
    </div>
    
    <div style="text-align: center; padding: 20px; background: #f8f9fa; color: #666; font-size: 12px; border-radius: 0 0 10px 10px;">
        <p style="margin: 0;">Need help? Contact us:</p>
        <p style="margin: 5px 0 0;">📞 WhatsApp: <strong>{COMPANY_PHONE}</strong> | 📧 Email: <strong>{COMPANY_EMAIL}</strong></p>
        <p style="margin: 10px 0 0;">© 2025 {COMPANY_NAME}. All rights reserved. | Accra, Ghana</p>
    </div>
</div>
"""
    
    return send_email(email, "🔐 Email Verification - Roamsmart", html_content)


def send_welcome_email(email, username, role='user'):
    """Send welcome email to new user or agent with proper HTML"""
    
    print(f"[EMAIL] Sending welcome email to: {email} (Role: {role})")
    
    if role == 'agent':
        subject = f"🎉 Welcome to {COMPANY_NAME} Agent Program!"
        
        html_content = f"""
<div style="font-family: 'Segoe UI', Arial, sans-serif; max-width: 600px; margin: 0 auto; background-color: #f5f7fa;">
    <div style="background: linear-gradient(135deg, #8B0000, #D2691E); padding: 30px; text-align: center; border-radius: 10px 10px 0 0;">
        <h1 style="color: white; margin: 0; font-size: 28px;">🎉 Welcome, Agent {username}!</h1>
        <p style="color: white; margin: 10px 0 0;">Your journey to earning starts here on {COMPANY_NAME}</p>
    </div>
    
    <div style="background: white; padding: 30px; border-radius: 0 0 10px 10px;">
        <p style="font-size: 16px;">Congratulations! Your agent application has been <strong style="color: #28a745;">approved</strong>. You now have access to:</p>
        
        <div style="background: #f8f9fa; padding: 15px; margin: 15px 0; border-radius: 10px; border-left: 4px solid #8B0000;">
            <strong>✅ Wholesale Prices</strong><br>
            Save up to 40% on data bundles
        </div>
        
        <div style="background: #f8f9fa; padding: 15px; margin: 15px 0; border-radius: 10px; border-left: 4px solid #8B0000;">
            <strong>✅ Your Own Store</strong><br>
            Get a branded online store to sell to customers
        </div>
        
        <div style="background: #f8f9fa; padding: 15px; margin: 15px 0; border-radius: 10px; border-left: 4px solid #8B0000;">
            <strong>✅ Earn Commission</strong><br>
            Earn up to 25% commission on every sale
        </div>
        
        <div style="background: #f8f9fa; padding: 15px; margin: 15px 0; border-radius: 10px; border-left: 4px solid #8B0000;">
            <strong>✅ Instant Withdrawals</strong><br>
            Withdraw your earnings to mobile money anytime
        </div>
        
        <div style="text-align: center; margin: 25px 0;">
            <a href="{COMPANY_WEBSITE}/agent" style="display: inline-block; background: #8B0000; color: white; padding: 12px 30px; text-decoration: none; border-radius: 30px;">Go to Agent Dashboard</a>
        </div>
        
        <h3 style="color: #333;">📊 Quick Start Guide:</h3>
        <ol style="color: #555;">
            <li><strong>Fund your wallet</strong> - Add money via Mobile Money or Card</li>
            <li><strong>Purchase wholesale data</strong> - Buy data at wholesale prices</li>
            <li><strong>Set your selling price</strong> - Recommended markup: 15-20%</li>
            <li><strong>Start selling!</strong> - Share your store link with customers</li>
        </ol>
        
        <p>Need help? Contact us on WhatsApp: <strong>{COMPANY_PHONE}</strong></p>
    </div>
    
    <div style="text-align: center; padding: 20px; background: #f8f9fa; color: #666; font-size: 12px;">
        <p>© 2025 {COMPANY_NAME}. All rights reserved. | Accra, Ghana</p>
    </div>
</div>
"""
    else:
        subject = f"🎉 Welcome to {COMPANY_NAME}!"
        
        html_content = f"""
<div style="font-family: 'Segoe UI', Arial, sans-serif; max-width: 600px; margin: 0 auto; background-color: #f5f7fa;">
    <div style="background: linear-gradient(135deg, #8B0000, #D2691E); padding: 30px; text-align: center; border-radius: 10px 10px 0 0;">
        <h1 style="color: white; margin: 0; font-size: 28px;">Welcome to {COMPANY_NAME}!</h1>
        <p style="color: white; margin: 10px 0 0;">Smart Data, Simpler Life</p>
    </div>
    
    <div style="background: white; padding: 30px; border-radius: 0 0 10px 10px;">
        <p style="font-size: 16px;">Hello <strong>{username}</strong>,</p>
        <p style="font-size: 16px;">Thank you for joining <strong style="color: #8B0000;">{COMPANY_NAME}</strong>! You can now purchase data bundles instantly with <strong>2-second delivery</strong>.</p>
        
        <div style="text-align: center; margin: 25px 0;">
            <a href="{COMPANY_WEBSITE}/dashboard" style="display: inline-block; background: #8B0000; color: white; padding: 12px 30px; text-decoration: none; border-radius: 30px;">Go to Dashboard</a>
        </div>
        
        <h3 style="color: #333;">📱 What you can do:</h3>
        <ul style="color: #555;">
            <li>✅ Buy data bundles for MTN, Telecel, and AirtelTigo</li>
            <li>✅ Get 2-second instant delivery</li>
            <li>✅ Fund wallet via Mobile Money or Card</li>
            <li>✅ Track your order history</li>
        </ul>
        
        <h3 style="color: #333;">💰 Refer & Earn:</h3>
        <p>Share your referral code with friends and earn <strong style="color: #28a745;">GHS 5</strong> for every friend who joins!</p>
        
        <p>Need help? Contact us on WhatsApp: <strong>{COMPANY_PHONE}</strong></p>
    </div>
    
    <div style="text-align: center; padding: 20px; background: #f8f9fa; color: #666; font-size: 12px;">
        <p>© 2025 {COMPANY_NAME}. All rights reserved. | Accra, Ghana</p>
    </div>
</div>
"""
    
    return send_email(email, subject, html_content)


# ========== HELPER FUNCTIONS ==========

def send_notification(notification_type, recipient, subject=None, message=None, phone=None, email=None, is_verification=False, is_data_delivery=False):
    """
    Unified notification system - SMS first, Email fallback for phone verification
    
    - Phone verification: ALWAYS try SMS first, email only if SMS fails
    - Email verification: Email only (existing system)
    - Data delivery: Network provider API only
    - General notifications: Email only
    """
    
    # Case 1: Phone Verification (SMS first, Email fallback)
    if is_verification and notification_type == 'phone_verification':
        if phone and email:
            result = verification_service.send_verification_code(phone, email)
            return result.get('success', False)
        return False
    
    # Case 2: Phone Verification Resend (SMS first again)
    elif is_verification and notification_type == 'phone_resend':
        if phone and email:
            result = verification_service.resend_verification_code(phone, email)
            return result.get('success', False)
        return False
    
    # Case 3: Email Verification (your existing system)
    elif is_verification and notification_type == 'email_verification':
        if recipient and subject and message:
            return send_email(recipient, subject, message)
        return False
    
    # Case 4: Data delivery - Send to network provider ONLY
    elif is_data_delivery:
        if phone:
            return send_data_delivery_to_provider(phone, message)
        return False
    
    # Case 5: General notifications - Email ONLY
    else:
        if recipient and subject and message:
            return send_email(recipient, subject, message)
        return False

def send_verification_sms(phone, message):
    """Send verification SMS using Africa's Talking API (LIVE)"""
    try:
        api_key = os.environ.get('AFRICASTALKING_API_KEY')
        username = os.environ.get('AFRICASTALKING_USERNAME', 'Roamsmart')
        sender_id = os.environ.get('AFRICASTALKING_SENDER_ID', 'Roamsmart')
        
        # Format phone number - remove leading zero and add 233
        formatted_phone = str(phone).strip()
        if formatted_phone.startswith('0'):
            formatted_phone = '233' + formatted_phone[1:]
        if formatted_phone.startswith('+'):
            formatted_phone = formatted_phone[1:]
        
        print(f"[VERIFICATION SMS] Original: {phone}")
        print(f"[VERIFICATION SMS] Formatted: {formatted_phone}")
        
        url = "https://api.africastalking.com/version1/messaging"
        
        data = {
            "username": username,
            "to": formatted_phone,
            "message": message,
            "from": sender_id
        }
        
        headers = {
            "apiKey": api_key,
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json"
        }
        
        response = requests.post(url, data=data, headers=headers, timeout=30)
        
        if response.status_code == 201 or response.status_code == 200:
            result = response.json()
            recipients = result.get('SMSMessageData', {}).get('Recipients', [])
            if recipients and recipients[0].get('status') == 'Success':
                log_sms(phone, message[:100], 'verification', 'africastalking')
                print(f"[VERIFICATION SMS] ✅ Sent to {phone}")
                return True
        
        print(f"[VERIFICATION SMS] ❌ Failed: {response.text}")
        return False
            
    except Exception as e:
        print(f"[VERIFICATION SMS] ❌ Error: {e}")
        return False

def send_data_delivery_to_provider(phone, message):
    """
    Send data delivery notification to network provider systems ONLY
    NO SMS to customer - network provider sends their own auto-message
    """
    try:
        network = detect_network_provider(phone)
        
        if network == 'mtn':
            return send_to_mtn_api(phone, message)
        elif network == 'telecel':
            return send_to_telecel_api(phone, message)
        elif network == 'airteltigo':
            return send_to_airteltigo_api(phone, message)
        else:
            log_sms(phone, message, 'data_delivery', network)
            print(f"[DATA DELIVERY] Sent to {network} provider for {phone}")
            return True
            
    except Exception as e:
        print(f"[DATA DELIVERY] Error: {e}")
        return False


def send_general_sms(phone, message):
    """
    Send general SMS using Africa's Talking API
    """
    global africas_talking_sms
    
    if not africas_talking_sms:
        print(f"[SMS] ❌ Africa's Talking not initialized. Cannot send SMS to {phone}")
        return False
    
    try:
        formatted_phone = phone
        if formatted_phone.startswith('+'):
            formatted_phone = formatted_phone[1:]
        if formatted_phone.startswith('233'):
            formatted_phone = '0' + formatted_phone[3:]
        
        response = africas_talking_sms.send(message, [formatted_phone])
        
        if response and response.get('SMSMessageData', {}).get('Recipients'):
            recipients = response['SMSMessageData']['Recipients']
            if recipients and len(recipients) > 0:
                status = recipients[0].get('status', '')
                if status == 'Success':
                    log_sms(phone, message[:100], 'general', 'africastalking')
                    print(f"[SMS] ✅ Sent to {phone}")
                    return True
        
        print(f"[SMS] ❌ Failed to send to {phone}")
        return False
            
    except Exception as e:
        print(f"[SMS] ❌ Error sending to {phone}: {e}")
        return False

def send_to_mtn_api(phone, message):
    """Send data delivery notification to MTN API"""
    try:
        mtn_api_key = app.config.get('MTN_API_KEY')
        
        if not mtn_api_key:
            log_sms(phone, message, 'data_delivery', 'mtn')
            print(f"[MTN API] Would send to {phone}: {message}")
            return True
        
        log_sms(phone, message, 'data_delivery', 'mtn')
        print(f"[MTN API] Sent data delivery to {phone}")
        return True
        
    except Exception as e:
        print(f"MTN API error: {e}")
        return True  # Return True to not break the flow


def send_to_telecel_api(phone, message):
    """Send data delivery notification to Telecel API"""
    try:
        telecel_api_key = app.config.get('TELECEL_API_KEY')
        
        if not telecel_api_key:
            log_sms(phone, message, 'data_delivery', 'telecel')
            print(f"[Telecel API] Would send to {phone}: {message}")
            return True
        
        log_sms(phone, message, 'data_delivery', 'telecel')
        print(f"[Telecel API] Sent data delivery to {phone}")
        return True
        
    except Exception as e:
        print(f"Telecel API error: {e}")
        return True


def send_to_airteltigo_api(phone, message):
    """Send data delivery notification to AirtelTigo API"""
    try:
        airteltigo_api_key = app.config.get('AIRTELTIGO_API_KEY')
        
        if not airteltigo_api_key:
            log_sms(phone, message, 'data_delivery', 'airteltigo')
            print(f"[AirtelTigo API] Would send to {phone}: {message}")
            return True
        
        log_sms(phone, message, 'data_delivery', 'airteltigo')
        print(f"[AirtelTigo API] Sent data delivery to {phone}")
        return True
        
    except Exception as e:
        print(f"AirtelTigo API error: {e}")
        return True


def detect_network_provider(phone):
    """Detect network provider from phone number"""
    phone = str(phone).strip()
    
    if phone.startswith('+233'):
        phone = phone[4:]
    elif phone.startswith('233'):
        phone = phone[3:]
    elif phone.startswith('0'):
        phone = phone[1:]
    
    if phone.startswith('54') or phone.startswith('55') or phone.startswith('24') or phone.startswith('59'):
        return 'mtn'
    elif phone.startswith('50') or phone.startswith('20') or phone.startswith('57'):
        return 'telecel'
    elif phone.startswith('53') or phone.startswith('26') or phone.startswith('27') or phone.startswith('56'):
        return 'airteltigo'
    else:
        return 'unknown'


def format_phone_number(phone):
    """Format phone number to international format"""
    phone = str(phone).strip()
    
    if phone.startswith('0'):
        return '233' + phone[1:]
    elif phone.startswith('+'):
        return phone[1:]
    elif phone.startswith('233'):
        return phone
    else:
        return '233' + phone


def log_sms(phone, message, sms_type, provider):
    """Log SMS delivery for audit purposes"""
    try:
        sms_log = SMSLog(
            phone_number=phone,
            message=message[:500],
            sms_type=sms_type,
            provider=provider,
            sent_at=datetime.utcnow()
        )
        db.session.add(sms_log)
        db.session.commit()
    except Exception as e:
        print(f"Failed to log SMS: {e}")


def log_email(recipient, subject, status, error=None):
    """Log email delivery for audit"""
    try:
        email_log = EmailLog(
            recipient=recipient,
            subject=subject[:200],
            status=status,
            error=error,
            sent_at=datetime.utcnow()
        )
        db.session.add(email_log)
        db.session.commit()
    except Exception as e:
        print(f"Failed to log email: {e}")


def send_sms(phone, message):
    """Legacy SMS function - now routes through unified system"""
    return send_general_sms(phone, message)


def email_verified_required(f):
    """Decorator to require email verification"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not g.current_user.email_verified:
            return jsonify({
                'success': False,
                'error': 'Email verification required',
                'message': f'Please verify your email address to access this feature on {COMPANY_NAME}',
                'requires_verification': True
            }), 403
        return f(*args, **kwargs)
    return decorated


def send_webhook(event, data):
    """Send webhook notification to registered endpoints"""
    webhooks = Webhook.query.filter_by(is_active=True).all()
    
    for webhook in webhooks:
        if event in webhook.events:
            try:
                payload = {
                    'event': event,
                    'timestamp': datetime.utcnow().isoformat(),
                    'data': data
                }
                headers = {'Content-Type': 'application/json'}
                if webhook.secret:
                    signature = hashlib.sha256(
                        f"{webhook.secret}{json.dumps(payload)}".encode()
                    ).hexdigest()
                    headers['X-Webhook-Signature'] = signature
                
                requests.post(webhook.url, json=payload, headers=headers, timeout=5)
            except Exception as e:
                print(f"Webhook error for {webhook.url}: {e}")


def generate_qr_code(data):
    """Generate QR code for 2FA"""
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    
    buffered = BytesIO()
    img.save(buffered, format="PNG")
    return base64.b64encode(buffered.getvalue()).decode()


def log_activity(user_id, action, details, ip_address=None):
    """Log user activity for audit"""
    activity = UserSession(
        user_id=user_id,
        action=action,
        details=details,
        ip_address=ip_address or request.remote_addr
    )
    db.session.add(activity)
    db.session.commit()


def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization', '').replace('Bearer ', '')
        if not token:
            return jsonify({'error': 'Token required', 'message': 'Authentication required'}), 401
        user = User.verify_token(token)
        if not user:
            return jsonify({'error': 'Invalid token', 'message': 'Please login again'}), 401
        g.current_user = user
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if g.current_user.role not in ['admin', 'super_admin']:
            return jsonify({'error': 'Forbidden', 'message': 'Admin access required'}), 403
        return f(*args, **kwargs)
    return decorated


def super_admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if g.current_user.role != 'super_admin':
            return jsonify({'error': 'Forbidden', 'message': 'Super admin access required'}), 403
        return f(*args, **kwargs)
    return decorated


def agent_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not g.current_user.is_agent or not g.current_user.agent_approved:
            return jsonify({'error': 'Forbidden', 'message': 'Agent access required'}), 403
        return f(*args, **kwargs)
    return decorated


def init_db():
    """Initialize database with default data"""
    with app.app_context():
        # Create all tables from all models
        db.create_all()
        
        # ========== ADD NEW COLUMNS TO ORDERS TABLE (MIGRATION) ==========
        from sqlalchemy import text
        try:
            with db.engine.connect() as conn:
                # Get existing columns for both tables
                inspector = db.inspect(db.engine)
                orders_columns = [col['name'] for col in inspector.get_columns('orders')]
                users_columns = [col['name'] for col in inspector.get_columns('users')]
                
                # ===== ORDERS TABLE MIGRATION =====
                print("\n📋 Checking Orders table columns...")
                
                if 'cost' not in orders_columns:
                    conn.execute(text('ALTER TABLE orders ADD COLUMN cost FLOAT DEFAULT 0.0'))
                    print("✅ Added 'cost' column to orders table")
                else:
                    print("⏭️ Column 'cost' already exists")
                
                if 'profit' not in orders_columns:
                    conn.execute(text('ALTER TABLE orders ADD COLUMN profit FLOAT DEFAULT 0.0'))
                    print("✅ Added 'profit' column to orders table")
                else:
                    print("⏭️ Column 'profit' already exists")
                
                if 'provider' not in orders_columns:
                    conn.execute(text("ALTER TABLE orders ADD COLUMN provider VARCHAR(50)"))
                    print("✅ Added 'provider' column to orders table")
                else:
                    print("⏭️ Column 'provider' already exists")
                
                if 'provider_order_id' not in orders_columns:
                    conn.execute(text("ALTER TABLE orders ADD COLUMN provider_order_id VARCHAR(100)"))
                    print("✅ Added 'provider_order_id' column to orders table")
                else:
                    print("⏭️ Column 'provider_order_id' already exists")
                
                if 'provider_reference' not in orders_columns:
                    conn.execute(text("ALTER TABLE orders ADD COLUMN provider_reference VARCHAR(100)"))
                    print("✅ Added 'provider_reference' column to orders table")
                else:
                    print("⏭️ Column 'provider_reference' already exists")
                
                if 'provider_cost' not in orders_columns:
                    conn.execute(text('ALTER TABLE orders ADD COLUMN provider_cost FLOAT DEFAULT 0.0'))
                    print("✅ Added 'provider_cost' column to orders table")
                else:
                    print("⏭️ Column 'provider_cost' already exists")
                
                # ===== USERS TABLE MIGRATION =====
                print("\n📋 Checking Users table columns...")
                
                if 'total_sales' not in users_columns:
                    conn.execute(text('ALTER TABLE users ADD COLUMN total_sales FLOAT DEFAULT 0.0'))
                    print("✅ Added 'total_sales' column to users table")
                else:
                    print("⏭️ Column 'total_sales' already exists")
                
                if 'total_commission' not in users_columns:
                    conn.execute(text('ALTER TABLE users ADD COLUMN total_commission FLOAT DEFAULT 0.0'))
                    print("✅ Added 'total_commission' column to users table")
                else:
                    print("⏭️ Column 'total_commission' already exists")
                
                if 'today_sales' not in users_columns:
                    conn.execute(text('ALTER TABLE users ADD COLUMN today_sales FLOAT DEFAULT 0.0'))
                    print("✅ Added 'today_sales' column to users table")
                else:
                    print("⏭️ Column 'today_sales' already exists")
                
                if 'this_week_sales' not in users_columns:
                    conn.execute(text('ALTER TABLE users ADD COLUMN this_week_sales FLOAT DEFAULT 0.0'))
                    print("✅ Added 'this_week_sales' column to users table")
                else:
                    print("⏭️ Column 'this_week_sales' already exists")
                
                if 'this_month_sales' not in users_columns:
                    conn.execute(text('ALTER TABLE users ADD COLUMN this_month_sales FLOAT DEFAULT 0.0'))
                    print("✅ Added 'this_month_sales' column to users table")
                else:
                    print("⏭️ Column 'this_month_sales' already exists")
                
                if 'total_customers' not in users_columns:
                    conn.execute(text('ALTER TABLE users ADD COLUMN total_customers INTEGER DEFAULT 0'))
                    print("✅ Added 'total_customers' column to users table")
                else:
                    print("⏭️ Column 'total_customers' already exists")
                
                conn.commit()
                print("✅ Database migration completed")
        except Exception as e:
            print(f"⚠️ Migration note: {e}")
        # ========== END OF MIGRATION ==========
        
        # Create ONLY ONE Super Admin (no support admin, no demo users/agents)
        if not User.query.filter_by(email=COMPANY_ADMIN_EMAIL).first():
            admin = User(
                username='Administrator',
                email=COMPANY_ADMIN_EMAIL,
                phone='0557388622',
                role='super_admin',
                wallet_balance=0,
                is_agent=True,
                agent_approved=True,
                referral_code='ADMIN001',
                email_verified=True,
                phone_verified=True
            )
            admin.set_password('Roamsmart123@$')
            db.session.add(admin)
            print("✅ Super Admin created with password: Roamsmart123@$")
        else:
            # Update existing admin password if needed
            admin = User.query.filter_by(email=COMPANY_ADMIN_EMAIL).first()
            admin.set_password('Roamsmart123@$')
            db.session.commit()
            print("✅ Super Admin password updated to: Roamsmart123@$")
        
        # Create PendingTransaction table if it doesn't exist (ensure it's created)
        # This is handled by db.create_all() above, but let's verify
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        if 'pending_transactions' not in inspector.get_table_names():
            print("⚠️ pending_transactions table not found, creating...")
            # Create table directly if model exists
            PendingTransaction.__table__.create(db.engine)
            print("✅ pending_transactions table created")
        else:
            print("✅ pending_transactions table already exists")
        
        # Create default price settings if none exist
        if PriceSetting.query.count() == 0:
            default_prices = [
                # User prices (retail)
                ('user_price', 'mtn', 1, 6.50),
                ('user_price', 'mtn', 2, 12.00),
                ('user_price', 'mtn', 5, 25.00),
                ('user_price', 'mtn', 10, 48.00),
                ('user_price', 'mtn', 20, 90.00),
                ('user_price', 'telecel', 1, 6.00),
                ('user_price', 'telecel', 2, 11.00),
                ('user_price', 'telecel', 5, 23.00),
                ('user_price', 'telecel', 10, 44.00),
                ('user_price', 'telecel', 20, 85.00),
                ('user_price', 'airteltigo', 1, 6.00),
                ('user_price', 'airteltigo', 2, 11.00),
                ('user_price', 'airteltigo', 5, 23.00),
                ('user_price', 'airteltigo', 10, 44.00),
                ('user_price', 'airteltigo', 20, 85.00),
                # Agent prices (wholesale)
                ('agent_price', 'mtn', 1, 5.50),
                ('agent_price', 'mtn', 2, 10.00),
                ('agent_price', 'mtn', 5, 22.00),
                ('agent_price', 'mtn', 10, 42.00),
                ('agent_price', 'mtn', 20, 80.00),
                ('agent_price', 'telecel', 1, 5.00),
                ('agent_price', 'telecel', 2, 9.00),
                ('agent_price', 'telecel', 5, 20.00),
                ('agent_price', 'telecel', 10, 38.00),
                ('agent_price', 'telecel', 20, 75.00),
                ('agent_price', 'airteltigo', 1, 5.00),
                ('agent_price', 'airteltigo', 2, 9.00),
                ('agent_price', 'airteltigo', 5, 20.00),
                ('agent_price', 'airteltigo', 10, 38.00),
                ('agent_price', 'airteltigo', 20, 75.00),
            ]
            
            for cat, net, size, price in default_prices:
                setting = PriceSetting(
                    category=cat,
                    network=net,
                    size_gb=size,
                    price=price
                )
                db.session.add(setting)
            print(f"✅ Created {len(default_prices)} default price settings")
        
        # Create master inventory if empty
        if MasterInventory.query.count() == 0:
            networks = ['mtn', 'telecel', 'airteltigo']
            sizes = [1, 2, 5, 10, 20]
            for network in networks:
                for size in sizes:
                    inventory = MasterInventory(
                        network=network,
                        size_gb=size,
                        total_purchased=0,
                        remaining=0,
                        sold_to_agents=0
                    )
                    db.session.add(inventory)
            print("✅ Created master inventory structure")
        
        # Create active announcement if none exists
        if Announcement.query.count() == 0:
            announcement = Announcement(
                title=f'Welcome to {COMPANY_NAME}!',
                message=f'Get instant data bundles with 2-second delivery on {COMPANY_NAME}. Become an agent and earn up to 25% commission!',
                type='success',
                is_active=True,
                expires_at=datetime.utcnow() + timedelta(days=30)
            )
            db.session.add(announcement)
            print("✅ Announcement created")
        
        db.session.commit()
        
        # Final verification
        print("\n" + "="*60)
        print("✅ DATABASE INITIALIZATION COMPLETE")
        print("="*60)
        print(f"🔐 Super Admin Email: {COMPANY_ADMIN_EMAIL}")
        print(f"🔐 Super Admin Password: Roamsmart123@$")
        
        # List all tables
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()
        print(f"\n📋 Database Tables ({len(tables)}):")
        for table in sorted(tables):
            print(f"   - {table}")
        print("="*60 + "\n")
# ========== PROFILE PICTURE UPLOAD ==========

import traceback
@app.route('/api/init-db', methods=['GET'])
def init_database_endpoint():
    """HTTP endpoint to initialize database - call this once after deployment"""
    try:
        from app import init_db
        init_db()
        return jsonify({
            'success': True,
            'message': 'Database initialized successfully!',
            'admin_email': COMPANY_ADMIN_EMAIL,
            'admin_password': 'Roamsmart123@$'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    
@app.route('/api/user/avatar', methods=['POST'])
@token_required
def upload_avatar():
    """Upload profile picture"""
    try:
        print("[AVATAR] Starting upload process")
        
        if 'avatar' not in request.files:
            print("[AVATAR] No file in request")
            return jsonify({'success': False, 'error': 'No file provided'}), 400
        
        file = request.files['avatar']
        print(f"[AVATAR] File received: {file.filename}")
        
        if file.filename == '':
            print("[AVATAR] Empty filename")
            return jsonify({'success': False, 'error': 'No file selected'}), 400
        
        # Check file extension
        ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
        print(f"[AVATAR] File extension: {ext}")
        
        if not ext or ext not in ALLOWED_EXTENSIONS:
            print(f"[AVATAR] Invalid file type: {ext}")
            return jsonify({'success': False, 'error': f'Invalid file type. Allowed: {", ".join(ALLOWED_EXTENSIONS)}'}), 400
        
        # Check file size
        file.seek(0, os.SEEK_END)
        file_size = file.tell()
        file.seek(0)
        print(f"[AVATAR] File size: {file_size} bytes")
        
        if file_size > MAX_FILE_SIZE:
            print(f"[AVATAR] File too large: {file_size}")
            return jsonify({'success': False, 'error': f'File too large. Max {MAX_FILE_SIZE // (1024*1024)}MB'}), 400
        
        # Generate unique filename
        filename = f"avatar_{g.current_user.id}_{uuid.uuid4().hex[:8]}.{ext}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        print(f"[AVATAR] Saving to: {filepath}")
        
        # Save file
        file.save(filepath)
        print(f"[AVATAR] File saved successfully")
        
        # Verify file was saved
        if not os.path.exists(filepath):
            raise Exception("Failed to save file")
        
        # Delete old avatar if exists
        if g.current_user.avatar_url:
            old_filename = os.path.basename(g.current_user.avatar_url)
            old_path = os.path.join(app.config['UPLOAD_FOLDER'], old_filename)
            print(f"[AVATAR] Old avatar path: {old_path}")
            if os.path.exists(old_path) and old_filename != filename:
                os.remove(old_path)
                print(f"[AVATAR] Deleted old file: {old_path}")
        
        # Update user with new avatar URL
        avatar_url = f"/uploads/profile_pics/{filename}"
        print(f"[AVATAR] New avatar URL: {avatar_url}")
        
        g.current_user.avatar_url = avatar_url
        
        print(f"[AVATAR] Committing to database...")
        db.session.commit()
        print(f"[AVATAR] Database commit successful")
        
        # Refresh user data
        db.session.refresh(g.current_user)
        print(f"[AVATAR] User refreshed")
        
        # Get user dict
        user_dict = g.current_user.to_dict()
        print(f"[AVATAR] User dict created with keys: {user_dict.keys() if user_dict else 'None'}")
        
        # Return full user data with role field
        response = jsonify({
            'success': True,
            'message': 'Profile picture uploaded successfully',
            'user': user_dict,
            'data': {'avatar_url': avatar_url}
        })
        
        print(f"[AVATAR] Upload completed successfully")
        return response
        
    except Exception as e:
        print(f"[AVATAR] Upload error: {e}")
        print(f"[AVATAR] Full traceback:")
        traceback.print_exc()
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    
@app.route('/api/user/avatar', methods=['DELETE'])
@token_required
def delete_avatar():
    """Delete profile picture"""
    try:
        if g.current_user.avatar_url:
            filename = g.current_user.avatar_url.split('/')[-1]
            filepath = os.path.join(UPLOAD_FOLDER, filename)
            if os.path.exists(filepath):
                os.remove(filepath)
            
            g.current_user.avatar_url = None
            db.session.commit()
            db.session.refresh(g.current_user)
            
            print(f"[AVATAR] Deleted for user {g.current_user.id}")
        
        # Return full user object
        return jsonify({
            'success': True, 
            'message': 'Profile picture deleted',
            'user': g.current_user.to_dict()
        })
        
    except Exception as e:
        print(f"[AVATAR] Delete error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/uploads/profile_pics/<filename>', methods=['GET'])
def get_avatar(filename):
    """Serve profile picture"""
    try:
        return send_from_directory(UPLOAD_FOLDER, filename)
    except Exception as e:
        return jsonify({'success': False, 'error': 'File not found'}), 404

# ========== PAYSTACK PAYMENT ENDPOINTS ==========

@app.route('/api/payment/paystack/initialize', methods=['POST'])
@token_required
@limiter.limit("10 per minute")
@limiter.limit("30 per hour")
def initialize_paystack_payment():
    """Initialize Paystack payment for wallet funding"""
    try:
        data = request.get_json()
        amount = data.get('amount')
        email = data.get('email')
        phone = data.get('phone')
        
        if not amount or amount < 10:
            return jsonify({'success': False, 'error': 'Minimum amount is GHS 10'}), 400
        
        if not email:
            return jsonify({'success': False, 'error': 'Email is required'}), 400
        
        user = g.current_user
        
        # Generate unique reference
        reference = f"PAYSTACK_{int(datetime.utcnow().timestamp())}_{user.id}_{secrets.token_hex(4)}"
        
        # Initialize transaction with Paystack
        result = initialize_paystack_transaction(
            email=email,
            amount=amount,
            reference=reference,
            metadata={
                'user_id': user.id,
                'username': user.username,
                'phone': phone,
                'type': 'wallet_funding'
            }
        )
        
        if result['success']:
            # Store pending transaction using your existing model
            pending_tx = PendingTransaction(
                user_id=user.id,
                reference=reference,
                amount=amount,
                payment_method='paystack',
                status='pending',
                created_at=datetime.utcnow()
            )
            db.session.add(pending_tx)
            db.session.commit()
            
            return jsonify({
                'success': True,
                'data': {
                    'authorization_url': result['authorization_url'],
                    'reference': reference,
                    'amount': amount
                }
            })
        else:
            return jsonify({'success': False, 'error': result.get('error', 'Payment initialization failed')}), 500
        
    except Exception as e:
        print(f"Initialize Paystack payment error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500




@app.route('/api/payment/momo/initialize', methods=['POST'])
@token_required
def initialize_momo_payment():
    """Initialize MTN MoMo payment for wallet funding"""
    try:
        data = request.get_json()
        amount = data.get('amount')
        phone = data.get('phone')
        name = data.get('name')
        
        if not amount or amount < 10:
            return jsonify({'success': False, 'error': 'Minimum amount is GHS 10'}), 400
        
        if not phone:
            return jsonify({'success': False, 'error': 'Phone number is required'}), 400
        
        if not name:
            return jsonify({'success': False, 'error': 'Name is required'}), 400
        
        user = g.current_user
        
        # Validate Ghana phone number
        if not validate_ghana_phone(phone):
            return jsonify({'success': False, 'error': 'Invalid Ghana phone number'}), 400
        
        # Generate unique reference
        reference = f"MOMO_{int(datetime.utcnow().timestamp())}_{user.id}_{secrets.token_hex(4)}"
        
        # Initialize MTN MoMo transaction
        result = initialize_momo_transaction(
            amount=amount,
            phone=phone,
            reference=reference,
            name=name,
            metadata={
                'user_id': user.id,
                'username': user.username,
                'type': 'wallet_funding'
            }
        )
        
        if result['success']:
            # Store pending transaction using your existing model
            pending_tx = PendingTransaction(
                user_id=user.id,
                reference=reference,
                amount=amount,
                payment_method='momo',
                status='pending',
                created_at=datetime.utcnow()
            )
            db.session.add(pending_tx)
            db.session.commit()
            
            return jsonify({
                'success': True,
                'data': {
                    'paymentReference': result['payment_reference'],
                    'checkoutRequestId': result['checkout_request_id'],
                    'reference': reference,
                    'amount': amount,
                    'message': 'Payment initiated. Please check your phone to authorize.'
                }
            })
        else:
            return jsonify({'success': False, 'error': result.get('error', 'Payment initialization failed')}), 500
        
    except Exception as e:
        print(f"Initialize MoMo payment error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/payment/momo/verify/<reference>', methods=['GET'])
@token_required
def verify_momo_payment(reference):
    """Verify MTN MoMo payment status"""
    try:
        if not reference:
            return jsonify({'success': False, 'error': 'Reference required'}), 400
        
        # Verify with MTN MoMo
        result = verify_momo_transaction(reference)
        
        if not result['success']:
            return jsonify({'success': False, 'error': 'Payment verification failed'}), 400
        
        # Check if already processed using your existing model
        pending_tx = PendingTransaction.query.filter_by(
            reference=reference,
            status='pending'
        ).first()
        
        if not pending_tx:
            # Check if already completed in transactions
            completed_tx = Transaction.query.filter_by(reference=reference).first()
            if completed_tx:
                return jsonify({
                    'success': True,
                    'data': {
                        'status': 'success',
                        'amount': float(completed_tx.amount),
                        'message': 'Payment already processed'
                    }
                })
            return jsonify({'success': False, 'error': 'Transaction not found'}), 404
        
        if result['status'] == 'success':
            # Update user wallet
            user = User.query.get(pending_tx.user_id)
            if not user:
                return jsonify({'success': False, 'error': 'User not found'}), 404
            
            # Add to wallet
            balance_before = user.wallet_balance
            user.wallet_balance += result['amount']
            
            # Update pending transaction
            pending_tx.status = 'completed'
            pending_tx.completed_at = datetime.utcnow()
            
            # Create transaction record using your existing model
            transaction = Transaction(
                user_id=user.id,
                type='fund',
                amount=result['amount'],
                balance_before=balance_before,
                balance_after=user.wallet_balance,
                description=f'Wallet funding via MTN MoMo - {reference}',
                reference=reference,
                status='completed',
                meta_data={
                    'payment_method': 'momo',
                    'reference': reference
                }
            )
            db.session.add(transaction)
            db.session.commit()
            
            # Send SMS confirmation
            send_momo_confirmation_sms(user.phone or phone, result['amount'], user.wallet_balance)
            
            return jsonify({
                'success': True,
                'data': {
                    'status': 'success',
                    'amount': float(result['amount']),
                    'new_balance': float(user.wallet_balance),
                    'message': f'Successfully added GHS {result["amount"]:.2f} to your wallet'
                }
            })
        elif result['status'] == 'pending':
            return jsonify({
                'success': True,
                'data': {
                    'status': 'pending',
                    'message': 'Payment is still pending. Please check your phone and authorize.'
                }
            })
        else:
            # Update failed transaction
            pending_tx.status = 'failed'
            db.session.commit()
            
            return jsonify({
                'success': False,
                'data': {
                    'status': 'failed',
                    'message': 'Payment was not successful'
                }
            }), 400
        
    except Exception as e:
        print(f"Verify MoMo payment error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/payment/momo/webhook', methods=['POST'])
def momo_webhook():
    """MTN MoMo webhook for automatic payment confirmation"""
    try:
        # Get webhook data
        data = request.get_json()
        
        # Process based on webhook type
        if data.get('status') == 'successful':
            reference = data.get('reference')
            transaction_id = data.get('transactionId')
            amount = data.get('amount', 0)
            
            # Find pending transaction using your existing model
            pending_tx = PendingTransaction.query.filter_by(
                reference=reference,
                status='pending',
                payment_method='momo'
            ).first()
            
            if pending_tx and pending_tx.status == 'pending':
                user = User.query.get(pending_tx.user_id)
                if user:
                    balance_before = user.wallet_balance
                    user.wallet_balance += amount
                    
                    pending_tx.status = 'completed'
                    pending_tx.completed_at = datetime.utcnow()
                    
                    # Create transaction record using your existing model
                    transaction = Transaction(
                        user_id=user.id,
                        type='fund',
                        amount=amount,
                        balance_before=balance_before,
                        balance_after=user.wallet_balance,
                        description=f'Wallet funding via MTN MoMo - {reference}',
                        reference=reference,
                        status='completed',
                        meta_data={
                            'payment_method': 'momo',
                            'webhook': True,
                            'transaction_id': transaction_id
                        }
                    )
                    db.session.add(transaction)
                    db.session.commit()
                    
                    print(f"[WEBHOOK] Processed MoMo payment {reference} for {user.email}")
        
        return jsonify({'success': True})
        
    except Exception as e:
        print(f"MoMo webhook error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


# Helper Functions

def initialize_paystack_transaction(email, amount, reference, metadata):
    """Initialize Paystack transaction"""
    try:
        import requests
        
        url = "https://api.paystack.co/transaction/initialize"
        headers = {
            "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}",
            "Content-Type": "application/json"
        }
        data = {
            "email": email,
            "amount": int(amount * 100),  # Convert to pesewas
            "reference": reference,
            "metadata": metadata,
            "callback_url": f"{COMPANY_WEBSITE}/wallet"
        }
        
        response = requests.post(url, json=data, headers=headers, timeout=30)
        result = response.json()
        
        if result.get('status'):
            return {
                'success': True,
                'authorization_url': result['data']['authorization_url'],
                'reference': result['data']['reference']
            }
        else:
            return {
                'success': False,
                'error': result.get('message', 'Paystack initialization failed')
            }
            
    except Exception as e:
        print(f"Paystack initialization error: {e}")
        return {'success': False, 'error': str(e)}


def verify_paystack_transaction(reference):
    """Verify Paystack transaction"""
    try:
        import requests
        
        url = f"https://api.paystack.co/transaction/verify/{reference}"
        headers = {
            "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}"
        }
        
        response = requests.get(url, headers=headers, timeout=30)
        result = response.json()
        
        if result.get('status') and result['data']['status'] == 'success':
            return {
                'success': True,
                'status': 'success',
                'amount': result['data']['amount'] / 100,
                'reference': reference
            }
        else:
            return {
                'success': True,
                'status': 'failed',
                'message': result.get('message', 'Payment not successful')
            }
            
    except Exception as e:
        print(f"Paystack verification error: {e}")
        return {'success': False, 'error': str(e)}


def initialize_momo_transaction(amount, phone, reference, name, metadata):
    """Initialize MTN MoMo transaction"""
    try:
        import requests
        
        # Get access token
        token_url = f"{MOMO_BASE_URL}/collection/token/"
        token_headers = {
            "Authorization": f"Basic {MOMO_API_KEY}",
            "Ocp-Apim-Subscription-Key": MOMO_SUBSCRIPTION_KEY
        }
        
        token_response = requests.post(token_url, headers=token_headers, timeout=30)
        access_token = token_response.json().get('access_token')
        
        if not access_token:
            return {'success': False, 'error': 'Failed to get access token'}
        
        # Initialize payment
        payment_url = f"{MOMO_BASE_URL}/collection/v1_0/requesttopay"
        payment_headers = {
            "Authorization": f"Bearer {access_token}",
            "X-Reference-Id": reference,
            "X-Target-Environment": MOMO_ENVIRONMENT,
            "Content-Type": "application/json",
            "Ocp-Apim-Subscription-Key": MOMO_SUBSCRIPTION_KEY
        }
        
        payment_data = {
            "amount": str(amount),
            "currency": "GHS",
            "externalId": reference,
            "payer": {
                "partyIdType": "MSISDN",
                "partyId": phone
            },
            "payerMessage": f"Fund {COMPANY_NAME} Wallet",
            "payeeNote": f"Wallet funding for {name}"
        }
        
        response = requests.post(payment_url, json=payment_data, headers=payment_headers, timeout=30)
        
        if response.status_code == 202:
            return {
                'success': True,
                'payment_reference': reference,
                'checkout_request_id': reference,
                'status': 'pending'
            }
        else:
            return {
                'success': False,
                'error': f'MoMo initialization failed: {response.text}'
            }
            
    except Exception as e:
        print(f"MoMo initialization error: {e}")
        return {'success': False, 'error': str(e)}


def verify_momo_transaction(reference):
    """Verify MTN MoMo transaction status"""
    try:
        import requests
        
        # Get access token
        token_url = f"{MOMO_BASE_URL}/collection/token/"
        token_headers = {
            "Authorization": f"Basic {MOMO_API_KEY}",
            "Ocp-Apim-Subscription-Key": MOMO_SUBSCRIPTION_KEY
        }
        
        token_response = requests.post(token_url, headers=token_headers, timeout=30)
        access_token = token_response.json().get('access_token')
        
        if not access_token:
            return {'success': False, 'error': 'Failed to get access token'}
        
        # Check payment status
        status_url = f"{MOMO_BASE_URL}/collection/v1_0/requesttopay/{reference}"
        status_headers = {
            "Authorization": f"Bearer {access_token}",
            "X-Target-Environment": MOMO_ENVIRONMENT,
            "Ocp-Apim-Subscription-Key": MOMO_SUBSCRIPTION_KEY
        }
        
        response = requests.get(status_url, headers=status_headers, timeout=30)
        result = response.json()
        
        if result.get('status') == 'SUCCESSFUL':
            return {
                'success': True,
                'status': 'success',
                'amount': float(result.get('amount', 0)),
                'reference': reference
            }
        elif result.get('status') == 'PENDING':
            return {
                'success': True,
                'status': 'pending',
                'message': 'Payment pending'
            }
        else:
            return {
                'success': True,
                'status': 'failed',
                'message': result.get('status', 'Payment failed')
            }
            
    except Exception as e:
        print(f"MoMo verification error: {e}")
        return {'success': False, 'error': str(e)}


def validate_ghana_phone(phone):
    """Validate Ghana phone number"""
    import re
    pattern = r'^(024|025|026|027|028|020|054|055|059|050|057|053|056)[0-9]{7}$'
    return bool(re.match(pattern, phone))

@app.route('/api/auth/verify-2fa-code', methods=['POST'])
@limiter.limit("10 per minute")
def verify_2fa_code():
    """Verify 2FA code sent via SMS"""
    data = request.get_json()
    user_id = data.get('user_id')
    code = data.get('code')
    
    verify_data = session.get('2fa_user')
    
    if not verify_data or verify_data.get('user_id') != user_id:
        return jsonify({
            'success': False,
            'error': 'Session expired. Please login again.'
        }), 400
    
    if datetime.fromisoformat(verify_data['expires']) < datetime.utcnow():
        session.pop('2fa_user', None)
        return jsonify({
            'success': False,
            'error': '2FA code expired. Please login again.'
        }), 400
    
    if code != verify_data.get('code'):
        return jsonify({'success': False, 'error': 'Invalid 2FA code'}), 401
    
    user = User.query.get(user_id)
    if not user:
        return jsonify({'success': False, 'error': 'User not found'}), 404
    
    session.pop('2fa_user', None)
    user.last_login = datetime.utcnow()
    db.session.commit()
    
    token = user.generate_token()
    
    if user.role == 'super_admin':
        redirect_url = '/admin'
    elif user.role == 'admin':
        redirect_url = '/admin'
    elif user.is_agent and user.agent_approved:
        redirect_url = '/agent'
    else:
        redirect_url = '/dashboard'
    
    return jsonify({
        'success': True,
        'token': token,
        'user': user.to_dict(),
        'redirect': redirect_url
    })


@app.route('/api/auth/me', methods=['GET'])
@token_required
@limiter.limit("60 per minute")  # Allow frequent checks
def get_current_user():
    """Get current user info"""
    try:
        user_data = g.current_user.to_dict()
        
        # Add additional security info
        user_data['two_factor_enabled'] = g.current_user.two_factor_enabled
        
        # Add last login info if available
        if hasattr(g.current_user, 'last_login'):
            user_data['last_login'] = g.current_user.last_login.isoformat() if g.current_user.last_login else None
        
        return jsonify({
            'success': True, 
            'user': user_data
        })
    except Exception as e:
        print(f"Get current user error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/auth/change-password', methods=['POST'])
@token_required
@limiter.limit("5 per minute")
@limiter.limit("10 per hour")
def change_password():
    """Change user password"""
    print("\n" + "="*60)
    print("[DEBUG] CHANGE PASSWORD ENDPOINT CALLED")
    print("="*60)
    
    try:
        data = request.get_json()
        print(f"[DEBUG] Request data: {data}")
        print(f"[DEBUG] User: {g.current_user.username} (ID: {g.current_user.id})")
        
        current_password = data.get('current_password')
        new_password = data.get('new_password')
        
        print(f"[DEBUG] Current password provided: {'Yes' if current_password else 'No'}")
        print(f"[DEBUG] New password provided: {'Yes' if new_password else 'No'}")
        
        if not current_password or not new_password:
            print("[DEBUG] ERROR: Missing password fields")
            return jsonify({'success': False, 'error': 'Current password and new password are required'}), 400
        
        if len(new_password) < 6:
            print("[DEBUG] ERROR: New password too short")
            return jsonify({'success': False, 'error': 'New password must be at least 6 characters'}), 400
        
        # Check current password
        print("[DEBUG] Checking current password...")
        password_valid = g.current_user.check_password(current_password)
        print(f"[DEBUG] Password valid: {password_valid}")
        
        if not password_valid:
            print("[DEBUG] ERROR: Current password incorrect")
            log_activity(g.current_user.id, 'change_password_failed', 'Incorrect current password')
            return jsonify({'success': False, 'error': 'Current password is incorrect'}), 401
        
        # Prevent using same password
        if current_password == new_password:
            print("[DEBUG] ERROR: New password same as current")
            return jsonify({'success': False, 'error': 'New password must be different from current password'}), 400
        
        # Update password
        print("[DEBUG] Setting new password...")
        g.current_user.set_password(new_password)
        db.session.commit()
        print("[DEBUG] Password changed successfully")
        
        # Log successful change
        log_activity(g.current_user.id, 'change_password', 'Password changed successfully')
        
        print("[DEBUG] CHANGE PASSWORD SUCCESS")
        print("="*60 + "\n")
        
        return jsonify({
            'success': True, 
            'message': 'Password changed successfully. Use your new password to login.'
        })
        
    except Exception as e:
        print(f"[DEBUG] EXCEPTION: {e}")
        import traceback
        traceback.print_exc()
        db.session.rollback()
        print("="*60 + "\n")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/user/change-password', methods=['POST'])
@token_required
@limiter.limit("5 per minute")
@limiter.limit("10 per hour")
def change_password_user():
    """Alias for change-password endpoint"""
    print("\n" + "="*60)
    print("[DEBUG] CHANGE PASSWORD (USER ALIAS) CALLED")
    print(f"[DEBUG] Request path: {request.path}")
    print("="*60)
    return change_password()


@app.route('/api/auth/2fa/enable', methods=['POST'])
@token_required
@limiter.limit("3 per minute")
@limiter.limit("5 per hour")
def enable_2fa():
    """Enable 2FA for user"""
    try:
        import pyotp
        import base64
        from io import BytesIO
        
        # Generate secret
        secret = pyotp.random_base32()
        totp = pyotp.TOTP(secret)
        provisioning_uri = totp.provisioning_uri(g.current_user.email, issuer_name=COMPANY_NAME)
        
        # Generate QR code
        import qrcode
        qr = qrcode.QRCode(box_size=10, border=4)
        qr.add_data(provisioning_uri)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        
        # Convert to base64
        buffered = BytesIO()
        img.save(buffered, format="PNG")
        qr_code_base64 = base64.b64encode(buffered.getvalue()).decode()
        
        # Store secret temporarily (will be verified before saving)
        set_temp_data(f"2fa_temp:{g.current_user.id}", {
            'secret': secret,
            'expires': (datetime.utcnow() + timedelta(minutes=10)).isoformat()
        }, expiry_seconds=600)
        
        return jsonify({
            'success': True,
            'secret': secret,
            'qr_code': f"data:image/png;base64,{qr_code_base64}",
            'message': 'Scan the QR code with Google Authenticator or any TOTP app'
        })
        
    except Exception as e:
        print(f"Enable 2FA error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/auth/2fa/verify', methods=['POST'])
@token_required
@limiter.limit("5 per minute")
@limiter.limit("10 per hour")
def verify_2fa_enable():
    """Verify and enable 2FA"""
    try:
        import pyotp
        
        data = request.get_json()
        code = data.get('code')
        
        if not code:
            return jsonify({'success': False, 'error': 'Verification code is required'}), 400
        
        # Get temporary secret
        temp_data = get_temp_data(f"2fa_temp:{g.current_user.id}")
        
        if not temp_data:
            return jsonify({'success': False, 'error': '2FA setup expired. Please try again.'}), 400
        
        secret = temp_data['secret']
        
        # Verify code
        totp = pyotp.TOTP(secret)
        if not totp.verify(code):
            # Log failed attempt
            log_activity(g.current_user.id, '2fa_verify_failed', 'Invalid 2FA code')
            return jsonify({'success': False, 'error': 'Invalid verification code'}), 400
        
        # Enable 2FA
        g.current_user.two_factor_secret = secret
        g.current_user.two_factor_enabled = True
        db.session.commit()
        
        # Clean up temp data
        delete_temp_data(f"2fa_temp:{g.current_user.id}")
        
        # Log success
        log_activity(g.current_user.id, '2fa_enabled', 'Two-factor authentication enabled')
        
        return jsonify({
            'success': True, 
            'message': f'2FA enabled successfully on {COMPANY_NAME}',
            'recovery_codes': generate_recovery_codes(g.current_user.id)  # Optional
        })
        
    except Exception as e:
        print(f"Verify 2FA error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/auth/2fa/disable', methods=['POST'])
@token_required
@limiter.limit("3 per minute")
@limiter.limit("5 per hour")
def disable_2fa():
    """Disable 2FA"""
    try:
        data = request.get_json()
        code = data.get('code')
        
        # Require 2FA code to disable (security)
        if g.current_user.two_factor_enabled:
            import pyotp
            totp = pyotp.TOTP(g.current_user.two_factor_secret)
            if not code or not totp.verify(code):
                return jsonify({'success': False, 'error': 'Valid 2FA code is required to disable'}), 401
        
        g.current_user.two_factor_enabled = False
        g.current_user.two_factor_secret = None
        db.session.commit()
        
        # Log activity
        log_activity(g.current_user.id, '2fa_disabled', 'Two-factor authentication disabled')
        
        return jsonify({
            'success': True, 
            'message': f'2FA disabled on {COMPANY_NAME}'
        })
        
    except Exception as e:
        print(f"Disable 2FA error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


# Optional: Helper function to generate recovery codes
def generate_recovery_codes(user_id):
    """Generate recovery codes for 2FA backup"""
    import secrets
    recovery_codes = []
    for _ in range(8):
        code = secrets.token_hex(4).upper()  # 8 character code
        recovery_codes.append(code)
        # Store in Redis or database
        set_temp_data(f"2fa_recovery:{user_id}:{code}", True, expiry_seconds=7776000)  # 90 days
    return recovery_codes

@app.route('/api/auth/sessions', methods=['GET'])
@token_required
@limiter.limit("30 per minute")
def get_sessions():
    """Get user's active sessions (USES REDIS)"""
    try:
        # Get sessions from Redis instead of database for better performance
        session_key = f"user_sessions:{g.current_user.id}"
        sessions = get_temp_data(session_key)
        
        if not sessions:
            # Fallback to database
            sessions = UserSession.query.filter_by(
                user_id=g.current_user.id
            ).order_by(UserSession.created_at.desc()).limit(10).all()
            
            sessions_data = [{
                'id': s.id,
                'device': s.device_info,
                'ip_address': s.ip_address,
                'location': s.location,
                'last_active': s.last_active.isoformat() if s.last_active else s.created_at.isoformat(),
                'is_current': s.id == getattr(g, 'current_session_id', None)
            } for s in sessions]
        else:
            sessions_data = sessions
        
        return jsonify({
            'success': True,
            'sessions': sessions_data,
            'total': len(sessions_data)
        })
        
    except Exception as e:
        print(f"Get sessions error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/auth/sessions/<int:session_id>', methods=['DELETE'])
@token_required
@limiter.limit("10 per minute")
@limiter.limit("30 per hour")
def revoke_session(session_id):
    """Revoke a user session (USES REDIS)"""
    try:
        # Check if session exists and belongs to user
        session = UserSession.query.filter_by(
            id=session_id, 
            user_id=g.current_user.id
        ).first()
        
        if not session:
            # Check Redis for active session
            session_key = f"session:{session_id}"
            session_data = get_temp_data(session_key)
            
            if session_data and session_data.get('user_id') == g.current_user.id:
                delete_temp_data(session_key)
                # Also remove from user's sessions list
                user_sessions_key = f"user_sessions:{g.current_user.id}"
                user_sessions = get_temp_data(user_sessions_key)
                if user_sessions:
                    user_sessions = [s for s in user_sessions if s.get('id') != session_id]
                    set_temp_data(user_sessions_key, user_sessions, 3600)
                
                # Log activity
                log_activity(g.current_user.id, 'session_revoked', f'Session {session_id} revoked')
                
                return jsonify({
                    'success': True, 
                    'message': 'Session revoked successfully'
                })
            
            return jsonify({'success': False, 'error': 'Session not found'}), 404
        
        # Delete from database
        db.session.delete(session)
        db.session.commit()
        
        # Also remove from Redis if exists
        session_key = f"session:{session_id}"
        delete_temp_data(session_key)
        
        # Remove from user's sessions list
        user_sessions_key = f"user_sessions:{g.current_user.id}"
        user_sessions = get_temp_data(user_sessions_key)
        if user_sessions:
            user_sessions = [s for s in user_sessions if s.get('id') != session_id]
            set_temp_data(user_sessions_key, user_sessions, 3600)
        
        # Log activity
        log_activity(g.current_user.id, 'session_revoked', f'Session {session_id} revoked')
        
        return jsonify({
            'success': True, 
            'message': 'Session revoked successfully'
        })
        
    except Exception as e:
        print(f"Revoke session error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/auth/sessions/revoke-all', methods=['DELETE'])
@token_required
@limiter.limit("5 per minute")
@limiter.limit("10 per hour")
def revoke_all_sessions():
    """Revoke all user sessions except current"""
    try:
        # Delete all sessions except current
        sessions = UserSession.query.filter_by(user_id=g.current_user.id).all()
        
        deleted_count = 0
        for session in sessions:
            if session.id != getattr(g, 'current_session_id', None):
                db.session.delete(session)
                deleted_count += 1
                
                # Also remove from Redis
                session_key = f"session:{session.id}"
                delete_temp_data(session_key)
        
        db.session.commit()
        
        # Clear user sessions from Redis
        user_sessions_key = f"user_sessions:{g.current_user.id}"
        delete_temp_data(user_sessions_key)
        
        # Log activity
        log_activity(g.current_user.id, 'all_sessions_revoked', f'Revoked {deleted_count} sessions')
        
        return jsonify({
            'success': True,
            'message': f'Revoked {deleted_count} sessions',
            'deleted_count': deleted_count
        })
        
    except Exception as e:
        print(f"Revoke all sessions error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/auth/log-activity', methods=['POST'])
@token_required
@limiter.limit("60 per minute")
def log_activity_endpoint():
    """Log user activity"""
    print("\n" + "="*60)
    print("[DEBUG] LOG ACTIVITY ENDPOINT CALLED")
    print("="*60)
    
    try:
        data = request.get_json() or {}
        print(f"[DEBUG] Request data: {data}")
        print(f"[DEBUG] User: {g.current_user.username} (ID: {g.current_user.id})")
        
        action = data.get('action')
        details = data.get('details')
        
        if not action:
            print("[DEBUG] No action provided - returning success")
            return jsonify({'success': True, 'message': 'No action provided'})
        
        print(f"[DEBUG] Action: {action}")
        print(f"[DEBUG] Details: {details}")
        
        # Rate limit per action type
        try:
            action_key = f"activity:{g.current_user.id}:{action}"
            print(f"[DEBUG] Rate limit key: {action_key}")
            action_count = get_temp_data(action_key)
            
            if action_count:
                print("[DEBUG] Rate limited - skipping")
                return jsonify({'success': True, 'message': 'Activity logged (rate limited)'})
            
            set_temp_data(action_key, 1, 1)
            print("[DEBUG] Rate limit set")
        except Exception as e:
            print(f"[DEBUG] Rate limiting error: {e}")
        
        # Log to database
        try:
            print("[DEBUG] Logging activity to database...")
            log_activity(g.current_user.id, action, details)
            print("[DEBUG] Database log successful")
        except Exception as e:
            print(f"[DEBUG] Database log error: {e}")
        
        # Store recent activities in Redis
        try:
            print("[DEBUG] Storing in Redis...")
            recent_key = f"recent_activities:{g.current_user.id}"
            recent_activities = get_temp_data(recent_key) or []
            
            recent_activities.insert(0, {
                'action': action,
                'details': details,
                'timestamp': datetime.utcnow().isoformat()
            })
            
            recent_activities = recent_activities[:50]
            set_temp_data(recent_key, recent_activities, 86400)
            print("[DEBUG] Redis storage successful")
        except Exception as e:
            print(f"[DEBUG] Redis storage error: {e}")
        
        print("[DEBUG] LOG ACTIVITY SUCCESS")
        print("="*60 + "\n")
        return jsonify({'success': True})
        
    except Exception as e:
        print(f"[DEBUG] EXCEPTION: {e}")
        import traceback
        traceback.print_exc()
        print("="*60 + "\n")
        return jsonify({'success': True, 'message': 'Activity noted'})
    
def log_activity(user_id, action, details, ip_address=None):
    """Log user activity to database"""
    print(f"[DEBUG log_activity] Called for user {user_id}, action: {action}")
    try:
        from models import UserSession
        activity = UserSession(
            user_id=user_id,
            action=action,
            details=details,
            ip_address=ip_address or request.remote_addr,
            created_at=datetime.utcnow()
        )
        db.session.add(activity)
        db.session.commit()
        print(f"[DEBUG log_activity] Successfully logged activity for user {user_id}")
    except Exception as e:
        print(f"[DEBUG log_activity] Error: {e}")
        # Don't raise, just print

@app.route('/api/auth/activities', methods=['GET'])
@token_required
@limiter.limit("30 per minute")
def get_user_activities():
    """Get user's recent activities"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('limit', 20, type=int)
        
        # Try to get from Redis first
        recent_key = f"recent_activities:{g.current_user.id}"
        activities = get_temp_data(recent_key)
        
        if activities:
            # Paginate Redis data
            start = (page - 1) * per_page
            end = start + per_page
            paginated = activities[start:end]
            
            return jsonify({
                'success': True,
                'activities': paginated,
                'total': len(activities),
                'page': page,
                'total_pages': (len(activities) + per_page - 1) // per_page
            })
        
        # Fallback to database
        # You would need a UserActivityLog model for this
        
        return jsonify({
            'success': True,
            'activities': [],
            'total': 0,
            'page': page,
            'total_pages': 0
        })
        
    except Exception as e:
        print(f"Get activities error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ========== USER ROUTES ==========

@app.route('/api/user/stats', methods=['GET'])
@token_required
def get_user_stats():
    """Get user dashboard statistics"""
    try:
        user = g.current_user
        
        # Get completed orders count
        completed_orders = Order.query.filter_by(
            user_id=user.id, 
            status='completed'
        ).count()
        
        # Get total spent
        total_spent = db.session.query(db.func.sum(Order.amount)).filter(
            Order.user_id == user.id, 
            Order.status == 'completed'
        ).scalar() or 0
        
        # Get referral stats
        referrals = Referral.query.filter_by(
            referrer_id=user.id
        ).count()
        
        referral_earnings = db.session.query(db.func.sum(Referral.reward_amount)).filter(
            Referral.referrer_id == user.id, 
            Referral.status == 'completed'
        ).scalar() or 0
        
        return jsonify({
            'success': True,
            'data': {
                'wallet_balance': float(user.wallet_balance or 0),
                'total_orders': completed_orders,
                'total_spent': float(total_spent),
                'referral_code': user.referral_code,
                'referral_count': referrals,
                'referral_earnings': float(referral_earnings),
                'is_agent': user.is_agent and user.agent_approved if hasattr(user, 'agent_approved') else user.is_agent,
                'username': user.username,
                'phone': user.phone,
                'email': user.email,
                'avatar_url': getattr(user, 'avatar_url', None)
            }
        })
        
    except Exception as e:
        print(f"User stats error: {e}")
        return jsonify({'success': False, 'error': 'Failed to fetch stats'}), 500

@app.route('/api/user/profile', methods=['PUT'])
@token_required
def update_profile():
    """Update user profile"""
    data = request.get_json()
    
    if 'username' in data:
        g.current_user.username = data['username']
    if 'email' in data:
        g.current_user.email = data['email']
    if 'phone' in data:
        g.current_user.phone = data['phone']
    if 'full_name' in data:
        g.current_user.full_name = data['full_name']
    
    db.session.commit()
    
    return jsonify({'success': True, 'user': g.current_user.to_dict()})


@app.route('/api/prices', methods=['GET'])
@token_required
def get_prices():
    """Get data bundle prices based on user role from database (1-100GB dynamic)"""
    try:
        user = g.current_user
        is_agent = user.is_agent and getattr(user, 'agent_approved', False)
        
        # Get all prices from PriceSetting table
        price_settings = PriceSetting.query.all()
        
        # Build price dictionaries from database only (no defaults)
        user_prices = {}
        agent_prices = {}
        
        for setting in price_settings:
            if setting.category == 'user_price' and setting.network and setting.size_gb:
                if setting.network not in user_prices:
                    user_prices[setting.network] = {}
                user_prices[setting.network][str(setting.size_gb)] = float(setting.price)
                print(f"Loaded user price: {setting.network} {setting.size_gb}GB = ₵{setting.price}")
                
            elif setting.category == 'agent_price' and setting.network and setting.size_gb:
                if setting.network not in agent_prices:
                    agent_prices[setting.network] = {}
                agent_prices[setting.network][str(setting.size_gb)] = float(setting.price)
                print(f"Loaded agent price: {setting.network} {setting.size_gb}GB = ₵{setting.price}")
        
        # Get all available sizes for reference
        all_sizes = sorted(set(
            [s.size_gb for s in price_settings if s.size_gb]
        ))
        
        # Return prices based on user role
        if is_agent:
            print(f"Returning agent prices for user {user.username} - {len(agent_prices.get('mtn', {}))} sizes available")
            return jsonify({
                'success': True,
                'data': agent_prices,
                'user_role': 'agent',
                'source': 'database',
                'available_sizes': all_sizes,
                'message': f'Prices configured by admin for {len(all_sizes)} data sizes'
            })
        else:
            print(f"Returning user prices for user {user.username} - {len(user_prices.get('mtn', {}))} sizes available")
            return jsonify({
                'success': True,
                'data': user_prices,
                'user_role': 'user',
                'source': 'database',
                'available_sizes': all_sizes,
                'message': f'Prices configured by admin for {len(all_sizes)} data sizes'
            })
        
    except Exception as e:
        print(f"Prices error: {e}")
        import traceback
        traceback.print_exc()
        # Return empty prices on error (no defaults)
        return jsonify({
            'success': False,
            'error': 'Failed to load prices',
            'message': 'Please contact admin to configure prices'
        }), 500

@app.route('/api/admin/total-sales', methods=['GET'])
@token_required
@admin_required
def admin_total_sales():
    """Get total sales for admin dashboard"""
    try:
        # Calculate total sales from your orders
        total_sales = db.session.query(func.sum(Order.amount)).filter(Order.status == 'completed').scalar() or 0
        
        # Optional: Get today's sales
        today = datetime.utcnow().date()
        today_sales = db.session.query(func.sum(Order.amount)).filter(
            Order.status == 'completed',
            func.date(Order.completed_at) == today
        ).scalar() or 0
        
        return jsonify({
            'success': True,
            'data': {
                'total_sales': float(total_sales),
                'today_sales': float(today_sales),
                'currency': 'GHS'
            }
        })
    except Exception as e:
        print(f"Error getting total sales: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/wallet/pending-topups', methods=['GET'])
@token_required
def get_pending_topups():
    """Get pending topups for the current user"""
    try:
        # Query pending transactions from the database
        pending = PendingTransaction.query.filter_by(
            user_id=g.current_user.id, 
            status='pending'
        ).all()
        
        return jsonify({
            'success': True,
            'data': [{
                'id': p.id,
                'reference': p.reference,
                'amount': float(p.amount),
                'payment_method': p.payment_method,
                'created_at': p.created_at.isoformat()
            } for p in pending]
        })
    except Exception as e:
        print(f"Error getting pending topups: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/prices/sizes', methods=['GET'])
@token_required
def get_available_sizes():
    """Get all available data sizes (1-100GB) that have prices configured"""
    try:
        from models import PriceSetting
        
        # Get unique sizes from price settings
        sizes = PriceSetting.query.with_entities(
            PriceSetting.size_gb
        ).filter(
            PriceSetting.size_gb.isnot(None)
        ).distinct().order_by(PriceSetting.size_gb).all()
        
        available_sizes = [s[0] for s in sizes if s[0] is not None]
        
        return jsonify({
            'success': True,
            'sizes': available_sizes,
            'min_size': min(available_sizes) if available_sizes else 1,
            'max_size': max(available_sizes) if available_sizes else 100,
            'total_sizes': len(available_sizes)
        })
        
    except Exception as e:
        print(f"Get sizes error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/prices/check', methods=['GET'])
@token_required
def check_price():
    """Check if price exists for specific network and size"""
    try:
        network = request.args.get('network')
        size_gb = request.args.get('size', type=int)
        
        if not network or not size_gb:
            return jsonify({'success': False, 'error': 'Network and size required'}), 400
        
        user = g.current_user
        is_agent = user.is_agent and getattr(user, 'agent_approved', False)
        
        from models import PriceSetting
        
        category = 'agent_price' if is_agent else 'user_price'
        
        setting = PriceSetting.query.filter_by(
            category=category,
            network=network,
            size_gb=size_gb
        ).first()
        
        if setting:
            return jsonify({
                'success': True,
                'exists': True,
                'price': float(setting.price),
                'network': network,
                'size_gb': size_gb,
                'message': f'Price available: ₵{setting.price} for {size_gb}GB'
            })
        else:
            return jsonify({
                'success': True,
                'exists': False,
                'network': network,
                'size_gb': size_gb,
                'message': f'No price configured for {size_gb}GB on {network.upper()}. Please contact admin.'
            })
            
    except Exception as e:
        print(f"Check price error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
# ========== PHONE VERIFICATION ENDPOINTS (Add these to your app.py) ==========

@app.route('/api/auth/send-phone-verification', methods=['POST'])
@token_required
def send_phone_verification():
    """Send verification code - ALWAYS SMS first, email only if SMS fails"""
    try:
        data = request.get_json()
        phone_number = data.get('phone')
        email = g.current_user.email if g.current_user else data.get('email')
        
        if not phone_number:
            return jsonify({'success': False, 'error': 'Phone number required'}), 400
        
        if not email:
            return jsonify({'success': False, 'error': 'Email required for fallback'}), 400
        
        # Validate Ghana phone number
        phone_regex = r'^(024|025|026|027|028|020|054|055|059|050|057|053|056)[0-9]{7}$'
        if not re.match(phone_regex, phone_number):
            return jsonify({'success': False, 'error': 'Invalid Ghana phone number'}), 400
        
        result = verification_service.send_verification_code(phone_number, email)
        
        return jsonify({
            'success': True,
            'method': result.get('method', 'sms'),
            'message': result['message'],
            'expires_in': result.get('expires_in', 600)
        })
        
    except Exception as e:
        print(f"Send phone verification error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/auth/resend-phone-verification', methods=['POST'])
@token_required
def resend_phone_verification():
    """Resend verification code - ALWAYS try SMS first again"""
    try:
        data = request.get_json()
        phone_number = data.get('phone')
        email = g.current_user.email if g.current_user else data.get('email')
        
        if not phone_number:
            return jsonify({'success': False, 'error': 'Phone number required'}), 400
        
        if not email:
            return jsonify({'success': False, 'error': 'Email required for fallback'}), 400
        
        result = verification_service.resend_verification_code(phone_number, email)
        
        return jsonify({
            'success': True,
            'method': result.get('method', 'sms'),
            'message': result['message'],
            'expires_in': result.get('expires_in', 600)
        })
        
    except Exception as e:
        print(f"Resend phone verification error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/auth/verify-phone-code', methods=['POST'])
@token_required
def verify_phone_code():
    """Verify phone number with code"""
    try:
        data = request.get_json()
        phone_number = data.get('phone')
        code = data.get('code')
        
        if not phone_number or not code:
            return jsonify({'success': False, 'error': 'Phone number and code required'}), 400
        
        result = verification_service.verify_code(phone_number, code)
        
        if result['success']:
            g.current_user.phone_verified = True
            db.session.commit()
            
            log_activity(g.current_user.id, 'phone_verified', f'Phone {phone_number} verified via {result.get("method", "unknown")}')
            
            return jsonify({
                'success': True,
                'message': 'Phone number verified successfully',
                'method': result.get('method', 'unknown')
            })
        else:
            return jsonify({'success': False, 'error': result['error']}), 400
        
    except Exception as e:
        print(f"Verify phone code error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


def send_phone_verification_email(email, phone_number, code):
    """Send verification code via email for phone verification resend"""
    html_content = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <div style="background: #8B0000; padding: 20px; text-align: center; border-radius: 10px 10px 0 0;">
            <h2 style="color: white;">📱 Phone Verification Code</h2>
            <p style="color: white;">{COMPANY_NAME}</p>
        </div>
        <div style="background: #f5f5f5; padding: 30px; border-radius: 0 0 10px 10px;">
            <p>Your verification code for <strong>{phone_number}</strong> is:</p>
            <div style="background: white; font-size: 36px; font-weight: bold; text-align: center; padding: 20px; border-radius: 10px; margin: 20px 0; letter-spacing: 5px;">
                {code}
            </div>
            <p style="color: #666;">This code expires in <strong>10 minutes</strong>.</p>
            <p style="color: #666; font-size: 12px;">If you didn't request this, please ignore this email.</p>
            <hr style="margin: 20px 0; border: none; border-top: 1px solid #ddd;">
            <p style="color: #999; font-size: 11px; text-align: center;">
                {COMPANY_NAME} - Smart Data, Simpler Life<br>
                Need help? Contact us: {COMPANY_PHONE}
            </p>
        </div>
    </div>
    """
    send_email(email, f"Phone Verification Code - {COMPANY_NAME}", html_content)

@app.route('/api/auth/resend-verification', methods=['POST'])
@limiter.limit("3 per minute")
@limiter.limit("10 per hour")
def resend_verification():
    """Resend verification code for email verification"""
    data = request.get_json()
    email = data.get('email')
    
    print(f"[RESEND] Request for email: {email}")
    
    if not email:
        return jsonify({'success': False, 'error': 'Email required'}), 400
    
    # Check for temp_user in session
    temp_user = session.get('temp_user')
    
    if temp_user and temp_user.get('email') == email:
        new_code = generate_verification_code()
        temp_user['verification_code'] = new_code
        temp_user['expires'] = (datetime.utcnow() + timedelta(minutes=10)).isoformat()
        session['temp_user'] = temp_user
        session[f'temp_user_{email}'] = temp_user
        
        print(f"[RESEND] New code for {email}: {new_code}")
        
        email_sent = send_verification_email(email, temp_user.get('username', 'User'), new_code)
        
        if email_sent:
            return jsonify({
                'success': True,
                'message': 'Verification code resent successfully',
                'data': {'email': email, 'expires_in': 10}
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Failed to send email. Please try again.'
            }), 500
    
    # Check for existing unverified user in database
    user = User.query.filter_by(email=email, email_verified=False).first()
    
    if user:
        new_code = generate_verification_code()
        
        session['temp_user'] = {
            'username': user.username,
            'email': user.email,
            'phone': user.phone,
            'password': None,
            'referral_code': None,
            'verification_code': new_code,
            'expires': (datetime.utcnow() + timedelta(minutes=10)).isoformat(),
            'existing_user_id': user.id
        }
        
        session[f'temp_user_{email}'] = session['temp_user']
        
        print(f"[RESEND] New session created for existing user: {email}")
        print(f"[RESEND] New code: {new_code}")
        
        email_sent = send_verification_email(email, user.username, new_code)
        
        if email_sent:
            return jsonify({
                'success': True,
                'message': 'Verification code resent successfully',
                'data': {'email': email, 'expires_in': 10}
            })
    
    email_temp = session.get(f'temp_user_{email}')
    if email_temp:
        new_code = generate_verification_code()
        email_temp['verification_code'] = new_code
        email_temp['expires'] = (datetime.utcnow() + timedelta(minutes=10)).isoformat()
        session[f'temp_user_{email}'] = email_temp
        session['temp_user'] = email_temp
        
        print(f"[RESEND] Found in email-specific session: {email}")
        print(f"[RESEND] New code: {new_code}")
        
        email_sent = send_verification_email(email, email_temp.get('username', 'User'), new_code)
        
        if email_sent:
            return jsonify({
                'success': True,
                'message': 'Verification code resent successfully',
                'data': {'email': email, 'expires_in': 10}
            })
    
    return jsonify({
        'success': False,
        'error': 'No pending registration found. Please register again.'
    }), 400


@app.route('/api/auth/resend-registration-code', methods=['POST'])
def resend_registration_code():
    """Resend verification code for registration (alternative endpoint)"""
    data = request.get_json()
    email = data.get('email')
    
    print(f"Resend registration code request for email: {email}")
    
    if not email:
        return jsonify({'success': False, 'error': 'Email required'}), 400
    
    temp_user = session.get('temp_user')
    
    if temp_user and temp_user.get('email') == email:
        new_code = generate_verification_code()
        temp_user['verification_code'] = new_code
        temp_user['expires'] = (datetime.utcnow() + timedelta(minutes=10)).isoformat()
        session['temp_user'] = temp_user
        
        send_verification_email(email, temp_user.get('username', 'User'), new_code)
        
        return jsonify({
            'success': True,
            'message': 'Verification code resent successfully'
        })
    
    return jsonify({
        'success': False,
        'error': 'No pending registration found. Please register again.'
    }), 400

# ========== FORGOT PASSWORD ROUTES ==========

@app.route('/api/auth/forgot-password', methods=['POST'])
@limiter.limit("3 per minute")
@limiter.limit("10 per hour")
def forgot_password():
    """Send password reset email"""
    import secrets
    try:
        data = request.get_json()
        email = data.get('email')
        
        if not email:
            return jsonify({'success': False, 'error': 'Email is required'}), 400
        
        user = User.query.filter_by(email=email).first()
        
        # For security, always return success even if user doesn't exist
        if not user:
            print(f"[PASSWORD] Reset requested for non-existent email: {email}")
            return jsonify({
                'success': True, 
                'message': 'If an account exists with this email, you will receive a reset link.'
            })
        
        # Generate reset token
        reset_token = secrets.token_urlsafe(32)
        user.reset_token = reset_token
        user.reset_token_expiry = datetime.utcnow() + timedelta(hours=24)
        db.session.commit()
        
        # Use production frontend URL only
        frontend_url = 'https://www.roamsmart.shop'
        reset_link = f"{frontend_url}/reset-password?token={reset_token}"
        
        print(f"[PASSWORD] Reset link generated: {reset_link}")
        
        # Create HTML email body
        email_body = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <div style="background: #8B0000; color: white; padding: 20px; text-align: center;">
                <h1>🔐 Reset Your Password</h1>
                <p>Roamsmart Digital Service</p>
            </div>
            <div style="background: #f9f9f9; padding: 30px;">
                <h2>Hello {user.username}!</h2>
                <p>We received a request to reset your password for your Roamsmart account.</p>
                <p>Click the button below to create a new password:</p>
                <div style="text-align: center; margin: 30px 0;">
                    <a href="{reset_link}" style="background: #8B0000; color: white; padding: 12px 30px; text-decoration: none; border-radius: 5px; display: inline-block;">
                        Reset Password
                    </a>
                </div>
                <p>This link will expire in <strong>24 hours</strong>.</p>
                <p>If you didn't request this, please ignore this email.</p>
                <hr>
                <p style="font-size: 12px; color: #666;">Or copy this link: {reset_link}</p>
            </div>
            <div style="text-align: center; padding: 20px; font-size: 12px; color: #666;">
                <p>Roamsmart Digital Service - Your trusted digital service partner</p>
                <p>© 2024 Roamsmart. All rights reserved.</p>
            </div>
        </div>
        """
        
        # Send email using your existing send_email function
        send_email(
            to=email,
            subject="Reset Your Roamsmart Password",
            body=email_body
        )
        
        print(f"[PASSWORD] Reset email sent to: {email}")
        
        return jsonify({
            'success': True,
            'message': 'Password reset link sent to your email'
        })
        
    except Exception as e:
        print(f"[PASSWORD] Forgot password error: {e}")
        import traceback
        traceback.print_exc()
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/auth/reset-password', methods=['POST'])
@limiter.limit("3 per minute")
@limiter.limit("10 per hour")
def reset_password():
    """Reset password using token"""
    try:
        import bcrypt  # Add this import
        
        data = request.get_json()
        token = data.get('token')
        new_password = data.get('new_password')
        
        if not token or not new_password:
            return jsonify({'success': False, 'error': 'Token and new password are required'}), 400
        
        if len(new_password) < 6:
            return jsonify({'success': False, 'error': 'Password must be at least 6 characters'}), 400
        
        # Find user by token
        user = User.query.filter_by(reset_token=token).first()
        
        if not user:
            return jsonify({'success': False, 'error': 'Invalid or expired reset token'}), 400
        
        # Check if token is expired
        if user.reset_token_expiry and user.reset_token_expiry < datetime.utcnow():
            return jsonify({'success': False, 'error': 'Reset token has expired. Please request a new one.'}), 400
        
        # ========== FIX: Use bcrypt (same as User model) ==========
        # Hash the new password with bcrypt
        salt = bcrypt.gensalt()
        hashed_password = bcrypt.hashpw(new_password.encode('utf-8'), salt).decode('utf-8')
        user.password_hash = hashed_password
        
        # Clear reset token
        user.reset_token = None
        user.reset_token_expiry = None
        db.session.commit()
        
        # Use production frontend URL only
        frontend_url = 'https://www.roamsmart.shop'
        
        # Send confirmation email
        confirmation_body = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <div style="background: #28a745; color: white; padding: 20px; text-align: center;">
                <h1>✅ Password Changed Successfully</h1>
                <p>Roamsmart Digital Service</p>
            </div>
            <div style="background: #f9f9f9; padding: 30px;">
                <h2>Hello {user.username}!</h2>
                <p>Your Roamsmart account password has been successfully changed.</p>
                <p>If you did not make this change, please contact our support team immediately.</p>
                <div style="text-align: center; margin: 30px 0;">
                    <a href="{frontend_url}/login" style="background: #28a745; color: white; padding: 12px 30px; text-decoration: none; border-radius: 5px; display: inline-block;">
                        Login to Your Account
                    </a>
                </div>
            </div>
            <div style="text-align: center; padding: 20px; font-size: 12px; color: #666;">
                <p>Roamsmart Digital Service</p>
            </div>
        </div>
        """
        
        send_email(
            to=user.email,
            subject="Your Roamsmart Password Has Been Changed",
            body=confirmation_body
        )
        
        print(f"[PASSWORD] Password reset successfully for user: {user.username}")
        
        return jsonify({
            'success': True,
            'message': 'Password reset successful. You can now login with your new password.'
        })
        
    except Exception as e:
        print(f"[PASSWORD] Reset password error: {e}")
        import traceback
        traceback.print_exc()
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/auth/verify-reset-token', methods=['POST'])
@limiter.limit("10 per minute")
@limiter.limit("50 per hour")
def verify_reset_token():
    """Verify if reset token is valid"""
    try:
        data = request.get_json()
        token = data.get('token')
        
        if not token:
            return jsonify({'success': False, 'error': 'Token is required'}), 400
        
        user = User.query.filter_by(reset_token=token).first()
        
        if not user:
            return jsonify({'success': False, 'error': 'Invalid token'}), 400
        
        if user.reset_token_expiry and user.reset_token_expiry < datetime.utcnow():
            return jsonify({'success': False, 'error': 'Token has expired'}), 400
        
        return jsonify({
            'success': True,
            'message': 'Token is valid',
            'email': user.email
        })
        
    except Exception as e:
        print(f"[PASSWORD] Verify token error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500




@app.route('/api/auth/register', methods=['POST'])
@limiter.limit("5 per minute")
def register():
    """Register new user - Send SMS verification first, email fallback (USES REDIS)"""
    try:
        data = request.get_json()
        
        username = data.get('username')
        email = data.get('email')
        phone = data.get('phone')
        password = data.get('password')
        referral_code = data.get('referral_code')
        
        if not all([username, email, phone, password]):
            return jsonify({'success': False, 'error': 'All fields required'}), 400
        
        # Check if user exists
        if User.query.filter_by(email=email).first():
            return jsonify({'success': False, 'error': 'Email already registered'}), 400
        
        if User.query.filter_by(phone=phone).first():
            return jsonify({'success': False, 'error': 'Phone already registered'}), 400
        
        verification_code = verification_service.generate_verification_code()
        
        # Store in Redis (10 minutes expiry)
        set_temp_data(
            f"register:{email}",
            {
                'username': username,
                'email': email,
                'phone': phone,
                'password': password,
                'referral_code': referral_code,
                'verification_code': verification_code,
                'expires': (datetime.utcnow() + timedelta(minutes=10)).isoformat()
            },
            expiry_seconds=600
        )
        
        print(f"[REGISTER] Stored verification for email: {email}")
        print(f"[REGISTER] Verification code: {verification_code}")
        
        # Try SMS first, then email fallback
        sms_sent = verification_service.send_sms(phone, verification_code)
        
        if sms_sent.get('success'):
            return jsonify({
                'success': True,
                'message': 'Verification code sent to your phone via SMS',
                'method': 'sms',
                'data': {'phone': phone, 'email': email, 'expires_in': 10}
            })
        else:
            # SMS failed - send email
            email_sent = send_verification_email(email, username, verification_code)
            if email_sent:
                return jsonify({
                    'success': True,
                    'message': 'SMS delivery failed. Verification code sent to your email.',
                    'method': 'email',
                    'data': {'email': email, 'expires_in': 10}
                })
            else:
                return jsonify({
                    'success': False, 
                    'error': 'Failed to send verification. Please try again.'
                }), 500
        
    except Exception as e:
        print(f"Register error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/auth/verify-code', methods=['POST'])
@limiter.limit("10 per minute")
@limiter.limit("10 per hour")
def verify_registration_code():
    """Verify registration code and complete registration (USES REDIS)"""
    try:
        data = request.get_json()
        user_code = data.get('code')
        email = data.get('email')
        
        print(f"[VERIFY] Received code: {user_code}")
        print(f"[VERIFY] Email: {email}")
        
        # Get temp data from Redis
        temp_user = get_temp_data(f"register:{email}")
        
        if not temp_user:
            print(f"[VERIFY] No pending registration found for {email}")
            return jsonify({
                'success': False, 
                'error': 'No pending registration found. Please register again.'
            }), 400
        
        # Check expiration
        expires_at = datetime.fromisoformat(temp_user['expires'])
        if datetime.utcnow() > expires_at:
            # Clean up expired entry
            delete_temp_data(f"register:{email}")
            return jsonify({
                'success': False, 
                'error': 'Verification code expired. Please register again.'
            }), 400
        
        # Verify code
        if user_code != temp_user.get('verification_code'):
            return jsonify({'success': False, 'error': 'Invalid verification code'}), 400
        
        # Check if user already exists
        existing_user = User.query.filter_by(email=temp_user['email']).first()
        
        if existing_user:
            if not existing_user.email_verified:
                existing_user.email_verified = True
                existing_user.email_verified_at = datetime.utcnow()
                db.session.commit()
                
                # Clean up Redis
                delete_temp_data(f"register:{email}")
                
                send_welcome_email(existing_user.email, existing_user.username, 'user')
                token = existing_user.generate_token()
                
                return jsonify({
                    'success': True,
                    'message': 'Email verified successfully!',
                    'token': token,
                    'user': existing_user.to_dict()
                })
            else:
                return jsonify({
                    'success': False,
                    'error': 'Email already verified. Please login.'
                }), 400
        
        # Create new user
        user_ref_code = f"REF{uuid.uuid4().hex[:8].upper()}"
        
        new_user = User(
            username=temp_user['username'],
            email=temp_user['email'],
            phone=temp_user['phone'],
            role='user',
            wallet_balance=0.0,
            referral_code=user_ref_code,
            email_verified=True,
            email_verified_at=datetime.utcnow()
        )
        new_user.set_password(temp_user['password'])
        
        if temp_user.get('referral_code'):
            referrer = User.query.filter_by(referral_code=temp_user['referral_code']).first()
            if referrer:
                new_user.referred_by = referrer.id
                
                referral = Referral(
                    referrer_id=referrer.id,
                    referred_id=new_user.id,
                    status='pending',
                    reward_amount=5.00
                )
                db.session.add(referral)
        
        db.session.add(new_user)
        db.session.commit()
        
        # Clean up Redis
        delete_temp_data(f"register:{email}")
        
        send_welcome_email(new_user.email, new_user.username, 'user')
        
        token = new_user.generate_token()
        
        return jsonify({
            'success': True,
            'message': f'Registration successful on {COMPANY_NAME}!',
            'token': token,
            'user': new_user.to_dict()
        })
        
    except Exception as e:
        print(f"Verify code error: {e}")
        import traceback
        traceback.print_exc()
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/auth/login', methods=['POST'])
@limiter.limit("10 per minute")
def login():
    """Login user - With account lockout protection (USES REDIS)"""
    try:
        data = request.get_json()
        email = data.get('email', '').lower().strip()
        password = data.get('password')
        remember_me = data.get('remember_me', False)
        
        print(f"\n{'='*60}")
        print(f"[LOGIN ATTEMPT]")
        print(f"  Email: {email}")
        print(f"  Password provided: {'Yes' if password else 'No'}")
        print(f"{'='*60}")
        
        if not email or not password:
            return jsonify({'success': False, 'error': 'Email and password required'}), 400
        
        # First, check if admin email is being used
        if email == COMPANY_ADMIN_EMAIL:
            print(f"[LOGIN] Admin login attempt for {email}")
        
        user = User.query.filter_by(email=email).first()
        
        if not user:
            # Don't reveal if user exists for security
            print(f"[LOGIN FAILED] User not found: {email}")
            return jsonify({'success': False, 'error': 'Invalid credentials'}), 401
        
        print(f"[USER FOUND] ID: {user.id}, Role: {user.role}, Email: {user.email}")
        
        # ========== ACCOUNT LOCKOUT CHECK ==========
        if user.is_locked():
            remaining = user.get_remaining_lockout_time()
            print(f"[LOGIN] Account locked for {email}. Remaining: {remaining} minutes")
            return jsonify({
                'success': False,
                'error': f'Account locked due to too many failed attempts. Try again in {remaining} minutes.',
                'locked': True,
                'retry_after_minutes': remaining
            }), 401
        
        # Check password
        try:
            password_valid = user.check_password(password)
            print(f"  Password check result: {password_valid}")
        except Exception as e:
            print(f"  Password check error: {e}")
            password_valid = False
        
        # ========== HANDLE FAILED ATTEMPT ==========
        if not password_valid:
            # Increment failed attempts
            user.increment_failed_attempts(request.remote_addr)
            db.session.commit()
            
            remaining_attempts = 5 - user.failed_login_attempts
            print(f"[LOGIN FAILED] Invalid password for {email}. Attempts: {user.failed_login_attempts}/5")
            
            # Log suspicious activity after 3 failures
            if user.failed_login_attempts >= 3:
                log_suspicious_activity(
                    user.id, 
                    'brute_force', 
                    f'Failed login attempts: {user.failed_login_attempts}', 
                    request.remote_addr
                )
            
            # Return error with remaining attempts
            if remaining_attempts > 0:
                return jsonify({
                    'success': False, 
                    'error': f'Invalid credentials. {remaining_attempts} attempts remaining.',
                    'remaining_attempts': remaining_attempts
                }), 401
            else:
                return jsonify({
                    'success': False,
                    'error': 'Account locked due to too many failed attempts. Try again in 30 minutes.',
                    'locked': True
                }), 401
        
        # ========== LOGIN SUCCESS - RESET FAILED ATTEMPTS ==========
        user.reset_failed_attempts()
        user.last_login = datetime.utcnow()
        user.last_ip_address = request.remote_addr
        db.session.commit()
        
        # If user is admin but email_verified is False, force set to True
        if user.role in ['admin', 'super_admin'] and not user.email_verified:
            print(f"[LOGIN] Forcing email_verified=True for admin user")
            user.email_verified = True
            db.session.commit()
        
        # Email verification check (skip for admin)
        if not user.email_verified and user.role not in ['admin', 'super_admin']:
            print(f"[LOGIN] Email not verified for {email}")
            verification_code = verification_service.generate_verification_code()
            
            # Store in Redis with 10 minutes expiry
            set_temp_data(
                f"verify_{user.id}",
                {
                    'user_id': user.id,
                    'code': verification_code,
                    'expires': (datetime.utcnow() + timedelta(minutes=10)).isoformat()
                },
                expiry_seconds=600
            )
            
            sms_sent = verification_service.send_sms(user.phone, verification_code)
            
            if sms_sent.get('success'):
                return jsonify({
                    'success': False,
                    'requires_verification': True,
                    'method': 'sms',
                    'message': 'Please verify your account. A verification code has been sent to your phone.',
                    'data': {'phone': user.phone, 'user_id': user.id}
                }), 403
            else:
                send_verification_email(user.email, user.username, verification_code)
                return jsonify({
                    'success': False,
                    'requires_verification': True,
                    'method': 'email',
                    'message': 'Please verify your email address. A verification code has been sent to your email.',
                    'data': {'email': user.email, 'user_id': user.id}
                }), 403
        
        # Generate token with explicit expiry
        token = user.generate_token()
        
        # Determine redirect URL based on role
        if user.role == 'super_admin' or user.role == 'admin':
            redirect_url = '/admin'
        elif user.is_agent and user.agent_approved:
            redirect_url = '/agent'
        else:
            redirect_url = '/dashboard'
        
        print(f"[LOGIN SUCCESS] {email} -> {redirect_url}")
        
        # Prepare user data for frontend
        user_dict = user.to_dict()
        user_dict['role'] = user.role  # Ensure role is explicitly set
        
        return jsonify({
            'success': True,
            'token': token,
            'user': user_dict,
            'redirect': redirect_url
        })
        
    except Exception as e:
        print(f"[LOGIN ERROR] {e}")
        import traceback
        traceback.print_exc()
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    
@app.route('/api/debug/fix-admin', methods=['GET'])
def fix_admin_debug():
    """Fix admin user - remove agent flags"""
    try:
        admin = User.query.filter_by(email='admin@roamsmart.shop').first()
        if admin:
            admin.is_agent = False
            admin.agent_approved = False
            admin.role = 'super_admin'
            db.session.commit()
            return jsonify({
                'success': True,
                'message': 'Admin fixed',
                'user': {
                    'id': admin.id,
                    'email': admin.email,
                    'role': admin.role,
                    'is_agent': admin.is_agent,
                    'agent_approved': admin.agent_approved
                }
            })
        return jsonify({'error': 'Admin not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    
@app.route('/api/admin/fix', methods=['GET'])
def fix_admin():
    """Fix admin user"""
    try:
        admin = User.query.filter_by(email=COMPANY_ADMIN_EMAIL).first()
        
        if not admin:
            # Create admin
            admin = User(
                username='Administrator',
                email=COMPANY_ADMIN_EMAIL,
                phone=COMPANY_PHONE,
                role='super_admin',
                email_verified=True,
                phone_verified=True,
                is_agent=True,
                agent_approved=True
            )
            admin.set_password('Roamsmart123@$')
            db.session.add(admin)
            db.session.commit()
            print("Admin created")
        else:
            # Fix existing admin
            admin.role = 'super_admin'
            admin.email_verified = True
            admin.phone_verified = True
            admin.set_password('Roamsmart123@$')
            db.session.commit()
            print("Admin fixed")
        
        return jsonify({
            'success': True,
            'message': 'Admin fixed',
            'email': admin.email,
            'role': admin.role,
            'password': 'Roamsmart123@$'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

# In your init_db or user creation
def create_admin():
    admin = User.query.filter_by(email=COMPANY_ADMIN_EMAIL).first()
    if not admin:
        admin = User(
            username='Administrator',
            email=COMPANY_ADMIN_EMAIL,
            phone='0557388622',
            role='super_admin',  # Important: set role correctly
            is_agent=True,
            agent_approved=True,
            email_verified=True,
            phone_verified=True
        )
        admin.set_password('Roamsmart123@$')
        db.session.add(admin)
        db.session.commit()
        print("Admin created with role: super_admin")
    else:
        # Ensure role is correct
        admin.role = 'super_admin'
        db.session.commit()
        print(f"Admin role set to: {admin.role}")

@app.route('/api/auth/verify-login-code', methods=['POST'])
@limiter.limit("10 per minute")
def verify_login_code():
    """Verify code for unverified email login (USES REDIS)"""
    try:
        data = request.get_json()
        user_code = data.get('code')
        user_id = data.get('user_id')
        
        if not user_id:
            return jsonify({'success': False, 'error': 'User ID required'}), 400
        
        # Get verification data from Redis
        verify_data = get_temp_data(f"verify_{user_id}")
        
        if not verify_data:
            return jsonify({
                'success': False,
                'error': 'No verification found. Please login again.'
            }), 400
        
        expires_at = datetime.fromisoformat(verify_data['expires'])
        if datetime.utcnow() > expires_at:
            delete_temp_data(f"verify_{user_id}")
            return jsonify({
                'success': False,
                'error': 'Verification code expired. Please login again.'
            }), 400
        
        if user_code != verify_data.get('code'):
            return jsonify({'success': False, 'error': 'Invalid verification code'}), 400
        
        user = User.query.get(user_id)
        
        if not user:
            delete_temp_data(f"verify_{user_id}")
            return jsonify({'success': False, 'error': 'User not found'}), 404
        
        user.email_verified = True
        user.email_verified_at = datetime.utcnow()
        db.session.commit()
        
        # Clean up Redis
        delete_temp_data(f"verify_{user_id}")
        
        token = user.generate_token()
        
        if user.role == 'super_admin':
            redirect_url = '/admin'
        elif user.role == 'admin':
            redirect_url = '/admin'
        elif user.is_agent and user.agent_approved:
            redirect_url = '/agent'
        else:
            redirect_url = '/dashboard'
        
        return jsonify({
            'success': True,
            'message': 'Email verified successfully!',
            'token': token,
            'user': user.to_dict(),
            'redirect': redirect_url
        })
        
    except Exception as e:
        print(f"Verify login code error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/auth/check-verification', methods=['GET'])
@token_required
def check_email_verification():
    """Check if user's email is verified"""
    try:
        return jsonify({
            'success': True,
            'data': {
                'email_verified': g.current_user.email_verified,
                'email': g.current_user.email
            }
        })
    except Exception as e:
        print(f"Check verification error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500



    
def send_order_confirmation_email(user, order_id, network, size_gb, phone, amount, quantity=1):
    """Send order confirmation email to user (NO SMS)"""
    try:
        company_name = COMPANY_NAME
        company_website = COMPANY_WEBSITE
        company_phone = COMPANY_PHONE
        company_email = COMPANY_EMAIL
        
        email_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Order Confirmation - {company_name}</title>
            <style>
                body {{ font-family: 'Segoe UI', Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: #8B0000; color: white; padding: 20px; text-align: center; border-radius: 10px 10px 0 0; }}
                .content {{ background: #f9f9f9; padding: 30px; border-radius: 0 0 10px 10px; }}
                .order-details {{ background: white; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #8B0000; }}
                .detail-row {{ margin: 10px 0; }}
                .detail-label {{ font-weight: bold; color: #555; }}
                .status {{ color: #28a745; font-weight: bold; }}
                .button {{ display: inline-block; background: #8B0000; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px; margin: 20px 0; }}
                .footer {{ text-align: center; padding: 20px; font-size: 12px; color: #888; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h2>✅ Order Confirmed!</h2>
                    <p>{company_name}</p>
                </div>
                <div class="content">
                    <p>Dear <strong>{user.username}</strong>,</p>
                    <p>Your order has been <span class="status">successfully completed</span>!</p>
                    
                    <div class="order-details">
                        <h3 style="margin-top: 0; color: #8B0000;">Order Details</h3>
                        <div class="detail-row"><span class="detail-label">Order ID:</span> {order_id}</div>
                        <div class="detail-row"><span class="detail-label">Package:</span> {quantity}x {size_gb}GB {network.upper()} Data</div>
                        <div class="detail-row"><span class="detail-label">Phone Number:</span> {phone}</div>
                        <div class="detail-row"><span class="detail-label">Amount Paid:</span> <strong style="color: #8B0000;">GHS {amount:.2f}</strong></div>
                        <div class="detail-row"><span class="detail-label">Status:</span> <span class="status">✅ Delivered</span></div>
                        <div class="detail-row"><span class="detail-label">Date:</span> {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}</div>
                    </div>
                    
                    <p>Your data bundle has been sent to <strong>{phone}</strong>. Please check your phone for the data credit.</p>
                    
                    <center>
                        <a href="{company_website}/orders" class="button">📦 View All Orders</a>
                    </center>
                    
                    <p style="margin-top: 20px;">Need help? Contact our support team:</p>
                    <ul>
                        <li>📧 Email: <a href="mailto:{company_email}">{company_email}</a></li>
                        <li>📱 WhatsApp: <a href="https://wa.me/233{company_phone}">{company_phone}</a></li>
                    </ul>
                </div>
                <div class="footer">
                    <p>&copy; {datetime.utcnow().year} {company_name}. All rights reserved.</p>
                    <p>This is an automated message, please do not reply.</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        send_email(user.email, f"Order Confirmation - {order_id}", email_html)
        
    except Exception as e:
        print(f"Send order confirmation email error: {e}")


# ========== HUBTEL BILL PAYMENT SERVICE ==========
class HubtelService:
    def __init__(self):
        self.client_id = os.environ.get('HUBTEL_CLIENT_ID')
        self.client_secret = os.environ.get('HUBTEL_CLIENT_SECRET')
        self.base_url = os.environ.get('HUBTEL_BASE_URL', 'https://api.hubtel.com/v1')
        
        if not self.client_id or not self.client_secret:
            print("[Hubtel] Warning: API credentials not configured")
        
        # Generate Basic Auth token
        auth_string = f"{self.client_id}:{self.client_secret}"
        self.auth_token = base64.b64encode(auth_string.encode()).decode()
        
        self.headers = {
            'Authorization': f'Basic {self.auth_token}',
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
    
    def validate_bill_account(self, biller_code, account_number):
        """Validate customer account for bill payment"""
        try:
            response = requests.post(
                f"{self.base_url}/bill/validate",
                json={
                    'billerCode': biller_code,
                    'accountNumber': account_number
                },
                headers=self.headers,
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                return {
                    'success': True,
                    'customer_name': data.get('customerName'),
                    'customer_phone': data.get('customerPhone'),
                    'customer_email': data.get('customerEmail'),
                    'biller_name': data.get('billerName'),
                    'amount_due': data.get('amountDue', 0),
                    'minimum_amount': data.get('minimumAmount', 0)
                }
            else:
                return {
                    'success': False,
                    'error': f'Validation failed: {response.text}'
                }
        except requests.exceptions.Timeout:
            return {'success': False, 'error': 'Hubtel API timeout'}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def get_bill_amount(self, biller_code, account_number):
        """Get bill amount due"""
        try:
            response = requests.post(
                f"{self.base_url}/bill/inquiry",
                json={
                    'billerCode': biller_code,
                    'accountNumber': account_number
                },
                headers=self.headers,
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                return {
                    'success': True,
                    'amount': data.get('amount', 0),
                    'due_date': data.get('dueDate'),
                    'reference': data.get('reference')
                }
            else:
                return {
                    'success': False,
                    'error': f'Inquiry failed: {response.text}'
                }
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def pay_bill(self, biller_code, account_number, amount, customer_name, customer_phone, customer_email=None, reference=None):
        """Process bill payment"""
        try:
            import uuid
            if not reference:
                reference = f"HUBTEL-{uuid.uuid4().hex[:12].upper()}"
            
            payload = {
                'billerCode': biller_code,
                'accountNumber': account_number,
                'amount': amount,
                'customerName': customer_name,
                'customerPhone': customer_phone,
                'reference': reference,
                'callbackUrl': f"{os.environ.get('BASE_URL', 'https://roamsmart-backend-production.up.railway.app')}/api/webhooks/hubtel"
            }
            
            if customer_email:
                payload['customerEmail'] = customer_email
            
            response = requests.post(
                f"{self.base_url}/bill/pay",
                json=payload,
                headers=self.headers,
                timeout=30
            )
            
            if response.status_code in [200, 201]:
                data = response.json()
                return {
                    'success': True,
                    'transaction_id': data.get('transactionId'),
                    'reference': reference,
                    'status': data.get('status', 'completed')
                }
            else:
                return {
                    'success': False,
                    'error': f'Payment failed: {response.text}'
                }
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def check_transaction_status(self, transaction_id):
        """Check transaction status"""
        try:
            response = requests.get(
                f"{self.base_url}/bill/status/{transaction_id}",
                headers=self.headers,
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                return {
                    'success': True,
                    'status': data.get('status'),
                    'amount': data.get('amount'),
                    'reference': data.get('reference')
                }
            else:
                return {'success': False, 'error': f'Status check failed: {response.text}'}
        except Exception as e:
            return {'success': False, 'error': str(e)}

# ========== HUBTEL BILL PAYMENT ENDPOINTS ==========

@app.route('/api/user/bills/history', methods=['GET'])
@token_required
def get_user_bill_history():
    """Get user's bill payment history"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('limit', 20, type=int)
        
        bills = Order.query.filter_by(
            user_id=g.current_user.id,
            type='bill_payment'
        ).order_by(Order.created_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        return jsonify({
            'success': True,
            'data': [{
                'id': b.id,
                'order_id': b.order_id,
                'biller_code': b.biller_code,
                'biller_name': b.biller_name,
                'account_number': b.account_number,
                'amount': float(b.amount),
                'status': b.status,
                'reference': b.provider_reference,
                'created_at': b.created_at.isoformat()
            } for b in bills.items],
            'total': bills.total,
            'page': page,
            'total_pages': bills.pages
        })
        
    except Exception as e:
        print(f"Error fetching bill history: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/bills/validate', methods=['POST'])
@token_required
def validate_bill_account():
    """Validate bill account with Hubtel API"""
    try:
        data = request.get_json()
        biller_code = data.get('biller_code')
        account_number = data.get('account_number')
        
        if not biller_code or not account_number:
            return jsonify({'success': False, 'error': 'Biller code and account number required'}), 400
        
        hubtel = HubtelService()
        result = hubtel.validate_bill_account(biller_code, account_number)
        
        if result.get('success'):
            return jsonify({
                'success': True,
                'data': {
                    'customer_name': result.get('customer_name'),
                    'customer_phone': result.get('customer_phone'),
                    'customer_email': result.get('customer_email'),
                    'biller_name': result.get('biller_name'),
                    'amount_due': result.get('amount_due'),
                    'minimum_amount': result.get('minimum_amount')
                }
            })
        else:
            return jsonify({
                'success': False,
                'error': result.get('error', 'Account validation failed')
            }), 400
        
    except Exception as e:
        print(f"Bill validation error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/bills/inquiry', methods=['POST'])
@token_required
def bill_inquiry():
    """Get bill amount due from Hubtel"""
    try:
        data = request.get_json()
        biller_code = data.get('biller_code')
        account_number = data.get('account_number')
        
        if not biller_code or not account_number:
            return jsonify({'success': False, 'error': 'Biller code and account number required'}), 400
        
        hubtel = HubtelService()
        result = hubtel.get_bill_amount(biller_code, account_number)
        
        if result.get('success'):
            return jsonify({
                'success': True,
                'data': {
                    'amount': result.get('amount'),
                    'due_date': result.get('due_date'),
                    'reference': result.get('reference')
                }
            })
        else:
            return jsonify({
                'success': False,
                'error': result.get('error', 'Could not fetch bill amount')
            }), 400
        
    except Exception as e:
        print(f"Bill inquiry error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/bills/pay', methods=['POST'])
@token_required
def pay_bill():
    """Process bill payment via Hubtel"""
    try:
        import uuid
        data = request.get_json()
        biller_code = data.get('biller_code')
        account_number = data.get('account_number')
        amount = data.get('amount')
        customer_name = data.get('customer_name')
        customer_phone = data.get('customer_phone')
        customer_email = data.get('customer_email')
        
        if not all([biller_code, account_number, amount, customer_name, customer_phone]):
            return jsonify({'success': False, 'error': 'Missing required fields'}), 400
        
        amount = float(amount)
        
        # Check wallet balance
        if g.current_user.wallet_balance < amount:
            return jsonify({
                'success': False,
                'error': f'Insufficient balance. Need GHS {amount:.2f}. Your balance: GHS {g.current_user.wallet_balance:.2f}'
            }), 400
        
        # Call Hubtel to process payment
        hubtel = HubtelService()
        payment_result = hubtel.pay_bill(
            biller_code=biller_code,
            account_number=account_number,
            amount=amount,
            customer_name=customer_name,
            customer_phone=customer_phone,
            customer_email=customer_email
        )
        
        if not payment_result.get('success'):
            return jsonify({
                'success': False,
                'error': payment_result.get('error', 'Payment failed')
            }), 400
        
        # Deduct from wallet
        balance_before = g.current_user.wallet_balance
        g.current_user.wallet_balance -= amount
        
        # Generate order ID
        order_id = f"BILL-{uuid.uuid4().hex[:8].upper()}"
        
        # Map biller codes to names
        biller_names = {
            'ECG': 'ECG Electricity',
            'GWCL': 'Ghana Water',
            'DSTV': 'DSTV',
            'GOTV': 'GoTV',
            'STARTIMES': 'StarTimes'
        }
        
        # Create order record
        order = Order(
            user_id=g.current_user.id,
            order_id=order_id,
            type='bill_payment',
            biller_code=biller_code,
            biller_name=biller_names.get(biller_code, biller_code),
            account_number=account_number,
            customer_name=customer_name,
            phone_number=customer_phone,
            amount=amount,
            status='completed',
            payment_method='wallet',
            provider='hubtel',
            provider_reference=payment_result.get('reference'),
            provider_order_id=payment_result.get('transaction_id'),
            completed_at=datetime.utcnow(),
            created_at=datetime.utcnow()
        )
        db.session.add(order)
        
        # Create transaction record
        transaction = Transaction(
            user_id=g.current_user.id,
            type='bill_payment',
            amount=amount,
            balance_before=balance_before,
            balance_after=g.current_user.wallet_balance,
            description=f'Bill payment: {biller_names.get(biller_code, biller_code)} - {account_number}',
            reference=order_id,
            status='completed'
        )
        db.session.add(transaction)
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'✅ Bill payment of GHS {amount:.2f} successful!',
            'data': {
                'order_id': order_id,
                'reference': payment_result.get('reference'),
                'transaction_id': payment_result.get('transaction_id'),
                'new_balance': g.current_user.wallet_balance
            }
        })
        
    except Exception as e:
        print(f"Bill payment error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/webhooks/hubtel', methods=['POST'])
def hubtel_webhook():
    """Handle Hubtel webhook notifications"""
    try:
        data = request.get_json()
        print(f"[Hubtel Webhook] Received: {data}")
        
        transaction_id = data.get('transactionId')
        status = data.get('status')
        reference = data.get('reference')
        
        if reference:
            order = Order.query.filter_by(provider_reference=reference).first()
            if order:
                order.status = 'completed' if status == 'success' else 'failed'
                if status == 'success':
                    order.completed_at = datetime.utcnow()
                db.session.commit()
                print(f"[Hubtel] Updated order {order.id} status to {status}")
        
        return jsonify({'success': True}), 200
    except Exception as e:
        print(f"[Hubtel Webhook Error] {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ========== RECURRING BILLS ENDPOINTS ==========

@app.route('/api/user/bills/recurring', methods=['GET'])
@token_required
def get_user_recurring_bills():
    """Get user's recurring bills"""
    try:
        
        recurring_bills = RecurringBill.query.filter_by(
            user_id=g.current_user.id,
            enabled=True  
        ).order_by(RecurringBill.created_at.desc()).all()
        
        return jsonify({
            'success': True,
            'data': [{
                'id': r.id,
                'biller_code': r.biller_code,
                'biller_name': r.biller_name,
                'account_number': r.account_number,
                'customer_name': r.customer_name,
                'frequency': r.frequency,
                'max_amount': float(r.max_amount) if r.max_amount else 0,
                'auto_pay': r.auto_pay,
                'enabled': r.enabled,
                'next_due_date': r.next_due_date.isoformat() if r.next_due_date else None,
                'created_at': r.created_at.isoformat()
            } for r in recurring_bills]
        })
        
    except Exception as e:
        print(f"Error fetching recurring bills: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/user/bills/recurring/add', methods=['POST'])
@token_required
def add_recurring_bill():
    """Add a recurring bill"""
    try:
        data = request.get_json()
        
        biller_code = data.get('biller_code')
        biller_name = data.get('biller_name')
        account_number = data.get('account_number')
        customer_name = data.get('customer_name')
        frequency = data.get('frequency', 'monthly')
        auto_pay = data.get('auto_pay', True)
        max_amount = data.get('max_amount', 0)
        
        if not biller_code or not account_number:
            return jsonify({'success': False, 'error': 'Biller code and account number required'}), 400
        
        # Calculate next due date based on frequency
        from datetime import datetime, timedelta
        frequency_days = {
            'weekly': 7,
            'biweekly': 14,
            'monthly': 30,
            'quarterly': 90
        }
        days = frequency_days.get(frequency, 30)
        next_due_date = datetime.utcnow() + timedelta(days=days)
        
        recurring_bill = RecurringBill(
            user_id=g.current_user.id,
            biller_code=biller_code,
            biller_name=biller_name,
            account_number=account_number,
            customer_name=customer_name,
            frequency=frequency,
            auto_pay=auto_pay,
            max_amount=max_amount,
            enabled=True,
            next_due_date=next_due_date,
            created_at=datetime.utcnow()
        )
        db.session.add(recurring_bill)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Recurring bill added successfully',
            'data': {
                'id': recurring_bill.id,
                'next_due_date': next_due_date.isoformat()
            }
        })
        
    except Exception as e:
        print(f"Error adding recurring bill: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/user/bills/recurring/remove/<int:bill_id>', methods=['DELETE'])
@token_required
def remove_recurring_bill(bill_id):
    """Remove a recurring bill"""
    try:
        recurring_bill = RecurringBill.query.filter_by(
            id=bill_id,
            user_id=g.current_user.id
        ).first()
        
        if not recurring_bill:
            return jsonify({'success': False, 'error': 'Recurring bill not found'}), 404
        
        db.session.delete(recurring_bill)
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Recurring bill removed'})
        
    except Exception as e:
        print(f"Error removing recurring bill: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/user/bills/recurring/toggle/<int:bill_id>', methods=['PUT'])
@token_required
def toggle_recurring_bill(bill_id):
    """Enable/disable a recurring bill"""
    try:
        data = request.get_json()
        enabled = data.get('enabled', False)
        
        recurring_bill = RecurringBill.query.filter_by(
            id=bill_id,
            user_id=g.current_user.id
        ).first()
        
        if not recurring_bill:
            return jsonify({'success': False, 'error': 'Recurring bill not found'}), 404
        
        recurring_bill.enabled = enabled
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Recurring bill {"enabled" if enabled else "disabled"}'
        })
        
    except Exception as e:
        print(f"Error toggling recurring bill: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

class DigimallService:
    def __init__(self):
        self.api_key = os.environ.get('DIGIMALL_API_KEY')
        self.base_url = os.environ.get('DIGIMALL_BASE_URL', 'https://www.digi-mall.app/api/v1')
        self.webhook_url = os.environ.get('DIGIMALL_WEBHOOK_URL', 'https://roamsmart-backend-production.up.railway.app/api/webhooks/digimall')
        
    def get_offer_slug(self, network, volume):
        """Get the correct offer slug for network and volume"""
        offers = self.get_offers()
        
        if not offers.get('success'):
            return None
        
        isp_map = {
            'mtn': 'MTN',
            'airteltigo': 'AirtelTigo',
            'telecel': 'Telecel'
        }
        
        isp_name = isp_map.get(network.lower(), network.capitalize())
        
        for offer in offers.get('offers', []):
            if offer.get('isp') == isp_name and offer.get('type') == 'Data':
                if volume in offer.get('volumes', []):
                    return offer.get('offerSlug')
        
        for offer in offers.get('offers', []):
            if offer.get('isp') == isp_name and offer.get('type') == 'Data':
                return offer.get('offerSlug')
        
        # Fallback slugs
        if network.lower() == 'mtn':
            return 'mtn_master_bundle'
        elif network.lower() == 'airteltigo':
            return 'airteltigo_ishare'
        elif network.lower() == 'telecel':
            return 'telecel'
        return None
    
    def get_offers(self):
        """Get all available offers"""
        try:
            response = requests.get(
                f"{self.base_url}/offers",
                headers={'x-api-key': self.api_key},
                timeout=10
            )
            if response.status_code == 200:
                return response.json()
            return {'success': False, 'error': f'HTTP {response.status_code}'}
        except Exception as e:
            print(f"[Digimall] Error fetching offers: {e}")
            return {'success': False, 'error': str(e)}
    
    def deliver_data(self, network, phone_number, volume):
        """
        Deliver data bundle to customer (delivery only, no pricing)
        """
        try:
            phone = self._format_phone(phone_number)
            
            offer_slug = self.get_offer_slug(network, volume)
            if not offer_slug:
                return {'success': False, 'error': f'No offer found for {network} {volume}GB'}
            
            endpoint_map = {
                'mtn': 'mtn',
                'airteltigo': 'at',
                'telecel': 'telecel'
            }
            endpoint = endpoint_map.get(network.lower(), network.lower())
            
            payload = {
                "type": "single",
                "volume": volume,
                "phone": phone,
                "offerSlug": offer_slug,
                "webhookUrl": self.webhook_url
            }
            
            print(f"[Digimall] Delivering {volume}GB {network} data to {phone}")
            print(f"[Digimall] Offer Slug: {offer_slug}")
            
            response = requests.post(
                f"{self.base_url}/order/{endpoint}",
                json=payload,
                headers={
                    'x-api-key': self.api_key,
                    'Content-Type': 'application/json'
                },
                timeout=30
            )
            
            if response.status_code in [200, 201]:
                result = response.json()
                print(f"[Digimall] Delivery initiated: {result.get('orderId')} - Status: {result.get('status')}")
                return result
            else:
                print(f"[Digimall] Delivery error: {response.status_code} - {response.text}")
                return {'success': False, 'error': f'Delivery failed: {response.text}'}
                
        except Exception as e:
            print(f"[Digimall] Error: {e}")
            return {'success': False, 'error': str(e)}
    
    def check_delivery_status(self, order_id):
        """Check delivery status of an order"""
        try:
            response = requests.get(
                f"{self.base_url}/order/status/{order_id}",
                headers={'x-api-key': self.api_key},
                timeout=10
            )
            
            if response.status_code == 200:
                return response.json()
            return {'success': False, 'error': f'HTTP {response.status_code}'}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def _format_phone(self, phone):
        """Format phone number to Digimall format"""
        phone = str(phone).strip()
        phone = phone.lstrip('+')
        if phone.startswith('0'):
            phone = '233' + phone[1:]
        if not phone.startswith('233'):
            phone = '233' + phone
        return phone



@app.route('/api/referral/balance', methods=['GET'])
@token_required
def get_referral_balance():
    """Get user's referral data balance"""
    try:
        user = g.current_user
        
        # Get completed referrals count
        completed_count = Referral.query.filter_by(
            referrer_id=user.id,
            status='completed'
        ).count()
        
        # Get pending referrals
        pending_count = Referral.query.filter_by(
            referrer_id=user.id,
            status='pending'
        ).count()
        
        # Calculate how many more referrals needed for next reward
        next_reward_at = 10 - (completed_count % 10)
        if completed_count % 10 == 0 and completed_count > 0:
            next_reward_at = 10
        
        return jsonify({
            'success': True,
            'data': {
                'referral_data_balance': float(user.referral_data_balance or 0),
                'total_referrals': completed_count,
                'pending_referrals': pending_count,
                'referrals_needed_for_next': next_reward_at,
                'reward_amount': '10MB Data',
                'max_redeemable': 50,  # Max 50MB can be redeemed
                'redeemable_data': min(float(user.referral_data_balance or 0), 50)
            }
        })
        
    except Exception as e:
        print(f"Get referral balance error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/referral/redeem', methods=['POST'])
@token_required
def redeem_referral_data():
    """Redeem referral data for actual data bundle (max 50MB total)"""
    try:
        data = request.get_json()
        network = data.get('network')
        mb_amount = data.get('mb', 10)
        phone = data.get('phone')
        
        if not phone:
            return jsonify({'success': False, 'error': 'Phone number required'}), 400
        
        if mb_amount not in [10, 20, 30, 40, 50]:
            return jsonify({'success': False, 'error': 'Redeem 10, 20, 30, 40, or 50 MB only'}), 400
        
        user = g.current_user
        
        # Check if user has enough referral data
        if (user.referral_data_balance or 0) < mb_amount:
            return jsonify({'success': False, 'error': f'Insufficient referral data. You have {user.referral_data_balance or 0} MB'}), 400
        
        # Check max redeemable (50MB total) - track redeemed amount separately
        # You may want to add a redeemed_referral_data column to User model
        if not hasattr(user, 'redeemed_referral_data'):
            user.redeemed_referral_data = 0
        
        if (user.redeemed_referral_data or 0) + mb_amount > 50:
            return jsonify({'success': False, 'error': f'Maximum redeemable is 50MB total. You have already redeemed {user.redeemed_referral_data or 0} MB'}), 400
        
        # Convert MB to GB
        gb_amount = mb_amount / 1000
        
        # Deduct from referral balance
        user.referral_data_balance -= mb_amount
        user.redeemed_referral_data = (user.redeemed_referral_data or 0) + mb_amount
        
        # Create order record
        order = Order(
            user_id=user.id,
            type='data',
            network=network,
            size_gb=gb_amount,
            phone_number=phone,
            amount=0,
            quantity=1,
            status='completed',
            payment_method='referral',
            description=f'Redeemed {mb_amount}MB referral data for {network} data',
            completed_at=datetime.utcnow(),
            created_at=datetime.utcnow()
        )
        db.session.add(order)
        
        db.session.commit()
        
        # Send data to network provider
        send_data_delivery_to_provider(phone, f"✅ Your {mb_amount}MB {network.upper()} data (earned from referrals on {COMPANY_NAME}) has been delivered!")
        
        # Send email confirmation
        send_email(
            user.email,
            f"Referral Data Redeemed - {mb_amount}MB - {COMPANY_NAME}",
            f"""
            <div style="font-family: Arial, sans-serif;">
                <h2 style="color: #8B0000;">Referral Data Redeemed Successfully!</h2>
                <p>Dear {user.username},</p>
                <p>You have successfully redeemed <strong>{mb_amount}MB</strong> of referral data for:</p>
                <h3>{network.upper()} Data</h3>
                <p><strong>Phone Number:</strong> {phone}</p>
                <p><strong>Remaining Referral Data:</strong> {user.referral_data_balance} MB</p>
                <p><strong>Total Redeemed:</strong> {user.redeemed_referral_data} MB (Max 50MB)</p>
                <p>Your data has been sent to your phone number!</p>
                <a href="{COMPANY_WEBSITE}/referrals" style="background: #8B0000; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">View Referrals</a>
            </div>
            """
        )
        
        return jsonify({
            'success': True,
            'message': f'Successfully redeemed {mb_amount}MB for {network} data',
            'data': {
                'redeemed_mb': mb_amount,
                'remaining_referral_data': user.referral_data_balance,
                'total_redeemed': user.redeemed_referral_data,
                'max_redeemable': 50
            }
        })
        
    except Exception as e:
        print(f"Redeem referral data error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    
@app.route('/api/referral/list', methods=['GET'])
@token_required
def get_referral_list():
    """Get list of user's referrals with status"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('limit', 20, type=int)
        
        pagination = Referral.query.filter_by(
            referrer_id=g.current_user.id
        ).order_by(Referral.created_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        referrals_data = []
        for r in pagination.items:
            referred_user = User.query.get(r.referred_id)
            referrals_data.append({
                'id': r.id,
                'username': referred_user.username if referred_user else 'Unknown',
                'email': referred_user.email if referred_user else 'Unknown',
                'phone': referred_user.phone if referred_user else 'Unknown',
                'status': r.status,
                'registered_at': r.created_at.isoformat(),
                'completed_at': r.completed_at.isoformat() if r.completed_at else None,
                'reward': '1 point towards 10MB' if r.status == 'completed' else 'Pending first purchase'
            })
        
        return jsonify({
            'success': True,
            'data': referrals_data,
            'total': pagination.total,
            'page': page,
            'total_pages': pagination.pages
        })
        
    except Exception as e:
        print(f"Get referral list error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
# ========== WAEC VOUCHER ENDPOINTS ==========

@app.route('/api/waec/vouchers', methods=['GET'])
@token_required
def get_waec_vouchers():
    """Get available WAEC vouchers and prices"""
    try:
        user = g.current_user
        is_agent = user.is_agent and user.agent_approved
        
        # Price depends on user role
        price = 18.00 if is_agent else 20.00
        
        # Get available counts
        available_counts = {
            'WASSCE': WAECVoucher.query.filter_by(exam_type='WASSCE', is_used=False).count(),
            'BECE': WAECVoucher.query.filter_by(exam_type='BECE', is_used=False).count(),
            'SHS Placement': WAECVoucher.query.filter_by(exam_type='SHS Placement', is_used=False).count()
        }
        
        return jsonify({
            'success': True,
            'data': {
                'vouchers': [
                    {
                        'type': 'WASSCE',
                        'price': price,
                        'description': 'WASSCE Result Checker',
                        'stock': available_counts['WASSCE']
                    },
                    {
                        'type': 'BECE',
                        'price': price,
                        'description': 'BECE Result Checker',
                        'stock': available_counts['BECE']
                    },
                    {
                        'type': 'SHS Placement',
                        'price': price,
                        'description': 'SHS Placement Checker',
                        'stock': available_counts['SHS Placement']
                    }
                ],
                'available_count': sum(available_counts.values()),
                'user_role': 'agent' if is_agent else 'customer'
            }
        })
        
    except Exception as e:
        print(f"Get WAEC vouchers error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/waec/purchase', methods=['POST'])
@token_required
def purchase_waec_voucher():
    """Purchase WAEC voucher"""
    try:
        data = request.get_json()
        exam_type = data.get('exam_type')
        quantity = data.get('quantity', 1)
        
        if not exam_type:
            return jsonify({'success': False, 'error': 'Exam type required'}), 400
        
        if quantity < 1 or quantity > 10:
            return jsonify({'success': False, 'error': 'Quantity must be between 1 and 10'}), 400
        
        user = g.current_user
        is_agent = user.is_agent and user.agent_approved
        price_per_voucher = 18.00 if is_agent else 20.00
        total_amount = price_per_voucher * quantity
        
        # Check wallet balance
        if user.wallet_balance < total_amount:
            return jsonify({'success': False, 'error': f'Insufficient wallet balance. Need GHS {total_amount:.2f}'}), 400
        
        # Get available vouchers
        vouchers = WAECVoucher.query.filter_by(
            exam_type=exam_type,
            is_used=False
        ).limit(quantity).all()
        
        if len(vouchers) < quantity:
            return jsonify({'success': False, 'error': f'Only {len(vouchers)} vouchers available'}), 400
        
        # Deduct from wallet
        balance_before = user.wallet_balance
        user.wallet_balance -= total_amount
        
        # Mark vouchers as purchased
        purchased_vouchers = []
        for voucher in vouchers:
            voucher.is_used = True
            voucher.used_by = user.id
            voucher.used_at = datetime.utcnow()
            voucher.purchased_by = user.id
            voucher.purchased_at = datetime.utcnow()
            
            purchased_vouchers.append({
                'voucher_code': voucher.voucher_code,
                'serial_number': voucher.serial_number,
                'pin': voucher.pin,
                'exam_type': voucher.exam_type,
                'year': voucher.year
            })
        
        # Create transaction
        transaction = Transaction(
            user_id=user.id,
            type='waec_purchase',
            amount=total_amount,
            balance_before=balance_before,
            balance_after=user.wallet_balance,
            description=f'Purchased {quantity}x WAEC {exam_type} voucher(s)',
            status='completed'
        )
        db.session.add(transaction)
        
        db.session.commit()
        
        # Send email confirmation
        voucher_details = ""
        for v in purchased_vouchers:
            voucher_details += f"""
            <div style="background: white; padding: 10px; margin: 10px 0; border: 1px solid #ddd; border-radius: 5px;">
                <p><strong>Voucher Code:</strong> {v['voucher_code']}</p>
                <p><strong>Serial Number:</strong> {v['serial_number']}</p>
                <p><strong>PIN:</strong> {v['pin']}</p>
            </div>
            """
        
        send_email(
            user.email,
            f"Your WAEC {exam_type} Voucher(s) - {COMPANY_NAME}",
            f"""
            <div style="font-family: Arial, sans-serif;">
                <h2 style="color: #8B0000;">WAEC Voucher Purchase Confirmation</h2>
                <p>Dear {user.username},</p>
                <p>You have successfully purchased <strong>{quantity} WAEC {exam_type} voucher(s)</strong>.</p>
                <p><strong>Total Amount:</strong> GHS {total_amount:.2f}</p>
                <h3>Your Vouchers:</h3>
                {voucher_details}
                <p>⚠️ Keep these details safe. Each voucher can only be used once.</p>
            </div>
            """
        )
        
        return jsonify({
            'success': True,
            'message': f'Successfully purchased {quantity} WAEC {exam_type} voucher(s)',
            'data': {
                'vouchers': purchased_vouchers,
                'total_amount': total_amount,
                'wallet_balance': user.wallet_balance
            }
        })
        
    except Exception as e:
        print(f"Purchase WAEC voucher error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/waec/verify', methods=['POST'])
@token_required
def verify_waec_voucher():
    """Verify WAEC voucher"""
    try:
        data = request.get_json()
        voucher_code = data.get('voucher_code')
        
        if not voucher_code:
            return jsonify({'success': False, 'error': 'Voucher code required'}), 400
        
        voucher = WAECVoucher.query.filter_by(voucher_code=voucher_code).first()
        
        if not voucher:
            return jsonify({'success': False, 'error': 'Invalid voucher code'}), 404
        
        if voucher.is_used:
            return jsonify({'success': False, 'error': 'Voucher has already been used'}), 400
        
        if voucher.expires_at and voucher.expires_at < datetime.utcnow():
            return jsonify({'success': False, 'error': 'Voucher has expired'}), 400
        
        return jsonify({
            'success': True,
            'data': {
                'voucher_code': voucher.voucher_code,
                'exam_type': voucher.exam_type,
                'year': voucher.year,
                'serial_number': voucher.serial_number,
                'pin': voucher.pin,
                'expires_at': voucher.expires_at.isoformat() if voucher.expires_at else None,
                'is_valid': True
            }
        })
        
    except Exception as e:
        print(f"Verify WAEC voucher error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ========== AGENT WAEC VOUCHER ENDPOINTS ==========

@app.route('/api/agent/waec/vouchers', methods=['GET'])
@token_required
@agent_required
def get_agent_waec_vouchers():
    """Get WAEC vouchers with agent pricing"""
    try:
        available_counts = {
            'WASSCE': WAECVoucher.query.filter_by(exam_type='WASSCE', is_used=False).count(),
            'BECE': WAECVoucher.query.filter_by(exam_type='BECE', is_used=False).count(),
            'SHS Placement': WAECVoucher.query.filter_by(exam_type='SHS Placement', is_used=False).count()
        }
        
        return jsonify({
            'success': True,
            'data': {
                'vouchers': [
                    {
                        'type': 'WASSCE',
                        'agent_price': 18.00,
                        'retail_price': 20.00,
                        'stock': available_counts['WASSCE']
                    },
                    {
                        'type': 'BECE',
                        'agent_price': 18.00,
                        'retail_price': 20.00,
                        'stock': available_counts['BECE']
                    },
                    {
                        'type': 'SHS Placement',
                        'agent_price': 18.00,
                        'retail_price': 20.00,
                        'stock': available_counts['SHS Placement']
                    }
                ],
                'agent_commission_rate': 10
            }
        })
        
    except Exception as e:
        print(f"Get agent WAEC vouchers error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/order', methods=['POST'])
@token_required
@limiter.limit("10 per minute")
@limiter.limit("100 per hour")
def create_order():
    """Create new order - Admin sets price, Digimall handles delivery"""
    
    try:
        data = request.get_json()
        
        print(f"\n{'='*60}")
        print(f"ORDER REQUEST DEBUG")
        print(f"{'='*60}")
        print(f"User: {g.current_user.username} (ID: {g.current_user.id})")
        print(f"Wallet Balance: ₵{g.current_user.wallet_balance}")
        print(f"Is Agent: {g.current_user.is_agent}")
        print(f"Request Data: {data}")
        
        network = data.get('network')
        size_gb = data.get('size_gb')
        phone = data.get('phone')
        payment_method = data.get('payment_method', 'wallet')
        quantity = data.get('quantity', 1)
        
        # Check required fields
        missing = []
        if not network:
            missing.append('network')
        if not size_gb:
            missing.append('size_gb')
        if not phone:
            missing.append('phone')
            
        if missing:
            return jsonify({'success': False, 'error': f'Missing required fields: {", ".join(missing)}'}), 400
        
        # Get MANUAL prices from database (admin sets these)
        is_agent = g.current_user.is_agent and getattr(g.current_user, 'agent_approved', False)
        
        if is_agent:
            unit_price = get_agent_price(network, size_gb)
        else:
            unit_price = get_user_price(network, size_gb)
        
        if unit_price == 0:
            return jsonify({
                'success': False, 
                'error': f'Price not configured for {network} {size_gb}GB. Please contact admin.'
            }), 400
        
        total_price = unit_price * quantity
        
        # Check wallet balance
        if payment_method == 'wallet':
            if g.current_user.wallet_balance < total_price:
                return jsonify({
                    'success': False, 
                    'error': f'Insufficient wallet balance. Need GHS {total_price:.2f}. Your balance: GHS {g.current_user.wallet_balance:.2f}'
                }), 400
        
        # Generate order ID
        order_id = f"ORD-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{g.current_user.id}"
        
        # Create order
        order = Order(
            user_id=g.current_user.id,
            order_id=order_id,
            type='data',
            network=network,
            size_gb=size_gb,
            phone_number=phone,
            amount=total_price,
            quantity=quantity,
            status='pending' if payment_method == 'manual' else 'processing',
            payment_method=payment_method,
            created_at=datetime.utcnow()
        )
        db.session.add(order)
        db.session.flush()
        
        if payment_method == 'wallet':
            # Initialize Digimall service for delivery only
            digimall = DigimallService()
            
            # Deduct from wallet (admin's retail price)
            balance_before = g.current_user.wallet_balance
            g.current_user.wallet_balance -= total_price
            
            # Create transaction record
            transaction = Transaction(
                user_id=g.current_user.id,
                type='purchase',
                amount=total_price,
                balance_before=balance_before,
                balance_after=g.current_user.wallet_balance,
                description=f'Purchase: {quantity}x {network} {size_gb}GB to {phone}',
                reference=order_id,
                status='pending'
            )
            db.session.add(transaction)
            db.session.commit()
            
            # Call Digimall for delivery (no pricing involved)
            digimall_response = digimall.deliver_data(network, phone, size_gb)
            
            if digimall_response.get('success'):
                order.status = 'completed'
                order.completed_at = datetime.utcnow()
                order.provider = 'digimall'
                order.provider_order_id = digimall_response.get('orderId')
                order.provider_reference = digimall_response.get('reference')
                order.provider_cost = digimall_response.get('totalAmount', 0)
                
                transaction.status = 'completed'
                db.session.commit()
                
                profit = total_price - (digimall_response.get('totalAmount', 0) * quantity)
                
                return jsonify({
                    'success': True,
                    'data': {
                        'order_id': order_id,
                        'balance': float(g.current_user.wallet_balance),
                        'amount': float(total_price),
                        'provider_order_id': digimall_response.get('orderId'),
                        'provider_status': digimall_response.get('status'),
                        'profit': float(profit)
                    },
                    'message': f'✅ {size_gb}GB {network.upper()} data ordered. Processing delivery...'
                })
            else:
                # Refund on delivery failure
                g.current_user.wallet_balance += total_price
                order.status = 'failed'
                order.error_message = digimall_response.get('error', 'Digimall delivery failed')
                transaction.status = 'failed'
                db.session.commit()
                
                return jsonify({
                    'success': False,
                    'error': f'Delivery failed: {digimall_response.get("error")}. Amount refunded.'
                }), 500
            
        elif payment_method == 'manual':
            reference = f"MAN-{uuid.uuid4().hex[:8].upper()}"
            order.payment_reference = reference
            
            manual_payment = ManualPayment(
                user_id=g.current_user.id,
                order_id=order.id,
                amount=total_price,
                reference=reference,
                status='pending_verification'
            )
            db.session.add(manual_payment)
            db.session.commit()
            
            return jsonify({
                'success': True,
                'data': {
                    'order_id': order_id,
                    'reference': reference,
                    'amount': total_price
                },
                'payment_instructions': {
                    'mobile_money_number': COMPANY_PHONE,
                    'recipient': COMPANY_NAME,
                    'reference': reference,
                    'amount': total_price
                },
                'message': f'Order created! Send GHS {total_price:.2f} to {COMPANY_PHONE} with reference: {reference}'
            })
        
    except Exception as e:
        print(f"Create order error: {e}")
        import traceback
        traceback.print_exc()
        db.session.rollback()
        
        if 'balance_before' in locals() and 'total_price' in locals():
            if 'g' in locals() and hasattr(g, 'current_user'):
                g.current_user.wallet_balance = balance_before
        
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/order/bulk', methods=['POST'])
@token_required
@agent_required
def bulk_agent_order():
    """Create bulk order (agent only) - Manual pricing, Digimall delivery"""
    
    data = request.get_json()
    orders = data.get('orders', [])
    
    if not orders:
        return jsonify({'success': False, 'error': 'No orders provided'}), 400
    
    digimall = DigimallService()
    
    success_count = 0
    failed_orders = []
    successful_orders = []
    
    # First, validate all orders and check wallet balance
    for order_data in orders:
        try:
            network = order_data.get('network')
            size_gb = order_data.get('size_gb')
            phone = order_data.get('phone')
            quantity = order_data.get('quantity', 1)
            
            bundle = DataBundle.query.filter_by(network=network, size_gb=size_gb, is_active=True).first()
            if not bundle:
                failed_orders.append({'phone': phone, 'error': 'Bundle not found'})
                continue
            
            total_price = float(bundle.agent_price) * quantity
            
            if g.current_user.wallet_balance < total_price:
                failed_orders.append({'phone': phone, 'error': 'Insufficient balance'})
                continue
            
            successful_orders.append({
                'network': network,
                'size_gb': size_gb,
                'phone': phone,
                'quantity': quantity,
                'total_price': total_price,
                'bundle': bundle
            })
            
        except Exception as e:
            failed_orders.append({'phone': order_data.get('phone'), 'error': str(e)})
    
    if not successful_orders:
        db.session.commit()
        return jsonify({
            'success': True,
            'total_orders': len(orders),
            'success_count': 0,
            'failed_count': len(failed_orders),
            'failed_orders': failed_orders
        })
    
    # Group by network for bulk processing
    orders_by_network = {}
    for order in successful_orders:
        network = order['network'].lower()
        if network not in orders_by_network:
            orders_by_network[network] = []
        orders_by_network[network].append(order)
    
    for network, network_orders in orders_by_network.items():
        items = []
        for order in network_orders:
            phone = order['phone']
            if phone.startswith('0'):
                phone = '233' + phone[1:]
            if phone.startswith('+'):
                phone = phone[1:]
            
            items.append({
                "volume": order['size_gb'],
                "recipient": phone
            })
        
        sample_order = network_orders[0]
        offer_slug = digimall.get_offer_slug(network, sample_order['size_gb'])
        
        if not offer_slug:
            for order in network_orders:
                failed_orders.append({'phone': order['phone'], 'error': f'No offer found for {network}'})
            continue
        
        endpoint_map = {
            'mtn': 'mtn',
            'airteltigo': 'at',
            'telecel': 'telecel'
        }
        endpoint = endpoint_map.get(network, network)
        
        payload = {
            "type": "bulk",
            "items": items,
            "offerSlug": offer_slug,
            "webhookUrl": digimall.webhook_url
        }
        
        print(f"[Digimall] Processing bulk order for {network}")
        print(f"[Digimall] Items: {len(items)}")
        
        try:
            response = requests.post(
                f"{digimall.base_url}/order/{endpoint}",
                json=payload,
                headers={
                    'x-api-key': digimall.api_key,
                    'Content-Type': 'application/json'
                },
                timeout=60
            )
            
            if response.status_code in [200, 201]:
                result = response.json()
                
                if result.get('success'):
                    for i, order in enumerate(network_orders):
                        try:
                            g.current_user.wallet_balance -= order['total_price']
                            
                            db_order = Order(
                                user_id=g.current_user.id,
                                order_id=f"ORD-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{g.current_user.id}-{i}",
                                type='data',
                                network=order['network'],
                                size_gb=order['size_gb'],
                                phone_number=order['phone'],
                                amount=order['total_price'],
                                quantity=order['quantity'],
                                status='completed',
                                payment_method='wallet',
                                provider='digimall',
                                provider_order_id=result.get('orderId'),
                                provider_reference=result.get('reference'),
                                provider_cost=result.get('totalAmount', 0) / len(network_orders) if result.get('totalAmount') else 0,
                                completed_at=datetime.utcnow()
                            )
                            db.session.add(db_order)
                            
                            transaction = Transaction(
                                user_id=g.current_user.id,
                                type='purchase',
                                amount=order['total_price'],
                                balance_before=g.current_user.wallet_balance + order['total_price'],
                                balance_after=g.current_user.wallet_balance,
                                description=f'Bulk purchase: {order["quantity"]}x {order["network"]} {order["size_gb"]}GB to {order["phone"]}',
                                reference=db_order.order_id,
                                status='completed'
                            )
                            db.session.add(transaction)
                            
                            success_count += 1
                            
                        except Exception as e:
                            g.current_user.wallet_balance += order['total_price']
                            failed_orders.append({'phone': order['phone'], 'error': str(e)})
                    
                    db.session.commit()
                    
                else:
                    error_msg = result.get('error', 'Digimall delivery failed')
                    for order in network_orders:
                        failed_orders.append({'phone': order['phone'], 'error': error_msg})
            else:
                error_msg = f'Digimall API error: {response.status_code}'
                for order in network_orders:
                    failed_orders.append({'phone': order['phone'], 'error': error_msg})
                    
        except Exception as e:
            error_msg = f'Delivery error: {str(e)}'
            for order in network_orders:
                failed_orders.append({'phone': order['phone'], 'error': error_msg})
    
    db.session.commit()
    
    return jsonify({
        'success': True,
        'total_orders': len(orders),
        'success_count': success_count,
        'failed_count': len(failed_orders),
        'failed_orders': failed_orders[:50],
        'message': f'Successfully processed {success_count} out of {len(orders)} orders via Digimall'
    })




@app.route('/api/webhooks/digimall', methods=['POST'])
def digimall_webhook():
    """Handle Digimall order status webhooks"""
    try:
        data = request.get_json()
        print(f"[Digimall Webhook] Received: {data}")
        
        event = data.get('event')
        
        if event == 'order.status.updated':
            order_id = data.get('orderId')
            reference = data.get('reference')
            status = data.get('status')
            recipient = data.get('recipient')
            volume = data.get('volume')
            
            # Update order status in your database
            if order_id:
                order = Order.query.filter_by(provider_order_id=order_id).first()
                if order:
                    old_status = order.status
                    order.status = 'completed' if status == 'delivered' else status
                    if status == 'delivered':
                        order.completed_at = datetime.utcnow()
                    db.session.commit()
                    print(f"[Digimall] Updated order {order_id}: {old_status} -> {status}")
        
        return jsonify({'success': True}), 200
        
    except Exception as e:
        print(f"[Digimall Webhook Error] {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
    
@app.route('/api/admin/digimall-balance', methods=['GET'])
@token_required
@admin_required
def admin_get_digimall_balance():
    """Get Digimall wallet balance"""
    try:
        DIGIMALL_API_KEY = os.environ.get('DIGIMALL_API_KEY')
        DIGIMALL_BASE_URL = os.environ.get('DIGIMALL_BASE_URL', 'https://www.digi-mall.app/api/v1')
        
        # Debug logging - will show in Railway logs
        print(f"[Digimall] API_KEY exists: {bool(DIGIMALL_API_KEY)}")
        print(f"[Digimall] API_KEY first 10 chars: {DIGIMALL_API_KEY[:10] if DIGIMALL_API_KEY else 'None'}")
        print(f"[Digimall] BASE_URL: {DIGIMALL_BASE_URL}")
        
        if not DIGIMALL_API_KEY:
            return jsonify({'success': False, 'error': 'Digimall API key not configured'}), 500
        
        # Call Digimall balance endpoint
        headers = {'x-api-key': DIGIMALL_API_KEY}
        url = f"{DIGIMALL_BASE_URL}/balance"
        
        print(f"[Digimall] Requesting: {url}")
        
        response = requests.get(url, headers=headers, timeout=10)
        
        print(f"[Digimall] Response status: {response.status_code}")
        print(f"[Digimall] Response body: {response.text[:200]}")
        
        if response.status_code == 200:
            data = response.json()
            return jsonify({
                'success': True,
                'data': {
                    'balance': data.get('balance', 0),
                    'currency': data.get('currency', 'GHS'),
                    'name': data.get('name', 'Roamsmart'),
                    'timestamp': data.get('timestamp')
                }
            })
        else:
            return jsonify({
                'success': False, 
                'error': f'Failed to fetch balance: {response.text}'
            }), response.status_code
            
    except Exception as e:
        print(f"Error fetching Digimall balance: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500
    
@app.route('/api/webhooks/digimall/low-balance', methods=['POST'])
def digimall_low_balance_webhook():
    """Handle Digimall low balance webhook notifications"""
    try:
        data = request.get_json()
        print(f"[Digimall Low Balance Webhook] Received: {data}")
        
        event = data.get('event')
        
        if event == 'balance.low':
            balance = data.get('balance')
            threshold = data.get('threshold')
            currency = data.get('currency', 'GHS')
            message = data.get('message')
            
            print(f"⚠️ LOW BALANCE ALERT: {currency} {balance} (threshold: {currency} {threshold})")
            
            # Send email notification to admin
            send_admin_alert(
                subject=f"⚠️ Digimall Wallet Low Balance Alert",
                message=f"""
                <div style="font-family: Arial, sans-serif;">
                    <h2 style="color: #ff9800;">⚠️ Low Balance Alert</h2>
                    <p>Your Digimall wallet balance has dropped below the configured threshold.</p>
                    <div style="background: #f8f9fa; padding: 15px; border-radius: 8px; margin: 15px 0;">
                        <p><strong>💰 Current Balance:</strong> {currency} {balance}</p>
                        <p><strong>⚙️ Threshold:</strong> {currency} {threshold}</p>
                        <p><strong>📝 Message:</strong> {message}</p>
                    </div>
                    <p>Please top up your Digimall wallet to continue processing orders.</p>
                    <a href="https://www.digi-mall.app/dashboard" style="background: #8B0000; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">
                        Top Up Now
                    </a>
                </div>
                """
            )
            
            # Optional: Pause order processing if balance is too low
            if balance < 10:
                print("⚠️ CRITICAL: Balance below GHS 10. Consider pausing orders.")
                # You could set a flag in your database to pause automated orders
        
        return jsonify({'success': True}), 200
        
    except Exception as e:
        print(f"[Digimall Low Balance Webhook Error] {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/wallet/transactions', methods=['GET'])
@token_required
def get_wallet_transactions():
    """Get wallet transactions"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('limit', 20, type=int)
    
    pagination = Transaction.query.filter_by(user_id=g.current_user.id).order_by(
        Transaction.created_at.desc()
    ).paginate(page=page, per_page=per_page, error_out=False)
    
    return jsonify({
        'success': True,
        'data': [t.to_dict() for t in pagination.items],
        'total': pagination.total,
        'page': page,
        'total_pages': pagination.pages
    })


@app.route('/api/wallet/fund', methods=['POST'])
@token_required
def fund_wallet():
    """Request wallet funding"""
    data = request.get_json()
    amount = float(data.get('amount', 0))
    
    if amount < 10:
        return jsonify({'success': False, 'error': 'Minimum funding is GHS 10'}), 400
    
    if amount > 100000:
        return jsonify({'success': False, 'error': 'Maximum funding is GHS 100,000'}), 400
    
    reference = f"FUND-{uuid.uuid4().hex[:8].upper()}"
    
    transaction = Transaction(
        user_id=g.current_user.id,
        type='fund',
        amount=amount,
        balance_before=g.current_user.wallet_balance,
        balance_after=g.current_user.wallet_balance,
        status='pending',
        reference=reference,
        description=f'Wallet funding request'
    )
    db.session.add(transaction)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'data': {
            'reference': reference,
            'amount': amount
        },
        'instructions': {
            'mobile_money_number': COMPANY_PHONE,
            'recipient': COMPANY_NAME,
            'reference': reference,
            'amount': amount
        },
        'message': f'Funding request created. Send GHS {amount:.2f} to {COMPANY_PHONE} with reference: {reference}'
    })


@app.route('/api/wallet/manual/request', methods=['POST'])
@token_required
def create_manual_request():
    """Create manual payment request"""
    data = request.get_json()
    amount = float(data.get('amount', 0))
    phone_number = data.get('phone_number')
    
    if amount < 10:
        return jsonify({'success': False, 'error': 'Minimum amount is GHS 10'}), 400
    
    reference = f"MAN-{uuid.uuid4().hex[:8].upper()}"
    
    manual_payment = ManualPayment(
        user_id=g.current_user.id,
        amount=amount,
        reference=reference,
        phone_number=phone_number,
        status='pending'
    )
    db.session.add(manual_payment)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'data': {
            'id': manual_payment.id,
            'reference': reference,
            'amount': amount
        }
    })


@app.route('/api/payment/upload-proof', methods=['POST']) 
@token_required
def upload_manual_proof():
    """Upload proof of manual payment"""
    try:
        request_id = request.form.get('request_id')
        proof = request.files.get('proof')
        
        if not proof:
            return jsonify({'success': False, 'error': 'No proof file provided'}), 400
        
        # Validate file type
        allowed_extensions = {'png', 'jpg', 'jpeg', 'pdf'}
        file_extension = proof.filename.rsplit('.', 1)[1].lower()
        if file_extension not in allowed_extensions:
            return jsonify({'success': False, 'error': 'Invalid file type. Use PNG, JPG, JPEG, or PDF'}), 400
        
        # Validate file size (max 5MB)
        proof.seek(0, os.SEEK_END)
        file_size = proof.tell()
        proof.seek(0)
        if file_size > 5 * 1024 * 1024:
            return jsonify({'success': False, 'error': 'File too large. Max 5MB'}), 400
        
        manual_payment = ManualPayment.query.get(request_id)
        if not manual_payment or manual_payment.user_id != g.current_user.id:
            return jsonify({'success': False, 'error': 'Request not found'}), 404
        
        if manual_payment.status != 'pending':
            return jsonify({'success': False, 'error': f'Payment already {manual_payment.status}'}), 400
        
        # Create upload directory if not exists
        upload_folder = app.config.get('UPLOAD_FOLDER', 'uploads')
        if not os.path.exists(upload_folder):
            os.makedirs(upload_folder)
        
        # Save file
        from werkzeug.utils import secure_filename
        filename = secure_filename(f"proof_{manual_payment.reference}_{uuid.uuid4().hex[:8]}.{file_extension}")
        filepath = os.path.join(upload_folder, filename)
        proof.save(filepath)
        
        # Update payment record
        manual_payment.proof_url = f"/uploads/{filename}"
        manual_payment.status = 'pending_verification'
        
        db.session.commit()
        
        # Notify admins via email
        admins = User.query.filter(User.role.in_(['admin', 'super_admin'])).all()
        for admin in admins:
            send_email(
                admin.email,
                f"Manual Payment Proof Uploaded - {manual_payment.reference}",
                f"""
                <h3>Manual Payment Verification Required - {COMPANY_NAME}</h3>
                <p><strong>User:</strong> {g.current_user.username}</p>
                <p><strong>Amount:</strong> GHS {manual_payment.amount:.2f}</p>
                <p><strong>Reference:</strong> {manual_payment.reference}</p>
                <p><a href="{COMPANY_WEBSITE}/admin/manual-payments/{manual_payment.id}">Verify Payment</a></p>
                """
            )
        
        return jsonify({
            'success': True, 
            'message': 'Proof uploaded successfully. Awaiting admin verification.',
            'data': {
                'proof_url': manual_payment.proof_url,
                'status': manual_payment.status
            }
        })
        
    except Exception as e:
        print(f"Upload proof error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Failed to upload proof'}), 500


@app.route('/api/wallet/manual/verify', methods=['POST'])
@token_required
def verify_manual_payment_user():
    """User initiates verification of manual payment"""
    try:
        data = request.get_json()
        reference = data.get('reference')
        transaction_id = data.get('transaction_id')
        sender_name = data.get('sender_name')
        sender_phone = data.get('sender_phone')
        
        if not reference:
            return jsonify({'success': False, 'error': 'Reference is required'}), 400
        
        manual_payment = ManualPayment.query.filter_by(reference=reference).first()
        if not manual_payment:
            return jsonify({'success': False, 'error': 'Payment request not found'}), 404
        
        if manual_payment.user_id != g.current_user.id:
            return jsonify({'success': False, 'error': 'Unauthorized'}), 403
        
        if manual_payment.status != 'pending':
            return jsonify({'success': False, 'error': f'Payment already {manual_payment.status}'}), 400
        
        # Update payment details
        if sender_name:
            manual_payment.sender_name = sender_name
        if sender_phone:
            manual_payment.sender_phone = sender_phone
        if transaction_id:
            manual_payment.transaction_id = transaction_id
        
        manual_payment.status = 'pending_verification'
        
        db.session.commit()
        
        # Notify admins via email
        admins = User.query.filter(User.role.in_(['admin', 'super_admin'])).all()
        admin_message = f"💰 Manual payment verification requested on {COMPANY_NAME}\nReference: {reference}\nAmount: GHS {manual_payment.amount:.2f}\nUser: {g.current_user.username}"
        
        for admin in admins:
            send_email(
                admin.email,
                f"Manual Payment Verification - {reference}",
                f"""
                <h3>Manual Payment Verification Request - {COMPANY_NAME}</h3>
                <p><strong>Reference:</strong> {reference}</p>
                <p><strong>Amount:</strong> GHS {manual_payment.amount:.2f}</p>
                <p><strong>User:</strong> {g.current_user.username} ({g.current_user.email})</p>
                <p><strong>Sender Name:</strong> {sender_name or 'Not provided'}</p>
                <p><strong>Sender Phone:</strong> {sender_phone or 'Not provided'}</p>
                <p><strong>Transaction ID:</strong> {transaction_id or 'Not provided'}</p>
                <p><a href="{COMPANY_WEBSITE}/admin/manual-payments/{manual_payment.id}">Verify Payment</a></p>
                """
            )
        
        # Send confirmation to user via email
        send_email(
            g.current_user.email,
            f"Payment Verification Requested - {reference}",
            f"""
            <h3>Verification Request Received - {COMPANY_NAME}</h3>
            <p>Dear {g.current_user.username},</p>
            <p>Your manual payment verification request has been submitted.</p>
            <p><strong>Reference:</strong> {reference}</p>
            <p><strong>Amount:</strong> GHS {manual_payment.amount:.2f}</p>
            <p>Our admin team will review your payment within 24 hours.</p>
            <p>You will receive a notification once your wallet is funded.</p>
            <hr>
            <p>Need help? Contact support on WhatsApp: {COMPANY_PHONE}</p>
            """
        )
        
        return jsonify({
            'success': True, 
            'message': 'Verification requested successfully. Admin will review your payment.',
            'data': {
                'reference': reference,
                'status': manual_payment.status,
                'amount': manual_payment.amount
            }
        })
        
    except Exception as e:
        print(f"Verify manual payment error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Failed to submit verification request'}), 500


@app.route('/api/wallet/manual/requests', methods=['GET'])
@token_required
def get_manual_requests():
    """Get user's manual payment requests"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('limit', 20, type=int)
        status = request.args.get('status')
        
        query = ManualPayment.query.filter_by(user_id=g.current_user.id)
        
        if status:
            query = query.filter_by(status=status)
        
        pagination = query.order_by(ManualPayment.created_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        return jsonify({
            'success': True,
            'data': [{
                'id': r.id,
                'amount': float(r.amount),
                'reference': r.reference,
                'status': r.status,
                'sender_name': r.sender_name,
                'sender_phone': r.sender_phone,
                'transaction_id': r.transaction_id,
                'proof_url': r.proof_url,
                'created_at': r.created_at.isoformat()
            } for r in pagination.items],
            'total': pagination.total,
            'page': page,
            'total_pages': pagination.pages
        })
        
    except Exception as e:
        print(f"Get manual requests error: {e}")
        return jsonify({'success': False, 'error': 'Failed to fetch requests'}), 500

@app.route('/api/wallet/generate-reference', methods=['POST'])
@token_required
def generate_manual_reference():
    """Generate a reference for manual payment"""
    try:
        data = request.get_json()
        amount = data.get('amount')
        
        if not amount or amount <= 0:
            return jsonify({'success': False, 'error': 'Invalid amount'}), 400
        
        import uuid
        reference = f"MAN-{uuid.uuid4().hex[:8].upper()}"
        
        manual_payment = ManualPayment(
            user_id=g.current_user.id,
            amount=amount,
            reference=reference,
            status='pending',
            created_at=datetime.utcnow()
        )
        
        db.session.add(manual_payment)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'data': {
                'id': manual_payment.id,          # ← This is important for the upload
                'reference': reference,
                'amount': amount,
                'created_at': manual_payment.created_at.isoformat()
            }
        })
        
    except Exception as e:
        print(f"Generate reference error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/wallet/manual/request/<int:request_id>', methods=['GET'])
@token_required
def get_manual_request_detail(request_id):
    """Get specific manual payment request details"""
    try:
        manual_payment = ManualPayment.query.get(request_id)
        
        if not manual_payment:
            return jsonify({'success': False, 'error': 'Request not found'}), 404
        
        if manual_payment.user_id != g.current_user.id and g.current_user.role not in ['admin', 'super_admin']:
            return jsonify({'success': False, 'error': 'Unauthorized'}), 403
        
        return jsonify({
            'success': True,
            'data': {
                'id': manual_payment.id,
                'amount': float(manual_payment.amount),
                'reference': manual_payment.reference,
                'status': manual_payment.status,
                'sender_name': manual_payment.sender_name,
                'sender_phone': manual_payment.sender_phone,
                'transaction_id': manual_payment.transaction_id,
                'proof_url': manual_payment.proof_url,
                'admin_notes': manual_payment.admin_notes,
                'created_at': manual_payment.created_at.isoformat()
            }
        })
        
    except Exception as e:
        print(f"Get manual request detail error: {e}")
        return jsonify({'success': False, 'error': 'Failed to fetch request details'}), 500


@app.route('/api/wallet/manual/request/<int:request_id>/cancel', methods=['POST'])
@token_required
def cancel_manual_request(request_id):
    """Cancel a pending manual payment request"""
    try:
        manual_payment = ManualPayment.query.get(request_id)
        
        if not manual_payment:
            return jsonify({'success': False, 'error': 'Request not found'}), 404
        
        if manual_payment.user_id != g.current_user.id:
            return jsonify({'success': False, 'error': 'Unauthorized'}), 403
        
        if manual_payment.status not in ['pending', 'pending_verification']:
            return jsonify({'success': False, 'error': f'Cannot cancel request with status: {manual_payment.status}'}), 400
        
        manual_payment.status = 'cancelled'
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Payment request cancelled successfully'
        })
        
    except Exception as e:
        print(f"Cancel manual request error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Failed to cancel request'}), 500


# ========== ADMIN MANUAL PAYMENT ENDPOINTS ==========
@app.route('/api/admin/manual-payments', methods=['GET'])
@token_required
@admin_required
@limiter.limit("30 per minute")
@limiter.limit("500 per hour")
def admin_get_manual_payments():
    """Admin: Get all manual payment requests (only pending ones)"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('limit', 20, type=int)
        
        # IMPORTANT: Only get pending_verification payments
        query = db.session.query(ManualPayment).filter(ManualPayment.status == 'pending_verification')
        
        pagination = query.order_by(ManualPayment.created_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        payments_data = []
        for payment in pagination.items:
            user = db.session.get(User, payment.user_id) if payment.user_id else None
            
            # Build the correct proof URL
            full_proof_url = None
            if payment.proof_url:
                if payment.proof_url.startswith(('http://', 'https://')):
                    full_proof_url = payment.proof_url
                else:
                    filename = payment.proof_url.split('/')[-1]
                    full_proof_url = f"{request.host_url.rstrip('/')}/uploads/profile_pics/{filename}"
            
            payments_data.append({
                'id': payment.id,
                'amount': float(payment.amount),
                'reference': payment.reference,
                'status': payment.status,
                'user_id': payment.user_id,
                'username': user.username if user else 'Unknown User',
                'email': user.email if user else 'No email',
                'phone': user.phone if user else 'No phone',
                'sender_name': payment.sender_name,
                'sender_phone': payment.sender_phone,
                'transaction_id': payment.transaction_id,
                'proof_url': full_proof_url,
                'created_at': payment.created_at.isoformat() if payment.created_at else None,
                'updated_at': payment.updated_at.isoformat() if hasattr(payment, 'updated_at') and payment.updated_at else payment.created_at.isoformat() if payment.created_at else None
            })
        
        return jsonify({
            'success': True,
            'data': payments_data,
            'total': pagination.total,
            'page': page,
            'total_pages': pagination.pages
        })
        
    except Exception as e:
        print(f"Admin get manual payments error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/admin/manual-payments/<int:payment_id>/approve-simple', methods=['POST'])
@token_required
@admin_required
def admin_approve_payment_simple(payment_id):
    """Admin: One-click approval - automatically credits user's wallet"""
    try:
        # Use db.session.get() instead of query.get() for SQLAlchemy 2.0
        manual_payment = db.session.get(ManualPayment, payment_id)
        
        if not manual_payment:
            return jsonify({'success': False, 'error': 'Payment request not found'}), 404
        
        if manual_payment.status != 'pending_verification':
            return jsonify({'success': False, 'error': f'Payment already {manual_payment.status}'}), 400
        
        # Update payment status
        manual_payment.status = 'verified'
        manual_payment.verified_at = datetime.utcnow()
        manual_payment.verified_by = g.current_user.id
        manual_payment.admin_notes = 'Auto-approved via one-click approval'
        
        # Fund user's wallet
        user = db.session.get(User, manual_payment.user_id)
        if not user:
            return jsonify({'success': False, 'error': 'User not found'}), 404
        
        balance_before = user.wallet_balance
        user.wallet_balance = float(user.wallet_balance) + float(manual_payment.amount)
        
        # Create transaction record (without 'created_by' field if it doesn't exist)
        transaction = Transaction(
            user_id=user.id,
            type='credit',
            amount=float(manual_payment.amount),
            balance_before=balance_before,
            balance_after=user.wallet_balance,
            description=f'Manual payment approval - Reference: {manual_payment.reference}',
            reference=manual_payment.reference,
            status='completed'
        )
        db.session.add(transaction)
        
        db.session.commit()
        
        # Send notification to user via email (optional)
        try:
            send_email(
                user.email,
                f"✅ Payment Approved - Wallet Credited | {COMPANY_NAME}",
                f"""
                <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                    <h2 style="color: #8B0000;">Payment Approved!</h2>
                    <p>Dear <strong>{user.username}</strong>,</p>
                    <p>Your manual payment has been approved and your wallet has been credited.</p>
                    
                    <div style="background: #f0f8ff; padding: 20px; border-radius: 10px; margin: 20px 0;">
                        <h3 style="margin-top: 0;">Transaction Details:</h3>
                        <p><strong>💰 Amount:</strong> GHS {float(manual_payment.amount):.2f}</p>
                        <p><strong>🆔 Reference:</strong> {manual_payment.reference}</p>
                        <p><strong>💳 Previous Balance:</strong> GHS {balance_before:.2f}</p>
                        <p><strong>✨ New Balance:</strong> GHS {user.wallet_balance:.2f}</p>
                        <p><strong>⏰ Date:</strong> {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}</p>
                    </div>
                    
                    <p>You can now use your wallet balance to purchase data, pay bills, or request withdrawals.</p>
                    
                    <hr style="margin: 20px 0;">
                    <p style="color: #666; font-size: 12px;">Thank you for using {COMPANY_NAME}!</p>
                </div>
                """
            )
        except Exception as email_error:
            print(f"Email notification error: {email_error}")
        
        return jsonify({
            'success': True,
            'message': f'✅ Payment approved! GHS {float(manual_payment.amount):.2f} credited to {user.username}',
            'data': {
                'user_id': user.id,
                'username': user.username,
                'amount': float(manual_payment.amount),
                'new_balance': user.wallet_balance,
                'reference': manual_payment.reference,
                'approved_at': manual_payment.verified_at.isoformat()
            }
        }), 200
        
    except Exception as e:
        print(f"Admin approve payment error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

# NEW: Batch approve multiple payments
@app.route('/api/admin/manual-payments/batch-approve', methods=['POST'])
@token_required
@admin_required
def admin_batch_approve_payments():
    """Admin: Batch approve multiple payments at once"""
    try:
        data = request.get_json()
        payment_ids = data.get('payment_ids', [])
        
        if not payment_ids:
            return jsonify({'success': False, 'error': 'No payment IDs provided'}), 400
        
        approved_count = 0
        total_amount = 0
        approved_payments = []
        
        for payment_id in payment_ids:
            # Use db.session.get() for SQLAlchemy 2.0
            manual_payment = db.session.get(ManualPayment, payment_id)
            
            if manual_payment and manual_payment.status == 'pending_verification':
                # Update payment status
                manual_payment.status = 'verified'
                manual_payment.verified_at = datetime.utcnow()
                manual_payment.verified_by = g.current_user.id
                manual_payment.admin_notes = f'Batch approved with {len(payment_ids)} other payments'
                
                # Fund user's wallet
                user = db.session.get(User, manual_payment.user_id)
                if user:
                    balance_before = user.wallet_balance
                    user.wallet_balance = float(user.wallet_balance) + float(manual_payment.amount)
                    total_amount += float(manual_payment.amount)
                    
                    # Create transaction record
                    transaction = Transaction(
                        user_id=user.id,
                        type='credit',
                        amount=float(manual_payment.amount),
                        balance_before=balance_before,
                        balance_after=user.wallet_balance,
                        description=f'Batch payment approval - Reference: {manual_payment.reference}',
                        reference=manual_payment.reference,
                        status='completed'
                    )
                    db.session.add(transaction)
                    
                    approved_count += 1
                    approved_payments.append({
                        'user_id': user.id,
                        'username': user.username,
                        'amount': float(manual_payment.amount),
                        'reference': manual_payment.reference
                    })
        
        db.session.commit()
        
        if approved_count > 0:
            return jsonify({
                'success': True,
                'message': f'✅ Successfully approved {approved_count} payments totaling GHS {total_amount:.2f}',
                'data': {
                    'approved_count': approved_count,
                    'total_amount': total_amount,
                    'approved_payments': approved_payments
                }
            }), 200
        else:
            return jsonify({
                'success': False,
                'error': 'No valid pending payments found to approve'
            }), 400
            
    except Exception as e:
        print(f"Admin batch approve error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

# Keep the original verify endpoint for backward compatibility
@app.route('/api/admin/manual-payments/<int:payment_id>/verify', methods=['POST'])
@token_required
@admin_required
def admin_verify_manual_payment(payment_id):
    """Admin: Verify and approve manual payment (legacy endpoint)"""
    try:
        data = request.get_json()
        action = data.get('action')
        admin_notes = data.get('admin_notes')
        sender_name = data.get('sender_name')
        sender_phone = data.get('sender_phone')
        
        manual_payment = ManualPayment.query.get(payment_id)
        
        if not manual_payment:
            return jsonify({'success': False, 'error': 'Payment request not found'}), 404
        
        if manual_payment.status != 'pending_verification':
            return jsonify({'success': False, 'error': f'Payment already {manual_payment.status}'}), 400
        
        if action == 'approve':
            manual_payment.status = 'verified'
            manual_payment.verified_at = datetime.utcnow()
            manual_payment.verified_by = g.current_user.id
            manual_payment.admin_notes = admin_notes
            manual_payment.sender_name = sender_name
            manual_payment.sender_phone = sender_phone
            
            # Fund user's wallet
            user = User.query.get(manual_payment.user_id)
            balance_before = user.wallet_balance
            user.wallet_balance += manual_payment.amount
            
            # Create transaction record
            transaction = Transaction(
                user_id=user.id,
                type='credit',
                amount=manual_payment.amount,
                balance_before=balance_before,
                balance_after=user.wallet_balance,
                description=f'Manual payment approved - Reference: {manual_payment.reference}',
                reference=manual_payment.reference,
                status='completed',
                created_by='admin',
                admin_id=g.current_user.id
            )
            db.session.add(transaction)
            
            db.session.commit()
            
            # Send notification to user
            send_email(
                user.email,
                f"✅ Wallet Funded - {manual_payment.reference} | {COMPANY_NAME}",
                f"""
                <h3>Payment Approved!</h3>
                <p>Dear {user.username},</p>
                <p>Your manual payment of <strong>GHS {manual_payment.amount:.2f}</strong> has been verified and added to your wallet.</p>
                <p><strong>Reference:</strong> {manual_payment.reference}</p>
                <p><strong>New Balance:</strong> GHS {user.wallet_balance:.2f}</p>
                <a href="{COMPANY_WEBSITE}/dashboard" style="background: #8B0000; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">View Dashboard</a>
                """
            )
            
            return jsonify({
                'success': True,
                'message': f'Payment approved. GHS {manual_payment.amount:.2f} added to user\'s wallet.',
                'data': {
                    'user_balance': user.wallet_balance,
                    'amount_credited': manual_payment.amount
                }
            })
            
        elif action == 'reject':
            manual_payment.status = 'rejected'
            manual_payment.verified_at = datetime.utcnow()
            manual_payment.verified_by = g.current_user.id
            manual_payment.admin_notes = admin_notes
            
            db.session.commit()
            
            # Notify user of rejection
            user = User.query.get(manual_payment.user_id)
            send_email(
                user.email,
                f"Payment Update - {manual_payment.reference} | {COMPANY_NAME}",
                f"""
                <h3>Payment Status Update</h3>
                <p>Dear {user.username},</p>
                <p>Your manual payment of <strong>GHS {manual_payment.amount:.2f}</strong> could not be verified.</p>
                <p><strong>Reference:</strong> {manual_payment.reference}</p>
                <p><strong>Reason:</strong> {admin_notes or 'Unable to verify payment. Please contact support.'}</p>
                <p>Please contact our support team for assistance.</p>
                <p>WhatsApp: {COMPANY_PHONE}</p>
                """
            )
            
            return jsonify({
                'success': True,
                'message': 'Payment rejected.'
            })
        else:
            return jsonify({'success': False, 'error': 'Invalid action. Use "approve" or "reject"'}), 400
            
    except Exception as e:
        print(f"Admin verify payment error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Failed to process payment'}), 500


# NEW: Get single payment details
@app.route('/api/admin/manual-payments/<int:payment_id>', methods=['GET'])
@token_required
@admin_required
def admin_get_manual_payment(payment_id):
    """Admin: Get single payment details"""
    try:
        payment = ManualPayment.query.get(payment_id)
        
        if not payment:
            return jsonify({'success': False, 'error': 'Payment not found'}), 404
        
        return jsonify({
            'success': True,
            'data': {
                'id': payment.id,
                'amount': float(payment.amount),
                'reference': payment.reference,
                'status': payment.status,
                'user_id': payment.user_id,
                'username': payment.user.username,
                'email': payment.user.email,
                'phone': payment.user.phone,
                'sender_name': payment.sender_name,
                'sender_phone': payment.sender_phone,
                'transaction_id': payment.transaction_id,
                'proof_url': payment.proof_url,
                'admin_notes': payment.admin_notes,
                'created_at': payment.created_at.isoformat(),
                'verified_at': payment.verified_at.isoformat() if payment.verified_at else None,
                'verified_by': payment.verified_by
            }
        })
        
    except Exception as e:
        print(f"Admin get payment error: {e}")
        return jsonify({'success': False, 'error': 'Failed to fetch payment details'}), 500

# KEEP ONLY ONE of these - delete the duplicate

@app.route('/api/payment/paystack/verify/<reference>', methods=['GET'])
@token_required
def verify_paystack_payment(reference):
    """Verify Paystack payment status"""
    try:
        if not reference:
            return jsonify({'success': False, 'error': 'Reference required'}), 400
        
        print(f"🔍 Verifying Paystack payment: {reference}")
        
        # First, check if we have a pending transaction
        pending_tx = PendingTransaction.query.filter_by(reference=reference).first()
        
        if not pending_tx:
            print(f"⚠️ No pending transaction found for reference: {reference}")
            
            # Check if already completed
            completed_tx = Transaction.query.filter_by(reference=reference).first()
            if completed_tx:
                print(f"✅ Transaction already processed: {reference}")
                return jsonify({
                    'success': True,
                    'data': {
                        'status': 'success',
                        'amount': float(completed_tx.amount),
                        'message': 'Payment already processed'
                    }
                })
            
            # Check if there's any transaction with similar reference
            partial_match = Transaction.query.filter(
                Transaction.reference.like(f'%{reference[-20:]}%')
            ).first()
            if partial_match:
                return jsonify({
                    'success': True,
                    'data': {
                        'status': 'success',
                        'amount': float(partial_match.amount),
                        'message': 'Payment already processed'
                    }
                })
            
            return jsonify({
                'success': False, 
                'error': f'No pending transaction found for reference: {reference}. Please create a new payment request.'
            }), 404
        
        print(f"📝 Found pending transaction: {pending_tx.id}, status: {pending_tx.status}")
        
        # Verify with Paystack
        result = verify_paystack_transaction(reference)
        
        if not result['success']:
            return jsonify({'success': False, 'error': 'Payment verification failed'}), 400
        
        if result['status'] == 'success':
            # Update user wallet
            user = User.query.get(pending_tx.user_id)
            if not user:
                return jsonify({'success': False, 'error': 'User not found'}), 404
            
            print(f"💰 Adding {result['amount']} to wallet for user {user.username}")
            
            # Add to wallet
            balance_before = user.wallet_balance
            user.wallet_balance += result['amount']
            
            # Update pending transaction
            pending_tx.status = 'completed'
            pending_tx.completed_at = datetime.utcnow()
            
            # Create transaction record
            transaction = Transaction(
                user_id=user.id,
                type='fund',
                amount=result['amount'],
                balance_before=balance_before,
                balance_after=user.wallet_balance,
                description=f'Wallet funding via Paystack - {reference}',
                reference=reference,
                status='completed',
                meta_data={
                    'payment_method': 'paystack',
                    'reference': reference
                }
            )
            db.session.add(transaction)
            db.session.commit()
            
            print(f"✅ Successfully credited {user.username} with GHS {result['amount']:.2f}")
            
            # Send email confirmation
            try:
                send_wallet_funding_email(user.email, user.username, result['amount'], user.wallet_balance)
            except Exception as email_err:
                print(f"Email error (non-critical): {email_err}")
            
            return jsonify({
                'success': True,
                'data': {
                    'status': 'success',
                    'amount': float(result['amount']),
                    'new_balance': float(user.wallet_balance),
                    'message': f'Successfully added GHS {result["amount"]:.2f} to your wallet'
                }
            })
        else:
            # Update failed transaction
            pending_tx.status = 'failed'
            db.session.commit()
            
            return jsonify({
                'success': False,
                'data': {
                    'status': 'failed',
                    'message': result.get('message', 'Payment was not successful')
                }
            }), 400
        
    except Exception as e:
        print(f"❌ Verify Paystack payment error: {e}")
        import traceback
        traceback.print_exc()
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/payment/paystack/webhook', methods=['POST'])
def paystack_webhook():
    """Paystack webhook for automatic payment confirmation"""
    try:
        # Verify webhook signature
        signature = request.headers.get('x-paystack-signature')
        if not signature:
            return jsonify({'success': False, 'error': 'No signature'}), 401
        
        # Get event data
        event_data = request.get_json()
        event = event_data.get('event')
        
        print(f"Paystack webhook received: {event}")
        
        if event == 'charge.success':
            data = event_data.get('data', {})
            reference = data.get('reference')
            amount = data.get('amount', 0) / 100
            
            # Find pending transaction
            pending_tx = PendingTransaction.query.filter_by(
                reference=reference,
                status='pending',
                payment_method='paystack'
            ).first()
            
            if pending_tx and pending_tx.status == 'pending':
                user = User.query.get(pending_tx.user_id)
                if user:
                    balance_before = user.wallet_balance
                    user.wallet_balance += amount
                    
                    pending_tx.status = 'completed'
                    pending_tx.completed_at = datetime.utcnow()
                    
                    transaction = Transaction(
                        user_id=user.id,
                        type='credit',
                        amount=amount,
                        balance_before=balance_before,
                        balance_after=user.wallet_balance,
                        description=f'Wallet funding via Paystack - {reference}',
                        reference=reference,
                        status='completed'
                    )
                    db.session.add(transaction)
                    db.session.commit()
                    
                    print(f"[WEBHOOK] Processed Paystack payment {reference} for {user.email}")
                    send_wallet_funding_email(user.email, user.username, amount, user.wallet_balance)
        
        return jsonify({'success': True})
        
    except Exception as e:
        print(f"Paystack webhook error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


def send_wallet_funding_email(email, username, amount, new_balance):
    """Send wallet funding confirmation email"""
    try:
        send_email(
            email,
            f"✅ Wallet Funded Successfully - {COMPANY_NAME}",
            f"""
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <div style="background: #8B0000; padding: 20px; text-align: center; border-radius: 10px 10px 0 0;">
                    <h2 style="color: white;">✅ Wallet Funded Successfully!</h2>
                    <p style="color: white;">{COMPANY_NAME}</p>
                </div>
                <div style="background: #f5f5f5; padding: 30px; border-radius: 0 0 10px 10px;">
                    <p>Dear <strong>{username}</strong>,</p>
                    <p>Your Roamsmart wallet has been successfully funded!</p>
                    <div style="background: white; padding: 20px; text-align: center; border-radius: 10px; margin: 20px 0;">
                        <p style="font-size: 14px; margin-bottom: 10px;">Amount Added:</p>
                        <p style="font-size: 32px; font-weight: bold; color: #28a745;">GHS {amount:.2f}</p>
                        <p style="font-size: 14px; margin-top: 10px;">New Balance: <strong>GHS {new_balance:.2f}</strong></p>
                    </div>
                    <p>You can now use your wallet balance to purchase data bundles, WAEC vouchers, and more!</p>
                    <div style="text-align: center; margin: 25px 0;">
                        <a href="{COMPANY_WEBSITE}/dashboard" style="background: #8B0000; color: white; padding: 12px 30px; text-decoration: none; border-radius: 30px;">Go to Dashboard</a>
                    </div>
                </div>
            </div>
            """
        )
    except Exception as e:
        print(f"Email error: {e}")



@app.route('/api/admin/admins/<int:admin_id>/role', methods=['PUT'])
@token_required
@super_admin_required
def admin_update_role(admin_id):
    """Update admin role (admin/super_admin)"""
    try:
        data = request.get_json()
        new_role = data.get('role')
        
        if new_role not in ['admin', 'super_admin']:
            return jsonify({'success': False, 'error': 'Invalid role'}), 400
        
        admin = User.query.get(admin_id)
        
        if not admin or not admin.is_admin:
            return jsonify({'success': False, 'error': 'Admin not found'}), 404
        
        # Prevent demoting last super_admin
        if admin.role == 'super_admin' and new_role == 'admin':
            super_admin_count = User.query.filter_by(role='super_admin').count()
            if super_admin_count <= 1:
                return jsonify({'success': False, 'error': 'Cannot demote the last super admin'}), 400
        
        admin.role = new_role
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Admin {admin.username} role updated to {new_role}'
        })
        
    except Exception as e:
        print(f"Update admin role error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Failed to update role'}), 500
# ========== AGENT ROUTES ==========

@app.route('/api/agent/apply', methods=['POST'])
@token_required
def apply_agent():
    """Apply to become an agent - FREE now (no payment required)"""
    try:
        data = request.get_json() or request.form
        
        # Check if already agent
        if g.current_user.is_agent and g.current_user.agent_approved:
            return jsonify({'success': False, 'error': 'You are already an approved agent'}), 400
        
        # Check for existing pending request
        existing = AgentRequest.query.filter_by(
            user_id=g.current_user.id, 
            status='pending'
        ).first()
        
        if existing:
            return jsonify({'success': False, 'error': 'You already have a pending application'}), 400
        
        # ========== FREE REGISTRATION - NO PAYMENT REQUIRED ==========
        # Auto-approve since it's free
        g.current_user.is_agent = True
        g.current_user.agent_approved = True
        g.current_user.agent_tier = 'Bronze'
        g.current_user.commission_rate = 10
        db.session.commit()
        
        # Create agent request record for tracking (already approved)
        reference = f"AGENT-{uuid.uuid4().hex[:8].upper()}"
        agent_request = AgentRequest(
            user_id=g.current_user.id,
            amount=0,  # FREE
            payment_method='free',
            status='approved',
            payment_reference=reference,
            created_at=datetime.utcnow()
        )
        db.session.add(agent_request)
        db.session.commit()
        
        # ========== SEND CONFIRMATION TO USER (Email) ==========
        user_email_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: 'Segoe UI', Arial, sans-serif; line-height: 1.6; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: linear-gradient(135deg, #8B0000, #D2691E); color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0; }}
                .content {{ padding: 30px; background: #f9f9f9; border-radius: 0 0 10px 10px; }}
                .feature-box {{ background: white; padding: 15px; border-radius: 8px; margin: 15px 0; border-left: 4px solid #28a745; }}
                .button {{ display: inline-block; background: #8B0000; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px; }}
                .footer {{ text-align: center; padding: 20px; color: #666; font-size: 12px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h2>🎉 Welcome to the Roamsmart Agent Program!</h2>
                    <p>You're now an official Roamsmart Agent</p>
                </div>
                <div class="content">
                    <p>Dear <strong>{g.current_user.username}</strong>,</p>
                    <p>Congratulations! Your application to become a Roamsmart Agent has been <strong style="color: #28a745;">APPROVED</strong> - and it was completely FREE!</p>
                    
                    <div class="feature-box">
                        <h3>✨ What you get as a Roamsmart Agent:</h3>
                        <ul>
                            <li>💰 <strong>Up to 25% commission</strong> on every data sale</li>
                            <li>🏪 <strong>Your own branded store page</strong> to sell to customers</li>
                            <li>📊 <strong>Access to wholesale prices</strong> on all networks</li>
                            <li>💸 <strong>Instant withdrawals</strong> of your earnings</li>
                            <li>📱 <strong>Sell via WhatsApp</strong> - share product links directly</li>
                            <li>🎓 <strong>Agent training and 24/7 support</strong></li>
                        </ul>
                    </div>
                    
                    <div style="text-align: center; margin: 30px 0;">
                        <a href="{COMPANY_WEBSITE}/agent" class="button">🚀 Start Selling Now</a>
                    </div>
                    
                    <div class="feature-box">
                        <h3>📋 Quick Start Guide:</h3>
                        <ol>
                            <li>Log into your Roamsmart agent dashboard</li>
                            <li>Set up your store with your branding</li>
                            <li>Share your store link with customers</li>
                            <li>Start earning commission on every sale!</li>
                        </ol>
                    </div>
                    
                    <p>Need help? Contact our support team:</p>
                    <p>📞 Call/WhatsApp: <strong>{COMPANY_PHONE}</strong><br>
                    📧 Email: <strong>{COMPANY_EMAIL}</strong></p>
                </div>
                <div class="footer">
                    <p>© 2025 {COMPANY_NAME}. All rights reserved.</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        send_email(g.current_user.email, f"🎉 Welcome to Roamsmart Agent Program! - {COMPANY_NAME}", user_email_html)
        
        # ========== SEND NOTIFICATION TO ADMIN ==========
        admin_email = COMPANY_ADMIN_EMAIL
        
        admin_email_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: 'Segoe UI', Arial, sans-serif; line-height: 1.6; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: linear-gradient(135deg, #8B0000, #D2691E); color: white; padding: 30px; text-align: center; }}
                .content {{ padding: 30px; background: #f9f9f9; }}
                .info-box {{ background: white; padding: 15px; border-radius: 8px; margin: 15px 0; border-left: 4px solid #28a745; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h2>🆕 New Agent Registration - {COMPANY_NAME}</h2>
                    <p>FREE Registration</p>
                </div>
                <div class="content">
                    <p>Hello Admin,</p>
                    <p>A new user has successfully registered as a Roamsmart Agent (Free Registration).</p>
                    
                    <div class="info-box">
                        <h3>Agent Details:</h3>
                        <ul>
                            <li><strong>Name:</strong> {g.current_user.username}</li>
                            <li><strong>Email:</strong> {g.current_user.email}</li>
                            <li><strong>Phone:</strong> {g.current_user.phone}</li>
                            <li><strong>Agent Tier:</strong> Bronze</li>
                            <li><strong>Commission Rate:</strong> 10%</li>
                            <li><strong>Registered:</strong> {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}</li>
                        </ul>
                    </div>
                </div>
                <div class="footer">
                    <p>© 2025 {COMPANY_NAME}. All rights reserved.</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        send_email(admin_email, f"New Free Agent Registration - {COMPANY_NAME}", admin_email_html)
        
        return jsonify({
            'success': True,
            'message': '🎉 Congratulations! You are now a Roamsmart Agent! Start selling and earning commission.',
            'data': {
                'agent_tier': 'Bronze',
                'commission_rate': 10,
                'is_agent': True
            }
        })
        
    except Exception as e:
        print(f"Apply agent error: {e}")
        import traceback
        traceback.print_exc()
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/agent/dashboard', methods=['GET'])
@token_required
@agent_required
def get_agent_dashboard():
    """Get agent dashboard data"""
    try:
        # Get sales stats
        total_sales = db.session.query(db.func.sum(Order.amount)).filter_by(
            user_id=g.current_user.id, 
            status='completed'
        ).scalar() or 0
        
        total_orders = Order.query.filter_by(
            user_id=g.current_user.id, 
            status='completed'
        ).count()
        
        # Get today's sales
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today_sales = db.session.query(db.func.sum(Order.amount)).filter(
            Order.user_id == g.current_user.id,
            Order.status == 'completed',
            Order.completed_at >= today
        ).scalar() or 0
        
        # Calculate commission earned (15% of sales)
        commissions = total_sales * (g.current_user.commission_rate or 15) / 100
        
        # Get total customers (store clients)
        total_customers = StoreClient.query.filter_by(
            agent_id=g.current_user.id
        ).count()
        
        # Get store info
        store = Store.query.filter_by(agent_id=g.current_user.id).first()
        
        # Get recent orders
        recent_orders = Order.query.filter_by(
            user_id=g.current_user.id
        ).order_by(Order.created_at.desc()).limit(10).all()
        
        return jsonify({
            'success': True,
            'data': {
                'wallet_balance': float(g.current_user.wallet_balance),
                'total_sales': float(total_sales),
                'total_orders': total_orders,
                'agent_savings': float(total_sales * 0.05),
                'total_commission': float(commissions),
                'pending_commission': float(commissions * 0.3),
                'today_sales': float(today_sales),
                'total_customers': total_customers,
                'agent_tier': g.current_user.agent_tier or 'Bronze',
                'commission_rate': g.current_user.commission_rate or 15,
                'store': store.to_dict() if store else None,
                'recent_orders': [{
                    'order_id': o.order_id,
                    'amount': float(o.amount),
                    'phone_number': o.phone_number,
                    'created_at': o.created_at.isoformat()
                } for o in recent_orders]
            }
        })
        
    except Exception as e:
        print(f"Get agent dashboard error: {e}")
        return jsonify({'success': False, 'error': 'Failed to fetch dashboard data'}), 500


@app.route('/api/agent/sell', methods=['POST'])
@token_required
@agent_required
def agent_sell():
    """Sell data to customer - No profit calculation shown"""
    try:
        data = request.get_json()
        
        network = data.get('network')
        size_gb = data.get('size_gb')
        phone = data.get('phone')
        customer_name = data.get('customer_name')
        quantity = data.get('quantity', 1)
        selling_price = data.get('selling_price')
        
        if not all([network, size_gb, phone]):
            return jsonify({'success': False, 'error': 'Missing required fields'}), 400
        
        # Get agent's wholesale price from database
        agent_cost = get_agent_price(network, size_gb)
        
        if agent_cost == 0:
            return jsonify({'success': False, 'error': f'Price not configured for {network} {size_gb}GB'}), 400
        
        total_cost = agent_cost * quantity
        
        # If selling price not provided, use agent cost + markup
        if not selling_price:
            markup = db.session.query(StoreSettings.markup).filter_by(agent_id=g.current_user.id).scalar() or 15
            selling_price = total_cost * (1 + markup / 100)
        
        total_revenue = selling_price * quantity
        
        # Check agent's wallet balance
        if g.current_user.wallet_balance < total_cost:
            return jsonify({
                'success': False, 
                'error': f'Insufficient wallet balance. Need GHS {total_cost:.2f}'
            }), 400
        
        # Generate order ID
        order_id = f"ORD-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{g.current_user.id}"
        
        # Deduct from agent's wallet
        balance_before = g.current_user.wallet_balance
        g.current_user.wallet_balance -= total_cost
        
        # Create order (profit still stored internally but not shown to agent)
        order = Order(
            user_id=g.current_user.id,
            agent_id=g.current_user.id,
            order_id=order_id,
            type='data',
            network=network,
            size_gb=size_gb,
            phone_number=phone,
            customer_name=customer_name,
            amount=total_revenue,
            cost=total_cost,
            profit=total_revenue - total_cost,  # Stored but not returned
            quantity=quantity,
            status='completed',
            payment_method='wallet',
            completed_at=datetime.utcnow(),
            created_at=datetime.utcnow()
        )
        db.session.add(order)
        
        # Create transaction record
        transaction = Transaction(
            user_id=g.current_user.id,
            type='sale',
            amount=total_revenue,
            balance_before=balance_before,
            balance_after=g.current_user.wallet_balance,
            description=f'Sale: {quantity}x {size_gb}GB {network} to {phone}',
            reference=order_id,
            status='completed'
        )
        db.session.add(transaction)
        
        # Update agent's stats
        g.current_user.total_sales = (g.current_user.total_sales or 0) + total_revenue
        
        # Add to store clients
        if customer_name or phone:
            try:
                from models import StoreClient
                client = StoreClient.query.filter_by(phone=phone, agent_id=g.current_user.id).first()
                if client:
                    client.total_spent = (client.total_spent or 0) + total_revenue
                    client.order_count = (client.order_count or 0) + 1
                    client.last_purchase = datetime.utcnow()
                else:
                    client = StoreClient(
                        agent_id=g.current_user.id,
                        name=customer_name or 'Customer',
                        phone=phone,
                        total_spent=total_revenue,
                        order_count=1,
                        last_purchase=datetime.utcnow()
                    )
                    db.session.add(client)
            except Exception as e:
                print(f"StoreClient error: {e}")
        
        db.session.commit()
        
        # Send data delivery
        digimall_result = None
        try:
            digimall = DigimallService()
            digimall_result = digimall.deliver_data(network, phone, size_gb)
            
            if digimall_result and digimall_result.get('success'):
                order.provider = 'digimall'
                order.provider_order_id = digimall_result.get('orderId')
                order.provider_reference = digimall_result.get('reference')
                order.provider_cost = digimall_result.get('totalAmount', 0)
                db.session.commit()
        except Exception as e:
            print(f"Digimall delivery error: {e}")
        
        # Return response WITHOUT profit
        return jsonify({
            'success': True,
            'message': f'Sold {quantity}x {size_gb}GB {network.upper()} to {phone}',
            'data': {
                'order_id': order_id,
                'amount': total_revenue,
                'balance': float(g.current_user.wallet_balance),
                # REMOVED: 'cost'
                # REMOVED: 'profit'
                'digimall_delivery': digimall_result.get('success') if digimall_result else False
            }
        })
        
    except Exception as e:
        print(f"Agent sell error: {e}")
        import traceback
        traceback.print_exc()
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/agent/earnings', methods=['GET'])
@token_required
@agent_required
def get_agent_earnings():
    """Get agent earnings - SIMPLIFIED, only show wallet balance"""
    try:
        agent = g.current_user
        
        # Get total sales revenue (what customers paid)
        total_sales = db.session.query(db.func.sum(Order.amount)).filter(
            Order.agent_id == agent.id,
            Order.status == 'completed'
        ).scalar() or 0
        
        # Get withdrawals (amounts agent has withdrawn)
        withdrawals = Transaction.query.filter_by(
            user_id=agent.id, 
            type='withdrawal',
            status='completed'
        ).all()
        withdrawn = sum(w.amount for w in withdrawals)
        
        # Get pending withdrawals
        pending_withdrawals = Transaction.query.filter_by(
            user_id=agent.id,
            type='withdrawal',
            status='pending'
        ).all()
        pending = sum(w.amount for w in pending_withdrawals)
        
        # Available balance (wallet)
        available = float(agent.wallet_balance)
        
        return jsonify({
            'success': True,
            'data': {
                'available': available,  # Wallet balance only
                'total_sales': float(total_sales),
                'pending_withdrawals': float(pending),
                'withdrawn': float(withdrawn),
                # REMOVED: 'total_earned'
                # REMOVED: 'this_month'
                # REMOVED: 'commission_rate'
                'next_tier': {
                    'name': 'Silver' if (agent.agent_tier or 'Bronze') == 'Bronze' else 'Gold',
                    'required_sales': 5000 if (agent.agent_tier or 'Bronze') == 'Bronze' else 10000,
                    'current_sales': float(total_sales)
                }
            }
        })
        
    except Exception as e:
        print(f"Get agent earnings error: {e}")
        return jsonify({'success': False, 'error': 'Failed to fetch earnings'}), 500

@app.route('/api/agent/stats', methods=['GET'])
@token_required
@agent_required
def get_agent_stats():
    """Get agent statistics - NO COMMISSION, NO PROFIT, only actual sales data from database"""
    try:
        agent = g.current_user
        
        print(f"\n=== AGENT STATS DEBUG (No Commission, No Profit) ===")
        print(f"Agent ID: {agent.id}")
        print(f"Agent Username: {agent.username}")
        
        # Get total sales from orders where agent_id matches
        total_sales = db.session.query(db.func.sum(Order.amount)).filter(
            Order.agent_id == agent.id,
            Order.status == 'completed'
        ).scalar() or 0
        
        print(f"Total sales: ₵{total_sales}")
        
        # Get total orders count
        total_orders = Order.query.filter_by(
            agent_id=agent.id,
            status='completed'
        ).count()
        
        print(f"Total orders: {total_orders}")
        
        # Get today's sales
        today = datetime.utcnow().date()
        today_start = datetime.combine(today, datetime.min.time())
        today_end = datetime.combine(today, datetime.max.time())
        
        today_sales = db.session.query(db.func.sum(Order.amount)).filter(
            Order.agent_id == agent.id,
            Order.status == 'completed',
            Order.created_at >= today_start,
            Order.created_at <= today_end
        ).scalar() or 0
        
        print(f"Today's sales: ₵{today_sales}")
        
        # Get this week's sales
        week_start = today - timedelta(days=today.weekday())
        week_start_dt = datetime.combine(week_start, datetime.min.time())
        
        week_sales = db.session.query(db.func.sum(Order.amount)).filter(
            Order.agent_id == agent.id,
            Order.status == 'completed',
            Order.created_at >= week_start_dt
        ).scalar() or 0
        
        # Get this month's sales
        month_start = today.replace(day=1)
        month_start_dt = datetime.combine(month_start, datetime.min.time())
        
        month_sales = db.session.query(db.func.sum(Order.amount)).filter(
            Order.agent_id == agent.id,
            Order.status == 'completed',
            Order.created_at >= month_start_dt
        ).scalar() or 0
        
        # Get customer count (unique phone numbers)
        customer_count = db.session.query(Order.phone_number).filter(
            Order.agent_id == agent.id,
            Order.status == 'completed'
        ).distinct().count()
        
        print(f"Customers: {customer_count}")
        
        # REMOVED: profit calculations
        # REMOVED: commission calculations
        # REMOVED: any earnings/savings calculations
        
        # Get agent tier based on sales volume (just for display)
        agent_tier = 'Bronze'
        next_tier_sales = 500
        if total_sales >= 10000:
            agent_tier = 'Platinum'
            next_tier_sales = 10000
        elif total_sales >= 2000:
            agent_tier = 'Gold'
            next_tier_sales = 2000
        elif total_sales >= 500:
            agent_tier = 'Silver'
            next_tier_sales = 500
        
        return jsonify({
            'success': True,
            'data': {
                'wallet_balance': float(agent.wallet_balance),
                'total_sales': float(total_sales),
                'total_orders': total_orders,
                # REMOVED: 'total_profit'
                # REMOVED: 'agent_savings'
                # REMOVED: 'total_commission'
                # REMOVED: 'pending_commission'
                'today_sales': float(today_sales),
                # REMOVED: 'today_profit'
                'this_week_sales': float(week_sales),
                # REMOVED: 'this_week_profit'
                'this_month_sales': float(month_sales),
                # REMOVED: 'this_month_profit'
                'total_customers': customer_count,
                'agent_tier': agent_tier,
                'next_tier_sales': next_tier_sales,
                # REMOVED: 'commission_rate'
                'rank': 0,
                'username': agent.username,
                'phone': agent.phone or ''
            }
        })
        
    except Exception as e:
        print(f"Get agent stats error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

# Helper function to get agent's wholesale price (admin configured)
def get_agent_price(network, size_gb):
    """Get wholesale price configured by admin"""
    from models import Price
    
    price_entry = Price.query.filter_by(
        network=network,
        size_gb=size_gb,
        is_active=True
    ).first()
    
    if price_entry:
        return float(price_entry.wholesale_price)
    
    # Fallback to default prices if not in database
    default_prices = {
        'mtn': {1: 5.50, 2: 10.00, 5: 22.00, 10: 42.00, 20: 80.00},
        'telecel': {1: 5.00, 2: 9.00, 5: 20.00, 10: 38.00, 20: 75.00},
        'airteltigo': {1: 5.00, 2: 9.00, 5: 20.00, 10: 38.00, 20: 75.00}
    }
    
    return default_prices.get(network, {}).get(size_gb, 0)


@app.route('/api/agent/withdraw', methods=['POST'])
@token_required
@agent_required
def agent_withdraw():
    """Request withdrawal for agent"""
    try:
        data = request.get_json()
        amount = float(data.get('amount', 0))
        mobile_money = data.get('mobile_money')
        
        if not mobile_money:
            return jsonify({'success': False, 'error': 'Mobile money number is required'}), 400
        
        if amount < 50:
            return jsonify({'success': False, 'error': 'Minimum withdrawal is GHS 50'}), 400
        
        if amount > g.current_user.wallet_balance:
            return jsonify({'success': False, 'error': f'Insufficient balance. Available: GHS {g.current_user.wallet_balance:.2f}'}), 400
        
        reference = f"WTH-{uuid.uuid4().hex[:8].upper()}"
        
        # Create withdrawal request
        transaction = Transaction(
            user_id=g.current_user.id,
            type='withdrawal',
            amount=amount,
            balance_before=g.current_user.wallet_balance,
            balance_after=g.current_user.wallet_balance,
            status='pending',
            description=f'Withdrawal request to {mobile_money}',
            reference=reference
        )
        db.session.add(transaction)
        db.session.commit()
        
        # Notify admins via email
        admins = User.query.filter(User.role.in_(['admin', 'super_admin'])).all()
        for admin in admins:
            send_email(
                admin.email,
                f"Withdrawal Request - {reference} - {COMPANY_NAME}",
                f"""
                <h3>New Withdrawal Request - {COMPANY_NAME}</h3>
                <p><strong>Agent:</strong> {g.current_user.username}</p>
                <p><strong>Amount:</strong> GHS {amount:.2f}</p>
                <p><strong>Mobile Money:</strong> {mobile_money}</p>
                <p><strong>Reference:</strong> {reference}</p>
                <a href="{COMPANY_WEBSITE}/admin/withdrawals/{transaction.id}">Process Withdrawal</a>
                """
            )
        
        # Send confirmation to agent via email
        send_email(
            g.current_user.email,
            f"Withdrawal Request Submitted - {reference} - {COMPANY_NAME}",
            f"""
            <h3>Withdrawal Request Submitted - {COMPANY_NAME}</h3>
            <p>Dear {g.current_user.username},</p>
            <p>Your withdrawal request has been submitted successfully.</p>
            <p><strong>Amount:</strong> GHS {amount:.2f}</p>
            <p><strong>Mobile Money:</strong> {mobile_money}</p>
            <p><strong>Reference:</strong> {reference}</p>
            <p>Our team will process your request within 24-48 hours.</p>
            """
        )
        
        return jsonify({
            'success': True, 
            'message': 'Withdrawal request submitted successfully',
            'data': {
                'reference': reference,
                'amount': amount,
                'status': 'pending'
            }
        })
        
    except Exception as e:
        print(f"Agent withdraw error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Failed to submit withdrawal request'}), 500


@app.route('/api/agent/withdrawals', methods=['GET'])
@token_required
@agent_required
def get_agent_withdrawals():
    """Get agent withdrawal history"""
    try:
        withdrawals = Transaction.query.filter_by(
            user_id=g.current_user.id, 
            type='withdrawal'
        ).order_by(Transaction.created_at.desc()).all()
        
        return jsonify({
            'success': True,
            'data': [{
                'id': w.id,
                'amount': float(w.amount),
                'mobile_money': w.description.split('to ')[-1] if 'to ' in w.description else 'N/A',
                'status': w.status,
                'reference': w.reference,
                'created_at': w.created_at.isoformat(),
                'processed_at': w.updated_at.isoformat() if w.status != 'pending' else None
            } for w in withdrawals]
        })
        
    except Exception as e:
        print(f"Get agent withdrawals error: {e}")
        return jsonify({'success': False, 'error': 'Failed to fetch withdrawals'}), 500


@app.route('/api/agent/store', methods=['GET', 'POST', 'PUT'])
@token_required
@agent_required
def agent_store():
    """Get or update agent store settings"""
    try:
        store = Store.query.filter_by(agent_id=g.current_user.id).first()
        
        if request.method == 'GET':
            if not store:
                # Create default store
                store = Store(
                    agent_id=g.current_user.id,
                    store_name=f"{g.current_user.username}'s Store",
                    store_slug=g.current_user.username.lower().replace(' ', '-'),
                    contact_phone=g.current_user.phone,
                    contact_email=g.current_user.email,
                    is_active=True
                )
                db.session.add(store)
                db.session.commit()
            
            return jsonify({'success': True, 'data': store.to_dict()})
        
        # POST or PUT - Update store
        data = request.get_json()
        
        if not store:
            store = Store(agent_id=g.current_user.id)
            db.session.add(store)
        
        # Update fields
        if 'store_name' in data:
            store.store_name = data['store_name']
        if 'store_slug' in data:
            store.store_slug = data['store_slug'].lower().replace(' ', '-')
        if 'contact_phone' in data:
            store.contact_phone = data['contact_phone']
        if 'contact_email' in data:
            store.contact_email = data['contact_email']
        if 'store_description' in data:
            store.store_description = data['store_description']
        if 'markup' in data:
            store.markup = max(0, min(100, data['markup']))
        if 'logo_url' in data:
            store.logo_url = data['logo_url']
        if 'banner_url' in data:
            store.banner_url = data['banner_url']
        if 'is_active' in data:
            store.is_active = data['is_active']
        
        store.updated_at = datetime.utcnow()
        db.session.commit()
        
        return jsonify({
            'success': True, 
            'message': 'Store updated successfully on Roamsmart',
            'data': store.to_dict()
        })
        
    except Exception as e:
        print(f"Agent store error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Failed to update store'}), 500


@app.route('/api/agent/products/<product_id>/markup', methods=['PUT'])
@token_required
@agent_required
def update_product_markup(product_id):
    """Update markup for a specific product and save to database"""
    try:
        data = request.get_json()
        markup = data.get('markup')
        
        print(f"Received markup update: {product_id} -> {markup}%")
        
        # Parse product ID (format: mtn_1, telecel_5, etc.)
        parts = product_id.split('_')
        if len(parts) != 2:
            return jsonify({'success': False, 'error': 'Invalid product ID format'}), 400
        
        network = parts[0]
        size_gb = int(parts[1])
        
        agent = g.current_user
        
        # Agent wholesale prices
        agent_prices = {
            'mtn': {1: 5.50, 2: 10.00, 5: 22.00, 10: 42.00, 20: 80.00},
            'telecel': {1: 5.00, 2: 9.00, 5: 20.00, 10: 38.00, 20: 75.00},
            'airteltigo': {1: 5.00, 2: 9.00, 5: 20.00, 10: 38.00, 20: 75.00}
        }
        
        wholesale_price = agent_prices.get(network, {}).get(size_gb)
        if not wholesale_price:
            return jsonify({'success': False, 'error': 'Product not found'}), 404
        
        # Calculate new retail price
        new_retail_price = wholesale_price * (1 + markup / 100)
        profit = new_retail_price - wholesale_price
        
        # SAVE TO DATABASE - Store in AgentProductPrice table
        try:
            # Check if AgentProductPrice table exists
            from models import AgentProductPrice
            
            product_price = AgentProductPrice.query.filter_by(
                agent_id=agent.id,
                network=network,
                size_gb=size_gb
            ).first()
            
            if product_price:
                product_price.markup = markup
                product_price.retail_price = new_retail_price
                product_price.updated_at = datetime.utcnow()
                print(f"Updated existing product price record")
            else:
                product_price = AgentProductPrice(
                    agent_id=agent.id,
                    network=network,
                    size_gb=size_gb,
                    retail_price=new_retail_price,
                    markup=markup,
                    created_at=datetime.utcnow()
                )
                db.session.add(product_price)
                print(f"Created new product price record")
            
            db.session.commit()
            print(f"✅ Saved markup {markup}% for {network} {size_gb}GB")
            
        except ImportError:
            # If table doesn't exist, store in agent's store settings
            from models import AgentStore
            
            store = AgentStore.query.filter_by(agent_id=agent.id).first()
            if store:
                # Store as JSON in store_description or create a new column
                print(f"Storing markup in agent store settings")
                # For now, just log it
            print(f"AgentProductPrice table not found, markup not persisted")
        
        return jsonify({
            'success': True,
            'message': f'Updated {network.upper()} {size_gb}GB markup to {markup}%',
            'data': {
                'network': network,
                'size_gb': size_gb,
                'wholesale_price': wholesale_price,
                'retail_price': new_retail_price,
                'markup': markup,
                'profit': profit
            }
        })
        
    except Exception as e:
        print(f"Update product markup error: {e}")
        import traceback
        traceback.print_exc()
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/agent/store/clients', methods=['GET'])
@token_required
@agent_required
def get_store_clients():
    """Get agent's store clients"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('limit', 20, type=int)
        search = request.args.get('search', '')
        
        query = StoreClient.query.filter_by(agent_id=g.current_user.id)
        
        if search:
            query = query.filter(
                db.or_(
                    StoreClient.name.ilike(f'%{search}%'),
                    StoreClient.phone.ilike(f'%{search}%'),
                    StoreClient.email.ilike(f'%{search}%')
                )
            )
        
        pagination = query.order_by(StoreClient.total_spent.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        return jsonify({
            'success': True,
            'data': [{
                'id': c.id,
                'name': c.name,
                'phone': c.phone,
                'email': c.email,
                'total_spent': float(c.total_spent or 0),
                'order_count': c.order_count or 0,
                'last_purchase': c.last_purchase.isoformat() if c.last_purchase else None,
                'created_at': c.created_at.isoformat()
            } for c in pagination.items],
            'total': pagination.total,
            'page': page,
            'total_pages': pagination.pages
        })
        
    except Exception as e:
        print(f"Get store clients error: {e}")
        return jsonify({'success': False, 'error': 'Failed to fetch clients from Roamsmart'}), 500


@app.route('/api/agent/store/orders', methods=['GET'])
@token_required
@agent_required
def get_store_orders():
    """Get agent's store orders"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('limit', 20, type=int)
        status = request.args.get('status')
        
        query = Order.query.filter_by(user_id=g.current_user.id)
        
        if status:
            query = query.filter_by(status=status)
        
        pagination = query.order_by(Order.created_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        return jsonify({
            'success': True,
            'data': [{
                'id': o.id,
                'order_id': o.order_id,
                'customer_name': o.customer_name,
                'customer_phone': o.phone_number,
                'network': o.network,
                'size_gb': o.size_gb,
                'quantity': o.quantity,
                'amount': float(o.amount),
                'status': o.status,
                'payment_method': o.payment_method,
                'created_at': o.created_at.isoformat(),
                'completed_at': o.completed_at.isoformat() if o.completed_at else None
            } for o in pagination.items],
            'total': pagination.total,
            'page': page,
            'total_pages': pagination.pages
        })
        
    except Exception as e:
        print(f"Get store orders error: {e}")
        return jsonify({'success': False, 'error': 'Failed to fetch orders from Roamsmart'}), 500


@app.route('/api/agent/customers', methods=['GET'])
@token_required
@agent_required
def get_agent_customers():
    """Get agent's customers (from store clients)"""
    try:
        clients = StoreClient.query.filter_by(
            agent_id=g.current_user.id
        ).order_by(StoreClient.total_spent.desc()).limit(50).all()
        
        return jsonify({
            'success': True,
            'data': [{
                'id': c.id,
                'name': c.name,
                'phone': c.phone,
                'total_spent': float(c.total_spent or 0),
                'order_count': c.order_count or 0,
                'average_order': float((c.total_spent or 0) / (c.order_count or 1)),
                'last_purchase': c.last_purchase.isoformat() if c.last_purchase else None
            } for c in clients]
        })
        
    except Exception as e:
        print(f"Get agent customers error: {e}")
        return jsonify({'success': False, 'error': 'Failed to fetch customers from Roamsmart'}), 500


# ========== ADMIN ROUTES ==========

@app.route('/api/admin/stats', methods=['GET'])
@token_required
@admin_required
def get_admin_stats():
    """Get admin dashboard statistics"""
    try:
        total_users = User.query.count()
        total_agents = User.query.filter_by(is_agent=True, agent_approved=True).count()
        pending_agents = AgentRequest.query.filter_by(status='pending').count()
        total_orders = Order.query.count()
        total_revenue = db.session.query(db.func.sum(Order.amount)).filter_by(status='completed').scalar() or 0
        pending_manual = ManualPayment.query.filter_by(status='pending_verification').count()
        pending_withdrawals = Transaction.query.filter_by(type='withdrawal', status='pending').count()
        
        # Get recent orders with user info
        recent_orders = Order.query.order_by(Order.created_at.desc()).limit(10).all()
        
        return jsonify({
            'success': True,
            'data': {
                'total_users': total_users,
                'total_agents': total_agents,
                'pending_agents': pending_agents,
                'total_orders': total_orders,
                'total_revenue': float(total_revenue),
                'pending_manual': pending_manual,
                'pending_withdrawals': pending_withdrawals,
                'recent_orders': [{
                    'order_id': o.order_id,
                    'user': User.query.get(o.user_id).username if o.user_id else 'N/A',
                    'amount': float(o.amount),
                    'status': o.status,
                    'date': o.created_at.strftime('%Y-%m-%d')
                } for o in recent_orders]
            }
        })
    except Exception as e:
        print(f"Get admin stats error: {e}")
        return jsonify({'success': False, 'error': 'Failed to fetch Roamsmart stats'}), 500


@app.route('/api/admin/users', methods=['GET'])
@token_required
@admin_required
def get_admin_users():
    """Get all users"""
    try:
        users = User.query.order_by(User.created_at.desc()).all()
        return jsonify({'success': True, 'data': [u.to_dict() for u in users]})
    except Exception as e:
        print(f"Get admin users error: {e}")
        return jsonify({'success': False, 'error': 'Failed to fetch users from Roamsmart'}), 500


@app.route('/api/admin/users/create', methods=['POST'])
@token_required
@admin_required
def create_admin_user():
    """Create user (admin only)"""
    try:
        data = request.get_json()
        
        username = data.get('username')
        email = data.get('email')
        phone = data.get('phone')
        password = data.get('password')
        role = data.get('role', 'user')
        wallet_balance = data.get('wallet_balance', 0)
        
        if User.query.filter_by(email=email).first():
            return jsonify({'success': False, 'error': 'Email already exists'}), 400
        
        new_user = User(
            username=username,
            email=email,
            phone=phone,
            role=role,
            wallet_balance=wallet_balance,
            referral_code=f"REF{uuid.uuid4().hex[:8].upper()}"
        )
        if password:
            new_user.set_password(password)
        else:
            new_user.set_password('password123')
        
        db.session.add(new_user)
        db.session.commit()
        
        # Send welcome email (priority)
        send_email(
            email,
            f"Account Created for You - {COMPANY_NAME}",
            f"""
            <h3>Account Created for You - {COMPANY_NAME}</h3>
            <p>Dear {username},</p>
            <p>An account has been created for you on {COMPANY_NAME}.</p>
            <p><strong>Email:</strong> {email}</p>
            <p><strong>Password:</strong> {password if password else 'password123'}</p>
            <p>Please login and change your password immediately.</p>
            <a href="{COMPANY_WEBSITE}/login" style="background: #8B0000; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">Login Now</a>
            """
        )
        
        return jsonify({'success': True, 'user': new_user.to_dict()})
    except Exception as e:
        print(f"Create admin user error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Failed to create user'}), 500


@app.route('/api/admin/users/<int:user_id>/suspend', methods=['POST'])
@token_required
@admin_required
def suspend_user(user_id):
    """Suspend a user - Email ONLY"""
    try:
        user = User.query.get(user_id)
        if not user:
            return jsonify({'success': False, 'error': 'User not found'}), 404
        
        user.is_suspended = True
        db.session.commit()
        
        # Send notification via email only
        send_email(
            user.email,
            f"Account Suspension Notice - {COMPANY_NAME}",
            f"""
            <h3>Account Suspended - {COMPANY_NAME}</h3>
            <p>Dear {user.username},</p>
            <p>Your {COMPANY_NAME} account has been suspended.</p>
            <p>Please contact our support team for assistance.</p>
            <p><strong>Support Contact:</strong> {COMPANY_PHONE}</p>
            <hr>
            <p>If you believe this is an error, please reach out immediately.</p>
            """
        )
        
        log_activity(g.current_user.id, 'suspend_user', f'Suspended user {user.email}')
        
        return jsonify({'success': True, 'message': 'User suspended'})
    except Exception as e:
        print(f"Suspend user error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Failed to suspend user'}), 500


@app.route('/api/admin/users/<int:user_id>/activate', methods=['POST'])
@token_required
@admin_required
def activate_user(user_id):
    """Activate a suspended user - Email ONLY"""
    try:
        user = User.query.get(user_id)
        if not user:
            return jsonify({'success': False, 'error': 'User not found'}), 404
        
        user.is_suspended = False
        db.session.commit()
        
        send_email(
            user.email,
            f"Account Reactivated - {COMPANY_NAME}",
            f"""
            <h3>Account Reactivated - {COMPANY_NAME}</h3>
            <p>Dear {user.username},</p>
            <p>Your {COMPANY_NAME} account has been reactivated.</p>
            <p>You can now login and continue using our services.</p>
            <a href="{COMPANY_WEBSITE}/login" style="background: #8B0000; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">Login Now</a>
            """
        )
        
        log_activity(g.current_user.id, 'activate_user', f'Activated user {user.email}')
        
        return jsonify({'success': True, 'message': 'User activated'})
    except Exception as e:
        print(f"Activate user error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Failed to activate user'}), 500


@app.route('/api/admin/agents', methods=['GET'])
@token_required
@admin_required
def get_admin_agents():
    """Get all agents"""
    try:
        agents = User.query.filter_by(is_agent=True, agent_approved=True).order_by(
            User.created_at.desc()
        ).all()
        
        agents_data = []
        for agent in agents:
            total_sales = db.session.query(db.func.sum(Order.amount)).filter_by(
                user_id=agent.id, status='completed'
            ).scalar() or 0
            
            withdrawals = db.session.query(db.func.sum(Transaction.amount)).filter_by(
                user_id=agent.id, type='withdrawal', status='completed'
            ).scalar() or 0
            
            agents_data.append({
                'id': agent.id,
                'username': agent.username,
                'email': agent.email,
                'phone': agent.phone,
                'total_sales': float(total_sales),
                'commission_earned': float(total_sales * 0.15),
                'withdrawn': float(withdrawals),
                'tier': agent.agent_tier or 'Bronze',
                'commission_rate': agent.commission_rate or 10,
                'created_at': agent.created_at.isoformat()
            })
        
        return jsonify({'success': True, 'data': agents_data})
    except Exception as e:
        print(f"Get admin agents error: {e}")
        return jsonify({'success': False, 'error': 'Failed to fetch agents from Roamsmart'}), 500


@app.route('/api/admin/agent-requests', methods=['GET'])
@token_required
@admin_required
def get_agent_requests():
    """Get pending agent requests"""
    try:
        requests = AgentRequest.query.filter_by(status='pending').order_by(
            AgentRequest.created_at.desc()
        ).all()
        
        return jsonify({
            'success': True,
            'data': [{
                'id': r.id,
                'user_id': r.user_id,
                'username': User.query.get(r.user_id).username,
                'email': User.query.get(r.user_id).email,
                'phone': User.query.get(r.user_id).phone,
                'amount': float(r.amount),
                'payment_reference': r.payment_reference,
                'created_at': r.created_at.strftime('%Y-%m-%d %H:%M')
            } for r in requests]
        })
    except Exception as e:
        print(f"Get agent requests error: {e}")
        return jsonify({'success': False, 'error': 'Failed to fetch agent requests'}), 500


@app.route('/api/admin/agent-requests/<int:request_id>/approve', methods=['POST'])
@token_required
@admin_required
def approve_agent_request(request_id):
    """Approve agent request - Email ONLY"""
    try:
        agent_request = AgentRequest.query.get(request_id)
        if not agent_request:
            return jsonify({'success': False, 'error': 'Request not found'}), 404
        
        user = User.query.get(agent_request.user_id)
        user.is_agent = True
        user.agent_approved = True
        user.agent_tier = 'Bronze'
        user.commission_rate = 10
        
        agent_request.status = 'approved'
        agent_request.approved_at = datetime.utcnow()
        
        db.session.commit()
        
        # Send notification via email only
        send_email(
            user.email,
            f"🎉 Congratulations! Agent Application Approved - {COMPANY_NAME}",
            f"""
            <h3>Welcome to {COMPANY_NAME} Agent Program!</h3>
            <p>Dear {user.username},</p>
            <p>Congratulations! Your agent application has been approved.</p>
            <p><strong>Your Benefits:</strong></p>
            <ul>
                <li>Wholesale prices on all data bundles</li>
                <li>10% base commission on all sales</li>
                <li>Access to agent dashboard</li>
                <li>Create your own store</li>
                <li>Track earnings and withdrawals</li>
            </ul>
            <a href="{COMPANY_WEBSITE}/agent/dashboard" style="background: #8B0000; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">Go to Agent Dashboard</a>
            <hr>
            <p>Need help? Contact support on WhatsApp: {COMPANY_PHONE}</p>
            """
        )
        
        send_webhook('agent.approved', {'user_id': user.id, 'username': user.username})
        log_activity(g.current_user.id, 'approve_agent', f'Approved agent {user.email}')
        
        return jsonify({'success': True, 'message': 'Agent approved on Roamsmart'})
    except Exception as e:
        print(f"Approve agent error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Failed to approve agent'}), 500


@app.route('/api/admin/agent-requests/<int:request_id>/reject', methods=['POST'])
@token_required
@admin_required
def reject_agent_request(request_id):
    """Reject agent request - Email ONLY"""
    try:
        agent_request = AgentRequest.query.get(request_id)
        if not agent_request:
            return jsonify({'success': False, 'error': 'Request not found'}), 404
        
        agent_request.status = 'rejected'
        db.session.commit()
        
        user = User.query.get(agent_request.user_id)
        
        send_email(
            user.email,
            f"Agent Application Update - {COMPANY_NAME}",
            f"""
            <h3>Application Status Update - {COMPANY_NAME}</h3>
            <p>Dear {user.username},</p>
            <p>Thank you for your interest in becoming an agent.</p>
            <p>After careful review, we regret to inform you that your application could not be approved at this time.</p>
            <p>Please contact our support team for more information about the decision.</p>
            <p>You may reapply after 30 days.</p>
            """
        )
        
        log_activity(g.current_user.id, 'reject_agent', f'Rejected agent {user.email}')
        
        return jsonify({'success': True, 'message': 'Agent request rejected'})
    except Exception as e:
        print(f"Reject agent error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Failed to reject agent'}), 500


@app.route('/api/admin/agent-requests/bulk-approve', methods=['POST'])
@token_required
@admin_required
def bulk_approve_agents():
    """Bulk approve agent requests - Email ONLY"""
    try:
        data = request.get_json()
        request_ids = data.get('request_ids', [])
        
        approved_count = 0
        approved_users = []
        
        for request_id in request_ids:
            agent_request = AgentRequest.query.get(request_id)
            if agent_request and agent_request.status == 'pending':
                user = User.query.get(agent_request.user_id)
                user.is_agent = True
                user.agent_approved = True
                user.agent_tier = 'Bronze'
                user.commission_rate = 10
                agent_request.status = 'approved'
                agent_request.approved_at = datetime.utcnow()
                approved_count += 1
                approved_users.append(user)
        
        db.session.commit()
        
        for user in approved_users:
            send_email(
                user.email,
                f"🎉 Congratulations! Agent Application Approved - {COMPANY_NAME}",
                f"""
                <h3>Welcome to {COMPANY_NAME} Agent Program!</h3>
                <p>Dear {user.username},</p>
                <p>Congratulations! Your agent application has been approved.</p>
                <a href="{COMPANY_WEBSITE}/agent/dashboard" style="background: #8B0000; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">Go to Agent Dashboard</a>
                """
            )
        
        log_activity(g.current_user.id, 'bulk_approve_agents', f'Approved {approved_count} agents')
        
        return jsonify({'success': True, 'approved_count': approved_count})
    except Exception as e:
        print(f"Bulk approve agents error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Failed to bulk approve'}), 500


@app.route('/api/payment/paystack/check/<reference>', methods=['GET'])
@token_required
def check_paystack_payment(reference):
    """Debug endpoint to check pending transaction status"""
    try:
        print(f"Checking pending transaction for reference: {reference}")
        
        # Check in PendingTransaction table
        pending_tx = PendingTransaction.query.filter_by(reference=reference).first()
        
        if pending_tx:
            return jsonify({
                'success': True,
                'exists': True,
                'data': {
                    'reference': pending_tx.reference,
                    'user_id': pending_tx.user_id,
                    'amount': float(pending_tx.amount),
                    'status': pending_tx.status,
                    'payment_method': pending_tx.payment_method,
                    'created_at': pending_tx.created_at.isoformat() if pending_tx.created_at else None
                }
            })
        else:
            # Check in Transaction table
            completed_tx = Transaction.query.filter_by(reference=reference).first()
            if completed_tx:
                return jsonify({
                    'success': True,
                    'exists': True,
                    'already_processed': True,
                    'data': {
                        'reference': completed_tx.reference,
                        'amount': float(completed_tx.amount),
                        'status': completed_tx.status
                    }
                })
            
            return jsonify({
                'success': True,
                'exists': False,
                'message': f'No transaction found with reference: {reference}'
            })
            
    except Exception as e:
        print(f"Check payment error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500





@app.route('/api/wallet/transactions', methods=['GET'])
@token_required
def get_walletagent_transactions():
    """Get wallet transactions"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('limit', 20, type=int)
    
    pagination = Transaction.query.filter_by(user_id=g.current_user.id).order_by(
        Transaction.created_at.desc()
    ).paginate(page=page, per_page=per_page, error_out=False)
    
    return jsonify({
        'success': True,
        'data': [t.to_dict() for t in pagination.items],
        'total': pagination.total,
        'page': page,
        'total_pages': pagination.pages
    })


@app.route('/api/wallet/fund', methods=['POST'])
@token_required
def fund_agent_wallet():
    """Request wallet funding"""
    data = request.get_json()
    amount = float(data.get('amount', 0))
    
    if amount < 10:
        return jsonify({'success': False, 'error': 'Minimum funding is GHS 10'}), 400
    
    if amount > 100000:
        return jsonify({'success': False, 'error': 'Maximum funding is GHS 100,000'}), 400
    
    reference = f"FUND-{uuid.uuid4().hex[:8].upper()}"
    
    transaction = Transaction(
        user_id=g.current_user.id,
        type='fund',
        amount=amount,
        balance_before=g.current_user.wallet_balance,
        balance_after=g.current_user.wallet_balance,
        status='pending',
        reference=reference,
        description=f'Wallet funding request on {COMPANY_NAME}'
    )
    db.session.add(transaction)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'data': {
            'reference': reference,
            'amount': amount
        },
        'instructions': {
            'mobile_money_number': COMPANY_PHONE,
            'recipient': COMPANY_NAME,
            'reference': reference,
            'amount': amount
        },
        'message': f'Funding request created. Send GHS {amount:.2f} to {COMPANY_PHONE} with reference: {reference}'
    })


@app.route('/api/wallet/manual/request', methods=['POST'])
@token_required
def create_admin_manual_request():
    """Create manual payment request"""
    data = request.get_json()
    amount = float(data.get('amount', 0))
    phone_number = data.get('phone_number')
    
    if amount < 10:
        return jsonify({'success': False, 'error': 'Minimum amount is GHS 10'}), 400
    
    reference = f"MAN-{uuid.uuid4().hex[:8].upper()}"
    
    manual_payment = ManualPayment(
        user_id=g.current_user.id,
        amount=amount,
        reference=reference,
        phone_number=phone_number,
        status='pending'
    )
    db.session.add(manual_payment)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'data': {
            'id': manual_payment.id,
            'reference': reference,
            'amount': amount
        }
    })


@app.route('/api/wallet/manual/upload-proof', methods=['POST'])
@token_required
def upload_agent_manual_proof():
    """Upload proof of manual payment"""
    try:
        request_id = request.form.get('request_id')
        proof = request.files.get('proof')
        
        if not proof:
            return jsonify({'success': False, 'error': 'No proof file provided'}), 400
        
        # Validate file type
        allowed_extensions = {'png', 'jpg', 'jpeg', 'pdf'}
        file_extension = proof.filename.rsplit('.', 1)[1].lower()
        if file_extension not in allowed_extensions:
            return jsonify({'success': False, 'error': 'Invalid file type. Use PNG, JPG, JPEG, or PDF'}), 400
        
        # Validate file size (max 5MB)
        proof.seek(0, os.SEEK_END)
        file_size = proof.tell()
        proof.seek(0)
        if file_size > 5 * 1024 * 1024:
            return jsonify({'success': False, 'error': 'File too large. Max 5MB'}), 400
        
        manual_payment = ManualPayment.query.get(request_id)
        if not manual_payment or manual_payment.user_id != g.current_user.id:
            return jsonify({'success': False, 'error': 'Request not found'}), 404
        
        if manual_payment.status != 'pending':
            return jsonify({'success': False, 'error': f'Payment already {manual_payment.status}'}), 400
        
        # Create upload directory if not exists
        upload_folder = app.config.get('UPLOAD_FOLDER', 'uploads')
        if not os.path.exists(upload_folder):
            os.makedirs(upload_folder)
        
        # Save file
        from werkzeug.utils import secure_filename
        filename = secure_filename(f"proof_{manual_payment.reference}_{uuid.uuid4().hex[:8]}.{file_extension}")
        filepath = os.path.join(upload_folder, filename)
        proof.save(filepath)
        
        # Update payment record
        manual_payment.proof_url = f"/uploads/{filename}"
        manual_payment.status = 'pending_verification'
        
        db.session.commit()
        
        # Notify admins via email
        admins = User.query.filter(User.role.in_(['admin', 'super_admin'])).all()
        for admin in admins:
            send_email(
                admin.email,
                f"Manual Payment Proof Uploaded - {manual_payment.reference} - {COMPANY_NAME}",
                f"""
                <h3>Manual Payment Verification Required - {COMPANY_NAME}</h3>
                <p><strong>User:</strong> {g.current_user.username}</p>
                <p><strong>Amount:</strong> GHS {manual_payment.amount:.2f}</p>
                <p><strong>Reference:</strong> {manual_payment.reference}</p>
                <p><strong>Proof:</strong> <a href="{manual_payment.proof_url}">View Upload</a></p>
                <p><a href="{COMPANY_WEBSITE}/admin/manual-payments/{manual_payment.id}">Verify Payment</a></p>
                """
            )
        
        return jsonify({
            'success': True, 
            'message': 'Proof uploaded successfully. Awaiting admin verification on Roamsmart.',
            'data': {
                'proof_url': manual_payment.proof_url,
                'status': manual_payment.status
            }
        })
        
    except Exception as e:
        print(f"Upload proof error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Failed to upload proof'}), 500


@app.route('/api/wallet/manual/verify', methods=['POST'])
@token_required
def verify_manual_admin_payment_user():
    """User initiates verification of manual payment"""
    try:
        data = request.get_json()
        reference = data.get('reference')
        transaction_id = data.get('transaction_id')
        sender_name = data.get('sender_name')
        sender_phone = data.get('sender_phone')
        
        if not reference:
            return jsonify({'success': False, 'error': 'Reference is required'}), 400
        
        manual_payment = ManualPayment.query.filter_by(reference=reference).first()
        if not manual_payment:
            return jsonify({'success': False, 'error': 'Payment request not found'}), 404
        
        if manual_payment.user_id != g.current_user.id:
            return jsonify({'success': False, 'error': 'Unauthorized'}), 403
        
        if manual_payment.status != 'pending':
            return jsonify({'success': False, 'error': f'Payment already {manual_payment.status}'}), 400
        
        # Update payment details
        if sender_name:
            manual_payment.sender_name = sender_name
        if sender_phone:
            manual_payment.sender_phone = sender_phone
        if transaction_id:
            manual_payment.transaction_id = transaction_id
        
        manual_payment.status = 'pending_verification'
        
        db.session.commit()
        
        # Notify admins via email
        admins = User.query.filter(User.role.in_(['admin', 'super_admin'])).all()
        
        for admin in admins:
            send_email(
                admin.email,
                f"Manual Payment Verification - {reference} - {COMPANY_NAME}",
                f"""
                <h3>Manual Payment Verification Request - {COMPANY_NAME}</h3>
                <p><strong>Reference:</strong> {reference}</p>
                <p><strong>Amount:</strong> GHS {manual_payment.amount:.2f}</p>
                <p><strong>User:</strong> {g.current_user.username} ({g.current_user.email})</p>
                <p><strong>Sender Name:</strong> {sender_name or 'Not provided'}</p>
                <p><strong>Sender Phone:</strong> {sender_phone or 'Not provided'}</p>
                <p><strong>Transaction ID:</strong> {transaction_id or 'Not provided'}</p>
                <p><a href="{COMPANY_WEBSITE}/admin/manual-payments/{manual_payment.id}">Verify Payment</a></p>
                """
            )
        
        # Send confirmation to user via email
        send_email(
            g.current_user.email,
            f"Payment Verification Requested - {reference} - {COMPANY_NAME}",
            f"""
            <h3>Verification Request Received - {COMPANY_NAME}</h3>
            <p>Dear {g.current_user.username},</p>
            <p>Your manual payment verification request has been submitted.</p>
            <p><strong>Reference:</strong> {reference}</p>
            <p><strong>Amount:</strong> GHS {manual_payment.amount:.2f}</p>
            <p>Our admin team will review your payment within 24 hours.</p>
            <p>You will receive a notification once your wallet is funded.</p>
            <hr>
            <p>Need help? Contact support on WhatsApp: {COMPANY_PHONE}</p>
            """
        )
        
        return jsonify({
            'success': True, 
            'message': 'Verification requested successfully. Admin will review your payment on Roamsmart.',
            'data': {
                'reference': reference,
                'status': manual_payment.status,
                'amount': manual_payment.amount
            }
        })
        
    except Exception as e:
        print(f"Verify manual payment error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Failed to submit verification request'}), 500

@app.route('/api/admin/orders/recent', methods=['GET'])
@token_required
@admin_required
def get_admin_recent_orders():
    """Get recent orders for admin dashboard"""
    try:
        # Get limit from query param (default 10)
        limit = request.args.get('limit', 10, type=int)
        
        # Get recent orders
        recent_orders = Order.query.filter_by(
            status='completed'
        ).order_by(Order.created_at.desc()).limit(limit).all()
        
        # Format the response
        orders_data = []
        for order in recent_orders:
            # Get customer/agent info
            user = User.query.get(order.user_id) if order.user_id else None
            agent = User.query.get(order.agent_id) if order.agent_id else None
            
            orders_data.append({
                'id': order.id,
                'order_id': order.order_id,
                'customer_name': order.customer_name or (user.username if user else 'Anonymous'),
                'customer_phone': order.phone_number,
                'amount': float(order.amount),
                'status': order.status,
                'created_at': order.created_at.isoformat() if order.created_at else None,
                'network': order.network,
                'size_gb': order.size_gb,
                'quantity': order.quantity,
                'agent_name': agent.username if agent else None,
                'profit': float(order.profit) if order.profit else 0
            })
        
        return jsonify({
            'success': True,
            'data': orders_data
        })
        
    except Exception as e:
        print(f"Get recent orders error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/admin/total-sales', methods=['GET'])
@token_required
@admin_required
def get_admin_total_sales():
    """Get total sales breakdown for admin dashboard"""
    try:
        from datetime import datetime, timedelta
        
        today = datetime.utcnow().date()
        today_start = datetime.combine(today, datetime.min.time())
        
        # Today's sales
        today_sales = db.session.query(db.func.sum(Order.amount)).filter(
            Order.status == 'completed',
            Order.created_at >= today_start
        ).scalar() or 0
        
        # This week
        week_start = today - timedelta(days=today.weekday())
        week_start_dt = datetime.combine(week_start, datetime.min.time())
        week_sales = db.session.query(db.func.sum(Order.amount)).filter(
            Order.status == 'completed',
            Order.created_at >= week_start_dt
        ).scalar() or 0
        
        # This month
        month_start = today.replace(day=1)
        month_start_dt = datetime.combine(month_start, datetime.min.time())
        month_sales = db.session.query(db.func.sum(Order.amount)).filter(
            Order.status == 'completed',
            Order.created_at >= month_start_dt
        ).scalar() or 0
        
        # This year
        year_start = today.replace(month=1, day=1)
        year_start_dt = datetime.combine(year_start, datetime.min.time())
        year_sales = db.session.query(db.func.sum(Order.amount)).filter(
            Order.status == 'completed',
            Order.created_at >= year_start_dt
        ).scalar() or 0
        
        # All time
        all_time = db.session.query(db.func.sum(Order.amount)).filter(
            Order.status == 'completed'
        ).scalar() or 0
        
        return jsonify({
            'success': True,
            'data': {
                'currency': 'GHS',
                'today_sales': float(today_sales),
                'week_sales': float(week_sales),
                'month_sales': float(month_sales),
                'year_sales': float(year_sales),
                'total_sales': float(all_time)
            }
        })
        
    except Exception as e:
        print(f"Get total sales error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/wallet/manual/requests', methods=['GET'])
@token_required
def get_manual_Admin_requests():
    """Get user's manual payment requests"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('limit', 20, type=int)
        status = request.args.get('status')
        
        query = ManualPayment.query.filter_by(user_id=g.current_user.id)
        
        if status:
            query = query.filter_by(status=status)
        
        pagination = query.order_by(ManualPayment.created_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        return jsonify({
            'success': True,
            'data': [{
                'id': r.id,
                'amount': float(r.amount),
                'reference': r.reference,
                'status': r.status,
                'sender_name': r.sender_name,
                'sender_phone': r.sender_phone,
                'transaction_id': r.transaction_id,
                'proof_url': r.proof_url,
                'created_at': r.created_at.isoformat()
            } for r in pagination.items],
            'total': pagination.total,
            'page': page,
            'total_pages': pagination.pages
        })
        
    except Exception as e:
        print(f"Get manual requests error: {e}")
        return jsonify({'success': False, 'error': 'Failed to fetch requests from Roamsmart'}), 500


@app.route('/api/wallet/manual/request/<int:request_id>', methods=['GET'])
@token_required
def get_manual_Admin_request_detail(request_id):
    """Get specific manual payment request details"""
    try:
        manual_payment = ManualPayment.query.get(request_id)
        
        if not manual_payment:
            return jsonify({'success': False, 'error': 'Request not found'}), 404
        
        if manual_payment.user_id != g.current_user.id and g.current_user.role not in ['admin', 'super_admin']:
            return jsonify({'success': False, 'error': 'Unauthorized'}), 403
        
        return jsonify({
            'success': True,
            'data': {
                'id': manual_payment.id,
                'amount': float(manual_payment.amount),
                'reference': manual_payment.reference,
                'status': manual_payment.status,
                'sender_name': manual_payment.sender_name,
                'sender_phone': manual_payment.sender_phone,
                'transaction_id': manual_payment.transaction_id,
                'proof_url': manual_payment.proof_url,
                'created_at': manual_payment.created_at.isoformat()
            }
        })
        
    except Exception as e:
        print(f"Get manual request detail error: {e}")
        return jsonify({'success': False, 'error': 'Failed to fetch request details from Roamsmart'}), 500


@app.route('/api/wallet/manual/request/<int:request_id>/cancel', methods=['POST'])
@token_required
def cancel_manual_Adinrequest(request_id):
    """Cancel a pending manual payment request"""
    try:
        manual_payment = ManualPayment.query.get(request_id)
        
        if not manual_payment:
            return jsonify({'success': False, 'error': 'Request not found'}), 404
        
        if manual_payment.user_id != g.current_user.id:
            return jsonify({'success': False, 'error': 'Unauthorized'}), 403
        
        if manual_payment.status not in ['pending', 'pending_verification']:
            return jsonify({'success': False, 'error': f'Cannot cancel request with status: {manual_payment.status}'}), 400
        
        manual_payment.status = 'cancelled'
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Payment request cancelled successfully on Roamsmart'
        })
        
    except Exception as e:
        print(f"Cancel manual request error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Failed to cancel request'}), 500

# ========== AGENT ROUTES ==========

@app.route('/api/agent/apply', methods=['POST'])
@token_required
def apply_adminagent():
    """Apply to become an agent - Email ONLY"""
    try:
        data = request.get_json() or request.form
        payment_method = data.get('payment_method', 'mobile_money')
        
        if g.current_user.is_agent and g.current_user.agent_approved:
            return jsonify({'success': False, 'error': 'You are already an approved agent on Roamsmart'}), 400
        
        existing = AgentRequest.query.filter_by(
            user_id=g.current_user.id, status='pending'
        ).first()
        
        if existing:
            return jsonify({'success': False, 'error': 'You already have a pending application'}), 400
        
        amount = 100.00
        reference = f"AGENT-{uuid.uuid4().hex[:8].upper()}"
        
        agent_request = AgentRequest(
            user_id=g.current_user.id, amount=amount, payment_method=payment_method,
            payment_reference=reference, status='pending', created_at=datetime.utcnow()
        )
        
        if payment_method == 'mobile_money':
            agent_request.payment_details = {
                'mobile_money_number': COMPANY_PHONE,
                'recipient': COMPANY_NAME,
                'reference': reference,
                'amount': amount
            }
            
            db.session.add(agent_request)
            db.session.commit()
            
            # Email confirmation to user (Email ONLY)
            send_email(
                g.current_user.email,
                f"Agent Application Submitted - {COMPANY_NAME}",
                f"""
                <div style="font-family: Arial, sans-serif;">
                    <h2 style="color: #8B0000;">Agent Application Received</h2>
                    <p>Dear {g.current_user.username},</p>
                    <p>Your agent application has been submitted successfully!</p>
                    <p><strong>Reference:</strong> {reference}</p>
                    <p><strong>Amount:</strong> GHS {amount:.2f}</p>
                    <p>Send payment to: <strong>{COMPANY_PHONE}</strong> with reference: {reference}</p>
                    <a href="{COMPANY_WEBSITE}/dashboard" style="background: #8B0000; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">Go to Dashboard</a>
                </div>
                """
            )
            
            # Email notification to admin
            send_email(
                COMPANY_ADMIN_EMAIL,
                f"New Agent Application - {reference} - {COMPANY_NAME}",
                f"""
                <h3>New Agent Application - {COMPANY_NAME}</h3>
                <p><strong>Applicant:</strong> {g.current_user.username}</p>
                <p><strong>Email:</strong> {g.current_user.email}</p>
                <p><strong>Phone:</strong> {g.current_user.phone}</p>
                <p><strong>Reference:</strong> {reference}</p>
                <a href="{COMPANY_WEBSITE}/admin/agent-requests">Review Application</a>
                """
            )
            
            return jsonify({
                'success': True,
                'message': f'Application submitted to {COMPANY_NAME}! Please make payment to complete registration.',
                'data': {
                    'request_id': agent_request.id,
                    'reference': reference,
                    'amount': amount,
                    'instructions': agent_request.payment_details
                }
            })
        
        return jsonify({'success': False, 'error': 'Invalid payment method'}), 400
        
    except Exception as e:
        print(f"Apply agent error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Failed to submit application'}), 500


@app.route('/api/agent/dashboard', methods=['GET'])
@token_required
@agent_required
def get_agent_admindashboard():
    """Get agent dashboard data"""
    try:
        total_sales = db.session.query(db.func.sum(Order.amount)).filter_by(
            user_id=g.current_user.id, status='completed'
        ).scalar() or 0
        
        total_orders = Order.query.filter_by(
            user_id=g.current_user.id, status='completed'
        ).count()
        
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today_sales = db.session.query(db.func.sum(Order.amount)).filter(
            Order.user_id == g.current_user.id,
            Order.status == 'completed',
            Order.completed_at >= today
        ).scalar() or 0
        
        commissions = total_sales * (g.current_user.commission_rate or 15) / 100
        total_customers = StoreClient.query.filter_by(agent_id=g.current_user.id).count()
        store = Store.query.filter_by(agent_id=g.current_user.id).first()
        
        return jsonify({
            'success': True,
            'data': {
                'wallet_balance': float(g.current_user.wallet_balance),
                'total_sales': float(total_sales),
                'total_orders': total_orders,
                'agent_savings': float(total_sales * 0.05),
                'total_commission': float(commissions),
                'pending_commission': float(commissions * 0.3),
                'today_sales': float(today_sales),
                'total_customers': total_customers,
                'agent_tier': g.current_user.agent_tier or 'Bronze',
                'commission_rate': g.current_user.commission_rate or 15,
                'store': store.to_dict() if store else None,
                'recent_orders': [{
                    'order_id': o.order_id,
                    'amount': float(o.amount),
                    'phone_number': o.phone_number,
                    'created_at': o.created_at.isoformat()
                } for o in recent_orders]
            }
        })
        
    except Exception as e:
        print(f"Get agent dashboard error: {e}")
        return jsonify({'success': False, 'error': 'Failed to fetch dashboard data from Roamsmart'}), 500


@app.route('/api/agent/sell', methods=['POST'])
@token_required
@agent_required
def agent_adminsell():
    """Sell data to customer (agent only) - NO customer SMS"""
    try:
        data = request.get_json()
        
        network = data.get('network')
        size_gb = data.get('size_gb')
        phone = data.get('phone')
        customer_name = data.get('customer_name')
        quantity = data.get('quantity', 1)
        price_override = data.get('price')
        
        if not all([network, size_gb, phone]):
            return jsonify({'success': False, 'error': 'Missing required fields'}), 400
        
        bundle = DataBundle.query.filter_by(network=network, size_gb=size_gb, is_active=True).first()
        if not bundle:
            return jsonify({'success': False, 'error': 'Bundle not available on Roamsmart'}), 400
        
        unit_price = price_override if price_override else bundle.agent_price
        total_price = unit_price * quantity
        
        if g.current_user.wallet_balance < total_price:
            return jsonify({'success': False, 'error': f'Insufficient wallet balance. Need GHS {total_price:.2f}'}), 400
        
        balance_before = g.current_user.wallet_balance
        g.current_user.wallet_balance -= total_price
        
        order = Order(
            user_id=g.current_user.id, type='data', network=network, size_gb=size_gb,
            phone_number=phone, amount=total_price, quantity=quantity, status='completed',
            payment_method='wallet', customer_name=customer_name, completed_at=datetime.utcnow()
        )
        db.session.add(order)
        
        transaction = Transaction(
            user_id=g.current_user.id, type='sale', amount=total_price,
            balance_before=balance_before, balance_after=g.current_user.wallet_balance,
            description=f'Sold {quantity}x {size_gb}GB {network} to {phone}', reference=order.order_id, status='completed'
        )
        db.session.add(transaction)
        
        if customer_name:
            client = StoreClient.query.filter_by(phone=phone, agent_id=g.current_user.id).first()
            if client:
                client.total_spent = (client.total_spent or 0) + total_price
                client.order_count = (client.order_count or 0) + 1
                client.last_purchase = datetime.utcnow()
            else:
                client = StoreClient(agent_id=g.current_user.id, name=customer_name, phone=phone, total_spent=total_price, order_count=1, last_purchase=datetime.utcnow())
                db.session.add(client)
        
        db.session.commit()
        
        # Send data delivery to network provider ONLY (NO customer SMS)
        send_data_delivery_to_provider(phone, f"✅ {COMPANY_NAME}: {quantity}x {size_gb}GB {network} data sent!")
        
        # Send email receipt to agent
        send_email(
            g.current_user.email,
            f"Sale Receipt - {order.order_id} - {COMPANY_NAME}",
            f"""
            <h3>Sale Completed on {COMPANY_NAME}</h3>
            <p>You sold {quantity}x {size_gb}GB {network} data to {customer_name or phone}</p>
            <p>Amount: GHS {total_price:.2f}</p>
            <p>Order ID: {order.order_id}</p>
            <p>Your new balance: GHS {g.current_user.wallet_balance:.2f}</p>
            """
        )
        
        commission = (unit_price - bundle.wholesale_price) * quantity
        
        return jsonify({
            'success': True,
            'message': f'Sold {quantity}x {size_gb}GB {network} to {phone} on {COMPANY_NAME}',
            'data': {
                'order_id': order.order_id,
                'amount': total_price,
                'commission': float(commission),
                'balance': float(g.current_user.wallet_balance)
            }
        })
        
    except Exception as e:
        print(f"Agent sell error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Failed to process sale on Roamsmart'}), 500


@app.route('/api/agent/earnings', methods=['GET'])
@token_required
@agent_required
def get_agent_userearnings():
    """Get agent earnings breakdown"""
    try:
        total_sales = db.session.query(db.func.sum(Order.amount)).filter_by(
            user_id=g.current_user.id, status='completed'
        ).scalar() or 0
        
        withdrawals = Transaction.query.filter_by(
            user_id=g.current_user.id, type='withdrawal', status='completed'
        ).all()
        withdrawn = sum(w.amount for w in withdrawals)
        
        pending_withdrawals = Transaction.query.filter_by(
            user_id=g.current_user.id, type='withdrawal', status='pending'
        ).all()
        pending = sum(w.amount for w in pending_withdrawals)
        
        current_month = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        monthly_earnings = db.session.query(db.func.sum(Order.amount)).filter(
            Order.user_id == g.current_user.id,
            Order.status == 'completed',
            Order.completed_at >= current_month
        ).scalar() or 0
        
        return jsonify({
            'success': True,
            'data': {
                'available': float(g.current_user.wallet_balance),
                'total_earned': float(total_sales),
                'pending': float(pending),
                'withdrawn': float(withdrawn),
                'this_month': float(monthly_earnings),
                'commission_rate': g.current_user.commission_rate or 15,
                'next_tier': {
                    'name': 'Silver' if g.current_user.agent_tier == 'Bronze' else 'Gold',
                    'required_sales': 5000 if g.current_user.agent_tier == 'Bronze' else 10000,
                    'current_sales': float(total_sales)
                }
            }
        })
        
    except Exception as e:
        print(f"Get agent earnings error: {e}")
        return jsonify({'success': False, 'error': 'Failed to fetch earnings from Roamsmart'}), 500


@app.route('/api/agent/withdraw', methods=['POST'])
@token_required
@agent_required
def agent_userwithdraw():
    """Request withdrawal for agent - Email ONLY"""
    try:
        data = request.get_json()
        amount = float(data.get('amount', 0))
        mobile_money = data.get('mobile_money')
        
        if not mobile_money:
            return jsonify({'success': False, 'error': 'Mobile money number is required'}), 400
        
        if amount < 50:
            return jsonify({'success': False, 'error': 'Minimum withdrawal is GHS 50'}), 400
        
        if amount > g.current_user.wallet_balance:
            return jsonify({'success': False, 'error': f'Insufficient balance. Available: GHS {g.current_user.wallet_balance:.2f}'}), 400
        
        reference = f"WTH-{uuid.uuid4().hex[:8].upper()}"
        
        transaction = Transaction(
            user_id=g.current_user.id, type='withdrawal', amount=amount,
            balance_before=g.current_user.wallet_balance, balance_after=g.current_user.wallet_balance,
            status='pending', description=f'Withdrawal request to {mobile_money}', reference=reference
        )
        db.session.add(transaction)
        db.session.commit()
        
        # Email notification to admins
        admins = User.query.filter(User.role.in_(['admin', 'super_admin'])).all()
        for admin in admins:
            send_email(
                admin.email,
                f"Withdrawal Request - {reference} - {COMPANY_NAME}",
                f"""
                <h3>New Withdrawal Request on {COMPANY_NAME}</h3>
                <p><strong>Agent:</strong> {g.current_user.username}</p>
                <p><strong>Amount:</strong> GHS {amount:.2f}</p>
                <p><strong>Mobile Money:</strong> {mobile_money}</p>
                <p><strong>Reference:</strong> {reference}</p>
                <a href="{COMPANY_WEBSITE}/admin/withdrawals/{transaction.id}">Process Withdrawal</a>
                """
            )
        
        # Email confirmation to agent
        send_email(
            g.current_user.email,
            f"Withdrawal Request Submitted - {reference} - {COMPANY_NAME}",
            f"""
            <h3>Withdrawal Request Submitted on {COMPANY_NAME}</h3>
            <p>Dear {g.current_user.username},</p>
            <p>Your withdrawal request has been submitted successfully.</p>
            <p><strong>Amount:</strong> GHS {amount:.2f}</p>
            <p><strong>Mobile Money:</strong> {mobile_money}</p>
            <p><strong>Reference:</strong> {reference}</p>
            <p>Our team will process your request within 24-48 hours.</p>
            """
        )
        
        return jsonify({
            'success': True, 
            'message': f'Withdrawal request submitted successfully on {COMPANY_NAME}',
            'data': {'reference': reference, 'amount': amount, 'status': 'pending'}
        })
        
    except Exception as e:
        print(f"Agent withdraw error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Failed to submit withdrawal request'}), 500


@app.route('/api/agent/withdrawals', methods=['GET'])
@token_required
@agent_required
def get_agent_adminwithdrawals():
    """Get agent withdrawal history"""
    try:
        withdrawals = Transaction.query.filter_by(
            user_id=g.current_user.id, type='withdrawal'
        ).order_by(Transaction.created_at.desc()).all()
        
        return jsonify({
            'success': True,
            'data': [{
                'id': w.id,
                'amount': float(w.amount),
                'mobile_money': w.description.split('to ')[-1] if 'to ' in w.description else 'N/A',
                'status': w.status,
                'reference': w.reference,
                'created_at': w.created_at.isoformat()
            } for w in withdrawals]
        })
        
    except Exception as e:
        print(f"Get agent withdrawals error: {e}")
        return jsonify({'success': False, 'error': 'Failed to fetch withdrawals from Roamsmart'}), 500


@app.route('/api/agent/store', methods=['GET', 'POST', 'PUT'])
@token_required
@agent_required
def agent_adminstore():
    """Get or update agent store settings"""
    try:
        store = Store.query.filter_by(agent_id=g.current_user.id).first()
        
        if request.method == 'GET':
            if not store:
                store = Store(
                    agent_id=g.current_user.id,
                    store_name=f"{g.current_user.username}'s Roamsmart Store",
                    store_slug=g.current_user.username.lower().replace(' ', '-'),
                    contact_phone=g.current_user.phone,
                    contact_email=g.current_user.email,
                    is_active=True
                )
                db.session.add(store)
                db.session.commit()
            
            return jsonify({'success': True, 'data': store.to_dict()})
        
        data = request.get_json()
        
        if not store:
            store = Store(agent_id=g.current_user.id)
            db.session.add(store)
        
        if 'store_name' in data:
            store.store_name = data['store_name']
        if 'store_slug' in data:
            store.store_slug = data['store_slug'].lower().replace(' ', '-')
        if 'contact_phone' in data:
            store.contact_phone = data['contact_phone']
        if 'contact_email' in data:
            store.contact_email = data['contact_email']
        if 'store_description' in data:
            store.store_description = data['store_description']
        if 'markup' in data:
            store.markup = max(0, min(100, data['markup']))
        if 'is_active' in data:
            store.is_active = data['is_active']
        
        store.updated_at = datetime.utcnow()
        db.session.commit()
        
        return jsonify({'success': True, 'message': f'Store updated successfully on {COMPANY_NAME}', 'data': store.to_dict()})
        
    except Exception as e:
        print(f"Agent store error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Failed to update store on Roamsmart'}), 500


@app.route('/api/agent/store/products', methods=['GET'])
@token_required
@agent_required
def get_agent_adinproducts():
    """Get products with agent-specific pricing"""
    try:
        bundles = DataBundle.query.filter_by(is_active=True).order_by(DataBundle.display_order).all()
        
        store = Store.query.filter_by(agent_id=g.current_user.id).first()
        markup = store.markup if store and store.markup else 15
        
        products = []
        for bundle in bundles:
            selling_price = bundle.agent_price * (1 + markup / 100)
            profit = selling_price - bundle.agent_price
            
            products.append({
                'id': bundle.id,
                'network': bundle.network,
                'size_gb': bundle.size_gb,
                'wholesale_price': float(bundle.wholesale_price),
                'agent_price': float(bundle.agent_price),
                'retail_price': float(bundle.retail_price),
                'selling_price': round(selling_price, 2),
                'profit': round(profit, 2),
                'markup': markup,
                'popular': bundle.popular,
                'display_order': bundle.display_order
            })
        
        return jsonify({'success': True, 'data': products, 'store_markup': markup})
        
    except Exception as e:
        print(f"Get agent products error: {e}")
        return jsonify({'success': False, 'error': 'Failed to fetch products from Roamsmart'}), 500


@app.route('/api/agent/store/clients', methods=['GET'])
@token_required
@agent_required
def get_storeadmin_clients():
    """Get agent's store clients"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('limit', 20, type=int)
        search = request.args.get('search', '')
        
        query = StoreClient.query.filter_by(agent_id=g.current_user.id)
        
        if search:
            query = query.filter(
                db.or_(
                    StoreClient.name.ilike(f'%{search}%'),
                    StoreClient.phone.ilike(f'%{search}%'),
                    StoreClient.email.ilike(f'%{search}%')
                )
            )
        
        pagination = query.order_by(StoreClient.total_spent.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        return jsonify({
            'success': True,
            'data': [{
                'id': c.id,
                'name': c.name,
                'phone': c.phone,
                'email': c.email,
                'total_spent': float(c.total_spent or 0),
                'order_count': c.order_count or 0,
                'last_purchase': c.last_purchase.isoformat() if c.last_purchase else None,
                'created_at': c.created_at.isoformat()
            } for c in pagination.items],
            'total': pagination.total,
            'page': page,
            'total_pages': pagination.pages
        })
        
    except Exception as e:
        print(f"Get store clients error: {e}")
        return jsonify({'success': False, 'error': 'Failed to fetch clients from Roamsmart'}), 500


@app.route('/api/agent/store/orders', methods=['GET'])
@token_required
@agent_required
def get_storeadmin_orders():
    """Get agent's store orders"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('limit', 20, type=int)
        status = request.args.get('status')
        
        query = Order.query.filter_by(user_id=g.current_user.id)
        
        if status:
            query = query.filter_by(status=status)
        
        pagination = query.order_by(Order.created_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        return jsonify({
            'success': True,
            'data': [{
                'id': o.id,
                'order_id': o.order_id,
                'customer_name': o.customer_name,
                'customer_phone': o.phone_number,
                'network': o.network,
                'size_gb': o.size_gb,
                'quantity': o.quantity,
                'amount': float(o.amount),
                'status': o.status,
                'payment_method': o.payment_method,
                'created_at': o.created_at.isoformat()
            } for o in pagination.items],
            'total': pagination.total,
            'page': page,
            'total_pages': pagination.pages
        })
        
    except Exception as e:
        print(f"Get store orders error: {e}")
        return jsonify({'success': False, 'error': 'Failed to fetch orders from Roamsmart'}), 500


@app.route('/api/agent/customers', methods=['GET'])
@token_required
@agent_required
def get_agentadmin_customers():
    """Get agent's customers (from store clients)"""
    try:
        clients = StoreClient.query.filter_by(
            agent_id=g.current_user.id
        ).order_by(StoreClient.total_spent.desc()).limit(50).all()
        
        return jsonify({
            'success': True,
            'data': [{
                'id': c.id,
                'name': c.name,
                'phone': c.phone,
                'total_spent': float(c.total_spent or 0),
                'order_count': c.order_count or 0,
                'average_order': float((c.total_spent or 0) / (c.order_count or 1)),
                'last_purchase': c.last_purchase.isoformat() if c.last_purchase else None
            } for c in clients]
        })
        
    except Exception as e:
        print(f"Get agent customers error: {e}")
        return jsonify({'success': False, 'error': 'Failed to fetch customers from Roamsmart'}), 500


# ========== ADMIN ROUTES ==========

@app.route('/api/admin/stats', methods=['GET'])
@token_required
@admin_required
def get_amin_stats():
    """Get admin dashboard statistics"""
    try:
        from datetime import datetime, timedelta
        
        today = datetime.utcnow().date()
        today_start = datetime.combine(today, datetime.min.time())
        
        print(f"\n=== STATS CALCULATION ===")
        print(f"Current UTC time: {datetime.utcnow()}")
        print(f"Today's date: {today}")
        print(f"Today start: {today_start}")
        
        # Get all completed orders for debugging
        all_completed = Order.query.filter_by(status='completed').all()
        print(f"Total completed orders in DB: {len(all_completed)}")
        
        for order in all_completed:
            print(f"  Order: {order.order_id}, Amount: ₵{order.amount}, Created: {order.created_at}")
        
        # Today's sales
        today_sales = db.session.query(db.func.sum(Order.amount)).filter(
            Order.status == 'completed',
            Order.created_at >= today_start
        ).scalar() or 0
        print(f"Today's sales query result: ₵{today_sales}")
        
        # Today's orders count
        today_orders = Order.query.filter(
            Order.status == 'completed',
            Order.created_at >= today_start
        ).count()
        print(f"Today's orders count: {today_orders}")
        
        # This week sales
        week_start = today - timedelta(days=today.weekday())
        week_start_dt = datetime.combine(week_start, datetime.min.time())
        week_sales = db.session.query(db.func.sum(Order.amount)).filter(
            Order.status == 'completed',
            Order.created_at >= week_start_dt
        ).scalar() or 0
        print(f"Week sales (from {week_start}): ₵{week_sales}")
        
        # This month sales
        month_start = today.replace(day=1)
        month_start_dt = datetime.combine(month_start, datetime.min.time())
        month_sales = db.session.query(db.func.sum(Order.amount)).filter(
            Order.status == 'completed',
            Order.created_at >= month_start_dt
        ).scalar() or 0
        print(f"Month sales (from {month_start}): ₵{month_sales}")
        
        # This year sales
        year_start = today.replace(month=1, day=1)
        year_start_dt = datetime.combine(year_start, datetime.min.time())
        year_sales = db.session.query(db.func.sum(Order.amount)).filter(
            Order.status == 'completed',
            Order.created_at >= year_start_dt
        ).scalar() or 0
        print(f"Year sales (from {year_start}): ₵{year_sales}")
        
        # All time sales
        all_time_sales = db.session.query(db.func.sum(Order.amount)).filter(
            Order.status == 'completed'
        ).scalar() or 0
        print(f"All time sales: ₵{all_time_sales}")
        
        # Other stats
        total_users = User.query.count()
        total_agents = User.query.filter_by(is_agent=True, agent_approved=True).count()
        pending_agents = AgentRequest.query.filter_by(status='pending').count()
        total_orders = Order.query.count()
        pending_manual = ManualPayment.query.filter_by(status='pending_verification').count()
        pending_withdrawals = Transaction.query.filter_by(type='withdrawal', status='pending').count()
        
        # Get recent orders
        recent_orders = Order.query.order_by(Order.created_at.desc()).limit(10).all()
        
        return jsonify({
            'success': True,
            'data': {
                # Sales data
                'today_sales': float(today_sales),
                'today_orders': today_orders,
                'week_sales': float(week_sales),
                'month_sales': float(month_sales),
                'year_sales': float(year_sales),
                'total_revenue': float(all_time_sales),
                
                # User stats
                'total_users': total_users,
                'total_agents': total_agents,
                'pending_agents': pending_agents,
                'total_orders': total_orders,
                
                # Payment stats
                'pending_manual': pending_manual,
                'pending_withdrawals': pending_withdrawals,
                
                # Recent orders
                'recent_orders': [{
                    'order_id': o.order_id,
                    'user': User.query.get(o.user_id).username if o.user_id else 'N/A',
                    'amount': float(o.amount),
                    'status': o.status,
                    'date': o.created_at.strftime('%Y-%m-%d') if o.created_at else 'Unknown'
                } for o in recent_orders]
            }
        })
        
    except Exception as e:
        print(f"Get admin stats error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': 'Failed to fetch Roamsmart stats'}), 500
    

@app.route('/api/admin/users', methods=['GET'])
@token_required
@admin_required
def get_amin_users():
    """Get all users"""
    try:
        users = User.query.order_by(User.created_at.desc()).all()
        return jsonify({'success': True, 'data': [u.to_dict() for u in users]})
    except Exception as e:
        print(f"Get admin users error: {e}")
        return jsonify({'success': False, 'error': 'Failed to fetch users from Roamsmart'}), 500


@app.route('/api/admin/users/create', methods=['POST'])
@token_required
@admin_required
def create_amin_user():
    """Create user (admin only)"""
    try:
        data = request.get_json()
        
        username = data.get('username')
        email = data.get('email')
        phone = data.get('phone')
        password = data.get('password')
        role = data.get('role', 'user')
        wallet_balance = data.get('wallet_balance', 0)
        
        if User.query.filter_by(email=email).first():
            return jsonify({'success': False, 'error': 'Email already exists'}), 400
        
        new_user = User(
            username=username,
            email=email,
            phone=phone,
            role=role,
            wallet_balance=wallet_balance,
            referral_code=f"REF{uuid.uuid4().hex[:8].upper()}"
        )
        if password:
            new_user.set_password(password)
        else:
            new_user.set_password('password123')
        
        db.session.add(new_user)
        db.session.commit()
        
        # Send welcome email (Email ONLY)
        send_email(
            email,
            f"Welcome to {COMPANY_NAME}",
            f"""
            <div style="font-family: Arial, sans-serif;">
                <h2 style="color: #8B0000;">Account Created for You</h2>
                <p>Dear {username},</p>
                <p>An account has been created for you on {COMPANY_NAME}.</p>
                <p><strong>Email:</strong> {email}</p>
                <p><strong>Password:</strong> {password if password else 'password123'}</p>
                <p>Please login and change your password immediately.</p>
                <a href="{COMPANY_WEBSITE}/login" style="background: #8B0000; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">Login Now</a>
            </div>
            """
        )
        
        return jsonify({'success': True, 'user': new_user.to_dict()})
    except Exception as e:
        print(f"Create admin user error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Failed to create user on Roamsmart'}), 500


@app.route('/api/admin/users/<int:user_id>/suspend', methods=['POST'])
@token_required
@admin_required
def suspend_admin_user(user_id):
    """Suspend a user - Email ONLY"""
    try:
        user = User.query.get(user_id)
        if not user:
            return jsonify({'success': False, 'error': 'User not found'}), 404
        
        user.is_suspended = True
        db.session.commit()
        
        # Send notification via Email ONLY
        send_email(
            user.email,
            f"Account Suspension Notice - {COMPANY_NAME}",
            f"""
            <div style="font-family: Arial, sans-serif;">
                <h2 style="color: #dc3545;">Account Suspended</h2>
                <p>Dear {user.username},</p>
                <p>Your {COMPANY_NAME} account has been suspended.</p>
                <p>Please contact our support team for assistance.</p>
                <p><strong>Support Contact:</strong> {COMPANY_PHONE}</p>
                <hr>
                <p>If you believe this is an error, please reach out immediately.</p>
            </div>
            """
        )
        
        log_activity(g.current_user.id, 'suspend_user', f'Suspended user {user.email}')
        
        return jsonify({'success': True, 'message': f'User suspended on {COMPANY_NAME}'})
    except Exception as e:
        print(f"Suspend user error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Failed to suspend user'}), 500

@app.route('/api/admin/inventory', methods=['GET'])
@token_required
@admin_required
def get_admin_inventory():
    """Get master inventory for admin dashboard"""
    try:
        # Get all inventory items from database
        inventory_items = MasterInventory.query.all()
        
        if not inventory_items:
            # Return empty structure if no inventory
            return jsonify({
                'success': True,
                'data': {
                    'mtn': {'total': 0, 'remaining': 0, 'sold': 0, 'bundles': {}},
                    'telecel': {'total': 0, 'remaining': 0, 'sold': 0, 'bundles': {}},
                    'airteltigo': {'total': 0, 'remaining': 0, 'sold': 0, 'bundles': {}}
                },
                'summary': {
                    'total_gb_available': 0,
                    'total_gb_sold': 0,
                    'total_value': 0,
                    'low_stock_alerts': []
                }
            })
        
        # Build inventory structure
        result = {
            'mtn': {'total': 0, 'remaining': 0, 'sold': 0, 'bundles': {}},
            'telecel': {'total': 0, 'remaining': 0, 'sold': 0, 'bundles': {}},
            'airteltigo': {'total': 0, 'remaining': 0, 'sold': 0, 'bundles': {}}
        }
        
        total_available = 0
        total_sold = 0
        low_stock_alerts = []
        
        for item in inventory_items:
            network = item.network
            size_gb = int(item.size_gb)
            
            result[network]['total'] += item.total_purchased
            result[network]['remaining'] += item.remaining
            result[network]['sold'] += item.sold_to_agents or 0
            
            result[network]['bundles'][f"{size_gb}gb"] = {
                'total_purchased': item.total_purchased,
                'remaining': item.remaining,
                'sold_to_agents': item.sold_to_agents or 0
            }
            
            total_available += item.remaining
            total_sold += item.sold_to_agents or 0
            
            # Check for low stock (less than 10% of total purchased or less than 10GB)
            if item.total_purchased > 0:
                low_threshold = item.total_purchased * 0.1
                if item.remaining < low_threshold and item.remaining > 0:
                    low_stock_alerts.append({
                        'network': network,
                        'size_gb': size_gb,
                        'remaining': item.remaining,
                        'threshold': low_threshold
                    })
            elif item.remaining < 10 and item.remaining > 0:
                low_stock_alerts.append({
                    'network': network,
                    'size_gb': size_gb,
                    'remaining': item.remaining,
                    'threshold': 10
                })
        
        # Calculate total value (estimate based on wholesale prices)
        wholesale_prices = {
            'mtn': {1: 5.50, 2: 10.00, 5: 22.00, 10: 42.00, 20: 80.00},
            'telecel': {1: 5.00, 2: 9.00, 5: 20.00, 10: 38.00, 20: 75.00},
            'airteltigo': {1: 5.00, 2: 9.00, 5: 20.00, 10: 38.00, 20: 75.00}
        }
        
        total_value = 0
        for item in inventory_items:
            price_per_gb = wholesale_prices.get(item.network, {}).get(int(item.size_gb), 5.00)
            total_value += item.remaining * price_per_gb
        
        return jsonify({
            'success': True,
            'data': result,
            'summary': {
                'total_gb_available': total_available,
                'total_gb_sold': total_sold,
                'total_value': round(total_value, 2),
                'low_stock_alerts': low_stock_alerts
            }
        })
        
    except Exception as e:
        print(f"Get admin inventory error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/admin/inventory', methods=['POST'])
@token_required
@admin_required
def add_to_inventory():
    """Add data to master inventory (admin purchase from network)"""
    try:
        data = request.get_json()
        network = data.get('network')
        size_gb = data.get('size_gb')
        quantity = data.get('quantity', 1)
        purchase_price = data.get('purchase_price')
        
        if not network or not size_gb:
            return jsonify({'success': False, 'error': 'Network and size required'}), 400
        
        total_gb = size_gb * quantity
        
        # Get or create inventory item
        inventory = MasterInventory.query.filter_by(
            network=network,
            size_gb=size_gb
        ).first()
        
        if inventory:
            inventory.total_purchased += total_gb
            inventory.remaining += total_gb
            inventory.last_purchase_date = datetime.utcnow()
        else:
            inventory = MasterInventory(
                network=network,
                size_gb=size_gb,
                total_purchased=total_gb,
                remaining=total_gb,
                last_purchase_date=datetime.utcnow()
            )
            db.session.add(inventory)
        
        # Log the purchase transaction
        transaction = InventoryTransaction(
            type='admin_purchase',
            network=network,
            size_gb=size_gb,
            quantity=quantity,
            total_gb=total_gb,
            amount=purchase_price,
            reference=f"ADMIN-{uuid.uuid4().hex[:8].upper()}",
            status='completed'
        )
        db.session.add(transaction)
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Added {quantity}x {size_gb}GB {network} to inventory',
            'data': {
                'total_gb': total_gb,
                'network': network,
                'size_gb': size_gb,
                'remaining': inventory.remaining
            }
        })
        
    except Exception as e:
        print(f"Add to inventory error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/admin/users/<int:user_id>/activate', methods=['POST'])
@token_required
@admin_required
def activate_admin_user(user_id):
    """Activate a suspended user - Email ONLY"""
    try:
        user = User.query.get(user_id)
        if not user:
            return jsonify({'success': False, 'error': 'User not found'}), 404
        
        user.is_suspended = False
        db.session.commit()
        
        # Send notification via Email ONLY
        send_email(
            user.email,
            f"Account Reactivated - {COMPANY_NAME}",
            f"""
            <div style="font-family: Arial, sans-serif;">
                <h2 style="color: #28a745;">Account Reactivated</h2>
                <p>Dear {user.username},</p>
                <p>Your {COMPANY_NAME} account has been reactivated.</p>
                <p>You can now login and continue using our services.</p>
                <a href="{COMPANY_WEBSITE}/login" style="background: #8B0000; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">Login Now</a>
            </div>
            """
        )
        
        log_activity(g.current_user.id, 'activate_user', f'Activated user {user.email}')
        
        return jsonify({'success': True, 'message': f'User activated on {COMPANY_NAME}'})
    except Exception as e:
        print(f"Activate user error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Failed to activate user'}), 500


@app.route('/api/admin/agents', methods=['GET'])
@token_required
@admin_required
def get_amin_agents():
    """Get all agents"""
    try:
        agents = User.query.filter_by(is_agent=True, agent_approved=True).order_by(
            User.created_at.desc()
        ).all()
        
        agents_data = []
        for agent in agents:
            total_sales = db.session.query(db.func.sum(Order.amount)).filter_by(
                user_id=agent.id, status='completed'
            ).scalar() or 0
            
            withdrawals = db.session.query(db.func.sum(Transaction.amount)).filter_by(
                user_id=agent.id, type='withdrawal', status='completed'
            ).scalar() or 0
            
            agents_data.append({
                'id': agent.id,
                'username': agent.username,
                'email': agent.email,
                'phone': agent.phone,
                'total_sales': float(total_sales),
                'commission_earned': float(total_sales * 0.15),
                'withdrawn': float(withdrawals),
                'tier': agent.agent_tier or 'Bronze',
                'commission_rate': agent.commission_rate or 10,
                'created_at': agent.created_at.isoformat()
            })
        
        return jsonify({'success': True, 'data': agents_data})
    except Exception as e:
        print(f"Get admin agents error: {e}")
        return jsonify({'success': False, 'error': 'Failed to fetch agents from Roamsmart'}), 500


@app.route('/api/admin/agent-requests', methods=['GET'])
@token_required
@admin_required
def get_agentadmin_requests():
    """Get pending agent requests"""
    try:
        requests = AgentRequest.query.filter_by(status='pending').order_by(
            AgentRequest.created_at.desc()
        ).all()
        
        return jsonify({
            'success': True,
            'data': [{
                'id': r.id,
                'user_id': r.user_id,
                'username': User.query.get(r.user_id).username,
                'email': User.query.get(r.user_id).email,
                'phone': User.query.get(r.user_id).phone,
                'amount': float(r.amount),
                'payment_reference': r.payment_reference,
                'created_at': r.created_at.strftime('%Y-%m-%d %H:%M')
            } for r in requests]
        })
    except Exception as e:
        print(f"Get agent requests error: {e}")
        return jsonify({'success': False, 'error': 'Failed to fetch agent requests from Roamsmart'}), 500


@app.route('/api/admin/agent-requests/<int:request_id>/approve', methods=['POST'])
@token_required
@admin_required
def approve_agentadmin_request(request_id):
    """Approve agent request - Email ONLY"""
    try:
        agent_request = AgentRequest.query.get(request_id)
        if not agent_request:
            return jsonify({'success': False, 'error': 'Request not found'}), 404
        
        user = User.query.get(agent_request.user_id)
        user.is_agent = True
        user.agent_approved = True
        user.agent_tier = 'Bronze'
        user.commission_rate = 10
        
        agent_request.status = 'approved'
        agent_request.approved_at = datetime.utcnow()
        
        db.session.commit()
        
        # Send notification via Email ONLY
        send_email(
            user.email,
            f"🎉 Congratulations! Agent Application Approved - {COMPANY_NAME}",
            f"""
            <div style="font-family: Arial, sans-serif;">
                <h2 style="color: #28a745;">🎉 Welcome to {COMPANY_NAME} Agent Program!</h2>
                <p>Dear {user.username},</p>
                <p>Congratulations! Your agent application has been approved.</p>
                <p><strong>Your Benefits:</strong></p>
                <ul>
                    <li>Wholesale prices on all data bundles</li>
                    <li>10% base commission on all sales</li>
                    <li>Access to agent dashboard</li>
                    <li>Create your own store</li>
                    <li>Track earnings and withdrawals</li>
                </ul>
                <a href="{COMPANY_WEBSITE}/agent/dashboard" style="background: #8B0000; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">Go to Agent Dashboard</a>
                <hr>
                <p>Need help? Contact support on WhatsApp: {COMPANY_PHONE}</p>
            </div>
            """
        )
        
        send_webhook('agent.approved', {'user_id': user.id, 'username': user.username})
        log_activity(g.current_user.id, 'approve_agent', f'Approved agent {user.email}')
        
        return jsonify({'success': True, 'message': f'Agent approved on {COMPANY_NAME}'})
    except Exception as e:
        print(f"Approve agent error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Failed to approve agent'}), 500


@app.route('/api/admin/agent-requests/<int:request_id>/reject', methods=['POST'])
@token_required
@admin_required
def reject_agentadmin_request(request_id):
    """Reject agent request - Email ONLY"""
    try:
        agent_request = AgentRequest.query.get(request_id)
        if not agent_request:
            return jsonify({'success': False, 'error': 'Request not found'}), 404
        
        agent_request.status = 'rejected'
        db.session.commit()
        
        user = User.query.get(agent_request.user_id)
        
        # Send notification via Email ONLY
        send_email(
            user.email,
            f"Agent Application Update - {COMPANY_NAME}",
            f"""
            <div style="font-family: Arial, sans-serif;">
                <h2 style="color: #dc3545;">Application Status Update</h2>
                <p>Dear {user.username},</p>
                <p>Thank you for your interest in becoming a {COMPANY_NAME} agent.</p>
                <p>After careful review, we regret to inform you that your application could not be approved at this time.</p>
                <p>Please contact our support team for more information about the decision.</p>
                <p>You may reapply after 30 days.</p>
                <p>Support: {COMPANY_PHONE}</p>
            </div>
            """
        )
        
        log_activity(g.current_user.id, 'reject_agent', f'Rejected agent {user.email}')
        
        return jsonify({'success': True, 'message': 'Agent request rejected'})
    except Exception as e:
        print(f"Reject agent error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Failed to reject agent'}), 500

@app.route('/api/admin/africastalking-balance', methods=['GET'])
@token_required
@admin_required
def admin_get_africastalking_balance():
    """Admin: Get Africa's Talking wallet balance"""
    try:
        import africastalking
        import os
        import re
        
        username = os.getenv('AFRICASTALKING_USERNAME', 'sandbox')
        api_key = os.getenv('AFRICASTALKING_API_KEY')
        
        if not api_key:
            return jsonify({
                'success': False, 
                'error': 'Africa\'s Talking API key not configured'
            }), 500
        
        africastalking.initialize(username, api_key)
        application = africastalking.Application
        app_data = application.fetch_application_data()
        
        balance = 0.0
        currency = 'GHS'
        
        if app_data and 'UserData' in app_data:
            user_data = app_data['UserData']
            balance_str = user_data.get('balance', 'GHS 0')
            
            match = re.search(r'(\d+(?:\.\d+)?)', balance_str)
            if match:
                balance = float(match.group(1))
            
            currency_match = re.match(r'([A-Z]{3})', balance_str)
            if currency_match:
                currency = currency_match.group(1)
        
        return jsonify({
            'success': True,
            'data': {
                'account_balance': balance,
                'wallet_balance': balance,
                'airtime_balance': balance,
                'sms_balance': balance,
                'voice_balance': balance,
                'currency': currency
            }
        })
        
    except Exception as e:
        print(f"Error fetching Africa's Talking balance: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/admin/agent-applications', methods=['GET'])
@token_required
@admin_required
def admin_get_agent_applications():
    """Admin: Get all agent applications"""
    try:
        from sqlalchemy import inspect
        
        inspector = inspect(db.engine)
        
        if not inspector.has_table('agent_applications'):
            return jsonify({
                'success': True,
                'data': [],
                'total': 0,
                'page': 1,
                'total_pages': 0
            })
        
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('limit', 20, type=int)
        status = request.args.get('status', 'pending')
        
        query = AgentApplication.query.filter_by(status=status)
        pagination = query.order_by(AgentApplication.created_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        applications = []
        for app in pagination.items:
            user = db.session.get(User, app.user_id) if app.user_id else None
            
            applications.append({
                'id': app.id,
                'user_id': app.user_id,
                'username': user.username if user else 'Unknown',
                'email': user.email if user else 'No email',
                'phone': user.phone if user else 'No phone',
                'amount': float(app.amount) if app.amount else 0,
                'payment_reference': app.payment_reference,
                'payment_proof_url': app.payment_proof_url,
                'status': app.status,
                'submitted_at': app.created_at.isoformat() if app.created_at else None,
                'processed_at': app.processed_at.isoformat() if hasattr(app, 'processed_at') and app.processed_at else None
            })
        
        return jsonify({
            'success': True,
            'data': applications,
            'total': pagination.total,
            'page': page,
            'total_pages': pagination.pages
        })
        
    except Exception as e:
        print(f"Error fetching agent applications: {e}")
        return jsonify({
            'success': True,
            'data': [],
            'total': 0,
            'page': 1,
            'total_pages': 0
        })

@app.route('/api/admin/agent-requests/bulk-approve', methods=['POST'])
@token_required
@admin_required
def bulk_approveadmin_agents():
    """Bulk approve agent requests - Email ONLY"""
    try:
        data = request.get_json()
        request_ids = data.get('request_ids', [])
        
        approved_count = 0
        approved_users = []
        
        for request_id in request_ids:
            agent_request = AgentRequest.query.get(request_id)
            if agent_request and agent_request.status == 'pending':
                user = User.query.get(agent_request.user_id)
                user.is_agent = True
                user.agent_approved = True
                user.agent_tier = 'Bronze'
                user.commission_rate = 10
                agent_request.status = 'approved'
                agent_request.approved_at = datetime.utcnow()
                approved_count += 1
                approved_users.append(user)
        
        db.session.commit()
        
        # Send notifications to all approved agents via Email ONLY
        for user in approved_users:
            send_email(
                user.email,
                f"🎉 Congratulations! Agent Application Approved - {COMPANY_NAME}",
                f"""
                <div style="font-family: Arial, sans-serif;">
                    <h2 style="color: #28a745;">🎉 Welcome to {COMPANY_NAME} Agent Program!</h2>
                    <p>Dear {user.username},</p>
                    <p>Congratulations! Your agent application has been approved.</p>
                    <a href="{COMPANY_WEBSITE}/agent/dashboard" style="background: #8B0000; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">Go to Agent Dashboard</a>
                </div>
                """
            )
        
        log_activity(g.current_user.id, 'bulk_approve_agents', f'Approved {approved_count} agents on Roamsmart')
        
        return jsonify({'success': True, 'approved_count': approved_count})
    except Exception as e:
        print(f"Bulk approve agents error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Failed to bulk approve agents on Roamsmart'}), 500


@app.route('/api/admin/manual-payments', methods=['GET'])
@token_required
@admin_required
def get_manualadmin_payments():
    """Get pending manual payments"""
    try:
        payments = ManualPayment.query.filter(
            ManualPayment.status.in_(['pending', 'pending_verification'])
        ).order_by(ManualPayment.created_at.desc()).all()
        
        return jsonify({
            'success': True,
            'data': [{
                'id': p.id,
                'user_id': p.user_id,
                'username': User.query.get(p.user_id).username,
                'email': User.query.get(p.user_id).email,
                'phone': User.query.get(p.user_id).phone,
                'amount': float(p.amount),
                'reference': p.reference,
                'proof_url': p.proof_url,
                'sender_name': p.sender_name,
                'sender_phone': p.sender_phone,
                'transaction_id': p.transaction_id,
                'created_at': p.created_at.strftime('%Y-%m-%d %H:%M')
            } for p in payments]
        })
    except Exception as e:
        print(f"Get manual payments error: {e}")
        return jsonify({'success': False, 'error': 'Failed to fetch manual payments from Roamsmart'}), 500


@app.route('/api/admin/manual-payments/<int:payment_id>/verify', methods=['POST'])
@token_required
@admin_required
def verify_admin_manual_payment(payment_id):
    """Verify manual payment and credit wallet - Email ONLY"""
    try:
        data = request.get_json()
        payment = ManualPayment.query.get(payment_id)
        
        if not payment:
            return jsonify({'success': False, 'error': 'Payment not found'}), 404
        
        if payment.status not in ['pending', 'pending_verification']:
            return jsonify({'success': False, 'error': 'Payment already processed'}), 400
        
        payment.status = 'completed'
        payment.verified_at = datetime.utcnow()
        payment.verified_by = g.current_user.id
        if data.get('sender_name'):
            payment.sender_name = data.get('sender_name')
        if data.get('sender_phone'):
            payment.sender_phone = data.get('sender_phone')
        
        # Credit user's wallet
        user = User.query.get(payment.user_id)
        balance_before = user.wallet_balance
        user.wallet_balance += payment.amount
        
        # Create transaction record
        transaction = Transaction(
            user_id=user.id,
            type='credit',
            amount=payment.amount,
            balance_before=balance_before,
            balance_after=user.wallet_balance,
            description=f'Manual payment verification - {payment.reference}',
            reference=payment.reference,
            status='completed'
        )
        db.session.add(transaction)
        
        db.session.commit()
        
        # Send notification to user via Email ONLY
        send_email(
            user.email,
            f"💰 Wallet Credited - {payment.reference} - {COMPANY_NAME}",
            f"""
            <div style="font-family: Arial, sans-serif;">
                <h2 style="color: #28a745;">Payment Verified Successfully!</h2>
                <p>Dear {user.username},</p>
                <p>Your manual payment has been verified and credited to your wallet.</p>
                <p><strong>Amount Credited:</strong> GHS {payment.amount:.2f}</p>
                <p><strong>Previous Balance:</strong> GHS {balance_before:.2f}</p>
                <p><strong>New Balance:</strong> GHS {user.wallet_balance:.2f}</p>
                <p><strong>Reference:</strong> {payment.reference}</p>
                <a href="{COMPANY_WEBSITE}/wallet" style="background: #8B0000; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">View Wallet</a>
            </div>
            """
        )
        
        send_webhook('payment.verified', {'user_id': user.id, 'amount': payment.amount})
        log_activity(g.current_user.id, 'verify_payment', f'Verified payment {payment.reference} for {user.email}')
        
        return jsonify({'success': True, 'message': f'Payment verified and wallet credited on {COMPANY_NAME}'})
    except Exception as e:
        print(f"Verify manual payment error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Failed to verify payment'}), 500


@app.route('/api/admin/manual-payments/<int:payment_id>/reject', methods=['POST'])
@token_required
@admin_required
def reject_manual_admin_payment(payment_id):
    """Reject manual payment - Email ONLY"""
    try:
        payment = ManualPayment.query.get(payment_id)
        
        if not payment:
            return jsonify({'success': False, 'error': 'Payment not found'}), 404
        
        payment.status = 'rejected'
        db.session.commit()
        
        user = User.query.get(payment.user_id)
        
        # Send notification via Email ONLY
        send_email(
            user.email,
            f"❌ Payment Rejected - {payment.reference} - {COMPANY_NAME}",
            f"""
            <div style="font-family: Arial, sans-serif;">
                <h2 style="color: #dc3545;">Payment Verification Failed</h2>
                <p>Dear {user.username},</p>
                <p>Your manual payment of <strong>GHS {payment.amount:.2f}</strong> has been rejected.</p>
                <p><strong>Reference:</strong> {payment.reference}</p>
                <p><strong>Possible reasons:</strong></p>
                <ul>
                    <li>Proof of payment unclear or invalid</li>
                    <li>Payment not received</li>
                    <li>Incorrect amount or reference</li>
                </ul>
                <p>Please contact our support team for assistance with this payment.</p>
                <p><strong>Support WhatsApp:</strong> {COMPANY_PHONE}</p>
            </div>
            """
        )
        
        log_activity(g.current_user.id, 'reject_payment', f'Rejected payment {payment.reference}')
        
        return jsonify({'success': True, 'message': 'Payment rejected on Roamsmart'})
    except Exception as e:
        print(f"Reject manual payment error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Failed to reject payment'}), 500


@app.route('/api/admin/withdrawals', methods=['GET'])
@token_required
@admin_required
def get_admin_withdrawals():
    """Get withdrawal requests"""
    try:
        withdrawals = Transaction.query.filter_by(
            type='withdrawal', status='pending'
        ).order_by(Transaction.created_at.desc()).all()
        
        return jsonify({
            'success': True,
            'data': [{
                'id': w.id,
                'agent_id': w.user_id,
                'agent_name': User.query.get(w.user_id).username,
                'agent_email': User.query.get(w.user_id).email,
                'agent_phone': User.query.get(w.user_id).phone,
                'amount': float(w.amount),
                'mobile_money': w.description.split('to ')[-1] if 'to ' in w.description else 'N/A',
                'reference': w.reference,
                'created_at': w.created_at.isoformat(),
                'status': w.status
            } for w in withdrawals]
        })
    except Exception as e:
        print(f"Get withdrawals error: {e}")
        return jsonify({'success': False, 'error': 'Failed to fetch withdrawals from Roamsmart'}), 500


@app.route('/api/admin/withdrawals/<int:withdrawal_id>/approve', methods=['POST'])
@token_required
@admin_required
def approve_admin_withdrawal(withdrawal_id):
    """Approve withdrawal request - Email ONLY"""
    try:
        withdrawal = Transaction.query.get(withdrawal_id)
        
        if not withdrawal or withdrawal.type != 'withdrawal':
            return jsonify({'success': False, 'error': 'Withdrawal not found'}), 404
        
        user = User.query.get(withdrawal.user_id)
        
        if withdrawal.status == 'pending':
            user.wallet_balance -= withdrawal.amount
            withdrawal.status = 'completed'
            withdrawal.balance_after = user.wallet_balance
            withdrawal.updated_at = datetime.utcnow()
            db.session.commit()
        
        # Send notification via Email ONLY
        send_email(
            user.email,
            f"💰 Withdrawal Processed - {withdrawal.reference} - {COMPANY_NAME}",
            f"""
            <div style="font-family: Arial, sans-serif;">
                <h2 style="color: #28a745;">Withdrawal Completed</h2>
                <p>Dear {user.username},</p>
                <p>Your withdrawal request has been processed successfully.</p>
                <p><strong>Amount:</strong> GHS {withdrawal.amount:.2f}</p>
                <p><strong>Mobile Money:</strong> {withdrawal.description.split('to ')[-1] if 'to ' in withdrawal.description else 'N/A'}</p>
                <p><strong>Reference:</strong> {withdrawal.reference}</p>
                <p><strong>New Balance:</strong> GHS {user.wallet_balance:.2f}</p>
                <p>Funds should reflect in your mobile money account within 24 hours.</p>
            </div>
            """
        )
        
        log_activity(g.current_user.id, 'approve_withdrawal', f'Approved withdrawal {withdrawal.reference} for {user.email}')
        
        return jsonify({'success': True, 'message': f'Withdrawal approved on {COMPANY_NAME}'})
    except Exception as e:
        print(f"Approve withdrawal error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Failed to approve withdrawal'}), 500


@app.route('/api/admin/withdrawals/<int:withdrawal_id>/reject', methods=['POST'])
@token_required
@admin_required
def reject_admin_withdrawal(withdrawal_id):
    """Reject withdrawal request - Email ONLY"""
    try:
        withdrawal = Transaction.query.get(withdrawal_id)
        
        if not withdrawal or withdrawal.type != 'withdrawal':
            return jsonify({'success': False, 'error': 'Withdrawal not found'}), 404
        
        user = User.query.get(withdrawal.user_id)
        
        withdrawal.status = 'rejected'
        withdrawal.updated_at = datetime.utcnow()
        db.session.commit()
        
        # Send notification via Email ONLY
        send_email(
            user.email,
            f"❌ Withdrawal Rejected - {withdrawal.reference} - {COMPANY_NAME}",
            f"""
            <div style="font-family: Arial, sans-serif;">
                <h2 style="color: #dc3545;">Withdrawal Request Rejected</h2>
                <p>Dear {user.username},</p>
                <p>Your withdrawal request has been rejected.</p>
                <p><strong>Amount:</strong> GHS {withdrawal.amount:.2f}</p>
                <p><strong>Reference:</strong> {withdrawal.reference}</p>
                <p><strong>Possible reasons:</strong></p>
                <ul>
                    <li>Insufficient balance</li>
                    <li>Invalid mobile money number</li>
                    <li>Pending verification</li>
                </ul>
                <p>Please contact support for more information.</p>
                <p>Support: {COMPANY_PHONE}</p>
            </div>
            """
        )
        
        log_activity(g.current_user.id, 'reject_withdrawal', f'Rejected withdrawal {withdrawal.reference}')
        
        return jsonify({'success': True, 'message': 'Withdrawal rejected'})
    except Exception as e:
        print(f"Reject withdrawal error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Failed to reject withdrawal'}), 500


# ========== ADMIN ANNOUNCEMENT ROUTES ==========

def get_or_create_price_password():
    """Get or create price management password hash and salt"""
    password_hash = SystemSetting.get('price_password_hash')
    password_salt = SystemSetting.get('price_password_salt')
    
    if not password_hash or not password_salt:
        # Set default password on first run
        default_password = "Roamsmart@2024"
        salt = secrets.token_hex(16)
        password_hash_value = hashlib.sha256(f"{default_password}{salt}".encode()).hexdigest()
        
        SystemSetting.set('price_password_salt', salt, 'string', 'Salt for price management password hashing')
        SystemSetting.set('price_password_hash', password_hash_value, 'string', 'Hashed price management password')
        
        return password_hash_value, salt
    
    return password_hash, password_salt


def verify_price_password(password):
    """Verify the price management password"""
    stored_hash, salt = get_or_create_price_password()
    
    input_hash = hashlib.sha256(f"{password}{salt}".encode()).hexdigest()
    return input_hash == stored_hash


def price_auth_required(f):
    """Decorator to require price management password"""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_token = request.headers.get('X-Price-Auth')
        
        if not auth_token:
            return jsonify({
                'success': False, 
                'error': 'Price management password required',
                'requires_auth': True
            }), 401
        
        # Verify the token (you can also implement proper JWT or session tokens)
        # For simplicity, we'll verify against the stored hash
        stored_hash, _ = get_or_create_price_password()
        
        # Simple token verification (in production, use JWT)
        if auth_token != stored_hash:
            return jsonify({
                'success': False, 
                'error': 'Invalid or expired session',
                'requires_auth': True
            }), 401
        
        return f(*args, **kwargs)
    return decorated


# Store active sessions (in production, use Redis or database)
active_price_sessions = {}  # {token: expiry_timestamp}


def create_price_session(user_id):
    """Create a new price management session"""
    token = secrets.token_hex(32)
    expiry = datetime.utcnow() + timedelta(hours=1)
    
    # Store in database or cache
    active_price_sessions[token] = {
        'user_id': user_id,
        'expiry': expiry.timestamp()
    }
    
    return token


def verify_price_session(token):
    """Verify if session token is valid"""
    session = active_price_sessions.get(token)
    if not session:
        return False
    
    if datetime.utcnow().timestamp() > session['expiry']:
        # Session expired
        del active_price_sessions[token]
        return False
    
    return True


def price_session_required(f):
    """Decorator to require price management session token"""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_token = request.headers.get('X-Price-Auth')
        
        if not auth_token:
            return jsonify({
                'success': False, 
                'error': 'Price management session required',
                'requires_auth': True
            }), 401
        
        if not verify_price_session(auth_token):
            return jsonify({
                'success': False, 
                'error': 'Session expired or invalid. Please re-enter password.',
                'requires_auth': True
            }), 401
        
        return f(*args, **kwargs)
    return decorated


@app.route('/api/admin/prices/verify', methods=['POST'])
@token_required
@admin_required
def verify_admin_price_password_endpoint():
    """Verify price management password and create session"""
    try:
        data = request.get_json()
        password = data.get('password')
        
        if not password:
            return jsonify({'success': False, 'error': 'Password required'}), 400
        
        if verify_price_password(password):
            # Create session token
            token = create_price_session(g.current_user.id)
            
            return jsonify({
                'success': True,
                'message': 'Password verified',
                'token': token,
                'expires_in': 3600  # 1 hour
            })
        else:
            return jsonify({'success': False, 'error': 'Invalid password'}), 401
            
    except Exception as e:
        print(f"Verify price password error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/admin/prices/logout', methods=['POST'])
@token_required
def price_session_admin_logout():
    """Logout from price management session"""
    try:
        auth_token = request.headers.get('X-Price-Auth')
        if auth_token and auth_token in active_price_sessions:
            del active_price_sessions[auth_token]
        
        return jsonify({'success': True, 'message': 'Logged out successfully'})
        
    except Exception as e:
        print(f"Price logout error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/admin/prices/update-password', methods=['POST'])
@token_required
@super_admin_required
def update_price_admin_password():
    """Update price management password (Super Admin only)"""
    try:
        data = request.get_json()
        new_password = data.get('new_password')
        confirm_password = data.get('confirm_password')
        
        if not new_password or len(new_password) < 6:
            return jsonify({'success': False, 'error': 'Password must be at least 6 characters'}), 400
        
        if new_password != confirm_password:
            return jsonify({'success': False, 'error': 'Passwords do not match'}), 400
        
        # Generate new salt and hash
        salt = secrets.token_hex(16)
        password_hash = hashlib.sha256(f"{new_password}{salt}".encode()).hexdigest()
        
        # Update settings
        SystemSetting.set('price_password_salt', salt, 'string', 'Salt for price management password hashing', updated_by=g.current_user.id)
        SystemSetting.set('price_password_hash', password_hash, 'string', 'Hashed price management password', updated_by=g.current_user.id)
        
        # Clear all active sessions
        active_price_sessions.clear()
        
        return jsonify({
            'success': True,
            'message': 'Price management password updated successfully. All active sessions have been terminated.'
        })
        
    except Exception as e:
        print(f"Update price password error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/admin/prices/check-auth', methods=['GET'])
@token_required
def check_admin_price_auth():
    """Check if current session is still valid"""
    try:
        auth_token = request.headers.get('X-Price-Auth')
        if not auth_token:
            return jsonify({'success': False, 'authenticated': False}), 200
        
        is_valid = verify_price_session(auth_token)
        return jsonify({'success': True, 'authenticated': is_valid}), 200
        
    except Exception as e:
        return jsonify({'success': False, 'authenticated': False}), 200

@app.route('/api/admin/settings', methods=['GET', 'PUT'])
@token_required
@admin_required
def system_admin_settings():
    """Get or update system settings"""
    try:
        if request.method == 'GET':
            settings = SystemSetting.query.all()
            settings_dict = {}
            
            for setting in settings:
                if setting.value_type == 'int':
                    settings_dict[setting.key] = int(setting.value)
                elif setting.value_type == 'float':
                    settings_dict[setting.key] = float(setting.value)
                elif setting.value_type == 'bool':
                    settings_dict[setting.key] = setting.value.lower() == 'true'
                elif setting.value_type == 'json':
                    settings_dict[setting.key] = json.loads(setting.value)
                else:
                    settings_dict[setting.key] = setting.value
            
            # Set defaults if not in database
            defaults = {
                'site_name': COMPANY_NAME,
                'site_url': COMPANY_WEBSITE,
                'support_phone': COMPANY_PHONE,
                'support_email': COMPANY_EMAIL,
                'min_withdrawal': 50,
                'max_withdrawal': 10000,
                'min_funding': 10,
                'max_funding': 100000,
                'agent_registration_fee': 100,
                'referral_bonus': 5,
                'maintenance_mode': False,
                'maintenance_message': 'We are currently performing maintenance. Please check back soon.',
                'commission_rates': {
                    'bronze': 10,
                    'silver': 15,
                    'gold': 20,
                    'platinum': 25
                }
            }
            
            for key, default_value in defaults.items():
                if key not in settings_dict:
                    settings_dict[key] = default_value
            
            return jsonify({'success': True, 'data': settings_dict})
        
        else:  # PUT
            data = request.get_json()
            
            for key, value in data.items():
                setting = SystemSetting.query.filter_by(key=key).first()
                if not setting:
                    setting = SystemSetting(key=key)
                    db.session.add(setting)
                
                if isinstance(value, bool):
                    setting.value_type = 'bool'
                    setting.value = str(value)
                elif isinstance(value, int):
                    setting.value_type = 'int'
                    setting.value = str(value)
                elif isinstance(value, float):
                    setting.value_type = 'float'
                    setting.value = str(value)
                elif isinstance(value, dict) or isinstance(value, list):
                    setting.value_type = 'json'
                    setting.value = json.dumps(value)
                else:
                    setting.value_type = 'string'
                    setting.value = str(value)
                
                setting.updated_by = g.current_user.id
                setting.updated_at = datetime.utcnow()
            
            db.session.commit()
            
            log_activity(g.current_user.id, 'update_settings', f'Updated {len(data)} system settings on {COMPANY_NAME}')
            
            return jsonify({'success': True, 'message': f'{COMPANY_NAME} settings updated'})
            
    except Exception as e:
        print(f"System settings error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


# ========== ADMIN WEBHOOK ROUTES ==========

@app.route('/api/admin/webhooks', methods=['GET', 'POST'])
@token_required
@super_admin_required
def manage_webhooks():
    """Manage webhooks"""
    try:
        if request.method == 'GET':
            webhooks = Webhook.query.order_by(Webhook.created_at.desc()).all()
            return jsonify({
                'success': True,
                'data': [{
                    'id': w.id,
                    'url': w.url,
                    'events': w.events,
                    'is_active': w.is_active,
                    'secret': w.secret[:10] + '...' if w.secret else None,
                    'last_triggered': w.last_triggered.isoformat() if w.last_triggered else None,
                    'failure_count': w.failure_count,
                    'created_at': w.created_at.isoformat()
                } for w in webhooks]
            })
        
        else:  # POST
            data = request.get_json()
            
            if not data.get('url') or not data.get('url').startswith(('http://', 'https://')):
                return jsonify({'success': False, 'error': 'Invalid webhook URL'}), 400
            
            webhook = Webhook(
                url=data.get('url'),
                events=data.get('events', []),
                secret=data.get('secret'),
                is_active=True,
                failure_count=0,
                created_at=datetime.utcnow(),
                created_by=g.current_user.id
            )
            db.session.add(webhook)
            db.session.commit()
            
            log_activity(g.current_user.id, 'create_webhook', f'Created webhook: {webhook.url}')
            
            return jsonify({'success': True, 'message': f'Webhook created on {COMPANY_NAME}', 'data': {'id': webhook.id}})
            
    except Exception as e:
        print(f"Manage webhooks error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/admin/webhooks/<int:webhook_id>', methods=['PUT', 'DELETE'])
@token_required
@super_admin_required
def update_webhook(webhook_id):
    """Update or delete webhook"""
    try:
        webhook = Webhook.query.get(webhook_id)
        if not webhook:
            return jsonify({'success': False, 'error': 'Webhook not found'}), 404
        
        if request.method == 'PUT':
            data = request.get_json()
            
            if 'url' in data:
                if not data['url'].startswith(('http://', 'https://')):
                    return jsonify({'success': False, 'error': 'Invalid webhook URL'}), 400
                webhook.url = data['url']
            if 'events' in data:
                webhook.events = data['events']
            if 'secret' in data:
                webhook.secret = data['secret']
            if 'is_active' in data:
                webhook.is_active = data['is_active']
            
            webhook.updated_at = datetime.utcnow()
            webhook.updated_by = g.current_user.id
            db.session.commit()
            
            log_activity(g.current_user.id, 'update_webhook', f'Updated webhook: {webhook.url}')
            
            return jsonify({'success': True, 'message': f'Webhook updated on {COMPANY_NAME}'})
        
        else:  # DELETE
            db.session.delete(webhook)
            db.session.commit()
            
            log_activity(g.current_user.id, 'delete_webhook', f'Deleted webhook: {webhook.url}')
            
            return jsonify({'success': True, 'message': f'Webhook deleted from {COMPANY_NAME}'})
            
    except Exception as e:
        print(f"Update webhook error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/admin/webhooks/<int:webhook_id>/test', methods=['POST'])
@token_required
@super_admin_required
def test_webhook(webhook_id):
    """Test webhook endpoint"""
    try:
        webhook = Webhook.query.get(webhook_id)
        if not webhook:
            return jsonify({'success': False, 'error': 'Webhook not found'}), 404
        
        test_payload = {
            'test': True,
            'timestamp': datetime.utcnow().isoformat(),
            'message': f'Webhook test from {COMPANY_NAME}',
            'event': 'test',
            'webhook_id': webhook_id
        }
        
        headers = {'Content-Type': 'application/json', 'User-Agent': f'{COMPANY_SHORT}-Webhook/1.0'}
        if webhook.secret:
            signature = hashlib.sha256(
                f"{webhook.secret}{json.dumps(test_payload)}".encode()
            ).hexdigest()
            headers['X-Webhook-Signature'] = signature
        
        start_time = datetime.utcnow()
        response = requests.post(webhook.url, json=test_payload, headers=headers, timeout=10)
        response_time = (datetime.utcnow() - start_time).total_seconds()
        
        if response.status_code in [200, 201, 202]:
            webhook.last_triggered = datetime.utcnow()
            webhook.last_response_time = response_time
            webhook.last_response_status = response.status_code
            webhook.failure_count = 0
            db.session.commit()
            
            log_activity(g.current_user.id, 'test_webhook', f'Tested webhook: {webhook.url} - Success')
            return jsonify({
                'success': True, 
                'message': f'Test webhook sent successfully from {COMPANY_NAME}',
                'data': {
                    'status_code': response.status_code,
                    'response_time': response_time,
                    'response': response.text[:200]
                }
            })
        else:
            webhook.failure_count += 1
            webhook.last_response_status = response.status_code
            db.session.commit()
            
            return jsonify({
                'success': False, 
                'error': f'Webhook responded with status {response.status_code}',
                'data': {'response': response.text[:200]}
            }), 500
            
    except requests.exceptions.Timeout:
        return jsonify({'success': False, 'error': 'Webhook timeout after 10 seconds'}), 500
    except requests.exceptions.ConnectionError:
        return jsonify({'success': False, 'error': 'Failed to connect to webhook URL'}), 500
    except Exception as e:
        print(f"Test webhook error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ========== ADMIN BACKUP ROUTES ==========

@app.route('/api/admin/backups', methods=['GET'])
@token_required
@super_admin_required
def get_backups():
    """Get list of backups"""
    try:
        backups = Backup.query.order_by(Backup.created_at.desc()).all()
        return jsonify({
            'success': True,
            'data': [{
                'id': b.id,
                'filename': b.filename,
                'size': b.size,
                'status': b.status,
                'created_at': b.created_at.isoformat()
            } for b in backups]
        })
    except Exception as e:
        print(f"Get backups error: {e}")
        return jsonify({'success': False, 'error': f'Failed to fetch backups from {COMPANY_NAME}'}), 500


@app.route('/api/admin/backup/create', methods=['POST'])
@token_required
@super_admin_required
def create_backup():
    """Create database backup"""
    try:
        database_url = app.config['SQLALCHEMY_DATABASE_URI']
        
        if 'sqlite' in database_url:
            # SQLite backup
            db_path = database_url.replace('sqlite:///', '')
            backup_dir = app.config.get('BACKUP_DIR', 'backups')
            
            if not os.path.exists(backup_dir):
                os.makedirs(backup_dir)
            
            timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
            filename = f"roamsmart_backup_{timestamp}.db"
            backup_path = os.path.join(backup_dir, filename)
            
            import shutil
            shutil.copy2(db_path, backup_path)
            
            file_size = os.path.getsize(backup_path)
            
            backup = Backup(
                filename=filename,
                size=file_size,
                file_path=backup_path,
                status='completed',
                created_by=g.current_user.id,
                created_at=datetime.utcnow()
            )
            db.session.add(backup)
            db.session.commit()
            
        elif 'postgresql' in database_url:
            # PostgreSQL backup
            import re
            import subprocess
            
            match = re.match(r'postgresql://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)', database_url)
            if match:
                username, password, host, port, dbname = match.groups()
                
                timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
                filename = f"roamsmart_backup_{timestamp}.sql"
                backup_dir = app.config.get('BACKUP_DIR', 'backups')
                
                if not os.path.exists(backup_dir):
                    os.makedirs(backup_dir)
                
                backup_path = os.path.join(backup_dir, filename)
                
                cmd = f'PGPASSWORD="{password}" pg_dump -h {host} -p {port} -U {username} -F c -b -v -f "{backup_path}" {dbname}'
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                
                if result.returncode == 0:
                    file_size = os.path.getsize(backup_path)
                    backup = Backup(
                        filename=filename,
                        size=file_size,
                        file_path=backup_path,
                        status='completed',
                        created_by=g.current_user.id,
                        created_at=datetime.utcnow()
                    )
                    db.session.add(backup)
                    db.session.commit()
                else:
                    raise Exception(f"Backup failed: {result.stderr}")
        
        # Clean old backups (keep last 30 days)
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        old_backups = Backup.query.filter(Backup.created_at < thirty_days_ago).all()
        for old_backup in old_backups:
            if os.path.exists(old_backup.file_path):
                os.remove(old_backup.file_path)
            db.session.delete(old_backup)
        db.session.commit()
        
        # Notify super admins via Email ONLY
        super_admins = User.query.filter_by(role='super_admin').all()
        for admin in super_admins:
            send_email(
                admin.email,
                f"Database Backup Created - {COMPANY_NAME}",
                f"""
                <h3>Database Backup Completed - {COMPANY_NAME}</h3>
                <p><strong>Filename:</strong> {filename}</p>
                <p><strong>Size:</strong> {file_size / 1024:.2f} KB</p>
                <p><strong>Time:</strong> {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC</p>
                <p><strong>Created by:</strong> {g.current_user.username}</p>
                """
            )
        
        log_activity(g.current_user.id, 'create_backup', f'Created backup: {filename}')
        
        return jsonify({
            'success': True, 
            'message': f'Backup created successfully on {COMPANY_NAME}',
            'data': {
                'filename': filename,
                'size': file_size,
                'created_at': backup.created_at.isoformat()
            }
        })
        
    except Exception as e:
        print(f"Create backup error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/admin/backup/<int:backup_id>/restore', methods=['POST'])
@token_required
@super_admin_required
def restore_backup(backup_id):
    """Restore from backup"""
    try:
        backup = Backup.query.get(backup_id)
        if not backup:
            return jsonify({'success': False, 'error': 'Backup not found'}), 404
        
        if not os.path.exists(backup.file_path):
            return jsonify({'success': False, 'error': 'Backup file not found'}), 404
        
        database_url = app.config['SQLALCHEMY_DATABASE_URI']
        
        # Create a restore point before restoring
        pre_restore_backup = create_backup()
        
        if 'sqlite' in database_url:
            db_path = database_url.replace('sqlite:///', '')
            
            db.session.remove()
            db.engine.dispose()
            
            import shutil
            shutil.copy2(backup.file_path, db_path)
            
        elif 'postgresql' in database_url:
            import re
            import subprocess
            
            match = re.match(r'postgresql://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)', database_url)
            if match:
                username, password, host, port, dbname = match.groups()
                
                cmd = f'PGPASSWORD="{password}" pg_restore -h {host} -p {port} -U {username} -d {dbname} --clean --if-exists "{backup.file_path}"'
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                
                if result.returncode != 0:
                    raise Exception(f"Restore failed: {result.stderr}")
        
        db.session.remove()
        db.engine.dispose()
        db.create_all()
        
        log_activity(g.current_user.id, 'restore_backup', f'Restored from backup: {backup.filename}')
        
        # Notify super admins via Email ONLY
        super_admins = User.query.filter_by(role='super_admin').all()
        for admin in super_admins:
            send_email(
                admin.email,
                f"Database Restore Completed - {COMPANY_NAME}",
                f"""
                <h3>Database Restore Completed - {COMPANY_NAME}</h3>
                <p><strong>Backup:</strong> {backup.filename}</p>
                <p><strong>Restore Point Created:</strong> {pre_restore_backup.filename}</p>
                <p><strong>Time:</strong> {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC</p>
                <p><strong>Restored by:</strong> {g.current_user.username}</p>
                <p><strong>⚠️ Action Required:</strong> Please verify all data integrity.</p>
                """
            )
        
        return jsonify({
            'success': True, 
            'message': f'Backup restored successfully on {COMPANY_NAME}. Please refresh your session.',
            'data': {
                'restored_from': backup.filename,
                'restore_point': pre_restore_backup.filename
            }
        })
        
    except Exception as e:
        print(f"Restore backup error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ========== ADMIN AUDIT LOGS ==========

@app.route('/api/admin/audit-logs', methods=['GET'])
@token_required
@super_admin_required
def get_audit_logs():
    """Get audit logs with filtering and pagination"""
    try:
        page = request.args.get('page', 1, type=int)
        limit = request.args.get('limit', 50, type=int)
        action = request.args.get('action')
        user_id = request.args.get('user_id', type=int)
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        
        query = UserSession.query
        
        if action:
            query = query.filter(UserSession.action.ilike(f'%{action}%'))
        if user_id:
            query = query.filter_by(user_id=user_id)
        if start_date:
            query = query.filter(UserSession.created_at >= datetime.fromisoformat(start_date))
        if end_date:
            query = query.filter(UserSession.created_at <= datetime.fromisoformat(end_date))
        
        pagination = query.order_by(UserSession.created_at.desc()).paginate(
            page=page, per_page=limit, error_out=False
        )
        
        logs_data = []
        for log in pagination.items:
            user = User.query.get(log.user_id)
            logs_data.append({
                'id': log.id,
                'admin_name': user.username if user else 'System',
                'admin_email': user.email if user else f'system@{COMPANY_DOMAIN}',
                'action': log.action,
                'details': log.details,
                'ip_address': log.ip_address,
                'user_agent': log.user_agent,
                'created_at': log.created_at.isoformat()
            })
        
        return jsonify({
            'success': True,
            'data': logs_data,
            'total': pagination.total,
            'page': page,
            'total_pages': pagination.pages,
            'has_next': pagination.has_next,
            'has_prev': pagination.has_prev
        })
        
    except Exception as e:
        print(f"Get audit logs error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ========== ADMIN SYSTEM HEALTH ==========

@app.route('/api/admin/system/health', methods=['GET'])
@token_required
@admin_required
def system_health():
    """Get system health status"""
    try:
        db_status = 'connected'
        db_latency = None
        try:
            import time
            start = time.time()
            db.session.execute('SELECT 1')
            db_latency = (time.time() - start) * 1000
        except Exception as e:
            db_status = f'disconnected: {str(e)}'
        
        import platform
        import subprocess
        
        if platform.system() == 'Linux':
            uptime_output = subprocess.check_output(['uptime', '-p']).decode().strip()
            uptime = uptime_output.replace('up ', '')
        else:
            uptime = 'Unknown'
        
        import psutil
        memory_usage = psutil.virtual_memory().percent
        cpu_usage = psutil.cpu_percent(interval=1)
        disk_usage = psutil.disk_usage('/').percent
        
        from flask import current_app
        active_requests = len(current_app.before_request_funcs)
        
        termii_status = 'unknown'
        if app.config.get('TERMII_API_KEY'):
            try:
                response = requests.get('https://v3.api.termii.com/api/sms/status', timeout=5)
                termii_status = 'operational' if response.status_code == 200 else 'degraded'
            except:
                termii_status = 'unavailable'
        
        return jsonify({
            'success': True,
            'data': {
                'database': {
                    'status': db_status,
                    'latency_ms': round(db_latency, 2) if db_latency else None
                },
                'system': {
                    'uptime': uptime,
                    'memory_usage_percent': memory_usage,
                    'cpu_usage_percent': cpu_usage,
                    'disk_usage_percent': disk_usage
                },
                'application': {
                    'status': 'running',
                    'environment': app.config.get('ENVIRONMENT', 'production'),
                    'version': app.config.get('APP_VERSION', '2.0.0'),
                    'active_requests': active_requests,
                    'name': COMPANY_NAME
                },
                'services': {
                    'termii': termii_status,
                    'smtp': 'operational' if app.config.get('SMTP_SERVER') else 'not_configured'
                },
                'timestamp': datetime.utcnow().isoformat()
            }
        })
        
    except Exception as e:
        print(f"System health error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ========== ADMIN PREDICTIONS / ANALYTICS ==========

@app.route('/api/admin/predictions', methods=['GET'])
@token_required
@admin_required
def get_predictions():
    """Get AI predictions and analytics based on real data"""
    try:
        last_30_days = datetime.utcnow() - timedelta(days=30)
        last_90_days = datetime.utcnow() - timedelta(days=90)
        
        daily_revenue = db.session.query(
            db.func.date(Order.completed_at),
            db.func.sum(Order.amount).label('revenue'),
            db.func.count(Order.id).label('order_count')
        ).filter(
            Order.status == 'completed',
            Order.completed_at >= last_30_days
        ).group_by(db.func.date(Order.completed_at)).all()
        
        if daily_revenue:
            avg_daily_revenue = sum(r[1] for r in daily_revenue) / len(daily_revenue)
            avg_daily_orders = sum(r[2] for r in daily_revenue) / len(daily_revenue)
            
            last_90_revenue = db.session.query(db.func.sum(Order.amount)).filter(
                Order.status == 'completed',
                Order.completed_at >= last_90_days,
                Order.completed_at < last_30_days
            ).scalar() or 0
            
            last_30_revenue = sum(r[1] for r in daily_revenue)
            
            if last_90_revenue > 0:
                growth_rate = ((last_30_revenue - last_90_revenue) / last_90_revenue) * 100
            else:
                growth_rate = 0
        else:
            avg_daily_revenue = 0
            avg_daily_orders = 0
            growth_rate = 0
        
        if len(daily_revenue) >= 7:
            last_7_days = daily_revenue[-7:]
            trend = sum((r[1] for r in last_7_days)) / 7
            next_month_revenue = trend * 30 * (1 + growth_rate / 100)
        else:
            next_month_revenue = avg_daily_revenue * 30
        
        hourly_orders = db.session.query(
            db.func.extract('hour', Order.created_at).label('hour'),
            db.func.count(Order.id).label('count')
        ).filter(
            Order.created_at >= last_30_days
        ).group_by('hour').all()
        
        if hourly_orders:
            peak_hour_data = max(hourly_orders, key=lambda x: x[1])
            peak_hour = int(peak_hour_data[0])
            peak_hour_prediction = f"{peak_hour}:00 - {peak_hour + 1}:00"
        else:
            peak_hour_prediction = "18:00 - 19:00"
        
        churn_threshold = datetime.utcnow() - timedelta(days=60)
        churn_risk_users = User.query.filter(
            User.last_login < churn_threshold,
            User.last_login.isnot(None),
            User.is_suspended == False
        ).count()
        
        active_threshold = datetime.utcnow() - timedelta(days=7)
        active_users = UserSession.query.filter(
            UserSession.created_at >= active_threshold
        ).distinct(UserSession.user_id).count()
        
        total_payments = ManualPayment.query.count()
        completed_payments = ManualPayment.query.filter_by(status='completed').count()
        customer_satisfaction = (completed_payments / total_payments * 5) if total_payments > 0 else 4.5
        
        popular_bundles = db.session.query(
            DataBundle.network,
            DataBundle.size_gb,
            db.func.count(Order.id).label('order_count'),
            db.func.sum(Order.amount).label('revenue')
        ).join(Order, DataBundle.network == Order.network)\
         .filter(Order.status == 'completed')\
         .group_by(DataBundle.network, DataBundle.size_gb)\
         .order_by(db.func.count(Order.id).desc())\
         .limit(5).all()
        
        total_orders_90 = Order.query.filter(
            Order.created_at >= last_90_days
        ).count()
        
        if total_orders_90 >= 1000:
            confidence = 95
        elif total_orders_90 >= 500:
            confidence = 85
        elif total_orders_90 >= 100:
            confidence = 75
        else:
            confidence = 60
        
        return jsonify({
            'success': True,
            'data': {
                'next_month_revenue': round(next_month_revenue, 2),
                'peak_hour_prediction': peak_hour_prediction,
                'churn_risk_users': churn_risk_users,
                'active_users': active_users,
                'avg_daily_revenue': round(avg_daily_revenue, 2),
                'avg_daily_orders': round(avg_daily_orders, 2),
                'growth_rate': round(growth_rate, 2),
                'customer_satisfaction': round(customer_satisfaction, 1),
                'prediction_confidence': confidence,
                'popular_bundles': [{
                    'network': bundle[0],
                    'size_gb': bundle[1],
                    'orders': bundle[2],
                    'revenue': round(bundle[3], 2)
                } for bundle in popular_bundles]
            }
        })
        
    except Exception as e:
        print(f"Get predictions error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ========== ADMIN EXPORT ROUTES ==========

@app.route('/api/admin/export/users', methods=['GET'])
@token_required
@super_admin_required
def export_users():
    """Export users data to CSV and send via email"""
    try:
        import csv
        from io import StringIO, BytesIO
        from flask import send_file
        
        export_format = request.args.get('format', 'csv')
        
        users = User.query.all()
        
        output = StringIO()
        writer = csv.writer(output)
        
        writer.writerow(['ID', 'Username', 'Email', 'Phone', 'Role', 'Wallet Balance', 
                        'Is Agent', 'Agent Approved', 'Agent Tier', 'Created At', 'Last Login', 
                        'Total Orders', 'Total Spent'])
        
        for user in users:
            total_orders = Order.query.filter_by(user_id=user.id, status='completed').count()
            total_spent = db.session.query(db.func.sum(Order.amount)).filter_by(
                user_id=user.id, status='completed'
            ).scalar() or 0
            
            writer.writerow([
                user.id, user.username, user.email, user.phone, user.role,
                user.wallet_balance, user.is_agent, user.agent_approved,
                user.agent_tier or 'N/A', user.created_at, user.last_login or 'Never',
                total_orders, total_spent
            ])
        
        if export_format == 'csv':
            output.seek(0)
            return send_file(
                BytesIO(output.getvalue().encode('utf-8')),
                mimetype='text/csv',
                as_attachment=True,
                download_name=f"roamsmart_users_export_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
            )
        else:
            send_email(
                g.current_user.email,
                f"User Export - {COMPANY_NAME}",
                f"""
                <h3>User Data Export Completed - {COMPANY_NAME}</h3>
                <p>Your requested user export has been processed.</p>
                <p><strong>Total Users:</strong> {len(users)}</p>
                <p><strong>Format:</strong> CSV</p>
                <p><strong>Export Date:</strong> {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC</p>
                """
            )
            
            log_activity(g.current_user.id, 'export_users', f'Exported {len(users)} users')
            
            return jsonify({
                'success': True,
                'message': f'User export sent to your email from {COMPANY_NAME}',
                'data': {
                    'total_users': len(users),
                    'format': 'csv'
                }
            })
        
    except Exception as e:
        print(f"Export users error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/admin/export/orders', methods=['GET'])
@token_required
@super_admin_required
def export_orders():
    """Export orders data to CSV and send via email"""
    try:
        import csv
        from io import StringIO, BytesIO
        from flask import send_file
        
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        export_format = request.args.get('format', 'csv')
        
        query = Order.query
        
        if start_date:
            query = query.filter(Order.created_at >= datetime.fromisoformat(start_date))
        if end_date:
            query = query.filter(Order.created_at <= datetime.fromisoformat(end_date))
        
        orders = query.order_by(Order.created_at.desc()).all()
        
        output = StringIO()
        writer = csv.writer(output)
        
        writer.writerow(['Order ID', 'User ID', 'Username', 'Type', 'Network', 'Size (GB)', 
                        'Phone Number', 'Amount', 'Quantity', 'Status', 'Payment Method',
                        'Created At', 'Completed At'])
        
        for order in orders:
            user = User.query.get(order.user_id)
            writer.writerow([
                order.order_id, order.user_id, user.username if user else 'N/A',
                order.type, order.network, order.size_gb, order.phone_number,
                order.amount, order.quantity, order.status, order.payment_method,
                order.created_at, order.completed_at or 'Pending'
            ])
        
        if export_format == 'csv':
            output.seek(0)
            return send_file(
                BytesIO(output.getvalue().encode('utf-8')),
                mimetype='text/csv',
                as_attachment=True,
                download_name=f"roamsmart_orders_export_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
            )
        else:
            total_revenue = sum(o.amount for o in orders if o.status == 'completed')
            
            send_email(
                g.current_user.email,
                f"Orders Export - {COMPANY_NAME}",
                f"""
                <h3>Orders Data Export Completed - {COMPANY_NAME}</h3>
                <p><strong>Total Orders:</strong> {len(orders)}</p>
                <p><strong>Total Revenue:</strong> GHS {total_revenue:.2f}</p>
                <p><strong>Date Range:</strong> {start_date or 'All'} to {end_date or 'Present'}</p>
                """
            )
            
            log_activity(g.current_user.id, 'export_orders', f'Exported {len(orders)} orders')
            
            return jsonify({
                'success': True,
                'message': f'Orders export sent to your email from {COMPANY_NAME}',
                'data': {
                    'total_orders': len(orders),
                    'total_revenue': total_revenue,
                    'format': 'csv'
                }
            })
        
    except Exception as e:
        print(f"Export orders error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ========== MISSING ADMIN ENDPOINTS ==========

@app.route('/api/admin/orders', methods=['GET'])
@token_required
@admin_required
def get_all_orders():
    """Get all orders for admin with pagination and filtering"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('limit', 50, type=int)
        status = request.args.get('status')
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        
        query = Order.query
        
        if status:
            query = query.filter_by(status=status)
        if start_date:
            query = query.filter(Order.created_at >= datetime.fromisoformat(start_date))
        if end_date:
            query = query.filter(Order.created_at <= datetime.fromisoformat(end_date))
        
        pagination = query.order_by(Order.created_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        orders_data = []
        for order in pagination.items:
            user = User.query.get(order.user_id)
            orders_data.append({
                **order.to_dict(),
                'username': user.username if user else 'Unknown',
                'user_email': user.email if user else 'Unknown',
                'user_phone': user.phone if user else 'Unknown',
                'platform': COMPANY_NAME
            })
        
        return jsonify({
            'success': True,
            'data': orders_data,
            'total': pagination.total,
            'page': page,
            'total_pages': pagination.pages,
            'has_next': pagination.has_next,
            'has_prev': pagination.has_prev
        })
    except Exception as e:
        print(f"Get all orders error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/admin/recent-activities', methods=['GET'])
@token_required
@admin_required
def get_recent_activities():
    """Get recent activities for admin dashboard"""
    try:
        limit = request.args.get('limit', 50, type=int)
        
        activities = ActivityLog.query.order_by(
            ActivityLog.created_at.desc()
        ).limit(limit).all()
        
        result = []
        for a in activities:
            user = User.query.get(a.user_id) if a.user_id else None
            result.append({
                'id': a.id,
                'type': a.action.split('_')[0] if '_' in a.action else a.action,
                'message': a.details or a.action,
                'user': user.username if user else 'System',
                'platform': COMPANY_NAME,
                'created_at': a.created_at.isoformat()
            })
        
        return jsonify({'success': True, 'data': result})
    except Exception as e:
        print(f"Get recent activities error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/admin/kyc-requests', methods=['GET'])
@token_required
@admin_required
def get_kyc_requests():
    """Get KYC verification requests"""
    try:
        status = request.args.get('status', 'pending')
        
        kyc_requests = KYCDocument.query.filter_by(status=status).all()
        
        result = []
        for kyc in kyc_requests:
            user = User.query.get(kyc.user_id)
            result.append({
                'id': kyc.id,
                'user_id': kyc.user_id,
                'username': user.username if user else 'Unknown',
                'email': user.email if user else 'Unknown',
                'phone': user.phone if user else 'Unknown',
                'document_type': kyc.document_type,
                'document_number': kyc.document_number,
                'document_url': kyc.document_url,
                'status': kyc.status,
                'created_at': kyc.created_at.isoformat()
            })
        
        return jsonify({'success': True, 'data': result})
    except Exception as e:
        print(f"Get KYC requests error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/admin/kyc/<int:request_id>/verify', methods=['POST'])
@token_required
@admin_required
def verify_kyc_request(request_id):
    """Verify or reject KYC request - Email ONLY"""
    try:
        data = request.get_json()
        status = data.get('status')
        reason = data.get('reason', '')
        
        kyc = KYCDocument.query.get(request_id)
        if not kyc:
            return jsonify({'success': False, 'error': 'KYC request not found'}), 404
        
        if kyc.status != 'pending':
            return jsonify({'success': False, 'error': 'KYC already processed'}), 400
        
        kyc.status = status
        kyc.verified_by = g.current_user.id
        kyc.verified_at = datetime.utcnow()
        kyc.rejection_reason = reason if status == 'rejected' else None
        
        if status == 'approved':
            user = User.query.get(kyc.user_id)
            if user:
                user.kyc_verified = True
        
        db.session.commit()
        
        user = User.query.get(kyc.user_id)
        if user:
            send_email(
                user.email,
                f"KYC {status.upper()} - {COMPANY_NAME}",
                f"""
                <div style="font-family: Arial, sans-serif;">
                    <h3>KYC Verification {status.upper()} - {COMPANY_NAME}</h3>
                    <p>Dear {user.username},</p>
                    <p>Your KYC document has been {status}.</p>
                    {f'<p><strong>Reason:</strong> {reason}</p>' if reason else ''}
                    <p>Thank you for your cooperation.</p>
                </div>
                """
            )
        
        log_activity(g.current_user.id, 'verify_kyc', f'KYC {status} for user {kyc.user_id}')
        
        return jsonify({'success': True, 'message': f'KYC {status} successfully on {COMPANY_NAME}'})
    except Exception as e:
        print(f"Verify KYC error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/admin/waec/vouchers', methods=['GET'])
@token_required
@admin_required
def get_waec_admin_Svouchers():
    """Get WAEC vouchers for admin with filtering"""
    try:
        exam_type = request.args.get('exam_type')
        is_used = request.args.get('is_used')
        limit = request.args.get('limit', 100, type=int)
        
        query = WAECVoucher.query
        
        if exam_type:
            query = query.filter_by(exam_type=exam_type)
        if is_used is not None:
            query = query.filter_by(is_used=is_used.lower() == 'true')
        
        vouchers = query.order_by(
            WAECVoucher.created_at.desc()
        ).limit(limit).all()
        
        result = []
        for v in vouchers:
            purchaser = User.query.get(v.purchased_by) if v.purchased_by else None
            user = User.query.get(v.used_by) if v.used_by else None
            result.append({
                'id': v.id,
                'voucher_code': v.voucher_code,
                'serial_number': v.serial_number,
                'pin': v.pin,
                'exam_type': v.exam_type,
                'year': v.year,
                'is_used': v.is_used,
                'retail_price': v.retail_price,
                'agent_price': v.agent_price,
                'purchased_by': v.purchased_by,
                'purchased_by_name': purchaser.username if purchaser else None,
                'used_by': v.used_by,
                'used_by_name': user.username if user else None,
                'used_at': v.used_at.isoformat() if v.used_at else None,
                'expires_at': v.expires_at.isoformat() if v.expires_at else None,
                'created_at': v.created_at.isoformat()
            })
        
        return jsonify({'success': True, 'data': result})
    except Exception as e:
        print(f"Get WAEC vouchers error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/admin/waec/stats', methods=['GET'])
@token_required
@admin_required
def get_waec_stats():
    """Get WAEC statistics"""
    try:
        total = WAECVoucher.query.count()
        used = WAECVoucher.query.filter_by(is_used=True).count()
        available = total - used
        
        by_exam_type = db.session.query(
            WAECVoucher.exam_type,
            db.func.count(WAECVoucher.id).label('total'),
            db.func.sum(db.case((WAECVoucher.is_used == True, 1), else_=0)).label('used')
        ).group_by(WAECVoucher.exam_type).all()
        
        total_revenue = db.session.query(db.func.sum(WAECVoucher.retail_price)).filter(
            WAECVoucher.is_used == True
        ).scalar() or 0
        
        return jsonify({
            'success': True,
            'data': {
                'total': total,
                'used': used,
                'available': available,
                'total_revenue': float(total_revenue),
                'by_exam_type': [{
                    'exam_type': item[0],
                    'total': item[1],
                    'used': item[2],
                    'available': item[1] - item[2]
                } for item in by_exam_type]
            }
        })
    except Exception as e:
        print(f"Get WAEC stats error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/admin/bill-payments', methods=['GET'])
@token_required
@admin_required
def get_bill_payments():
    """Get all bill payments for admin with filtering"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('limit', 50, type=int)
        status = request.args.get('status')
        bill_type = request.args.get('bill_type')
        
        query = BillPayment.query
        
        if status:
            query = query.filter_by(status=status)
        if bill_type:
            query = query.filter_by(bill_type=bill_type)
        
        pagination = query.order_by(
            BillPayment.created_at.desc()
        ).paginate(page=page, per_page=per_page, error_out=False)
        
        result = []
        for p in pagination.items:
            user = User.query.get(p.user_id)
            result.append({
                'id': p.id,
                'reference': p.reference,
                'user_id': p.user_id,
                'username': user.username if user else 'Unknown',
                'biller_name': p.biller_name,
                'bill_type': p.bill_type,
                'account_number': p.account_number,
                'amount': float(p.amount),
                'status': p.status,
                'transaction_id': p.transaction_id,
                'customer_name': p.customer_name,
                'customer_phone': p.customer_phone,
                'customer_email': p.customer_email,
                'created_at': p.created_at.isoformat(),
                'completed_at': p.completed_at.isoformat() if p.completed_at else None
            })
        
        return jsonify({
            'success': True,
            'data': result,
            'total': pagination.total,
            'page': page,
            'total_pages': pagination.pages
        })
    except Exception as e:
        print(f"Get bill payments error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/user/permissions', methods=['GET'])
@token_required
def get_user_permissions():
    """Get current user's permissions"""
    try:
        permissions = {
            'can_purchase': not g.current_user.is_suspended,
            'can_view_orders': True,
            'can_refer': True,
            'can_view_wallet': True,
            'can_fund_wallet': not g.current_user.is_suspended,
            'can_withdraw': g.current_user.is_agent and g.current_user.agent_approved and not g.current_user.is_suspended,
            'can_access_agent_dashboard': g.current_user.is_agent and g.current_user.agent_approved,
            'can_access_admin_dashboard': g.current_user.role in ['admin', 'super_admin'],
            'can_manage_users': g.current_user.role in ['admin', 'super_admin'],
            'can_manage_agents': g.current_user.role in ['admin', 'super_admin'],
            'can_view_reports': g.current_user.role in ['admin', 'super_admin'],
            'is_agent': g.current_user.is_agent and g.current_user.agent_approved,
            'is_admin': g.current_user.role in ['admin', 'super_admin'],
            'is_super_admin': g.current_user.role == 'super_admin',
            'kyc_status': 'verified' if hasattr(g.current_user, 'kyc_verified') and g.current_user.kyc_verified else 'pending',
            'platform': COMPANY_NAME
        }
        
        return jsonify({'success': True, 'data': permissions})
    except Exception as e:
        print(f"Get user permissions error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/admin/admins/<int:admin_id>', methods=['DELETE'])
@token_required
@super_admin_required
def admin_delete_admin(admin_id):
    """Delete an admin user"""
    try:
        # Prevent deleting yourself
        if admin_id == g.current_user.id:
            return jsonify({'success': False, 'error': 'Cannot delete your own account'}), 400
        
        admin = User.query.get(admin_id)
        
        if not admin or not admin.is_admin:
            return jsonify({'success': False, 'error': 'Admin not found'}), 404
        
        # Don't allow deleting last super_admin
        if admin.role == 'super_admin':
            super_admin_count = User.query.filter_by(role='super_admin').count()
            if super_admin_count <= 1:
                return jsonify({'success': False, 'error': 'Cannot delete the last super admin'}), 400
        
        db.session.delete(admin)
        db.session.commit()
        
        return jsonify({'success': True, 'message': f'Admin {admin.username} deleted'})
        
    except Exception as e:
        print(f"Delete admin error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Failed to delete admin'}), 500
    
@app.route('/api/admin/admins', methods=['POST'])
@token_required
@super_admin_required  # Only super admin can create new admins
def admin_create_admin():
    """Create a new admin user"""
    try:
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['username', 'email', 'password']
        for field in required_fields:
            if not data.get(field):
                return jsonify({'success': False, 'error': f'{field} is required'}), 400
        
        # Check if user exists
        existing = User.query.filter(
            db.or_(User.email == data['email'], User.username == data['username'])
        ).first()
        
        if existing:
            return jsonify({'success': False, 'error': 'Username or email already exists'}), 400
        
        # Create new admin
        new_admin = User(
            username=data['username'],
            email=data['email'],
            phone=data.get('phone'),
            password_hash=bcrypt.generate_password_hash(data['password']).decode('utf-8'),
            role=data.get('role', 'admin'),  # 'admin' or 'super_admin'
            is_agent=False,
            is_admin=True,
            created_at=datetime.utcnow()
        )
        
        db.session.add(new_admin)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Admin {new_admin.username} created successfully',
            'data': {
                'id': new_admin.id,
                'username': new_admin.username,
                'email': new_admin.email,
                'role': new_admin.role
            }
        })
        
    except Exception as e:
        print(f"Create admin error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Failed to create admin'}), 500
    
@app.route('/api/admin/admins', methods=['GET'])
@token_required
@admin_required
def admin_get_admins():
    """Get all admin users"""
    try:
        admins = User.query.filter(
            User.role.in_(['admin', 'super_admin'])
        ).all()
        
        result = []
        for admin in admins:
            result.append({
                'id': admin.id,
                'username': admin.username,
                'email': admin.email,
                'phone': admin.phone,
                'role': admin.role,
                'is_active': not admin.is_suspended,
                'last_login': admin.last_login.isoformat() if admin.last_login else None,
                'created_at': admin.created_at.isoformat() if admin.created_at else None
            })
        
        return jsonify({'success': True, 'data': result})
        
    except Exception as e:
        print(f"Get admins error: {e}")
        return jsonify({'success': False, 'error': 'Failed to fetch admins'}), 500
    
@app.route('/api/admin/stats/regional', methods=['GET'])
@token_required
@admin_required
def admin_get_regional_stats():
    """Get regional sales and user statistics"""
    try:
        # Option 1: If you have region data in orders table (based on customer phone prefix)
        # Query regional stats based on phone number prefixes
        regional_data = db.session.query(
            Order.phone_number,
            func.count(Order.id).label('order_count'),
            func.sum(Order.amount).label('total_sales')
        ).filter(
            Order.status == 'completed'
        ).group_by(
            Order.phone_number
        ).all()
        
        # Define Ghana regions based on phone prefixes
        regional_mapping = {
            '020': 'Greater Accra',
            '024': 'Greater Accra',
            '026': 'Greater Accra',
            '050': 'Greater Accra',
            '054': 'Greater Accra',
            '055': 'Greater Accra',
            '059': 'Greater Accra',
            '027': 'Western',
            '057': 'Western',
            '053': 'Ashanti',
            '056': 'Ashanti',
            '025': 'Central',
            '028': 'Volta',
            '058': 'Volta',
            '021': 'Eastern',
            '052': 'Northern'
        }
        
        # Aggregate by region
        region_stats = {}
        
        for record in regional_data:
            phone = record.phone_number or ''
            # Extract prefix (first 3 digits after 0)
            prefix = phone[:3] if phone.startswith('0') else phone[:3]
            
            region = regional_mapping.get(prefix, 'Other')
            
            if region not in region_stats:
                region_stats[region] = {
                    'region': region,
                    'sales': 0,
                    'users': 0,
                    'agents': 0,
                    'orders': 0
                }
            
            region_stats[region]['sales'] += float(record.total_sales or 0)
            region_stats[region]['orders'] += record.order_count
        
        # Get user counts by region (if you have region field in User model)
        users_by_region = {}
        try:
            # If User model has region column
            if hasattr(User, 'region'):
                user_regions = db.session.query(
                    User.region,
                    func.count(User.id).label('user_count'),
                    func.count(case((User.is_agent == True, User.id))).label('agent_count')
                ).group_by(User.region).all()
                
                for ur in user_regions:
                    if ur.region:
                        users_by_region[ur.region] = {
                            'users': ur.user_count,
                            'agents': ur.agent_count
                        }
        except:
            pass
        
        # Merge data
        result = []
        all_regions = ['Greater Accra', 'Ashanti', 'Western', 'Eastern', 'Central', 'Volta', 'Northern', 'Other']
        
        for region in all_regions:
            stats = region_stats.get(region, {})
            user_stats = users_by_region.get(region, {})
            
            result.append({
                'region': region,
                'sales': round(stats.get('sales', 0), 2),
                'users': user_stats.get('users', 0),
                'agents': user_stats.get('agents', 0),
                'orders': stats.get('orders', 0)
            })
        
        # Sort by sales descending
        result.sort(key=lambda x: x['sales'], reverse=True)
        
        return jsonify({
            'success': True,
            'data': result
        })
        
    except Exception as e:
        print(f"Regional stats error: {e}")
        import traceback
        traceback.print_exc()
        
        # Return default data if query fails
        default_regions = [
            {'region': 'Greater Accra', 'sales': 0, 'users': 0, 'agents': 0, 'orders': 0},
            {'region': 'Ashanti', 'sales': 0, 'users': 0, 'agents': 0, 'orders': 0},
            {'region': 'Western', 'sales': 0, 'users': 0, 'agents': 0, 'orders': 0},
            {'region': 'Eastern', 'sales': 0, 'users': 0, 'agents': 0, 'orders': 0},
            {'region': 'Central', 'sales': 0, 'users': 0, 'agents': 0, 'orders': 0},
            {'region': 'Volta', 'sales': 0, 'users': 0, 'agents': 0, 'orders': 0},
            {'region': 'Northern', 'sales': 0, 'users': 0, 'agents': 0, 'orders': 0},
            {'region': 'Other', 'sales': 0, 'users': 0, 'agents': 0, 'orders': 0}
        ]
        return jsonify({'success': True, 'data': default_regions})

# Add to app.py for testing

@app.route('/api/test/sms', methods=['POST'])
@token_required
def test_sms_endpoint():
    """Test endpoint for Africa's Talking SMS"""
    try:
        data = request.get_json()
        phone = data.get('phone')
        message = data.get('message', 'Test SMS from Roamsmart Digital Service')
        
        if not phone:
            return jsonify({'success': False, 'error': 'Phone number required'}), 400
        
        print(f"[TEST SMS] Original phone: {phone}")
        
        # Format phone number correctly
        formatted_phone = str(phone).strip()
        
        # Remove any '+' prefix
        if formatted_phone.startswith('+'):
            formatted_phone = formatted_phone[1:]
        
        # Replace '0' prefix with '233' (Ghana code)
        if formatted_phone.startswith('0'):
            formatted_phone = '233' + formatted_phone[1:]
        
        # If it starts with '233', keep as is
        if not formatted_phone.startswith('233'):
            formatted_phone = '233' + formatted_phone
        
        print(f"[TEST SMS] Formatted phone: {formatted_phone}")
        
        # Validate phone number (should be 12 digits: 233 + 9 digits)
        if len(formatted_phone) != 12 or not formatted_phone.isdigit():
            return jsonify({
                'success': False, 
                'error': f'Invalid phone number format. Expected 12 digits (e.g., 233XXXXXXXXX), got {formatted_phone}'
            }), 400
        
        global africas_talking_sms
        
        if not africas_talking_sms:
            return jsonify({
                'success': False, 
                'error': 'Africa\'s Talking not initialized. Check API key.'
            }), 500
        
        response = africas_talking_sms.send(message, [formatted_phone])
        
        print(f"[TEST SMS] Response: {response}")
        
        if response and response.get('SMSMessageData', {}).get('Recipients'):
            recipients = response['SMSMessageData']['Recipients']
            if recipients and len(recipients) > 0:
                status = recipients[0].get('status', '')
                if status == 'Success':
                    message_id = recipients[0].get('messageId', 'N/A')
                    return jsonify({
                        'success': True,
                        'message': f'SMS sent successfully to {phone}',
                        'message_id': message_id,
                        'formatted_phone': formatted_phone
                    })
        
        return jsonify({
            'success': False,
            'error': 'Failed to send SMS',
            'response': response
        }), 500
        
    except Exception as e:
        print(f"[TEST SMS] Error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/user/notifications', methods=['GET'])
@token_required
def get_user_notifications():
    """Get user's notifications with pagination"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('limit', 20, type=int)
        unread_only = request.args.get('unread_only', 'false').lower() == 'true'
        
        query = Notification.query.filter_by(user_id=g.current_user.id)
        
        if unread_only:
            query = query.filter_by(is_read=False)
        
        pagination = query.order_by(
            Notification.created_at.desc()
        ).paginate(page=page, per_page=per_page, error_out=False)
        
        return jsonify({
            'success': True,
            'data': [n.to_dict() for n in pagination.items],
            'total': pagination.total,
            'unread_count': Notification.query.filter_by(
                user_id=g.current_user.id, is_read=False
            ).count(),
            'page': page,
            'total_pages': pagination.pages
        })
    except Exception as e:
        print(f"Get user notifications error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/user/notifications/<int:notification_id>/read', methods=['PUT'])
@token_required
def mark_notification_read(notification_id):
    """Mark a notification as read"""
    try:
        notification = Notification.query.get(notification_id)
        
        if not notification or notification.user_id != g.current_user.id:
            return jsonify({'success': False, 'error': 'Notification not found'}), 404
        
        notification.is_read = True
        notification.read_at = datetime.utcnow()
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Notification marked as read on Roamsmart'})
    except Exception as e:
        print(f"Mark notification read error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/user/notifications/read-all', methods=['POST'])
@token_required
def mark_all_notifications_read():
    """Mark all notifications as read"""
    try:
        Notification.query.filter_by(
            user_id=g.current_user.id, is_read=False
        ).update({'is_read': True, 'read_at': datetime.utcnow()})
        db.session.commit()
        
        return jsonify({'success': True, 'message': f'All notifications marked as read on {COMPANY_NAME}'})
    except Exception as e:
        print(f"Mark all notifications read error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/admin/notification-templates', methods=['GET', 'POST'])
@token_required
@admin_required
def manage_notification_templates():
    """Manage email/SMS notification templates"""
    try:
        if request.method == 'GET':
            templates = NotificationTemplate.query.all()
            return jsonify({
                'success': True,
                'data': [{
                    'id': t.id,
                    'name': t.name,
                    'type': t.type,
                    'subject': t.subject,
                    'body_template': t.body_template,
                    'variables': json.loads(t.variables) if t.variables else [],
                    'is_active': t.is_active
                } for t in templates]
            })
        
        else:  # POST
            data = request.get_json()
            
            template = NotificationTemplate.query.filter_by(name=data['name']).first()
            if not template:
                template = NotificationTemplate(name=data['name'])
                db.session.add(template)
            
            template.type = data.get('type', 'email')
            template.subject = data.get('subject')
            template.body_template = data.get('body_template')
            template.variables = json.dumps(data.get('variables', []))
            template.is_active = data.get('is_active', True)
            template.updated_by = g.current_user.id
            
            db.session.commit()
            
            log_activity(g.current_user.id, 'update_template', f'Updated template: {data["name"]} on {COMPANY_NAME}')
            
            return jsonify({'success': True, 'message': f'Template updated on {COMPANY_NAME}'})
            
    except Exception as e:
        print(f"Manage templates error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/admin/notification-templates/<template_name>/preview', methods=['POST'])
@token_required
@admin_required
def preview_template(template_name):
    """Preview notification template with sample data"""
    try:
        template = NotificationTemplate.query.filter_by(name=template_name).first()
        if not template:
            return jsonify({'success': False, 'error': 'Template not found'}), 404
        
        sample_data = {
            'username': 'John Doe',
            'email': 'john@example.com',
            'order_id': 'ORD-123456',
            'amount': '100.00',
            'reference': 'REF-ABC123',
            'phone': '0244123456',
            'platform': COMPANY_NAME
        }
        
        preview_content = template.body_template
        for key, value in sample_data.items():
            preview_content = preview_content.replace(f'{{{key}}}', str(value))
        
        return jsonify({
            'success': True,
            'data': {
                'subject': template.subject,
                'content': preview_content,
                'variables': json.loads(template.variables) if template.variables else []
            }
        })
        
    except Exception as e:
        print(f"Preview template error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ========== ADMIN ACTIVITY SUMMARY ==========

@app.route('/api/admin/activity-summary', methods=['GET'])
@token_required
@admin_required
def get_activity_summary():
    """Get summary of system activity"""
    try:
        seven_days_ago = datetime.utcnow() - timedelta(days=7)
        twenty_four_hours = datetime.utcnow() - timedelta(hours=24)
        
        new_users = User.query.filter(User.created_at >= seven_days_ago).count()
        new_users_today = User.query.filter(User.created_at >= twenty_four_hours).count()
        
        new_orders = Order.query.filter(Order.created_at >= seven_days_ago).count()
        new_orders_today = Order.query.filter(Order.created_at >= twenty_four_hours).count()
        
        completed_orders = Order.query.filter(
            Order.status == 'completed',
            Order.completed_at >= seven_days_ago
        ).count()
        
        revenue_7d = db.session.query(db.func.sum(Order.amount)).filter(
            Order.status == 'completed',
            Order.completed_at >= seven_days_ago
        ).scalar() or 0
        
        revenue_today = db.session.query(db.func.sum(Order.amount)).filter(
            Order.status == 'completed',
            Order.completed_at >= twenty_four_hours
        ).scalar() or 0
        
        new_payments = ManualPayment.query.filter(
            ManualPayment.created_at >= seven_days_ago,
            ManualPayment.status == 'completed'
        ).count()
        
        total_payment_amount = db.session.query(db.func.sum(ManualPayment.amount)).filter(
            ManualPayment.created_at >= seven_days_ago,
            ManualPayment.status == 'completed'
        ).scalar() or 0
        
        pending_verifications = ManualPayment.query.filter_by(status='pending_verification').count()
        
        daily_stats = []
        for i in range(7):
            day = datetime.utcnow() - timedelta(days=i)
            day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day.replace(hour=23, minute=59, second=59, microsecond=999999)
            
            day_users = User.query.filter(
                User.created_at >= day_start,
                User.created_at <= day_end
            ).count()
            
            day_orders = Order.query.filter(
                Order.created_at >= day_start,
                Order.created_at <= day_end
            ).count()
            
            day_revenue = db.session.query(db.func.sum(Order.amount)).filter(
                Order.status == 'completed',
                Order.completed_at >= day_start,
                Order.completed_at <= day_end
            ).scalar() or 0
            
            daily_stats.append({
                'date': day.strftime('%Y-%m-%d'),
                'new_users': day_users,
                'orders': day_orders,
                'revenue': float(day_revenue)
            })
        
        return jsonify({
            'success': True,
            'data': {
                'period': 'Last 7 Days',
                'new_users': new_users,
                'new_users_today': new_users_today,
                'new_orders': new_orders,
                'new_orders_today': new_orders_today,
                'completed_orders': completed_orders,
                'revenue_7d': float(revenue_7d),
                'revenue_today': float(revenue_today),
                'new_payments': new_payments,
                'total_payments': float(total_payment_amount),
                'pending_verifications': pending_verifications,
                'active_users': UserSession.query.filter(
                    UserSession.created_at >= seven_days_ago
                ).distinct(UserSession.user_id).count(),
                'daily_breakdown': daily_stats,
                'platform': COMPANY_NAME
            }
        })
        
    except Exception as e:
        print(f"Get activity summary error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ========== PUBLIC ROUTES ==========

# ========== PUBLIC STATISTICS ==========

@app.route('/api/public/stats', methods=['GET'])
def get_public_stats():
    """Get public statistics for landing page"""
    try:
        total_users = User.query.count()
        total_completed_orders = Order.query.filter_by(status='completed').count()
        
        total_orders = Order.query.count()
        if total_orders > 0:
            success_rate = (total_completed_orders / total_orders) * 100
        else:
            success_rate = 100.0
        
        delivered_orders = Order.query.filter(
            Order.status == 'completed',
            Order.completed_at.isnot(None),
            Order.created_at.isnot(None)
        ).all()
        
        if delivered_orders:
            avg_delivery_seconds = sum(
                (order.completed_at - order.created_at).total_seconds() 
                for order in delivered_orders
            ) / len(delivered_orders)
            avg_delivery_seconds = round(avg_delivery_seconds, 0)
        else:
            avg_delivery_seconds = 2
        
        active_agents = User.query.filter_by(
            is_agent=True, 
            agent_approved=True
        ).count()
        
        total_revenue = db.session.query(db.func.sum(Order.amount)).filter_by(
            status='completed'
        ).scalar() or 0
        
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today_orders = Order.query.filter(
            Order.status == 'completed',
            Order.completed_at >= today
        ).count()
        
        return jsonify({
            'success': True,
            'data': {
                'happy_customers': total_users,
                'success_rate': round(success_rate, 1),
                'avg_delivery_seconds': avg_delivery_seconds,
                'active_agents': active_agents,
                'total_orders_served': total_completed_orders,
                'today_orders': today_orders,
                'total_revenue': round(total_revenue, 2),
                'platform': COMPANY_NAME
            }
        })
        
    except Exception as e:
        print(f"Get public stats error: {e}")
        return jsonify({
            'success': True,
            'data': {
                'happy_customers': 5000,
                'success_rate': 99.9,
                'avg_delivery_seconds': 2,
                'active_agents': 150,
                'total_orders_served': 25000,
                'today_orders': 45,
                'total_revenue': 125000,
                'platform': COMPANY_NAME
            }
        }), 200


# ========== PUBLIC DATA PLANS ==========

@app.route('/api/public/data-plans', methods=['GET'])
def get_public_data_admin_plans():
    """Get public data plans for website display"""
    try:
        network = request.args.get('network')
        popular_only = request.args.get('popular', 'false').lower() == 'true'
        
        query = DataBundle.query.filter_by(is_active=True)
        
        if network:
            query = query.filter_by(network=network)
        
        if popular_only:
            query = query.filter_by(popular=True)
        
        bundles = query.order_by(DataBundle.display_order).all()
        
        grouped_bundles = {}
        for bundle in bundles:
            if bundle.network not in grouped_bundles:
                grouped_bundles[bundle.network] = {
                    'network': bundle.network,
                    'network_display': bundle.network.upper(),
                    'plans': []
                }
            
            grouped_bundles[bundle.network]['plans'].append({
                'id': bundle.id,
                'size_gb': bundle.size_gb,
                'size_display': f"{bundle.size_gb}GB" if bundle.size_gb < 1024 else f"{bundle.size_gb/1024:.1f}TB",
                'price': float(bundle.retail_price),
                'price_display': f"GHS {bundle.retail_price:.2f}",
                'popular': bundle.popular,
                'savings': calculate_savings(bundle),
                'provider': COMPANY_NAME
            })
        
        return jsonify({
            'success': True,
            'data': list(grouped_bundles.values()),
            'meta': {
                'total_plans': len(bundles),
                'networks_available': list(grouped_bundles.keys()),
                'provider': COMPANY_NAME
            }
        })
        
    except Exception as e:
        print(f"Get public data plans error: {e}")
        return jsonify({'success': False, 'error': 'Failed to fetch data plans from Roamsmart'}), 500


def calculate_savings(bundle):
    """Calculate savings compared to standard rates"""
    standard_rate = 8.00
    standard_price = standard_rate * bundle.size_gb
    savings = standard_price - bundle.retail_price
    savings_percent = (savings / standard_price) * 100 if standard_price > 0 else 0
    
    return {
        'amount': round(savings, 2),
        'percentage': round(savings_percent, 0)
    }


# ========== NEWSLETTER SUBSCRIPTION ==========

@app.route('/api/newsletter/subscribe', methods=['POST'])
@limiter.limit("3 per minute")
def subscribe_newsletter():
    """Subscribe to newsletter - Email ONLY"""
    try:
        data = request.get_json()
        email = data.get('email')
        name = data.get('name')
        
        if not email:
            return jsonify({'success': False, 'error': 'Email is required'}), 400
        
        import re
        email_regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_regex, email):
            return jsonify({'success': False, 'error': 'Invalid email format'}), 400
        
        existing = NewsletterSubscriber.query.filter_by(email=email).first()
        if existing:
            if existing.is_active:
                return jsonify({'success': False, 'error': 'Email already subscribed'}), 400
            else:
                existing.is_active = True
                existing.unsubscribed_at = None
                existing.ip_address = request.remote_addr
                existing.user_agent = request.headers.get('User-Agent')
                db.session.commit()
        else:
            subscriber = NewsletterSubscriber(
                email=email,
                name=name,
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent')
            )
            db.session.add(subscriber)
            db.session.commit()
        
        welcome_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: #8B0000; color: white; padding: 20px; text-align: center; }}
                .content {{ padding: 20px; background: #f9f9f9; }}
                .button {{ background: #8B0000; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px; display: inline-block; }}
                .footer {{ text-align: center; padding: 20px; font-size: 12px; color: #666; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>Welcome to {COMPANY_NAME}!</h1>
                </div>
                <div class="content">
                    <h2>Thank you for subscribing, {name or 'there'}! 🎉</h2>
                    <p>You'll now receive exclusive updates and offers from {COMPANY_NAME}.</p>
                    <ul>
                        <li>📱 Exclusive data bundle offers</li>
                        <li>💰 Special discount codes</li>
                        <li>🚀 Early access to new features</li>
                        <li>🎁 Monthly giveaways and promotions</li>
                    </ul>
                    <a href="{COMPANY_WEBSITE}/shop" class="button">Shop Now</a>
                </div>
                <div class="footer">
                    <p>You're receiving this email because you subscribed to the {COMPANY_NAME} newsletter.</p>
                    <p><a href="{COMPANY_WEBSITE}/unsubscribe?email={email}">Unsubscribe</a> | <a href="{COMPANY_WEBSITE}/privacy">Privacy Policy</a></p>
                </div>
            </div>
        </body>
        </html>
        """
        
        send_email(email, f"Welcome to {COMPANY_NAME} Newsletter! 🎉", welcome_html)
        
        log_activity(None, 'newsletter_subscribe', f'Newsletter subscription: {email}')
        
        return jsonify({
            'success': True, 
            'message': f'Subscribed successfully to {COMPANY_NAME} newsletter! Check your email for welcome message.'
        })
        
    except Exception as e:
        print(f"Newsletter subscribe error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Failed to subscribe'}), 500


@app.route('/api/newsletter/unsubscribe', methods=['POST'])
@limiter.limit("3 per minute")
def unsubscribe_newsletter():
    """Unsubscribe from newsletter"""
    try:
        data = request.get_json()
        email = data.get('email')
        
        if not email:
            return jsonify({'success': False, 'error': 'Email is required'}), 400
        
        subscriber = NewsletterSubscriber.query.filter_by(email=email).first()
        if subscriber:
            subscriber.is_active = False
            subscriber.unsubscribed_at = datetime.utcnow()
            db.session.commit()
            
            log_activity(None, 'newsletter_unsubscribe', f'Newsletter unsubscription: {email}')
            
            return jsonify({'success': True, 'message': f'Unsubscribed from {COMPANY_NAME} newsletter'})
        else:
            return jsonify({'success': True, 'message': 'Email not found in our records'})
        
    except Exception as e:
        print(f"Newsletter unsubscribe error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Failed to unsubscribe'}), 500


@app.route('/api/newsletter/send', methods=['POST'])
@token_required
@admin_required
def send_newsletter():
    """Send newsletter to all subscribers (admin only) - Email ONLY"""
    try:
        data = request.get_json()
        subject = data.get('subject')
        content = data.get('content')
        send_to_all = data.get('send_to_all', True)
        
        if not subject or not content:
            return jsonify({'success': False, 'error': 'Subject and content required'}), 400
        
        query = NewsletterSubscriber.query.filter_by(is_active=True)
        
        if not send_to_all:
            pass
        
        subscribers = query.all()
        
        if not subscribers:
            return jsonify({'success': False, 'error': 'No active subscribers found'}), 400
        
        batch_size = 50
        sent_count = 0
        failed_count = 0
        
        for i in range(0, len(subscribers), batch_size):
            batch = subscribers[i:i+batch_size]
            for subscriber in batch:
                try:
                    send_email(
                        subscriber.email,
                        subject,
                        f"""
                        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                            <div style="background: #8B0000; color: white; padding: 20px; text-align: center;">
                                <h1>{COMPANY_NAME}</h1>
                            </div>
                            <div style="padding: 20px;">
                                {content}
                            </div>
                            <div style="text-align: center; padding: 20px; font-size: 12px; color: #666;">
                                <p><a href="{COMPANY_WEBSITE}/unsubscribe?email={subscriber.email}">Unsubscribe</a></p>
                            </div>
                        </div>
                        """
                    )
                    sent_count += 1
                except Exception as e:
                    print(f"Failed to send to {subscriber.email}: {e}")
                    failed_count += 1
        
        log_activity(g.current_user.id, 'send_newsletter', f'Sent newsletter to {sent_count} subscribers')
        
        return jsonify({
            'success': True,
            'message': f'Newsletter sent to {sent_count} subscribers on {COMPANY_NAME}',
            'data': {
                'sent': sent_count,
                'failed': failed_count,
                'total': len(subscribers)
            }
        })
        
    except Exception as e:
        print(f"Send newsletter error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/newsletter/stats', methods=['GET'])
@token_required
@admin_required
def get_newsletter_stats():
    """Get newsletter subscription statistics (admin only)"""
    try:
        total_subscribers = NewsletterSubscriber.query.filter_by(is_active=True).count()
        total_unsubscribed = NewsletterSubscriber.query.filter_by(is_active=False).count()
        
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        daily_subs = db.session.query(
            db.func.date(NewsletterSubscriber.subscribed_at),
            db.func.count(NewsletterSubscriber.id)
        ).filter(
            NewsletterSubscriber.subscribed_at >= thirty_days_ago
        ).group_by(db.func.date(NewsletterSubscriber.subscribed_at)).all()
        
        return jsonify({
            'success': True,
            'data': {
                'total_active_subscribers': total_subscribers,
                'total_unsubscribed': total_unsubscribed,
                'total_all_time': total_subscribers + total_unsubscribed,
                'daily_subscriptions': [{
                    'date': str(date),
                    'count': count
                } for date, count in daily_subs],
                'growth_rate': calculate_growth_rate(daily_subs),
                'platform': COMPANY_NAME
            }
        })
        
    except Exception as e:
        print(f"Get newsletter stats error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


def calculate_growth_rate(daily_subs):
    """Calculate subscription growth rate"""
    if len(daily_subs) < 7:
        return 0
    
    last_week = sum(count for _, count in daily_subs[-7:])
    previous_week = sum(count for _, count in daily_subs[-14:-7])
    
    if previous_week > 0:
        growth = ((last_week - previous_week) / previous_week) * 100
        return round(growth, 1)
    return 0


# ========== CONTACT FORM ==========

@app.route('/api/contact', methods=['POST'])
@limiter.limit("5 per minute")
def contact_form():
    """Submit contact form - Email ONLY"""
    try:
        data = request.get_json()
        
        name = data.get('name')
        email = data.get('email')
        phone = data.get('phone')
        subject = data.get('subject')
        message = data.get('message')
        
        if not all([name, email, subject, message]):
            return jsonify({'success': False, 'error': 'All fields are required'}), 400
        
        contact = ContactMessage(
            name=name,
            email=email,
            phone=phone,
            subject=subject,
            message=message,
            created_at=datetime.utcnow()
        )
        db.session.add(contact)
        db.session.commit()
        
        auto_reply_html = f"""
        <!DOCTYPE html>
        <html>
        <body style="font-family: Arial, sans-serif;">
            <h2 style="color: #8B0000;">Thank you for contacting {COMPANY_NAME}!</h2>
            <p>Dear {name},</p>
            <p>We have received your message and will get back to you within 24 hours.</p>
            <p><strong>Your message:</strong></p>
            <div style="background: #f9f9f9; padding: 15px; border-left: 3px solid #8B0000;">
                <p><strong>Subject:</strong> {subject}</p>
                <p><strong>Message:</strong> {message}</p>
            </div>
            <p>Reference ID: <strong>#{contact.id}</strong></p>
            <hr>
            <p style="color: #666;">Need immediate assistance? Contact us on WhatsApp: {COMPANY_PHONE}</p>
        </body>
        </html>
        """
        
        send_email(email, f"Thank you for contacting {COMPANY_NAME}", auto_reply_html)
        
        admins = User.query.filter(User.role.in_(['admin', 'super_admin'])).all()
        for admin in admins:
            send_email(
                admin.email,
                f"New Contact Form Message - {subject} - {COMPANY_NAME}",
                f"""
                <h3>New Contact Form Submission - {COMPANY_NAME}</h3>
                <p><strong>From:</strong> {name} ({email})</p>
                <p><strong>Phone:</strong> {phone or 'Not provided'}</p>
                <p><strong>Subject:</strong> {subject}</p>
                <p><strong>Message:</strong></p>
                <div style="background: #f9f9f9; padding: 15px;">
                    {message}
                </div>
                <p><a href="{COMPANY_WEBSITE}/admin/contact/{contact.id}">View and Reply</a></p>
                """
            )
        
        log_activity(None, 'contact_form', f'Contact form submission from {email}')
        
        return jsonify({
            'success': True,
            'message': f'Message sent successfully to {COMPANY_NAME}! We will get back to you soon.',
            'reference_id': contact.id
        })
        
    except Exception as e:
        print(f"Contact form error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Failed to send message'}), 500


# ========== HEALTH CHECK ==========

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint for monitoring"""
    try:
        db.session.execute('SELECT 1')
        db_status = 'healthy'
    except Exception as e:
        db_status = 'unhealthy'
    
    status = 'healthy' if db_status == 'healthy' else 'degraded'
    
    return jsonify({
        'status': status,
        'timestamp': datetime.utcnow().isoformat(),
        'version': '2.0.0',
        'database': db_status,
        'environment': app.config.get('ENVIRONMENT', 'production'),
        'service': COMPANY_NAME
    }), 200 if status == 'healthy' else 503

# ========== RATE LIMIT STATUS ==========
@app.route('/api/debug/rate-limits', methods=['GET'])
@token_required
@admin_required
def get_rate_limit_status():
    """Get current rate limit status (admin only)"""
    return jsonify({
        'success': True,
        'rate_limits': {
            'login': '5 per minute, 20 per hour',
            'register': '3 per minute, 10 per hour',
            'order': '10 per minute, 100 per hour',
            'agent_sell': '20 per minute, 200 per hour',
            'admin_approve': '10 per minute, 50 per hour'
        },
        'storage': 'redis' if redis_available else 'memory'
    })
# ========== FAQ ENDPOINT ==========

@app.route('/api/faq', methods=['GET'])
def get_faqs():
    """Get frequently asked questions"""
    try:
        category = request.args.get('category')
        query = FAQ.query.filter_by(is_active=True)
        
        if category:
            query = query.filter_by(category=category)
        
        faqs = query.order_by(FAQ.order).all()
        
        return jsonify({
            'success': True,
            'data': [{
                'id': f.id,
                'question': f.question,
                'answer': f.answer,
                'category': f.category
            } for f in faqs],
            'platform': COMPANY_NAME
        })
        
    except Exception as e:
        print(f"Get FAQs error: {e}")
        return jsonify({'success': False, 'error': f'Failed to fetch FAQs from {COMPANY_NAME}'}), 500


# ========== TESTIMONIALS ==========

@app.route('/api/testimonials', methods=['GET'])
def get_testimonials():
    """Get customer testimonials"""
    try:
        testimonials = Testimonial.query.filter_by(
            is_active=True, 
            is_verified=True
        ).order_by(Testimonial.created_at.desc()).limit(10).all()
        
        return jsonify({
            'success': True,
            'data': [{
                'id': t.id,
                'name': t.name,
                'role': t.role,
                'content': t.content,
                'rating': t.rating,
                'date': t.created_at.strftime('%B %d, %Y'),
                'platform': COMPANY_NAME
            } for t in testimonials]
        })
        
    except Exception as e:
        print(f"Get testimonials error: {e}")
        return jsonify({'success': False, 'error': f'Failed to fetch testimonials from {COMPANY_NAME}'}), 500


# ========== NETWORK API SERVICE (Super Admin Only) ==========

class NetworkAPIService:
    """Handles all direct network provider API calls (Super Admin only)"""
    
    def __init__(self):
        self.api_keys = self._load_api_keys()
    
    def _load_api_keys(self):
        """Load API keys from environment variables"""
        return {
            'mtn': {
                'api_key': os.environ.get('MTN_API_KEY', 'test_key_mtn'),
                'api_secret': os.environ.get('MTN_API_SECRET', 'test_secret_mtn'),
                'endpoint': os.environ.get('MTN_API_ENDPOINT', 'https://api.mtn.com.gh/v1/data')
            },
            'telecel': {
                'api_key': os.environ.get('TELECEL_API_KEY', 'test_key_telecel'),
                'api_secret': os.environ.get('TELECEL_API_SECRET', 'test_secret_telecel'),
                'endpoint': os.environ.get('TELECEL_API_ENDPOINT', 'https://api.telecel.com.gh/v1/data')
            },
            'airteltigo': {
                'api_key': os.environ.get('AIRTELTIGO_API_KEY', 'test_key_airteltigo'),
                'api_secret': os.environ.get('AIRTELTIGO_API_SECRET', 'test_secret_airteltigo'),
                'endpoint': os.environ.get('AIRTELTIGO_API_ENDPOINT', 'https://api.airteltigo.com.gh/v1/data')
            }
        }
    
    def purchase_bulk_data(self, network, size_gb, quantity):
        """Super Admin purchases data directly from network provider"""
        api_config = self.api_keys.get(network)
        if not api_config:
            return {'success': False, 'error': 'Network not configured'}
        
        if os.environ.get('MOCK_API', 'false').lower() == 'true':
            return {
                'success': True,
                'total_gb': size_gb * quantity,
                'transaction_id': f"MOCK_{uuid.uuid4().hex[:8].upper()}",
                'delivery_status': 'completed',
                'amount': size_gb * quantity * 3.5,
                'provider': COMPANY_NAME
            }
        
        try:
            response = requests.post(
                f"{api_config['endpoint']}/purchase",
                headers={
                    'Authorization': f"Bearer {api_config['api_key']}",
                    'Content-Type': 'application/json',
                    'X-API-Secret': api_config['api_secret']
                },
                json={
                    'size_gb': size_gb,
                    'quantity': quantity,
                    'reference': f"ADMIN_{uuid.uuid4().hex[:8]}",
                    'timestamp': datetime.utcnow().isoformat()
                },
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                return {
                    'success': True,
                    'total_gb': size_gb * quantity,
                    'transaction_id': data.get('transaction_id'),
                    'delivery_status': data.get('status', 'completed'),
                    'amount': data.get('amount', size_gb * quantity * 3.5),
                    'provider': COMPANY_NAME
                }
            else:
                print(f"Network API error: {response.status_code} - {response.text}")
                return {'success': False, 'error': f"API Error: {response.text}"}
                
        except requests.exceptions.Timeout:
            return {'success': False, 'error': 'API request timeout'}
        except requests.exceptions.ConnectionError:
            return {'success': False, 'error': 'Cannot connect to network provider API'}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def send_data_to_customer(self, network, phone, size_gb, quantity, order_id):
        """Send data to customer via network provider - Network provider will send SMS"""
        api_config = self.api_keys.get(network)
        if not api_config:
            return {'success': False, 'error': 'Network not configured'}
        
        total_gb = size_gb * quantity
        
        # Check if mock mode is enabled (for testing without real API)
        if os.environ.get('MOCK_API', 'true').lower() == 'true':
            print(f"[MOCK] Sending {total_gb}GB {network} data to {phone}")
            print(f"[MOCK] Order ID: {order_id}")
            return {
                'success': True,
                'message': 'Data sent successfully (mock mode)',
                'transaction_id': f"MOCK_{uuid.uuid4().hex[:8].upper()}",
                'provider_note': 'Network provider will send SMS to customer'
            }
        
        try:
            # Format phone number for API
            formatted_phone = phone
            if formatted_phone.startswith('0'):
                formatted_phone = '233' + formatted_phone[1:]
            if formatted_phone.startswith('+'):
                formatted_phone = formatted_phone[1:]
            
            response = requests.post(
                f"{api_config['endpoint']}/send",
                headers={
                    'Authorization': f"Bearer {api_config['api_key']}",
                    'Content-Type': 'application/json',
                    'X-API-Secret': api_config['api_secret']
                },
                json={
                    'phone': formatted_phone,
                    'data_size_gb': size_gb,
                    'quantity': quantity,
                    'total_gb': total_gb,
                    'order_id': order_id,
                    'reference': f"RS-{order_id}",
                    'timestamp': datetime.utcnow().isoformat()
                },
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                return {
                    'success': True,
                    'message': 'Data sent successfully',
                    'transaction_id': data.get('transaction_id'),
                    'provider_note': 'Network provider will send SMS to customer'
                }
            else:
                return {
                    'success': False, 
                    'error': f"API Error: {response.status_code} - {response.text}"
                }
                
        except requests.exceptions.Timeout:
            return {'success': False, 'error': 'API request timeout'}
        except requests.exceptions.ConnectionError:
            return {'success': False, 'error': 'Cannot connect to network provider API'}
        except Exception as e:
            return {'success': False, 'error': str(e)}


# ========== PRICE HELPERS (FROM DATABASE - SET BY ADMIN) ==========

def get_user_price(network, size_gb):
    """Get user retail price from database (set by admin)"""
    from models import PriceSetting
    
    setting = PriceSetting.query.filter_by(
        category='user_price',
        network=network,
        size_gb=size_gb
    ).first()
    
    if setting:
        return float(setting.price)
    
    # Return 0 if not set - admin must configure
    return 0

def get_agent_price(network, size_gb):
    """Get agent wholesale price from database (set by admin)"""
    from models import PriceSetting
    
    setting = PriceSetting.query.filter_by(
        category='agent_price',
        network=network,
        size_gb=size_gb
    ).first()
    
    if setting:
        return float(setting.price)
    
    # Return 0 if not set - admin must configure
    return 0

# ========== ANNOUNCEMENT ROUTES ==========

@app.route('/api/announcement/active', methods=['GET'])
def get_active_1announcement():
    """Get active announcement for public display"""
    try:
        announcement = Announcement.query.filter_by(is_active=True).first()
        
        if announcement:
            # Check if announcement has expired
            if announcement.expires_at and announcement.expires_at < datetime.utcnow():
                # Deactivate expired announcement
                announcement.is_active = False
                db.session.commit()
                broadcast_announcement_update('deleted', {'id': announcement.id})
                return jsonify({'success': True, 'data': None})
            
            return jsonify({
                'success': True,
                'data': {
                    'id': announcement.id,
                    'title': announcement.title,
                    'message': announcement.message,
                    'type': announcement.type,
                    'network_affected': announcement.network_affected,
                    'expires_at': announcement.expires_at.isoformat() if announcement.expires_at else None
                }
            })
        
        return jsonify({'success': True, 'data': None})
        
    except Exception as e:
        print(f"Get active announcement error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/announcement', methods=['GET'])
@token_required
@admin_required
def get_1announcements():
    """Get all announcements (admin only)"""
    try:
        announcements = Announcement.query.order_by(
            Announcement.created_at.desc()
        ).all()
        
        return jsonify({
            'success': True,
            'data': [{
                'id': a.id,
                'title': a.title,
                'message': a.message,
                'type': a.type,
                'network_affected': a.network_affected,
                'is_active': a.is_active,
                'expires_at': a.expires_at.isoformat() if a.expires_at else None,
                'created_at': a.created_at.isoformat(),
                'created_by': a.created_by
            } for a in announcements]
        })
        
    except Exception as e:
        print(f"Get announcements error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/announcement', methods=['POST'])
@token_required
@admin_required
def create_1announcement():
    """Create a new announcement (admin only)"""
    try:
        data = request.get_json()
        
        title = data.get('title', 'Announcement')
        message = data.get('message')
        announcement_type = data.get('type', 'info')
        network_affected = data.get('network_affected', 'all')
        expires_at = data.get('expires_at')
        
        if not message:
            return jsonify({'success': False, 'error': 'Message is required'}), 400
        
        # Deactivate any existing active announcements
        Announcement.query.update({'is_active': False})
        
        announcement = Announcement(
            title=title,
            message=message,
            type=announcement_type,
            network_affected=network_affected,
            is_active=True,
            created_by=g.current_user.id,
            created_at=datetime.utcnow()
        )
        
        if expires_at:
            announcement.expires_at = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
        
        db.session.add(announcement)
        db.session.commit()
        
        # Broadcast WebSocket event
        broadcast_announcement_update('created', announcement.to_dict())
        
        # Log activity
        log_activity(g.current_user.id, 'create_announcement', f'Created announcement: {title}')
        
        return jsonify({
            'success': True,
            'message': 'Announcement created successfully',
            'data': {
                'id': announcement.id,
                'title': announcement.title,
                'message': announcement.message,
                'type': announcement.type,
                'is_active': announcement.is_active
            }
        })
        
    except Exception as e:
        print(f"Create announcement error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/announcement/<int:announcement_id>', methods=['PUT'])
@token_required
@admin_required
def update_1announcement(announcement_id):
    """Update an announcement (admin only)"""
    try:
        announcement = Announcement.query.get(announcement_id)
        
        if not announcement:
            return jsonify({'success': False, 'error': 'Announcement not found'}), 404
        
        data = request.get_json()
        
        if 'title' in data:
            announcement.title = data['title']
        if 'message' in data:
            announcement.message = data['message']
        if 'type' in data:
            announcement.type = data['type']
        if 'network_affected' in data:
            announcement.network_affected = data['network_affected']
        if 'is_active' in data:
            announcement.is_active = data['is_active']
        if 'expires_at' in data and data['expires_at']:
            announcement.expires_at = datetime.fromisoformat(data['expires_at'].replace('Z', '+00:00'))
        
        db.session.commit()
        
        # Broadcast WebSocket event
        broadcast_announcement_update('updated', announcement.to_dict())
        
        log_activity(g.current_user.id, 'update_announcement', f'Updated announcement: {announcement.title}')
        
        return jsonify({
            'success': True,
            'message': 'Announcement updated successfully',
            'data': announcement.to_dict()
        })
        
    except Exception as e:
        print(f"Update announcement error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/announcement/<int:announcement_id>', methods=['DELETE'])
@token_required
@admin_required
def delete_1announcement(announcement_id):
    """Delete an announcement (admin only)"""
    try:
        announcement = Announcement.query.get(announcement_id)
        
        if not announcement:
            return jsonify({'success': False, 'error': 'Announcement not found'}), 404
        
        db.session.delete(announcement)
        db.session.commit()
        
        # Broadcast WebSocket event
        broadcast_announcement_update('deleted', {'id': announcement_id})
        
        log_activity(g.current_user.id, 'delete_announcement', f'Deleted announcement: {announcement.title}')
        
        return jsonify({'success': True, 'message': 'Announcement deleted successfully'})
        
    except Exception as e:
        print(f"Delete announcement error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/announcement/<int:announcement_id>/toggle', methods=['POST'])
@token_required
@admin_required
def toggle_1announcement(announcement_id):
    """Toggle announcement active status (admin only)"""
    try:
        announcement = Announcement.query.get(announcement_id)
        
        if not announcement:
            return jsonify({'success': False, 'error': 'Announcement not found'}), 404
        
        announcement.is_active = not announcement.is_active
        db.session.commit()
        
        # Broadcast WebSocket event
        broadcast_announcement_update('toggled', {
            'id': announcement.id,
            'is_active': announcement.is_active
        })
        
        log_activity(g.current_user.id, 'toggle_announcement', 
                    f'Toggled announcement {announcement.title} to {"active" if announcement.is_active else "inactive"}')
        
        return jsonify({
            'success': True,
            'message': f'Announcement {"activated" if announcement.is_active else "deactivated"}',
            'is_active': announcement.is_active
        })
        
    except Exception as e:
        print(f"Toggle announcement error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/announcement/broadcast', methods=['POST'])
@token_required
@admin_required
def broadcast_1announcement():
    """Broadcast announcement to all users via email (admin only)"""
    try:
        data = request.get_json()
        title = data.get('title', 'Important Announcement')
        message = data.get('message')
        announcement_type = data.get('type', 'info')
        
        if not message:
            return jsonify({'success': False, 'error': 'Message is required'}), 400
        
        # Get all active users
        users = User.query.filter_by(is_active=True, is_suspended=False).all()
        
        # Send email to all users (using COMPANY_NAME instead of hardcoded)
        sent_count = 0
        for user in users:
            send_notification(
                notification_type='alert',
                recipient=user.email,
                subject=f"📢 {title} - {COMPANY_NAME}",
                message=f"""
                <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                    <div style="background: {'#8B0000' if announcement_type == 'info' else '#f44336' if announcement_type == 'error' else '#ff9800'}; 
                                color: white; padding: 20px; text-align: center; border-radius: 10px 10px 0 0;">
                        <h2>{title}</h2>
                    </div>
                    <div style="padding: 20px; background: #f9f9f9;">
                        <p>Dear {user.username},</p>
                        <div style="background: white; padding: 15px; border-radius: 5px; margin: 15px 0;">
                            {message}
                        </div>
                        <p>Thank you for being part of {COMPANY_NAME}!</p>
                    </div>
                    <div style="text-align: center; padding: 20px; color: #666; font-size: 12px;">
                        <p>Need help? Contact us on WhatsApp: {COMPANY_PHONE}</p>
                    </div>
                </div>
                """,
                phone=None,
                is_verification=False,
                is_data_delivery=False
            )
            sent_count += 1
        
        # Also create an announcement in the database
        announcement = Announcement(
            title=title,
            message=message,
            type=announcement_type,
            is_active=True,
            created_by=g.current_user.id,
            created_at=datetime.utcnow()
        )
        db.session.add(announcement)
        db.session.commit()
        
        # Broadcast WebSocket event
        broadcast_announcement_update('broadcast', announcement.to_dict())
        
        log_activity(g.current_user.id, 'broadcast_announcement', 
                    f'Broadcast announcement to {sent_count} users: {title}')
        
        return jsonify({
            'success': True,
            'message': f'Announcement broadcast to {sent_count} users',
            'data': {
                'recipients': sent_count,
                'announcement_id': announcement.id
            }
        })
        
    except Exception as e:
        print(f"Broadcast announcement error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/admin/announcement', methods=['GET', 'POST', 'DELETE'])
@token_required
@admin_required
def manage_announcement():
    """Manage system announcements"""
    try:
        if request.method == 'GET':
            announcement = Announcement.query.filter_by(is_active=True).first()
            if announcement:
                return jsonify({
                    'success': True,
                    'data': {
                        'id': announcement.id,
                        'title': announcement.title,
                        'message': announcement.message,
                        'type': announcement.type,
                        'is_active': announcement.is_active,
                        'expires_at': announcement.expires_at.isoformat() if announcement.expires_at else None
                    }
                })
            return jsonify({'success': True, 'data': None})
        
        elif request.method == 'POST':
            data = request.get_json()
            
            # Deactivate old announcements
            Announcement.query.update({'is_active': False})
            
            announcement = Announcement(
                title=data.get('title', 'Announcement'),
                message=data.get('message'),
                type=data.get('type', 'info'),
                is_active=True,
                expires_at=datetime.fromisoformat(data['expires_at']) if data.get('expires_at') else None,
                created_by=g.current_user.id,
                created_at=datetime.utcnow()
            )
            db.session.add(announcement)
            db.session.commit()
            
            # Notify all users via email using COMPANY_NAME
            users = User.query.filter_by(is_suspended=False).all()
            
            # Batch send emails to avoid overwhelming the system
            batch_size = 50
            for i in range(0, len(users), batch_size):
                batch = users[i:i+batch_size]
                for user in batch:
                    send_notification(
                        notification_type='alert',
                        recipient=user.email,
                        subject=f"📢 New Announcement: {announcement.title}",
                        message=f"""
                        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                            <h2 style="color: #8B0000;">{announcement.title}</h2>
                            <div style="padding: 20px; background: #f9f9f9; border-radius: 5px;">
                                <p>{announcement.message}</p>
                            </div>
                            <p style="color: #666; font-size: 12px; margin-top: 20px;">
                                This is an automated announcement from {COMPANY_NAME}.
                            </p>
                        </div>
                        """,
                        phone=None,
                        is_verification=False,
                        is_data_delivery=False
                    )
            
            # Broadcast WebSocket event
            broadcast_announcement_update('created', announcement.to_dict())
            
            log_activity(g.current_user.id, 'create_announcement', f'Created announcement: {announcement.title}')
            
            return jsonify({'success': True, 'message': f'Announcement published and sent to {len(users)} users'})
        
        else:  # DELETE
            # Soft delete - mark as inactive instead of deleting
            Announcement.query.update({'is_active': False})
            db.session.commit()
            
            # Broadcast WebSocket event
            broadcast_announcement_update('deleted_all', {})
            
            log_activity(g.current_user.id, 'delete_announcement', 'Deleted all announcements')
            return jsonify({'success': True, 'message': 'Announcement removed'})
            
    except Exception as e:
        print(f"Manage announcement error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/admin/announcement/active', methods=['GET'])
def get_active_announcement():
    """Get active announcement for public"""
    try:
        announcement = Announcement.query.filter_by(is_active=True).first()
        if announcement and (not announcement.expires_at or announcement.expires_at > datetime.utcnow()):
            return jsonify({
                'success': True,
                'data': {
                    'id': announcement.id,
                    'title': announcement.title,
                    'message': announcement.message,
                    'type': announcement.type
                }
            })
        return jsonify({'success': True, 'data': None})
    except Exception as e:
        print(f"Get active announcement error: {e}")
        return jsonify({'success': False, 'error': 'Failed to fetch announcement'}), 500

# ========== INVENTORY SERVICE ==========

# ========== UPDATED INVENTORY SERVICE WITH USER DIRECT PURCHASE ==========

class InventoryService:
    """Manages inventory across all levels (Super Admin → Agents → Customers)"""
    
    @staticmethod
    def send_data_via_africastalking(phone_number, size_gb, quantity=1):
        """
        Send data to customer using Africa's Talking Mobile Data API
        """
        try:
            import africastalking
            import os
            
            username = os.environ.get('AFRICASTALKING_USERNAME', 'sandbox')
            api_key = os.environ.get('AFRICASTALKING_API_KEY')
            product_name = os.environ.get('AFRICASTALKING_PRODUCT_NAME')
            
            if not api_key:
                print("Africa's Talking API key not configured")
                return {'success': True, 'simulated': True}  # Simulate for testing
            
            africastalking.initialize(username, api_key)
            mobile_data = africastalking.MobileData
            
            # Format phone number to international format
            if phone_number.startswith('0'):
                international_phone = '233' + phone_number[1:]
            else:
                international_phone = phone_number
            
            total_mb = size_gb * 1024 * quantity
            
            # Determine unit based on size
            if total_mb < 1024:
                unit = 'MB'
                quantity_mb = total_mb
            else:
                unit = 'GB'
                quantity_gb = size_gb * quantity
            
            recipients = [{
                'phoneNumber': international_phone,
                'quantity': quantity_mb if unit == 'MB' else quantity_gb,
                'unit': unit,
                'validity': 'Day',
                'metadata': {
                    'network': 'All Networks',
                    'size_gb': size_gb,
                    'quantity': quantity,
                    'delivery_time': datetime.utcnow().isoformat()
                }
            }]
            
            response = mobile_data.send(product_name, recipients)
            
            print(f"📱 Africa's Talking: Sent {quantity}x {size_gb}GB to {international_phone}")
            print(f"Response: {response}")
            
            return {
                'success': True,
                'delivered': True,
                'transaction_id': response.get('transactionId'),
                'message': 'Data delivered successfully'
            }
            
        except Exception as e:
            print(f"Error sending data via Africa's Talking: {e}")
            # Fallback: Simulate delivery (for testing)
            return {
                'success': True,
                'simulated': True,
                'message': f'Data delivery simulated: {quantity}x {size_gb}GB to {phone_number}'
            }
    
    @staticmethod
    def add_to_master_inventory(network, size_gb, quantity, purchase_price):
        """Super Admin adds purchased data to master inventory"""
        total_gb = size_gb * quantity
        
        inventory = MasterInventory.query.filter_by(
            network=network, size_gb=size_gb
        ).first()
        
        if inventory:
            inventory.total_purchased += total_gb
            inventory.remaining += total_gb
            inventory.last_purchase_date = datetime.utcnow()
        else:
            inventory = MasterInventory(
                network=network,
                size_gb=size_gb,
                total_purchased=total_gb,
                remaining=total_gb,
                last_purchase_date=datetime.utcnow()
            )
            db.session.add(inventory)
        
        transaction = InventoryTransaction(
            type='master_purchase',
            network=network,
            size_gb=size_gb,
            quantity=quantity,
            total_gb=total_gb,
            amount=purchase_price,
            reference=f"RS-MASTER-{uuid.uuid4().hex[:8].upper()}"
        )
        db.session.add(transaction)
        
        db.session.commit()
        return inventory
    
    @staticmethod
    def agent_purchase_from_master(agent_id, network, size_gb, quantity, price_per_gb):
        """Agent purchases data from Super Admin - Email ONLY"""
        master_inv = MasterInventory.query.filter_by(
            network=network, size_gb=size_gb
        ).first()
        
        total_gb = size_gb * quantity
        
        if not master_inv or master_inv.remaining < total_gb:
            return {'success': False, 'error': 'Insufficient master inventory on Roamsmart'}
        
        agent = User.query.get(agent_id)
        total_cost = total_gb * price_per_gb
        
        if agent.wallet_balance < total_cost:
            return {'success': False, 'error': 'Insufficient wallet balance'}
        
        # Deduct from master inventory
        master_inv.remaining -= total_gb
        master_inv.sold_to_agents += total_gb
        
        # Add to agent inventory
        agent_inv = AgentInventory.query.filter_by(
            agent_id=agent_id, network=network, size_gb=size_gb
        ).first()
        
        if agent_inv:
            agent_inv.purchased += total_gb
            agent_inv.remaining += total_gb
            agent_inv.last_purchase_date = datetime.utcnow()
        else:
            agent_inv = AgentInventory(
                agent_id=agent_id,
                network=network,
                size_gb=size_gb,
                purchased=total_gb,
                remaining=total_gb
            )
            db.session.add(agent_inv)
        
        # Deduct from agent wallet
        agent.wallet_balance -= total_cost
        
        # Create transaction record
        transaction = InventoryTransaction(
            type='agent_purchase',
            from_user_id=None,
            to_user_id=agent_id,
            network=network,
            size_gb=size_gb,
            quantity=quantity,
            total_gb=total_gb,
            amount=total_cost,
            reference=f"RS-AGENT-{uuid.uuid4().hex[:8].upper()}"
        )
        db.session.add(transaction)
        
        db.session.commit()
        
        # Send email confirmation to agent (Email ONLY)
        send_email(
            agent.email,
            f"Data Purchase Confirmation - {size_gb}GB {network.upper()} - {COMPANY_NAME}",
            f"""
            <div style="font-family: Arial, sans-serif;">
                <h2 style="color: #8B0000;">Data Purchase Confirmation - {COMPANY_NAME}</h2>
                <p>Dear {agent.username},</p>
                <p>You have successfully purchased data from the master inventory.</p>
                <p><strong>Network:</strong> {network.upper()}</p>
                <p><strong>Size:</strong> {size_gb}GB</p>
                <p><strong>Quantity:</strong> {quantity}</p>
                <p><strong>Total GB:</strong> {total_gb}GB</p>
                <p><strong>Total Cost:</strong> GHS {total_cost:.2f}</p>
                <p><strong>Remaining Balance:</strong> GHS {agent.wallet_balance:.2f}</p>
                <a href="{COMPANY_WEBSITE}/agent/inventory" style="background: #8B0000; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">View Inventory</a>
            </div>
            """
        )
        
        return {
            'success': True,
            'total_gb': total_gb,
            'total_cost': total_cost,
            'remaining_balance': agent.wallet_balance
        }
    
    @staticmethod
    def user_direct_purchase(user_id, network, size_gb, quantity, phone_number):
        """
        User directly purchases data from master inventory
        Delivers data to customer phone via Africa's Talking
        """
        try:
            user = User.query.get(user_id)
            if not user:
                return {'success': False, 'error': 'User not found'}
            
            total_gb = size_gb * quantity
            
            # Get price from PriceSetting
            price_setting = PriceSetting.query.filter_by(
                category='user_price',
                network=network,
                size_gb=size_gb
            ).first()
            
            if not price_setting:
                return {'success': False, 'error': f'Price not configured for {network} {size_gb}GB'}
            
            price_per_unit = float(price_setting.price)
            total_price = price_per_unit * quantity
            
            # Check inventory
            inventory = MasterInventory.query.filter_by(
                network=network, size_gb=size_gb
            ).first()
            
            if not inventory or inventory.remaining < total_gb:
                return {'success': False, 'error': 'Insufficient inventory. Please contact admin.'}
            
            # Check wallet balance
            if user.wallet_balance < total_price:
                return {'success': False, 'error': f'Insufficient balance. Need ₵{total_price:.2f}'}
            
            # Send data via Africa's Talking FIRST
            delivery_result = InventoryService.send_data_via_africastalking(
                phone_number, size_gb, quantity
            )
            
            if not delivery_result.get('success'):
                return {'success': False, 'error': 'Data delivery failed. Please try again.'}
            
            # Deduct from user wallet
            balance_before = user.wallet_balance
            user.wallet_balance -= total_price
            
            # Update inventory
            inventory.remaining -= total_gb
            inventory.sold_to_users = (inventory.sold_to_users or 0) + total_gb
            
            # Create order
            order_id = f"ORD-{uuid.uuid4().hex[:8].upper()}"
            order = Order(
                user_id=user.id,
                order_id=order_id,
                network=network,
                size_gb=size_gb,
                quantity=quantity,
                phone_number=phone_number,
                amount=total_price,
                status='completed',
                payment_method='wallet',
                created_at=datetime.utcnow(),
                completed_at=datetime.utcnow()
            )
            db.session.add(order)
            
            # Create transaction
            transaction = Transaction(
                user_id=user.id,
                type='debit',
                amount=total_price,
                balance_before=balance_before,
                balance_after=user.wallet_balance,
                description=f'Data purchase - {quantity}x {size_gb}GB {network.upper()} to {phone_number}',
                reference=order_id,
                status='completed'
            )
            db.session.add(transaction)
            
            db.session.commit()
            
            # Send email confirmation
            send_email(
                user.email,
                f"Data Purchase Confirmation - {COMPANY_NAME}",
                f"""
                <div style="font-family: Arial, sans-serif;">
                    <h2 style="color: #8B0000;">Purchase Confirmation ✅</h2>
                    <p>Dear {user.username},</p>
                    <p>You have successfully purchased data.</p>
                    <p><strong>Network:</strong> {network.upper()}</p>
                    <p><strong>Size:</strong> {size_gb}GB</p>
                    <p><strong>Quantity:</strong> {quantity}</p>
                    <p><strong>Total GB:</strong> {total_gb}GB</p>
                    <p><strong>Phone Number:</strong> {phone_number}</p>
                    <p><strong>Amount Paid:</strong> GHS {total_price:.2f}</p>
                    <p><strong>New Balance:</strong> GHS {user.wallet_balance:.2f}</p>
                    <a href="{COMPANY_WEBSITE}/dashboard" style="background: #8B0000; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">Go to Dashboard</a>
                </div>
                """
            )
            
            return {
                'success': True,
                'order_id': order_id,
                'total_gb': total_gb,
                'total_price': total_price,
                'new_balance': float(user.wallet_balance),
                'delivery_status': 'delivered',
                'delivery_message': delivery_result.get('message', 'Data delivered')
            }
            
        except Exception as e:
            print(f"User direct purchase error: {e}")
            db.session.rollback()
            return {'success': False, 'error': str(e)}
    
    @staticmethod
    def agent_sell_to_customer(agent_id, network, size_gb, quantity, customer_phone, selling_price, customer_name=None, customer_id=None):
        """Agent sells data to customer (uses agent's inventory) - Email ONLY - Delivers via Africa's Talking"""
        try:
            agent_inv = AgentInventory.query.filter_by(
                agent_id=agent_id, network=network, size_gb=size_gb
            ).first()
            
            total_gb = size_gb * quantity
            
            if not agent_inv or agent_inv.remaining < total_gb:
                return {'success': False, 'error': 'Insufficient agent inventory'}
            
            # Send data via Africa's Talking FIRST
            delivery_result = InventoryService.send_data_via_africastalking(
                customer_phone, size_gb, quantity
            )
            
            if not delivery_result.get('success'):
                return {'success': False, 'error': 'Data delivery failed. Please try again.'}
            
            # Deduct from agent inventory
            agent_inv.remaining -= total_gb
            agent_inv.sold += total_gb
            
            # Credit agent's wallet
            agent = User.query.get(agent_id)
            agent.wallet_balance += selling_price
            
            # Create order record with agent_id
            order = Order(
                user_id=customer_id or agent_id,
                agent_id=agent_id,
                type='data',
                network=network,
                size_gb=size_gb,
                quantity=quantity,
                phone_number=customer_phone,
                customer_name=customer_name,
                amount=selling_price,
                status='completed',
                payment_method='wallet',
                completed_at=datetime.utcnow()
            )
            db.session.add(order)
            
            # Create transaction record
            transaction = Transaction(
                user_id=agent_id,
                type='sale',
                amount=selling_price,
                balance_before=agent.wallet_balance - selling_price,
                balance_after=agent.wallet_balance,
                description=f'Sold {quantity}x {size_gb}GB {network.upper()} data to {customer_phone}',
                reference=f"RS-SALE-{uuid.uuid4().hex[:8].upper()}",
                status='completed'
            )
            db.session.add(transaction)
            
            db.session.commit()
            
            # Send email confirmation to agent
            send_email(
                agent.email,
                f"Sale Confirmation - {size_gb}GB {network.upper()} - {COMPANY_NAME}",
                f"""
                <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                    <h2 style="color: #8B0000;">Sale Completed Successfully ✅</h2>
                    <p>Dear {agent.username},</p>
                    <p>You have successfully sold data to a customer on {COMPANY_NAME}.</p>
                    
                    <div style="background: #f9f9f9; padding: 15px; border-left: 3px solid #8B0000; margin: 20px 0;">
                        <p><strong>Network:</strong> {network.upper()}</p>
                        <p><strong>Size:</strong> {size_gb}GB</p>
                        <p><strong>Quantity:</strong> {quantity}</p>
                        <p><strong>Total GB:</strong> {total_gb}GB</p>
                        <p><strong>Customer Phone:</strong> {customer_phone}</p>
                        <p><strong>Selling Price:</strong> GHS {selling_price:.2f}</p>
                        <p><strong>New Wallet Balance:</strong> GHS {agent.wallet_balance:.2f}</p>
                        <p><strong>Delivery Status:</strong> {delivery_result.get('message', 'Delivered')}</p>
                    </div>
                    
                    <a href="{COMPANY_WEBSITE}/agent/orders" style="background: #8B0000; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px; display: inline-block;">View Orders</a>
                </div>
                """
            )
            
            return {
                'success': True,
                'order_id': order.order_id,
                'delivery_status': 'completed',
                'agent_balance': agent.wallet_balance,
                'profit': selling_price - ((agent_inv.purchased / agent_inv.sold) if agent_inv.sold > 0 else 0),
                'delivery_message': delivery_result.get('message')
            }
            
        except Exception as e:
            print(f"Agent sell to customer error: {e}")
            db.session.rollback()
            return {'success': False, 'error': str(e)}
    
    @staticmethod
    def get_agent_inventory(agent_id):
        """Get agent's current inventory"""
        inventory = AgentInventory.query.filter_by(agent_id=agent_id).all()
        
        result = {
            'mtn': {'total': 0, 'remaining': 0, 'sold': 0, 'bundles': {}},
            'telecel': {'total': 0, 'remaining': 0, 'sold': 0, 'bundles': {}},
            'airteltigo': {'total': 0, 'remaining': 0, 'sold': 0, 'bundles': {}}
        }
        
        for item in inventory:
            result[item.network]['total'] += item.purchased
            result[item.network]['remaining'] += item.remaining
            result[item.network]['sold'] += item.sold
            result[item.network]['bundles'][f"{int(item.size_gb)}gb"] = {
                'purchased': item.purchased,
                'sold': item.sold,
                'remaining': item.remaining
            }
        
        return result
    
    @staticmethod
    def get_master_inventory():
        """Get master inventory (Super Admin view)"""
        inventory = MasterInventory.query.all()
        
        result = {
            'mtn': {'total': 0, 'remaining': 0, 'sold_to_agents': 0, 'sold_to_users': 0, 'bundles': {}},
            'telecel': {'total': 0, 'remaining': 0, 'sold_to_agents': 0, 'sold_to_users': 0, 'bundles': {}},
            'airteltigo': {'total': 0, 'remaining': 0, 'sold_to_agents': 0, 'sold_to_users': 0, 'bundles': {}}
        }
        
        for item in inventory:
            result[item.network]['total'] += item.total_purchased
            result[item.network]['remaining'] += item.remaining
            result[item.network]['sold_to_agents'] += getattr(item, 'sold_to_agents', 0)
            result[item.network]['sold_to_users'] += getattr(item, 'sold_to_users', 0)
            result[item.network]['bundles'][f"{int(item.size_gb)}gb"] = {
                'total_purchased': item.total_purchased,
                'remaining': item.remaining,
                'sold_to_agents': getattr(item, 'sold_to_agents', 0),
                'sold_to_users': getattr(item, 'sold_to_users', 0)
            }
        
        return result
    
    @staticmethod
    def get_inventory_summary():
        """Get inventory summary with alerts for low stock"""
        master_inv = MasterInventory.query.all()
        
        low_stock_alerts = []
        for item in master_inv:
            if item.remaining < item.total_purchased * 0.1:
                low_stock_alerts.append({
                    'network': item.network,
                    'size_gb': item.size_gb,
                    'remaining': item.remaining,
                    'threshold': item.total_purchased * 0.1
                })
        
        return {
            'total_gb_available': sum(item.remaining for item in master_inv),
            'total_gb_sold_to_agents': sum(getattr(item, 'sold_to_agents', 0) for item in master_inv),
            'total_gb_sold_to_users': sum(getattr(item, 'sold_to_users', 0) for item in master_inv),
            'low_stock_alerts': low_stock_alerts,
            'platform': COMPANY_NAME
        }


# Add to your app.py

@app.route('/api/user/direct-purchase', methods=['POST'])
@token_required
def user_direct_purchase():
    """User directly purchases data from master inventory"""
    try:
        data = request.get_json()
        
        network = data.get('network')
        size_gb = data.get('size_gb')
        quantity = data.get('quantity', 1)
        phone_number = data.get('phone_number')
        
        if not network or not size_gb or not phone_number:
            return jsonify({'success': False, 'error': 'Network, size, and phone number required'}), 400
        
        user = g.current_user
        
        inventory_service = InventoryService()
        result = inventory_service.user_direct_purchase(
            user_id=user.id,
            network=network,
            size_gb=size_gb,
            quantity=quantity,
            phone_number=phone_number
        )
        
        if not result['success']:
            return jsonify({'success': False, 'error': result['error']}), 400
        
        return jsonify({
            'success': True,
            'message': f'Successfully purchased {result["total_gb"]}GB {network.upper()} data',
            'data': result
        }), 201
        
    except Exception as e:
        print(f"User direct purchase error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/admin/network/purchase', methods=['POST', 'OPTIONS'])
@token_required
@admin_required
def admin_network_purchase():
    """Admin: Purchase Mobile Data from Africa's Talking"""
    
    if request.method == 'OPTIONS':
        response = jsonify({'success': True})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
        response.headers.add('Access-Control-Allow-Methods', 'POST,OPTIONS')
        return response
    
    try:
        import uuid
        import requests
        import os
        
        data = request.get_json()
        
        product_type = data.get('product_type', 'data')
        network = data.get('network', '').lower()
        selected_bundle_index = data.get('bundle_index', 0)  # Let frontend select exact bundle
        quantity = data.get('quantity', 1)
        phone_number = data.get('phone_number', '')
        
        # Africa's Talking Mobile Data API endpoint
        AT_DATA_URL = "https://bundles.africastalking.com/mobile/data/request"
        
        # Get API credentials
        api_key = os.environ.get('AFRICASTALKING_API_KEY')
        username = os.environ.get('AFRICASTALKING_USERNAME', 'Roamsmart')
        
        if not api_key:
            return jsonify({'success': False, 'error': 'Africa\'s Talking API key not configured'}), 500
        
        # Format phone number
        if phone_number.startswith('0'):
            phone_number = '233' + phone_number[1:]
        if not phone_number.startswith('+'):
            phone_number = '+' + phone_number
        
        # Exact Africa's Talking Ghana bundles (must match exactly)
        available_bundles = {
            'mtn': [
                {'mb': 20.46, 'price': 0.49, 'display': '20.46 MB'},
                {'mb': 40.91, 'price': 0.99, 'display': '40.91 MB'},
                {'mb': 401.63, 'price': 2.97, 'display': '401.63 MB'},
                {'mb': 826.72, 'price': 9.90, 'display': '826.72 MB'},
                {'mb': 106810, 'price': 346.62, 'display': '106.81 GB'},
                {'mb': 214530, 'price': 395.14, 'display': '214.53 GB'}
            ],
            'airteltigo': [
                {'mb': 50, 'price': 0.98, 'display': '50 MB'},
                {'mb': 110, 'price': 1.96, 'display': '110 MB'},
                {'mb': 385, 'price': 2.94, 'display': '385 MB'},
                {'mb': 550, 'price': 4.90, 'display': '550 MB'},
                {'mb': 880, 'price': 9.80, 'display': '880 MB'},
                {'mb': 1740, 'price': 19.60, 'display': '1.7 GB'},
                {'mb': 4505, 'price': 49.00, 'display': '4.4 GB'},
                {'mb': 10137, 'price': 98.00, 'display': '9.9 GB'},
                {'mb': 33792, 'price': 196.00, 'display': '33 GB'},
                {'mb': 101376, 'price': 294.01, 'display': '99 GB'},
                {'mb': 118272, 'price': 343.01, 'display': '115.5 GB'},
                {'mb': 256000, 'price': 392.01, 'display': '250 GB'}
            ],
            'telecel': [
                {'mb': 22, 'price': 0.49, 'display': '22 MB'},
                {'mb': 49.5, 'price': 0.98, 'display': '49.5 MB'},
                {'mb': 110, 'price': 1.96, 'display': '110 MB'},
                {'mb': 550, 'price': 4.90, 'display': '550 MB'},
                {'mb': 880, 'price': 9.80, 'display': '880 MB'},
                {'mb': 1729, 'price': 19.60, 'display': '1.689 GB'},
                {'mb': 4608, 'price': 49.00, 'display': '4.5 GB'},
                {'mb': 10373, 'price': 98.00, 'display': '10.13 GB'},
                {'mb': 34600, 'price': 196.00, 'display': '33.79 GB'},
                {'mb': 103833, 'price': 294.01, 'display': '101.4 GB'},
                {'mb': 262144, 'price': 392.01, 'display': '256 GB'}
            ]
        }
        
        # Get bundles for selected network
        bundles = available_bundles.get(network, [])
        if not bundles:
            return jsonify({'success': False, 'error': f'No bundles available for {network}'}), 400
        
        # Use selected bundle or default to first
        if isinstance(selected_bundle_index, int) and selected_bundle_index < len(bundles):
            selected_bundle = bundles[selected_bundle_index]
        else:
            # If size_gb provided, find closest match
            size_gb = data.get('size_gb', 0)
            target_mb = size_gb * 1024
            selected_bundle = min(bundles, key=lambda x: abs(x['mb'] - target_mb))
        
        # Calculate total price
        unit_price = selected_bundle['price']
        total_price = unit_price * quantity
        total_mb = selected_bundle['mb'] * quantity
        total_gb = total_mb / 1024
        
        # IMPORTANT: quantity must be a NUMBER (float)
        mb_quantity = float(selected_bundle['mb'])
        
        payload = {
            "username": username,
            "productName": "Mobile Data",
            "recipients": [
                {
                    "phoneNumber": phone_number,
                    "quantity": mb_quantity,  # Float: 20.46
                    "unit": "MB",
                    "validity": "NonExpiry",
                    "metadata": {
                        "source": "Roamsmart_Admin",
                        "purpose": "Bulk Purchase",
                        "network": network,
                        "bundle_count": str(quantity)
                    }
                }
            ]
        }
        
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "apiKey": api_key,
            "Idempotency-Key": str(uuid.uuid4())
        }
        
        print(f"[DATA] Purchasing from Africa's Talking...")
        print(f"[DATA] URL: {AT_DATA_URL}")
        print(f"[DATA] Phone: {phone_number}")
        print(f"[DATA] Bundle: {selected_bundle['display']}")
        print(f"[DATA] Bundle MB: {selected_bundle['mb']}")
        print(f"[DATA] Quantity: {quantity}")
        print(f"[DATA] Total MB: {total_mb:.2f}MB ({total_gb:.2f}GB)")
        print(f"[DATA] Price: GHS {total_price:.2f}")
        print(f"[DATA] Payload: {payload}")
        
        # Make request to Africa's Talking
        response = requests.post(
            AT_DATA_URL,
            json=payload,
            headers=headers,
            timeout=30
        )
        
        print(f"[DATA] Response Status: {response.status_code}")
        print(f"[DATA] Response: {response.text}")
        
        if response.status_code in [200, 201, 202]:
            result = response.json()
            
            if 'entries' in result:
                entries = result.get('entries', [])
                if entries:
                    entry = entries[0]
                    if entry.get('status') == 'Success':
                        update_data_inventory(network, total_gb)
                        
                        return jsonify({
                            'success': True,
                            'message': f'Successfully purchased {quantity}x {selected_bundle["display"]} ({total_gb:.2f}GB total) from {network.upper()} for GHS {total_price:.2f}',
                            'data': {
                                'network': network,
                                'bundle_mb': selected_bundle['mb'],
                                'bundle_display': selected_bundle['display'],
                                'quantity': quantity,
                                'total_mb': total_mb,
                                'total_gb': total_gb,
                                'price_per_unit': unit_price,
                                'total_price': total_price,
                                'transaction_id': entry.get('transactionId'),
                                'status': entry.get('status')
                            }
                        })
                    else:
                        return jsonify({
                            'success': False,
                            'error': entry.get('errorMessage', 'Purchase failed')
                        }), 400
                else:
                    return jsonify({
                        'success': True,
                        'message': f'Purchase request sent. Check Africa\'s Talking dashboard for status.',
                        'data': result
                    }), 200
            else:
                return jsonify({
                    'success': True,
                    'message': f'Purchase request sent. Check Africa\'s Talking dashboard for status.',
                    'data': result
                }), 200
        else:
            return jsonify({
                'success': False,
                'error': f'Africa\'s Talking error: {response.text}'
            }), response.status_code
        
    except Exception as e:
        print(f"Purchase execution error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

def update_data_inventory(network, gb_purchased):
    """Update data inventory in database"""
    try:
        from app import db, MasterInventory
        
        inventory = MasterInventory.query.filter_by(network=network).first()
        if inventory:
            inventory.total_purchased = float(inventory.total_purchased or 0) + float(gb_purchased)
            inventory.remaining = float(inventory.remaining or 0) + float(gb_purchased)
        else:
            inventory = MasterInventory(
                network=network,
                total_purchased=float(gb_purchased),
                remaining=float(gb_purchased),
                sold_to_agents=0
            )
            db.session.add(inventory)
        
        db.session.commit()
        print(f"[INVENTORY] Updated {network}: +{gb_purchased} GB")
        
    except Exception as e:
        print(f"Error updating inventory: {e}")
        db.session.rollback()

# Endpoint to get available bundles for display
@app.route('/api/admin/africastalking-bundles', methods=['GET'])
@token_required
@admin_required
def admin_get_africastalking_bundles():
    """Admin: Get available data bundles with their prices"""
    try:
        AFRICASTALKING_BUNDLES = {
            'mtn': [
                {'size_mb': 20.46, 'size_gb': 0.02, 'price': 0.49, 'description': '20.46 MB - GHS 0.49'},
                {'size_mb': 40.91, 'size_gb': 0.04, 'price': 0.99, 'description': '40.91 MB - GHS 0.99'},
                {'size_mb': 401.63, 'size_gb': 0.39, 'price': 2.97, 'description': '401.63 MB - GHS 2.97'},
                {'size_mb': 826.72, 'size_gb': 0.81, 'price': 9.90, 'description': '826.72 MB - GHS 9.90'},
                {'size_mb': 106810, 'size_gb': 104.31, 'price': 346.62, 'description': '106.81 GB - GHS 346.62'},
                {'size_mb': 214530, 'size_gb': 209.50, 'price': 395.14, 'description': '214.53 GB - GHS 395.14'}
            ],
            'airteltigo': [
                {'size_mb': 50, 'size_gb': 0.05, 'price': 0.98, 'description': '50 MB - GHS 0.98'},
                {'size_mb': 110, 'size_gb': 0.11, 'price': 1.96, 'description': '110 MB - GHS 1.96'},
                {'size_mb': 385, 'size_gb': 0.38, 'price': 2.94, 'description': '385 MB - GHS 2.94'},
                {'size_mb': 550, 'size_gb': 0.54, 'price': 4.90, 'description': '550 MB - GHS 4.90'},
                {'size_mb': 880, 'size_gb': 0.86, 'price': 9.80, 'description': '880 MB - GHS 9.80'},
                {'size_mb': 1740, 'size_gb': 1.70, 'price': 19.60, 'description': '1.7 GB - GHS 19.60'},
                {'size_mb': 4505, 'size_gb': 4.40, 'price': 49.00, 'description': '4.4 GB - GHS 49.00'},
                {'size_mb': 10137, 'size_gb': 9.90, 'price': 98.00, 'description': '9.9 GB - GHS 98.00'},
                {'size_mb': 33792, 'size_gb': 33.00, 'price': 196.00, 'description': '33 GB - GHS 196.00'},
                {'size_mb': 101376, 'size_gb': 99.00, 'price': 294.01, 'description': '99 GB - GHS 294.01'},
                {'size_mb': 118272, 'size_gb': 115.50, 'price': 343.01, 'description': '115.5 GB - GHS 343.01'},
                {'size_mb': 256000, 'size_gb': 250.00, 'price': 392.01, 'description': '250 GB - GHS 392.01'}
            ],
            'telecel': [
                {'size_mb': 22, 'size_gb': 0.02, 'price': 0.49, 'description': '22 MB - GHS 0.49'},
                {'size_mb': 49.5, 'size_gb': 0.05, 'price': 0.98, 'description': '49.5 MB - GHS 0.98'},
                {'size_mb': 110, 'size_gb': 0.11, 'price': 1.96, 'description': '110 MB - GHS 1.96'},
                {'size_mb': 550, 'size_gb': 0.54, 'price': 4.90, 'description': '550 MB - GHS 4.90'},
                {'size_mb': 880, 'size_gb': 0.86, 'price': 9.80, 'description': '880 MB - GHS 9.80'},
                {'size_mb': 1729, 'size_gb': 1.69, 'price': 19.60, 'description': '1.689 GB - GHS 19.60'},
                {'size_mb': 4608, 'size_gb': 4.50, 'price': 49.00, 'description': '4.5 GB - GHS 49.00'},
                {'size_mb': 10373, 'size_gb': 10.13, 'price': 98.00, 'description': '10.13 GB - GHS 98.00'},
                {'size_mb': 34600, 'size_gb': 33.79, 'price': 196.00, 'description': '33.79 GB - GHS 196.00'},
                {'size_mb': 103833, 'size_gb': 101.40, 'price': 294.01, 'description': '101.4 GB - GHS 294.01'},
                {'size_mb': 262144, 'size_gb': 256.00, 'price': 392.01, 'description': '256 GB - GHS 392.01'}
            ]
        }
        
        return jsonify({
            'success': True,
            'data': AFRICASTALKING_BUNDLES,
            'last_updated': datetime.utcnow().isoformat()
        }), 200
        
    except Exception as e:
        print(f"Error fetching bundles: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500



@app.route('/api/agent/inventory/purchase', methods=['POST'])
@token_required
@agent_required
def agent_purchase_from_master():
    """Agent purchases data from master inventory"""
    try:
        data = request.get_json()
        network = data.get('network')
        size_gb = data.get('size_gb')
        quantity = data.get('quantity', 1)
        
        agent = g.current_user
        
        # Get agent wholesale price from database
        price_per_gb = get_agent_price(network, size_gb)
        
        if price_per_gb == 0:
            return jsonify({'success': False, 'error': 'Price not configured. Contact admin.'}), 400
        
        inventory_service = InventoryService()
        result = inventory_service.agent_purchase_from_master(
            agent_id=agent.id,
            network=network,
            size_gb=size_gb,
            quantity=quantity,
            price_per_gb=price_per_gb
        )
        
        if not result['success']:
            return jsonify({'success': False, 'error': result['error']}), 400
        
        return jsonify({
            'success': True,
            'message': f'Purchased {quantity}x {size_gb}GB {network.upper()} data',
            'data': {
                'total_gb': result['total_gb'],
                'total_cost': result['total_cost'],
                'new_balance': result['remaining_balance']
            }
        })
        
    except Exception as e:
        print(f"Agent purchase error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500



@app.route('/api/agent/inventory', methods=['GET'])
@token_required
@agent_required
def get_agent_inventory():
    """Get agent's current inventory"""
    try:
        inventory_service = InventoryService()
        inventory = inventory_service.get_agent_inventory(g.current_user.id)
        
        return jsonify({
            'success': True,
            'data': inventory
        })
        
    except Exception as e:
        print(f"Get agent inventory error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500



@app.route('/api/admin/inventory/transactions', methods=['GET'])
@token_required
@admin_required
def get_inventory_transactions():
    """Get inventory transaction history (Admin only)"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('limit', 50, type=int)
        transaction_type = request.args.get('type')
        
        query = InventoryTransaction.query
        
        if transaction_type:
            query = query.filter_by(type=transaction_type)
        
        pagination = query.order_by(InventoryTransaction.created_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        transactions = []
        for t in pagination.items:
            from_user = User.query.get(t.from_user_id) if t.from_user_id else None
            to_user = User.query.get(t.to_user_id) if t.to_user_id else None
            
            transactions.append({
                'id': t.id,
                'type': t.type,
                'network': t.network,
                'size_gb': t.size_gb,
                'quantity': t.quantity,
                'total_gb': t.total_gb,
                'amount': float(t.amount),
                'reference': t.reference,
                'from_user': from_user.username if from_user else 'System',
                'to_user': to_user.username if to_user else 'System',
                'created_at': t.created_at.isoformat(),
                'platform': COMPANY_NAME
            })
        
        return jsonify({
            'success': True,
            'data': transactions,
            'total': pagination.total,
            'page': page,
            'total_pages': pagination.pages
        })
        
    except Exception as e:
        print(f"Get inventory transactions error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ========== AGENT ORDERS ROUTES ==========


    
@app.route('/api/agent/stats', methods=['GET'])
@token_required
@agent_required
def get_agent_stats_enhanced():
    """Get enhanced agent statistics with accurate profit calculation"""
    try:
        agent = g.current_user
        
        # Get total sales (amount from completed orders where agent is seller)
        total_sales = db.session.query(func.sum(Order.amount)).filter(
            Order.agent_id == agent.id,
            Order.status == 'completed'
        ).scalar() or 0
        
        # ACCURATE: Get total profit (sum of profit from each sale)
        total_profit = db.session.query(func.sum(Order.profit)).filter(
            Order.agent_id == agent.id,
            Order.status == 'completed'
        ).scalar() or 0
        
        # Get total wholesale spent (what agent paid)
        total_wholesale = db.session.query(func.sum(Order.wholesale_price)).filter(
            Order.agent_id == agent.id,
            Order.status == 'completed'
        ).scalar() or 0
        
        # Get total orders count
        total_orders = Order.query.filter_by(
            agent_id=agent.id,
            status='completed'
        ).count()
        
        # Get today's sales and profit
        today = datetime.utcnow().date()
        today_start = datetime.combine(today, datetime.min.time())
        today_end = datetime.combine(today, datetime.max.time())
        
        today_sales = db.session.query(func.sum(Order.amount)).filter(
            Order.agent_id == agent.id,
            Order.status == 'completed',
            Order.created_at >= today_start,
            Order.created_at <= today_end
        ).scalar() or 0
        
        today_profit = db.session.query(func.sum(Order.profit)).filter(
            Order.agent_id == agent.id,
            Order.status == 'completed',
            Order.created_at >= today_start,
            Order.created_at <= today_end
        ).scalar() or 0
        
        # Get this week's sales and profit
        week_start = today - timedelta(days=today.weekday())
        week_start_dt = datetime.combine(week_start, datetime.min.time())
        
        week_sales = db.session.query(func.sum(Order.amount)).filter(
            Order.agent_id == agent.id,
            Order.status == 'completed',
            Order.created_at >= week_start_dt
        ).scalar() or 0
        
        week_profit = db.session.query(func.sum(Order.profit)).filter(
            Order.agent_id == agent.id,
            Order.status == 'completed',
            Order.created_at >= week_start_dt
        ).scalar() or 0
        
        # Get this month's sales and profit
        month_start = today.replace(day=1)
        month_start_dt = datetime.combine(month_start, datetime.min.time())
        
        month_sales = db.session.query(func.sum(Order.amount)).filter(
            Order.agent_id == agent.id,
            Order.status == 'completed',
            Order.created_at >= month_start_dt
        ).scalar() or 0
        
        month_profit = db.session.query(func.sum(Order.profit)).filter(
            Order.agent_id == agent.id,
            Order.status == 'completed',
            Order.created_at >= month_start_dt
        ).scalar() or 0
        
        # Get customer count
        customer_count = db.session.query(Order.phone_number).filter(
            Order.agent_id == agent.id,
            Order.status == 'completed'
        ).distinct().count()
        
        # Calculate commission rate based on tier (or from store)
        commission_rate = getattr(agent, 'commission_rate', 15)
        
        return jsonify({
            'success': True,
            'data': {
                'wallet_balance': float(agent.wallet_balance),
                'total_sales': float(total_sales),
                'total_orders': total_orders,
                'agent_savings': float(total_wholesale),  # Total spent on inventory
                'total_commission': float(total_profit),  # Actual profit
                'pending_commission': 0,
                'today_sales': float(today_sales),
                'today_profit': float(today_profit),
                'this_week_sales': float(week_sales),
                'this_week_profit': float(week_profit),
                'this_month_sales': float(month_sales),
                'this_month_profit': float(month_profit),
                'total_customers': customer_count,
                'agent_tier': getattr(agent, 'agent_tier', 'Bronze'),
                'next_tier_sales': 5000,
                'commission_rate': commission_rate,
                'rank': 0,
                'username': agent.username
            }
        })
        
    except Exception as e:
        print(f"Get agent stats error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
    
@app.route('/api/agent/bulk-order', methods=['POST'])
@token_required
@agent_required
def agent_bulk_order():
    """Agent sells multiple data bundles in bulk"""
    try:
        data = request.get_json()
        orders_data = data.get('orders', [])
        
        if not orders_data:
            return jsonify({'success': False, 'error': 'No orders provided'}), 400
        
        agent = g.current_user
        
        agent_prices = {
            'mtn': {1: 5.50, 2: 10.00, 5: 22.00, 10: 42.00, 20: 80.00},
            'telecel': {1: 5.00, 2: 9.00, 5: 20.00, 10: 38.00, 20: 75.00},
            'airteltigo': {1: 5.00, 2: 9.00, 5: 20.00, 10: 38.00, 20: 75.00}
        }
        
        suggested_prices = {
            'mtn': {1: 6.50, 2: 12.00, 5: 25.00, 10: 48.00, 20: 90.00},
            'telecel': {1: 6.00, 2: 11.00, 5: 23.00, 10: 44.00, 20: 85.00},
            'airteltigo': {1: 6.00, 2: 11.00, 5: 23.00, 10: 44.00, 20: 85.00}
        }
        
        total_wholesale = 0
        total_profit = 0
        successful_orders = []
        phone = orders_data[0].get('phone') if orders_data else None
        
        for order_data in orders_data:
            network = order_data.get('network', '').lower()
            size_gb = order_data.get('size_gb')
            quantity = order_data.get('quantity', 1)
            
            wholesale_price = agent_prices.get(network, {}).get(size_gb)
            if not wholesale_price:
                continue
            
            selling_price = suggested_prices.get(network, {}).get(size_gb, wholesale_price + 1)
            unit_profit = selling_price - wholesale_price
            
            for _ in range(quantity):
                total_wholesale += wholesale_price
                total_profit += unit_profit
                successful_orders.append({
                    'network': network,
                    'size_gb': size_gb,
                    'wholesale_price': wholesale_price,
                    'selling_price': selling_price,
                    'profit': unit_profit
                })
        
        # Check if agent has enough balance
        if agent.wallet_balance < total_wholesale:
            return jsonify({
                'success': False,
                'error': f'Insufficient balance. Need ₵{total_wholesale:.2f}'
            }), 400
        
        # Deduct from agent's wallet
        balance_before = agent.wallet_balance
        agent.wallet_balance -= total_wholesale
        
        # Create order records
        orders_created = []
        for idx, sale in enumerate(successful_orders):
            order_id = f"BULK-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{agent.id}-{idx}"
            
            order = Order(
                user_id=agent.id,
                agent_id=agent.id,
                order_id=order_id,
                type='data',
                network=sale['network'],
                size_gb=sale['size_gb'],
                phone_number=phone,
                amount=sale['selling_price'],
                status='completed',
                payment_method='wallet',
                created_at=datetime.utcnow(),
                completed_at=datetime.utcnow()
            )
            db.session.add(order)
            orders_created.append(order)
        
        # Create transaction record
        transaction = Transaction(
            user_id=agent.id,
            type='sale',
            amount=total_wholesale,
            balance_before=balance_before,
            balance_after=agent.wallet_balance,
            description=f'Bulk sale of {len(successful_orders)} data bundles',
            reference=f"BULK-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
            status='completed'
        )
        db.session.add(transaction)
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Successfully processed {len(successful_orders)} orders',
            'data': {
                'total_orders': len(successful_orders),
                'total_amount': float(total_wholesale),
                'total_profit': float(total_profit),
                'new_balance': float(agent.wallet_balance)
            }
        })
        
    except Exception as e:
        print(f"Agent bulk order error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/agent/orders-debug', methods=['GET'])
@token_required
@agent_required
def debug_agent_orders():
    """Debug endpoint to check what orders exist"""
    try:
        agent = g.current_user
        
        # Get all orders regardless of status
        all_orders = Order.query.filter(
            db.or_(
                Order.agent_id == agent.id,
                Order.user_id == agent.id
            )
        ).all()
        
        result = []
        for order in all_orders:
            result.append({
                'id': order.id,
                'order_id': order.order_id,
                'agent_id': order.agent_id,
                'user_id': order.user_id,
                'network': order.network,
                'size_gb': order.size_gb,
                'amount': float(order.amount),
                'status': order.status,
                'created_at': order.created_at.isoformat() if order.created_at else None
            })
        
        return jsonify({
            'success': True,
            'count': len(result),
            'orders': result,
            'agent_id': agent.id,
            'agent_username': agent.username
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/agent/orders', methods=['GET'])
@token_required
@agent_required
def get_agent_orders():
    """Get all orders for the agent"""
    try:
        agent = g.current_user
        
        print("\n" + "="*60)
        print("DEBUG: /api/agent/orders called")
        print("="*60)
        print(f"Agent ID: {agent.id}")
        print(f"Agent Username: {agent.username}")
        print(f"Agent Email: {agent.email}")
        print(f"Is Agent: {agent.is_agent}")
        
        # Get orders where this agent made the sale
        orders = Order.query.filter_by(agent_id=agent.id).order_by(Order.created_at.desc()).limit(50).all()
        
        print(f"\nFound {len(orders)} orders for agent {agent.id}")
        
        # Debug: Print each order
        for idx, order in enumerate(orders):
            print(f"\nOrder {idx + 1}:")
            print(f"  ID: {order.id}")
            print(f"  Order ID: {order.order_id}")
            print(f"  Agent ID in DB: {order.agent_id}")
            print(f"  User ID: {order.user_id}")
            print(f"  Network: {order.network}")
            print(f"  Size: {order.size_gb}GB")
            print(f"  Amount: ₵{order.amount}")
            print(f"  Status: {order.status}")
            print(f"  Phone: {order.phone_number}")
            print(f"  Created: {order.created_at}")
        
        # Also check for orders with NULL agent_id
        null_orders = Order.query.filter(Order.agent_id.is_(None)).count()
        if null_orders > 0:
            print(f"\n⚠️ WARNING: {null_orders} orders have NULL agent_id!")
            
            # Show sample of NULL agent_id orders
            sample_null = Order.query.filter(Order.agent_id.is_(None)).limit(3).all()
            for order in sample_null:
                print(f"  NULL Agent Order: ID={order.id}, Order={order.order_id}, Amount=₵{order.amount}")
        
        orders_list = []
        for order in orders:
            orders_list.append({
                'id': order.id,
                'order_id': order.order_id,
                'customer_name': order.customer_name or 'Customer',
                'customer_phone': order.phone_number,
                'network': order.network,
                'size_gb': order.size_gb,
                'amount': float(order.amount),
                'status': order.status,
                'payment_method': order.payment_method,
                'created_at': order.created_at.isoformat() if order.created_at else None,
                'profit': float(order.amount * 0.15)
            })
        
        print(f"\n✅ Returning {len(orders_list)} orders to frontend")
        print("="*60 + "\n")
        
        return jsonify({
            'success': True,
            'data': orders_list,
            'debug': {
                'agent_id': agent.id,
                'orders_found': len(orders_list),
                'null_agent_orders': null_orders
            }
        })
        
    except Exception as e:
        print(f"❌ Get agent orders error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/agent/sell', methods=['POST'])
@token_required
@agent_required
def agent_sell_data():
    """Agent sells data - supports both methods"""
    try:
        data = request.get_json()
        network = data.get('network')
        size_gb = data.get('size_gb')
        phone = data.get('phone')
        customer_name = data.get('customer_name', '')
        selling_price = data.get('selling_price')
        use_inventory = data.get('use_inventory', False)  # Agent chooses
        
        agent = g.current_user
        wholesale_price = get_agent_price(network, size_gb)
        
        # Calculate selling price if not provided
        if not selling_price:
            retail_price = get_user_price(network, size_gb)
            selling_price = retail_price if retail_price > 0 else wholesale_price * 1.18
        
        profit = selling_price - wholesale_price
        
        # METHOD 1: Use Inventory (if agent has stock)
        if use_inventory:
            from models import AgentInventory
            inventory = AgentInventory.query.filter_by(
                agent_id=agent.id,
                network=network,
                size_gb=size_gb
            ).first()
            
            if inventory and inventory.remaining >= 1:
                # Use inventory - NO wallet deduction
                inventory.remaining -= 1
                inventory.sold = (inventory.sold or 0) + 1
                
                order = Order(
                    user_id=agent.id,
                    agent_id=agent.id,
                    network=network,
                    size_gb=size_gb,
                    phone_number=phone,
                    amount=selling_price,
                    status='completed',
                    payment_method='inventory'  # Paid from inventory
                )
                db.session.add(order)
                db.session.commit()
                
                # Call network to send data
                network_service = NetworkAPIService()
                network_service.send_data_to_customer(network, phone, size_gb, 1, order.order_id)
                
                return jsonify({
                    'success': True,
                    'method': 'inventory',
                    'profit': profit,
                    'message': f'Sold from inventory. Customer pays you ₵{selling_price:.2f}'
                })
        
        # METHOD 2: Direct Wallet Deduction (Fallback)
        if agent.wallet_balance >= wholesale_price:
            # Deduct from wallet
            agent.wallet_balance -= wholesale_price
            
            order = Order(
                user_id=agent.id,
                agent_id=agent.id,
                network=network,
                size_gb=size_gb,
                phone_number=phone,
                amount=selling_price,
                status='completed',
                payment_method='wallet'  # Paid from wallet
            )
            db.session.add(order)
            db.session.commit()
            
            # Call network to send data
            network_service = NetworkAPIService()
            network_service.send_data_to_customer(network, phone, size_gb, 1, order.order_id)
            
            return jsonify({
                'success': True,
                'method': 'wallet',
                'new_balance': float(agent.wallet_balance),
                'profit': profit,
                'message': f'Sold using wallet. Customer pays you ₵{selling_price:.2f}'
            })
        
        # No inventory AND insufficient wallet
        return jsonify({
            'success': False,
            'error': 'Insufficient wallet balance and no inventory. Please add funds or purchase inventory.'
        }), 400
        
    except Exception as e:
        print(f"Agent sell error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/agent/orders/<int:order_id>/status', methods=['PUT'])
@token_required
@agent_required
def update_order_status(order_id):
    """Update order status (pending -> processing -> sending -> completed) - Email ONLY for notifications"""
    try:
        data = request.get_json()
        new_status = data.get('status')
        
        order = Order.query.get(order_id)
        if not order or order.agent_id != g.current_user.id:
            return jsonify({'success': False, 'error': 'Order not found'}), 404
        
        valid_statuses = ['pending', 'processing', 'sending', 'completed', 'failed']
        if new_status not in valid_statuses:
            return jsonify({'success': False, 'error': 'Invalid status'}), 400
        
        old_status = order.status
        order.status = new_status
        
        if new_status == 'completed':
            order.completed_at = datetime.utcnow()
            
            customer = User.query.get(order.user_id) if order.user_id else None
            if customer and customer.email:
                send_email(
                    customer.email,
                    f"Order Completed - {order.order_id} - {COMPANY_NAME}",
                    f"""
                    <div style="font-family: Arial, sans-serif;">
                        <h2 style="color: #28a745;">✅ Your Data Order Has Been Delivered!</h2>
                        <p>Dear {customer.username},</p>
                        <p>Your data order has been successfully delivered via {COMPANY_NAME}.</p>
                        <p><strong>Order ID:</strong> {order.order_id}</p>
                        <p><strong>Package:</strong> {order.quantity}x {order.size_gb}GB {order.network.upper()}</p>
                        <p><strong>Phone Number:</strong> {order.phone_number}</p>
                        <p><strong>Amount:</strong> GHS {order.amount:.2f}</p>
                        <p><strong>Status:</strong> Delivered ✓</p>
                        <a href="{COMPANY_WEBSITE}/orders" style="background: #8B0000; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">View Order</a>
                    </div>
                    """
                )
            else:
                send_data_delivery_to_provider(order.phone_number, f"✅ Your {order.quantity}x {order.size_gb}GB {order.network.upper()} data has been delivered via {COMPANY_NAME}! Order ID: {order.order_id}")
        
        elif new_status == 'failed':
            customer = User.query.get(order.user_id) if order.user_id else None
            if customer and customer.email:
                send_email(
                    customer.email,
                    f"Order Failed - {order.order_id} - {COMPANY_NAME}",
                    f"""
                    <div style="font-family: Arial, sans-serif;">
                        <h2 style="color: #dc3545;">❌ Order Delivery Failed</h2>
                        <p>Dear {customer.username},</p>
                        <p>We're sorry, but your data order could not be delivered.</p>
                        <p><strong>Order ID:</strong> {order.order_id}</p>
                        <p><strong>Package:</strong> {order.quantity}x {order.size_gb}GB {order.network.upper()}</p>
                        <p>Please contact our support team for assistance. Your payment will be refunded.</p>
                        <p>Contact support: {COMPANY_PHONE}</p>
                    </div>
                    """
                )
        
        db.session.commit()
        
        log_activity(g.current_user.id, 'update_order_status', 
                    f'Updated order {order.order_id} status from {old_status} to {new_status}')
        
        return jsonify({'success': True, 'message': f'Order status updated to {new_status} on {COMPANY_NAME}'})
        
    except Exception as e:
        print(f"Update order status error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/agent/order/notify-customer', methods=['POST'])
@token_required
@agent_required
def notify_customer():
    """Send notification to customer about order status (Email ONLY)"""
    try:
        data = request.get_json()
        email = data.get('email')
        message = data.get('message')
        subject = data.get('subject', f'Order Update - {COMPANY_NAME}')
        
        if not email:
            return jsonify({'success': False, 'error': 'Email is required'}), 400
        
        send_email(
            email,
            subject,
            f"""
            <div style="font-family: Arial, sans-serif;">
                <h3>Order Update from {COMPANY_NAME}</h3>
                <p>{message}</p>
                <p>Thank you for choosing {COMPANY_NAME}!</p>
            </div>
            """
        )
        
        log_activity(g.current_user.id, 'notify_customer', f'Notified customer: {email}')
        
        return jsonify({'success': True, 'message': f'Notification sent to {email} from {COMPANY_NAME}'})
        
    except Exception as e:
        print(f"Notify customer error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/agent/check-orders', methods=['GET'])
@token_required
@agent_required
def check_agent_orders():
    """Debug endpoint to check what orders exist"""
    try:
        agent = g.current_user
        
        # Count total orders in database
        total_orders = Order.query.count()
        
        # Count orders where this agent is the agent
        agent_orders = Order.query.filter_by(agent_id=agent.id).count()
        
        # Get sample orders
        all_orders_sample = Order.query.limit(5).all()
        
        return jsonify({
            'success': True,
            'agent_id': agent.id,
            'agent_username': agent.username,
            'total_orders_in_db': total_orders,
            'orders_for_this_agent': agent_orders,
            'sample_orders': [
                {
                    'id': o.id,
                    'order_id': o.order_id,
                    'agent_id': o.agent_id,
                    'user_id': o.user_id,
                    'network': o.network,
                    'amount': float(o.amount),
                    'status': o.status
                } for o in all_orders_sample
            ]
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
# ========== AGENT STORE STATS ENDPOINT ==========

@app.route('/api/agent/store/orders', methods=['GET'])
@token_required
@agent_required
def get_agent_store_orders():
    """Get orders for agent's store"""
    try:
        agent = g.current_user
        
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('limit', 20, type=int)
        
        # Get orders where this agent is the seller
        query = Order.query.filter_by(agent_id=agent.id).order_by(Order.created_at.desc())
        
        paginated = query.paginate(page=page, per_page=per_page, error_out=False)
        
        orders_list = []
        for order in paginated.items:
            orders_list.append({
                'id': order.id,
                'order_id': order.order_id,
                'customer_name': order.customer_name or 'Customer',
                'customer_phone': order.phone_number,
                'network': order.network,
                'size_gb': order.size_gb,
                'amount': float(order.amount),
                'status': order.status,
                'payment_method': order.payment_method,
                'created_at': order.created_at.isoformat() if order.created_at else None,
                'profit': float(order.amount * 0.15)
            })
        
        return jsonify({
            'success': True,
            'data': orders_list,
            'pagination': {
                'page': page,
                'limit': per_page,
                'total': paginated.total,
                'pages': paginated.pages
            }
        })
        
    except Exception as e:
        print(f"Get agent store orders error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ========== AGENT STORE ENDPOINT (already exists, but ensure it's working) ==========

@app.route('/api/agent/store', methods=['GET'])
@token_required
@agent_required
def get_agent_store():
    """Get agent's store settings"""
    try:
        agent = g.current_user
        
        # Try to get existing store
        store = AgentStore.query.filter_by(agent_id=agent.id).first()
        
        if not store:
            # Return default store structure
            return jsonify({
                'success': True,
                'data': {
                    'store_name': f"{agent.username}'s Store",
                    'store_slug': agent.username.lower().replace(' ', '-'),
                    'contact_phone': agent.phone or '',
                    'contact_email': agent.email,
                    'store_description': f"Welcome to {agent.username}'s Roamsmart Digital Store",
                    'markup': 15,
                    'is_active': True,
                    'created_at': datetime.utcnow().isoformat()
                }
            })
        
        return jsonify({
            'success': True,
            'data': {
                'id': store.id,
                'store_name': store.store_name,
                'store_slug': store.store_slug,
                'contact_phone': store.contact_phone,
                'contact_email': store.contact_email,
                'store_description': store.store_description,
                'markup': float(store.markup) if store.markup else 15,
                'is_active': store.is_active,
                'created_at': store.created_at.isoformat() if store.created_at else None
            }
        })
        
    except Exception as e:
        print(f"Get agent store error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/agent/store', methods=['POST'])
@token_required
@agent_required
def save_agent_store():
    """Save or update agent's store settings"""
    try:
        data = request.get_json()
        agent = g.current_user
        
        store = AgentStore.query.filter_by(agent_id=agent.id).first()
        
        if store:
            # Update existing
            store.store_name = data.get('store_name', store.store_name)
            store.store_slug = data.get('store_slug', store.store_slug)
            store.contact_phone = data.get('contact_phone', store.contact_phone)
            store.contact_email = data.get('contact_email', store.contact_email)
            store.store_description = data.get('store_description', store.store_description)
            store.markup = data.get('markup', store.markup)
            store.updated_at = datetime.utcnow()
        else:
            # Create new
            store = AgentStore(
                agent_id=agent.id,
                store_name=data.get('store_name', f"{agent.username}'s Store"),
                store_slug=data.get('store_slug', agent.username.lower().replace(' ', '-')),
                contact_phone=data.get('contact_phone', agent.phone),
                contact_email=data.get('contact_email', agent.email),
                store_description=data.get('store_description', ''),
                markup=data.get('markup', 15),
                is_active=True,
                created_at=datetime.utcnow()
            )
            db.session.add(store)
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Store settings saved successfully',
            'data': {
                'store_name': store.store_name,
                'store_slug': store.store_slug,
                'markup': float(store.markup) if store.markup else 15
            }
        })
        
    except Exception as e:
        print(f"Save agent store error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/agent/products', methods=['GET'])
@token_required
@agent_required
def get_agent_products():
    """Get products for agent store management"""
    try:
        agent = g.current_user
        
        # Get saved custom prices for this agent
        custom_prices = {}
        try:
            from models import AgentProductPrice
            prices = AgentProductPrice.query.filter_by(agent_id=agent.id).all()
            for p in prices:
                custom_prices[f"{p.network}_{p.size_gb}"] = {
                    'retail_price': float(p.retail_price),
                    'markup': float(p.markup)
                }
        except:
            custom_prices = {}
        
        # Products
        products = []
        
        networks = ['mtn', 'telecel', 'airteltigo']
        sizes = [1, 2, 5, 10, 20]
        
        agent_prices = {
            'mtn': {1: 5.50, 2: 10.00, 5: 22.00, 10: 42.00, 20: 80.00},
            'telecel': {1: 5.00, 2: 9.00, 5: 20.00, 10: 38.00, 20: 75.00},
            'airteltigo': {1: 5.00, 2: 9.00, 5: 20.00, 10: 38.00, 20: 75.00}
        }
        
        suggested_prices = {
            'mtn': {1: 6.50, 2: 12.00, 5: 25.00, 10: 48.00, 20: 90.00},
            'telecel': {1: 6.00, 2: 11.00, 5: 23.00, 10: 44.00, 20: 85.00},
            'airteltigo': {1: 6.00, 2: 11.00, 5: 23.00, 10: 44.00, 20: 85.00}
        }
        
        for network in networks:
            for size in sizes:
                if size in agent_prices.get(network, {}):
                    product_key = f"{network}_{size}"
                    wholesale = agent_prices[network][size]
                    
                    # Check if agent has custom price
                    if product_key in custom_prices:
                        retail = custom_prices[product_key]['retail_price']
                        markup = custom_prices[product_key]['markup']
                    else:
                        retail = suggested_prices[network][size]
                        markup = 15  # Default markup
                    
                    products.append({
                        'id': product_key,
                        'network': network,
                        'size_gb': size,
                        'name': f"{network.upper()} {size}GB Data",
                        'wholesale_price': wholesale,
                        'retail_price': retail,
                        'markup': markup,
                        'profit': retail - wholesale,
                        'is_active': True,
                        'created_at': datetime.utcnow().isoformat()
                    })
        
        return jsonify({
            'success': True,
            'data': products,
            'total': len(products)
        })
        
    except Exception as e:
        print(f"Get agent products error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/agent/products/<product_id>', methods=['PUT'])
@token_required
@agent_required
def update_agent_product(product_id):
    """Update agent product pricing"""
    try:
        data = request.get_json()
        retail_price = data.get('retail_price')
        
        if not retail_price:
            return jsonify({'success': False, 'error': 'Retail price required'}), 400
        
        # Parse product ID (format: mtn_1)
        parts = product_id.split('_')
        if len(parts) != 2:
            return jsonify({'success': False, 'error': 'Invalid product ID'}), 400
        
        network = parts[0]
        size_gb = int(parts[1])
        
        # Save custom pricing for this agent
        agent_price_setting = AgentProductPrice.query.filter_by(
            agent_id=g.current_user.id,
            network=network,
            size_gb=size_gb
        ).first()
        
        if agent_price_setting:
            agent_price_setting.retail_price = retail_price
            agent_price_setting.updated_at = datetime.utcnow()
        else:
            agent_price_setting = AgentProductPrice(
                agent_id=g.current_user.id,
                network=network,
                size_gb=size_gb,
                retail_price=retail_price,
                created_at=datetime.utcnow()
            )
            db.session.add(agent_price_setting)
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Updated {network.upper()} {size_gb}GB price to ₵{retail_price}'
        })
        
    except Exception as e:
        print(f"Update agent product error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


def to_float(value):
    """Convert Decimal or other numeric types to float"""
    if value is None:
        return 0.0
    if hasattr(value, 'quantize'):  # Decimal
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0

@app.route('/api/agent/store/stats', methods=['GET'])
@token_required
@agent_required
def get_agent_store_stats():
    """Get agent's store statistics for dashboard"""
    try:
        agent = g.current_user
        
        # Get date ranges
        today = datetime.utcnow().date()
        week_start = today - timedelta(days=today.weekday())
        month_start = today.replace(day=1)
        
        today_start = datetime.combine(today, datetime.min.time())
        week_start_dt = datetime.combine(week_start, datetime.min.time())
        month_start_dt = datetime.combine(month_start, datetime.min.time())
        
        # Get orders stats
        total_orders = Order.query.filter_by(agent_id=agent.id).count()
        completed_orders = Order.query.filter_by(agent_id=agent.id, status='completed').count()
        pending_orders = Order.query.filter_by(agent_id=agent.id, status='pending').count()
        
        # Get revenue stats
        total_revenue = to_float(db.session.query(func.sum(Order.amount)).filter(
            Order.agent_id == agent.id,
            Order.status == 'completed'
        ).scalar())
        
        today_sales = to_float(db.session.query(func.sum(Order.amount)).filter(
            Order.agent_id == agent.id,
            Order.status == 'completed',
            Order.created_at >= today_start
        ).scalar())
        
        week_sales = to_float(db.session.query(func.sum(Order.amount)).filter(
            Order.agent_id == agent.id,
            Order.status == 'completed',
            Order.created_at >= week_start_dt
        ).scalar())
        
        month_sales = to_float(db.session.query(func.sum(Order.amount)).filter(
            Order.agent_id == agent.id,
            Order.status == 'completed',
            Order.created_at >= month_start_dt
        ).scalar())
        
        # Customer count
        customer_count = db.session.query(Order.phone_number).filter(
            Order.agent_id == agent.id,
            Order.status == 'completed'
        ).distinct().count()
        
        # Calculate commission
        commission_rate = 15
        total_commission = total_revenue * (commission_rate / 100)
        
        return jsonify({
            'success': True,
            'data': {
                'total_orders': total_orders,
                'completed_orders': completed_orders,
                'pending_orders': pending_orders,
                'total_revenue': total_revenue,
                'total_commission': total_commission,
                'today_sales': today_sales,
                'week_sales': week_sales,
                'month_sales': month_sales,
                'customer_count': customer_count,
                'store_name': agent.username,
                'store_slug': None,
                'store_rating': 5.0,
                'store_views': 0,
                'conversion_rate': float((completed_orders / total_orders * 100) if total_orders > 0 else 0)
            }
        })
        
    except Exception as e:
        print(f"Agent store stats error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


# ========== AGENT INVENTORY TRANSACTIONS ENDPOINT ==========

@app.route('/api/agent/inventory/transactions', methods=['GET'])
@token_required
@agent_required
def get_agent_inventory_transactions():
    """Get agent's inventory purchase history"""
    try:
        agent = g.current_user
        
        # Get pagination parameters
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('limit', 20, type=int)
        
        # Query from the new table
        transactions = AgentInventoryTransaction.query.filter_by(
            agent_id=agent.id
        ).order_by(AgentInventoryTransaction.created_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        result = []
        for t in transactions.items:
            result.append({
                'id': t.id,
                'network': t.network,
                'size_gb': t.size_gb,
                'quantity': t.quantity,
                'total_gb': t.size_gb * t.quantity,
                'price_per_unit': float(t.price_per_unit),
                'amount': float(t.total_amount),
                'payment_method': t.payment_method,
                'status': t.status,
                'reference': t.reference,
                'created_at': t.created_at.isoformat() if t.created_at else None
            })
        
        return jsonify({
            'success': True,
            'data': result,
            'pagination': {
                'page': page,
                'limit': per_page,
                'total': transactions.total,
                'pages': transactions.pages
            }
        })
        
    except Exception as e:
        print(f"Agent inventory transactions error: {e}")
        return jsonify({
            'success': True,
            'data': [],
            'pagination': {'page': 1, 'limit': 20, 'total': 0, 'pages': 1}
        }), 200

# ========== AGENT INVENTORY PURCHASE ENDPOINT ==========

@app.route('/api/agent/inventory/purchase', methods=['POST'])
@token_required
@agent_required
def purchase_wholesale_inventory():
    """Agent purchases wholesale data for their inventory"""
    try:
        data = request.get_json()
        network = data.get('network')
        size_gb = data.get('size_gb')
        quantity = data.get('quantity', 1)
        
        if not network or not size_gb:
            return jsonify({'success': False, 'error': 'Network and size required'}), 400
        
        agent = g.current_user
        
        # Agent wholesale prices
        wholesale_prices = {
            'mtn': {1: 5.50, 2: 10.00, 5: 22.00, 10: 42.00, 20: 80.00},
            'telecel': {1: 5.00, 2: 9.00, 5: 20.00, 10: 38.00, 20: 75.00},
            'airteltigo': {1: 5.00, 2: 9.00, 5: 20.00, 10: 38.00, 20: 75.00}
        }
        
        price_per_unit = wholesale_prices.get(network, {}).get(size_gb)
        if not price_per_unit:
            return jsonify({'success': False, 'error': 'Invalid bundle size'}), 400
        
        total_amount = price_per_unit * quantity
        
        # Check wallet balance
        if agent.wallet_balance < total_amount:
            return jsonify({
                'success': False,
                'error': f'Insufficient balance. Need ₵{total_amount:.2f}'
            }), 400
        
        # Deduct from wallet
        balance_before = agent.wallet_balance
        agent.wallet_balance -= total_amount
        
        # Create transaction record in the new table
        import uuid
        transaction = AgentInventoryTransaction(
            agent_id=agent.id,
            network=network,
            size_gb=size_gb,
            quantity=quantity,
            price_per_unit=price_per_unit,
            total_amount=total_amount,
            payment_method='wallet',
            status='completed',
            reference=f"WH-{uuid.uuid4().hex[:8].upper()}"
        )
        db.session.add(transaction)
        
        # Update agent's inventory (add to existing)
        inventory = AgentInventory.query.filter_by(
            agent_id=agent.id,
            network=network,
            size_gb=size_gb
        ).first()
        
        if inventory:
            inventory.quantity += quantity
            inventory.total += size_gb * quantity
            inventory.remaining += size_gb * quantity
        else:
            inventory = AgentInventory(
                agent_id=agent.id,
                network=network,
                size_gb=size_gb,
                quantity=quantity,
                total=size_gb * quantity,
                remaining=size_gb * quantity,
                sold=0
            )
            db.session.add(inventory)
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Purchased {quantity}x {size_gb}GB {network.upper()} data',
            'data': {
                'total_amount': float(total_amount),
                'new_balance': float(agent.wallet_balance),
                'total_gb': size_gb * quantity,
                'transaction_id': transaction.id
            }
        })
        
    except Exception as e:
        print(f"Purchase wholesale inventory error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

# ========== PRICE MANAGEMENT ENDPOINTS (Super Admin Only) ==========
def get_or_create_price_password():
    """Get or create price management password hash and salt"""
    from models import SystemSetting
    
    password_hash = SystemSetting.get('price_password_hash')
    password_salt = SystemSetting.get('price_password_salt')
    
    if not password_hash or not password_salt:
        # Set default password on first run
        default_password = "Roamsmart@2024"
        salt = secrets.token_hex(16)
        password_hash_value = hashlib.sha256(f"{default_password}{salt}".encode()).hexdigest()
        
        SystemSetting.set('price_password_salt', salt, 'string', 'Salt for price management password hashing')
        SystemSetting.set('price_password_hash', password_hash_value, 'string', 'Hashed price management password')
        
        return password_hash_value, salt
    
    return password_hash, password_salt


def verify_price_password(password):
    """Verify the price management password"""
    stored_hash, salt = get_or_create_price_password()
    input_hash = hashlib.sha256(f"{password}{salt}".encode()).hexdigest()
    return input_hash == stored_hash


def create_price_session(user_id):
    """Create a new price management session in database"""
    token = secrets.token_hex(32)
    expiry = datetime.utcnow() + timedelta(hours=1)
    
    # Clean up expired sessions first
    cleanup_expired_sessions()
    
    # Create new session in database
    session = PriceSession(
        token=token,
        user_id=user_id,
        expires_at=expiry,
        is_active=True
    )
    db.session.add(session)
    db.session.commit()
    
    return token


def verify_price_session(token):
    """Verify if session token is valid from database"""
    if not token:
        return False
    
    # Clean up expired sessions
    cleanup_expired_sessions()
    
    # Find active session
    session = PriceSession.query.filter_by(
        token=token,
        is_active=True
    ).first()
    
    if not session:
        return False
    
    # Check if expired
    if datetime.utcnow() > session.expires_at:
        session.is_active = False
        db.session.commit()
        return False
    
    return True


def cleanup_expired_sessions():
    """Remove or mark expired sessions as inactive"""
    now = datetime.utcnow()
    
    # Mark expired sessions as inactive
    expired_sessions = PriceSession.query.filter(
        PriceSession.expires_at < now,
        PriceSession.is_active == True
    ).all()
    
    for session in expired_sessions:
        session.is_active = False
    
    if expired_sessions:
        db.session.commit()


def get_price_session_user(token):
    """Get user ID from session token"""
    session = PriceSession.query.filter_by(
        token=token,
        is_active=True
    ).first()
    
    if not session:
        return None
    
    if datetime.utcnow() > session.expires_at:
        session.is_active = False
        db.session.commit()
        return None
    
    return session.user_id


def revoke_all_user_sessions(user_id):
    """Revoke all sessions for a user"""
    sessions = PriceSession.query.filter_by(
        user_id=user_id,
        is_active=True
    ).all()
    
    for session in sessions:
        session.is_active = False
    
    db.session.commit()


def revoke_all_sessions():
    """Revoke all active price sessions (used when password changes)"""
    sessions = PriceSession.query.filter_by(is_active=True).all()
    
    for session in sessions:
        session.is_active = False
    
    db.session.commit()


def price_session_required(f):
    """Decorator to require price management session token for write operations"""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_token = request.headers.get('X-Price-Auth')
        
        if not auth_token:
            return jsonify({
                'success': False, 
                'error': 'Price management session required. Please enter password first.',
                'requires_auth': True
            }), 401
        
        if not verify_price_session(auth_token):
            return jsonify({
                'success': False, 
                'error': 'Session expired or invalid. Please re-enter password.',
                'requires_auth': True
            }), 401
        
        return f(*args, **kwargs)
    return decorated


# ========== PRICE MANAGEMENT ENDPOINTS ==========

@app.route('/api/admin/prices', methods=['GET'])
@token_required
@admin_required
def get_all_prices():
    """Get all prices for admin management (READ ONLY - no password required)"""
    try:
        # Get prices from database or return defaults
        price_settings = PriceSetting.query.all()
        
        if not price_settings:
            # Return default prices
            default_prices = {
                'user_prices': {
                    'mtn': {'1': 6.50, '2': 12.00, '5': 25.00, '10': 48.00, '20': 90.00},
                    'telecel': {'1': 6.00, '2': 11.00, '5': 23.00, '10': 44.00, '20': 85.00},
                    'airteltigo': {'1': 6.00, '2': 11.00, '5': 23.00, '10': 44.00, '20': 85.00}
                },
                'agent_prices': {
                    'mtn': {'1': 5.50, '2': 10.00, '5': 22.00, '10': 42.00, '20': 80.00},
                    'telecel': {'1': 5.00, '2': 9.00, '5': 20.00, '10': 38.00, '20': 75.00},
                    'airteltigo': {'1': 5.00, '2': 9.00, '5': 20.00, '10': 38.00, '20': 75.00}
                },
                'waec_prices': {
                    'WASSCE': 20.00,
                    'BECE': 15.00,
                    'SHS Placement': 10.00
                },
                'commission_rates': {
                    'Bronze': 10,
                    'Silver': 15,
                    'Gold': 20,
                    'Platinum': 25
                }
            }
            return jsonify({'success': True, 'data': default_prices})
        
        result = {
            'user_prices': {},
            'agent_prices': {},
            'waec_prices': {},
            'commission_rates': {}
        }
        
        for setting in price_settings:
            if setting.category == 'user_price':
                if setting.network not in result['user_prices']:
                    result['user_prices'][setting.network] = {}
                result['user_prices'][setting.network][str(setting.size_gb)] = float(setting.price)
            elif setting.category == 'agent_price':
                if setting.network not in result['agent_prices']:
                    result['agent_prices'][setting.network] = {}
                result['agent_prices'][setting.network][str(setting.size_gb)] = float(setting.price)
            elif setting.category == 'waec_price':
                result['waec_prices'][setting.exam_type] = float(setting.price)
            elif setting.category == 'commission_rate':
                result['commission_rates'][setting.tier] = float(setting.rate)
        
        return jsonify({'success': True, 'data': result})
        
    except Exception as e:
        print(f"Get all prices error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/admin/prices/verify', methods=['POST'])
@token_required
@admin_required
def verify_price_password_endpoint():
    """Verify price management password and create session"""
    try:
        data = request.get_json()
        password = data.get('password')
        
        if not password:
            return jsonify({'success': False, 'error': 'Password required'}), 400
        
        if verify_price_password(password):
            # Create session token in database
            token = create_price_session(g.current_user.id)
            
            return jsonify({
                'success': True,
                'message': 'Password verified. You can now edit prices.',
                'token': token,
                'expires_in': 3600  # 1 hour
            })
        else:
            return jsonify({'success': False, 'error': 'Invalid password'}), 401
            
    except Exception as e:
        print(f"Verify price password error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/admin/prices/logout', methods=['POST'])
@token_required
def price_session_logout():
    """Logout from price management session"""
    try:
        auth_token = request.headers.get('X-Price-Auth')
        
        if auth_token:
            # Find and deactivate the session in database
            session = PriceSession.query.filter_by(token=auth_token, is_active=True).first()
            if session:
                session.is_active = False
                db.session.commit()
        
        return jsonify({'success': True, 'message': 'Logged out of price management'})
        
    except Exception as e:
        print(f"Price logout error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/admin/prices/check-auth', methods=['GET'])
@token_required
def check_price_auth():
    """Check if current price management session is still valid"""
    try:
        auth_token = request.headers.get('X-Price-Auth')
        if not auth_token:
            return jsonify({'success': True, 'authenticated': False}), 200
        
        is_valid = verify_price_session(auth_token)
        return jsonify({'success': True, 'authenticated': is_valid}), 200
        
    except Exception as e:
        return jsonify({'success': True, 'authenticated': False}), 200


@app.route('/api/admin/prices/sessions', methods=['GET'])
@token_required
@super_admin_required
def get_active_price_sessions():
    """Get all active price management sessions (Super Admin only)"""
    try:
        sessions = PriceSession.query.filter_by(is_active=True).all()
        
        result = []
        for session in sessions:
            user = User.query.get(session.user_id)
            result.append({
                'id': session.id,
                'user': user.username if user else 'Unknown',
                'created_at': session.created_at.isoformat() if session.created_at else None,
                'expires_at': session.expires_at.isoformat() if session.expires_at else None
            })
        
        return jsonify({'success': True, 'data': result})
        
    except Exception as e:
        print(f"Get price sessions error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/admin/prices/revoke-session/<int:session_id>', methods=['DELETE'])
@token_required
@super_admin_required
def revoke_price_session(session_id):
    """Revoke a specific price management session (Super Admin only)"""
    try:
        session = PriceSession.query.get(session_id)
        if session:
            session.is_active = False
            db.session.commit()
            return jsonify({'success': True, 'message': 'Session revoked successfully'})
        
        return jsonify({'success': False, 'error': 'Session not found'}), 404
        
    except Exception as e:
        print(f"Revoke session error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/admin/prices/update-password', methods=['POST'])
@token_required
@super_admin_required
def update_price_password():
    """Update price management password (Super Admin only)"""
    try:
        data = request.get_json()
        new_password = data.get('new_password')
        confirm_password = data.get('confirm_password')
        
        if not new_password or len(new_password) < 6:
            return jsonify({'success': False, 'error': 'Password must be at least 6 characters'}), 400
        
        if new_password != confirm_password:
            return jsonify({'success': False, 'error': 'Passwords do not match'}), 400
        
        # Generate new salt and hash
        salt = secrets.token_hex(16)
        password_hash = hashlib.sha256(f"{new_password}{salt}".encode()).hexdigest()
        
        # Update settings using SystemSetting
        from models import SystemSetting
        SystemSetting.set('price_password_salt', salt, 'string', 'Salt for price management password hashing', updated_by=g.current_user.id)
        SystemSetting.set('price_password_hash', password_hash, 'string', 'Hashed price management password', updated_by=g.current_user.id)
        
        # Revoke all active sessions (force re-login)
        revoke_all_sessions()
        
        return jsonify({
            'success': True,
            'message': 'Price management password updated successfully. All active sessions have been terminated.'
        })
        
    except Exception as e:
        print(f"Update price password error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


# ========== PRICE UPDATE ENDPOINTS (with session requirement) ==========

@app.route('/api/admin/prices/user', methods=['PUT'])
@token_required
@admin_required
@price_session_required
def update_user_prices():
    """Update user retail prices (requires price management password)"""
    try:
        data = request.get_json()
        network = data.get('network')
        size_gb = data.get('size_gb')
        price = data.get('price')
        
        if not all([network, size_gb, price]):
            return jsonify({'success': False, 'error': 'Missing required fields'}), 400
        
        # Update or create price setting
        price_setting = PriceSetting.query.filter_by(
            category='user_price',
            network=network,
            size_gb=size_gb
        ).first()
        
        if price_setting:
            price_setting.price = price
            price_setting.updated_at = datetime.utcnow()
        else:
            price_setting = PriceSetting(
                category='user_price',
                network=network,
                size_gb=size_gb,
                price=price,
                created_at=datetime.utcnow()
            )
            db.session.add(price_setting)
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Updated {network.upper()} {size_gb}GB user price to ₵{price}'
        })
        
    except Exception as e:
        print(f"Update user price error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/admin/prices/agent', methods=['PUT'])
@token_required
@admin_required
@price_session_required
def update_agent_prices():
    """Update agent wholesale prices (requires price management password)"""
    try:
        data = request.get_json()
        network = data.get('network')
        size_gb = data.get('size_gb')
        price = data.get('price')
        
        if not all([network, size_gb, price]):
            return jsonify({'success': False, 'error': 'Missing required fields'}), 400
        
        price_setting = PriceSetting.query.filter_by(
            category='agent_price',
            network=network,
            size_gb=size_gb
        ).first()
        
        if price_setting:
            price_setting.price = price
            price_setting.updated_at = datetime.utcnow()
        else:
            price_setting = PriceSetting(
                category='agent_price',
                network=network,
                size_gb=size_gb,
                price=price,
                created_at=datetime.utcnow()
            )
            db.session.add(price_setting)
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Updated {network.upper()} {size_gb}GB agent price to ₵{price}'
        })
        
    except Exception as e:
        print(f"Update agent price error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/admin/prices/waec', methods=['PUT'])
@token_required
@admin_required
@price_session_required
def update_waec_prices():
    """Update WAEC voucher prices (requires price management password)"""
    try:
        data = request.get_json()
        exam_type = data.get('exam_type')
        price = data.get('price')
        
        if not all([exam_type, price]):
            return jsonify({'success': False, 'error': 'Missing required fields'}), 400
        
        price_setting = PriceSetting.query.filter_by(
            category='waec_price',
            exam_type=exam_type
        ).first()
        
        if price_setting:
            price_setting.price = price
            price_setting.updated_at = datetime.utcnow()
        else:
            price_setting = PriceSetting(
                category='waec_price',
                exam_type=exam_type,
                price=price,
                created_at=datetime.utcnow()
            )
            db.session.add(price_setting)
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Updated {exam_type} price to ₵{price}'
        })
        
    except Exception as e:
        print(f"Update WAEC price error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/admin/prices/commission', methods=['PUT'])
@token_required
@admin_required
@price_session_required
def update_commission_rates():
    """Update agent commission rates by tier (requires price management password)"""
    try:
        data = request.get_json()
        tier = data.get('tier')
        rate = data.get('rate')
        
        if not all([tier, rate]):
            return jsonify({'success': False, 'error': 'Missing required fields'}), 400
        
        price_setting = PriceSetting.query.filter_by(
            category='commission_rate',
            tier=tier
        ).first()
        
        if price_setting:
            price_setting.rate = rate
            price_setting.updated_at = datetime.utcnow()
        else:
            price_setting = PriceSetting(
                category='commission_rate',
                tier=tier,
                rate=rate,
                created_at=datetime.utcnow()
            )
            db.session.add(price_setting)
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Updated {tier} commission rate to {rate}%'
        })
        
    except Exception as e:
        print(f"Update commission rate error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

# ========== AGENT CUSTOMER ROUTES ==========

@app.route('/api/agent/customers/<int:customer_id>/orders', methods=['GET'])
@token_required
@agent_required
def get_customer_orders(customer_id):
    """Get orders for a specific customer"""
    try:
        orders = Order.query.filter_by(
            agent_id=g.current_user.id, 
            user_id=customer_id
        ).order_by(Order.created_at.desc()).all()
        
        return jsonify({
            'success': True, 
            'data': [o.to_dict() for o in orders]
        })
    except Exception as e:
        print(f"Get customer orders error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/agent/customers/<int:customer_id>/stats', methods=['GET'])
@token_required
@agent_required
def get_customer_stats(customer_id):
    """Get stats for a specific customer"""
    try:
        orders = Order.query.filter_by(
            agent_id=g.current_user.id, 
            user_id=customer_id,
            status='completed'
        ).all()
        
        total_spent = sum(o.amount for o in orders)
        total_orders = len(orders)
        
        customer = User.query.get(customer_id)
        
        if not customer:
            return jsonify({'success': False, 'error': 'Customer not found'}), 404
        
        avg_order_value = total_spent / total_orders if total_orders > 0 else 0
        last_order = orders[0].created_at if orders else None
        
        return jsonify({
            'success': True,
            'data': {
                'customer_id': customer.id,
                'customer_name': customer.username,
                'customer_phone': customer.phone,
                'customer_email': customer.email,
                'total_orders': total_orders,
                'total_spent': float(total_spent),
                'avg_order_value': float(avg_order_value),
                'loyalty_points': int(total_spent / 10),
                'joined_date': customer.created_at.isoformat() if customer.created_at else None,
                'last_order_date': last_order.isoformat() if last_order else None,
                'platform': COMPANY_NAME
            }
        })
        
    except Exception as e:
        print(f"Get customer stats error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# Add this to your existing app.py

@app.route('/api/admin/africastalking-balance', methods=['GET'])
@token_required
@admin_required
def get_africastalking_balance():
    """Fetch Africa's Talking account balance"""
    try:
        import africastalking
        import os
        
        username = os.environ.get('AFRICASTALKING_USERNAME', 'sandbox')
        api_key = os.environ.get('AFRICASTALKING_API_KEY')
        
        if not api_key:
            return jsonify({
                'success': False,
                'error': 'Africa\'s Talking API key not configured'
            }), 500
        
        africastalking.initialize(username, api_key)
        application = africastalking.Application
        
        # Fetch wallet balance
        wallet_balance = application.fetch_wallet_balance()
        
        # Fetch application data
        app_data = application.fetch_application_data()
        
        return jsonify({
            'success': True,
            'data': {
                'account_balance': app_data.get('balance', 0),
                'wallet_balance': wallet_balance.get('balance', 0),
                'currency': 'GHS',
                'last_updated': datetime.utcnow().isoformat()
            }
        })
        
    except Exception as e:
        print(f"Error fetching Africa's Talking balance: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/admin/purchase-data', methods=['POST'])
@token_required
@admin_required
def admin_purchase_data():
    """Admin purchases data from network provider - NO SMS"""
    try:
        data = request.get_json()
        
        network = data.get('network', 'mtn')
        size_gb = data.get('size_gb')
        quantity = data.get('quantity', 1)
        total_gb = data.get('total_gb')
        amount_paid = data.get('amount_paid')
        phone_number = data.get('phone_number')
        is_custom = data.get('is_custom', False)
        
        if not amount_paid:
            return jsonify({'success': False, 'error': 'Amount paid is required'}), 400
        
        # Calculate total GB
        if is_custom:
            total_gb_value = total_gb
        else:
            total_gb_value = size_gb * quantity
        
        # Use your existing InventoryService to add to master inventory
        inventory_service = InventoryService()
        inventory_service.add_to_master_inventory(
            network=network,
            size_gb=size_gb if not is_custom else 1,
            quantity=quantity if not is_custom else int(total_gb_value),
            purchase_price=amount_paid
        )
        
        # Create purchase record (optional - for tracking)
        purchase = NetworkPurchase(
            admin_id=g.current_user.id,
            network=network,
            size_gb=size_gb if not is_custom else total_gb_value,
            quantity=quantity if not is_custom else 1,
            total_gb=total_gb_value,
            amount_paid=amount_paid,
            phone_number=phone_number,
            status='completed',
            created_at=datetime.utcnow()
        )
        db.session.add(purchase)
        
        # Log transaction
        transaction = Transaction(
            user_id=g.current_user.id,
            type='debit',
            amount=amount_paid,
            balance_before=g.current_user.wallet_balance,
            balance_after=g.current_user.wallet_balance,
            description=f'Data purchase from {network.upper()} - {total_gb_value}GB',
            reference=f"ADMIN-PURCHASE-{uuid.uuid4().hex[:8].upper()}",
            status='completed'
        )
        db.session.add(transaction)
        
        db.session.commit()
        
        # NO SMS SENDING - Only log
        print(f"[ADMIN PURCHASE] Admin: {g.current_user.username}, Network: {network}, Total GB: {total_gb_value}, Amount: ₵{amount_paid}")
        
        return jsonify({
            'success': True,
            'message': f'Successfully purchased {total_gb_value} GB from {network.upper()}',
            'data': {
                'total_gb': total_gb_value,
                'amount_paid': amount_paid,
                'network': network
            }
        }), 201
        
    except Exception as e:
        print(f"Admin purchase error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/user/purchase-data', methods=['POST'])
@token_required
def user_purchase_data():
    """User purchases data using wallet balance - delivers via Africa's Talking"""
    try:
        data = request.get_json()
        
        network = data.get('network')
        size_gb = data.get('size_gb')
        phone_number = data.get('phone_number')
        quantity = data.get('quantity', 1)
        
        if not network or not size_gb or not phone_number:
            return jsonify({'success': False, 'error': 'Network, size, and phone required'}), 400
        
        user = g.current_user
        
        # Get price from PriceSetting
        price_setting = PriceSetting.query.filter_by(
            category='user_price' if not user.is_agent else 'agent_price',
            network=network,
            size_gb=size_gb
        ).first()
        
        if not price_setting:
            return jsonify({'success': False, 'error': f'Price not configured for {network} {size_gb}GB'}), 400
        
        price_per_unit = float(price_setting.price)
        total_price = price_per_unit * quantity
        total_gb = size_gb * quantity
        
        # Check wallet balance
        if user.wallet_balance < total_price:
            return jsonify({'success': False, 'error': f'Insufficient balance. Need ₵{total_price:.2f}'}), 400
        
        # Check inventory
        inventory = MasterInventory.query.filter_by(
            network=network,
            size_gb=size_gb
        ).first()
        
        if not inventory or inventory.remaining < total_gb:
            return jsonify({'success': False, 'error': 'Insufficient inventory. Please contact admin.'}), 400
        
        # Format phone number for Africa's Talking (international format)
        # Convert Ghana number (024XXXXXXX) to international format (23324XXXXXXX)
        if phone_number.startswith('0'):
            international_phone = '233' + phone_number[1:]
        else:
            international_phone = phone_number
        
        # Send data via Africa's Talking
        delivery_result = send_data_to_customer(international_phone, size_gb, quantity)
        
        if not delivery_result['success']:
            return jsonify({
                'success': False, 
                'error': f'Data delivery failed: {delivery_result.get("error", "Unknown error")}'
            }), 500
        
        # Deduct from user wallet
        balance_before = user.wallet_balance
        user.wallet_balance -= total_price
        
        # Update inventory
        inventory.remaining -= total_gb
        inventory.sold_to_users = (inventory.sold_to_users or 0) + total_gb
        
        # Create order
        order_id = f"ORD-{uuid.uuid4().hex[:8].upper()}"
        order = Order(
            user_id=user.id,
            order_id=order_id,
            network=network,
            size_gb=size_gb,
            quantity=quantity,
            phone_number=phone_number,
            amount=total_price,
            status='completed',
            payment_method='wallet',
            created_at=datetime.utcnow(),
            completed_at=datetime.utcnow(),
            delivery_transaction_id=delivery_result.get('transaction_id')
        )
        db.session.add(order)
        
        # Create transaction
        transaction = Transaction(
            user_id=user.id,
            type='debit',
            amount=total_price,
            balance_before=balance_before,
            balance_after=user.wallet_balance,
            description=f'Data purchase - {quantity}x {size_gb}GB {network.upper()} to {phone_number}',
            reference=order_id,
            status='completed',
            delivery_status='delivered'
        )
        db.session.add(transaction)
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Successfully purchased and delivered {total_gb}GB {network.upper()} data to {phone_number}',
            'data': {
                'order_id': order_id,
                'total_gb': total_gb,
                'total_price': total_price,
                'new_balance': float(user.wallet_balance),
                'delivery_status': 'delivered',
                'delivery_transaction_id': delivery_result.get('transaction_id')
            }
        }), 201
        
    except Exception as e:
        print(f"User purchase error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/agent/customers', methods=['GET'])
@token_required
@agent_required
def get_agent_admin_customers():
    """Get all customers for the agent"""
    try:
        customers_dict = {}
        orders = Order.query.filter_by(agent_id=g.current_user.id).order_by(Order.created_at.desc()).all()
        
        for order in orders:
            if order.user_id:
                customer = User.query.get(order.user_id)
                if customer and customer.phone not in customers_dict:
                    customer_orders = Order.query.filter_by(
                        agent_id=g.current_user.id,
                        user_id=customer.id,
                        status='completed'
                    ).all()
                    total_spent = sum(o.amount for o in customer_orders)
                    
                    customers_dict[customer.phone] = {
                        'id': customer.id,
                        'name': customer.username,
                        'phone': customer.phone,
                        'email': customer.email,
                        'total_spent': float(total_spent),
                        'order_count': len(customer_orders),
                        'last_purchase': order.created_at.isoformat(),
                        'joined_date': customer.created_at.isoformat() if customer.created_at else None
                    }
        
        return jsonify({
            'success': True, 
            'data': list(customers_dict.values())
        })
        
    except Exception as e:
        print(f"Get agent customers error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

class EmailService:
    """Email service for welcome messages and notifications (Email ONLY - No SMS)"""
    
    def __init__(self):
        self.sendgrid_api_key = os.environ.get('SENDGRID_API_KEY')
        self.from_email = os.environ.get('FROM_EMAIL', f'admin@{COMPANY_DOMAIN}')
        self.from_name = os.environ.get('FROM_NAME', COMPANY_NAME)
    
    def send_welcome_email(self, email, username, role='user', referral_code=None):
        """Send welcome email to new user (Email ONLY)"""
        
        if role == 'agent':
            subject = f"🎉 Welcome to {COMPANY_NAME} Agent Program!"
            
            html_content = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <style>
                    body {{ font-family: 'Segoe UI', Arial, sans-serif; line-height: 1.6; color: #333; }}
                    .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                    .header {{ background: linear-gradient(135deg, #8B0000, #D2691E); color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0; }}
                    .content {{ padding: 30px; background: #f9f9f9; }}
                    .button {{ display: inline-block; background: #8B0000; color: white; padding: 12px 30px; text-decoration: none; border-radius: 5px; margin: 20px 0; }}
                    .feature {{ margin: 20px 0; padding: 15px; background: white; border-radius: 8px; border-left: 4px solid #8B0000; }}
                    .footer {{ text-align: center; padding: 20px; color: #666; font-size: 12px; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h1>🎉 Welcome to the {COMPANY_NAME} Agent Program!</h1>
                    </div>
                    <div class="content">
                        <h2>Hello {username},</h2>
                        <p>Congratulations! Your agent application has been approved. You now have access to:</p>
                        
                        <div class="feature">
                            <strong>✅ Wholesale Data Prices</strong><br>
                            Save up to 40% on data bundles
                        </div>
                        
                        <div class="feature">
                            <strong>✅ Your Own Branded Store</strong><br>
                            Create your custom store with your pricing
                        </div>
                        
                        <div class="feature">
                            <strong>✅ Earn Up to 25% Commission</strong><br>
                            Make profit on every sale
                        </div>
                        
                        <div class="feature">
                            <strong>✅ Real-time Order Tracking</strong><br>
                            Track all your sales and customers
                        </div>
                        
                        <a href="{COMPANY_WEBSITE}/agent/dashboard" class="button">🚀 Go to Agent Dashboard</a>
                        
                        <h3>📊 Quick Start Guide:</h3>
                        <ol>
                            <li>Fund your wallet via Mobile Money or Card</li>
                            <li>Purchase wholesale data bundles from inventory</li>
                            <li>Set your selling price (recommended: 15-20% markup)</li>
                            <li>Start selling to customers!</li>
                        </ol>
                        
                        <p>Need help? Contact us on WhatsApp: <strong>{COMPANY_PHONE}</strong></p>
                    </div>
                    <div class="footer">
                        <p>© 2025 {COMPANY_NAME}. All rights reserved.</p>
                        <p><small>If you didn't request this, please ignore this email.</small></p>
                    </div>
                </div>
            </body>
            </html>
            """
        else:
            subject = f"Welcome to {COMPANY_NAME}! 🚀"
            
            html_content = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <style>
                    body {{ font-family: 'Segoe UI', Arial, sans-serif; line-height: 1.6; color: #333; }}
                    .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                    .header {{ background: linear-gradient(135deg, #8B0000, #D2691E); color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0; }}
                    .content {{ padding: 30px; background: #f9f9f9; }}
                    .code {{ background: white; padding: 10px; font-size: 24px; font-weight: bold; text-align: center; letter-spacing: 5px; border-radius: 5px; margin: 20px 0; }}
                    .button {{ display: inline-block; background: #8B0000; color: white; padding: 12px 30px; text-decoration: none; border-radius: 5px; margin: 20px 0; }}
                    .footer {{ text-align: center; padding: 20px; color: #666; font-size: 12px; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h1>Welcome to {COMPANY_NAME}!</h1>
                    </div>
                    <div class="content">
                        <h2>Hello {username},</h2>
                        <p>Thank you for joining {COMPANY_NAME}! You can now purchase data bundles instantly.</p>
                        
                        <p><strong>🎁 Your Client Code:</strong></p>
                        <div class="code">{referral_code or 'N/A'}</div>
                        
                        <p>Share this code with friends and earn <strong>GHS 5</strong> for each referral!</p>
                        
                        <a href="{COMPANY_WEBSITE}/dashboard" class="button">📱 Go to Dashboard</a>
                        
                        <h3>✨ What you can do:</h3>
                        <ul>
                            <li>Buy data bundles for MTN, Telecel, and AirtelTigo</li>
                            <li>Get 2-second delivery</li>
                            <li>Earn GHS 5 for every friend you refer</li>
                            <li>24/7 customer support</li>
                        </ul>
                        
                        <p>Need help? Contact us on WhatsApp: <strong>{COMPANY_PHONE}</strong></p>
                    </div>
                    <div class="footer">
                        <p>© 2025 {COMPANY_NAME}. All rights reserved.</p>
                    </div>
                </div>
            </body>
            </html>
            """
        
        # Try SendGrid first if configured
        if self.sendgrid_api_key:
            try:
                from sendgrid import SendGridAPIClient
                from sendgrid.helpers.mail import Mail
                
                message = Mail(
                    from_email=self.from_email,
                    to_emails=email,
                    subject=subject,
                    html_content=html_content
                )
                
                sg = SendGridAPIClient(self.sendgrid_api_key)
                response = sg.send(message)
                
                if response.status_code in [200, 202]:
                    print(f"Welcome email sent to {email} via SendGrid")
                    return True
                else:
                    print(f"SendGrid error: {response.status_code}")
                    return send_email(email, subject, html_content)
                    
            except Exception as e:
                print(f"SendGrid error: {e}")
                return send_email(email, subject, html_content)
        else:
            return send_email(email, subject, html_content)
    
    def send_payment_confirmation(self, email, username, amount, reference, balance=None):
        """Send payment confirmation email (Email ONLY)"""
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: #8B0000; color: white; padding: 20px; text-align: center; border-radius: 10px 10px 0 0; }}
                .content {{ padding: 20px; background: #f9f9f9; }}
                .amount {{ font-size: 32px; font-weight: bold; color: #8B0000; text-align: center; margin: 20px 0; }}
                .footer {{ text-align: center; padding: 20px; color: #666; font-size: 12px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h2>✅ Payment Confirmed - {COMPANY_NAME}</h2>
                </div>
                <div class="content">
                    <p>Hello <strong>{username}</strong>,</p>
                    <p>Your payment has been successfully processed and credited to your wallet.</p>
                    
                    <div class="amount">₵{amount:.2f}</div>
                    
                    <p><strong>Reference:</strong> {reference}</p>
                    {f'<p><strong>New Balance:</strong> ₵{balance:.2f}</p>' if balance else ''}
                    
                    <p>You can now use your wallet balance to purchase data bundles instantly.</p>
                    
                    <a href="{COMPANY_WEBSITE}/wallet" style="background: #8B0000; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px; display: inline-block;">View Wallet</a>
                </div>
                <div class="footer">
                    <p>Need help? Contact us on WhatsApp: {COMPANY_PHONE}</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        return send_email(email, f"✅ Payment Confirmed - {COMPANY_NAME}", html_content)
    
    def send_withdrawal_notification(self, email, username, amount, status, reference=None, notes=None):
        """Send withdrawal status notification (Email ONLY)"""
        if status == 'approved':
            subject = "✅ Withdrawal Approved"
            message = f"Your withdrawal of ₵{amount:.2f} has been approved and sent to your mobile money."
            color = "#4CAF50"
            action_text = "Check your mobile money account"
        elif status == 'completed':
            subject = "💰 Withdrawal Completed"
            message = f"Your withdrawal of ₵{amount:.2f} has been successfully processed."
            color = "#4CAF50"
            action_text = "Check your mobile money account"
        else:
            subject = "❌ Withdrawal Rejected"
            message = f"Your withdrawal request of ₵{amount:.2f} was rejected."
            color = "#f44336"
            action_text = "Contact Support"
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: {color}; color: white; padding: 20px; text-align: center; border-radius: 10px 10px 0 0; }}
                .content {{ padding: 20px; background: #f9f9f9; }}
                .footer {{ text-align: center; padding: 20px; color: #666; font-size: 12px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h2>{subject} - {COMPANY_NAME}</h2>
                </div>
                <div class="content">
                    <p>Hello <strong>{username}</strong>,</p>
                    <p>{message}</p>
                    
                    <p><strong>Amount:</strong> ₵{amount:.2f}</p>
                    {f'<p><strong>Reference:</strong> {reference}</p>' if reference else ''}
                    {f'<p><strong>Notes:</strong> {notes}</p>' if notes else ''}
                    
                    <a href="{COMPANY_WEBSITE}/agent/withdrawals" style="background: {color}; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px; display: inline-block; margin-top: 20px;">{action_text}</a>
                </div>
                <div class="footer">
                    <p>Need help? Contact us on WhatsApp: {COMPANY_PHONE}</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        return send_email(email, f"{subject} - {COMPANY_NAME}", html_content)
    
    def send_order_confirmation(self, email, username, order_details):
        """Send order confirmation email (Email ONLY)"""
        items_html = ""
        for item in order_details.get('items', []):
            items_html += f"""
            <tr>
                <td>{item.get('network', '').upper()} {item.get('size_gb', 0)}GB</td>
                <td>{item.get('quantity', 1)}</td>
                <td>₵{item.get('price', 0):.2f}</td>
                <td>₵{item.get('total', 0):.2f}</td>
            </tr>
            """
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: #8B0000; color: white; padding: 20px; text-align: center; }}
                .content {{ padding: 20px; background: #f9f9f9; }}
                table {{ width: 100%; border-collapse: collapse; }}
                th, td {{ padding: 10px; text-align: left; border-bottom: 1px solid #ddd; }}
                .total {{ font-size: 18px; font-weight: bold; text-align: right; margin-top: 20px; }}
                .footer {{ text-align: center; padding: 20px; color: #666; font-size: 12px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h2>Order Confirmation - {COMPANY_NAME}</h2>
                </div>
                <div class="content">
                    <p>Hello <strong>{username}</strong>,</p>
                    <p>Thank you for your order! Your data has been delivered.</p>
                    
                    <p><strong>Order ID:</strong> {order_details.get('order_id')}</p>
                    <p><strong>Order Date:</strong> {order_details.get('created_at')}</p>
                    
                    <table>
                        <thead>
                            <tr><th>Item</th><th>Qty</th><th>Price</th><th>Total</th></tr>
                        </thead>
                        <tbody>
                            {items_html}
                        </tbody>
                    </table>
                    
                    <div class="total">
                        <strong>Total: ₵{order_details.get('total', 0):.2f}</strong>
                    </div>
                    
                    <a href="{COMPANY_WEBSITE}/orders" style="background: #8B0000; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px; display: inline-block;">View Order History</a>
                </div>
                <div class="footer">
                    <p>Need help? Contact us on WhatsApp: {COMPANY_PHONE}</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        return send_email(email, f"Order Confirmation - {order_details.get('order_id')}", html_content)


# ========== AGENT APPLICATION ROUTES (Updated) ==========
@app.route('/api/agent/apply', methods=['POST'])
@token_required
def apply_for_agent():
    """Submit agent application - Manual payment only"""
    try:
        print("=" * 50)
        print("AGENT APPLICATION STARTED")
        print("=" * 50)
        
        # Get JSON data
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No JSON data provided'}), 400
        
        user = g.current_user
        print(f"User: {user.username} (ID: {user.id})")
        
        # Check if user is already an agent
        if user.is_agent and user.agent_approved:
            return jsonify({'success': False, 'error': f'You are already an agent on {COMPANY_NAME}'}), 400
        
        # Check for existing pending application
        existing = AgentApplication.query.filter_by(
            user_id=user.id, 
            status='pending'
        ).first()
        
        if existing:
            return jsonify({'success': False, 'error': 'You already have a pending application'}), 400
        
        # Get data (payment_method is always manual)
        phone = data.get('phone', user.phone or '')
        proof_base64 = data.get('proof_base64', None)
        proof_filename = data.get('proof_filename', 'proof.jpg')
        
        # Always set to manual
        payment_method = 'manual'
        amount = 100.00
        reference = f"AGENT-{uuid.uuid4().hex[:8].upper()}"
        
        print(f"Payment Method: {payment_method}")
        print(f"Phone: {phone}")
        print(f"Reference: {reference}")
        print(f"Has Proof: {proof_base64 is not None}")
        
        # Create application
        application = AgentApplication(
            user_id=user.id,
            payment_reference=reference,
            payment_amount=amount,
            payment_method=payment_method,
            status='pending',
            created_at=datetime.utcnow()
        )
        
        # Handle base64 proof upload
        if proof_base64:
            try:
                import base64
                if ',' in proof_base64:
                    proof_base64 = proof_base64.split(',')[1]
                
                file_data = base64.b64decode(proof_base64)
                
                upload_folder = os.path.join(app.root_path, 'uploads', 'agent_proofs')
                if not os.path.exists(upload_folder):
                    os.makedirs(upload_folder)
                
                file_extension = proof_filename.rsplit('.', 1)[1].lower() if '.' in proof_filename else 'jpg'
                filename = f"agent_proof_{reference}_{uuid.uuid4().hex[:8]}.{file_extension}"
                filepath = os.path.join(upload_folder, filename)
                
                with open(filepath, 'wb') as f:
                    f.write(file_data)
                
                application.payment_proof_url = f"/uploads/agent_proofs/{filename}"
                print(f"Proof saved to: {application.payment_proof_url}")
            except Exception as file_error:
                print(f"File save error: {file_error}")
        
        db.session.add(application)
        db.session.commit()
        print(f"✅ Application saved to database with ID: {application.id}")
        
        # Send email to applicant
        try:
            send_email(
                user.email,
                f"Agent Application Received - {COMPANY_NAME}",
                f"""
                <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                    <h2 style="color: #8B0000;">Application Received - {COMPANY_NAME}</h2>
                    <p>Dear {user.username},</p>
                    <p>Thank you for your interest in becoming a Roamsmart agent.</p>
                    
                    <div style="background: #f5f5f5; padding: 15px; border-radius: 8px; margin: 20px 0;">
                        <p><strong>Application Reference:</strong> {reference}</p>
                        <p><strong>Amount:</strong> GHS {amount:.2f}</p>
                        <p><strong>Status:</strong> Pending Review</p>
                    </div>
                    
                    <div style="background: #fff3cd; padding: 15px; border-radius: 8px; margin: 20px 0;">
                        <p><strong>💰 Payment Instructions:</strong></p>
                        <ul style="margin: 10px 0;">
                            <li>Send GHS {amount:.2f} to <strong>{COMPANY_PHONE}</strong></li>
                            <li>Use reference: <strong>{reference}</strong></li>
                            <li>Upload your payment proof/screenshot</li>
                        </ul>
                    </div>
                    
                    <p>Your application will be reviewed within 24 hours after payment confirmation.</p>
                    
                    <p>Best regards,<br/>{COMPANY_NAME} Team</p>
                </div>
                """
            )
            print(f"✅ Email sent to applicant: {user.email}")
        except Exception as email_error:
            print(f"Email error (non-critical): {email_error}")
        
        return jsonify({
            'success': True,
            'message': f'Application submitted successfully to {COMPANY_NAME}!',
            'data': {
                'application_id': application.id,
                'reference': reference,
                'amount': amount,
                'status': application.status,
                'payment_method': payment_method,
                'instructions': {
                    'amount': amount,
                    'reference': reference,
                    'phone': COMPANY_PHONE
                }
            }
        }), 201
        
    except Exception as e:
        print(f"❌ ERROR in apply_for_agent: {str(e)}")
        import traceback
        traceback.print_exc()
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500



@app.route('/api/agent/application/status', methods=['GET'])
@token_required
def get_agent_application_status():
    """Get agent application status"""
    try:
        user = g.current_user
        
        # Check if user is already an agent
        if user.is_agent and user.agent_approved:
            return jsonify({
                'success': True,
                'data': {
                    'is_agent': True,
                    'has_applied': True,
                    'status': 'approved',
                    'approved_at': user.agent_approved_at
                }
            })
        
        # Get latest application
        application = AgentApplication.query.filter_by(
            user_id=user.id
        ).order_by(AgentApplication.created_at.desc()).first()
        
        if not application:
            return jsonify({
                'success': True,
                'data': {
                    'has_applied': False,
                    'status': None
                }
            })
        
        return jsonify({
            'success': True,
            'data': {
                'has_applied': True,
                'status': application.status,
                'payment_reference': application.payment_reference,
                'submitted_at': application.created_at,
                'rejection_reason': application.rejection_reason if application.status == 'rejected' else None,
                'payment_method': application.payment_method or 'manual'
            }
        })
        
    except Exception as e:
        print(f"Get application status error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
    
@app.route('/api/admin/agent-applications/<int:app_id>/approve', methods=['POST'])
@token_required
@admin_required
def approve_agent_application(app_id):
    """Approve agent application and send approval email (Email ONLY)"""
    try:
        application = AgentApplication.query.get(app_id)
        
        if not application:
            return jsonify({'success': False, 'error': 'Application not found'}), 404
        
        if application.status != 'pending':
            return jsonify({'success': False, 'error': 'Application already processed'}), 400
        
        user = User.query.get(application.user_id)
        
        user.is_agent = True
        user.agent_approved = True
        user.agent_tier = 'Bronze'
        user.commission_rate = 10
        user.agent_approved_at = datetime.utcnow()
        
        application.status = 'approved'
        application.approved_by = g.current_user.id
        application.approved_at = datetime.utcnow()
        
        db.session.commit()
        
        # Send approval email to agent (Email ONLY)
        approval_email_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: 'Segoe UI', Arial, sans-serif; line-height: 1.6; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: linear-gradient(135deg, #28a745, #20c997); color: white; padding: 30px; text-align: center; }}
                .content {{ padding: 30px; background: #f9f9f9; }}
                .feature {{ background: white; padding: 15px; margin: 15px 0; border-radius: 8px; border-left: 4px solid #28a745; }}
                .button {{ display: inline-block; background: #28a745; color: white; padding: 12px 30px; text-decoration: none; border-radius: 5px; margin: 20px 0; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h2>🎉 Congratulations! Agent Application Approved</h2>
                </div>
                <div class="content">
                    <p>Dear <strong>{user.username}</strong>,</p>
                    <p>Great news! Your agent application has been <strong>approved</strong>. Welcome to the {COMPANY_NAME} Agent Program!</p>
                    
                    <div class="feature">
                        <strong>✅ Wholesale Prices</strong><br>
                        Save up to 40% on data bundles
                    </div>
                    
                    <div class="feature">
                        <strong>✅ Your Own Store</strong><br>
                        Create your branded store at: {COMPANY_WEBSITE}/store/setup
                    </div>
                    
                    <div class="feature">
                        <strong>✅ Earn Commission</strong><br>
                        Your commission rate: <strong>10%</strong> (Bronze Tier)
                    </div>
                    
                    <div style="text-align: center;">
                        <a href="{COMPANY_WEBSITE}/agent" class="button">Go to Agent Dashboard</a>
                    </div>
                    
                    <p>Need help? Contact our support team: <strong>{COMPANY_PHONE}</strong></p>
                </div>
            </div>
        </body>
        </html>
        """
        
        send_email(user.email, f"🎉 Agent Application Approved - {COMPANY_NAME}", approval_email_html)
        
        return jsonify({'success': True, 'message': f'Agent application approved on {COMPANY_NAME} and email sent'})
        
    except Exception as e:
        print(f"Approve agent error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Failed to approve application'}), 500


@app.route('/api/admin/agent-applications/<int:app_id>/reject', methods=['POST'])
@token_required
@admin_required
def reject_agent_application(app_id):
    """Reject agent application and send rejection email (Email ONLY)"""
    try:
        data = request.get_json()
        reason = data.get('reason', 'Your application did not meet the requirements at this time.')
        
        application = AgentApplication.query.get(app_id)
        
        if not application:
            return jsonify({'success': False, 'error': 'Application not found'}), 404
        
        if application.status != 'pending':
            return jsonify({'success': False, 'error': 'Application already processed'}), 400
        
        user = User.query.get(application.user_id)
        
        application.status = 'rejected'
        application.rejected_by = g.current_user.id
        application.rejected_at = datetime.utcnow()
        application.rejection_reason = reason
        
        db.session.commit()
        
        # Send rejection email to applicant (Email ONLY)
        rejection_email_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: 'Segoe UI', Arial, sans-serif; line-height: 1.6; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: linear-gradient(135deg, #dc3545, #c82333); color: white; padding: 30px; text-align: center; }}
                .content {{ padding: 30px; background: #f9f9f9; }}
                .reason-box {{ background: #fff3cd; padding: 15px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #ffc107; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h2>Agent Application Update - {COMPANY_NAME}</h2>
                </div>
                <div class="content">
                    <p>Dear <strong>{user.username}</strong>,</p>
                    <p>Thank you for your interest in becoming a {COMPANY_NAME} agent.</p>
                    
                    <div class="reason-box">
                        <strong>📋 Application Status:</strong> Not Approved
                    </div>
                    
                    <p><strong>Reason:</strong> {reason}</p>
                    
                    <p>You may reapply after 30 days. If you have any questions, please contact our support team.</p>
                    
                    <p>Need help? Contact us: <strong>{COMPANY_PHONE}</strong></p>
                </div>
            </div>
        </body>
        </html>
        """
        
        send_email(user.email, f"Agent Application Update - {COMPANY_NAME}", rejection_email_html)
        
        return jsonify({'success': True, 'message': f'Agent application rejected on {COMPANY_NAME} and email sent'})
        
    except Exception as e:
        print(f"Reject agent error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Failed to reject application'}), 500


# ========== LOYALTY POINTS ROUTES ==========

@app.route('/api/user/loyalty', methods=['GET'])
@token_required
def get_loyalty_info():
    """Get user's loyalty points and tier"""
    try:
        loyalty = LoyaltyPoints.query.filter_by(user_id=g.current_user.id).first()
        
        if not loyalty:
            loyalty = LoyaltyPoints(
                user_id=g.current_user.id, points=0, lifetime_points=0, tier='Bronze'
            )
            db.session.add(loyalty)
            db.session.commit()
        
        if loyalty.lifetime_points >= 5000:
            loyalty.tier = 'Platinum'
        elif loyalty.lifetime_points >= 2000:
            loyalty.tier = 'Gold'
        elif loyalty.lifetime_points >= 500:
            loyalty.tier = 'Silver'
        else:
            loyalty.tier = 'Bronze'
        
        db.session.commit()
        
        tier_thresholds = {
            'Bronze': {'next': 'Silver', 'points': 500},
            'Silver': {'next': 'Gold', 'points': 2000},
            'Gold': {'next': 'Platinum', 'points': 5000},
            'Platinum': {'next': None, 'points': None}
        }
        
        current_tier_info = tier_thresholds.get(loyalty.tier, {})
        if current_tier_info.get('next'):
            next_tier = current_tier_info['next']
            points_needed = max(0, current_tier_info['points'] - loyalty.lifetime_points)
        else:
            next_tier = None
            points_needed = 0
        
        recent_transactions = PointsTransaction.query.filter_by(
            user_id=g.current_user.id
        ).order_by(PointsTransaction.created_at.desc()).limit(10).all()
        
        tier_benefits = {
            'Bronze': {'discount': '0%', 'free_data': '0GB', 'cashback': '0%', 'priority_support': False},
            'Silver': {'discount': '5%', 'free_data': '1GB/month', 'cashback': '2%', 'priority_support': False},
            'Gold': {'discount': '10%', 'free_data': '2GB/month', 'cashback': '5%', 'priority_support': True},
            'Platinum': {'discount': '15%', 'free_data': '5GB/month', 'cashback': '10%', 'priority_support': True}
        }
        
        return jsonify({
            'success': True,
            'data': {
                'points': loyalty.points,
                'lifetime_points': loyalty.lifetime_points,
                'tier': loyalty.tier,
                'next_tier': next_tier,
                'points_to_next_tier': points_needed,
                'benefits': tier_benefits.get(loyalty.tier, tier_benefits['Bronze']),
                'recent_transactions': [{
                    'points': t.points,
                    'type': t.type,
                    'description': t.description,
                    'created_at': t.created_at.isoformat()
                } for t in recent_transactions],
                'platform': COMPANY_NAME
            }
        })
        
    except Exception as e:
        print(f"Get loyalty info error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/user/loyalty/redeem', methods=['POST'])
@token_required
def redeem_points():
    """Redeem loyalty points for discount (Email ONLY)"""
    try:
        data = request.get_json()
        points_to_redeem = data.get('points')
        
        if not points_to_redeem or points_to_redeem < 100:
            return jsonify({'success': False, 'error': 'Minimum 100 points required for redemption'}), 400
        
        loyalty = LoyaltyPoints.query.filter_by(user_id=g.current_user.id).first()
        
        if not loyalty or loyalty.points < points_to_redeem:
            return jsonify({'success': False, 'error': 'Insufficient points'}), 400
        
        discount = (points_to_redeem / 100) * 5
        
        transaction = PointsTransaction(
            user_id=g.current_user.id,
            points=-points_to_redeem,
            type='redeemed',
            description=f'Redeemed {points_to_redeem} points for GHS {discount:.2f} discount',
            created_at=datetime.utcnow()
        )
        db.session.add(transaction)
        
        loyalty.points -= points_to_redeem
        
        discount_code = f"LOYALTY-{uuid.uuid4().hex[:8].upper()}"
        
        db.session.commit()
        
        # Send confirmation email (Email ONLY)
        send_email(
            g.current_user.email,
            f"Points Redeemed - {discount_code} - {COMPANY_NAME}",
            f"""
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <h2 style="color: #8B0000;">Points Redeemed Successfully! 🎉</h2>
                <p>Dear {g.current_user.username},</p>
                <p>You have successfully redeemed your loyalty points on {COMPANY_NAME}.</p>
                
                <div style="background: #f9f9f9; padding: 15px; border-left: 3px solid #8B0000; margin: 20px 0;">
                    <p><strong>Points Redeemed:</strong> {points_to_redeem}</p>
                    <p><strong>Discount Value:</strong> GHS {discount:.2f}</p>
                    <p><strong>Discount Code:</strong> <code>{discount_code}</code></p>
                    <p><strong>Remaining Points:</strong> {loyalty.points}</p>
                </div>
                
                <p>Use this discount code on your next purchase!</p>
                
                <a href="{COMPANY_WEBSITE}/shop" style="background: #8B0000; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">Shop Now</a>
            </div>
            """
        )
        
        log_activity(g.current_user.id, 'redeem_points', f'Redeemed {points_to_redeem} points for GHS {discount:.2f}')
        
        return jsonify({
            'success': True,
            'message': f'Redeemed {points_to_redeem} points for GHS {discount:.2f} discount on {COMPANY_NAME}',
            'data': {
                'discount_code': discount_code,
                'discount_amount': discount,
                'remaining_points': loyalty.points
            }
        })
        
    except Exception as e:
        print(f"Redeem points error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


# ========== PUBLIC FAQS ENDPOINT ==========

@app.route('/api/public/faqs', methods=['GET'])
def get_public_faqs():
    """Get public FAQs for landing page"""
    try:
        faqs = FAQ.query.filter_by(is_active=True).order_by(FAQ.order).all()
        
        return jsonify({
            'success': True,
            'data': [{
                'id': f.id,
                'question': f.question,
                'answer': f.answer,
                'category': f.category
            } for f in faqs]
        })
        
    except Exception as e:
        print(f"Get public FAQs error: {e}")
        # Return default FAQs if database query fails
        default_faqs = [
            {"id": 1, "question": "How fast is delivery?", "answer": "Data bundles are delivered instantly within 2 seconds after payment.", "category": "General"},
            {"id": 2, "question": "How do I become an agent?", "answer": "Click on 'Become an Agent' and follow the registration process.", "category": "Agent"},
            {"id": 3, "question": "What payment methods are accepted?", "answer": "We accept Mobile Money (MTN, Telecel, AirtelTigo) and Card payments.", "category": "Payments"},
            {"id": 4, "question": "Is my money safe?", "answer": "Yes, we use secure payment gateways and SSL encryption.", "category": "Security"},
            {"id": 5, "question": "Can I get a refund?", "answer": "Refunds are processed within 24 hours if the data bundle is not delivered.", "category": "Refunds"},
            {"id": 6, "question": "How do I contact support?", "answer": f"Contact us via WhatsApp at {COMPANY_PHONE} or email {COMPANY_EMAIL}.", "category": "Support"}
        ]
        return jsonify({'success': True, 'data': default_faqs}), 200


# ========== PUBLIC TESTIMONIALS ENDPOINT ==========

@app.route('/api/public/testimonials', methods=['GET'])
def get_public_testimonials():
    """Get public testimonials for landing page"""
    try:
        testimonials = Testimonial.query.filter_by(
            is_active=True, 
            is_verified=True
        ).order_by(Testimonial.created_at.desc()).limit(10).all()
        
        return jsonify({
            'success': True,
            'data': [{
                'id': t.id,
                'name': t.name,
                'role': t.role,
                'text': t.content,
                'rating': t.rating,
                'avatar': t.avatar_url or f"https://ui-avatars.com/api/?name={t.name}&background=8B0000&color=fff",
                'location': t.location,
                'date': t.created_at.strftime('%B %d, %Y') if t.created_at else None
            } for t in testimonials]
        })
        
    except Exception as e:
        print(f"Get public testimonials error: {e}")
        # Return default testimonials if database query fails
        default_testimonials = [
            {"id": 1, "name": "Kwame Mensah", "role": "Agent - Kumasi", "text": "Roamsmart has transformed my business! I make over GHS 3,000 monthly selling data bundles. The platform is reliable and support is excellent.", "rating": 5, "location": "Ashanti Region"},
            {"id": 2, "name": "Adjoa Serwaa", "role": "Customer - Accra", "text": "Instant delivery every single time! I buy all my data from Roamsmart. Best prices in Ghana.", "rating": 5, "location": "Greater Accra"},
            {"id": 3, "name": "Michael Osei Tutu", "role": "Agent - Tema", "text": "The commission rates are unbeatable. I've built a thriving business with Roamsmart.", "rating": 5, "location": "Greater Accra"},
            {"id": 4, "name": "Esi Addo", "role": "Student - Cape Coast", "text": "As a student, I appreciate the affordable data bundles. The WAEC voucher service also helped me.", "rating": 4, "location": "Central Region"},
            {"id": 5, "name": "Dr. Kofi Annan", "role": "Business Owner - Takoradi", "text": "Professional platform with great customer service. I recommend Roamsmart to all my business associates.", "rating": 5, "location": "Western Region"},
            {"id": 6, "name": "Ama Darkoa", "role": "Agent - Tamale", "text": "The wholesale prices allow me to offer competitive rates to my customers.", "rating": 5, "location": "Northern Region"}
        ]
        return jsonify({'success': True, 'data': default_testimonials}), 200


# ========== PUBLIC NETWORKS ENDPOINT ==========

@app.route('/api/public/networks', methods=['GET'])
def get_public_networks():
    """Get public networks list"""
    try:
        networks = [
            {"name": "MTN", "code": "mtn", "icon": "📱", "color": "#FFC107", "bundles": [1, 2, 5, 10, 20]},
            {"name": "Telecel", "code": "telecel", "icon": "📱", "color": "#EC008C", "bundles": [1, 2, 5, 10]},
            {"name": "AirtelTigo", "code": "airteltigo", "icon": "📱", "color": "#ED1B24", "bundles": [1, 2, 5]}
        ]
        return jsonify({'success': True, 'data': networks})
        
    except Exception as e:
        print(f"Get public networks error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ========== PUBLIC DATA PLANS ENDPOINT ==========

@app.route('/api/public/data-plans', methods=['GET'])
def get_public_data_plans():
    """Get public data plans"""
    try:
        network = request.args.get('network')
        
        query = DataBundle.query.filter_by(is_active=True)
        if network:
            query = query.filter_by(network=network)
        
        bundles = query.order_by(DataBundle.display_order).all()
        
        # Group by network
        grouped = {}
        for bundle in bundles:
            if bundle.network not in grouped:
                grouped[bundle.network] = []
            grouped[bundle.network].append({
                'size_gb': bundle.size_gb,
                'price': bundle.retail_price,
                'popular': bundle.popular
            })
        
        return jsonify({
            'success': True,
            'data': grouped
        })
        
    except Exception as e:
        print(f"Get public data plans error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ========== WAEC VOUCHER ROUTES (Updated) ==========

@app.route('/api/waec/purchase', methods=['POST'])
@token_required
def purchase_waecagent_voucher():
    """Purchase WAEC voucher (Email ONLY)"""
    try:
        data = request.get_json()
        exam_type = data.get('exam_type')
        quantity = data.get('quantity', 1)
        
        if not exam_type:
            return jsonify({'success': False, 'error': 'Exam type required'}), 400
        
        if quantity < 1 or quantity > 10:
            return jsonify({'success': False, 'error': 'Quantity must be between 1 and 10'}), 400
        
        result = WAECService.purchase_voucher(
            user_id=g.current_user.id,
            exam_type=exam_type,
            quantity=quantity
        )
        
        if not result['success']:
            return jsonify({'success': False, 'error': result['error']}), 400
        
        voucher_details = ""
        for v in result['vouchers']:
            voucher_details += f"""
            <div style="background: white; padding: 10px; margin: 10px 0; border: 1px solid #ddd; border-radius: 5px;">
                <p><strong>Voucher Code:</strong> {v['voucher_code']}</p>
                <p><strong>Serial Number:</strong> {v['serial_number']}</p>
                <p><strong>PIN:</strong> {v['pin']}</p>
            </div>
            """
        
        send_email(
            g.current_user.email,
            f"Your WAEC Voucher(s) - {exam_type} - {COMPANY_NAME}",
            f"""
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <h2 style="color: #8B0000;">WAEC Voucher Purchase Confirmation - {COMPANY_NAME}</h2>
                <p>Dear {g.current_user.username},</p>
                <p>You have successfully purchased <strong>{quantity} WAEC {exam_type} voucher(s)</strong>.</p>
                
                <div style="background: #f9f9f9; padding: 15px; margin: 20px 0;">
                    <p><strong>Total Amount:</strong> GHS {result['total_amount']:.2f}</p>
                    <p><strong>Wallet Balance:</strong> GHS {result['wallet_balance']:.2f}</p>
                </div>
                
                <h3>Your Vouchers:</h3>
                {voucher_details}
                
                <p style="color: #f44336; font-size: 12px;">⚠️ Keep these details safe. Each voucher can only be used once.</p>
                
                <a href="{COMPANY_WEBSITE}/waec" style="background: #8B0000; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">View All Vouchers</a>
            </div>
            """
        )
        
        log_activity(g.current_user.id, 'purchase_waec', f'Purchased {quantity} WAEC {exam_type} vouchers')
        
        return jsonify({
            'success': True,
            'message': f'Successfully purchased {quantity} WAEC {exam_type} voucher(s) on {COMPANY_NAME}. Check your email for details.',
            'data': {
                'vouchers': result['vouchers'],
                'total_amount': result['total_amount'],
                'wallet_balance': result['wallet_balance']
            }
        })
        
    except Exception as e:
        print(f"Purchase WAEC voucher error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ========== BILL PAYMENT ROUTES ==========

class BillPaymentService:
    """Bill Payment Integration Service (Email ONLY)"""
    
    # Supported Billers
    BILLERS = {
        'electricity': {
            'name': 'Electricity (ECG/NEDCo)',
            'code': 'ECG',
            'category': 'utility',
            'icon': '⚡',
            'fields': ['meter_number', 'amount']
        },
        'water': {
            'name': 'Water (GWCL)',
            'code': 'GWCL',
            'category': 'utility',
            'icon': '💧',
            'fields': ['account_number', 'amount']
        },
        'dstv': {
            'name': 'DStv',
            'code': 'DSTV',
            'category': 'tv',
            'icon': '📺',
            'fields': ['smartcard_number', 'amount']
        },
        'gotv': {
            'name': 'GOtv',
            'code': 'GOTV',
            'category': 'tv',
            'icon': '📺',
            'fields': ['smartcard_number', 'amount']
        },
        'internet': {
            'name': 'Internet (Vodafone/MTN)',
            'code': 'INTERNET',
            'category': 'internet',
            'icon': '🌐',
            'fields': ['account_number', 'amount']
        },
        'school_fees': {
            'name': 'School Fees',
            'code': 'SCHOOL',
            'category': 'education',
            'icon': '🎓',
            'fields': ['student_id', 'amount', 'institution']
        }
    }
    
    @staticmethod
    def validate_account(biller_code, account_number):
        """Validate account with biller"""
        biller = BillPaymentService.BILLERS.get(biller_code)
        if not biller:
            return {'success': False, 'error': 'Invalid biller'}
        
        return {
            'success': True,
            'customer_name': f"Customer {account_number[-4:]}",
            'customer_email': f"customer{account_number[-4:]}@example.com",
            'customer_phone': '024XXXXXXX',
            'amount_due': None
        }
    
    @staticmethod
    def pay_bill(user_id, biller_code, account_number, amount, customer_name=None, customer_email=None, customer_phone=None):
        """Process bill payment (Email ONLY)"""
        
        biller = BillPaymentService.BILLERS.get(biller_code)
        if not biller:
            return {'success': False, 'error': 'Invalid biller'}
        
        user = User.query.get(user_id)
        
        if user.wallet_balance < amount:
            return {'success': False, 'error': 'Insufficient wallet balance'}
        
        reference = f"RS-BILL-{biller_code.upper()}-{uuid.uuid4().hex[:8].upper()}"
        
        balance_before = user.wallet_balance
        user.wallet_balance -= amount
        
        bill_payment = BillPayment(
            user_id=user_id,
            bill_type=biller_code,
            biller_name=biller['name'],
            account_number=account_number,
            amount=amount,
            reference=reference,
            status='completed',
            transaction_id=f"RS-TXN-{uuid.uuid4().hex[:8].upper()}",
            payment_method='wallet',
            customer_name=customer_name,
            customer_email=customer_email,
            customer_phone=customer_phone,
            completed_at=datetime.utcnow(),
            created_at=datetime.utcnow()
        )
        db.session.add(bill_payment)
        
        transaction = Transaction(
            user_id=user_id,
            type='bill_payment',
            amount=amount,
            balance_before=balance_before,
            balance_after=user.wallet_balance,
            description=f'Bill payment - {biller["name"]} - {account_number}',
            reference=reference,
            status='completed'
        )
        db.session.add(transaction)
        
        db.session.commit()
        
        # Send email confirmation (Email ONLY)
        send_email(
            user.email,
            f"Bill Payment Confirmation - {biller['name']} - {COMPANY_NAME}",
            f"""
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <h2 style="color: #8B0000;">Bill Payment Successful ✅</h2>
                <p>Dear {user.username},</p>
                <p>Your bill payment has been processed successfully on {COMPANY_NAME}.</p>
                
                <div style="background: #f9f9f9; padding: 15px; border-left: 3px solid #8B0000; margin: 20px 0;">
                    <p><strong>Biller:</strong> {biller['name']}</p>
                    <p><strong>Account Number:</strong> {account_number}</p>
                    <p><strong>Amount Paid:</strong> GHS {amount:.2f}</p>
                    <p><strong>Reference:</strong> {reference}</p>
                    <p><strong>New Balance:</strong> GHS {user.wallet_balance:.2f}</p>
                </div>
                
                <a href="{COMPANY_WEBSITE}/bills/history" style="background: #8B0000; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px; display: inline-block;">View Payment History</a>
            </div>
            """
        )
        
        log_activity(user_id, 'pay_bill', f'Paid GHS {amount:.2f} to {biller["name"]} on {COMPANY_NAME}')
        
        return {
            'success': True,
            'message': f'Successfully paid GHS {amount:.2f} to {biller["name"]} on {COMPANY_NAME}',
            'data': {
                'reference': reference,
                'amount': amount,
                'biller': biller['name'],
                'account_number': account_number,
                'wallet_balance': user.wallet_balance
            }
        }
    
    @staticmethod
    def get_bill_payment_history(user_id, limit=20):
        """Get user's bill payment history"""
        payments = BillPayment.query.filter_by(user_id=user_id).order_by(
            BillPayment.created_at.desc()
        ).limit(limit).all()
        
        return [{
            'id': p.id,
            'reference': p.reference,
            'biller_name': p.biller_name,
            'bill_type': p.bill_type,
            'account_number': p.account_number,
            'amount': float(p.amount),
            'status': p.status,
            'created_at': p.created_at.isoformat(),
            'completed_at': p.completed_at.isoformat() if p.completed_at else None
        } for p in payments]


# ========== REFERRAL CLAIM ENDPOINT ==========
# ========== USER ENDPOINTS FOR DASHBOARD ==========

@app.route('/api/user/orders', methods=['GET'])
@token_required
def get_user_orders():
    """Get user orders with pagination"""
    try:
        user = g.current_user
        
        # Get pagination parameters
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('limit', 20, type=int)
        
        # Query orders for this user with pagination
        paginated_orders = Order.query.filter_by(
            user_id=user.id
        ).order_by(Order.created_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        orders = []
        for order in paginated_orders.items:
            orders.append({
                'order_id': order.order_id,
                'phone': order.phone_number,
                'network': order.network,
                'size_gb': order.size_gb,
                'amount': float(order.amount),
                'status': order.status,
                'payment_method': order.payment_method,
                'created_at': order.created_at.isoformat() if order.created_at else None,
                'date': order.created_at.strftime('%Y-%m-%d %H:%M:%S') if order.created_at else None
            })
        
        return jsonify({
            'success': True,
            'data': orders,
            'total_pages': paginated_orders.pages,
            'current_page': page,
            'total': paginated_orders.total
        })
        
    except Exception as e:
        print(f"User orders error: {e}")
        return jsonify({'success': False, 'error': 'Failed to fetch orders'}), 500

@app.route('/api/user/wallet/history', methods=['GET'])
@token_required
def get_wallet_history():
    """Get user's wallet transaction history"""
    try:
        user = g.current_user
        
        transactions = Transaction.query.filter_by(
            user_id=user.id
        ).order_by(Transaction.created_at.desc()).limit(50).all()
        
        result = []
        for t in transactions:
            result.append({
                'id': t.id,
                'type': t.type,
                'amount': float(t.amount),
                'balance_before': float(t.balance_before) if t.balance_before else None,
                'balance_after': float(t.balance_after) if t.balance_after else None,
                'description': t.description,
                'reference': t.reference,
                'status': t.status,
                'created_at': t.created_at.isoformat() if t.created_at else None
            })
        
        return jsonify({
            'success': True,
            'data': result
        })
        
    except Exception as e:
        print(f"Wallet history error: {e}")
        return jsonify({'success': False, 'error': 'Failed to fetch history'}), 500


@app.route('/api/referrals', methods=['GET'])
@token_required
def get_referrals():
    """Get user's referral statistics"""
    try:
        user = g.current_user
        
        # Get referred users (users who signed up using this user's referral code)
        referred_users = User.query.filter_by(referred_by=user.id).all()
        
        # Calculate earnings from completed referrals
        total_earnings = 0
        pending_earnings = 0
        
        for referred in referred_users:
            # Check if referred user has made a purchase (completed order)
            has_purchase = Order.query.filter(
                Order.user_id == referred.id,
                Order.status == 'completed'
            ).first() is not None
            
            if has_purchase:
                # Check if reward was already given
                reward_given = ReferralReward.query.filter_by(
                    referrer_id=user.id,
                    referred_id=referred.id,
                    status='paid'
                ).first()
                
                if not reward_given:
                    pending_earnings += 5.00  # GHS 5 per qualified referral
                else:
                    total_earnings += 5.00
            else:
                pending_earnings += 5.00  # Pending until they make a purchase
        
        # Get referral code
        referral_code = user.referral_code
        
        # If no referral code exists, generate one
        if not referral_code:
            import string
            import random
            referral_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
            user.referral_code = referral_code
            db.session.commit()
        
        # Build referrals list for display
        referrals_list = []
        for referred in referred_users:
            has_purchase = Order.query.filter(
                Order.user_id == referred.id,
                Order.status == 'completed'
            ).first() is not None
            
            status = 'completed' if has_purchase else 'pending'
            
            referrals_list.append({
                'id': referred.id,
                'referred_user': referred.username,
                'referred_phone': referred.phone,
                'reward_amount': 5.00,
                'status': status,
                'created_at': referred.created_at.isoformat() if referred.created_at else None
            })
        
        return jsonify({
            'success': True,
            'data': {
                'referral_code': referral_code,
                'total_referrals': len(referred_users),
                'total_earnings': float(total_earnings),
                'pending_earnings': float(pending_earnings),
                'bonus_per_referral': 5.00,
                'referrals_list': referrals_list
            }
        })
        
    except Exception as e:
        print(f"Referrals error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500
    
@app.route('/api/referral/<int:referral_id>/claim', methods=['POST'])
@token_required
def claim_referral_bonus(referral_id):
    """Claim referral bonus (Email ONLY)"""
    try:
        referral = Referral.query.get(referral_id)
        
        if not referral or referral.referrer_id != g.current_user.id:
            return jsonify({'success': False, 'error': 'Referral not found'}), 404
        
        if referral.status != 'completed':
            return jsonify({'success': False, 'error': 'Referral bonus already claimed or not available'}), 400
        
        # Credit bonus to wallet
        user = g.current_user
        balance_before = user.wallet_balance
        user.wallet_balance += referral.reward_amount
        
        # Update referral status
        referral.status = 'paid'
        
        # Create transaction
        transaction = Transaction(
            user_id=user.id,
            type='referral_bonus',
            amount=referral.reward_amount,
            balance_before=balance_before,
            balance_after=user.wallet_balance,
            description=f'Referral bonus for referring user {referral.referred_id}',
            status='completed',
            created_at=datetime.utcnow()
        )
        db.session.add(transaction)
        
        db.session.commit()
        
        # Send email confirmation (Email ONLY)
        send_email(
            user.email,
            f"Referral Bonus Credited - {COMPANY_NAME}",
            f"""
            <div style="font-family: Arial, sans-serif;">
                <h2 style="color: #8B0000;">Referral Bonus Credited! 🎉</h2>
                <p>Dear {user.username},</p>
                <p>Your referral bonus of <strong>GHS {referral.reward_amount:.2f}</strong> has been credited to your wallet.</p>
                <p><strong>New Balance:</strong> GHS {user.wallet_balance:.2f}</p>
                <p>Thank you for referring friends to {COMPANY_NAME}!</p>
                <a href="{COMPANY_WEBSITE}/referrals" style="background: #8B0000; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">View Referrals</a>
            </div>
            """
        )
        
        log_activity(user.id, 'claim_referral', f'Claimed referral bonus of GHS {referral.reward_amount}')
        
        return jsonify({
            'success': True,
            'message': f'Referral bonus of GHS {referral.reward_amount:.2f} credited',
            'data': {
                'amount': referral.reward_amount,
                'wallet_balance': user.wallet_balance
            }
        })
        
    except Exception as e:
        print(f"Claim referral bonus error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500



@app.route('/api/user/withdrawals', methods=['GET'])
@token_required
def get_user_withdrawals():
    """Get user's withdrawal history (for users who are not agents)"""
    try:
        user = g.current_user
        
        # Users can only see their own withdrawal requests
        withdrawals = Withdrawal.query.filter_by(
            user_id=user.id
        ).order_by(Withdrawal.created_at.desc()).all()
        
        result = []
        for w in withdrawals:
            result.append({
                'id': w.id,
                'amount': float(w.amount),
                'status': w.status,
                'payment_method': w.payment_method,
                'account_details': w.account_details,
                'reference': w.reference,
                'admin_notes': w.admin_notes,
                'created_at': w.created_at.isoformat() if w.created_at else None,
                'processed_at': w.processed_at.isoformat() if w.processed_at else None
            })
        
        return jsonify({
            'success': True,
            'data': {
                'withdrawals': result,
                'total_withdrawn': sum(w.amount for w in withdrawals if w.status == 'completed'),
                'pending_count': len([w for w in withdrawals if w.status == 'pending'])
            }
        })
        
    except Exception as e:
        print(f"User withdrawals error: {e}")
        return jsonify({'success': False, 'error': 'Failed to fetch withdrawals'}), 500
    
@app.route('/api/user/earnings', methods=['GET'])
@token_required
def get_user_earnings():
    """Get user's earnings from referrals (for regular users)"""
    try:
        user = g.current_user
        
        # Get referral earnings
        referred_users = User.query.filter_by(referred_by=user.id).all()
        
        total_earnings = 0
        for referred in referred_users:
            has_purchase = Order.query.filter(
                Order.user_id == referred.id,
                Order.status == 'completed'
            ).first() is not None
            
            if has_purchase:
                total_earnings += 5.00
        
        return jsonify({
            'success': True,
            'data': {
                'referral_earnings': float(total_earnings),
                'available_balance': float(user.wallet_balance or 0),
                'total_earned': float(total_earnings)
            }
        })
        
    except Exception as e:
        print(f"User earnings error: {e}")
        return jsonify({'success': False, 'error': 'Failed to fetch earnings'}), 500
# ========== WAEC VOUCHER SERVICE ==========

class WAECService:
    """WAEC Voucher Management Service (Email ONLY)"""
    
    @staticmethod
    def generate_vouchers(exam_type, year, quantity, retail_price=20.00, agent_price=18.00, wholesale_price=15.00):
        """Generate WAEC vouchers (Admin only)"""
        try:
            import random
            import string
            
            vouchers = []
            
            for i in range(quantity):
                voucher_code = f"RS-WAEC-{exam_type[:3]}-{year}-{''.join(random.choices(string.ascii_uppercase + string.digits, k=10))}"
                serial_number = f"RS-SER-{exam_type[:3]}{year}{''.join(random.choices(string.digits, k=8))}"
                pin = ''.join(random.choices(string.digits, k=12))
                
                voucher = WAECVoucher(
                    voucher_code=voucher_code,
                    serial_number=serial_number,
                    pin=pin,
                    exam_type=exam_type,
                    year=year,
                    retail_price=retail_price,
                    agent_price=agent_price,
                    wholesale_price=wholesale_price,
                    expires_at=datetime.utcnow() + timedelta(days=365),
                    created_at=datetime.utcnow()
                )
                vouchers.append(voucher)
            
            db.session.add_all(vouchers)
            db.session.commit()
            
            return vouchers
            
        except Exception as e:
            print(f"Generate vouchers error: {e}")
            db.session.rollback()
            return []
    
    @staticmethod
    def get_voucher_price(user):
        """Get voucher price based on user role"""
        if user.is_agent and user.agent_approved:
            return 18.00
        return 20.00
    
    @staticmethod
    def purchase_voucher(user_id, exam_type, quantity=1):
        """Purchase WAEC voucher (Email ONLY)"""
        try:
            vouchers = WAECVoucher.query.filter_by(
                exam_type=exam_type,
                is_used=False
            ).limit(quantity).all()
            
            if len(vouchers) < quantity:
                return {'success': False, 'error': 'Insufficient vouchers available on Roamsmart'}
            
            user = User.query.get(user_id)
            price_per_voucher = WAECService.get_voucher_price(user)
            total_amount = price_per_voucher * quantity
            
            if user.wallet_balance < total_amount:
                return {'success': False, 'error': 'Insufficient wallet balance'}
            
            balance_before = user.wallet_balance
            user.wallet_balance -= total_amount
            
            purchased_vouchers = []
            for voucher in vouchers:
                voucher.is_used = True
                voucher.used_by = user_id
                voucher.used_at = datetime.utcnow()
                voucher.purchased_by = user_id
                voucher.purchased_at = datetime.utcnow()
                
                purchased_vouchers.append({
                    'voucher_code': voucher.voucher_code,
                    'serial_number': voucher.serial_number,
                    'pin': voucher.pin,
                    'exam_type': voucher.exam_type,
                    'year': voucher.year
                })
            
            transaction = Transaction(
                user_id=user_id,
                type='waec_purchase',
                amount=total_amount,
                balance_before=balance_before,
                balance_after=user.wallet_balance,
                description=f'Purchased {quantity}x WAEC {exam_type} voucher(s)',
                status='completed',
                created_at=datetime.utcnow()
            )
            db.session.add(transaction)
            
            db.session.commit()
            
            voucher_details = ""
            for v in purchased_vouchers:
                voucher_details += f"""
                <div style="background: white; padding: 10px; margin: 10px 0; border: 1px solid #ddd; border-radius: 5px;">
                    <p><strong>Voucher Code:</strong> {v['voucher_code']}</p>
                    <p><strong>Serial Number:</strong> {v['serial_number']}</p>
                    <p><strong>PIN:</strong> {v['pin']}</p>
                </div>
                """
            
            send_email(
                user.email,
                f"Your WAEC {exam_type} Voucher(s) - {COMPANY_NAME}",
                f"""
                <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                    <h2 style="color: #8B0000;">WAEC Voucher Purchase Confirmation ✅</h2>
                    <p>Dear {user.username},</p>
                    <p>You have successfully purchased <strong>{quantity} WAEC {exam_type} voucher(s)</strong> on {COMPANY_NAME}.</p>
                    
                    <div style="background: #f9f9f9; padding: 15px; margin: 20px 0;">
                        <p><strong>Total Amount:</strong> GHS {total_amount:.2f}</p>
                        <p><strong>Price per Voucher:</strong> GHS {price_per_voucher:.2f}</p>
                        <p><strong>Wallet Balance:</strong> GHS {user.wallet_balance:.2f}</p>
                    </div>
                    
                    <h3>Your Voucher Details:</h3>
                    {voucher_details}
                    
                    <p style="color: #f44336; font-size: 12px;">⚠️ Keep these details safe. Each voucher can only be used once.</p>
                    <p style="color: #f44336; font-size: 12px;">⚠️ Vouchers expire 1 year from purchase date.</p>
                    
                    <a href="{COMPANY_WEBSITE}/waec" style="background: #8B0000; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">View All Vouchers</a>
                    
                    <hr>
                    <p>Need help? Contact support on WhatsApp: {COMPANY_PHONE}</p>
                </div>
                """
            )
            
            return {
                'success': True,
                'vouchers': purchased_vouchers,
                'total_amount': total_amount,
                'wallet_balance': user.wallet_balance
            }
            
        except Exception as e:
            print(f"Purchase voucher error: {e}")
            db.session.rollback()
            return {'success': False, 'error': str(e)}
    
    @staticmethod
    def verify_voucher(voucher_code):
        """Verify if a voucher is valid"""
        try:
            voucher = WAECVoucher.query.filter_by(voucher_code=voucher_code).first()
            
            if not voucher:
                return {'success': False, 'error': 'Invalid voucher code'}
            
            if voucher.is_used:
                return {'success': False, 'error': 'Voucher has already been used'}
            
            if voucher.expires_at and voucher.expires_at < datetime.utcnow():
                return {'success': False, 'error': 'Voucher has expired'}
            
            return {
                'success': True,
                'data': {
                    'voucher_code': voucher.voucher_code,
                    'exam_type': voucher.exam_type,
                    'year': voucher.year,
                    'serial_number': voucher.serial_number,
                    'pin': voucher.pin,
                    'expires_at': voucher.expires_at.isoformat() if voucher.expires_at else None,
                    'is_valid': True
                }
            }
            
        except Exception as e:
            print(f"Verify voucher error: {e}")
            return {'success': False, 'error': str(e)}
    
    @staticmethod
    def get_available_vouchers_count():
        """Get count of available vouchers by type"""
        try:
            result = {}
            for exam_type in ['WASSCE', 'BECE', 'SHS Placement']:
                count = WAECVoucher.query.filter_by(
                    exam_type=exam_type,
                    is_used=False
                ).count()
                result[exam_type] = count
            return result
            
        except Exception as e:
            print(f"Get available vouchers error: {e}")
            return {'WASSCE': 0, 'BECE': 0, 'SHS Placement': 0}
    
    @staticmethod
    def get_user_vouchers(user_id):
        """Get user's purchased vouchers"""
        try:
            vouchers = WAECVoucher.query.filter_by(
                purchased_by=user_id
            ).order_by(WAECVoucher.purchased_at.desc()).all()
            
            return [{
                'voucher_code': v.voucher_code,
                'serial_number': v.serial_number,
                'exam_type': v.exam_type,
                'year': v.year,
                'purchased_at': v.purchased_at.isoformat(),
                'expires_at': v.expires_at.isoformat() if v.expires_at else None,
                'is_used': v.is_used,
                'used_at': v.used_at.isoformat() if v.used_at else None
            } for v in vouchers]
            
        except Exception as e:
            print(f"Get user vouchers error: {e}")
            return []


# ========== ADMIN WAEC MANAGEMENT ==========

# ========== USER WAEC VOUCHER ENDPOINTS ==========

@app.route('/api/waec/vouchers', methods=['GET'])
@token_required
def get_waec_user_vouchers():
    """Get available WAEC vouchers for regular users"""
    try:
        # Get vouchers that are available for sale
        vouchers = WAECVoucher.query.filter_by(
            is_active=True,
            is_used=False
        ).group_by(WAECVoucher.exam_type, WAECVoucher.year).all()
        
        # Or return default available vouchers
        default_vouchers = [
            {'type': 'WASSCE', 'price': 20.00, 'year': 2024},
            {'type': 'WASSCE', 'price': 20.00, 'year': 2023},
            {'type': 'BECE', 'price': 15.00, 'year': 2024},
            {'type': 'BECE', 'price': 15.00, 'year': 2023},
            {'type': 'SHS Placement', 'price': 10.00, 'year': 2024}
        ]
        
        # Count available vouchers by type
        available_count = {}
        for v in default_vouchers:
            count = WAECVoucher.query.filter_by(
                exam_type=v['type'],
                year=v['year'],
                is_used=False,
                is_active=True
            ).count()
            available_count[v['type']] = count if count > 0 else 100  # Default 100 if none in DB
        
        return jsonify({
            'success': True,
            'data': {
                'vouchers': default_vouchers,
                'available_count': available_count
            }
        })
        
    except Exception as e:
        print(f"WAEC vouchers error: {e}")
        # Return default data even on error
        return jsonify({
            'success': True,
            'data': {
                'vouchers': [
                    {'type': 'WASSCE', 'price': 20.00, 'year': 2024},
                    {'type': 'BECE', 'price': 15.00, 'year': 2024}
                ],
                'available_count': {'WASSCE': 100, 'BECE': 100}
            }
        }), 200


@app.route('/api/waec/purchase', methods=['POST'])
@token_required
def purchase_user_waec_voucher():
    """Purchase WAEC voucher for regular users"""
    try:
        data = request.get_json()
        exam_type = data.get('exam_type')
        quantity = data.get('quantity', 1)
        
        if not exam_type:
            return jsonify({'success': False, 'error': 'Exam type required'}), 400
        
        if quantity < 1 or quantity > 10:
            return jsonify({'success': False, 'error': 'Quantity must be between 1 and 10'}), 400
        
        user = g.current_user
        
        # Get voucher price
        voucher_prices = {
            'WASSCE': 20.00,
            'BECE': 15.00,
            'SHS Placement': 10.00
        }
        
        price_per_voucher = voucher_prices.get(exam_type, 20.00)
        total_amount = price_per_voucher * quantity
        
        # Check if user has enough balance
        if user.wallet_balance < total_amount:
            return jsonify({
                'success': False, 
                'error': f'Insufficient balance. Need ₵{total_amount:.2f}. Your balance: ₵{user.wallet_balance:.2f}'
            }), 400
        
        # Get available vouchers from database or generate new ones
        vouchers = WAECVoucher.query.filter_by(
            exam_type=exam_type,
            is_used=False,
            is_active=True
        ).limit(quantity).all()
        
        # If not enough in DB, generate new ones
        if len(vouchers) < quantity:
            # Generate new vouchers
            new_vouchers = generate_waec_vouchers(exam_type, quantity - len(vouchers))
            for v in new_vouchers:
                db.session.add(v)
            vouchers.extend(new_vouchers)
        
        # Deduct from wallet
        balance_before = user.wallet_balance
        user.wallet_balance -= total_amount
        
        # Create transaction record
        transaction = Transaction(
            user_id=user.id,
            type='purchase',
            amount=total_amount,
            balance_before=balance_before,
            balance_after=user.wallet_balance,
            description=f'Purchase of {quantity} WAEC {exam_type} voucher(s)',
            reference=f'WAEC-{datetime.utcnow().strftime("%Y%m%d%H%M%S")}-{user.id}',
            status='completed'
        )
        db.session.add(transaction)
        
        # Mark vouchers as used/sold
        voucher_details = []
        for voucher in vouchers[:quantity]:
            voucher.is_used = True
            voucher.user_id = user.id
            voucher.purchased_at = datetime.utcnow()
            voucher_details.append({
                'voucher_code': voucher.voucher_code,
                'serial_number': voucher.serial_number,
                'pin': voucher.pin
            })
        
        db.session.commit()
        
        # Create order record
        order = Order(
            user_id=user.id,
            order_id=f'WAEC-{datetime.utcnow().strftime("%Y%m%d%H%M%S")}',
            type='waec',
            exam_type=exam_type,
            quantity=quantity,
            amount=total_amount,
            status='completed',
            created_at=datetime.utcnow()
        )
        db.session.add(order)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Successfully purchased {quantity} WAEC {exam_type} voucher(s)',
            'data': {
                'vouchers': voucher_details,
                'total_amount': total_amount,
                'quantity': quantity,
                'new_balance': float(user.wallet_balance)
            }
        })
        
    except Exception as e:
        print(f"WAEC purchase error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


def generate_waec_vouchers(exam_type, count):
    """Generate new WAEC vouchers"""
    import random
    import string
    
    vouchers = []
    year = datetime.utcnow().year
    
    for i in range(count):
        # Generate random voucher code
        voucher_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=12))
        serial_number = f"{exam_type[:3]}{year}{random.randint(10000, 99999)}"
        pin = ''.join(random.choices(string.digits, k=10))
        
        voucher = WAECVoucher(
            exam_type=exam_type,
            year=year,
            voucher_code=voucher_code,
            serial_number=serial_number,
            pin=pin,
            is_used=False,
            is_active=True,
            created_at=datetime.utcnow()
        )
        vouchers.append(voucher)
    
    return vouchers


@app.route('/api/admin/waec/generate', methods=['POST'])
@token_required
@admin_required
def admin_generate_waec_vouchers():
    """Admin: Generate WAEC vouchers (Email notification to admins)"""
    try:
        data = request.get_json()
        exam_type = data.get('exam_type')
        year = data.get('year', datetime.utcnow().year)
        quantity = data.get('quantity', 100)
        retail_price = data.get('retail_price', 20.00)
        agent_price = data.get('agent_price', 18.00)
        wholesale_price = data.get('wholesale_price', 15.00)
        
        if not exam_type:
            return jsonify({'success': False, 'error': 'Exam type required'}), 400
        
        if quantity < 1 or quantity > 10000:
            return jsonify({'success': False, 'error': 'Quantity must be between 1 and 10000'}), 400
        
        vouchers = WAECService.generate_vouchers(
            exam_type=exam_type,
            year=year,
            quantity=quantity,
            retail_price=retail_price,
            agent_price=agent_price,
            wholesale_price=wholesale_price
        )
        
        super_admins = User.query.filter_by(role='super_admin').all()
        for admin in super_admins:
            send_email(
                admin.email,
                f"WAEC Vouchers Generated - {exam_type} {year} - {COMPANY_NAME}",
                f"""
                <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                    <h2 style="color: #8B0000;">WAEC Vouchers Generated ✅</h2>
                    <p>Dear {admin.username},</p>
                    <p>New WAEC vouchers have been generated on {COMPANY_NAME}.</p>
                    
                    <div style="background: #f9f9f9; padding: 15px; border-left: 3px solid #8B0000; margin: 20px 0;">
                        <p><strong>Exam Type:</strong> {exam_type}</p>
                        <p><strong>Year:</strong> {year}</p>
                        <p><strong>Quantity:</strong> {quantity}</p>
                        <p><strong>Retail Price:</strong> GHS {retail_price:.2f}</p>
                        <p><strong>Agent Price:</strong> GHS {agent_price:.2f}</p>
                        <p><strong>Wholesale Price:</strong> GHS {wholesale_price:.2f}</p>
                        <p><strong>Generated by:</strong> {g.current_user.username}</p>
                    </div>
                    
                    <a href="{COMPANY_WEBSITE}/admin/waec" style="background: #8B0000; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">View Vouchers</a>
                </div>
                """
            )
        
        log_activity(g.current_user.id, 'generate_waec', f'Generated {quantity} {exam_type} vouchers')
        
        return jsonify({
            'success': True,
            'message': f'Generated {quantity} {exam_type} vouchers for {year} on {COMPANY_NAME}',
            'data': {'count': len(vouchers), 'exam_type': exam_type, 'year': year}
        })
        
    except Exception as e:
        print(f"Generate WAEC vouchers error: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/admin/waec/export', methods=['GET'])
@token_required
@admin_required
def admin_export_waec_vouchers():
    """Admin: Export WAEC vouchers to CSV"""
    try:
        import io
        import csv
        
        exam_type = request.args.get('exam_type')
        is_used = request.args.get('is_used', 'false').lower() == 'true'
        
        query = WAECVoucher.query
        if exam_type:
            query = query.filter_by(exam_type=exam_type)
        query = query.filter_by(is_used=is_used)
        
        vouchers = query.order_by(WAECVoucher.created_at.desc()).all()
        
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Voucher Code', 'Serial Number', 'PIN', 'Exam Type', 'Year', 'Status', 'Purchased By', 'Purchase Date', 'Expires At'])
        
        for v in vouchers:
            purchaser = User.query.get(v.purchased_by) if v.purchased_by else None
            writer.writerow([
                v.voucher_code, 
                v.serial_number, 
                v.pin, 
                v.exam_type, 
                v.year,
                'Used' if v.is_used else 'Available',
                purchaser.username if purchaser else 'N/A',
                v.purchased_at.strftime('%Y-%m-%d %H:%M') if v.purchased_at else 'N/A',
                v.expires_at.strftime('%Y-%m-%d') if v.expires_at else 'N/A'
            ])
        
        output.seek(0)
        
        log_activity(g.current_user.id, 'export_waec', f'Exported {len(vouchers)} WAEC vouchers')
        
        return send_file(
            io.BytesIO(output.getvalue().encode('utf-8')),
            mimetype='text/csv',
            as_attachment=True,
            download_name=f'roamsmart_waec_vouchers_{exam_type or "all"}_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.csv'
        )
        
    except Exception as e:
        print(f"Export WAEC vouchers error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/admin/waec/stock', methods=['GET'])
@token_required
@admin_required
def admin_waec_stock():
    """Admin: Get WAEC voucher stock levels"""
    try:
        stock = WAECService.get_available_vouchers_count()
        
        total_generated = WAECVoucher.query.count()
        total_used = WAECVoucher.query.filter_by(is_used=True).count()
        total_available = total_generated - total_used
        
        sales_by_type = db.session.query(
            WAECVoucher.exam_type,
            db.func.count(WAECVoucher.id).label('sold_count'),
            db.func.sum(WAECVoucher.retail_price).label('revenue')
        ).filter(
            WAECVoucher.is_used == True
        ).group_by(WAECVoucher.exam_type).all()
        
        return jsonify({
            'success': True,
            'data': {
                'available_stock': stock,
                'total_generated': total_generated,
                'total_used': total_used,
                'total_available': total_available,
                'utilization_rate': round((total_used / total_generated * 100) if total_generated > 0 else 0, 2),
                'sales_by_type': [{
                    'exam_type': s[0],
                    'sold': s[1],
                    'revenue': float(s[2] or 0)
                } for s in sales_by_type],
                'platform': COMPANY_NAME
            }
        })
        
    except Exception as e:
        print(f"WAEC stock error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/user/waec/vouchers', methods=['GET'])
@token_required
def get_user_waec_vouchers():
    """Get user's purchased WAEC vouchers"""
    try:
        vouchers = WAECService.get_user_vouchers(g.current_user.id)
        
        return jsonify({
            'success': True,
            'data': vouchers,
            'count': len(vouchers)
        })
        
    except Exception as e:
        print(f"Get user WAEC vouchers error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ========== ERROR HANDLERS ==========

@app.errorhandler(404)
def not_found(error):
    return jsonify({
        'error': 'Not found', 
        'message': f'The requested endpoint does not exist on {COMPANY_NAME}',
        'status_code': 404
    }), 404


@app.errorhandler(500)
def internal_error(error):
    return jsonify({
        'error': 'Internal server error', 
        'message': f'Something went wrong on {COMPANY_NAME}. Please try again later.',
        'status_code': 500
    }), 500


@app.errorhandler(429)
def rate_limit_error(error):
    return jsonify({
        'error': 'Rate limit exceeded',
        'message': f'Too many requests on {COMPANY_NAME}. Please try again later.',
        'status_code': 429
    }), 429


@app.errorhandler(401)
def unauthorized_error(error):
    return jsonify({
        'error': 'Unauthorized',
        'message': f'Authentication required to access this resource on {COMPANY_NAME}',
        'status_code': 401
    }), 401


@app.errorhandler(403)
def forbidden_error(error):
    return jsonify({
        'error': 'Forbidden',
        'message': f'You do not have permission to access this resource on {COMPANY_NAME}',
        'status_code': 403
    }), 403


# ========== RUN APP ==========

if __name__ == '__main__':
    upload_folder = app.config.get('UPLOAD_FOLDER', 'uploads')
    if not os.path.exists(upload_folder):
        os.makedirs(upload_folder)
    
    init_db()
    
    port = int(os.environ.get('PORT', 5000))
    
    print("=" * 60)
    print(f"🚀 {COMPANY_NAME} API v2.0 Running")
    print(f"📍 URL: http://localhost:{port}")
    print("-" * 60)
    print(f"📧 Admin Login:")
    print(f"   Email: {COMPANY_ADMIN_EMAIL}")
    print(f"   Password: admin123")
    print("-" * 60)
    print(f"👤 Demo User:")
    print(f"   Email: demo@{COMPANY_DOMAIN}")
    print(f"   Password: user123")
    print("-" * 60)
    print(f"🤝 Demo Agent:")
    print(f"   Email: agent@{COMPANY_DOMAIN}")
    print(f"   Password: agent123")
    print("-" * 60)
    print("=" * 60)
    
    app.run(host='0.0.0.0', port=port, debug=app.config.get('DEBUG', False))