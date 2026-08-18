# EDEN Protocol 設計書

版: v2（frontier-mint転換後）
日付: 2026-08-16
状態: 概念設計の収束版。実装未着手。
正本: このファイル。起源は2026-08-16の設計対話（初期構想v1 → レビュー → frontier-mint転換）。

変更履歴:
- v1: 初期構想。baseline-and-credit方式（Saved = Baseline − Actual をmint根拠とする）
- v2: frontier-mint転換。Baselineを発行根拠から全廃し、Pareto前線の更新のみをmintイベントとする

---

## 0. 前文（思想 — 変更しない）

価値とは、知性によって不要になった資源である。

ただしプロトコルは「不要になったはず」のものに価値を発行しない。
前文は思想を語り、条文は観測だけを信用する。

EDENでは、記録を取ること（Receipt）と記録を破ること（Frontier更新）が同じ台帳上に存在する。
記録更新の瞬間だけ、反実仮想は観測に変わる。

一行定義:

```text
EDEN mints on observed dominance, not counterfactual savings.
```

EDENは「節約したはず」に金を出さない。
実測された知性の前線を更新したときだけ、新しい価値を発行する。

象徴語: **record**（make a record ＝ 記録する / break a record ＝ 記録を破る）

一般向け説明: 知性が世界記録を更新したときにだけ生まれる貨幣。

---

## 1. 憲法（4本・確定）

**I. Observation Before Prediction**
予測は発行根拠にならない。発行は観測にのみ基づく。
（予測モデルは価格付け・スケジューリング・事前スクリーニングに使ってよい。mintには使えない）

**II. Result Before Efficiency**
成果が証明されるまで、効率には価値を与えない。

**III. Net Efficiency Only**
計測・検証・監査を含む総資源が改善しなければ、効率改善とは認めない。

**IV. Facts Outlive Rules**
事実は規則より長生きする。
Observation Receiptは不変。FrontierとMintは版を持つ解釈であり改訂できるが、過去の事実からの再計算可能性を壊してはならない。

EDENは経済台帳である前に、知性の物理史である。
（帰結: Receiptは原則削除しない。保存コストはPhase 2以降の設計対象）

---

## 2. 三層アーキテクチャ（確定）

観測 → 合意された前線 → 発行 を完全分離する。

### 2.1 Observation Receipt（不変の観測事実）

```text
task_contract_version
task_instance_id
result
quality_measurement

run_energy
verification_energy
energy_boundary        # 会計境界の宣言（限界エネルギーか、アイドル按分込みか）

measurement_profile    # meter_profile_id。σはここからプロトコルが決定
uncertainty_profile

verifier_spec_hash
runner_id / meter_id / verifier_id
hardware_profile       # 事実として記録する。family_idには原則含めない

timestamp
signatures
```

**Receiptに入れてはならないもの: baseline / saved / mint額 / efficiency_ratio。**
（v1のschema例はここで§21.1の分離原則に自己違反していた。修正済み）

### 2.2 Frontier Certificate（Receipt群から形成される合意状態）

```text
family_id
epoch
eligible_receipt_set
measurement_requirements
current_pareto_frontier
frontier_rule_version
```

前線を動かすReceiptには通常より強い証明を要求する:
Level V/P計測 ＋ 独立再現 ＋ challenge audit。
偽の超低エネルギーReceipt 1件で前線を破壊させない（griefing対策）。

### 2.3 Mint Certificate

```text
Receipt X dominates Frontier Epoch Y by ΔFrontier
```

この証明が成立したときのみCREDITをmintする。

---

## 3. 発行規則（確定）

- **Work Income**: RequesterからRunnerへのCREDIT移転。総供給は増えない。
- **Innovation Mint**: Pareto前線の更新のみが新規発行を生む。
  マネーサプライはAI経済のGDPではなく、知能効率の進歩速度に連動する。
- **Difficulty**: 調整主体は存在しない。物理法則・アルゴリズム・ハードウェア・数学そのものが壁になる。前線は押すほど硬くなる。**R&D is mining.**
- **Certified Dominance**: `E_new_high < E_frontier_low` のときのみ支配を認める。信頼区間が重なる「改善」はmintしない。
- **σの自己申告禁止**: 不確かさは計測方式×ハードウェアクラスごとにプロトコルが割り当て、物理メーターとの定期校正で更新する。Runnerは方式を選べるが幅は選べない。
  （帰結: EDEN Cable等の物理メーターは「σを狭める装置」となり、ハードウェア事業に内発的需要が生まれる）
