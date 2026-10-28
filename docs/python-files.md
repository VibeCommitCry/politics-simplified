# What each Python file does

This describes the code as it is now: the test mode, the writer and critic loop, the fallback to the next model when one is busy, and the FastAPI service.

All Python code lives in the `simplifier/` package, split into folders by layer.

| File | Job in one line |
|---|---|
| `__init__.py` | Marks the folder as a package and defines `REPO_ROOT` |
| `__main__.py` | The command you run: reads a request file, prints a response |
| `api/app_api.py` | The FastAPI service: `POST /simplify` (needs `X-Api-Key`) and `GET /health` |
| `api/schemas.py` | Defines the shape of the request and the response, and checks the rules |
| `api/enums/` | The keys of the prompt's data block and of the writer's JSON answer |
| `ai/registry.py` | Reads `models.yaml` |
| `ai/client.py` | Connects to a model provider |
| `limits/rate_limiter.py` | Keeps each model under its requests-per-minute limit |
| `limits/cooldown.py` | Leaves a busy model alone for 60 seconds |
| `prompt/builder.py` | Builds the writer prompt |
| `prompt/sanitize.py` | Keeps the untrusted motie text inside its markers |
| `core/pipeline.py` | Calls a model (the next one if it is busy) and checks the answer |

## How one run flows

```
python -m simplifier --file tests/samples/example.json
        │
        ▼
__main__.py   reads the JSON file and turns it into a SimplifyRequest   (api/schemas.py)
        │
        ▼
core/pipeline.py   run(request)
        │       1. builds the writer prompt from prompts/v1/writer.md and the request   (prompt/builder.py)
        │       2. takes the first model from models.yaml that is not cooling down   (ai/registry.py, limits/cooldown.py)
        │       3. waits for the rate limit and sends the prompt; on 429/503 goes back to 2   (limits/rate_limiter.py, ai/client.py)
        │       4. checks the model's answer against the rules          (api/schemas.py)
        │       5. returns a SimplifyResponse, or an error response
        ▼
__main__.py   prints the response as JSON, exit code 0 (ok) or 1 (error)
```

## `__init__.py`

Python needs this file to treat `simplifier/` as a package, which is what makes `python -m simplifier` and `from simplifier import ...` work. It also defines `REPO_ROOT`, worked out from the file's own location, so the code finds `models.yaml`, `.env` and `prompts/` no matter which folder you run it from.

## `__main__.py`: the test mode

Python runs this file when you type `python -m simplifier`. It has two functions.

**`simplify_file(path)`** turns a file into a response:

1. Reads the file and parses it as JSON.
2. Remembers the `case_id` if it can find one, so that even a broken request gets an answer with the right id.
3. Validates the JSON as a `SimplifyRequest`. If the file is missing, is not JSON or has the wrong fields, it returns an error response and stops.
4. Otherwise hands the request to `pipeline.run`.

**`main()`** is the command-line wrapper:

1. Uses `argparse` to read the required `--file` argument.
2. Calls `simplify_file`.
3. Switches stdout to UTF-8. Windows consoles use a different encoding by default, and Dutch text has characters like `é` and `ë`.
4. Prints the response as indented JSON. `ensure_ascii=False` keeps those characters readable instead of turning them into `é`.
5. Returns exit code 1 if the response has an `error`, else 0.

Nothing else is ever printed to stdout, so the output can always be parsed as JSON.

## `api/schemas.py`: the contract and the rules

This file uses pydantic. A pydantic model is a class that describes what a piece of JSON must look like; when you validate data against it, pydantic either gives you a typed object or raises an error that says exactly which field is wrong. This is how the rules are checked in code, not only in the prompt.

**The request** (what Symfony sends):

- `Submitter`: a name and a party.
- `PartyVote`: a party and its number of seats (0 or more).
- `Vote`: date, outcome and the lists of parties for and against. The outcome can only be `"aangenomen"` or `"verworpen"`. Because `for` is a reserved word in Python, the field is called `for_` in code and keeps the name `for` in JSON through an alias.
- `SimplifyRequest`: the whole request. The text, the submitters and the topic list may not be empty. `related` defaults to an empty list.

