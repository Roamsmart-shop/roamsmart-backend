# config.py
import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()

# Company Configuration
COMPANY_NAME = "Roamsmart Digital Service"
COMPANY_SHORT = "Roamsmart"
COMPANY_EMAIL = "support@roamsmart.shop"
COMPANY_ADMIN_EMAIL = "admin@roamsmart.shop"
COMPANY_PHONE = "0557388622"
COMPANY_WEBSITE = "https://roamsmart.shop"
COMPANY_DOMAIN = "roamsmart.shop"

class Config:
    # Core
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
    FLASK_ENV = os.environ.get('FLASK_ENV', 'development')
    APP_NAME = os.environ.get('APP_NAME', COMPANY_NAME)
    
    # Database - Default to SQLite for development
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', 'sqlite:///roamsmart_local.db')
    
    # Database Pool Settings (Production)
    SQLALCHEMY_POOL_SIZE = int(os.environ.get('SQLALCHEMY_POOL_SIZE', 10))
    SQLALCHEMY_MAX_OVERFLOW = int(os.environ.get('SQLALCHEMY_MAX_OVERFLOW', 20))
    SQLALCHEMY_POOL_TIMEOUT = int(os.environ.get('SQLALCHEMY_POOL_TIMEOUT', 30))
    SQLALCHEMY_POOL_RECYCLE = 3600
    
    # JWT Settings
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY', SECRET_KEY)
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(days=7) if os.environ.get('FLASK_ENV') == 'development' else timedelta(hours=int(os.environ.get('JWT_ACCESS_TOKEN_EXPIRES', 1)))
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=int(os.environ.get('JWT_REFRESH_TOKEN_EXPIRES', 7)))
    
    # Rate Limiting
    RATELIMIT_DEFAULT = os.environ.get('RATELIMIT_DEFAULT', "100 per hour")
    RATELIMIT_LOGIN = os.environ.get('RATELIMIT_LOGIN', "5 per minute")
    RATELIMIT_ORDER = os.environ.get('RATELIMIT_ORDER', "10 per minute")
    RATELIMIT_WITHDRAWAL = os.environ.get('RATELIMIT_WITHDRAWAL', "3 per minute")
    RATELIMIT_REFERRAL = os.environ.get('RATELIMIT_REFERRAL', "5 per minute")
    RATELIMIT_STORAGE_URL = os.environ.get('RATELIMIT_STORAGE_URL', "memory://")
    RATELIMIT_ENABLED = os.environ.get('RATELIMIT_ENABLED', 'false').lower() == 'true'
    
    # Upload
    UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER', 'uploads')
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB
    
    # Africa's Talking (SMS Verification)
    AFRICASTALKING_API_KEY = os.environ.get('AFRICASTALKING_API_KEY')
    AFRICASTALKING_USERNAME = os.environ.get('AFRICASTALKING_USERNAME', 'sandbox')
    AFRICASTALKING_SENDER_ID = os.environ.get('AFRICASTALKING_SENDER_ID', COMPANY_SHORT)
    
    # Paystack
    PAYSTACK_SECRET_KEY = os.environ.get('PAYSTACK_SECRET_KEY')
    PAYSTACK_PUBLIC_KEY = os.environ.get('PAYSTACK_PUBLIC_KEY')
    
    # MTN MoMo
    MTN_MOMO_BASE_URL = os.environ.get('MTN_MOMO_BASE_URL')
    MTN_MOMO_API_USER = os.environ.get('MTN_MOMO_API_USER')
    MTN_MOMO_API_KEY = os.environ.get('MTN_MOMO_API_KEY')
    MTN_MOMO_SUBSCRIPTION_KEY = os.environ.get('MTN_MOMO_SUBSCRIPTION_KEY')
    MTN_MOMO_ENVIRONMENT = os.environ.get('MTN_MOMO_ENVIRONMENT', 'sandbox')
    
    # Email SMTP
    SMTP_SERVER = os.environ.get('SMTP_SERVER', 'smtp.gmail.com')
    SMTP_PORT = int(os.environ.get('SMTP_PORT', 465))
    SMTP_USERNAME = os.environ.get('SMTP_USERNAME')
    SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD')
    FROM_EMAIL = os.environ.get('FROM_EMAIL', COMPANY_ADMIN_EMAIL)
    FROM_NAME = os.environ.get('FROM_NAME', COMPANY_NAME)
    
    # SendGrid (Optional)
    SENDGRID_API_KEY = os.environ.get('SENDGRID_API_KEY')
    SENDGRID_AGENT_WELCOME_TEMPLATE = os.environ.get('SENDGRID_AGENT_WELCOME_TEMPLATE')
    
    # Network Provider APIs
    MTN_API_KEY = os.environ.get('MTN_API_KEY')
    MTN_API_SECRET = os.environ.get('MTN_API_SECRET')
    MTN_API_ENDPOINT = os.environ.get('MTN_API_ENDPOINT')
    
    TELECEL_API_KEY = os.environ.get('TELECEL_API_KEY')
    TELECEL_API_SECRET = os.environ.get('TELECEL_API_SECRET')
    TELECEL_API_ENDPOINT = os.environ.get('TELECEL_API_ENDPOINT')
    
    AIRTELTIGO_API_KEY = os.environ.get('AIRTELTIGO_API_KEY')
    AIRTELTIGO_API_SECRET = os.environ.get('AIRTELTIGO_API_SECRET')
    AIRTELTIGO_API_ENDPOINT = os.environ.get('AIRTELTIGO_API_ENDPOINT')
    
    # Support
    SUPPORT_PHONE = os.environ.get('SUPPORT_PHONE', COMPANY_PHONE)
    SUPPORT_EMAIL = os.environ.get('SUPPORT_EMAIL', COMPANY_EMAIL)
    SUPPORT_WHATSAPP = os.environ.get('SUPPORT_WHATSAPP', '233557388622')
    
    # Site
    SITE_NAME = os.environ.get('SITE_NAME', COMPANY_NAME)
    SITE_URL = os.environ.get('SITE_URL', 'http://localhost:5000')
    FRONTEND_URL = os.environ.get('FRONTEND_URL', 'http://localhost:3000')
    BACKEND_URL = os.environ.get('BACKEND_URL', 'http://localhost:5000')
    
    # Agent Configuration
    AGENT_REGISTRATION_FEE = int(os.environ.get('AGENT_REGISTRATION_FEE', 100))
    MIN_WITHDRAWAL_AMOUNT = int(os.environ.get('MIN_WITHDRAWAL_AMOUNT', 50))
    MAX_WITHDRAWAL_AMOUNT = int(os.environ.get('MAX_WITHDRAWAL_AMOUNT', 10000))
    
    # Commission Rates
    COMMISSION_RATES = {
        'bronze': int(os.environ.get('BRONZE_COMMISSION', 10)),
        'silver': int(os.environ.get('SILVER_COMMISSION', 15)),
        'gold': int(os.environ.get('GOLD_COMMISSION', 20)),
        'platinum': int(os.environ.get('PLATINUM_COMMISSION', 25))
    }
    
    # Referral
    REFERRAL_BONUS = int(os.environ.get('REFERRAL_BONUS_AMOUNT', 5))
    
    # Feature Flags
    ENABLE_WHATSAPP_BOT = os.environ.get('ENABLE_WHATSAPP_BOT', 'false').lower() == 'true'
    ENABLE_AFA_REGISTRATION = os.environ.get('ENABLE_AFA_REGISTRATION', 'true').lower() == 'true'
    ENABLE_WAEC_VOUCHERS = os.environ.get('ENABLE_WAEC_VOUCHERS', 'true').lower() == 'true'
    ENABLE_BILL_PAYMENTS = os.environ.get('ENABLE_BILL_PAYMENTS', 'true').lower() == 'true'
    
    # CORS
    CORS_ORIGINS = os.environ.get('CORS_ORIGINS', 'http://localhost:3000,http://localhost:5000').split(',')
    CORS_ALLOW_CREDENTIALS = os.environ.get('CORS_ALLOW_CREDENTIALS', 'true').lower() == 'true'
    
    # Mock API for testing
    MOCK_API = os.environ.get('MOCK_API', 'true').lower() == 'true'
    
    # Dynamic Pricing Configuration
    MIN_DATA_SIZE = int(os.environ.get('MIN_DATA_SIZE', 1))
    MAX_DATA_SIZE = int(os.environ.get('MAX_DATA_SIZE', 100))
    
    # Base rates per GB (fallback only if not in database)
    BASE_USER_RATES = {
        'mtn': float(os.environ.get('MTN_BASE_USER_RATE', 6.00)),
        'telecel': float(os.environ.get('TELECEL_BASE_USER_RATE', 5.50)),
        'airteltigo': float(os.environ.get('AIRTELTIGO_BASE_USER_RATE', 5.50))
    }
    
    BASE_AGENT_RATES = {
        'mtn': float(os.environ.get('MTN_BASE_AGENT_RATE', 5.00)),
        'telecel': float(os.environ.get('TELECEL_BASE_AGENT_RATE', 4.50)),
        'airteltigo': float(os.environ.get('AIRTELTIGO_BASE_AGENT_RATE', 4.50))
    }
    
    # Volume discounts (percentage off)
    VOLUME_DISCOUNTS = {
        10: int(os.environ.get('VOLUME_DISCOUNT_10GB', 5)),
        20: int(os.environ.get('VOLUME_DISCOUNT_20GB', 10)),
        50: int(os.environ.get('VOLUME_DISCOUNT_50GB', 15)),
        100: int(os.environ.get('VOLUME_DISCOUNT_100GB', 20))
    }
    
    # Order Settings
    MAX_ORDER_QUANTITY = int(os.environ.get('MAX_ORDER_QUANTITY', 10))
    ORDER_TIMEOUT_MINUTES = int(os.environ.get('ORDER_TIMEOUT_MINUTES', 30))
    
    # Price Cache Settings
    PRICE_CACHE_TTL = int(os.environ.get('PRICE_CACHE_TTL', 3600))
    ENABLE_PRICE_CACHE = os.environ.get('ENABLE_PRICE_CACHE', 'true').lower() == 'true'
    
    # Admin Password (for initialization)
    ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'Roamsmart123@$')


class DevelopmentConfig(Config):
    DEBUG = True
    TESTING = True
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', 'sqlite:///roamsmart_dev.db')
    MOCK_API = True
    RATELIMIT_ENABLED = False
    ENABLE_PRICE_CACHE = False


class ProductionConfig(Config):
    DEBUG = False
    TESTING = False
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL')
    MOCK_API = False
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    REMEMBER_COOKIE_SECURE = True
    REMEMBER_COOKIE_HTTPONLY = True
    RATELIMIT_ENABLED = True
    ENABLE_PRICE_CACHE = True
    
    # Stronger security for production
    SESSION_COOKIE_DOMAIN = os.environ.get('SESSION_COOKIE_DOMAIN', '.roamsmart.shop')
    PREFERRED_URL_SCHEME = 'https'


class TestingConfig(Config):
    TESTING = True
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    MOCK_API = True
    RATELIMIT_ENABLED = False
    ENABLE_PRICE_CACHE = False
    WTF_CSRF_ENABLED = False


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}