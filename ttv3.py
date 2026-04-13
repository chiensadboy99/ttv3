import json
import os
import random
import asyncio
import logging
import aiohttp
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)
from datetime import datetime, timedelta, timezone

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Data files
DATA_FILE = "thanhtungbase.json"
HISTORY_FILE = "thanhtunghistory.json"
ADMIN_FILE = "admctv.json"

# Bot token
BOT_TOKEN = "88684463452:AAF63cKhatW3kk1ZLORZEfN6j7kzfGQjLiI"

# API URL
API_URL = "https://docquyen9-production.up.railway.app"

# Default admin IDs
DEFAULT_ADMIN_IDS = ["7071414779", "7071414779"]

# Default data structure
DEFAULT_DATA = {
    "users": {},
    "keys": {},
    "running": {},
    "last_prediction": {},
    "last_session": {}
}

# Khóa để đồng bộ đọc/ghi file JSON
file_lock = asyncio.Lock()

# Dictionary để lưu các tác vụ api_listener đang chạy
running_tasks = {}

# JSON file read/write functions
async def load_data():
    async with file_lock:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r") as f:
                return json.load(f)
        return DEFAULT_DATA

async def save_data(data):
    async with file_lock:
        with open(DATA_FILE, "w") as f:
            json.dump(data, f, indent=4)

async def load_history():
    async with file_lock:
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, "r") as f:
                return json.load(f)
        return []

async def save_history(history):
    async with file_lock:
        with open(HISTORY_FILE, "w") as f:
            json.dump(history, f, indent=4)

async def load_admins():
    async with file_lock:
        if os.path.exists(ADMIN_FILE):
            with open(ADMIN_FILE, "r") as f:
                return json.load(f)
        return {"admins": DEFAULT_ADMIN_IDS}

async def save_admins(admins):
    async with file_lock:
        with open(ADMIN_FILE, "w") as f:
            json.dump(admins, f, indent=4)

# Check if user is admin
async def is_admin(user_id):
    admins = await load_admins()
    return str(user_id) in admins["admins"]

# Check if user has an active package
async def has_active_package(user_id, data):
    user = data["users"].get(str(user_id), {})
    if not user.get("package") or not user.get("expiry_date"):
        logger.info(f"User {user_id} has no package or expiry_date: {user}")
        return False
    
    package = user["package"].lower()
    if package not in ["basic"]:
        logger.info(f"User {user_id} has invalid package: {package}")
        return False
    
    try:
        expiry = datetime.fromisoformat(user["expiry_date"])
        is_active = expiry > datetime.now(timezone.utc)
        if not is_active:
            logger.info(f"User {user_id} package expired: {expiry}")
        return is_active
    except (ValueError, TypeError) as e:
        logger.error(f"Invalid expiry_date for user {user_id}: {user.get('expiry_date')}, error: {e}")
        return False

# Generate random key
def generate_key():
    return "".join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", k=12))

# Escape special characters for HTML
def escape_html(text):
    if not isinstance(text, str):
        text = str(text)
    escape_chars = {
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;"
    }
    for char, escaped in escape_chars.items():
        text = text.replace(char, escaped)
    text = text.replace('➡️', '->')
    return text

