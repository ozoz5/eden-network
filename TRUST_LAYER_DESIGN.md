# EDEN Trust Layer 設計書（草案）

状態: **設計草案 — 実装禁止。実装前に敵対監査を通過すること**（追補13の宣言による）
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
- node_id = SHA-256(公開鍵)[:16]。公開鍵本体は台帳のnodesテーブルへ登録
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
5. node_id衝突（16hex切詰め — 台帳完全性監査の指摘L と同根）
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
