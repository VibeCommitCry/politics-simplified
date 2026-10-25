# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Status

`repo2-politics-simplified-plan.md` is leading: read it before changing behaviour. It is built in three steps (its section 12, prompts 1 to 3). **Steps 1 and 2 are done**: test mode, the writer ⇄ critic loop (max 3 rounds), readability, and fallback to the next model on status 429/503 with a cooldown and a per-model rate limit. Not built yet (step 3): FastAPI, Docker, the remaining pytest tests. Build only the step asked for.

## What this is

A **stateless Python service** that takes one voted Dutch parliamentary motie as JSON and returns a simplified version for a mobile feed: a `hook` (max 200 chars), a four-section `detail`, `topics`, a `relevance` score, plus the critic's verdict, the model used and the full prompts.

It is the AI half of a larger system. A separate Symfony (PHP, MySQL) backend fetches all data, decides which moties to process, calls the service and stores the result. Consequences:

- No database, no state between requests, no fetching from the Open Data Portal.
- Everything the model needs arrives in the request, including the allowed topic list and votes already summed per party.
- Everything Symfony needs to store goes in the response, including the filled-in prompts and `prompt_version`.
- Failures never raise: the response is always valid JSON with `error` filled and `critic_passed: false`.

## Commands

```
python -m venv .venv && .venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m simplifier --file tests/samples/input-example.json   # one request JSON in, one response JSON on stdout
```

Needs the first model's key (`GEMINI_API_KEY`) in `.env` (see `.env.example`); without it the command prints an error response and exits 1. Lint and format with Ruff (config in `ruff.toml`, line length 100): `.venv\Scripts\ruff check` and `.venv\Scripts\ruff format`.

```
.venv\Scripts\pytest                                                   # all tests, no API key needed
.venv\Scripts\pytest tests/test_llm.py::test_503_moves_to_next_model_without_retrying
```

To exercise the pipeline without a key or `models.yaml`, pass your own entries and a client factory: `pipeline.run(request, models, client_factory)`; see the fakes in `tests/test_llm.py`.

## Architecture

The package is split by layer: `api/` (contract), `core/` (pipeline with the critic loop, critic, readability), `prompt/`, `ai/` (models and clients), `limits/` (rate limit and cooldown). `REPO_ROOT` lives in `simplifier/__init__.py`.

- `simplifier/api/schemas.py` (+ `api/enums/`): the contract. `WriterOutput` is the strict shape the model must return; `SimplifyResponse` is what Symfony stores and allows empty content fields only when `error` is set. Rules are enforced **here in code**, not only in the prompt. The topic check needs the request's list, passed as validation context: `WriterOutput.model_validate(data, context={"allowed_topics": request.topics})`. Step 3's FastAPI app belongs in `api/` too.
- `simplifier/ai/`: `registry.py` loads `models.yaml` (ordered list of OpenAI-compatible endpoints); `client.py` returns an `openai` client for one entry, always with `max_retries=0`. An entry's optional `options` map is passed as extra arguments to `chat.completions.create` and overrides the defaults. `provider` in the response is the part of the entry's `name` before the first dash.
- `simplifier/limits/`: the in-memory, per-model state. `rate_limiter.py` is a sliding-window limiter (optional `rpm` per entry; calls wait rather than exceed it); `cooldown.py` holds the 60 s cooldowns. `limits.reset_state()` clears both (tests).
- `simplifier/prompt/`: `builder.py` (`build_writer_prompt`, `build_critic_prompt`, `PROMPT_VERSION`) joins the fixed `prompts/v1/writer.md` / `critic.md` with templates from the same directory (`data.md`, `feedback.md`, `answer.md`, `critic_answer.md`) filled with `string.Template`: lowercase placeholders are runtime values, UPPERCASE ones are JSON keys from the enums in `api/enums/`, a literal `$` is `$$`, and a missing value raises `KeyError`. No prompt text lives in Python. `tests/golden/` holds snapshots of the full prompts; regenerate them with `UPDATE_GOLDENS=1` only for an intended prompt change. From round 2 the writer prompt also gets its previous answer and the critic's problems; every call is one stateless user message. `sanitize.py` holds the untrusted-text markers.
- `simplifier/core/pipeline.py`: `run` tries the models in order and turns any exception into an error response. One model does the whole run: up to 3 rounds of writer then critic (`core/critic.py`, temperature 0, returns `CriticOutput`), stopping when the critic passes. Not passing after round 3 is not an error: the content is returned with `critic_passed: false` for manual review. The response holds the last round's verdict, confidence and prompts. Each round logs `round model=… round=N passed=… confidence=… duration=…s` to stderr. A model that answers 429 or 503 goes into cooldown and the run restarts from round 1 with the next one; models in cooldown are skipped; each skip is logged to stderr. A bad generation (the answer fails pydantic validation, or the API answers 400 with code `json_validate_failed`) is retried once for that call, then the next model restarts the run without a cooldown; it is logged to stderr with the first 300 characters of the returned text. Any other failure (timeout, missing key) ends the run with an error and does not fall through; it is raised as `RunFailed` carrying the model and the prompts built so far, which go into the error response. The layers: `run` (safety net: `RunFailed`, then a catch-all), `_first_available_model` (model loop, cooldown), `_falls_through` (pure check), `_run_with_model` (rounds, fresh `Prompts()` per call). `core/generation.py` holds the shared JSON call.
- `simplifier/core/readability.py`: Flesch-Douma (textstat, `nl`) of the motie text (`before`) and of the three prose detail sections without the word list (`after`); `null` on an error.
- `simplifier/__main__.py`: the `--file` test mode. Step 3's FastAPI endpoint must use the same `pipeline.run`.
- `prompts/v1/`: all versioned prompt text (LF line endings, enforced by `.gitattributes`); substituted values are never re-scanned, so nothing in the motie text is ever parsed as a template. A prompt change that alters output means a new version directory.

Rules that span files:

- **Motie text is untrusted data.** So is model output fed into a later prompt. They sit between `TEXT_BEGIN`/`TEXT_END` and `ANSWER_BEGIN`/`ANSWER_END` markers (defined in `prompt/sanitize.py`), the markers are stripped from all external strings first, and the prompt tells the model never to follow instructions inside it.
- **Facts are never generated.** Names, numbers, dates and the vote pass through from the request; seat totals are summed in code, not by the model.
- **One model per run**: writer and critic use the same model; on a model error restart the *whole run* with the next entry in `models.yaml`, never switch mid-run.
- **`confidence` is load-bearing**: a later phase escalates to a bigger model when it is low. It is the last round's critic confidence.
- **stdout is the response.** Any logging goes to stderr.

## Conventions

- Code, comments, README and this file in **English**; prompts and all model output in **Dutch at B1 level**.
- JSON field names in the contract are fixed and partly Dutch (`waar_gaat_het_over`, `wat_betekent_het_voor_jou`, `wat_is_er_besloten`, `moeilijke_woorden`); Symfony depends on them, so do not rename.
- Output must be neutral: no loaded or judging words ("eindelijk", "schandalig", "terecht"). Questions to the reader are allowed. Detail sections are plain text, no markdown.