# Advanced AI Prediction System
class GamePredictor:
    def __init__(self):
        self.history = []
        self.patterns = {
            'consecutive_tai': 0,
            'consecutive_xiu': 0,
            'total_frequency': {'tai': 0, 'xiu': 0},
            'dice_patterns': {},
            'time_patterns': {},
            'reversal_patterns': []
        }
        
    def add_result(self, dice1, dice2, dice3, total, result, timestamp=None):
        """Thêm kết quả vào lịch sử để phân tích"""
        # Chuẩn hóa kết quả
        normalized_result = result.lower().replace('à', 'a').replace('ỉ', 'i').replace('ũ', 'u')
        if 'tai' in normalized_result:
            normalized_result = 'tai'
        elif 'xiu' in normalized_result:
            normalized_result = 'xiu'
        
        entry = {
            'dice1': dice1, 'dice2': dice2, 'dice3': dice3,
            'total': total, 'result': normalized_result,
            'timestamp': timestamp or datetime.now()
        }
        self.history.append(entry)
        
        # Giữ lại 500 kết quả gần nhất
        if len(self.history) > 500:
            self.history = self.history[-500:]
            
        self._update_patterns()
    
    def _update_patterns(self):
        """Cập nhật các pattern từ lịch sử"""
        if len(self.history) < 2:
            return
            
        # Đếm chuỗi liên tiếp
        current_streak = 1
        last_result = self.history[-1]['result']
        
        for i in range(len(self.history) - 2, -1, -1):
            if self.history[i]['result'] == last_result:
                current_streak += 1
            else:
                break
                
        if last_result == 'tai':
            self.patterns['consecutive_tai'] = current_streak
            self.patterns['consecutive_xiu'] = 0
        else:
            self.patterns['consecutive_xiu'] = current_streak
            self.patterns['consecutive_tai'] = 0
            
        # Reset và cập nhật tần suất tổng
        self.patterns['total_frequency'] = {'tai': 0, 'xiu': 0}
        for entry in self.history[-100:]:  # 100 kết quả gần nhất
            result = entry['result']
            if result in self.patterns['total_frequency']:
                self.patterns['total_frequency'][result] += 1
                
        # Phân tích pattern xúc xắc
        self._analyze_dice_patterns()
        
        # Phân tích pattern đảo chiều
        self._analyze_reversal_patterns()
    
    def _analyze_dice_patterns(self):
        """Phân tích pattern các con xúc xắc"""
        recent_history = self.history[-50:]  # 50 kết quả gần nhất
        
        for entry in recent_history:
            dice_sum = entry['dice1'] + entry['dice2'] + entry['dice3']
            result = entry['result']
            
            if dice_sum not in self.patterns['dice_patterns']:
                self.patterns['dice_patterns'][dice_sum] = {'tai': 0, 'xiu': 0}
            
            self.patterns['dice_patterns'][dice_sum][result] += 1
    
    def _analyze_reversal_patterns(self):
        """Phân tích pattern đảo chiều (từ chuỗi dài sang kết quả ngược lại)"""
        if len(self.history) < 10:
            return
            
        reversals = []
        for i in range(len(self.history) - 5):
            # Kiểm tra chuỗi 3-5 kết quả liên tiếp
            for streak_len in range(3, 6):
                if i + streak_len >= len(self.history):
                    continue
                    
                streak_results = [self.history[j]['result'] for j in range(i, i + streak_len)]
                
                if len(set(streak_results)) == 1:  # Chuỗi đồng nhất
                    if i + streak_len < len(self.history):
                        next_result = self.history[i + streak_len]['result']
                        if next_result != streak_results[0]:  # Có đảo chiều
                            reversals.append({
                                'streak_length': streak_len,
                                'streak_result': streak_results[0],
                                'reversal_result': next_result
                            })
        
        self.patterns['reversal_patterns'] = reversals[-20:]  # Giữ 20 pattern gần nhất
    
    def predict_next(self, current_dice1, current_dice2, current_dice3, current_total, current_result):
        """Dự đoán kết quả tiếp theo với độ chính xác cao"""
        if len(self.history) < 10:
            # Không đủ dữ liệu, dự đoán theo xác suất cơ bản
            return "Tài" if random.random() < 0.52 else "Xỉu"
        
        prediction_scores = {'tai': 0.0, 'xiu': 0.0}
        
        # 1. Phân tích chuỗi liên tiếp (weight: 30%)
        consecutive_score = self._analyze_consecutive_pattern(current_result.lower())
        prediction_scores['tai'] += consecutive_score['tai'] * 0.3
        prediction_scores['xiu'] += consecutive_score['xiu'] * 0.3
        
        # 2. Phân tích tần suất tổng thể (weight: 20%)
        frequency_score = self._analyze_frequency_pattern()
        prediction_scores['tai'] += frequency_score['tai'] * 0.2
        prediction_scores['xiu'] += frequency_score['xiu'] * 0.2
        
        # 3. Phân tích pattern xúc xắc (weight: 25%)
        dice_score = self._analyze_dice_pattern(current_dice1, current_dice2, current_dice3)
        prediction_scores['tai'] += dice_score['tai'] * 0.25
        prediction_scores['xiu'] += dice_score['xiu'] * 0.25
        
        # 4. Phân tích pattern đảo chiều (weight: 25%)
        reversal_score = self._analyze_reversal_prediction()
        prediction_scores['tai'] += reversal_score['tai'] * 0.25
        prediction_scores['xiu'] += reversal_score['xiu'] * 0.25
        
        # Chọn kết quả có điểm cao nhất
        if prediction_scores['tai'] > prediction_scores['xiu']:
            return "Tài"
        elif prediction_scores['xiu'] > prediction_scores['tai']:
            return "Xỉu"
        else:
            # Nếu bằng nhau, dựa vào xu hướng gần nhất
            recent_results = [entry['result'] for entry in self.history[-5:]]
            tai_count = recent_results.count('tai')
            return "Xỉu" if tai_count >= 3 else "Tài"
    
    def _analyze_consecutive_pattern(self, current_result):
        """Phân tích pattern chuỗi liên tiếp"""
        scores = {'tai': 0.5, 'xiu': 0.5}
        
        # Chuẩn hóa current_result
        normalized = current_result.lower().replace('à', 'a').replace('ỉ', 'i')
        if 'tai' in normalized:
            consecutive = self.patterns['consecutive_tai']
        else:
            consecutive = self.patterns['consecutive_xiu']
        
        # Nếu chuỗi quá dài (>=4), khả năng đảo chiều cao
        if consecutive >= 4:
            if 'tai' in normalized:
                scores['xiu'] += 0.4
                scores['tai'] -= 0.3
            else:
                scores['tai'] += 0.4
                scores['xiu'] -= 0.3
        # Chuỗi vừa phải (2-3), có xu hướng tiếp tục
        elif consecutive in [2, 3]:
            if 'tai' in normalized:
                scores['tai'] += 0.2
                scores['xiu'] -= 0.1
            else:
                scores['xiu'] += 0.2
                scores['tai'] -= 0.1
        
        return scores
    
    def _analyze_frequency_pattern(self):
        """Phân tích tần suất tổng thể"""
        scores = {'tai': 0.5, 'xiu': 0.5}
        
        total_games = sum(self.patterns['total_frequency'].values())
        if total_games > 0:
            tai_ratio = self.patterns['total_frequency']['tai'] / total_games
            xiu_ratio = self.patterns['total_frequency']['xiu'] / total_games
            
            # Nếu một bên thiếu hơn, tăng khả năng xuất hiện
            if tai_ratio < 0.45:
                scores['tai'] += 0.3
                scores['xiu'] -= 0.2
            elif xiu_ratio < 0.45:
                scores['xiu'] += 0.3
                scores['tai'] -= 0.2
        
        return scores
    
    def _analyze_dice_pattern(self, dice1, dice2, dice3):
        """Phân tích pattern dựa trên xúc xắc hiện tại"""
        scores = {'tai': 0.5, 'xiu': 0.5}
        
        current_total = dice1 + dice2 + dice3
        
        # Kiểm tra pattern trong lịch sử
        if current_total in self.patterns['dice_patterns']:
            pattern_data = self.patterns['dice_patterns'][current_total]
            total_count = pattern_data['tai'] + pattern_data['xiu']
            
            if total_count > 5:  # Đủ dữ liệu để phân tích
                tai_ratio = pattern_data['tai'] / total_count
                
                if tai_ratio > 0.6:
                    scores['tai'] += 0.3
                    scores['xiu'] -= 0.2
                elif tai_ratio < 0.4:
                    scores['xiu'] += 0.3
                    scores['tai'] -= 0.2
        
        # Phân tích pattern số
        if dice1 == dice2 == dice3:  # Ba số giống nhau
            scores['xiu'] += 0.2 if current_total <= 10 else -0.2
            scores['tai'] += 0.2 if current_total >= 11 else -0.2
        
        return scores
    
    def _analyze_reversal_prediction(self):
        """Phân tích khả năng đảo chiều"""
        scores = {'tai': 0.5, 'xiu': 0.5}
        
        # Kiểm tra xem hiện tại có đang trong chuỗi dài không
        current_tai_streak = self.patterns['consecutive_tai']
        current_xiu_streak = self.patterns['consecutive_xiu']
        
        max_streak = max(current_tai_streak, current_xiu_streak)
        
        if max_streak >= 4:
            # Phân tích lịch sử đảo chiều
            reversal_data = {}
            for reversal in self.patterns['reversal_patterns']:
                if reversal['streak_length'] == max_streak:
                    result = reversal['reversal_result']
                    if result not in reversal_data:
                        reversal_data[result] = 0
                    reversal_data[result] += 1
            
            if reversal_data:
                total_reversals = sum(reversal_data.values())
                if 'tai' in reversal_data:
                    tai_ratio = reversal_data['tai'] / total_reversals
                    scores['tai'] += tai_ratio * 0.4
                    scores['xiu'] += (1 - tai_ratio) * 0.4
        
        return scores
    
    def get_prediction_confidence(self):
        """Tính độ tin cậy của dự đoán"""
        if len(self.history) < 20:
            return "Thấp (Cần thêm dữ liệu)"
        elif len(self.history) < 50:
            return "Trung bình"
        else:
            return "Cao"
    
    def get_analysis_reason(self, prediction):
        """Tạo lý do phân tích chi tiết"""
        reasons = []
        
        if self.patterns['consecutive_tai'] >= 4:
            reasons.append(f"[Pattern] Chuỗi Tài {self.patterns['consecutive_tai']} lần - khả năng đảo chiều cao")
        elif self.patterns['consecutive_xiu'] >= 4:
            reasons.append(f"[Pattern] Chuỗi Xỉu {self.patterns['consecutive_xiu']} lần - khả năng đảo chiều cao")
        
        total_games = sum(self.patterns['total_frequency'].values())
        if total_games > 0:
            tai_ratio = self.patterns['total_frequency']['tai'] / total_games
            if tai_ratio < 0.4:
                reasons.append("[Frequency] Tài thiếu hụt trong lịch sử gần đây")
            elif tai_ratio > 0.6:
                reasons.append("[Frequency] Xỉu thiếu hụt trong lịch sử gần đây")
        
        if len(self.patterns['reversal_patterns']) > 5:
            reasons.append("[Reversal] Phân tích pattern đảo chiều từ dữ liệu lịch sử")
        
        if not reasons:
            reasons.append(f"[AI Analysis] Thuật toán AI phân tích {len(self.history)} kết quả gần nhất")
        
        return " | ".join(reasons[:2])  # Lấy tối đa 2 lý do

