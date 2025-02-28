import json
import os
import urllib.parse
import mysql.connector
import base64

def lambda_handler(event, context):
    print(f"[DEBUG] Full event: {json.dumps(event)}")

    path = event.get("path", "/")
    http_method = event.get("httpMethod", "GET")
    print(f"[DEBUG] path={path}, method={http_method}")

    # 1) 画像配信 /static/tiles/xxx.gif
    if path.startswith("/static/tiles/"):
        filename = path[len("/static/tiles/"):]
        tile_path = f"./tiles/{filename}"  # Lambdaに tiles/ フォルダを同梱

        try:
            with open(tile_path, "rb") as f:
                data = f.read()
            return {
                "statusCode": 200,
                "headers": {"Content-Type": "image/gif"},
                "body": base64.b64encode(data).decode("utf-8"),
                "isBase64Encoded": True
            }
        except FileNotFoundError:
            return {
                "statusCode": 404,
                "body": "Not Found"
            }

    # 2) GET / => 初回表示 (フォームのみ)
    if path == "/" and http_method == "GET":
        print("[DEBUG] GET request - returning initial HTML page")
        html_content = build_html_page(selected_tiles=None, sorted_result=None)
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "text/html; charset=utf-8"},
            "body": html_content
        }

    # 3) POST / => ユーザーが選択した牌を受け取り、discard_orderで順番チェック → 待ち確率表示
    if path == "/" and http_method == "POST":
        body_str = event.get("body", "")
        # ALB経由でBase64エンコードされている場合 decode
        if event.get("isBase64Encoded", False):
            body_str = base64.b64decode(body_str).decode("utf-8")

        print(f"[DEBUG] Decoded POST body: {body_str}")

        form_data = urllib.parse.parse_qs(body_str)
        selected_tiles_str = form_data.get("selected_tiles", [""])[0]
        selected_tiles = [t for t in selected_tiles_str.split(",") if t]
        print("[DEBUG] selected_tiles:", selected_tiles)

        # 牌の種類数を取得
        unique_tiles = set(selected_tiles)
        num_types = len(unique_tiles)
        num_selected = len(selected_tiles)

        # 2～5種類以外は空表示
        if num_types < 2 or num_types > 5:
            print(f"[DEBUG] num_types={num_types} => out of range (2-5)")
            html_content = build_html_page(selected_tiles=selected_tiles, sorted_result=[])
            return {
                "statusCode": 200,
                "headers": {"Content-Type": "text/html; charset=utf-8"},
                "body": html_content
            }

        try:
            print("[DEBUG] Connecting to DB ...")
            db_password = os.environ.get("DB_PASSWORD", "")
            cnx = mysql.connector.connect(
                user='admin',
                password=db_password,
                host='machi-database-2-public.ch0kwscomlmk.us-east-1.rds.amazonaws.com',
                database='mahjong'
            )
            cursor = cnx.cursor()

            # --- 1) 選択牌順に捨てられているリーチIDを抽出 (動的SQL) ---
            join_clauses = []
            alias_first = "d1"
            # 先頭
            join_clauses.append(
                f"{alias_first} AS (SELECT riichi_id, discard_order FROM discards WHERE tile = %s)"
            )

            # 2枚目以降
            for i in range(2, len(selected_tiles) + 1):
                alias_current = f"d{i}"
                alias_prev = f"d{i-1}"
                join_clauses.append(f"""
{alias_current} AS (
  SELECT d.riichi_id, d.discard_order
  FROM discards d
  JOIN {alias_prev}
    ON d.riichi_id = {alias_prev}.riichi_id
   AND d.discard_order > {alias_prev}.discard_order
  WHERE d.tile = %s
)
""".strip())

            cte_list = ",\n".join(join_clauses)
            final_alias = f"d{len(selected_tiles)}"
            placeholders = tuple(selected_tiles)  # N個ぶん

            cte_query = f"""
WITH
{cte_list}
SELECT {final_alias}.riichi_id
FROM {final_alias}
GROUP BY {final_alias}.riichi_id
"""
            print("[DEBUG] cte_query:\n", cte_query)

            cursor.execute(cte_query, placeholders)
            matching_riichi = cursor.fetchall()
            print("[DEBUG] matching_riichi count:", len(matching_riichi))

            if len(matching_riichi) == 0:
                # ヒット無し
                html_content = build_html_page(selected_tiles, sorted_result=[])
                cursor.close()
                cnx.close()
                return {
                    "statusCode": 200,
                    "headers": {"Content-Type": "text/html; charset=utf-8"},
                    "body": html_content
                }

            # --- 2) wait_patterns で待ち候補を集計 ---
            matching_ids = [row[0] for row in matching_riichi]
            in_placeholders = ",".join(["%s"] * len(matching_ids))

            wait_query = f"""
WITH total_cte AS (
  SELECT COUNT(*) AS total_count
  FROM wait_patterns
  WHERE riichi_id IN ({in_placeholders})
)
SELECT
  wp.waits AS waiting_tile,
  COUNT(*) AS count_wait,
  ROUND(COUNT(*) / total_cte.total_count, 3) AS probability
FROM wait_patterns wp
CROSS JOIN total_cte
WHERE wp.riichi_id IN ({in_placeholders})
GROUP BY wp.waits
ORDER BY probability DESC
"""
            wait_params = tuple(matching_ids) + tuple(matching_ids)
            print("[DEBUG] wait_query:\n", wait_query)

            cursor.execute(wait_query, wait_params)
            wait_rows = cursor.fetchall()
            print("[DEBUG] wait_rows length:", len(wait_rows))

            cursor.close()
            cnx.close()

            # 3) 選択牌を除外
            sorted_result = []
            for (waiting_tile, count_wait, prob) in wait_rows:
                if waiting_tile not in selected_tiles:
                    sorted_result.append((waiting_tile, float(prob)))

            print("[DEBUG] final sorted_result:", sorted_result)

            # HTML返却
            html_content = build_html_page(
                selected_tiles=selected_tiles,
                sorted_result=sorted_result
            )
            return {
                "statusCode": 200,
                "headers": {"Content-Type": "text/html; charset=utf-8"},
                "body": html_content
            }

        except Exception as e:
            print("[ERROR]", e)
            html_content = build_html_page(selected_tiles=None, sorted_result=[], error_msg=str(e))
            return {
                "statusCode": 200,
                "headers": {"Content-Type": "text/html; charset=utf-8"},
                "body": html_content
            }

    # 4) その他 => 404
    print("[DEBUG] 404 - No matching route")
    return {
        "statusCode": 404,
        "headers": {"Content-Type": "text/plain; charset=utf-8"},
        "body": "Not Found"
    }

