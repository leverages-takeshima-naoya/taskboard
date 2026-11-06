# Linear 調査メモ（taskboard のデザインガイドライン用）

- 調査日：2026-11-06
- 環境：Chrome（Windows）、Linear Web 版。ワークスペース「Leverages」（Free plan、課題なしの状態から開始）
- 読み方：「実測」は getComputedStyle の値、「目視」はスクショから読んだもの
- 色は Linear が LCH で持っている値を canvas で sRGB の HEX に直した。元の LCH も一部併記する
- ライトはテーマを一時的に Light にして測り、測定後に元の「System preference」へ戻した

---

## 1. 見た目

### 1-1. 色

Linear の色は CSS 変数で定義され、テーマ切替で値が丸ごと入れ替わる。変数名は次のとおり。

| CSS 変数 | ダーク | ライト | 読み方 |
|---|---|---|---|
| --color-bg-primary（メイン面の地） | #121213 `lch(5.52% 0.4 272)` | #f9f9fa `lch(97.94% 0.5 282)` | 実測 |
| --color-bg-secondary | #161617 | #e9e9ea | 実測 |
| --color-bg-tertiary | #17181a | #e5e5e6 | 実測 |
| --color-bg-quaternary | #1a1a1b | #efeff0 | 実測 |
| --bg-sidebar-color / --bg-color（外枠・サイドバー） | #09090a | #efeff0 | 実測 |
| --color-border-primary | #1a1b1d | #f1f1f1 | 実測 |
| --color-border-secondary | #232426 | #dedede | 実測 |
| --color-border-tertiary | #28282b | #d3d3d3 | 実測 |
| --color-text-primary | #ffffff | #1b1b1b | 実測 |
| --color-text-secondary | #e3e4e6 | #2f2f31 | 実測 |
| --color-text-tertiary | #959597 | #5c5c5e | 実測 |
| --color-text-quaternary | #565759 | #9c9d9f | 実測 |
| --focus-ring-color | #5e69d1（幅 1px、`1px solid`） | 同じ | 実測 |
| --selection-bg | `color-mix(in srgb, #949597 20%, transparent)` | 同じ | 実測 |
| --selection-bg-active | `color-mix(in srgb, #5e69d1 40%, transparent)` | 同じ | 実測 |

ダークの面は色相 272（わずかに青み）、ライトは 282 で彩度 0.4〜1.5 しかない。ほぼ無彩色のグレーに、ごく薄く青を混ぜている。

場所ごとの実際の色は次のとおり。

| 項目 | ダーク | ライト | 読み方 |
|---|---|---|---|
| 地（メイン面） | #121213 | #f9f9fa | 実測 |
| サイドバー（画面の外枠） | #09090a | #efeff0 | 実測 |
| パネル：新規作成モーダル | #1a1a1b | 未測定 | 実測 |
| パネル：⌘K・ドロップダウン・ポップオーバー | #212122、枠 #323336 | #ffffff、枠 #e4e4e4 | 実測 |
| 一覧のグループ見出し行 | #1a1a1b | #efeff0 | 実測 |
| ホバー中の行 | #1a1a1b | #efeff0 | 実測 |
| 選択中の行（x で選択） | #1c1e37（アクセントを薄く混ぜた色） | #e7e8f4 | 実測 |
| メニュー内のハイライト行 | #313234 | #f1f1f1 | 実測 |
| サイドバーの現在地 | #232325 | #e1e1e2 | 実測 |
| 区切り線（メイン面の枠） | #1a1b1d | #f1f1f1 | 実測 |
| 本文（課題タイトル） | #ffffff | #1b1b1b | 実測 |
| メニューの文字 | #e5e6e8 | #303032 | 実測 |
| 補足の文字（ID・日付・プロパティ見出し） | #959597 | #5c5c5e | 実測 |
| サイドバーの文字（未選択） | #919294 | #59595b | 実測 |
| 薄い文字（quaternary） | #565759 | #9c9d9f | 実測 |
| アクセント（主ボタン・Done） | #5e6ad2 `lch(47.9 59.3 288.4)` | 同じ | 実測 |
| アクセント上の文字 | `lch(100 5 288)`（ほぼ白） | 同じ | 実測 |
| スイッチ ON | 未測定（目視でアクセント） | #6d78d5 | 実測 |
| スイッチ OFF | #727374 | 未測定 | 実測 |
| 状態：赤（期限切れ） | #f34e52 `lch(58 73 29)` | #f34e52 | 実測 |
| 状態：オレンジ（期日が近い・優先度 Urgent） | #ff7336 `lch(66 80 48)` | 同じ（目視） | 実測 |
| 状態：黄（In Progress） | #f0bf00 `lch(80 90 85)` | #f0bf00 | 実測 |
| 状態：緑 | 状態アイコンには使われていない。完了（Done）はアクセントの青紫 | 同じ | 目視 |
| Canceled / Duplicate | #95a2b3 | #95a2b3 | 実測 |
| Todo の丸 | #e2e2e2 | #a6a6a6 | 実測 |
| 削除ボタン（確認ダイアログ） | 赤の塗り | 未確認 | 目視 |

