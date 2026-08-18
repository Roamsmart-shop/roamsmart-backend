# models.py
from datetime import datetime, timedelta
import jwt
import bcrypt
import uuid
from flask_sqlalchemy import SQLAlchemy
from flask import current_app

db = SQLAlchemy()


COMPANY_NAME = "AFDALNOVA Digital Service"
COMPANY_SHORT = "AFDALNOVA"
COMPANY_TAGLINE = "Innovation Meets Excellence"
COMPANY_EMAIL = "support@abigalisticstudious.com"
COMPANY_PHONE = "0548247241"
COMPANY_PHONE_2 = "0599874865"
COMPANY_WHATSAPP = "233599874865"
COMPANY_WEBSITE = "https://abigalisticstudious.com"
COMPANY_DOMAIN = "abigalisticstudious.com"
 

class Platform(db.Model):
    __tablename__ = 'platforms'
    
    id = db.Column(db.Integer, primary_key=True)
    platform_key = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    domain = db.Column(db.String(255))
    
    # Payment Configuration
    paystack_public_key = db.Column(db.String(255))
    paystack_secret_key = db.Column(db.String(255))
    paystack_webhook_secret = db.Column(db.String(255))
    callback_url = db.Column(db.String(500))
    webhook_url = db.Column(db.String(500))
    
    # Branding
    brand_name = db.Column(db.String(100))
    brand_tagline = db.Column(db.String(200))
    brand_logo = db.Column(db.String(500))
    brand_color = db.Column(db.String(20))
    brand_primary_color = db.Column(db.String(20))
    brand_secondary_color = db.Column(db.String(20))
    
    # Contact Info
    support_email = db.Column(db.String(120))
    support_phone = db.Column(db.String(20))
    support_phone_2 = db.Column(db.String(20))
    whatsapp = db.Column(db.String(20))
    
    # Status
    is_active = db.Column(db.Boolean, default=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    users = db.relationship('User', backref='platform_ref', lazy=True)
    
    def to_dict(self):
        return {
            'id': self.id,
            'platform_key': self.platform_key,
            'name': self.name,
            'domain': self.domain,
            'brand_name': self.brand_name,
            'brand_tagline': self.brand_tagline,
            'brand_logo': self.brand_logo,
            'brand_color': self.brand_color,
            'support_email': self.support_email,
            'support_phone': self.support_phone,
            'support_phone_2': self.support_phone_2,
            'whatsapp': self.whatsapp,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class User(db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    phone = db.Column(db.String(20), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    
    # ========== PLATFORM SUPPORT ==========
    platform = db.Column(db.String(20), default='platform_a')
    platform_created = db.Column(db.String(20), default='platform_a')
    platform_id = db.Column(db.Integer, db.ForeignKey('platforms.id'), nullable=True)
    
    # Role & Status
    role = db.Column(db.String(20), default='user')
    is_agent = db.Column(db.Boolean, default=False)
    agent_approved = db.Column(db.Boolean, default=False)
    agent_tier = db.Column(db.String(20), default='Bronze')
    commission_rate = db.Column(db.Integer, default=10)
    is_suspended = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    is_super_admin = db.Column(db.Boolean, default=False)  # ✅ ADDED
    
    # Security Fields
    failed_login_attempts = db.Column(db.Integer, default=0)
    locked_until = db.Column(db.DateTime, nullable=True)
    last_ip_address = db.Column(db.String(45), nullable=True)
    account_created_ip = db.Column(db.String(45), nullable=True)
    
    # Wallet
    wallet_balance = db.Column(db.Float, default=0.0)
    
    # ========== POINTS SYSTEM ==========  # ✅ ADDED
    points_balance = db.Column(db.Integer, default=0)
    total_points_earned = db.Column(db.Integer, default=0)
    total_points_redeemed = db.Column(db.Integer, default=0)
    
    # Verification
    email_verified = db.Column(db.Boolean, default=False)
    phone_verified = db.Column(db.Boolean, default=False)
    two_factor_enabled = db.Column(db.Boolean, default=False)
    two_factor_secret = db.Column(db.String(200), nullable=True)
    
    # Referral
    referral_code = db.Column(db.String(20), unique=True)
    referred_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    
    # Profile
    full_name = db.Column(db.String(100), nullable=True)
    avatar_url = db.Column(db.String(500), nullable=True)
    
    # KYC
    kyc_verified = db.Column(db.Boolean, default=False)
    total_sales = db.Column(db.Float, default=0.0)
    total_commission = db.Column(db.Float, default=0.0)
    today_sales = db.Column(db.Float, default=0.0)
    this_week_sales = db.Column(db.Float, default=0.0)
    this_month_sales = db.Column(db.Float, default=0.0)
    total_customers = db.Column(db.Integer, default=0)
    
    # Timestamps
    last_login = db.Column(db.DateTime, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    email_verification_token = db.Column(db.String(500), nullable=True)
    email_verification_sent_at = db.Column(db.DateTime, nullable=True)
    email_verified_at = db.Column(db.DateTime, nullable=True)
    referral_data_balance = db.Column(db.Float, default=0.0)
    redeemed_referral_data = db.Column(db.Float, default=0.0)
    reset_token = db.Column(db.String(255), nullable=True)
    reset_token_expiry = db.Column(db.DateTime, nullable=True)
    wholesale_price = db.Column(db.Numeric(10, 2), default=0)
    profit = db.Column(db.Numeric(10, 2), default=0)
    commission_amount = db.Column(db.Numeric(10, 2), default=0)
    
    # Relationships
    transactions = db.relationship('Transaction', backref='user', lazy=True)
    agent_requests = db.relationship('AgentRequest', backref='user', lazy=True)
    manual_payments = db.relationship('ManualPayment', backref='user', lazy=True)
    notifications = db.relationship('Notification', backref='user', lazy=True)
    store = db.relationship('Store', backref='agent', uselist=False, lazy=True)
    store_clients = db.relationship('StoreClient', backref='agent', lazy=True)
    referrals_given = db.relationship('Referral', foreign_keys='Referral.referrer_id', backref='referrer', lazy=True)
    referrals_received = db.relationship('Referral', foreign_keys='Referral.referred_id', backref='referred', lazy=True)
    sessions = db.relationship('UserSession', backref='user', lazy=True)
    points_transactions = db.relationship('PointsTransaction', backref='user', lazy=True)
    points_redemptions = db.relationship('PointsRedemption', backref='user', lazy=True)
    
    # ✅ Use back_populates for RefundRequest
    refund_requests = db.relationship('RefundRequest', back_populates='user', lazy=True)
    admin_logs = db.relationship('AdminLog', back_populates='admin', lazy=True)
   
    
   
    def increment_failed_attempts(self, ip_address=None):
        from datetime import datetime, timedelta
        self.failed_login_attempts += 1
        if self.failed_login_attempts >= 5:
            self.locked_until = datetime.utcnow() + timedelta(minutes=30)
        if ip_address:
            self.last_ip_address = ip_address
        db.session.commit()
    
    def reset_failed_attempts(self):
        self.failed_login_attempts = 0
        self.locked_until = None
        db.session.commit()
    
    def is_locked(self):
        from datetime import datetime
        if self.locked_until and datetime.utcnow() < self.locked_until:
            return True
        return False
    
    def get_remaining_lockout_time(self):
        from datetime import datetime
        if self.locked_until and datetime.utcnow() < self.locked_until:
            return int((self.locked_until - datetime.utcnow()).seconds / 60)
        return 0
    
    # ========== POINTS METHODS ==========  # ✅ ADDED
    def add_points(self, points, type, description, reference=None):
        if points <= 0:
            return False
        self.points_balance = (self.points_balance or 0) + points
        self.total_points_earned = (self.total_points_earned or 0) + points
        transaction = PointsTransaction(
            user_id=self.id,
            points=points,
            type=type,
            description=description,
            reference=reference,
            balance_after=self.points_balance,
            platform=self.platform
        )
        db.session.add(transaction)
        db.session.commit()
        return True
    
    def deduct_points(self, points, type, description, reference=None):
        if points <= 0:
            return False
        if (self.points_balance or 0) < points:
            return False
        self.points_balance -= points
        self.total_points_redeemed = (self.total_points_redeemed or 0) + points
        transaction = PointsTransaction(
            user_id=self.id,
            points=-points,
            type=type,
            description=description,
            reference=reference,
            balance_after=self.points_balance,
            platform=self.platform
        )
        db.session.add(transaction)
        db.session.commit()
        return True
    
    def set_password(self, password):
        self.password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    def check_password(self, password):
        if not self.password_hash:
            return False
        try:
            return bcrypt.checkpw(password.encode('utf-8'), self.password_hash.encode('utf-8'))
        except Exception as e:
            print(f"Password check error: {e}")
            return False
    
    def generate_token(self):
        from datetime import datetime, timedelta
        try:
            payload = {
                'user_id': self.id,
                'email': self.email,
                'role': self.role,
                'platform': self.platform,
                'exp': datetime.utcnow() + timedelta(hours=2),
                'iat': datetime.utcnow(),
                'jti': str(uuid.uuid4())
            }
            return jwt.encode(payload, current_app.config['SECRET_KEY'], algorithm='HS256')
        except Exception as e:
            print(f"Token generation error: {e}")
            return None
    
    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'phone': self.phone,
            'role': self.role,
            'platform': self.platform,
            'platform_created': self.platform_created,
            'is_agent': self.is_agent and self.agent_approved,
            'agent_tier': self.agent_tier,
            'commission_rate': self.commission_rate,
            'wallet_balance': self.wallet_balance,
            'points_balance': self.points_balance or 0,
            'total_points_earned': self.total_points_earned or 0,
            'total_points_redeemed': self.total_points_redeemed or 0,
            'referral_code': self.referral_code,
            'full_name': self.full_name,
            'avatar': self.avatar_url,
            'kyc_verified': self.kyc_verified,
            'two_factor_enabled': self.two_factor_enabled,
            'is_super_admin': self.is_super_admin,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_login': self.last_login.isoformat() if self.last_login else None
        }
    
    def generate_email_verification_token(self):
        token = jwt.encode(
            {
                'user_id': self.id,
                'email': self.email,
                'type': 'email_verification',
                'exp': datetime.utcnow() + timedelta(hours=24)
            },
            current_app.config['SECRET_KEY'],
            algorithm='HS256'
        )
        self.email_verification_token = token
        self.email_verification_sent_at = datetime.utcnow()
        db.session.commit()
        return token
    
    @staticmethod
    def verify_token(token):
        try:
            payload = jwt.decode(token, current_app.config['SECRET_KEY'], algorithms=['HS256'])
            return User.query.get(payload['user_id'])
        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return None
    
    @staticmethod
    def verify_email_token(token):
        try:
            payload = jwt.decode(token, current_app.config['SECRET_KEY'], algorithms=['HS256'])
            if payload.get('type') != 'email_verification':
                return None
            user = User.query.get(payload.get('user_id'))
            if user and user.email == payload.get('email'):
                return user
            return None
        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return None


class SuspiciousActivityLog(db.Model):
    __tablename__ = 'suspicious_activity_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    activity_type = db.Column(db.String(50), nullable=False)
    details = db.Column(db.Text)
    ip_address = db.Column(db.String(45))
    platform = db.Column(db.String(20), default='platform_a')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', foreign_keys=[user_id])


class PendingTransaction(db.Model):
    __tablename__ = 'pending_transactions'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    reference = db.Column(db.String(100), unique=True, nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    payment_method = db.Column(db.String(50), default='paystack')
    platform = db.Column(db.String(20), default='platform_a')
    status = db.Column(db.String(50), default='pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)


class DataBundle(db.Model):
    __tablename__ = 'data_bundles'
    
    id = db.Column(db.Integer, primary_key=True)
    network = db.Column(db.String(20), nullable=False)  # mtn, telecel, airteltigo
    size_gb = db.Column(db.Float, nullable=False)
    retail_price = db.Column(db.Float, nullable=False)
    agent_price = db.Column(db.Float, nullable=False)
    wholesale_price = db.Column(db.Float, nullable=False)
    popular = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    display_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    platform = db.Column(db.String(20), default='platform_a')
    platform_created = db.Column(db.String(20), default='platform_a')  # Where bundle was created

    def to_dict(self):
        return {
            'id': self.id,
            'network': self.network,
            'size_gb': self.size_gb,
            'retail_price': self.retail_price,
            'agent_price': self.agent_price,
            'wholesale_price': self.wholesale_price,
            'popular': self.popular,
            'is_active': self.is_active,
            'platform': self.platform
        }


class Order(db.Model):
    __tablename__ = 'orders'
    
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.String(20), unique=True, default=lambda: f"RS-{uuid.uuid4().hex[:8].upper()}")
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    agent_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    type = db.Column(db.String(20), default='data') 
    network = db.Column(db.String(20), nullable=True)
    size_gb = db.Column(db.Float, nullable=True)
    quantity = db.Column(db.Integer, default=1)
    phone_number = db.Column(db.String(20), nullable=True)
    customer_name = db.Column(db.String(100), nullable=True)
    biller_code = db.Column(db.String(20), nullable=True)  
    biller_name = db.Column(db.String(100), nullable=True)
    account_number = db.Column(db.String(50), nullable=True)
    amount = db.Column(db.Float, nullable=False)  
    cost = db.Column(db.Float, default=0.0)  
    profit = db.Column(db.Float, default=0.0)  
    payment_method = db.Column(db.String(20), default='wallet')
    payment_reference = db.Column(db.String(100), nullable=True)
    provider = db.Column(db.String(50), nullable=True) 
    provider_order_id = db.Column(db.String(100), nullable=True)  
    provider_reference = db.Column(db.String(100), nullable=True)  
    provider_cost = db.Column(db.Float, default=0.0)  
    delivery_status = db.Column(db.String(30), default='pending') 
    delivery_status_updated_at = db.Column(db.DateTime, nullable=True)
    delivery_attempts = db.Column(db.Integer, default=0)
    last_delivery_error = db.Column(db.String(500), nullable=True)
    webhook_received = db.Column(db.Boolean, default=False)
    webhook_last_payload = db.Column(db.JSON, nullable=True)
    webhook_retry_count = db.Column(db.Integer, default=0)
    status = db.Column(db.String(20), default='pending')  
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)
    last_status_check = db.Column(db.DateTime, nullable=True)
    
    # ========== PLATFORM SUPPORT ==========
    platform = db.Column(db.String(20), default='platform_a')
    platform_created = db.Column(db.String(20), default='platform_a')
    
    # ========== COMMISSION FIELDS ==========
    hubtel_commission_rate = db.Column(db.Float, default=0.0)
    total_commission = db.Column(db.Float, default=0.0)
    admin_commission = db.Column(db.Float, default=0.0)
    initiator_commission = db.Column(db.Float, default=0.0)
    initiator_type = db.Column(db.String(20), default='user')
    initiator_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    delivery_type = db.Column(db.String(50), nullable=True)
    offer_slug = db.Column(db.String(100), nullable=True)
    commission_rate = db.Column(db.Float, default=0.0)
    commission_amount = db.Column(db.Float, default=0.0)
    agent_commission = db.Column(db.Float, default=0.0)
    
    # ========== RESOLUTION FIELDS ==========
    resolved_at = db.Column(db.DateTime, nullable=True)
    resolved_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    resolution_note = db.Column(db.String(500), nullable=True)
    
    # ========== ERROR FIELDS (ADD THESE) ==========
    error_type = db.Column(db.String(100), nullable=True)
    error_code = db.Column(db.String(100), nullable=True)
    user_message = db.Column(db.Text, nullable=True)
    
    customer = db.relationship('User', foreign_keys=[user_id], backref='purchases')
    agent = db.relationship('User', foreign_keys=[agent_id], backref='sales')
    initiator = db.relationship('User', foreign_keys=[initiator_id], backref='initiated_orders')
    resolver = db.relationship('User', foreign_keys=[resolved_by], backref='resolved_orders')
    
    def to_dict(self):
        return {
            'id': self.id,
            'order_id': self.order_id,
            'user_id': self.user_id,
            'agent_id': self.agent_id,
            'type': self.type,
            'network': self.network,
            'size_gb': self.size_gb,
            'quantity': self.quantity,
            'phone': self.phone_number,
            'customer_name': self.customer_name,
            'biller_code': self.biller_code,
            'biller_name': self.biller_name,
            'account_number': self.account_number,
            'amount': self.amount,
            'cost': self.cost,
            'profit': self.profit,
            'payment_method': self.payment_method,
            'provider': self.provider,
            'provider_order_id': self.provider_order_id,
            'status': self.status,
            'delivery_status': self.delivery_status,
            'delivery_status_updated_at': self.delivery_status_updated_at.isoformat() if self.delivery_status_updated_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'date': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'platform': self.platform,
            'platform_created': self.platform_created,
            'resolved_at': self.resolved_at.isoformat() if self.resolved_at else None,
            'resolution_note': self.resolution_note,
            'commission': {
                'hubtel_rate': self.hubtel_commission_rate,
                'total': self.total_commission,
                'admin': self.admin_commission,
                'initiator': self.initiator_commission,
                'initiator_type': self.initiator_type,
                'agent_commission': self.agent_commission
            } if self.total_commission > 0 else None
        }
    
    def get_delivery_status_display(self):
        status_map = {
            'pending': '⏳ Pending',
            'queued': '📋 Queued',
            'processing': '🔄 Processing',
            'delivered': '✅ Delivered',
            'failed': '❌ Failed',
            'cancelled': '🚫 Cancelled',
            'refunded': '💰 Refunded',
            'resolved': '✓ Resolved'
        }
        return status_map.get(self.delivery_status, self.delivery_status or 'Unknown')
    
    def update_delivery_status(self, new_status, error=None):
        self.delivery_status = new_status
        self.delivery_status_updated_at = datetime.utcnow()
        if error:
            self.last_delivery_error = error
        db.session.commit()
    
    def mark_resolved(self, admin_id, note=None):  # ✅ ADDED
        self.status = 'resolved'
        self.delivery_status = 'resolved'
        self.resolved_at = datetime.utcnow()
        self.resolved_by = admin_id
        if note:
            self.resolution_note = note
        db.session.commit()
    
    def set_safe_values(self, **kwargs):
        max_lengths = {
            'order_id': 100,
            'provider_order_id': 200,
            'provider_reference': 200,
            'customer_name': 200,
            'phone_number': 20,
            'network': 20,
            'biller_code': 50,
            'account_number': 100,
            'resolution_note': 500
        }
        for key, value in kwargs.items():
            if key in max_lengths and value and len(str(value)) > max_lengths[key]:
                value = str(value)[:max_lengths[key]]
            setattr(self, key, value)
    
    def set_commission(self, commission_data, initiator_id, initiator_type='user'):  # ✅ ADDED
        self.hubtel_commission_rate = commission_data.get('hubtel_rate', 0)
        self.total_commission = commission_data.get('total_commission', 0)
        self.admin_commission = commission_data.get('admin_commission', 0)
        self.initiator_commission = commission_data.get('initiator_commission', 0)
        self.initiator_type = initiator_type
        self.initiator_id = initiator_id


class RecurringBill(db.Model):
    __tablename__ = 'recurring_bills'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    biller_code = db.Column(db.String(20), nullable=False)
    biller_name = db.Column(db.String(100), nullable=False)
    account_number = db.Column(db.String(50), nullable=False)
    customer_name = db.Column(db.String(100), nullable=True)
    frequency = db.Column(db.String(20), default='monthly')
    auto_pay = db.Column(db.Boolean, default=True)
    max_amount = db.Column(db.Float, default=0)
    enabled = db.Column(db.Boolean, default=True)  
    next_due_date = db.Column(db.DateTime, nullable=True)
    last_paid_date = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    platform = db.Column(db.String(20), default='platform_a')
    
    user = db.relationship('User', backref='recurring_bills')


class DeliveryLog(db.Model):
    __tablename__ = 'delivery_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    phone_number = db.Column(db.String(20), nullable=False)
    message = db.Column(db.Text)
    status = db.Column(db.String(50), default='pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    delivered_at = db.Column(db.DateTime, nullable=True)
    platform = db.Column(db.String(20), default='platform_a')


class AgentInventoryTransaction(db.Model):
    __tablename__ = 'agent_inventory_transactions'
    
    id = db.Column(db.Integer, primary_key=True)
    agent_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    network = db.Column(db.String(50), nullable=False)
    size_gb = db.Column(db.Integer, nullable=False)
    quantity = db.Column(db.Integer, default=1)
    price_per_unit = db.Column(db.Numeric(10, 2), nullable=False)
    total_amount = db.Column(db.Numeric(10, 2), nullable=False)
    payment_method = db.Column(db.String(50), default='wallet')
    status = db.Column(db.String(50), default='completed')
    reference = db.Column(db.String(100), unique=True, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    platform = db.Column(db.String(20), default='platform_a')
    
    # Relationships
    agent = db.relationship('User', backref='inventory_transactions', foreign_keys=[agent_id])
    
    def to_dict(self):
        return {
            'id': self.id,
            'agent_id': self.agent_id,
            'network': self.network,
            'size_gb': self.size_gb,
            'quantity': self.quantity,
            'total_gb': self.size_gb * self.quantity,
            'price_per_unit': float(self.price_per_unit),
            'total_amount': float(self.total_amount),
            'payment_method': self.payment_method,
            'status': self.status,
            'reference': self.reference,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class StorePayment(db.Model):
    __tablename__ = 'store_payments'
    
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=False)
    store_id = db.Column(db.Integer, db.ForeignKey('stores.id'), nullable=False)
    
    amount = db.Column(db.Float, nullable=False)
    reference = db.Column(db.String(100), unique=True, nullable=False)
    payment_method = db.Column(db.String(50), nullable=False)  # mobile_money, bank_transfer, paystack
    
    # Payment details
    recipient_phone = db.Column(db.String(20), nullable=True)
    recipient_name = db.Column(db.String(100), nullable=True)
    bank_name = db.Column(db.String(100), nullable=True)
    account_name = db.Column(db.String(100), nullable=True)
    account_number = db.Column(db.String(50), nullable=True)
    
    # Paystack specific
    paystack_reference = db.Column(db.String(100), nullable=True)
    paystack_amount = db.Column(db.Float, nullable=True)
    
    # Status
    status = db.Column(db.String(20), default='pending')  # pending, completed, failed, refunded
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    verified_at = db.Column(db.DateTime, nullable=True)
    
    # Platform
    platform = db.Column(db.String(20), default='platform_a')
    
    # Relationships
    order = db.relationship('Order', backref='store_payment', uselist=False)
    store = db.relationship('Store', backref='payments')
    
    def to_dict(self):
        return {
            'id': self.id,
            'order_id': self.order_id,
            'store_id': self.store_id,
            'amount': self.amount,
            'reference': self.reference,
            'payment_method': self.payment_method,
            'recipient_phone': self.recipient_phone,
            'recipient_name': self.recipient_name,
            'bank_name': self.bank_name,
            'account_name': self.account_name,
            'account_number': self.account_number,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'verified_at': self.verified_at.isoformat() if self.verified_at else None
        }
    
class DeliverySetting(db.Model):
    __tablename__ = 'delivery_settings'
    
    id = db.Column(db.Integer, primary_key=True)
    network = db.Column(db.String(20), nullable=False)
    delivery_type = db.Column(db.String(50), nullable=False)
    multiplier = db.Column(db.Numeric(5, 4), default=1.0)
    fixed_premium = db.Column(db.Numeric(10, 2), default=0.0)
    min_time = db.Column(db.Integer, default=2)
    max_time = db.Column(db.Integer, default=5)
    avg_time = db.Column(db.Integer, default=3)
    is_active = db.Column(db.Boolean, default=True)
    queue_length = db.Column(db.Integer, default=0)
    status = db.Column(db.String(20), default='normal')
    offer_slug = db.Column(db.String(100), nullable=True)
    platform = db.Column(db.String(20), default='platform_b')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        db.UniqueConstraint('network', 'delivery_type', name='unique_network_delivery'),
    )
    
    def to_dict(self):
        return {
            'id': self.id,
            'network': self.network,
            'delivery_type': self.delivery_type,
            'multiplier': float(self.multiplier),
            'fixed_premium': float(self.fixed_premium),
            'min_time': self.min_time,
            'max_time': self.max_time,
            'avg_time': self.avg_time,
            'is_active': self.is_active,
            'queue_length': self.queue_length,
            'status': self.status,
            'offer_slug': self.offer_slug,
            'platform': self.platform,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class PriceSetting(db.Model):
    __tablename__ = 'price_settings'
    
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(50), nullable=False)  
    network = db.Column(db.String(50), nullable=True)    
    size_gb = db.Column(db.Integer, nullable=True)       
    delivery_type = db.Column(db.String(50), nullable=True)  # ✅ ADDED
    exam_type = db.Column(db.String(50), nullable=True)  
    tier = db.Column(db.String(50), nullable=True)       
    price = db.Column(db.Numeric(10, 2), nullable=True)
    rate = db.Column(db.Numeric(5, 2), nullable=True)
    is_available = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    platform = db.Column(db.String(20), default='platform_a')
    
    def to_dict(self):
        return {
            'id': self.id,
            'category': self.category,
            'network': self.network,
            'size_gb': self.size_gb,
            'delivery_type': self.delivery_type,
            'exam_type': self.exam_type,
            'tier': self.tier,
            'price': float(self.price) if self.price else None,
            'rate': float(self.rate) if self.rate else None,
            'is_available': self.is_available,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

class Transaction(db.Model):
    __tablename__ = 'transactions'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    type = db.Column(db.String(20), nullable=False)  
    amount = db.Column(db.Float, nullable=False)
    balance_before = db.Column(db.Float, nullable=False)
    balance_after = db.Column(db.Float, nullable=False)
    description = db.Column(db.String(500), nullable=True)
    reference = db.Column(db.String(100), unique=True, default=lambda: f"RS-TXN-{uuid.uuid4().hex[:8].upper()}")
    status = db.Column(db.String(20), default='completed')
    meta_data = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)  # ✅ ADDED
    platform = db.Column(db.String(20), default='platform_a')
    
    def to_dict(self):
        return {
            'id': self.id,
            'type': self.type,
            'amount': self.amount,
            'balance_before': self.balance_before,
            'balance_after': self.balance_after,
            'description': self.description,
            'reference': self.reference,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class AgentRequest(db.Model):
    __tablename__ = 'agent_requests'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # Request Details
    amount = db.Column(db.Float, default=100.00)
    payment_method = db.Column(db.String(20), default='manual')
    payment_reference = db.Column(db.String(100), nullable=True)
    proof_url = db.Column(db.String(500), nullable=True)
    status = db.Column(db.String(20), default='pending')  # pending, approved, rejected
    
    # Admin Review
    reviewed_by = db.Column(db.Integer, nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    rejection_reason = db.Column(db.String(500), nullable=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    approved_at = db.Column(db.DateTime, nullable=True)
    
    # Platform
    platform = db.Column(db.String(20), default='platform_a')


class ManualPayment(db.Model):
    __tablename__ = 'manual_payments'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=True)
    
    # Payment Details
    amount = db.Column(db.Float, nullable=False)
    reference = db.Column(db.String(100), unique=True, nullable=False)
    phone_number = db.Column(db.String(20), nullable=True)
    
    # Proof
    proof_url = db.Column(db.String(500), nullable=True)
    sender_name = db.Column(db.String(100), nullable=True)
    sender_phone = db.Column(db.String(20), nullable=True)
    transaction_id = db.Column(db.String(100), nullable=True)
    
    # Status
    status = db.Column(db.String(20), default='pending')
    
    # Admin Review
    verified_by = db.Column(db.Integer, nullable=True)
    verified_at = db.Column(db.DateTime, nullable=True)
    notes = db.Column(db.String(500), nullable=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Platform
    platform = db.Column(db.String(20), default='platform_a')


class Notification(db.Model):
    __tablename__ = 'notifications'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.String(1000), nullable=False)
    type = db.Column(db.String(50), default='info')
    is_read = db.Column(db.Boolean, default=False)
    
    # Action
    action_url = db.Column(db.String(500), nullable=True)
    action_text = db.Column(db.String(100), nullable=True)
    
    # Metadata
    meta_data = db.Column(db.JSON, nullable=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    read_at = db.Column(db.DateTime, nullable=True)
    
    # Platform
    platform = db.Column(db.String(20), default='platform_a')
    
    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'message': self.message,
            'type': self.type,
            'is_read': self.is_read,
            'action_url': self.action_url,
            'action_text': self.action_text,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class Store(db.Model):
    __tablename__ = 'stores'
    
    id = db.Column(db.Integer, primary_key=True)
    agent_id = db.Column(db.Integer, db.ForeignKey('users.id'), unique=True, nullable=False)
    store_name = db.Column(db.String(100), nullable=False)
    store_slug = db.Column(db.String(100), unique=True, nullable=False)
    contact_phone = db.Column(db.String(20), nullable=False)
    contact_email = db.Column(db.String(120), nullable=False)
    store_description = db.Column(db.Text, nullable=True)
    logo_url = db.Column(db.String(500), nullable=True)
    banner_color = db.Column(db.String(7), default='#8B0000')
    markup = db.Column(db.Integer, default=15)
    custom_prices = db.Column(db.JSON, nullable=True)
    custom_products = db.Column(db.JSON, nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    total_sales = db.Column(db.Float, default=0.0)
    total_orders = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    platform = db.Column(db.String(20), default='platform_a')
    
    def to_dict(self):
        return {
            'id': self.id,
            'store_name': self.store_name,
            'store_slug': self.store_slug,
            'contact_phone': self.contact_phone,
            'contact_email': self.contact_email,
            'store_description': self.store_description,
            'logo_url': self.logo_url,
            'banner_color': self.banner_color,
            'markup': self.markup,
            'custom_prices': self.custom_prices,
            'custom_products': self.custom_products,
            'is_active': self.is_active,
            'total_sales': self.total_sales,
            'total_orders': self.total_orders,
            'store_url': f"/store/{self.store_slug}"
        }


class PackageAvailability(db.Model):
    __tablename__ = 'package_availability'
    
    id = db.Column(db.Integer, primary_key=True)
    network = db.Column(db.String(50), nullable=False)
    size_gb = db.Column(db.Float, nullable=False)
    is_available = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    platform = db.Column(db.String(20), default='platform_a')
    
    # Add unique constraint
    __table_args__ = (db.UniqueConstraint('network', 'size_gb', name='unique_network_size'),)
    
    def to_dict(self):
        return {
            'id': self.id,
            'network': self.network,
            'size_gb': self.size_gb,
            'is_available': self.is_available,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class PaymentSession(db.Model):
    __tablename__ = 'payment_sessions'
    
    id = db.Column(db.Integer, primary_key=True)
    reference = db.Column(db.String(100), unique=True, nullable=False)
    store_slug = db.Column(db.String(100), nullable=False)
    agent_id = db.Column(db.Integer, nullable=False)
    network = db.Column(db.String(20), nullable=False)
    size_gb = db.Column(db.Float, nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), default='pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, default=lambda: datetime.utcnow() + timedelta(hours=1))
    order_id = db.Column(db.String(50), nullable=True)
    platform = db.Column(db.String(20), default='platform_a')
    
    def to_dict(self):
        return {
            'reference': self.reference,
            'store_slug': self.store_slug,
            'agent_id': self.agent_id,
            'network': self.network,
            'size_gb': self.size_gb,
            'phone': self.phone,
            'amount': self.amount,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'order_id': self.order_id
        }


class AgentProductPrice(db.Model):
    __tablename__ = 'agent_product_prices'
    
    id = db.Column(db.Integer, primary_key=True)
    agent_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    network = db.Column(db.String(50), nullable=False)
    size_gb = db.Column(db.Integer, nullable=False)
    retail_price = db.Column(db.Numeric(10, 2), nullable=False)
    markup = db.Column(db.Numeric(5, 2), default=15.00)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    platform = db.Column(db.String(20), default='platform_a')
    
    agent = db.relationship('User', backref='product_prices')


class AgentStore(db.Model):
    __tablename__ = 'agent_stores'
    
    id = db.Column(db.Integer, primary_key=True)
    agent_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    store_name = db.Column(db.String(100), nullable=False)
    store_slug = db.Column(db.String(100), unique=True, nullable=False)
    contact_phone = db.Column(db.String(20))
    contact_email = db.Column(db.String(100))
    store_description = db.Column(db.Text)
    default_markup = db.Column(db.Numeric(5, 2), default=15.00)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    platform = db.Column(db.String(20), default='platform_a')
    
    agent = db.relationship('User', backref='agent_store')


class StoreClient(db.Model):
    __tablename__ = 'store_clients'
    
    id = db.Column(db.Integer, primary_key=True)
    agent_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # Client Details
    name = db.Column(db.String(100), nullable=True)
    phone = db.Column(db.String(20), nullable=False)
    email = db.Column(db.String(120), nullable=True)
    
    # Stats
    total_spent = db.Column(db.Float, default=0.0)
    order_count = db.Column(db.Integer, default=0)
    
    # Timestamps
    last_purchase = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    platform = db.Column(db.String(20), default='platform_a')


class Referral(db.Model):
    __tablename__ = 'referrals'
    
    id = db.Column(db.Integer, primary_key=True)
    referrer_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    referred_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # Reward
    reward_amount = db.Column(db.Float, default=5.00)
    status = db.Column(db.String(20), default='pending')  # pending, completed, paid
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)
    platform = db.Column(db.String(20), default='platform_a')
    
    def to_dict(self):
        return {
            'id': self.id,
            'referrer_id': self.referrer_id,
            'referred_id': self.referred_id,
            'reward_amount': self.reward_amount,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class Announcement(db.Model):
    __tablename__ = 'announcements'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    type = db.Column(db.String(20), default='info')
    network_affected = db.Column(db.String(20), default='all')
    
    is_active = db.Column(db.Boolean, default=True)
    expires_at = db.Column(db.DateTime, nullable=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.Integer, nullable=True)
    
    # Platform
    platform = db.Column(db.String(20), default='platform_a')
    
    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'message': self.message,
            'type': self.type,
            'network_affected': self.network_affected,
            'is_active': self.is_active,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None
        }


class KYCDocument(db.Model):
    __tablename__ = 'kyc_documents'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # Document Details
    document_type = db.Column(db.String(50), nullable=False)  # ghana_card, passport, drivers_license
    document_number = db.Column(db.String(100), nullable=False)
    document_url = db.Column(db.String(500), nullable=False)
    
    # Verification
    status = db.Column(db.String(20), default='pending')
    verified_by = db.Column(db.Integer, nullable=True)
    verified_at = db.Column(db.DateTime, nullable=True)
    rejection_reason = db.Column(db.String(500), nullable=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    platform = db.Column(db.String(20), default='platform_a')
    
    def to_dict(self):
        return {
            'id': self.id,
            'document_type': self.document_type,
            'document_number': self.document_number,
            'document_url': self.document_url,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class Webhook(db.Model):
    __tablename__ = 'webhooks'
    
    id = db.Column(db.Integer, primary_key=True)
    url = db.Column(db.String(500), nullable=False)
    events = db.Column(db.JSON, default=[])
    secret = db.Column(db.String(200), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    
    # Stats
    last_triggered = db.Column(db.DateTime, nullable=True)
    failure_count = db.Column(db.Integer, default=0)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    platform = db.Column(db.String(20), default='platform_a')
    
    def to_dict(self):
        return {
            'id': self.id,
            'url': self.url,
            'events': self.events,
            'is_active': self.is_active,
            'last_triggered': self.last_triggered.isoformat() if self.last_triggered else None,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class Backup(db.Model):
    __tablename__ = 'backups'
    
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(200), nullable=False)
    size = db.Column(db.Integer, default=0)
    path = db.Column(db.String(500), nullable=True)
    
    # Metadata
    type = db.Column(db.String(20), default='manual')
    status = db.Column(db.String(20), default='completed')
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.Integer, nullable=True)
    platform = db.Column(db.String(20), default='platform_a')
    
    def to_dict(self):
        return {
            'id': self.id,
            'filename': self.filename,
            'size': self.size,
            'type': self.type,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class UserSession(db.Model):
    __tablename__ = 'user_sessions'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # Session Details
    token = db.Column(db.String(500), nullable=True)
    ip_address = db.Column(db.String(50), nullable=True)
    user_agent = db.Column(db.String(500), nullable=True)
    device_info = db.Column(db.String(200), nullable=True)
    location = db.Column(db.String(200), nullable=True)
    
    # Action Logging
    action = db.Column(db.String(100), nullable=True)
    details = db.Column(db.Text, nullable=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=True)
    platform = db.Column(db.String(20), default='platform_a')
    
    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'ip_address': self.ip_address,
            'device_info': self.device_info,
            'location': self.location,
            'action': self.action,
            'details': self.details,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class SupportTicket(db.Model):
    __tablename__ = 'support_tickets'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # Ticket Details
    ticket_id = db.Column(db.String(20), unique=True, default=lambda: f"RS-TKT-{uuid.uuid4().hex[:8].upper()}")
    subject = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    priority = db.Column(db.String(20), default='normal')
    status = db.Column(db.String(20), default='open')
    
    # Admin Response
    response = db.Column(db.Text, nullable=True)
    resolved_by = db.Column(db.Integer, nullable=True)
    resolved_at = db.Column(db.DateTime, nullable=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    platform = db.Column(db.String(20), default='platform_a')
    
    def to_dict(self):
        return {
            'id': self.id,
            'ticket_id': self.ticket_id,
            'subject': self.subject,
            'message': self.message,
            'priority': self.priority,
            'status': self.status,
            'response': self.response,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class NewsletterSubscriber(db.Model):
    __tablename__ = 'newsletter_subscribers'
    
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    
    # Timestamps
    subscribed_at = db.Column(db.DateTime, default=datetime.utcnow)
    unsubscribed_at = db.Column(db.DateTime, nullable=True)
    platform = db.Column(db.String(20), default='platform_a')
    
    def to_dict(self):
        return {
            'id': self.id,
            'email': self.email,
            'subscribed_at': self.subscribed_at.isoformat() if self.subscribed_at else None
        }


class ActivityLog(db.Model):
    __tablename__ = 'activity_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    
    # Activity Details
    action = db.Column(db.String(100), nullable=False)
    entity_type = db.Column(db.String(50), nullable=True)
    entity_id = db.Column(db.Integer, nullable=True)
    details = db.Column(db.Text, nullable=True)
    ip_address = db.Column(db.String(50), nullable=True)
    user_agent = db.Column(db.String(500), nullable=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    platform = db.Column(db.String(20), default='platform_a')
    
    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'action': self.action,
            'entity_type': self.entity_type,
            'entity_id': self.entity_id,
            'details': self.details,
            'ip_address': self.ip_address,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class NetworkProvider(db.Model):
    __tablename__ = 'network_providers'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)  # MTN, Telecel, AirtelTigo
    api_key = db.Column(db.String(500), nullable=True)
    api_secret = db.Column(db.String(500), nullable=True)
    api_endpoint = db.Column(db.String(500), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    last_sync = db.Column(db.DateTime, nullable=True)
    platform = db.Column(db.String(20), default='platform_a')


class MasterInventory(db.Model):
    __tablename__ = 'master_inventories'
    
    id = db.Column(db.Integer, primary_key=True)
    network = db.Column(db.String(50), nullable=False)
    size_gb = db.Column(db.Integer, nullable=False)
    total_purchased = db.Column(db.Integer, default=0)
    remaining = db.Column(db.Integer, default=0)
    sold_to_agents = db.Column(db.Integer, default=0)
    sold_to_users = db.Column(db.Integer, default=0)
    last_purchase_date = db.Column(db.DateTime, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    platform = db.Column(db.String(20), default='platform_a')


class AgentInventory(db.Model):
    __tablename__ = 'agent_inventory'
    
    id = db.Column(db.Integer, primary_key=True)
    agent_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    network = db.Column(db.String(20), nullable=False)
    size_gb = db.Column(db.Float, nullable=False)
    purchased = db.Column(db.Float, default=0)
    sold = db.Column(db.Float, default=0)
    remaining = db.Column(db.Float, default=0)
    last_purchase_date = db.Column(db.DateTime, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    platform = db.Column(db.String(20), default='platform_a')


class InventoryTransaction(db.Model):
    __tablename__ = 'inventory_transactions'
    
    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(20), nullable=False)  # master_purchase, agent_purchase, agent_sale
    from_user_id = db.Column(db.Integer, nullable=True)
    to_user_id = db.Column(db.Integer, nullable=True)
    network = db.Column(db.String(20), nullable=False)
    size_gb = db.Column(db.Float, nullable=False)
    quantity = db.Column(db.Integer, default=1)
    total_gb = db.Column(db.Float, nullable=False)
    amount = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), default='completed')
    reference = db.Column(db.String(100), unique=True, default=lambda: f"RS-INV-{uuid.uuid4().hex[:8].upper()}")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    platform = db.Column(db.String(20), default='platform_a')


class LoyaltyPoints(db.Model):
    __tablename__ = 'loyalty_points'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    points = db.Column(db.Integer, default=0)
    lifetime_points = db.Column(db.Integer, default=0)
    tier = db.Column(db.String(20), default='Bronze')
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    platform = db.Column(db.String(20), default='platform_a')


class PointsTransaction(db.Model):
    __tablename__ = 'points_transactions'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=True)
    points = db.Column(db.Integer, nullable=False)
    type = db.Column(db.String(20), nullable=False)
    description = db.Column(db.String(500), nullable=True)
    reference = db.Column(db.String(50), nullable=True)
    balance_after = db.Column(db.Integer, default=0)  # ✅ ADDED
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    platform = db.Column(db.String(20), default='platform_a')



class AgentApplication(db.Model):
    __tablename__ = 'agent_applications'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    status = db.Column(db.String(20), default='pending')
    rejection_reason = db.Column(db.String(500), nullable=True)
    approved_by = db.Column(db.Integer, nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Payment info
    payment_reference = db.Column(db.String(100), nullable=True)
    payment_proof_url = db.Column(db.String(500), nullable=True)
    payment_amount = db.Column(db.Float, default=100.00)
    payment_method = db.Column(db.String(50), default='manual')
    
    # Platform
    platform = db.Column(db.String(20), default='platform_a')
    
    # Relationships
    user = db.relationship('User', backref='agent_applications', foreign_keys=[user_id])
    
    def to_dict(self):
        return {
            'id': self.id,
            'status': self.status,
            'rejection_reason': self.rejection_reason,
            'payment_reference': self.payment_reference,
            'payment_amount': self.payment_amount,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'approved_at': self.approved_at.isoformat() if self.approved_at else None
        }


class WAECVoucher(db.Model):
    __tablename__ = 'waec_vouchers'
    
    id = db.Column(db.Integer, primary_key=True)
    voucher_code = db.Column(db.String(50), unique=True, nullable=False)
    serial_number = db.Column(db.String(50), unique=True, nullable=False)
    pin = db.Column(db.String(50), nullable=False)
    exam_type = db.Column(db.String(20), nullable=False)  # WASSCE, BECE, SHS Placement
    year = db.Column(db.Integer, nullable=False)
    retail_price = db.Column(db.Float, default=20.00)
    agent_price = db.Column(db.Float, default=18.00)
    wholesale_price = db.Column(db.Float, default=15.00)
    is_used = db.Column(db.Boolean, default=False)
    used_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    used_at = db.Column(db.DateTime, nullable=True)
    purchased_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    purchased_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    platform = db.Column(db.String(20), default='platform_a')


class BillPayment(db.Model):
    __tablename__ = 'bill_payments'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    bill_type = db.Column(db.String(50), nullable=False)
    biller_name = db.Column(db.String(100), nullable=False)
    account_number = db.Column(db.String(100), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    reference = db.Column(db.String(100), unique=True, default=lambda: f"RS-BILL-{uuid.uuid4().hex[:8].upper()}")
    status = db.Column(db.String(20), default='pending')
    transaction_id = db.Column(db.String(100), nullable=True)
    payment_method = db.Column(db.String(50), default='wallet')
    customer_name = db.Column(db.String(200), nullable=True)
    customer_email = db.Column(db.String(200), nullable=True)
    customer_phone = db.Column(db.String(20), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)
    platform = db.Column(db.String(20), default='platform_a')
    
    user = db.relationship('User', backref='bill_payments')


class Biller(db.Model):
    __tablename__ = 'billers'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    code = db.Column(db.String(50), unique=True, nullable=False)
    category = db.Column(db.String(50), nullable=False)
    icon = db.Column(db.String(100), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    min_amount = db.Column(db.Float, default=10.00)
    max_amount = db.Column(db.Float, default=10000.00)
    convenience_fee = db.Column(db.Float, default=0.00)
    api_endpoint = db.Column(db.String(500), nullable=True)
    api_key = db.Column(db.String(200), nullable=True)
    display_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    platform = db.Column(db.String(20), default='platform_a')


class SMSLog(db.Model):
    __tablename__ = 'sms_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    phone_number = db.Column(db.String(20), nullable=False)
    message = db.Column(db.Text, nullable=False)
    sms_type = db.Column(db.String(50))
    provider = db.Column(db.String(50))
    status = db.Column(db.String(20), default='sent')
    error = db.Column(db.Text)
    sent_at = db.Column(db.DateTime, default=datetime.utcnow)
    platform = db.Column(db.String(20), default='platform_a')


class EmailLog(db.Model):
    __tablename__ = 'email_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    recipient = db.Column(db.String(255), nullable=False)
    subject = db.Column(db.String(500), nullable=False)
    status = db.Column(db.String(20))
    error = db.Column(db.Text)
    sent_at = db.Column(db.DateTime, default=datetime.utcnow)
    platform = db.Column(db.String(20), default='platform_a')


class SystemSetting(db.Model):
    __tablename__ = 'system_settings'
    
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.Text)
    value_type = db.Column(db.String(20), default='string')
    description = db.Column(db.String(500))
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    platform = db.Column(db.String(20), default='platform_a')
    
    @staticmethod
    def get(key, default=None):
        """Get setting value by key"""
        setting = SystemSetting.query.filter_by(key=key).first()
        if not setting:
            return default
        
        # Convert value based on type
        if setting.value_type == 'int':
            return int(setting.value) if setting.value else default
        elif setting.value_type == 'float':
            return float(setting.value) if setting.value else default
        elif setting.value_type == 'bool':
            return setting.value.lower() == 'true' if setting.value else default
        elif setting.value_type == 'json':
            import json
            return json.loads(setting.value) if setting.value else default
        else:
            return setting.value
    
    @staticmethod
    def set(key, value, value_type='string', description=None, updated_by=None):
        """Set setting value by key"""
        setting = SystemSetting.query.filter_by(key=key).first()
        
        # Convert value based on type
        if value_type == 'json':
            import json
            value = json.dumps(value)
        elif value_type == 'bool':
            value = str(value).lower()
        else:
            value = str(value) if value is not None else None
        
        if setting:
            setting.value = value
            setting.value_type = value_type
            setting.updated_at = datetime.utcnow()
            setting.updated_by = updated_by
            if description:
                setting.description = description
        else:
            setting = SystemSetting(
                key=key,
                value=value,
                value_type=value_type,
                description=description,
                updated_by=updated_by
            )
            db.session.add(setting)
        
        db.session.commit()
        return setting


class PriceSession(db.Model):
    """Store active price management sessions in database"""
    __tablename__ = 'price_sessions'
    
    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(100), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)
    platform = db.Column(db.String(20), default='platform_a')
    
    # Relationship
    user = db.relationship('User', backref='price_sessions')
    
    def to_dict(self):
        return {
            'id': self.id,
            'token': self.token,
            'user_id': self.user_id,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'is_active': self.is_active
        }


class NotificationTemplate(db.Model):
    __tablename__ = 'notification_templates'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    type = db.Column(db.String(20))  # email, sms
    subject = db.Column(db.String(500))
    body_template = db.Column(db.Text, nullable=False)
    variables = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    platform = db.Column(db.String(20), default='platform_a')


class ContactMessage(db.Model):
    __tablename__ = 'contact_messages'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(255), nullable=False)
    phone = db.Column(db.String(20))
    subject = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default='pending')
    replied_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    replied_at = db.Column(db.DateTime)
    reply_message = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    platform = db.Column(db.String(20), default='platform_a')


class FAQ(db.Model):
    __tablename__ = 'faqs'
    
    id = db.Column(db.Integer, primary_key=True)
    question = db.Column(db.String(500), nullable=False)
    answer = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(100))
    order = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    platform = db.Column(db.String(20), default='platform_a')


class Testimonial(db.Model):
    __tablename__ = 'testimonials'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(100))
    content = db.Column(db.Text, nullable=False)
    rating = db.Column(db.Integer, default=5)
    location = db.Column(db.String(100))
    avatar_url = db.Column(db.String(500))
    is_verified = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    platform = db.Column(db.String(20), default='platform_a')

class VisitorLog(db.Model):
    """Track individual visitor sessions"""
    __tablename__ = 'visitor_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.String(100), unique=True, nullable=False)  # Unique session identifier
    visitor_id = db.Column(db.String(100), nullable=True)  # Persistent visitor ID (cookie-based)
    ip_address = db.Column(db.String(45), nullable=True)
    user_agent = db.Column(db.String(500), nullable=True)
    
    # Device & Browser Info
    device_type = db.Column(db.String(50), default='desktop')  # desktop, mobile, tablet
    browser = db.Column(db.String(50), default='other')  # chrome, firefox, safari, edge, other
    os = db.Column(db.String(50), nullable=True)
    screen_size = db.Column(db.String(50), nullable=True)
    
    # Geolocation (optional)
    country = db.Column(db.String(100), nullable=True)
    region = db.Column(db.String(100), nullable=True)
    city = db.Column(db.String(100), nullable=True)
    
    # Referrer
    referrer_url = db.Column(db.String(500), nullable=True)
    landing_page = db.Column(db.String(500), nullable=True)
    
    # Session Tracking
    first_visit = db.Column(db.DateTime, default=datetime.utcnow)
    last_activity = db.Column(db.DateTime, default=datetime.utcnow)
    page_views = db.Column(db.Integer, default=0)
    session_duration = db.Column(db.Integer, default=0)  # In seconds
    is_active = db.Column(db.Boolean, default=True)
    platform = db.Column(db.String(20), default='platform_a')
    
    # Relationships
    page_visits = db.relationship('PageVisit', backref='visitor', lazy=True)
    
    def to_dict(self):
        return {
            'id': self.id,
            'session_id': self.session_id,
            'visitor_id': self.visitor_id,
            'ip_address': self.ip_address,
            'device_type': self.device_type,
            'browser': self.browser,
            'os': self.os,
            'country': self.country,
            'referrer_url': self.referrer_url,
            'landing_page': self.landing_page,
            'first_visit': self.first_visit.isoformat() if self.first_visit else None,
            'last_activity': self.last_activity.isoformat() if self.last_activity else None,
            'page_views': self.page_views,
            'session_duration': self.session_duration,
            'is_active': self.is_active,
            'platform': self.platform
        }
    
    @staticmethod
    def get_active_sessions():
        """Get count of active sessions in the last 5 minutes"""
        five_minutes_ago = datetime.utcnow() - timedelta(minutes=5)
        return VisitorLog.query.filter(
            VisitorLog.last_activity >= five_minutes_ago,
            VisitorLog.is_active == True
        ).count()
    
    @staticmethod
    def get_unique_visitors_today():
        """Get unique visitors for today"""
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        return db.session.query(db.func.count(db.distinct(VisitorLog.visitor_id))).filter(
            VisitorLog.first_visit >= today_start,
            VisitorLog.visitor_id.isnot(None)
        ).scalar() or 0
    
    @staticmethod
    def get_visitor_stats(platform='platform_a'):
        """Get comprehensive visitor statistics"""
        now = datetime.utcnow()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timedelta(days=today_start.weekday())
        month_start = today_start.replace(day=1)
        
        # Filter by platform
        platform_filter = VisitorLog.platform == platform
        
        # Total visitors (unique)
        total_visitors = db.session.query(db.func.count(db.distinct(VisitorLog.visitor_id))).filter(
            platform_filter,
            VisitorLog.visitor_id.isnot(None)
        ).scalar() or 0
        
        # Today's visitors
        today_visitors = db.session.query(db.func.count(db.distinct(VisitorLog.visitor_id))).filter(
            platform_filter,
            VisitorLog.first_visit >= today_start,
            VisitorLog.visitor_id.isnot(None)
        ).scalar() or 0
        
        # This week's visitors
        week_visitors = db.session.query(db.func.count(db.distinct(VisitorLog.visitor_id))).filter(
            platform_filter,
            VisitorLog.first_visit >= week_start,
            VisitorLog.visitor_id.isnot(None)
        ).scalar() or 0
        
        # This month's visitors
        month_visitors = db.session.query(db.func.count(db.distinct(VisitorLog.visitor_id))).filter(
            platform_filter,
            VisitorLog.first_visit >= month_start,
            VisitorLog.visitor_id.isnot(None)
        ).scalar() or 0
        
        # Active now
        five_minutes_ago = now - timedelta(minutes=5)
        active_now = VisitorLog.query.filter(
            platform_filter,
            VisitorLog.last_activity >= five_minutes_ago,
            VisitorLog.is_active == True
        ).count()
        
        # Total page views
        page_views = VisitorLog.query.filter(platform_filter).with_entities(
            db.func.sum(VisitorLog.page_views)
        ).scalar() or 0
        
        # Average session duration
        avg_duration = db.session.query(db.func.avg(VisitorLog.session_duration)).filter(
            platform_filter
        ).scalar() or 0
        
        # Bounce rate (sessions with only 1 page view)
        total_sessions = VisitorLog.query.filter(platform_filter).count()
        bounced_sessions = VisitorLog.query.filter(
            platform_filter,
            VisitorLog.page_views == 1
        ).count()
        bounce_rate = (bounced_sessions / total_sessions * 100) if total_sessions > 0 else 0
        
        # Device breakdown
        devices = db.session.query(
            VisitorLog.device_type,
            db.func.count(VisitorLog.id)
        ).filter(platform_filter).group_by(VisitorLog.device_type).all()
        device_stats = {device: count for device, count in devices}
        
        # Browser breakdown
        browsers = db.session.query(
            VisitorLog.browser,
            db.func.count(VisitorLog.id)
        ).filter(platform_filter).group_by(VisitorLog.browser).all()
        browser_stats = {browser: count for browser, count in browsers}
        
        # Top pages
        top_pages = db.session.query(
            PageVisit.page_url,
            db.func.count(PageVisit.id)
        ).join(VisitorLog).filter(
            VisitorLog.platform == platform
        ).group_by(PageVisit.page_url).order_by(
            db.func.count(PageVisit.id).desc()
        ).limit(10).all()
        
        top_pages_data = [{'page': page, 'views': views} for page, views in top_pages]
        
        return {
            'total_visitors': total_visitors,
            'unique_visitors': total_visitors,
            'today_visitors': today_visitors,
            'this_week_visitors': week_visitors,
            'this_month_visitors': month_visitors,
            'active_now': active_now,
            'page_views': page_views,
            'bounce_rate': round(bounce_rate, 2),
            'avg_session_duration': round(avg_duration / 60, 1),  # Convert to minutes
            'devices': {
                'desktop': device_stats.get('desktop', 0),
                'mobile': device_stats.get('mobile', 0),
                'tablet': device_stats.get('tablet', 0)
            },
            'browsers': {
                'chrome': browser_stats.get('chrome', 0),
                'firefox': browser_stats.get('firefox', 0),
                'safari': browser_stats.get('safari', 0),
                'edge': browser_stats.get('edge', 0),
                'other': browser_stats.get('other', 0)
            },
            'top_pages': top_pages_data
        }


class PageVisit(db.Model):
    """Track individual page visits"""
    __tablename__ = 'page_visits'
    
    id = db.Column(db.Integer, primary_key=True)
    visitor_id = db.Column(db.Integer, db.ForeignKey('visitor_logs.id'), nullable=False)
    page_url = db.Column(db.String(500), nullable=False)
    page_title = db.Column(db.String(255), nullable=True)
    referrer_url = db.Column(db.String(500), nullable=True)
    time_spent = db.Column(db.Integer, default=0)  # In seconds
    scroll_depth = db.Column(db.Integer, default=0)  # Percentage
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'page_url': self.page_url,
            'page_title': self.page_title,
            'time_spent': self.time_spent,
            'scroll_depth': self.scroll_depth,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

class PointsRedemption(db.Model):
    __tablename__ = 'points_redemptions'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    points_used = db.Column(db.Integer, nullable=False)
    redeemed_value = db.Column(db.Float, nullable=False)
    redemption_type = db.Column(db.String(30), nullable=False)
    details = db.Column(db.JSON, nullable=True)
    status = db.Column(db.String(20), default='pending')
    platform = db.Column(db.String(20), default='platform_b')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)


# ============================================================
# CUSTOMER (NEW)
# ============================================================
class Customer(db.Model):
    __tablename__ = 'customers'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    phone = db.Column(db.String(20), nullable=False)
    email = db.Column(db.String(100))
    agent_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    total_spent = db.Column(db.Numeric(10, 2), default=0)
    order_count = db.Column(db.Integer, default=0)
    platform = db.Column(db.String(20), default='platform_a')
    last_purchase = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # ========== RELATIONSHIP ==========
    # ✅ Add this relationship - creates 'customers' backref on User
    agent = db.relationship('User', backref='customers')
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'phone': self.phone,
            'email': self.email,
            'total_spent': float(self.total_spent) if self.total_spent else 0,
            'order_count': self.order_count,
            'platform': self.platform,
            'last_purchase': self.last_purchase.isoformat() if self.last_purchase else None,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

# ============================================================
# COMMISSION TRANSACTION (NEW)
# ============================================================
class CommissionTransaction(db.Model):
    __tablename__ = 'commission_transactions'
    
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.String(50), nullable=False)
    transaction_type = db.Column(db.String(50), nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    hubtel_commission_rate = db.Column(db.Numeric(5, 4))
    total_commission = db.Column(db.Numeric(10, 2), nullable=False)
    admin_commission = db.Column(db.Numeric(10, 2), nullable=False)
    initiator_commission = db.Column(db.Numeric(10, 2), nullable=False)
    initiator_type = db.Column(db.String(20), nullable=False)
    initiator_id = db.Column(db.Integer, nullable=False)
    admin_id = db.Column(db.Integer)
    status = db.Column(db.String(20), default='completed')
    platform = db.Column(db.String(20), default='platform_b')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'order_id': self.order_id,
            'transaction_type': self.transaction_type,
            'amount': float(self.amount),
            'hubtel_commission_rate': float(self.hubtel_commission_rate) if self.hubtel_commission_rate else 0,
            'total_commission': float(self.total_commission),
            'admin_commission': float(self.admin_commission),
            'initiator_commission': float(self.initiator_commission),
            'initiator_type': self.initiator_type,
            'status': self.status,
            'platform': self.platform,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


# ============================================================
# COMMISSION RATE (NEW)
# ============================================================
class CommissionRate(db.Model):
    __tablename__ = 'commission_rates'
    
    id = db.Column(db.Integer, primary_key=True)
    service_type = db.Column(db.String(50), unique=True, nullable=False)
    service_name = db.Column(db.String(100), nullable=False)
    hubtel_commission_rate = db.Column(db.Numeric(5, 4), nullable=False)
    admin_share = db.Column(db.Numeric(5, 2), default=30.00)
    initiator_share = db.Column(db.Numeric(5, 2), default=70.00)
    is_active = db.Column(db.Boolean, default=True)
    platform = db.Column(db.String(20), default='platform_b')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'service_type': self.service_type,
            'service_name': self.service_name,
            'hubtel_commission_rate': float(self.hubtel_commission_rate),
            'admin_share': float(self.admin_share),
            'initiator_share': float(self.initiator_share),
            'is_active': self.is_active,
            'platform': self.platform
        }


# ============================================================
# REFUND REQUEST (NEW)
# ============================================================
class RefundRequest(db.Model):
    __tablename__ = 'refund_requests'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    order_id = db.Column(db.String(100), nullable=False)
    amount = db.Column(db.Float, default=0)
    charges = db.Column(db.Float, default=0)
    reason = db.Column(db.String(500), nullable=True)
    status = db.Column(db.String(20), default='pending')
    response_code = db.Column(db.String(10), nullable=True)
    external_transaction_id = db.Column(db.String(100), nullable=True)
    error_message = db.Column(db.String(500), nullable=True)
    platform = db.Column(db.String(20), default='platform_a')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)
    
    # ✅ Use back_populates to match User
    user = db.relationship('User', back_populates='refund_requests')

# ============================================================
# ADMIN LOG (NEW)
# ============================================================
class AdminLog(db.Model):
    __tablename__ = 'admin_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    admin_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    action = db.Column(db.String(50), nullable=False)
    target_id = db.Column(db.Integer, nullable=True)
    target_type = db.Column(db.String(50), nullable=True)
    details = db.Column(db.Text, nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)
    platform = db.Column(db.String(20), default='platform_a')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # ✅ Use back_populates instead of backref
    admin = db.relationship('User', back_populates='admin_logs')
    
    def to_dict(self):
        return {
            'id': self.id,
            'admin_id': self.admin_id,
            'admin_name': self.admin.username if self.admin else None,
            'action': self.action,
            'target_id': self.target_id,
            'target_type': self.target_type,
            'details': self.details,
            'ip_address': self.ip_address,
            'platform': self.platform,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
