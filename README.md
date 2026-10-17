# politics-simplified

A stateless Python service that turns one voted Tweede Kamer motie into plain Dutch (B1 level) for a mobile feed: a short hook, a detailed text in four fixed sections, topics and a relevance score.

It has no database and fetches nothing itself. A separate Symfony backend collects the Tweede Kamer data, sends one motie per request and stores the result. The full design is in [repo2-politics-simplified-plan.md](repo2-politics-simplified-plan.md).

Status: only the test mode with the writer exists. The critic, the readability scores and the HTTP service are not built yet.

## Setup

```
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env          # macOS/Linux: cp .env.example .env
```

Put your API key in `.env`. The writer uses the first model in `models.yaml` (`GEMINI_API_KEY`) and moves on to the next ones when a model is busy, so fill in the keys for all models you want as a fallback.

## Test mode

```
python -m simplifier --file tests/samples/example.json
```

This reads one request JSON, calls the writer once and prints one response JSON to stdout. The exit code is 0 on success and 1 when the response has an `error`.

- The request format is the one Symfony will send: the motie text, the submitters, the vote per party and the list of topics to choose from. `tests/samples/example.json` is a made-up motie with made-up vote numbers.
- The writer prompt is `prompts/v1/writer.md` (fixed rules) + the per-call data block `prompts/v1/data.md` + the answer format `prompts/v1/answer.md` (JSON keys from the `OutputData` enum), filled with `string.Template`. The filled-in prompt is returned in `prompts.writer`, with `prompt_version: "v1"`.
- The model's answer is checked in code: hook at most 200 characters, exactly the four detail sections, 1 to 3 topics that all come from the request's list, relevance 1 to 5.
- If anything fails (no API key, the model is unreachable, the answer breaks a rule), the output is still valid JSON with `error` filled, `critic_passed: false` and empty content fields (`hook: ""`, `detail: null`, `topics: []`, `relevance: null`).
- There is no critic yet, so a successful run also has `critic_passed: false`, `confidence: 0.0` and `rounds: 1`.

## Busy models

Models are tried in the order of `models.yaml`. When a model answers with status 429 (rate limit) or 503 (overloaded), it is not retried: it is put aside for 60 seconds and the run starts again with the next model. Models that are still put aside are skipped. Each skip is logged to stderr with the model name and the status code. If no model is left, the response has an `error`.

When a model answers with something unusable, it gets one more try. This covers an answer that is not valid JSON or breaks a rule, and a provider that rejects the answer itself (status 400 with code `json_validate_failed`). After a second bad answer the next model takes over; the model is not put aside. Each bad answer is logged to stderr with the model name, the error code and the first 300 characters of the returned text.

Any other failure (a timeout, a missing key) ends the run with an `error` and does not move on to the next model.

Each model can have an optional `rpm` in `models.yaml`: the provider's limit in requests per minute. A call that would go over the limit waits until there is room. It can also have an `options` map with extra arguments that are sent with every request to that model, such as `max_tokens` or `reasoning_effort`.

Both the cooldowns and the rate-limit counts live in memory, so they only last as long as the process. In the test mode that is one run; they start to matter once the service runs continuously.

## Tests

```
pytest
```

The tests use fake clients and need no API key.