- **独立再現による区間収縮**: 独立再現n回でσ/√nの収縮を認める。σ未満の実改善も反復により統計的に前線を抜ける（凍結前線問題の解法）。
- **commit-reveal**: 前線更新の優先順位はcommit時刻で決める。検証者による前線フロントランニングを防ぐ。
- **quality次元の一般化**: 前線は(Quality, Resource)空間のPareto前線。発行量は概念的に `Mint ∝ ΔFrontier Hypervolume`。v0はQualityがPASS/FAILなので1次元に退化し `ΔE = PreviousBest − NewBest` で足りる。

---

## 4. Task Family（確定）

自己申告禁止。機械的に導出する:

```text
family_id = H(
    task_contract_version
  + verifier_spec_hash
  + input_schema_hash
  + task_generator_hash
  + quality_metric_hash
  + resource_boundary_profile   # 粒度は粗く保つ。※注意参照
)
```

※注意: resource_boundary_profileの粒度を細かくするとハードウェアクラスごとに前線が分裂し、ゲリマンダリング（柔らかい前線の乱造）が再発する。粗粒度に限定するか、含めない案を残す（未決6.8）。

Verifierを変更したらfamily versionも変わる。旧Frontierは履歴として残る（憲法IV）。

### Family Lifecycle

```text
OBSERVE → CALIBRATE → ELIGIBLE → MINTING → RECALIBRATION / SUSPENDED
```

CALIBRATE通過条件（例）:
- 十分な独立Runner数
- 一定数の高信頼Receipt
- ρ（検証/実行比）が閾値以下
- 測定誤差が許容範囲
- verifier robustness test合格

新familyを乱造しても即mintできない。架空family攻撃の経済的メリットを削る。

---

## 5. 定義域原則（確定）

```text
ρ = E_verify / E_run
```

ρが閾値以下のfamilyだけがmint対象。ρは台帳のReceipt（verification_energyを含む）から実測できるため、定義域の判定はデータ駆動で行い、委員会を置かない。

ρは固定値ではない。検証を安く正しくする技術はEDENの定義域そのものを拡げる — Runnerだけでなく検証技術にも巨大なインセンティブが生まれる。

**v0ドメイン: Short-Horizon, Cheaply Verifiable Computation。**
小さな関数修正、アルゴリズム問題、データ変換、圧縮、決定的計算、形式検証可能な問題。
根拠: reward hacking gapはタスク規模とともに拡大する（コード規模10倍ごとに+28pt。SpecBench）。「Coding全般」は広すぎる。

Verifierは固定しない。visible tests ＋ hidden holdout ＋ ランダム検査 ＋ property-based / metamorphic verification（インスタンス無限生成可能な検証が長期の本線。hiddenテストは使えば燃える）。Verifierはgeneratorと共進化させる。

---

## 6. 未決問題（決め方まで含めて記録する）

1. **Family横断のΔJ→CREDIT換算** — 最大の未解決。hypervolumeはfamily内の量であり、family間の価値は物理でなく経済。Phase 3で最低3方式を競わせて実測で決める:
   - Physical Mint: `Mint ∝ ΔJ`
   - Demand-Weighted Mint: `Mint ∝ ΔJ × verified demand`（偽需要は実ジュールを燃やすためコストは掛かるが、self-dealingを呼び戻す）
   - Budgeted Family Mint: family別発行枠＋半減期
   観察対象: 流通、投機、family spam、self-dealing、価格安定性。
