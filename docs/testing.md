# Testing

No test needs an API key or network access. Model calls go through the fake clients in `tests/fakes.py`, and the shared fixtures (`request_`, the reset of the rate limit and cooldown state) live in `tests/conftest.py`.

```
.venv\Scripts\pytest                                    # all tests
.venv\Scripts\pytest tests/**folder name**                    # one layer
```

## Layout

`tests/` mirrors the `simplifier/` package: one `<layer>_test/` folder per layer.

| Folder | Type | What it covers |
| --- | --- | --- |
| `api_test/` | Unit | The contract in `api/schemas.py`. One test per rule, each changing one field of a valid base: hook length, topics (allowed list, count, context), relevance, the detail sections, `moeilijke_woorden`, extra keys, the critic's verdict, the request and the response's content-or-error rule. |
| `core_test/test_pipeline.py` | Integration | The whole pipeline with fake clients: fallback to the next model, cooldown, the retry on a bad generation, and the writer ⇄ critic loop. |
| `core_test/test_error_response.py` | Integration | Every way a run can fail (every model unavailable, `RunFailed`, the catch-all) ends in an error response that round-trips through JSON. |
| `core_test/test_readability.py` | Unit | The Flesch-Douma scores and which text they are computed on. |
| `limits_test/` | Unit | The rate limiter and the 60 s cooldown, with a fake clock. |
| `ai_test/` | Integration | A model entry's `options` reach the API call. |
| `prompt_test/test_prompt_templates.py` | Unit | The templates in `prompts/v1/` match the values the builders pass. |
| `prompt_test/test_prompts_golden.py` | Regression | The full writer and critic prompts match the snapshots in `tests/golden/`. |

- **Unit**: one function or model on its own.
- **Integration**: several layers together (pipeline, prompt builder, schemas, limits), with only the model faked.
- **Regression**: compares against a stored result, so a refactor cannot change behaviour unnoticed.

## Golden files

`tests/golden/` holds the exact prompts the model sees. A refactor of the prompt code must leave them unchanged. After an *intended* prompt change, regenerate them and review the diff before committing:

```
$env:UPDATE_GOLDENS=1; .venv\Scripts\pytest tests/prompt_test; Remove-Item Env:UPDATE_GOLDENS
```

A prompt change that alters the output belongs in a new `prompts/vN/` directory, with its own goldens.

## Adding a test

- Put it in the folder of the layer it tests.
- Start from a valid base (`GOOD_ANSWER`, `PASS_VERDICT`, the sample request) and change one thing, so a failure points at one rule.
- For a rule that rejects, also test the value just inside the limit.
