"""Admin handlers for VPN Telegram Bot"""

import logging
import asyncio
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from sqlalchemy import func, desc

from bot.models.database import DatabaseManager, User, Subscription, Payment, VPNKey, BotStats
from bot.config.settings import Config
from bot.utils.helpers import (
    is_admin, 
    log_admin_action, 
    format_datetime, 
    format_date,
    format_time_ago,
    StatsCalculator,
    get_user_vpn_usage,
    reset_user_data_usage,
    delete_user_from_vpn
)
from bot.utils.marzban_api import marzban_api
from locales.ru import get_message

logger = logging.getLogger(__name__)

db_manager = DatabaseManager(Config.DATABASE_URL)

# Admin conversation states
WAITING_BROADCAST_MESSAGE = 1


async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show admin panel"""
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text(get_message('admin_not_authorized'))
        return
    
    session = db_manager.get_session()
    try:
        # Get comprehensive statistics
        total_users = session.query(User).count()
        active_users = session.query(User).filter(
            User.last_activity >= datetime.utcnow() - timedelta(days=7)
        ).count()
        
        active_subscriptions = session.query(Subscription).filter(
            Subscription.is_active == True,
            Subscription.end_date > datetime.utcnow()
        ).count()
        
        # Daily revenue
        today = datetime.utcnow().date()
        daily_revenue = session.query(func.sum(Payment.amount)).filter(
            Payment.status == 'completed',
            Payment.completed_at >= today
        ).scalar() or 0
        daily_revenue = daily_revenue / 100  # Convert from kopecks
        
        # Monthly revenue
        start_of_month = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        monthly_revenue = session.query(func.sum(Payment.amount)).filter(
            Payment.status == 'completed',
            Payment.completed_at >= start_of_month
        ).scalar() or 0
        monthly_revenue = monthly_revenue / 100  # Convert from kopecks
        
        # Available VPN keys
        available_keys = session.query(VPNKey).filter(VPNKey.is_used == False).count()
        
        # New users today
        new_users = session.query(User).filter(
            User.created_at >= today
        ).count()
        
        admin_text = get_message('admin_panel',
            total_users=total_users,
            active_subscriptions=active_subscriptions,
            daily_revenue=int(daily_revenue),
            monthly_revenue=int(monthly_revenue),
            available_keys=available_keys,
            new_users=new_users,
            last_update=format_datetime(datetime.utcnow())
        )
        
        keyboard = [
            [
                InlineKeyboardButton("👥 Пользователи", callback_data='admin_users'),
                InlineKeyboardButton("📊 Статистика", callback_data='admin_stats')
            ],
            [
                InlineKeyboardButton("🔑 VPN ключи", callback_data='admin_keys'),
                InlineKeyboardButton("💰 Платежи", callback_data='admin_payments')
            ],
            [
                InlineKeyboardButton("📢 Рассылка", callback_data='admin_broadcast'),
                InlineKeyboardButton("📋 Логи", callback_data='admin_logs')
            ],
            [
                InlineKeyboardButton("⚙️ Настройки", callback_data='admin_settings'),
                InlineKeyboardButton("🔄 Обновить", callback_data='admin_refresh')
            ]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            text=admin_text,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
        
        log_admin_action(user_id, "accessed_admin_panel")
        
    finally:
        session.close()


async def admin_statistics(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show admin statistics (legacy function for compatibility)"""
    # Redirect to new detailed stats function
    await admin_detailed_stats(update, context)


