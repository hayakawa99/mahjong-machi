import pandas as pd

# fileのファイルパス
file_test_path = "/Users/hayakawa/Library/Mobile Documents/com~apple~CloudDocs/ma-jan/file"  # 実際のファイル名
output_path = "/Users/hayakawa/Library/Mobile Documents/com~apple~CloudDocs/ma-jan/format_file.csv"

# ファイルの読み込み
with open(file_test_path, "r") as f:
    lines = f.readlines()

# データ整形
formatted_data = []
line_number = 1  # 連番のカウンタ
for line in lines:
    ids = line.strip().split("\t")
    for id_ in ids:
        formatted_data.append({"連番": line_number, "牌譜ID": id_.replace(".xml", "")})
        line_number += 1  # 各牌譜IDごとに連番を更新

# データフレームを作成
df = pd.DataFrame(formatted_data)

# CSV形式で保存
df.to_csv(output_path, index=False, encoding="utf-8-sig")

print(f"整形されたデータを以下に保存しました: {output_path}")
