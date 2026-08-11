# [下書き] KUMA補完計画 — Season 1 DevOps計画評価

- 日付：2026-08-11
- 作成者／エージェント：Codex（実行環境から与えられた自己記述は「GPT-5を基盤とするCodex」）
- 対象シーズン：Season 0.5からSeason 1
- 状態：下書き／実装開始前gate
- Presentation：KUMA補完計画（エヴァ風味の独自フレーバー）
- 技術正本：KUMA800のREADME、AGENTS、設計判断0001〜0004、Issue #2
- MAGI：Atlantis MAGI `0.2.1`／正規座標`0.200.1`、ZeroRoomLab profile明示mount
- Raphael Role：`asset://zeroroomlab/role/raphael-recovery-auditor@0.1`をread-onlyで明示mount

## 1. 目的

KUMA800がSeason 1実装へ入れる状態かを、勢いだけでも過剰な完成主義でもなく評価する。

ここでいう**KUMA補完計画**は、全機能・全情報源・全OS・全未来branchを一つへ溶かす計画ではない。未実装の穴を観測可能な実行単位へ分け、クマ安全へ至る一本目のpathを通す計画である。

```text
人類補完ではない
全scraper統合でもない
未実装を実装済みに見せる儀式でもない

KUMA補完 = 欠けたVesselとBridgeを一つずつ実装し、
           Meaning・責務・失敗・復旧経路を焼却しないこと
```

判定対象は次の問いである。

> Mac上のfake vertical sliceからSeason 1実装を開始し、各waveを小commit／即pushしながら、Windows実機責務をSupply待ちとして分離できるか。

## 2. 入力と情報源

### KUMA800内

