# models.py
from datetime import datetime, timedelta
import jwt
import bcrypt
import uuid
from flask_sqlalchemy import SQLAlchemy
from flask import current_app

db = SQLAlchemy()


# ========== COMPANY CONFIGURATION ==========
COMPANY_NAME = "Roamsmart Digital Service"
COMPANY_SHORT = "Roamsmart"
COMPANY_EMAIL = "support@roamsmart.shop"
COMPANY_PHONE = "0557388622"

class User(db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    phone = db.Column(db.String(20), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    
    # Role & Status
    role = db.Column(db.String(20), default='user')
    is_agent = db.Column(db.Boolean, default=False)
    agent_approved = db.Column(db.Boolean, default=False)
    agent_tier = db.Column(db.String(20), default='Bronze')
    commission_rate = db.Column(db.Integer, default=10)
    is_suspended = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    
    # ========== SECURITY FIELDS ==========
    failed_login_attempts = db.Column(db.Integer, default=0)
    locked_until = db.Column(db.DateTime, nullable=True)
    last_ip_address = db.Column(db.String(45), nullable=True)
    account_created_ip = db.Column(db.String(45), nullable=True)
    
    # Wallet
    wallet_balance = db.Column(db.Float, default=0.0)
    
    # ========== POINTS SYSTEM ==========
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
    
    # ========== ALL RELATIONSHIPS DEFINED HERE (ONLY ONCE) ==========
    # Existing relationships
    transactions = db.relationship('Transaction', backref='user', lazy=True)
    agent_requests = db.relationship('AgentRequest', backref='user', lazy=True)
    manual_payments = db.relationship('ManualPayment', backref='user', lazy=True)
    notifications = db.relationship('Notification', backref='user', lazy=True)
    store = db.relationship('Store', backref='agent', uselist=False, lazy=True)
    store_clients = db.relationship('StoreClient', backref='agent', lazy=True)
    sessions = db.relationship('UserSession', backref='user', lazy=True)
    
    # ========== NEW POINTS RELATIONSHIPS ==========
    # Define the relationships here - the child models should NOT have backrefs
    points_transactions = db.relationship('PointsTransaction', backref='user', lazy=True)
    points_redemptions = db.relationship('PointsRedemption', backref='user', lazy=True)
    
    # ========== REFERRAL RELATIONSHIPS ==========
    # Use unique backref names to avoid conflicts
    referrals_given = db.relationship('Referral', 
                                     foreign_keys='Referral.referrer_id', 
                                     backref='referrer_user', 
                                     lazy=True)
    
    referrals_received = db.relationship('Referral', 
                                        foreign_keys='Referral.referred_user_id', 
                                        backref='referred_user', 
                                        lazy=True)
    
    # ========== SECURITY METHODS ==========
    def increment_failed_attempts(self, ip_address=None):
        """Increment failed login attempts and lock account if needed"""
        from datetime import datetime, timedelta
        self.failed_login_attempts += 1
        if self.failed_login_attempts >= 5:
            self.locked_until = datetime.utcnow() + timedelta(minutes=30)
        if ip_address:
            self.last_ip_address = ip_address
        db.session.commit()
    
    def reset_failed_attempts(self):
        """Reset failed login attempts after successful login"""
        self.failed_login_attempts = 0
        self.locked_until = None
        db.session.commit()
    
    def is_locked(self):
        """Check if account is currently locked"""
        from datetime import datetime
        if self.locked_until and datetime.utcnow() < self.locked_until:
            return True
        return False
    
    def get_remaining_lockout_time(self):
        """Get remaining lockout time in minutes"""
        from datetime import datetime
        if self.locked_until and datetime.utcnow() < self.locked_until:
            return int((self.locked_until - datetime.utcnow()).seconds / 60)
        return 0
    
    # ========== POINTS METHODS ==========
    def add_points(self, points, type, description, reference=None):
        """Add points to user's balance"""
        if points <= 0:
            return False
        
        self.points_balance = (self.points_balance or 0) + points
        self.total_points_earned = (self.total_points_earned or 0) + points
        
        # Create points transaction
        transaction = PointsTransaction(
            user_id=self.id,
            points=points,
            type=type,
            description=description,
            reference=reference,
            balance_after=self.points_balance
        )
        db.session.add(transaction)
        db.session.commit()
        return True
    
    def deduct_points(self, points, type, description, reference=None):
        """Deduct points from user's balance"""
        if points <= 0:
            return False
        
        if (self.points_balance or 0) < points:
            return False
        
        self.points_balance -= points
        self.total_points_redeemed = (self.total_points_redeemed or 0) + points
        
        # Create points transaction
        transaction = PointsTransaction(
            user_id=self.id,
            points=-points,
            type=type,
            description=description,
            reference=reference,
            balance_after=self.points_balance
        )
        db.session.add(transaction)
        db.session.commit()
        return True
    
    def get_points_value(self):
        """Get current points value in GHS"""
        return (self.points_balance or 0) / POINTS_CONFIG['POINTS_TO_GHS_RATE']
    
    def can_redeem_points(self, points):
        """Check if user can redeem points"""
        if points < POINTS_CONFIG['MIN_REDEMPTION_POINTS']:
            return False, f"Minimum redemption is {POINTS_CONFIG['MIN_REDEMPTION_POINTS']} points"
        if points > POINTS_CONFIG['MAX_REDEMPTION_POINTS']:
            return False, f"Maximum redemption is {POINTS_CONFIG['MAX_REDEMPTION_POINTS']} points"
        if (self.points_balance or 0) < points:
            return False, f"Insufficient points. You have {self.points_balance} points"
        return True, "OK"
    
    def set_password(self, password):
        """Set password hash"""
        self.password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    def check_password(self, password):
        """Check password hash"""
        if not self.password_hash:
            return False
        try:
            return bcrypt.checkpw(password.encode('utf-8'), self.password_hash.encode('utf-8'))
        except Exception as e:
            print(f"Password check error: {e}")
            return False
    
    def generate_token(self):
        """Generate JWT token with 2-hour expiry"""
        try:
            payload = {
                'user_id': self.id,
                'email': self.email,
                'role': self.role,
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
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_login': self.last_login.isoformat() if self.last_login else None
        }
    
    def generate_email_verification_token(self):
        """Generate a unique token for email verification"""
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
        """Verify email verification token"""
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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', foreign_keys=[user_id])

class PendingTransaction(db.Model):
    __tablename__ = 'pending_transactions'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    reference = db.Column(db.String(100), unique=True, nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    payment_method = db.Column(db.String(50), default='paystack')
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
    
    def to_dict(self):
        return {
            'id': self.id,
            'network': self.network,
            'size_gb': self.size_gb,
            'retail_price': self.retail_price,
            'agent_price': self.agent_price,
            'wholesale_price': self.wholesale_price,
            'popular': self.popular,
            'is_active': self.is_active
        }



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
    
    user = db.relationship('User', backref='recurring_bills')

class DeliveryLog(db.Model):
    __tablename__ = 'delivery_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    phone_number = db.Column(db.String(20), nullable=False)
    message = db.Column(db.Text)
    status = db.Column(db.String(50), default='pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    delivered_at = db.Column(db.DateTime, nullable=True)
# models.py - Add this class

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

# models.py - Add this class

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
    
class PriceSetting(db.Model):
    __tablename__ = 'price_settings'
    
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(50), nullable=False)  # user_price, agent_price
    network = db.Column(db.String(50), nullable=True)
    size_gb = db.Column(db.Integer, nullable=True)
    delivery_type = db.Column(db.String(50), nullable=True)  # express, master, standard, mashup_voice, mashup_data
    exam_type = db.Column(db.String(50), nullable=True)
    tier = db.Column(db.String(50), nullable=True)
    price = db.Column(db.Numeric(10, 2), nullable=True)
    rate = db.Column(db.Numeric(5, 2), nullable=True)
    is_available = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
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
# ========== TRANSACTION MODEL ==========
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
    
    # Metadata
    meta_data = db.Column(db.JSON, nullable=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)  # Add this line
    
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
            'updated_at': self.updated_at.isoformat() if self.updated_at else None  # Add this line
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
    offer_slug = db.Column(db.String(100), nullable=True)  # <-- ADD THIS
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
            'offer_slug': self.offer_slug,  # <-- ADD THIS
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

class AdminLog(db.Model):
    __tablename__ = 'admin_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    admin_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    action = db.Column(db.String(50), nullable=False)  # 'update_user', 'delete_user', 'approve_agent', etc.
    target_id = db.Column(db.Integer, nullable=True)
    target_type = db.Column(db.String(50), nullable=True)  # 'user', 'agent', 'order', etc.
    details = db.Column(db.Text, nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    admin = db.relationship('User', foreign_keys=[admin_id], backref='admin_logs')
    
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
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

# ========== AGENT REQUEST MODEL ==========
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

# ========== MANUAL PAYMENT MODEL ==========
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

# ========== NOTIFICATION MODEL ==========
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
    custom_prices = db.Column(db.JSON, nullable=True)      # Original column
    custom_products = db.Column(db.JSON, nullable=True)    # New column (add this)
    is_active = db.Column(db.Boolean, default=True)
    total_sales = db.Column(db.Float, default=0.0)
    total_orders = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
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
            'custom_products': self.custom_products,  # Add this
            'is_active': self.is_active,
            'total_sales': self.total_sales,
            'total_orders': self.total_orders,
            'store_url': f"/store/{self.store_slug}"
        }

# models.py - Add this model
class PackageAvailability(db.Model):
    __tablename__ = 'package_availability'
    
    id = db.Column(db.Integer, primary_key=True)
    network = db.Column(db.String(50), nullable=False)
    size_gb = db.Column(db.Float, nullable=False)
    is_available = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    
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
    default_markup = db.Column(db.Numeric(5, 2), default=15.00)  # Add this
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    agent = db.relationship('User', backref='agent_store')

# ========== STORE CLIENT MODEL ==========
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

class Referral(db.Model):
    __tablename__ = 'referrals'
    
    id = db.Column(db.Integer, primary_key=True)
    referrer_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    referred_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    referral_code = db.Column(db.String(20), nullable=False)
    status = db.Column(db.String(20), default='pending')  # pending, completed, paid
    points_earned = db.Column(db.Integer, default=1)  # 1 point per referral
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)
    
   

class PointsTransaction(db.Model):
    __tablename__ = 'points_transactions'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    points = db.Column(db.Integer, nullable=False)
    type = db.Column(db.String(30), nullable=False)  # referral_bonus, redemption, adjustment
    description = db.Column(db.String(255), nullable=True)
    reference = db.Column(db.String(50), nullable=True)
    balance_after = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    


class PointsRedemption(db.Model):
    __tablename__ = 'points_redemptions'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    points_used = db.Column(db.Integer, nullable=False)
    redeemed_value = db.Column(db.Float, nullable=False)  # GHS value
    redemption_type = db.Column(db.String(30), nullable=False)  # data_bundle, bill_payment
    details = db.Column(db.JSON, nullable=True)  # network, size_gb, biller_code, etc.
    status = db.Column(db.String(20), default='pending')  # pending, completed, failed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)
    
    
    
class Customer(db.Model):
    """Customer model for agents to track their customers"""
    __tablename__ = 'customers'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    phone = db.Column(db.String(20), nullable=False)
    email = db.Column(db.String(100))
    agent_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # Statistics
    total_spent = db.Column(db.Numeric(10, 2), default=0)
    order_count = db.Column(db.Integer, default=0)
    last_purchase = db.Column(db.DateTime)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    agent = db.relationship('User', backref=db.backref('customers', lazy=True))
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'phone': self.phone,
            'email': self.email,
            'total_spent': float(self.total_spent) if self.total_spent else 0,
            'order_count': self.order_count,
            'last_purchase': self.last_purchase.isoformat() if self.last_purchase else None,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

# models.py - Add these model classes

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
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class CommissionRate(db.Model):
    __tablename__ = 'commission_rates'
    
    id = db.Column(db.Integer, primary_key=True)
    service_type = db.Column(db.String(50), unique=True, nullable=False)
    service_name = db.Column(db.String(100), nullable=False)
    hubtel_commission_rate = db.Column(db.Numeric(5, 4), nullable=False)
    admin_share = db.Column(db.Numeric(5, 2), default=30.00)
    initiator_share = db.Column(db.Numeric(5, 2), default=70.00)
    is_active = db.Column(db.Boolean, default=True)
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
            'is_active': self.is_active
        }


class RefundRequest(db.Model):
    __tablename__ = 'refund_requests'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    order_id = db.Column(db.String(100), nullable=False)  # Hubtel Order ID
    amount = db.Column(db.Float, default=0)
    charges = db.Column(db.Float, default=0)
    reason = db.Column(db.String(500), nullable=True)
    status = db.Column(db.String(20), default='pending')
    response_code = db.Column(db.String(10), nullable=True)
    external_transaction_id = db.Column(db.String(100), nullable=True)
    error_message = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)
    
    user = db.relationship('User', backref='refund_requests')

