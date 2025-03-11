from flask import Flask, request, jsonify, render_template_string, session
import requests
import os
import uuid
import sqlite3
from datetime import datetime
import subprocess
import shlex
import re

app = Flask(__name__)
app.secret_key = "your-secret-key"  # Replace with a strong secret key

# Base endpoints for Venice API
TEXT_ENDPOINT = "https://api.venice.ai/api/v1/chat/completions"
IMAGE_ENDPOINT = "https://api.venice.ai/api/v1/image/generate"

# Database path for conversation memory
DB_PATH = "conversation.db"

# Initialize SQLite database for conversation history
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT,
        role TEXT,
        content TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.commit()
    conn.close()

init_db()

# Database functions for memory management
def save_message(session_id, role, content):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
              (str(session_id), role, content))
    conn.commit()
    conn.close()

def get_recent_history(session_id, limit=10):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT role, content FROM messages WHERE session_id=? ORDER BY id DESC LIMIT ?",
              (str(session_id), limit))
    rows = c.fetchall()
    conn.close()
    rows.reverse()  # Reverse to chronological order
    return [{"role": row[0], "content": row[1]} for row in rows]

# Token estimation and summarization
TOKEN_THRESHOLD = 1000  # Rough word count threshold for summarization

def estimate_tokens(messages):
    total = 0
    for msg in messages:
        total += len(msg["content"].split())
    return total

def summarize_history(messages, api_key, model, top_p, max_tokens, presence_penalty, frequency_penalty):
    conversation_text = "\n".join([f"{msg['role']}: {msg['content']}" for msg in messages])
    summarization_prompt = f"Summarize the following conversation concisely:\n{conversation_text}"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a summarization assistant."},
            {"role": "user", "content": summarization_prompt}
        ],
        "temperature": 0.5,
        "top_p": top_p,
        "max_tokens": 300,
        "presence_penalty": presence_penalty,
        "frequency_penalty": frequency_penalty
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    else:
        default_key = os.getenv("VENICE_API_KEY")
        if default_key:
            headers["Authorization"] = f"Bearer {default_key}"
    try:
        response = requests.post(TEXT_ENDPOINT, json=payload, headers=headers)
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"].strip()
        else:
            return "Summary unavailable due to an API error."
    except Exception as e:
        return "Summary unavailable due to an exception."

# Function to run terminal commands securely
def run_terminal_command(command, approved=False):
    allowed_commands = ['ls', 'pwd', 'whoami', 'echo']
    parts = shlex.split(command)
    if parts and (parts[0] in allowed_commands or approved):
        try:
            result = subprocess.run(parts, capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                return result.stdout.strip()
            else:
                return f"Error: {result.stderr.strip()}"
        except Exception as e:
            return f"Execution error: {str(e)}"
    else:
        return "Command not allowed."

# New endpoint to generate subtasks
@app.route("/generate_subtasks", methods=["POST"])
def generate_subtasks():
    data = request.json
    task = data.get("task", "")
    model = data.get("model", "deepseek-r1-671b")
    temperature = data.get("temperature", 0.7)
    top_p = data.get("top_p", 0.9)
    max_tokens = data.get("max_tokens", 7000)
    presence_penalty = data.get("presence_penalty", 1)
    frequency_penalty = data.get("frequency_penalty", 0.9)
    api_key = data.get("api_key", "")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    else:
        default_key = os.getenv("VENICE_API_KEY")
        if default_key:
            headers["Authorization"] = f"Bearer {default_key}"
    
    decomposition_prompt = (
        f"Decompose the following task into a list of subtasks. "
        f"Each subtask should be on a new line and start with 'TEXT: ' for text generation tasks or 'COMMAND: ' for commands to execute.\n"
        f"Task: {task}"
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are an expert at breaking down tasks into clear subtasks."},
            {"role": "user", "content": decomposition_prompt}
        ],
        "temperature": temperature,
        "top_p": top_p,
        "max_tokens": max_tokens,
        "presence_penalty": presence_penalty,
        "frequency_penalty": frequency_penalty
    }
    try:
        response = requests.post(TEXT_ENDPOINT, json=payload, headers=headers)
        if response.status_code == 200:
            decomposition = response.json()["choices"][0]["message"]["content"].strip()
            subtasks = []
            for line in decomposition.split('\n'):
                line = line.strip()
                if line.startswith("TEXT:"):
                    subtasks.append({"type": "text", "content": line[5:].strip()})
                elif line.startswith("COMMAND:"):
                    subtasks.append({"type": "command", "content": line[8:].strip()})
            return jsonify({"subtasks": subtasks})
        else:
            return jsonify({"error": f"API error: {response.text}"}), 500
    except Exception as e:
        return jsonify({"error": f"Exception: {str(e)}"}), 500

