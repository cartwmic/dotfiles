<!-- printed -->
# khoj guide

Repo: khoj. Commit: ae229ca894c0b80ad84664afcfdde523b5e87057. Date: 2026-11-20.
Counts: 243 surfaces (entry 24, flag 9, route 88, event 14, env 64, config 1, manifest 9, doc 1, ci 33); 16 scout names found, 0 not found and dropped; 234 test cases in 24 files; 27 of 175 named surfaces appear in tests.
Evidence: code and the repo's own words first; tests where the repo has them (A2).
<!-- /printed -->

# Part 1: In plain English

## What it is and who it is for

Khoj is a personal AI app that scales from an on-device assistant to a cloud-scale one. [A3.1] You can chat with local or online language models. [A3.2] It also gives answers from the internet and your documents, and offers custom agents. [A3.3] You reach it from Browser, Obsidian, Emacs, Desktop, Phone or Whatsapp. [A3.4] It is open-source and self-hostable, so you can run it yourself. [A3.5]

## What you can do

Chatting needs a signed-in user. [A4.2] A reply can stream as plain text, or come back whole. [A4.5] [A4.6] Trial users get 100 requests a day, and subscribed users get 600. [A4.4] A model call picks data sources and output format when the commands are just the default. [A4.14] Research mode loops up to 5 times by default, choosing tools on each pass. [A4.21] [A4.25] It stops when the cancellation event is set. [A4.22] Document tools are hidden when you have no entries. [A4.30]

Uploaded files are sorted into org, markdown, pdf, plaintext, image and docx groups by detected type. [A5.3] Other file types are skipped. [A5.4] Long text is split into chunks of at most 256 words by default. [A5.21] A search asks the database for at most 10 hits. [A5.27] Notion content and GitHub repos can be indexed too. [A5.13] [A5.19]

An agent has a name, personality, chat model, slug, input tools and output modes. [A6.1] Input tools are general, online, notes, webpage or code. [A6.3] Output modes are image or diagram. [A6.4] Privacy level is public, private or protected, and defaults to private. [A6.2] Creating an agent runs a prompt check on the persona first. [A6.22]

An automation runs a query on a schedule and sends the result. [A7.1] You can list your automations, add them and delete them. [A7.3] [A7.15] [A7.4] You can also trigger one on demand. [A7.17] Khoj emails the result when it should notify and Resend is enabled. [A7.34]

Khoj keeps facts about a user as memories, stored per user. [A8.1] You can list, edit or delete them. [A8.1] When memory is enabled, a chat query loads recent and long term memories. [A8.21] A server setting can turn memory off whatever the user chose. [A8.18]

You can list chat models with their name, id, strengths and description. [A9.2] A chat model has a provider type of openai, anthropic or google. [A9.23] You can pick a voice model and an image model too. [A9.5] A user without the premium scope cannot pick a chat model that is not free. [A9.7]

Web search tries Serper, Exa, Firecrawl, Google and SearXNG, each added when its key or URL is set. [A10.6] It stops at the first engine that returns non-empty results. [A10.7] Khoj asks a model to generate Python code and input files, then runs the code. [A10.18] Computer operation needs a vision-enabled chat model. [A10.26] Its iteration limit defaults to 100. [A10.29]

Image generation uses OpenAI, Replicate or Google, chosen by the model type. [A11.5] Speech routes stream audio as audio/mpeg. [A11.14] Transcription returns the text. [A11.21] Twilio Verify sends a code over WhatsApp. [A11.25]

## How the parts fit

The command line parses options, mounts the routes, and starts a background scheduler. [A3.7] The server is a FastAPI app, and Django is mounted at /server. [A3.11] Django owns the database models and the admin interface. [A3.12] The chat, agent, automation, model, memory, content and Notion routers sit under /api. [A3.13] The database engine is PostgreSQL. [A3.23] The index update job repeats at 22 to 25 hour intervals. [A3.37]

## What it needs and keeps

The package needs Python 3.10 or later and below 3.13. [A3.33] The default host is 127.0.0.1 and the default port is 42110. [A3.9] Database host, port, name, user and password default from environment variables. [A3.23] User, agent, chat model, conversation and entry records are Django models. [A3.22] Memories are kept for each user. [A8.1] The log file defaults to ~/.khoj/khoj.log. [A3.26] The compose file defines database, sandbox, search, computer and server services. [A3.28] The server service keeps config and model caches in named volumes. [A3.29] Phone routes need three Twilio settings to be set. [A11.22] [A11.23] Telemetry upload runs at 2 minute intervals. [A3.38]

## What it does not do

Unknown command-line arguments are logged and ignored. [A3.10] Without a code sandbox, the Python tool is hidden. [A4.33] The chat check raises an error unless the model is OpenAI, Anthropic or Google type. [A4.13] Web tools are hidden when web search is off. [A4.32] When the machine is offline, web search returns an empty result. [A10.2] A model name outside the Anthropic prefixes raises an error for the operator. [A10.28] Without a text-to-image model, image requests give status 501 and a setup message. [A11.1] Speech fails when the Eleven Labs key is not set. [A11.15] When memory mode is DISABLED, memory is off whatever the user chose. [A8.18] Deleting an agent the caller did not create removes nothing, yet the route replies "Agent deleted." [A6.21]

# Part 2: Appendix: technical detail

## A1 Surfaces

