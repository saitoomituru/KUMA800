# Dev期の既存DB破壊的操作前にdumpを残す

- 状態：採用
- 日付：2026-08-30
- 対象シーズン：Season 1（Stable未達の間）
- 決定者：リポジトリ所有者
- 関連判断：[0001 ローカル収集キャッシュMCP構成](0001-ローカル収集キャッシュMCP構成を採用.ja.md)

## 背景

Issue #6（consumer hard-kill後のstale追跡・冪等再実行）は、`fetch_runs`へrun lineageを追記できるようschema migrationを伴う。KUMA800はまだStableへ到達しておらず、migration設計は今後も変わりうる。

このとき二つの極端はどちらも採らない。

- 破壊的操作（migration適用、schema変更、再構築）を全面禁止する → Dev grade中の設計変更が進まなくなる。
- 破壊的操作前のdumpをrepositoryへ自動保存する仕組みを無条件に作る → 将来DBへ第三者の個人情報を持つtableが追加された場合、気づかないまま自動でrepositoryへ漏らす事故経路になる。

`kuma.sqlite3`は現在、`sources` / `fetch_runs` / `sightings` / `sighting_assertions` / `source_state` / `schema_migrations`のみで構成され、いずれも公開情報源由来のクマ観測データである。利用者位置は[0001](0001-ローカル収集キャッシュMCP構成を採用.ja.md)の判断どおり別YAML（`.gitignore`で除外、`users.yaml`）に分離されており、このSQLiteには含まれない。

## 判断

Dev grade（Stable未達）の間、既存`kuma.sqlite3`へ破壊的操作を行う前に、構造とデータをSQLテキストとしてexportし、`docs/db-snapshots/`配下へcommitする運用とする。

実装は`kuma800.storage.dump.dump_database()`とする。

```text
1. sqlite_masterから実在tableを列挙する
2. 許可table一覧（allow-list）と完全一致するか検査する
   一致しない場合はexportせずエラーで停止する（fail-closed）
3. 一致する場合だけ、schema + dataをSQLテキストとしてexportする
4. 出力先が.sqlite3系拡張子でないことを確認してから書き出す
```

allow-listは`kuma800.storage.migrations`のtable定義に追随させ、無審査でtableを追加しない。

この運用は次を明示的に境界とする。

- **allow-list外のtableが存在する場合はexportを拒否する。** 将来、利用者位置や認証情報を持つtableが追加された場合、このコードのallow-listを人間が明示的に更新するまでdumpできない。
- **常駐worker・MCP・periodic taskからは呼び出さない。** dumpは人間またはCIが破壊的操作の直前に明示実行する手動/半自動ツールであり、自動化された定期dumpにしない。
- **この運用はDev grade限定。** Stableへ昇格した時点で本ADRを見直し条件に従って終了し、git履歴を肥大させ続けない別のbackup経路（repository外）へ切り替える。

## 根拠

SQLiteは`.dump`相当（`sqlite3.Connection.iterdump()`）で構造とデータをテキストSQLへ変換でき、実装コストが低い。テキストSQLはPull Requestで差分レビューでき、破壊的操作の前後比較がGit履歴上に残る。

第三者の個人情報を保存する層（`users.yaml`）は[0001](0001-ローカル収集キャッシュMCP構成を採用.ja.md)により物理的に別ファイル・別gitignore境界へ分離済みであるため、`kuma.sqlite3`のみを対象にする限り、この運用は既存アーキテクチャの境界を壊さない。

## 代替案

- 破壊的操作の全面禁止：Dev gradeの前進を止めるため却下。
- DBファイルそのものをbinaryでrepositoryへ退避：diffレビューができず、バイナリのgit履歴肥大を招くため却下。
- 外部storageへの自動バックアップ：ZeroRoomLabはUPS単独電源・ギフトエコノミー運用で、常時稼働する外部backup基盤を前提にできないため却下。

## 影響

- migration実装前にdump手順を踏む一手間が増える。
- allow-list外のtableが検出された時点でdumpは失敗し、破壊的操作は人間の判断待ちで止まる（安全側の停止）。

## 不明点

- Stable到達をどの基準で判定するか（他ADR・Issueで別途定める）。
- allow-listの粒度をtable単位からcolumn単位まで広げる必要が生じるか。

## 見直し条件

- KUMA800がStableへ昇格した時点。
- `kuma.sqlite3`のschemaへ個人を特定できるfieldを持つtableが追加された時点（allow-list更新、または本運用の停止のいずれかを判断する）。
