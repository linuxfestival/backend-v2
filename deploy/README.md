# Container deployment

This directory is the complete server deployment. Application source is not
required: Compose pulls the frontend and backend images from GHCR. Each image
tag is the first seven characters of its repository's commit SHA.

The stack contains PostgreSQL, MinIO S3 storage, Django/Gunicorn, the compiled
React site, and Caddy. Only Caddy publishes host ports. PostgreSQL, MinIO, and
the application containers remain on a private Docker network.

## Server files

Copy this directory to the server and create the untracked environment file:

```sh
cp .env.example .env
chmod 600 .env
```

Set `BACKEND_IMAGE_TAG` and `FRONTEND_IMAGE_TAG` independently because the two
repositories have different commit histories. Replace every placeholder secret.

GHCR packages are private by default. Either make both packages public or log
the server in once with a classic GitHub token that has `read:packages`:

```sh
printf '%s' "$GHCR_TOKEN" | docker login ghcr.io -u GITHUB_USERNAME --password-stdin
```

Pull and deploy:

```sh
docker compose pull
docker compose up -d --remove-orphans
docker compose ps
```

The backend waits for PostgreSQL, applies committed migrations, collects static
files, and then starts Gunicorn. MinIO media and Caddy certificates persist in
named volumes.

To deploy a new build, update one or both image tags in `.env`, then run the
same three commands. Do not delete the `postgres_data`, `minio_data`, or
`caddy_data` volumes during routine updates.

Useful operations:

```sh
docker compose logs --tail=200 backend frontend proxy
docker compose exec backend python manage.py createsuperuser
docker compose restart proxy
```
