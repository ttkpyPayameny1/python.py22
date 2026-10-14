# CloudNest Hosting Platform — expiry automation update

A Flask + SQLite starter website with accounts, plans, deposits, support tickets, an admin panel, in-app notifications, and a separate expiry worker.

## Important status

This update adds the scheduled expiry manager and Railway API stop/redeploy functions. It can actually stop a configured Railway deployment only after the deployment has been created on Railway and its IDs have been saved in the admin panel. The current `/hosting` form still records a deployment request; **automatic GitHub-to-Railway provisioning/OAuth is not implemented in this starter**. Do not accept real hosting payments until the provider provisioning flow, backups, security, and production database have been completed and tested.

## Run locally

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
export SECRET_KEY='replace-with-a-long-random-secret'
export ADMIN_EMAIL='admin@example.com'
export ADMIN_PASSWORD='use-a-strong-unique-password'
python app.py
```

The first startup creates the admin account if `ADMIN_EMAIL` and `ADMIN_PASSWORD` are set. Keep secrets in environment variables, never in source code or GitHub.

## Railway expiry automation setup

1. Create a Railway API token with access only to the project/environment this platform must manage. Put it in the platform service environment as `RAILWAY_TOKEN`.
2. Deploy the website service normally.
3. Create a **separate Railway worker service** from the same repository and set its start command to `python worker.py`. Keep it running. The worker checks every 30 seconds by default; change `EXPIRY_CHECK_SECONDS` if needed (minimum 15 seconds).
4. In the admin panel, open **Deployment History & Railway Expiry Setup** for a bot and save its Railway Service ID, Environment ID, and currently running Deployment ID. The deployment row will be marked `running`.
5. At 24 hours before a plan ends, the worker creates an in-app notification. When the end time passes, it calls Railway's `deploymentStop` mutation for the saved deployment ID. On success it marks the deployment stopped and shows the user a message. On failure it records the error, leaves the subscription in `expired_unstopped`, and retries on later worker cycles while alerting the admin if optional Telegram settings are configured.
6. When the user buys a new plan, the website tries to redeploy their previously stopped Railway bot using the saved service/environment IDs. It records the new deployment ID and shows a success/failure notification.

Optional admin Telegram alerts:

- `TELEGRAM_BOT_TOKEN`: token of a Telegram bot you control.
- `TELEGRAM_ADMIN_CHAT_ID`: the admin chat ID that should receive expiry failures/success notices.

These settings are optional. Users always receive in-app notifications visible on the dashboard.

## Railway API operations used

The implementation uses Railway's official GraphQL API endpoint `https://backboard.railway.com/graphql/v2`, with `deploymentStop` to stop a running deployment and `serviceInstanceDeployV2` to launch a new deployment. Railway API credentials must have access to the corresponding service/environment.

## Limitations and production checklist

- GitHub OAuth and automatic repository provisioning are not included yet. The deployment form currently records a request only.
- Railway IDs are manually attached by an administrator in this build.
- The worker must be deployed as a continuously running separate service; a web-only deployment will not run scheduled expiry checks reliably.
- SQLite is suitable for a demo/small single-instance setup only. Use managed PostgreSQL and backups for production/multiple instances.
- Add CSRF protection, rate limiting, email verification/password reset, provider OAuth, webhook verification, and monitoring before production use.
- Vercel deployments are not controlled by the Railway stop/redeploy integration.
