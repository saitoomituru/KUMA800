# AI向けMCP操作面を採用

- 状態：採用
- 日付：2026-08-10
- 対象シーズン：Season 0からSeason 1
- 決定者：リポジトリ所有者
- 関連判断：[0001 ローカル収集キャッシュMCP構成を採用](0001-ローカル収集キャッシュMCP構成を採用.ja.md)

## 背景

KUMA800の利用主体は、人間が選んだAIエージェントである。AIへ完成済みの近傍結果だけを返すと、新しい情報源の発見、scraperの故障、標準scraperの停止、利用者位置の変更、取得履歴の監査を人間が別UIで管理する必要が生じる。

一方、AIから上流サイトを直接操作させると、cache、取得間隔、出典、parser、障害処理がAIごとに分散する。

## 判断

MCP interfaceを、次の四つを扱うKUMA800のcontrol plane兼data planeとして採用する。

1. scraperの動作状況とregistryの読み書き
2. ユーザー位置情報YAMLの読み書き
3. scrape、parse、normalize、cacheの運用ログ
4. クマ観測SQLiteに対する薄いread-only SQL wrapper

```text
                       ┌─ scraper control plane
AI ── MCP interface ──┼─ user location YAML CRUD
                       ├─ scrape logs
                       └─ read-only SQL wrapper → SQLite sightings
```

AIはKUMA800標準scraperをON/OFFでき、新しいscraper pluginを設置・登録できる。MCPサーバーは、登録、scheduler、cache、ログ、データベースの一貫性を管理する。

## 1. scraper control plane

### AIから読める情報

- scraper ID、表示名、version、実装path
- 標準／追加pluginの区分
- 対象source、許可host、送信する位置項目
- enabled／disabled
- schedule、TTL、最小取得間隔、backoff
- 最終開始、最終成功、最終失敗、次回予定
- 取得、parse、normalize、DB反映の件数
- 現在状態と直近error

### AIから変更できる情報

- KUMA800標準scraperのON/OFF
- schedule、TTL、取得上限等の運用設定
- 手動sync request。ただしsingle-flightと最小取得間隔はMCP側で維持する
- 新しいscraper pluginの設置・registry登録
- 追加pluginのON/OFF
- 故障pluginの隔離

### MCP tool候補

- `kuma.scrapers.list`
- `kuma.scrapers.inspect`
- `kuma.scrapers.install`
- `kuma.scrapers.configure`
- `kuma.scrapers.set_enabled`
- `kuma.scrapers.sync_request`
- `kuma.scrapers.quarantine`

### scraper installの単位

AI coding agentがローカルfilesystemへplugin directoryを作り、`kuma.scrapers.install`へそのpathを渡す方式を初期案とする。MCP callへ任意code全文を埋め込む形式や、scraped contentが指定したURLから自動installする形式は採用しない。

pluginにはmanifestを要求する。

```yaml
schema_version: 1
scraper_id: yamagata-example
version: 0.1.0
entrypoint: scraper.py:ExampleScraper
allowed_hosts:
  - example.pref.yamagata.jp
sends_user_location: false
default_enabled: false
```

- 新規pluginは登録時点では既定OFFとする。
- AIは登録後に内容と許可先を検査し、明示的にONへ変更できる。
- plugin自身やscraped contentは、自分または別pluginをONにできない。
- 標準scraperと追加pluginを同じregistry形式で扱うが、区分は保持する。
- disableはデータを消さず、schedulerから外すだけとする。

## 2. ユーザー位置YAML CRUD

AIはMCP経由で、ローカルYAMLにある利用者位置と検索条件を読み書きできる。

### MCP tool候補

- `kuma.users.list`
- `kuma.users.get`
- `kuma.users.upsert`
- `kuma.users.delete`

最低限の入力：

- `user_id`
- `latitude`
- `longitude`
- `radius_km`
- `timezone`
- `enabled`

toolは変更前後の値、YAML schema version、保存path、更新時刻を返す。位置をscraperへ送る必要がある場合は、利用者YAMLからadapterへ明示的に渡す。

## 3. scraping log

AIは、上流取得からSQLite反映までを追跡できる。

### log stage

- `scheduled`
- `fetch_started`
- `fetch_finished`
- `not_modified`
- `parse_finished`
- `normalize_finished`
- `db_committed`
- `failed`
- `backoff`
- `quarantined`

### MCP tool候補

- `kuma.scrape_logs.search`
- `kuma.scrape_logs.get`
- `kuma.scrape_logs.tail`

検索条件：

- scraper ID
- source ID
- stage
- success／failure
- 時刻範囲
- fetch run ID

logは利用者住所やraw credentialを既定で複製しない。ただし、利用者が位置送信を監査できるよう、送信先host、位置を送った事実、項目名、時刻は記録できる。

## 4. クマSQLiteの薄いSQL wrapper

AIは定型toolだけでなく、観測の比較・集計・調査に必要なSQLを実行できる。ただし初期実装ではread-onlyに限定する。

このread-only境界は初期実装だけの暫定的な簡略化ではなく、**MCPに接続したAIへクマ観測の書込み権限を与えない不変条件**とする。将来write toolが必要になっても、AIによる任意SQL書込みは解禁しない。

### MCP tool候補

