# EDEN Protocol 設計書

版: v2（frontier-mint転換後）
日付: 2026-08-16（実装記録は追補1〜4を参照）
状態: v0実装済み・実測済み・公開済み（https://github.com/ozoz5/eden-network）。敵対監査1周通過。
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

### v0実装記録 追補4（2026-08-18 — 外部レビュー（GPT）の反映）

公開リポジトリへのGPTレビューを現物と突き合わせ。旧版READMEへの指摘（撤回済み数字等）を除き、生存3点を即日修正:
- **複製群キーにrunner_code_hashを追加**: (runner_id, runner_code_hash, meter_id)。同名runnerのコード差し替えで
  他実装のσを継承する攻撃を遮断。表示は `runner#hash6@meter`
- **同一メーター内認証ゲート**: 異なるmeter classの群同士のdominanceは認証不能（§2.2のv0最小実装）。
  バイアスした安価な計測が実測メーターの前線を奪う経路を遮断
- **設計書ヘッダの「実装未着手」を実態に更新**

採用した言い換え（GPT由来、公開文書へ反映）: code-fix実験が証明したのは「rule-based > LLM」ではなく
**「正しい事前知識を持つspecialistはgeneralistより桁で省資源」**であり、EDENは
**「この問題について事前知識を持つことの価値」を物理量（J）として測っている** — brute 1.538 J と
rules 0.343 J の差は、PATTERN/FIXという知識が消した約1.2 Jである。

§6へ追加:
17. **Instance cherry-picking / challenge分布**: family_idはseedを除外するため、「偶然簡単なinstanceだけ提出する」
    前線選別が可能。前線は「自由に選んだ問題の最小J」ではなく「プロトコルが配布するchallenge分布に対する期待J」で
    定義すべき（§6.13の計測窓ゲーミングと対）。v0.1のFrontier eligibilityモジュール（meter class・runner hash・
    challenge sampling・replication・ρ・audit条件の一元化）で扱う。

### v0実装記録 追補5（2026-08-18 — v0.1: Frontier eligibilityモジュール）

発行に関わる全条件を `eligibility.py` として独立モジュール化（GPTレビュー提案の採用）。eden.pyは委譲のみ。

**強制される条件（テスト25本で固定）:**
- 複製キー (runner_id, runner_code_hash, meter_id)
- σ規則: 実測σ(n≥3)のみ√n縮小、assigned_cvは全幅、下限0クランプ
- 同一メーター内でのみdominance定義（異メーター比較は認証不能）
- 記録保持・奪取に最小再現数 n≥3（MIN_REPLICATIONS）
- **ρゲート**: ρ = E_verify/E_run > 1.0 の群は記録は取れるがmintは発生しない（§5のmint定義域のコード化。
  認証と発行の分離 — 記録は歴史、mintは経済）
- 純利得 > 0（憲法III）

**未強制の条件（§2.2/§6由来。assessは常に "pending" として明示報告し、検査済みを偽装できない）:**
challenge sampling（§6.17）／独立再現（§6.2）／challenge audit・hidden holdout（§6.13）

これによりv0.1の発行規則は全て単一ファイルで監査・単体テスト可能になった。「single file on purpose」は
「two files on purpose」に改訂（パイプラインと発行規則の分離はReceipt/Frontier/Mint三層分離の実装版）。

### v0実装記録 追補6（2026-08-18 — v0.2: challenge samplingと§9初回実験）

**実装（challenge.py + epoch台帳4テーブル + CLI `challenge open/run/report`、テスト31本）:**
- epoch seedは台帳から再計算可能（H(family | epoch番号 | 直近レシート群)）。監査可能だがtrustlessではない
  （運営者はレシート追加でgrind可能 — 痕跡は残る。真の解はv1§13のORE型公開乱数、未決のまま）
- **enrollmentがinstance生成に先行**: runnerコードハッシュはinstance公開前にcommitされ、
  実行時にハッシュ照合。事後にコードを問題へ合わせる経路を遮断
