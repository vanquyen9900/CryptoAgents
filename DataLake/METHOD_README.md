# DataLake Method Report: MeMo Adapt Q1/2024

## 1. Muc Tieu

`DataLake` la harness du lieu va thuc nghiem dung de danh gia viec ket hop
TradingAgents-style multi-agent reasoning voi MeMo-style memory adaptation.

Cau hoi chinh:

> Bo nho lich su co giup agent ra quyet dinh tot hon baseline khong co memory
> tren tap test Q1/2024 hay khong?

Tai lieu nay gom gon method tu hai report:

- `reports/q1_2024_performance_analysis.md`
- `reports/memories_extracted.md`

Ket qua khong phai loi khuyen dau tu. Day la benchmark offline, point-in-time,
de so sanh prompt, memory policy va kha nang quan tri rui ro.

## 2. Thiet Lap Thuc Nghiem

| Thanh phan | Gia tri |
|---|---|
| Test split | `DataLake/data_test_2024_q1` |
| Giai doan danh gia | `2024-01-02` den `2024-03-29` |
| Symbols | `AAPL`, `AMZN`, `GOOGL` |
| Tournament | `tour_2024_q1_eval` |
| Context policy | `ctx_paper_aligned_v1` |
| Data mode | `offline_full_pipeline` |
| Memory policy | `mem_top5_role_v1` cho arm co memory |
| Execution | decision ngay `t`, khop lenh o open ngay giao dich ke tiep |
| Portfolio | long-only, initial capital `100000`, transaction cost `0 bps` |

Pipeline chinh:

```text
crawl/normalize data
  -> build Q1 episodes
  -> materialize point-in-time context
  -> run_memo_tournament.py
  -> trajectory decisions
  -> weekly memory lessons
  -> portfolio evaluation
```

Lenh chay chinh:

```powershell
python DataLake/run_test_2024_q1_crawl.py --skip-crawl
python DataLake/run_q1_2024_experiment.py
python DataLake/run_q1_2024_experiment.py --arm EVAL
```

## 3. Arms Va Artifact Status

| Arm | Nhom so sanh | Mo ta |
|---|---|---|
| Market | Buy & Hold | Benchmark thi truong cho tung symbol |
| Arm A | Ours w/o Memory | Agent khong co memory, dung `mem_none_v1` |
| Arm B | Ours + Memory | Seed memory tu 2022 + weekly learning trong Q1/2024 |

Trang thai artifact hien tai:

- Episodes/materialized inputs co du Q1 window trong canonical split.
- Real trajectories canonical hien co 2 nhom: Arm A va Arm B.
- Moi nhom co 189 trajectory rows, tu `2024-01-02` den `2024-01-31`.
- Moi trajectory la mot cap `episode x prompt_set`.
- Benchmark report phan tich portfolio tren cua so Q1 bang cach forward-fill
  exposure tu cac decision da co.

## 4. Co Che MeMo Adapt

### 4.1 Memory Bank

Memory bank la tap hop cac bai hoc co cau truc, moi memory gom:

- `memory_id`: khoa dinh danh bai hoc.
- `memory_bank_version`: version cua bank duoc dung trong arm.
- `agent_role`: role duoc ap dung, hien runner filter theo `trader`.
- `symbol`: symbol goc cua bai hoc, hoac `ANY` voi weekly lesson.
- `market_regime`: regime cua bai hoc, vi du `bearish_momentum`.
- `lesson`, `do`, `avoid`, `trigger_conditions`: noi dung dua vao context.
- `quality_score`, `reward_20d`: tin hieu de xep hang memory.
- `visible_from`: moc thoi gian memory bat dau duoc phep nhin thay.

Arm B seed memory duoc copy tu training bank:

```text
mb_2022_full_highvar_trueskill_socialproxy_llm_v1
  -> mb_q1_2024_2022_memory_weekly_learning_v1
```

Khi copy seed, runner doi `memory_id` bang suffix `_seed2022` va dat
`visible_from = 2024-01-02T00:00:00Z`, nen Q1 agent co the dung seed memory
ngay tu ngay dau.

### 4.2 Weekly Learning

