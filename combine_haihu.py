#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import datetime
import codecs
from glob import glob
import mysql.connector

###############################################################################
# 1) 赤5変換・和了判定などのロジック
###############################################################################
def convert_red_five(tile: str) -> str:
    """赤5(m0,p0,s0) を通常5(m5,p5,s5)に変換"""
    if len(tile) == 2:
        suit, num = tile[0], tile[1]
        if num == '0' and suit in ('m', 'p', 's'):
            return f"{suit}5"
    return tile

def is_valid_sequence(seq):
    if len(seq) != 3:
        return False
    if any(t.startswith('z') for t in seq):
        return False
    nums = sorted(int(x[1:]) for x in seq)
    return nums[0] + 1 == nums[1] and nums[1] + 1 == nums[2]

def is_valid_triplet(triplet):
    return len(triplet) == 3 and len(set(triplet)) == 1

def is_valid_pair(pair):
    return len(pair) == 2 and pair[0] == pair[1]

def find_combinations(hand, combinations, current=None):
    if current is None:
        current = []
    if not hand:
        combinations.append(current)
        return

    first = hand[0]
    rest = hand[1:]

    # 刻子
    if rest.count(first) >= 2:
        new_rest = rest[:]
        new_rest.remove(first)
        new_rest.remove(first)
        find_combinations(new_rest, combinations, current + [[first] * 3])

    # 順子
    if not first.startswith('z'):
        suit = first[0]
        num = int(first[1:])
        needed = [f"{suit}{num + i}" for i in range(3)]
        new_rest = rest[:]
        valid_seq = True
        for tile in needed[1:]:
            if tile in new_rest:
                new_rest.remove(tile)
            else:
                valid_seq = False
                break
        if valid_seq:
            find_combinations(new_rest, combinations, current + [needed])

    # 対子
    if rest.count(first) >= 1:
        new_rest = rest[:]
        new_rest.remove(first)
        find_combinations(new_rest, combinations, current + [[first] * 2])

    # 何もしない
    find_combinations(rest, combinations, current)

def is_winning_hand(hand14):
    """14枚が和了形(七対子 or 4面子1雀頭)かどうか"""
    if len(hand14) != 14:
        return False

    # 七対子
    unique_tiles = set(hand14)
    if len(unique_tiles) == 7 and all(hand14.count(x) == 2 for x in unique_tiles):
        return True

    # 4面子+雀頭
    sorted_hand = sorted(hand14)
    combos = []
    find_combinations(sorted_hand, combos)
    for c in combos:
        pairs = [g for g in c if is_valid_pair(g)]
        melds = [g for g in c if is_valid_triplet(g) or is_valid_sequence(g)]
        if len(pairs) == 1 and len(melds) == 4:
            return True

    return False

def find_waiting_tiles(hand13):
    """13枚+1で和了になる牌を全列挙"""
    all_tiles = []
    for suit in ('m', 'p', 's'):
        for num in range(1, 10):
            all_tiles.append(f"{suit}{num}")
    for num in range(1, 8):
        all_tiles.append(f"z{num}")

    waits = []
    for t in all_tiles:
        if is_winning_hand(hand13 + [t]):
            waits.append(t)
    return sorted(set(waits))

###############################################################################
# 2) MySQL格納用のメイン処理
###############################################################################

# 入出力パス（JSONファイルが格納されているディレクトリ）
INPUT_DIR = "/Users/hayakawa/Library/Mobile Documents/com~apple~CloudDocs/ma-jan/tenhou_logs"

# グローバル連番
GLOBAL_LOG_ID = 0     # discards テーブル用の連番 (1からインクリメント)
GLOBAL_RIICHI_ID = 0  # 立直宣言ごとに +1
GLOBAL_WAIT_ID = 0    # wait_patterns テーブル用の連番

