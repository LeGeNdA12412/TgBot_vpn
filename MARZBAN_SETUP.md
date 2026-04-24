# Настройка Marzban для VPN бота

## 🚀 Быстрая установка Marzban

### 1. Установка на сервер
```bash
# Установите Docker и Docker Compose
curl -fsSL https://get.docker.com | sh
sudo curl -L "https://github.com/docker/compose/releases/download/v2.24.0/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# Клонируйте Marzban
git clone https://github.com/Gozargah/Marzban.git
cd Marzban

# Запустите установку
sudo bash marzban.sh up
```

### 2. Настройка панели
- Откройте браузер: `http://your-server-ip:8000`
- Создайте админа (username: `admin`, password: сгенерированный)
- Настройте inbounds для разных протоколов

### 3. Настройка бота
Обновите `.env` файл:
```bash
MARZBAN_BASE_URL=http://your-server-ip:8000
MARZBAN_USERNAME=admin
MARZBAN_PASSWORD=your_admin_password
```

### 4. Запуск бота
```bash
python bot/main.py
```

## 📋 Поддерживаемые протоколы
- ✅ V2Ray (VMess, VLESS)
- ✅ Trojan
- ✅ Shadowsocksx`
- ✅ WireGuard (через Xray)

## 🔧 Управление через админку бота
- **Список пользователей** - просмотр всех VPN пользователей
- **Статистика использования** - трафик и активность
- **Синхронизация** - обновление статусов подписок
- **Очистка** - деактивация истекших подписок

## 📊 Мониторинг
- Реальное время статистики через Marzban API
- Автоматическая синхронизация пользователей
- Логи всех операций в `logs/vpn_bot_*.log`