# Global predictor instance
game_predictor = GamePredictor()

# Generate prediction using advanced AI
def generate_prediction(dice1, dice2, dice3, total):
    """Sử dụng AI predictor để dự đoán"""
    # Thêm kết quả hiện tại vào predictor (giả định kết quả dựa trên total)
    current_result = "Tài" if total >= 11 else "Xỉu"
    
    # Dự đoán kết quả tiếp theo
    prediction = game_predictor.predict_next(dice1, dice2, dice3, total, current_result)
    
    return prediction

def get_prediction_reason(dice1, dice2, dice3, total, prediction):
    """Lấy lý do phân tích từ AI predictor"""
    current_result = "Tài" if total >= 11 else "Xỉu"
    
    # Thêm kết quả vào history để cập nhật patterns
    game_predictor.add_result(dice1, dice2, dice3, total, current_result)
    
    # Lấy lý do phân tích
    reason = game_predictor.get_analysis_reason(prediction)
    confidence = game_predictor.get_prediction_confidence()
    
    return f"{reason} | Độ tin cậy: {confidence}"

# API listener for real-time game data
async def api_listener(user_id, chat_id, bot):
    data = await load_data()
    user_id_str = str(user_id)
    last_session_processed = None
    
    while data["running"].get(user_id_str, False):
        try:
            async with aiohttp.ClientSession() as session:
                logger.info(f"User {user_id}: Connecting to API {API_URL}")
                
                while data["running"].get(user_id_str, False):
                    try:
                        # Gọi API để lấy dữ liệu game mới nhất
                        async with session.get(f"{API_URL}/api/game_data") as response:
                            if response.status == 200:
                                game_data = await response.json()
                                logger.info(f"User {user_id}: Received data: {game_data}")
                                
                                # Extract game information
                                session_id = game_data.get("Phien", 0)
                                dice1 = game_data.get("Xuc_xac_1", 0)
                                dice2 = game_data.get("Xuc_xac_2", 0)
                                dice3 = game_data.get("Xuc_xac_3", 0)
                                total = game_data.get("Tong", 0)
                                result = game_data.get("Ket_qua", "")
                                
                                # Check if this is a new session
                                if last_session_processed == session_id:
                                    await asyncio.sleep(2)
                                    continue
                                
                                # Generate prediction for next round using advanced AI
                                predicted_result = generate_prediction(dice1, dice2, dice3, total)
                                reason = get_prediction_reason(dice1, dice2, dice3, total, predicted_result)
                                
                                # Get last prediction for accuracy tracking
                                last_prediction = data.get("last_prediction", {}).get(user_id_str, "")
                                
                                # Save to history if we have a previous prediction
                                if last_prediction and last_session_processed:
                                    history = await load_history()
                                    history_entry = {
                                        "user_id": user_id_str,
                                        "session": last_session_processed,
                                        "actual_result": result,
                                        "prediction": last_prediction,
                                        "status": "Đúng" if last_prediction == result else "Sai",
                                        "timestamp": datetime.now(timezone(timedelta(hours=7))).isoformat()
                                    }
                                    history.append(history_entry)
                                    history = history[-1000:]  # Keep last 1000 entries
                                    await save_history(history)
                                
                                # Update data
                                data["last_prediction"][user_id_str] = predicted_result
                                data["last_session"][user_id_str] = session_id
                                await save_data(data)
                                
                                # Update last processed session
                                last_session_processed = session_id
                                
                                # Create message with new format
                                next_session = session_id + 1
                                
                                message_text = (
                                    f"🎮 Kết quả phiên hiện tại: {escape_html(result)}\n"
                                    f"🎲 {dice1}-{dice2}-{dice3} Tổng: {total}\n"
                                    f"=====================================\n"
                                    f"🔢 Phiên: {session_id} → {next_session}\n"
                                    f"🤖 Dự đoán: {escape_html(predicted_result)}\n"
                                    f"📌Lý do: {escape_html(reason)}\n"
                                    f"=====================================\n"
                                    f"⚠️ Hãy đặt cược sớm trước khi phiên kết thúc!"
                                )
                                
                                await bot.send_message(chat_id=chat_id, text=message_text)
                                logger.info(f"User {user_id}: Sent prediction for session {session_id}")
                            
                            elif response.status == 404:
                                logger.warning(f"User {user_id}: API endpoint not found")
                                await bot.send_message(
                                    chat_id=chat_id,
                                    text="⚠️ API endpoint chưa sẵn sàng. Đang chờ..."
                                )
                            else:
                                logger.warning(f"User {user_id}: API returned status {response.status}")
                        
                        # Đợi 2 giây trước khi gọi API tiếp theo
                        await asyncio.sleep(2)
                        
                        # Reload data to check if user is still running
                        data = await load_data()
                        if not data["running"].get(user_id_str, False):
                            logger.info(f"User {user_id}: Stopping API listener")
                            break
                            
                    except aiohttp.ClientError as e:
                        logger.error(f"API request error for user {user_id}: {e}")
                        await asyncio.sleep(5)
                    except json.JSONDecodeError as e:
                        logger.error(f"JSON decode error for user {user_id}: {e}")
                        await asyncio.sleep(2)
                    except Exception as e:
                        logger.error(f"Error processing data for user {user_id}: {e}")
                        await asyncio.sleep(2)
                        
        except Exception as e:
            logger.error(f"API listener error for user {user_id}: {e}")
            await bot.send_message(
                chat_id=chat_id,
                text="❌ Lỗi kết nối API. Đang thử kết nối lại..."
            )
            await asyncio.sleep(5)
            data = await load_data()