<!-- printed -->
entry | ENTRYPOINT ["python3", "src/khoj/main.py"] | Dockerfile:64
entry | service database | docker-compose.yml:2
entry | service sandbox | docker-compose.yml:15
entry | service search | docker-compose.yml:22
entry | service computer | docker-compose.yml:30
entry | service server | docker-compose.yml:40
entry | script docusaurus | documentation/package.json:6
entry | script start | documentation/package.json:7
entry | script build | documentation/package.json:8
entry | script swizzle | documentation/package.json:9
entry | script deploy | documentation/package.json:10
entry | script clear | documentation/package.json:11
entry | script serve | documentation/package.json:12
entry | script write-translations | documentation/package.json:13
entry | script write-heading-ids | documentation/package.json:14
entry | script khoj | pyproject.toml:107
entry | script bump_version.sh | scripts/bump_version.sh:1
entry | script gradlew | src/interface/android/gradlew:1
entry | main "main.js" | src/interface/desktop/package.json:10
entry | script start | src/interface/desktop/package.json:16
entry | script pre-commit | src/interface/web/.husky/pre-commit:1
entry | if __name__ == "__main__": | src/khoj/main.py:253
entry | if __name__ == "__main__": | src/khoj/manage.py:22
entry | if __name__ == "__main__": | src/telemetry/telemetry.py:69
flag | --destination | src/khoj/database/management/commands/change_generated_images_url.py:19
flag | --verbose | src/khoj/utils/cli.py:18
flag | --host | src/khoj/utils/cli.py:19
flag | --port | src/khoj/utils/cli.py:20
flag | --sslcert | src/khoj/utils/cli.py:26
flag | --sslkey | src/khoj/utils/cli.py:27
flag | --version | src/khoj/utils/cli.py:28
flag | --host | src/telemetry/telemetry.py:72
flag | --port | src/telemetry/telemetry.py:73
route | /self | src/khoj/routers/api.py:38
route | /search | src/khoj/routers/api.py:46
route | /update | src/khoj/routers/api.py:80
route | /transcribe | src/khoj/routers/api.py:108
route | /settings | src/khoj/routers/api.py:175
route | /user/name | src/khoj/routers/api.py:186
route | /user/memory | src/khoj/routers/api.py:218
route | /health | src/khoj/routers/api.py:241
route | /v1/user | src/khoj/routers/api.py:248
route | /conversation | src/khoj/routers/api_agents.py:106
route | /options | src/khoj/routers/api_agents.py:163
route | /{agent_slug} | src/khoj/routers/api_agents.py:193
route | /{agent_slug} | src/khoj/routers/api_agents.py:231
route | /hidden | src/khoj/routers/api_agents.py:254
route | /hidden | src/khoj/routers/api_agents.py:303
route | /trigger | src/khoj/routers/api_automation.py:124
route | /stats | src/khoj/routers/api_chat.py:109
route | /export | src/khoj/routers/api_chat.py:118
route | /conversation/file-filters/{conversation_id} | src/khoj/routers/api_chat.py:132
route | /conversation/file-filters/bulk | src/khoj/routers/api_chat.py:148
route | /conversation/file-filters/bulk | src/khoj/routers/api_chat.py:157
route | /conversation/file-filters | src/khoj/routers/api_chat.py:170
route | /conversation/file-filters | src/khoj/routers/api_chat.py:183
route | /feedback | src/khoj/routers/api_chat.py:192
route | /speech | src/khoj/routers/api_chat.py:199
route | /starters | src/khoj/routers/api_chat.py:226
route | /history | src/khoj/routers/api_chat.py:237
route | /share/history | src/khoj/routers/api_chat.py:302
route | /history | src/khoj/routers/api_chat.py:380
route | /share/fork | src/khoj/routers/api_chat.py:402
route | /share | src/khoj/routers/api_chat.py:443
route | /share | src/khoj/routers/api_chat.py:479
route | /sessions | src/khoj/routers/api_chat.py:506
route | /sessions | src/khoj/routers/api_chat.py:557
route | /options | src/khoj/routers/api_chat.py:587
route | /title | src/khoj/routers/api_chat.py:608
route | /title | src/khoj/routers/api_chat.py:638
route | /conversation/message | src/khoj/routers/api_chat.py:663
route | /ws | src/khoj/routers/api_chat.py:1489
route | /github | src/khoj/routers/api_content.py:119
route | /notion | src/khoj/routers/api_content.py:153
route | /github | src/khoj/routers/api_content.py:171
route | /notion | src/khoj/routers/api_content.py:201
route | /file | src/khoj/routers/api_content.py:235
route | /files | src/khoj/routers/api_content.py:262
route | /size | src/khoj/routers/api_content.py:285
route | /types | src/khoj/routers/api_content.py:297
route | /files | src/khoj/routers/api_content.py:308
route | /file | src/khoj/routers/api_content.py:346
route | /type/{content_type} | src/khoj/routers/api_content.py:379
route | /{content_source} | src/khoj/routers/api_content.py:409
route | /source/{content_source} | src/khoj/routers/api_content.py:428
route | /convert | src/khoj/routers/api_content.py:465
route | /{memory_id} | src/khoj/routers/api_memories.py:43
route | /{memory_id} | src/khoj/routers/api_memories.py:71
route | /chat/options | src/khoj/routers/api_model.py:22
route | /chat | src/khoj/routers/api_model.py:43
route | /chat | src/khoj/routers/api_model.py:59
route | /voice | src/khoj/routers/api_model.py:95
route | /paint | src/khoj/routers/api_model.py:130
route | /verify | src/khoj/routers/api_phone.py:62
route | /login | src/khoj/routers/auth.py:76
route | /login | src/khoj/routers/auth.py:82
route | /magic | src/khoj/routers/auth.py:88
route | /magic | src/khoj/routers/auth.py:123
route | /token | src/khoj/routers/auth.py:148
route | /token | src/khoj/routers/auth.py:162
route | /token | src/khoj/routers/auth.py:170
route | /redirect | src/khoj/routers/auth.py:177
route | /redirect | src/khoj/routers/auth.py:222
route | /logout | src/khoj/routers/auth.py:309
route | /oauth/metadata | src/khoj/routers/auth.py:315
route | /auth/callback | src/khoj/routers/notion.py:33
route | / | src/khoj/routers/web_client.py:21
route | / | src/khoj/routers/web_client.py:31
route | /home | src/khoj/routers/web_client.py:37
route | /home/{file_path:path} | src/khoj/routers/web_client.py:46
route | /search | src/khoj/routers/web_client.py:55
route | /chat | src/khoj/routers/web_client.py:61
route | /login | src/khoj/routers/web_client.py:67
route | /agents | src/khoj/routers/web_client.py:78
route | /settings | src/khoj/routers/web_client.py:83
route | /settings/content/github | src/khoj/routers/web_client.py:89
route | /share/chat/{public_conversation_slug} | src/khoj/routers/web_client.py:119
route | /automations | src/khoj/routers/web_client.py:124
route | /.well-known/assetlinks.json | src/khoj/routers/web_client.py:131
route | /server/error | src/khoj/routers/web_client.py:136
route | /v1/telemetry | src/telemetry/telemetry.py:21
event | closed | src/interface/desktop/main.js:543
event | update-state | src/interface/desktop/main.js:569
event | needsSubscription | src/interface/desktop/main.js:574
event | navigate | src/interface/desktop/main.js:579
event | navigateToWebApp | src/interface/desktop/main.js:583
event | ready | src/interface/desktop/main.js:625
event | closed | src/interface/desktop/main.js:658
event | continue-conversation-button-clicked | src/interface/desktop/main.js:662
event | activate | src/interface/desktop/main.js:671
event | window-all-closed | src/interface/desktop/main.js:676
event | did-finish-load | src/interface/desktop/main.js:704
event | closed | src/interface/desktop/main.js:715
event | clip | src/interface/desktop/preload.js:20
event | file-open | src/interface/obsidian/src/similar_view.ts:107
env | GUNICORN_WORKERS | gunicorn-config.py:6
env | GUNICORN_TIMEOUT | gunicorn-config.py:10
env | GUNICORN_GRACEFUL_TIMEOUT | gunicorn-config.py:11
env | GUNICORN_KEEP_ALIVE | gunicorn-config.py:12
env | APP_HOME | src/interface/android/gradlew:87
env | npm_package_version | src/interface/obsidian/version-bump.mjs:3
env | NEXT_PUBLIC_ENV | src/interface/web/next.config.mjs:3
env | KHOJ_DJANGO_SECRET_KEY | src/khoj/app/settings.py:26
env | KHOJ_DOMAIN | src/khoj/app/settings.py:29
env | KHOJ_ALLOWED_DOMAIN | src/khoj/app/settings.py:33
env | POSTGRES_DB | src/khoj/app/settings.py:122
env | POSTGRES_HOST | src/khoj/app/settings.py:123
env | POSTGRES_PORT | src/khoj/app/settings.py:124
env | PGSERVER_DATA_DIR | src/khoj/app/settings.py:142
env | POSTGRES_USER | src/khoj/app/settings.py:183
env | POSTGRES_PASSWORD | src/khoj/app/settings.py:185
env | EXA_API_KEY | src/khoj/database/adapters/__init__.py:1504
env | EXA_API_URL | src/khoj/database/adapters/__init__.py:1505
env | OLOSTEP_API_KEY | src/khoj/database/adapters/__init__.py:1514
env | OLOSTEP_API_URL | src/khoj/database/adapters/__init__.py:1515
env | FIRECRAWL_API_KEY | src/khoj/database/adapters/__init__.py:1524
env | FIRECRAWL_API_URL | src/khoj/database/adapters/__init__.py:1525
env | TOKENIZERS_PARALLELISM | src/khoj/main.py:121
env | KHOJ_LLM_SEED | src/khoj/processor/conversation/google/utils.py:216
env | PROMPTRACE_DIR | src/khoj/processor/conversation/utils.py:1096
env | KHOJ_OPERATOR_ITERATIONS | src/khoj/processor/operator/__init__.py:70
env | KHOJ_CDP_URL | src/khoj/processor/operator/operator_environment_browser.py:44
env | DISPLAY | src/khoj/processor/operator/operator_environment_computer.py:593
env | ELEVEN_LABS_API_KEY | src/khoj/processor/speech/text_to_speech.py:9
env | GOOGLE_SEARCH_API_KEY | src/khoj/processor/tools/online_search.py:38
env | GOOGLE_SEARCH_ENGINE_ID | src/khoj/processor/tools/online_search.py:39
env | SERPER_DEV_API_KEY | src/khoj/processor/tools/online_search.py:41
env | KHOJ_SEARXNG_URL | src/khoj/processor/tools/online_search.py:46
env | KHOJ_TERRARIUM_URL | src/khoj/processor/tools/run_code.py:43
env | E2B_API_KEY | src/khoj/processor/tools/run_code.py:237
env | E2B_TEMPLATE | src/khoj/processor/tools/run_code.py:238
env | STRIPE_API_KEY | src/khoj/routers/api_subscription.py:18
env | STRIPE_SIGNING_SECRET | src/khoj/routers/api_subscription.py:19
env | STRIPE_KHOJ_PRODUCT_ID | src/khoj/routers/api_subscription.py:20
env | RESEND_API_KEY | src/khoj/routers/auth.py:57
env | GOOGLE_CLIENT_ID | src/khoj/routers/auth.py:58
env | GOOGLE_CLIENT_SECRET | src/khoj/routers/auth.py:254
env | RESEND_AUDIENCE_ID | src/khoj/routers/email.py:16
env | RESEND_EMAIL | src/khoj/routers/email.py:45
env | NOTION_OAUTH_CLIENT_ID | src/khoj/routers/helpers.py:150
env | NOTION_OAUTH_CLIENT_SECRET | src/khoj/routers/helpers.py:151
env | NOTION_REDIRECT_URI | src/khoj/routers/helpers.py:152
env | KHOJ_CLOUD_SUBSCRIPTION_URL | src/khoj/routers/helpers.py:2998
env | KHOJ_RESEARCH_ITERATIONS | src/khoj/routers/research.py:498
env | AWS_ACCESS_KEY | src/khoj/routers/storage.py:7
env | AWS_SECRET_KEY | src/khoj/routers/storage.py:8
env | AWS_IMAGE_UPLOAD_BUCKET | src/khoj/routers/storage.py:12
env | AWS_USER_UPLOADED_IMAGES_BUCKET_NAME | src/khoj/routers/storage.py:13
env | TWILIO_ACCOUNT_SID | src/khoj/routers/twilio.py:8
env | TWILIO_AUTH_TOKEN | src/khoj/routers/twilio.py:9
env | TWILIO_VERIFICATION_SID | src/khoj/routers/twilio.py:10
env | KHOJ_ADMIN_EMAIL | src/khoj/utils/initialization.py:30
env | KHOJ_ADMIN_PASSWORD | src/khoj/utils/initialization.py:36
env | OPENAI_BASE_URL | src/khoj/utils/initialization.py:45
env | OPENAI_API_KEY | src/khoj/utils/initialization.py:47
env | GEMINI_API_KEY | src/khoj/utils/initialization.py:115
env | ANTHROPIC_API_KEY | src/khoj/utils/initialization.py:141
env | KHOJ_DEFAULT_CHAT_MODEL | src/khoj/utils/initialization.py:282
env | POSTHOG_API_KEY | src/telemetry/telemetry.py:18
config | pytest.ini | pytest.ini:1
manifest | Dockerfile | .devcontainer/Dockerfile:1
manifest | Dockerfile | Dockerfile:1
manifest | docker-compose.yml | docker-compose.yml:1
manifest | package.json | documentation/package.json:1
manifest | pyproject.toml | pyproject.toml:1
manifest | package.json | src/interface/desktop/package.json:1
manifest | package.json | src/interface/obsidian/package.json:1
manifest | package.json | src/interface/web/package.json:1
manifest | Dockerfile | src/telemetry/Dockerfile:1
doc | README.md | README.md:1
ci | / | .github/workflows/build_khoj_el.yml:30
ci | echo $GITHUB_REF && make -C ~/melpazoid | .github/workflows/build_khoj_el.yml:41
ci | / | .github/workflows/desktop.yml:37
ci | / | .github/workflows/desktop.yml:43
ci | / | .github/workflows/desktop.yml:53
ci | echo "version=$(pipx run hatch version)" >> $GITHUB_OUTPUT | .github/workflows/dockerize.yml:83
ci | rm -rf /opt/hostedtoolcache | .github/workflows/dockerize.yml:86
ci | / | .github/workflows/dockerize.yml:156
ci | / | .github/workflows/dockerize.yml:172
ci | / | .github/workflows/dockerize.yml:188
ci | / | .github/workflows/github_pages_deploy.yml:29
ci | / | .github/workflows/github_pages_deploy.yml:33
ci | uv python install 3.11 | .github/workflows/pre-commit.yml:44
ci | / | .github/workflows/pre-commit.yml:47
ci | uv sync --all-extras | .github/workflows/pre-commit.yml:55
ci | uv run pre-commit run --hook-stage manual --all | .github/workflows/pre-commit.yml:58
ci | uv python install 3.11.12 | .github/workflows/pypi.yml:43
ci | uv sync --all-extras | .github/workflows/pypi.yml:46
ci | / | .github/workflows/pypi.yml:54
ci | / | .github/workflows/pypi.yml:60
ci | / | .github/workflows/pypi.yml:70
ci | / | .github/workflows/release.yml:33
ci | uv python install 3.10 | .github/workflows/run_evals.yml:112
ci | / | .github/workflows/run_evals.yml:116
ci | / | .github/workflows/run_evals.yml:128
ci | / | .github/workflows/run_evals.yml:139
ci | / | .github/workflows/run_evals.yml:172
ci | / | .github/workflows/run_evals.yml:220
ci | uv python install ${{ matrix.python_version }} | .github/workflows/test.yml:63
ci | / | .github/workflows/test.yml:68
ci | sed -i 's/dynamic = \["version"\]/version = "0.0.0"/' pyproject.toml && uv sync --all-extr | .github/workflows/test.yml:82
ci | uv run pytest | .github/workflows/test.yml:92
ci | / | .github/workflows/test_khoj_el.yml:38
scout | api_chat | src/khoj/configure.py:324
scout | api_agents | src/khoj/configure.py:322
scout | api_automation | src/khoj/configure.py:323
scout | api_memories | src/khoj/configure.py:326
scout | api_content | src/khoj/configure.py:53
scout | api_model | src/khoj/configure.py:327
scout | api_phone | src/khoj/configure.py:354
scout | notion_router | src/khoj/configure.py:328
scout | text_to_entries | src/khoj/processor/content/docx/docx_to_entries.py:9
scout | text_search | src/khoj/routers/helpers.py:118
scout | search_online | src/khoj/processor/tools/online_search.py:56
scout | run_code | src/khoj/utils/helpers.py:434
scout | operate_environment | src/khoj/processor/operator/__init__.py:34
scout | text_to_image | src/khoj/processor/image/generate.py:41
scout | text_to_speech | src/khoj/routers/api_chat.py:48
scout | apick_next_tool | src/khoj/routers/research.py:277
<!-- /printed -->

