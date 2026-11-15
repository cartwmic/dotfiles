# Token baseline
window 2026-11-11T18:07:51.696Z to 2026-11-13T01:14:00.034Z (31.1 hours, 1.30 days), 34503 API requests, 784 transcript files

## Total
|  | requests | fresh input | cache write | cache read | output | avg prompt | list $ | share | $ read | $ write | $ output |
|---|---|---|---|---|---|---|---|---|---|---|---|
| all | 34503 | 80.35K | 132.45M | 6.52B | 26.10M | 192.91K | $1911 | 100% | 52% | 31% | 17% |

per day: requests 26.62K, cache read 5.03B, cache write 102.20M, output 20.14M, list $1474

## By seat (own sessions; helpers started with the Agent tool are listed under their own seat line)
|  | requests | fresh input | cache write | cache read | output | avg prompt | list $ | share | $ read | $ write | $ output |
|---|---|---|---|---|---|---|---|---|---|---|---|
| lead | 7941 | 20.48K | 22.13M | 2.05B | 4.01M | 260.95K | $624 | 33% | 62% | 26% | 12% |
| builder | 15120 | 32.58K | 63.00M | 2.69B | 14.07M | 182.24K | $566 | 30% | 48% | 32% | 20% |
| reviewer | 6563 | 13.49K | 33.91M | 623.15M | 4.81M | 100.12K | $414 | 22% | 30% | 47% | 23% |
| coordinator | 3315 | 10.55K | 4.35M | 922.38M | 976.34K | 279.56K | $239 | 13% | 77% | 15% | 8% |
| planner | 1228 | 2.55K | 5.85M | 212.33M | 1.71M | 177.68K | $58 | 3% | 39% | 30% | 31% |
| helper of builder | 184 | 380 | 1.78M | 15.73M | 471.06K | 95.15K | $5 | 0% | 28% | 33% | 39% |
| unattributed | 96 | 204 | 877.65K | 5.05M | 23.50K | 61.77K | $2 | 0% | 11% | 84% | 5% |
| michael-direct | 19 | 40 | 112.52K | 1.09M | 9.09K | 63.39K | $1 | 0% | 17% | 69% | 14% |
| helper of lead | 37 | 76 | 440.65K | 1.36M | 16.64K | 48.77K | $0 | 0% | 14% | 78% | 8% |

## By model
|  | requests | fresh input | cache write | cache read | output | avg prompt | list $ | share | $ read | $ write | $ output |
|---|---|---|---|---|---|---|---|---|---|---|---|
| claude-opus-5-5 | 17743 | 44.38K | 58.29M | 3.64B | 9.73M | 208.21K | $1323 | 69% | 55% | 30% | 15% |
| claude-sonnet-5-5 | 13443 | 29.11K | 58.40M | 2.29B | 11.61M | 175.06K | $526 | 28% | 44% | 34% | 22% |
| claude-haiku-5-5 | 3220 | 6.66K | 15.03M | 574.85M | 4.61M | 183.20K | $43 | 2% | 62% | 15% | 22% |
| claude-fable-5-2 | 97 | 210 | 724.79K | 17.90M | 143.84K | 192.01K | $19 | 1% | 19% | 52% | 30% |