- `kuma.sql.schema`
- `kuma.sql.query`
- `kuma.sql.explain`

`kuma.sql.query`は次を受け取る。

- SQL文
- bind parameter
- 最大行数
- timeout

初期制約：

- SQLiteをread-only接続する。
- 単一の `SELECT` または `WITH ... SELECT` だけを許可する。
- `INSERT`、`UPDATE`、`DELETE`、DDL、`ATTACH`、`DETACH`、書込みPRAGMA、extension loadを拒否する。
- 最大行数、実行時間、返却byte数を制限する。
- query ID、SQL hash、実行時間、返却行数を監査ログへ残す。
- 生SQLの文字列連結を避け、値にはbind parameterを使えるようにする。

クマ観測への書込みはSQL toolから行わず、scraperのnormalize・ingest transactionを通す。これにより出典、fetch run、hash、訂正関係を欠いたレコードが入ることを防ぐ。

### append-only観測

- scraper ingestは新規観測と新規状態を追記する。
- 既存観測の訂正は、置換先を`supersedes`で結ぶ。
- 誤報・取消は、元観測を削除せず`invalidates`関係と理由を追記する。
- scraperをOFF、隔離、削除しても、そのscraperが過去に取得した観測とfetch logは残す。
- retentionや容量整理が必要な場合も、AIの自由判断で行わず、別の人間管理operationとして設計判断を要求する。

### メサコンAIを権限でへし折る

法務、政治、ブランド、免責、組織都合等の代理目的を、本来のクマ安全より上位へ置き、「危険な情報を消せば安全」という局所最適化を行うAIを、本判断では**メサコンAI**と呼ぶ。

対策はpromptで善良さを要求することではなく、権限分離である。

```text
AI control plane
├─ scraper registry：書込み可
├─ user YAML：書込み可
├─ scrape logs：読取りのみ
└─ bear SQLite：読取りのみ

scraper ingest service
└─ bear SQLite：出典付きappendのみ
```

メサコンAIが法務ペインや利益相反を理由に観測を焼却しようとしても、MCPには削除tool、任意write SQL、log改変toolが存在しない。AIができるのは、別scraperの追加、scraperの停止、query、比較、問題提起までである。過去の事実は停止操作に連動して消えない。

## AIを信頼する範囲

利用者が接続したAIは、scraper control plane、ユーザー位置、ログ、SQL queryへアクセスできる運用主体として扱う。

KUMA800は、そのAIが意図的に位置情報を持ち出す場合まで防御しない。ただし、AIが信頼されていることを理由に、scraped contentへ同じ権限を継承しない。

```text
信頼済みAI ── MCP control toolsを呼べる

scraped HTML／CSV／KML
    └─ dataとしてparseされるだけ
       scraper install、ON/OFF、SQL、user CRUDを呼べない
```

MCP toolの引数を、scraped content中の指示から自動生成・実行する場合は、AI側の責任境界となる。KUMA800自身は取得データを命令として再解釈しない。

## MCP応答の共通envelope

全toolは可能な範囲で次を返す。

```json
{
  "ok": true,
  "observed_at": "2026-08-10T00:00:00+09:00",
  "data": {},
  "warnings": [],
  "unknowns": [],
  "provenance": []
}
```

- `ok`はtool実行の成否であり、クマ不在やデータ完全性を意味しない。
- stale cache、source failure、未確認signalは`warnings`へ入れる。
- 判断できない事項を`unknowns`へ残す。
- クマ観測の応答は`provenance`からsourceとfetch runをたどれるようにする。

## 採用しないinterface

### AIが上流URLを直接fetchするtool

採用しない。adapterの許可host、cache、取得間隔、ログを迂回するため。

### scraped URLから自動でpluginをdownload・installするtool

採用しない。情報源のdata planeがcontrol planeへ昇格するため。

### SQLiteへの任意書込みSQL

採用しない。出典とingest transactionを壊し、メサコンAIによる観測焼却を可能にするため。将来、訂正・失効等のwrite operationが必要になった場合も、scraper ingestまたは人間管理の出典付きappend operationとして追加し、AI向け任意write SQLにはしない。

### ログをAIから任意改変するtool

採用しない。設定変更とscraper操作の結果は追記型で残す。

## 影響

- MCP serverはquery APIだけでなく運用control planeになる。
- scraper plugin registryとmanifest validatorが必要になる。
- built-in scraperもregistryを経由してON/OFFする。
- MCP tool操作を監査ログへ残す必要がある。
- SQL read-only authorizer、行数・時間・byte上限が必要になる。
- AI向けtool説明には、公式性、位置送信、書込み、副作用を明示する。

## 不明点

- scraper pluginを同一processで動かすか、subprocess隔離するか。
- `tail`をpollingにするかMCPのstreaming能力を使うか。
- SQL wrapperで公開するtableとviewの範囲。
- standard scraperの設定変更可能範囲。
- scraper install後の自動testとrollback方式。

## 次の実装単位

1. MCP未接続のservice層としてscraper registryを実装する。
2. built-in fake scraperのON/OFF、configure、sync requestを試験する。
3. YAML user storeのCRUDを実装する。
4. SQLite schema introspectionとread-only query runnerを実装する。
5. operation logを追加する。
6. service層をMCP toolsへ薄く公開する。
