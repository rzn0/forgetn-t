# Discord Task List Bot

[![Python Version](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT) <!-- Assuming MIT, adjust if different -->

A Python-based Discord bot using `py-cord` and SQLite to manage server tasks through dedicated "Open", "In Progress", and "Completed" channels via interactive buttons and slash commands.

## Features

*   **Dedicated Task Channels**: Uses separate channels for viewing tasks that are Open, In Progress, or Completed (logging).
*   **Task Workflow**:
    *   Users can add tasks using the `/addtask` command.
    *   Tasks appear in the "Open" channel with a "Claim" button.
    *   Claiming moves the task to the "In Progress" channel, assigns it to the claimer, and adds a "Complete" button.
    *   Completing removes the task from "In Progress", optionally logs it to the "Completed" channel, and deletes it from the database.
*   **Channel Configuration**: Server administrators use `/setup` commands to designate the specific channels for Open, In Progress, and Completed tasks.
*   **Slash Commands**: Utilizes Discord's built-in slash commands for adding tasks and configuration.
*   **Persistent Buttons**: Task buttons (Claim/Complete) utilize persistent views, allowing them to function even after the bot restarts.
*   **Database**: Stores task information and channel configurations per server using SQLite (`tasks.db`).
*   **Admin Resync**: Provides an `/resync_tasks` command for administrators to refresh task messages if display issues occur.
*   **Secure**: Bot token is managed securely via a `.env` file.

## Requirements

*   **Python 3.8+**
*   **Pip** (Python package installer)
*   **Git** (for cloning the repository)
*   **Python Dependencies**: Listed in `requirements.txt` (includes `py-cord`, etc.)

## Setup Instructions

1.  **Clone the Repository:**
    ```bash
    git clone <repository_url> # Replace <repository_url> with the actual URL
    cd <repository_directory> # e.g., cd discord-task-bot
    ```

2.  **Create a Virtual Environment (Recommended):**
    ```bash
    python3 -m venv venv
    source venv/bin/activate  # Linux/macOS
    # venv\Scripts\activate    # Windows
    ```

3.  **Install Dependencies:**
    ```bash
    pip install --upgrade pip
    pip install -r requirements.txt
    ```

4.  **Configure Environment Variables:**
    *   In the root directory (where `taskBot.py` is), create a file named `.env`.
    *   **Edit the `.env` file:**
        ```env
        # Discord Bot Token (REQUIRED) - Get from Discord Developer Portal
        DISCORD_TOKEN=YOUR_BOT_TOKEN_GOES_HERE
        ```
    *   **Replace `YOUR_BOT_TOKEN_GOES_HERE` with your actual bot token.**
    *   **IMPORTANT:** Ensure the `.env` file is listed in your `.gitignore` file and **never commit it** to version control.

5.  **Discord Application Setup:**
    *   Go to the [Discord Developer Portal](https://discord.com/developers/applications).
    *   Create a **New Application**.
    *   Go to the **Bot** tab and click **Add Bot**.
    *   **Token:** Get your bot token (Reset/View Token) and put it in the `.env` file. **Keep this token secret!**
    *   **Privileged Gateway Intents:** Scroll down and **ENABLE** the **`SERVER MEMBERS INTENT`**. This is needed to accurately retrieve member information when assigning/displaying tasks. `MESSAGE CONTENT INTENT` is generally not needed unless you add features that read messages. Click **Save Changes**.

6.  **Invite Bot to Your Server:**
    *   Go to **OAuth2 -> URL Generator**.
    *   **Scopes:** Select `bot` and `applications.commands`.
    *   **Bot Permissions:** Select:
        *   `View Channels` (Read Messages)
        *   `Send Messages`
        *   `Manage Messages` (Required to delete old task messages when claimed/completed/resynced)
        *   `Embed Links` (Required for displaying tasks nicely)
        *   `Read Message History` (Needed to find messages for buttons/updates)
    *   Copy the **Generated URL** and use it to add the bot to your server.

7.  **Initial Bot Run & Channel Setup (Mandatory):**
    *   Run the bot (see next section). It will automatically create the database file (`tasks.db`) if it doesn't exist. Check logs for errors.
    *   **After the bot is online:** An administrator with **"Manage Channels"** permission must configure the task channels:
        *   Go to the channel designated for **open** tasks and run `/setup open_channel`.
        *   Go to the channel designated for **in-progress** tasks and run `/setup inprogress_channel`.
        *   (Optional) Go to the channel designated for **completed** task logs and run `/setup completed_channel`.
    *   The bot **must** have the required permissions (View, Send, Manage Messages, Embed Links, Read History) in these configured channels.
    *   The `/addtask` command will only function correctly once *both* the open and in-progress channels are set up.

## Running the Bot

1.  **Activate Virtual Environment** (if used):
    ```bash
    source venv/bin/activate # Linux/macOS
    # venv\Scripts\activate   # Windows
    ```
2.  **Run the Python script:**
    ```bash
    python bot.py
    ```
3.  Check console logs for readiness messages and errors.
4.  **Remember to perform the mandatory `/setup` steps** in your server after the first run.

## Commands

*(Uses Slash Commands)*

*   `/setup open_channel [channel]`
    *   **Permission:** User needs `Manage Channels`.
    *   **Action:** Sets the channel where new, unclaimed tasks will be posted. Best run *in* the desired channel.
*   `/setup inprogress_channel [channel]`
    *   **Permission:** User needs `Manage Channels`.
    *   **Action:** Sets the channel where claimed, in-progress tasks will be moved/displayed. Best run *in* the desired channel.
*   `/setup completed_channel [channel]`
    *   **Permission:** User needs `Manage Channels`.
    *   **Action:** (Optional) Sets the channel where details of completed tasks will be logged. Best run *in* the desired channel. If not set, completed tasks are simply removed.
*   `/addtask description`
    *   **Permission:** Anyone (configurable in Discord command permissions if needed).
    *   **Action:** Creates a new task with the provided description. The task embed is posted to the configured "Open Tasks" channel.
*   `/resync_tasks`
    *   **Permission:** User needs `Manage Server`.
    *   **Action:** Attempts to refresh the messages for all tasks currently in the database (Open and In Progress) by deleting the old message (if found) and posting a new one with updated buttons. Useful if buttons stopped working or display is incorrect.

## Usage Workflow

1.  **Admin Setup:** Use the `/setup` commands to designate the three task channels (Open and In-Progress are mandatory).
2.  **Add Task:** Any user runs `/addtask description: <Your Task>`.
3.  **Task Appears:** Bot posts an embed for the new task in the "Open Tasks" channel with a "Claim Task" button.
4.  **Claim Task:** A user clicks "Claim Task". The bot edits the original message (or deletes and reposts) in the "Open Tasks" channel to show it's claimed, posts a new embed in the "In Progress Tasks" channel showing the task and the claimer, and adds a "Complete Task" button.
5.  **Complete Task:** The assigned user clicks "Complete Task" in the "In Progress Tasks" channel. The bot deletes the message from "In Progress", logs the completion details (user, task, time) to the "Completed Tasks" channel (if configured), and removes the task from the database.

## Limitations

*   **Channel Permissions:** The bot *must* have adequate permissions (View, Send, Manage Messages, Embed Links, Read History) in all configured task channels to function correctly.
*   **Setup Dependency:** Adding tasks requires the Open and In-Progress channels to be configured first via `/setup`.
*   **SQLite Scalability:** Suitable for most servers, but might encounter performance issues with an extremely high volume of tasks over a long period.
*   **Button Persistence:** Relies on Discord correctly re-attaching views on startup. While generally reliable, edge cases or API changes could affect this. `/resync_tasks` can help mitigate issues.
*   **Error Handling:** Assumes basic error handling is present; detailed diagnostic messages primarily appear in the console logs.

## Contributing

Contributions are welcome! Please feel free to submit pull requests or open issues for bugs or feature suggestions.
