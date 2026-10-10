# FabricFlow

**Textile Multi-Agent AI System for Production Delay Prediction and Intelligent Order Management**

FabricFlow helps textile and garment manufacturers find production delays early. It reads a customer order, checks the factory's resources, predicts the probability of a delay, and recommends corrective actions to a manager. The principle of the design is simple: **the AI recommends, the human manager decides.**

> Course project for IT3041 – Information Retrieval and Web Analytics (SLIIT).

---

## Overview

Textile factories lose time and money when orders are late. Delays come from machine breakdowns, limited machine capacity, material shortages, supplier delays, rework, and unrealistic deadlines. A single prediction number does not help a manager much, so FabricFlow goes further:

- it understands the order (from typed text or a PDF),
- checks machines, materials and suppliers in the database,
- predicts the delay probability with a machine-learning model,
- explains the main reasons for the risk,
- retrieves relevant standard operating procedures (SOPs), and
- proposes corrective actions that a manager approves or rejects.

## Key Features

- **Order intake from text or PDF.** An LLM turns free text into a structured order. Missing fields are sent back for clarification instead of being guessed.
- **Database-driven resource check.** Machine capacity, workload, material stock and supplier lead time come from PostgreSQL. All calculations are done in Python, never by the LLM.
- **Delay prediction with machine learning.** A scikit-learn Random Forest outputs a delay probability. The LLM never calculates the probability.
- **Explainable risk.** Each prediction shows its top contributing factors and a plain-language explanation.
- **Grounded recommendations.** Actions are backed by SOP documents retrieved from a local vector index (information retrieval). Actions that no SOP supports are dropped, not invented.
- **Human in the loop.** Every recommendation requires manager approval. Decisions are stored for audit.
- **Authentication.** Managers sign up and sign in with a Manager ID and password; the API uses JWT tokens.
- **Manager dashboard.** Order, risk and decision overview with charts.

## How It Works

```
Customer order (text or PDF)
        |
        v
 Order Analysis Agent          -> structured order (LLM, validated)
        |
        v
 Resource & Production Agent   -> machine, material and supplier facts + calculations (PostgreSQL + Python)
        |
        v
 Delay Prediction / Risk Agent -> delay probability + risk level + top factors (scikit-learn)
        |
        v
 Recommendation Agent          -> SOP retrieval + corrective actions (vector search + rules)
        |
        v
 Manager review                -> Approve / Reject / Override (human in the loop)
```

The output of each agent is the input of the next agent. Agents communicate through REST endpoints using structured JSON.

## The Four Agents

| Agent | Purpose | Main technology |
|---|---|---|
| **Order Analysis Agent** | Extracts product, material, quantity, deadline, priority and more from a message or PDF; validates the result and asks for clarification when fields are missing | LLM (Groq), Pydantic validation, PDF text extraction |
| **Resource & Production Agent** | Reads machines, materials and suppliers; calculates available capacity, required production days, material shortage and deadline pressure; explains the result | PostgreSQL, Python calculations, optional LLM explanation with template fallback |
| **Delay Prediction / Risk Agent** | Predicts the probability that an order will be delayed and classifies the risk | scikit-learn `RandomForestClassifier` trained on the `orders` table |
| **Recommendation Agent** | Retrieves relevant SOPs and recommends ranked corrective actions with sources | ChromaDB + sentence-transformers (TF-IDF fallback), rule-based action mapping |

**Risk levels**

| Delay probability | Risk level |
|---|---|
| 0 – 30 % | Low |
| 31 – 60 % | Medium |
| 61 – 100 % | High |

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python, FastAPI, Uvicorn |
| Database | PostgreSQL (docker-compose) |
| Machine learning | scikit-learn (Random Forest), pandas, joblib |
| Information retrieval | ChromaDB, sentence-transformers (`all-MiniLM-L6-v2`), TF-IDF fallback |
| LLM | Groq API (model set in `.env`) |
| Authentication | JWT (HS256), bcrypt password hashing |
| Frontend | Streamlit |

## Project Structure

The layout below is a guide. File names may differ slightly in your copy.

```
FabricFlow/
├── backend/
│   └── app/
│       ├── main.py                  # FastAPI app, routers, CORS
│       ├── agents/                  # order_analysis, resource_production, delay_risk, recommendation
│       ├── api/routes/              # orders, production, risk, recommendation, auth, dashboard
│       ├── core/                    # settings and security helpers
│       ├── db/                      # database connection and models
│       ├── schemas/                 # Pydantic request/response models
│       ├── services/                # LLM client, PDF, order and material services
│       ├── ml/                      # model training and artifacts (model, metrics.json)
│       ├── ir/                      # knowledge-base loader, index builder, retriever
│       └── knowledge_base/
│           ├── docs/                # SOP text files (26 documents)
│           └── chroma/              # generated vector index (git-ignored)
├── frontend/
│   ├── streamlit_app.py             # entry point
│   ├── api_client.py                # calls to the backend
│   └── pages/                       # New Order, Orders, Delay Prediction, Recommendations, ...
├── scripts/
│   └── setup_db.py                  # creates tables and loads data
├── docker-compose.yml               # PostgreSQL
├── requirements.txt
├── .env.example
└── README.md
```

## Getting Started

### Prerequisites

- Python 3.10 or newer
- Docker and Docker Compose (for PostgreSQL)
- Git
- A Groq API key (for the LLM features)

### 1. Clone the repository

```bash
git clone <your-repository-url>
cd FabricFlow
```

### 2. Create a virtual environment and install dependencies

```bash
python -m venv venv

# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt
```

