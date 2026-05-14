# battle-assistant-sv
ポケモンSVランクマッチ用のリアルタイム自動ダメージ計算サイト<br>
https://pbasv.cloudfree.jp/<br>
のソースコード

## 使用言語
- Javascript
- Python

## ディレクトリ構成
- log : デバッグ用
- data/battle_data : ポケモンHOMEの使用率データ
- data/icon : ポケモンのアイコン画像
- data/item_img : ポケモンのアイテム画像
- data/template : テンプレートマッチング用のアイコン画像
- data/type_img : タイプのアイコン画像

## 使い方
- index.html : リアルタイム自動ダメージ計算アプリ
- setting.html : 詳細設定の小型ウィンドウ
- pokemon_view.html : ポケモンの育成情報を見る小型ウィンドウ
- manager.html : ポケモン管理ページ
- data/update_battle_data.py : ポケモンHOMEのランクマッチ使用率を取得する。毎日走らせる
- data/*.py : 様々なバックデータを作成するが、すでにあるため不要

## js/
- index.js, manager.js : 自動ダメージ計算・ポケモン管理アプリのロジック
- pokemon.js : ダメージ計算やランクマッチ使用率の読み込みなどの、ポケモン対戦に関するクラス
- common.js : 汎用関数
- storage.js : ローカルストレージを扱うクラス
- opencv.js : OpenCV
- tesseract.min.js : OCR
- guessLanguage.js, _languageData.js : 言語識別
- combobox.js, imageselect.js : UI