### 1-2. 文字

| 項目 | 値 | 読み方 |
|---|---|---|
| フォント | `"Inter Variable", "SF Pro Display", -apple-system, BlinkMacSystemFont, "Segoe UI", …`。日本語は OS のフォールバックになる | 実測 |
| 太さの段階 | 400 / 450 / 500 / 600。450 は可変フォントの中間値で、補足の文字に使う | 実測 |
| 一覧の課題タイトル | 13px / 500 / line-height normal | 実測 |
| 一覧の ID（LEV-11） | 13px / 450、補足色 | 実測 |
| 一覧の日付 | 12px / 450、補足色 | 実測 |
| グループ見出し（In Progress 1） | 13px / 500 | 実測 |
| サイドバー項目 | 13px / 500 | 実測 |
| サイドバーのセクション名（Workspace など） | 12px / 500 | 実測 |
| パンくず | 13px / 500 | 実測 |
| ボタン・タブ・チップ | 12px / 500 | 実測 |
| メニュー項目 | 13px / 450 / 15.6px | 実測 |
| メニュー・⌘K の入力欄 | 13px / 400 | 実測 |
| 課題詳細のタイトル | 24px / 600 / 32px | 実測 |
| 課題詳細「Properties」見出し | 13px / 500、補足色 | 実測 |
| 課題詳細のプロパティ値 | 13px / 500（未設定は補足色） | 実測 |
| 課題詳細「Activity」見出し | 15px / 600 / 23px | 実測 |
| アクティビティの行 | 12px / 450 / 16.8px | 実測 |
| 新規作成モーダルのタイトル欄 | 18px / 600 / 28.8px | 実測 |
| 空状態の見出し（Welcome to Linear） | 20px / 500 | 実測 |
| キーボードの印（kbd） | 12px / 400、枠 1px、角丸 4px、padding 2px | 実測 |

本文の基準は 16px / 24px だが、画面に出る文字はほぼ 12px と 13px の2種類しかない。

### 1-3. 形と余白

