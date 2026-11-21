# Check report: GUIDE.md lines 861-1010 (slice 4)

Repo: khoj at ae229ca894c0b80ad84664afcfdde523b5e87057. Check brief v6.

All 25 flagged claims were checked first, against the whole defining code:
- 874: `/operator` maps to Operator only via `startswith("/operator") and is_operator_enabled()` (src/khoj/routers/helpers.py:274-275); `is_env_var_true` compares lowercased value to "true" (src/khoj/utils/helpers.py:761-763, 778-781).
- 878, 880: `aget_vision_enabled_config` returns the first vision model or None, then ValueError (src/khoj/processor/operator/__init__.py:60-63). The OpenAI and binary branches are `and False` / `elif False`, so every non-Anthropic match, gpt-4o included, reaches the "Unsupported operator model" raise (:84, :96, :116-120).
- 882: the chat call (src/khoj/routers/api_chat.py:1243-1256) passes no `environment_type`. The research caller (src/khoj/routers/research.py:587) is a different caller, and the sentence does not cover it.
- 887, 893, 894: the termination and response branches at src/khoj/processor/operator/__init__.py:195-219 and the previous-trajectory reset at :53-55 match.
- 903: six digits from `range(6)`, name lowercased with spaces turned into hyphens (src/khoj/database/models/__init__.py:340-343).
- 911: `[:50]`, `two_weeks_ago`, `get_conversation_sessions(user, client_app)` (src/khoj/routers/api_agents.py:87-99).
- 914, 924, 926, 927: the 404 branches and the creator check in `adelete_agent_by_slug` (src/khoj/database/adapters/__init__.py:695-701) match.
- 937, 943, 948: they match src/khoj/database/adapters/__init__.py:1644-1647, 2301-2302, 2342-2343 and src/khoj/routers/helpers.py:1060-1066.
- 964: the file has five routes and each carries `@requires(["authenticated"])` (src/khoj/routers/api_automation.py:26, 38, 52, 125, 150).
- 977, 1005, 979, 982: they match api_automation.py:68-69, 167-168, 82-85 and helpers.py:639-643 (`len(response) != 3`).
- 996, 998: `schedule.every(17).minutes` and the lock and pause logic (src/khoj/configure.py:468-497).

The remaining claims (diagram flow, agent model and routes, memory routes, automation POST, PUT and trigger, scheduling) were each read against their cited lines and the surrounding function. None failed.

Findings (non-HOLDS): none.

Counts: claims checked 96; HOLDS 96; WRONG 0; OVERSTATED 0; UNSUPPORTED 0.
