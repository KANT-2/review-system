# Continuous delivery

`Production delivery` runs after the `Quality checks` workflow succeeds on
`main`. It can also be started manually with `workflow_dispatch`.

The workflow checks out the exact tested commit, renders a mode-`0600`
production environment file, uploads the release over pinned-host-key SSH, and
runs the production Compose deployment. Database migrations and Django's
deployment checks must succeed before the app and Caddy services are recreated.
The workflow finishes by checking the public HTTPS login page.

## GitHub production environment

Configure these encrypted Environment Secrets:

- `DEPLOY_SSH_KEY`: private SSH key accepted by the deployment account
- `DJANGO_SECRET_KEY`: URL-safe value with at least 64 characters
- `POSTGRES_PASSWORD`: URL-safe value with at least 48 characters
- `DJANGO_EMAIL_HOST_PASSWORD`: URL-safe value with at least 32 characters

Configure these non-secret Environment Variables:

- `DEPLOY_HOST`: deployment server hostname
- `DEPLOY_PORT`: SSH port
- `DEPLOY_USER`: deployment account
- `DEPLOY_PATH`: `/home/<DEPLOY_USER>/services/review-system`
- `DEPLOY_KNOWN_HOSTS`: pinned `ssh-keyscan -H` output for the host and port

Do not put secret values in repository files, workflow YAML, command arguments,
or pull request descriptions. Rotate the SMTP account password and its GitHub
secret together so the mail server and application remain synchronized.

## Deployment behavior

Each tested commit is uploaded to `DEPLOY_PATH/releases/<commit-sha>`. The
shared production environment file lives outside release directories at
`DEPLOY_PATH/shared/.env.production`. After a successful health check,
`DEPLOY_PATH/current` points to the active release.

The database and named Docker volumes are retained between releases. The
workflow does not automatically reverse database migrations; review backward
compatibility and the rollback plan before merging a destructive migration.