- instance生成はバグ注入（正解モジュールへのseeded単一変異、コンパイル可能かつテスト破壊を検証）。
  epoch内重複は決定論的リトライで回避
- 生成エネルギーは計測窓外（§6.13の実例として記録）

**§9初回実験（epoch 16c4b89c798ea9e9、6インスタンス × 3runner、2026-08-18実測）:**

```text
codefix_brute  6/6 (100%)  total   8.4 J  → 1.41 J/success   [estimated]
codefix_rules  0/6 (  0%)  total   0.9 J  → ∞                [estimated]
codefix_llm    1/6 ( 17%)  total 893.9 J  → 894 J/success    [Level V]
```

**発見（3点）:**
1. **cherry-pickingは実在した**: 手動family（自選の1バグ）でLLMは8/8成功だったが、プロトコル配布の
   分布では1/6。自分で選んだ問題での成績は分布上の成績を予測しない — challenge samplingを実装した
   瞬間に、それまでの数字の選択バイアスが可視化された
2. **J/successが失敗を課金する設計（§8）が機能**: LLMの失敗5回は各130〜165 Jを実際に燃やしており、
   成功1件あたりの真のコストは894 Jに跳ねた。成功時だけ数える指標では絶対に見えない数字
3. **専門知識は分布外で死ぬ**: rulesは全滅（0.15 J/回で正直に諦める）。知識の価値は分布依存

**宣言すべき偏り（過大主張の禁止）**: 注入バグの語彙（単一トークン変異8種）はbruteの探索語彙の部分集合であり、
この分布は構造的に探索側有利。「探索がLLMに勝つ」ではなく「単一トークンバグ分布では探索が支配する」が正しい主張。
深いバグ類（複数行・意味的）ではbruteは崩れる — 分布の設計自体が前線の意味を決める（§6.17の実証）。

**ハーネス検証**: 失敗したinstance 2の手動再現はPASS（確率的失敗）、instance 0/4は再試行でもFAIL
（クラス依存の実力）。5/6失敗はハーネス欠陥ではなくモデルの実測。

### v0実装記録 追補7（2026-08-18 — v0.3: Distribution CertificateとPareto前線）

challenge epochの集約結果を前線の正式な入力単位にした（GPTレビュー第2弾の中心提案の採用）。
世界記録の定義が変わる: 「この問題を0.3 Jで解いた」ではなく
**「プロトコル配布の分布Dを、成功率qで、成功1件あたりX Jで処理した」**。

**実装（テスト38本）:**
- `Distribution Certificate`（distribution_certsテーブル）: epoch × runner × meterの集約 —
  成功率（Wilson 95%区間付き）、総エネルギー、J/success。**検証エネルギーはcertのコストに内蔵**
  （憲法IIIは控除ステップではなく構造になった）
- **前線は(成功率↑, J/success↓)の2次元Pareto**（meter層別）。設計書§3の「Quality × Resource Pareto前線」が
  1次元退化を脱して本来の形になった。GPTの例（A:100%/20J、B:95%/10J、C:60%/2Jが共存し、
  D:96%/8JがBだけを支配する）はテストで固定済み
- **mintはcert登録時に台帳順序の純関数として発生**（監査指摘G「発行が照会タイミングの関数」への解答、
  challenge familyについては解決）。genesisはmintなし。無限J/success（成功0）のcertを支配しても
  価格付け不能でmintなし。単位は「J/success改善1につき1 CREDIT」（v0仮）
- MIN_INSTANCES=5未満のepochはcert不適格。失敗runのエネルギーはcertに全額算入され、
  **監査指摘C（憲法II×III衝突: 失敗コストの発行会計漏れ）はchallenge familyについて構造的に解消**

**初回の分布前線（実データ）:**
```text
★ brute  rate 100% [61,100]  1.590 J/success   ← estimated層の前線
  rules  rate   0% [ 0, 39]  ∞
★ llm    rate  17% [ 3, 56]  894.004 J/success  ← powermetrics層（単独genesis）
```