async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle admin callback queries"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await query.edit_message_text(get_message('admin_not_authorized'))
        return
    
    callback_data = query.data
    action = callback_data.replace('admin_', '')
    
    # Main menu handlers
    if action == 'refresh':
        await admin_panel_refresh(update, context)
    elif action == 'users':
        context.user_data['admin_users_page'] = 0
        await admin_users_list(update, context)
    elif action == 'stats':
        await admin_detailed_stats(update, context)
    elif action == 'keys':
        await admin_keys_management(update, context)
    elif action == 'payments':
        await admin_payments_list(update, context)
    elif action == 'broadcast':
        await admin_broadcast_start(update, context)
    elif action == 'logs':
        await admin_logs_view(update, context)
    elif action == 'settings':
        await admin_settings(update, context)
    elif action == 'back':
        await admin_back_to_panel(update, context)
    
    # Pagination handlers
    elif action.startswith('users_page_'):
        page_num = int(action.split('_')[-1])
        context.user_data['admin_users_page'] = page_num
        await admin_users_list(update, context)
    
    # Broadcast handler
    elif action == 'broadcast_confirm':
        await admin_broadcast_confirm(update, context)
    
    # Marzban management handlers
    elif action == 'marzban_users':
        await admin_marzban_users_list(update, context)
    elif action == 'marzban_usage':
        await admin_marzban_usage_stats(update, context)
    elif action == 'marzban_sync':
        await admin_marzban_sync(update, context)
    elif action == 'marzban_cleanup':
        await admin_marzban_cleanup(update, context)
    
    # Placeholder handlers for unimplemented features
    elif action in ['user_search', 'user_stats', 'revenue_chart', 'activity_chart', 
                    'export_data', 'keys_add', 'keys_list', 'keys_cleanup', 'keys_stats',
                    'revenue_stats', 'payment_search', 'payment_methods', 'download_logs',
                    'edit_prices', 'edit_referrals', 'system_settings', 'backup']:
        await query.edit_message_text(
            text="🔄 Эта функция еще не реализована. В разработке...",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Назад в админку", callback_data='admin_back')]
            ])
        )