| 項目 | 値 | 読み方 |
|---|---|---|
| 一覧の1行の高さ | 44px | 実測 |
| グループ見出し行の高さ | 36px、角丸 8px、右 padding 8px | 実測 |
| 行の左余白（行の端→最初のアイコン） | 16px | 実測 |
| 行の並び | 優先度 18px → ID 49px → 状態 16px → タイトル（伸びる）→ 期日チップ → 担当 18px → 作成日 60px | 実測 |
| ホバー・選択の塗り | 行全体ではなく左右 8px 内側に入れた角丸 8px の面（`::before`、inset 0 8px） | 実測 |
| 行と行の区切り線 | なし（border 0） | 実測 |
| サブ課題の字下げ | 親から 24px。左に縦の線（ツリー線）が出る | 実測＋目視 |
| サイドバー幅 | 244px（--sidebar-width） | 実測 |
| サイドバー項目 | 高さ 28px、角丸 8px、アイコン 16px | 実測 |
| 上部ヘッダーの高さ | 43px（--header-height） | 実測 |
| メイン面 | 外枠から上・右 8px 浮かせ、角丸 12px、枠 1px | 実測 |
| メイン面の影 | ダーク `lch(0 0 0/.3) 0 .5px 1px 1px` ／ ライト `0 3px 6px -2px 2%黒, 0 1px 1px 4%黒` | 実測 |
| 角丸の段階 | 4px（kbd）／8px（行・ボタン類の --control-border-radius）／12px（メニュー・メイン面）／21px（新規作成モーダル）／9999px（ボタン・タブ・チップ） | 実測 |
| ⌘K・状態メニュー | 幅 720px、角丸 12px、枠 1px、項目の高さ 46px、ハイライトは上下 2px 内側の角丸 8px | 実測 |
| ドロップダウン（フィルタ） | 幅 238px、項目の高さ 32px、区切りは上下 6px の余白 | 実測 |
| 表示設定ポップオーバー | 幅 302px、角丸 12px | 実測 |
| 大きいメニューの影 | `0 4px 40px 10%, 0 3px 20px 12.5%, 0 3px 12px 12.5%, 0 2px 8px 12.5%, 0 1px 1px 12.5%`（すべて黒） | 実測 |
| 小さいメニューの影 | `0 3px 8px, 0 2px 5px, 0 1px 1px`（各 12.5% 黒） | 実測 |
| ライトのメニューの影 | `0 9px 48px 8%, 0 6px 24px 10%, 0 1px 1px 4%` | 実測 |
| ボードのカード | 幅 324px、角丸 8px、地 #1a1a1b、影 `0 0 0 1px lch(100 0 0/.048), 0 .5px 1px 1px lch(0 0 0/.3)`（1px の白い縁取りを影で描く） | 実測 |
| ボードの列 | 幅 348px | 実測 |
| 区切り線の太さ | 1px | 実測 |

### 1-4. 部品

| 部品 | 通常 | ホバー・選択中 | 読み方 |
|---|---|---|---|
| 主ボタン（Create issue） | 高さ 28px、ピル型、padding 0 10px、地 #5e6ad2、影 `0 .5px 1px 1px 30%黒` | ホバーの値は未測定 | 実測 |
| 普通ボタン（Documentation・Cancel） | ピル型、地は面より一段明るいグレー | 未測定 | 目視 |
| アイコンだけのボタン（フィルタ・表示設定） | 丸型、地なし | ホバーで丸い地が出る。開いている間は地が残る | 目視 |
| ビュー切替タブ（Active / Backlog / All issues） | 高さ 28px、ピル型。未選択：地 #1c1c1d・文字 #959597 | 選択中：地 #29292b・文字 #ffffff（ライト：未選択 #ffffff/#5c5c5e、選択中 #ececed/#1b1b1b） | 実測 |
| プロパティチップ（新規作成モーダル） | 高さ 24px、ピル型、地 #2a2b2d、文字 12px/500 #9c9d9f | 未測定 | 実測 |
| 表示項目のトグルチップ | OFF：地 #2a2b2c・文字 #9c9d9f | ON：地 #3c3d3f・文字 #fff（ライト OFF #ffffff/#5e5e60、ON #f0f0f0/#1b1b1b） | 実測 |
| 選択メニュー（表示設定の Grouping など） | 高さ 24px、角丸 8px、地 #2a2b2c、右に ▾ | 開くと下にドロップダウン | 実測 |
| スイッチ | 22×14px、角丸いっぱい | ON でアクセント色 | 実測 |
| 日付の選び方 | 自然文の入力欄（例：24h, 7 days, Feb 9）＋候補（Tomorrow / End of this week / In one week）＋ Custom… | Custom で2か月並びのカレンダー。土日の列は地が一段濃い。今日は丸で囲む | 目視 |
| 状態アイコン | 14px。Backlog 点線の丸／Todo 実線の丸／In Progress 半分塗りの丸（黄）／Done 塗りの丸にチェック（アクセント）／Canceled・Duplicate 灰色の塗りに×や斜線 | 選んだものには右にチェック | 実測＋目視 |
| 優先度アイコン | 16px。No priority は「---」／Urgent は角丸四角に「!」（オレンジ）／High・Medium・Low は3本の棒で、塗っていない棒は 40% の不透明度 | 一覧では Urgent だけ色が付く | 実測 |
| 期日チップ | 高さ 24px、ピル型、枠 1px #28282b、地はメイン面と同じ、文字は補足色 | 期限切れはカレンダーアイコンが赤（×入り）。数日以内はオレンジ。文字色は変わらない | 実測 |
| サブ課題の進み具合 | 期日チップと同じ形で「◔ 0/2」 | — | 実測 |
| ラベル | Free plan・ラベルなしのため未確認 | — | — |
| 複数選択時のバー | 画面下中央に浮くピル（高さ 44px）。「6 selected」「⌘ Actions」×ボタン | — | 実測（ライト） |

