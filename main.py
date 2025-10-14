
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from datetime import datetime
from pymongo import MongoClient, ASCENDING, DESCENDING
from bson import ObjectId
import os
import uuid
import logging

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'gizli-anahtar-2024')

# Logging konfigürasyonu
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode='threading',
    logger=False,
    engineio_logger=False,
    ping_timeout=60,
    ping_interval=25,
    transport=['websocket', 'polling']
)

# Aktif kullanıcıları takip etmek için
active_users = {}

# MongoDB bağlantısı
MONGODB_URI = os.environ.get(
    'MONGODB_URI',
    'mongodb+srv://Eymen:Eymen6969@cluster0.vqwhlrj.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0'
)

try:
    client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
    client.admin.command('ping')
    logger.info('✅ MongoDB bağlantısı başarılı!')
    
    db = client.chat_db
    messages_collection = db.messages
    rooms_collection = db.rooms
    users_collection = db.users
    friend_requests_collection = db.friend_requests
    friendships_collection = db.friendships
    groups_collection = db.groups
    
    messages_collection.create_index([("room", ASCENDING), ("timestamp", DESCENDING)])
    rooms_collection.create_index([("name", ASCENDING)], unique=True)
    users_collection.create_index([("user_id", ASCENDING)], unique=True)
    users_collection.create_index([("username", ASCENDING)])
    friend_requests_collection.create_index([("to_id", ASCENDING), ("status", ASCENDING)])
    friend_requests_collection.create_index([("from_id", ASCENDING), ("status", ASCENDING)])
    friendships_collection.create_index([("user_low", ASCENDING), ("user_high", ASCENDING)], unique=True)
    groups_collection.create_index([("group_id", ASCENDING)], unique=True)
    groups_collection.create_index([("members", ASCENDING)])
    
    logger.info('✅ Index\'ler oluşturuldu')
    
except Exception as e:
    logger.error(f'❌ MongoDB bağlantı hatası: {e}')
    exit(1)

def init_db():
    default_rooms = ['Genel', 'Teknoloji', 'Spor', 'Müzik', 'Oyun']
    for room_name in default_rooms:
        try:
            rooms_collection.insert_one({'name': room_name, 'created_at': datetime.now()})
            logger.info(f'✅ Oda oluşturuldu: {room_name}')
        except:
            pass

init_db()

def are_friends(user_a: str, user_b: str) -> bool:
    if not user_a or not user_b:
        return False
    if user_a == user_b:
        return False
    low, high = sorted([user_a.upper(), user_b.upper()])
    try:
        doc = friendships_collection.find_one({'user_low': low, 'user_high': high}, {'_id': 1})
        return doc is not None
    except Exception as e:
        logger.error(f'❌ Arkadaşlık kontrol hatası: {e}')
        return False

def get_online_sid_by_user_id(uid: str):
    for sid, user in active_users.items():
        if user.get('user_id') == uid:
            return sid
    return None

