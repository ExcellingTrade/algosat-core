"""
Security utilities for Algosat trading system.
Provides encryption, authentication, and secure credential management.
Enhanced for production VPS deployment with comprehensive security features.
"""
import os
import sys
import base64
import secrets
import hashlib
import hmac
import logging
import asyncio
import ipaddress
import sqlite3
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Set
from pathlib import Path
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import bcrypt
import jwt
from functools import wraps
import aiofiles
import re
from collections import defaultdict
import json
from pydantic import BaseModel, EmailStr # Add EmailStr
from passlib.context import CryptContext
from algosat.core.dbschema import users
from algosat.core.db import AsyncSessionLocal, get_user_by_username

logger = logging.getLogger(__name__)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

class SecurityError(Exception):
    """Custom exception for security-related errors."""
    pass

# Password Hashing Context
# Placeholder for database interaction or user store
# USERS_DB = {
#     "testuser": {"username": "testuser", "hashed_password": pwd_context.hash("testpassword"), "email": "testuser@example.com", "full_name": "Test User", "disabled": False}
# }

class User(BaseModel):
    username: str
    email: EmailStr | None = None
    full_name: str | None = None
    disabled: bool | None = None

class UserInDB(User):
    hashed_password: str

class InvalidInputError(ValueError):
    """Custom exception for invalid input."""
    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)

class EnhancedInputValidator:
    """Enhanced input validation for API endpoints."""
    
    def __init__(self):
        self.email_pattern = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
        self.username_pattern = re.compile(r'^[a-zA-Z0-9_]{3,50}$')
    
    def validate_string(self, value: str, field_name: str, min_length: int = 1, max_length: int = 255) -> str:
        """Validate string input."""
        if not isinstance(value, str):
            raise InvalidInputError(f"{field_name} must be a string")
        
        value = value.strip()
        if len(value) < min_length:
            raise InvalidInputError(f"{field_name} must be at least {min_length} characters")
        if len(value) > max_length:
            raise InvalidInputError(f"{field_name} must be at most {max_length} characters")
        
        return value
    
    def validate_email(self, email: str) -> str:
        """Validate email format."""
        email = self.validate_string(email, "email", max_length=254)
        if not self.email_pattern.match(email):
            raise InvalidInputError("Invalid email format")
        return email
    
    def validate_username(self, username: str) -> str:
        """Validate username format."""
        username = self.validate_string(username, "username", min_length=3, max_length=50)
        if not self.username_pattern.match(username):
            raise InvalidInputError("Username can only contain letters, numbers, and underscores")
        return username
    
    def validate_date(self, date_str: str) -> datetime.date:
        try:
            return datetime.strptime(date_str, "%Y-%m-%d").date()
        except Exception:
            raise ValueError("Invalid date format, expected YYYY-MM-DD")
    
    def validate_password(self, password: str) -> str:
        """Validate password strength."""
        if not isinstance(password, str):
            raise InvalidInputError("Password must be a string")
        
        if len(password) < 8:
            raise InvalidInputError("Password must be at least 8 characters")
        if len(password) > 128:
            raise InvalidInputError("Password must be at most 128 characters")
        
        return password
    
    def validate_id(self, id_value: str, field_name: str = "id") -> str:
        """Validate ID values."""
        return self.validate_string(id_value, field_name, min_length=1, max_length=100)
    
    def validate_and_sanitize(self, value, field_name: str, expected_type=str, min_length: int = 1, 
                            max_length: int = 255, pattern: str = None, allow_none: bool = False):
        """Comprehensive validation and sanitization method."""
        if value is None and allow_none:
            return None
            
        if value is None and not allow_none:
            raise InvalidInputError(f"{field_name} cannot be None")
            
        if expected_type == str:
            if not isinstance(value, str):
                raise InvalidInputError(f"{field_name} must be a string")
                
            value = value.strip()
            
            if len(value) < min_length:
                raise InvalidInputError(f"{field_name} must be at least {min_length} characters")
            if len(value) > max_length:
                raise InvalidInputError(f"{field_name} must be at most {max_length} characters")
            
            if pattern and not re.match(pattern, value):
                raise InvalidInputError(f"{field_name} format is invalid")
                
            return value
        else:
            # Handle other types as needed
            return value

    def validate_auth_input(self, data: dict) -> dict:
        """Validate authentication input data."""
        if not isinstance(data, dict):
            raise InvalidInputError("Request body must be a JSON object")
        
        if "username" not in data:
            raise InvalidInputError("Username is required")
        if "password" not in data:
            raise InvalidInputError("Password is required")
        
        username = self.validate_username(data["username"])
        password = self.validate_password(data["password"])
        
        return {
            "username": username,
            "password": password
        }

    @staticmethod
    def validate_and_sanitize_static(value, field_name: str, expected_type=str, min_length: int = 1, 
                            max_length: int = 255, pattern: str = None, allow_none: bool = False):
        """Static version for backward compatibility."""
        validator = EnhancedInputValidator()
        return validator.validate_and_sanitize(value, field_name, expected_type, min_length, max_length, pattern, allow_none)

    def validate_integer(self, value, field_name: str = "id", min_value: int = 1, max_value: int = 1_000_000_000):
        """Validate integer input for IDs and similar fields."""
        if not isinstance(value, int):
            raise InvalidInputError(f"{field_name} must be an integer")
        if value < min_value:
            raise InvalidInputError(f"{field_name} must be >= {min_value}")
        if value > max_value:
            raise InvalidInputError(f"{field_name} must be <= {max_value}")
        return value