def process_logfile(filepath):
    """
    ログファイル1個を処理し、discards と wait_patterns 用の行を生成
    """
    try:
        size = os.path.getsize(filepath)
        if size == 0:
            print(f"Skipping empty file (size 0): {filepath}")
            return [], []
        with codecs.open(filepath, "r", "utf-8-sig") as f:
            content = f.read()
            if not content.strip():
                print(f"File content empty after stripping: {filepath}")
                return [], []
            # デバッグ用：読み込んだ内容の先頭100文字を表示
            print(f"DEBUG: {filepath} (size: {size} bytes) first 100 chars: {repr(content[:100])}")
            data = json.loads(content)
    except Exception as e:
        print(f"Error reading {filepath}: {e}")
        return [], []

    logs = data.get("log", [])
    filename = os.path.basename(filepath)

    discards_rows = []
    waits_rows = []

    for round_info in logs:
        if not round_info:
            continue

        qipai = round_info[0].get("qipai") if round_info[0] else None
        if not qipai:
            continue

        init_hands_strs = qipai.get("shoupai", [])
        if len(init_hands_strs) != 4:
            continue

        # 各プレイヤーの手牌(13枚)を構築
        player_hands = []
        for i in range(4):
            tiles = []
            suit = ""
            for ch in init_hands_strs[i]:
                if ch in "mpsz":
                    suit = ch
                else:
                    t = convert_red_five(suit + ch)
                    tiles.append(t)
            player_hands.append(tiles)

        # 立直状態管理
        already_riichi = [False] * 4
        # 立直判定前の捨て牌をバッファ
        player_discard_buffer = [[] for _ in range(4)]

        for action in round_info[1:]:
            if "zimo" in action:
                l = action["zimo"]["l"]
                if not already_riichi[l]:
                    tile = convert_red_five(action["zimo"]["p"])
                    player_hands[l].append(tile)

            elif "dapai" in action:
                l = action["dapai"]["l"]
                if already_riichi[l]:
                    continue

                raw_p = action["dapai"]["p"]
                base_tile = raw_p.rstrip("*_")
                base_tile = convert_red_five(base_tile)

                if base_tile in player_hands[l]:
                    player_hands[l].remove(base_tile)

                star_tile_flag = ("*" in raw_p)
                if star_tile_flag:
                    player_discard_buffer[l].append(base_tile + "*")
                else:
                    player_discard_buffer[l].append(base_tile)

                if star_tile_flag:
                    global GLOBAL_LOG_ID, GLOBAL_RIICHI_ID, GLOBAL_WAIT_ID
                    GLOBAL_RIICHI_ID += 1
                    current_riichi_id = GLOBAL_RIICHI_ID
                    already_riichi[l] = True

                    sorted_hand13 = sorted(player_hands[l])
                    waits = find_waiting_tiles(sorted_hand13)

                    discard_order = 0
                    for i_buf, discard_tile in enumerate(player_discard_buffer[l]):
                        GLOBAL_LOG_ID += 1
                        riichi_tile_flag = (i_buf == len(player_discard_buffer[l]) - 1)
                        discards_rows.append({
                            "log_id": GLOBAL_LOG_ID,
                            "riichi_id": current_riichi_id,
                            "discard_order": discard_order,
                            "tile": discard_tile.rstrip("*"),
                            "riichi_tile": "TRUE" if riichi_tile_flag else "FALSE",
                            "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        })
                        discard_order += 1

                    for w in waits:
                        GLOBAL_WAIT_ID += 1
                        waits_rows.append({
                            "wait_id": GLOBAL_WAIT_ID,
                            "riichi_id": current_riichi_id,
                            "waits": w,
                            "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        })

                    player_discard_buffer[l].clear()

    return discards_rows, waits_rows

def main():
    # グローバル変数初期化
    global GLOBAL_LOG_ID, GLOBAL_RIICHI_ID, GLOBAL_WAIT_ID
    GLOBAL_LOG_ID = 1
    GLOBAL_RIICHI_ID = 0
    GLOBAL_WAIT_ID = 1

    input_files = glob(os.path.join(INPUT_DIR, "*.json"))
    all_discards = []
    all_waits = []

    for fpath in input_files:
        if not os.path.isfile(fpath):
            continue
        discards_rows, waits_rows = process_logfile(fpath)
        all_discards.extend(discards_rows)
        all_waits.extend(waits_rows)

    # MySQL 接続設定（環境に合わせて変更してください）
    db_config = {
        'user': 'machi-database-2-public.ch0kwscomlmk.us-east-1.rds.amazonaws.com',
        'password': 'Fight913',
        'host': 'admin',
        'database': 'mahjong'
    }

    try:
        cnx = mysql.connector.connect(**db_config)
        cursor = cnx.cursor()

        discards_insert_query = (
            "INSERT INTO discards (log_id, riichi_id, discard_order, tile, riichi_tile, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s)"
        )
        wait_patterns_insert_query = (
            "INSERT INTO wait_patterns (wait_id, riichi_id, waits, created_at) "
            "VALUES (%s, %s, %s, %s)"
        )

        discards_data = [
            (row["log_id"], row["riichi_id"], row["discard_order"],
             row["tile"], row["riichi_tile"], row["created_at"])
            for row in all_discards
        ]
        wait_patterns_data = [
            (row["wait_id"], row["riichi_id"], row["waits"], row["created_at"])
            for row in all_waits
        ]

        if discards_data:
            cursor.executemany(discards_insert_query, discards_data)
        if wait_patterns_data:
            cursor.executemany(wait_patterns_insert_query, wait_patterns_data)

        cnx.commit()
        print("MySQL への格納が完了しました")
    except mysql.connector.Error as err:
        print("MySQL error:", err)
    finally:
        if cursor:
            cursor.close()
        if cnx:
            cnx.close()

if __name__ == "__main__":
    main()