## By seat and model
|  | requests | fresh input | cache write | cache read | output | avg prompt | list $ | share | $ read | $ write | $ output |
|---|---|---|---|---|---|---|---|---|---|---|---|
| lead / opus-5-5 medium | 6771 | 17.76K | 18.49M | 1.79B | 3.34M | 267.38K | $573 | 30% | 63% | 26% | 12% |
| reviewer / opus-5-5 medium | 6324 | 13.00K | 31.58M | 605.11M | 4.66M | 100.68K | $402 | 21% | 30% | 47% | 23% |
| builder / sonnet-5-5 high | 9508 | 20.60K | 37.12M | 1.68B | 8.05M | 180.57K | $367 | 19% | 46% | 32% | 22% |
| coordinator / opus-5-5 medium | 3315 | 10.55K | 4.35M | 922.38M | 976.34K | 279.56K | $239 | 13% | 77% | 15% | 8% |
| builder / opus-5-5 medium | 1190 | 2.77K | 3.19M | 301.00M | 665.59K | 255.62K | $99 | 5% | 61% | 26% | 13% |
| builder / sonnet-5-5 medium | 1365 | 2.90K | 10.36M | 135.61M | 1.07M | 106.94K | $50 | 3% | 27% | 52% | 21% |
| planner / sonnet-5-5 high | 1041 | 2.16K | 4.86M | 192.58M | 1.52M | 189.66K | $49 | 3% | 40% | 29% | 31% |
| lead / sonnet-5-5 high | 1143 | 2.67K | 3.43M | 254.66M | 614.34K | 225.80K | $45 | 2% | 56% | 30% | 14% |
| builder / haiku-5-5 xhigh | 2670 | 5.50K | 10.78M | 538.80M | 3.98M | 205.84K | $40 | 2% | 64% | 14% | 22% |
| builder / fable-5-2 medium | 47 | 102 | 266.05K | 9.76M | 46.20K | 213.28K | $8 | 0% | 24% | 53% | 23% |
| planner / opus-5-5 medium | 114 | 234 | 417.73K | 13.85M | 77.29K | 125.16K | $6 | 0% | 43% | 33% | 24% |
| lead / fable-5-2 medium | 26 | 54 | 190.82K | 3.51M | 54.81K | 142.22K | $6 | 0% | 12% | 51% | 37% |
| reviewer / fable-5-2 medium | 24 | 54 | 267.92K | 4.64M | 42.84K | 204.30K | $5 | 0% | 17% | 50% | 32% |
| helper of builder / sonnet-5-5 high | 129 | 264 | 563.04K | 14.36M | 159.05K | 115.69K | $4 | 0% | 32% | 32% | 36% |
| reviewer / sonnet-5-5 high | 126 | 252 | 849.44K | 9.58M | 70.16K | 82.79K | $4 | 0% | 22% | 62% | 16% |
| planner / sonnet-5-5 medium | 73 | 154 | 574.46K | 5.91M | 108.76K | 88.76K | $3 | 0% | 19% | 46% | 35% |
| unattributed / opus-5-5 medium | 10 | 22 | 147.90K | 596.09K | 3.38K | 74.40K | $1 | 0% | 9% | 86% | 5% |
| reviewer / sonnet-5-5 medium | 34 | 68 | 435.94K | 1.38M | 7.94K | 53.55K | $1 | 0% | 11% | 83% | 6% |
| michael-direct / opus-5-5 medium | 19 | 40 | 112.52K | 1.09M | 9.09K | 63.39K | $1 | 0% | 17% | 69% | 14% |
| builder / haiku-5-5 medium | 340 | 724 | 1.28M | 27.52M | 258.67K | 84.71K | $1 | 0% | 59% | 18% | 23% |
| helper of builder / haiku-5-5 medium | 55 | 116 | 1.22M | 1.37M | 312.01K | 46.97K | $1 | 0% | 6% | 36% | 58% |
| unattributed / sonnet-5-5 medium | 13 | 28 | 104.06K | 658.58K | 2.23K | 58.67K | $1 | 0% | 13% | 83% | 4% |

## By day (PST)
|  | requests | fresh input | cache write | cache read | output | avg prompt | list $ | share | $ read | $ write | $ output |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-11-11 | 16140 | 37.13K | 67.04M | 2.96B | 11.86M | 187.79K | $891 | 47% | 49% | 33% | 17% |
| 2026-11-12 | 18363 | 43.22K | 65.41M | 3.56B | 14.24M | 197.41K | $1019 | 53% | 54% | 30% | 17% |

## Main thread vs Agent-tool helpers
|  | requests | fresh input | cache write | cache read | output | avg prompt | list $ | share | $ read | $ write | $ output |
|---|---|---|---|---|---|---|---|---|---|---|---|
| main session | 22348 | 55.34K | 63.86M | 4.97B | 13.97M | 225.33K | $1399 | 73% | 58% | 28% | 14% |
| Agent-tool helper | 12155 | 25.02K | 68.58M | 1.55B | 12.13M | 133.30K | $512 | 27% | 34% | 40% | 26% |

