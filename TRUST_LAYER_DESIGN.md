# EDEN Trust Layer 設計書（草案）

状態: **Phase A / B / 失効 実装済み（2026-08-19）**。Phase C（meter attestation）は未着手
日付: 2026-08-18
対象: 第3次監査の未解決1〜3（Node/Receipt署名、Meter attestation、Verifier独立性）

---

## 0. この層が守るもの・守らないもの（最初に書く）

**守るもの:**
- 否認不能性: ノードは自分が発行したレシートを後から否定できない
- 改竄の帰属: chain（改竄検出）に署名が加わり、「誰の主張がいつ変わったか」を特定できる
- 越境検証の土台: 別ノードによる再検証（VERIFIED階位）を定義可能にする
- 将来のstake/slashの前提条件（罰するには相手の同一性が要る）

**守らないもの（署名を入れても残る穴 — 偽装しない）:**
- **嘘の計測**: 署名は「この主張はこの鍵の持ち主のもの」を固定するだけで、主張の真実性は固定しない。
  自己所有ハードウェアでのmeter attestationは本質的に弱い（EDEN Cable = 外部計測が最終解）
- **Sybil**: 鍵の生成は無料。identity ≠ 希少性。stake導入までSybil耐性はゼロのまま
- **単一台帳のoperator全能性**: 台帳保持者は依然として掲載拒否・順序操作ができる

## 1. 暗号方式の選定 — sshsig（OpenSSH署名）

**決定: `ssh-keygen -Y sign / -Y verify`（Ed25519, sshsig形式）を子プロセスとして使う。**

理由:
1. Python stdlibに公開鍵署名は存在しない。pip依存（cryptography等）はEDENの
   「stdlib only」原則を破る。OpenSSHは全対象OS（macOS/Linux）に標準搭載
2. 実装は20年監査され続けたOpenSSHに委ね、EDENは呼び出しと形式だけを持つ
   （自作暗号を書かない — この層で一番やってはいけないこと）
3. TwinLoop Relayが既にSSH鍵の署名運用を持つ — WITNESS統合が自然
4. sshsigはnamespace分離を持つ: `eden-receipt` / `eden-checkpoint` / `eden-epoch`
   を分けることで署名の転用（あるnamespaceの署名を別文脈で再生する攻撃）を防ぐ

鍵の保管: v0.5はファイル（`~/.eden/node_ed25519`、権限0600）。
Secure Enclave/TPMはPhase 2+（設計はここで固定しない）。

## 2. 署名対象の正準化

**実測で確定した規則（2026-08-18、この機で検証）:**

| 検査 | 結果 | 設計への帰結 |
|---|---|---|
| Ed25519署名の決定性 | 同一入力→同一署名 | chain/hashへ署名を含めても再現可能 |
| stdin署名（`-f key -n ns -`） | 可能（306 bytes） | **一時ファイルを使わない**（TOCTOU・権限・TMPDIR汚染の回避） |
| 署名レイテンシ | 4ms/件（147枚で0.6秒） | emit時の同期署名で運用上問題なし |
| 改竄検出 / namespace転用 | 両方 exit 255 で拒否 | 前提通り |

**自己監査で発見した正準化の穴（2026-08-18、実装前に発見）:**
Pythonの`json.dumps`は `Infinity` / `NaN` を出力するが、これは **RFC 8259非準拠** で
他言語のパーサは拒否する（実測: `parse_constant`で REJECTED）。EDENは J/success に ∞ を
扱う設計であり、正準化に非RFC値が混じると **署名の再検証が言語を跨いで不可能** になる。
実レシート147枚への混入は0件（レシートは常にPASS時のみ発行されるため）だが、規則として固定する:

```text
CANONICAL RULE (署名対象):
  json.dumps(body, sort_keys=True, separators=(",",":"),
             ensure_ascii=True, allow_nan=False)
  - allow_nan=False: Infinity/NaN は署名対象に入れない（入れば例外で停止）
  - ensure_ascii=True: 非ASCIIは\uXXXXへ正準化（実測: "測定" → "\u6e2c\u5b9a"）
  - 数値型の同一性: 1 と 1.0 は別文字列になる（実測）。よってレシート生成側で
    エネルギー値は常にfloat、カウントは常にintと型を固定する
  - 重複キーは再パースで後勝ち（実測）。署名検証は必ず「受信バイト列」に対して行い、
    パース済みオブジェクトを再シリアライズして検証しない
```

- 署名ペイロード = `canonical(receipt から signatures フィールドを除いた本体)`
- signaturesエントリ: `{role, node_id, alg: "sshsig-ed25519", namespace, sig_b64, signed_at}`
- role ∈ {runner, meter, verifier} — v1構想§15の分離をそのまま採用。
  **単一ノードでは3役が同一鍵に縮退する。これは縮退であって統合ではない**と
  レシート自身に記録する（`"role_collapse": true`）
