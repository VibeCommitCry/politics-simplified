# politics-simplified

A stateless Python service that turns one voted Tweede Kamer motie into plain Dutch (B1 level) for a mobile feed: a short hook, a detailed text in four fixed sections, topics and a relevance score.

It has no database and fetches nothing itself. A separate Symfony backend collects the Tweede Kamer data, sends one motie per request and stores the result. The full design is in [repo2-politics-simplified-plan.md](repo2-politics-simplified-plan.md).

Status: only the test mode with the writer exists. The critic, the fallback to other models, the readability scores and the HTTP service are not built yet.

## Setup

```
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env          # macOS/Linux: cp .env.example .env
```

Put your API key in `.env`. Only `GEMINI_API_KEY` is needed for now: the writer uses the first model in `models.yaml`.

## Test mode

```
python -m simplifier --file tests/samples/example.json
```

This reads one request JSON, calls the writer once and prints one response JSON to stdout. The exit code is 0 on success and 1 when the response has an `error`.

- The request format is the one Symfony will send: the motie text, the submitters, the vote per party and the list of topics to choose from. `tests/samples/example.json` is a made-up motie with made-up vote numbers.
- The writer prompt is `prompts/v1/writer.md`. The filled-in prompt is returned in `prompts.writer`, with `prompt_version: "v1"`.
- The model's answer is checked in code: hook at most 200 characters, exactly the four detail sections, 1 to 3 topics that all come from the request's list, relevance 1 to 5.
- If anything fails (no API key, the model is unreachable, the answer breaks a rule), the output is still valid JSON with `error` filled, `critic_passed: false` and empty content fields (`hook: ""`, `detail: null`, `topics: []`, `relevance: null`).
- There is no critic yet, so a successful run also has `critic_passed: false`, `confidence: 0.0` and `rounds: 1`.