## A2 Evidence

<!-- printed -->
tests found: 234 cases in 24 files
surfaces named in tests: 27 of 175 (command, flag, route, event and env rows)
never named in tests:
flag | --destination | src/khoj/database/management/commands/change_generated_images_url.py:19
flag | --verbose | src/khoj/utils/cli.py:18
flag | --host | src/khoj/utils/cli.py:19
flag | --port | src/khoj/utils/cli.py:20
flag | --sslcert | src/khoj/utils/cli.py:26
flag | --sslkey | src/khoj/utils/cli.py:27
flag | --version | src/khoj/utils/cli.py:28
flag | --host | src/telemetry/telemetry.py:72
flag | --port | src/telemetry/telemetry.py:73
route | /self | src/khoj/routers/api.py:38
route | /transcribe | src/khoj/routers/api.py:108
route | /settings | src/khoj/routers/api.py:175
route | /user/name | src/khoj/routers/api.py:186
route | /user/memory | src/khoj/routers/api.py:218
route | /health | src/khoj/routers/api.py:241
route | /v1/user | src/khoj/routers/api.py:248
route | /options | src/khoj/routers/api_agents.py:163
route | /{agent_slug} | src/khoj/routers/api_agents.py:193
route | /{agent_slug} | src/khoj/routers/api_agents.py:231
route | /hidden | src/khoj/routers/api_agents.py:254
route | /hidden | src/khoj/routers/api_agents.py:303
route | /stats | src/khoj/routers/api_chat.py:109
route | /conversation/file-filters/{conversation_id} | src/khoj/routers/api_chat.py:132
route | /conversation/file-filters/bulk | src/khoj/routers/api_chat.py:148
route | /conversation/file-filters/bulk | src/khoj/routers/api_chat.py:157
route | /feedback | src/khoj/routers/api_chat.py:192
route | /speech | src/khoj/routers/api_chat.py:199
route | /starters | src/khoj/routers/api_chat.py:226
route | /history | src/khoj/routers/api_chat.py:237
route | /share/history | src/khoj/routers/api_chat.py:302
route | /history | src/khoj/routers/api_chat.py:380
route | /share/fork | src/khoj/routers/api_chat.py:402
route | /share | src/khoj/routers/api_chat.py:443
route | /share | src/khoj/routers/api_chat.py:479
route | /sessions | src/khoj/routers/api_chat.py:506
route | /sessions | src/khoj/routers/api_chat.py:557
route | /options | src/khoj/routers/api_chat.py:587
route | /conversation/message | src/khoj/routers/api_chat.py:663
route | /ws | src/khoj/routers/api_chat.py:1489
route | /notion | src/khoj/routers/api_content.py:153
route | /notion | src/khoj/routers/api_content.py:201
route | /files | src/khoj/routers/api_content.py:262
route | /size | src/khoj/routers/api_content.py:285
route | /files | src/khoj/routers/api_content.py:308
route | /type/{content_type} | src/khoj/routers/api_content.py:379
route | /{content_source} | src/khoj/routers/api_content.py:409
route | /source/{content_source} | src/khoj/routers/api_content.py:428
route | /convert | src/khoj/routers/api_content.py:465
route | /{memory_id} | src/khoj/routers/api_memories.py:43
route | /{memory_id} | src/khoj/routers/api_memories.py:71
route | /chat/options | src/khoj/routers/api_model.py:22
route | /voice | src/khoj/routers/api_model.py:95
route | /paint | src/khoj/routers/api_model.py:130
route | /verify | src/khoj/routers/api_phone.py:62
route | /login | src/khoj/routers/auth.py:76
route | /login | src/khoj/routers/auth.py:82
route | /magic | src/khoj/routers/auth.py:88
route | /magic | src/khoj/routers/auth.py:123
route | /token | src/khoj/routers/auth.py:148
route | /token | src/khoj/routers/auth.py:162
route | /token | src/khoj/routers/auth.py:170
route | /redirect | src/khoj/routers/auth.py:177
route | /redirect | src/khoj/routers/auth.py:222
route | /logout | src/khoj/routers/auth.py:309
route | /oauth/metadata | src/khoj/routers/auth.py:315
route | /auth/callback | src/khoj/routers/notion.py:33
route | / | src/khoj/routers/web_client.py:21
route | / | src/khoj/routers/web_client.py:31
route | /home | src/khoj/routers/web_client.py:37
route | /home/{file_path:path} | src/khoj/routers/web_client.py:46
route | /login | src/khoj/routers/web_client.py:67
route | /agents | src/khoj/routers/web_client.py:78
route | /settings | src/khoj/routers/web_client.py:83
route | /settings/content/github | src/khoj/routers/web_client.py:89
route | /share/chat/{public_conversation_slug} | src/khoj/routers/web_client.py:119
route | /automations | src/khoj/routers/web_client.py:124
route | /.well-known/assetlinks.json | src/khoj/routers/web_client.py:131
route | /server/error | src/khoj/routers/web_client.py:136
route | /v1/telemetry | src/telemetry/telemetry.py:21
event | update-state | src/interface/desktop/main.js:569
event | needsSubscription | src/interface/desktop/main.js:574
event | navigate | src/interface/desktop/main.js:579
event | navigateToWebApp | src/interface/desktop/main.js:583
event | continue-conversation-button-clicked | src/interface/desktop/main.js:662
event | window-all-closed | src/interface/desktop/main.js:676
event | did-finish-load | src/interface/desktop/main.js:704
event | clip | src/interface/desktop/preload.js:20
event | file-open | src/interface/obsidian/src/similar_view.ts:107
env | GUNICORN_WORKERS | gunicorn-config.py:6
env | GUNICORN_TIMEOUT | gunicorn-config.py:10
env | GUNICORN_GRACEFUL_TIMEOUT | gunicorn-config.py:11
env | GUNICORN_KEEP_ALIVE | gunicorn-config.py:12
env | APP_HOME | src/interface/android/gradlew:87
env | npm_package_version | src/interface/obsidian/version-bump.mjs:3
env | NEXT_PUBLIC_ENV | src/interface/web/next.config.mjs:3
env | KHOJ_DJANGO_SECRET_KEY | src/khoj/app/settings.py:26
env | KHOJ_DOMAIN | src/khoj/app/settings.py:29
env | KHOJ_ALLOWED_DOMAIN | src/khoj/app/settings.py:33
env | POSTGRES_DB | src/khoj/app/settings.py:122
env | POSTGRES_HOST | src/khoj/app/settings.py:123
env | POSTGRES_PORT | src/khoj/app/settings.py:124
env | PGSERVER_DATA_DIR | src/khoj/app/settings.py:142
env | POSTGRES_USER | src/khoj/app/settings.py:183
env | POSTGRES_PASSWORD | src/khoj/app/settings.py:185
env | EXA_API_KEY | src/khoj/database/adapters/__init__.py:1504
env | EXA_API_URL | src/khoj/database/adapters/__init__.py:1505
env | OLOSTEP_API_URL | src/khoj/database/adapters/__init__.py:1515
env | FIRECRAWL_API_KEY | src/khoj/database/adapters/__init__.py:1524
env | FIRECRAWL_API_URL | src/khoj/database/adapters/__init__.py:1525
env | TOKENIZERS_PARALLELISM | src/khoj/main.py:121
env | KHOJ_LLM_SEED | src/khoj/processor/conversation/google/utils.py:216
env | PROMPTRACE_DIR | src/khoj/processor/conversation/utils.py:1096
env | KHOJ_OPERATOR_ITERATIONS | src/khoj/processor/operator/__init__.py:70
env | KHOJ_CDP_URL | src/khoj/processor/operator/operator_environment_browser.py:44
env | DISPLAY | src/khoj/processor/operator/operator_environment_computer.py:593
env | ELEVEN_LABS_API_KEY | src/khoj/processor/speech/text_to_speech.py:9
env | GOOGLE_SEARCH_API_KEY | src/khoj/processor/tools/online_search.py:38
env | GOOGLE_SEARCH_ENGINE_ID | src/khoj/processor/tools/online_search.py:39
env | SERPER_DEV_API_KEY | src/khoj/processor/tools/online_search.py:41
env | KHOJ_SEARXNG_URL | src/khoj/processor/tools/online_search.py:46
env | KHOJ_TERRARIUM_URL | src/khoj/processor/tools/run_code.py:43
env | E2B_API_KEY | src/khoj/processor/tools/run_code.py:237
env | E2B_TEMPLATE | src/khoj/processor/tools/run_code.py:238
env | STRIPE_API_KEY | src/khoj/routers/api_subscription.py:18
env | STRIPE_SIGNING_SECRET | src/khoj/routers/api_subscription.py:19
env | STRIPE_KHOJ_PRODUCT_ID | src/khoj/routers/api_subscription.py:20
env | RESEND_API_KEY | src/khoj/routers/auth.py:57
env | GOOGLE_CLIENT_ID | src/khoj/routers/auth.py:58
env | GOOGLE_CLIENT_SECRET | src/khoj/routers/auth.py:254
env | RESEND_AUDIENCE_ID | src/khoj/routers/email.py:16
env | RESEND_EMAIL | src/khoj/routers/email.py:45
env | NOTION_OAUTH_CLIENT_ID | src/khoj/routers/helpers.py:150
env | NOTION_OAUTH_CLIENT_SECRET | src/khoj/routers/helpers.py:151
env | NOTION_REDIRECT_URI | src/khoj/routers/helpers.py:152
env | KHOJ_CLOUD_SUBSCRIPTION_URL | src/khoj/routers/helpers.py:2998
env | KHOJ_RESEARCH_ITERATIONS | src/khoj/routers/research.py:498
env | AWS_ACCESS_KEY | src/khoj/routers/storage.py:7
env | AWS_SECRET_KEY | src/khoj/routers/storage.py:8
env | AWS_IMAGE_UPLOAD_BUCKET | src/khoj/routers/storage.py:12
env | AWS_USER_UPLOADED_IMAGES_BUCKET_NAME | src/khoj/routers/storage.py:13
env | TWILIO_ACCOUNT_SID | src/khoj/routers/twilio.py:8
env | TWILIO_AUTH_TOKEN | src/khoj/routers/twilio.py:9
env | TWILIO_VERIFICATION_SID | src/khoj/routers/twilio.py:10
env | KHOJ_ADMIN_EMAIL | src/khoj/utils/initialization.py:30
env | KHOJ_ADMIN_PASSWORD | src/khoj/utils/initialization.py:36
env | OPENAI_BASE_URL | src/khoj/utils/initialization.py:45
env | KHOJ_DEFAULT_CHAT_MODEL | src/khoj/utils/initialization.py:282
env | POSTHOG_API_KEY | src/telemetry/telemetry.py:18
<!-- /printed -->