- **node_id = SHA-256(公開鍵) の全64hex**（切詰めない）。表示のみ先頭12hexへ短縮する。
  第4次監査の指摘を採用: 識別子を短くする利益は見た目だけで、衝突耐性を失う代償に見合わない。
  **未実装の今なら変更コストはゼロ** — レシートへ焼き込まれた後では憲法IVにより不可能になる。
  同じ理由で `node_lineage_id`（§9.4）も全長を保存する。
  （台帳内の他ID — receipt_id/family_id等 — の16hex切詰めは既存レシートに焼き込み済みのため
   別問題として残る。新規に作る識別子は全長、が今後の規則）
- 公開鍵本体は台帳のnodesテーブルへ登録
  （単一台帳=中央レジストリであることを宣言。相互署名/web of trustはPhase 2+）

## 3. trust_state 状態機械（第3次監査の提案を採用）

```text
LOCAL     この台帳自身のパイプラインが生成（runs連鎖あり）
UNSIGNED  輸入・無署名（現在のext-レシート）
SIGNED    正準本体への有効なノード署名あり
ATTESTED  SIGNED + meter attestation（v0.5では同一鍵=弱いと宣言。実解はEDEN Cable）
VERIFIED  ATTESTED + 別ノードによる独立再検証（出力とテストを再実行して一致）
```

- 遷移は昇格のみ（降格は新しい事実の追加であり、既存stateの書換えではない — 憲法IV）
- **eligibilityへの接続**: 外来レシートの前線参加はSIGNED以上、
  外来レシートによる前線更新はVERIFIED以上。ローカルレシートはLOCALのまま
  自台帳で有効（単一ノードの現実を宣言した上で）
- 現行の`ext-`文字列規約はtrust_state列（ALTER TABLE、追加のみ）へ移行。
  既存147レシートはLOCAL/UNSIGNEDへ遡及分類（本文は不変、分類は解釈）

## 4. Verifier独立性 — 検証を独立した署名対象にする

- 検証結果を独立オブジェクト化: `verification_receipt` =
  `{run受領証hash, verifier_spec_hash, verdict, verify_energy, verifier署名}`
- 同一operatorのverifier署名は独立性ゼロ（宣言）。しかし形式を分離しておくことで:
  - **WITNESS再検証が最初の本物のVERIFIEDを作れる**: shadow_verify_v1で
    出力＋テストを送り、WITNESSが再実行し、WITNESS鍵で署名した
    verification_receiptを返す。2ノード目が初めて「他人の検証」になる
  - 第三者verifierの参入形式が最初から存在する

## 5. Chainへの接続 — checkpoint署名

- `eden chain checkpoint`: 現在のchain headにノード鍵でnamespace
  `eden-checkpoint`の署名を打ち、checkpointsテーブルへ追記
- 公開anchor（git commit本文へのhead焼き込み）と組で、
  「このheadをこの鍵が保証した」が時刻付きで残る
- epoch開設のPhase A（commitment永続化）にも`eden-epoch`署名を付け、
  C1の2段階コミットへ否認不能性を追加

## 6. 実装計画（設計監査通過後のみ着手）

- **Phase A**: `eden identity init/show` / emit時の自動署名 /
  `eden verify-signatures`（全署名の再検証コマンド）/ trust_state列 /
  checkpoint署名。テスト: 署名往復・改竄検出・namespace転用拒否・鍵不在時の
  明示的degradation（無署名生成をエラーではなくUNSIGNED明示で許す — 測定は
  信頼より先に存在してよい。ただし既定は署名）
- **Phase B**: WITNESS再検証 → VERIFIED階位の実データ生成
- **Phase C**: meter attestation（EDEN Cable系の外部計測と結合 — 設計は別文書）

## 7. この設計への既知の攻撃（自己申告 — 敵対監査への出題）

1. 署名時点とレシート生成時点の乖離（後署名: 生成後に都合の良いレシートだけ署名する選別）
2. 鍵ファイルの窃取・複製（0600はマルウェアに無力。Enclave移行までの窓）
3. verification_receiptのreplay（別runへの再適用 — run hash束縛の徹底で防ぐ設計だが、実装ミスの温床）
4. ssh-keygenのバージョン差・出力形式差による検証の非決定性
5. ~~node_id衝突（16hex切詰め）~~ → **解消済み**: node_idは全64hex保存へ変更（§2）。
   既存の16hex識別子（receipt_id等）の衝突リスクは残る（別課題）
6. 「SIGNED以上」ゲートがUNSIGNEDの正直な観測を経済的に無価値化し、
   署名鍵を持つ者だけの閉鎖経済になる誘因（アクセシビリティとのtension）

## 8. 自己監査で判明した設計の欠落（実装前に埋めるべき — 未解決）

外部監査エージェントが実行途中で停止したため、設計者自身が敵対役として攻撃した結果。
**「見つからなかった」ではなく「自分で見つけた」ものとして記録する。**

