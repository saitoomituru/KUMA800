# db-snapshots

破壊的なDB操作（migration適用、schema変更、再構築）の直前に取る、`kuma.sqlite3`の構造＋データdumpを置く場所です。

運用ルールの正本は[設計判断0005](../decisions/0005-Dev期の既存DB破壊的操作前にdumpを残す.ja.md)です。`kuma800.storage.dump.dump_database()`（CLI: `kuma800-db-dump`）で生成します。

- 対象は`kuma.sqlite3`のみ。allow-list外のtableが見つかった場合はexportに失敗します（意図した安全側停止）。
- 命名：`YYYYMMDD-対象migrationまたは操作の短い説明.sql`
- ここに置くdumpは公開情報源由来のクマ観測データのみを含みます。利用者位置（`users.yaml`）はこのSQLiteに含まれず、対象外です。
- 本運用はDev grade（Stable未達）限定です。見直し条件は0005を参照してください。