残る構造課題: 1D前線（非challenge family）とdist前線の併存はv0.4で統合判断。
区間考慮のPareto支配（ci95重複時の保留）は未実装（pendingに追加すべき）。

### v0実装記録 追補8（2026-08-18 — WITNESS独立再現: EDENが2ノードになった日）

TwinLoop Relay `shadow_verify_v1`（署名付きジョブ・任意コマンド不可）経由で、サブ機WITNESS（M1 Air / 8GB /
macOS 26.5.2 / Python 3.9）にEDEN計測パイプラインをテストペイロードとして送り、レシート6枚を
ログ経由で回収してFORGE台帳へ取り込んだ（`eden import`、無署名クレームと明示）。

**確定した事実:**
- **family_idが両ノードで独立導出され完全一致**（`2a8243b5b0f9f404`。Python 3.14 vs 3.9、別マシン）—
  §4の機械導出が初めてクロスノードで実証された
- **runner_code_hashも両ノードで一致** — 同一実装の証明がハッシュで通った
- **ハードウェア指紋層別が機能** — 同一runner・同一メーターでもhwf991f2（FORGE/M5 Pro）と
  hw10f070（WITNESS/M1）は別群となり、σを共有しない
- **初のハードウェア波動データ（§6.3）**: 同一コードのcpu時間比 M1/M5 Pro ≈ 1.4×
  （naive 0.595 vs 0.408 J、counter 0.128 vs 0.094 J — estimated同一6.0W仮定下、実質cpu秒比較）
- 輸送はSHA-256付きtransport receiptで検証可能（job d1054dbd、verdict: pass）

**過程で発見・修正**: WITNESSのsandboxは全書き込みに128KB上限（RLIMIT_FSIZE）。コーパス→12kトークン、
SQLiteページ→1024バイト（新規DBのみ、eden.py恒久修正）で通過。3回の実測往復（1.2MB失敗→352KB失敗→
72KB+44KB成功）で限界値を確定。

**正直な限界**: WITNESSレシートは無署名（データ完全性は未決のまま）。6.0W/cpu秒の仮定は両機共通に
適用しており、実際の電力差は測っていない（M1のLevel V化はWITNESS側のsudo許可が必要）。
再現はn=2/群であり、記録保持資格（n≥3）には満たない — これは意図的で、次のepochで積む。

### v0実装記録 追補9（2026-08-18 — §9本実験: 「賢い省計算」は実在した）

epoch cc84667499ff60d5（12インスタンス・有効バグ8種の分布・enrollment固定）× 7戦略、
LLM系は全てLevel V（GPU込みパッケージ実測）、全失敗課金、検証エネルギー内蔵。

```text
戦略                 成功    J/success(検証込)  メーター
cascade(rules→brute→1.5b→7b)  12/12  1.37   Level V   ← os-counter前線を単独保持
brute                12/12  1.53             estimated ← estimated前線
phi4 (14b)           11/12  287              Level V
qwen2.5:1.5b          6/12  81.5             Level V
qwen2.5:7b            5/12  391              Level V
7b×リトライ3          5/12  404              Level V
rules                 0/12  ∞                estimated
```

**発見4点:**
1. **カスケードが全部門制覇** — §9の中心仮説「賢い省計算は発見できるか」への肯定的回答。
   安い順に昇格する合成戦略が、100%成功をphi4の1/210のJ/successで達成し、
   Level V実測でPareto前線を単独保持した（phi4もdominated）
2. **小型は成功1件あたり3.5〜4.8倍安い** — 1.5b（50%・81 J/s）は7b（42%・391）をPareto支配し
   （+310 CREDIT simulated）、phi4（92%・287）より単価で3.5倍安い。「小さく考える方が安い」は
   この分布では真。ただしカバレッジ50%が代償
3. **リトライは系統的失敗に効かない** — retry3は単発7bと同率（5/12）のままコストだけ3%増。
   7bの失敗は確率的でなく系統的（同じ誤修正を繰り返す）で、リトライが買えるのは確率的失敗のみ。
   単発877 J→リトライでも成功率不変、は実測しないと出ない数字