## By prompt size of the request
|  | requests | fresh input | cache write | cache read | output | avg prompt | list $ | share | $ read | $ write | $ output |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 0-50K | 771 | 1.55K | 15.79M | 17.27M | 254.75K | 42.88K | $58 | 3% | 4% | 92% | 4% |
| 50-100K | 7567 | 15.60K | 42.49M | 549.47M | 5.23M | 78.23K | $336 | 18% | 24% | 56% | 21% |
| 100-150K | 7828 | 17.08K | 21.96M | 940.19M | 6.69M | 122.91K | $307 | 16% | 43% | 31% | 27% |
| 150-200K | 4933 | 11.60K | 13.27M | 839.81M | 4.53M | 172.94K | $223 | 12% | 52% | 25% | 23% |
| 200-300K | 6525 | 16.35K | 16.71M | 1.59B | 5.32M | 245.72K | $379 | 20% | 62% | 22% | 17% |
| 300-467K | 6848 | 18.05K | 22.13M | 2.57B | 4.03M | 378.92K | $605 | 32% | 70% | 21% | 10% |
| 467K+ | 31 | 124 | 90.96K | 17.50M | 40.17K | 567.43K | $3 | 0% | 76% | 11% | 13% |

## Prompt size by seat
| seat | requests | avg prompt | cache read in prompts >150K | >300K | max prompt |
|---|---|---|---|---|---|
| builder | 15120 | 182.24K | 73% | 32% | 867.22K |
| coordinator | 3315 | 279.56K | 94% | 59% | 467.50K |
| helper of builder | 184 | 95.15K | 16% | 0% | 186.65K |
| helper of lead | 37 | 48.77K | 0% | 0% | 77.91K |
| lead | 7941 | 260.95K | 91% | 55% | 536.97K |
| michael-direct | 19 | 63.39K | 0% | 0% | 79.94K |
| planner | 1228 | 177.68K | 75% | 24% | 883.91K |
| reviewer | 6563 | 100.12K | 22% | 2% | 531.24K |
| unattributed | 96 | 61.77K | 0% | 0% | 111.07K |

## Fixed start-up prefix (smallest prompt the session ever sent) re-read on every request
| seat | sessions | median smallest prompt | prefix tokens re-read | share of the seat cache read |
|---|---|---|---|---|
| builder | 289 | 44.85K | 806.90M | 30% |
| lead | 24 | 58.12K | 414.97M | 20% |
| reviewer | 381 | 43.59K | 314.41M | 50% |
| coordinator | 1 | 85.50K | 283.04M | 31% |
| planner | 28 | 44.67K | 58.70M | 28% |
| helper of builder | 25 | 4.97K | 8.15M | 52% |
| unattributed | 23 | 58.07K | 4.56M | 90% |
| helper of lead | 10 | 43.18K | 1.12M | 82% |
| michael-direct | 3 | 50.23K | 859.36K | 79% |
| all | 784 |  | 1.89B | 29% |

first requests of 784 sessions started in window: cache written 26.23M, read from an earlier session 14.47M (36% shared)

## First request of each new session: prefix written fresh vs read from a cache another session left
| seat | new sessions | avg written | avg read from shared cache | list $ of the writes |
|---|---|---|---|---|
| reviewer | 381 | 32.34K | 17.34K | $69 |
| builder | 289 | 31.39K | 20.16K | $24 |
| lead | 24 | 95.38K | 23.93K | $16 |
| coordinator | 1 | 442.95K | 0 | $4 |
| planner | 28 | 33.58K | 12.55K | $3 |
| unattributed | 23 | 27.06K | 27.95K | $1 |
| michael-direct | 3 | 18.24K | 30.96K | $0 |
| helper of builder | 25 | 8.10K | 11.07K | $0 |
| helper of lead | 10 | 28.18K | 9.79K | $0 |
| all | 784 | 33.45K | 18.46K | $118 |