## A3 The product as a whole

Khoj is a personal AI app that scales from an on-device assistant to a cloud-scale one (README). `README.md:44`

The README lists chat with local or online language models. `README.md:46`

The README also lists answers from the internet and your documents, and custom agents. `README.md:47` `README.md:49`

The README says you reach it from Browser, Obsidian, Emacs, Desktop, Phone or Whatsapp. `README.md:48`

The README calls it open-source and self-hostable. `README.md:53`

The `khoj` command runs `khoj.main:run`. `pyproject.toml:107`

`run` parses the command line, mounts the routes, and starts a background scheduler. `src/khoj/main.py:125` `src/khoj/main.py:185` `src/khoj/main.py:156`

The command line takes host, port, socket, certificate, key, verbose and anonymous-mode options, among others. `src/khoj/utils/cli.py:18-34`

The default host is 127.0.0.1 and the default port is 42110. `src/khoj/utils/cli.py:19-20`

Unknown command-line arguments are logged and ignored. `src/khoj/utils/cli.py:44-45`

The server is a FastAPI app, and `run` mounts Django at `/server`. `src/khoj/main.py:62` `src/khoj/main.py:119` `src/khoj/main.py:188`

Django owns the database models and the admin interface (Django README). `src/khoj/app/README.md:3`

`configure_routes` mounts the chat, agent, automation, model, memory, content and Notion routers under `/api`. `src/khoj/configure.py:319` `src/khoj/configure.py:331-338`

When anonymous mode is off, `configure_routes` also mounts the login routes at `/auth`. `src/khoj/configure.py:319` `src/khoj/configure.py:341-344`

When billing is enabled, it mounts subscription routes. `src/khoj/configure.py:347-350`

`configure_middleware` adds authentication and session middleware. `src/khoj/configure.py:403` `src/khoj/configure.py:406`

`initialize_server` builds an embeddings model and a cross-encoder model per search model it loads. `src/khoj/configure.py:253` `src/khoj/configure.py:264-287`

When that loading fails, it logs an error and startup continues. `src/khoj/configure.py:295-296`

The `EmbeddingsModel` and `CrossEncoderModel` classes live in the processor package. `src/khoj/processor/embeddings.py:29` `src/khoj/processor/embeddings.py:117`

Web search is implemented in `search_online`, and code execution in `run_code`. `src/khoj/processor/tools/online_search.py:56` `src/khoj/processor/tools/run_code.py:53`

Image generation lives in `text_to_image`. `src/khoj/processor/image/generate.py:41`

User, agent, chat model, conversation and entry records are Django models. `src/khoj/database/models/__init__.py:153` `src/khoj/database/models/__init__.py:248` `src/khoj/database/models/__init__.py:220` `src/khoj/database/models/__init__.py:658` `src/khoj/database/models/__init__.py:768`

The database engine is PostgreSQL, and its host, port, name, user and password default from environment variables. `src/khoj/app/settings.py:180` `src/khoj/app/settings.py:122-124` `src/khoj/app/settings.py:183-185`

When `USE_EMBEDDED_DB` is true, settings try to start an embedded Postgres with pgserver. `src/khoj/app/settings.py:127` `src/khoj/app/settings.py:148`

On import, `main.py` applies database migrations and collects static files. `src/khoj/main.py:53` `src/khoj/main.py:58`

The `--log-file` option defaults to `~/.khoj/khoj.log`. `src/khoj/utils/cli.py:14`

When non-interactive and the admin email or password is unset, admin creation logs an error and exits. `src/khoj/utils/initialization.py:30-34`

The compose file defines database, sandbox, search, computer and server services. `docker-compose.yml:2-40`

The server service keeps config and model caches in named volumes. `docker-compose.yml:59-61`

The compose server command passes host, port, verbosity, anonymous mode and non-interactive flags. `docker-compose.yml:125`

