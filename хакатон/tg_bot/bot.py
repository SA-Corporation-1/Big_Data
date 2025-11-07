import asyncio
import logging
import re
import json
import aiohttp
import os
from datetime import datetime, timedelta, timezone
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart, StateFilter, Command
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.client.bot import Bot, DefaultBotProperties
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID"))
DB_FILE = 'complaints_db.jsonl'
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
VIDEO_GUIDE_FILE_ID = os.getenv("VIDEO_GUIDE_FILE_ID", "СІЗДІҢ_ВИДЕО_FILE_ID_ОСЫНДА") 

STATUS_NEW = "⏳ Қабылданды (Өңделуде)"
STATUS_RESOLVED = "✅ Шешілді"
STATUS_REJECTED = "❌ Бас тартылды"

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

ASPECT_KEYWORDS = {
    'Қызметкер әрекеті': [], 'Уақытылы келу': [], 'Автобус толымдылығы': [],
    'Автобус жағдайы': [], 'Қауіпсіздік': [], 'Төлем': [], 'Басқа': []
}
RECOMMENDATIONS_DB = {
    'Қызметкер әрекеті': 'Персоналмен (жүргізушілермен/кондукторлармен) мотивациялық және түсіндіру жұмыстарын күшейту.',
    'Уақытылы келу': 'Осы маршруттағы автобустар санын көбейту немесе кестені қайта қарастыру.',
    'Автобус толымдылығы': 'Пик сағаттарында маршрутқа қосымша, сыйымдылығы жоғары автобустарды қосу.',
    'Автобус жағдайы': 'Автобус паркінің санитарлық және техникалық жағдайын дереу тексеру.',
    'Қауіпсіздік': 'Жүргізушілерге қауіпсіз жүргізу бойынша қосымша нұсқаулық өткізу.',
    'Төлем': 'Төлем терминалдарының жұмысын тексеріп, ақауларды жою.',
    'Басқа': 'Жағдайды нақтылау үшін қосымша тексеру жүргізу.'
}
def get_priority(text, aspekt):
    text_lower = str(text).lower()
    if any(kw in text_lower for kw in ['апат', 'қауіпті', 'денсаулыққа', 'угроза']): return 'Шұғыл'
    if any(kw in text_lower for kw in ['үнемі', 'жиі', 'күнде', 'постоянно', 'всегда']): return 'Жоғары'
    if aspekt not in ['Басқа', 'Уақытылы келу']: return 'Орташа'
    return 'Төмен'

class ComplaintFSM(StatesGroup):
    waiting_for_route = State()
    waiting_for_aspect = State()
    waiting_for_date = State()
    waiting_for_time = State()
    waiting_for_bus_stop_name = State()
    waiting_for_description = State()
    waiting_for_action = State()

def get_start_keyboard():
    buttons = [[InlineKeyboardButton(text="📝 Жаңа Шағым Бастау", callback_data="start_complaint")]]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_action_keyboard(): 
    buttons = [
        [InlineKeyboardButton(text="📸 Дәлел Қосу (Фото/Видео/Дауыс)", callback_data="add_evidence")],
        [InlineKeyboardButton(text="✅ Шағымды Аяқтау", callback_data="finish_complaint")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_aspect_keyboard():
    builder = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=aspect)] for aspect in ASPECT_KEYWORDS.keys()],
        resize_keyboard=True, one_time_keyboard=True
    )
    return builder

def get_date_keyboard():
    builder = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Бүгін")], [KeyboardButton(text="Кеше")]],
        resize_keyboard=True, one_time_keyboard=True
    )
    return builder

def get_time_keyboard():
    builder = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🕒 Қазіргі уақыт")]],
        resize_keyboard=True, one_time_keyboard=True
    )
    return builder

def read_db():
    try:
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            return [json.loads(line) for line in lines]
    except FileNotFoundError:
        return []

def write_db(complaints):
    try:
        with open(DB_FILE, 'w', encoding='utf-8') as f:
            for complaint in complaints:
                f.write(json.dumps(complaint, ensure_ascii=False) + '\n')
    except Exception as e:
        logging.error(f"DB жазу қатесі (write_db): {e}")

