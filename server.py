import asyncio
import json
import time
import os
import random
import threading
from flask import Flask, request, jsonify, Response, send_from_directory
from flask_cors import CORS
from telethon import TelegramClient, errors
from telethon.tl.functions.channels import LeaveChannelRequest
from telethon.tl.functions.messages import DeleteChatUserRequest
from telethon.tl.types import (
    Chat, Channel, ChatForbidden, ChannelForbidden,
    InputChannel, InputUser
)

app = Flask(__name__, static_folder='static')
CORS(app)

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')
SESSION_NAME = 'telegram_session'

api_id = None
api_hash = None
client = None
loop = None
phone_hash = None


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


@app.route('/')
def index():
    return send_from_directory('static', 'index.html')


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
                return jsonify({
                    'success': False,
                    'needs_2fa': True,
                    'error': '2FA password required'
                }), 200

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
    groups_to_leave = data.get('groups', [])  # [{id, type}, ...]

    # Backwards compat: if old format with just IDs
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

        # Cache get_me() once — no repeated API calls
        me = run_async(c.get_me())
        me_input = InputUser(user_id=me.id, access_hash=me.access_hash or 0)

        for i, group in enumerate(groups_to_leave):
            gid = group['id']
            gtype = group.get('type', 'unknown')
            access_hash = int(group.get('access_hash', '0'))

            async def leave_direct(gid_inner, gtype_inner, ahash):
                # Build InputChannel directly from stored data — NO API calls needed
                if gtype_inner in ('supergroup', 'channel'):
                    input_ch = InputChannel(channel_id=gid_inner, access_hash=ahash)
                    await c(LeaveChannelRequest(input_ch))
                elif gtype_inner == 'group':
                    await c(DeleteChatUserRequest(gid_inner, me_input))
                else:
                    # Fallback only for unknown types
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
                        'index': i + 1,
                        'total': total,
                        'group_id': gid,
                        'status': 'success',
                        'success_count': success_count,
                        'fail_count': fail_count
                    })
                    yield f"data: {event_data}\n\n"
                    break  # success, move on

                except errors.FloodWaitError as e:
                    wait_time = e.seconds + 10  # wait extra 10s buffer
                    event_data = json.dumps({
                        'index': i + 1,
                        'total': total,
                        'group_id': gid,
                        'status': 'flood_wait',
                        'wait_seconds': wait_time,
                        'success_count': success_count,
                        'fail_count': fail_count
                    })
                    yield f"data: {event_data}\n\n"
                    time.sleep(wait_time)
                    # Loop will retry on next attempt

                except Exception as e:
                    if attempt < max_retries - 1:
                        time.sleep(5)
                        continue
                    break  # exhausted retries

            if not left_ok:
                fail_count += 1
                event_data = json.dumps({
                    'index': i + 1,
                    'total': total,
                    'group_id': gid,
                    'status': 'failed',
                    'error': 'Failed after retries',
                    'success_count': success_count,
                    'fail_count': fail_count
                })
                yield f"data: {event_data}\n\n"

            if i < total - 1:
                # Every 5 groups, take a long 60s break to avoid rate limits
                if (i + 1) % 5 == 0:
                    pause = random.uniform(55, 70)
                    event_data = json.dumps({
                        'index': i + 1,
                        'total': total,
                        'status': 'batch_pause',
                        'wait_seconds': int(pause),
                        'success_count': success_count,
                        'fail_count': fail_count
                    })
                    yield f"data: {event_data}\n\n"
                    time.sleep(pause)
                else:
                    time.sleep(random.uniform(10, 18))

        summary = json.dumps({
            'done': True,
            'success_count': success_count,
            'fail_count': fail_count,
            'total': total
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
        if os.path.exists(f'{SESSION_NAME}.session'):
            os.remove(f'{SESSION_NAME}.session')
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


if __name__ == '__main__':
    load_config()
    print("\n=== Telegram Group Leaver ===")
    print("Open http://localhost:8080 in your browser\n")
    app.run(host='127.0.0.1', port=8080, debug=False, threaded=True)
