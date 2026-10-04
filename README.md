# SENTINEL-X

> **Semantic Impact Resolution for Interruptible Real-Time Agents**

SENTINEL-X is a full-stack application designed to handle semantic impact resolution for real-time agents, featuring a FastAPI-based backend and a React/Vite-based frontend with interactive task graph visualization.

## Features

- **Real-Time Websocket Communication**: seamless data synchronization between agents and the frontend.
- **Task Graph Visualization**: Built with `@xyflow/react` to map and manipulate agent state and impacts dynamically.
- **Robust API**: Powered by FastAPI, SQLAlchemy, and NetworkX.
- **Modern UI**: Built with React 19, Zustand for state management, and Vite for blazing-fast development.

## 🛠️ Tech Stack

### Backend
- Python (>=3.11)
- FastAPI & Uvicorn (REST API + WebSockets)
- SQLAlchemy & aiosqlite (Database)
- NetworkX (Graph processing)
- Pydantic (Data validation)

### Frontend
- React 19 & TypeScript
- Vite (Build Tool & Dev Server)
- `@xyflow/react` (Node/Edge visualizer)
- Zustand (State Management)
- Lucide React (Icons)

## 📦 Installation & Setup

### 1. Clone the repository
```bash
git clone https://github.com/abhi2005-bit/sentinal_x.git
cd sentinal_x
```

### 2. Backend Setup
The backend uses `uv` (or `pip`) for dependency management.

```bash
# Create a virtual environment and install dependencies
uv venv
source .venv/bin/activate
uv pip install -e .

# Alternatively with pip:
# python -m venv .venv
# source .venv/bin/activate
# pip install -r requirements.txt # (if available) or pip install -e .
```

Copy the example environment file:
```bash
cp .env.example .env
```

Start the FastAPI server:
```bash
# Run using the script entry point
sentinal-x
# Or run with uvicorn directly
uvicorn sentinel_x.main:app --reload
```
The API will be available at `http://localhost:8000`.

### 3. Frontend Setup
Open a new terminal and navigate to the `frontend` directory.

```bash
cd frontend

# Install Node dependencies
npm install

# Start the development server
npm run dev
```
The frontend will be available at `http://localhost:5173`.

## 📂 Project Structure

- `src/sentinel_x/` - Backend Python application (FastAPI, WebSockets, core logic).
- `frontend/` - Frontend React application (Vite, UI, Graph Visualization).
- `scripts/` - Assorted helper scripts for benchmarks, demos, and validations.
- `docs/` - Architecture, research, and documentation files.
- `.gsd/`, `.agent/`, `.agents/` - Workflow and methodology automation configurations.

## 📝 License
ISC
