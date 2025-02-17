import os
import pandas as pd
import re
from subprocess import run

# 入力CSVファイルと出力ディレクトリ
input_file = "/Users/hayakawa/Library/Mobile Documents/com~apple~CloudDocs/ma-jan/formatted_file_test.csv"
output_dir = "/Users/hayakawa/Library/Mobile Documents/com~apple~CloudDocs/ma-jan/tenhou_logs"

# 出力ディレクトリを作成（既存の場合は無視）
os.makedirs(output_dir, exist_ok=True)

# 正しい牌譜IDのフォーマットを定義（例: "2019070401gm-00a9-0000-xxxxxxxx"）
haifu_id_pattern = re.compile(r"^\d{10}gm-\w{4}-\w{4}-[a-f0-9]{8}$")

# CSVを読み込み
df = pd.read_csv(input_file)

# 各行を処理
for _, row in df.iterrows():
    haifu_id = row["牌譜ID"]

    # 牌譜IDの形式を検証
    if not haifu_id_pattern.match(haifu_id):
        print(f"スキップ: 無効な牌譜ID {haifu_id}")
        continue

    # 出力ファイルのパスを作成
    output_file = os.path.join(output_dir, f"{haifu_id}.json")

    # すでに出力ファイルが存在する場合はスキップ
    if os.path.exists(output_file):
        print(f"スキップ: 既に存在するファイル {output_file}")
        continue

    # コマンドを実行して牌譜データを変換
    print(f"Processing: {haifu_id} -> {output_file}")
    result = run(["tenhou-log", haifu_id], capture_output=True, text=True)

    # 結果を処理
    if result.returncode == 0:
        with open(output_file, "w") as f:
            f.write(result.stdout)
    else:
        print(f"エラー: 牌譜ID {haifu_id} の処理に失敗しました")

print(f"全ての牌譜IDの処理が完了しました。出力先: {output_dir}")
