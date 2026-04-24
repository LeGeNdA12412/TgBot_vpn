"""Utility functions for VPN Bot with Marzban integration"""

import string
import random
import hashlib
import logging
import os
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import qrcode
from io import BytesIO
import base64

from bot.utils.marzban_api import marzban_api

logger = logging.getLogger(__name__)


def setup_logging():
    """Setup logging configuration"""
    from bot.config.settings import Config
    
    # Create logs directory if not exists
    os.makedirs('logs', exist_ok=True)
    
    # Configure logging
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    log_level = getattr(logging, Config.LOG_LEVEL.upper(), logging.INFO)
    
    # File handler
    file_handler = logging.FileHandler(
        f'logs/vpn_bot_{datetime.now().strftime("%Y%m%d")}.log',
        encoding='utf-8'
    )
    file_handler.setFormatter(logging.Formatter(log_format))
    file_handler.setLevel(log_level)
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(log_format))
    console_handler.setLevel(log_level)
    
    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    
    # Suppress noisy libraries
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('requests').setLevel(logging.WARNING)


def generate_referral_code(length: int = 8) -> str:
    """Generate unique referral code"""
    chars = string.ascii_uppercase + string.digits
    return ''.join(random.choice(chars) for _ in range(length))


def generate_vpn_config(user_id: int, plan_type: str = "1_month", server_location: str = "default") -> Optional[Dict[str, Any]]:
    """Generate VPN configuration using Marzban API"""
    try:
        # Generate unique username for Marzban
        username = f"user_{user_id}_{plan_type}_{int(datetime.utcnow().timestamp())}"

        # Calculate subscription end date
        end_date = calculate_end_date(plan_type)

        # Create user in Marzban
        user_data = marzban_api.create_user(
            username=username,
            data_limit=0,  # Unlimited data
            expire_date=end_date
        )

        if not user_data:
            logger.error(f"Failed to create Marzban user for user_id {user_id}")
            return None

        # Get user configuration
        config_data = marzban_api.get_user_config(username)

        if not config_data:
            logger.error(f"Failed to get config for Marzban user {username}")
            return None

        return {
            'username': username,
            'config_data': config_data,
            'end_date': end_date,
            'server_location': server_location
        }

    except Exception as e:
        logger.error(f"Error generating VPN config for user {user_id}: {e}")
        return None


def get_user_vpn_config(username: str) -> Optional[Dict[str, Any]]:
    """Get user's VPN configuration from Marzban"""
    try:
        return marzban_api.get_user_config(username)
    except Exception as e:
        logger.error(f"Error getting VPN config for user {username}: {e}")
        return None


def extend_user_subscription(username: str, new_end_date: datetime) -> bool:
    """Extend user subscription in Marzban"""
    try:
        return marzban_api.update_user(username=username, expire_date=new_end_date)
    except Exception as e:
        logger.error(f"Error extending subscription for user {username}: {e}")
        return False


def deactivate_user_subscription(username: str) -> bool:
    """Deactivate user subscription in Marzban"""
    try:
        return marzban_api.update_user(username=username, status='disabled')
    except Exception as e:
        logger.error(f"Error deactivating subscription for user {username}: {e}")
        return False


def reactivate_user_subscription(username: str, new_end_date: Optional[datetime] = None) -> bool:
    """Reactivate user subscription in Marzban"""
    try:
        return marzban_api.update_user(username=username, status='active', expire_date=new_end_date)
    except Exception as e:
        logger.error(f"Error reactivating subscription for user {username}: {e}")
        return False


def delete_user_from_vpn(username: str) -> bool:
    """Delete user from Marzban"""
    try:
        return marzban_api.delete_user(username)
    except Exception as e:
        logger.error(f"Error deleting user {username} from VPN: {e}")
        return False


def get_user_vpn_usage(username: str) -> Optional[Dict[str, Any]]:
    """Get user's VPN usage statistics"""
    try:
        return marzban_api.get_user_usage(username)
    except Exception as e:
        logger.error(f"Error getting usage for user {username}: {e}")
        return None


def reset_user_data_usage(username: str) -> bool:
    """Reset user's data usage in Marzban"""
    try:
        return marzban_api.reset_user_data_usage(username)
    except Exception as e:
        logger.error(f"Error resetting data usage for user {username}: {e}")
        return False


def create_qr_code(data: str) -> BytesIO:
    """Create QR code from data"""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(data)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    img_buffer = BytesIO()
    img.save(img_buffer, format='PNG')
    img_buffer.seek(0)
    return img_buffer