HTML_PAGE = """<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Grup Sohbet</title>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.5.4/socket.io.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 20px;
        }
        .main-container {
            width: 100%;
            max-width: 1200px;
            height: 90vh;
            background: white;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            display: flex;
            overflow: hidden;
        }
        .sidebar {
            width: 280px;
            background: #2c3e50;
            display: flex;
            flex-direction: column;
        }
        .sidebar-header {
            padding: 25px 20px;
            background: #1a252f;
            color: white;
            border-bottom: 2px solid #34495e;
        }
        .sidebar-header h2 {
            font-size: 20px;
            margin-bottom: 8px;
        }
        .user-info {
            font-size: 13px;
            opacity: 0.8;
            color: #ecf0f1;
            word-break: break-all;
        }
        .user-id-display {
            font-size: 11px;
            color: #95a5a6;
            margin-top: 5px;
            font-family: monospace;
            background: #34495e;
            padding: 5px;
            border-radius: 4px;
            cursor: pointer;
            transition: all 0.2s;
        }
        .user-id-display:hover {
            background: #667eea;
            color: white;
        }
        .rooms-list {
            flex: 1;
            overflow-y: auto;
            padding: 15px 10px;
        }
        .room-item {
            padding: 15px 15px;
            margin-bottom: 8px;
            border-radius: 10px;
            cursor: pointer;
            transition: all 0.3s;
            display: flex;
            align-items: center;
            gap: 12px;
            color: #ecf0f1;
        }
        .room-item:hover {
            background: #34495e;
            transform: translateX(5px);
        }
        .room-item.active {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            font-weight: 600;
        }
        .room-item.private {
            border-left: 3px solid #f39c12;
        }
        .room-icon {
            font-size: 22px;
        }
        .room-name {
            flex: 1;
            font-size: 15px;
        }
        .new-room-section {
            padding: 15px;
            background: #1a252f;
            border-top: 2px solid #34495e;
        }
        .section-title { color: #ecf0f1; font-size: 12px; opacity: 0.8; margin: 6px 0 8px; }
        .new-room-input {
            width: 100%;
            padding: 12px;
            border: none;
            border-radius: 8px;
            margin-bottom: 10px;
            font-size: 14px;
            background: #34495e;
            color: white;
        }
        .new-room-input::placeholder {
            color: #95a5a6;
        }
        .new-room-btn {
            width: 100%;
            padding: 12px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-weight: bold;
            transition: transform 0.2s;
            font-size: 14px;
            margin-bottom: 8px;
        }
        .new-room-btn:hover {
            transform: scale(1.02);
        }
        .private-room-input {
            width: 100%;
            padding: 10px;
            border: none;
            border-radius: 8px;
            font-size: 12px;
            background: #34495e;
            color: white;
            margin-bottom: 8px;
        }
        .private-room-input::placeholder {
            color: #95a5a6;
        }
        .private-btn {
            width: 100%;
            padding: 10px;
            background: #f39c12;
            color: white;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-weight: bold;
            font-size: 12px;
            transition: transform 0.2s;
        }
        .private-btn:hover {
            transform: scale(1.02);
        }
        .chat-container {
            flex: 1;
            display: flex;
            flex-direction: column;
        }
        .chat-header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px 25px;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        .chat-header h2 {
            font-size: 24px;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .messages {
            flex: 1;
            padding: 25px;
            overflow-y: auto;
            background: #ecf0f1;
        }
        .message {
            margin-bottom: 20px;
            animation: slideIn 0.3s ease;
            display: flex;
            flex-direction: column;
        }
        @keyframes slideIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }
        .message-content {
            background: white;
            padding: 14px 18px;
            border-radius: 18px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            max-width: 65%;
            word-wrap: break-word;
        }
        .message.own {
            align-items: flex-end;
        }
        .message.own .message-content {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }
        .username {
            font-weight: 700;
            font-size: 14px;
            margin-bottom: 6px;
            color: #667eea;
        }
        .message.own .username {
            color: white;
        }
        .message-text {
            font-size: 15px;
            line-height: 1.5;
            margin-bottom: 6px;
        }
        .timestamp {
            font-size: 11px;
            color: #7f8c8d;
            font-weight: 500;
        }
        .message.own .timestamp {
            color: rgba(255,255,255,0.8);
        }
        .input-area {
            padding: 20px 25px;
            background: white;
            border-top: 2px solid #e0e0e0;
            display: flex;
            gap: 12px;
        }
        input.message-input {
            flex: 1;
            padding: 14px 20px;
            border: 2px solid #e0e0e0;
            border-radius: 25px;
            font-size: 15px;
            outline: none;
            transition: border 0.3s;
        }
        input.message-input:focus { 
            border-color: #667eea;
            box-shadow: 0 0 0 3px rgba(102,126,234,0.1);
        }
        button.send-btn {
            padding: 14px 35px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 25px;
            cursor: pointer;
            font-weight: bold;
            transition: transform 0.2s;
            font-size: 15px;
        }
        button.send-btn:hover { 
            transform: scale(1.05);
            box-shadow: 0 5px 15px rgba(102,126,234,0.4);
        }
        button.send-btn:active { transform: scale(0.95); }
        .login-screen {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0,0,0,0.85);
            display: flex;
            justify-content: center;
            align-items: center;
            z-index: 1000;
        }
        .login-box {
            background: white;
            padding: 45px;
            border-radius: 20px;
            text-align: center;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            min-width: 350px;
        }
        .login-box h2 {
            margin-bottom: 25px;
            color: #667eea;
            font-size: 28px;
        }
        .login-input {
            width: 100%;
            padding: 14px 18px;
            border: 2px solid #e0e0e0;
            border-radius: 12px;
            font-size: 15px;
            margin-bottom: 20px;
            outline: none;
            transition: border 0.3s;
        }
        .login-input:focus {
            border-color: #667eea;
        }
        .login-btn {
            width: 100%;
            padding: 14px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 12px;
            cursor: pointer;
            font-weight: bold;
            font-size: 16px;
            transition: transform 0.2s;
        }
        .login-btn:hover {
            transform: scale(1.02);
        }
        .hidden { display: none; }
        .empty-state {
            text-align: center;
            padding: 40px;
            color: #7f8c8d;
        }
        .empty-state-icon {
            font-size: 48px;
            margin-bottom: 15px;
        }
        @media (max-width: 768px) {
            .sidebar { width: 220px; }
            .main-container { height: 95vh; }
        }
    </style>
</head>
<body>
    <div class="login-screen" id="loginScreen">
        <div class="login-box">
            <h2>💬 Grup Sohbete Katıl</h2>
            <input type="text" id="usernameInput" class="login-input" placeholder="Kullanıcı adınızı girin" maxlength="20">
            <button class="login-btn" onclick="login()">Giriş Yap</button>
        </div>
    </div>
    <div class="main-container">
        <div class="sidebar">
            <div class="sidebar-header">
                <h2>🏠 Sohbet Odaları</h2>
                <div class="user-info" id="userInfo"></div>
                <div class="user-id-display" id="userIdDisplay" title="Kliklayarak kopyala"></div>
            </div>
            <div class="rooms-list" id="roomsList"></div>
            <div class="new-room-section">
                <div class="section-title">Genel Oda</div>
                <input type="text" class="new-room-input" id="newRoomInput" placeholder="Yeni oda adı" maxlength="30">
                <button class="new-room-btn" onclick="createRoom()">➕ Oda Oluştur</button>
                
                <input type="text" class="private-room-input" id="privateUserIdInput" placeholder="Özel sohbet için ID girin" maxlength="50">
                <button class="private-btn" onclick="startPrivateChat()">🔒 Özel Sohbet</button>

                <div class="section-title" style="margin-top:10px">Arkadaşlar</div>
                <input type="text" class="private-room-input" id="friendUserIdInput" placeholder="Arkadaş ID'si" maxlength="50">
                <button class="private-btn" style="background:#27ae60" onclick="sendFriendRequest()">➕ Arkadaş Ekle</button>
                <div id="friendRequests" style="margin-top:8px;color:#ecf0f1;font-size:12px"></div>

                <div class="section-title" style="margin-top:10px">Gruplar (max 5 kişi)</div>
                <input type="text" class="private-room-input" id="groupNameInput" placeholder="Yeni grup adı" maxlength="30">
                <input type="text" class="private-room-input" id="groupMemberIdsInput" placeholder="Davet (virgülle ID'ler)" maxlength="200">
                <button class="private-btn" style="background:#8e44ad" onclick="createGroup()">👥 Grup Kur</button>
                <input type="text" class="private-room-input" id="renameGroupInput" placeholder="Grup yeni adı" maxlength="30">
                <button class="private-btn" style="background:#2980b9" onclick="renameCurrentGroup()">✏️ Grup Adını Değiştir</button>
            </div>
        </div>
        <div class="chat-container">
            <div class="chat-header">
                <h2 id="currentRoomName"><span class="room-icon">💬</span> Genel</h2>
            </div>
            <div class="messages" id="messages">
                <div class="empty-state">
                    <div class="empty-state-icon">💬</div>
                    <p>Henüz mesaj yok. İlk mesajı sen gönder!</p>
                </div>
            </div>
            <div class="input-area">
                <input type="text" class="message-input" id="messageInput" placeholder="Mesajınızı yazın..." maxlength="500">
                <button class="send-btn" onclick="sendMessage()">Gönder</button>
            </div>
        </div>
    </div>
    <script>
        var socket;
        var username = '';
        var userId = '';
        var currentRoom = 'Genel';
        var roomLabels = {}; // room id/name -> display label
        
        function login() {
            var input = document.getElementById('usernameInput');
            username = input.value.trim();
            if (username) {
                document.getElementById('loginScreen').classList.add('hidden');
                document.getElementById('userInfo').textContent = '👤 ' + username;
                initSocket();
                loadRooms();
            } else {
                alert('Lütfen bir kullanıcı adı girin!');
            }
        }
        
        function initSocket() {
            socket = io({
                transports: ['websocket', 'polling'],
                upgrade: true,
                rememberUpgrade: true,
                reconnection: true,
                reconnectionDelay: 1000,
                reconnectionDelayMax: 5000,
                reconnectionAttempts: 5
            });
            
            socket.on('connect', function() {
                console.log('✅ Socket bağlandı! ID:', socket.id);
                socket.emit('register_user', { username: username });
            });
            
            socket.on('user_registered', function(data) {
                userId = data.user_id;
                document.getElementById('userIdDisplay').textContent = '🔑 ID: ' + userId;
                console.log('✅ Kullanıcı kaydedildi. ID:', userId);
                
                if (currentRoom) {
                    socket.emit('join_room', { room: currentRoom, username: username });
                }

                // Load groups after we know our userId
                fetch('/api/my_groups?user_id=' + encodeURIComponent(userId))
                    .then(function(res){ return res.json(); })
                    .then(function(groups){
                        groups.forEach(function(g){ 
                            roomLabels[g.room] = g.name || g.room;
                            addRoomToList(g.room, false, g.name);
                        });
                    });
            });
            
            socket.on('disconnect', function() {
                console.log('❌ Socket bağlantısı kesildi');
            });
            
            socket.on('receive_message', function(data) {
                console.log('📩 Mesaj alındı:', data);
                
                if (data.room === currentRoom) {
                    console.log('✅ Mesaj bu odaya ait, gösteriliyor');
                    displayMessage(data.username, data.message, data.timestamp);
                }
            });
            
            socket.on('room_created', function(data) {
                console.log('🆕 Yeni oda oluşturuldu:', data.name);
                addRoomToList(data.name);
            });
            
            socket.on('private_room_created', function(data) {
                console.log('🔒 Özel oda oluşturuldu:', data.room);
                addRoomToList(data.room, true);
                joinRoom(data.room);
            });
            
            socket.on('error_message', function(data) {
                alert(data.message);
            });

            socket.on('friend_request_received', function(data) {
                // Show incoming request
                var list = document.getElementById('friendRequests');
                var item = document.createElement('div');
                item.style.marginBottom = '6px';
                item.innerHTML = '📨 ' + data.from_username + ' ('+data.from_id+') arkadaşlık isteği ' +
                    '<button style="margin-left:6px" onclick="respondFriendRequest(\''+data.request_id+'\', true)">Kabul</button>' +
                    '<button style="margin-left:4px" onclick="respondFriendRequest(\''+data.request_id+'\', false)">Reddet</button>';
                list.appendChild(item);
            });

            socket.on('friend_request_result', function(data) {
                alert(data.message);
            });

            socket.on('group_created', function(data) {
                // Fetch group label on load
                roomLabels[data.room] = data.name || data.room;
                addRoomToList(data.room, false, data.name);
                joinRoom(data.room);
            });

            socket.on('group_renamed', function(data) {
                var room = data.old_room;
                var item = document.querySelector('[data-room="'+room+'"]');
                if (item) {
                    item.querySelector('.room-name').textContent = data.name;
                }
                roomLabels[room] = data.name;
                if (currentRoom === room) {
                    document.getElementById('currentRoomName').innerHTML = '<span class="room-icon">👥</span> ' + data.name;
                }
            });
        }
        
        function loadRooms() {
            fetch('/api/rooms')
                .then(function(response) { return response.json(); })
                .then(function(rooms) {
                    var roomsList = document.getElementById('roomsList');
                    roomsList.innerHTML = '';
                    rooms.forEach(function(room) {
                        addRoomToList(room.name, false);
                    });
                    // Load user's groups as well
                    if (userId) {
                        fetch('/api/my_groups?user_id=' + encodeURIComponent(userId))
                            .then(function(res){ return res.json(); })
                            .then(function(groups){
                                groups.forEach(function(g){ 
                                    roomLabels[g.room] = g.name || g.room;
                                    addRoomToList(g.room, false, g.name);
                                });
                            });
                    }
                    setActiveRoom('Genel');
                    joinRoom('Genel');
                });
        }
        
        function addRoomToList(roomName, isPrivate, label) {
            if (typeof isPrivate === 'undefined') isPrivate = false;
            if (typeof label === 'undefined' || !label) label = roomName;
            roomLabels[roomName] = label;
            
            var roomsList = document.getElementById('roomsList');
            var existingRoom = document.querySelector('[data-room="' + roomName + '"]');
            if (existingRoom) return;
            
            var roomItem = document.createElement('div');
            roomItem.className = 'room-item' + (isPrivate ? ' private' : '');
            roomItem.setAttribute('data-room', roomName);
            roomItem.onclick = function() { joinRoom(roomName); };
            
            var icons = {
                'Genel': '💬',
                'Teknoloji': '💻',
                'Spor': '⚽',
                'Müzik': '🎵',
                'Oyun': '🎮'
            };
            var icon = isPrivate ? '🔒' : (roomName.startsWith('_group_') ? '👥' : (icons[roomName] || '📌'));
            
            roomItem.innerHTML = '<span class="room-icon">' + icon + '</span><span class="room-name">' + label + '</span>';
            roomsList.appendChild(roomItem);
        }
        
        function setActiveRoom(roomName) {
            var items = document.querySelectorAll('.room-item');
            items.forEach(function(item) {
                item.classList.remove('active');
                if (item.getAttribute('data-room') === roomName) {
                    item.classList.add('active');
                }
            });
        }
        
        function joinRoom(roomName) {
            if (currentRoom === roomName) return;
            
            console.log('🚪 Oda değiştiriliyor:', currentRoom, '->', roomName);
            
            if (socket && currentRoom) {
                socket.emit('leave_room', { room: currentRoom, username: username });
            }
            
            currentRoom = roomName;
            
            if (socket) {
                socket.emit('join_room', { room: roomName, username: username });
            }
            
            var icons = {
                'Genel': '💬',
                'Teknoloji': '💻',
                'Spor': '⚽',
                'Müzik': '🎵',
                'Oyun': '🎮'
            };
            var isPrivate = roomName.includes('_private_');
            var isGroup = roomName.startsWith('_group_');
            var icon = isPrivate ? '🔒' : (isGroup ? '👥' : (icons[roomName] || '📌'));
            
            var label = roomLabels[roomName] || roomName;
            document.getElementById('currentRoomName').innerHTML = '<span class="room-icon">' + icon + '</span> ' + label;
            setActiveRoom(roomName);
            loadMessages(roomName);
        }
        
        function loadMessages(roomName) {
            var url = '/api/messages?room=' + encodeURIComponent(roomName);
            if (userId) url += '&user_id=' + encodeURIComponent(userId);
            fetch(url)
                .then(function(response) { return response.json(); })
                .then(function(messages) {
                    var messagesDiv = document.getElementById('messages');
                    messagesDiv.innerHTML = '';
                    
                    if (messages.length === 0) {
                        messagesDiv.innerHTML = '<div class="empty-state"><div class="empty-state-icon">💬</div><p>' + roomName + ' odasında henüz mesaj yok. İlk mesajı sen gönder!</p></div>';
                    } else {
                        messages.forEach(function(msg) {
                            displayMessage(msg.username, msg.message, msg.timestamp, true);
                        });
                    }
                    scrollToBottom();
                });
        }
        
        function displayMessage(user, message, timestamp, isHistory) {
            if (typeof isHistory === 'undefined') isHistory = false;
            
            var messagesDiv = document.getElementById('messages');
            var emptyState = messagesDiv.querySelector('.empty-state');
            if (emptyState) emptyState.remove();
            
            var messageDiv = document.createElement('div');
            messageDiv.className = 'message' + (user === username ? ' own' : '');
            
            messageDiv.innerHTML = 
                '<div class="message-content">' +
                    '<div class="username">' + user + '</div>' +
                    '<div class="message-text">' + message + '</div>' +
                    '<div class="timestamp">' + timestamp + '</div>' +
                '</div>';
            
            messagesDiv.appendChild(messageDiv);
            if (!isHistory) scrollToBottom();
        }
        
        function sendMessage() {
            var input = document.getElementById('messageInput');
            var message = input.value.trim();
            
            if (message && socket && socket.connected && currentRoom) {
                socket.emit('send_message', { 
                    username: username, 
                    message: message,
                    room: currentRoom
                });
                input.value = '';
            }
        }
        
        function createRoom() {
            var input = document.getElementById('newRoomInput');
            var roomName = input.value.trim();
            
            if (roomName) {
                fetch('/api/create_room', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name: roomName })
                })
                .then(function(response) { return response.json(); })
                .then(function(data) {
                    if (data.success) {
                        input.value = '';
                        socket.emit('new_room', { name: roomName });
                        addRoomToList(roomName, false);
                        joinRoom(roomName);
                    } else {
                        alert(data.message || 'Oda oluşturulamadı!');
                    }
                });
            }
        }
        
        function startPrivateChat() {
            var input = document.getElementById('privateUserIdInput');
            var targetUserId = input.value.trim();
            
            if (!targetUserId) {
                alert('Lütfen geçerli bir ID girin!');
                return;
            }
            
            if (targetUserId === userId) {
                alert('Kendinizle özel sohbet yapamazsınız!');
                return;
            }
            
            socket.emit('start_private_chat', {
                from_id: userId,
                to_id: targetUserId,
                username: username
            });
            
            input.value = '';
        }

        function sendFriendRequest() {
            var input = document.getElementById('friendUserIdInput');
            var toId = input.value.trim();
            if (!toId) { alert('Hedef ID girin'); return; }
            socket.emit('friend_request_send', { from_id: userId, to_id: toId, from_username: username });
            input.value = '';
        }

        function respondFriendRequest(requestId, accept) {
            socket.emit('friend_request_respond', { request_id: requestId, accept: accept, user_id: userId });
        }

        function createGroup() {
            var name = document.getElementById('groupNameInput').value.trim();
            var ids = document.getElementById('groupMemberIdsInput').value.trim();
            var memberIds = ids ? ids.split(',').map(function(s){return s.trim().toUpperCase();}).filter(Boolean) : [];
            socket.emit('group_create', { owner_id: userId, owner_username: username, name: name, members: memberIds });
        }

        function renameCurrentGroup() {
            var newName = document.getElementById('renameGroupInput').value.trim();
            if (!currentRoom || !currentRoom.startsWith('_group_')) { alert('Bir grupta değilsiniz'); return; }
            socket.emit('group_rename', { room: currentRoom, requester_id: userId, new_name: newName });
            document.getElementById('renameGroupInput').value = '';
        }
        
        function scrollToBottom() {
            var messagesDiv = document.getElementById('messages');
            messagesDiv.scrollTop = messagesDiv.scrollHeight;
        }
        
        document.getElementById('messageInput').addEventListener('keypress', function(e) {
            if (e.key === 'Enter') sendMessage();
        });
        
        document.getElementById('usernameInput').addEventListener('keypress', function(e) {
            if (e.key === 'Enter') login();
        });
        
        document.getElementById('newRoomInput').addEventListener('keypress', function(e) {
            if (e.key === 'Enter') createRoom();
        });
        
        document.getElementById('privateUserIdInput').addEventListener('keypress', function(e) {
            if (e.key === 'Enter') startPrivateChat();
        });
        
        document.getElementById('userIdDisplay').addEventListener('click', function() {
            var text = userId;
            var textarea = document.createElement('textarea');
            textarea.value = text;
            document.body.appendChild(textarea);
            textarea.select();
            document.execCommand('copy');
            document.body.removeChild(textarea);
            alert('ID kopyalandı: ' + text);
        });
    </script>
</body>
</html>"""

