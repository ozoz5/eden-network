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
