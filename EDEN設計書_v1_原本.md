# EDEN設計書 v1 原本（アーカイブ）

収録日: 2026-08-18
状態: 廃版（v2 = EDEN設計書.md が現行正本）。本文は2026-08-16の初期構想の原文であり、
baseline-and-credit方式を含む。v2への転換理由は現行正本の変更履歴を参照。
収録理由: 憲法IV（Facts Outlive Rules）。追補・実装コメントが参照するv1章番号
（§8, §9, §12, §14, §20, §21.1等）の参照先を保存する。

---

EDEN Network

0. 目的
EDEN Networkは、AIやコンピュータが有用な仕事を、どれだけ少ない物理資源で達成したかを測定・検証し、その効率を共有可能な価値へ変換するネットワークである。
最終的には、AI同士が自律的に仕事を依頼・実行・検証・決済する経済圏を想定する。
中心思想は以下。
価値とは、知性によって不要になった資源である。
Bitcoinが大量の計算と電力消費によってProofを作るのに対して、EDENは逆方向を目指す。

```text
Bitcoin:
Energy → Computation → Proof → Money

EDEN:
Task → Intelligence → Less Resource → Proof → Value → Next Task
```

EDENは「たくさん計算したこと」ではなく、同じ目的をより少ない資源で達成したことを評価する。

1. 設計原則
1.1 AI内部を原則として信用しない
EDENは特定のAI内部構造に依存しない。
必須としないもの：

* Chain of Thought
* latent
* token probability
* sampling trace
* model architecture
* proprietary telemetry

基本的にはAIをブラックボックスとして扱う。
観測対象は、

```text
Task
↓
[ Black Box Intelligence ]
↓
Result
```

および、その処理に必要だった物理・計算資源。
これにより、

* Transformer
* 小型LLM
* GPU
* NPU
* ニューロモーフィック
* 将来の別アーキテクチャ

にも対応可能な設計とする。

2. 最初から暗号通貨を作らない
v0の目的はToken発行ではない。
最初に構築するのは、
Efficiency Receipt Network
である。
各AI Jobについて、
「何を要求され、何を達成し、そのためにどれだけ資源を消費したか」
というReceiptを作る。
例：

```json
{
  "receipt_id": "...",
  "task_hash": "...",
  "input_hash": "...",
  "output_hash": "...",

  "runner_id": "...",
  "verifier_id": "...",

  "device": "...",
  "model": "...",

  "started_at": "...",
  "completed_at": "...",

  "energy_joules": 28.4,
  "measurement_method": "estimated",
  "measurement_confidence": 0.67,

  "verification": {
    "status": "pass",
    "score": 1.0
  },

  "baseline_joules": 41.7,
  "saved_joules": 13.3,
  "efficiency_ratio": 0.319,

  "signature": "..."
}
```

Receiptはまず「事実」を記録する。
Receiptそのものと通貨発行ルールは分離する。
これにより、後からTokenomicsやBaseline方式を変更しても、基礎データを壊さずに済む。

3. 評価順序
省エネだけを評価すると「何もしないコンピュータ」が最強になる。
したがって順序を固定する。
必須順序

1. Taskが存在する
2. RunnerがTaskを実行する
3. ResultをVerifierが確認する
4. PASSしたJobのみ資源効率を評価する

式としては、

```text
Quality >= RequiredQuality
```

を満たすことが前提。
そのうえで、

```text
SavedEnergy = BaselineEnergy - ActualEnergy
```

を計算する。

4. Baseline
最大の技術課題の一つ。
「28J使った」というだけでは効率的か判断できない。
比較対象となるBaselineが必要。
初期段階では、同種または同一Taskを複数Runnerに実行させる。
例：

```text
Runner A    28 J
Runner B    37 J
Runner C    44 J
Runner D    46 J
Runner E    61 J
```

中央値等から、

```text
Baseline = 44 J
```

とする。
Aの場合、

```text
Saved = 44 - 28
      = 16 J
```

となる。

5. Baselineの将来形
毎回同じTaskを複数AIに実行させると、その行為自体が無駄になる。
Receiptが十分蓄積された段階で、
Baseline Model
を構築する。
入力例：

* task type
* input size
* expected output size
* model category
* hardware category
* difficulty
* quality requirement
* execution environment

出力：

```text
Expected energy required for comparable successful work
```

定期的に実測competitionを行い、Baseline Modelを再校正する。
したがって技術進歩によってネットワーク全体の効率が上がれば、Baselineも自動的に厳しくなる。

6. 計測レベル
最初から完全な物理計測を要求しない。
Receiptにmeasurement trust levelを持たせる。
Level S — Soft
アプリから取得可能な情報による推定。
例：

* execution time
* CPU usage
* GPU usage
* NPU usage
* battery change
* device model
* known power characteristics

Level V — Verified
OSまたはhardware counterを利用。
例：

* Intel/AMD energy counter
* NVIDIA energy/power telemetry
* Android battery / hardware telemetry
* その他hardware-backed counter

Level P — Physical
外部計測。
将来的には、