Sau moi tuan cua Arm B, `memo_weekly_lesson_manager.py` loc trajectories trong
tuan do va sinh mot weekly lesson.

Co che hien tai la rule-based reflection:

- Dem tan suat action theo symbol, vi du `AAPL: Hold`, `AMZN: Buy`.
- Tao situational lesson nhac agent so sanh current evidence voi decision ledger.
- Nhac agent khong dung momentum don le; can support/resistance, risk,
  macro/social confirmation.
- Ghi lesson ra `memory_bank/weekly_lessons/*.md`.

Weekly lesson dat `visible_from` sau `week_end`, vi vay lesson cua tuan hien tai
khong leak nguoc vao chinh cac decision trong tuan do.

### 4.3 Cach Chon Bai Hoc Dua Vao Context

Trong `run_memo_tournament.py`, voi moi trajectory:

1. Load memory bank theo `memory_bank_version`.
2. Loai memory co `visible_from > analysis_time`.
3. Goi `retrieve_memories_for_context(...)`.
4. Format memory thanh markdown bang `format_retrieved_memories(...)`.
5. Dua memory markdown vao final portfolio decision stage.

Policy `mem_top5_role_v1`:

| Rule | Gia tri |
|---|---|
| `top_k_memories` | 5 |
| `same_symbol_boost` | true |
| `same_regime_required` | false |
| `agent_role_filter` | true |

Regime hien tai duoc infer tu materialized input:

- `close` so voi `SMA50`.
- `close` so voi `SMA200`.
- `MACD` am/duong.
- `RSI` yeu/manh.

Neu bearish votes >= 2 thi regime la `bearish_momentum`; neu bullish votes >= 2
thi la `bullish_momentum`; con lai la `mixed_regime`.

Sau khi loc, memory duoc score:

```text
score =
  quality_score
  + same_symbol_boost
  + regime_match_bonus
  + risk_or_negative_lesson_bonus
  + min(abs(reward_20d), 0.25)
```

Cuoi cung runner lay top 5 memories co score cao nhat. Memory chi la
`situational prior`; prompt final decision noi ro current point-in-time evidence
va current portfolio state phai uu tien hon bai hoc lich su.

### 4.4 Memory Duoc Dua Vao Stage Nao

`offline_full_pipeline` chay 7 stage LLM:

1. Market analyst.
2. News/social/macro analyst.
3. Fundamentals analyst.
4. Research manager.
5. Trader.
6. Risk debate.
7. Portfolio manager final decision.

Memory chi duoc inject vao stage 7: `portfolio_manager_final_decision`.

Decision ledger duoc dua vao trader/risk/final stage. Ledger chi gom cac
decision truoc do cung `symbol`, cung `prompt_set`, cung `comparison_group`, va
cho biet `current_exposure_before_decision`.

Y nghia thuc nghiem:

- Analyst stages doc du lieu hien tai, khong bi memory chi phoi.
- Trader/risk stage thay lich su position gan day qua decision ledger.
- Final portfolio manager moi nhan memory nhu kinh nghiem bo sung.
- Cach nay giam nguy co memory tro thanh "ground truth" thay vi soft prior.

## 5. Benchmark Q1/2024

Chi so:

- `CR%`: cumulative return.
- `ARR%`: annualized return.
- `SR`: Sharpe ratio.
- `MDD%`: maximum drawdown, hien thi theo do lon drawdown duong nhu report goc.

### Market Benchmark

| Symbol | CR% | ARR% | SR | MDD% |
|---|---:|---:|---:|---:|
| AAPL | -7.91 | -27.71 | -1.59 | 13.50 |
| GOOGL | 12.87 | 61.10 | 1.86 | 14.40 |
| AMZN | 22.26 | 120.63 | 3.22 | 4.22 |

### Agent Benchmark

