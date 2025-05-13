import os
import sys
import logging
import asyncio
import time
from datetime import datetime, timedelta
import threading
import traceback
import json

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Updater,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    Filters,
    CallbackContext
)

from router.hybrid_router import HybridRouter, RouterMethod
from auth.token_manager import TokenManager
import utils

# Setup logger
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Global variables
token_manager = TokenManager(storage_dir="./storage")
active_routers = {}  # Store router instances for active users
start_time = time.time()
bot_status = {
    "active_sessions": 0,
    "processed_messages": 0,
    "errors": 0,
    "uptime": 0
}

def get_bot_status():
    """Return the current status of the bot"""
    bot_status["uptime"] = format_uptime(time.time() - start_time)
    bot_status["active_sessions"] = len(active_routers)
    return bot_status

def start_command(update: Update, context: CallbackContext) -> None:
    """Handle the /start command"""
    user = update.effective_user
    user_id = str(user.id)
    
    logger.info(f"User {user_id} ({user.first_name}) started the bot")
    
    update.message.reply_text(
        f"Hi {user.first_name}! I'm your direct connection to Replit AI. Just send me a message and I'll forward it to Replit.\n\n"
        "There's no need to use any special commands or prefixes - just talk to me as you would to Replit directly!\n\n"
        "Type /help to see all available commands."
    )

def help_command(update: Update, context: CallbackContext) -> None:
    """Handle the /help command"""
    update.message.reply_text(
        "Here are the commands you can use:\n\n"
        "/start - Start the bot\n"
        "/help - Show this help message\n"
        "/status - Show the current status of the bot\n"
        "/reset - Reset your session (use if you experience issues)\n\n"
        "You don't need any special commands to talk to Replit. Just send me your message directly!"
    )

def status_command(update: Update, context: CallbackContext) -> None:
    """Handle the /status command"""
    user_id = str(update.effective_user.id)
    status = get_bot_status()
    
    user_router = active_routers.get(user_id)
    user_stats = user_router.get_stats() if user_router else {"total_calls": 0}
    
    message = (
        f"🤖 *Bot Status*\n"
        f"Uptime: {status['uptime']}\n"
        f"Active sessions: {status['active_sessions']}\n"
        f"Total messages processed: {status['processed_messages']}\n"
        f"Errors: {status['errors']}\n\n"
        f"👤 *Your Session*\n"
        f"Messages sent: {user_stats.get('total_calls', 0)}\n"
        f"Success rate: {user_stats.get('success_rate', 0)}%\n"
        f"Method used: {user_stats.get('last_method', 'None')}\n"
    )
    
    update.message.reply_text(message, parse_mode="Markdown")

def reset_command(update: Update, context: CallbackContext) -> None:
    """Handle the /reset command"""
    user_id = str(update.effective_user.id)
    
    if user_id in active_routers:
        router = active_routers[user_id]
        
        # Create a new thread to close the router so we don't block
        def close_router():
            asyncio.run(router.close())
        
        thread = threading.Thread(target=close_router)
        thread.daemon = True
        thread.start()
        
        del active_routers[user_id]
        
        # Optionally clear user tokens
        token_manager.delete_user_tokens(user_id)
        
        update.message.reply_text(
            "Your session has been reset. All connection data has been cleared.\n"
            "You can continue with a fresh session now!"
        )
    else:
        update.message.reply_text(
            "You don't have an active session to reset."
        )