- **失効(revocation)が設計に存在しない**【設計致命】: trust_stateは昇格のみだが、
  鍵が漏洩した場合に過去の署名をどう扱うかが未定義。憲法IV（事実は不変）と
  「漏洩鍵の署名は信用できない」は正面衝突する。方針案: レシート本文は不変のまま、
  **失効イベントを追記オブジェクト**として台帳へ入れ、trust_stateの評価は
  「署名時刻 < 失効時刻」を条件に含める（＝解釈層で解決し、事実層は触らない）。
  ただし署名時刻の自己申告を信用する問題が残る → timestamp信頼はPhase 2の別課題
- **鍵ローテーション / アルゴリズムagility**【重大】: node_idが公開鍵ハッシュ由来のため、
  鍵を替えるとノードの同一性が切れる。ノード履歴の連続性をどう保つか未定義
  （案: 旧鍵で新鍵を署名する継承チェーン。ただしこれも漏洩時に悪用される）
- **後署名による選別**【重大】: §7-1の再評価 — 過小評価だった。emit時に必ず署名する
  設計にしても、operatorは「署名しないレシートを作らない」ことしかできず、
  **不利なrunをそもそもemitしない**選別は防げない。これはchallenge epochの
  coverage検証（H5）でのみ部分的に防がれている。署名では解決しないと明記すべき
- **複数署名の閾値**【軽微だが未定義】: role分離（runner/meter/verifier）を導入するなら、
  「何個の署名が揃えばSIGNEDか」の定義が要る。現設計は暗黙に1個

**結論: この設計はまだ実装可能な状態にない。** 少なくとも失効の扱いを決めるまで、
Phase Aに着手しない。

---

## 9. 失効(revocation)の設計 — 決定（2026-08-19）

§8の設計致命への解答。**時刻を信用せず、chain上の順序だけを信用する。**

### 9.1 中心となる観察

署名時刻の自己申告は信用できない（§8で指摘した通り）。しかしEDENは既に、
時刻に依存しない順序を持っている:

```text
chain journal  = 追記専用、各entryが前entryにコミット
chain head     = git commit本文へ焼き込み済み（外部アンカー）
```

**あるレシートがchainのどのseqにいるかは、gitの公開履歴が固定している。**
だから失効の判定に日時は要らない:

```text
署名が有効 ⟺ receipt の chain seq  <  失効イベントの chain seq
```

これは憲法I（Observation Before Prediction）の精神そのもの —
自己申告のtimestampではなく、台帳に観測された順序だけを根拠にする。

### 9.2 失効イベントの形

失効もまた事実であり、追記される（憲法IV: 既存事実は書き換えない）:

```text
revocation = {
  node_id, revoked_pubkey_fingerprint,
  reason: "compromise" | "rotation" | "retirement",
  successor_node_id  (rotationの場合のみ),
  declared_by: 失効を宣言する鍵（自己失効 or 継承鍵）,
  署名 (namespace: eden-revocation)
}
```

- 失効イベントはchainに入る（＝seqを持つ）。だから失効自体も順序が固定される
- **降格は起きない**: trust_stateは昇格のみのまま。失効は
  「そのseq以降の署名を評価しない」という*解釈規則*であり、
  過去のSIGNEDレシートの本文もstateも書き換えない
- 失効後に現れた同一鍵の署名は `SIGNED` に到達しない（UNSIGNED相当として扱う）

### 9.3 anchor頻度が失効の解像度を決める（正直な限界）

git anchorが最後に打たれたseqを `A`、現在のheadを `H` とすると:

- `seq ≤ A` の区間: 外部で固定済み。攻撃者は鍵を盗んでも過去へ遡って
  レシートを差し込めない（chain hashが壊れ、gitの記録と矛盾する）
- `A < seq ≤ H` の区間: **まだ外部で固定されていない**。
  鍵とローカル台帳の両方を握った攻撃者は、この区間を作り直せる

つまり **失効の実効的な保護は、直近のanchorまでしか遡らない**。
これは分散consensusの代わりに公開gitを使うことの正確な代償であり、隠さない。

対策（実装時の規則）:
1. `eden chain checkpoint` を打つたびにanchor推奨をCLIが表示する
2. 失効イベントを追記したら、**直ちに** checkpoint + git anchorを打つ
   （攻撃者が未anchor区間を操作する窓を最小化する）
3. anchor間隔はレシート数ではなく「未anchorの区間長」として台帳に表示する

### 9.4 鍵ローテーション（§8の重大項目への解答）

- `reason: "rotation"` の失効イベントに `successor_node_id` を含め、
  **旧鍵で新鍵を署名**した継承レコードを添える
- ノードの同一性は「鍵」ではなく「**継承チェーンの根**」で定義する:
  `node_lineage_id = 最初の公開鍵のhash`。以後の鍵はこの系譜に属する
- 漏洩(compromise)の場合は継承を許さない: 盗まれた鍵で後継を指名できてしまうため。
  compromise失効後の新鍵は**新しい系譜**として出直す（履歴の連続性を失う代償を払う）

