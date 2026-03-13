import os
import telebot
import sqlite3
import datetime
from telebot import types
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'Bot is running')
    
    def log_message(self, format, *args):
        # Отключаем логирование запросов
        pass

def run_http_server():
    server = HTTPServer(('0.0.0.0', 10000), SimpleHandler)
    server.serve_forever()

# Запускаем HTTP-сервер в отдельном потоке
thread = threading.Thread(target=run_http_server, daemon=True)
thread.start()

# ========== НАСТРОЙКИ ==========
BOT_TOKEN = os.environ.get('BOT_TOKEN')
TEACHER_ID = int(os.environ.get('TEACHER_ID', 0))  # 0 — значение по умолчанию, если переменная не задана
GROUP_NAME = "ПИГМУ-25"
# ================================

conn = sqlite3.connect('attendance.db', check_same_thread=False)
cursor = conn.cursor()

cursor.execute('''
    CREATE TABLE IF NOT EXISTS students (
        telegram_id INTEGER PRIMARY KEY,
        full_name TEXT NOT NULL
    )
''')

cursor.execute('''
    CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER NOT NULL,
        date TEXT NOT NULL,
        checkin_time TEXT NOT NULL,
        FOREIGN KEY(student_id) REFERENCES students(telegram_id)
    )
''')
conn.commit()

bot = telebot.TeleBot(BOT_TOKEN)

def today_str():
    return datetime.date.today().isoformat()

# ========== КОМАНДЫ ==========

@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    cursor.execute("SELECT full_name FROM students WHERE telegram_id = ?", (user_id,))
    student = cursor.fetchone()
    if student:
        show_checkin_button(message.chat.id, f"С возвращением, {student[0]}! Нажмите кнопку, чтобы отметить посещение.")
    else:
        msg = bot.send_message(message.chat.id, "Добро пожаловать! Введите ваше полное имя (ФИО):")
        bot.register_next_step_handler(msg, process_name)

def process_name(message):
    user_id = message.from_user.id
    full_name = message.text.strip()
    cursor.execute("INSERT INTO students (telegram_id, full_name) VALUES (?, ?)",
                   (user_id, full_name))
    conn.commit()
    bot.send_message(message.chat.id, f"Регистрация завершена, {full_name}!")
    show_checkin_button(message.chat.id, "Теперь вы можете отмечаться кнопкой ниже.")

def show_checkin_button(chat_id, text):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn = types.KeyboardButton("✅ Отметиться")
    markup.add(btn)
    bot.send_message(chat_id, text, reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == "✅ Отметиться")
def checkin(message):
    user_id = message.from_user.id
    today = today_str()
    now_time = datetime.datetime.now().strftime("%H:%M:%S")

    cursor.execute("SELECT full_name FROM students WHERE telegram_id = ?", (user_id,))
    student = cursor.fetchone()
    if not student:
        bot.send_message(message.chat.id, "Вы не зарегистрированы. Напишите /start для регистрации.")
        return

    cursor.execute("SELECT id FROM attendance WHERE student_id = ? AND date = ?", (user_id, today))
    if cursor.fetchone():
        bot.send_message(message.chat.id, "Вы уже отмечались сегодня.")
        return

    cursor.execute("INSERT INTO attendance (student_id, date, checkin_time) VALUES (?, ?, ?)",
                   (user_id, today, now_time))
    conn.commit()
    bot.send_message(message.chat.id, f"✅ Вы отмечены в {now_time}. Хорошего дня!")

@bot.message_handler(commands=['report'])
def report(message):
    if message.from_user.id != TEACHER_ID:
        bot.send_message(message.chat.id, "Нет доступа.")
        return

    # Определяем дату: если передан параметр, используем его, иначе сегодня
    parts = message.text.split()
    if len(parts) >= 2:
        date_arg = parts[1]
        try:
            datetime.datetime.strptime(date_arg, "%Y-%m-%d")
            target_date = date_arg
        except ValueError:
            bot.send_message(message.chat.id, "Неверный формат даты. Используйте ГГГГ-ММ-ДД (например, 2025-03-05).")
            return
    else:
        target_date = today_str()

    # Получаем всех студентов
    cursor.execute("SELECT telegram_id, full_name FROM students")
    all_students = cursor.fetchall()
    if not all_students:
        bot.send_message(message.chat.id, "Нет зарегистрированных студентов.")
        return

    # Получаем отметившихся в указанную дату
    cursor.execute("SELECT student_id FROM attendance WHERE date = ?", (target_date,))
    attended_ids = {row[0] for row in cursor.fetchall()}

    present = []
    absent = []
    for student_id, name in all_students:
        if student_id in attended_ids:
            present.append(name)
        else:
            absent.append(name)

    present_list = "\n".join([f"✅ {name}" for name in present]) if present else "✅ Никого нет"
    absent_list = "\n".join([f"❌ {name}" for name in absent]) if absent else "❌ Все присутствуют"

    report_text = f"📊 Отчёт по группе {GROUP_NAME} на {target_date}:\n\nПРИСУТСТВОВАЛИ:\n{present_list}\n\nОТСУТСТВОВАЛИ:\n{absent_list}"
    bot.send_message(message.chat.id, report_text)

@bot.message_handler(commands=['help'])
def help_command(message):
    help_text = f"""
👨‍🎓 Бот для отметки посещаемости группы {GROUP_NAME}

Для студентов:
• /start – зарегистрироваться (если ещё не) и получить кнопку отметки
• Нажмите кнопку "✅ Отметиться" – отметка за сегодня

Для преподавателя:
• /report – отчёт за сегодня
• /report ГГГГ-ММ-ДД – отчёт за конкретную дату (например, /report 2025-03-05)

    """#Все данные хранятся локально в файле attendance.db.
    bot.send_message(message.chat.id, help_text)

# Заглушка для любых других сообщений
@bot.message_handler(func=lambda message: True)
def echo(message):
    bot.send_message(message.chat.id, "Я понимаю только команды /start , /help , /report и кнопку 'Отметиться'.")

if __name__ == "__main__":
    print("Бот запущен...")
    bot.infinity_polling()