async def send_to_webhook(data: dict):
    if not WEBHOOK_URL:
        logging.warning("WEBHOOK_URL .env файлында орнатылмаған. Webhook жіберілмеді.")
        return
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(WEBHOOK_URL, json=data) as response:
                if response.status == 200:
                    logging.info(f"Webhook-қа сәтті жіберілді (ID: {data.get('complaint_id')})")
                else:
                    logging.warning(f"Webhook қатесі: {response.status} - {await response.text()}")
    except aiohttp.ClientError as e:
        logging.error(f"Webhook-қа қосылу қатесі: {e}")
    except Exception as e:
        logging.error(f"Webhook-та күтпеген қате: {e}")

@dp.message(CommandStart(), StateFilter("*"))
async def send_welcome(message: Message, state: FSMContext):
    await state.clear()
    await message.reply(
        "Сәлеметсіз бе!\n\n"
        "Мен қоғамдық көлік жұмысы туралы шағымдарды қабылдайтын Интеллектуалды Агентпін.\n\n"
        "<b>Шағым тіркеу</b> үшін 📝 батырмасын басыңыз.\n"
        "<b>Көмек керек болса</b> /help деп жазыңыз.",
        reply_markup=get_start_keyboard()
    )

@dp.message(Command(commands=["admin"]), StateFilter("*"))
async def admin_panel(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_CHAT_ID:
        await message.reply("❌ Сізде бұл командаға рұқсат жоқ.")
        return
        
    all_complaints = read_db()
    new_complaints = [c for c in all_complaints if c.get('status') == STATUS_NEW]
    if not new_complaints:
        await message.reply("👍 Барлық шағымдар өңделген. Жаңа шағымдар жоқ.")
        return
    
    await message.reply(f"<b>--- 🛡️ БАСҚАРУ ПАНЕЛІ ---</b>\n"
                        f"Өңделуде тұрған <b>{len(new_complaints)}</b> шағым бар:")

    for complaint in reversed(new_complaints[-5:]):
        user = complaint.get('жалобщик', f"ID: {complaint['user_id']}")
        
        text = (
            f"<b>ID:</b> <code>#{complaint['complaint_id']}</code> - <b>{user}</b>\n"
            f"<b>Шағым:</b> {complaint.get('object')} - {complaint.get('aspect')}\n"
            f"<b>Оқиға:</b> {complaint.get('date_time', 'N/A')}\n"
            f"<b>Орны:</b> {complaint.get('location', 'Белгісіз')}\n"
            f"<b>Маңыздылығы:</b> {complaint.get('severty')}\n"
            f"<b>Сипаттамасы:</b> <i>«{complaint.get('description')}»</i>"
        )
        
        admin_kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Шешілді", callback_data=f"admin_resolve:{complaint['complaint_id']}"),
                InlineKeyboardButton(text="❌ Бас тарту", callback_data=f"admin_reject:{complaint['complaint_id']}")
            ]
        ])
        await message.answer(text, reply_markup=admin_kb)

@dp.message(Command(commands=["help"]), StateFilter("*"))
async def send_help(message: Message, state: FSMContext):
    await message.answer("Ботты қалай қолдану керек?")
    help_text = (
        "Бұл бот шағымдарды қадам-қадам қабылдайды:\n"
        "1️⃣ <b>/start</b> -> <b>[📝 Жаңа Шағым Бастау]</b> басыңыз.\n"
        "2️⃣ <b>Маршрут нөмірін</b> жазыңыз.\n"
        "3️⃣ <b>Проблема түрін</b> төменгі клавиатурадан таңдаңыз.\n"
        "4️⃣ <b>Оқиға күнін</b> таңдаңыз (мысалы: 'Бүгін').\n"
        "5️⃣ <b>Оқиға уақытын</b> ('🕒 Қазіргі уақыт') таңдаңыз немесе жазыңыз.\n"
        "6️⃣ <b>Аялдаманың атын</b> жазыңыз.\n"
        "7️⃣ <b>Толық сипаттаманы</b> жазыңыз.\n"
        "8️⃣ Соңында <b>[📸 Дәлел Қосу]</b> немесе <b>[✅ Аяқтау]</b> басыңыз."
    )
    await message.answer(help_text)
    if VIDEO_GUIDE_FILE_ID == "СІЗДІҢ_ВИДЕО_FILE_ID_ОСЫНДА":
        await message.answer("<i>(Бейне-нұсқаулық әлі жүктелмеген.)</i>")
    else:
        try:
            await message.answer_video(video=VIDEO_GUIDE_FILE_ID, caption="Міне, қысқаша бейне-нұсқаулық.")
        except Exception as e:
            logging.error(f"Бейне-нұсқаулық жіберу қатесі: {e}")