# /start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    data = await load_data()
    
    if str(user.id) not in data["users"]:
        data["users"][str(user.id)] = {
            "name": user.first_name,
            "id": str(user.id),
            "username": user.username if user.username else "Không có",
            "package": "Chưa kích hoạt",
            "activation_date": None,
            "expiry_date": None,
            "banned": False
        }
        await save_data(data)
    
    username = user.username if user.username else user.first_name
    package = data["users"][str(user.id)]["package"]
    expiry = data["users"][str(user.id)].get("expiry_date", "Chưa kích hoạt")
    expiry_display = expiry
    if expiry != "Chưa kích hoạt":
        try:
            expiry_display = datetime.fromisoformat(expiry).strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            expiry_display = "Chưa kích hoạt"
    
    message = (
        "<b>🌟 CHÀO MỪNG @{}</b> 🌟\n"
        "🎉 <b>Chào mừng đến với Bot Thanh Tùng</b> 🎉\n"
        "<b>📦 Gói hiện tại</b>: <code>{}</code>\n"
        "<b>⏰ Hết hạn</b>: <code>{}</code>\n"
        "<b>💡 Dùng /help để xem các lệnh</b>"
    ).format(escape_html(username), escape_html(package), escape_html(expiry_display))
    await update.message.reply_text(message, parse_mode="HTML")

