import os
import asyncio
from pydantic import BaseModel
from fastapi import FastAPI, WebSocket, Depends, File, UploadFile, HTTPException, WebSocketDisconnect, Query, Request, BackgroundTasks, Form, Path
from fastapi.responses import RedirectResponse, Response, FileResponse
from starlette.websockets import WebSocketState
from fastapi.middleware.cors import CORSMiddleware
import logging
from tinydb import TinyDB, Query
from .interface import *
from dotenv import load_dotenv
import threading
import queue
import uuid
from skills import skills

# load env
# if os.path.exists('.env'):
#     load_dotenv('.env')

# set logging level
from GeneralAgent.utils import set_logging_level
set_logging_level(os.environ.get('LOG_LEVEL', 'ERROR'))


app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

db = TinyDB('./general_agent_db.json')
task_queue: queue.Queue = queue.Queue()
response_queue: queue.Queue = queue.Queue()


def sync_worker():
    asyncio.run(worker())

def get_chat_dir(bot_id, chat_id):
    data_dir = os.path.join(os.getcwd(), 'data', bot_id, chat_id)
    return data_dir

def history_to_messages(history):
    messages = []
    for item in history:
        message = Message(**item)
        role = {'user': 'user', 'bot': 'assistant'}.get(message.role, 'user')
        content = message.msg if len(message.msg) > 0 else message.file
        messages.append({'role': role, 'content': content})
    return messages

def try_create_chat_name(message:Message, chat_messages):
    from skills import skills
    chat = db.table('chats').get(Query().id == message.chat_id)
    chat = Chat(**chat)
    if chat.name == '' and len(chat_messages) > 0:
        content = chat_messages[0]['content']
        if len(content) < 10:
            title = content
        else:
            title = skills.extract_title(content)
        chat.name = title
        db.table('chats').update({'name': title}, Query().id == message.chat_id)

async def worker():
    while True:
        message:Message = await asyncio.to_thread(task_queue.get)
        logging.info('Worker get a message')
        chat_id = message.chat_id
        bot_id = message.bot_id
        msg_id = str(uuid.uuid4())
        result = ''
        async def _output_callback(token):
            nonlocal result
            nonlocal msg_id
            if token is not None:
                result += token
                response:Message = message.response_template(is_token=True)
                response.msg = token
                response.id = msg_id
                # await response_queue.put(response)
                await asyncio.to_thread(response_queue.put, response)
            else:
                response:Message = message.response_template()
                response.msg = result
                response.id = msg_id
                await save_message(response)
                await asyncio.to_thread(response_queue.put, response)
                # await response_queue.put(response)
                result = ''
                msg_id = str(uuid.uuid4())
                logging.info('sended message')

        async def _file_callback(file_path):
            file_path = skills.try_download_file(file_path)
            response:Message = message.response_template()
            response.file = file_path
            await save_message(response)
            await asyncio.to_thread(response_queue.put, response)
            logging.info('sended file')

        async def _ui_callback(name, js_path, data={}):
            response:Message = message.response_template()
            response.ui = json.dumps({
                'name': name,
                'js': js_path,
                'data': data
            })
            await save_message(response)
            await asyncio.to_thread(response_queue.put, response)
            logging.info('sended ui')
        
        # os.chdir(self.local_dir)
        current_workspace_dir = os.getcwd()
        code_path = os.path.join(os.path.dirname(__file__), f"./applications/{bot_id}/main.py")
        application = skills.load_application(code_path)
        db.table('mesasges').clear_cache()
        history = db.table('messages').search((Query().bot_id == bot_id) & (Query().chat_id == chat_id))[-20:]
        chat_messages = history_to_messages(history)

        try_create_chat_name(message, chat_messages)

        try:
            # data_dir = os.path.join(os.getcwd(), 'data', bot_id, chat_id)
            data_dir = get_chat_dir(bot_id, chat_id)
            if not os.path.exists(data_dir):
                os.makedirs(data_dir)
            os.chdir(data_dir)
            if application is not None:
                file = None if message.file == '' else message.file
                await application.main(chat_messages, message.msg, file, _output_callback, _file_callback, _ui_callback)
                if len(result) > 0:
                    response = message.response_template()
                    response.msg = result
                    response.id = msg_id
                    await save_message(response)
                    await asyncio.to_thread(response_queue.put, response)
            else:
                response = message.response_template()
                response.msg = 'application load error'
                await save_message(response)
                # await response_queue.put(response)
                await asyncio.to_thread(response_queue.put, response)
        except Exception as e:
            logging.exception(e)
            response = message.response_template()
            response.msg = str(e)
            await save_message(response)
            await asyncio.to_thread(response_queue.put, response)
        finally:
            os.chdir(current_workspace_dir)

        task_queue.task_done()

