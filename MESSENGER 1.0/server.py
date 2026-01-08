from flask import Flask, render_template_string, request
from flask_socketio import SocketIO, emit, disconnect
import datetime
import hashlib
import secrets
import threading
import webbrowser
import sys
import time
import random
import string

# ==================== НАСТРОЙКА ====================
app = Flask(__name__)
app.config['SECRET_KEY'] = secrets.token_hex(32)

# Используем threading для Python 3.12
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# ==================== БАЗА ДАННЫХ ====================
users_db = {}           # username: {password_hash, user_id, created_at, banned, muted_until, admin}
online_users = {}       # socket_id: {username, user_id}
messages = []           # все сообщения с id, username, message, timestamp, channel, type, is_private
private_chats = {}      # chat_id: {name: str, users: [user_id1, user_id2], created_at: str, creator_id: str, type: 'private'}
group_chats = {}        # chat_id: {name: str, users: [user_id1, ...], creator_id: str, created_at: str, type: 'group'}

# Фиксированные каналы
channels = [
    {"id": "general", "name": "📝 Общий чат", "type": "text", "public": True},
    {"id": "games", "name": "🎮 Игры", "type": "text", "public": True},
    {"id": "music", "name": "🎵 Музыка", "type": "text", "public": True},
    {"id": "memes", "name": "😂 Мемы", "type": "text", "public": True}
]

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================
def generate_user_id():
    """Генерация уникального ID пользователя (6 цифр)"""
    while True:
        user_id = ''.join(random.choices(string.digits, k=6))
        if not any(user['user_id'] == user_id for user in users_db.values()):
            return user_id

def generate_chat_id():
    """Генерация уникального ID чата"""
    while True:
        chat_id = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
        if chat_id not in private_chats and chat_id not in group_chats:
            return chat_id

def hash_password(password):
    """Хэширование пароля"""
    return hashlib.sha256((password + "messengerprosto").encode()).hexdigest()

def is_username_taken(username):
    """Проверка, занято ли имя"""
    return username in users_db

def is_user_banned(username):
    """Проверка, забанен ли пользователь"""
    if username in users_db and users_db[username].get('banned'):
        return True
    return False

def is_user_muted(username):
    """Проверка, заглушен ли пользователь"""
    if username in users_db:
        muted_until = users_db[username].get('muted_until')
        if muted_until and datetime.datetime.now() < datetime.datetime.fromisoformat(muted_until):
            return True
    return False

def broadcast_system_message(message):
    """Отправка системного сообщения всем"""
    system_msg = {
        'id': len(messages) + 1,
        'username': 'SYSTEM',
        'message': message,
        'timestamp': datetime.datetime.now().isoformat(),
        'type': 'system',
        'channel': 'general'
    }
    messages.append(system_msg)
    socketio.emit('new_message', system_msg, broadcast=True)

def update_online_users():
    """Обновить список онлайн пользователей для всех клиентов"""
    users_list = []
    for sid, user_data in online_users.items():
        users_list.append({
            'username': user_data['username'],
            'user_id': user_data['user_id'],
            'socket_id': sid
        })
    socketio.emit('users_update', {'users': users_list}, broadcast=True)

def get_user_by_id(user_id):
    """Найти пользователя по ID"""
    for username, data in users_db.items():
        if data.get('user_id') == user_id:
            return username, data
    return None, None

def get_next_message_id():
    """Получить следующий ID сообщения"""
    return len(messages) + 1

def is_user_admin(username):
    """Проверка, является ли пользователь админом"""
    return username in users_db and users_db[username].get('admin', False)

# ==================== HTML ШАБЛОН ====================
HTML = '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MessengerProsto</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            font-family: 'Segoe UI', Arial, sans-serif;
        }
        
        body {
            background: #1a1a1a;
            color: #fff;
            height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 20px;
        }
        
        .container {
            width: 100%;
            max-width: 1200px;
            height: 95vh;
            background: #2d2d2d;
            border-radius: 10px;
            overflow: hidden;
            display: flex;
            box-shadow: 0 10px 30px rgba(0,0,0,0.5);
        }
        
        /* Сайдбар */
        .sidebar {
            width: 250px;
            background: #252525;
            padding: 20px;
            overflow-y: auto;
        }
        
        .logo {
            text-align: center;
            margin-bottom: 30px;
            padding-bottom: 20px;
            border-bottom: 1px solid #444;
        }
        
        .logo h1 {
            font-size: 24px;
            color: #7289da;
            margin-bottom: 5px;
        }
        
        .logo p {
            color: #999;
            font-size: 14px;
        }
        
        .user-info {
            text-align: center;
            margin-bottom: 20px;
            padding: 10px;
            background: #363636;
            border-radius: 5px;
        }
        
        .user-id {
            font-size: 12px;
            color: #43b581;
            margin-top: 5px;
        }
        
        .section {
            margin-bottom: 25px;
        }
        
        .section h3 {
            color: #888;
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 10px;
        }
        
        .channel {
            padding: 10px;
            margin: 5px 0;
            border-radius: 5px;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: space-between;
            transition: background 0.2s;
        }
        
        .channel:hover {
            background: #363636;
        }
        
        .channel.active {
            background: #363636;
            border-left: 3px solid #7289da;
        }
        
        .channel-icon {
            margin-right: 10px;
            font-size: 18px;
        }
        
        .channel-private {
            color: #f04747;
        }
        
        .channel-group {
            color: #faa61a;
        }
        
        .channel-actions {
            display: flex;
            gap: 5px;
        }
        
        .channel-btn {
            background: none;
            border: none;
            color: #999;
            cursor: pointer;
            padding: 2px 5px;
            border-radius: 3px;
            font-size: 12px;
        }
        
        .channel-btn:hover {
            background: #40444b;
        }
        
        .user-list {
            margin-top: 20px;
        }
        
        .user-item {
            padding: 8px;
            margin: 3px 0;
            border-radius: 5px;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        
        .user-status {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            margin-right: 10px;
        }
        
        .user-status.online {
            background: #43b581;
        }
        
        .user-status.offline {
            background: #747f8d;
        }
        
        .user-id-badge {
            font-size: 10px;
            background: #7289da;
            padding: 2px 6px;
            border-radius: 10px;
            color: white;
        }
        
        /* Основная область */
        .main-area {
            flex: 1;
            display: flex;
            flex-direction: column;
        }
        
        /* Заголовок чата */
        .chat-header {
            padding: 20px;
            background: #363636;
            border-bottom: 1px solid #444;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .chat-header h2 {
            font-size: 18px;
        }
        
        .chat-info {
            color: #999;
            font-size: 14px;
        }
        
        .chat-actions {
            display: flex;
            gap: 10px;
        }
        
        /* Сообщения */
        .messages-container {
            flex: 1;
            padding: 20px;
            overflow-y: auto;
            background: #2d2d2d;
        }
        
        .message {
            margin-bottom: 20px;
            padding: 10px;
            border-radius: 5px;
            background: #363636;
            position: relative;
        }
        
        .message:hover {
            background: #3a3a3a;
        }
        
        .message.system {
            background: #3a3a3a;
            border-left: 3px solid #7289da;
        }
        
        .message.private {
            background: #3a2e3a;
            border-left: 3px solid #f04747;
        }
        
        .message.group {
            background: #3a3a2e;
            border-left: 3px solid #faa61a;
        }
        
        .message-header {
            display: flex;
            justify-content: space-between;
            margin-bottom: 5px;
            font-size: 14px;
        }
        
        .message-username {
            font-weight: bold;
            color: #7289da;
        }
        
        .message.system .message-username {
            color: #f04747;
        }
        
        .message.private .message-username {
            color: #ff73fd;
        }
        
        .message.group .message-username {
            color: #ffcc00;
        }
        
        .message-time {
            color: #999;
            font-size: 12px;
        }
        
        .message-text {
            line-height: 1.4;
            word-wrap: break-word;
            padding-right: 30px;
        }
        
        .message-edited {
            font-size: 11px;
            color: #999;
            font-style: italic;
            margin-left: 5px;
        }
        
        .message-actions {
            position: absolute;
            top: 5px;
            right: 5px;
            display: none;
            gap: 5px;
        }
        
        .message:hover .message-actions {
            display: flex;
        }
        
        .message-btn {
            background: #40444b;
            border: none;
            color: #fff;
            cursor: pointer;
            padding: 3px 6px;
            border-radius: 3px;
            font-size: 11px;
        }
        
        .message-btn:hover {
            background: #7289da;
        }
        
        .message-btn.delete {
            background: #f04747;
        }
        
        .message-btn.delete:hover {
            background: #d84040;
        }
        
        /* Поле ввода */
        .input-area {
            padding: 20px;
            background: #363636;
            border-top: 1px solid #444;
        }
        
        .input-container {
            display: flex;
            gap: 10px;
        }
        
        #message-input {
            flex: 1;
            padding: 15px;
            background: #40444b;
            border: none;
            border-radius: 5px;
            color: white;
            font-size: 16px;
            resize: none;
            min-height: 50px;
            max-height: 150px;
        }
        
        #message-input:focus {
            outline: none;
        }
        
        #message-input:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }
        
        #send-btn {
            padding: 0 25px;
            background: #7289da;
            color: white;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            font-weight: bold;
            transition: background 0.2s;
        }
        
        #send-btn:hover {
            background: #677bc4;
        }
        
        #send-btn:disabled {
            background: #4a4f5c;
            cursor: not-allowed;
        }
        
        /* Экран входа */
        .login-screen {
            width: 100%;
            max-width: 400px;
            background: #2d2d2d;
            padding: 40px;
            border-radius: 10px;
            text-align: center;
        }
        
        .login-screen h1 {
            color: #7289da;
            margin-bottom: 30px;
        }
        
        .login-input {
            width: 100%;
            padding: 15px;
            margin-bottom: 15px;
            background: #40444b;
            border: none;
            border-radius: 5px;
            color: white;
            font-size: 16px;
        }
        
        .login-btn {
            width: 100%;
            padding: 15px;
            background: #7289da;
            color: white;
            border: none;
            border-radius: 5px;
            font-size: 16px;
            font-weight: bold;
            cursor: pointer;
            margin-bottom: 10px;
        }
        
        .login-btn:hover {
            background: #677bc4;
        }
        
        .btn-green {
            background: #43b581 !important;
        }
        
        .btn-green:hover {
            background: #3ca374 !important;
        }
        
        .btn-red {
            background: #f04747 !important;
        }
        
        .btn-red:hover {
            background: #d84040 !important;
        }
        
        .btn-orange {
            background: #faa61a !important;
        }
        
        .btn-orange:hover {
            background: #e69518 !important;
        }
        
        .btn-purple {
            background: #9b59b6 !important;
        }
        
        .btn-purple:hover {
            background: #8e44ad !important;
        }
        
        .error-message {
            color: #f04747;
            margin-top: 10px;
            font-size: 14px;
        }
        
        .success-message {
            color: #43b581;
            margin-top: 10px;
            font-size: 14px;
        }
        
        .hidden {
            display: none !important;
        }
        
        /* Модальное окно */
        .modal {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0,0,0,0.8);
            display: flex;
            justify-content: center;
            align-items: center;
            z-index: 1000;
        }
        
        .modal-content {
            background: #2d2d2d;
            padding: 30px;
            border-radius: 10px;
            width: 90%;
            max-width: 400px;
        }
        
        .modal-title {
            margin-bottom: 20px;
            color: #7289da;
        }
        
        .modal-input {
            width: 100%;
            padding: 12px;
            margin-bottom: 15px;
            background: #40444b;
            border: none;
            border-radius: 5px;
            color: white;
            font-size: 16px;
        }
        
        .modal-buttons {
            display: flex;
            gap: 10px;
            margin-top: 20px;
        }
        
        /* Полоса прокрутки */
        ::-webkit-scrollbar {
            width: 8px;
        }
        
        ::-webkit-scrollbar-track {
            background: #2d2d2d;
        }
        
        ::-webkit-scrollbar-thumb {
            background: #202225;
            border-radius: 4px;
        }
        
        ::-webkit-scrollbar-thumb:hover {
            background: #40444b;
        }
    </style>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
