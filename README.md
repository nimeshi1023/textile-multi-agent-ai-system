# textile-multi-agent-ai-system
Multi-Agent AI System for Textile Production Delay Prediction and Intelligent Order Management

## Authentication

Only signed-in managers can use FabricFlow: every API router except `/health`, `/auth/signup`,
`/auth/login`, `/auth/manager-types` and the docs needs a Bearer token, and every Streamlit page
shows the Sign In / Sign Up screen until you sign in.

1. Add to `.env` (generate the key with `python -c "import secrets; print(secrets.token_urlsafe(48))"`):
   ```
   AUTH_SECRET_KEY=<your generated key>
   AUTH_TOKEN_EXPIRE_MINUTES=60
   ```
   The backend refuses to start without `AUTH_SECRET_KEY`.
2. Open the app, choose **Sign Up** (manager type, Manager ID, email, password), then **Sign In**
   with your Manager ID and password.

Notes
- Passwords are stored only as bcrypt hashes. After 5 wrong passwords the account is locked for 15 minutes.
- The sign-in token is kept only in the Streamlit session: **refreshing the browser ends the session and you
  need to sign in again.** Tokens also expire after `AUTH_TOKEN_EXPIRE_MINUTES`.
- There is no password reset or email verification yet.