The Dockerfile builds the web app with bun and the server with pip. `Dockerfile:35` `Dockerfile:48`

The image entrypoint runs `src/khoj/main.py`. `Dockerfile:64`

The package needs Python 3.10 or later and below 3.13. `pyproject.toml:10`

When gunicorn is loaded, importing `main.py` calls `run` without starting the server. `src/khoj/main.py:256-257`

Without a leader lock, `run` sets one and starts the scheduler unpaused. `src/khoj/main.py:172-176`

When a leader lock exists, the scheduler starts paused. `src/khoj/main.py:170`

The index update job repeats at 22 to 25 hour intervals. `src/khoj/configure.py:417`

The telemetry upload runs at 2 minute intervals, and returns early when telemetry is disabled or empty. `src/khoj/configure.py:433` `src/khoj/configure.py:436`

## A4 Chat and research

The app mounts the chat router under `/api/chat`. `src/khoj/configure.py:332`

`POST /api/chat` requires an authenticated user. `src/khoj/routers/api_chat.py:1733-1734`
It allows 20 requests a minute to trial and subscribed users alike. `src/khoj/routers/api_chat.py:1740`
It allows 100 requests a day to trial users and 600 to subscribed users. `src/khoj/routers/api_chat.py:1743`
When `body.stream` is set, it streams `text/plain`. `src/khoj/routers/api_chat.py:1756-1757`
When `body.stream` is not set, it returns the whole stream as JSON. `src/khoj/routers/api_chat.py:1760-1761`

The `/ws` websocket route closes with code 1008 when the origin is missing or not in `ALLOWED_HOSTS`. `src/khoj/routers/api_chat.py:1489` `src/khoj/routers/api_chat.py:1497-1498`
It also closes with 1008 when the user has too many connections. `src/khoj/routers/api_chat.py:1506-1507`
The limits are 5 connections for trial users and 10 for subscribed users. `src/khoj/routers/api_chat.py:1503`

When the query is empty, a turn replies with a prompt to ask and ends. `src/khoj/routers/api_chat.py:930-933`
When no conversation matches, a turn replies that it was not found and ends. `src/khoj/routers/api_chat.py:951-955`
Past those checks, a turn verifies the user's chat model. `src/khoj/routers/api_chat.py:970`
That check raises HTTP 500 unless the model is OpenAI, Anthropic or Google type with an API configured. `src/khoj/routers/helpers.py:174-188`
When the commands are just the default, a model call picks data sources and output format. `src/khoj/routers/api_chat.py:1002`
When that call raises `ValueError`, the turn falls back to the General source and Text output. `src/khoj/routers/api_chat.py:1014`
When the picked commands include Research, they shrink to Research alone. `src/khoj/routers/api_chat.py:1019-1020`
Research is the one command in the rate limiter's restricted list. `src/khoj/routers/helpers.py:2344`
That limit applies when billing is enabled and the user is authenticated. `src/khoj/routers/helpers.py:2347-2351`
A limited user gets the limit message as the reply and the turn ends. `src/khoj/routers/api_chat.py:1032-1034`

`research` runs when the commands are exactly Research. `src/khoj/routers/api_chat.py:1038-1039`
Its loop continues while the iteration count is below `KHOJ_RESEARCH_ITERATIONS`, default 5. `src/khoj/routers/research.py:498` `src/khoj/routers/research.py:511`
It stops when the cancellation event is set. `src/khoj/routers/research.py:513-515`
When a non-abort interrupt message arrives, it becomes the new query. `src/khoj/routers/research.py:531`
When the interrupt equals the abort message, research stops. `src/khoj/routers/research.py:519-522`
On each loop pass, `research` calls `apick_next_tool` for tool choices. `src/khoj/routers/research.py:539`
It runs `OperateComputer` calls one by one and the other tools in parallel. `src/khoj/routers/research.py:565` `src/khoj/routers/research.py:645`
When a tool result sets `should_terminate`, the iteration count jumps to the maximum. `src/khoj/routers/research.py:660-661`
A finished iteration without results gets "Failed to get results." as its summary. `src/khoj/routers/research.py:697-699`

When the last iteration is an unfinished Operator call, `apick_next_tool` reuses it with the new query. `src/khoj/routers/research.py:277` `src/khoj/routers/research.py:299-315`

`apick_next_tool` hides document tools when the user has zero entries. `src/khoj/routers/research.py:277` `src/khoj/routers/research.py:342-348`
It hides the operator tool unless the operator is enabled. `src/khoj/routers/research.py:345-346`
It hides web tools when web search is off. `src/khoj/routers/research.py:351-352`
It hides the Python tool without a code sandbox. `src/khoj/routers/research.py:354-355`
When the agent's input tools map to no research tools, no agent filter applies. `src/khoj/routers/research.py:366`
MCP tools are offered under the server name plus the tool name. `src/khoj/routers/research.py:381`
An MCP server that fails to list its tools is logged and skipped. `src/khoj/routers/research.py:391`
When the planning model call raises, it yields an iteration with a "Skipping iteration" warning. `src/khoj/routers/research.py:431-435`
When the reply does not parse as tool calls, it becomes one Text tool call. `src/khoj/routers/research.py:441-444`
A tool and argument pair already used gets a "Repeated tool" warning. `src/khoj/routers/research.py:464-466`

## A5 Indexing and searching your content

The `put_content` route calls `indexer` with regenerate set to true. `src/khoj/routers/api_content.py:77` `src/khoj/routers/api_content.py:94`

The `patch_content` route calls `indexer` with regenerate set to false. `src/khoj/routers/api_content.py:99` `src/khoj/routers/api_content.py:116`

The `indexer` function sorts uploaded files into org, markdown, pdf, plaintext, image and docx groups by detected type. `src/khoj/routers/api_content.py:556-563` `src/khoj/routers/api_content.py:568-570`

When a file's type is not one of those groups, `indexer` skips it and logs at debug level. `src/khoj/routers/api_content.py:572-573`

On success, `indexer` returns the indexed file names, comma-joined, with status 200. `src/khoj/routers/api_content.py:544` `src/khoj/routers/api_content.py:626-627`

When indexing raises an error or reports failure, `indexer` returns the body "Failed" with status 500. `src/khoj/routers/api_content.py:544` `src/khoj/routers/api_content.py:593-594` `src/khoj/routers/api_content.py:602`

The `convert_documents` route skips files over 10 MB and logs a warning. `src/khoj/routers/api_content.py:472-473` `src/khoj/routers/api_content.py:485-489`

For pdf and docx files, `convert_documents` prefixes pages with "Page N of" and the file name. `src/khoj/routers/api_content.py:467` `src/khoj/routers/api_content.py:499-502` `src/khoj/routers/api_content.py:504-509`

The `/files` route returns 10 files per page. It cuts `raw_text` to 1000 characters when `truncated` is true. `src/khoj/routers/api_content.py:323` `src/khoj/routers/api_content.py:333`

The `/size` route returns the indexed data size in megabytes, rounded up. `src/khoj/routers/api_content.py:291`

When the content type is not a `SearchType` value, `delete_content_type` raises `ValueError`. `src/khoj/routers/api_content.py:387-388`

After saving the token, `set_content_notion` queues Notion indexing in the background when the token is non-empty. `src/khoj/routers/api_content.py:220-222`

The `set_content_github` route returns status 500 when saving the GitHub config fails. `src/khoj/routers/api_content.py:186-188`

When `code` or `state` is missing, `notion_auth_callback` returns status 400. `src/khoj/routers/notion.py:35` `src/khoj/routers/notion.py:38-39`

When `state` differs from the user's UUID, `notion_auth_callback` returns status 400. `src/khoj/routers/notion.py:35` `src/khoj/routers/notion.py:45-47`

Otherwise `notion_auth_callback` posts the code to the Notion token endpoint and saves the returned token. `src/khoj/routers/notion.py:35` `src/khoj/routers/notion.py:66` `src/khoj/routers/notion.py:71`

It then queues Notion indexing and redirects to the config page. `src/khoj/routers/notion.py:85` `src/khoj/routers/notion.py:87`

When the GitHub token is empty, `process` logs a warning, then calls `process_repo` for the configured repos. `src/khoj/processor/content/github/github_to_entries.py:53-59`

The `split_entries_by_max_tokens` method skips entries whose compiled text is empty. `src/khoj/processor/content/text_to_entries.py:67-68`

It splits compiled text into chunks of at most `max_tokens` whitespace-separated words, 256 by default. `src/khoj/processor/content/text_to_entries.py:62` `src/khoj/processor/content/text_to_entries.py:72-76`

For chunks after the first, it prepends the heading's last 100 characters, when the entry has a heading. `src/khoj/processor/content/text_to_entries.py:112-117`

It drops words longer than `max_word_length`, 500 by default. `src/khoj/processor/content/text_to_entries.py:62` `src/khoj/processor/content/text_to_entries.py:120` `src/khoj/processor/content/text_to_entries.py:50`

When `regenerate` is true, `update_embeddings` first deletes the user's entries of that file type. `src/khoj/processor/content/text_to_entries.py:142` `src/khoj/processor/content/text_to_entries.py:162-165`

It embeds entries whose hash is missing from the user's stored entries of that file type. `src/khoj/processor/content/text_to_entries.py:171-175`