4. **7bの成績が前回1/6→今回5/12に変動** — 小標本の分布依存性そのもの。ci95の重なりが
   「n=12でも断定するな」と言っている（区間考慮Pareto支配の必要性を再確認）

**宣言すべき偏り（毎回書く）**: バグ語彙8種はbrute/cascadeの探索語彙の部分集合。カスケードの
LLM段は一度も発火していない（rule/brute段で全部解決）。この分布での「カスケード勝利」は
「探索可能な分布では安い段で止まる設計が正しい」の実証であり、LLMが必要な分布での成績は未測定。
12インスタンス中4つは重複バグ（変異可能サイトの実数が上限）。実験中の並行負荷は最小。
mint合計 +892.7 CREDIT（simulated、J/success改善建て）は台帳に記録済み。

### v0実装記録 追補10（2026-08-18 — 探索を打ち破る分布: 前線は反転した）

意味変異6クラス（母分散化・ソート消し・分子分母反転・中央値index・非中心化・最終値平均）を追加。
**全クラスが単一トークン置換で不可逆であることをテストで証明**した上で、code-fix/3として別family化
（分布難度が違うものを同じ前線で比較しない — cherry-picking対策の裏面）。epoch f7f0863a、
12インスタンス×同7戦略、条件は前回と同一。

```text
戦略           成功    J/success(検証込)   前回(token分布)
phi4 14b       11/12   221     ← 前線＆王座    11/12 287
cascade         6/12   299     ← 支配された    12/12 1.37 ← 前回の王者
1.5b            4/12   111     ← 前線（単価王） 6/12  81
7b              3/12   617                     5/12  391
7b×リトライ3    3/12   742                     5/12  404
brute           0/12   ∞      ← 証明通り絶滅  12/12 1.53
rules           0/12   ∞                       0/12  ∞
```

**発見（今回の核心）:**
1. **前線は戦略の性質ではなく分布の性質** — 昨日の王者カスケードはphi4にPareto支配され（+77 CREDIT）、
   絶対王者は存在しないことをEDEN自身が実証した。「どの知性が効率的か」に分布非依存の答えはない。
   これが§6.17（challenge分布が前線の意味を決める）の最終実証であり、引用可能な一行になる
2. **安い順カスケードは「安い段がときどき当たる」分布でしか勝てない** — 全外れの安い段は純粋な
   無駄コストになり、かつ昇格先(1.5b→7b)がphi4より弱ければ二重に負ける
3. **1.5b>7bのPareto支配が2分布連続で成立**（+506 CREDIT）— qwen2.5:7bはこのタスク族では
   同族の1.5bに成功率でも単価でも劣る。分布を変えても崩れなかった唯一のLLM間関係
4. **リトライ無力も2分布連続** — 系統的失敗にはATTEMPTS×コストだけが増える
5. phi4のJ/successは難化で改善（287→221）— 意味修正は強いモデルには「短い仕事」

表示の既知課題: 成功0のcert（jps=∞）がestimated層の「前線」に残る（同メーター競合が居ないため
非支配）。無意味なので表示フィルタが要る（軽微、次コミット）。→ 追補11で解消済み。

### v0実装記録 追補11（2026-08-18 — 文化層・可視化・改竄検出）

- **ORE実装（v1§13、最後の未実装層）**: 封印epoch（レシート作成後最初に開かれたepoch）のseedとの
  ハッシュで希少判定。レシートは自分を封印する乱数を選べない（epoch seedは後続台帳から導出）。
  120枚の封印済みレシートから史上最初のSPARK 4つを発見。経済からの完全分離（§6.7）をテストで強制:
  経済フィールドなし・CREDIT変換なし・eligibility不import
- **eden html**: 台帳の自己完結ページ（前線SVG・mint史・ORE画廊）。読み取り専用の投影層 —
  「レシートは不変の観測、ページは版を持つ解釈」（憲法IVの可視化）