2. **発見者/再現者の報酬分配** — 100/0か、70/30か。Phase 3実験。注意: 再現側に報酬を置くとSybil圧が再現へ移動する（偽再現カルテル）。再現報酬は独立性証明（別ハードウェア・別identity・stake）が前提。
3. **ハードウェア波動** — 新チップ登場で全family前線が一斉更新可能になり、発明ゼロの大量mint波が起きる。補正はしない（補正＝予測であり憲法I違反。方法は問わず結果と物理資源だけを見るブラックボックス原則とも一致）。帰結（世代同期のmint波、早期アクセス資本の優位）は公平性の問題として観察を続ける。
4. **hypervolume reference point** — quantile問題は1次元では消えたが、品質軸を足すとreference point選択として転生する。「消えた」ではなく「v0では退化により消えている」。
5. **慢性デフレ** — supply ∝ 進歩速度の裏面。進歩の飽和とタスク需要の成長が重なると恒常増価→退蔵→流通速度低下（Bitcoinの価値保存漂流と同型の力学。一般論であり未実測）。Phase 3観察対象。
6. **stake / identity / audit経済** — ランダム監査の抑止には `P(audit) × Penalty > 不正利得` が必要で、Penaltyにはstake / bond / future earnings collateralが要る。実通貨フェーズより前にarchitectureとして identity / stake / challenge / audit / slash を想定する。v0では仮想CREDITでシミュレーション。
7. **ORE** — 経済プロトコルから完全分離（確定）。CREDIT交換・優先mint権・stake利用のいずれかを許した瞬間に実質premineになる。ゲーム・文化的collectibleとしてのみ存在し、CREDIT発行権には一切影響しない。
8. **family_idにおけるresource_boundary_profileの扱い** — 含めるなら粗粒度、含めない案も残る（§4注意）。

---

## 7. v0仕様（確定・cut line）

今日の全設計変更を通っても、v0は一本のまま:

```text
task → run → measure → verify → receipt
```

- CLI。SQLite。family 1個（short-horizon code fix）。
- Receiptは§2.1のschema（baseline/saved/mintを含まない）。
- family_idはハッシュで機械生成。
- Frontier = receiptテーブルからの区間比較付きSELECT。
- Mint = ログ出力のシミュレーション。CREDITは作らない。
- stake / epoch / hypervolume / commit-reveal は実装しない。schemaが将来それを妨げないことだけ確認する。
- Measurement adapterはv1構想通りinterface化（estimated / RAPL / NVML / external meterを差し替え可能に）。

### v0の最初の実験（最初の関門）

同一Runner × 同一Task × 10回。ジュールの分散を実測する。

```text
31.2 / 30.7 / 32.1 / 30.9 / 31.4 / 30.8 / 32.0 / 31.1 / 30.9 / 31.5 J
```

ここから初めて「この環境で1J改善は主張できるのか、5Jなら言えるのか、方式を変えるとσはいくつか」が現実の数字で話せる。
**EDEN最初の研究成果は通貨ではなくσである。それでいい。**

### v0のゴール（EDEN最初の「ブロック」）

Runner Bを投入して最初のrecordを作る。Runner Cがそれを破った瞬間:

```text
NEW FRONTIER
Previous: 31.3 J
New:      26.8 J
Improvement: 4.5 J
Independently verified
```

この表示が出た瞬間、EDENの全思想が1台のPCの中で実証される。
まず金を作るのではない。世界記録が更新される瞬間を作る。

### v0実装記録（2026-08-16 実装・実測済み）

実装: `eden.py`（単一ファイルCLI、Python stdlib only）+ `runners/`（4本）+ `tasks/topk_words.json`。
実行: `python3 eden.py demo`

- デモfamilyは設計の「code fix」ではなくデータ変換（top-k word frequency、§5定義域内）。
  理由: code-fix familyはLLM runner接続時に追加する。準備済みパッチではRunnerエネルギーが実測にならない。
- 実測（M5 Pro / macOS 26.5.1 / estimated-cpu-v1, 6.0 W/cpu-s仮定）:
  - σ = 0.037 J（naive_count×10、mean 5.680 J、cv 0.7%）。単発の証明可能最小改善 2σ = 0.074 J。
  - FIRST RECORD: naive_count 5.680 J → NEW FRONTIER: dict_loop 0.148 J（certified net gain +5.237、mint simulated）
  - counter_fast 0.139 Jはdict_loopを区間支配で更新したが、E_verify 0.27 Jを引くと **certified net gain = 0**。
    憲法IIIが初回実走で発火: 前線付近ではρ≈1.9（検証が実行の約2倍）となり、このfamilyは前線近傍でmint定義域の境界に達した。§5のρ原則の最初の実測例。
  - bad_topk（誤答・低消費）はFAIL → Receipt拒否（憲法II動作確認）。
- Receipt実物は§2.1準拠、禁止フィールド（baseline/saved/mint）不在をコード内assertで強制。

### v0実装記録 追補（2026-08-17）

