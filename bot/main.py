"""Main bot application - VPN Telegram Bot"""

import os
import sys
import logging
import asyncio
import traceback
from datetime import datetime

# Add parent directory to path for proper imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from telegram.ext import (
    Application, 
    CommandHandler, 
    CallbackQueryHandler, 
    MessageHandler, 
    ConversationHandler,
    filters
)
from telegram.request import HTTPXRequest

from bot.config.settings import Config
from bot.handlers.main import (
    start_command,
    show_plans,
    select_payment_method,
    process_payment,
    verify_payment,
    show_profile,
    show_my_config,
    show_referral_info,
    show_help,
    show_support,
    main_menu,
    cancel_conversation,
    SELECTING_PLAN,
    SELECTING_PAYMENT_METHOD,
    WAITING_PAYMENT
)
from bot.handlers.admin import (
    admin_panel,
    admin_callback_handler,
    handle_broadcast_message,
    admin_back_to_panel,
    admin_broadcast_confirm
)
from bot.utils.helpers import setup_logging
from bot.models.database import DatabaseManager

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)

# ✅ Глобальный экземпляр БД — инициализируется один раз
db_manager = None


def create_application() -> Application:
    """Create and configure the bot application"""
    # Validate configuration
    Config.validate()
    
    # Настройки HTTP-запросов с таймаутами
    request_config = {
        "connect_timeout": 30,
        "read_timeout": 30,
        "write_timeout": 30,
        "pool_timeout": 30,
    }
    
    # Прокси если указан в конфиге
    if hasattr(Config, 'PROXY_URL') and Config.PROXY_URL:
        request_config["proxy_url"] = Config.PROXY_URL
    
    # Create application with custom request
    application = (
        Application.builder()
        .token(Config.BOT_TOKEN)
        .request(HTTPXRequest(**request_config))
        .get_updates_request(HTTPXRequest(**request_config))
        .build()
    )
    
    # Purchase conversation handler
    purchase_conversation = ConversationHandler(
        entry_points=[CallbackQueryHandler(show_plans, pattern='^buy_vpn$')],
        states={
            SELECTING_PLAN: [
                CallbackQueryHandler(select_payment_method, pattern='^plan_'),
                CallbackQueryHandler(main_menu, pattern='^main_menu$')
            ],
            SELECTING_PAYMENT_METHOD: [
                CallbackQueryHandler(process_payment, pattern='^pay_'),
                CallbackQueryHandler(show_plans, pattern='^buy_vpn$')
            ],
            WAITING_PAYMENT: [
                CallbackQueryHandler(verify_payment, pattern='^verify_payment_'),
                CallbackQueryHandler(select_payment_method, pattern='^plan_'),   # ✅ Новая строка
                CallbackQueryHandler(main_menu, pattern='^main_menu$')
            ]
        },
        fallbacks=[
            CommandHandler('cancel', cancel_conversation),
            CallbackQueryHandler(main_menu, pattern='^main_menu$')
        ],
        per_message=False  # ✅ Подавляем предупреждение
    )
    
    # Main command handlers
    application.add_handler(CommandHandler('start', start_command))
    application.add_handler(CommandHandler('admin', admin_panel))
    application.add_handler(purchase_conversation)
    
    # Profile and info handlers
    application.add_handler(CallbackQueryHandler(show_profile, pattern='^profile$'))
    application.add_handler(CallbackQueryHandler(show_my_config, pattern='^my_config$'))
    application.add_handler(CallbackQueryHandler(show_referral_info, pattern='^referral$'))
    application.add_handler(CallbackQueryHandler(show_help, pattern='^help$'))
    application.add_handler(CallbackQueryHandler(show_support, pattern='^support$'))
    application.add_handler(CallbackQueryHandler(main_menu, pattern='^main_menu$'))
    
    # Admin handlers
    application.add_handler(CallbackQueryHandler(admin_callback_handler, pattern='^admin_'))
    application.add_handler(CallbackQueryHandler(admin_back_to_panel, pattern='^admin_back$'))
    application.add_handler(CallbackQueryHandler(admin_broadcast_confirm, pattern='^admin_broadcast_confirm$'))
    
    # Broadcast message handler (for admins)
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_broadcast_message
    ))
    
    # Error handler
    application.add_error_handler(error_handler)
    
    return application