@app.route('/')
def index():
    return HTML_PAGE

@app.route('/api/rooms')
def get_rooms():
    try:
        rooms = list(rooms_collection.find({}, {'_id': 0, 'name': 1}).sort('name', ASCENDING))
        return jsonify(rooms)
    except Exception as e:
        logger.error(f'❌ Oda listesi hatası: {e}')
        return jsonify([])

@app.route('/api/create_room', methods=['POST'])
def create_room():
    data = request.json
    room_name = data.get('name', '').strip()
    
    if not room_name:
        return jsonify({'success': False, 'message': 'Oda adı boş olamaz!'})
    
    try:
        rooms_collection.insert_one({'name': room_name, 'created_at': datetime.now()})
        return jsonify({'success': True, 'name': room_name})
    except Exception as e:
        return jsonify({'success': False, 'message': 'Bu oda zaten mevcut!'})


@app.route('/api/my_groups')
def api_my_groups():
    user_id = request.args.get('user_id', '').upper()
    if not user_id:
        return jsonify([])
    try:
        groups = list(groups_collection.find({ 'members': user_id }, { '_id': 0, 'room': 1, 'name': 1 }).sort('name', ASCENDING))
        return jsonify(groups)
    except Exception as e:
        logger.error(f'❌ Gruplar yüklenemedi: {e}')
        return jsonify([])

