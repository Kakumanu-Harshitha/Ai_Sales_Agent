# SETV AI Sales Agent Platform

This repository contains the SETV AI Sales Agent Platform, a full-stack application built with a React (Vite) frontend and a Python (FastAPI/SQLAlchemy) backend. 

The platform utilizes a multi-agent architecture (driven by Groq/Gemini models) to orchestrate prospecting, signal detection, multi-channel outreach, and meeting scheduling.

---

## 🛠️ Prerequisites

Before you begin, ensure you have the following installed on your machine:
*   **Python 3.10+** (for the FastAPI backend)
*   **Node.js 18+** (for the React/Vite frontend)
*   **PostgreSQL** (running locally or via a cloud provider like Supabase/AWS)

---

## 🚀 Setup Instructions

If you have just pulled this project, follow these steps to set up your local environment from scratch.

### 1. Database Configuration
You must have a running PostgreSQL database. Create an empty database for the project (e.g., `setv_agent`).

### 2. Environment Variables (`.env`)
The project relies on environment variables for API keys and database credentials. These are excluded from version control.

1.  Copy the example environment file:
    *   **Windows:** `copy .env.example .env`
    *   **Mac/Linux:** `cp .env.example .env`
2.  Open the newly created `.env` file in your editor.
3.  Fill in the required values. At a minimum, you **must** configure:
    *   `DATABASE_URL` (e.g., `postgresql://user:password@localhost:5432/setv_agent`)
    *   Your AI Provider API Keys (e.g., `GEMINI_API_KEY` or `OPENAI_API_KEY`)
    *   (Optional) Email/SMTP settings if you are testing live outreach.

### 3. Backend Setup (FastAPI)
The backend requires a Python virtual environment to isolate its dependencies.

1.  Open your terminal in the root directory of the project.
2.  **Create a virtual environment:**
    *   **Windows:** `python -m venv venv`
    *   **Mac/Linux:** `python3 -m venv venv`
3.  **Activate the virtual environment:**
    *   **Windows:** `.\venv\Scripts\activate`
    *   **Mac/Linux:** `source venv/bin/activate`
4.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
5.  **Run Database Migrations (Alembic):**
    Before starting the server, initialize your database tables:
    ```bash
    alembic upgrade head
    ```
    *(Note: If you are using a SQLite test DB, the app may auto-create tables, but Alembic is recommended for Postgres).*
6.  **Start the Backend Server:**
    ```bash
    uvicorn apps.api.main:app --reload
    ```
    The backend API will now be running at [http://localhost:8000](http://localhost:8000).

### 4. Frontend Setup (React / Vite)
The frontend is a modern React application built with Vite and Tailwind CSS.

1.  Open a **new, separate terminal window** in the root directory of the project.
2.  **Install Node dependencies:**
    ```bash
    npm install
    ```
3.  **Start the Frontend Development Server:**
    ```bash
    npm run dev
    ```
    The frontend UI will now be accessible at [http://localhost:3000](http://localhost:3000).

### 5. Google Workspace Credentials (Gmail & Calendar)
To enable the agent to send emails and schedule meetings, you need a `credentials.json` file from Google Cloud.

1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Create a new project (or select an existing one).
3. Navigate to **APIs & Services > Library** and enable both the **Gmail API** and the **Google Calendar API**.
4. Navigate to **APIs & Services > OAuth consent screen** and configure it (you can choose "External" and add your email as a Test User).
5. Navigate to **APIs & Services > Credentials**.
6. Click **Create Credentials > OAuth client ID**.
7. Choose **Desktop App** as the application type and click Create.
8. Click the download icon to download your client secret JSON file.
9. Rename the downloaded file to `credentials.json` and place it in the root directory of this project.
*(Note: Run `python check_oauth.py` to authenticate locally and generate your `token.json` file for the first time).*

---

## 🏗️ Project Architecture

*   **`apps/api/`**: Contains the FastAPI backend, database models (`models.py`), orchestration logic (`agent_controller.py`), and API endpoints.
*   **`src/`**: Contains the React frontend, UI components, and dashboard layouts.
*   **`alembic/`**: Contains database migration scripts.
*   **Agent Controller**: The background scheduling engine runs within the FastAPI event loop, driven by APScheduler, evaluating the sales pipeline and taking automated actions.

## 🐛 Troubleshooting

*   **Socket / Connection Abort Errors (10053):** If you see SQLAlchemy operational errors stating the connection was aborted, this is usually caused by your database host killing idle connections during long AI generation cycles. Ensure `pool_pre_ping=True` is enabled in `database.py` and consider using a Transaction Pooler (port 6543) if using Supabase.
*   **Dependencies Failing to Install:** Ensure your active Python environment is explicitly `venv` and that you are using Node 18+.
