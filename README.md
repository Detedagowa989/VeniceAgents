Documentation for VeniceAgents.py
Introduction
VeniceAgents.py is a web-based application that integrates with the Venice API to provide an agentic AI capable of generating text, creating images, and performing tasks via a Flask-powered chat interface. It was developed as a personal project by iteratively refining code with the help of ChatGPT and Grok3, blending their strengths to overcome limitations encountered during development.
How It Was Made
This application is a “Frankenstein” creation, born from bouncing ideas and code snippets between ChatGPT and Grok3. Initially, I aimed to build a simple interface for the Venice API, but it evolved into a multi-mode agentic AI. ChatGPT helped with structuring Flask routes and HTML templates, while Grok3 assisted in refining the agent logic and debugging API integrations. The process involved:
Starting with a basic Flask app for text generation.

Adding image generation capabilities using Venice API’s image endpoint.

Implementing an agent mode with task decomposition and command execution, iterating on prompts and logic to handle subtasks.

Overcoming issues (e.g., command execution errors) by tweaking system prompts and whitelisting mechanisms.

The result is a functional, albeit imperfect, hybrid that showcases collaborative AI-assisted coding.
Features
Text Mode: Generates text responses using the Venice API based on user prompts, with adjustable parameters like model, temperature, and max tokens.

Image Mode: Creates images from text prompts, supporting customization (e.g., height, width, steps) and displaying them in the browser as base64-encoded data.

Agent Mode: Breaks down high-level tasks into subtasks (text generation or command execution), processes them, and checks for completion. Supports whitelisted commands with optional auto-execution.

Conversation History: Stores messages in an SQLite database, with summarization for long conversations.

UI Features: Dark/light themes, markdown rendering with marked.js, typing animations, and a settings panel for configuration.

Setup
Prerequisites
Python 3.x: Ensure Python is installed (python3 --version).

Dependencies:
Flask: pip install flask

Requests: pip install requests

SQLite3: Included with Python by default.

Venice API Key: Optional but recommended for full functionality. Obtain from Venice AI.

Git: For cloning the repository (see upload steps above).

Installation
Clone the Repository:

git clone https://github.com/yourusername/VeniceAgents.git
cd VeniceAgents

Install Dependencies:

pip install flask requests

Secure the Secret Key:
Open VeniceAgents.py and replace app.secret_key = "your-secret-key" with a strong, unique key (e.g., generate one with python -c "import secrets; print(secrets.token_hex(16))").

For production, use an environment variable instead: export FLASK_SECRET_KEY="your-secret-key" and update the code to app.secret_key = os.getenv("FLASK_SECRET_KEY").

Running the Application
Start the Server:

python VeniceAgents.py

Access the App:
Open a web browser and go to http://127.0.0.1:5000/.

The interface loads with a chat window, mode buttons, and settings.

Usage
Switching Modes: Use the “Text,” “Image,” or “Agent” buttons to change modes.

Text Mode:
Enter a message, adjust settings (e.g., model, temperature), and click “Send” or press Enter.

Responses appear with a typing animation.

Image Mode:
Input a prompt (e.g., “A cat in space”), tweak image settings, and send.

Generated images display inline.

Agent Mode:
Provide a task (e.g., “Get weather data for Hong Kong”).

The agent decomposes it into subtasks, executes them (if commands are whitelisted/approved), and loops until complete or requiring clarification.

Settings:
Toggle “Show Settings” to configure API key, model parameters, theme, and more.

Optionally set a default API key via environment variable: export VENICE_API_KEY="your-api-key".

Technical Details
Backend: Flask handles routing, SQLite stores conversation history, and requests interacts with the Venice API.

Frontend: An embedded HTML template with CSS for styling, JavaScript for interactivity, and marked.js for markdown rendering.

API Integration: Uses Venice API endpoints for text (chat/completions) and image (image/generate) generation.

Database: SQLite (conversation.db) saves messages with session IDs, summarizing long histories to manage token limits.

Agent Logic: Decomposes tasks into subtasks (text or commands), executes them, and checks completion via API calls.

Known Issues
Command Execution Reliability: The agent struggles to execute commands correctly, sometimes misinterpreting instructions (e.g., using API keys instead of curl when explicitly told to use curl for weather data).

Command Selection: Even with clear instructions, it may choose inappropriate methods, indicating a need for better prompt engineering.

Code Structure: As a “Frankenstein” creation, it lacks optimal organization, making maintenance challenging.

Future Improvements
Refine System Prompts: Enhance agent prompts to enforce command adherence (e.g., “Use only the specified tool, such as curl, without substituting APIs”).

Improve Command Logic: Strengthen the run_terminal_command function with better parsing and validation.

Error Handling: Add robust feedback for failed subtasks or API errors.

Refactoring: Reorganize the code into modular components (e.g., separate agent logic, UI, and API calls).

Security: Expand the whitelist and add sandboxing for command execution.

Security Considerations
Command Execution: Only whitelisted commands (ls, pwd, etc.) run automatically if auto_execute is enabled. Non-whitelisted commands require manual approval, but this is still a risk if misused.

API Key: Avoid hardcoding; use the settings input or environment variables.

Secret Key: Replace the placeholder in production to prevent session hijacking.

