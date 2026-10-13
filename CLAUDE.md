# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Status

`repo2-politics-simplified-plan.md` is leading: read it before changing behaviour. It is built in three steps (its section 12, prompts 1 to 3). **Step 1 is done** (test mode with the writer only). Not built yet: critic and 3-round loop, fallback through `models.yaml`, readability (step 2); FastAPI, Docker, pytest tests (step 3). Build only the step asked for.

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
.venv\Scripts\python -m simplifier --file tests/samples/example.json   # one request JSON in, one response JSON on stdout
```

Needs the first model's key (`GEMINI_API_KEY`) in `.env` (see `.env.example`); without it the command prints an error response and exits 1. There are no tests or linter yet (pytest arrives in step 3).

To exercise the pipeline without a key, pass a fake client: `pipeline.run(request, client=fake)` where `fake.chat.completions.create(...)` returns an object with `.choices[0].message.content`.

## Architecture

- `simplifier/models.py`: the contract. `WriterOutput` is the strict shape the model must return; `SimplifyResponse` is what Symfony stores and allows empty content fields only when `error` is set. Rules are enforced **here in code**, not only in the prompt. The topic check needs the request's list, passed as validation context: `WriterOutput.model_validate(data, context={"allowed_topics": request.topics})`.
- `simplifier/llm.py`: loads `models.yaml` (ordered list of OpenAI-compatible endpoints) and returns an `openai` client for one entry. `provider` in the response is the part of the entry's `name` before the first dash.
- `simplifier/pipeline.py`: `build_writer_prompt` fills `prompts/v1/writer.md`; `run` calls the first model, validates, and turns any exception into an error response.
- `simplifier/__main__.py`: the `--file` test mode. Step 3's FastAPI endpoint must use the same `pipeline.run`.
- `prompts/v1/`: versioned prompts with `{{placeholder}}` slots, filled in a single regex pass so placeholders inside the motie text are left alone. A prompt change that alters output means a new version directory.

Rules that span files:

- **Motie text is untrusted data.** It sits between `TEXT_BEGIN`/`TEXT_END` markers (defined in `pipeline.py`), the markers are stripped from all external strings first, and the prompt tells the model never to follow instructions inside it.
- **Facts are never generated.** Names, numbers, dates and the vote pass through from the request; seat totals are summed in code, not by the model.
- **One model per run** (step 2): writer and critic use the same model; on a model error restart the *whole run* with the next entry in `models.yaml`, never switch mid-run.
- **`confidence` is load-bearing**: a later phase escalates to a bigger model when it is low. It is 0.0 until the critic exists.
- **stdout is the response.** Any logging goes to stderr.

## Conventions

- Code, comments, README and this file in **English**; prompts and all model output in **Dutch at B1 level**.
- JSON field names in the contract are fixed and partly Dutch (`waar_gaat_het_over`, `wat_betekent_het_voor_jou`, `wat_is_er_besloten`, `moeilijke_woorden`); Symfony depends on them, so do not rename.
- Output must be neutral: no loaded or judging words ("eindelijk", "schandalig", "terecht"). Questions to the reader are allowed. Detail sections are plain text, no markdown.