| Model | Prompt | AAPL CR/ARR/SR/MDD | GOOGL CR/ARR/SR/MDD | AMZN CR/ARR/SR/MDD |
|---|---|---:|---:|---:|
| Ours w/o Memory | `ps_default_v1` | 0.00 / 0.00 / - / 0.00 | -0.98 / -3.80 / -0.14 / 8.74 | 20.00 / 105.01 / 3.00 / 4.22 |
| Ours w/o Memory | `ps_macro_defensive_v1` | -9.74 / -33.20 / -2.39 / 11.65 | -2.19 / -8.37 / -0.65 / 6.09 | 12.18 / 57.21 / 2.00 / 4.69 |
| Ours w/o Memory | `ps_risk_aware_v1` | -3.76 / -14.01 / -2.57 / 4.86 | -2.19 / -8.37 / -0.65 / 6.09 | 12.45 / 58.75 / 2.04 / 4.22 |
| Ours + Memory | `ps_default_v1` | -13.04 / -42.31 / -3.07 / 13.60 | -3.81 / -14.20 / -0.82 / 8.74 | 16.36 / 81.58 / 2.60 / 4.22 |
| Ours + Memory | `ps_macro_defensive_v1` | -10.79 / -36.22 / -2.53 / 13.51 | 2.35 / 9.56 / 1.51 / 1.10 | 18.14 / 92.77 / 2.78 / 4.22 |
| Ours + Memory | `ps_risk_aware_v1` | -1.82 / -6.98 / -1.25 / 3.06 | -2.19 / -8.37 / -0.65 / 6.09 | 14.05 / 67.79 / 2.26 / 4.22 |

## 6. Dien Giai Ket Qua

### AAPL: thi truong giam

Buy & Hold lo `-7.91%` voi MDD `13.50%`. Memory phat huy tot nhat khi ket hop
voi `ps_risk_aware_v1`: CR chi con `-1.82%`, MDD `3.06%`. Day la bang chung
ro nhat cho vai tro phong thu cua memory.

### GOOGL: thi truong bien dong, tang nhe

Buy & Hold dat `12.87%` nhung MDD cao `14.40%`. Cau hinh Memory +
`ps_macro_defensive_v1` khong bat tron upside, nhung van co CR duong `2.35%`
va giam MDD xuong `1.10%`, la diem manh ve risk control.

### AMZN: thi truong tang manh

Buy & Hold dat `22.26%`. Agent bat duoc xu huong tang kha tot, dac biet
baseline `ps_default_v1` dat `20.00%`. Khi bat memory, loi nhuan AMZN thap hon
mot phan, cho thay memory co xu huong than trong hon de doi lay drawdown thap.

## 7. Ket Luan Method

MeMo Adapt trong Q1/2024 khong dong vai tro "toi da hoa loi nhuan" mot cach
don thuan. Tac dong ro nhat la lop phong thu drawdown:

- Tot nhat tren AAPL khi thi truong giam: Memory + `ps_risk_aware_v1`.
- Tot nhat tren GOOGL khi thi truong nhieu/bien dong: Memory +
  `ps_macro_defensive_v1`.
- Tren AMZN uptrend manh, baseline co the dat return cao hon, nhung memory van
  giu drawdown o muc thap.

Vi vay, ket qua nen duoc doc nhu mot trade-off: memory giup agent thuc dung va
phong thu hon, dac biet khi prompt da co bias quan tri rui ro.

## 8. Reproducibility

Validation truoc va sau khi chay:

```powershell
python DataLake/tools/health/check_test_split_health.py
python DataLake/tools/contracts/test_memo_q1_real_artifact_contract.py --data-dir DataLake/data_test_2024_q1 --tournament-id tour_2024_q1_eval --symbols AAPL AMZN GOOGL
python DataLake/tools/contracts/test_memo_portfolio_evaluation_contract.py --data-dir DataLake/data_test_2024_q1 --tournament-id tour_2024_q1_eval --start-date 2024-01-02 --end-date 2024-03-29 --symbols AAPL AMZN GOOGL
python DataLake/tools/contracts/test_memo_decision_ledger_contract.py
```

Quy tac bao cao:

- Chi dung `DataLake/data_test_2024_q1` lam canonical Q1 split.
- Khong dung output mock/demo lam research result.
- Khong recreate `data_test_2024_q1_armB` hay `data_test_2024_q1_armC`.
- Luon giu ro `comparison_group`, `memory_policy_id`, `memory_bank_version`,
  `context_policy_id` trong trajectory va report.