# /help command
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    username = user.username if user.username else user.first_name
    data = await load_data()
    package = data["users"].get(str(user.id), {}).get("package", "Chưa kích hoạt")
    message = (
        "<b>🌟 HƯỚNG DẪN SỬ DỤNG @{}</b> 🌟\n"
        "<b>📦 Gói hiện tại</b>: <code>{}</code>\n"
        "<b>🔥 Các lệnh có sẵn</b>:\n"
        "✅ /start - Đăng ký và bắt đầu\n"
        "📋 /model - Xem thông tin gói\n"
        "🔑 /key [mã] - Kích hoạt gói\n"
        "🎮 /modelbasic - Chạy dự đoán Basic\n"
        "🛑 /stop - Dừng dự đoán\n"
        "🛠️ /admin - Lệnh dành cho admin\n"
        "<b>📬 Liên hệ</b>:\n"
        "👤 Admin: <a href='https://t.me/dethanhtung0988'>t.me/dethanhtung0988</a>\n"
        "👥 CTV: <a href='https://t.me/hknamvip'>t.me/hknamvip</a>"
    ).format(escape_html(username), escape_html(package))
    await update.message.reply_text(message, parse_mode="HTML")

# /model command
async def model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = (
        "<b>🌟 THÔNG TIN GÓI 🌟</b>\n"
        "<b>🔹 Gói Basic</b>:\n"
        "  💸 1 ngày: 25,000 VNĐ\n"
        "  💸 7 ngày: 100,000 VNĐ\n"
        "  💸 30 ngày: 180,000 VNĐ\n"
        "<b>📬 Liên hệ để kích hoạt</b>:\n"
        "👤 Admin: <a href='https://t.me/NguyenTung2029'>t.me/NguyenTung2029</a>\n"
        "👥 CTV: <a href='https://t.me/NguyenTung2029'>t.me/NguyenTung2029</a>\n"
        "<b>🔑 Dùng /key [mã] để kích hoạt</b>"
    )
    await update.message.reply_text(message, parse_mode="HTML")