- **改竄検出チェーン（監査指摘10/16の解消）**: append-onlyのchain journalを新設。各entryが前entryに
  コミットし、`chain verify`が全receipt本文の再ハッシュとリンク再計算で改竄を検出する
  （改竄を不可能にはしない — 検出可能にする。単一ノードの正直な限界）。UPDATE攻撃・リンク改竄の
  検出をテストで実証。**chain headは公開gitのコミットメッセージへ焼き込み、git履歴を外部アンカーとする**
- 0成功certの前線表示問題を解消（空メーター層は「無限の前線」を持たない、テスト付き）
- テスト52本。2026-08-18時点のchain head: 4bf1aa201b16c386f8423048daeb0643ec6baac4b316e9156111081bda7bf6e9
  （147レシート、verdict: INTACT）※「52本」は数え間違いで実数は51本（追補12で訂正）

### v0実装記録 追補12（2026-08-18 — 第2次外部監査: 敵対的プロトコルとしての穴）

外部監査（研究プロトタイプ8/10・敵対的ネットワーク4/10・実通貨基盤2/10）の生存判定と同日修正。
全指摘が現行コードと一致する正確な監査だった。

**同日修正（CRITICAL×3＋HIGH×2＋MEDIUM×2）:**
- **C1 Challenge事前予測可能** → seed v2: H(family | epoch | enrollment commitment | **commit後に取得する
  外部乱数**)。乱数源はdrand(Cloudflareミラー)→NIST beacon→operator-local urandomの順で取得し、
  源と値をepochへ記録。fallbackは「参加者には予測不能・operatorは信頼前提」と偽装なく宣言。
  旧seed導出はv1として保存（過去epochの再計算可能性、憲法IV）
- **C2 無署名importが前線材料** → 検疫: `ext-`レシートは観測クレームとして保存されるが、
  frontier/certificationの入力から除外。署名+attestation実装までQUARANTINED
- **C3 familyが分布をコミットしない** → family材料にbug_mode・generator_fingerprint（注入コード＋
  語彙表のhash）・基材ソースhashを追加。**分布が変われば原則familyが変わる**。既存familyのIDは
  変わる（新familyとして再出発、旧前線は履歴。verifier変更時と同じ扱い）
- **H4 点推定Pareto** → 二層化: Observed frontier（点推定）とCertified（Wilson区間分離 or
  J/successマージン20%）。**mintはCertifiedのみ**。マージンはcertごとのエネルギー区間が
  できるまでの暫定と宣言
- **H5 coverage未証明** → certify時に COUNT(DISTINCT instance_index)==n_instances と
  全runのcode hash==enrollment hashを検証
- **H7 cert集約にhardware不在** → v0ガード: epochのレシートが複数hardware指紋に跨る場合は
  certify拒否（クロスノード認証は未実装と明示）
- **M8 会計境界の言い切り** → README: 「EDEN measures marginal in-window execution cost」と限定
- **M9 ORE市場価値** → 「二次市場価値が生じてもプロトコルは保証しない」を仕様に明記

**未修正（設計判断・順序どおり次へ）:** H6のoperator grinding完全排除（epoch開設タイミングの
選択権はoperatorに残る — round事前コミット等はPhase 2）、署名/attestation本体（⑥）、
J/success側の真の信頼区間。

**監査の総括への同意**: 「研究として強いが、信用を置くにはまだ危険」は正確な現在地。
本監査前の実験結果（前線反転・1.5b>7b・リトライ無力）は測定として有効なまま —
攻撃されたのは数字ではなく、敵対環境での再現保証だった。

### v0実装記録 追補13（2026-08-18 — 第3次監査: C1残穴の即日修正と信頼層への警告）

第3次監査（研究8.5/10・敵対6/10・通貨3/10に上昇）。指摘の中心は
**「commitments first, THEN randomness」がコメント上の主張でしかなかった**こと —
乱数取得がenrollmentのDB commitより前にあり、operatorは乱数を見てから
「epochを開かなかったこと」にできた。正確な指摘で、即日修正:

- **2段階コミット化**: Phase A（epochスタブseed='PENDING'＋enrollmentsを永続化しcommit）→
  Phase B（外部乱数取得→seed確定をUPDATE）。**中止されたepochはPENDINGスタブとして台帳に残る** —
  operator grindingは不可能にはならないが、不可視から可視に変わった。epoch_idの導出も
  seed由来からcommitment由来へ変更（seed確定前にIDが存在する必要があるため）
- **認証根拠の命名分離**: 「Certified」を success-rate-certified（Wilson区間分離＝統計的根拠）と
  energy-margin-certified（20%マージン＝**プロトコルパラメータであってCIではない**と明示）に分離。
  certifyの出力とmints.noteに根拠を記録
- 完全解（未来のdrand round番号の事前固定＋commitment外部anchor）はPhase 2へ

**残る重い未解決（監査の重要度順に採用）:**
1. Node/Receipt署名（`"signatures": []` が埋まらない限りNetworkにならない — 最大）
2. Meter attestation 3. Verifier独立性 4. J/successの真のCI（bootstrap/階層モデル）
5. operator-grinding耐性乱数 6. family横断換算（経済学上の最大問題）
将来のtrust_state列（LOCAL/UNSIGNED/SIGNED/ATTESTED/VERIFIED）も採用予定として記録。

**監査の警告を正面から受ける**: 「次に署名を雑に実装すると一気に危なくなる。Trust Layerは
一番慎重に設計すべき」— 従う。**署名は今夜書かない。** Trust Layerは実装前に設計文書を書き、
悪魔の代弁者を実装前の設計段階に入れる（監査を後追いから前置きに変える）。

---

## 8. 検証済みの外部事実（2026-08-16時点の調査）

- SpecBench（arXiv 2605.21384, 2026-05）: visible testsを全フロンティアagentが飽和させてもholdout gapは残り、コード規模10倍ごとに+28pt拡大。
- The Verification Horizon（arXiv 2606.26300）: 固定verifierは能力向上で有効性を失い得る。verificationはgeneratorと共進化が必要。
- ML.ENERGY Benchmark v3.0（2025-12）: 46モデル×7タスクでJ/task測定。指標の学術基盤は既存。EDENの発明点は指標ではなく「検証済み成果と束ねたレシート台帳」。
- 計測誤差: nvidia-smiは近年GPUで実行時間の約25%しかサンプリングせず過少報告。RAPLは外部電力計と±3〜10%相関だがソケット単位でプロセス帰属不可。
- カーボン市場: REDD+でex-ante予測が実測の3.7倍のover-crediting。baseline-and-credit方式の構造的失敗事例。EDEN v1はこれと同型だった。v2はデジタルタスクの再実行可能性により反実仮想を観測へ置換して脱出。
- 競合: Gensyn（検証可能な計算、2026-04 mainnet）/ Bittensor（peer評価）/ Akash（GPU市場）— いずれも計算の販売・検証。「効率の価値化」ポジションは空白。


---

### v0実装記録 追補14（2026-08-19 — §6.1「最大の未解決」を測定可能にした）

family横断のΔJ→CREDIT換算は、議論で決めないと定めた（Phase 3で3方式を競わせる）。
その前段として、**現在の台帳で各方式が何を発行するか**を計算する `eden valuation` を実装。
mintルールは変えていない — 選択の根拠を作っただけ。

### 実データが示したこと（9件のmint、4family）

```text
mint  family     改善倍率   physical   demand   budget    ratio
  1   5cb6812f     37.8x       0.4%     0.2%    25.0%    26.5%
  5   00bbfbd4      2.3x      33.9%    43.2%    14.1%     6.0%
  7   00bbfbd4     59.6x       5.4%     6.9%     2.2%    29.8%
```