@app.route('/api/messages')
def get_messages():
    room = request.args.get('room', 'Genel')
    requester_id = (request.args.get('user_id') or '').upper()
    try:
        # Access control for group rooms
        if room.startswith('_group_'):
            grp = groups_collection.find_one({ 'room': room }, { 'members': 1 })
            if not grp or requester_id not in (grp.get('members') or []):
                logger.info(f'⛔ Yetkisiz mesaj erişimi engellendi room={room} user={requester_id}')
                return jsonify([])

        messages = list(messages_collection.find(
            {'room': room}, 
            {'_id': 0, 'username': 1, 'message': 1, 'timestamp': 1}
        ).sort('_id', ASCENDING).limit(100))
        
        logger.info(f'✅ Oda: {room}, Mesaj sayısı: {len(messages)}')
        return jsonify(messages)
    except Exception as e:
        logger.error(f'❌ Mesaj yükleme hatası: {e}')
        return jsonify([])

@socketio.on('register_user')
def handle_register_user(data):
    username = data.get('username', 'Anonim')
    provided_id = data.get('user_id')
    if provided_id and isinstance(provided_id, str):
        user_id = provided_id.strip().upper()
    else:
        user_id = str(uuid.uuid4())[:8].upper()

    active_users[request.sid] = {
        'username': username,
        'user_id': user_id,
        'socket_id': request.sid
    }

    try:
        # Upsert user profile for basic username lookup and persistence
        users_collection.update_one(
            { 'user_id': user_id },
            { '$set': { 'username': username, 'updated_at': datetime.now() }, '$setOnInsert': { 'created_at': datetime.now() } },
            upsert=True
        )
    except Exception as e:
        logger.error(f'❌ Kullanıcı upsert hatası: {e}')

    logger.info(f'✅ Kullanıcı kaydedildi - Adı: {username}, ID: {user_id}, SID: {request.sid}')
    emit('user_registered', {'user_id': user_id})