## System prompt and tool schemas sent with each request (all data; tokens = chars / 4, rough)
| who | requests logged | system prompt tokens | tool schema tokens | tools |
|---|---|---|---|---|
| helper: agent:builtin:general-purpose | 36044 | 740 | 12.41K | 11 |
| main: lead | 25973 | 3.28K | 18.65K | 24 |
| main: builder | 25522 | 3.55K | 17.12K | 17 |
| main: coordinator | 18637 | 27.36K | 19.89K | 32 |
| main: reviewer | 6174 | 3.33K | 16.54K | 16 |
| main: planner | 3183 | 3.18K | 15.45K | 17 |
| main: unattributed | 732 | 3.07K | 16.13K | 19 |
| helper: agent:builtin:claude | 510 | 790 | 10.74K | 9 |
| helper: agent:builtin:web-fetch | 107 | 1.50K | 312 | 2 |
| helper: agent:builtin:Explore | 94 | 869 | 2.57K | 6 |
| helper: agent:builtin:Plan | 60 | 1.01K | 2.58K | 6 |

## Largest tool schemas in the most used request shape (10 tools, 10.84K tokens total)
| tool | tokens (chars / 4) |
|---|---|
| Artifact | 6.52K |
| Agent | 1.34K |
| Bash | 947 |
| Read | 493 |
| Skill | 461 |
| ToolSearch | 372 |
| Edit | 251 |
| mcp__t3-code__request_secret | 226 |
| Write | 165 |
| DeferredToolPlaceholder | 53 |

## What started each turn
| seat | turn started by | turns | requests | avg prompt | cache read | list $ | share | one-request short-reply turns | their list $ |
|---|---|---|---|---|---|---|---|---|---|
| reviewer | brief (first turn) | 381 | 6450 | 99.62K | 608.79M | $407 | 21% | 0 | $0 |
| builder | brief (first turn) | 289 | 10397 | 154.57K | 1.55B | $351 | 18% | 0 | $0 |
| lead | message from another agent | 425 | 1653 | 286.82K | 468.64M | $148 | 8% | 33 | $3 |
| lead | other follow-up | 470 | 2111 | 250.55K | 525.09M | $143 | 7% | 81 | $4 |
| coordinator | coordinator event | 1386 | 2056 | 277.88K | 568.88M | $143 | 7% | 945 | $64 |
| lead | coordinator event | 240 | 1131 | 272.30K | 301.22M | $123 | 6% | 38 | $5 |
| builder | other follow-up | 608 | 2535 | 238.98K | 600.77M | $100 | 5% | 179 | $6 |
| lead | child finished notice | 778 | 1331 | 273.84K | 362.64M | $88 | 5% | 517 | $33 |
| lead | background task finished | 361 | 1221 | 266.07K | 322.94M | $85 | 4% | 98 | $7 |
| coordinator | message from another agent | 502 | 1086 | 281.16K | 304.16M | $79 | 4% | 97 | $7 |
| builder | message from another agent | 111 | 1205 | 248.30K | 296.62M | $65 | 3% | 14 | $1 |
| planner | brief (first turn) | 28 | 1075 | 165.21K | 172.36M | $48 | 3% | 0 | $0 |
| builder | background task finished | 116 | 774 | 265.73K | 204.06M | $44 | 2% | 4 | $0 |
| lead | brief (first turn) | 17 | 421 | 126.07K | 51.36M | $29 | 2% | 0 | $0 |
| coordinator | other follow-up | 44 | 125 | 287.15K | 35.20M | $14 | 1% | 4 | $0 |
| lead | PR watch | 20 | 73 | 257.74K | 18.21M | $9 | 0% | 3 | $0 |
| planner | other follow-up | 11 | 128 | 251.60K | 31.71M | $8 | 0% | 0 | $0 |
| builder | coordinator event | 13 | 152 | 186.81K | 28.10M | $6 | 0% | 0 | $0 |
| helper of builder | brief (first turn) | 23 | 144 | 84.30K | 10.46M | $4 | 0% | 0 | $0 |
| reviewer | message from another agent | 6 | 52 | 128.63K | 6.57M | $4 | 0% | 0 | $0 |
| coordinator | child finished notice | 29 | 48 | 295.45K | 14.13M | $4 | 0% | 12 | $1 |
| planner | message from another agent | 5 | 25 | 335.24K | 8.26M | $2 | 0% | 0 | $0 |
| reviewer | other follow-up | 4 | 44 | 118.07K | 5.13M | $2 | 0% | 0 | $0 |
| unattributed | brief (first turn) | 22 | 75 | 64.34K | 4.04M | $2 | 0% | 0 | $0 |