def format_marzban_config(config_data: Dict[str, Any], protocol: str = 'vless') -> str:
    """Format Marzban configuration for display"""
    try:
        if protocol not in config_data:
            # Return first available protocol
            protocol = list(config_data.keys())[0]

        protocol_config = config_data[protocol]

        if protocol == 'vless':
            # VLESS format
            return f"""vless://{protocol_config.get('id', '')}@{protocol_config.get('server', '')}:{protocol_config.get('port', 443)}?type={protocol_config.get('type', 'tcp')}&security={protocol_config.get('security', 'tls')}&pbk={protocol_config.get('pbk', '')}&fp={protocol_config.get('fp', 'random')}&sni={protocol_config.get('sni', '')}&sid={protocol_config.get('sid', '')}&spx={protocol_config.get('spx', '')}#{protocol_config.get('server', 'VPN')}"""

        elif protocol == 'vmess':
            # VMess format
            vmess_config = {
                "v": "2",
                "ps": protocol_config.get('server', 'VPN'),
                "add": protocol_config.get('server', ''),
                "port": str(protocol_config.get('port', 443)),
                "id": protocol_config.get('id', ''),
                "aid": "0",
                "net": protocol_config.get('type', 'tcp'),
                "type": "none",
                "host": protocol_config.get('host', ''),
                "path": protocol_config.get('path', ''),
                "tls": "tls" if protocol_config.get('security') == 'tls' else ""
            }
            import base64
            return f"vmess://{base64.b64encode(json.dumps(vmess_config).encode()).decode()}"

        elif protocol == 'trojan':
            # Trojan format
            return f"""trojan://{protocol_config.get('password', '')}@{protocol_config.get('server', '')}:{protocol_config.get('port', 443)}?type={protocol_config.get('type', 'tcp')}&security={protocol_config.get('security', 'tls')}&fp={protocol_config.get('fp', 'random')}&sni={protocol_config.get('sni', '')}#{protocol_config.get('server', 'VPN')}"""

        elif protocol == 'shadowsocks':
            # Shadowsocks format
            import base64
            ss_config = f"{protocol_config.get('method', 'chacha20-ietf-poly1305')}:{protocol_config.get('password', '')}"
            encoded = base64.b64encode(ss_config.encode()).decode()
            return f"ss://{encoded}@{protocol_config.get('server', '')}:{protocol_config.get('port', 443)}#{protocol_config.get('server', 'VPN')}"

        return json.dumps(protocol_config, indent=2)

    except Exception as e:
        logger.error(f"Error formatting Marzban config: {e}")
        return json.dumps(config_data, indent=2)


def format_datetime(dt: datetime) -> str:
    """Format datetime for Russian locale"""
    return dt.strftime("%d.%m.%Y %H:%M")


def format_date(dt: datetime) -> str:
    """Format date for Russian locale"""
    return dt.strftime("%d.%m.%Y")


def format_time_ago(dt: datetime) -> str:
    """Format time ago in Russian"""
    now = datetime.utcnow()
    diff = now - dt
    
    if diff.days > 0:
        return f"{diff.days} дн. назад"
    elif diff.seconds > 3600:
        hours = diff.seconds // 3600
        return f"{hours} ч. назад"
    elif diff.seconds > 60:
        minutes = diff.seconds // 60
        return f"{minutes} мин. назад"
    else:
        return "только что"


def calculate_end_date(plan_type: str) -> datetime:
    """Calculate subscription end date based on plan"""
    from bot.config.settings import SUBSCRIPTION_PLANS
    
    plan = SUBSCRIPTION_PLANS.get(plan_type)
    if not plan:
        raise ValueError(f"Unknown plan type: {plan_type}")
    
    return datetime.utcnow() + timedelta(days=plan['duration_days'])


def is_admin(user_id: int) -> bool:
    """Check if user is admin"""
    from bot.config.settings import Config
    return user_id in Config.ADMIN_IDS


def format_currency(amount: int) -> str:
    """Format amount in kopecks to rubles"""
    return f"{amount / 100:.0f} ₽"


def generate_payment_id() -> str:
    """Generate unique payment ID"""
    timestamp = int(datetime.utcnow().timestamp())
    random_part = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"VPN_{timestamp}_{random_part}"


def validate_email(email: str) -> bool:
    """Validate email address"""
    import re
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None


def escape_markdown(text: str) -> str:
    """Escape markdown special characters"""
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
    return text


def truncate_text(text: str, max_length: int = 100) -> str:
    """Truncate text to specified length"""
    if len(text) <= max_length:
        return text
    return text[:max_length - 3] + "..."


def get_user_display_name(user) -> str:
    """Get user display name from telegram user object"""
    if user.first_name and user.last_name:
        return f"{user.first_name} {user.last_name}"
    elif user.first_name:
        return user.first_name
    elif user.username:
        return f"@{user.username}"
    else:
        return f"User {user.id}"


