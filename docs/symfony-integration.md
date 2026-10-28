# Connecting the Symfony backend

The service is not a public API. It is only meant to be called by the Symfony backend, over a private Docker network, with a shared secret.

## 1. One shared network

Both compose projects join the same external network. Create it once on the machine:

```
docker network create Social-Politics
```

## 2. Add the service to Symfony's compose

Build the image from this repository and join the shared network. Do **not** add `ports:`; nothing outside Docker should be able to reach the service.

```yaml
services:
    simplify:
        build: ../politics-simplified      # path to this repository
        env_file: ../politics-simplified/.env
        expose:
            - "8000"
        restart: unless-stopped
        mem_limit: 512m
        networks:
            - Social-Politics

    php:                                    # your existing Symfony service
        networks:
            - Social-Politics
            - default

networks:
    Social-Politics:
        external: true
```

The service reads its model keys and the shared secret from `.env` (copy `.env.example`). It refuses to start without `SIMPLIFY_API_KEY`.

## 3. The shared secret

Generate a long random value once and put it in both places:

- `SIMPLIFY_API_KEY` in this repository's `.env`
- the same value in Symfony's environment, for example `SIMPLIFY_API_KEY` in its `.env.local`

## 4. Calling the service

From inside the Symfony container the service is at `http://simplify:8000`.

```
POST http://simplify:8000/simplify
X-Api-Key: <SIMPLIFY_API_KEY>
Content-Type: application/json

{ ...one motie, as in tests/samples/input-example.json... }
```

| Status | Meaning |
|---|---|
| 200 | The run finished. Check `error`: it is `null` on success, filled when every model failed. Check `critic_passed` too; `false` means the content needs manual review. |
| 401 | `X-Api-Key` is missing or wrong. |
| 422 | The request body does not match the contract. `error` lists the fields. |

Every response is valid JSON in the same shape, with `error` filled on a failure. `GET /health` needs no key and returns `{"status": "ok"}`.

## 5. Running it at the right pace

The service runs a single worker, because the rate limiter and the cooldowns are kept in memory. It does not queue or limit incoming requests: Symfony decides how many moties it sends and how fast. A run can take a while (up to 3 writer and critic rounds, and a wait when a model's limit is reached), so use a generous HTTP timeout and send moties one after another, not in large parallel batches.

## Testing it from your own machine

`docker-compose.override.yml` in this repository publishes the port on `127.0.0.1` only, so this works from the host:

```
curl -X POST http://127.0.0.1:8000/simplify -H "X-Api-Key: <SIMPLIFY_API_KEY>" -H "Content-Type: application/json" --data-binary "@tests/samples/input-example.json"
```