@socketio.on('send_message')
def handle_message(data):
    username = data.get('username', 'Anonim')
    message = data.get('message', '')
    room = data.get('room', 'Genel')
    timestamp = datetime.now().strftime('%H:%M')
    
    logger.info(f'📨 Mesaj alındı -> Kullanıcı: {username}, Oda: {room}, Mesaj: {message}')
    
    # Guard: if room is a group, ensure sender is a member
    if room.startswith('_group_'):
        try:
            grp = groups_collection.find_one({'room': room}, {'members': 1})
            sender = active_users.get(request.sid)
            sender_id = sender['user_id'] if sender else None
            if not grp or not sender_id or sender_id.upper() not in grp.get('members', []):
                emit('error_message', {'message': 'Bu gruba üye değilsiniz.'})
                return
        except Exception as e:
            logger.error(f'❌ Grup mesaj guard hatası: {e}')
            emit('error_message', {'message': 'Grup doğrulaması başarısız.'})
            return

    socketio.emit('receive_message', {
        'username': username,
        'message': message,
        'timestamp': timestamp,
        'room': room
    }, to=room)
    
    logger.info(f'📢 Mesaj {room} odasındaki herkese yayınlandı')
    
    try:
        is_private = '_private_' in room
        messages_collection.insert_one({
            'username': username,
            'message': message,
            'timestamp': timestamp,
            'room': room,
            'private': is_private,
            'created_at': datetime.now()
        })
        logger.info(f'💾 Mesaj MongoDB\'ye kaydedildi')
    except Exception as e:
        logger.error(f'❌ MongoDB kayıt hatası: {e}')