async def error_handler(update: object, context) -> None:
    """Log errors caused by Updates."""
    # ✅ ПОЛНОЕ ЛОГИРОВАНИЕ ОШИБКИ
    logger.error("=" * 80)
    logger.error("Exception while handling an update:")
    logger.error(f"Update: {update}")
    logger.error(f"Context error: {context.error}")
    logger.error(f"Traceback:\n{traceback.format_exc()}")
    logger.error("=" * 80)
    
    # Try to send error message to user if possible
    try:
        if update and hasattr(update, 'effective_chat') and update.effective_chat:
            error_text = (
                "❌ Произошла техническая ошибка. Мы уже работаем над её устранением.\n\n"
                "Попробуйте позже или обратитесь в поддержку: @vpn_support_bot"
            )
            
            # ✅ В DEBUG режиме показываем краткую ошибку
            if Config.DEBUG and context.error:
                error_text += f"\n\n<code>{str(context.error)[:200]}</code>"
            
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=error_text,
                parse_mode='HTML'
            )
    except Exception as e:
        logger.error(f"Failed to send error message to user: {e}")


async def post_init(application: Application) -> None:
    """Post initialization tasks"""
    logger.info("🚀 VPN Bot post-init started")
    
    # Get bot info
    bot_info = await application.bot.get_me()
    logger.info(f"✅ Bot info: @{bot_info.username} ({bot_info.first_name})")
    
    # Send startup message to admins
    startup_message = (
        "🤖 <b>VPN Bot запущен успешно!</b>\n\n"
        f"🆔 Бот: @{bot_info.username}\n"
        f"📅 Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"⚙️ Debug: {'✅' if Config.DEBUG else '❌'}\n"
        f"🗄️ БД: ✅\n\n"
        "🎯 Бот готов к работе!"
    )
    
    for admin_id in Config.ADMIN_IDS:
        try:
            await application.bot.send_message(
                chat_id=admin_id,
                text=startup_message,
                parse_mode='HTML'
            )
            logger.info(f"✅ Startup message sent to admin {admin_id}")
        except Exception as e:
            logger.warning(f"Failed to notify admin {admin_id}: {e}")
    
    logger.info("🎉 VPN Bot initialization completed")


async def post_shutdown(application: Application) -> None:
    """Post shutdown tasks"""
    logger.info("🛑 VPN Bot shutdown initiated")
    
    try:
        bot_info = await application.bot.get_me()
        shutdown_message = (
            "🛑 <b>VPN Bot остановлен</b>\n\n"
            f"🆔 Бот: @{bot_info.username}\n"
            f"📅 Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            "ℹ️ Бот временно недоступен."
        )
        
        for admin_id in Config.ADMIN_IDS:
            try:
                await application.bot.send_message(
                    chat_id=admin_id,
                    text=shutdown_message,
                    parse_mode='HTML'
                )
            except Exception as e:
                logger.warning(f"Failed to notify admin {admin_id}: {e}")
    except Exception as e:
        logger.error(f"Error during shutdown: {e}")
    
    # Close database connection
    global db_manager
    if db_manager:
        db_manager.close()
        logger.info("✅ Database connection closed")
    
    logger.info("✅ VPN Bot shutdown completed")


def main():
    """Main function to run the bot"""
    global db_manager
    
    logger.info("🚀 Starting VPN Telegram Bot...")
    
    try:
        # ✅ 1. Инициализация БД ПЕРЕД созданием application
        logger.info("🗄️ Initializing database...")
        db_manager = DatabaseManager(Config.DATABASE_URL)
        db_manager.create_tables()
        logger.info("✅ Database initialized successfully")
        
        # ✅ 2. Создаём приложение
        application = create_application()
        
        # ✅ 3. Делаем db_manager доступным в хендлерах
        application.bot_data['db_manager'] = db_manager
        
        # Set lifecycle hooks
        application.post_init = post_init
        application.post_shutdown = post_shutdown
        
        # Run the bot
        logger.info("⚡ Bot is starting polling...")
        application.run_polling(
            allowed_updates=["message", "callback_query"],
            drop_pending_updates=True,
            close_loop=False
        )
        
    except KeyboardInterrupt:
        logger.info("🛑 Bot stopped by user (Ctrl+C)")
    except Exception as e:
        logger.error(f"❌ Failed to start bot: {e}")
        logger.error(f"Traceback:\n{traceback.format_exc()}")
        raise


if __name__ == '__main__':
    main()