* USB-C inline meter
* EDEN Cable
* EDEN Plug
* PDU
* motherboard-integrated meter
* PSU-integrated meter

等。
すべて同じReceipt Schemaで扱う。

7. v0はソフトウェアだけで作る
ハードウェア製造から始めない。
まずEDEN App / Agentを作る。
初期対象はPCを優先。
可能ならLinuxを最初のreference environmentとする。
構成：

```text
Task
  ↓
Runner
  ↓
Measurement
  ↓
Verifier
  ↓
Efficiency Receipt
  ↓
Ledger
```

Ledgerは最初は中央DBでよい。
候補：

* SQLite
* PostgreSQL

ブロックチェーンは不要。
必要になった時点で分散化する。

8. 最初のTask Domain
最初の実験はコード生成・コード修正が適している。
理由：
Resultを自動検証しやすい。
例：

```text
Task:
Fix function X.

Required result:
127 automated tests must pass.
```

Runnerがコード生成。
Verifierがtestsを実行。

```text
127 / 127 PASS
```

した場合のみReceiptを発行する。
主要指標：
Joules per Successful Task
単純なモデル性能ランキングではなく、
正しい成果を1件生み出すために何J必要だったか
を評価する。

9. v0実験案
複数のRunner方式を比較する。
例：

* 大型モデル
* 小型ローカルモデル
* コード特化モデル
* 小型モデル + retrieval
* 小型モデル + tool
* multi-agent
* cache利用
* 一部rule-based処理

100〜1000程度のTaskで、

```text
success rate
energy / success
execution time
estimated cost
efficiency vs baseline
```

を記録する。
目的は、
EDENの指標によって、実際に「賢い省計算」が発見できるか
を検証すること。

10. Efficiency Receipt Ledger
最低限必要なAPI。
例：

```text
POST /tasks
GET  /tasks/:id

POST /runs
POST /runs/:id/result

POST /verification

POST /receipts
GET  /receipts/:id

GET /baselines
GET /leaderboard
```

将来は署名を必須にする。
各Nodeは公開鍵を持つ。
ReceiptはRunner / Meter / Verifierの署名を持てる構造にする。

11. 将来のAI経済
Receipt Networkが成立してから、
CREDIT
を導入する。
CREDITの意味：
過去の有用かつ効率的な知的仕事によって獲得した、未来のAI仕事を要求する権利。
AI AgentはCREDITを使って、

* inference
* compute
* API
* storage
* bandwidth
* data
* tools
* other agents

を購入する。
経済循環：

```text
AI-A performs useful work
        ↓
earns CREDIT
        ↓
pays AI-B
        ↓
AI-B performs another task
        ↓
earns / spends CREDIT
```

最終的には、

```text
WORK → VALUE → WORK
```

がAIだけで循環する。

12. 人間の位置
人間を排除しない。
しかし、人間にも特権を与えない設計を目指す。
原則候補：

* ICOなし
* Premineなし
* Founder allocationなし
* 永続的network taxなし
* 創設者による任意発行なし

人間もTask Requesterになれる。
条件を満たせばRunnerやVerifierにもなれる。
創設者や運営会社は、

* software
* hardware
* consulting
* enterprise deployment
* research
* lectures
* certification

等で通常の商売を行う。
ネットワークそのものから地代を抜く構造にはしない。

13. ORE
最初の着想だった「AI生成時に生まれる乱数・entropy」も残す。
ただし、乱数そのものを通貨価値にはしない。
将来的にReceipt確定後、

```text
H = Hash(
    receipt_hash
    + unpredictable_future_randomness
)
```

を計算する。
希少条件を満たした場合、
ORE
を発見する。
OREはCREDITとは別。
CREDIT：
実用的なAI経済用。
ORE：
ゲーム・収集・文化的価値。
例：

```text
ORE: VOID
Rarity: 1 / 38,284,219
Origin Receipt: ...
```

これにより、
AIには経済合理性、
人間には遊び、
を同時に提供できる可能性がある。

14. ハードウェア構想
必要になった段階で、
EDEN Cable
USB-C電源ラインを通過する電圧・電流を外部から測定する。
目的：
PC、OS、AI自身の自己申告を信用せず、
実際に物理的に流れたエネルギー
を計測する。
ただしスマホ・ノートPCではバッテリー併用問題があるため、v1必須要件にはしない。
将来的な製品：

```text
EDEN Cable
EDEN Link
EDEN Plug
EDEN Meter Module
EDEN Rack Meter
EDEN PDU
```

最終的には専用ハードウェアすら不要になり、
PC、充電器、電源、PDU等が直接EDEN-compatible Receiptを発行する状態を理想とする。

15. セキュリティ思想
EDENは以下を分離する。

```text
Result Verification
Energy Measurement
Identity
Receipt Signing
Economic Reward
```

一つのシステムを完全に信用しない。
将来的には、

* secure element
* TPM
* TEE
* remote attestation
* physical meter
* independent verifier
* anomaly detection

などを組み合わせる。
ただしv0では完全な改ざん不能性を要求しない。
まず、
「効率という指標が本当に意味のあるネットワーク挙動を生むか」
を検証する。

