from flask import jsonify, render_template, request, redirect, url_for, session, flash
from flask_login import current_user
import os
import threading
import time
import json
import logging

from app import app, db
from models import User, Message
from replit_auth import login_required, make_replit_blueprint
from telegram_bot import start_telegram_bot, get_bot_status
from router.hybrid_router import HybridRouter

# Set up logging
logger = logging.getLogger(__name__)

# Register Replit Auth blueprint
app.register_blueprint(make_replit_blueprint(), url_prefix="/auth")

# Make session permanent
@app.before_request
def make_session_permanent():
    session.permanent = True

# Global variables
bot_thread = None
bot_started = False
hybrid_router = None

# Home route - accessible without login
@app.route('/')
def home():
    """Render the home page"""
    return render_template('index.html')

# Admin dashboard - requires login
@app.route('/dashboard')
@login_required
def dashboard():
    """Admin dashboard page"""
    # Check if user is admin, if not redirect to chat
    if not current_user.is_admin:
        return redirect(url_for('chat'))
    
    status = get_bot_status()
    return render_template('dashboard.html', 
                           status=status, 
                           bot_started=bot_started)

# Chat interface - requires login
@app.route('/chat')
@login_required
def chat():
    """Chat interface page"""
    # Get user's previous messages
    messages = Message.query.filter_by(user_id=current_user.id).order_by(Message.created_at.desc()).limit(10).all()
    
    return render_template('chat.html', 
                           messages=messages)

# Send message API
@app.route('/api/send', methods=['POST'])
@login_required
def send_message():
    """API endpoint to send a message to Replit Agent"""
    content = request.json.get('message', '')
    
    if not content:
        return jsonify({'error': 'Message is required'}), 400
    
    # Create message record
    message = Message(
        user_id=current_user.id,
        content=content
    )
    db.session.add(message)
    db.session.commit()
    
    # If bot is not running, start it
    global bot_started, hybrid_router
    if not bot_started:
        flash("Bot is not running. Please ask an admin to start it.", "warning")
        return jsonify({
            'error': 'Bot is not running',
            'message_id': message.id
        }), 503
    
    try:
        # Initialize router if not already done
        if hybrid_router is None:
            hybrid_router = HybridRouter()
        
        # Send message to Replit Agent using async methods but in a sync way
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        response = loop.run_until_complete(hybrid_router.send_message(content))
        loop.close()
        
        # Update message with response
        message.response = response
        db.session.commit()
        
        return jsonify({
            'response': response,
            'message_id': message.id
        })
    except Exception as e:
        logger.error(f"Error sending message: {e}")
        return jsonify({
            'error': str(e),
            'message_id': message.id
        }), 500

# Bot control API endpoints - admin only
@app.route('/api/start', methods=['POST'])
@login_required
def start_bot_api():
    """API endpoint to start the Telegram bot"""
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403
    
    global bot_thread, bot_started
    
    if not bot_started:
        bot_thread = threading.Thread(target=start_bot_thread)
        bot_thread.daemon = True
        bot_thread.start()
        bot_started = True
        logger.info("Bot started from dashboard by user %s", current_user.id)
        
    return jsonify({'status': 'started'})

@app.route('/api/stop', methods=['POST'])
@login_required
def stop_bot_api():
    """API endpoint to stop the Telegram bot"""
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403
    
    global bot_started
    
    if bot_started:
        # Signal bot to stop - implementation depends on your bot architecture
        bot_started = False
        logger.info("Bot stopped from dashboard by user %s", current_user.id)
    
    return jsonify({'status': 'stopped'})

# Status API endpoint
@app.route('/api/status')
@login_required
def status_api():
    """API endpoint to get the bot status"""
    status = get_bot_status()
    status['is_running'] = bot_started
    return jsonify(status)

@app.route('/api/messages')
@login_required
def get_messages():
    """API endpoint to get user's messages"""
    limit = int(request.args.get('limit', 10))
    offset = int(request.args.get('offset', 0))
    
    if current_user.is_admin and request.args.get('all') == 'true':
        # Admin can see all messages
        messages = Message.query.order_by(Message.created_at.desc()).limit(limit).offset(offset).all()
    else:
        # Users can only see their own messages
        messages = Message.query.filter_by(user_id=current_user.id).order_by(
            Message.created_at.desc()).limit(limit).offset(offset).all()
    
    return jsonify([{
        'id': msg.id,
        'content': msg.content,
        'response': msg.response,
        'created_at': msg.created_at.isoformat(),
        'user_id': msg.user_id,
        'telegram_user_id': msg.telegram_user_id
    } for msg in messages])

def start_bot_thread():
    """Start the Telegram bot in a separate thread"""
    try:
        # Ensure storage directories exist
        os.makedirs('./storage', exist_ok=True)
        os.makedirs('./logs', exist_ok=True)
        
        # Check for Telegram bot token
        telegram_token = os.environ.get('TELEGRAM_BOT_TOKEN')
        if not telegram_token:
            logger.error("TELEGRAM_BOT_TOKEN environment variable not set")
            return
        
        # Start the bot in threaded mode
        logger.info("Starting Telegram bot in threaded mode...")
        start_telegram_bot(threaded_mode=True)
    except Exception as e:
        logger.error(f"Error starting bot: {e}")
        import traceback
        logger.error(traceback.format_exc())

# Auto-start bot on application start if configured
def auto_start_bot_on_startup():
    """Auto-start the bot if configured"""
    auto_start = os.environ.get('AUTO_START_BOT', 'false').lower() == 'true'
    telegram_token = os.environ.get('TELEGRAM_BOT_TOKEN')
    
    global bot_thread, bot_started
    
    if auto_start and telegram_token and not bot_started:
        logger.info("Auto-starting bot...")
        bot_thread = threading.Thread(target=start_bot_thread)
        bot_thread.daemon = True
        bot_thread.start()
        bot_started = True

# Register auto_start_bot to run on first request
@app.before_request
def check_auto_start():
    global bot_started
    if not bot_started and request.endpoint not in ['static']:
        auto_start_bot_on_startup()