@app.on_event("startup")
async def startup_event():
    threading.Thread(target=sync_worker, daemon=True).start()

@app.on_event('shutdown')
async def shutdown_event():
    os._exit(0)


async def save_message(message:Message):
    if message.chat_id == '':
        chat = Chat(
            bot_id=message.bot_id,
        )
        db.table('chats').insert(chat.__dict__)
        message.chat_id = chat.id
    db.table('messages').insert(message.__dict__)


async def listen_message(websocket: WebSocket) -> None:
    while True:
        # message = await response_queue.get()
        message:Message = await asyncio.to_thread(response_queue.get)
        await websocket.send_text(message.to_text())
        response_queue.task_done()


@app.websocket("/ws/user/")
async def websocket_user_endpoint(websocket: WebSocket):
    await websocket.accept()
    listen_task = asyncio.create_task(listen_message(websocket))
    try:
        while True:
            data = await websocket.receive_text()
            if data == 'ping':
                await websocket.send_text('pong')
                continue
            else:
                data = json.loads(data)
                logging.info('Websocket get a message')
                if data['type'] == 'message':
                    message = Message(**data['data'])
                    message.role = 'user'
                    await save_message(message)
                    await websocket.send_text(message.to_text())
                    await asyncio.to_thread(task_queue.put, message)
                    # await task_queue.put(message)
    except Exception as e:
        if isinstance(e, WebSocketDisconnect):
            logging.info(f"websocket disconnect: {e}")
        else:
            logging.exception(e)
    finally:
        listen_task.cancel()
        if websocket.client_state != WebSocketState.DISCONNECTED:
            try:
                await websocket.close(code=4001)
            except:
                pass

@app.get("/bot/list")
async def bot_list():
    from skills import skills
    current_dir = os.path.abspath(os.path.dirname(__file__))
    APPLICATIONS_PATH = os.path.join(current_dir, 'applications')
    return skills.load_applications(APPLICATIONS_PATH)


@app.get("/chats/{bot_id}")
async def user_chat(bot_id: str):
    chats = db.table('chats').search(Query().bot_id == bot_id)
    # 当chats为空的时候，创建一个
    if len(chats) == 0:
        chat = Chat(
            bot_id=bot_id,
        )
        db.table('chats').insert(chat.__dict__)
        chats = db.table('chats').search(Query().bot_id == bot_id)
    # 倒序排列
    chats = chats[::-1]
    return chats

@app.get("/chats/new/{bot_id}")
async def user_chat_new(bot_id: str):
    chat = Chat(
        bot_id=bot_id,
    )
    db.table('chats').insert(chat.__dict__)
    chats = db.table('chats').search(Query().bot_id == bot_id)
    chats = chats[::-1]
    return chats


# 清空某个bot的消息
@app.post('/clear/{bot_id}')
async def clear_messages(bot_id: str):
    db.table('messages').remove(Query().bot_id == bot_id)
    db.table('chats').remove(Query().bot_id == bot_id)
    return 'ok'

# 获取某个bot下某轮chat的消息
class MessagesInput(BaseModel):
    bot_id: str
    chat_id: str
@app.post("/messages/")
async def user_messages(data:MessagesInput):
    bot_id = data.bot_id
    chat_id = data.chat_id
    db.table('mesasges').clear_cache()
    messages = db.table('messages').search((Query().bot_id == bot_id) & (Query().chat_id == chat_id))
    return messages

@app.get("/system/file/{path:path}")
async def get_file(path: str):
    if os.path.exists(path):
        return FileResponse(path)
    else:
        raise HTTPException(status_code=404, detail="File not found")


@app.get("/file/download/{bot_id}/{chat_id}/{file_name:path}")
async def download_file(bot_id: str, chat_id: str, file_name: str = Path(..., convert_underscores=False)):
    the_dir = get_chat_dir(bot_id, chat_id)
    file_path = os.path.join(the_dir, file_name)
    # print(file_path)
    if os.path.exists(file_path):
        return FileResponse(file_path)
    else:
        raise HTTPException(status_code=404, detail="File not found")


# 文件上传: /file/upload
@app.post("/file/upload")
async def upload_file(
    bot_id: str = Form(..., description="Bot ID"),
    chat_id: str = Form(..., description="Chat ID"),
    file: UploadFile = File(...)
    ):
    file_name = file.filename
    the_dir = get_chat_dir(bot_id, chat_id)
    if not os.path.exists(the_dir):
        os.makedirs(the_dir)
    file_path = os.path.join(the_dir, file_name)
    with open(file_path, 'wb') as f:
        f.write(file.file.read())
    return {'code': 0, "message": "File uploaded successfully", 'file': './'+file_name}