### 9.5 この設計に残る穴（自己申告）

1. **operatorが失効イベントをchainに入れない**: 失効の隠蔽は防げない。
   第三者がanchorを監視して不一致を叫ぶしかない（分散化の前借りはできない）
2. **未anchor区間の書き換え**（§9.3）: anchor頻度で緩和するのみ
3. **自己失効の可用性**: 鍵を失った（漏洩でなく紛失した）ノードは自己失効を署名できない。
   → 事前に「失効宣言を先に署名して保管しておく」(pre-signed revocation) を推奨事項とする
4. **系譜の分岐**: 同一系譜から2つの後継が出た場合の解決規則が未定義（Phase 2）

### 9.6 結論 — Phase Aのブロック解除条件

§8の設計致命は解けた（時刻ではなく順序で解く）。残る§8項目のうち:
- 鍵ローテーション → §9.4で解決
- 後署名による選別 → **署名では解決しないと確定**。challenge coverageで縛る
- 複数署名の閾値 → v0.5では「role毎に1署名、SIGNEDはrunner署名のみで成立」と定義。
  meter/verifier署名は ATTESTED/VERIFIED の条件であり、SIGNEDの条件ではない

**Phase A着手可。** ただし実装は §9.3 の anchor 規則を含むこと。

### 9.7 設計を書いた直後の自己攻撃（同日、実装前に発見）

**発見1【設計致命】: chainは失効イベントを入れられない。**
現行スキーマは `chain(receipt_id UNIQUE, receipt_hash, prev_chain, chain_hash, ...)` で
**レシート専用**。§9.2は「失効イベントはchainに入る」と書いたが、そのままでは入らない。
修正: chainを汎用journalへ一般化する。

```text
chain(seq, entry_type, entry_id UNIQUE, entry_hash, prev_chain, chain_hash, chained_at)
  entry_type ∈ {receipt, revocation, checkpoint, epoch_commitment}
```

既存147行は `entry_type='receipt'`, `entry_id=receipt_id`, `entry_hash=receipt_hash` へ
**列名の移行のみ**で写る（chain_hashの再計算は不要 — 連鎖の材料はentry_hashのみ）。
これは実装前に見つかったので移行コストがほぼゼロで済む。実装後なら147行の再連鎖が必要だった。

**発見2【重大】: 未anchor区間は「0」ではなく運用で常に伸びる。**
実測（2026-08-19、この台帳）: chain 147 / anchor済み 147 / 未保護 0枚。
ただしこれは直前のcommitでheadを焼いたため。**challenge epoch 1回で18レシート**積まれるので、
実験を回した直後は常に未保護区間ができる。§9.3の「anchor頻度が失効の解像度」は
理論上の注意ではなく日常的な状態。
→ 実装必須: `eden chain status` が未anchor区間長を常時表示し、
   閾値超過で anchor を促す（数値ではなく「保護されていない枚数」で言う）。

**発見3【軽微】: pre-signed revocation の保管場所問題。**
§9.5-3で推奨した事前署名済み失効宣言は、鍵と同じ場所に置けば同時に盗まれ、
別の場所に置けば紛失リスクが増える。v0.5では推奨に留め、保管方式は規定しない
（規定できないことを規定しない）。

---

## 10. Journalのdomain separation と、規則の版管理（2026-08-19）

第4次監査の指摘: 署名ではnamespace分離を採用したのに、journalのhashには適用していない
（原則の適用漏れ）。実測で衝突経路を確認した上で採用する。

### 10.1 衝突は実在する（実測）

```text
checkpoint body = {"chain_head":"abc123","node_id":"n1"}
revocation body = {"chain_head":"abc123","node_id":"n1"}
→ canonical一致 → SHA256一致（211b2ccc...）
```

異種entryが同じバイト列になれば、**「何であるか」を偽装できる**。
domain separationで分離する:

```text
entry_hash = SHA256("EDEN:" + entry_type + ":v1|" + canonical_bytes)
```

区切り文字の偽装は成立しない（実測）: canonical JSONは必ず `{` で始まり、
body内の `|` や domain文字列は JSON文字列としてescapeされるため、
`domain + "|" + "{"` という構造は不変。

### 10.2 これが暴いた、より重い問題 — 既存chainの再計算不能性

domain separationを導入すると `entry_hash` の計算規則が変わる。
既存147件は `entry_hash = receipt_hash`（domain無し）で連鎖しており、
新規則を遡及適用すると **chain全体が再計算され、gitに焼いた head
`4bf1aa20...` が無効になる**。それは公開済みの事実の破壊であり、憲法IV違反。

**解: 規則に版を持たせ、事実には触らない。**

```text
chain(seq, entry_type, entry_id, entry_hash, hash_rule, prev_chain, chain_hash, ...)

hash_rule = "v1-legacy"   seq 1..147   entry_hash = receipt_hash（domain無し）
hash_rule = "v2-domain"   seq 148..    entry_hash = SHA256(domain|canonical)
```