def build_html_page(selected_tiles, sorted_result, error_msg=None):
    """
    HTMLを動的に生成。
      selected_tiles, sorted_result があれば下部に表示。
      error_msg があればエラー表示。
    """

    # フォーム説明: (2種以上選択, 最大5個), +10秒かかる文言を追加
    form_html = """<p>待ちを推測したい立直者の捨て牌を選択してください（2種以上選択,最大5個）<br>*10秒ほど時間がかかります</p>
<div class="tile-group">
  <button type="button" class="tile" data-value="m1"><img src="/static/tiles/m1.gif"></button>
  <button type="button" class="tile" data-value="m2"><img src="/static/tiles/m2.gif"></button>
  <button type="button" class="tile" data-value="m3"><img src="/static/tiles/m3.gif"></button>
  <button type="button" class="tile" data-value="m4"><img src="/static/tiles/m4.gif"></button>
  <button type="button" class="tile" data-value="m5"><img src="/static/tiles/m5.gif"></button>
  <button type="button" class="tile" data-value="m6"><img src="/static/tiles/m6.gif"></button>
  <button type="button" class="tile" data-value="m7"><img src="/static/tiles/m7.gif"></button>
  <button type="button" class="tile" data-value="m8"><img src="/static/tiles/m8.gif"></button>
  <button type="button" class="tile" data-value="m9"><img src="/static/tiles/m9.gif"></button>
</div>
<div class="tile-group">
  <button type="button" class="tile" data-value="s1"><img src="/static/tiles/s1.gif"></button>
  <button type="button" class="tile" data-value="s2"><img src="/static/tiles/s2.gif"></button>
  <button type="button" class="tile" data-value="s3"><img src="/static/tiles/s3.gif"></button>
  <button type="button" class="tile" data-value="s4"><img src="/static/tiles/s4.gif"></button>
  <button type="button" class="tile" data-value="s5"><img src="/static/tiles/s5.gif"></button>
  <button type="button" class="tile" data-value="s6"><img src="/static/tiles/s6.gif"></button>
  <button type="button" class="tile" data-value="s7"><img src="/static/tiles/s7.gif"></button>
  <button type="button" class="tile" data-value="s8"><img src="/static/tiles/s8.gif"></button>
  <button type="button" class="tile" data-value="s9"><img src="/static/tiles/s9.gif"></button>
</div>
<div class="tile-group">
  <button type="button" class="tile" data-value="p1"><img src="/static/tiles/p1.gif"></button>
  <button type="button" class="tile" data-value="p2"><img src="/static/tiles/p2.gif"></button>
  <button type="button" class="tile" data-value="p3"><img src="/static/tiles/p3.gif"></button>
  <button type="button" class="tile" data-value="p4"><img src="/static/tiles/p4.gif"></button>
  <button type="button" class="tile" data-value="p5"><img src="/static/tiles/p5.gif"></button>
  <button type="button" class="tile" data-value="p6"><img src="/static/tiles/p6.gif"></button>
  <button type="button" class="tile" data-value="p7"><img src="/static/tiles/p7.gif"></button>
  <button type="button" class="tile" data-value="p8"><img src="/static/tiles/p8.gif"></button>
  <button type="button" class="tile" data-value="p9"><img src="/static/tiles/p9.gif"></button>
</div>
<div class="tile-group">
  <button type="button" class="tile" data-value="z1"><img src="/static/tiles/z1.gif"></button>
  <button type="button" class="tile" data-value="z2"><img src="/static/tiles/z2.gif"></button>
  <button type="button" class="tile" data-value="z3"><img src="/static/tiles/z3.gif"></button>
  <button type="button" class="tile" data-value="z4"><img src="/static/tiles/z4.gif"></button>
  <button type="button" class="tile" data-value="z5"><img src="/static/tiles/z5.gif"></button>
  <button type="button" class="tile" data-value="z6"><img src="/static/tiles/z6.gif"></button>
  <button type="button" class="tile" data-value="z7"><img src="/static/tiles/z7.gif"></button>
</div>
<input type="hidden" name="selected_tiles" id="selected_tiles">
<div id="selection_display">選択順: (まだ何も選択していません)</div>
<br>
<input type="submit" id="submit_button" value="決定" disabled>"""

    error_html = ""
    if error_msg:
        error_html = f'<div class="error">エラー: {error_msg}</div>'

    selected_html = ""
    if selected_tiles:
        tile_imgs = ""
        for tile in selected_tiles:
            tile_imgs += f'<div class="pattern-box"><img src="/static/tiles/{tile}.gif" alt="{tile}"></div>'
        selected_html = f"""
<h2 style="text-align: center;">あなたが選択した牌</h2>
<div class="pattern-container">
  {tile_imgs}
</div>
"""

    result_html = ""
    if sorted_result is not None:
        if len(sorted_result) > 0:
            wait_imgs = ""
            for (tile, prob) in sorted_result:
                wait_imgs += f"""
<div class="pattern-box">
  <img src="/static/tiles/{tile}.gif" alt="{tile}">
  <div>{prob*100:.1f}%</div>
</div>
"""
            result_html = f"""
<h2 style="text-align: center;">待ちになっている確率 (高い順)</h2>
<div class="pattern-container">
  {wait_imgs}
</div>
"""
        else:
            result_html = """<div class="no-result" style="text-align:center; margin-top:20px;">
<p>一致するデータがありません。</p>
</div>"""

    html_page = f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <title>麻雀待ち予測ツール</title>
  <style>
    body {{
      font-family: sans-serif;
      margin: 20px;
      background: #f5f7fa;
      color: #333;
    }}
    h1 {{
      text-align: center;
      margin-bottom: 30px;
      font-weight: 500;
      color: #444;
    }}
    form {{
      max-width: 800px;
      margin: 0 auto;
      background: #fff;
      padding: 20px;
      border: 1px solid #ddd;
      border-radius: 8px;
    }}
    p {{
      text-align: center;
      font-size: 1.1rem;
      margin-bottom: 20px;
    }}
    .tile-group {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      margin-bottom: 5px;
    }}
    .tile {{
      margin: 3px;
      padding: 3px;
      cursor: pointer;
      border: 1px solid #ccc;
      border-radius: 4px;
      background-color: #fff;
      transition: background-color 0.2s ease, box-shadow 0.2s ease;
    }}
    .tile:hover {{
      background-color: #e9f0f7;
      box-shadow: 0 2px 5px rgba(0,0,0,0.15);
    }}
    .tile img {{
      display: block;
      width: 50px;
      height: auto;
    }}
    #selection_display {{
      margin-top: 15px;
      font-weight: bold;
      text-align: center;
      font-size: 1.1rem;
    }}
    input[type="submit"] {{
      display: block;
      margin: 20px auto 0 auto;
      padding: 8px 16px;
      background-color: #4285f4;
      color: #fff;
      border: none;
      border-radius: 4px;
      cursor: pointer;
      font-size: 1rem;
      transition: background-color 0.2s ease;
    }}
    input[type="submit"]:hover:enabled {{
      background-color: #357ae8;
    }}
    input[type="submit"]:disabled {{
      background-color: #aaa;
      cursor: not-allowed;
    }}
    .pattern-container {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: center;
    }}
    .pattern-box {{
      background: #fff;
      margin: 5px;
      padding: 5px;
      border: 1px solid #ddd;
      border-radius: 8px;
      box-shadow: 0 2px 5px rgba(0,0,0,0.1);
      text-align: center;
      width: 60px;
    }}
    .pattern-box img {{
      display: block;
      margin: 0 auto 5px;
      width: 50px;
      height: auto;
    }}
    .error {{
      text-align: center;
      color: #d93025;
      font-weight: bold;
      margin-top: 20px;
    }}
    .no-result p {{
      color: #444;
      font-size: 1.2rem;
      font-weight: bold;
    }}
  </style>