It writes new entries to the database in batches of up to 200. `src/khoj/processor/content/text_to_entries.py:202`

The `query` function asks the database for at most 10 hits. `src/khoj/search_type/text_search.py:125` `src/khoj/search_type/text_search.py:130`

Without a `max_distance` argument, `query` uses the model's bi-encoder confidence threshold, else infinity. `src/khoj/search_type/text_search.py:113-117`

When `dedupe` is true, `collate_results` skips hits whose hash or corpus id was already seen. `src/khoj/search_type/text_search.py:145`

Reranking needs more than one hit, plus a rerank request or an enabled inference server. `src/khoj/search_type/text_search.py:195-197`

When the inference endpoint raises an HTTP error, `cross_encoder_score` logs it and uses scores of 0.0. `src/khoj/search_type/text_search.py:240-242`

Results sort by bi-encoder score, then by cross-encoder score when reranking. `src/khoj/search_type/text_search.py:254-256`

In `WordFilter`, `+"word"` marks a required term and `-"word"` a blocked term. `src/khoj/search_filter/word_filter.py:14-15`

In `FileFilter`, `file:"name"` requires a file and `-file:"name"` excludes one. `src/khoj/search_filter/file_filter.py:13-14`

## A6 Agents

An agent has a name, personality, chat model, slug, input tools and output modes. `src/khoj/database/models/__init__.py:318-328`
Privacy level is public, private or protected, and defaults to private. `src/khoj/database/models/__init__.py:297-300` `src/khoj/database/models/__init__.py:331`
Input tools are general, online, notes, webpage or code. `src/khoj/database/models/__init__.py:302-308`
Output modes are image or diagram. `src/khoj/database/models/__init__.py:310-313`
When saved with no creator, an agent is marked managed by admin. `src/khoj/database/models/__init__.py:337-338`
When a new agent has no slug, save builds one from its name and six random digits. `src/khoj/database/models/__init__.py:340-343`

The router root lists agents. For a signed-in user, it holds public admin-managed agents and the user's own non-hidden agents. `src/khoj/database/adapters/__init__.py:734-743`
Without a signed-in user, the list holds only public admin-managed agents. `src/khoj/database/adapters/__init__.py:735-737` `src/khoj/database/adapters/__init__.py:748-749`
The list puts the default agent first when it is among those agents. `src/khoj/routers/api_agents.py:100-101`
For a signed-in user, other agents sort by latest conversation, from the 50 newest within two weeks. `src/khoj/routers/api_agents.py:87-99`
Agents with no recent conversation come in random order. `src/khoj/routers/api_agents.py:98-99`
Entries show the chat model's friendly name and the attached file names. `src/khoj/routers/api_agents.py:63-65` `src/khoj/routers/api_agents.py:75-76`
The options route returns input tools and output modes with their descriptions. `src/khoj/routers/api_agents.py:168-190`
Getting one agent by slug returns 404 unless it is public, protected or the caller's own. `src/khoj/routers/api_agents.py:200-207` `src/khoj/database/adapters/__init__.py:682-685`

Getting an agent by conversation id requires authentication and returns 404 for an unknown conversation. `src/khoj/routers/api_agents.py:107` `src/khoj/routers/api_agents.py:117-122`
When that conversation has no agent, the default agent is returned. `src/khoj/routers/api_agents.py:123-126`
That route returns a null chat model unless the user is premium or the model is free tier. `src/khoj/routers/api_agents.py:136-139`

Deleting requires authentication and returns 404 when no matching agent is found for the user. `src/khoj/routers/api_agents.py:232` `src/khoj/routers/api_agents.py:242-247`
When the caller is the creator, deleting also removes the agent's entries. `src/khoj/database/adapters/__init__.py:695-701`
Deleting an agent the caller did not create removes nothing, yet the route replies "Agent deleted." `src/khoj/database/adapters/__init__.py:695-696` `src/khoj/routers/api_agents.py:249-251`

Creating an agent requires authentication and runs a prompt check on the persona first. `src/khoj/routers/api_agents.py:367` `src/khoj/routers/api_agents.py:375-377`
A persona that fails the check returns 400 with the reason. `src/khoj/routers/api_agents.py:379-384`
The named chat model is used when the user is premium or the model is free tier. `src/khoj/routers/api_agents.py:386-389`
Otherwise the user's default chat model is used. `src/khoj/routers/api_agents.py:391` `src/khoj/database/adapters/__init__.py:928-929`
Saving updates the caller's agent with the given slug, or creates one. `src/khoj/database/adapters/__init__.py:862`
Saving deletes the agent's existing file objects and entries. `src/khoj/database/adapters/__init__.py:877-878`
It then copies the caller's unattached files and entries that match the files list. `src/khoj/database/adapters/__init__.py:881-889`
A ValidationError from saving answers 400, giving its message. `src/khoj/routers/api_agents.py:408-413`

Updating by PATCH returns 404 when that slug is not found for the caller. `src/khoj/routers/api_agents.py:444-451`
Update checks the persona when it differs from the stored persona. `src/khoj/routers/api_agents.py:453-464`
Update does not pass is_hidden, so the saved agent becomes not hidden. `src/khoj/routers/api_agents.py:474-486` `src/khoj/database/adapters/__init__.py:860` `src/khoj/database/adapters/__init__.py:873`

Creating a hidden agent returns 404 when the conversation id is not the user's. `src/khoj/routers/api_agents.py:320-326`
It returns 400 when the conversation already has an agent other than the default. `src/khoj/routers/api_agents.py:328-337`
A new hidden agent gets a random internal name. `src/khoj/database/adapters/__init__.py:962`
A hidden agent is saved private, blue, Lightbulb, with an empty files list. `src/khoj/database/adapters/__init__.py:968-976`
The conversation is then pointed at the new agent. `src/khoj/routers/api_agents.py:350-351`
Patching a hidden agent returns 404 when the slug is not found for the caller. `src/khoj/routers/api_agents.py:270-277`

## A7 Automations

An automation runs a query on a cron schedule and sends the result.

The `api_automation` router is mounted at `/api/automation`. `src/khoj/configure.py:334`

GET returns the signed-in user's automations as JSON. `src/khoj/routers/api_automation.py:31-34`

When deleting succeeds, DELETE returns the deleted automation's JSON. `src/khoj/routers/api_automation.py:43-48`

When deleting raises a ValueError, DELETE returns status 204. `src/khoj/routers/api_automation.py:44-45`

POST returns 400 when `q` or `crontime` is empty. `src/khoj/routers/api_automation.py:66-67`

POST returns 400 "Invalid crontime" when `cron_descriptor` returns an empty description. `src/khoj/routers/api_automation.py:68-69`

POST uses a given `subject`, else the one `schedule_query` generates. `src/khoj/routers/api_automation.py:72-73`

POST prefixes the query with `/automated_task` when it lacks that prefix. `src/khoj/routers/api_automation.py:78-79`

When `crontime` has over 5 fields, POST keeps the first 5. `src/khoj/routers/api_automation.py:83-85`

POST swaps `?` for `*` in `crontime`. `src/khoj/routers/api_automation.py:88`

POST returns 400 when the minute field of `crontime` is not digits. `src/khoj/routers/api_automation.py:91-96`

POST creates a conversation titled "Automation: <subject>" for the new automation. `src/khoj/routers/api_automation.py:99-100`

When `schedule_automation` raises, POST logs it and returns 500. `src/khoj/routers/api_automation.py:106-115`

Otherwise POST returns the new automation's metadata as JSON. `src/khoj/routers/api_automation.py:118-121`

POST `/trigger` returns 403 "Invalid automation" when the lookup raises a ValueError. `src/khoj/routers/api_automation.py:133-137`

Otherwise POST `/trigger` runs the job's function in a new thread. `src/khoj/routers/api_automation.py:143-146`

PUT returns 400 when `q`, `subject` or `crontime` is empty. `src/khoj/routers/api_automation.py:165-166`

PUT returns 403 when the automation lookup raises a ValueError. `src/khoj/routers/api_automation.py:171-175`

When the stored job has no `conversation_id`, PUT creates a conversation for it. `src/khoj/routers/api_automation.py:210-217`

When the new trigger differs from the old one, PUT reschedules the job. `src/khoj/routers/api_automation.py:235-236`

`schedule_automation` adds a job to `state.scheduler` that calls `run_with_process_lock`. `src/khoj/routers/helpers.py:2638,2675-2681`

Its job id is `automation_` plus the user uuid and an md5 of query and crontime. `src/khoj/routers/helpers.py:2673-2674`

When the minute field is not digits, it swaps in a random minute. `src/khoj/routers/helpers.py:2649-2652`

When the timezone is unknown, it logs a warning and uses UTC. `src/khoj/routers/helpers.py:2656-2659`

It sets the trigger jitter to 60. `src/khoj/routers/helpers.py:2662`

`create_automation` infers crontime, query and subject with `aschedule_query`, then schedules the job. `src/khoj/routers/helpers.py:2624-2634`

When given a `job_id` and a last run under six hours old, `scheduled_chat` returns without running. `src/khoj/routers/helpers.py:2524,2534-2546`

When a `conversation_id` is given and the conversation is missing, `scheduled_chat` deletes the automation. `src/khoj/routers/helpers.py:2524,2559-2567`