### 1-5. 動き

| 項目 | 値 | 読み方 |
|---|---|---|
| ボタン・チップ・タブ | border / background-color / color / opacity を 0.15s | 実測 |
| サイドバーのリンク | color 0.15s | 実測 |
| 一覧の行ホバー | transition なし。即座に塗りが出る | 実測 |
| スイッチ | background-color・opacity 0.15s ease-out | 実測 |
| 新規作成モーダル | min-height 0.3s、max-width 0.22s。曲線は `cubic-bezier(0.43, 0.07, 0.59, 0.94)` | 実測 |
| テーマ切替 | 全体がクロスフェードする。1〜2秒 | 目視 |
| メニューの開閉 | 未測定 | — |

---

## 2. 機能

### 2-1. Inbox と Triage

**Inbox（個人宛ての通知）**
- 画面：サイドバー最上段。左に一覧（幅 399px）、右に選んだ1件の中身の2ペイン。何も選んでいないと右は「No notification selected」
- 1件の見え方：高さ約 55px。左にアイコン（人のアバターなど）、1行目にタイトル 13px/500、2行目に要約 12px/450、右端に経過時間（11min）。既読はタイトルも補足色に落ちる（実測）
- 並び：表示設定で「Ordering：Newest」。ほかに「Group unreads by」「Show snoozed」「Show unread first」「Enable priority inbox」のスイッチがある（目視）
- キーボード：E または Backspace で削除、U で既読/未読、H でスヌーズ、F でフィルタ（ショートカット一覧から）
- まとめて処理：「…」メニューに「Delete all」「Delete all read」。既読をまとめて消すショートカットもある
- 試せた範囲：通知は Welcome の1件だけ。複数件や未読の見え方は見ていない

**Triage（チームの受付箱）**
- チーム設定で ON にする機能で、今回は OFF のため画面は見ていない。以下はヘルプからの事実
- Slack・Sentry などの連携やチーム外のメンバーが作った課題は、Triage という状態で入る
- 1件ずつ開いて、1 で受け入れ（コメントを残せる→チームの初期状態へ）、2 で却下（Canceled）、3 または M M で重複にする（統合先を選ぶ）、H でスヌーズ（指定日か新しい動きがあるまで隠す）
- G → T で Triage に移動。Triage の課題は通常のビューには出ない
- 有料プランでは Triage Intelligence（AI が担当・ラベルを提案し、重複を見つける）と Triage Rules（条件で自動振り分け）が使える

taskboard の inbox に近いのは Triage のほうで、「1件ずつ開く→数字キー1つで行き先を決める→AI が属性を提案」という形が同じ。

### 2-2. 課題の一覧

- 画面：チームの Issues。上にビュー切替タブ（Active / Backlog / All issues）、右上にフィルタ・表示設定・右パネルのアイコン
- まとめ方：Grouping（No grouping / Status / Status type / Assignee / Agent / Project / Priority / Label）と Sub-grouping の2段
- 並び替え：Ordering（Manual / Title / Status / Priority / Assignee / Agent / Estimate / Updated / Created / Due date / Link count / Time in status）。矢印ボタンで昇順・降順。「Order completed by recency」スイッチもある
- 優先度を変えると、行がすぐ並び替わる（Ordering: Priority のとき）
- 表示項目：チップの ON/OFF で ID / Status / Assignee / Creator / Priority / Project / Due date / Milestone / Labels / Links / Time in status / Created / Updated を出し入れする
- その他の表示設定：Completed issues（All など）、Show sub-issues、Nested sub-issues（Show matching）、Show empty groups
- 絞り込み：F またはフィルタアイコン。最上段に「AI filter」（自然文）、次に「Advanced filter」、その下に Status / Assignee / Creator / Priority / Labels / Relations / Dates / Project / Subscribers / Content / Links / Template などの項目
- 表示の切り替え：表示設定の最上段で List / Board。Ctrl+B でも切り替わる。ボードは状態ごとの列で、件数0の列は右側の「Hidden columns」にまとめて畳まれる
- ボードのカード：1行目に ID（サブ課題は「LEV-15 › 親のタイトル」）、2行目に状態アイコン＋タイトル、3行目にプロパティのチップ、最下行に「Created Nov 6」
- 行の操作：ホバーした行にそのままキーが効く（S 状態、P 優先度、Shift+D 期日）。選んだ行の上でメニューが開き、メニュー上部に対象の課題名が出る。メニューの各項目には数字キーが振られていて、S→3 のように2打で状態が変わる