**The writer's answer** (what the model must return):

- `DifficultWord`: a `woord` and its `betekenis`.
- `Detail`: the four sections. `extra="forbid"` means a fifth section from the model is rejected, so it is always exactly these four.
- `WriterOutput`: the hook (1 to 200 characters), the detail, 1 to 3 topics and a relevance of 1 to 5.

The topic rule needs something a normal field check does not have: the list of topics from the request. The pipeline passes that list in as validation context, and the validator `topics_come_from_request` rejects any topic that is not in it.

**The response** (what Symfony stores):

- `Readability` and `Prompts`: small helper shapes. `Readability` is unused until step 2.
- `SimplifyResponse`: the full response. Most fields have a default, so an error response can be built with almost nothing filled in.

The validator `content_or_error` makes sure a response is always one of two kinds:

- **With an error:** `critic_passed` must be false; the content fields may be empty.
- **Without an error:** hook, detail, topics and relevance must all be filled.

`WriterOutput` and `SimplifyResponse` are separate on purpose. The first is strict, because it judges what the model wrote. The second has to be able to describe a failed run too.

## `ai/`: models and connections

This folder knows where the models are and how to reach them. It knows nothing about moties or prompts.

- **`ModelEntry`** (`registry.py`) is one entry from `models.yaml`: `name`, `base_url`, `model`, `api_key_env`, an optional `rpm` (requests per minute) and an optional `options` map with extra arguments for the request, such as `max_tokens`. Its `provider` property is the part of the name before the first dash, so `gemini-flash` gives `gemini`. That value ends up in the response.
- **`load_models()`** reads `models.yaml`, validates every entry and returns them in file order. That order is the order in which models will be tried. An empty file raises an error.
- **`client_for(entry)`** (`client.py`) returns a ready-to-use `openai` client for one entry:
  1. Loads `.env` so the keys become environment variables.
  2. Looks up the variable named in `api_key_env`. The YAML holds the *name* of the variable, never the key itself.
  3. Raises a clear error if the key is missing.
  4. Creates the client with the entry's `base_url`, a 60-second timeout and `max_retries=0`. By default the `openai` client quietly retries a failed call twice; that is switched off, because a failing model is handled by moving to the next one.

One `openai` client works for every provider because Gemini, Groq and NVIDIA all offer an OpenAI-compatible endpoint; only the URL and the key differ.

## `limits/`: rate limit and cooldown

This folder keeps two small pieces of memory per model. Both live only in the running process; nothing is saved to disk.

- **The rate limiter** (`rate_limiter.py`). `RateLimiter` remembers the times of the calls in the last 60 seconds. `wait()` checks whether there is still room under the `rpm` limit; if not, it sleeps until the oldest call is 60 seconds old. `wait_for_rate_limit(entry)` is the function the pipeline calls before each request; it does nothing for a model without `rpm`.
- **The cooldowns** (`cooldown.py`). `start_cooldown(entry, status)` notes that a model should be left alone for 60 seconds and which status code caused it. `cooldown_status(entry)` returns that status code while the cooldown lasts, and `None` once it is over.

`log_skip` (`cooldown.py`) writes one line to stderr when a model is skipped. `limits.reset_state()` empties both memories; the tests use it to start clean.

## `prompt/`: building the prompt

**`build_writer_prompt(request)`** and **`build_critic_prompt(request, output)`** (`builder.py`) make the text that is sent to the model. All prompt text lives in `prompts/v1/`; Python only fills and joins it:

1. Reads `writer.md` (or `critic.md`) as-is.
2. Prepares a value for every slot of `data.md`: the title, the submitters as a list, the vote date and outcome, the parties for and against with their seats, the seat totals, the allowed topics and the motie text.
3. Fills the templates with `string.Template` (`data.md`, from round 2 `feedback.md`, and `answer.md` or `critic_answer.md`) and joins the parts with a blank line.