@dp.message(Command(commands=["get_id"]), F.video, StateFilter("*"))
async def get_video_id(message: Message, state: FSMContext):
    if message.from_user.id == ADMIN_CHAT_ID:
        await message.reply(f"🎥 <b>Бейне Файлының ID-і:</b>\n\n<code>{message.video.file_id}</code>\n\n"
                            f"↑ Осы ID-ді көшіріп, `.env` файлындағы `VIDEO_GUIDE_FILE_ID` орнына қойыңыз.")
    else:
        await message.reply("❌ Бұл жасырын админ командасы.")

@dp.callback_query(F.data == "start_complaint")
async def start_complaint_callback(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "<b>1-ҚАДАМ:</b> 🚌\n\n"
        "Шағым қай **маршрутқа** ('route_number') қатысты? \n"
        "<i>(Мысалы: 12, 105, 7)</i>"
    )
    await state.set_state(ComplaintFSM.waiting_for_route)
    await callback.answer()

@dp.message(ComplaintFSM.waiting_for_route, F.text)
async def handle_route(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.reply("❌ Қате. Тек маршруттың нөмірін (сандарды) жазыңыз. Мысалы: <i>7</i>")
        return
    await state.update_data(route_number=message.text)
    
    await message.reply(
        f"<b>2-ҚАДАМ:</b> 🛠️\n\n"
        f"Маршрут: <b>{message.text}</b>.\n"
        f"Проблеманың негізгі түрін таңдаңыз:",
        reply_markup=get_aspect_keyboard()
    )
    await state.set_state(ComplaintFSM.waiting_for_aspect)

@dp.message(ComplaintFSM.waiting_for_aspect, F.text)
async def handle_aspect(message: Message, state: FSMContext):
    if message.text not in ASPECT_KEYWORDS:
        await message.reply(
            "Түсінбедім. Өтінемін, төмендегі батырмалардың бірін таңдаңыз:",
             reply_markup=get_aspect_keyboard()
        )
        return
    await state.update_data(aspect=message.text)

    await message.reply(
        f"<b>3-ҚАДАМ:</b> 📅\n\n"
        f"Оқиға **қашан** болды? ('date')\n"
        f"Төменнен таңдаңыз немесе өзіңіз жазыңыз (мысалы: <i>06.11.2025</i>)",
        reply_markup=get_date_keyboard()
    )
    await state.set_state(ComplaintFSM.waiting_for_date)

@dp.message(ComplaintFSM.waiting_for_date, F.text)
async def handle_date(message: Message, state: FSMContext):
    date_text = message.text
    if date_text == "Бүгін":
        date_text = datetime.now().strftime('%Y-%m-%d')
    elif date_text == "Кеше":
        date_text = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    
    await state.update_data(incident_date=date_text)
    
    await message.reply(
        f"<b>4-ҚАДАМ:</b> ⏰\n\n"
        f"Оқиға шамамен <b>сағат нешеде</b> болды? ('time')\n"
        f"Дәл қазір болса, батырманы басыңыз, немесе уақытты өзіңіз жазыңыз (мысалы: <i>10:30</i>)",
        reply_markup=get_time_keyboard()
    )
    await state.set_state(ComplaintFSM.waiting_for_time)

@dp.message(ComplaintFSM.waiting_for_time, F.text)
async def handle_time(message: Message, state: FSMContext):
    time_text = message.text
    
    if time_text == "🕒 Қазіргі уақыт":
        time_text = datetime.now().strftime('%H:%M')
    
    await state.update_data(incident_time=time_text)

    await message.reply(
        f"<b>5-ҚАДАМ:</b> 🚌\n\n"
        f"Оқиға болған <b>аялдаманың атын</b> жазыңыз.\n"
        f"<i>(Мысалы: Астана Балет, Керуен)</i>",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(ComplaintFSM.waiting_for_bus_stop_name)

@dp.message(ComplaintFSM.waiting_for_bus_stop_name, F.text)
async def handle_bus_stop_name(message: Message, state: FSMContext):
    location_data = f"Аялдама: {message.text}"
    await state.update_data(location=location_data)
    
    await message.reply(
        f"<b>6-ҚАДАМ (Соңғы):</b> 💬\n\n"
        f"Аялдама ({message.text}) қабылданды. Енді оқиғаны толығырақ <b>сипаттап</b> ('description') беріңіз.",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(ComplaintFSM.waiting_for_description)

@dp.message(ComplaintFSM.waiting_for_description, F.text)
async def handle_description_and_finalize(message: Message, state: FSMContext):
    data = await state.get_data()
    route = data.get('route_number', 'Белгісіз')
    aspect = data.get('aspect', 'Басқа')
    incident_date = data.get('incident_date', 'Белгісіз')
    incident_time = data.get('incident_time', 'N/A')
    location = data.get('location', 'Белгісіз')
    description = message.text
    
    severity = get_priority(description, aspect) 
    complaint_id = int(datetime.now().timestamp())
    date_time_combined = f"{incident_date} {incident_time}"
    full_complaint_text = (
        f"Маршрут: {route}. Проблема: {aspect}. \n"
        f"Күні/Уақыты: {date_time_combined}. \n"
        f"Орны: {location}. \n"
        f"Сипаттамасы: {description}"
    )
    
    result = {
        'complaint_id': complaint_id,
        'жалобщик': message.from_user.username or f"ID: {message.from_user.id}",
        'user_id': message.from_user.id,
        'object': f"Маршрут {route}",
        'route_number': route,
        'date_time': date_time_combined,
        'location': location,
        'aspect': aspect,
        'description': description,
        'severty': severity,
        'full_complaint': full_complaint_text,
        'status': STATUS_NEW,
        'recommendation_kz': RECOMMENDATIONS_DB.get(aspect, RECOMMENDATIONS_DB['Басқа']),
        'timestamp_filed': datetime.now().isoformat()
    }
    
    write_db(read_db() + [result])
    await send_to_webhook(result)
        
    response_text = (
        f"<b>✅ Шағымыңыз (ID: #{complaint_id}) қабылданды!</b>\n\n"
        f"<b>Сіздің деректеріңіз:</b>\n"
        f"<b>- Маршрут:</b> {route}\n"
        f"<b>- Күні/Уақыты:</b> {date_time_combined}\n"
        f"<b>- Орны:</b> {location}\n"
        f"<b>- Проблема:</b> {aspect}\n\n"
        f"<b>Талдау нәтижесі:</b>\n"
        f"<b>- Статус:</b> {STATUS_NEW}\n"
        f"<b>- Маңыздылығы:</b> {severity}\n\n"
        f"--- \n"
        f"Енді осы шағымға <b>дәлелдеме (фото/видео/дауыс)</b> қоса аласыз ба?"
    )
    
    await state.update_data(current_complaint_id=complaint_id)
    await state.set_state(ComplaintFSM.waiting_for_action) 
    await message.reply(response_text, reply_markup=get_action_keyboard())

@dp.callback_query(ComplaintFSM.waiting_for_action, F.data == "add_evidence")
async def add_evidence_callback(callback: CallbackQuery, state: FSMContext):
    await callback.message.reply("Дәлелдемеңізді жіберіңіз (фото, видео, аудиофайл немесе дауыстық хабарлама).")
    await callback.answer()

@dp.callback_query(ComplaintFSM.waiting_for_action, F.data == "finish_complaint")
async def finish_complaint_callback(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    complaint_id = data.get('current_complaint_id', 'N/A')
    await callback.message.edit_text(
        f"✅ Рахмет! Сіздің <b>Шағымыңыз (ID: #{complaint_id})</b> толығымен тіркелді.\n\n"
        f"Жаңа шағым бастау үшін /start командасын қайта басыңыз."
    )
    await state.clear()
    await callback.answer()

@dp.message(ComplaintFSM.waiting_for_action, F.photo | F.video | F.audio | F.voice | F.document)
async def handle_media(message: Message, state: FSMContext):
    data = await state.get_data()
    complaint_id = data.get('current_complaint_id', 'N/A')
    if complaint_id == 'N/A':
        await message.reply("❌ Қате пайда болды. /start деп қайта бастаңыз.")
        await state.clear()
        return
    try:
        caption = (f"⚠️ <b>Жаңа Дәлелдеме</b> ⚠️\n\n<b>Шағым ID:</b> <code>#{complaint_id}</code>\n"
                   f"<b>Пайдаланушы:</b> @{message.from_user.username} (ID: <code>{message.from_user.id}</code>)")
        await message.copy_to(chat_id=ADMIN_CHAT_ID, caption=caption)
        await message.reply(
            f"✅ Дәлелдемеңіз <b>(Шағым #{complaint_id} үшін)</b> қабылданды.\n\n"
            "Тағы да дәлелдеме қосасыз ба, әлде шағымды аяқтайсыз ба?",
            reply_markup=get_action_keyboard()
        )
    except Exception as e:
        logging.error(f"Медиа жіберу қатесі: {e}")
        await message.reply("❌ Кешірініз, файлды админге жіберу кезінде қате пайда болды.")

@dp.message(ComplaintFSM.waiting_for_action)
async def wrong_input_at_action_stage(message: Message, state: FSMContext):
    
    if message.text:
        if message.text.startswith('/'):
            if message.text == '/start':
                await send_welcome(message, state)
                return
            elif message.text == '/help':
                await send_help(message, state)
                return
            elif message.text == '/admin':
                await admin_panel(message, state)
                return
            else:
                await message.reply(
                    "Түсінбедім. Команданы дұрыс жазыңыз немесе батырманы басыңыз.",
                    reply_markup=get_action_keyboard()
                )
                return

        await message.reply(
            "Түсінбедім. Өтінемін, төмендегі батырмалардың бірін басыңыз.",
            reply_markup=get_action_keyboard()
        )
        return

    await message.reply(
        "Түсінбедім. Тек батырманы басыңыз немесе фото/видео жіберіңіз.",
        reply_markup=get_action_keyboard()
    )

@dp.callback_query(F.data.startswith("admin_resolve:") | F.data.startswith("admin_reject:"))
async def handle_admin_action(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_CHAT_ID:
        await callback.answer("❌ Рұқсат жоқ!", show_alert=True)
        return
    action, complaint_id_str = callback.data.split(":")
    complaint_id = int(complaint_id_str)
    new_status = STATUS_RESOLVED if action == "admin_resolve" else STATUS_REJECTED
    
    all_complaints = read_db()
    target_complaint = None
    for i, complaint in enumerate(all_complaints):
        if complaint.get('complaint_id') == complaint_id:
            all_complaints[i]['status'] = new_status
            target_complaint = all_complaints[i]
            break
            
    if not target_complaint:
        await callback.answer(f"❌ Қате: Шағым #{complaint_id} табылмады.", show_alert=True)
        return
        
    write_db(all_complaints) 
    
    try:
        user_id_to_notify = target_complaint['user_id']
        push_message = (
            f"🔔 <b>Статус Жаңартуы</b> 🔔\n\n"
            f"Сіздің <b>#{complaint_id}</b> ID-нөмірлі шағымыңыз бойынша жаңа статус:\n\n"
            f"<b>{new_status}</b>\n\n<i>Көмегіңізге рахмет!</i>"
        )
        await bot.send_message(chat_id=user_id_to_notify, text=push_message)
    except Exception as e:
        logging.error(f"ПУШ жіберу қатесі (ID: {user_id_to_notify}): {e}")
    
    await callback.message.edit_text(
        callback.message.text + f"\n\n<b>--- ADMIN: Статус орнатылды: {new_status} ---</b>"
    )
    await callback.answer(f"Статус #{complaint_id} үшін '{new_status}' деп өзгертілді!")

async def main():
    if not ADMIN_CHAT_ID:
        logging.critical("ҚАТЕ: 'ADMIN_CHAT_ID' .env файлында орнатылмаған.")
        return
    if not BOT_TOKEN:
        logging.critical("ҚАТЕ: 'BOT_TOKEN' .env файлында орнатылмаған. @BotFather арқылы токен алыңыз.")
        return
    if not WEBHOOK_URL:
        logging.warning("ЕСКЕРТУ: 'WEBHOOK_URL' .env файлында орнатылмаған. Make.com интеграциясы істемейді.")
    
    logging.info("Бот іске қосылуда (Таза нұсқа: Тек Аялдама)...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Бот тоқтатылды.")