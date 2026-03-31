import asyncio
import json
import time
import os
import sys
import random
import threading
import webbrowser
from flask import Flask, request, jsonify, Response
from flask_cors import CORS
from telethon import TelegramClient, errors
from telethon.tl.functions.channels import LeaveChannelRequest
from telethon.tl.functions.messages import DeleteChatUserRequest
from telethon.tl.types import (
    Chat, Channel, ChatForbidden, ChannelForbidden,
    InputChannel, InputUser
)

# --- Determine base path (works for both script and PyInstaller exe) ---
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_FILE = os.path.join(BASE_DIR, 'config.json')
SESSION_NAME = os.path.join(BASE_DIR, 'telegram_session')

app = Flask(__name__)
CORS(app)

client = None
loop = None
phone_hash = None
api_id = None
api_hash = None


def load_config():
    global api_id, api_hash
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            cfg = json.load(f)
            api_id = cfg.get('api_id')
            api_hash = cfg.get('api_hash')
            return True
    return False


def save_config(aid, ahash):
    global api_id, api_hash
    api_id = int(aid)
    api_hash = ahash
    with open(CONFIG_FILE, 'w') as f:
        json.dump({'api_id': api_id, 'api_hash': api_hash}, f)


def get_or_create_loop():
    global loop
    if loop is None or loop.is_closed():
        loop = asyncio.new_event_loop()
        t = threading.Thread(target=loop.run_forever, daemon=True)
        t.start()
    return loop


def run_async(coro):
    l = get_or_create_loop()
    future = asyncio.run_coroutine_threadsafe(coro, l)
    return future.result(timeout=120)


def get_client():
    global client
    if client is None:
        l = get_or_create_loop()
        client = TelegramClient(SESSION_NAME, api_id, api_hash, loop=l)
    return client