Placeholders like `$title` are runtime values; UPPERCASE ones like `$HOOK` are JSON keys taken from the `OutputData` / `CriticData` enums. A literal `$` is written `$$`, and a missing value raises `KeyError` instead of becoming empty.

Three details matter here:

- **The totals are added up in Python**, not by the model. Models make arithmetic mistakes; `sum()` does not.
- **The motie text is treated as untrusted.** It is placed between the markers `<<<MOTIETEKST_BEGIN>>>` and `<<<MOTIETEKST_EINDE>>>`, and the prompt tells the model never to follow instructions found there. The markers and the helper `untrusted` live in `sanitize.py`; it first removes those markers from any outside text, so a motie cannot "close" the block early and smuggle in instructions.
- **Filled values are never re-scanned**, so a slot name that happens to appear inside the motie text (for example `$topics`) stays as plain text and is not filled in.

`_format_parties` is a small helper that writes one line per party and picks "zetel" or "zetels" correctly.

## `core/pipeline.py`: the actual work

This is where a request becomes a response. `log_bad_generation` writes one line to stderr for an unusable answer, with the first 300 characters of the text the model returned.

**`error_response(...)`** builds a valid `SimplifyResponse` for a failed run: the error message, `critic_passed: false`, and whatever is already known (the model, the provider, the prompt).

**`_write(request, entry, client, writer_prompt)`** does one attempt with one model:

1. Waits if the model's `rpm` limit is reached.
   Then puts the request together: the defaults below plus the model's `options` from `models.yaml`, which win if both set the same thing.
2. Sends the prompt as one user message. `response_format={"type": "json_object"}` asks the provider to return JSON only; `temperature=0.3` keeps the writing fairly steady between runs.
3. Parses the answer as JSON and validates it as a `WriterOutput`, with the request's topics as context.
   If that fails, it raises `BadGeneration`. It does the same when the provider itself rejects the answer (status 400 with code `json_validate_failed`, which Groq sends).
4. Copies the result into a `SimplifyResponse`, together with the model, the provider, the prompt version and the full prompt.

**`run(request)`** does one complete run:

1. Builds the writer prompt.
2. Goes through the models in the order of `models.yaml`.
3. Skips a model that is cooling down, and logs that.
4. Calls `_write` for the first model that is available. If that works, the run is done.
5. If the answer is a bad generation, logs it and gives the same model one more try. After the second bad answer it continues with the next model, without a cooldown.
6. If the model answers with status 429 (rate limit) or 503 (overloaded), puts it in cooldown for 60 seconds, logs it and continues with the next model. The same model is not tried again.
7. If no model is left, returns an error response.

Any other failure (a timeout, a missing key) ends the run with an error and does not move on to the next model.

`run` also accepts its own list of models and its own function for making clients. That is how the tests run it with fake clients and without an API key.

The error handling is split into layers, each with one job:

- **`run`** is only the safety net. It catches `RunFailed` and turns it into an error response with the model and the prompts it carries. A final `except Exception` catches everything else (for example a broken `models.yaml`), so `run` never raises. That is what lets the service promise valid JSON every time.
- **`_first_available_model`** is the loop over the models: it skips models in cooldown, starts the cooldown on 429/503, and moves on after two bad generations. When no model is left it raises `RunFailed("no model available: …")`.
- **`_falls_through(exc)`** only decides: True for a failure that hands the run to the next model (a bad generation, 429 or 503). It has no side effects.
- **`_run_with_model`** does the rounds with its own fresh `Prompts()`. A failure that falls through is passed on as is. Any other failure becomes `RunFailed` with the prompts built so far, so the error response shows what was sent.

Error messages keep the form `Type: message`.

## What is not here yet

Nothing from the original three steps. The HTTP service is `api/app_api.py`; `docs/symfony-integration.md` explains how the backend calls it.