- 各entryは**自分がどの規則で作られたか**を持つ。検証は entry の hash_rule に従って行う
- 過去のchain_hashは一切変わらない。gitアンカーは有効なまま
- これは憲法IVの逐語的実装: **事実（過去のhash）は不変、規則（計算方法）は版を持つ**

### 10.3 規則変更そのものをjournalに刻む

版が変わる境界を、後から「そう言っているだけ」にしない:

```text
entry_type = "rule_change"
body = {from_seq: 148, field: "entry_hash", old_rule: "v1-legacy",
        new_rule: "v2-domain", reason: "domain separation (audit 4)"}
```

この entry 自体が seq を持ち、chainに刻まれ、以降のanchorで外部固定される。
**プロトコルが自分の規則変更を自分の台帳へ記録する** — 規則の履歴もまた観測事実になる。

### 10.5 第5次監査の3指摘 — 設計へ反映し、実装済み

- **HIGH 1 循環（rule_changeが新規則で自分を正当化する）** → transition entryは
  **旧規則で刻む**。seq 148 = rule_change (v1-legacy, 16hex)、seq 149以降がv2-domain。
  旧世界が新世界への入口を認証する
- **HIGH 2 規則の自己申告** → `rule_at(seq)` をjournal履歴から導出する
  （`journal.py`）。entryの`hash_rule`列は冗長な表示値であり、
  検証時に履歴と食い違えば **rule mismatch** として拒否する
- **HIGH 3 後付けmetadataは旧chainに保護されていない** → 移行前entryの型と規則は
  DBの列ではなく **protocol migration rule**（`journal.legacy_type_of`）で導出する。
  さらに147件の(seq, type, rule, entry_hash)を **migration manifest** として
  canonicalizeし、そのhashをtransition entryのbodyへ含めた
  （manifest自体が旧規則のentry_hashで保護され、次のanchorで外部固定される）
- **rule_changeに万能の権限を与えない** → `journal.SUPPORTED_RULES` と
  `RULE_STRENGTH` により、未知規則とdowngradeをVerifierが拒否する。
  journalは「規則が変わった事実」を記録するが、どんな規則でも正当化しない

### 10.6 実装中に発見した後退（同日、テストが捕捉）

汎用journal化の初版で、レシート本文のコピーを`entry_body`列へ保存した結果、
**検証がコピーを見てreceiptsテーブルの改竄を検出できなくなった**（既存テスト2件が失敗）。
レシート本文の正本は`receipts`テーブルであり、journalはhashのみを持つ。
`store_body=False` を receipt entry に適用して修正。
教訓: **正本の二重化は改竄検出を殺す。** journalに置いてよいのは、
他に本文の置き場がないentry（rule_change等）だけ。

### 10.7 規則履歴そのものの検証（第6次監査 — 実装済み）

`rule_at()` が読む `rule_change` 群を、**主張の列ではなく状態機械として検証する**。
`journal.validate_rule_history()`:

| 検査 | 拒否する攻撃 |
|---|---|
| `from_seq == seq + 1` | 遡って過去の解釈を書き換える change、先の範囲を予約する change |
| `old_rule == 宣言時点で有効な規則` | 履歴を無視した規則の詐称 |
| `from_seq` の重複なし | 同じ地点から分岐する履歴 |
| `validate_rule_change` | 未知規則、弱い規則への後退 |

実測で各検査が単独に効くことを確認（テスト固定）。遡及changeを実台帳形式で挿入した
攻撃も拒否される。**規則変更は事実として記録されるが、履歴の整合を欠く変更は
解釈として採用されない。**

### 10.4 実装順序への影響（Phase A改訂）

1. chain汎用journal化（列追加 + hash_rule='v1-legacy' を既存147件へ）
2. rule_change entry を刻む（seq 148）
3. 以降のentryを v2-domain で連鎖
4. checkpoint署名 → git anchor（新regimeを外部固定）
5. その後に identity / emit署名

**1〜4を署名より先に済ませる。** 署名entryが v1-legacy 規則で刻まれてしまうと、
以後ずっと2規則が混在したままになる。


---

## 11. Phase A 実装記録（2026-08-19）

`identity.py`（sshsig呼び出しの隔離層）+ eden.py接続。実装したもの:

- `eden identity init/show` — 鍵生成（0600）、node_id全64hex、nodesテーブルへ登録
- レシート発行時の自動署名（namespace `eden-receipt`、signaturesを除いた本体が対象）
- `eden verify-signatures` — 台帳全件の署名再検証とtrust_state分類
- `eden chain checkpoint` — headへ署名（namespace `eden-checkpoint`）
- CANONICAL RULE（§2）をcanonical()へ適用（allow_nan=False。既存hashへの影響なしを実測確認）