# ===================== EMBEDDED HTML =====================
HTML_PAGE = r'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Telegram Group Leaver</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #1a1a2e;
    color: #e0e0e0;
    min-height: 100vh;
  }
  .container { max-width: 900px; margin: 0 auto; padding: 20px; }
  h1 { text-align: center; color: #00d2ff; margin-bottom: 5px; font-size: 28px; }
  .subtitle { text-align: center; color: #888; margin-bottom: 30px; font-size: 14px; }

  .auth-card {
    background: #16213e; border-radius: 12px; padding: 30px;
    max-width: 420px; margin: 40px auto;
    box-shadow: 0 4px 20px rgba(0,0,0,0.3);
  }
  .auth-card h2 { color: #00d2ff; margin-bottom: 20px; text-align: center; }
  .auth-card input, .auth-card select {
    width: 100%; padding: 12px 16px;
    border: 1px solid #2a3a5c; border-radius: 8px;
    background: #0f1a30; color: #e0e0e0;
    font-size: 16px; margin-bottom: 12px; outline: none;
  }
  .auth-card input:focus { border-color: #00d2ff; }
  .auth-card input::placeholder { color: #555; }
  .auth-card .help-text { color: #888; font-size: 12px; margin-bottom: 16px; text-align: center; line-height: 1.6; }
  .auth-card a { color: #00d2ff; }

  .btn {
    padding: 12px 24px; border: none; border-radius: 8px;
    font-size: 15px; font-weight: 600; cursor: pointer; transition: all 0.2s;
  }
  .btn:disabled { opacity: 0.5; cursor: not-allowed; }
  .btn-primary { background: #00d2ff; color: #000; width: 100%; }
  .btn-primary:hover:not(:disabled) { background: #00b8e6; }
  .btn-danger { background: #ff4757; color: #fff; }
  .btn-danger:hover:not(:disabled) { background: #e0303f; }
  .btn-secondary { background: #2a3a5c; color: #e0e0e0; }
  .btn-secondary:hover:not(:disabled) { background: #3a4a6c; }
  .btn-sm { padding: 8px 16px; font-size: 13px; }
  .error { color: #ff4757; font-size: 14px; margin-top: 8px; text-align: center; }

  .user-bar {
    background: #16213e; border-radius: 12px; padding: 16px 24px;
    display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;
  }
  .user-info { display: flex; align-items: center; gap: 12px; }
  .user-avatar {
    width: 40px; height: 40px; border-radius: 50%;
    background: #00d2ff; display: flex; align-items: center; justify-content: center;
    font-weight: bold; color: #000; font-size: 18px;
  }
  .user-name { font-weight: 600; }
  .user-phone { color: #888; font-size: 13px; }

  .toolbar { display: flex; gap: 10px; align-items: center; margin-bottom: 16px; flex-wrap: wrap; }
  .search-box {
    flex: 1; min-width: 200px; padding: 10px 16px;
    border: 1px solid #2a3a5c; border-radius: 8px;
    background: #0f1a30; color: #e0e0e0; font-size: 14px; outline: none;
  }
  .search-box:focus { border-color: #00d2ff; }
  .search-box::placeholder { color: #555; }
  .filter-btn {
    padding: 8px 14px; border: 1px solid #2a3a5c; border-radius: 8px;
    background: transparent; color: #888; cursor: pointer; font-size: 13px; transition: all 0.2s;
  }
  .filter-btn.active { border-color: #00d2ff; color: #00d2ff; }
  .filter-btn:hover { border-color: #00d2ff; color: #00d2ff; }
  .selected-count {
    background: #00d2ff; color: #000; padding: 4px 12px;
    border-radius: 20px; font-size: 13px; font-weight: 600;
  }

  .group-list { display: flex; flex-direction: column; gap: 6px; margin-bottom: 80px; }
  .group-item {
    background: #16213e; border-radius: 10px; padding: 14px 18px;
    display: flex; align-items: center; gap: 14px;
    cursor: pointer; transition: all 0.15s; border: 2px solid transparent;
  }
  .group-item:hover { background: #1a2744; }
  .group-item.selected { border-color: #00d2ff; background: #0d1f3c; }
  .group-item input[type="checkbox"] {
    width: 20px; height: 20px; accent-color: #00d2ff; cursor: pointer; flex-shrink: 0;
  }
  .group-details { flex: 1; min-width: 0; }
  .group-name {
    font-weight: 600; font-size: 15px;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .group-meta { color: #888; font-size: 12px; margin-top: 2px; display: flex; gap: 12px; }
  .badge {
    padding: 3px 10px; border-radius: 12px; font-size: 11px; font-weight: 600;
    text-transform: uppercase; flex-shrink: 0;
  }
  .badge-group { background: #2a3a5c; color: #a0b0d0; }
  .badge-supergroup { background: #1a3a2a; color: #2ed573; }
  .badge-channel { background: #3a2a1a; color: #ffa502; }
  .badge-muted { background: #3a1a1a; color: #ff6b6b; font-size: 10px; }

  .action-bar {
    position: fixed; bottom: 0; left: 0; right: 0;
    background: linear-gradient(transparent, #1a1a2e 30%);
    padding: 20px 0 16px; text-align: center; z-index: 100;
  }
  .btn-leave {
    background: #ff4757; color: #fff; padding: 14px 40px;
    font-size: 16px; font-weight: 700; border: none; border-radius: 10px;
    cursor: pointer; transition: all 0.2s;
  }
  .btn-leave:hover:not(:disabled) { background: #e0303f; transform: scale(1.02); }
  .btn-leave:disabled { opacity: 0.4; cursor: not-allowed; transform: none; }

  .modal-overlay {
    display: none; position: fixed; inset: 0;
    background: rgba(0,0,0,0.7); z-index: 1000;
    align-items: center; justify-content: center;
  }
  .modal-overlay.active { display: flex; }
  .modal {
    background: #16213e; border-radius: 14px; padding: 28px;
    max-width: 500px; width: 90%; max-height: 80vh; overflow-y: auto;
    box-shadow: 0 8px 40px rgba(0,0,0,0.5);
  }
  .modal h3 { color: #ff4757; margin-bottom: 16px; }
  .modal-list {
    list-style: none; max-height: 300px; overflow-y: auto;
    margin-bottom: 20px; border: 1px solid #2a3a5c; border-radius: 8px; padding: 8px;
  }
  .modal-list li { padding: 6px 10px; border-bottom: 1px solid #1a2744; font-size: 14px; }
  .modal-list li:last-child { border-bottom: none; }
  .modal-actions { display: flex; gap: 10px; justify-content: flex-end; }

  .progress-section {
    display: none; background: #16213e; border-radius: 12px; padding: 24px; margin-top: 20px;
  }
  .progress-section.active { display: block; }
  .progress-bar-container {
    background: #0f1a30; border-radius: 8px; height: 24px; overflow: hidden; margin: 16px 0;
  }
  .progress-bar {
    height: 100%; background: linear-gradient(90deg, #00d2ff, #2ed573);
    border-radius: 8px; transition: width 0.3s;
    display: flex; align-items: center; justify-content: center;
    font-size: 12px; font-weight: 700; color: #000; min-width: 40px;
  }
  .progress-log {
    max-height: 250px; overflow-y: auto;
    font-family: 'Consolas', monospace; font-size: 13px;
    background: #0f1a30; border-radius: 8px; padding: 12px;
  }
  .log-entry { padding: 4px 0; border-bottom: 1px solid #1a2744; }
  .log-success { color: #2ed573; }
  .log-fail { color: #ff4757; }
  .log-wait { color: #ffa502; }

  .summary-card {
    text-align: center; padding: 20px;
    background: #16213e; border-radius: 12px; margin-top: 16px;
  }
  .summary-card h3 { margin-bottom: 12px; color: #00d2ff; }
  .summary-stats { display: flex; gap: 30px; justify-content: center; }
  .stat { font-size: 28px; font-weight: 700; }
  .stat-label { font-size: 13px; color: #888; }
  .stat-success { color: #2ed573; }
  .stat-fail { color: #ff4757; }

  .loading { text-align: center; padding: 40px; color: #888; }
  .spinner {
    display: inline-block; width: 30px; height: 30px;
    border: 3px solid #2a3a5c; border-top-color: #00d2ff;
    border-radius: 50%; animation: spin 0.8s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  .hidden { display: none !important; }
  .flood-timer { color: #ffa502; font-size: 18px; font-weight: 700; text-align: center; margin: 10px 0; }
</style>
</head>
<body>
<div class="container">
  <h1>Telegram Group Leaver</h1>
  <p class="subtitle">Select groups and leave them in bulk</p>

  <!-- API Setup Section -->
  <div id="apiSetupSection" class="hidden">
    <div class="auth-card">
      <h2>API Setup (One-Time)</h2>
      <p class="help-text">
        Go to <a href="https://my.telegram.org" target="_blank">my.telegram.org</a>, log in,
        click "API development tools", create an app,<br>then paste your credentials below.
      </p>
      <input type="text" id="apiIdInput" placeholder="API ID (e.g. 12345678)">
      <input type="text" id="apiHashInput" placeholder="API Hash (e.g. abcdef1234...)">
      <button class="btn btn-primary" onclick="saveApiConfig()">Save & Continue</button>
      <div class="error" id="apiError"></div>
    </div>
  </div>

  <!-- Auth Section -->
  <div id="authSection" class="hidden">
    <div class="auth-card" id="phoneStep">
      <h2>Login to Telegram</h2>
      <input type="tel" id="phoneInput" placeholder="+1 234 567 8900" autofocus>
      <button class="btn btn-primary" id="sendCodeBtn" onclick="sendCode()">Send Code</button>
      <div class="error" id="phoneError"></div>
    </div>
    <div class="auth-card hidden" id="codeStep">
      <h2>Enter Verification Code</h2>
      <p style="color:#888; margin-bottom:16px; text-align:center; font-size:14px;">Check your Telegram app for the code</p>
      <input type="text" id="codeInput" placeholder="12345" maxlength="5" style="text-align:center; font-size:24px; letter-spacing:8px;">
      <button class="btn btn-primary" id="verifyCodeBtn" onclick="verifyCode()">Verify</button>
      <div class="error" id="codeError"></div>
    </div>
    <div class="auth-card hidden" id="twoFaStep">
      <h2>Two-Factor Authentication</h2>
      <p style="color:#888; margin-bottom:16px; text-align:center; font-size:14px;">Enter your 2FA password</p>
      <input type="password" id="passwordInput" placeholder="2FA Password">
      <button class="btn btn-primary" onclick="verify2FA()">Submit</button>
      <div class="error" id="twoFaError"></div>
    </div>
  </div>

  <!-- Main App Section -->
  <div id="appSection" class="hidden">
    <div class="user-bar">
      <div class="user-info">
        <div class="user-avatar" id="userAvatar">?</div>
        <div>
          <div class="user-name" id="userName">User</div>
          <div class="user-phone" id="userPhone">+000</div>
        </div>
      </div>
      <div style="display:flex;gap:10px;align-items:center;">
        <button class="btn btn-secondary btn-sm" onclick="loadGroups()">Refresh</button>
        <button class="btn btn-danger btn-sm" onclick="logout()">Logout</button>
      </div>
    </div>

    <div class="toolbar">
      <input type="text" class="search-box" id="searchBox" placeholder="Search groups..." oninput="filterGroups()">
      <button class="filter-btn active" data-filter="all" onclick="setFilter('all', this)">All</button>
      <button class="filter-btn" data-filter="group" onclick="setFilter('group', this)">Groups</button>
      <button class="filter-btn" data-filter="supergroup" onclick="setFilter('supergroup', this)">Supergroups</button>
      <button class="filter-btn" data-filter="channel" onclick="setFilter('channel', this)">Channels</button>
    </div>

    <div style="display:flex;gap:10px;margin-bottom:16px;align-items:center;">
      <button class="btn btn-secondary btn-sm" onclick="selectAll()">Select All</button>
      <button class="btn btn-secondary btn-sm" onclick="deselectAll()">Deselect All</button>
      <button class="btn btn-secondary btn-sm" onclick="selectMuted()">Select Muted</button>
      <span class="selected-count" id="selectedCount">0 selected</span>
      <span style="color:#888;font-size:13px;margin-left:auto;" id="totalCount">0 groups</span>
    </div>

    <div id="groupList" class="group-list"></div>
    <div id="loadingGroups" class="loading hidden"><div class="spinner"></div><p style="margin-top:10px">Loading groups...</p></div>
    <div id="noGroups" class="loading hidden"><p>No groups found.</p></div>

    <div class="action-bar">
      <button class="btn-leave" id="leaveBtn" onclick="showConfirmModal()" disabled>Leave Selected (0)</button>
    </div>

    <div class="progress-section" id="progressSection">
      <h3 style="margin-bottom:8px;">Leaving Groups...</h3>
      <div id="floodTimer" class="flood-timer hidden"></div>
      <div class="progress-bar-container">
        <div class="progress-bar" id="progressBar" style="width:0%">0%</div>
      </div>
      <div class="progress-log" id="progressLog"></div>
    </div>

    <div class="summary-card hidden" id="summaryCard">
      <h3>Done!</h3>
      <div class="summary-stats">
        <div><div class="stat stat-success" id="summarySuccess">0</div><div class="stat-label">Left Successfully</div></div>
        <div><div class="stat stat-fail" id="summaryFail">0</div><div class="stat-label">Failed</div></div>
      </div>
      <button class="btn btn-primary" style="margin-top:20px;width:auto;padding:10px 30px;" onclick="closeSummary()">OK</button>
    </div>
  </div>
</div>

<div class="modal-overlay" id="confirmModal">
  <div class="modal">
    <h3>Confirm Leaving Groups</h3>
    <p style="margin-bottom:12px;color:#888;">You are about to leave <strong id="confirmCount">0</strong> groups. This cannot be undone.</p>
    <ul class="modal-list" id="confirmList"></ul>
    <div class="modal-actions">
      <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
      <button class="btn btn-danger" id="confirmLeaveBtn" onclick="startLeaving()">Leave All</button>
    </div>
  </div>
</div>

<script>
const API = '';
let allGroups = [];
let selectedIds = new Set();
let currentFilter = 'all';
let currentPhone = '';

window.addEventListener('DOMContentLoaded', init);

async function init() {
  try {
    const res = await fetch(API + '/api/config-status');
    const data = await res.json();
    if (!data.configured) {
      document.getElementById('apiSetupSection').classList.remove('hidden');
    } else {
      checkAuth();
    }
  } catch(e) {
    document.getElementById('apiSetupSection').classList.remove('hidden');
  }
}

async function saveApiConfig() {
  const aid = document.getElementById('apiIdInput').value.trim();
  const ahash = document.getElementById('apiHashInput').value.trim();
  if (!aid || !ahash) {
    document.getElementById('apiError').textContent = 'Both fields are required';
    return;
  }
  if (!/^\d+$/.test(aid)) {
    document.getElementById('apiError').textContent = 'API ID must be a number';
    return;
  }
  try {
    const res = await fetch(API + '/api/save-config', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({api_id: aid, api_hash: ahash})
    });
    const data = await res.json();
    if (data.success) {
      document.getElementById('apiSetupSection').classList.add('hidden');
      checkAuth();
    } else {
      document.getElementById('apiError').textContent = data.error || 'Failed to save';
    }
  } catch(e) {
    document.getElementById('apiError').textContent = 'Connection error';
  }
}

async function checkAuth() {
  try {
    const res = await fetch(API + '/auth/status');
    const data = await res.json();
    if (data.authorized) {
      showApp(data.user);
      loadGroups();
    } else {
      document.getElementById('authSection').classList.remove('hidden');
    }
  } catch(e) {
    document.getElementById('authSection').classList.remove('hidden');
  }
}

async function sendCode() {
  const phone = document.getElementById('phoneInput').value.trim();
  if (!phone) return;
  currentPhone = phone;
  const btn = document.getElementById('sendCodeBtn');
  btn.disabled = true; btn.textContent = 'Sending...';
  document.getElementById('phoneError').textContent = '';
  try {
    const res = await fetch(API + '/auth/send-code', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({phone: phone})
    });
    const data = await res.json();
    if (data.success) {
      document.getElementById('phoneStep').classList.add('hidden');
      document.getElementById('codeStep').classList.remove('hidden');
      document.getElementById('codeInput').focus();
    } else {
      document.getElementById('phoneError').textContent = data.error || 'Failed to send code';
    }
  } catch(e) {
    document.getElementById('phoneError').textContent = 'Connection error. Is the server running?';
  }
  btn.disabled = false; btn.textContent = 'Send Code';
}

async function verifyCode() {
  const code = document.getElementById('codeInput').value.trim();
  if (!code) return;
  const btn = document.getElementById('verifyCodeBtn');
  btn.disabled = true; btn.textContent = 'Verifying...';
  document.getElementById('codeError').textContent = '';
  try {
    const res = await fetch(API + '/auth/verify-code', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({phone: currentPhone, code: code})
    });
    const data = await res.json();
    if (data.success) { showApp(data.user); loadGroups(); }
    else if (data.needs_2fa) {
      document.getElementById('codeStep').classList.add('hidden');
      document.getElementById('twoFaStep').classList.remove('hidden');
      document.getElementById('passwordInput').focus();
    } else {
      document.getElementById('codeError').textContent = data.error || 'Invalid code';
    }
  } catch(e) { document.getElementById('codeError').textContent = 'Connection error'; }
  btn.disabled = false; btn.textContent = 'Verify';
}

async function verify2FA() {
  const password = document.getElementById('passwordInput').value;
  if (!password) return;
  try {
    const res = await fetch(API + '/auth/verify-code', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ phone: currentPhone, code: document.getElementById('codeInput').value.trim(), password: password })
    });
    const data = await res.json();
    if (data.success) { showApp(data.user); loadGroups(); }
    else { document.getElementById('twoFaError').textContent = data.error || 'Wrong password'; }
  } catch(e) { document.getElementById('twoFaError').textContent = 'Connection error'; }
}

function showApp(user) {
  document.getElementById('authSection').classList.add('hidden');
  document.getElementById('appSection').classList.remove('hidden');
  document.getElementById('userName').textContent = ((user.first_name || '') + ' ' + (user.last_name || '')).trim();
  document.getElementById('userPhone').textContent = user.phone ? '+' + user.phone : '';
  document.getElementById('userAvatar').textContent = (user.first_name || '?')[0].toUpperCase();
}

async function loadGroups() {
  document.getElementById('loadingGroups').classList.remove('hidden');
  document.getElementById('groupList').innerHTML = '';
  document.getElementById('noGroups').classList.add('hidden');
  try {
    const res = await fetch(API + '/groups');
    const data = await res.json();
    if (data.success) {
      allGroups = data.groups.sort((a, b) => a.name.localeCompare(b.name));
      selectedIds.clear();
      renderGroups();
    }
  } catch(e) { console.error('Failed to load groups:', e); }
  document.getElementById('loadingGroups').classList.add('hidden');
}

function renderGroups() {
  const search = document.getElementById('searchBox').value.toLowerCase();
  const list = document.getElementById('groupList');
  list.innerHTML = '';
  const filtered = allGroups.filter(g => {
    if (currentFilter !== 'all' && g.type !== currentFilter) return false;
    if (search && !g.name.toLowerCase().includes(search)) return false;
    return true;
  });
  document.getElementById('noGroups').classList.toggle('hidden', filtered.length > 0);
  filtered.forEach(g => {
    var div = document.createElement('div');
    div.className = 'group-item' + (selectedIds.has(g.id) ? ' selected' : '');
    div.onclick = e => { if (e.target.tagName !== 'INPUT') toggleGroup(g.id); };
    var bc = g.type === 'channel' ? 'badge-channel' : g.type === 'supergroup' ? 'badge-supergroup' : 'badge-group';
    var mb = g.muted ? '<span class="badge badge-muted">MUTED</span>' : '';
    div.innerHTML =
      '<input type="checkbox" ' + (selectedIds.has(g.id) ? 'checked' : '') + ' onchange="toggleGroup(' + g.id + ')">' +
      '<div class="group-details"><div class="group-name">' + escapeHtml(g.name) + '</div>' +
      '<div class="group-meta"><span>' + (g.members > 0 ? g.members.toLocaleString() + ' members' : 'Unknown') + '</span></div></div>' +
      '<span class="badge ' + bc + '">' + g.type + '</span>' + mb;
    list.appendChild(div);
  });
  updateCounts();
  document.getElementById('totalCount').textContent = filtered.length + ' of ' + allGroups.length + ' groups';
}

function toggleGroup(id) {
  if (selectedIds.has(id)) selectedIds.delete(id); else selectedIds.add(id);
  renderGroups();
}
function selectAll() {
  var s = document.getElementById('searchBox').value.toLowerCase();
  allGroups.forEach(g => {
    if (currentFilter !== 'all' && g.type !== currentFilter) return;
    if (s && !g.name.toLowerCase().includes(s)) return;
    selectedIds.add(g.id);
  });
  renderGroups();
}
function deselectAll() { selectedIds.clear(); renderGroups(); }
function selectMuted() { allGroups.forEach(g => { if (g.muted) selectedIds.add(g.id); }); renderGroups(); }
function setFilter(f, btn) {
  currentFilter = f;
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  renderGroups();
}
function filterGroups() { renderGroups(); }
function updateCounts() {
  var c = selectedIds.size;
  document.getElementById('selectedCount').textContent = c + ' selected';
  document.getElementById('leaveBtn').textContent = 'Leave Selected (' + c + ')';
  document.getElementById('leaveBtn').disabled = c === 0;
}

function showConfirmModal() {
  if (selectedIds.size === 0) return;
  document.getElementById('confirmCount').textContent = selectedIds.size;
  var list = document.getElementById('confirmList');
  list.innerHTML = '';
  allGroups.filter(g => selectedIds.has(g.id)).forEach(g => {
    var li = document.createElement('li'); li.textContent = g.name; list.appendChild(li);
  });
  document.getElementById('confirmModal').classList.add('active');
}
function closeModal() { document.getElementById('confirmModal').classList.remove('active'); }

async function startLeaving() {
  closeModal();
  var groupMap = {};
  var groupsToLeave = [];
  allGroups.forEach(g => {
    if (selectedIds.has(g.id)) {
      groupMap[g.id] = g.name;
      groupsToLeave.push({id: g.id, type: g.type, access_hash: g.access_hash});
    }
  });

  var ps = document.getElementById('progressSection');
  ps.classList.add('active');
  document.getElementById('progressLog').innerHTML = '';
  document.getElementById('progressBar').style.width = '0%';
  document.getElementById('progressBar').textContent = '0%';
  document.getElementById('leaveBtn').disabled = true;
  document.getElementById('summaryCard').classList.add('hidden');

  try {
    var res = await fetch(API + '/leave', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({groups: groupsToLeave})
    });
    var reader = res.body.getReader();
    var decoder = new TextDecoder();
    var buffer = '';
    while (true) {
      var result = await reader.read();
      if (result.done) break;
      buffer += decoder.decode(result.value, {stream: true});
      var lines = buffer.split('\n');
      buffer = lines.pop();
      for (var k = 0; k < lines.length; k++) {
        var line = lines[k];
        if (!line.startsWith('data: ')) continue;
        var data = JSON.parse(line.slice(6));
        if (data.done) { showSummary(data.success_count, data.fail_count); loadGroups(); return; }
        var pct = Math.round((data.index / data.total) * 100);
        document.getElementById('progressBar').style.width = pct + '%';
        document.getElementById('progressBar').textContent = pct + '%';
        var log = document.getElementById('progressLog');
        var name = groupMap[data.group_id] || ('ID:' + data.group_id);
        if (data.status === 'success') {
          log.innerHTML += '<div class="log-entry log-success">OK - Left "' + escapeHtml(name) + '"</div>';
        } else if (data.status === 'failed') {
          log.innerHTML += '<div class="log-entry log-fail">FAIL - "' + escapeHtml(name) + '": ' + escapeHtml(data.error || 'Unknown') + '</div>';
        } else if (data.status === 'flood_wait') {
          log.innerHTML += '<div class="log-entry log-wait">WAIT - Rate limited, waiting ' + data.wait_seconds + 's...</div>';
          await showFloodCountdown(data.wait_seconds);
        } else if (data.status === 'batch_pause') {
          log.innerHTML += '<div class="log-entry log-wait">PAUSE - Cooldown break, resuming in ' + data.wait_seconds + 's...</div>';
          await showFloodCountdown(data.wait_seconds);
        }
        log.scrollTop = log.scrollHeight;
      }
    }
  } catch(e) { console.error('Leave error:', e); }
}

async function showFloodCountdown(seconds) {
  var timer = document.getElementById('floodTimer');
  timer.classList.remove('hidden');
  for (var i = seconds; i > 0; i--) {
    timer.textContent = 'Rate limited - resuming in ' + i + 's';
    await new Promise(r => setTimeout(r, 1000));
  }
  timer.classList.add('hidden');
}

function showSummary(s, f) {
  document.getElementById('progressSection').classList.remove('active');
  document.getElementById('summaryCard').classList.remove('hidden');
  document.getElementById('summarySuccess').textContent = s;
  document.getElementById('summaryFail').textContent = f;
}
function closeSummary() {
  document.getElementById('summaryCard').classList.add('hidden');
  document.getElementById('leaveBtn').disabled = false;
}
async function logout() {
  if (!confirm('Are you sure you want to logout?')) return;
  try { await fetch(API + '/logout', {method: 'POST'}); } catch(e) {}
  location.reload();
}
function escapeHtml(t) { var d = document.createElement('div'); d.textContent = t; return d.innerHTML; }

document.getElementById('phoneInput').addEventListener('keydown', e => { if (e.key === 'Enter') sendCode(); });
document.getElementById('codeInput').addEventListener('keydown', e => { if (e.key === 'Enter') verifyCode(); });
document.getElementById('passwordInput').addEventListener('keydown', e => { if (e.key === 'Enter') verify2FA(); });
</script>
</body>
</html>'''


# ===================== ROUTES =====================

@app.route('/')
def index():
    return Response(HTML_PAGE, mimetype='text/html')


@app.route('/api/config-status', methods=['GET'])
def config_status():
    configured = load_config()
    return jsonify({'configured': configured})


@app.route('/api/save-config', methods=['POST'])
def save_config_route():
    try:
        data = request.json
        aid = data.get('api_id', '')
        ahash = data.get('api_hash', '')
        if not aid or not ahash:
            return jsonify({'success': False, 'error': 'Both fields required'}), 400
        save_config(aid, ahash)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/auth/status', methods=['GET'])
def auth_status():
    try:
        c = get_client()
        run_async(c.connect())
        authorized = run_async(c.is_user_authorized())
        if authorized:
            me = run_async(c.get_me())
            return jsonify({
                'authorized': True,
                'user': {
                    'first_name': me.first_name or '',
                    'last_name': me.last_name or '',
                    'phone': me.phone or '',
                    'username': me.username or ''
                }
            })
        return jsonify({'authorized': False})
    except Exception as e:
        return jsonify({'authorized': False, 'error': str(e)})


@app.route('/auth/send-code', methods=['POST'])
def send_code():
    global phone_hash
    try:
        data = request.json
        phone = data.get('phone', '')
        if not phone:
            return jsonify({'success': False, 'error': 'Phone number required'}), 400
        c = get_client()
        run_async(c.connect())
        result = run_async(c.send_code_request(phone))
        phone_hash = result.phone_code_hash
        return jsonify({'success': True, 'phone_hash': phone_hash})
    except errors.FloodWaitError as e:
        return jsonify({'success': False, 'error': f'Rate limited. Wait {e.seconds} seconds.'}), 429
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/auth/verify-code', methods=['POST'])
def verify_code():
    global phone_hash
    try:
        data = request.json
        phone = data.get('phone', '')
        code = data.get('code', '')
        password = data.get('password', None)
        c = get_client()
        try:
            run_async(c.sign_in(phone=phone, code=code, phone_code_hash=phone_hash))
        except errors.SessionPasswordNeededError:
            if password:
                run_async(c.sign_in(password=password))
            else:
                return jsonify({'success': False, 'needs_2fa': True, 'error': '2FA password required'}), 200
        me = run_async(c.get_me())
        return jsonify({
            'success': True,
            'user': {
                'first_name': me.first_name or '',
                'last_name': me.last_name or '',
                'phone': me.phone or '',
                'username': me.username or ''
            }
        })
    except errors.PhoneCodeInvalidError:
        return jsonify({'success': False, 'error': 'Invalid code. Please try again.'}), 400
    except errors.FloodWaitError as e:
        return jsonify({'success': False, 'error': f'Rate limited. Wait {e.seconds} seconds.'}), 429
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/groups', methods=['GET'])
def get_groups():
    try:
        c = get_client()

        async def fetch_groups():
            dialogs = await c.get_dialogs(limit=None)
            groups = []
            for d in dialogs:
                entity = d.entity
                if isinstance(entity, (ChatForbidden, ChannelForbidden)):
                    continue
                if isinstance(entity, Chat):
                    if entity.deactivated or entity.left:
                        continue
                    groups.append({
                        'id': entity.id,
                        'name': entity.title or 'Unknown',
                        'type': 'group',
                        'members': entity.participants_count or 0,
                        'muted': d.dialog.notify_settings.mute_until is not None if d.dialog and d.dialog.notify_settings else False,
                        'access_hash': '0'
                    })
                elif isinstance(entity, Channel):
                    if entity.left:
                        continue
                    ctype = 'channel' if entity.broadcast else 'supergroup'
                    groups.append({
                        'id': entity.id,
                        'name': entity.title or 'Unknown',
                        'type': ctype,
                        'members': entity.participants_count or 0,
                        'muted': d.dialog.notify_settings.mute_until is not None if d.dialog and d.dialog.notify_settings else False,
                        'access_hash': str(entity.access_hash or 0)
                    })
            return groups

        groups = run_async(fetch_groups())
        return jsonify({'success': True, 'groups': groups})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/leave', methods=['POST'])
def leave_groups():
    data = request.json
    groups_to_leave = data.get('groups', [])
    if not groups_to_leave:
        group_ids = data.get('group_ids', [])
        groups_to_leave = [{'id': gid, 'type': 'unknown'} for gid in group_ids]
    if not groups_to_leave:
        return jsonify({'success': False, 'error': 'No groups selected'}), 400

    def generate():
        c = get_client()
        total = len(groups_to_leave)
        success_count = 0
        fail_count = 0

        me = run_async(c.get_me())
        me_input = InputUser(user_id=me.id, access_hash=me.access_hash or 0)

        for i, group in enumerate(groups_to_leave):
            gid = group['id']
            gtype = group.get('type', 'unknown')
            access_hash = int(group.get('access_hash', '0'))

            async def leave_direct(gid_inner, gtype_inner, ahash):
                if gtype_inner in ('supergroup', 'channel'):
                    input_ch = InputChannel(channel_id=gid_inner, access_hash=ahash)
                    await c(LeaveChannelRequest(input_ch))
                elif gtype_inner == 'group':
                    await c(DeleteChatUserRequest(gid_inner, me_input))
                else:
                    entity = await c.get_entity(gid_inner)
                    if isinstance(entity, Channel):
                        await c(LeaveChannelRequest(InputChannel(entity.id, entity.access_hash)))
                    elif isinstance(entity, Chat):
                        await c(DeleteChatUserRequest(entity.id, me_input))

            left_ok = False
            max_retries = 5
            for attempt in range(max_retries):
                try:
                    run_async(leave_direct(gid, gtype, access_hash))
                    success_count += 1
                    left_ok = True
                    event_data = json.dumps({
                        'index': i + 1, 'total': total, 'group_id': gid,
                        'status': 'success', 'success_count': success_count, 'fail_count': fail_count
                    })
                    yield f"data: {event_data}\n\n"
                    break
                except errors.FloodWaitError as e:
                    wait_time = e.seconds + 10
                    event_data = json.dumps({
                        'index': i + 1, 'total': total, 'group_id': gid,
                        'status': 'flood_wait', 'wait_seconds': wait_time,
                        'success_count': success_count, 'fail_count': fail_count
                    })
                    yield f"data: {event_data}\n\n"
                    time.sleep(wait_time)
                except Exception as e:
                    if attempt < max_retries - 1:
                        time.sleep(5)
                        continue
                    break

            if not left_ok:
                fail_count += 1
                event_data = json.dumps({
                    'index': i + 1, 'total': total, 'group_id': gid,
                    'status': 'failed', 'error': 'Failed after retries',
                    'success_count': success_count, 'fail_count': fail_count
                })
                yield f"data: {event_data}\n\n"

            if i < total - 1:
                if (i + 1) % 5 == 0:
                    pause = random.uniform(55, 70)
                    event_data = json.dumps({
                        'index': i + 1, 'total': total, 'status': 'batch_pause',
                        'wait_seconds': int(pause), 'success_count': success_count, 'fail_count': fail_count
                    })
                    yield f"data: {event_data}\n\n"
                    time.sleep(pause)
                else:
                    time.sleep(random.uniform(10, 18))

        summary = json.dumps({
            'done': True, 'success_count': success_count,
            'fail_count': fail_count, 'total': total
        })
        yield f"data: {summary}\n\n"

    return Response(generate(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@app.route('/logout', methods=['POST'])
def logout():
    global client
    try:
        if client:
            run_async(client.log_out())
            client = None
        session_path = f'{SESSION_NAME}.session'
        if os.path.exists(session_path):
            os.remove(session_path)
        if os.path.exists(CONFIG_FILE):
            os.remove(CONFIG_FILE)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


if __name__ == '__main__':
    PORT = 8080
    print("\n=== Telegram Group Leaver ===")
    print(f"Opening http://localhost:{PORT} in your browser...\n")
    webbrowser.open(f'http://localhost:{PORT}')
    app.run(host='127.0.0.1', port=PORT, debug=False, threaded=True)
