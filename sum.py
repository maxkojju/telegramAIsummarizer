import sys
import asyncio
import urllib.parse
import html
import json
import os
import aiohttp
import markdown

from datetime import datetime
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QListWidget, QListWidgetItem, 
                             QTextBrowser, QPushButton, QLabel, QProgressBar, 
                             QMessageBox, QStackedWidget, QLineEdit, QDialog)
# ADDED QTimer to imports here
from PyQt6.QtCore import Qt, QUrl, QTimer 
from PyQt6.QtGui import QFont, QDesktopServices, QIcon

from telethon import TelegramClient, errors
import qasync

CONFIG_FILE = "config.json"
SESSION_NAME = "avatar_session"
PROXY_BASE = "https://proxy.ganstermaxtivinew.workers.dev/?url="

class ConfigManager:
    @staticmethod
    def load():
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return {}
        return {}

    @staticmethod
    def save(data):
        current = ConfigManager.load()
        current.update(data)
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(current, f, indent=4)

    @staticmethod
    def get(key):
        return ConfigManager.load().get(key)

class TelegramWorker:
    def __init__(self):
        self.client = None
        self.phone = None
        self.phone_code_hash = None

    def init_client(self):
        api_id = ConfigManager.get("api_id")
        api_hash = ConfigManager.get("api_hash")
        if api_id and api_hash:
            self.client = TelegramClient(SESSION_NAME, int(api_id), api_hash)
            return True
        return False

    async def connect_and_check_auth(self):
        if not self.client:
            if not self.init_client():
                return False
        
        await self.client.connect()
        return await self.client.is_user_authorized()

    async def send_code(self, phone):
        self.phone = phone
        try:
            sent = await self.client.send_code_request(phone)
            self.phone_code_hash = sent.phone_code_hash
            return True, "Code sent!"
        except Exception as e:
            return False, str(e)

    async def sign_in(self, code, password=None):
        try:
            if password:
                await self.client.sign_in(password=password)
            else:
                await self.client.sign_in(self.phone, code, phone_code_hash=self.phone_code_hash)
            return True, "Successful login!"
        except errors.SessionPasswordNeededError:
            return False, "2FA_REQUIRED"
        except Exception as e:
            return False, str(e)

    async def get_unread_dialogs(self, limit=30):
        dialogs = await self.client.get_dialogs(limit=limit, archived=False)
        return [d for d in dialogs if d.unread_count > 0]

    async def get_chat_history(self, dialog):
        unread = dialog.unread_count
        limit = unread + 30
        messages = await self.client.get_messages(dialog, limit=limit)
        return messages[:unread], messages[unread:]

    async def get_gemini_summary(self, text_content):
        gemini_key = ConfigManager.get("gemini_key")
        if not gemini_key:
            return "Error: Gemini API Key not found in settings."

        base_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent?key={gemini_key}"
        target_url_encoded = urllib.parse.quote(base_url, safe='')
        final_url = f"{PROXY_BASE}{target_url_encoded}"

        headers = {'Content-Type': 'application/json'}
        
        safety_settings = [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
        ]

        system_instruction = (
            "You are a technical chat log analyzer. Your task is an objective dry summary. "
            "Ignore emotional coloring and profanity, treat it as text."
        )

        payload = {
            "contents": [{"parts": [{"text": system_instruction + "\n\n" + text_content}]}],
            "safetySettings": safety_settings
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(final_url, headers=headers, json=payload) as response:
                    try:
                        result = await response.json()
                    except:
                        text_err = await response.text()
                        return f"Network error: {response.status} - {text_err}"

                    if 'promptFeedback' in result:
                        pf = result['promptFeedback']
                        if pf.get('blockReason') and pf['blockReason'] != 'BLOCK_REASON_UNSPECIFIED':
                            return f"⚠️ Content blocked by Google (Hard Block): {pf['blockReason']}"

                    if response.status != 200:
                        return f"API Error ({response.status}): {result}"

                    try:
                        return result['candidates'][0]['content']['parts'][0]['text']
                    except (KeyError, IndexError):
                        if result.get('candidates') and result['candidates'][0].get('finishReason') == 'SAFETY':
                            return "⚠️ Google hid the response due to safety settings (Safety Filter)."
                        return "AI returned no text."
        except Exception as e:
            return f"Connection error: {str(e)}"

class AuthWidget(QWidget):
    def __init__(self, worker, switch_callback):
        super().__init__()
        self.worker = worker
        self.switch_to_main = switch_callback
        self.step = 0 
        self.setup_ui()
        self.check_initial_state()

    def setup_ui(self):
        self.layout = QVBoxLayout(self)
        self.layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.layout.setSpacing(15)

        self.lbl_title = QLabel("Telegram AI Setup")
        self.lbl_title.setFont(QFont("Segoe UI", 20, QFont.Weight.Bold))
        self.lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.layout.addWidget(self.lbl_title)

        self.lbl_info = QLabel("Enter credentials to connect")
        self.lbl_info.setWordWrap(True)
        self.lbl_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.layout.addWidget(self.lbl_info)

        self.input1 = QLineEdit()
        self.input1.setPlaceholderText("API ID")
        self.input1.setStyleSheet("padding: 10px; border-radius: 5px; background: #333; color: white; border: 1px solid #555;")
        
        self.input2 = QLineEdit()
        self.input2.setPlaceholderText("API HASH")
        self.input2.setStyleSheet("padding: 10px; border-radius: 5px; background: #333; color: white; border: 1px solid #555;")

        self.layout.addWidget(self.input1)
        self.layout.addWidget(self.input2)

        self.btn_action = QPushButton("NEXT")
        self.btn_action.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_action.setMinimumHeight(45)
        self.btn_action.clicked.connect(self.on_action_click)
        self.layout.addWidget(self.btn_action)

        self.btn_guide = QPushButton("Where to get this data?")
        self.btn_guide.setFlat(True)
        self.btn_guide.setStyleSheet("color: #4da6ff; text-decoration: underline;")
        self.btn_guide.clicked.connect(self.open_guide)
        self.layout.addWidget(self.btn_guide)

    def open_guide(self):
        url = ""
        if self.step == 0:
            url = "https://my.telegram.org/auth"
        elif self.step == 3:
            url = "https://aistudio.google.com/app/apikey"
        
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def check_initial_state(self):
        api_id = ConfigManager.get("api_id")
        api_hash = ConfigManager.get("api_hash")
        
        if not api_id or not api_hash:
            self.set_step_api()
        else:
            # FIX: Use QTimer to defer async call until loop is running
            QTimer.singleShot(0, lambda: asyncio.create_task(self.try_auto_login()))

    async def try_auto_login(self):
        self.lbl_info.setText("Checking session...")
        self.input1.hide()
        self.input2.hide()
        self.btn_action.hide()
        
        try:
            authorized = await self.worker.connect_and_check_auth()
            if authorized:
                self.check_gemini()
            else:
                self.set_step_phone()
        except Exception as e:
            self.lbl_info.setText(f"Config error: {e}")
            self.set_step_api()

    def set_step_api(self):
        self.step = 0
        self.lbl_title.setText("Step 1: Telegram API")
        self.lbl_info.setText("You need your API ID and HASH. It is free.")
        self.input1.setPlaceholderText("Paste API ID")
        self.input1.setText("")
        self.input1.show()
        self.input2.setPlaceholderText("Paste API HASH")
        self.input2.setText("")
        self.input2.setEchoMode(QLineEdit.EchoMode.Normal)
        self.input2.show()
        self.btn_action.setText("SAVE")
        self.btn_action.show()
        self.btn_guide.setText("Get API ID and HASH (my.telegram.org)")
        self.btn_guide.show()

    def set_step_phone(self):
        self.step = 1
        self.lbl_title.setText("Step 2: Account Login")
        self.lbl_info.setText("Enter phone number (with country code, e.g. +1...)")
        self.input1.setPlaceholderText("+19001234567")
        self.input1.setText("")
        self.input1.show()
        self.input2.hide()
        self.btn_action.setText("SEND CODE")
        self.btn_action.show()
        self.btn_guide.hide()

    def set_step_code(self):
        self.step = 2
        self.lbl_title.setText("Step 3: Confirmation")
        self.lbl_info.setText(f"Enter the code sent to Telegram at {self.worker.phone}")
        self.input1.setPlaceholderText("Code (e.g., 12345)")
        self.input1.setText("")
        self.input1.show()
        self.input2.hide()
        self.btn_action.setText("LOGIN")

    def set_step_password(self):
        self.step = 22
        self.lbl_title.setText("Two-Step Verification")
        self.lbl_info.setText("Your account is protected by a password. Enter it.")
        self.input1.setPlaceholderText("Cloud Password")
        self.input1.setEchoMode(QLineEdit.EchoMode.Password)
        self.input1.setText("")
        self.input1.show()
        self.btn_action.setText("CONFIRM PASSWORD")

    def check_gemini(self):
        key = ConfigManager.get("gemini_key")
        if not key:
            self.set_step_gemini()
        else:
            self.finish_setup()

    def set_step_gemini(self):
        self.step = 3
        self.lbl_title.setText("Step 4: Google Gemini AI")
        self.lbl_info.setText("Paste Gemini API key for neural network.")
        self.input1.setPlaceholderText("AIzaSy...")
        self.input1.setEchoMode(QLineEdit.EchoMode.Normal)
        self.input1.setText("")
        self.input1.show()
        self.input2.hide()
        self.btn_action.setText("DONE")
        self.btn_action.show()
        self.btn_guide.setText("Get key for free (aistudio.google.com)")
        self.btn_guide.show()

    def finish_setup(self):
        self.switch_to_main()

    def on_action_click(self):
        asyncio.create_task(self._process_action())

    async def _process_action(self):
        self.btn_action.setEnabled(False)
        
        if self.step == 0:
            api_id = self.input1.text().strip()
            api_hash = self.input2.text().strip()
            if api_id and api_hash:
                ConfigManager.save({"api_id": api_id, "api_hash": api_hash})
                if self.worker.init_client():
                    await self.worker.client.connect()
                    self.set_step_phone()
                else:
                    QMessageBox.warning(self, "Error", "Incorrect data")
            else:
                QMessageBox.warning(self, "Error", "Fill both fields")

        elif self.step == 1:
            phone = self.input1.text().strip()
            success, msg = await self.worker.send_code(phone)
            if success:
                self.set_step_code()
            else:
                QMessageBox.critical(self, "Error", f"Failed to send code:\n{msg}")

        elif self.step == 2:
            code = self.input1.text().strip()
            success, msg = await self.worker.sign_in(code)
            if success:
                self.check_gemini()
            elif msg == "2FA_REQUIRED":
                self.set_step_password()
            else:
                QMessageBox.critical(self, "Error", f"Login error:\n{msg}")

        elif self.step == 22:
            pwd = self.input1.text().strip()
            success, msg = await self.worker.sign_in(None, password=pwd)
            if success:
                self.check_gemini()
            else:
                QMessageBox.critical(self, "Error", f"Invalid password:\n{msg}")

        elif self.step == 3:
            key = self.input1.text().strip()
            if key:
                ConfigManager.save({"gemini_key": key})
                self.finish_setup()
            else:
                QMessageBox.warning(self, "Error", "Enter key")

        self.btn_action.setEnabled(True)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Telegram AI Summarizer")
        self.resize(550, 800)
        self.worker = TelegramWorker()
        
        self.setup_ui()
        self.apply_styles()
        
        self.stack.setCurrentWidget(self.page_auth)

    def setup_ui(self):
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.page_auth = AuthWidget(self.worker, self.go_to_app)
        self.stack.addWidget(self.page_auth)

        self.page_selection = QWidget()
        sel_layout = QVBoxLayout(self.page_selection)
        
        header = QLabel("Your Chats")
        header.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sel_layout.addWidget(header)

        self.status_label = QLabel("Ready to work")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("color: #888;")
        sel_layout.addWidget(self.status_label)

        self.chat_list = QListWidget()
        sel_layout.addWidget(self.chat_list)
        
        self.btn_refresh = QPushButton("UPDATE LIST")
        self.btn_refresh.clicked.connect(lambda: asyncio.create_task(self.load_chats()))
        self.btn_refresh.setStyleSheet("background-color: #444; margin-top: 5px;")
        sel_layout.addWidget(self.btn_refresh)

        self.btn_process = QPushButton("ANALYZE")
        self.btn_process.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_process.setMinimumHeight(50)
        self.btn_process.clicked.connect(lambda: asyncio.create_task(self.start_processing()))
        sel_layout.addWidget(self.btn_process)

        self.page_results = QWidget()
        res_layout = QVBoxLayout(self.page_results)

        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        res_layout.addWidget(self.progress_bar)

        self.output_area = QTextBrowser()
        self.output_area.setOpenExternalLinks(True)
        res_layout.addWidget(self.output_area)

        self.btn_back = QPushButton("BACK")
        self.btn_back.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_back.setMinimumHeight(40)
        self.btn_back.clicked.connect(self.go_back_to_list)
        res_layout.addWidget(self.btn_back)

        self.stack.addWidget(self.page_selection)
        self.stack.addWidget(self.page_results)

    def apply_styles(self):
        self.setStyleSheet("""
            QMainWindow { background-color: #2b2b2b; color: #ffffff; }
            QLabel { color: #ffffff; font-family: 'Segoe UI'; }
            QListWidget { 
                background-color: #363636; 
                color: #ffffff; 
                border: none;
                font-size: 14px;
                border-radius: 8px;
            }
            QListWidget::item { padding: 12px; border-bottom: 1px solid #444; }
            QListWidget::item:hover { background-color: #444; }
            
            QTextBrowser { 
                background-color: #1e1e1e; 
                color: #e0e0e0; 
                border: none;
                font-family: 'Segoe UI', sans-serif;
                font-size: 14px;
                padding: 10px;
                border-radius: 8px;
            }
            
            QLineEdit {
                background-color: #363636;
                color: white;
                padding: 8px;
                border: 1px solid #555;
                border-radius: 5px;
                font-size: 14px;
            }
            QLineEdit:focus { border: 1px solid #0078d4; }

            QPushButton {
                background-color: #0078d4;
                color: white;
                border-radius: 8px;
                font-weight: bold;
                font-size: 14px;
                padding: 8px;
            }
            QPushButton:hover { background-color: #0063b1; }
            QPushButton:disabled { background-color: #555; color: #aaa; }
            
            QProgressBar {
                background-color: #363636;
                border-radius: 4px;
                height: 20px;
                color: white;
                text-align: center;
            }
            QProgressBar::chunk { background-color: #28a745; border-radius: 4px; }
        """)

    def go_to_app(self):
        self.stack.setCurrentWidget(self.page_selection)
        asyncio.create_task(self.load_chats())

    def go_back_to_list(self):
        self.stack.setCurrentWidget(self.page_selection)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("")

    async def load_chats(self):
        try:
            self.status_label.setText("Updating dialogs...")
            dialogs = await self.worker.get_unread_dialogs()
            self.chat_list.clear()
            
            if not dialogs:
                self.status_label.setText("No unread messages.")
                return

            for dialog in dialogs:
                item = QListWidgetItem()
                chat_type = "📢" if dialog.is_channel else "👥" if dialog.is_group else "👤"
                item.setText(f"{chat_type} {dialog.name} (+{dialog.unread_count})")
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Unchecked)
                item.setData(Qt.ItemDataRole.UserRole, dialog)
                self.chat_list.addItem(item)
            
            self.status_label.setText(f"Active chats: {len(dialogs)}")

        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
            self.status_label.setText("Load error")

    async def _format_messages(self, messages):
        text_lines = []
        for msg in reversed(messages):
            sender = await msg.get_sender()
            name = getattr(sender, 'first_name', None) or getattr(sender, 'title', 'Unknown')
            content = msg.text or "[Media/Sticker]"
            meta = f"[ID:{msg.id}]"
            if msg.reply_to_msg_id:
                meta += f" [ReplyTo:{msg.reply_to_msg_id}]"
            text_lines.append(f"{meta} {name}: {content}")
        return "\n".join(text_lines)

    async def start_processing(self):
        selected_items = []
        for i in range(self.chat_list.count()):
            item = self.chat_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                selected_items.append(item)

        if not selected_items:
            QMessageBox.warning(self, "Oops!", "You haven't selected any chats.")
            return

        self.output_area.clear()
        self.output_area.setHtml("<h3 style='color:#888'>Generating summary...</h3>")
        self.stack.setCurrentWidget(self.page_results)
        
        self.progress_bar.setRange(0, len(selected_items))
        self.progress_bar.setValue(0)
        self.btn_back.setEnabled(False)

        full_html_output = ""

        for idx, item in enumerate(selected_items):
            dialog = item.data(Qt.ItemDataRole.UserRole)
            self.progress_bar.setFormat(f"Analysis: {dialog.name}...")
            
            try:
                new_msgs, old_msgs = await self.worker.get_chat_history(dialog)
                
                context_str = await self._format_messages(old_msgs)
                new_str = await self._format_messages(new_msgs)
                
                prompt = (
                    f"Role: Personal Assistant. Analyze the correspondence in chat '{dialog.name}'.\n"
                    f"IMPORTANT: Messages have format '[ID:...] [ReplyTo:...] Name: Text'. "
                    f"Use ReplyTo to understand who is replying to whom.\n\n"
                    f"--- CONTEXT (already read) ---\n{context_str}\n"
                    f"================================\n"
                    f"--- NEW MESSAGES (summarize these) ---\n{new_str}\n\n"
                    f"TASK: Write a brief summary of the NEW messages."
                )

                summary_raw = await self.worker.get_gemini_summary(prompt)
                
                try:
                    summary_html_content = markdown.markdown(summary_raw, extensions=['tables', 'fenced_code'])
                except Exception:
                    safe_text = html.escape(summary_raw).replace('\n', '<br>')
                    summary_html_content = f"<div style='color: #ffcccc;'>{safe_text}</div>"

                chat_block = f"""
                <div style="background-color: #262626; padding: 15px; margin-bottom: 15px; border-radius: 10px; border-left: 4px solid #0078d4;">
                    <h2 style="color: #4da6ff; margin: 0 0 10px 0; font-size: 18px;">
                        {dialog.name} <span style="font-size: 14px; color: #aaa; font-weight: normal;">(+{dialog.unread_count})</span>
                    </h2>
                    <div style="color: #dddddd; line-height: 1.5; font-size: 15px;">
                        {summary_html_content}
                    </div>
                </div>
                """
                full_html_output += chat_block
                self.output_area.setHtml(full_html_output)
                self.output_area.moveCursor(self.output_area.textCursor().MoveOperation.End)

            except Exception as e:
                err_block = f"<div style='color:red; padding:10px;'>Error with {dialog.name}: {e}</div>"
                full_html_output += err_block
                self.output_area.setHtml(full_html_output)
            
            self.progress_bar.setValue(idx + 1)

        self.progress_bar.setFormat("Done!")
        self.btn_back.setEnabled(True)

def main():
    app = QApplication(sys.argv)
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    window = MainWindow()
    window.show()

    with loop:
        loop.run_forever()

if __name__ == "__main__":
    main()