class SecurityManager:
    """Centralized security management for the trading system."""
    
    def __init__(self, master_key: Optional[str] = None, data_dir: str = "/opt/algosat/data"):
        """Initialize security manager with encryption capabilities."""
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        self.master_key = master_key or os.getenv('ALGOSAT_MASTER_KEY')
        if not self.master_key:
            # Generate a new master key if none exists
            self.master_key = self._generate_master_key()
            logger.warning("Generated new master key. Store securely: ALGOSAT_MASTER_KEY")
        
        self.cipher_suite = self._init_cipher()
        self.jwt_secret = os.getenv('JWT_SECRET', secrets.token_urlsafe(32))
        
        # Initialize logger and config
        self.logger = logger
        self.config = {
            "jwt_secret_key": self.jwt_secret,
            "jwt_algorithm": "HS256",
            "jwt_expiry_minutes": int(os.getenv('JWT_EXPIRY_MINUTES', '60'))
        }
        
        # Initialize security databases
        self._init_security_db()
        self.failed_attempts = defaultdict(list)
        self.blocked_ips = set()
        
        # Security settings
        self.max_failed_attempts = int(os.getenv('MAX_FAILED_ATTEMPTS', '5'))
        self.lockout_duration = int(os.getenv('LOCKOUT_DURATION_MINUTES', '15'))
        self.session_timeout = int(os.getenv('SESSION_TIMEOUT_SECONDS', '3600'))
    
    def _init_security_db(self):
        """Initialize SQLite database for security events."""
        self.security_db_path = self.data_dir / "security.db"
        conn = sqlite3.connect(str(self.security_db_path))
        cursor = conn.cursor()
        
        # Create security events table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS security_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                event_type TEXT NOT NULL,
                ip_address TEXT,
                user_id TEXT,
                details TEXT,
                severity TEXT DEFAULT 'INFO'
            )
        """)
        
        # Create API access logs table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS api_access_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                ip_address TEXT NOT NULL,
                endpoint TEXT NOT NULL,
                method TEXT NOT NULL,
                user_id TEXT,
                api_key_hash TEXT,
                success BOOLEAN DEFAULT TRUE,
                response_time_ms INTEGER
            )
        """)
        
        # Create rate limiting table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS rate_limits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ip_address TEXT NOT NULL,
                endpoint TEXT NOT NULL,
                request_count INTEGER DEFAULT 1,
                window_start DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(ip_address, endpoint, window_start)
            )
        """)
        
        conn.commit()
        conn.close()
        
    def log_security_event(self, event_type: str, ip_address: str = None, 
                          user_id: str = None, details: str = None, 
                          severity: str = "INFO"):
        """Log security event to database."""
        try:
            conn = sqlite3.connect(str(self.security_db_path))
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO security_events 
                (event_type, ip_address, user_id, details, severity)
                VALUES (?, ?, ?, ?, ?)
            """, (event_type, ip_address, user_id, details, severity))
            conn.commit()
            conn.close()
            
            if severity in ['WARNING', 'ERROR', 'CRITICAL']:
                logger.warning(f"Security event: {event_type} - {details}")
                
        except Exception as e:
            logger.error(f"Failed to log security event: {e}")
    
    async def check_rate_limit(self, ip_address: str, endpoint: str, 
                        max_requests: int = 100, window_seconds: int = 60) -> bool:
        """Check if request is within rate limits."""
        try:
            conn = sqlite3.connect(str(self.security_db_path))
            cursor = conn.cursor()
            
            current_time = datetime.utcnow()
            window_start = current_time - timedelta(seconds=window_seconds)
            
            # Clean old entries
            cursor.execute("""
                DELETE FROM rate_limits 
                WHERE window_start < ?
            """, (window_start,))
            
            # Count current requests
            cursor.execute("""
                SELECT SUM(request_count) FROM rate_limits
                WHERE ip_address = ? AND endpoint = ? AND window_start >= ?
            """, (ip_address, endpoint, window_start))
            
            result = cursor.fetchone()
            current_count = result[0] if result[0] else 0
            
            if current_count >= max_requests:
                conn.close()
                self.log_security_event(
                    "RATE_LIMIT_EXCEEDED", 
                    ip_address=ip_address,
                    details=f"Endpoint: {endpoint}, Count: {current_count}",
                    severity="WARNING"
                )
                return False
            
            # Increment counter
            cursor.execute("""
                INSERT OR REPLACE INTO rate_limits 
                (ip_address, endpoint, request_count, window_start)
                VALUES (?, ?, COALESCE((
                    SELECT request_count FROM rate_limits 
                    WHERE ip_address = ? AND endpoint = ? AND window_start >= ?
                ), 0) + 1, ?)
            """, (ip_address, endpoint, ip_address, endpoint, window_start, current_time))
            
            conn.commit()
            conn.close()
            return True
            
        except Exception as e:
            logger.error(f"Rate limiting check failed: {e}")
            return True  # Allow on error to avoid blocking legitimate requests
            
    
    def is_ip_blocked(self, ip_address: str) -> bool:
        """Check if IP address is currently blocked."""
        if ip_address in self.blocked_ips:
            return True
            
        # Check failed attempts
        now = datetime.utcnow()
        recent_failures = [
            attempt for attempt in self.failed_attempts[ip_address]
            if now - attempt < timedelta(minutes=self.lockout_duration)
        ]
        
        if len(recent_failures) >= self.max_failed_attempts:
            self.blocked_ips.add(ip_address)
            self.log_security_event(
                "IP_BLOCKED",
                ip_address=ip_address,
                details=f"Too many failed attempts: {len(recent_failures)}",
                severity="WARNING"
            )
            return True
            
        return False
    
    def record_failed_attempt(self, ip_address: str, user_id: str = None):
        """Record a failed authentication attempt."""
        self.failed_attempts[ip_address].append(datetime.utcnow())
        self.log_security_event(
            "AUTH_FAILURE",
            ip_address=ip_address,
            user_id=user_id,
            severity="WARNING"
        )
    
    def clear_failed_attempts(self, ip_address: str):
        """Clear failed attempts for successful authentication."""
        if ip_address in self.failed_attempts:
            del self.failed_attempts[ip_address]
        if ip_address in self.blocked_ips:
            self.blocked_ips.remove(ip_address)
    
    def validate_ip_whitelist(self, ip_address: str) -> bool:
        """Validate if IP is in whitelist (if configured)."""
        whitelist = os.getenv('IP_WHITELIST', '').split(',')
        if not whitelist or whitelist == ['']:
            return True  # No whitelist configured
            
        try:
            client_ip = ipaddress.ip_address(ip_address)
            for allowed in whitelist:
                allowed = allowed.strip()
                if not allowed:
                    continue
                    
                # Check if it's a network or single IP
                if '/' in allowed:
                    if client_ip in ipaddress.ip_network(allowed, strict=False):
                        return True
                else:
                    if client_ip == ipaddress.ip_address(allowed):
                        return True
            return False
        except ValueError:
            logger.error(f"Invalid IP address format: {ip_address}")
            return False
        
    def _generate_master_key(self) -> str:
        """Generate a new master encryption key."""
        return base64.urlsafe_b64encode(os.urandom(32)).decode()
    
    def _init_cipher(self) -> Fernet:
        """Initialize Fernet cipher for encryption/decryption."""
        key = base64.urlsafe_b64encode(self.master_key.encode()[:32].ljust(32, b'0'))
        return Fernet(key)
    
    def encrypt_credentials(self, credentials: Dict[str, Any]) -> str:
        """Encrypt broker credentials securely."""
        try:
            import json
            credentials_json = json.dumps(credentials)
            encrypted_data = self.cipher_suite.encrypt(credentials_json.encode())
            return base64.urlsafe_b64encode(encrypted_data).decode()
        except Exception as e:
            logger.error(f"Failed to encrypt credentials: {e}")
            raise SecurityError("Credential encryption failed")
    
    def decrypt_credentials(self, encrypted_credentials: str) -> Dict[str, Any]:
        """Decrypt broker credentials securely."""
        try:
            import json
            encrypted_data = base64.urlsafe_b64decode(encrypted_credentials.encode())
            decrypted_data = self.cipher_suite.decrypt(encrypted_data)
            return json.loads(decrypted_data.decode())
        except Exception as e:
            logger.error(f"Failed to decrypt credentials: {e}")
            raise SecurityError("Credential decryption failed")
    
    def hash_password(self, password: str) -> str:
        """Hash password using bcrypt."""
        salt = bcrypt.gensalt()
        return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')
    
    def verify_password(self, password: str, hashed: str) -> bool:
        """Verify password against bcrypt hash."""
        return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))
    
    def generate_api_key(self, user_id: str) -> str:
        """Generate secure API key for user."""
        payload = {
            'user_id': user_id,
            'type': 'api_key',
            'generated_at': datetime.utcnow().isoformat(),
            'nonce': secrets.token_hex(16)
        }
        return jwt.encode(payload, self.jwt_secret, algorithm='HS256')
    
    def verify_api_key(self, api_key: str) -> Optional[Dict[str, Any]]:
        """Verify and decode API key."""
        try:
            payload = jwt.decode(api_key, self.jwt_secret, algorithms=['HS256'])
            return payload
        except jwt.InvalidTokenError:
            return None
    
    def generate_session_token(self, user_id: str, expires_in: int = 3600) -> str:
        """Generate session token with expiration."""
        payload = {
            'user_id': user_id,
            'type': 'session',
            'exp': datetime.utcnow() + timedelta(seconds=expires_in),
            'iat': datetime.utcnow()
        }
        return jwt.encode(payload, self.jwt_secret, algorithm='HS256')
    
    def verify_session_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Verify session token and check expiration."""
        try:
            payload = jwt.decode(token, self.jwt_secret, algorithms=['HS256'])
            return payload
        except jwt.ExpiredSignatureError:
            logger.warning("Session token expired")
            return None
        except jwt.InvalidTokenError:
            logger.warning("Invalid session token")
            return None
    
    def generate_hmac_signature(self, data: str, secret: str) -> str:
        """Generate HMAC signature for webhook validation."""
        return hmac.new(
            secret.encode('utf-8'),
            data.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
    
    def verify_hmac_signature(self, data: str, signature: str, secret: str) -> bool:
        """Verify HMAC signature."""
        expected_signature = self.generate_hmac_signature(data, secret)
        return hmac.compare_digest(signature, expected_signature)
    
    async def log_api_access(self, ip_address: str, endpoint: str, method: str,
                           user_id: str = None, api_key_hash: str = None,
                           success: bool = True, response_time_ms: int = None):
        """Log API access for audit trail."""
        try:
            conn = sqlite3.connect(str(self.security_db_path))
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO api_access_logs 
                (ip_address, endpoint, method, user_id, api_key_hash, success, response_time_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (ip_address, endpoint, method, user_id, api_key_hash, success, response_time_ms))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to log API access: {e}")
    
    def get_security_summary(self, hours: int = 24) -> Dict[str, Any]:
        """Get security summary for the last N hours."""
        try:
            conn = sqlite3.connect(str(self.security_db_path))
            cursor = conn.cursor()
            
            cutoff_time = datetime.utcnow() - timedelta(hours=hours)
            
            # Get security events summary
            cursor.execute("""
                SELECT event_type, severity, COUNT(*) as count
                FROM security_events 
                WHERE timestamp >= ?
                GROUP BY event_type, severity
                ORDER BY count DESC
            """, (cutoff_time,))
            
            events = cursor.fetchall()
            
            # Get API access summary
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_requests,
                    SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successful_requests,
                    AVG(response_time_ms) as avg_response_time,
                    COUNT(DISTINCT ip_address) as unique_ips
                FROM api_access_logs 
                WHERE timestamp >= ?
            """, (cutoff_time,))
            
            api_summary = cursor.fetchone()
            
            # Get top IPs by request count
            cursor.execute("""
                SELECT ip_address, COUNT(*) as request_count
                FROM api_access_logs 
                WHERE timestamp >= ?
                GROUP BY ip_address
                ORDER BY request_count DESC
                LIMIT 10
            """, (cutoff_time,))
            
            top_ips = cursor.fetchall()
            
            conn.close()
            
            return {
                'time_period_hours': hours,
                'security_events': [
                    {'type': event[0], 'severity': event[1], 'count': event[2]}
                    for event in events
                ],
                'api_summary': {
                    'total_requests': api_summary[0] or 0,
                    'successful_requests': api_summary[1] or 0,
                    'success_rate': (api_summary[1] or 0) / max(api_summary[0] or 1, 1) * 100,
                    'avg_response_time_ms': api_summary[2] or 0,
                    'unique_ips': api_summary[3] or 0
                },
                'top_ips': [
                    {'ip': ip[0], 'request_count': ip[1]}
                    for ip in top_ips
                ]
            }
            
        except Exception as e:
            logger.error(f"Failed to get security summary: {e}")
            return {}
    
    def cleanup_old_data(self, retention_days: int = 30):
        """Cleanup old security and access log data."""
        try:
            conn = sqlite3.connect(str(self.security_db_path))
            cursor = conn.cursor()
            
            cutoff_time = datetime.utcnow() - timedelta(days=retention_days)
            
            # Clean security events
            cursor.execute("DELETE FROM security_events WHERE timestamp < ?", (cutoff_time,))
            events_deleted = cursor.rowcount
            
            # Clean API access logs
            cursor.execute("DELETE FROM api_access_logs WHERE timestamp < ?", (cutoff_time,))
            logs_deleted = cursor.rowcount
            
            # Clean rate limit data
            cursor.execute("DELETE FROM rate_limits WHERE window_start < ?", (cutoff_time,))
            rate_limits_deleted = cursor.rowcount
            
            conn.commit()
            conn.close()
            
            logger.info(f"Cleaned up old data: {events_deleted} events, {logs_deleted} logs, {rate_limits_deleted} rate limits")
            
        except Exception as e:
            logger.error(f"Failed to cleanup old data: {e}")
    
    async def authenticate_user(self, username: str, password: str, request_info: Dict[str, Any]) -> Dict[str, Any]:
        """Authenticate user and return token if successful."""
        user_record = await self._get_user(username)
        if not user_record:
            self.logger.warning(
                f"Authentication failed - invalid user: {username}, ip: {request_info.get('ip')}"
            )
            return {"success": False, "message": "Invalid username or password"}
        if self._verify_password(password, user_record["password_hash"]):
            user_info = {
                "user_id": user_record["user_id"],
                "username": username,
                "role": user_record.get("role", "user"),
                "email": user_record.get("email", "")
            }
            token_duration = timedelta(minutes=self.config.get("jwt_expiry_minutes", 60))
            token_str, expires_in_seconds = self._create_jwt_token(user_info, expires_delta=token_duration)
            self.logger.info(
                f"User authenticated successfully - username: {username}, "
                f"ip: {request_info.get('ip')}, user_agent: {request_info.get('user_agent')}"
            )
            return {
                "success": True,
                "token": token_str,
                "expires_in": expires_in_seconds,
                "user_info": user_info
            }
        else:
            self.logger.warning(
                f"Authentication failed - invalid password for user: {username}, ip: {request_info.get('ip')}"
            )
            return {"success": False, "message": "Invalid username or password"}

    async def regenerate_token(self, user_info: Dict[str, Any], expires_delta: timedelta) -> tuple[str, int]:
        """Regenerate JWT token with a new expiry."""
        if not user_info or "user_id" not in user_info:
            self.logger.warning(f"Attempted to regenerate token for invalid user_info: {user_info}")
            raise ValueError("Valid user_info with user_id is required to regenerate token")

        token_str, expires_in_seconds = self._create_jwt_token(user_info, expires_delta)
        self.logger.info(f"Token regenerated for user_id: {user_info['user_id']}, expires in: {expires_in_seconds} seconds")
        return token_str, expires_in_seconds

    def _create_jwt_token(self, data: Dict[str, Any], expires_delta: timedelta) -> tuple[str, int]:
        """Helper to create JWT token."""
        to_encode = data.copy()
        expire = datetime.utcnow() + expires_delta
        to_encode.update({"exp": expire})
        # Ensure JWT_SECRET_KEY is loaded, ideally from a secure config
        secret_key = self.config.get("jwt_secret_key", "a_very_secret_key_that_should_be_in_config")
        if secret_key == "a_very_secret_key_that_should_be_in_config":
            self.logger.warning("Using default JWT secret key. THIS IS NOT SECURE FOR PRODUCTION.")
        encoded_jwt = jwt.encode(to_encode, secret_key, algorithm=self.config.get("jwt_algorithm", "HS256"))
        expires_in_seconds = int(expires_delta.total_seconds())
        return encoded_jwt, expires_in_seconds

    async def validate_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Validate JWT token and return user info."""
        try:
            # Ensure JWT_SECRET_KEY is loaded
            secret_key = self.config.get("jwt_secret_key", "a_very_secret_key_that_should_be_in_config")
            payload = jwt.decode(token, secret_key, algorithms=[self.config.get("jwt_algorithm", "HS256")])
            # Perform additional checks if needed (e.g., token revocation list)
            # For now, just return the payload as user_info
            # Ensure essential fields like user_id and username are present
            if "user_id" not in payload or "username" not in payload:
                self.logger.warning(f"Token validation failed: missing essential user fields in payload: {payload}")
                return None
            return payload
        except jwt.ExpiredSignatureError:
            self.logger.info("Token validation failed: Expired signature")
            return None
        except jwt.InvalidTokenError as e:
            self.logger.warning(f"Token validation failed: Invalid token - {str(e)}")
            return None
        except Exception as e:
            self.logger.error(f"Unexpected error during token validation: {str(e)}", exc_info=True)
            return None
    
    async def _get_user(self, username: str) -> Optional[Dict[str, Any]]:
        """Get user from database or storage."""
        async with AsyncSessionLocal() as session:
            db_user = await get_user_by_username(session, username)
            if db_user:
                return {
                    "user_id": db_user["id"],
                    "username": db_user["username"],
                    "password_hash": db_user["hashed_password"],
                    "email": db_user["email"],
                    "role": db_user["role"],
                }
            return None
    
    def _verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """Verify password against hash."""
        return pwd_context.verify(plain_password, hashed_password)
    
    async def validate_request(self, request) -> bool:
        """Validate request for security checks."""
        # Basic request validation - can be expanded
        return True
    
    async def logout_user(self, user_id: str) -> bool:
        """Logout user by invalidating their session."""
        try:
            # Log the logout event for audit trail
            self.logger.info(f"User logout requested for user_id: {user_id}")
            
            # In a real-world scenario, you might want to:
            # 1. Add token to blacklist/revocation list
            # 2. Clear user sessions from Redis/cache
            # 3. Log security event
            
            # For now, we'll just log the event and return success
            # The actual token invalidation happens on the client side
            # by clearing localStorage
            
            # Log security event
            try:
                conn = sqlite3.connect(str(self.security_db_path))
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO security_events 
                    (event_type, description, severity, user_id, timestamp) 
                    VALUES (?, ?, ?, ?, ?)
                """, ("logout", f"User {user_id} logged out", "INFO", user_id, datetime.utcnow()))
                conn.commit()
                conn.close()
            except Exception as e:
                self.logger.warning(f"Failed to log logout event: {e}")
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error during logout for user {user_id}: {e}")
            return False