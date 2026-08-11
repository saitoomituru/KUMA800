# FastMCPとHueyを常駐制御面とワーカー面に分離する

- 状態：採用（OS常駐adapterの製品選定は保留。2026-08-11にWindows worker型を訂正）
- 日付：2026-08-11
- 対象シーズン：Season 0からSeason 1
- 決定者：リポジトリ所有者
- 関連判断：[0001 ローカル収集キャッシュMCP構成](0001-ローカル収集キャッシュMCP構成を採用.ja.md)、[0002 AI向けMCP操作面](0002-AI向けMCP操作面を採用.ja.md)、[0003 クマ索敵と提示への責務限定](0003-KUMA800はクマ索敵と提示に責務を限定する.ja.md)

## 背景

FastMCPをHTTP transportで起動すればMCP server自体は常駐できる。しかし、MCP requestの寿命と、定期収集、再試行、複数scraperの並列実行、process障害からの復旧は同じ問題ではない。

FastMCP process内へschedulerとscraper taskをすべて置くと、次の結合が生じる。

- MCP serverの再起動が収集中taskを巻き込む。
- ASGI worker数やlifespanの起動回数によって定期taskが重複しうる。
- scraperの停止、hang、memory leakがcontrol planeを停止させうる。
- OS起動登録、死活監視、task queue、cache、クマ観測DBの責任が一つのprocessへ混ざる。

一方、KUMA800専用の親daemonを自作すると、macOS、Windows、Linuxごとのservice登録・再起動・log・終了処理まで製品固有コードとして背負うことになる。

## 判断

FastMCPとHueyを、同じKUMA800に属する**兄弟service**として分離する。

```text
AI / MCP client
       │
       ▼
kuma-mcp（FastMCP、loopback HTTP、単一process）
  ├─ user YAMLの読み書き
  ├─ scraper・fetch run状態の読取り
  ├─ sync requestのenqueue
  └─ クマSQLiteのread-only query
       │
       ▼
queue.sqlite3（Hueyの運用queue）
       │
       ▼
kuma-worker（Huey consumer / scheduler / platform workers）
  ├─ source別schedule、retry、backoff、single-flight
  ├─ scraperのfetch・parse・normalize
  └─ core ingest APIだけを通してappend
       │
       ▼
kuma.sqlite3（観測・出典・fetch run）

OS service manager
  ├─ kuma-mcpの起動・停止・再起動・log
  └─ kuma-workerの起動・停止・再起動・log
```

FastMCPはAI向けcontrol planeとquery面を担当する。Hueyは定期実行とworker concurrencyを持つdata planeを担当する。両者の連絡には一時的なpipeではなく、durableなqueueを使う。

Huey公式資料ではmultiprocess workerはWindows非対応である。Season 1はI/O-boundなscrapingを主対象とするため、macOSとWindowsに共通する`thread` workerを既定とする。macOS／Linuxの`process` workerはCPU-bound解析の比較probeに降格し、Windows対応を示す根拠にはしない。

ここで維持する「別process」とは、FastMCP serviceとHuey consumer serviceの分離である。Season 1は、すべてのscraper taskがHuey内部でも個別processに隔離されるとは主張しない。強い隔離が必要になったadapterには、timeoutとresource上限を持つsubprocess runnerまたは別worker serviceを将来追加する。

OSへの常駐登録とprocess死活監視は、FastMCPにもHueyにも内包せず、外部のservice manager adapterへ委譲する。`py-simple-service-manager`は候補として実機probeするが、現時点では最終採用しない。macOSのlaunchd、WindowsのWinSWまたは同等機構、Linuxのsystemdを直接包む薄いadapterも比較対象に残す。

## 保存境界

### `queue.sqlite3`

Hueyが所有する可変の運用queueとする。taskの予約、retry、schedule等を保持する。これは観測の正本ではなく、消失時に再構築可能な運用状態である。

### `kuma.sqlite3`

クマ観測、出典、fetch run、訂正・失効関係を保持する。AIは書き込めない。登録済みscraperの結果を検証するcore ingest APIだけがtransactionを開始し、unique constraintと内容hashにより冪等にappendする。

複数workerからingestが呼ばれても、SQLite transactionで書込みを直列化する。Season 1では専用writer processを追加しない。lock競合やwrite throughputが実測上の問題になった場合だけ、ingest command queueと単一writerを再検討する。

### `users.yaml`

利用者位置と検索条件を保持する。repository、クマ観測DB、公開logへ混ぜない。MCPを通じて利用者が選んだAIへ読み書きを提供する境界は、設計判断0001と0002を維持する。

### raw artifact

HTTP取得物は観測tableへ直接埋め込まず、内容hash、取得時刻、最終URL、応答metadataからたどれる隔離可能なartifactとして扱う。保存量とretentionは別判断とする。

## process障害と冪等性

workerまたはconsumer serviceを強制終了すると、実行中taskが完了通知を残さず失われる可能性がある。そのため、queueの存在だけを実行証明にしない。

- `fetch_runs`へ`STARTED`、`SUCCEEDED`、`FAILED`、`STALE`を記録する。
- 起動時に期限超過した`STARTED`を`STALE`へ遷移させ、再実行候補にする。
- source単位のleaseまたはsingle-flight keyで同時fetchを抑止する。
- 同じartifact hash、source event ID、assertionを再処理しても観測が無制限に重複しないようにする。
- 失敗時も直前正常snapshotを削除しない。
- task引数とworkerへ渡すmodelをserialize可能にし、queue payloadへruntime objectやcredentialを入れない。

## scraper境界

Season 1では、repositoryに同梱する少数のadapterを静的に登録する。最初のvertical sliceは実ネットワークへ接続しないfake scraperで通す。