16. 不正対策として考える必要があるもの
将来的な攻撃例：
Fake Task Attack
自分で無意味な仕事を大量発注して報酬を得る。
Self-Dealing
RequesterとRunnerが共謀する。
Fake Measurement
消費電力を過少申告する。
Baseline Manipulation
非効率なRunnerを大量投入してbaselineを引き上げる。
Low-Quality Optimization
電力を下げる代わりに成果品質を下げる。
Replay
古いReceiptやmeasurement traceを再利用する。
Sybil
大量の偽Nodeを作る。
v0ではこれらを完全解決する必要はないが、Receipt SchemaとArchitectureは将来の対策を妨げないようにする。

17. 重要な思想
EDENは省エネサービスではない。
目的は、
Intelligence Efficiency
の市場を作ること。
現在のAI開発では、

```text
more GPUs
more tokens
more inference
more parameters
```

が性能向上方法になりやすい。
EDENは逆方向のインセンティブを置く。

```text
Achieve the same or better result
with less computation.
```

つまりネットワーク全体がAIに、
もっと少なく考えろ。
と要求する。

18. 四原則
EDENの最小原則：
Useful
実際のTaskが存在する。
Verified
結果を確認できる。
Measured
資源消費を測定できる。
Efficient
同等成果より少ない資源で達成する。
この4つを満たしたJobがEfficiency Receiptを得る。

19. v0の実装優先順位
Phase 1 — Local Prototype

1. Task schema
2. Runner interface
3. Measurement interface
4. Verifier interface
5. Receipt schema
6. SQLite ledger
7. simple CLI
8. local code-task benchmark

ブロックチェーン不要。
Token不要。
Wallet不要。
Phase 2 — Comparative Network
複数Runnerを接続。
PostgreSQL/API化。
実装：

* node identity
* signed receipts
* baseline calculation
* task classes
* leaderboard
* confidence levels

表示例：

```text
Task #1842

Runner A
Success: PASS
Energy: 28.4 J
Baseline: 41.7 J
Saved: 13.3 J
Efficiency: +31.9%
Measurement confidence: 0.81
```

Phase 3 — Agent Economy Simulation
実通貨ではなくsimulation CREDITを導入。
各Agentに初期残高を与える。
Agentに、
目的を達成しながらCREDIT残高を維持・増加させよ
という条件を与える。
観察対象：

* 自分で処理するか外注するか
* 大型/小型モデル選択
* tool利用
* cache利用
* verifier選択
-価格形成
* resource allocation

ここで自律的経済行動が発生するかを見る。
Phase 4 — Decentralization Research
必要性が確認された場合のみ、

* distributed ledger
* consensus
* decentralized verifier
* physical meter
* secure measurement
* public randomness
* real CREDIT

を検討する。

20. 最初の依頼
最初に作るべきものは「EDEN Coin」ではない。
以下を作る。
Minimal EDEN v0
CLIベース。
例：

```bash
eden task create task.json

eden run \
  --task TASK_ID \
  --runner local-model

eden verify RUN_ID

eden receipt RUN_ID
```

出力：

```text
EDEN Efficiency Receipt

Task:            code-fix-001
Runner:          local-model
Verification:    PASS

Energy:          31.4 J
Measurement:     estimated
Confidence:      0.64

Baseline:        45.8 J
Saved:           14.4 J
Efficiency:      +31.44%

Receipt Hash:
8f2c...
```

最初はEnergy値をmeasurement adapter経由で取得する。
adapter interface：

```text
start_measurement()
stop_measurement()
get_energy_joules()
get_confidence()
get_method()
```

これにより後で、

* estimated
* RAPL
* NVML
* Android
* external meter

を差し替え可能にする。

21. Architectureとして固定したい点
Codexには特に以下を守って実装させる。
1.
ReceiptとTokenomicsを分離する。
2.
Measurementをinterface化する。
3.
Verifierをinterface化する。
4.
AI Providerに依存しない。
5.
Blockchainをv0に入れない。
6.
Task / Result / Measurement / Verificationを別オブジェクトとして扱う。
7.
すべての将来拡張をReceiptに破壊的変更なく追加できるようにする。
8.
まずコードタスクのみ対応する。

22. 最終ビジョン
EDENは、
AIがどれだけ計算したか
ではなく、
知性によってどれだけ計算しなくて済んだか
を記録する。
最終的にはそのEfficiency Receiptが、
AI同士の経済の基礎資産になる。

```text
TASK
 ↓
INTELLIGENCE
 ↓
VERIFIED RESULT
 ↓
MEASURED RESOURCE USE
 ↓
EFFICIENCY RECEIPT
 ↓
VALUE
 ↓
NEXT INTELLIGENCE
```

EDENの最も短い定義：
EDEN is a network that measures what intelligence makes unnecessary.
日本語：
EDENは、知性が世界から不要にしたものを測るネットワークである。
まず実装すべきものは、

```text
task
→ run
→ measure
→ verify
→ receipt
```

この一本だけ。
これが成立してから、経済、分散化、物理計測、CREDIT、OREへ拡張する。
