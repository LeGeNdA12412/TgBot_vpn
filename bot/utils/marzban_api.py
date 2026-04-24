"""Marzban VPN Panel API Client"""

import logging
import requests
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from bot.config.settings import Config

logger = logging.getLogger(__name__)


class MarzbanAPI:
    """Marzban VPN Panel API Client"""

    def __init__(self):
        self.base_url = Config.MARZBAN_BASE_URL.rstrip('/')
        self.username = Config.MARZBAN_USERNAME
        self.password = Config.MARZBAN_PASSWORD
        self.access_token = None
        self.session = requests.Session()
        # Set timeouts to prevent hanging
        self.session.timeout = 10  # 10 seconds timeout

    def _get_headers(self) -> Dict[str, str]:
        """Get headers for API requests"""
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
        if self.access_token:
            headers['Authorization'] = f'Bearer {self.access_token}'
        return headers

    def login(self) -> bool:
        """Login to Marzban panel and get access token"""
        try:
            url = f"{self.base_url}/api/admin/token"
            data = {
                'username': self.username,
                'password': self.password
            }

            response = self.session.post(url, json=data, headers={'Content-Type': 'application/json'}, timeout=10)
            response.raise_for_status()

            result = response.json()
            self.access_token = result.get('access_token')
            Config.MARZBAN_ACCESS_TOKEN = self.access_token

            logger.info("Successfully logged in to Marzban panel")
            return True

        except requests.exceptions.Timeout:
            logger.error("Marzban login timeout")
            return False
        except requests.RequestException as e:
            logger.error(f"Failed to login to Marzban: {e}")
            return False
        except Exception as e:
            logger.error(f"Marzban login error: {e}")
            return False

    def _ensure_authenticated(self) -> bool:
        """Ensure we have valid authentication"""
        if not self.access_token:
            return self.login()
        return True

    def get_user(self, username: str) -> Optional[Dict[str, Any]]:
        """Get user information from Marzban"""
        if not self._ensure_authenticated():
            return None

        try:
            url = f"{self.base_url}/api/user/{username}"
            response = self.session.get(url, headers=self._get_headers(), timeout=10)

            if response.status_code == 404:
                return None  # User not found

            response.raise_for_status()
            return response.json()

        except requests.exceptions.Timeout:
            logger.error(f"Timeout getting user {username}")
            return None
        except requests.RequestException as e:
            logger.error(f"Failed to get user {username}: {e}")
            return None

    def create_user(self, username: str, data_limit: int = 0, expire_date: Optional[datetime] = None,
                   proxies: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """Create new user in Marzban"""
        if not self._ensure_authenticated():
            return None

        try:
            url = f"{self.base_url}/api/user"

            # Prepare user data
            user_data = {
                'username': username,
                'data_limit': data_limit,  # 0 = unlimited
                'data_limit_reset_strategy': 'no_reset',
                'status': 'active'
            }

            if expire_date:
                user_data['expire'] = int(expire_date.timestamp())

            if proxies:
                user_data['proxies'] = proxies
            else:
                # Default proxies configuration
                user_data['proxies'] = {
                    'vless': {
                        'id': f'user-{username}',
                        'flow': ''
                    },
                    'vmess': {
                        'id': f'user-{username}'
                    },
                    'trojan': {
                        'password': f'user-{username}'
                    },
                    'shadowsocks': {
                        'password': f'user-{username}'
                    }
                }

            response = self.session.post(url, json=user_data, headers=self._get_headers(), timeout=10)
            response.raise_for_status()

            result = response.json()
            logger.info(f"Created user {username} in Marzban")
            return result

        except requests.exceptions.Timeout:
            logger.error(f"Timeout creating user {username} in Marzban")
            return None
        except requests.RequestException as e:
            logger.error(f"Failed to create user {username}: {e}")
            return None

    def update_user(self, username: str, data_limit: Optional[int] = None,
                   expire_date: Optional[datetime] = None, status: Optional[str] = None) -> bool:
        """Update user in Marzban"""
        if not self._ensure_authenticated():
            return False

        try:
            url = f"{self.base_url}/api/user/{username}"

            update_data = {}
            if data_limit is not None:
                update_data['data_limit'] = data_limit
            if expire_date is not None:
                update_data['expire'] = int(expire_date.timestamp())
            if status is not None:
                update_data['status'] = status

            if not update_data:
                return True  # Nothing to update

            response = self.session.put(url, json=update_data, headers=self._get_headers(), timeout=10)
            response.raise_for_status()

            logger.info(f"Updated user {username} in Marzban")
            return True

        except requests.exceptions.Timeout:
            logger.error(f"Timeout updating user {username}")
            return False
        except requests.RequestException as e:
            logger.error(f"Failed to update user {username}: {e}")
            return False

    def delete_user(self, username: str) -> bool:
        """Delete user from Marzban"""
        if not self._ensure_authenticated():
            return False

        try:
            url = f"{self.base_url}/api/user/{username}"
            response = self.session.delete(url, headers=self._get_headers(), timeout=10)
            response.raise_for_status()

            logger.info(f"Deleted user {username} from Marzban")
            return True

        except requests.exceptions.Timeout:
            logger.error(f"Timeout deleting user {username}")
            return False
        except requests.RequestException as e:
            logger.error(f"Failed to delete user {username}: {e}")
            return False

    def get_user_config(self, username: str) -> Optional[Dict[str, Any]]:
        """Get user configuration data"""
        if not self._ensure_authenticated():
            return None

        try:
            url = f"{self.base_url}/api/user/{username}/get_config"
            response = self.session.get(url, headers=self._get_headers(), timeout=10)
            response.raise_for_status()

            return response.json()

        except requests.exceptions.Timeout:
            logger.error(f"Timeout getting config for user {username}")
            return None
        except requests.RequestException as e:
            logger.error(f"Failed to get config for user {username}: {e}")
            return None

    def get_user_usage(self, username: str) -> Optional[Dict[str, Any]]:
        """Get user usage statistics"""
        if not self._ensure_authenticated():
            return None

        try:
            url = f"{self.base_url}/api/user/{username}/usage"
            response = self.session.get(url, headers=self._get_headers(), timeout=10)
            response.raise_for_status()

            return response.json()

        except requests.exceptions.Timeout:
            logger.error(f"Timeout getting usage for user {username}")
            return None
        except requests.RequestException as e:
            logger.error(f"Failed to get usage for user {username}: {e}")
            return None

    def get_system_stats(self) -> Optional[Dict[str, Any]]:
        """Get system statistics"""
        if not self._ensure_authenticated():
            return None

        try:
            url = f"{self.base_url}/api/system"
            response = self.session.get(url, headers=self._get_headers(), timeout=10)
            response.raise_for_status()

            return response.json()

        except requests.exceptions.Timeout:
            logger.error("Timeout getting system stats")
            return None
        except requests.RequestException as e:
            logger.error(f"Failed to get system stats: {e}")
            return None

    def get_all_users(self, offset: int = 0, limit: int = 50) -> Optional[List[Dict[str, Any]]]:
        """Get list of all users"""
        if not self._ensure_authenticated():
            return None

        try:
            url = f"{self.base_url}/api/users"
            params = {'offset': offset, 'limit': limit}
            response = self.session.get(url, params=params, headers=self._get_headers(), timeout=10)
            response.raise_for_status()

            result = response.json()
            return result.get('users', [])

        except requests.exceptions.Timeout:
            logger.error("Timeout getting users list")
            return None
        except requests.RequestException as e:
            logger.error(f"Failed to get users list: {e}")
            return None

    def reset_user_data_usage(self, username: str) -> bool:
        """Reset user's data usage"""
        if not self._ensure_authenticated():
            return False

        try:
            url = f"{self.base_url}/api/user/{username}/reset"
            response = self.session.post(url, headers=self._get_headers(), timeout=10)
            response.raise_for_status()

            logger.info(f"Reset data usage for user {username}")
            return True

        except requests.exceptions.Timeout:
            logger.error(f"Timeout resetting data usage for user {username}")
            return False
        except requests.RequestException as e:
            logger.error(f"Failed to reset data usage for user {username}: {e}")
            return False


# Global Marzban API instance
marzban_api = MarzbanAPI()