</head>
<body>
  <h1>麻雀待ち予測ツール</h1>
  <form method="post" action="/">
    {form_html}
  </form>
  {error_html}
  {selected_html}
  {result_html}
  <script>
    let selectedTiles = [];
    const submitButton = document.getElementById('submit_button');

    function updateSelectionDisplay() {{
      const displayElem = document.getElementById('selection_display');
      const hiddenInput = document.getElementById('selected_tiles');

      if (selectedTiles.length === 0) {{
        displayElem.textContent = "選択順: (まだ何も選択していません)";
        hiddenInput.value = "";
      }} else {{
        let html = "選択順: ";
        selectedTiles.forEach(tile => {{
          html += `<img src="/static/tiles/${{tile}}.gif" alt="${{tile}}" style="width:40px; height:auto; margin-right:4px;">`;
        }});
        displayElem.innerHTML = html;
        hiddenInput.value = selectedTiles.join(',');
      }}

      // 2種類以上(= unique tileが2つ以上)か判定
      let uniqueSet = new Set(selectedTiles);
      const numTypes = uniqueSet.size;

      // 2 <= numTypes <= 5 かつ
      // 合計何枚選んだか…は今回は最大枚数5 "種類" としているので
      // もし「5枚を超えて同じ牌もカウント」するなら別ロジック要
      // ここでは要求にある「6個以上の牌を選択するとNG」も確認
      const totalSelected = selectedTiles.length;

      // 2 <= numTypes <= 5 かつ totalSelected <= 5
      if (numTypes >= 2 && numTypes <= 5 && totalSelected <= 5) {{
        submitButton.disabled = false;
      }} else {{
        submitButton.disabled = true;
      }}
    }}

    // タイルクリックで追加
    document.querySelectorAll('.tile').forEach(button => {{
      button.addEventListener('click', function() {{
        let tile = this.getAttribute('data-value');
        selectedTiles.push(tile);
        updateSelectionDisplay();
      }});
    }});
  </script>
</body>
</html>
"""
    return html_page
