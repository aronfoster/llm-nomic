# Live run on a ChatGPT plan (Sign in with ChatGPT, no API key)

llm-nomic can play a bounded game on your ChatGPT plan (Plus, Pro,
Business, Enterprise) through OpenAI's documented
[Sign in with ChatGPT for open-source apps](https://developers.openai.com/siwc/token-sharing-open-source)
flow. There's no API key, no client secret, and no pay-as-you-go billing.
Calls count against your ChatGPT plan's usage limits. On Business, a
workspace admin must have ChatGPT plan usage for third-party apps
switched on.

All commands run from the repository root, in the project's virtualenv
(`pip install -r requirements.txt`).

## 1. Sign in (once per computer, on a computer with a browser)

```sh
python -m src.nomic_engine.live_run openai-chatgpt-plan login
```

- This opens your browser at `auth.openai.com`. Choose the ChatGPT account
  or workspace, keep the agent name **llm-nomic**, and approve **ChatGPT
  plan usage**.
- The browser returns to `http://127.0.0.1:1455/auth/callback`, a
  listener started by the command that only accepts loopback connections.
  If port 1455 is busy, a free port is used. To pick one yourself, pass
  `--port N`.
- The first sign-in registers a per-user client. Its issued `client_id`
  is saved and reused, so later logins skip the consent screen.
- If the plan-usage scope isn't granted, login fails and saves nothing.

Check it:

```sh
python -m src.nomic_engine.live_run openai-chatgpt-plan status
python -m src.nomic_engine.live_run openai-chatgpt-plan models   # lists model slugs; no inference
```

If `gpt-5.2` isn't in the `models` list, change `api_model_id` of the
`chatgpt-plan` entry in `config/models.yml` to a slug that is.

## 2. Where the credential file lives

| File | Contents |
| --- | --- |
| `~/.config/llm-nomic/chatgpt_credentials.json` | issued client ID, verified account (`sub`, email), ID/access/refresh tokens, scopes, expiry |
| `~/.config/llm-nomic/chatgpt_host_id` | this computer's stable `ext_agent_host_id` |
| `~/.config/llm-nomic/chatgpt_credentials.lock` | refresh lock (empty) |

- The directory is `0700` and the files are `0600`, written atomically. A
  file readable by group or others is refused.
- To use another directory, set `LLM_NOMIC_CONFIG_DIR=/path` or pass
  `--config-dir /path`. A directory inside the repository is refused.
- Access tokens last 1 hour and refresh automatically. Refresh tokens
  last 30 days and rotate on every refresh, so the file changes while a
  game runs.
- Never commit, paste, or log these files.

## 3. Dry run, then the first bounded game

```sh
python -m src.nomic_engine.live_run openai-chatgpt-plan --dry-run
python -m src.nomic_engine.live_run openai-chatgpt-plan
```

The dry run prints the plan and creates and calls nothing. The live run
plays two LLM players (Ada and Grace) and an LLM judge, all on model
`chatgpt-plan`, under these default caps:

| Cap | Default | Flag |
| --- | --- | --- |
| turns | 2 | `--turns` |
| provider calls (retries count) | 40 | `--max-calls` |
| total tokens | 200,000 | `--max-tokens` |
| wall time | 1200 s | `--max-wall-seconds` |
| per-call timeout | 120 s | `--call-timeout-seconds` |

- Every request is `POST https://api.openai.com/v1/responses` with
  `store: false` and `stream: true`. The system prompt goes in
  `instructions`.
- Usage is read from each `response.completed` event. The game stops
  before the next call once a cap is reached. If a call reports no usage,
  the game stops at the next call while a token cap is set.
- `--allow-missing-usage` drops the token cap, leaving only the call and
  time caps.
- The route can't set `max_output_tokens`, so the token cap can overshoot
  by one call's output.
- If your plan's usage limit is hit (HTTP 429
  `subscription_sharing_usage_limit_exceeded`), the call counts as a
  quota error. Check ChatGPT Settings → Usage.

The game directory is `games/live-<timestamp>/`. Per-call usage is in
`token_usage.jsonl`, and a usage summary prints at the end.

## 4. Using the sign-in on another machine

The recommended way: run `login` on that machine too. If it has no
browser, forward the callback port first:

```sh
ssh -L 1455:127.0.0.1:1455 other-host
# on other-host:
python -m src.nomic_engine.live_run openai-chatgpt-plan login
# open the printed URL in the browser on your own computer
```

The fallback is to copy the credential file:

```sh
ssh other-host 'mkdir -p ~/.config/llm-nomic && chmod 700 ~/.config/llm-nomic'
scp -p ~/.config/llm-nomic/chatgpt_credentials.json other-host:~/.config/llm-nomic/
ssh other-host 'chmod 600 ~/.config/llm-nomic/chatgpt_credentials.json'
```

- Copy only `chatgpt_credentials.json`. The other machine creates its own
  `chatgpt_host_id`.
- Refresh tokens rotate, so once copied, **use the sign-in on one machine
  only**. Whichever machine refreshes first invalidates the other copy
  (`refresh_token_reused`), and that one must run `login` again.

## 5. Sign out

```sh
python -m src.nomic_engine.live_run openai-chatgpt-plan logout
```

This revokes the refresh token at OpenAI and clears the local tokens. The
registration (client ID and host ID) is kept for the next login. You can
also disconnect llm-nomic in ChatGPT Settings.
