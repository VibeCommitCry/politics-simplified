# What each Python file does

This describes the code as it is after step 1 of the plan (the test mode with the writer only), plus the fallback to the next model when one is busy. There is no critic and no HTTP service yet.

All Python code lives in the `simplifier/` package. There are five files.

| File | Job in one line |
|---|---|
| `__init__.py` | Marks the folder as a package |
| `__main__.py` | The command you run: reads a request file, prints a response |
| `models.py` | Defines the shape of the request and the response, and checks the rules |
| `llm.py` | Reads `models.yaml`, connects to a model provider, tracks rate limits and cooldowns |
| `pipeline.py` | Builds the prompt, calls a model (the next one if it is busy), checks the answer |

## How one run flows

```
python -m simplifier --file tests/samples/example.json
        │
        ▼
__main__.py   reads the JSON file and turns it into a SimplifyRequest   (models.py)
        │
        ▼
pipeline.py   run(request)
        │       1. concatenates prompts/v1/writer.md, generate_writer_template() and generate_answer_template(), filled with the request data
        │       2. takes the first model from models.yaml that is not cooling down   (llm.py)
        │       3. sends the prompt to the model; on 429/503 goes back to 2          (llm.py)
        │       4. checks the model's answer against the rules          (models.py)
        │       5. returns a SimplifyResponse, or an error response
        ▼
__main__.py   prints the response as JSON, exit code 0 (ok) or 1 (error)
```

## `__init__.py`

One line of documentation and nothing else. Python needs this file to treat `simplifier/` as a package, which is what makes `python -m simplifier` and `from simplifier import ...` work.

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

## `models.py`: the contract and the rules

This file uses pydantic. A pydantic model is a class that describes what a piece of JSON must look like; when you validate data against it, pydantic either gives you a typed object or raises an error that says exactly which field is wrong. This is how the plan's "rules checked in code, not only in the prompt" are enforced.

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

## `llm.py`: models and connections

This file knows where the models are and how to reach them. It knows nothing about moties or prompts.

- **`ModelEntry`** is one entry from `models.yaml`: `name`, `base_url`, `model`, `api_key_env`, an optional `rpm` (requests per minute) and an optional `options` map with extra arguments for the request, such as `max_tokens`. Its `provider` property is the part of the name before the first dash, so `gemini-flash` gives `gemini`. That value ends up in the response.
- **`load_models()`** reads `models.yaml`, validates every entry and returns them in file order. That order is the order in which models will be tried. An empty file raises an error.
- **`client_for(entry)`** returns a ready-to-use `openai` client for one entry:
  1. Loads `.env` so the keys become environment variables.
  2. Looks up the variable named in `api_key_env`. The YAML holds the *name* of the variable, never the key itself.
  3. Raises a clear error if the key is missing.
  4. Creates the client with the entry's `base_url`, a 60-second timeout and `max_retries=0`. By default the `openai` client quietly retries a failed call twice; that is switched off, because a failing model is handled by moving to the next one.

One `openai` client works for every provider because Gemini, Groq and NVIDIA all offer an OpenAI-compatible endpoint; only the URL and the key differ.

The file also keeps two small pieces of memory per model. Both live only in the running process; nothing is saved to disk.

- **The rate limiter.** `RateLimiter` remembers the times of the calls in the last 60 seconds. `wait()` checks whether there is still room under the `rpm` limit; if not, it sleeps until the oldest call is 60 seconds old. `wait_for_rate_limit(entry)` is the function the pipeline calls before each request; it does nothing for a model without `rpm`.
- **The cooldowns.** `start_cooldown(entry, status)` notes that a model should be left alone for 60 seconds and which status code caused it. `cooldown_status(entry)` returns that status code while the cooldown lasts, and `None` once it is over.

`log_skip` writes one line to stderr when a model is skipped. `log_bad_generation` does the same for an unusable answer, with the first 300 characters of the text the model returned. `reset_state` empties both memories; the tests use it to start clean.

`REPO_ROOT` is worked out from the file's own location, so the code finds `models.yaml`, `.env` and `prompts/` no matter which folder you run it from.

## `pipeline.py`: the actual work

This is where a request becomes a response.

**`build_writer_prompt(request)`** makes the text that is sent to the model:

1. Concatenates `writer.md`, the data block from `generate_writer_template()` and `generate_answer_template()`. The data block has slots (one per `InputData` key) like `{{title}}` and `{{text}}`.
2. Prepares a value for every slot: the title, the submitters as a list, the vote date and outcome, the parties for and against with their seats, the seat totals, the allowed topics and the motie text.
3. Fills all slots in a single pass with a regular expression.

Three details matter here:

- **The totals are added up in Python**, not by the model. Models make arithmetic mistakes; `sum()` does not.
- **The motie text is treated as untrusted.** It is placed between the markers `<<<MOTIETEKST_BEGIN>>>` and `<<<MOTIETEKST_EINDE>>>`, and the prompt tells the model never to follow instructions found there. The helper `_untrusted` first removes those markers from any outside text, so a motie cannot "close" the block early and smuggle in instructions.
- **The single pass** means a slot name that happens to appear inside the motie text (for example `{{topics}}`) stays as plain text and is not filled in.

`_format_parties` is a small helper that writes one line per party and picks "zetel" or "zetels" correctly.

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

Everything happens inside one `try`. Whatever goes wrong (no key, the provider is down, the answer is not JSON, the hook is too long) is caught and turned into an error response. `run` never raises, which is what lets the service promise valid JSON every time.

Because there is no critic yet, a successful run still reports `critic_passed: false`, `confidence: 0.0` and `rounds: 1`.

## What is not here yet

- **Step 2:** the critic, the loop of up to 3 rounds and `readability.py`.
- **Step 3:** `api.py` (the FastAPI service), the Dockerfile and the tests for the pydantic rules.