### 2-3. サブ課題

- 親から作る：課題詳細の説明欄の下にある「+ Add sub-issues」を押すと、その場にインラインの作成欄が開く（タイトル・説明・チーム・Priority・Assignee・Labels・…）。Ctrl+Shift+O でも作れる
- 注意：作成欄でタイトルを打って Enter を押すと説明欄に移る。作るには Create ボタンか Ctrl+Enter
- 親の見え方：詳細に「Sub-issues ◔ 0/2」の見出しと子の一覧（行の高さ 36px）。一覧では親のタイトルの右に「◔ 0/2」のチップ
- 子の見え方：一覧では親の下に 24px 字下げで並び、左にツリー線。ボードでは別カードになり、ID の横に親のタイトルが出る
- 関連ショートカット：Ctrl+Shift+P で親を設定、Ctrl+Shift+↑ で親を開く、Ctrl+Shift+↓ で子を開く

### 2-4. 期日・見積もり

- 期日の入れ方：Shift+D でメニュー。入力欄に自然文（24h, 7 days, Feb 9）か、候補（Tomorrow / End of this week / In one week）を選ぶ。Custom… でカレンダーのダイアログ（2か月並び、Save due date ボタン）。Ctrl+Shift+D で外す
- 自然文の入力では過去の日付を選べなかった（「Nov 3」「2026-11-03」は来年の 2027/11/3 になり、「yesterday」は候補が出ない）。過去日は Custom のカレンダーからなら入る
- 期限切れの見え方：期日チップのカレンダーアイコンが赤（#f34e52）に変わり、×が入る。数日以内（3日後で確認）はオレンジ（#ff7336）。文字は補足色のまま。課題詳細のプロパティでもアイコンが同じ色になる
- 見積もり：Shift+E で変える（ショートカット一覧より）。チーム設定で見積もりが OFF のため、画面には出てこなかった

### 2-5. キーボード操作

⌘K（Windows は Ctrl+K）のコマンドメニュー
- 課題を開いた状態では、上部にその課題名が出て、課題への操作が並ぶ：Assign to… / Assign to me / Change status… / Set priority… / Add to project… / Add labels… / Change due date… / Copy issue ID / Copy issue URL / Copy issue as Markdown / Copy git branch name / Copy as prompt / Unsubscribe / Mark issue as… など。各行の右に単体ショートカットが出る
- 文字を打つと設定やコマンドも引ける（例：「theme」でテーマ切替が出る）
- 入力欄の右に「Ask Linear ｜Tab」。Tab で AI に質問するモードに切り替わる
- Ctrl+/ で右からショートカット一覧のパネルが開き、検索できる

よく使いそうなショートカット10個

| キー | 動作 |
|---|---|
| C | 新規課題 |
| Ctrl+K | コマンドメニュー |
| J / K（↑↓） | 一覧の上下移動 |
| X | 行を選択（Shift+クリックで範囲選択、Ctrl+A で全選択） |
| Space | 覗き見（右上に小さなカードで中身を出す） |
| Enter | 課題を開く |
| S | 状態を変える（メニューで数字 1〜6） |
| P | 優先度を変える（0〜4） |
| Shift+D | 期日 |
| G → I / G → M / G → T | Inbox / 自分の課題 / Triage へ移動 |