async def admin_panel_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Refresh admin panel"""
    query = update.callback_query
    user_id = update.effective_user.id
    
    session = db_manager.get_session()
    try:
        # Get fresh statistics
        total_users = session.query(User).count()
        active_subscriptions = session.query(Subscription).filter(
            Subscription.is_active == True,
            Subscription.end_date > datetime.utcnow()
        ).count()
        
        today = datetime.utcnow().date()
        daily_revenue = session.query(func.sum(Payment.amount)).filter(
            Payment.status == 'completed',
            Payment.completed_at >= today
        ).scalar() or 0
        daily_revenue = daily_revenue / 100
        
        start_of_month = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        monthly_revenue = session.query(func.sum(Payment.amount)).filter(
            Payment.status == 'completed',
            Payment.completed_at >= start_of_month
        ).scalar() or 0
        monthly_revenue = monthly_revenue / 100
        
        available_keys = session.query(VPNKey).filter(VPNKey.is_used == False).count()
        new_users = session.query(User).filter(User.created_at >= today).count()
        
        admin_text = get_message('admin_panel',
            total_users=total_users,
            active_subscriptions=active_subscriptions,
            daily_revenue=int(daily_revenue),
            monthly_revenue=int(monthly_revenue),
            available_keys=available_keys,
            new_users=new_users,
            last_update=format_datetime(datetime.utcnow())
        )
        
        keyboard = [
            [
                InlineKeyboardButton("👥 Пользователи", callback_data='admin_users'),
                InlineKeyboardButton("📊 Статистика", callback_data='admin_stats')
            ],
            [
                InlineKeyboardButton("🔑 VPN ключи", callback_data='admin_keys'),
                InlineKeyboardButton("💰 Платежи", callback_data='admin_payments')
            ],
            [
                InlineKeyboardButton("📢 Рассылка", callback_data='admin_broadcast'),
                InlineKeyboardButton("📋 Логи", callback_data='admin_logs')
            ],
            [
                InlineKeyboardButton("⚙️ Настройки", callback_data='admin_settings'),
                InlineKeyboardButton("🔄 Обновлено ✅", callback_data='admin_refresh')
            ]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text=admin_text,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
        
        log_admin_action(user_id, "refreshed_admin_panel")
        
    finally:
        session.close()


async def admin_users_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show users list for admin"""
    query = update.callback_query
    user_id = update.effective_user.id
    
    session = db_manager.get_session()
    try:
        # Get recent users with pagination
        page = context.user_data.get('admin_users_page', 0)
        limit = 10
        offset = page * limit
        
        users = session.query(User).order_by(desc(User.created_at)).offset(offset).limit(limit).all()
        total_users = session.query(User).count()
        
        users_text = f"👥 Пользователи (стр. {page + 1}):\n\n"
        
        for user in users:
            status_emoji = "✅" if user.has_active_subscription else "❌"
            last_activity = format_time_ago(user.last_activity)
            
            users_text += f"{status_emoji} <b>{user.full_name}</b>\n"
            users_text += f"   🆔 ID: <code>{user.telegram_id}</code>\n"
            users_text += f"   👤 @{user.username or 'None'}\n"
            users_text += f"   📅 Регистрация: {format_date(user.created_at)}\n"
            users_text += f"   🕐 Активность: {last_activity}\n"
            users_text += f"   💰 Потрачено: {user.total_spent} ₽\n"
            users_text += f"   🎁 Рефералов: {user.total_referrals}\n\n"
        
        users_text += f"📊 Всего пользователей: {total_users}"
        
        # Navigation buttons
        keyboard = []
        nav_row = []
        
        if page > 0:
            nav_row.append(InlineKeyboardButton("⬅️ Назад", callback_data=f'admin_users_page_{page-1}'))
        
        if (page + 1) * limit < total_users:
            nav_row.append(InlineKeyboardButton("Вперед ➡️", callback_data=f'admin_users_page_{page+1}'))
        
        if nav_row:
            keyboard.append(nav_row)
        
        keyboard.extend([
            [
                InlineKeyboardButton("🔍 Поиск пользователя", callback_data='admin_user_search'),
                InlineKeyboardButton("📊 Статистика", callback_data='admin_user_stats')
            ],
            [InlineKeyboardButton("⬅️ Назад в админку", callback_data='admin_back')]
        ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text=users_text,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
        
    finally:
        session.close()


async def admin_detailed_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show detailed statistics"""
    query = update.callback_query
    user_id = update.effective_user.id
    
    session = db_manager.get_session()
    try:
        # Calculate comprehensive stats
        stats = StatsCalculator.calculate_daily_stats()
        
        # User statistics
        total_users = session.query(User).count()
        active_users_week = session.query(User).filter(
            User.last_activity >= datetime.utcnow() - timedelta(days=7)
        ).count()
        active_users_month = session.query(User).filter(
            User.last_activity >= datetime.utcnow() - timedelta(days=30)
        ).count()
        
        # Subscription statistics
        subs_by_plan = session.query(
            Subscription.plan_type,
            func.count(Subscription.id)
        ).filter(
            Subscription.is_active == True,
            Subscription.end_date > datetime.utcnow()
        ).group_by(Subscription.plan_type).all()
        
        # Payment statistics
        total_revenue = session.query(func.sum(Payment.amount)).filter(
            Payment.status == 'completed'
        ).scalar() or 0
        total_revenue = total_revenue / 100
        
        # Weekly revenue
        week_ago = datetime.utcnow() - timedelta(days=7)
        weekly_revenue = session.query(func.sum(Payment.amount)).filter(
            Payment.status == 'completed',
            Payment.completed_at >= week_ago
        ).scalar() or 0
        weekly_revenue = weekly_revenue / 100
        
        stats_text = f"📊 <b>Подробная статистика</b>\n\n"
        
        stats_text += f"👥 <b>Пользователи:</b>\n"
        stats_text += f"   • Всего: {total_users}\n"
        stats_text += f"   • Новых сегодня: {stats['new_users']}\n"
        stats_text += f"   • Активных за неделю: {active_users_week}\n"
        stats_text += f"   • Активных за месяц: {active_users_month}\n\n"
        
        stats_text += f"📱 <b>Подписки:</b>\n"
        stats_text += f"   • Активных: {stats['active_subscriptions']}\n"
        for plan_type, count in subs_by_plan:
            plan_name = plan_type.replace('_', ' ').title()
            stats_text += f"   • {plan_name}: {count}\n"
        stats_text += "\n"
        
        stats_text += f"💰 <b>Доходы:</b>\n"
        stats_text += f"   • Сегодня: {stats['daily_revenue']:.0f} ₽\n"
        stats_text += f"   • За неделю: {weekly_revenue:.0f} ₽\n"
        stats_text += f"   • Всего: {total_revenue:.0f} ₽\n"
        stats_text += f"   • Платежей сегодня: {stats['successful_payments']}\n\n"
        
        stats_text += f"🔄 <b>Обновлено:</b> {format_datetime(datetime.utcnow())}"
        
        keyboard = [
            [
                InlineKeyboardButton("📈 График доходов", callback_data='admin_revenue_chart'),
                InlineKeyboardButton("👥 Активность пользователей", callback_data='admin_activity_chart')
            ],
            [
                InlineKeyboardButton("📊 Экспорт данных", callback_data='admin_export_data'),
                InlineKeyboardButton("🔄 Обновить", callback_data='admin_stats')
            ],
            [InlineKeyboardButton("⬅️ Назад в админку", callback_data='admin_back')]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text=stats_text,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
        
        log_admin_action(user_id, "viewed_detailed_stats")
        
    finally:
        session.close()


async def admin_keys_management(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manage VPN users via Marzban"""
    query = update.callback_query
    user_id = update.effective_user.id

    session = db_manager.get_session()
    try:
        # Get Marzban system stats
        system_stats = marzban_api.get_system_stats()

        # Get total users from database (our bot users)
        total_bot_users = session.query(User).count()
        active_subscriptions = session.query(Subscription).filter(
            Subscription.is_active == True,
            Subscription.end_date > datetime.utcnow()
        ).count()

        keys_text = f"🔑 <b>Управление VPN пользователями</b>\n\n"

        if system_stats:
            keys_text += f"📊 <b>Статистика Marzban:</b>\n"
            keys_text += f"   • Всего пользователей: {system_stats.get('total_users', 'N/A')}\n"
            keys_text += f"   • Активных: {system_stats.get('active_users', 'N/A')}\n"
            keys_text += f"   • Использовано трафика: {system_stats.get('total_traffic', 'N/A')} GB\n\n"

        keys_text += f"🤖 <b>Статистика бота:</b>\n"
        keys_text += f"   • Пользователей бота: {total_bot_users}\n"
        keys_text += f"   • Активных подписок: {active_subscriptions}\n\n"

        keys_text += f"🔄 <b>Обновлено:</b> {format_datetime(datetime.utcnow())}"

        keyboard = [
            [
                InlineKeyboardButton("👥 Список пользователей", callback_data='admin_marzban_users'),
                InlineKeyboardButton("📊 Статистика использования", callback_data='admin_marzban_usage')
            ],
            [
                InlineKeyboardButton("🔄 Синхронизировать", callback_data='admin_marzban_sync'),
                InlineKeyboardButton("🗑️ Очистить неактивных", callback_data='admin_marzban_cleanup')
            ],
            [InlineKeyboardButton("⬅️ Назад в админку", callback_data='admin_back')]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            text=keys_text,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )

    finally:
        session.close()


async def admin_payments_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show recent payments"""
    query = update.callback_query
    user_id = update.effective_user.id
    
    session = db_manager.get_session()
    try:
        # Get recent payments
        payments = session.query(Payment).order_by(desc(Payment.created_at)).limit(20).all()
        
        payments_text = f"💰 <b>Последние платежи</b>\n\n"
        
        for payment in payments:
            user = session.query(User).filter_by(id=payment.user_id).first()
            status_emoji = {
                'completed': '✅',
                'pending': '⏳',
                'failed': '❌',
                'cancelled': '🚫'
            }.get(payment.status, '❓')
            
            payments_text += f"{status_emoji} <b>{payment.amount_rubles:.0f} ₽</b>\n"
            payments_text += f"   👤 {user.full_name if user else 'Unknown'}\n"
            payments_text += f"   📦 {payment.plan_type.replace('_', ' ').title()}\n"
            payments_text += f"   💳 {payment.payment_method.upper()}\n"
            payments_text += f"   📅 {format_datetime(payment.created_at)}\n\n"
        
        keyboard = [
            [
                InlineKeyboardButton("💰 Статистика доходов", callback_data='admin_revenue_stats'),
                InlineKeyboardButton("🔍 Поиск платежа", callback_data='admin_payment_search')
            ],
            [
                InlineKeyboardButton("📊 По методам оплаты", callback_data='admin_payment_methods'),
                InlineKeyboardButton("🔄 Обновить", callback_data='admin_payments')
            ],
            [InlineKeyboardButton("⬅️ Назад в админку", callback_data='admin_back')]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text=payments_text,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
        
    finally:
        session.close()


async def admin_broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start broadcast message creation"""
    query = update.callback_query
    user_id = update.effective_user.id
    
    session = db_manager.get_session()
    try:
        total_users = session.query(User).count()
        active_users = session.query(User).filter(
            User.last_activity >= datetime.utcnow() - timedelta(days=30)
        ).count()
        
        broadcast_text = get_message('broadcast_start',
            total_users=total_users,
            active_users=active_users
        )
        
        keyboard = [
            [InlineKeyboardButton("⬅️ Назад в админку", callback_data='admin_back')]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text=broadcast_text,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
        
        # Set state for waiting broadcast message
        context.user_data['waiting_broadcast'] = True
        
    finally:
        session.close()


async def handle_broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle broadcast message from admin"""
    user_id = update.effective_user.id
    
    if not is_admin(user_id) or not context.user_data.get('waiting_broadcast'):
        return
    
    broadcast_message = update.message.text
    context.user_data['waiting_broadcast'] = False
    context.user_data['broadcast_message'] = broadcast_message
    
    session = db_manager.get_session()
    try:
        total_users = session.query(User).count()
        
        confirm_text = get_message('broadcast_confirm',
            recipients=total_users,
            message=broadcast_message
        )
        
        keyboard = [
            [
                InlineKeyboardButton("✅ Отправить всем", callback_data='admin_broadcast_confirm'),
                InlineKeyboardButton("❌ Отмена", callback_data='admin_back')
            ]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            text=confirm_text,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
        
    finally:
        session.close()


async def admin_broadcast_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Confirm and execute broadcast"""
    query = update.callback_query
    await query.answer("📢 Начинаем рассылку...")
    
    user_id = update.effective_user.id
    broadcast_message = context.user_data.get('broadcast_message')
    
    if not broadcast_message:
        await query.edit_message_text("❌ Сообщение для рассылки не найдено")
        return
    
    session = db_manager.get_session()
    try:
        users = session.query(User).all()
        total_users = len(users)
        sent_count = 0
        failed_count = 0
        
        # Update message to show progress
        await query.edit_message_text(
            f"📢 Рассылка запущена...\n\n"
            f"👥 Всего получателей: {total_users}\n"
            f"✅ Отправлено: 0\n"
            f"❌ Ошибок: 0"
        )
        
        # Send messages with progress updates
        for i, user in enumerate(users):
            try:
                await context.bot.send_message(
                    chat_id=user.telegram_id,
                    text=broadcast_message,
                    parse_mode='HTML'
                )
                sent_count += 1
                
                # Update progress every 50 messages
                if (i + 1) % 50 == 0:
                    await query.edit_message_text(
                        f"📢 Рассылка в процессе...\n\n"
                        f"👥 Всего получателей: {total_users}\n"
                        f"✅ Отправлено: {sent_count}\n"
                        f"❌ Ошибок: {failed_count}\n"
                        f"📊 Прогресс: {((i + 1) / total_users * 100):.1f}%"
                    )
                
                # Small delay to avoid rate limits
                await asyncio.sleep(0.1)
                
            except Exception as e:
                failed_count += 1
                logger.warning(f"Failed to send broadcast to user {user.telegram_id}: {e}")
        
        # Final result
        success_text = get_message('broadcast_success', sent=sent_count, total=total_users)
        if failed_count > 0:
            success_text += f"\n❌ Не удалось отправить: {failed_count}"
        
        keyboard = [
            [InlineKeyboardButton("⬅️ Назад в админку", callback_data='admin_back')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text=success_text,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
        
        log_admin_action(user_id, "broadcast_sent", details=f"Sent to {sent_count}/{total_users} users")
        
    finally:
        session.close()


async def admin_logs_view(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """View admin logs"""
    query = update.callback_query
    user_id = update.effective_user.id
    
    # Read recent log entries from file
    try:
        log_file = f"logs/vpn_bot_{datetime.now().strftime('%Y%m%d')}.log"
        with open(log_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            recent_logs = lines[-20:]  # Last 20 lines
        
        logs_text = f"📋 <b>Последние логи</b>\n\n"
        logs_text += "<pre>"
        for line in recent_logs:
            if len(line) > 100:
                line = line[:97] + "..."
            logs_text += line
        logs_text += "</pre>"
        
    except FileNotFoundError:
        logs_text = "📋 <b>Логи</b>\n\n❌ Файл логов не найден"
    except Exception as e:
        logs_text = f"📋 <b>Логи</b>\n\n❌ Ошибка чтения логов: {str(e)}"
    
    keyboard = [
        [
            InlineKeyboardButton("📁 Скачать полный лог", callback_data='admin_download_logs'),
            InlineKeyboardButton("🔄 Обновить", callback_data='admin_logs')
        ],
        [InlineKeyboardButton("⬅️ Назад в админку", callback_data='admin_back')]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        text=logs_text,
        reply_markup=reply_markup,
        parse_mode='HTML'
    )


async def admin_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show admin settings"""
    query = update.callback_query
    
    settings_text = f"⚙️ <b>Настройки бота</b>\n\n"
    settings_text += f"🤖 <b>Основные:</b>\n"
    settings_text += f"   • Режим отладки: {'✅' if Config.DEBUG else '❌'}\n"
    settings_text += f"   • Уровень логов: {Config.LOG_LEVEL}\n"
    settings_text += f"   • Язык по умолчанию: {Config.DEFAULT_LANGUAGE}\n\n"
    
    settings_text += f"💰 <b>Тарифы:</b>\n"
    settings_text += f"   • 1 месяц: {Config.PLAN_1_MONTH_PRICE} ₽\n"
    settings_text += f"   • 3 месяца: {Config.PLAN_3_MONTH_PRICE} ₽\n"
    settings_text += f"   • 6 месяцев: {Config.PLAN_6_MONTH_PRICE} ₽\n"
    settings_text += f"   • 12 месяцев: {Config.PLAN_12_MONTH_PRICE} ₽\n\n"
    
    settings_text += f"🎁 <b>Реферальная программа:</b>\n"
    settings_text += f"   • Процент бонуса: {Config.REFERRAL_BONUS_PERCENT}%\n"
    settings_text += f"   • Минимум для вывода: {Config.REFERRAL_MIN_PAYOUT} ₽\n"
    
    keyboard = [
        [
            InlineKeyboardButton("💰 Изменить тарифы", callback_data='admin_edit_prices'),
            InlineKeyboardButton("🎁 Настроить рефералы", callback_data='admin_edit_referrals')
        ],
        [
            InlineKeyboardButton("🔧 Системные настройки", callback_data='admin_system_settings'),
            InlineKeyboardButton("💾 Резервное копирование", callback_data='admin_backup')
        ],
        [InlineKeyboardButton("⬅️ Назад в админку", callback_data='admin_back')]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        text=settings_text,
        reply_markup=reply_markup,
        parse_mode='HTML'
    )


async def admin_back_to_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Return to admin panel"""
    query = update.callback_query
    await query.answer()
    
    # Clear any admin states
    context.user_data.pop('waiting_broadcast', None)
    context.user_data.pop('broadcast_message', None)
    
    # Show fresh admin panel
    await admin_panel_refresh(update, context)


# Marzban management functions

async def admin_marzban_users_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show Marzban users list"""
    query = update.callback_query
    user_id = update.effective_user.id

    # Get users from Marzban
    users = marzban_api.get_all_users(limit=20)

    if not users:
        await query.edit_message_text(
            text="❌ Не удалось получить список пользователей Marzban",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Назад", callback_data='admin_keys')]
            ])
        )
        return

    users_text = f"👥 <b>Пользователи Marzban</b>\n\n"

    for user in users[:10]:  # Show first 10 users
        status = user.get('status', 'unknown')
        status_emoji = {'active': '✅', 'disabled': '❌', 'limited': '⚠️'}.get(status, '❓')

        users_text += f"{status_emoji} <b>{user.get('username', 'N/A')}</b>\n"
        users_text += f"   📅 Создан: {user.get('created_at', 'N/A')[:10]}\n"
        users_text += f"   📊 Статус: {status}\n"

        # Get usage info
        usage = marzban_api.get_user_usage(user.get('username'))
        if usage:
            used_traffic = usage.get('used_traffic', 0)
            users_text += f"   📈 Трафик: {used_traffic} GB\n"

        users_text += "\n"

    users_text += f"📊 Показано {min(len(users), 10)} из {len(users)} пользователей"

    keyboard = [
        [InlineKeyboardButton("🔄 Обновить", callback_data='admin_marzban_users')],
        [InlineKeyboardButton("⬅️ Назад", callback_data='admin_keys')]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        text=users_text,
        reply_markup=reply_markup,
        parse_mode='HTML'
    )


async def admin_marzban_usage_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show Marzban usage statistics"""
    query = update.callback_query
    user_id = update.effective_user.id

    # Get system stats
    system_stats = marzban_api.get_system_stats()

    if not system_stats:
        await query.edit_message_text(
            text="❌ Не удалось получить статистику Marzban",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Назад", callback_data='admin_keys')]
            ])
        )
        return

    stats_text = f"📊 <b>Статистика использования Marzban</b>\n\n"

    stats_text += f"👥 <b>Пользователи:</b>\n"
    stats_text += f"   • Всего: {system_stats.get('total_users', 'N/A')}\n"
    stats_text += f"   • Активных: {system_stats.get('active_users', 'N/A')}\n\n"

    stats_text += f"📈 <b>Трафик:</b>\n"
    stats_text += f"   • Общий: {system_stats.get('total_traffic', 'N/A')} GB\n"
    stats_text += f"   • Сегодня: {system_stats.get('today_traffic', 'N/A')} GB\n\n"

    stats_text += f"🔄 <b>Обновлено:</b> {format_datetime(datetime.utcnow())}"

    keyboard = [
        [InlineKeyboardButton("🔄 Обновить", callback_data='admin_marzban_usage')],
        [InlineKeyboardButton("⬅️ Назад", callback_data='admin_keys')]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        text=stats_text,
        reply_markup=reply_markup,
        parse_mode='HTML'
    )


async def admin_marzban_sync(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sync bot subscriptions with Marzban"""
    query = update.callback_query
    user_id = update.effective_user.id

    await query.edit_message_text("🔄 Синхронизация с Marzban...")

    session = db_manager.get_session()
    try:
        # Get active subscriptions
        active_subs = session.query(Subscription).filter(
            Subscription.is_active == True,
            Subscription.end_date > datetime.utcnow(),
            Subscription.marzban_username.isnot(None)
        ).all()

        synced = 0
        failed = 0

        for sub in active_subs:
            # Check if user exists in Marzban
            marzban_user = marzban_api.get_user(sub.marzban_username)

            if marzban_user:
                # Update expiration if needed
                current_expire = marzban_user.get('expire')
                if current_expire:
                    marzban_expire = datetime.fromtimestamp(current_expire)
                    if marzban_expire != sub.end_date:
                        # Sync expiration date
                        if marzban_api.update_user(sub.marzban_username, expire_date=sub.end_date):
                            synced += 1
                        else:
                            failed += 1
                    else:
                        synced += 1
                else:
                    failed += 1
            else:
                # User doesn't exist in Marzban, recreate
                logger.warning(f"User {sub.marzban_username} not found in Marzban, skipping")
                failed += 1

        result_text = f"✅ <b>Синхронизация завершена</b>\n\n"
        result_text += f"📊 Результаты:\n"
        result_text += f"   • Синхронизировано: {synced}\n"
        result_text += f"   • Ошибок: {failed}\n\n"
        result_text += f"🔄 <b>Обновлено:</b> {format_datetime(datetime.utcnow())}"

        keyboard = [
            [InlineKeyboardButton("⬅️ Назад", callback_data='admin_keys')]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            text=result_text,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )

        log_admin_action(user_id, "marzban_sync", details=f"Synced {synced} users, {failed} failed")

    finally:
        session.close()


async def admin_marzban_cleanup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Clean up expired users from Marzban"""
    query = update.callback_query
    user_id = update.effective_user.id

    await query.edit_message_text("🗑️ Очистка неактивных пользователей...")

    session = db_manager.get_session()
    try:
        # Get expired subscriptions
        expired_subs = session.query(Subscription).filter(
            Subscription.is_active == True,
            Subscription.end_date <= datetime.utcnow(),
            Subscription.marzban_username.isnot(None)
        ).all()

        cleaned = 0
        failed = 0

        for sub in expired_subs:
            # Disable user in Marzban
            if marzban_api.update_user(sub.marzban_username, status='disabled'):
                # Mark subscription as inactive
                sub.is_active = False
                cleaned += 1
            else:
                failed += 1

        session.commit()

        result_text = f"✅ <b>Очистка завершена</b>\n\n"
        result_text += f"📊 Результаты:\n"
        result_text += f"   • Деактивировано: {cleaned}\n"
        result_text += f"   • Ошибок: {failed}\n\n"
        result_text += f"🔄 <b>Обновлено:</b> {format_datetime(datetime.utcnow())}"

        keyboard = [
            [InlineKeyboardButton("⬅️ Назад", callback_data='admin_keys')]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            text=result_text,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )

        log_admin_action(user_id, "marzban_cleanup", details=f"Cleaned {cleaned} users, {failed} failed")

    finally:
        session.close()