**実測した拒否（テスト8本で固定）:** 改竄payload / namespace転用 / 別鍵での偽装 /
不正base64 — すべて拒否。鍵不在は例外ではなくUNSIGNEDとして扱う（測定は信頼に先行する）。

**実装中に見つけた欠陥（実台帳で走らせなければ埋もれていた）:**
`receipts` へ `trust_state` 列を足した結果、暗黙の `INSERT ... VALUES (?,?,?,?,?,?)` が
列数不一致で失敗し、**レシート発行が静かに落ちていた**。CLIはエラーを表示せず、
台帳の件数が増えないことでしか気づけなかった。全INSERTを列明示へ変更。
教訓: スキーマを足したら、暗黙の列順に依存する書き込みを全数洗う。

**現在の台帳:** 149 entries / INTACT / LOCAL 141・UNSIGNED 6・**SIGNED 1**（史上初）/
checkpoint署名済み head `6b6ba8f382fa6a03b14b647a6f99f291e7ededc386226d8396ea29e0f9b380e4`

**テスト射程外を実測して見つけたもの（同日）:** 台帳経由で本体改竄・未登録node_id・
namespace書換を試すと、いずれも拒否されるが結果が `LOCAL` — つまり
**署名を偽ったレシートと、署名を付けていない正直なレシートが同じ状態に見えた**。
失敗した主張を無署名として扱うのは詐称への加担なので、`INVALID` 状態を新設して分離。
台帳経路のtrust_state判定をテスト5本で固定（identity層の単体テストでは届かない範囲）。

**Phase Aで到達していないもの（正直に）:** SIGNEDは「誰が言ったか」しか固定しない。
ATTESTED（計測根拠）とVERIFIED（他ノードの再検証）は未実装であり、
現在の1件は単一ノードの自己署名 — role_collapse=true をレシート自身が申告している。


---

## 12. trust_stateの2軸化（Phase B着手前の設計修正、2026-08-19）

### 12.1 線形階梯は間違いだった

§3は `SIGNED → ATTESTED → VERIFIED` という一本の階梯を定めていた。
Phase Bを実装しようとして、それが**二つの無関係な問いを直列にしている**と分かった:

```text
「誰が言ったか」        署名（SIGNED）
「他人が再現したか」    独立再検証（VERIFIED）   ← 主張の信頼度という同じ軸
「計測器は証明済みか」  attestation              ← 測定の質という別の軸
```

線形にすると、meter attestation（実解はEDEN Cable = 物理ハードウェア）が
存在するまで、**別ノードが再検証しても状態が上がらない**。
2台目がある今、それは事実を捨てている。

### 12.2 修正後

```text
trust_state (主張の信頼度、線形):
  LOCAL     自台帳のパイプラインが生成、署名なし
  UNSIGNED  輸入、署名なし
  INVALID   署名を伴うが検証に失敗（正直な無署名と区別する — Phase A実測より）
  SIGNED    有効なノード署名あり = 誰が言ったかが固定された
  VERIFIED  SIGNED + 別ハードウェアのノードによる独立再検証

meter attestation (測定の質、独立した属性):
  既存の meter_class（S=推定 / V=OSカウンタ / P=物理計測）の延長に置く。
  レシートの属性であり、主張の信頼度の階梯には含めない。
```

**eligibilityへの接続も変わる**: 前線更新に要求するのはVERIFIED（＝再現された）。
測定の質はmeter層別（既存）が既に担っており、二重に階梯へ持ち込まない。

### 12.3 Phase Bで作れるもの・作れないもの（先に宣言する）

WITNESSは TwinLoop Relay の `shadow_verify_v1`（署名付きジョブ、任意コマンド不可、
成果物はログ経由）でしか動かせない。**恒久的な鍵をWITNESSへ置く経路がない** —
relayは任意ファイル書き込みを許さず、それは緩めるべきでない制約。

したがってPhase Bで得られるのは:
- **得られる**: 「別ハードウェアで、同じ検証仕様により、同じ結果が再現された」という事実。
  jobごとに生成した鍵で署名され、その鍵の出所はrelayのtransport receipt（SHA-256付き）が担保する
- **得られない**: WITNESSノードの恒久的同一性。鍵はjobごとに使い捨てで、
  「同じノードが繰り返し検証している」ことは言えない

**正直な帰結**: WITNESS由来の署名の信頼は、EDEN自身の暗号ではなく
**TwinLoop relayのtransport認証に依存する**。EDENの台帳にはそう記録する
（`verifier_trust_basis: "twinloop-relay-transport"`）。
第三者verifierが恒久鍵を持って参加すれば、この依存は消える。


---

## 13. Phase B 実装記録 — 最初のVERIFIED（2026-08-19）

WITNESS（M1 Air）が、FORGEのレシートを**自分で再検証して署名した**。

```text
対象レシート : counter_fast / family 2a8243b5b0f9f404 / output 73883d04ae2dcc7c
WITNESS判定  : PASS（自分で仕様から入力を再生成し、runnerを再実行して到達）
hw指紋       : 10f070（FORGE = f991f2）
verifier_spec: FORGEの主張と一致
trust_basis  : twinloop-relay-transport（宣言）
```