# /key command
async def key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    data = await load_data()
    
    if str(user_id) not in data["users"]:
        await update.message.reply_text("❗ <b>Vui lòng dùng /start để đăng ký!</b>", parse_mode="HTML")
        return
    
    if len(context.args) != 1:
        await update.message.reply_text("❗ <b>Nhập mã key. Ví dụ: /key [mã]</b>", parse_mode="HTML")
        return
    
    key_code = context.args[0]
    if key_code not in data["keys"]:
        await update.message.reply_text("❌ <b>Key không hợp lệ hoặc không tồn tại!</b>", parse_mode="HTML")
        return
    
    if data["keys"][key_code].get("activated_by") is not None:
        await update.message.reply_text("❌ <b>Key đã được sử dụng bởi người khác!</b>", parse_mode="HTML")
        return
    
    activated_keys = sum(1 for key in data["keys"].values() if key.get("activated_by") is not None)
    if activated_keys >= 500:
        await update.message.reply_text("❌ <b>Đã đạt giới hạn 500 key kích hoạt! Liên hệ admin!</b>", parse_mode="HTML")
        return
    
    key_info = data["keys"][key_code]
    package = key_info["package"]
    duration = key_info["duration"]
    
    duration_map = {
        "1 ngày": timedelta(days=1),
        "7 ngày": timedelta(days=7),
        "30 ngày": timedelta(days=30)
    }
    
    if duration not in duration_map:
        await update.message.reply_text("❌ <b>Thời hạn key không hợp lệ!</b>", parse_mode="HTML")
        return
    
    now = datetime.now(timezone.utc)
    expiry = now + duration_map[duration]
    
    data["users"][str(user_id)] = {
        "name": update.effective_user.first_name,
        "id": str(user_id),
        "username": update.effective_user.username if update.effective_user.username else "Không có",
        "package": package,
        "activation_date": now.isoformat(),
        "expiry_date": expiry.isoformat(),
        "banned": data["users"][str(user_id)].get("banned", False)
    }
    
    data["keys"][key_code]["activated_by"] = {
        "user_id": str(user_id),
        "name": update.effective_user.first_name,
        "username": update.effective_user.username if update.effective_user.username else "Không có",
        "activation_time": now.isoformat()
    }
    
    await save_data(data)
    
    expiry_display = expiry.strftime("%Y-%m-%d %H:%M:%S")
    await update.message.reply_text(
        "<b>🎉 KÍCH HOẠT THÀNH CÔNG</b> 🎉\n"
        f"<b>📦 Gói:</b> <code>{escape_html(package)}</code>\n"
        f"<b>⏰ Hết hạn:</b> <code>{escape_html(expiry_display)}</code>\n"
        f"<b>🔥 Bắt đầu dự đoán với /modelbasic</b>",
        parse_mode="HTML"
    )
    
    # Notify admin
    admin_message = (
        "<b>🔑 KEY ĐÃ ĐƯỢC KÍCH HOẠT</b>\n"
        f"<b>🆔 User ID:</b> <code>{str(user_id)}</code>\n"
        f"<b>👤 Tên:</b> {escape_html(update.effective_user.first_name)}\n"
        f"<b>📧 Username:</b> <code>{escape_html(update.effective_user.username if update.effective_user.username else 'Không có')}</code>\n"
        f"<b>📌 Key:</b> <code>{key_code}</code>\n"
        f"<b>📦 Gói:</b> <code>{escape_html(package)}</code>\n"
        f"<b>⏰ Thời gian kích hoạt:</b> <code>{now.strftime('%Y-%m-%d %H:%M:%S')}</code>"
    )
    for admin_id in DEFAULT_ADMIN_IDS:
        try:
            await context.bot.send_message(chat_id=admin_id, text=admin_message, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Failed to send message to admin {admin_id}: {e}")

# /modelbasic command
async def modelbasic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    data = await load_data()
    
    if data["users"].get(str(user_id), {}).get("banned", False):
        await update.message.reply_text("🚫 <b>Tài khoản bị cấm. Liên hệ admin!</b>", parse_mode="HTML")
        return
    
    if not await has_active_package(user_id, data):
        await update.message.reply_text("❗ <b>Chưa kích hoạt gói Basic. Dùng /key [mã]!</b>", parse_mode="HTML")
        return
    
    if data["running"].get(str(user_id), False):
        await update.message.reply_text("⚠️ <b>Đang chạy dự đoán. Dùng /stop để dừng!</b>", parse_mode="HTML")
        return
    
    if str(user_id) in running_tasks:
        running_tasks[str(user_id)].cancel()
        logger.info(f"User {user_id}: Cancelled previous api_listener task")
    
    data["running"][str(user_id)] = True
    await save_data(data)
    
    task = asyncio.create_task(api_listener(user_id, chat_id, context.bot))
    running_tasks[str(user_id)] = task
    logger.info(f"User {user_id}: Started new api_listener task")
    
    await update.message.reply_text("🔄 <b>BẮT ĐẦU DỰ ĐOÁN REALTIME</b>\n🌐 Kết nối API...\nDùng /stop để dừng!", parse_mode="HTML")

# /stop command
async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    data = await load_data()
    user_id_str = str(user_id)
    
    if user_id_str in data["running"]:
        data["running"][user_id_str] = False
        await save_data(data)
        
        if user_id_str in running_tasks:
            running_tasks[user_id_str].cancel()
            del running_tasks[user_id_str]
            logger.info(f"User {user_id}: Stopped api_listener task")
        
        await update.message.reply_text("✅ <b>ĐÃ DỪNG DỰ ĐOÁN</b>", parse_mode="HTML")
    else:
        await update.message.reply_text("⚠️ <b>Chưa chạy dự đoán!</b>", parse_mode="HTML")

# /admin command
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id):
        await update.message.reply_text("🚫 <b>Không có quyền dùng lệnh này!</b>", parse_mode="HTML")
        return
    
    message = (
        "<b>🛠️ QUẢN LÝ</b>\n"
        "<b>🔹 Quản lý user:</b>\n"
        "  • /users - Xem danh sách user\n"
        "  • /ban [id] - Ban user\n"
        "  • /unban [id] - Unban user\n"
        "<b>🔹 Quản lý key:</b>\n"
        "  • /createkey [gói] [thời hạn] - Tạo key\n"
        "  • /danhsachkey - Xem danh sách key\n"
        "<b>🔹 Quản lý admin:</b>\n"
        "  • /congadm [id] - Thêm admin\n"
        "  • /remvadm [id] - Xóa admin\n"
        "<b>🔹 Thống kê:</b>\n"
        "  • /stats - Xem thống kê dự đoán"
    )
    await update.message.reply_text(message, parse_mode="HTML")