# ========== ANNOUNCEMENT MODEL ==========
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

# ========== KYC DOCUMENT MODEL ==========
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
    
    def to_dict(self):
        return {
            'id': self.id,
            'document_type': self.document_type,
            'document_number': self.document_number,
            'document_url': self.document_url,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

# ========== WEBHOOK MODEL ==========
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
    
    def to_dict(self):
        return {
            'id': self.id,
            'url': self.url,
            'events': self.events,
            'is_active': self.is_active,
            'last_triggered': self.last_triggered.isoformat() if self.last_triggered else None,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

# ========== BACKUP MODEL ==========
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
    
    def to_dict(self):
        return {
            'id': self.id,
            'filename': self.filename,
            'size': self.size,
            'type': self.type,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

# ========== USER SESSION MODEL ==========
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

# ========== SUPPORT TICKET MODEL ==========
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

# ========== NEWSLETTER SUBSCRIBER MODEL ==========
class NewsletterSubscriber(db.Model):
    __tablename__ = 'newsletter_subscribers'
    
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    
    # Timestamps
    subscribed_at = db.Column(db.DateTime, default=datetime.utcnow)
    unsubscribed_at = db.Column(db.DateTime, nullable=True)
    
    def to_dict(self):
        return {
            'id': self.id,
            'email': self.email,
            'subscribed_at': self.subscribed_at.isoformat() if self.subscribed_at else None
        }

# ========== ACTIVITY LOG MODEL ==========
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

# ========== NETWORK PROVIDER MODEL ==========
class NetworkProvider(db.Model):
    __tablename__ = 'network_providers'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)  # MTN, Telecel, AirtelTigo
    api_key = db.Column(db.String(500), nullable=True)
    api_secret = db.Column(db.String(500), nullable=True)
    api_endpoint = db.Column(db.String(500), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    last_sync = db.Column(db.DateTime, nullable=True)

# ========== MASTER INVENTORY MODEL ==========
# Update MasterInventory model in models.py - add sold_to_users column

class MasterInventory(db.Model):
    __tablename__ = 'master_inventories'
    
    id = db.Column(db.Integer, primary_key=True)
    network = db.Column(db.String(50), nullable=False)
    size_gb = db.Column(db.Integer, nullable=False)
    total_purchased = db.Column(db.Integer, default=0)
    remaining = db.Column(db.Integer, default=0)
    sold_to_agents = db.Column(db.Integer, default=0)
    sold_to_users = db.Column(db.Integer, default=0)  # Add this
    last_purchase_date = db.Column(db.DateTime, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
# ========== AGENT INVENTORY MODEL ==========
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

# ========== INVENTORY TRANSACTION MODEL ==========
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

# ========== LOYALTY POINTS MODEL ==========
class LoyaltyPoints(db.Model):
    __tablename__ = 'loyalty_points'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    points = db.Column(db.Integer, default=0)
    lifetime_points = db.Column(db.Integer, default=0)
    tier = db.Column(db.String(20), default='Bronze')
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ========== AGENT APPLICATION MODEL ==========
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

# ========== WAEC VOUCHER MODEL ==========
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

# ========== BILL PAYMENT MODEL ==========
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
    
    user = db.relationship('User', backref='bill_payments')

# ========== BILLER MODEL ==========
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

# ========== SMS LOG MODEL ==========
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

# ========== EMAIL LOG MODEL ==========
class EmailLog(db.Model):
    __tablename__ = 'email_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    recipient = db.Column(db.String(255), nullable=False)
    subject = db.Column(db.String(500), nullable=False)
    status = db.Column(db.String(20))
    error = db.Column(db.Text)
    sent_at = db.Column(db.DateTime, default=datetime.utcnow)

# ========== SYSTEM SETTING MODEL ==========
# models.py - Add to SystemSetting class

class SystemSetting(db.Model):
    __tablename__ = 'system_settings'
    
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.Text)
    value_type = db.Column(db.String(20), default='string')
    description = db.Column(db.String(500))
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    
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

# ========== NOTIFICATION TEMPLATE MODEL ==========
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

# ========== CONTACT MESSAGE MODEL ==========
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

# ========== FAQ MODEL ==========
class FAQ(db.Model):
    __tablename__ = 'faqs'
    
    id = db.Column(db.Integer, primary_key=True)
    question = db.Column(db.String(500), nullable=False)
    answer = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(100))
    order = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# ========== TESTIMONIAL MODEL ==========




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