**現行のphysical方式では、37.8倍の改善が0.4%、2.3倍の改善が33.9%を受け取る。**
16倍賢い改善が、85分の1しか報われない。理由は単純で、前者は0.1J単位のfamily、
後者は100J単位のfamilyだから。**節約したジュールの絶対量と、示された知性は、
逆を向くことがある** — これが実測で出た。

### salt-the-mine誘因の数値化（§6.11の実装）

同じ「5倍改善」を100倍浪費的な土俵で行った場合の発行倍率:

```text
physical  100x  ← 浪費が報われる
demand    100x  ← 需要重みでは打ち消せない
budget      1x  ← スケール非依存
ratio       1x  ← スケール非依存
```

### 第4の方式 — ratio（改善倍率で報いる）

3方式に加え、`Mint ∝ log2(before/after)` を候補として追加した。
**改善の倍率は土俵のスケールに依存しない**ので、salt-the-mineが構造的に無効になる。
実データでも改善倍率の順位と発行の順位が一致する唯一の方式だった。

### まだ決めない

budgetはfamily定義と枠の大きさを誰かが決める必要がある（**ガバナンスが戻る** —
§5の「委員会を置かない」と衝突）。ratioは`before`の取り方に依存する
（sandbagged genesis §6.9と結合すると新しい攻撃面になり得る）。
**Phase 3のエージェント経済シミュレーションで実測して決める**という設計判断は変えない。
今回作ったのはその実験の測定器であり、答えではない。

### v0実装記録 追補15（2026-08-19 — 比較の単位はrunではなくinstanceだった）

外部監査の「bootstrapがinstance難易度の非IID性を扱っていない」への解答。
実測してから設計を決めた。詳細は `TRUST_LAYER_DESIGN.md` §21。

**epochが発行したのはinstanceであり、runではない。** 難易度はinstanceに属し、
難しいinstanceは全runnerを落とす。resampleの単位をinstanceへ移し（cluster
bootstrap）、同一epoch内の比較は**instance集合を一度だけ引いて両者に同じ引きを
見せる**paired比較にした。成功率の軸は離散二値なのでMcNemar厳密検定を使う。

```text
                                unpaired               paired
1.5b vs 7b (token bugs)     [55,162] vs [213,1060]   Δ [-979, -118]  両方
1.5b vs 7b (semantic bugs)  [62,435] vs [300, inf]   Δ [-inf,  -52]  pairedのみ
phi4 vs cascade             11/12 vs 6/12 (Wilson重なり)  McNemar p=0.031
```

**pairedは発行を増やす向きの変更**である。正当化は「unpairedは保守的だったのでは
なく、共通instance比較に対して道具が違っていた。偶然厳しいことは安全性ではない」。
代わりにpairing成立条件を厳格化した（同一epoch・全観測がinstance keyを持つ・
instance集合が完全一致）。**配列の位置は同一性ではない**という条件は、実装中に
自分のテストが捕まえた欠陥から来ている。

### 同じ調査で発行を1件取り消した

記録保持者 `16c4b89c:codefix_llm` は**6回中1成功**で区間が無限まで伸びる。
挑戦者の区間は完全に重なる。それでも旧コードは+502 CREDITを発行していた。
bootstrap区間が**保存されず、DBから読み戻した記録保持者が区間を失って到着する**ため、
点推定への20%固定marginだけが残っていたから。§20の原則どおり、保存もbackfillもせず
**比較時に台帳から再導出**する形にした。

台帳のコピーで3 epochを再生し、旧規則3 mint / 新規則4 mintを差分で確認。
**本番台帳は書き換えていない** — 既存6件のnoteは `SIMULATED-DIST`（基準名なし）＝
H4ゲート以前の規則で発行された履歴であり、憲法IVにより事実として残る。

副産物: 分析実行がcommit実行より弱い規則をpreviewしていた（`existing.append` が
`if commit:` の内側）、証明書を畳み込む順序が未指定だった（`ORDER BY` 追加）、
そして乱数400件のfuzzで**区間が引数の順序に依存していた**（認定が通る向きへ1順序統計量ぶん）。