# New endpoint to check task completion
@app.route("/check_completion", methods=["POST"])
def check_completion():
    data = request.json
    task = data.get("task", "")
    results = data.get("results", [])
    answer = data.get("answer", "")
    model = data.get("model", "deepseek-r1-671b")
    temperature = data.get("temperature", 0.7)
    top_p = data.get("top_p", 0.9)
    max_tokens = data.get("max_tokens", 7000)
    presence_penalty = data.get("presence_penalty", 1)
    frequency_penalty = data.get("frequency_penalty", 0.9)
    api_key = data.get("api_key", "")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    else:
        default_key = os.getenv("VENICE_API_KEY")
        if default_key:
            headers["Authorization"] = f"Bearer {default_key}"
    
    results_str = "\n".join([f"Subtask: {res['subtask']}\nResult: {res['result']}" for res in results])
    check_prompt = (
        f"Based on the following task and the results of the subtasks, determine if the task is complete.\n"
        f"If it is, respond with 'COMPLETE'.\n"
        f"If more subtasks are needed, respond with 'MORE_SUBTASKS: ' followed by the new subtasks, each on a new line starting with 'TEXT: ' or 'COMMAND: '.\n"
        f"If you need clarification from the user, respond with 'QUESTION: ' followed by the question.\n"
        f"Task: {task}\n"
        f"Subtask results:\n{results_str}"
    )
    if answer:
        check_prompt += f"\nUser's answer to the previous question: {answer}"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are an assistant that checks task completion and manages workflow."},
            {"role": "user", "content": check_prompt}
        ],
        "temperature": temperature,
        "top_p": top_p,
        "max_tokens": max_tokens,
        "presence_penalty": presence_penalty,
        "frequency_penalty": frequency_penalty
    }
    try:
        response = requests.post(TEXT_ENDPOINT, json=payload, headers=headers)
        if response.status_code == 200:
            check_result = response.json()["choices"][0]["message"]["content"].strip()
            check_result = check_result.strip()  # Normalize response
            if check_result.upper().startswith("COMPLETE"):
                return jsonify({"complete": True})
            elif check_result.upper().startswith("MORE_SUBTASKS:"):
                more_subtasks_text = check_result[len("MORE_SUBTASKS:"):].strip()
                subtasks = []
                for line in more_subtasks_text.split('\n'):
                    line = line.strip()
                    if line.startswith("TEXT:"):
                        subtasks.append({"type": "text", "content": line[5:].strip()})
                    elif line.startswith("COMMAND:"):
                        subtasks.append({"type": "command", "content": line[8:].strip()})
                return jsonify({"subtasks": subtasks})
            elif check_result.upper().startswith("QUESTION:"):
                question = check_result[len("QUESTION:"):].strip()
                return jsonify({"question": question})
            else:
                app.logger.error(f"Invalid response from API: {check_result}")
                return jsonify({"error": "Invalid response from API"}), 500
        else:
            return jsonify({"error": f"API error: {response.text}"}), 500
    except Exception as e:
        return jsonify({"error": f"Exception: {str(e)}"}), 500

# New endpoint to save messages
@app.route("/save_message", methods=["POST"])
def save_message_route():
    data = request.json
    session_id = session.get("session_id")
    role = data.get("role", "user")
    content = data.get("content", "")
    save_message(session_id, role, content)
    return jsonify({"success": True})

@app.route("/")
def index():
    if "session_id" not in session:
        session["session_id"] = str(uuid.uuid4())
    return render_template_string(INDEX_HTML)