`scheduled_chat` posts the query as JSON to the `/api/chat?client=khoj` URL. `src/khoj/routers/helpers.py:2524,2573-2587`

When the chat call returns a status other than 200, `scheduled_chat` logs an error. `src/khoj/routers/helpers.py:2524,2596-2598`

`should_notify` returns False when the query or the response is empty. `src/khoj/routers/helpers.py:2494-2495`

When the model call fails, `should_notify` returns True. `src/khoj/routers/helpers.py:2516-2521`

When `should_notify` is true and Resend is enabled, `scheduled_chat` emails the result. `src/khoj/routers/helpers.py:2524,2613-2619`

The app starts a `BackgroundScheduler` with UTC, a 60 second misfire grace and coalescing. `src/khoj/main.py:156-162`

When a schedule leader lock already exists, the scheduler starts paused. `src/khoj/main.py:167-170`

## A8 Memories

Khoj keeps facts about a user as memories, stored per user and listed, edited or deleted through `api_memories`.

A `UserMemory` row has a user, an optional agent, an embedding and `raw` text. `src/khoj/database/models/__init__.py:860-863`

The model's docstring calls it a long term memory store derived from conversation (code comment). `src/khoj/database/models/__init__.py:857`

The `api_memories` router is mounted at `/api/memories`. `src/khoj/configure.py:336`

Listing, deleting and updating a memory require an authenticated user. `src/khoj/routers/api_memories.py:19` `src/khoj/routers/api_memories.py:44` `src/khoj/routers/api_memories.py:72`

`GET /api/memories` returns the user's memories as JSON with `id`, `raw` and `created_at`. `src/khoj/routers/api_memories.py:27` `src/khoj/routers/api_memories.py:33-35` `src/khoj/routers/api_memories.py:40`

`DELETE /api/memories/{memory_id}` returns 404 when the user has no memory with that id. `src/khoj/routers/api_memories.py:54-58`

Otherwise it deletes the memory and returns 204. `src/khoj/routers/api_memories.py:60-62`

`PUT /api/memories/{memory_id}` takes a JSON body with a string `raw`. `src/khoj/routers/api_memories.py:65-68`

When the user has no memory with that id, `PUT` returns 404. `src/khoj/routers/api_memories.py:83-87` `src/khoj/routers/api_memories.py:71`

When `raw` is empty, `PUT` returns 400 with "Missing required field 'raw'". `src/khoj/routers/api_memories.py:90-95` `src/khoj/routers/api_memories.py:71`

Otherwise `PUT` deletes the old row and saves the text as a new memory. `src/khoj/routers/api_memories.py:97-103` `src/khoj/routers/api_memories.py:71`

`PUT` passes no agent, so the new memory has none. `src/khoj/routers/api_memories.py:100-103` `src/khoj/routers/api_memories.py:71`

`PUT` answers 200 with the new memory's `id` and `raw`. `src/khoj/routers/api_memories.py:105-113` `src/khoj/routers/api_memories.py:71`

`save_memory` embeds the text with the default search model, then creates the row. `src/khoj/database/adapters/__init__.py:2316-2317` `src/khoj/database/adapters/__init__.py:2324`

`save_memory` sets the agent when one is given and it is not the default agent. `src/khoj/database/adapters/__init__.py:2311` `src/khoj/database/adapters/__init__.py:2319-2321`

`PATCH /api/user/memory` sets the user's `enable_memory` to the `enable_memory` query value. `src/khoj/routers/api.py:218` `src/khoj/routers/api.py:227-229`

When the server `memory_mode` is DISABLED, memory is off whatever the user chose. `src/khoj/database/adapters/__init__.py:1638-1639`

With ENABLED_DEFAULT_OFF, a user with no saved config has memory off. `src/khoj/database/adapters/__init__.py:1644-1647`

With no server settings row, memory is on unless the user's `enable_memory` is false. `src/khoj/database/adapters/__init__.py:1656-1659`

When memory is enabled, a chat query loads recent and long term memories. `src/khoj/routers/api_chat.py:979-981`

When memory is disabled, `relevant_memories` stays empty. `src/khoj/routers/api_chat.py:978-979`

Chat de-duplicates the two lists by memory id. `src/khoj/routers/api_chat.py:983`

`pull_memories` defaults to 10 memories updated in the last 7 days, newest first. `src/khoj/database/adapters/__init__.py:2295` `src/khoj/database/adapters/__init__.py:2306`

`search_memories` orders memories by cosine distance to the query embedding, closest first. `src/khoj/database/adapters/__init__.py:2332` `src/khoj/database/adapters/__init__.py:2347-2349`

`search_memories` drops memories beyond the search model's `bi_encoder_confidence_threshold`, when set. `src/khoj/database/adapters/__init__.py:2338` `src/khoj/database/adapters/__init__.py:2350`

For a non-default agent, both lookups keep that agent's memories. `src/khoj/database/adapters/__init__.py:2301-2302` `src/khoj/database/adapters/__init__.py:2342-2343`

`save_to_conversation_log` calls `ai_update_memories` unless the turn has an `automation_id`. `src/khoj/processor/conversation/utils.py:541` `src/khoj/processor/conversation/utils.py:612-614`

`ai_update_memories` returns early when memory is disabled for the user. `src/khoj/routers/helpers.py:1038` `src/khoj/routers/helpers.py:1049-1050`

Otherwise it saves the facts in the model's `create` list as a new memory. `src/khoj/routers/helpers.py:1060-1062`

It calls `delete_memory` with the entries of the model's `delete` list as ids. `src/khoj/routers/helpers.py:1064-1066`

`delete_memory` returns False when no memory with that id exists for the user. `src/khoj/database/adapters/__init__.py:2362-2366`

When the model's reply cannot be parsed, `extract_facts_from_query` returns no facts to create or delete. `src/khoj/routers/helpers.py:994` `src/khoj/routers/helpers.py:1032-1034`

## A9 Choosing models

The `api_model` router is mounted at `/api/model`. `src/khoj/configure.py:335`

`GET /chat/options` lists chat models with their name, id, strengths and description. `src/khoj/routers/api_model.py:27-36`

`GET /chat` requires an authenticated user. `src/khoj/routers/api_model.py:44`

`GET /chat` returns the id and friendly name of the model that `get_chat_model` picks. `src/khoj/routers/api_model.py:51-56`

`POST /chat`, `POST /voice` and `POST /paint` take an `id` and need an authenticated user. `src/khoj/routers/api_model.py:59-60` `src/khoj/routers/api_model.py:95-96` `src/khoj/routers/api_model.py:130-131`

When the id is not a stored chat model, `POST /chat` answers 404. `src/khoj/routers/api_model.py:59` `src/khoj/routers/api_model.py:71-72`

When the caller lacks the premium scope and the chat model is not free, `POST /chat` answers 403. `src/khoj/routers/api_model.py:59` `src/khoj/routers/api_model.py:73-75`

When both checks pass, `POST /chat` calls `aset_user_conversation_processor`, which stores the user's setting. `src/khoj/routers/api_model.py:59` `src/khoj/routers/api_model.py:79` `src/khoj/database/adapters/__init__.py:1183`

`POST /voice` looks the voice model up by its `model_id`. `src/khoj/routers/api_model.py:95` `src/khoj/routers/api_model.py:106`

When the id is not a stored voice model, `POST /voice` answers 404. `src/khoj/routers/api_model.py:95` `src/khoj/routers/api_model.py:107-108`

When the caller lacks the premium scope and the voice model is not free, `POST /voice` answers 403. `src/khoj/routers/api_model.py:95` `src/khoj/routers/api_model.py:109-111`

When the voice choice is saved, `POST /voice` answers 202. `src/khoj/routers/api_model.py:95` `src/khoj/routers/api_model.py:124-127`

When the id is not a stored image model, `POST /paint` answers 404. `src/khoj/routers/api_model.py:130` `src/khoj/routers/api_model.py:142-143`

When the caller lacks the premium scope and the image model is not free, `POST /paint` answers 403. `src/khoj/routers/api_model.py:130` `src/khoj/routers/api_model.py:144-146`

For a subscribed user, `get_chat_model` returns the user's saved model when one is set. `src/khoj/database/adapters/__init__.py:1199-1202`

For a subscribed user without a saved model, `get_chat_model` calls `get_advanced_chat_model`. `src/khoj/database/adapters/__init__.py:1204`

For other users, `get_chat_model` returns the saved model when it is set and free. `src/khoj/database/adapters/__init__.py:1207-1208`

Otherwise those users get `get_default_chat_model`. `src/khoj/database/adapters/__init__.py:1210`

In `get_default_chat_model`, a subscribed user gets the server's `chat_advanced` model when it is set. `src/khoj/database/adapters/__init__.py:1280-1281`

After that it returns the server's `chat_default` model when it is set. `src/khoj/database/adapters/__init__.py:1283-1284`

After that it returns the user's saved model when one is set. `src/khoj/database/adapters/__init__.py:1288-1289`

Last it returns the first chat model in the database. `src/khoj/database/adapters/__init__.py:1292`

A `ChatModel` has a provider type of openai, anthropic or google. `src/khoj/database/models/__init__.py:220-224`

A `ChatModel` provider type defaults to google, and its price tier to free. `src/khoj/database/models/__init__.py:220` `src/khoj/database/models/__init__.py:231-232`