台帳: **VERIFIED 1 / SIGNED 1** — EDEN史上初のVERIFIEDレシート。

### 13.1 独立性は言葉ではなくハードウェアで判定する

`cmd_import_verification` が拒否するもの（実測、テスト4本で固定）:

| 攻撃 | 結果 |
|---|---|
| 同一hw指紋での自己確認（**署名は有効**） | REJECTED — 機械が自分に頷くのは独立検証ではない |
| verdict/出力hashの書換 | REJECTED（署名不一致） |
| 存在しないレシートへの検証 | REJECTED |
| 未登録鍵での主張 | REJECTED |

最初の攻撃検査では、同一マシン攻撃が「署名不一致」で先に落ちて**検査の証明になっていなかった**。
攻撃者の鍵で正しく署名し直した上で再攻撃し、同一マシン検査が単独で発火することを確認してから固定した。

### 13.2 これで何が言えて、何が言えないか

- **言える**: 別のハードウェアが、同じ検証仕様で、同じ結果に到達した
- **言えない**: そのノードの恒久的同一性。鍵はjobごとの使い捨てで、
  「同じWITNESSが繰り返し検証している」ことは主張できない
- **依存**: この署名の出所はEDENの暗号ではなく**TwinLoop relayのtransport認証**。
  台帳は `trust_basis: "twinloop-relay-transport"` としてその依存を記録する。
  恒久鍵を持つ第三者verifierが参加すれば、この依存は消える


---

## 14. 信頼層を経済層へ接続（2026-08-19）

Phase A/Bで trust_state は計算できるようになったが、**前線判定はそれを一度も参照していなかった**。
信頼の階梯を作って経済に繋がなければ、階梯は装飾になる。

```text
前線への参加（group_stats の入力になれるか）:
  LOCAL     ○  自台帳のパイプライン産。無署名であることを隠さない
  SIGNED    ○
  VERIFIED  ○
  INVALID   ×  署名を伴うが検証に失敗 = 失敗した主張であり、測定ではない
  UNSIGNED  ×  輸入・無署名。観測資料としては残るが、値付けはしない
  ＋ 外来（ext-）が LOCAL を名乗る場合は拒否 — LOCALは自台帳だけが主張できる

記録の保持（admits_to_record）:
  外来の結果が記録を持つには VERIFIED（＝別ハードウェアで再現された）を要求する
```

**INVALIDを自台帳でも除外する**のが要点。署名を偽ったレシートを「無署名として扱う」のは
詐称への加担であり、Phase Aで状態を分離した理由がここで効く。

実測（テスト6本で固定）: LOCAL参加可 / UNSIGNED不参加 / INVALIDは自台帳でも不参加 /
外来のLOCAL僭称は拒否 / **署名付き外来レシートは参加可**。

**正直な現状**: 今の台帳では結果が変わらない（外来6件はすべてUNSIGNEDで、
以前の `ext-` 文字列除外と同じ結果になる）。差が出るのは署名付きの外来レシートが
到着したときで、規則はその日のために先に置かれている。


---

## 15. Rollback / freshness / record admission（第7次監査、2026-08-19）

### 15.1 巻き戻し攻撃は成立していた（実測）

`chain status` は「自分のheadがanchorされているか」だけを問うていた。
だから**過去のanchor地点ちょうどへ切り詰めると、健全に見える**:

```text
攻撃前: 150 entries / anchored 150 / UNPROTECTED 0
攻撃  : DELETE FROM chain WHERE seq > 148   （SIGNEDとVERIFIEDの記録を消す）
攻撃後: 148 entries / anchored 148 / UNPROTECTED 0 / verdict INTACT  ← 気づけない
```

**修正 — 問いを逆にする**: 「自分のheadは守られているか」ではなく
**「かつて公表した全headが、今もこのchainに在るか」**を問う。
`detect_rollback()` は checkpoint署名したheadを台帳から探し、消えていれば名指しで報告する。
誤検出を避けるため、判定材料は**自分がcheckpointとして署名したhead**に限る
（commit本文中の任意の64hex文字列を根拠にしない）。

実測（攻撃を台帳のコピーで再現、本番は無傷）:
```text
ROLLBACK DETECTED
  a head we signed is gone from this chain: 6b6ba8f382fa6a03…
  a head we signed is gone from this chain: 3a2b72ad2aa5ca92…
```

### 15.2 anchorは「公開済み」でなければ意味がない

`git log --all` はローカルcommitを含む。台帳を書き換えられる者は、
**都合の良いheadを書いたcommitをローカルに作れる**。
anchorの判定を `git log origin/main` に限定し、未pushのheadは
「まだ何も守っていない」と明示表示する。

### 15.3 record admission が実経路に無かった