# /users command
async def users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id):
        await update.message.reply_text("🚫 Không có quyền dùng lệnh này!", parse_mode="HTML")
        return
    
    data = await load_data()
    if not data["users"]:
        await update.message.reply_text("📦 Chưa có user nào!", parse_mode="HTML")
        return
    
    message = "<b>👥 DANH SÁCH USER</b>\n"
    for user_id, info in data["users"].items():
        expiry = info.get("expiry_date", "Chưa kích hoạt")
        activation = info.get("activation_date", "Chưa kích hoạt")
        if expiry != "Chưa kích hoạt":
            try:
                expiry = datetime.fromisoformat(expiry).strftime("%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError):
                expiry = "Chưa kích hoạt"
        if activation != "Chưa kích hoạt":
            try:
                activation = datetime.fromisoformat(activation).strftime("%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError):
                activation = "Chưa kích hoạt"
        banned = "🔴 Có" if info.get("banned", False) else "🟢 Không"
        message += (
            f"───────────────\n"
            f"<b>🆔 ID:</b> <code>{user_id}</code>\n"
            f"<b>👤 Tên:</b> {escape_html(info['name'])}\n"
            f"<b>📧 Username:</b> <code>{escape_html(info['username'])}</code>\n"
            f"<b>📦 Gói:</b> <code>{escape_html(info['package'])}</code>\n"
            f"<b>📅 Kích hoạt:</b> <code>{escape_html(activation)}</code>\n"
            f"<b>⏰ Hết hạn:</b> <code>{escape_html(expiry)}</code>\n"
            f"<b>🚫 Bị cấm:</b> {banned}\n"
        )
    message += "──────────────"
    await update.message.reply_text(message, parse_mode="HTML")

# /ban command
async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id):
        await update.message.reply_text("🚫 <b>Không có quyền dùng lệnh này!</b>", parse_mode="HTML")
        return
    
    if len(context.args) != 1:
        await update.message.reply_text("❗ <b>Cần cung cấp ID user! Ví dụ: /ban [id]</b>", parse_mode="HTML")
        return
    
    user_id = context.args[0]
    if not user_id.isdigit():
        await update.message.reply_text("❗ <b>ID user phải là số!</b>", parse_mode="HTML")
        return
    
    data = await load_data()
    
    if user_id not in data["users"]:
        await update.message.reply_text("❌ <b>User không tồn tại!</b>", parse_mode="HTML")
        return
    
    data["users"][user_id]["banned"] = True
    await save_data(data)
    await update.message.reply_text(f"✅ <b>Đã cấm user <code>{user_id}</code>!</b>", parse_mode="HTML")

# /unban command
async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id):
        await update.message.reply_text("🚫 <b>Không có quyền dùng lệnh này!</b>", parse_mode="HTML")
        return
    
    if len(context.args) != 1:
        await update.message.reply_text("❗ <b>Cần cung cấp ID user! Ví dụ: /unban [id]</b>", parse_mode="HTML")
        return
    
    user_id = context.args[0]
    if not user_id.isdigit():
        await update.message.reply_text("❗ <b>ID user phải là số!</b>", parse_mode="HTML")
        return
    
    data = await load_data()
    
    if user_id not in data["users"]:
        await update.message.reply_text("❌ <b>User không tồn tại!</b>", parse_mode="HTML")
        return
    
    data["users"][user_id]["banned"] = False
    await save_data(data)
    await update.message.reply_text(f"✅ <b>Đã mở cấm user <code>{user_id}</code>!</b>", parse_mode="HTML")

# /createkey command
async def createkey(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id):
        await update.message.reply_text("🚫 <b>Không có quyền dùng lệnh này!</b>", parse_mode="HTML")
        return
    
    if len(context.args) != 2:
        await update.message.reply_text("❗ <b>Cần cung cấp gói và thời hạn! Ví dụ: /createkey Basic 1d</b>", parse_mode="HTML")
        return
    
    package, duration = context.args
    duration_map = {
        "1d": "1 ngày",
        "7d": "7 ngày",
        "30d": "30 ngày"
    }
    
    if duration not in duration_map:
        await update.message.reply_text("❗ <b>Thời hạn không hợp lệ! Chọn: 1d, 7d, 30d</b>", parse_mode="HTML")
        return
    
    key = generate_key()
    data = await load_data()
    data["keys"][key] = {
        "package": package,
        "duration": duration_map[duration],
        "activated_by": None
    }
    await save_data(data)
    
    message = (
        f"<b>🔑 KEY MỚI TẠO</b>\n\n"
        f"<b>📌 Key:</b> <code>{key}</code>\n"
        f"<b>📦 Gói:</b> <code>{escape_html(package)}</code>\n"
        f"<b>⏳ Thời hạn:</b> <code>{escape_html(duration_map[duration])}</code>\n"
        f"<b>Sử dụng ngay với /key [mã]</b>"
    )
    await update.message.reply_text(message, parse_mode="HTML")