def handle_message(update: Update, context: CallbackContext) -> None:
    """Handle incoming messages from users"""
    try:
        user = update.effective_user
        user_id = str(user.id)
        message_text = update.message.text
        
        # Skip processing on empty messages
        if not message_text or message_text.isspace():
            update.message.reply_text("I received an empty message. Please send me some text to process.")
            return
        
        # Log the incoming message
        logger.info(f"Received message from {user_id} ({user.first_name}): {message_text[:50]}...")
        
        # Send typing action
        context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        
        # Get or create router for this user
        if user_id not in active_routers:
            logger.info(f"Creating new router for user {user_id}")
            cookies_file = os.environ.get("COOKIES_FILE", "./storage/cookies.json")
            
            # Create a new router
            router = HybridRouter(
                user_id=user_id,
                token_manager=token_manager,
                cookies_file=cookies_file,
                method=RouterMethod.AUTO
            )
            
            active_routers[user_id] = router
        else:
            router = active_routers[user_id]
        
        # Use the message reference for reply tracking
        message_reference = update.message
        initial_reply = message_reference.reply_text(
            "Connecting to Replit AI...",
            quote=True
        )
        
        # Run the async router message sending in a separate thread
        def process_message():
            try:
                # Create an event loop for async operations
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                response_buffer = ""
                last_update_time = time.time()
                UPDATE_INTERVAL = 1  # Update message every second
                
                # Callback for streaming updates
                async def update_callback(content):
                    nonlocal response_buffer, last_update_time
                    response_buffer += content
                    
                    # Only update the message periodically to avoid Telegram API limits
                    current_time = time.time()
                    if current_time - last_update_time >= UPDATE_INTERVAL:
                        # Format and truncate response if needed
                        formatted_response = format_response_for_telegram(response_buffer)
                        
                        try:
                            context.bot.edit_message_text(
                                chat_id=update.effective_chat.id,
                                message_id=initial_reply.message_id,
                                text=formatted_response
                            )
                            last_update_time = current_time
                        except Exception as e:
                            logger.warning(f"Failed to update message: {e}")
                
                # Send the message to Replit
                response = loop.run_until_complete(router.send_message(message_text, on_update=update_callback))
                
                # Update metrics
                bot_status["processed_messages"] += 1
                
                # Format and send the final response
                formatted_response = format_response_for_telegram(response)
                
                if not formatted_response or formatted_response.isspace():
                    formatted_response = "I received an empty response from Replit AI. Please try again or reset your session with /reset."
                
                # Final update of the message
                try:
                    context.bot.edit_message_text(
                        chat_id=update.effective_chat.id,
                        message_id=initial_reply.message_id,
                        text=formatted_response
                    )
                except Exception as e:
                    # If editing fails (e.g., message too long), send as a new message
                    logger.warning(f"Failed to edit message: {e}")
                    context.bot.send_message(
                        chat_id=update.effective_chat.id,
                        text="The response is too long for a single message. Here's the complete response:"
                    )
                    
                    # Split the response into chunks of 4000 characters
                    for i in range(0, len(formatted_response), 4000):
                        chunk = formatted_response[i:i+4000]
                        if chunk:
                            context.bot.send_message(
                                chat_id=update.effective_chat.id,
                                text=chunk
                            )
                
                # Close the event loop
                loop.close()
                
            except Exception as e:
                logger.error(f"Error processing message: {e}")
                logger.error(traceback.format_exc())
                bot_status["errors"] += 1
                
                try:
                    context.bot.send_message(
                        chat_id=update.effective_chat.id,
                        text=f"An error occurred while processing your message: {str(e)}\n"
                              "Please try again or use /reset to reset your session."
                    )
                except Exception:
                    # In case we can't reply to the original message
                    pass
        
        # Start processing thread
        process_thread = threading.Thread(target=process_message)
        process_thread.daemon = True
        process_thread.start()
        
    except Exception as e:
        logger.error(f"Error handling message: {e}")
        logger.error(traceback.format_exc())
        bot_status["errors"] += 1
        
        try:
            update.message.reply_text(
                f"An error occurred while processing your message: {str(e)}\n"
                "Please try again or use /reset to reset your session."
            )
        except Exception:
            # In case we can't reply to the original message
            pass

def format_uptime(seconds):
    """Format uptime in seconds to a human-readable format"""
    delta = timedelta(seconds=int(seconds))
    days = delta.days
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    
    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    parts.append(f"{seconds}s")
    
    return " ".join(parts)

def format_response_for_telegram(text):
    """Format text for Telegram, ensuring it's within limits"""
    if not text:
        return ""
    
    # Telegram has a 4096 character limit per message
    # We'll keep it to 4000 to be safe
    MAX_LENGTH = 4000
    
    if len(text) <= MAX_LENGTH:
        return text
    
    # If longer than the limit, truncate and add indicator
    return text[:MAX_LENGTH - 3] + "..."

async def error_handler(update, context):
    """Handle errors in the telegram bot"""
    logger.error(f"Update {update} caused error {context.error}")
    logger.error(traceback.format_exc())
    bot_status["errors"] += 1

# Global variable to store the bot updater
bot_updater = None

def start_telegram_bot(threaded_mode=False):
    """Start the Telegram bot
    
    Args:
        threaded_mode (bool): Whether the bot is being run in a thread
    
    Returns:
        The updater object
    """
    # Get bot token from environment
    telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    
    if not telegram_token:
        logger.error("TELEGRAM_BOT_TOKEN not set in environment variables")
        return None
    
    # Create a global token manager
    global token_manager, bot_updater
    
    # Create and configure the bot with Updater (for python-telegram-bot v13.x)
    updater = Updater(token=telegram_token, use_context=True)
    dispatcher = updater.dispatcher
    
    # Add handlers
    dispatcher.add_handler(CommandHandler("start", start_command))
    dispatcher.add_handler(CommandHandler("help", help_command))
    dispatcher.add_handler(CommandHandler("status", status_command))
    dispatcher.add_handler(CommandHandler("reset", reset_command))
    
    # Message handler for all other messages
    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))
    
    # Error handler
    dispatcher.add_error_handler(error_handler)
    
    # Start the bot
    logger.info("Starting Telegram bot")
    updater.start_polling()
    
    # Store the updater for later use
    bot_updater = updater
    
    # Only use idle() when not in threaded mode
    # This avoids the signal handler error
    if not threaded_mode:
        logger.info("Running in main process mode")
        updater.idle()
    else:
        logger.info("Running in threaded mode - no signal handlers")
    
    return updater

if __name__ == "__main__":
    # Create storage directory if it doesn't exist
    os.makedirs("./storage", exist_ok=True)
    
    # Start the bot
    start_telegram_bot()