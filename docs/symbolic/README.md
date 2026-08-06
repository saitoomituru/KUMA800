# シンボリック参照

KUMA800が参照する上位概念と、repository内での翻訳先をまとめます。

## ZeroRoomLab Manifest

- 参照先：https://github.com/saitoomituru/ZeroRoomLab-manifest
- 役割：複数repositoryをまたぐ研究原則、公開境界、責任配分
- KUMA800への翻訳：物理安全を優先し、根拠・不明・取得履歴を焼却しない

## SphereOS Atlantis

SphereOS Atlantisの語彙は、KUMA800の設計を整理するためのシンボリックです。現時点でKUMA800がAtlantis実行基盤へ依存することを意味しません。

| シンボリック | KUMA800での扱い |
|---|---|
| Meaning | 原文、文脈、正規化後データを分離して保持する |
| World | 山形県、自治体、年度、公開主体、取得時点を観測世界として識別する |
| Registry | データ源、解析器、schema、MCPツールを登録可能な境界にする |
| OAE / Provenance | URL、取得日時、ハッシュ、変換過程を追跡する |
| FoldLog | 訂正、棄却、再解釈を元データの削除なしで残す |
| DOs | 入力、出力、副作用、権限、検証、不明を作業単位ごとに明示する |

## OpenSourcePITETOから継承する運用

- repository直下の `AGENTS.md` を局所規約の正本とする
- `note/` を下書きの実験台帳として使う
- 採用判断を設計台帳へ昇格する
- 未実装を実装済みへ変換しない
- 人間とAIの引継ぎを会話ログだけに依存させない

## 参照の原則

- 概念名の格好よさだけで依存関係を増やさない
- 実装責務へ翻訳できないシンボリックはコードへ持ち込まない
- 日本語で説明できる設計を、英語語彙だけで権威化しない