@socketio.on('join_room')
def handle_join_room(data):
    room = data.get('room', 'Genel')
    username = data.get('username', 'Anonim')
    # Guard: if group room, ensure user is member and room not full
    if room.startswith('_group_'):
        try:
            grp = groups_collection.find_one({'room': room})
            user = active_users.get(request.sid)
            user_id = user['user_id'] if user else None
            if not grp or not user_id or user_id.upper() not in grp.get('members', []):
                emit('error_message', {'message': 'Bu gruba erişiminiz yok.'})
                return
            if len(grp.get('members', [])) > 5:
                emit('error_message', {'message': 'Grup kapasitesi aşıldı (max 5).'})
                return
        except Exception as e:
            logger.error(f'❌ Grup katılma guard hatası: {e}')
            emit('error_message', {'message': 'Grup doğrulaması başarısız.'})
            return

    join_room(room)
    logger.info(f'✅ {username} (SID: {request.sid}) -> {room} odasına katıldı')
    
    if '_private_' not in room:
        socketio.emit('receive_message', {
            'username': 'Sistem',
            'message': f'{username} odaya katıldı',
            'timestamp': datetime.now().strftime('%H:%M'),
            'room': room
        }, to=room)

@socketio.on('leave_room')
def handle_leave_room(data):
    room = data.get('room')
    username = data.get('username', 'Anonim')
    leave_room(room)
    logger.info(f'❌ {username} {room} odasından ayrıldı')