### 3. Configure the environment

Copy the example file and fill in your own values (see [Environment Variables](#environment-variables)):

```bash
cp .env.example .env
```

Generate a strong secret for `AUTH_SECRET_KEY`:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

> **Never commit `.env`.** It contains secrets. Make sure it is listed in `.gitignore`.

### 4. Start the database and load the data

```bash
docker-compose up -d
python scripts/setup_db.py
```

### 5. Train the delay prediction model

The model is trained from the `orders` table and saved under `backend/app/ml/artifacts/`. Run the training script once (from the `backend` folder):

```bash
cd backend
python -m app.ml.train
```

> If your training script has a different name or location, use that command instead. The API shows the exact command in its "model not trained" message.

### 6. Build the knowledge-base index

The SOP documents are indexed once into a local vector store. Run this again whenever you change a file in `knowledge_base/docs/`:

```bash
cd backend
python -m app.ir.build_index
```

### 7. Run the backend

```bash
cd backend
uvicorn app.main:app --reload
```

The API runs at `http://localhost:8000` and the interactive documentation is at `http://localhost:8000/docs`.

### 8. Run the frontend

In a second terminal (from the project root):

```bash
streamlit run frontend/streamlit_app.py
```

The application opens at `http://localhost:8501`.

## Environment Variables

| Variable | Description |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string (database name `FabricFlow`) |
| `GROQ_API_KEY` | API key for the LLM provider |
| `GROQ_MODEL` | LLM model name |
| `AUTH_SECRET_KEY` | Secret used to sign JWT tokens (required) |
| `AUTH_TOKEN_EXPIRE_MINUTES` | Token lifetime in minutes (default 60) |
| `USE_LLM_EXPLANATION` | `true` to let the LLM polish explanations; default `false` (templates are used) |

Do not put real keys or passwords in the README, in screenshots, or in Git history. If a key is ever exposed, revoke it and create a new one.

## Using the Application

1. **Sign up** as a manager: choose a manager type, a Manager ID, an email and a password (8+ characters with upper case, lower case and a digit).
2. **Sign in** with your Manager ID and password.
3. **New Order**: type or paste a customer order, or upload a PDF, then review the extracted fields and confirm to save.
4. **Delay Prediction**: select an order to run the resource check and see the delay probability, risk level and top factors.
5. **Recommendations**: for Medium and High risk orders, review the suggested actions and their SOP sources, then approve, reject or override with a comment.
6. **Dashboard**: see orders, risk levels and decisions at a glance.

## API Overview

All endpoints except `/health`, `/auth/signup` and `/auth/login` require a valid `Authorization: Bearer <token>` header.

| Area | Endpoint | Purpose |
|---|---|---|
| Auth | `POST /auth/signup` | Create a manager account |
| Auth | `POST /auth/login` | Sign in and receive a JWT |
| Auth | `GET /auth/me` | Current manager profile |
| Orders | `POST /orders/analyze/message` | Extract an order from text (not saved) |
| Orders | `POST /orders/analyze/pdf` | Extract an order from a PDF (not saved) |
| Orders | `POST /orders` | Save a confirmed order |
| Orders | `GET /orders`, `GET /orders/{id}` | List and read orders |
| Risk | `POST /risk/predict` | Delay probability, risk level and top factors |
| Risk | `GET /risk/model-info` | Model metrics, class balance and bias report |
| Recommendation | `POST /recommendation/generate` | Generate SOP-backed recommendations |
| Recommendation | `POST /recommendation/search` | Search the knowledge base |
| Recommendation | `GET /recommendation/kb` | List indexed SOP documents |
| Recommendation | `POST /recommendation/decision` | Save a manager decision |
| System | `GET /health` | Health check |

See `http://localhost:8000/docs` for the full, current list with request and response examples.

## Responsible AI and Security

FabricFlow is designed as decision support, not an autonomous system.

- **Human oversight.** The AI recommends; a manager approves, rejects or overrides. Nothing changes an order, machine or stock automatically.
- **Explainability.** Predictions come with their top factors and a readable explanation, and each recommendation cites its SOP source.
- **No numbers from the LLM.** Facts come from the database, calculations are done in Python, and the delay probability comes only from the ML model.
- **Grounded actions.** A recommendation is shown only if a retrieved SOP supports it.
- **Fallbacks.** If the LLM is unavailable, extraction and explanations fall back to rules and templates so the system keeps working.
- **Security.** Passwords are hashed with bcrypt, tokens are signed JWTs with an expiry, API endpoints are protected, database queries are parameterised, and repeated failed logins lock the account temporarily.

## Testing

```bash
cd backend
pytest
```

The tests cover the agents, the API, authentication and the retrieval layer. Use the Swagger UI at `/docs` for manual API checks.

## Known Limitations

- The ML model is trained on a prototype dataset, so real deployments need more representative historical data.
- Unfamiliar product types are scored without a warning; the model cannot learn from categories it has not seen.
- The login session ends when the browser page is refreshed (the token is kept in the Streamlit session only).
- There is no password reset or email verification yet.
- Local deployment uses plain HTTP; use HTTPS and restricted CORS for any real deployment.

## Team

Group project for IT3041 – Information Retrieval and Web Analytics.

| Name | Student ID | Role |
|---|---|---|
| [Name] | [ID] | [e.g. Order Analysis Agent] |
| [Name] | [ID] | [e.g. Resource & Production Agent] |
| [Name] | [ID] | [e.g. Delay Prediction Agent] |
| [Name] | [ID] | [e.g. Recommendation Agent] |

## License

This project was created for academic purposes.