# /danhsachkey command
async def danhsachkey(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id):
        await update.message.reply_text("🚫 <b>Không có quyền dùng lệnh này!</b>", parse_mode="HTML")
        return
    
    data = await load_data()
    if not data["keys"]:
        await update.message.reply_text("📦 <b>Chưa có key nào!</b>", parse_mode="HTML")
        return
    
    message = "<b>🔑 DANH SÁCH KEY</b>\n"
    for key, info in data["keys"].items():
        activated_by = info.get("activated_by")
        if activated_by:
            try:
                activation_time = datetime.fromisoformat(activated_by['activation_time']).strftime("%Y-%m-%d %H:%M:%S")
                activation_info = (
                    f"User: {escape_html(activated_by['name'])} "
                    f"(@{escape_html(activated_by['username'])}) "
                    f"vào {escape_html(activation_time)}"
                )
            except (ValueError, TypeError):
                activation_info = "Thông tin kích hoạt lỗi"
        else:
            activation_info = "Chưa kích hoạt"
        message += (
            f"───────────────\n"
            f"<b>🔹 Key:</b> <code>{key}</code>\n"
            f"<b>📦 Gói:</b> <code>{escape_html(info['package'])}</code>\n"
            f"<b>⏳ Thời hạn:</b> <code>{escape_html(info['duration'])}</code>\n"
            f"<b>👤 Kích hoạt bởi:</b> {activation_info}\n"
        )
    message += "──────────────"
    await update.message.reply_text(message, parse_mode="HTML")

# /stats command
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id):
        await update.message.reply_text("🚫 <b>Không có quyền dùng lệnh này!</b>", parse_mode="HTML")
        return
    
    history = await load_history()
    if not history:
        await update.message.reply_text("📦 <b>Chưa có lịch sử dự đoán!</b>", parse_mode="HTML")
        return
    
    total_predictions = len(history)
    wins = len([entry for entry in history if entry["status"] == "Đúng"])
    losses = total_predictions - wins
    win_rate = (wins / total_predictions * 100) if total_predictions > 0 else 0
    
    vn_time = datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d %H:%M:%S")
    
    message = (
        "<b>📊 THỐNG KÊ DỰ ĐOÁN</b>\n"
        f"<b>⏰ Thời gian (VN):</b> <code>{escape_html(vn_time)}</code>\n"
        f"<b>🔢 Tổng dự đoán:</b> {total_predictions}\n"
        f"<b>✅ Đúng:</b> {wins}\n"
        f"<b>❌ Sai:</b> {losses}\n"
        f"<b>📈 Tỷ lệ đúng:</b> {win_rate:.2f}%\n"
    )
    await update.message.reply_text(message, parse_mode="HTML")

# /congadm command
async def congadm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id):
        await update.message.reply_text("🚫 <b>Không có quyền dùng lệnh này!</b>", parse_mode="HTML")
        return
    
    if len(context.args) != 1:
        await update.message.reply_text("❗ <b>Cần cung cấp ID admin! Ví dụ: /congadm [id]</b>", parse_mode="HTML")
        return
    
    admin_id = context.args[0]
    if not admin_id.isdigit():
        await update.message.reply_text("❗ <b>ID admin phải là số!</b>", parse_mode="HTML")
        return
    
    admins = await load_admins()
    
    if admin_id in admins["admins"]:
        await update.message.reply_text(f"❗ <b>ID <code>{admin_id}</code> đã là admin!</b>", parse_mode="HTML")
        return
    
    admins["admins"].append(admin_id)
    await save_admins(admins)
    await update.message.reply_text(f"✅ <b>Đã thêm admin <code>{admin_id}</code>!</b>", parse_mode="HTML")

# /remvadm command
async def remvadm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id):
        await update.message.reply_text("🚫 <b>Không có quyền dùng lệnh này!</b>", parse_mode="HTML")
        return
    
    if len(context.args) != 1:
        await update.message.reply_text("❗ <b>Cần cung cấp ID admin! Ví dụ: /remvadm [id]</b>", parse_mode="HTML")
        return
    
    admin_id = context.args[0]
    if not admin_id.isdigit():
        await update.message.reply_text("❗ <b>ID admin phải là số!</b>", parse_mode="HTML")
        return
    
    admins = await load_admins()
    
    if admin_id not in admins["admins"]:
        await update.message.reply_text(f"❗ <b>ID <code>{admin_id}</code> không phải admin!</b>", parse_mode="HTML")
        return
    
    admins["admins"].remove(admin_id)
    await save_admins(admins)
    await update.message.reply_text(f"✅ <b>Đã xóa admin <code>{admin_id}</code>!</b>", parse_mode="HTML")

# Global error handler
async def error_handler(update: Update, context: ContextTypes):
    logger.error(f"Update {update} caused error {context.error}")
    if update and update.effective_message:
        await update.effective_message.reply_text(
            "❌ Đã xảy ra lỗi. Vui lòng thử lại hoặc liên hệ admin!"
        )

# Main function
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("model", model))
    app.add_handler(CommandHandler("key", key))
    app.add_handler(CommandHandler("modelbasic", modelbasic))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CommandHandler("users", users))
    app.add_handler(CommandHandler("ban", ban))
    app.add_handler(CommandHandler("unban", unban))
    app.add_handler(CommandHandler("createkey", createkey))
    app.add_handler(CommandHandler("danhsachkey", danhsachkey))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("congadm", congadm))
    app.add_handler(CommandHandler("remvadm", remvadm))
    
    app.add_error_handler(error_handler)
    
    logger.info("Bot started with API support")
    app.run_polling()

if __name__ == "__main__":
    main()