- **code-fix family実装**（§8の本来ドメイン）: `tasks/codefix.json` + バグ入り `stats.median` + 12テスト。
  Verifierはunittest実行（tests-pass、計測付き子プロセス）。family_idはテストスイートのハッシュから導出。
- **Runner 3戦略の実測（J/success、全run込み）**: rules 0.343 J（前線）/ brute 1.538 J / LLM ≥2.44 J。
  「同じ検証済み成果を、知性の差で4.5倍のエネルギー差」が§8の主要指標で観測された。
- **本物のLLM Runner稼働**: ollama qwen2.5:7b がmedianバグを3/3で修正しPASS。
- **計測の盲点を発見・宣言**: Apple SiliconのLLM推論はGPU/ANEで走り、cpu-time採取では取れない。
  estimated-cpu+ollama-v1プロファイルに「joules are a lower bound」と明記し、Receipt実物に記録される。
  Level V化（powermetrics）はsudoパスワードが必要なため未実施（AIはパスワード入力不可）。ユーザー操作で解禁可能。
- git公開: README.md（英語・公開入口）追加。eden.db / data/ は.gitignoreで除外（台帳はローカル観測データ）。
- License未定 — 公開リポジトリのライセンス選定は本人判断待ち。

### v0実装記録 追補2（2026-08-18 — Level V達成）

- **PowermetricsAdapter実装**（powermetrics-package-v1、Level V / os-counter）:
  CPU+GPU+ANEパッケージ電力を100ms間隔で採取し、アイドルベースライン（pre-roll 0.5s実測）を控除して積分。
  root所有プロセスへはシグナル不可のため、pipe閉鎖→SIGPIPEで停止する設計。sudoers 1行（powermetrics限定NOPASSWD）で解禁。
- **6.0 W仮定の初校正**: cpu-boundタスクの実測は約9.3 W/cpu秒相当。仮定は約1.55倍の過少だった。
  旧レシートは生cpu秒を保持しているため再導出可能（憲法IVの実務初仕事）。
- **GPU盲点の定量化**: LLM推論の実エネルギーは57〜159 J/回（推論中パッケージ30.4 W vs アイドル3.7 W）。
  cpu-time計測の見かけ2.4 Jに対し**25〜65倍**の過少だった。計測レベルを上げたら物語が2桁変わった —
  Receiptが計測プロファイルとconfidenceを持つ設計思想（§6計測レベル）の実証。
- 実測J/success（code-fix family）: rules 0.343 / brute 1.538 / LLM 57〜159（同じ検証済み成果に約200〜450倍差）。
- 既知のデータ品質注意: codefix_llm群には旧計測（下限値）と新計測（Level V）のレシートが混在。
  群の平均は混在分だけ歪む。Receipt自体はどちらも正しい観測（計測プロファイル明記）であり、meter別の層別集計で解決する。
- 次: §9実験（実タスク群 × ローカルLLM複数 × 戦略比較）の実施が解禁された。

### v0実装記録 追補3（2026-08-18 — 悪魔の代弁者監査と一括修正）

4本の敵対監査（実装バグ／計測統計／プロトコル経済／公開物信頼性）を実施。反証が通らなかった指摘に基づき修正:

**実装修正（テスト14本で固定）:**
- 群統計を(runner, meter)で層別。異メーターのレシートは決してσを共有しない
- 区間下限を0でクランプ（負エネルギー区間の禁止）
- assigned_cv（系統誤差）は√nで縮小しない。√n縮小は実測σ（n≥3）のみ
- E_verifyはrunと同一メータークラスで計測（異スケールの減算を排除）
- `frontier`は既定で読み取り専用。`--commit`のみが状態更新・mintを行う
- holder消失時は不整合上書きせず明示的に再確立。同一遷移の再mint禁止。gain 0はmintなし
- 禁止フィールド検査をassertからValueError＋再帰キー名走査へ（-Oで消えない、値の誤爆なし）
- powermetricsのfallback計測は別プロファイルID（estimated-cpu-pmfallback-v1）
- アイドルベースラインは適応preroll（最低5サンプル。従来は2サンプルしか取れていなかった）
- 実レシート2枚をexamples/として公開。v1原本をEDEN設計書_v1_原本.mdとして収録

**公開数字の訂正（旧READMEの主張を撤回）:**
- 「9.3 W」→ n=3の最小値だった。n=10に拡張したところ並行負荷混入でcv 39%となり、校正定数としては不成立。
  「exclusive use assumed」は宣言であって事実ではないことが自データで実証された
