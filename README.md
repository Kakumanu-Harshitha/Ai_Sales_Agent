# SETV AI Sales Agent Platform

This repository contains the SETV AI Sales Agent Platform, a full-stack application designed to automate the sales pipeline. It features a modern React (Vite) frontend with an Emerald/Teal brand theme, and a Python (FastAPI/SQLAlchemy) backend.

The platform utilizes a multi-agent architecture (driven by AI models like Groq/Gemini) to orchestrate prospecting, signal detection, multi-channel outreach, and meeting scheduling.

---

## 🚀 Live Deployments

*   **Frontend (Vercel):** [https://ai-sales-agent-nine.vercel.app/](https://ai-sales-agent-nine.vercel.app/)
*   **Backend API (Render):** [https://ai-sales-agent-zgen.onrender.com/](https://ai-sales-agent-zgen.onrender.com/)

---

## 📁 Project Structure

The project has been refactored into a clear monorepo structure:

*   **`frontend/`**: Contains the React/Vite application.
    *   `src/`: UI components, pages (Dashboard, CRM, Outreach, Signals, Orchestration), API utility with SWR caching.
    *   `src/index.css`: Tailwind configuration and core Emerald/Teal brand theme variables.
*   **`backend/`**: Contains the FastAPI application.
    *   `apps/api/modules/`: Domain-specific modules (CRM, Orchestration, Calendar, Jobs, etc.).
    *   `main.py`: Application entry point.
    *   `alembic/`: Database migration scripts.

---

## 🛠️ Prerequisites

Before you begin, ensure you have the following installed on your machine:
*   **Python 3.10+** (for the FastAPI backend)
*   **Node.js 18+** (for the React/Vite frontend)
*   **PostgreSQL** (running locally or via a cloud provider like Supabase/AWS)

---

## ⚙️ Setup Instructions

### 1. Database Configuration
You must have a running PostgreSQL database. Create an empty database for the project (e.g., `setv_agent`).

### 2. Backend Setup (FastAPI)

1.  Navigate to the backend directory:
    ```bash
    cd backend
    ```
2.  **Environment Variables:**
    Copy the example environment file and fill in the required values:
    ```bash
    cp .env.example .env
    ```
    *Required variables include `DATABASE_URL` and AI Provider API Keys (e.g., `GEMINI_API_KEY` or `OPENAI_API_KEY`).*
3.  **Create and activate a virtual environment:**
    *   **Windows:** `python -m venv venv` and `.\venv\Scripts\activate`
    *   **Mac/Linux:** `python3 -m venv venv` and `source venv/bin/activate`
4.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
5.  **Run Database Migrations (Alembic):**
    ```bash
    alembic upgrade head
    ```
6.  **Start the Backend Server:**
    ```bash
    python main.py
    # or
    uvicorn main:app --reload
    ```
    The backend API will run at [http://localhost:8000](http://localhost:8000).

### 3. Frontend Setup (React / Vite)

1.  Open a **new terminal window** and navigate to the frontend directory:
    ```bash
    cd frontend
    ```
2.  **Environment Variables:**
    Ensure you configure the `.env` file to point to your backend API URL if developing locally. By default, the app is configured to use the dynamic `VITE_API_URL` variable.
3.  **Install Node dependencies:**
    ```bash
    npm install
    ```
4.  **Start the Frontend Development Server:**
    ```bash
    npm run dev
    ```
    The frontend UI will be accessible at [http://localhost:3000](http://localhost:3000).

### 4. Google Workspace Credentials (Gmail & Calendar)
To enable the agent to send emails and schedule meetings, you need a `credentials.json` file from Google Cloud.

1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Enable the **Gmail API** and **Google Calendar API**.
3. Configure the **OAuth consent screen**.
4. Create **OAuth client ID** credentials (Desktop App type).
5. Download the client secret JSON, rename it to `credentials.json`, and place it in the appropriate backend directory to authenticate and generate `token.json`.

---

## ⚡ Performance Optimization & Caching

The frontend includes optimizations to ensure snappy tab navigation and avoid redundant API calls:
*   **Stale-While-Revalidate (SWR) Caching:** GET requests (e.g., `/leads`) are cached with a 30-second TTL to instantly serve data on navigation.
*   **Automatic Cache Invalidation:** Write actions (POST/PUT/DELETE) automatically flush the cache to guarantee fresh data.
*   **State Retention:** The layout utilizes a `display: none` tab retention strategy, ensuring that filters, scroll position, and inputs are preserved when navigating between modules (CRM, Outreach, etc.).

---

## 🔧 Troubleshooting

*   **Socket / Connection Abort Errors (10053):** If SQLAlchemy operational errors occur stating the connection was aborted, ensure `pool_pre_ping=True` is enabled in your database configuration.
*   **Dependencies Failing to Install:** Ensure your active Python environment is explicitly `venv` (Python 3.10+) and that you are using Node 18+ for the frontend.