one-request short-reply turns (reply under 250 output tokens, no tool loop): 2033 turns, cache read 576.39M, list $130 (6.8%)

## Whole-prompt cache rewrites after the first request (over half the prompt written fresh)
| seat | cause | requests | tokens rewritten | list $ |
|---|---|---|---|---|
| lead | idle over 1 hour | 30 | 7.96M | $60 |
| builder | idle 5-60 min on the 5-minute cache | 97 | 14.72M | $34 |
| builder | idle over 1 hour | 13 | 2.82M | $15 |
| lead | after a compaction | 18 | 899.08K | $7 |
| lead | under 5 min idle (prefix changed) | 2 | 644.92K | $5 |
| lead | idle 5-60 min on the 1-hour cache (unexpected) | 1 | 391.68K | $3 |
| reviewer | idle 5-60 min on the 5-minute cache | 4 | 392.94K | $2 |
| builder | after a compaction | 8 | 415.33K | $2 |
| coordinator | after a compaction | 3 | 204.08K | $2 |
| planner | after a compaction | 1 | 62.56K | $0 |
| helper of builder | under 5 min idle (prefix changed) | 19 | 788.55K | $0 |
| builder | under 5 min idle (prefix changed) | 1 | 202.16K | $0 |
| all |  | 197 | 29.50M | $130 (6.8%) |

## Cache lifetime requested, by seat
| seat / ttl | requests | 1h writes | 5m writes |
|---|---|---|---|
| builder / ttl 1h | 8604 | 24.51M | 0 |
| builder / ttl 5m | 6516 | 0 | 38.48M |
| coordinator / ttl 1h | 3315 | 4.35M | 0 |
| helper of builder / ttl 1h | 1 | 9.79K | 0 |
| helper of builder / ttl 5m | 183 | 0 | 1.77M |
| helper of lead / ttl 5m | 37 | 0 | 440.65K |
| lead / ttl 1h | 7941 | 22.13M | 0 |
| michael-direct / ttl 1h | 19 | 112.52K | 0 |
| planner / ttl 1h | 327 | 1.37M | 0 |
| planner / ttl 5m | 901 | 0 | 4.48M |
| reviewer / ttl 1h | 2046 | 10.51M | 0 |
| reviewer / ttl 5m | 4517 | 0 | 23.40M |
| unattributed / ttl 1h | 96 | 877.65K | 0 |

## Compactions
| seat | trigger | count | min before | median before | max before | avg after |
|---|---|---|---|---|---|---|
| builder | auto | 8 | 467.25K | 467.83K | 468.51K | 27.12K |
| coordinator | auto | 9 | 466.85K | 468.35K | 469.24K | 19.50K |
| coordinator | manual | 1 | 385.42K | 385.42K | 385.42K | 12.75K |
| lead | auto | 18 | 466.96K | 467.59K | 468.96K | 26.22K |
| planner | auto | 1 | 467.11K | 467.11K | 467.11K | 36.09K |

