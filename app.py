from flask import Flask, render_template, request

app = Flask(__name__)

@app.route('/', methods=['GET', 'POST'])
def index():
    sorted_result = None
    error = None

    if request.method == 'POST':
        selected_string = request.form.get('selected_tiles', '')
        
        if not selected_string:
            error = "牌が選択されていません"
        else:
            selected_tiles = [s for s in selected_string.split(',') if s]
            if not selected_tiles:
                error = "牌が選択されていません"
            else:
                # ダミーの待ち牌結果を生成
                # 牌コードはマンズ(m1～m9)、索子(s1～s9)、筒子(p1～p9)、字牌(z1～z7)
                tile_codes = (
                    [f"m{i}" for i in range(1,10)] +
                    [f"s{i}" for i in range(1,10)] +
                    [f"p{i}" for i in range(1,10)] +
                    [f"z{i}" for i in range(1,8)]
                )
                # ここでは、単純に上位になるほど確率が高いと仮定
                result = {}
                for index, tile in enumerate(tile_codes):
                    # 確率を (34-index)/100 として、例えば最初のtileが0.34, 最後が0.01
                    result[tile] = round((len(tile_codes) - index) / 100.0, 2)
                # 降順にソート
                sorted_result = sorted(result.items(), key=lambda x: x[1], reverse=True)
    
    return render_template('index.html', sorted_result=sorted_result, error=error)

if __name__ == '__main__':
    app.run(debug=True)