@app.route("/chat", methods=["POST"])
def chat():
    data = request.json
    mode = data.get("mode", "text")
    api_key = data.get("api_key", "")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    else:
        default_key = os.getenv("VENICE_API_KEY")
        if default_key:
            headers["Authorization"] = f"Bearer {default_key}"
    
    session_id = session.get("session_id")
    if not session_id:
        session["session_id"] = str(uuid.uuid4())
        session_id = session["session_id"]
    
    if mode == "text":
        message = data.get("message", "")
        system_prompt = data.get("system_prompt", "You are a helpful assistant.")
        model = data.get("model", "llama-3.3-70b")
        temperature = data.get("temperature", 0.7)
        top_p = data.get("top_p", 0.9)
        max_tokens = data.get("max_tokens", 7000)
        presence_penalty = data.get("presence_penalty", 1)
        frequency_penalty = data.get("frequency_penalty", 0.9)
        venice_params = data.get("venice_params", "")
        if venice_params:
            model += ":" + venice_params
        save_message(session_id, "user", message)
        history = get_recent_history(session_id)
        messages = [{"role": "system", "content": system_prompt}] + history + [{"role": "user", "content": message}]
        if estimate_tokens(messages) > TOKEN_THRESHOLD and len(history) > 1:
            summary = summarize_history(history, api_key, model, top_p, max_tokens, presence_penalty, frequency_penalty)
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "assistant", "content": "Summary of previous conversation: " + summary},
                {"role": "user", "content": message}
            ]
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "top_p": top_p,
            "max_tokens": max_tokens,
            "presence_penalty": presence_penalty,
            "frequency_penalty": frequency_penalty
        }
        try:
            response = requests.post(TEXT_ENDPOINT, json=payload, headers=headers)
            if response.status_code == 200:
                reply = response.json()["choices"][0]["message"]["content"].strip()
            else:
                reply = f"Error {response.status_code}: {response.text}"
        except Exception as e:
            reply = f"Exception occurred: {str(e)}"
        save_message(session_id, "assistant", reply)
        return jsonify({"reply": reply})
    
    elif mode == "image":
        prompt = data.get("prompt", data.get("message", ""))
        model = data.get("model", "fluently-xl")
        height = data.get("image_height", 1024)
        width = data.get("image_width", 1024)
        steps = data.get("steps", 20)
        hide_watermark = data.get("hide_watermark", False)
        embed_exif = data.get("embed_exif_metadata", False)
        negative_prompt = data.get("negative_prompt", "")
        cfg_scale = data.get("cfg_scale", 7.5)
        lora_strength = data.get("lora_strength", 50)
        payload = {
            "model": model,
            "prompt": prompt,
            "height": height,
            "width": width,
            "steps": steps,
            "return_binary": False,
            "hide_watermark": hide_watermark,
            "format": data.get("format", "png"),
            "safe_mode": False,
            "embed_exif_metadata": embed_exif,
            "negative_prompt": negative_prompt,
            "cfg_scale": cfg_scale,
            "lora_strength": lora_strength
        }
        seed_value = data.get("seed", "")
        if seed_value.strip() != "":
            payload["seed"] = int(seed_value)
        if "inpaint" in data:
            payload["inpaint"] = data["inpaint"]
        try:
            response = requests.post(IMAGE_ENDPOINT, json=payload, headers=headers)
            if response.status_code == 200:
                response_data = response.json()
                image_data = response_data.get("image") or response_data.get("images")
                if isinstance(image_data, list):
                    image_data = image_data[0].strip()
                if image_data:
                    fmt = payload.get("format", "png").lower()
                    mime_map = {"png": "image/png", "webp": "image/webp", "jpg": "image/jpeg"}
                    mime = mime_map.get(fmt, "image/png")
                    image_url = "data:" + mime + ";base64," + image_data
                else:
                    error_message = response_data.get("error", "No image data returned")
                    image_url = f"Error: {error_message}"
                return jsonify({"image_url": image_url})
            else:
                return jsonify({"image_url": f"Error {response.status_code}: {response.text}"})
        except Exception as e:
            return jsonify({"image_url": f"Exception occurred: {str(e)}"})
    
    elif mode == "agent":
        # Simplified agent mode: now primarily for compatibility or direct text generation
        message = data.get("message", "")
        model = data.get("model", "deepseek-r1-671b")
        temperature = data.get("temperature", 0.7)
        top_p = data.get("top_p", 0.9)
        max_tokens = data.get("max_tokens", 7000)
        presence_penalty = data.get("presence_penalty", 1)
        frequency_penalty = data.get("frequency_penalty", 0.9)
        auto_execute = data.get("auto_execute", False)
        save_message(session_id, "user", message)
        reply = process_agent_task(message, api_key, model, temperature, top_p, max_tokens, presence_penalty, frequency_penalty, auto_execute)
        save_message(session_id, "assistant", reply)
        return jsonify({"reply": reply})
    
    else:
        return jsonify({"reply": "Invalid mode specified."})

# Agent workflow (unchanged for compatibility)
def process_agent_task(task, api_key, model, temperature, top_p, max_tokens, presence_penalty, frequency_penalty, auto_execute):
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    else:
        default_key = os.getenv("VENICE_API_KEY")
        if default_key:
            headers["Authorization"] = f"Bearer {default_key}"
    
    decomposition_prompt = (
        f"Decompose the following high-level task into a numbered list of actionable subtasks:\n"
        f"Task: {task}\n"
        f"Provide one subtask per line in the format 'N. subtask description'"
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are an expert at breaking down tasks into clear subtasks."},
            {"role": "user", "content": decomposition_prompt}
        ],
        "temperature": temperature,
        "top_p": top_p,
        "max_tokens": max_tokens,
        "presence_penalty": presence_penalty,
        "frequency_penalty": frequency_penalty
    }
    try:
        response = requests.post(TEXT_ENDPOINT, json=payload, headers=headers)
        if response.status_code == 200:
            decomposition = response.json()["choices"][0]["message"]["content"].strip()
        else:
            return f"Error decomposing task: {response.text}"
    except Exception as e:
        return f"Exception during task decomposition: {str(e)}"
    
    subtasks = re.findall(r'\d+\.\s*(.+)', decomposition)
    if not subtasks:
        subtasks = [decomposition]
    
    results = []
    for subtask in subtasks:
        subtask = subtask.strip()
        if subtask.upper().startswith("RUN COMMAND:"):
            command = subtask[len("RUN COMMAND:"):].strip()
            if auto_execute:
                result = run_terminal_command(command)
            else:
                result = f"Auto-execution disabled. Command '{command}' not run."
            results.append({"subtask": subtask, "result": result})
        else:
            sub_payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": "You are now executing a subtask as part of a larger agent workflow."},
                    {"role": "user", "content": subtask}
                ],
                "temperature": temperature,
                "top_p": top_p,
                "max_tokens": max_tokens,
                "presence_penalty": presence_penalty,
                "frequency_penalty": frequency_penalty
            }
            try:
                sub_resp = requests.post(TEXT_ENDPOINT, json=sub_payload, headers=headers)
                if sub_resp.status_code == 200:
                    sub_result = sub_resp.json()["choices"][0]["message"]["content"].strip()
                else:
                    sub_result = f"Error: {sub_resp.text}"
            except Exception as e:
                sub_result = f"Exception: {str(e)}"
            results.append({"subtask": subtask, "result": sub_result})
    
    reply = "Agent Task Decomposition and Execution Results:\n\n"
    reply += "Subtasks:\n" + "\n".join([f"- {s}" for s in subtasks]) + "\n\n"
    for idx, res in enumerate(results, 1):
        reply += f"Result for subtask {idx}:\n{res['result']}\n\n"
    return reply