将来のmeta記述へ道を残すため、概念上の境界は次に固定する。

```python
class ScraperAdapter(Protocol):
    scraper_id: str
    version: str

    async def discover(self, context: ScrapeContext) -> list[FetchRequest]: ...
    async def parse(self, artifact: RawArtifact) -> list[SourceRecord]: ...
    async def normalize(self, record: SourceRecord) -> CandidateObservation: ...
```

URL取得、timeout、redirect、Content-Type、容量上限、内容hashはadapter自身ではなくcore fetcherが強制する。将来の宣言的scraper記述も、同じ`FetchRequest`、`SourceRecord`、`CandidateObservation`へcompileする。

## Season 1へ入れる範囲

- Python packageと設定path
- FastMCPのloopback HTTP server
- HueyのSQLite queue、consumer、定期task、thread worker
- fake scraperによるenqueueからread-only queryまでのvertical slice
- `kuma.sqlite3` migration、core ingest、append-only provenance
- `users.yaml`の原子更新
- fetch runのstale回収、冪等性、source single-flight
- macOSとWindowsでのservice manager adapter比較probe
- macOSでのHuey `thread`／`process`比較probe。Windowsは`thread`だけを受け入れ対象とする
- 山形県CSVを最初の実情報源候補とし、けものおと2と過年度KML/KMZを独立adapter候補として保持

## Season 3へ送る範囲

- AIによる新規scraper pluginの設置
- 標準・追加scraperの動的ON/OFFと設定変更
- scraper manifest、設定schema、署名・rollback・隔離操作
- scraper動作を表す宣言的meta記述またはDSL
- registryと運用状態を扱うCockpit

Season 1で静的な緊急停止設定またはCLIを持つことは妨げない。ただし、それを動的control plane完成とは数えない。

## 根拠

- AIの問い合わせ頻度と上流取得頻度を切り離せる。
- scraper障害をMCP query面から隔離できる。
- custom daemonizerを自作せず、OSの既存service機構を利用できる。
- queueの再試行と観測の正本を別DBへ分け、運用状態の破損を観測焼却へ伝播させない。
- static adapterで縦に通してからmeta scraperへ拡張でき、Season 1の完成条件を肥大化させない。

## 代替案

### FastMCP process内でschedulerとscraperを動かす

Season 1の本構成では棄却する。小規模prototypeでは可能だが、server再起動、lifespan重複、scraper故障のblast radiusが大きい。

### KUMA800専用の親daemonを自作する

棄却する。OS service managerとtask queueが解いている問題を再実装することになる。

### Celery、Redis、外部RDBを必須にする

Season 1では棄却する。ローカル単体運用に対して依存と運用費が大きい。HueyとSQLiteで不足する実測が得られた場合に再検討する。

### scraperごとに独立serviceを登録する

Season 1では保留する。最初は一つのHuey consumer配下でthread workerを分ける。adapter固有依存や障害隔離が必要になったsourceだけ、後からsubprocess runner、別worker pool、または別serviceへ分離する。

## 影響

- 設計判断0001の「MCPサーバーが収集schedulerまで統合する」というprocess配置を本判断で置換する。保存境界、cache責務、AIと上流取得頻度の分離は維持する。
- 設計判断0002のcontrol plane全体像は維持するが、scraper install・動的ON/OFF・CockpitはSeason 3へ延期する。
- FastMCPとHueyの二つのserviceについて、起動、終了、log、health、versionを観測する必要がある。
- `queue.sqlite3`と`kuma.sqlite3`を別path、別backup方針で扱う必要がある。
- MCPが停止してもworkerは収集を継続でき、workerが停止してもMCPは直前正常cacheを鮮度付きで返せる。

## 不明点

- macOSとWindowsで採用するservice manager adapter。
- Hueyの採用versionとPython 3.12／3.13／Windowsでのprocess mode実機結果。
- shutdown中task、lease timeout、stale判定時間の具体値。
- raw artifactの保存量、暗号化、retention。
- SQLite write競合が専用writerを必要とする閾値。

## 見直し条件

- Hueyのthread workerまたはschedulerが主要OSで安定運用できないとき。
- SQLite queueの破損・lock・throughputが安全情報の鮮度を実測で損なうとき。
- FastMCPの推奨deploymentまたはtask機構が変わり、兄弟service分離より単純で同等に回復可能な構成が得られたとき。
- 公式push feed等により定期polling自体が不要になったとき。
- Season 3の動的plugin境界を実装するとき。

## 受け入れ試験

1. FastMCPからfake syncを要求すると、durable queue経由でworkerが実行する。
2. Huey consumer serviceをtask途中で停止して再起動すると、stale runを検出し、観測を重複焼却せず再実行できる。
3. MCPだけを再起動しても、workerのscheduleが重複しない。
4. worker停止中も、MCPは直前正常cacheと停止・鮮度を返す。
5. AI向けSQLから`kuma.sqlite3`へ書込みできない。
6. `queue.sqlite3`を再作成しても`kuma.sqlite3`の観測と出典が消えない。
7. macOSとWindowsで、loginまたはboot後の起動、異常終了後の再起動、正常停止、log取得を再現できる。

## 実装追跡

- Season 1のvertical slice：[Issue #2](https://github.com/saitoomituru/KUMA800/issues/2)
- Season 3のscraper meta記述・動的運用・Cockpit：[Issue #3](https://github.com/saitoomituru/KUMA800/issues/3)
- PayToGate・公共調達・データ独占の慢性調査：[Issue #1](https://github.com/saitoomituru/KUMA800/issues/1)。重要な周辺課題だが、本architectureの実装blockerにはしない。