## Tool results: size, and tokens re-read because the result stays in the prompt (whole files of sessions active in the window; tokens = chars / 3.2, rough)
| tool | calls | result tokens | avg per call | tokens re-read later | share of cache read |
|---|---|---|---|---|---|
| Bash | 28558 | 27.56M | 965 | 1.40B | 21.4% |
| Read | 917 | 3.81M | 4.16K | 176.51M | 2.7% |
| mcp__t3-code__* | 3890 | 943.05K | 242 | 128.30M | 2.0% |
| mcp__hindsight__* | 113 | 295.84K | 2.62K | 38.39M | 0.6% |
| Agent | 672 | 492.95K | 733 | 37.20M | 0.6% |
| WebFetch | 226 | 932.91K | 4.13K | 4.99M | 0.1% |
| WebSearch | 156 | 184.25K | 1.18K | 4.61M | 0.1% |
| Artifact | 4 | 22.15K | 5.54K | 3.35M | 0.1% |
| SendMessage | 197 | 20.63K | 104 | 1.93M | 0.0% |
| ToolSearch | 472 | 16.48K | 34 | 1.57M | 0.0% |
| Monitor | 147 | 17.45K | 118 | 1.49M | 0.0% |
| Write | 528 | 31.22K | 59 | 1.21M | 0.0% |
| Edit | 630 | 31.57K | 50 | 1.13M | 0.0% |
| mcp__context7__* | 23 | 29.42K | 1.28K | 1.08M | 0.0% |
| all tools | 36757 | 34.41M |  | 1.80B | 27.6% |
| model output kept in the prompt | 39261 | 29.69M |  | 1.88B | 28.8% |
| turn prompts (briefs, messages, notices) | 7702 | 3.72M | 483 | 475.31M | 7.3% |

## Bash calls by kind of command
| kind | calls | result tokens | avg per call | tokens re-read later | share of Bash re-read |
|---|---|---|---|---|---|
| read a file with cat, sed, head, tail, wc | 6747 | 12.19M | 1.81K | 588.61M | 42% |
| search and list (grep, ls, find) | 5495 | 5.13M | 933 | 253.54M | 18% |
| other | 6212 | 2.69M | 432 | 170.17M | 12% |
| git | 3102 | 4.20M | 1.35K | 155.74M | 11% |
| inline scripts and loops | 3935 | 2.12M | 538 | 119.94M | 9% |
| ledger and coordinator CLIs | 1720 | 441.44K | 256 | 51.05M | 4% |
| GitHub CLI | 727 | 427.28K | 587 | 27.41M | 2% |
| remote: kgate, kubectl, ssh, curl | 498 | 335.65K | 674 | 27.41M | 2% |
| build and test runners | 119 | 29.11K | 244 | 1.15M | 0% |

Read calls 917, of which repeats of the same file and range in one session: 11 (1%), about 18.32K tokens returned again

## Hook text added to the prompt
| hook event | times | tokens added (chars / 4) | avg |
|---|---|---|---|
| SessionStart | 1097 | 1.56M | 1.42K |
| SessionStart:ctx | 372 | 1.43M | 3.84K |
| PostToolUse:ctx | 10 | 60.43K | 6.04K |
| UserPromptSubmit:ctx | 111 | 29.80K | 268 |
| PreToolUse:ctx | 1 | 55 | 55 |
| PreToolUse | 3392 | 54 | 0 |

## Agent-tool helpers by who started them
| started by | helper seat | helpers | requests | avg requests | avg first prompt | cache read | list $ |
|---|---|---|---|---|---|---|---|
| lead | reviewer | 188 | 3072 | 16 | 42.83K | 263.89M | $178 |
| lead | builder | 105 | 4235 | 40 | 42.77K | 619.83M | $126 |
| builder | builder | 61 | 2281 | 37 | 43.99K | 365.98M | $81 |
| builder | reviewer | 74 | 1445 | 20 | 43.71K | 137.99M | $81 |
| lead | planner | 17 | 537 | 32 | 43.37K | 70.18M | $24 |
| builder | planner | 6 | 364 | 61 | 41.85K | 76.74M | $17 |
| builder | helper of builder | 25 | 184 | 7 | 19.17K | 15.73M | $5 |
| lead | helper of lead | 10 | 37 | 4 | 37.97K | 1.36M | $0 |

## Sessions by seat
| seat | sessions | avg requests | max requests | median list $ | max list $ | total list $ |
|---|---|---|---|---|---|---|
| builder | 289 | 52 | 606 | $0.96 | $36.14 | $566 |
| coordinator | 1 | 3315 | 3315 | $238.86 | $238.86 | $239 |
| helper of builder | 25 | 7 | 30 | $0.02 | $1.35 | $5 |
| helper of lead | 10 | 4 | 6 | $0.01 | $0.13 | $0 |
| lead | 24 | 331 | 2402 | $7.77 | $174.83 | $624 |
| michael-direct | 3 | 6 | 13 | $0.34 | $0.68 | $1 |
| planner | 28 | 44 | 112 | $1.87 | $7.09 | $58 |
| reviewer | 381 | 17 | 121 | $0.91 | $7.15 | $414 |
| unattributed | 23 | 4 | 11 | $0.01 | $0.83 | $2 |