@app.route("/execute", methods=["POST"])
def execute_command():
    data = request.json
    command = data.get("command", "")
    approved = data.get("approved", False)
    output = run_terminal_command(command, approved)
    return jsonify({'output': output})

@app.route("/new_chat", methods=["POST"])
def new_chat():
    data = request.json
    keep_history = data.get("keep_history", False)
    session_id = session.get("session_id")
    if not keep_history and session_id:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
        conn.commit()
        conn.close()
    return jsonify({"success": True})

INDEX_HTML = '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Venice Chat App</title>
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
    <style>
        html, body {
            margin: 0; padding: 0;
            height: 100%; width: 100%;
            font-family: Arial, sans-serif;
        }
        body.dark-mode {
            background-color: #2c2c2c;
            color: #ccc;
        }
        body.light-mode {
            background-color: #f7f7f7;
            color: #000;
        }
        .container {
            width: 100%; height: 100%;
            display: flex; flex-direction: column;
            align-items: center;
            box-sizing: border-box;
            padding: 10px;
        }
        h1 { text-align: center; }
        .chat-container {
            width: 100%; max-width: 800px;
            flex: 1;
            border: 1px solid #444;
            border-radius: 8px;
            background: inherit;
            padding: 20px;
            overflow-y: auto;
            display: flex;
            flex-direction: column;
            gap: 10px;
        }
        body.light-mode .message.user {
            align-self: flex-end;
            background-color: #dcf8c6;
            color: #000;
            border: 1px solid #aaa;
        }
        body.light-mode .message.assistant {
            align-self: flex-start;
            background-color: #fff;
            color: #000;
            border: 1px solid #aaa;
        }
        body.dark-mode .message.user {
            align-self: flex-end;
            background-color: #0056b3;
            color: #fff;
            border: 1px solid #007bff;
        }
        body.dark-mode .message.assistant {
            align-self: flex-start;
            background-color: #444;
            color: #fff;
            border: 1px solid #666;
        }
        .message {
            max-width: 70%;
            padding: 10px 15px;
            border-radius: 15px;
            line-height: 1.5;
            word-wrap: break-word;
        }
        .input-container {
            width: 100%; max-width: 800px;
            display: flex; margin-top: 20px;
        }
        .input-container input {
            flex: 1; padding: 10px;
            border-radius: 4px; border: 1px solid #777;
        }
        .input-container button {
            padding: 10px 20px; margin-left: 10px;
            border: none; background: #007bff; color: #fff;
            border-radius: 4px; cursor: pointer;
        }
        .mode-buttons {
            margin-top: 10px;
            display: flex;
            justify-content: center;
            gap: 20px;
        }
        .mode-buttons button {
            padding: 10px 20px;
            border: none;
            background: #28a745;
            color: #fff;
            border-radius: 4px;
            cursor: pointer;
        }
        .settings {
            width: 100%; max-width: 800px;
            margin-top: 20px;
            border: 1px solid #444; border-radius: 8px;
            background: inherit; padding: 10px;
            display: none;
            text-align: left;
        }
        .settings label { font-weight: bold; }
        .settings input, .settings select, .settings textarea {
            width: 100%; padding: 5px; margin: 5px 0 10px 0;
            border: 1px solid #777; border-radius: 4px;
            background: inherit; color: inherit;
        }
        .toggle-settings {
            margin-top: 10px;
            cursor: pointer;
            color: #007bff; text-decoration: underline;
        }
        .mode-settings { display: none; }
        .blinking-cursor {
            font-weight: 100;
            font-size: 1em;
            color: #ccc;
            -webkit-animation: 1s blink step-end infinite;
            animation: 1s blink step-end infinite;
        }
        @keyframes blink {
            from, to { border-right-color: transparent; }
            50% { border-right-color: #ccc; }
        }
        @-webkit-keyframes blink {
            from, to { border-right-color: transparent; }
            50% { border-right-color: #ccc; }
        }
        pre {
            background-color: #333;
            color: #eee;
            padding: 10px;
            border-radius: 4px;
            position: relative;
            overflow-x: auto;
        }
        code {
            font-family: Consolas, "Courier New", monospace;
        }
        .copy-button {
            position: absolute;
            top: 5px; right: 5px;
            padding: 2px 6px;
            font-size: 0.8em;
            cursor: pointer;
            background: #007bff;
            border: none;
            border-radius: 3px;
            color: #fff;
        }
        #preview-container {
            width: 100%; max-width: 800px;
            margin-top: 10px;
            border: 1px solid #444;
            border-radius: 4px;
            padding: 10px;
            min-height: 50px;
            background: inherit;
            color: inherit;
        }
    </style>
</head>
<body class="dark-mode">
    <div class="container">
        <h1>Venice Chat App</h1>
        <button onclick="startNewChat()">New Chat</button>
        <div class="chat-container" id="chat-container"></div>
        <!-- Mode Buttons -->
        <div class="mode-buttons">
            <button onclick="setMode('text')">Text</button>
            <button onclick="setMode('image')">Image</button>
            <button onclick="setMode('agent')">Agent</button>
        </div>
        <div class="input-container">
            <input type="text" id="user-input" placeholder="Type your message or task...">
            <button onclick="sendMessage()">Send</button>
        </div>
        <div id="preview-container"></div>
        <div class="toggle-settings" onclick="toggleSettings()">Show Settings</div>
        <div class="settings" id="settings">
            <label>API Key:</label>
            <input type="text" id="api-key" placeholder="Enter your API Key">
            <label>System Prompt (for text mode):</label>
            <textarea id="system-prompt" rows="3" placeholder="Enter system prompt"></textarea>
            <label>Theme:</label>
            <select id="theme-select" onchange="toggleTheme(this.value)">
                <option value="dark-mode" selected>Dark</option>
                <option value="light-mode">Light</option>
            </select>
            <label><input type="checkbox" id="enter-to-send" checked> Send message with Enter key</label>
            <!-- Text Settings -->
            <div id="text-settings" class="mode-settings">
                <label>Select Text Model:</label>
                <select id="text-model-select">
                    <option value="llama-3.3-70b">Llama 3.3 70B</option>
                    <option value="llama-3.2-3b">Llama 3.2 3B</option>
                    <option value="dolphin-2.9.2-qwen2-72b">Dolphin 2.9.2 Qwen2 72B</option>
                    <option value="llama-3.1-405b">Llama 3.1 405B</option>
                    <option value="qwen-2.5-coder-32b">Qwen 2.5 Coder 32B</option>
                    <option value="deepseek-r1-671b">Deepseek R1 671B</option>
                    <option value="qwen-2.5-vl">Qwen 2.5 VL</option>
                    <option value="qwen-2.5-qwq-32b">Qwen 2.5 Qwq 32B</option>
                </select>
                <label>Temperature:</label>
                <input type="number" id="temperature" step="0.1" value="0.7">
                <label>Top P:</label>
                <input type="number" id="top-p" step="0.1" value="0.9">
                <label>Max Tokens:</label>
                <input type="number" id="max-tokens" value="7000">
                <label>Presence Penalty:</label>
                <input type="number" id="presence-penalty" step="0.1" value="1">
                <label>Frequency Penalty:</label>
                <input type="number" id="frequency-penalty" step="0.1" value="0.9">
                <label>Model Feature Suffix:</label>
                <input type="text" id="venice-params" placeholder="Optional model feature suffix">
                <label><input type="checkbox" id="keep-history" checked> Keep conversation history</label>
            </div>
            <!-- Image Settings -->
            <div id="image-settings" class="mode-settings">
                <label>Select Image Model:</label>
                <select id="image-model-select">
                    <option value="fluently-xl">Fluently-XL</option>
                    <option value="flux-dev">Flux-Dev</option>
                    <option value="flux-dev-uncensored">Flux-Dev Uncensored</option>
                    <option value="pony-realism">Pony Realism</option>
                    <option value="stable-diffusion-3.5">Stable Diffusion 3.5</option>
                    <option value="lustify-sdxl">Lustify SDXL</option>
                </select>
                <label>Image Height:</label>
                <input type="number" id="image-height" value="1024">
                <label>Image Width:</label>
                <input type="number" id="image-width" value="1024">
                <label>Steps:</label>
                <input type="number" id="image-steps" value="20">
                <label>Art Style:</label>
                <input type="text" id="art-style" placeholder="Optional art style">
                <label>Image Format:</label>
                <select id="image-format">
                    <option value="png" selected>PNG</option>
                    <option value="webp">WEBP</option>
                    <option value="jpg">JPG</option>
                </select>
                <label>Hide Watermark:</label>
                <select id="hide-watermark">
                    <option value="false" selected>No</option>
                    <option value="true">Yes</option>
                </select>
                <label>Embed EXIF Metadata:</label>
                <select id="embed-exif">
                    <option value="false" selected>No</option>
                    <option value="true">Yes</option>
                </select>
                <label>Negative Prompt:</label>
                <input type="text" id="negative-prompt" placeholder="Optional negative prompt">
                <label>CFG Scale:</label>
                <input type="number" id="cfg-scale" step="0.1" value="7.5">
                <label>Lora Strength:</label>
                <input type="number" id="lora-strength" step="0.1" value="50">
                <label>Seed (optional):</label>
                <input type="text" id="seed" placeholder="Optional seed value">
            </div>
            <!-- Agent Settings -->
            <div id="agent-settings" class="mode-settings">
                <label>Select Agent Model:</label>
                <select id="agent-model-select">
                    <option value="deepseek-r1-671b">Deepseek 671 (Reasoning)</option>
                    <option value="qwen-2.5-coder-32b">Qwen Coder 32B (Coding)</option>
                    <option value="dolphin-2.9.2-qwen2-72b">Dolphin 72B (Uncensored)</option>
                </select>
                <label>Temperature:</label>
                <input type="number" id="agent-temperature" step="0.1" value="0.7">
                <label>Top P:</label>
                <input type="number" id="agent-top-p" step="0.1" value="0.9">
                <label>Max Tokens:</label>
                <input type="number" id="agent-max-tokens" value="7000">
                <label>Presence Penalty:</label>
                <input type="number" id="agent-presence-penalty" step="0.1" value="1">
                <label>Frequency Penalty:</label>
                <input type="number" id="agent-frequency-penalty" step="0.1" value="0.9">
                <label><input type="checkbox" id="auto-execute-agent"> Allow auto execution of terminal commands</label>
                <label>Additional Whitelisted Commands (comma-separated):</label>
                <input type="text" id="additional-whitelist" placeholder="e.g., cat, grep">
            </div>
        </div>
    </div>
    <script>
        var currentMode = "text";
        function setMode(mode) {
            currentMode = mode;
            updateModeSettings();
        }
        function updateModeSettings() {
            document.getElementById("text-settings").style.display = "none";
            document.getElementById("image-settings").style.display = "none";
            document.getElementById("agent-settings").style.display = "none";
            if(currentMode === "text") {
                document.getElementById("text-settings").style.display = "block";
            } else if(currentMode === "image") {
                document.getElementById("image-settings").style.display = "block";
            } else if(currentMode === "agent") {
                document.getElementById("agent-settings").style.display = "block";
            }
        }
        updateModeSettings();
        function toggleSettings() {
            var settings = document.getElementById("settings");
            settings.style.display = (settings.style.display === "none" || settings.style.display === "") ? "block" : "none";
        }
        function toggleTheme(themeClass) {
            document.body.className = themeClass;
        }
        function appendAndSaveMessage(role, text) {
            var chatContainer = document.getElementById("chat-container");
            var messageDiv = document.createElement("div");
            messageDiv.className = "message " + role;
            messageDiv.innerHTML = "<strong>" + role + ":</strong> " + marked.parse(text);
            chatContainer.appendChild(messageDiv);
            chatContainer.scrollTop = chatContainer.scrollHeight;
            fetch("/save_message", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ role: role, content: text })
            }).catch(error => console.error("Error saving message:", error));
            return messageDiv;
        }
        function typeOutText(element, fullText, callback) {
            let i = 0;
            let accumulatedText = "";
            let interval = setInterval(function(){
                if (i < fullText.length) {
                    accumulatedText += fullText.charAt(i);
                    element.innerHTML = marked.parse(accumulatedText) + "<span class='blinking-cursor'>|</span>";
                    i++;
                } else {
                    clearInterval(interval);
                    element.innerHTML = marked.parse(fullText);
                    if(callback) callback();
                    addCopyButtonsToCodeBlocks(element);
                }
            }, 10);
        }
        function addCopyButtonsToCodeBlocks(container) {
            var codeBlocks = container.querySelectorAll("pre");
            codeBlocks.forEach(function(preBlock) {
                if(!preBlock.querySelector(".copy-button")) {
                    var button = document.createElement("button");
                    button.textContent = "Copy";
                    button.className = "copy-button";
                    button.onclick = function() {
                        navigator.clipboard.writeText(preBlock.textContent).then(function(){
                            button.textContent = "Copied!";
                            setTimeout(function(){ button.textContent = "Copy"; }, 2000);
                        });
                    };
                    preBlock.insertBefore(button, preBlock.firstChild);
                }
            });
        }
        async function executeAgentTask(task) {
            appendAndSaveMessage("assistant", "Starting agent task: " + task);
            var apiKey = document.getElementById("api-key").value;
            var model = document.getElementById("agent-model-select").value;
            var temperature = parseFloat(document.getElementById("agent-temperature").value);
            var top_p = parseFloat(document.getElementById("agent-top-p").value);
            var max_tokens = parseInt(document.getElementById("agent-max-tokens").value);
            var presence_penalty = parseFloat(document.getElementById("agent-presence-penalty").value);
            var frequency_penalty = parseFloat(document.getElementById("agent-frequency-penalty").value);
            var autoExecute = document.getElementById("auto-execute-agent").checked;
            var additionalWhitelist = document.getElementById("additional-whitelist").value.split(',').map(cmd => cmd.trim());
            var commandWhitelist = ['ls', 'pwd', 'whoami', 'echo'].concat(additionalWhitelist);

            var subtasksResponse = await fetch("/generate_subtasks", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    task: task,
                    model: model,
                    temperature: temperature,
                    top_p: top_p,
                    max_tokens: max_tokens,
                    presence_penalty: presence_penalty,
                    frequency_penalty: frequency_penalty,
                    api_key: apiKey
                })
            });
            var subtasksData = await subtasksResponse.json();
            if (subtasksData.error) {
                appendAndSaveMessage("assistant", "Error generating subtasks: " + subtasksData.error);
                return;
            }
            var subtasks = subtasksData.subtasks;

            while (true) {
                var results = [];
                for (var subtask of subtasks) {
                    appendAndSaveMessage("assistant", "Processing subtask: " + subtask.content);
                    if (subtask.type === "text") {
                        var textPayload = {
                            mode: "text",
                            message: subtask.content,
                            api_key: apiKey,
                            model: model,
                            temperature: temperature,
                            top_p: top_p,
                            max_tokens: max_tokens,
                            presence_penalty: presence_penalty,
                            frequency_penalty: frequency_penalty
                        };
                        var textResponse = await fetch("/chat", {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify(textPayload)
                        });
                        var textData = await textResponse.json();
                        appendAndSaveMessage("assistant", "Text subtask result: " + textData.reply);
                        results.push({ subtask: subtask.content, result: textData.reply });
                    } else if (subtask.type === "command") {
                        var command = subtask.content;
                        var cmdBase = command.split(' ')[0];
                        var isWhitelisted = commandWhitelist.includes(cmdBase);
                        var execute = false;
                        var approved = false;
                        if (autoExecute && isWhitelisted) {
                            execute = true;
                            appendAndSaveMessage("assistant", "Auto-executing whitelisted command: " + command);
                        } else {
                            if (!isWhitelisted) {
                                appendAndSaveMessage("assistant", "Command not in whitelist: " + command);
                            } else {
                                appendAndSaveMessage("assistant", "Awaiting approval for command: " + command);
                            }
                            execute = confirm(`Do you want to execute the command: ${command}?`);
                            approved = execute && !isWhitelisted;
                        }
                        if (execute) {
                            appendAndSaveMessage("assistant", "Executing command: " + command);
                            var execPayload = { command: command, approved: approved };
                            var execResponse = await fetch("/execute", {
                                method: "POST",
                                headers: { "Content-Type": "application/json" },
                                body: JSON.stringify(execPayload)
                            });
                            var execData = await execResponse.json();
                            appendAndSaveMessage("assistant", "Command output: " + execData.output);
                            results.push({ subtask: subtask.content, result: execData.output });
                        } else {
                            appendAndSaveMessage("assistant", "Command skipped: " + command);
                            results.push({ subtask: subtask.content, result: "Command skipped." });
                        }
                    }
                }

                appendAndSaveMessage("assistant", "Checking task completion...");
                var checkPayload = {
                    task: task,
                    results: results,
                    model: model,
                    temperature: temperature,
                    top_p: top_p,
                    max_tokens: max_tokens,
                    presence_penalty: presence_penalty,
                    frequency_penalty: frequency_penalty,
                    api_key: apiKey
                };
                var checkResponse = await fetch("/check_completion", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(checkPayload)
                });
                var checkData = await checkResponse.json();

                if (checkData.complete) {
                    appendAndSaveMessage("assistant", "Task complete.");
                    break;
                } else if (checkData.subtasks) {
                    subtasks = checkData.subtasks;
                } else if (checkData.question) {
                    var answer = prompt(checkData.question);
                    appendAndSaveMessage("user", "Clarification provided: " + answer);
                    checkPayload.answer = answer;
                    var answerResponse = await fetch("/check_completion", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify(checkPayload)
                    });
                    var answerData = await answerResponse.json();
                    if (answerData.complete) {
                        appendAndSaveMessage("assistant", "Task complete after clarification.");
                        break;
                    } else if (answerData.subtasks) {
                        subtasks = answerData.subtasks;
                    } else {
                        appendAndSaveMessage("assistant", "Error: No valid response after clarification.");
                        break;
                    }
                } else {
                    appendAndSaveMessage("assistant", "Error: Invalid response from check_completion.");
                    break;
                }
            }
        }
        function sendMessage() {
            var input = document.getElementById("user-input");
            var message = input.value;
            if(!message) return;
            appendAndSaveMessage("user", message);
            input.value = "";
            var apiKey = document.getElementById("api-key").value;
            if(currentMode === "text") {
                var payload = {
                    mode: "text",
                    message: message,
                    api_key: apiKey,
                    system_prompt: document.getElementById("system-prompt").value,
                    model: document.getElementById("text-model-select").value,
                    temperature: parseFloat(document.getElementById("temperature").value),
                    top_p: parseFloat(document.getElementById("top-p").value),
                    max_tokens: parseInt(document.getElementById("max-tokens").value),
                    presence_penalty: parseFloat(document.getElementById("presence-penalty").value),
                    frequency_penalty: parseFloat(document.getElementById("frequency-penalty").value)
                };
                var veniceParams = document.getElementById("venice-params").value;
                if (veniceParams.trim() !== "") {
                    payload.venice_params = veniceParams;
                }
                var assistantMsgDiv = document.createElement("div");
                assistantMsgDiv.className = "message assistant";
                assistantMsgDiv.innerHTML = "<strong>assistant:</strong> <span class='typing'>Assistant is thinking...</span>";
                document.getElementById("chat-container").appendChild(assistantMsgDiv);
                document.getElementById("chat-container").scrollTop = document.getElementById("chat-container").scrollHeight;
                var typingSpan = assistantMsgDiv.querySelector(".typing");
                fetch("/chat", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload)
                })
                .then(response => response.json())
                .then(data => {
                    typeOutText(typingSpan, data.reply, function() {
                        fetch("/save_message", {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({ role: "assistant", content: data.reply })
                        }).catch(error => console.error("Error saving message:", error));
                    });
                })
                .catch(error => {
                    console.error("Error:", error);
                    typingSpan.innerHTML = "Error: " + error;
                });
            } else if(currentMode === "image") {
                var payload = {
                    mode: "image",
                    message: message,
                    api_key: apiKey,
                    model: document.getElementById("image-model-select").value,
                    image_height: parseInt(document.getElementById("image-height").value),
                    image_width: parseInt(document.getElementById("image-width").value),
                    steps: parseInt(document.getElementById("image-steps").value),
                    hide_watermark: document.getElementById("hide-watermark").value === "true",
                    embed_exif_metadata: document.getElementById("embed-exif").value === "true",
                    negative_prompt: document.getElementById("negative-prompt").value,
                    cfg_scale: parseFloat(document.getElementById("cfg-scale").value),
                    lora_strength: parseFloat(document.getElementById("lora-strength").value),
                    format: document.getElementById("image-format").value
                };
                var artStyle = document.getElementById("art-style").value;
                payload.prompt = artStyle.trim() !== "" ? message + " in " + artStyle + " style" : message;
                var seedValue = document.getElementById("seed").value;
                if(seedValue.trim() !== "") { 
                    payload.seed = seedValue;
                }
                var assistantMsgDiv = document.createElement("div");
                assistantMsgDiv.className = "message assistant";
                assistantMsgDiv.innerHTML = "<strong>assistant:</strong> <span class='typing'>Generating image...</span>";
                document.getElementById("chat-container").appendChild(assistantMsgDiv);
                document.getElementById("chat-container").scrollTop = document.getElementById("chat-container").scrollHeight;
                var typingSpan = assistantMsgDiv.querySelector(".typing");
                fetch("/chat", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload)
                })
                .then(response => response.json())
                .then(data => {
                    if (data.image_url) {
                        if (data.image_url.startsWith("Error:")) {
                            typingSpan.innerHTML = data.image_url;
                            fetch("/save_message", {
                                method: "POST",
                                headers: { "Content-Type": "application/json" },
                                body: JSON.stringify({ role: "assistant", content: data.image_url })
                            });
                        } else {
                            assistantMsgDiv.innerHTML = "<strong>assistant:</strong><br><img src='" + data.image_url + "' style='max-width:100%; border:1px solid #777; border-radius:4px;'/>";
                            fetch("/save_message", {
                                method: "POST",
                                headers: { "Content-Type": "application/json" },
                                body: JSON.stringify({ role: "assistant", content: "Image generated: " + data.image_url })
                            });
                        }
                    } else {
                        typingSpan.innerHTML = "No image returned.";
                        fetch("/save_message", {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({ role: "assistant", content: "No image returned." })
                        });
                    }
                })
                .catch(error => {
                    console.error("Error:", error);
                    typingSpan.innerHTML = "Error: " + error;
                    fetch("/save_message", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ role: "assistant", content: "Error: " + error })
                    });
                });
            } else if(currentMode === "agent") {
                executeAgentTask(message);
            }
        }
        function startNewChat() {
            var keepHistory = document.getElementById("keep-history").checked;
            fetch("/new_chat", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ keep_history: keepHistory })
            })
            .then(response => response.json())
            .then(data => {
                if(data.success) {
                    if(!keepHistory) {
                        document.getElementById("chat-container").innerHTML = "";
                    }
                }
            })
            .catch(error => console.error("Error:", error));
        }
        var userInput = document.getElementById("user-input");
        userInput.addEventListener("keydown", function(event) {
            if(event.key === "Enter") {
                var enterToSend = document.getElementById("enter-to-send").checked;
                if(enterToSend) {
                    event.preventDefault();
                    sendMessage();
                }
            }
        });
        userInput.addEventListener("input", function() {
            var previewContainer = document.getElementById("preview-container");
            previewContainer.innerHTML = marked.parse(this.value);
        });
    </script>
</body>
</html>
'''

if __name__ == "__main__":
    app.run(debug=True)