`admits_to_record()` は定義されていたが**呼び出し0件**で、しかも
`is_foreign` を見ずSIGNEDでも真を返していた — コメントの主張と実装の乖離。

修正:
```text
admits_to_record(state, is_foreign):
  foreign → VERIFIED のみ（他ハードで再現された結果だけが記録を持てる）
  local   → LOCAL / SIGNED / VERIFIED
```
`group_stats` が各グループへ `trust_floor`（**構成レシートの最弱**）と
`is_foreign` を付与し、FIRST RECORDと前線更新の**両方の実経路**でこのゲートを通す。

### 15.4 entry_id を hash preimage へ束縛（v3-bound-id）

失効や検証はentryを**idで指す**。idがpreimageの外にあると、
同一bodyの別idエントリが同じhashを持つ。規則v3で束縛:

```text
entry_hash = SHA256("EDEN:" + type + ":v3|" + entry_id + "|" + canonical_body)
```

既存chainは触らない（v1/v2のまま）。移行は `rule_change` として刻む —
規則の版管理（§10）がそのまま使える。


---

## 16. 失効の実装 — 設計§9をコードへ（2026-08-19）

§9で「時刻ではなく順序」と決めながら、**実装は存在していなかった**。
`admits_to_record` が呼び出し0件だったのと同じ型の穴（設計と実経路の乖離）。

### 16.1 実装

```text
eden revoke compromise|rotation|retirement [--successor <node_id>]
  → revocation entry を chain へ追記（namespace eden-revocation で署名）

signature_still_valid(node_id, receipt_seq):
  失効の seq より後に台帳へ入った署名は数えない。時計は一切参照しない
```

- 新状態 **REVOKED**: 有効な署名だが、台帳が後に信頼を取り消した鍵のもの
- **経済ゲートへ接続**: REVOKED は前線に参加できず、記録も保持できない
- **compromise は後継を指名できない**（鍵を握った者が歴史の相続人を選べてしまう）
- **rotation は successor 必須**

### 16.2 判断: 台帳に未登録のレシートは失効後に数えない

chain に入っていないレシートには比較すべき位置がない。
ここで「疑わしきは有効」とすると、**盗まれた鍵を持つ側に利益が渡る**。
だから未登録のレシートは失効後に SIGNED へ到達しない（テストで固定）。

### 16.3 実測（テスト6本）

```text
失効前に台帳へ入った署名 : SIGNED    ← 過去は無傷（憲法IV）
失効後に台帳へ入った署名 : REVOKED
前線参加 / 記録保持       : どちらも拒否
```

### 16.4 副産物 — 規則移行の汎用化と、空台帳のバグ

- `chain migrate` を「現規則 → 次に強い規則」へ汎用化。実台帳を **v3-bound-id** へ移行し、
  作った規則が実際に使われる状態になった（未使用の規則をコードに残さない）
- 移行の表示文が v1→v2 用にハードコードされ、**v3移行時に嘘を表示していた**ので修正
- 失効テストが実装のバグを発見: **空の台帳で `chain build` を呼ぶと例外**。
  初回起動時に誰でも踏む経路だった


---

## 17. J/success の信頼区間 — マージンからbootstrapへ（2026-08-19）

§12で導入した `Certified` のうち、エネルギー側は `JPS_MARGIN = 0.2` という
**恣意的なパラメータ**だった（監査の指摘: 「Certifiedと呼ぶなら本物のCIにすべき」）。

### 17.1 なぜ点推定＋マージンでは足りないか

J/success は **分子（消費エネルギー）と分母（成功数）の両方が動く比**。
点推定に一律のマージンを掛けても、成功が偶然多かった回と少なかった回の差は表せない。
bootstrapは実際のrunをリサンプリングするので、この二つが連動したまま分布になる。

**成功0のリサンプルは∞として残す**（捨てない）。捨てれば、たまにしか成功しない
runnerを実力以上に良く見せてしまう。決定的seedを固定し、同じ証拠からは
誰が再計算しても同じ区間が出る。

### 17.2 実データが過去の主張を訂正した

epoch cc846674 を再認証した結果:

```text
cascade  1.37 J/success  ci95 [0.78, 2.07]  ⎫ 重なる → 証拠は両者を区別していない
brute    1.53 J/success  ci95 [1.20, 1.87]  ⎭
1.5b       81 J/success  ci95 [54.7, 162.5] ⎫ 分離 → この支配は本物
7b        392 J/success  ci95 [213, 1060]   ⎭
```

**「カスケードが探索に勝った」は12回の実行から読み過ぎだった。**
「小型が同族の大型より成功単価で安い」は再標本化を生き延びた。
READMEを訂正済み — mintは区間分離を要求するようになったので、
前者はもう何も生まない。

### 17.3 後方互換

観測データを持たない旧certificateは、従来のマージン規則で評価される
（`_jps_separated` が自動で切り替え、認証根拠の表示も区別する）。
過去のcertを作り直さない — 憲法IV。
