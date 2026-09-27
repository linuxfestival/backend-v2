# Container deployment

The two repositories publish one image for every pushed commit. Each image tag
is the first seven characters of that repository's commit SHA.

## Server files

Copy only this `deploy` directory to the server, then create the untracked env
files:

```sh
cp .env.example .env
cp .env.backend.example .env.backend
cp .env.frontend.example .env.frontend
```

Set `BACKEND_IMAGE_TAG` and `FRONTEND_IMAGE_TAG` independently because the two
repositories have different commit histories. Replace every placeholder secret.

If the GHCR packages are private, authenticate once with a classic GitHub token
that has `read:packages` permission:

```sh
printf '%s' "$GHCR_TOKEN" | docker login ghcr.io -u GITHUB_USERNAME --password-stdin
```

Pull and deploy:

```sh
docker compose pull
docker compose up -d
docker compose ps
```

The frontend binds only to `127.0.0.1:8080` by default. The host reverse proxy
should send the public HTTPS site to that address. Requests under `/api/` and
`/admin/` are proxied internally to Django. PostgreSQL and Django are not exposed
on public host ports.

To deploy a new build, update one or both image tags in `.env`, then run the same
three commands. Database migrations and static-file collection run when the
backend container starts.