## Output and thinking
| seat / model effort | requests | output | thinking | thinking share | output per request |
|---|---|---|---|---|---|
| builder / sonnet-5-5 high | 9508 | 8.05M | 2.81M | 35% | 847 |
| reviewer / opus-5-5 medium | 6324 | 4.66M | 1.95M | 42% | 736 |
| builder / haiku-5-5 xhigh | 2670 | 3.98M | 2.61M | 66% | 1.49K |
| lead / opus-5-5 medium | 6771 | 3.34M | 625.58K | 19% | 493 |
| planner / sonnet-5-5 high | 1041 | 1.52M | 769.80K | 51% | 1.46K |
| builder / sonnet-5-5 medium | 1365 | 1.07M | 260.38K | 24% | 782 |
| coordinator / opus-5-5 medium | 3315 | 976.34K | 135.81K | 14% | 294 |
| builder / opus-5-5 medium | 1190 | 665.59K | 134.18K | 20% | 559 |
| lead / sonnet-5-5 high | 1143 | 614.34K | 193.47K | 31% | 537 |
| helper of builder / haiku-5-5 medium | 55 | 312.01K | 202.12K | 65% | 5.67K |
| builder / haiku-5-5 medium | 340 | 258.67K | 116.87K | 45% | 760 |
| helper of builder / sonnet-5-5 high | 129 | 159.05K | 40.63K | 26% | 1.23K |
| planner / sonnet-5-5 medium | 73 | 108.76K | 47.47K | 44% | 1.49K |
| planner / opus-5-5 medium | 114 | 77.29K | 26.56K | 34% | 677 |

advisor calls: 239 requests, 34.46M advisor input tokens, 2.53M advisor output tokens (not in the usage totals above)

## Advisor tool calls (a second, stronger model is sent the whole transcript; billed outside the totals above)
| seat | advisor model | calls | input (all uncached) | avg input per call | output | list $ |
|---|---|---|---|---|---|---|
| builder | fable-5-2 | 102 | 14.50M | 142.15K | 1.09M | $160 |
| reviewer | fable-5-2 | 92 | 12.29M | 133.61K | 997.22K | $138 |
| planner | fable-5-2 | 19 | 4.40M | 231.35K | 255.85K | $45 |
| lead | fable-5-2 | 12 | 1.62M | 135.35K | 78.42K | $16 |
| lead | opus-5-5 | 5 | 833.64K | 166.73K | 37.86K | $4 |
| helper of builder | fable-5-2 | 4 | 266.05K | 66.51K | 23.48K | $3 |
| builder | opus-5-5 | 5 | 550.28K | 110.06K | 42.99K | $3 |
| all |  | 239 | 34.46M |  | 2.53M | $370 = 19% on top of the total |

## What-if: compact at a lower prompt size (today: 467K)
| limit | cache read avoided | share of cache read | extra compactions | net list $ in window | where |
|---|---|---|---|---|---|
| 300.00K | 1.51B | 23% | 178 | $151 (8%) | lead $98, coordinator $53, builder $24, planner $-7 |
| 200.00K | 2.44B | 37% | 468 | $134 (7%) | lead $116, coordinator $68, builder $16, planner $-11 |
| 150.00K | 2.99B | 46% | 827 | $43 (2%) | lead $101, coordinator $67, helper of builder $-0, builder $-16 |
| 100.00K | 3.62B | 55% | 3181 | $-1084 (-57%) | unattributed $-1, helper of builder $-4, coordinator $-64, planner $-64 |