@socketio.on('new_room')
def handle_new_room(data):
    emit('room_created', {'name': data['name']}, broadcast=True)

@socketio.on('start_private_chat')
def handle_start_private_chat(data):
    from_id = data.get('from_id')
    to_id = data.get('to_id')
    username = data.get('username')
    
    target_user = None
    target_socket_id = None
    
    for sid, user_data in active_users.items():
        if user_data['user_id'] == to_id:
            target_user = user_data
            target_socket_id = sid
            break
    
    if not target_user:
        emit('error_message', {
            'message': '❌ Kullanıcı çevrimiçi değil veya ID hatalı!'
        })
        logger.info(f'❌ Özel sohbet hatası: Hedef kullanıcı {to_id} bulunamadı')
        return
    
    private_room = f'_private_{sorted([from_id, to_id])[0]}_{sorted([from_id, to_id])[1]}'
    
    logger.info(f'🔒 Özel sohbet başlatılıyor: {username} ({from_id}) <-> {target_user["username"]} ({to_id})')
    logger.info(f'🔒 Oda adı: {private_room}')
    
    socketio.emit('private_room_created', {
        'room': private_room,
        'other_username': target_user['username'],
        'other_id': to_id
    }, to=request.sid)
    
    socketio.emit('private_room_created', {
        'room': private_room,
        'other_username': username,
        'other_id': from_id
    }, to=target_socket_id)
    
    logger.info(f'✅ Özel oda oluşturuldu: {private_room}')


@socketio.on('friend_request_send')
def handle_friend_request_send(data):
    from_id = data.get('from_id', '').upper()
    to_id = data.get('to_id', '').upper()
    from_username = data.get('from_username', 'Anonim')

    if not from_id or not to_id or from_id == to_id:
        emit('friend_request_result', {'ok': False, 'message': 'Geçersiz istek.'})
        return

    # Already friends?
    if are_friends(from_id, to_id):
        emit('friend_request_result', {'ok': False, 'message': 'Zaten arkadaşsınız.'})
        return

    try:
        # Prevent duplicate pending
        existing = friend_requests_collection.find_one({
            'from_id': from_id,
            'to_id': to_id,
            'status': 'pending'
        })
        if existing:
            emit('friend_request_result', {'ok': True, 'message': 'İstek zaten gönderildi.'})
            return

        req = {
            'from_id': from_id,
            'to_id': to_id,
            'from_username': from_username,
            'status': 'pending',
            'created_at': datetime.now()
        }
        result = friend_requests_collection.insert_one(req)
        request_id = str(result.inserted_id)
        # Notify receiver if online
        target_sid = get_online_sid_by_user_id(to_id)
        if target_sid:
            socketio.emit('friend_request_received', {
                'request_id': request_id,
                'from_id': from_id,
                'from_username': from_username
            }, to=target_sid)
        emit('friend_request_result', {'ok': True, 'message': 'Arkadaşlık isteği gönderildi.'})
    except Exception as e:
        logger.error(f'❌ Arkadaşlık isteği hatası: {e}')
        emit('friend_request_result', {'ok': False, 'message': 'İstek gönderilemedi.'})


@socketio.on('friend_request_respond')
def handle_friend_request_respond(data):
    request_id = data.get('request_id')
    accept = bool(data.get('accept'))
    user_id = data.get('user_id', '').upper()
    try:
        req = friend_requests_collection.find_one({ '_id': ObjectId(request_id) })
        if not req or req.get('to_id') != user_id or req.get('status') != 'pending':
            emit('friend_request_result', {'ok': False, 'message': 'Geçersiz istek.'})
            return
        if accept:
            low, high = sorted([req['from_id'], req['to_id']])
            friendships_collection.update_one(
                { 'user_low': low, 'user_high': high },
                { '$setOnInsert': { 'created_at': datetime.now() } },
                upsert=True
            )
            friend_requests_collection.update_one({ '_id': req['_id'] }, { '$set': { 'status': 'accepted', 'updated_at': datetime.now() } })
            # Notify both sides
            from_sid = get_online_sid_by_user_id(req['from_id'])
            if from_sid:
                socketio.emit('friend_request_result', {'ok': True, 'message': f"{user_id} isteğinizi kabul etti."}, to=from_sid)
            emit('friend_request_result', {'ok': True, 'message': 'Arkadaşlık isteği kabul edildi.'})
        else:
            friend_requests_collection.update_one({ '_id': req['_id'] }, { '$set': { 'status': 'rejected', 'updated_at': datetime.now() } })
            from_sid = get_online_sid_by_user_id(req['from_id'])
            if from_sid:
                socketio.emit('friend_request_result', {'ok': True, 'message': f"{user_id} isteğinizi reddetti."}, to=from_sid)
            emit('friend_request_result', {'ok': True, 'message': 'Arkadaşlık isteği reddedildi.'})
    except Exception as e:
        logger.error(f'❌ Arkadaşlık isteği cevap hatası: {e}')
        emit('friend_request_result', {'ok': False, 'message': 'İşlem başarısız.'})


