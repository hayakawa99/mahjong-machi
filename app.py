from flask import Flask, render_template, request
import mysql.connector
import os  # ← 環境変数を読み取るために必要

app = Flask(__name__)

@app.route('/', methods=['GET', 'POST'])
def index():
    sorted_result = None
    error = None
    selected_tiles = []

    if request.method == 'POST':
        selected_string = request.form.get('selected_tiles', '')

        if not selected_string:
            error = "牌が選択されていません"
        else:
            selected_tiles = [s for s in selected_string.split(',') if s]
            if not selected_tiles:
                error = "牌が選択されていません"
            else:
                try:
                    # DBパスワードを環境変数から取得する
                    db_password = os.environ.get("DB_PASSWORD", "placeholder_password")

                    cnx = mysql.connector.connect(
                        user='admin',
                        password=db_password,  # ソースコードに直書きせず環境変数を使用
                        host='machi-database-2-public.ch0kwscomlmk.us-east-1.rds.amazonaws.com',
                        database='mahjong'
                    )
                    cursor = cnx.cursor()

                    tile_count = len(selected_tiles)
                    placeholders = ",".join(["%s"] * tile_count)

                    query = f"""
WITH cond_cte AS (
  SELECT riichi_id
  FROM discards_summary_all
  WHERE tile IN ({placeholders})
  GROUP BY riichi_id
  HAVING COUNT(DISTINCT tile) = {tile_count}
),
total_cte AS (
  SELECT COUNT(*) AS total_count
  FROM wait_patterns wp
  JOIN cond_cte c ON wp.riichi_id = c.riichi_id
)
SELECT
  wp.waits AS waiting_tile,
  COUNT(*) AS count_wait,
  ROUND(COUNT(*) / total_cte.total_count, 3) AS probability
FROM wait_patterns wp
JOIN cond_cte c ON wp.riichi_id = c.riichi_id
CROSS JOIN total_cte
GROUP BY wp.waits
ORDER BY probability DESC
"""
                    # クエリを実行
                    cursor.execute(query, tuple(selected_tiles))
                    rows = cursor.fetchall()

                    cursor.close()
                    cnx.close()

                    # rows = [(waiting_tile, count_wait, probability), ...]
                    sorted_result = []
                    for (waiting_tile, count_wait, prob) in rows:
                        # 選択された牌は結果から除外
                        if waiting_tile not in selected_tiles:
                            sorted_result.append((waiting_tile, float(prob)))

                except Exception as e:
                    error = f"DBエラーが発生しました: {e}"

    return render_template(
        'index.html',
        sorted_result=sorted_result,
        error=error,
        selected_tiles=selected_tiles
    )


if __name__ == '__main__':
    # ローカル開発時は、事前に下記のように環境変数をセットしておく:
    #   export DB_PASSWORD='*****'
    #   python app.py
    #
    # または configファイル等で設定し、このコードでは os.environ["DB_PASSWORD"] を参照。
    app.run(debug=True, host='0.0.0.0', port=5001)