## Review sessions by role
| role | model | sessions | avg requests | cache write | cache read | output | list $ | $ per session |
|---|---|---|---|---|---|---|---|---|
| reviewer | opus-5-5 | 300 | 19 | 28.60M | 551.02M | 4.18M | $366 | $1.22 |
| intent checker | opus-5-5 | 18 | 14 | 1.41M | 17.35M | 245.41K | $15 | $0.86 |
| blind designer | opus-5-5 | 2 | 76 | 363.59K | 24.61M | 116.73K | $9 | $4.54 |
| labeller | opus-5-5 | 11 | 9 | 617.93K | 6.82M | 52.20K | $6 | $0.57 |
| reviewer | fable-5-2 | 1 | 24 | 267.92K | 4.64M | 42.84K | $5 | $5.32 |
| comparer | opus-5-5 | 5 | 11 | 326.16K | 4.05M | 48.86K | $3 | $0.68 |
| labeller | sonnet-5-5 | 18 | 4 | 871.71K | 3.29M | 17.18K | $3 | $0.18 |
| reviewer | sonnet-5-5 | 4 | 22 | 359.42K | 7.49M | 59.65K | $2 | $0.56 |
| churn judge | opus-5-5 | 7 | 4 | 258.06K | 1.26M | 12.06K | $2 | $0.28 |
| churn judge | sonnet-5-5 | 1 | 3 | 54.26K | 178.97K | 1.27K | $0 | $0.25 |
| labeller | haiku-5-5 | 14 | 4 | 780.49K | 2.43M | 33.11K | $0 | $0.01 |

## Fifteen most expensive sessions in the window
| seat | model | requests | avg prompt | max prompt | cache read | list $ | brief starts |
|---|---|---|---|---|---|---|---|
| coordinator | opus-5-5 | 3315 | 279.56K | 467.50K | 922.38M | $239 | You are the new coordinator thread, and this is only a start |
| lead | opus-5-5 | 2402 | 271.99K | 466.90K | 650.37M | $175 | Seat: Lead. Model: Opus 5.5 medium. You are the code lead fo |
| lead | sonnet-5-5 | 1106 | 274.23K | 466.34K | 299.93M | $96 | Seat: Lead. Model: Sonnet 5.5 high.  You lead a new workstre |
| lead | opus-5-5 | 942 | 277.52K | 466.27K | 259.56M | $76 | Seat: Lead. Model: Opus 5.5 medium. You lead the workstream  |
| lead | opus-5-5 | 752 | 265.36K | 466.73K | 197.19M | $65 | Seat: Lead. Model: Opus 5.5 medium. You lead the workstream  |
| lead | opus-5-5 | 641 | 275.13K | 536.97K | 174.21M | $58 | Seat: lead. Model: Sonnet 5.5 high.  You are the lead for th |
| builder | opus-5-5 | 449 | 262.40K | 464.14K | 116.83M | $36 | Act as the implementation sub-agent for this task.  Seat: Ru |
| lead | opus-5-5 | 272 | 277.71K | 465.57K | 73.50M | $34 | Seat: lead. Model: Sonnet 5.5 high.  You are the lead for th |
| builder | opus-5-5 | 449 | 259.11K | 466.14K | 115.65M | $33 | Act as the implementation sub-agent for this task.  Seat: Ru |
| lead | sonnet-5-5 | 699 | 271.28K | 466.86K | 187.76M | $30 | Seat: Lead. Model: Sonnet 5.5 high. You lead the workstream  |
| builder | sonnet-5-5 | 259 | 253.37K | 465.14K | 59.71M | $23 | Seat: Builder (escalated: the AGENTS.md route is ambiguous w |
| builder | sonnet-5-5 | 509 | 278.27K | 853.58K | 140.62M | $22 | Act as the implementation sub-agent for this task.  Seat: Bu |
| builder | sonnet-5-5 | 426 | 274.90K | 464.65K | 116.36M | $18 | Act as the implementation sub-agent for this task.  Seat: bu |
| lead | opus-5-5 | 221 | 246.37K | 368.89K | 54.11M | $16 | Seat: Lead. Model: Opus 5.5 medium. You lead the workstream  |
| builder | fable-5-2 | 87 | 274.68K | 556.11K | 23.24M | $15 | Act as the research sub-agent for this task.  Read and follo |

top 15 sessions: $937, 49% of the window