@socketio.on('group_create')
def handle_group_create(data):
    owner_id = data.get('owner_id', '').upper()
    owner_username = data.get('owner_username', 'Anonim')
    name = (data.get('name') or '').strip() or 'Yeni Grup'
    invited = [owner_id] + [mid.upper() for mid in (data.get('members') or [])]
    # Dedupe and cap size to 5
    members = []
    for m in invited:
        if m and m not in members:
            members.append(m)
    if len(members) > 5:
        emit('error_message', { 'message': 'Grup en fazla 5 kişi olabilir.' })
        return

    # Only allow if all non-owner members are friends with owner
    for m in members:
        if m == owner_id:
            continue
        if not are_friends(owner_id, m):
            emit('error_message', { 'message': 'Tüm üyeler önce arkadaş olmalı.' })
            return

    group_id = str(uuid.uuid4())[:8].upper()
    room = f'_group_{group_id}'
    try:
        groups_collection.insert_one({
            'group_id': group_id,
            'name': name,
            'room': room,
            'owner_id': owner_id,
            'members': members,
            'created_at': datetime.now()
        })
        # Notify all online members
        for m in members:
            sid = get_online_sid_by_user_id(m)
            if sid:
                socketio.emit('group_created', { 'room': room, 'name': name, 'group_id': group_id }, to=sid)
        logger.info(f'👥 Grup oluşturuldu: {group_id}, ad {name}, üyeler {members}')
    except Exception as e:
        logger.error(f'❌ Grup oluşturma hatası: {e}')
        emit('error_message', { 'message': 'Grup oluşturulamadı.' })


@socketio.on('group_rename')
def handle_group_rename(data):
    room = data.get('room')
    requester_id = data.get('requester_id', '').upper()
    new_name = (data.get('new_name') or '').strip()
    if not room or not new_name:
        emit('error_message', { 'message': 'Yeni ad gerekli.' })
        return
    try:
        grp = groups_collection.find_one({ 'room': room })
        if not grp:
            emit('error_message', { 'message': 'Grup bulunamadı.' })
            return
        if requester_id not in grp.get('members', []):
            emit('error_message', { 'message': 'Sadece grup üyeleri adı değiştirebilir.' })
            return
        groups_collection.update_one({ 'room': room }, { '$set': { 'name': new_name, 'updated_at': datetime.now() } })
        # We will broadcast a room name change logically by mapping to a synthetic new channel name for UI
        old_room = room
        new_room = room  # keep same room id; UI updates its label
        for m in grp.get('members', []):
            sid = get_online_sid_by_user_id(m)
            if sid:
                socketio.emit('group_renamed', { 'old_room': old_room, 'new_room': new_room, 'name': new_name }, to=sid)
        logger.info(f'✏️ Grup adı güncellendi: {room} -> {new_name}')
    except Exception as e:
        logger.error(f'❌ Grup ad değiştirme hatası: {e}')
        emit('error_message', { 'message': 'Ad değiştirilemedi.' })

@socketio.on('connect')
def handle_connect():
    user_ip = request.remote_addr
    sid = request.sid
    logger.info(f'✅ Kullanıcı bağlandı - SID: {sid}, IP: {user_ip}')

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    if sid in active_users:
        user_info = active_users[sid]
        logger.info(f'❌ Kullanıcı ayrıldı - Adı: {user_info["username"]}, ID: {user_info["user_id"]}, SID: {sid}')
        del active_users[sid]
    else:
        logger.info(f'❌ Kullanıcı ayrıldı - SID: {sid}')

if __name__ == '__main__':
    print('\n' + '='*60)
    print('🚀 GRUP SOHBET SUNUCUSU BAŞLATILDI! (MongoDB)')
    print('='*60)
    print('📍 Render\'da çalışıyor...')
    print('='*60)
    print('✨ Özellikler:')
    print('   • MongoDB Atlas bağlantısı')
    print('   • 5 Varsayılan oda (Genel, Teknoloji, Spor, Müzik, Oyun)')
    print('   • Yeni oda oluşturma')
    print('   • Her odanın bağımsız mesaj sistemi')
    print('   • Gerçek zamanlı mesajlaşma')
    print('   • Her kullanıcıya benzersiz ID verilir')
    print('   • Özel sohbet sistemi (sadece 2 kullanıcı görür)')
    print('   • Modern ve şık tasarım')
    print('='*60 + '\n')

    port = int(os.environ.get("PORT", 5000))
    socketio.run(
        app,
        host="0.0.0.0",
        port=port,
        debug=False,
        allow_unsafe_werkzeug=True  # 🔥 Burası kritik!
    )