その他：L ラベル、A 担当、I 自分に割当、Shift+H リマインド、Ctrl+B 一覧/ボード切替、F フィルタ、[ でサイドバー開閉、Alt+↑↓ で行の並び順を1つ動かす、Ctrl+Delete で削除。

### 2-6. 課題の詳細

- 開き方：一覧で行をクリックか Enter で、メイン面全体が詳細に切り替わる（別画面。横のパネルではない）。Space の覗き見だけは一覧の右上に小さなカードで出る
- 上部：パンくず（チーム › Issues › ID タイトル）、お気に入り、…メニュー。右端に「4 / 4」と ↓↑ で前後の課題へ移動
- 左（本文、幅約 650px）：タイトル（24px/600）→説明（Add description...）→添付などのアイコン→「+ Add sub-issues」→区切り線→Activity（作成履歴など）→コメント欄
- 右（プロパティ、幅約 200px）：Properties 見出しの下に、状態・優先度・担当・期日を1行ずつ（アイコン＋値）。未設定は「Set priority」「Assign」のように補足色で動詞を出す。その下に Labels（Add label）、Project（Add to project）
- 右上のアイコン群：リンクのコピー・ID のコピー・ブランチ名のコピーなど

### 2-7. 外部から入ってくる課題（Slack）

連携はしていない。以下はヘルプの記述で、画面では確認していない。
- Slack のメッセージから「More actions → Connect to apps → Create new issue…」で作るか、@Linear にメンションして自然文で頼む（例：「@Linear file a bug, assign me」）。/linear コマンドでも作れる
- 連携で作られた課題は Triage 状態で入る（Triage を ON にしているチームの場合）
- 作るときに「同期スレッド」を付けられる。Linear 側のコメントと Slack のスレッドが行き来し、課題が完了・却下・重複になると Slack 側のスレッドにも通知が出る
- 既存の課題に Slack メッセージを紐づける方法もある（Link existing issue、または URL を Ctrl+L で添付）。この場合は同期しない
- Linear Agent に「チャンネル名とプロジェクトの対応」などの指示を書いておくと、作成先の推測に使われる

課題の画面上で Slack 由来の課題がどう見えるか（出どころのアイコン、添付の形）は確認できていない。たぶん添付欄に Slack メッセージのリンクが付き、Activity に Slack 経由で作られた旨が出るはず。

---

## 3. スクショを撮る価値がある画面

| 画面・状態 | 理由 |
|---|---|
| チームの Issues 一覧（Status でまとめ、親子あり、期限切れ1件あり、1行をホバー中） | 44px の行、内側に入った角丸ホバー、ツリー線、期日チップの赤とオレンジが1枚で見える |
| 同じ一覧で X を押して2〜3行選んだ状態 | 選択色と、下に浮く「n selected / Actions」バーの見本になる |
| 行の上で S を押した状態メニュー | taskboard の「1件ずつ行き先を決める」操作の手本。数字キー付きの大きいメニュー |
| Shift+D の期日メニューと、Custom のカレンダー | 自然文入力と候補とカレンダーの3段構えがそのまま参考になる |
| 課題詳細（サブ課題2件、期日あり、右にプロパティ） | 本文とプロパティの2列の比率と、未設定項目の見せ方 |
| 表示設定のポップオーバー（List/Board、Grouping、Display properties） | 設定パネルの密度と、チップの ON/OFF の見せ方 |
| ⌘K を課題の上で開いた状態 | コマンド名と右端のショートカット表記の並べ方 |
| Inbox に未読が数件ある状態（左一覧＋右に中身） | 2ペインの比率と、未読・既読の差。今回は通知が1件しかなく撮れていない |

---

## 分からなかったこと・試せなかったこと

- Triage の画面：チーム設定で ON にする必要があり、設定変更にあたるので触っていない。ヘルプの記述だけ
- 見積もり：同じくチーム設定が OFF。表示も入力も見ていない
- ラベル：ラベルを作るのは設定に近いので作っていない。見た目は未確認
- Slack 由来の課題の画面上の見え方：連携していないので未確認
- Inbox の未読・複数件の見え方：通知が1件しかなかった
- ライトの一部の値：新規作成モーダルの地、主ボタン、ボードのカード、スイッチ OFF は未測定
- ホバー時の色変化：ボタン類のホバー値は測っていない（一覧の行とメニューの項目だけ測った）
- メニューの開閉アニメーションの長さ：未測定
- 緑：状態アイコンには使われていなかった。作成完了のトーストのチェックが緑だが、値は測っていない
- 作った [テスト] 課題6件（LEV-10〜15）は削除済み。Linear の仕様で「Recently deleted」に30日残ってから完全に消える
- テーマは「System preference」に戻した。一覧の表示を一度 Board にしたが、List に戻してある
