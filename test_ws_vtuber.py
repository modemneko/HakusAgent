import asyncio
import websockets
import json

async def test():
    uri = 'ws://127.0.0.1:8081/ws/virtual-avatar/test_session'
    try:
        async with websockets.connect(uri) as ws:
            print('WebSocket connected!')
            msg = await ws.recv()
            data = json.loads(msg)
            print(f'Server: {data["type"]} - {data.get("message", "")}')

            await ws.send(json.dumps({'type': 'text', 'content': '你好'}))
            print('Sent: 你好')

            for i in range(15):
                msg = await asyncio.wait_for(ws.recv(), timeout=120)
                data = json.loads(msg)
                msg_type = data.get('type', '')
                
                if msg_type == 'tts_start':
                    print('[TTS] Start')
                elif msg_type == 'tts_audio':
                    audio_len = len(data.get('audio', ''))
                    print(f'[TTS] Audio: {audio_len} chars base64, format={data.get("format")}')
                    has_text = bool(data.get('text'))
                    print(f'[TTS] Has text: {has_text}')
                elif msg_type == 'response':
                    text = data.get('text', '')[:100]
                    print(f'[Response] {text}...')
                elif msg_type == 'tts_end':
                    print('[TTS] End')
                    break
                elif msg_type == 'error':
                    print(f'[Error] {data.get("message", "")}')
                    break
                else:
                    print(f'[{msg_type}] {str(data)[:120]}')
    except Exception as e:
        print(f'Error: {type(e).__name__}: {e}')

asyncio.run(test())