</head>
<body>
    <!-- Экран входа -->
    <div id="login-screen" class="login-screen">
        <h1><i class="fas fa-comments"></i> MessengerProsto</h1>
        <input type="text" id="username-input" class="login-input" placeholder="Имя пользователя" maxlength="20">
        <input type="password" id="password-input" class="login-input" placeholder="Пароль">
        <button class="login-btn" onclick="login()">Войти</button>
        <button class="login-btn btn-green" onclick="register()">Регистрация</button>
        <div id="error-message" class="error-message"></div>
        <div id="success-message" class="success-message"></div>
    </div>
    
    <!-- Основной интерфейс -->
    <div id="main-interface" class="container hidden">
        <!-- Сайдбар -->
        <div class="sidebar">
            <div class="logo">
                <h1>MessengerProsto</h1>
                <div class="user-info">
                    <div id="current-user-display">Вы: ...</div>
                    <div class="user-id">ID: <span id="current-user-id">000000</span></div>
                </div>
            </div>
            
            <div class="section">
                <button class="login-btn btn-green" onclick="showCreateChatModal()" style="width: 100%; margin-bottom: 10px;">
                    <i class="fas fa-plus"></i> Приватный чат
                </button>
                <button class="login-btn btn-purple" onclick="showCreateGroupModal()" style="width: 100%;">
                    <i class="fas fa-users"></i> Создать группу
                </button>
            </div>
            
            <!-- Публичные каналы -->
            <div class="section">
                <h3><i class="fas fa-hashtag"></i> Публичные каналы</h3>
                <div id="public-channels"></div>
            </div>
            
            <!-- Приватные чаты -->
            <div class="section">
                <h3><i class="fas fa-lock"></i> Приватные чаты</h3>
                <div id="private-channels"></div>
            </div>
            
            <!-- Группы -->
            <div class="section">
                <h3><i class="fas fa-users"></i> Группы</h3>
                <div id="group-channels"></div>
            </div>
            
            <!-- Онлайн пользователи -->
            <div class="section">
                <h3><i class="fas fa-users"></i> Онлайн (<span id="online-count">0</span>)</h3>
                <div id="online-users" class="user-list"></div>
            </div>
        </div>
        
        <!-- Основная область -->
        <div class="main-area">
            <!-- Заголовок чата -->
            <div class="chat-header">
                <div>
                    <h2 id="current-channel">Выберите канал</h2>
                    <div class="chat-info" id="channel-info"></div>
                </div>
                <div class="chat-actions">
                    <button class="login-btn btn-orange" id="clear-history-btn" onclick="clearHistory()" style="padding: 10px 20px; display: none;">
                        <i class="fas fa-trash"></i> Очистить историю
                    </button>
                    <button class="login-btn btn-red" style="padding: 10px 20px;" onclick="logout()">
                        <i class="fas fa-sign-out-alt"></i> Выйти
                    </button>
                </div>
            </div>
            
            <!-- Сообщения -->
            <div id="messages-container" class="messages-container">
                <div style="text-align: center; color: #999; padding: 40px;">
                    <i class="fas fa-comments" style="font-size: 48px; margin-bottom: 20px;"></i>
                    <h3>Добро пожаловать в MessengerProsto!</h3>
                    <p>Выберите канал слева, чтобы начать общение</p>
                </div>
            </div>
            
            <!-- Поле ввода -->
            <div class="input-area">
                <div class="input-container">
                    <textarea id="message-input" placeholder="Напишите сообщение..." rows="1" onkeydown="handleKeyDown(event)" disabled></textarea>
                    <button id="send-btn" onclick="sendMessage()" disabled><i class="fas fa-paper-plane"></i></button>
                </div>
            </div>
        </div>
    </div>
    
    <!-- Модальное окно создания приватного чата -->
    <div id="create-chat-modal" class="modal hidden">
        <div class="modal-content">
            <h2 class="modal-title"><i class="fas fa-user-plus"></i> Создать приватный чат</h2>
            <p style="margin-bottom: 15px; color: #999;">Введите ID пользователя</p>
            <input type="text" id="invite-user-id" class="modal-input" placeholder="ID пользователя (6 цифр)" maxlength="6">
            <div class="modal-buttons">
                <button class="login-btn btn-green" onclick="createPrivateChat()">Создать</button>
                <button class="login-btn btn-red" onclick="hideCreateChatModal()">Отмена</button>
            </div>
        </div>
    </div>
    
    <!-- Модальное окно создания группы -->
    <div id="create-group-modal" class="modal hidden">
        <div class="modal-content">
            <h2 class="modal-title"><i class="fas fa-users"></i> Создать группу</h2>
            <input type="text" id="group-name" class="modal-input" placeholder="Название группы" maxlength="20">
            <textarea id="group-members" class="modal-input" placeholder="ID участников через запятую (6 цифр каждый)" rows="3"></textarea>
            <div class="modal-buttons">
                <button class="login-btn btn-purple" onclick="createGroup()">Создать</button>
                <button class="login-btn btn-red" onclick="hideCreateGroupModal()">Отмена</button>
            </div>
        </div>
    </div>
    
    <!-- Модальное окно редактирования сообщения -->
    <div id="edit-message-modal" class="modal hidden">
        <div class="modal-content">
            <h2 class="modal-title"><i class="fas fa-edit"></i> Редактировать сообщение</h2>
            <textarea id="edit-message-text" class="modal-input" rows="3" placeholder="Введите новый текст сообщения"></textarea>
            <div class="modal-buttons">
                <button class="login-btn btn-green" onclick="saveEditedMessage()">Сохранить</button>
                <button class="login-btn btn-red" onclick="hideEditModal()">Отмена</button>
            </div>
        </div>
    </div>

    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.5.0/socket.io.min.js"></script>
    <script>
        // Глобальные переменные
        let socket = null;
        let currentUser = '';
        let currentUserId = '';
        let currentChannel = null;
        let onlineUsers = [];
        let isMuted = false;
        let editingMessageId = null;
        let isAdmin = false;
        
        // Инициализация при загрузке
        document.addEventListener('DOMContentLoaded', function() {
            socket = io();
            setupSocketListeners();
        });
        
        // Настройка обработчиков Socket.IO
        function setupSocketListeners() {
            socket.on('connect', () => {
                console.log('Подключено к серверу');
            });
            
            socket.on('disconnect', () => {
                console.log('Отключено от сервера');
            });
            
            socket.on('auth_success', handleAuthSuccess);
            socket.on('auth_error', handleAuthError);
            socket.on('register_success', handleRegisterSuccess);
            socket.on('register_error', handleRegisterError);
            
            socket.on('new_message', handleNewMessage);
            socket.on('chat_history', handleChatHistory);
            
            socket.on('users_update', handleUsersUpdate);
            socket.on('user_joined', handleUserJoined);
            socket.on('user_left', handleUserLeft);
            
            socket.on('user_banned', handleUserBanned);
            socket.on('user_muted', handleUserMuted);
            socket.on('user_kicked', handleUserKicked);
            
            socket.on('private_chat_created', handlePrivateChatCreated);
            socket.on('private_chat_error', handlePrivateChatError);
            socket.on('private_chats_list', handlePrivateChatsList);
            socket.on('private_chat_deleted', handlePrivateChatDeleted);
            
            socket.on('group_created', handleGroupCreated);
            socket.on('group_error', handleGroupError);
            socket.on('groups_list', handleGroupsList);
            
            socket.on('message_deleted', handleMessageDeleted);
            socket.on('message_edited', handleMessageEdited);
            socket.on('history_cleared', handleHistoryCleared);
        }
        
        // Обработчики событий
        function handleAuthSuccess(data) {
            currentUser = data.username;
            currentUserId = data.user_id;
            isMuted = data.is_muted || false;
            isAdmin = data.is_admin || false;
            
            document.getElementById('current-user-display').textContent = `Вы: ${currentUser}`;
            document.getElementById('current-user-id').textContent = currentUserId;
            document.getElementById('login-screen').classList.add('hidden');
            document.getElementById('main-interface').classList.remove('hidden');
            
            // Загружаем каналы
            loadChannels();
            
            // Запрашиваем приватные чаты и группы
            socket.emit('get_private_chats');
            socket.emit('get_groups');
            
            // Присоединяемся к общему чату
            joinChannel('general', '📝 Общий чат', 'public');
            
            showSystemMessage(`Добро пожаловать, ${currentUser}!`);
            
            console.log('Авторизация успешна:', currentUser, 'ID:', currentUserId, 'Admin:', isAdmin);
        }
        
        function handleAuthError(data) {
            showError(data.message);
            console.log('Ошибка авторизации:', data.message);
        }
        
        function handleRegisterSuccess(data) {
            showSuccess('Регистрация успешна! Теперь войдите.');
            document.getElementById('username-input').value = '';
            document.getElementById('password-input').value = '';
            console.log('Регистрация успешна');
        }
        
        function handleRegisterError(data) {
            showError(data.message);
            console.log('Ошибка регистрации:', data.message);
        }
        
        function handleNewMessage(data) {
            if (currentChannel && data.channel === currentChannel.id) {
                addMessageToChat(data);
            }
        }
        
        function handleChatHistory(data) {
            const container = document.getElementById('messages-container');
            container.innerHTML = '';
            
            if (data.messages.length === 0) {
                container.innerHTML = `
                    <div style="text-align: center; color: #999; padding: 40px;">
                        <i class="fas fa-comment-dots" style="font-size: 48px; margin-bottom: 20px;"></i>
                        <h3>Нет сообщений</h3>
                        <p>Будьте первым!</p>
                    </div>
                `;
            } else {
                data.messages.forEach(msg => {
                    addMessageToChat(msg);
                });
                scrollToBottom();
            }
        }
        
        function handleUsersUpdate(data) {
            onlineUsers = data.users;
            updateOnlineUsers();
        }
        
        function handleUserJoined(data) {
            if (data.username !== currentUser) {
                showSystemMessage(`${data.username} подключился`);
            }
        }
        
        function handleUserLeft(data) {
            if (data.username !== currentUser) {
                showSystemMessage(`${data.username} отключился`);
            }
        }
        
        function handleUserBanned(data) {
            if (data.username === currentUser) {
                alert('Вы были забанены администратором!');
                logout();
            } else {
                showSystemMessage(`${data.username} был забанен`);
            }
        }
        
        function handleUserMuted(data) {
            if (data.username === currentUser) {
                isMuted = true;
                showSystemMessage('Вас заглушили администратором');
                document.getElementById('message-input').placeholder = 'Вы заглушены!';
                document.getElementById('message-input').disabled = true;
                document.getElementById('send-btn').disabled = true;
            } else {
                showSystemMessage(`${data.username} был заглушен`);
            }
        }
        
        function handleUserKicked(data) {
            if (data.username === currentUser) {
                alert('Вас кикнули из чата!');
                logout();
            } else {
                showSystemMessage(`${data.username} был кикнут`);
            }
        }
        
        function handlePrivateChatCreated(data) {
            hideCreateChatModal();
            showSystemMessage(`Создан приватный чат с пользователем ${data.other_user}`);
            socket.emit('get_private_chats');
            joinChannel(data.chat_id, `🔒 ${data.other_user}`, 'private');
        }
        
        function handlePrivateChatError(data) {
            showError(data.message);
        }
        
        function handlePrivateChatsList(data) {
            const container = document.getElementById('private-channels');
            container.innerHTML = '';
            
            if (data.chats.length === 0) {
                container.innerHTML = '<div style="color: #999; font-size: 12px; padding: 10px;">У вас нет приватных чатов</div>';
            } else {
                data.chats.forEach(chat => {
                    const chatDiv = document.createElement('div');
                    chatDiv.className = 'channel';
                    chatDiv.innerHTML = `
                        <div onclick="joinChannel('${chat.id}', '🔒 ${escapeHtml(chat.name)}', 'private')" style="flex: 1; display: flex; align-items: center;">
                            <span class="channel-icon"><i class="fas fa-lock"></i></span>
                            <span>${escapeHtml(chat.name)}</span>
                        </div>
                        <div class="channel-actions">
                            <button class="channel-btn" onclick="leavePrivateChat('${chat.id}', event)" title="Выйти из чата">
                                <i class="fas fa-sign-out-alt"></i>
                            </button>
                            ${chat.is_creator ? `<button class="channel-btn delete" onclick="deletePrivateChat('${chat.id}', event)" title="Удалить чат">
                                <i class="fas fa-trash"></i>
                            </button>` : ''}
                        </div>
                    `;
                    
                    container.appendChild(chatDiv);
                });
            }
        }
        
        function handlePrivateChatDeleted(data) {
            showSystemMessage('Приватный чат был удален');
            socket.emit('get_private_chats');
            if (currentChannel && currentChannel.id === data.chat_id) {
                joinChannel('general', '📝 Общий чат', 'public');
            }
        }
        
        function handleGroupCreated(data) {
            hideCreateGroupModal();
            showSystemMessage(`Создана группа "${data.group_name}"`);
            socket.emit('get_groups');
            joinChannel(data.chat_id, `👥 ${data.group_name}`, 'group');
        }
        
        function handleGroupError(data) {
            showError(data.message);
        }
        
        function handleGroupsList(data) {
            const container = document.getElementById('group-channels');
            container.innerHTML = '';
            
            if (data.groups.length === 0) {
                container.innerHTML = '<div style="color: #999; font-size: 12px; padding: 10px;">У вас нет групп</div>';
            } else {
                data.groups.forEach(group => {
                    const groupDiv = document.createElement('div');
                    groupDiv.className = 'channel';
                    groupDiv.innerHTML = `
                        <div onclick="joinChannel('${group.id}', '👥 ${escapeHtml(group.name)}', 'group')" style="flex: 1; display: flex; align-items: center;">
                            <span class="channel-icon"><i class="fas fa-users"></i></span>
                            <span>${escapeHtml(group.name)}</span>
                        </div>
                        <div class="channel-actions">
                            <button class="channel-btn" onclick="leaveGroup('${group.id}', event)" title="Выйти из группы">
                                <i class="fas fa-sign-out-alt"></i>
                            </button>
                            ${group.is_creator ? `<button class="channel-btn delete" onclick="deleteGroup('${group.id}', event)" title="Удалить группу">
                                <i class="fas fa-trash"></i>
                            </button>` : ''}
                        </div>
                    `;
                    
                    container.appendChild(groupDiv);
                });
            }
        }
        
        function handleMessageDeleted(data) {
            if (currentChannel && currentChannel.id === data.channel) {
                const messageElement = document.querySelector(`[data-message-id="${data.message_id}"]`);
                if (messageElement) {
                    messageElement.remove();
                }
            }
        }
        
        function handleMessageEdited(data) {
            if (currentChannel && currentChannel.id === data.channel) {
                const messageElement = document.querySelector(`[data-message-id="${data.message_id}"]`);
                if (messageElement) {
                    const textElement = messageElement.querySelector('.message-text');
                    if (textElement) {
                        textElement.innerHTML = escapeHtml(data.message) + '<span class="message-edited"> (ред.)</span>';
                    }
                }
            }
        }
        
        function handleHistoryCleared(data) {
            if (currentChannel && currentChannel.id === data.channel) {
                const container = document.getElementById('messages-container');
                container.innerHTML = `
                    <div style="text-align: center; color: #999; padding: 40px;">
                        <i class="fas fa-comment-dots" style="font-size: 48px; margin-bottom: 20px;"></i>
                        <h3>История чата очищена</h3>
                        <p>Начните общение заново!</p>
                    </div>
                `;
            }
        }
        
        // Функции UI
        function showError(message) {
            const element = document.getElementById('error-message');
            element.textContent = message;
            setTimeout(() => {
                element.textContent = '';
            }, 3000);
        }
        
        function showSuccess(message) {
            const element = document.getElementById('success-message');
            element.textContent = message;
            setTimeout(() => {
                element.textContent = '';
            }, 3000);
        }
        
        function showSystemMessage(text) {
            const container = document.getElementById('messages-container');
            const placeholder = container.querySelector('div[style*="text-align: center"]');
            if (placeholder) placeholder.remove();
            
            const messageDiv = document.createElement('div');
            messageDiv.className = 'message system';
            
            const time = new Date().toLocaleTimeString('ru-RU', {
                hour: '2-digit',
                minute: '2-digit'
            });
            
            messageDiv.innerHTML = `
                <div class="message-header">
                    <span class="message-username">SYSTEM</span>
                    <span class="message-time">${time}</span>
                </div>
                <div class="message-text">${escapeHtml(text)}</div>
            `;
            
            container.appendChild(messageDiv);
            scrollToBottom();
        }
        
        function addMessageToChat(data) {
            const container = document.getElementById('messages-container');
            const placeholder = container.querySelector('div[style*="text-align: center"]');
            if (placeholder) placeholder.remove();
            
            const messageDiv = document.createElement('div');
            messageDiv.className = `message ${data.type === 'system' ? 'system' : data.is_private ? 'private' : data.is_group ? 'group' : ''}`;
            messageDiv.dataset.messageId = data.id;
            
            const time = new Date(data.timestamp).toLocaleTimeString('ru-RU', {
                hour: '2-digit',
                minute: '2-digit'
            });
            
            const displayName = data.username === currentUser ? 'Вы' : data.username;
            const isOwnMessage = data.username === currentUser;
            const canDelete = isOwnMessage || isAdmin;
            
            const editedBadge = data.edited ? '<span class="message-edited"> (ред.)</span>' : '';
            
            messageDiv.innerHTML = `
                <div class="message-header">
                    <span class="message-username">${escapeHtml(displayName)}</span>
                    <span class="message-time">${time}</span>
                </div>
                <div class="message-text">${escapeHtml(data.message)}${editedBadge}</div>
                ${canDelete && data.type !== 'system' ? `
                    <div class="message-actions">
                        ${isOwnMessage ? `
                        <button class="message-btn" onclick="editMessage(${data.id})" title="Редактировать">
                            <i class="fas fa-edit"></i>
                        </button>
                        ` : ''}
                        <button class="message-btn delete" onclick="deleteMessage(${data.id})" title="Удалить">
                            <i class="fas fa-trash"></i>
                        </button>
                    </div>
                ` : ''}
            `;
            
            container.appendChild(messageDiv);
            scrollToBottom();
        }
        
        function scrollToBottom() {
            const container = document.getElementById('messages-container');
            container.scrollTop = container.scrollHeight;
        }
        
        function loadChannels() {
            // Публичные каналы
            const publicContainer = document.getElementById('public-channels');
            publicContainer.innerHTML = `
                <div class="channel active" onclick="joinChannel('general', '📝 Общий чат', 'public')">
                    <div>
                        <span class="channel-icon">#</span>
                        <span>Общий чат</span>
                    </div>
                </div>
                <div class="channel" onclick="joinChannel('games', '🎮 Игры', 'public')">
                    <div>
                        <span class="channel-icon">#</span>
                        <span>Игры</span>
                    </div>
                </div>
                <div class="channel" onclick="joinChannel('music', '🎵 Музыка', 'public')">
                    <div>
                        <span class="channel-icon">#</span>
                        <span>Музыка</span>
                    </div>
                </div>
                <div class="channel" onclick="joinChannel('memes', '😂 Мемы', 'public')">
                    <div>
                        <span class="channel-icon">#</span>
                        <span>Мемы</span>
                    </div>
                </div>
            `;
        }
        
        function updateOnlineUsers() {
            const container = document.getElementById('online-users');
            const countElement = document.getElementById('online-count');
            
            container.innerHTML = '';
            countElement.textContent = onlineUsers.length;
            
            // Добавляем всех пользователей
            onlineUsers.forEach(user => {
                const userItem = document.createElement('div');
                userItem.className = 'user-item';
                const isCurrentUser = user.user_id === currentUserId;
                
                userItem.innerHTML = `
                    <div>
                        <div class="user-status online"></div>
                        <span>${escapeHtml(user.username)}${isCurrentUser ? ' (Вы)' : ''}</span>
                    </div>
                    <div class="user-id-badge">${user.user_id}</div>
                `;
                container.appendChild(userItem);
            });
        }
        
        // Основные функции
        function login() {
            const username = document.getElementById('username-input').value.trim();
            const password = document.getElementById('password-input').value;
            
            if (!username || !password) {
                showError('Заполните все поля');
                return;
            }
            
            console.log('Попытка входа:', username);
            socket.emit('login', {
                username: username,
                password: password
            });
        }
        
        function register() {
            const username = document.getElementById('username-input').value.trim();
            const password = document.getElementById('password-input').value;
            
            if (!username || !password) {
                showError('Заполните все поля');
                return;
            }
            
            if (username.length < 3) {
                showError('Имя должно быть не менее 3 символов');
                return;
            }
            
            console.log('Попытка регистрации:', username);
            socket.emit('register', {
                username: username,
                password: password
            });
        }
        
        function logout() {
            if (confirm('Выйти из аккаунта?')) {
                socket.disconnect();
                currentUser = '';
                currentUserId = '';
                document.getElementById('main-interface').classList.add('hidden');
                document.getElementById('login-screen').classList.remove('hidden');
                document.getElementById('username-input').value = '';
                document.getElementById('password-input').value = '';
                location.reload();
            }
        }
        
        function joinChannel(channelId, channelName, channelType) {
            currentChannel = { id: channelId, name: channelName, type: channelType };
            
            // Обновляем UI
            document.querySelectorAll('.channel').forEach(ch => ch.classList.remove('active'));
            const activeChannel = Array.from(document.querySelectorAll('.channel')).find(ch => 
                ch.textContent.includes(channelName.replace('🔒 ', '').replace('👥 ', '')) || 
                (channelType === 'private' && ch.textContent.includes('🔒')) ||
                (channelType === 'group' && ch.textContent.includes('👥'))
            );
            if (activeChannel) activeChannel.classList.add('active');
            
            document.getElementById('current-channel').textContent = channelName;
            let channelInfo = '';
            if (channelType === 'private') channelInfo = 'Приватный чат';
            else if (channelType === 'group') channelInfo = 'Групповой чат';
            else channelInfo = 'Публичный канал';
            document.getElementById('channel-info').textContent = channelInfo;
            
            // Показываем кнопку очистки истории
            const clearBtn = document.getElementById('clear-history-btn');
            clearBtn.style.display = 'block';
            
            // Активируем поле ввода
            document.getElementById('message-input').disabled = isMuted;
            document.getElementById('send-btn').disabled = isMuted;
            document.getElementById('message-input').placeholder = isMuted ? 'Вы заглушены!' : 'Напишите сообщение...';
            
            // Запрашиваем историю
            socket.emit('join_channel', {
                channel_id: channelId,
                channel_type: channelType
            });
        }
        
        function sendMessage() {
            const input = document.getElementById('message-input');
            const message = input.value.trim();
            
            if (!message || !currentChannel || isMuted) return;
            
            socket.emit('send_message', {
                channel: currentChannel.id,
                message: message,
                channel_type: currentChannel.type
            });
            
            input.value = '';
            input.style.height = 'auto';
        }
        
        function handleKeyDown(event) {
            if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                sendMessage();
            }
        }
        
        function showCreateChatModal() {
            document.getElementById('create-chat-modal').classList.remove('hidden');
            document.getElementById('invite-user-id').focus();
        }
        
        function hideCreateChatModal() {
            document.getElementById('create-chat-modal').classList.add('hidden');
            document.getElementById('invite-user-id').value = '';
        }
        
        function createPrivateChat() {
            const userId = document.getElementById('invite-user-id').value.trim();
            
            if (!userId) {
                showError('Введите ID пользователя');
                return;
            }
            
            if (userId === currentUserId) {
                showError('Нельзя создать чат с самим собой');
                return;
            }
            
            socket.emit('create_private_chat', {
                target_user_id: userId
            });
        }
        
        function showCreateGroupModal() {
            document.getElementById('create-group-modal').classList.remove('hidden');
            document.getElementById('group-name').focus();
        }
        
        function hideCreateGroupModal() {
            document.getElementById('create-group-modal').classList.add('hidden');
            document.getElementById('group-name').value = '';
            document.getElementById('group-members').value = '';
        }
        
        function createGroup() {
            const groupName = document.getElementById('group-name').value.trim();
            const membersText = document.getElementById('group-members').value.trim();
            
            if (!groupName) {
                showError('Введите название группы');
                return;
            }
            
            if (!membersText) {
                showError('Введите ID участников');
                return;
            }
            
            const members = membersText.split(',').map(id => id.trim()).filter(id => id);
            
            if (members.length === 0) {
                showError('Введите хотя бы одного участника');
                return;
            }
            
            socket.emit('create_group', {
                group_name: groupName,
                members: members
            });
        }
        
        function leavePrivateChat(chatId, event) {
            event.stopPropagation();
            if (confirm('Вы уверены, что хотите выйти из этого чата?')) {
                socket.emit('leave_private_chat', { chat_id: chatId });
            }
        }
        
        function deletePrivateChat(chatId, event) {
            event.stopPropagation();
            if (confirm('Вы уверены, что хотите удалить этот чат? Это действие удалит чат для всех участников.')) {
                socket.emit('delete_private_chat', { chat_id: chatId });
            }
        }
        
        function leaveGroup(chatId, event) {
            event.stopPropagation();
            if (confirm('Вы уверены, что хотите выйти из этой группы?')) {
                socket.emit('leave_group', { chat_id: chatId });
            }
        }
        
        function deleteGroup(chatId, event) {
            event.stopPropagation();
            if (confirm('Вы уверены, что хотите удалить эту группу? Это действие удалит группу для всех участников.')) {
                socket.emit('delete_group', { chat_id: chatId });
            }
        }
        
        function deleteMessage(messageId) {
            if (confirm('Удалить это сообщение?')) {
                socket.emit('delete_message', {
                    message_id: messageId,
                    channel: currentChannel.id
                });
            }
        }
        
        function editMessage(messageId) {
            const messageElement = document.querySelector(`[data-message-id="${messageId}"]`);
            if (messageElement) {
                const textElement = messageElement.querySelector('.message-text');
                let text = textElement.textContent;
                // Убираем "(ред.)" если есть
                text = text.replace(' (ред.)', '');
                document.getElementById('edit-message-text').value = text;
                editingMessageId = messageId;
                document.getElementById('edit-message-modal').classList.remove('hidden');
            }
        }
        
        function hideEditModal() {
            document.getElementById('edit-message-modal').classList.add('hidden');
            editingMessageId = null;
        }
        
        function saveEditedMessage() {
            const newText = document.getElementById('edit-message-text').value.trim();
            if (!newText) {
                showError('Введите текст сообщения');
                return;
            }
            
            if (editingMessageId) {
                socket.emit('edit_message', {
                    message_id: editingMessageId,
                    channel: currentChannel.id,
                    message: newText
                });
                hideEditModal();
            }
        }
        
        function clearHistory() {
            if (confirm('Очистить всю историю этого чата? Это действие нельзя отменить.')) {
                socket.emit('clear_history', {
                    channel: currentChannel.id,
                    channel_type: currentChannel.type
                });
            }
        }
        
        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }
    </script>
