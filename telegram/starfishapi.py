from flask import Flask, request
import telebot
import os
from starfishdb import StarfishDB
from threading import Thread
import time

# Constants for testing
TEACHER_USERNAME = 'teacher_username'  # Replace with actual teacher username

# Initialize Flask app
app = Flask(__name__)

# Initialize the bot with your bot token
bot = telebot.TeleBot(os.getenv('BOT_TOKEN'), parse_mode=None)
db = StarfishDB()

# When user uses /start command and username exists in the database

@bot.message_handler(commands=['start'], func=lambda message: db.user_exists(message.chat.username))
def start(message):
    # Get all chat information
    chat_id, username = message.chat.id, message.chat.username

    # Upudates the channel id for the user
    db.update_channel_id(username, chat_id)
    
    bot.send_message(chat_id, f"(Name) is now verified as {username}.\nChannel ID: {chat_id}")
    bot.send_message(db.get_channel_id(TEACHER_USERNAME), f"(Name) is now verified as {username}.\nChannel ID: {chat_id}")

# Set up webhook route for Telegram
@app.route('/send_message', methods=['POST'])
def send_message():
    # Get the username and message from the request
    username = request.json['username']
    message_to_send = request.json['message']
    
    # Send the message to the user
    message = bot.send_message(db.get_channel_id(username), message_to_send)

    # Register the next step handler (uses message.chat.id)
    bot.register_next_step_handler(message, confirmation)
    return 'Message sent!'
    
def confirmation(message):
    # Get all chat information
    chat_id, username, text = message.chat.id, message.chat.username, message.text.strip()
    
    bot.send_message(chat_id, f"Confirm that this is your reason for being late (yes/no):\n<i><b>{text}</b></i>", parse_mode="html")
    
    # Confirm the reason
    bot.register_next_step_handler(message, handle_reason, text)

def handle_reason(message, reason):
    # Get all chat information
    chat_id, username, text = message.chat.id, message.chat.username, message.text.strip()
    
    if text.lower() == "yes":
        bot.send_message(chat_id, "Your reason has been recorded.")
        
        # Notify the teacher
        bot.send_message(db.get_channel_id(TEACHER_USERNAME), f"{username} late due to:\n{reason}")
        
        # Update the reason in the database
        db.update_reason(username, reason)
        
        return
    # If the user does not confirm the reason
    bot.send_message(chat_id, "Please re-enter your reason.")
    bot.register_next_step_handler(message, confirmation)

def run_flask():
    app.run(port=5001, threaded=True)

def run_bot():
    bot.polling(none_stop=True)

if __name__ == '__main__':
    flask_thread = Thread(target=run_flask) # For interacting with Telegram after sending messages
    bot_thread = Thread(target=run_bot) # For interacting with Telegram after receiving messages
    
    flask_thread.daemon = True
    bot_thread.daemon = True
    
    flask_thread.start()
    bot_thread.start()
    
    # To stop the threads
    try:
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nCtrl+C pressed. Stopping threads...")
        exit(1)