- 「25〜65×」→ 異メーター・別run・分母不整合の比であり撤回。正しくは「cpu-time計測はGPU/ANE推論エネルギーの
  約20〜60倍を取り逃がす（レンジであって定数ではない）」
- 「200〜450×」→ どの整合的な割り算からも出ない数字であり撤回。異メーター比は公開不能
- LLM実測（Level V, n=5）: 51〜159 J/fix、mean 93.7 J、cv 57%（出力長の非決定性が支配）。全8試行PASS
- 追補2の「3/3」は当時の実行数（最終8/8）。日付の混乱（08-17/08-18）はJST/UTC併記漏れが原因

**§6へ追加する未決問題（監査由来、9〜16）:**
9. **Sandbagged genesis**: FIRST RECORDは無審査で復活したbaseline。最良解を伏せて遅い初記録を立てれば発行総量を
   開示戦略で操作できる。初期記録の審査規則が必要だが、審査主体は「委員会を置かない」（§5）と衝突する
10. **憲法II×IIIの衝突**: FAIL runはReceiptを持てないため失敗試行のエネルギーが発行会計から漏れる。
    retry-until-pass戦略は失敗コストを外部化できる。全run強制記録と選択的開示（--no-chain）の扱い
11. **Verifier共進化×family分裂の再発行インフレ**: verifier改訂のたびに新familyの空の前線が生まれ、
    同一知識が再mintされる。前線の互換写像（旧前線の持ち込み規則）が未定義
12. **Mint決定論化**: 発行は台帳の純関数であるべき。現実装は照会タイミングに依存する状態機械。
    net-gain-0遷移が将来の発行原資を無償で焼却するgriefing経路も未解決
13. **計測窓ゲーミング**: warm-up除外・入力の事前配布・テスト全文のRunnerへの開示（hidden holdout不在）・
    リモートオフロード（ネットワーク待ちはほぼ0 Jに見える）。境界宣言の検証可能化が必要
14. **σ割当のガバナンス**: K_SIGMA・assigned_cv・校正手続きを決める者は事実上のdifficulty調整者。
    「調整主体は存在しない」（§3）とσ割当制度は両立していない。低σ計測装置の保有は発行コストの二乗優位
15. **中心命題の限定**: EDENが測るのは「計測窓内に残された限界資源」。ルール作者の認知もLLMの訓練費も窓外。
    命題は「窓内限界資源の前線」として正直に限定するか、ハーネス固定費控除を定義する必要がある
16. **台帳の完全性**: 識別子の64bit切詰め（衝突2^32仕事）、mintのeligible receipt set不記録、
    INSERT OR IGNOREによる衝突の黙殺、hash chain・署名・外部アンカーの不在（改竄検出ゼロ）

**監査で反証できなかった角度（記録）**: getrusageのpowermetrics汚染なし（reap順序で保護）、
rootプロセスのリークなし、cputime解析正常、run/measurement孤児なし、topkタイブレーク決定論的。

---

## 8. 検証済みの外部事実（2026-08-16時点の調査）

- SpecBench（arXiv 2605.21384, 2026-05）: visible testsを全フロンティアagentが飽和させてもholdout gapは残り、コード規模10倍ごとに+28pt拡大。
- The Verification Horizon（arXiv 2606.26300）: 固定verifierは能力向上で有効性を失い得る。verificationはgeneratorと共進化が必要。
- ML.ENERGY Benchmark v3.0（2025-12）: 46モデル×7タスクでJ/task測定。指標の学術基盤は既存。EDENの発明点は指標ではなく「検証済み成果と束ねたレシート台帳」。
- 計測誤差: nvidia-smiは近年GPUで実行時間の約25%しかサンプリングせず過少報告。RAPLは外部電力計と±3〜10%相関だがソケット単位でプロセス帰属不可。
- カーボン市場: REDD+でex-ante予測が実測の3.7倍のover-crediting。baseline-and-credit方式の構造的失敗事例。EDEN v1はこれと同型だった。v2はデジタルタスクの再実行可能性により反実仮想を観測へ置換して脱出。
- 競合: Gensyn（検証可能な計算、2026-04 mainnet）/ Bittensor（peer評価）/ Akash（GPU市場）— いずれも計算の販売・検証。「効率の価値化」ポジションは空白。