def calculate_referral_bonus(amount: int) -> int:
    """Calculate referral bonus amount"""
    from bot.config.settings import Config
    return int(amount * Config.REFERRAL_BONUS_PERCENT / 100)


def generate_config_filename(user_id: int, plan_type: str) -> str:
    """Generate VPN config filename"""
    timestamp = datetime.now().strftime("%Y%m%d")
    return f"vpn_config_{user_id}_{plan_type}_{timestamp}.conf"


def get_plan_emoji(plan_type: str) -> str:
    """Get emoji for plan type"""
    emojis = {
        '1_month': '🥉',
        '3_months': '🥈',
        '6_months': '🥇',
        '12_months': '💰'
    }
    return emojis.get(plan_type, '📦')


def get_server_flag(location: str) -> str:
    """Get flag emoji for server location"""
    flags = {
        "Netherlands": "🇳🇱",
        "Germany": "🇩🇪",
        "France": "🇫🇷",
        "United States": "🇺🇸",
        "Japan": "🇯🇵",
        "Singapore": "🇸🇬",
        "United Kingdom": "🇬🇧",
        "Canada": "🇨🇦",
        "Australia": "🇦🇺"
    }
    return flags.get(location, "🌍")


def create_referral_link(referral_code: str, bot_username: str) -> str:
    """Create referral link"""
    return f"https://t.me/{bot_username}?start={referral_code}"


def log_admin_action(admin_id: int, action: str, target_user_id: Optional[int] = None, details: Optional[str] = None):
    """Log admin action to database"""
    from bot.models.database import DatabaseManager, AdminLog
    from bot.config.settings import Config
    
    db_manager = DatabaseManager(Config.DATABASE_URL)
    session = db_manager.get_session()
    
    try:
        log_entry = AdminLog(
            admin_id=admin_id,
            action=action,
            target_user_id=target_user_id,
            details=details
        )
        session.add(log_entry)
        session.commit()
        logger.info(f"Admin action logged: {admin_id} - {action}")
    except Exception as e:
        logger.error(f"Failed to log admin action: {e}")
        session.rollback()
    finally:
        session.close()


def update_user_activity(user_id: int):
    """Update user's last activity timestamp"""
    from bot.models.database import DatabaseManager, User
    from bot.config.settings import Config
    
    db_manager = DatabaseManager(Config.DATABASE_URL)
    session = db_manager.get_session()
    
    try:
        user = session.query(User).filter_by(telegram_id=user_id).first()
        if user:
            user.last_activity = datetime.utcnow()
            session.commit()
    except Exception as e:
        logger.error(f"Failed to update user activity: {e}")
        session.rollback()
    finally:
        session.close()


def get_random_server_location() -> str:
    """Get random server location for load balancing"""
    locations = ["Netherlands", "Germany", "France", "United States", "Japan", "Singapore"]
    return random.choice(locations)


def create_config_file(config_data: str, filename: str) -> BytesIO:
    """Create configuration file as BytesIO"""
    file_buffer = BytesIO()
    file_buffer.write(config_data.encode('utf-8'))
    file_buffer.seek(0)
    file_buffer.name = filename
    return file_buffer


class StatsCalculator:
    """Statistics calculation utilities"""
    
    @staticmethod
    def calculate_daily_stats():
        """Calculate daily statistics"""
        from bot.models.database import DatabaseManager, User, Payment, Subscription
        from bot.config.settings import Config
        
        db_manager = DatabaseManager(Config.DATABASE_URL)
        session = db_manager.get_session()
        
        try:
            today = datetime.utcnow().date()
            
            # New users today
            new_users = session.query(User).filter(
                User.created_at >= today
            ).count()
            
            # Successful payments today
            successful_payments = session.query(Payment).filter(
                Payment.created_at >= today,
                Payment.status == 'completed'
            ).count()
            
            # Daily revenue
            revenue_result = session.query(Payment).filter(
                Payment.created_at >= today,
                Payment.status == 'completed'
            ).all()
            
            daily_revenue = sum(p.amount_rubles for p in revenue_result)
            
            # Active subscriptions
            active_subscriptions = session.query(Subscription).filter(
                Subscription.is_active == True,
                Subscription.end_date > datetime.utcnow()
            ).count()
            
            return {
                'new_users': new_users,
                'successful_payments': successful_payments,
                'daily_revenue': daily_revenue,
                'active_subscriptions': active_subscriptions
            }
            
        except Exception as e:
            logger.error(f"Failed to calculate daily stats: {e}")
            return {
                'new_users': 0,
                'successful_payments': 0,
                'daily_revenue': 0.0,
                'active_subscriptions': 0
            }
        finally:
            session.close()


# Import payment manager
from bot.utils.payments import payment_manager, PaymentError