</body>
</html>
'''

# ==================== ВЕБ-ОБРАБОТЧИКИ ====================
@app.route('/')
def index():
    return render_template_string(HTML)

# ==================== SOCKET.IO ОБРАБОТЧИКИ ====================

# ---------- АВТОРИЗАЦИЯ ----------
@socketio.on('register')
def handle_register(data):
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    
    print(f"[DEBUG] Регистрация: {username}")
    
    if not username or not password:
        emit('register_error', {'message': 'Заполните все поля'})
        return
    
    if len(username) < 3:
        emit('register_error', {'message': 'Имя должно быть не менее 3 символов'})
        return
    
    if is_username_taken(username):
        emit('register_error', {'message': 'Это имя уже занято'})
        return
    
    # Генерация уникального ID пользователя
    user_id = generate_user_id()
    
    # Регистрация пользователя
    users_db[username] = {
        'password_hash': hash_password(password),
        'user_id': user_id,
        'created_at': datetime.datetime.now().isoformat(),
        'banned': False,
        'muted_until': None,
        'admin': (username == 'admin')
    }
    
    print(f"[DEBUG] Зарегистрирован: {username}, ID: {user_id}")
    
    emit('register_success', {'message': 'Регистрация успешна! Теперь войдите.'})

@socketio.on('login')
def handle_login(data):
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    
    print(f"[DEBUG] Попытка входа: {username}")
    
    if username not in users_db:
        print(f"[DEBUG] Пользователь {username} не найден")
        emit('auth_error', {'message': 'Пользователь не найден'})
        return
    
    # Получаем сохраненный хэш
    stored_hash = users_db[username]['password_hash']
    input_hash = hash_password(password)
    
    if input_hash != stored_hash:
        print(f"[DEBUG] Неверный пароль для {username}")
        emit('auth_error', {'message': 'Неверный пароль'})
        return
    
    if is_user_banned(username):
        print(f"[DEBUG] Пользователь {username} забанен")
        emit('auth_error', {'message': 'Вы забанены'})
        return
    
    # Авторизация успешна
    online_users[request.sid] = {
        'username': username,
        'user_id': users_db[username]['user_id'],
        'joined_at': datetime.datetime.now().isoformat()
    }
    
    print(f"[DEBUG] Успешный вход: {username}, ID: {users_db[username]['user_id']}")
    
    emit('auth_success', {
        'username': username,
        'user_id': users_db[username]['user_id'],
        'is_muted': is_user_muted(username),
        'is_admin': is_user_admin(username)
    })
    
    # Уведомляем всех о новом пользователе
    emit('user_joined', {'username': username}, broadcast=True, skip_sid=request.sid)
    
    # Обновляем список онлайн пользователей
    update_online_users()
    
    # Отправляем системное сообщение
    broadcast_system_message(f'👋 {username} присоединился к чату')

# ---------- ЧАТЫ ----------
@socketio.on('join_channel')
def handle_join_channel(data):
    if request.sid not in online_users:
        return
    
    username = online_users[request.sid]['username']
    channel_id = data.get('channel_id')
    channel_type = data.get('channel_type')
    
    print(f"[DEBUG] {username} присоединился к каналу {channel_id}")
    
    # Отправляем историю сообщений для этого канала
    if channel_type == 'public':
        channel_messages = [msg for msg in messages if msg.get('channel') == channel_id]
    else:  # private или group
        channel_messages = [msg for msg in messages if msg.get('channel') == channel_id]
    
    emit('chat_history', {'messages': channel_messages[-50:]})

@socketio.on('send_message')
def handle_send_message(data):
    if request.sid not in online_users:
        return
    
    username = online_users[request.sid]['username']
    user_id = online_users[request.sid]['user_id']
    channel = data.get('channel')
    message_text = data.get('message', '').strip()
    channel_type = data.get('channel_type', 'public')
    
    print(f"[DEBUG] Сообщение от {username} в {channel}: {message_text}")
    
    # Проверка на мут
    if is_user_muted(username):
        emit('system_message', {'message': 'Вы заглушены и не можете отправлять сообщения'})
        return
    
    if not message_text:
        return
    
    # Проверка для приватных чатов и групп
    if channel_type in ['private', 'group']:
        # Проверяем приватные чаты
        if channel in private_chats:
            chat_data = private_chats[channel]
            if user_id not in chat_data['users']:
                emit('system_message', {'message': 'Вы не участник этого чата'})
                return
        # Проверяем группы
        elif channel in group_chats:
            chat_data = group_chats[channel]
            if user_id not in chat_data['users']:
                emit('system_message', {'message': 'Вы не участник этой группы'})
                return
        else:
            emit('system_message', {'message': 'Чат не найден'})
            return
    
    # Определяем тип чата для сообщения
    is_private = False
    is_group = False
    if channel_type == 'private':
        is_private = True
    elif channel_type == 'group':
        is_group = True
    
    # Создаем сообщение
    message = {
        'id': get_next_message_id(),
        'username': username,
        'message': message_text,
        'timestamp': datetime.datetime.now().isoformat(),
        'type': 'message',
        'channel': channel,
        'is_private': is_private,
        'is_group': is_group,
        'edited': False
    }
    
    # Сохраняем сообщение
    messages.append(message)
    
    # Отправляем сообщение
    if channel_type == 'public':
        emit('new_message', message, broadcast=True)
    else:  # private или group
        # Определяем список участников
        participants = []
        if channel in private_chats:
            participants = private_chats[channel]['users']
        elif channel in group_chats:
            participants = group_chats[channel]['users']
        
        # Отправляем только участникам
        for participant_id in participants:
            for sid, user_data in online_users.items():
                if user_data['user_id'] == participant_id:
                    emit('new_message', message, room=sid)

# ---------- ПРИВАТНЫЕ ЧАТЫ ----------
@socketio.on('create_private_chat')
def handle_create_private_chat(data):
    if request.sid not in online_users:
        return
    
    username = online_users[request.sid]['username']
    user_id = online_users[request.sid]['user_id']
    target_user_id = data.get('target_user_id', '').strip()
    
    print(f"[DEBUG] {username} создает приватный чат с ID: {target_user_id}")
    
    # Проверяем, существует ли целевой пользователь
    target_username, target_data = get_user_by_id(target_user_id)
    if not target_username:
        emit('private_chat_error', {'message': 'Пользователь с таким ID не найден'})
        return
    
    # Проверяем, не пытаемся ли создать чат с самим собой
    if target_user_id == user_id:
        emit('private_chat_error', {'message': 'Нельзя создать чат с самим собой'})
        return
    
    # Проверяем, существует ли уже такой чат
    for chat_id, chat_data in private_chats.items():
        if user_id in chat_data['users'] and target_user_id in chat_data['users']:
            emit('private_chat_error', {'message': 'Приватный чат уже существует'})
            return
    
    # Создаем приватный чат
    chat_id = generate_chat_id()
    private_chats[chat_id] = {
        'name': target_username,
        'users': [user_id, target_user_id],
        'creator_id': user_id,
        'created_at': datetime.datetime.now().isoformat(),
        'type': 'private'
    }
    
    print(f"[DEBUG] Создан приватный чат {chat_id} между {username} и {target_username}")
    
    # Уведомляем создателя
    emit('private_chat_created', {
        'chat_id': chat_id,
        'other_user': target_username
    })
    
    # Уведомляем второго пользователя, если он онлайн
    for sid, user_data in online_users.items():
        if user_data['user_id'] == target_user_id:
            emit('private_chat_created', {
                'chat_id': chat_id,
                'other_user': username
            }, room=sid)
            break
    
    # Отправляем обновленный список приватных чатов обоим пользователям
    send_private_chats_to_user(request.sid)
    for sid, user_data in online_users.items():
        if user_data['user_id'] == target_user_id:
            send_private_chats_to_user(sid)
            break

@socketio.on('get_private_chats')
def handle_get_private_chats():
    if request.sid not in online_users:
        return
    
    send_private_chats_to_user(request.sid)

def send_private_chats_to_user(sid):
    """Отправить список приватных чатов пользователю"""
    user_id = online_users[sid]['user_id']
    user_chats = []
    
    for chat_id, chat_data in private_chats.items():
        if user_id in chat_data['users'] and chat_data['type'] == 'private':
            # Находим имя другого пользователя
            other_user_id = chat_data['users'][0] if chat_data['users'][1] == user_id else chat_data['users'][1]
            other_username, _ = get_user_by_id(other_user_id)
            
            user_chats.append({
                'id': chat_id,
                'name': other_username if other_username else 'Неизвестный',
                'is_creator': (chat_data['creator_id'] == user_id)
            })
    
    emit('private_chats_list', {'chats': user_chats}, room=sid)

@socketio.on('leave_private_chat')
def handle_leave_private_chat(data):
    if request.sid not in online_users:
        return
    
    username = online_users[request.sid]['username']
    user_id = online_users[request.sid]['user_id']
    chat_id = data.get('chat_id')
    
    print(f"[DEBUG] {username} выходит из приватного чата {chat_id}")
    
    if chat_id not in private_chats:
        emit('system_message', {'message': 'Приватный чат не найден'})
        return
    
    chat_data = private_chats[chat_id]
    
    # Проверяем, является ли пользователь участником чата
    if user_id not in chat_data['users']:
        emit('system_message', {'message': 'Вы не участник этого чата'})
        return
    
    # Удаляем пользователя из списка участников
    chat_data['users'].remove(user_id)
    
    # Если в чате остался только один участник или никого, удаляем чат
    if len(chat_data['users']) <= 1:
        # Уведомляем оставшегося участника (если есть)
        for participant_id in chat_data['users']:
            for sid, user_data in online_users.items():
                if user_data['user_id'] == participant_id:
                    emit('private_chat_deleted', {'chat_id': chat_id}, room=sid)
                    break
        
        # Удаляем чат
        del private_chats[chat_id]
        # Удаляем все сообщения этого чата
        global messages
        messages = [msg for msg in messages if msg.get('channel') != chat_id]
    else:
        # Обновляем список приватных чатов для всех участников
        for participant_id in chat_data['users']:
            for sid, user_data in online_users.items():
                if user_data['user_id'] == participant_id:
                    send_private_chats_to_user(sid)
                    break
    
    # Обновляем список для вышедшего пользователя
    send_private_chats_to_user(request.sid)
    
    emit('system_message', {'message': 'Вы вышли из приватного чата'})

@socketio.on('delete_private_chat')
def handle_delete_private_chat(data):
    if request.sid not in online_users:
        return
    
    username = online_users[request.sid]['username']
    user_id = online_users[request.sid]['user_id']
    chat_id = data.get('chat_id')
    
    print(f"[DEBUG] {username} удаляет приватный чат {chat_id}")
    
    if chat_id not in private_chats:
        emit('system_message', {'message': 'Приватный чат не найден'})
        return
    
    chat_data = private_chats[chat_id]
    
    # Проверяем, является ли пользователь создателем чата
    if chat_data['creator_id'] != user_id:
        emit('system_message', {'message': 'Только создатель чата может его удалить'})
        return
    
    # Уведомляем всех участников об удалении чата
    for participant_id in chat_data['users']:
        for sid, user_data in online_users.items():
            if user_data['user_id'] == participant_id:
                emit('private_chat_deleted', {'chat_id': chat_id}, room=sid)
                # Обновляем список приватных чатов
                send_private_chats_to_user(sid)
                break
    
    # Удаляем чат
    del private_chats[chat_id]
    # Удаляем все сообщения этого чата
    global messages
    messages = [msg for msg in messages if msg.get('channel') != chat_id]
    
    print(f"[DEBUG] Приватный чат {chat_id} удален пользователем {username}")

# ---------- ГРУППЫ ----------
@socketio.on('create_group')
def handle_create_group(data):
    if request.sid not in online_users:
        return
    
    username = online_users[request.sid]['username']
    user_id = online_users[request.sid]['user_id']
    group_name = data.get('group_name', '').strip()
    members = data.get('members', [])
    
    print(f"[DEBUG] {username} создает группу: {group_name}")
    
    if not group_name:
        emit('group_error', {'message': 'Введите название группы'})
        return
    
    if len(members) == 0:
        emit('group_error', {'message': 'Добавьте хотя бы одного участника'})
        return
    
    # Проверяем существование всех участников
    valid_members = [user_id]  # Создатель автоматически добавляется
    for member_id in members:
        if member_id == user_id:
            continue  # Пропускаем себя
        
        target_username, target_data = get_user_by_id(member_id)
        if not target_username:
            emit('group_error', {'message': f'Пользователь с ID {member_id} не найден'})
            return
        
        valid_members.append(member_id)
    
    # Убираем дубликаты
    valid_members = list(set(valid_members))
    
    # Создаем группу
    chat_id = generate_chat_id()
    group_chats[chat_id] = {
        'name': group_name,
        'users': valid_members,
        'creator_id': user_id,
        'created_at': datetime.datetime.now().isoformat(),
        'type': 'group'
    }
    
    print(f"[DEBUG] Создана группа {chat_id}: {group_name} с {len(valid_members)} участниками")
    
    # Уведомляем создателя
    emit('group_created', {
        'chat_id': chat_id,
        'group_name': group_name
    })
    
    # Уведомляем участников, если они онлайн
    for member_id in valid_members:
        if member_id != user_id:  # Создателя уже уведомили
            for sid, user_data in online_users.items():
                if user_data['user_id'] == member_id:
                    emit('group_created', {
                        'chat_id': chat_id,
                        'group_name': group_name
                    }, room=sid)
                    break
    
    # Отправляем обновленный список групп всем участникам
    for member_id in valid_members:
        for sid, user_data in online_users.items():
            if user_data['user_id'] == member_id:
                send_groups_to_user(sid)
                break

@socketio.on('get_groups')
def handle_get_groups():
    if request.sid not in online_users:
        return
    
    send_groups_to_user(request.sid)

def send_groups_to_user(sid):
    """Отправить список групп пользователю"""
    user_id = online_users[sid]['user_id']
    user_groups = []
    
    for chat_id, chat_data in group_chats.items():
        if user_id in chat_data['users'] and chat_data['type'] == 'group':
            user_groups.append({
                'id': chat_id,
                'name': chat_data['name'],
                'is_creator': (chat_data['creator_id'] == user_id)
            })
    
    emit('groups_list', {'groups': user_groups}, room=sid)

@socketio.on('leave_group')
def handle_leave_group(data):
    if request.sid not in online_users:
        return
    
    username = online_users[request.sid]['username']
    user_id = online_users[request.sid]['user_id']
    chat_id = data.get('chat_id')
    
    print(f"[DEBUG] {username} выходит из группы {chat_id}")
    
    if chat_id not in group_chats:
        emit('system_message', {'message': 'Группа не найдена'})
        return
    
    chat_data = group_chats[chat_id]
    
    # Проверяем, является ли пользователь участником группы
    if user_id not in chat_data['users']:
        emit('system_message', {'message': 'Вы не участник этой группы'})
        return
    
    # Нельзя выйти, если ты создатель (только удалить группу)
    if chat_data['creator_id'] == user_id:
        emit('system_message', {'message': 'Создатель не может выйти из группы. Удалите группу вместо этого.'})
        return
    
    # Удаляем пользователя из списка участников
    chat_data['users'].remove(user_id)
    
    # Если в группе остался только один участник, удаляем группу
    if len(chat_data['users']) <= 1:
        # Уведомляем оставшегося участника (создателя)
        for sid, user_data in online_users.items():
            if user_data['user_id'] == chat_data['creator_id']:
                emit('system_message', {'message': f'Группа "{chat_data["name"]}" удалена, так как все вышли'}, room=sid)
                break
        
        # Удаляем группу
        del group_chats[chat_id]
        # Удаляем все сообщения этой группы
        global messages
        messages = [msg for msg in messages if msg.get('channel') != chat_id]
    else:
        # Обновляем список групп для всех участников
        for participant_id in chat_data['users']:
            for sid, user_data in online_users.items():
                if user_data['user_id'] == participant_id:
                    send_groups_to_user(sid)
                    break
    
    # Обновляем список для вышедшего пользователя
    send_groups_to_user(request.sid)
    
    emit('system_message', {'message': f'Вы вышли из группы "{chat_data["name"]}"'})

@socketio.on('delete_group')
def handle_delete_group(data):
    if request.sid not in online_users:
        return
    
    username = online_users[request.sid]['username']
    user_id = online_users[request.sid]['user_id']
    chat_id = data.get('chat_id')
    
    print(f"[DEBUG] {username} удаляет группу {chat_id}")
    
    if chat_id not in group_chats:
        emit('system_message', {'message': 'Группа не найдена'})
        return
    
    chat_data = group_chats[chat_id]
    
    # Проверяем, является ли пользователь создателем группы
    if chat_data['creator_id'] != user_id:
        emit('system_message', {'message': 'Только создатель группы может ее удалить'})
        return
    
    # Уведомляем всех участников об удалении группы
    for participant_id in chat_data['users']:
        for sid, user_data in online_users.items():
            if user_data['user_id'] == participant_id:
                emit('system_message', {'message': f'Группа "{chat_data["name"]}" была удалена создателем'}, room=sid)
                # Обновляем список групп
                send_groups_to_user(sid)
                break
    
    # Удаляем группу
    del group_chats[chat_id]
    # Удаляем все сообщения этой группы
    global messages
    messages = [msg for msg in messages if msg.get('channel') != chat_id]
    
    print(f"[DEBUG] Группа {chat_id} удалена пользователем {username}")

# ---------- УДАЛЕНИЕ И РЕДАКТИРОВАНИЕ СООБЩЕНИЙ ----------
@socketio.on('delete_message')
def handle_delete_message(data):
    if request.sid not in online_users:
        return
    
    username = online_users[request.sid]['username']
    message_id = data.get('message_id')
    channel = data.get('channel')
    
    print(f"[DEBUG] {username} удаляет сообщение {message_id} в канале {channel}")
    
    # Находим сообщение
    message_to_delete = None
    for msg in messages:
        if msg['id'] == message_id and msg['channel'] == channel:
            message_to_delete = msg
            break
    
    if not message_to_delete:
        emit('system_message', {'message': 'Сообщение не найдено'})
        return
    
    # Проверяем, является ли пользователь автором сообщения или админом
    if message_to_delete['username'] != username and not is_user_admin(username):
        emit('system_message', {'message': 'Вы можете удалять только свои сообщения'})
        return
    
    # Удаляем сообщение
    messages.remove(message_to_delete)
    
    # Рассылаем событие об удалении сообщения
    emit('message_deleted', {
        'message_id': message_id,
        'channel': channel
    }, broadcast=True)
    
    print(f"[DEBUG] Сообщение {message_id} удалено пользователем {username}")

@socketio.on('edit_message')
def handle_edit_message(data):
    if request.sid not in online_users:
        return
    
    username = online_users[request.sid]['username']
    message_id = data.get('message_id')
    channel = data.get('channel')
    new_text = data.get('message', '').strip()
    
    print(f"[DEBUG] {username} редактирует сообщение {message_id}")
    
    if not new_text:
        emit('system_message', {'message': 'Сообщение не может быть пустым'})
        return
    
    # Находим сообщение
    message_to_edit = None
    for msg in messages:
        if msg['id'] == message_id and msg['channel'] == channel:
            message_to_edit = msg
            break
    
    if not message_to_edit:
        emit('system_message', {'message': 'Сообщение не найдено'})
        return
    
    # Проверяем, является ли пользователь автором сообщения
    if message_to_edit['username'] != username:
        emit('system_message', {'message': 'Вы можете редактировать только свои сообщения'})
        return
    
    # Обновляем сообщение
    message_to_edit['message'] = new_text
    message_to_edit['edited'] = True
    
    # Рассылаем событие об редактировании сообщения
    emit('message_edited', {
        'message_id': message_id,
        'channel': channel,
        'message': new_text
    }, broadcast=True)
    
    print(f"[DEBUG] Сообщение {message_id} отредактировано пользователем {username}")

@socketio.on('clear_history')
def handle_clear_history(data):
    if request.sid not in online_users:
        return
    
    username = online_users[request.sid]['username']
    user_id = online_users[request.sid]['user_id']
    channel = data.get('channel')
    channel_type = data.get('channel_type')
    
    print(f"[DEBUG] {username} очищает историю канала {channel}")
    
    # Проверяем права
    if channel_type == 'public':
        # Для публичных каналов только администратор
        if not is_user_admin(username):
            emit('system_message', {'message': 'Только администратор может очищать историю публичных чатов'})
            return
    elif channel_type == 'private':
        # Для приватных чатов проверяем, является ли пользователь участником
        if channel not in private_chats:
            emit('system_message', {'message': 'Чат не найден'})
            return
        if user_id not in private_chats[channel]['users']:
            emit('system_message', {'message': 'Вы не участник этого чата'})
            return
    elif channel_type == 'group':
        # Для групп проверяем, является ли пользователь участником
        if channel not in group_chats:
            emit('system_message', {'message': 'Группа не найден'})
            return
        if user_id not in group_chats[channel]['users']:
            emit('system_message', {'message': 'Вы не участник этой группы'})
            return
    
    # Удаляем все сообщения канала
    global messages
    messages = [msg for msg in messages if msg.get('channel') != channel]
    
    # Рассылаем событие об очистке истории
    emit('history_cleared', {'channel': channel}, broadcast=True)
    
    print(f"[DEBUG] История канала {channel} очищена пользователем {username}")

# ---------- ПОЛЬЗОВАТЕЛИ ----------
@socketio.on('disconnect')
def handle_disconnect():
    if request.sid in online_users:
        username = online_users[request.sid]['username']
        del online_users[request.sid]
        
        print(f"[DEBUG] Пользователь отключился: {username}")
        
        # Уведомляем остальных об отключении
        emit('user_left', {'username': username}, broadcast=True)
        
        # Обновляем список онлайн пользователей
        update_online_users()

# ==================== АДМИН-КОМАНДЫ (в терминале) ====================

def admin_commands():
    """Обработка админ-команд в терминале"""
    print("\n" + "="*50)
    print("АДМИН-ПАНЕЛЬ MESSENGERPROSTO")
    print("="*50)
    print("Доступные команды:")
    print("  /list           - Показать всех пользователей")
    print("  /online         - Показать онлайн пользователей")
    print("  /ban <ник>      - Забанить пользователя")
    print("  /unban <ник>    - Разбанить пользователя")
    print("  /kick <ник>     - Кикнуть пользователя")
    print("  /mute <ник> <мин> - Заглушить пользователя на N минут")
    print("  /unmute <ник>   - Снять мут")
    print("  /prog kill <ник> - Принудительно завершить сессию")
    print("  /broadcast <текст> - Отправить сообщение всем")
    print("  /help           - Показать эту справку")
    print("  /exit           - Выйти из админ-панели")
    print("="*50)
    
    while True:
        try:
            command = input("\nadmin> ").strip()
            
            if command == "/exit":
                print("Выход из админ-панели")
                break
                
            elif command == "/help":
                print("Доступные команды:")
                print("  /list           - Показать всех пользователей")
                print("  /online         - Показать онлайн пользователей")
                print("  /ban <ник>      - Забанить пользователя")
                print("  /unban <ник>    - Разбанить пользователя")
                print("  /kick <ник>     - Кикнуть пользователя")
                print("  /mute <ник> <мин> - Заглушить пользователя на N минут")
                print("  /unmute <ник>   - Снять мут")
                print("  /prog kill <ник> - Принудительно завершить сессию")
                print("  /broadcast <текст> - Отправить сообщение всем")
                print("  /help           - Показать эту справку")
                print("  /exit           - Выйти из админ-панели")
                
            elif command == "/list":
                print("\nЗарегистрированные пользователи:")
                for username, data in users_db.items():
                    status = "БАН" if data.get('banned') else "OK"
                    muted = f"МУТ до {data.get('muted_until')}" if data.get('muted_until') else "НЕ МУТ"
                    admin = "АДМИН" if data.get('admin') else "USER"
                    user_id = data.get('user_id', 'N/A')
                    print(f"  {username} (ID: {user_id}): {status} | {muted} | {admin}")
                    
            elif command == "/online":
                print("\nОнлайн пользователи:")
                for sid, data in online_users.items():
                    print(f"  {data['username']} (ID: {data['user_id']}, sid: {sid[:8]}...)")
                    
            elif command.startswith("/ban "):
                parts = command.split(" ", 1)
                if len(parts) == 2:
                    username = parts[1].strip()
                    ban_user(username)
                else:
                    print("Использование: /ban <ник>")
                    
            elif command.startswith("/unban "):
                parts = command.split(" ", 1)
                if len(parts) == 2:
                    username = parts[1].strip()
                    unban_user(username)
                else:
                    print("Использование: /unban <ник>")
                    
            elif command.startswith("/kick "):
                parts = command.split(" ", 1)
                if len(parts) == 2:
                    username = parts[1].strip()
                    kick_user(username)
                else:
                    print("Использование: /kick <ник>")
                    
            elif command.startswith("/mute "):
                parts = command.split(" ", 2)
                if len(parts) == 3:
                    username = parts[1].strip()
                    try:
                        minutes = int(parts[2].strip())
                        mute_user(username, minutes)
                    except ValueError:
                        print("Минуты должны быть числом")
                else:
                    print("Использование: /mute <ник> <минуты>")
                    
            elif command.startswith("/unmute "):
                parts = command.split(" ", 1)
                if len(parts) == 2:
                    username = parts[1].strip()
                    unmute_user(username)
                else:
                    print("Использование: /unmute <ник>")
                    
            elif command.startswith("/prog kill "):
                parts = command.split(" ", 2)
                if len(parts) == 3:
                    username = parts[2].strip()
                    kill_session(username)
                else:
                    print("Использование: /prog kill <ник>")
                    
            elif command.startswith("/broadcast "):
                parts = command.split(" ", 1)
                if len(parts) == 2:
                    message = parts[1].strip()
                    broadcast_system_message(f"📢 АДМИНИСТРАТОР: {message}")
                    print(f"Сообщение отправлено всем: {message}")
                else:
                    print("Использование: /broadcast <текст>")
                    
            elif command == "":
                continue
            else:
                print(f"Неизвестная команда: {command}")
                print("Введите /help для списка команд")
                
        except Exception as e:
            print(f"Ошибка: {e}")

def ban_user(username):
    """Забанить пользователя"""
    if username in users_db:
        users_db[username]['banned'] = True
        
        # Отключаем пользователя если он онлайн
        for sid, data in list(online_users.items()):
            if data['username'] == username:
                socketio.emit('user_banned', {'username': username}, room=sid)
                # Отключаем пользователя
                socketio.server.disconnect(sid)
                if sid in online_users:
                    del online_users[sid]
                break
        
        broadcast_system_message(f'🚫 Пользователь {username} был забанен администратором')
        print(f'Пользователь {username} забанен')
        update_online_users()
        return True
    else:
        print(f'Пользователь {username} не найден')
        return False

def unban_user(username):
    """Разбанить пользователя"""
    if username in users_db:
        users_db[username]['banned'] = False
        print(f'Пользователь {username} разбанен')
        return True
    else:
        print(f'Пользователь {username} не найден')
        return False

def kick_user(username):
    """Кикнуть пользователя"""
    # Ищем пользователя онлайн
    kicked = False
    for sid, data in list(online_users.items()):
        if data['username'] == username:
            socketio.emit('user_kicked', {'username': username}, room=sid)
            # Отключаем пользователя
            socketio.server.disconnect(sid)
            del online_users[sid]
            kicked = True
            break
    
    if kicked:
        broadcast_system_message(f'👢 Пользователь {username} был кикнут администратором')
        print(f'Пользователь {username} кикнут')
        update_online_users()
        return True
    else:
        print(f'Пользователь {username} не в сети')
        return False

def mute_user(username, minutes):
    """Заглушить пользователя"""
    if username in users_db:
        muted_until = datetime.datetime.now() + datetime.timedelta(minutes=minutes)
        users_db[username]['muted_until'] = muted_until.isoformat()
        
        # Уведомляем пользователя если он онлайн
        for sid, data in online_users.items():
            if data['username'] == username:
                socketio.emit('user_muted', {'username': username}, room=sid)
                break
        
        broadcast_system_message(f'🔇 Пользователь {username} заглушен на {minutes} минут')
        print(f'Пользователь {username} заглушен на {minutes} минут')
        return True
    else:
        print(f'Пользователь {username} не найден')
        return False

def unmute_user(username):
    """Снять мут с пользователя"""
    if username in users_db:
        users_db[username]['muted_until'] = None
        print(f'Мут снят с пользователя {username}')
        return True
    else:
        print(f'Пользователь {username} не найден')
        return False

def kill_session(username):
    """Принудительно завершить сессию пользователя"""
    killed = False
    for sid, data in list(online_users.items()):
        if data['username'] == username:
            # Отправляем сообщение пользователю
            socketio.emit('system_message', {'message': 'Ваша сессия была завершена администратором'}, room=sid)
            # Отключаем пользователя
            socketio.server.disconnect(sid)
            del online_users[sid]
            killed = True
            break
    
    if killed:
        broadcast_system_message(f'🔌 Сессия пользователя {username} была завершена администратором')
        print(f'Сессия пользователя {username} завершена')
        update_online_users()
        return True
    else:
        print(f'Пользователь {username} не в сети')
        return False

# ==================== ЗАПУСК СЕРВЕРА ====================
def open_browser():
    time.sleep(1)
    webbrowser.open('http://localhost:5000')

def start_admin_panel():
    """Запуск админ-панели в отдельном потоке"""
    time.sleep(2)
    admin_commands()

if __name__ == '__main__':
    print("=" * 60)
    print("MESSENGERPROSTO - ЗАПУСК")
    print("=" * 60)
    print("Совместим с Python 3.12")
    print("Использует threading mode")
    print("=" * 60)
    print("Адрес: http://localhost:5000")
    print("=" * 60)
    print("Тестовый аккаунт: admin / admin123")
    print("АДМИН-ПАНЕЛЬ доступна в терминале!")
    print("=" * 60)
    
    # Создаем тестового пользователя admin если его нет
    if 'admin' not in users_db:
        admin_hash = hash_password('admin123')
        admin_id = generate_user_id()
        print(f"[INIT] Создаю пользователя admin (ID: {admin_id})")
        users_db['admin'] = {
            'password_hash': admin_hash,
            'user_id': admin_id,
            'created_at': datetime.datetime.now().isoformat(),
            'banned': False,
            'muted_until': None,
            'admin': True
        }
    else:
        print(f"[INIT] Пользователь admin уже существует")
    
    # Автоматически открываем браузер
    threading.Thread(target=open_browser, daemon=True).start()
    
    # Запускаем админ-панель в отдельном потоке
    admin_thread = threading.Thread(target=start_admin_panel, daemon=True)
    admin_thread.start()
    
    # Запускаем сервер
    try:
        socketio.run(app, host='0.0.0.0', port=5000, debug=True, use_reloader=False, allow_unsafe_werkzeug=True)
    except Exception as e:
        print(f"Ошибка запуска сервера: {e}")
        print("Попробуйте изменить порт на 5001")
        socketio.run(app, host='0.0.0.0', port=5001, debug=True, use_reloader=False, allow_unsafe_werkzeug=True)