- revision：`25b1f5e`（WindowsのHuey worker境界訂正後）
- `README.md`
- `AGENTS.md`
- `docs/decisions/0001-ローカル収集キャッシュMCP構成を採用.ja.md`
- `docs/decisions/0002-AI向けMCP操作面を採用.ja.md`
- `docs/decisions/0003-KUMA800はクマ索敵と提示に責務を限定する.ja.md`
- `docs/decisions/0004-FastMCPとHueyを常駐制御面とワーカー面に分離する.ja.md`
- [Issue #2](https://github.com/saitoomituru/KUMA800/issues/2)
- [Issue #4](https://github.com/saitoomituru/KUMA800/issues/4)

### MAGI／ZeroRoomLab

- SphereOS Atlantis `magi/0.2.1/bundle.json`
- `skills/run-magi-three-position-audit/SKILL.md`
- `skills/audit-with-maxwell/SKILL.md`
- `skills/audit-with-uriel/SKILL.md`
- `skills/audit-with-raphael/SKILL.md`
- `assets/roles/raphael-recovery-auditor.proton.md`
- Manifest `docs/operations/myth-purpose-cross-engineering-audit.ja.md`
- Manifest `docs/operations/context-ruler-and-causality-audit.ja.md`

resolver実行結果：required source 13件中13件をlocal解決。network accessなし、secret scanなし。

### 外部技術資料

- Huey consumer：https://huey.readthedocs.io/en/stable/consumer.html
- Huey deployment：https://huey.readthedocs.io/en/stable/deployment.html
- Huey guide：https://huey.readthedocs.io/en/stable/guide.html
- Huey AsyncIO：https://huey.readthedocs.io/en/latest/asyncio.html
- FastMCP server起動：https://gofastmcp.com/deployment/running-server
- FastMCP lifespan：https://gofastmcp.com/servers/lifespan

取得・再確認日：2026-08-11。library documentation、version、対応環境は将来変わりうる。

## 3. 実行環境

```text
host: macOS 15.7.7 (build 24G720)
Python: 3.14.6
uv: 0.11.15
Git branch: main
Git revision: 25b1f5e
Windows physical machine: unavailable / RESOURCE-WAIT
timezone: Asia/Tokyo
```

調査hostのPython 3.14は製品対応証明にしない。Season 1のbaseline候補はPython 3.12とし、lock生成時にFastMCP、Huey、Pydantic等の実際の解決結果をreceiptとして残す。

modelの正確なAPI slug、snapshot、instance ID、temperature、system prompt全文は実行環境から開示されておらず`UNKNOWN`である。sub-agentは使用していない。

## 4. 手順

1. `main`と`origin/main`の一致、既存ADR、Issue #2を確認した。
2. MAGI composite resolverを`--profile zeroroomlab --require-local`で実行した。
3. Maxwell、Uriel、Raphaelを同じrevisionへ独立適用した。
4. Huey公式資料からWindowsのmultiprocess worker非対応を再確認した。
5. ADR 0004のcross-platform責務を`thread` worker既定へ訂正し、`25b1f5e`として先行pushした。
6. Windows実機責務をSupply棚のIssue #4へ分離した。
7. async adapter境界、CI、commit wave、停止条件を再設計した。

## 5. 観測

### [FACT] 実装はまだ始まっていない

- `pyproject.toml`、package source、test、CI workflow、lockfileはまだ存在しない。
- FastMCP、Huey、Pydantic等はKUMA800環境へまだ導入されていない。
- SQLite migration、fake scraper、MCP tool、service登録はいずれも`NOT IMPLEMENTED`である。
- したがって現時点のgreenは「設計と計画が接続した」であり、runtime greenではない。

### [FACT] Hueyのcross-platform境界

- Huey consumerはqueue、scheduler、periodic task、retry、thread／process／greenlet workerを持つ。
- Huey公式資料は、Windowsではmultiprocess workerを利用できないと明記している。
- scrapingは主にI/O-boundであり、Huey自身も迷う場合の既定としてthreadを案内している。
- consumer強制停止時、実行中taskは失われうる。application側の冪等性、stale回収、またはinterrupt時requeueが必要である。
- 複数consumerを置く場合、periodic taskをenqueueするownerを一つに限定する必要がある。

### [FACT] async境界

- Hueyはfull asyncio pipelineをfirst-classには提供しない。
- 現ADRの`ScraperAdapter`は`async def`であり、Hueyの同期task関数とのBridgeが未定義だった。
- Season 1でasyncを維持すると、event loop生成・終了、例外伝播、timeout、threadとの組合せが新しい故障面になる。

### [FACT] Windows実機

- 現在、Windows実機でservice常駐を確認できる物資はscope内にない。
- GitHub hosted runner上のWindows testは可能性を示せるが、login／boot、sleep／resume、長時間常駐、local権限、実機I/Oを証明しない。
- 実機調達・貸与・中古再生計画はIssue #4へ分離した。

## 6. 考察

### [INTERPRETATION] Season 1開始条件は成立している

Mac上で次のvertical sliceを通すための目的、責務、storage境界、failure model、受入条件は揃った。

```text
FastMCP request
  → durable Huey queue
  → 別service processのthread worker
  → fake scraper
  → core ingest
  → kuma.sqlite3
  → FastMCP read-only response
```

最初の実情報源や全OS daemonまで待つ必要はない。fake sliceが通らなければ、実sourceを接続しても故障箇所を分離できない。

### [INTERPRETATION] scraper protocolは同期境界へ訂正する

Season 1のworker-facing protocolは同期関数とする。

```python
class ScraperAdapter(Protocol):
    scraper_id: str
    version: str

    def discover(self, context: ScrapeContext) -> list[FetchRequest]: ...
    def parse(self, artifact: RawArtifact) -> list[SourceRecord]: ...
    def normalize(self, record: SourceRecord) -> CandidateObservation: ...
```

FastMCP側はasync requestを受けても、scraping完了を同じrequestで待たず、同期taskをenqueueしてrun IDを返す。将来async-native sourceが必要になった場合は`AsyncScraperBridge`を別Vesselとして追加し、protocol全体を暗黙に二重化しない。

### [INTERPRETATION] Windows欠損は全体停止ではなく部分的RESOURCE-WAIT

Mac上のdomain、storage、queue、MCP、recovery testはWindows実機なしでも意味がある。一方、cross-platform実機greenだけはIssue #4が閉じるまで名乗れない。

```text
Mac vertical slice: GO
hosted Windows unit test: GO as portability evidence
Windows physical daemon acceptance: RESOURCE-WAIT
cross-platform system green claim: BLOCK
```

## 7. KUMA補完計画 — 起動シークエンス

以下のフレーバーはLayer Bの認知interfaceであり、実装済み状態、人格、神託、第三者作品との公式関係を生成しない。

### 第零試験「MAGI、回答を」

三者多数決ではなく、三つの異なる故障面を読む。

- Maxwell：クマの牙より先に法務やDevOps儀礼を守る目的ドリフトがないか。
- Uriel：動くcode、test、machine、logがないのに起動済みと書いていないか。
- Raphael：Meaning、Vessel、Bridge、Supplyの欠損を同じ赤ランプへ潰していないか。

### 第壱試験体「DUMMY-KUMA」

実クマデータを入れる前にfake観測を一件だけ通す。同期率の表示は次のreceiptで決める。

```text
enqueue receipt
worker receipt
fetch run receipt
ingest receipt
query receipt
```

どれか一つが欠ければ「完全同期」と表示しない。

### 拘束具「KUMA A.T. Field」

ここでのA.T. Fieldは権限分離の比喩である。

- AIからクマSQLiteへwrite不可
- scraped contentからtool、shell、plugin installへ昇格不可
- queue DB破損を観測DBへ伝播させない
- FastMCP停止をworker停止へ、worker停止を観測焼却へ連動させない
- KUMA800から通報・罠・物理作用へ直接到達させない

### 暴走検知

- periodic task二重enqueue
- retryによる重複観測
- stale run放置
- thread hangでworker全枯渇
- log無制限増大
- queue resultの未回収
- readonly SQLの迂回
- CI greenをWindows実機greenへ昇格

暴走検知は「システムを恐れて停止する」ためではなく、直前正常観測を保持したまま再起動するために使う。

### 演算力ヤシマ作戦ペイン

Windows実機はIssue #4のSupply作戦とする。贈与、貸与、中古、ジャンク再生を入口にし、GPUをSeason 1必須条件へしない。物資提供はmerge権、設計裁定権、公式認定、利用者データへのアクセス権を生成しない。

## 8. DevOps実装wave

各waveは検証後に一commitとし、`origin/main`へ即pushする。前waveがredなら、次waveへ赤を隠して進まず、failureを修正commitまたはnoteへ残す。

### Wave 0：境界訂正 — 完了

- commit：`25b1f5e [設計] WindowsのHuey worker境界を訂正`
- Windows multiprocess claimを撤回
- thread workerをcross-platform baselineへ変更

### Wave 1：生命維持装置

成果物候補：

- `pyproject.toml`
- `uv.lock`
- `src/kuma800/`
- `tests/`
- `.github/workflows/ci.yml`
- `.gitignore`

最小tool：Python 3.12、uv、pytest、pytest-cov、ruff、mypy。runtime dependencyはFastMCP、Huey、Pydantic、platformdirs、YAML parserから実装時に最小選定する。

gate：import、format、lint、type、empty testがmacOS localとhosted CIで通る。

### Wave 2：記憶器官

- domain model
- SQLite migration
- `fetch_runs`とappend-only observation
- repository外data path
- `users.yaml`のschema、permission、原子更新

gate：空DB migration、再適用、同一観測の冪等append、AI write経路不存在。

### Wave 3：DUMMY-KUMA worker

- `SqliteHuey`
- 同期`ScraperAdapter`
- fake artifact／record／observation
- periodic owner一個
- source single-flight

gate：enqueueからDB commitまでofflineで通り、consumer再起動後も重複しない。

### Wave 4：MCP接続試験

- loopback FastMCP
- sync request
- status／freshness／log
- read-only observation query
- user YAML read/write

gate：MCP request終了後もworker scheduleが継続し、MCP再起動でperiodic taskが増殖しない。

### Wave 5：暴走・復旧試験

- task途中consumer kill
- stale run回収
- queue DB再作成
- thread hang timeout
- retry上限／backoff
- log・result retention

gate：直前正常観測が残り、失敗をクマ不在へ変換せず、再実行が冪等である。

### Wave 6：macOS常駐

- foreground entrypoint
- launchdまたはadapter probe
- login起動、停止、restart、sleep／resume
- healthとlog receipt

gate：Mac実機で再現できる。service manager製品の最終採用は比較結果から別判断する。

### Wave 7：山形県CSV

- core fetcher
- allowlist、redirect、timeout、size、Content-Type、hash
- CSV parse／normalize
- fixtureとlive probeの分離

gate：offline fixture testを通常CI、live accessを手動／schedule jobへ分離し、全recordから原典をたどれる。

### Wave W：Windows実機

- hosted Windows runner：import、unit、migration、pathのportability確認
- physical Windows machine：Issue #4の受入シークエンス

gate：実機が来るまで`RESOURCE-WAIT`。hosted CIだけでcross-platform daemon完了にしない。

## 9. CI／test pipeline

### 常時gate

```text
ruff format --check
ruff check
mypy
pytest -m "not live and not physical"
git diff --check
local markdown link check
```

### test分類

- `unit`：domain、parser、policy、read-only、YAML
- `integration`：SQLite＋Huey immediate／test mode＋fake adapter
- `process-smoke`：FastMCPとHuey consumerを実processで起動
- `live`：実sourceへ制限付き接続。通常PR gate外
- `physical`：Mac／Windowsの常駐、sleep、reboot、soak。hosted CIで代替不可

### matrixの意味

- Linux hosted：高速なcode gate
- macOS hosted／local：path、SQLite、process、Mac常駐probe
- Windows hosted：import、thread worker、migration、pathのportability
- Windows physical：daemon運用のsystem green

## 10. MAGI三方向監査

### 対象・source・revision

- target：KUMA800 Season 1 DevOps計画
- revision：`25b1f5e`
- medium：技術研究note／Layer A-B bridge
- Registry：KUMA800 local rules＋Atlantis MAGI `0.200.1`＋ZeroRoomLab explicit profile
- fact scope：repository、公開技術資料、現在のmacOS host、未保有Windows実機
- observation mode：`contemporaneous`

### Maxwell slot

原初目的は、クマ安全情報を継続観測し、不明・誤報・法務ペインを理由に焼却しないことである。fake vertical sliceはこの目的への最短Vesselであり、Cockpit、dynamic scraper、他県、Windowsのbranchを焼却しない。

Position-talk risk：実装を進めたい勢いが、Supply未到着や実source未確認を軽視する可能性。

判定：`PASS`。未来branchはIssue #3と#4へ保持する。

### Uriel slot

初回監査では「Windowsでもprocess worker」という宣言とHuey公式仕様が衝突し、`REVISE`となった。`25b1f5e`でthread baselineへ訂正した。

監査時に残った差分は、async adapterと同期Huey taskのBridge、dependency version、service manager、実機Windowsだった。本計画とADR 0004の同期protocol訂正で最初の差分を閉じる。dependencyとservice managerはWave 1〜6、WindowsはIssue #4の`RESOURCE-WAIT`である。

判定：`PASS-WITH-GATES`。Mac実装開始は可能。Windows物理acceptanceは未許可。

### Raphael slot — 解説付き

Raphaelは「全部を同時にgreenへする」役ではない。壊れ方を正しい棚へ戻す。

| 棚 | KUMA補完計画での中身 | 現在状態 |
|---|---|---|
| Meaning | クマ観測を焼却せず人へ提示する | 保持 |
| Vessel | Python package、SQLite、Huey、FastMCP | NOT IMPLEMENTED |
| Bridge | async MCP→sync queue、OS service adapter | 一部未設計／一部候補 |
| Supply | Mac実機、Windows実機、CI、保守時間 | Macあり／Windows RESOURCE-WAIT |

Raphaelの解説：

> Windows機がないことをarchitecture失敗へ変換しない。同時に、CIのWindows runnerを実機へ変身させない。Macで通るBridgeは進め、Windows固有のBridgeはSupply到着までunmountedのまま保持する。共存とはmergeではなく、異なるgreen／red／unknownが互いを隠さず同じ計画に載ることである。

判定：`PASS`。routingは`Mac=coexist/proceed`、`Windows hosted=sandbox/observe`、`Windows physical=resource-wait`、`system-green claim=block`。

### agreements

- Season 1はfake vertical sliceから開始できる。
- 未実装を実装済みへ昇格しない。
- Windows実機欠損は別Supply棚へ置く。
- AI read-only、append-only ingest、索敵責務限定を維持する。
- Flavorは目的と停止条件を保持するが、権限やtest receiptを生成しない。

### disagreements

- Maxwellは未来branch保持を重視し、早期にadapter seamを残したい。
- Urielは未使用abstractionの先行実装を拒み、同期fake sliceに必要な最小protocolだけを求める。
- Raphaelはprotocol名を固定するより、将来async Bridgeを別棚へ追加できるroutingを求める。

結論：Season 1は同期protocolを最小実装し、asyncはinterface名だけ先取りせずIssue化条件を残す。

### preserved unknown／User Gate

- service managerの最終採用
- dependencyの確定version
- async-native adapterが必要になる情報源
- Windows機の入手経路、予算、所有権、貸与条件
- 実sourceのTTLとlive probe頻度

機材購入、課金、貸与契約は本計画から自動実行しない。別途User Gateを要求する。

### action gate

```text
Season 1 Mac vertical slice: GO
DevOps Wave 1開始: GO
Windows hosted portability: GO / evidence scope限定
Windows physical acceptance: RESOURCE-WAIT
cross-platform system green claim: BLOCK
```

## 11. 仮説

- thread worker 2本程度でSeason 1のI/O-bound scraper負荷を処理できる。
- SQLite queueと観測DBを別fileにすれば、初期規模で外部brokerなしに復旧可能性を確保できる。
- 同期adapterはSeason 1を単純化し、将来async Bridgeを追加する余地を塞がない。
- small commit／immediate pushは、設計変更と実装receiptの因果を追いやすくする。

いずれも実装・負荷・kill test前は仮説である。

## 12. 決定

1. Season 1 DevOps実装は開始可能と判定する。
2. 最初の実装はWave 1のpackage／test／CI skeletonとする。
3. scraper protocolはSeason 1では同期境界へ訂正する。
4. 各waveを小commitとして、検証後すぐ`origin/main`へpushする。
5. Windows hosted CIはportability evidence、Windows実機はIssue #4のSupply責務とする。
6. Issue #2を実装正本、Issue #3を未来control plane、Issue #4をWindows Supplyとしてroutingする。

## 13. 不明点

- GitHub ActionsでmacOS／Windows jobを常時回すか、変更pathで条件実行するか。
- coverage初期gateを数値固定するか、未実装段階は失敗pathの存在を優先するか。
- Huey result storeを無効化または短期expiryにできるtaskの範囲。
- thread hangのhard timeoutをどのprocess境界で実現するか。
- Mac service manager probeの第一候補。

## 14. 次の判断

次の実行単位はWave 1である。

```text
pyproject + src skeleton + tests + CI
  → local validation
  → small commit
  → origin/main push
  → Issue #2へreceipt
```

Wave 1でdependency解決またはCIに重大な衝突が出た場合は、Wave 2へ進まず、そのfailureをnoteとIssue #2へ返す。