A `VoiceModelOption` has a `model_id` and a price tier that defaults to standard. `src/khoj/database/models/__init__.py:243-245`

A `TextToImageModelConfig` provider type is openai, replicate or google, defaulting to openai. `src/khoj/database/models/__init__.py:589-596`

Without a staff user and without a default chat model, `initialization` runs chat setup. `src/khoj/utils/initialization.py:255` `src/khoj/utils/initialization.py:264-268`

In non-interactive mode, a provider's chat models are added when its default API key is present. `src/khoj/utils/initialization.py:162-168`

When chat setup does not run, `initialization` calls `_update_chat_model_options` for providers named Ollama. `src/khoj/utils/initialization.py:218` `src/khoj/utils/initialization.py:277`

`initialization` reads `KHOJ_DEFAULT_CHAT_MODEL` when a default chat model already exists. `src/khoj/utils/initialization.py:282-284`

When that name differs from the default and matches a stored model, `initialization` makes it the default. `src/khoj/utils/initialization.py:285-292`

`set_default_chat_model` sets both `chat_default` and `chat_advanced` to that model. `src/khoj/database/adapters/__init__.py:1394-1395`

## A10 Web search, code and computer tools

`search_online` appends the custom filters to the query. `src/khoj/processor/tools/online_search.py:73`
When the machine is offline, `search_online` logs a warning and yields an empty dict. `src/khoj/processor/tools/online_search.py:74-77`
When online, it passes `max_online_searches`, which defaults to 3, to the subquery generator. `src/khoj/processor/tools/online_search.py:63` `src/khoj/processor/tools/online_search.py:88`
It drops subqueries already in `previous_subqueries`. `src/khoj/processor/tools/online_search.py:93`
When no new subqueries remain, it yields an empty result and stops. `src/khoj/processor/tools/online_search.py:96-99`
Engines are listed as Serper, Exa, Firecrawl, Google, SearXNG, each added when its key or URL is set. `src/khoj/processor/tools/online_search.py:102-116`
It stops at the first engine that returns non-empty results. `src/khoj/processor/tools/online_search.py:131-132`
When an engine raises, it logs the error and tries the next engine. `src/khoj/processor/tools/online_search.py:133-135`
When `KHOJ_AUTO_READ_WEBPAGE` is not true, it yields the search results without reading pages. `src/khoj/processor/tools/online_search.py:137-139`
When auto-read is on, it skips subqueries that have an answer box. `src/khoj/processor/tools/online_search.py:144-145`
It collects the first `max_webpages_to_read` organic links per subquery to read; the default is 1. `src/khoj/processor/tools/online_search.py:64` `src/khoj/processor/tools/online_search.py:151`

`read_webpages` asks a model to infer the URLs to read from the query. `src/khoj/processor/tools/online_search.py:456`
`read_webpages_content` yields the extracts under the query's `webpages` list. `src/khoj/processor/tools/online_search.py:480` `src/khoj/processor/tools/online_search.py:501`
When no content is passed, `extract_from_webpage` scrapes the page first. `src/khoj/processor/tools/online_search.py:558-559`
The scrape tries the enabled web scrapers in order until one returns content. `src/khoj/processor/tools/online_search.py:533-538`
For internal URLs, the scrape keeps scrapers of the direct type. `src/khoj/processor/tools/online_search.py:527-528`
The direct scraper sends a GET request and converts the page body to markdown. `src/khoj/processor/tools/online_search.py:578-583`

`run_code` asks a model to generate Python code and input files. `src/khoj/processor/tools/run_code.py:73`
When generation fails, `run_code` raises a `ValueError`. `src/khoj/processor/tools/run_code.py:85-86`
When `E2B_API_KEY` is set, it tries an E2B sandbox first. `src/khoj/utils/helpers.py:333` `src/khoj/processor/tools/run_code.py:224-226`
When the E2B sandbox is off, it posts to the URL in `KHOJ_TERRARIUM_URL`. `src/khoj/processor/tools/run_code.py:43` `src/khoj/processor/tools/run_code.py:229`
The Terrarium request times out after 30 seconds. `src/khoj/processor/tools/run_code.py:329`
When Terrarium returns a status other than 200, the result has `success` False. `src/khoj/processor/tools/run_code.py:330` `src/khoj/processor/tools/run_code.py:342-346`
On a timeout, `run_code` calls the `/stop` URL and raises a `ValueError`. `src/khoj/processor/tools/run_code.py:109-116`

`operate_environment` defaults to the computer environment type. `src/khoj/processor/operator/__init__.py:34` `src/khoj/processor/operator/__init__.py:40`
When no vision-enabled chat model exists, it raises a `ValueError`. `src/khoj/processor/operator/__init__.py:60-63`
Model names starting with `claude-sonnet-4` select the Anthropic operator agent. `src/khoj/processor/operator/__init__.py:237` `src/khoj/processor/operator/__init__.py:72-73`
A model name outside the Anthropic prefixes raises a `ValueError`. `src/khoj/processor/operator/__init__.py:117`
The iteration limit is `KHOJ_OPERATOR_ITERATIONS`, which defaults to 100. `src/khoj/processor/operator/__init__.py:70`
For the browser type it starts a `BrowserEnvironment`; otherwise a docker `ComputerEnvironment`. `src/khoj/processor/operator/__init__.py:126-129`
When the agent requests no actions, the task counts as completed. `src/khoj/processor/operator/__init__.py:195`
When the agent requests user input, the environment is not closed. `src/khoj/processor/operator/__init__.py:175` `src/khoj/processor/operator/__init__.py:221`
Absent completion, input request or cancellation, the response begins "Operator hit iteration limit". `src/khoj/processor/operator/__init__.py:212-219`
For the browser type, visited URLs are returned as `webpages`. `src/khoj/processor/operator/__init__.py:226-227`

## A11 Images, speech and phone

When the user has no text-to-image model, `text_to_image` yields status 501 and a setup message. `src/khoj/processor/image/generate.py:60-65`

When the model name is not a listed multimodal name, `text_to_image` first rewrites the prompt. `src/khoj/processor/image/generate.py:82-103`

When the model name is a listed multimodal name, the user's message is the prompt. `src/khoj/processor/image/generate.py:104`

The multimodal names are `gemini-2.5-flash-image` and `gemini-3-pro-image-preview`. `src/khoj/processor/image/generate.py:442-443`

The model type chooses OpenAI, Replicate or Google generation. `src/khoj/processor/image/generate.py:114-125`

When OpenAI generation raises a content-policy error, the generator yields a policy-violation message. `src/khoj/processor/image/generate.py:132-137`

When generation raises `ValueError`, the generator yields status 500. `src/khoj/processor/image/generate.py:145-149`

When generation raises a network error, the generator yields status 502. `src/khoj/processor/image/generate.py:151-155`

After generation, the code passes the image to `upload_generated_image_to_bucket`. `src/khoj/processor/image/generate.py:159`

When the upload returns no URL, the image is yielded as base64 webp data. `src/khoj/processor/image/generate.py:161-162`

The speech route calls `generate_text_to_speech` with the request text. `src/khoj/routers/api_chat.py:214` `src/khoj/routers/api_chat.py:220`

When the user has a voice model, the route passes its model id as `voice_id`. `src/khoj/routers/api_chat.py:216-217`

When that call raises `TextToSpeechError`, the route returns status 503. `src/khoj/routers/api_chat.py:221-222`

Otherwise the route streams the audio as `audio/mpeg`. `src/khoj/routers/api_chat.py:223`

`generate_text_to_speech` raises `TextToSpeechError` when `ELEVEN_LABS_API_KEY` is not set. `src/khoj/processor/speech/text_to_speech.py:28-29`

It converts the markdown text to plain text before posting it. `src/khoj/processor/speech/text_to_speech.py:32-33`

When the text-to-speech response is not ok, it raises `TextToSpeechError`. `src/khoj/processor/speech/text_to_speech.py:51-54`

The `/transcribe` route sits in `api.py`. `src/khoj/routers/api.py:108-110`

When the uploaded file is over 10 MB, the route returns status 422. `src/khoj/routers/api.py:126-128`

When no speech-to-text model is configured, the route returns status 501. `src/khoj/routers/api.py:140-142` `src/khoj/routers/api.py:160-161`

When transcription gives text, the route returns it as JSON under `text`. `src/khoj/routers/api.py:171-172`

`api_phone` is mounted at `/api/phone` when `is_twilio_enabled()` is true. `src/khoj/configure.py:353-356`

Twilio is enabled when `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` and `TWILIO_VERIFICATION_SID` are set. `src/khoj/routers/twilio.py:8-12`

The POST route saves the phone number, then calls `create_otp`. `src/khoj/routers/api_phone.py:28-29`

`create_otp` asks Twilio Verify to send a code over WhatsApp. `src/khoj/routers/twilio.py:25-27`

That POST is limited to 5 requests per day. `src/khoj/routers/api_phone.py:23`

The DELETE route removes the user's phone number. `src/khoj/routers/api_phone.py:50`

The `/verify` route returns status 400 "Invalid OTP" when Twilio does not approve the code. `src/khoj/routers/api_phone.py:81-82`

When the code is approved, `/verify` marks the number verified. `src/khoj/routers/api_phone.py:84-85`

## A-last Not read

<!-- printed -->
none
<!-- /printed -->
