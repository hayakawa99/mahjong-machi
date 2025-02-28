#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import datetime
import codecs
from glob import glob
import mysql.connector

PROGRESS_FILE = "progress.json"   # 進捗を記録するファイル
INPUT_DIR = "/Users/hayakawa/Library/Mobile Documents/com~apple~CloudDocs/ma-jan/tenhou_logs"

CHUNK_SIZE = 5000  # 5000ラウンドごとにDBへINSERT & progress保存

GLOBAL_RIICHI_ID = 0

###############################################################################
# 進捗ファイルの読み書き
###############################################################################
def load_progress():
    """progress.json から進捗を読み込む。無い/空ファイルの場合は空dict"""
    if not os.path.exists(PROGRESS_FILE):
        return {}
    with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
        content = f.read().strip()
        if not content:
            return {}
        return json.loads(content)

def save_progress(progress_dict):
    """進捗dictを progress.json に保存"""
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(progress_dict, f, ensure_ascii=False, indent=2)

###############################################################################
# 赤5変換・和了判定などの既存ロジック
###############################################################################
def convert_red_five(tile: str) -> str:
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
# ファイル1つ分を処理する関数
###############################################################################
def process_logfile(fpath, start_index, total_rounds, progress_dict, cnx, cursor):
    """
    - fpath: JSONファイルパス
    - start_index: 今回の処理開始ラウンド
    - total_rounds: ファイル内ラウンド総数
    - progress_dict: 進捗を更新するdict
    - cnx, cursor: MySQL接続
    """
    global GLOBAL_RIICHI_ID

    # ファイルを開いて logs を読んで、start_index〜total_roundsのラウンドを処理
    try:
        size = os.path.getsize(fpath)
        if size == 0:
            print(f"Skipping empty file (size 0): {fpath}")
            return
        with codecs.open(fpath, "r", "utf-8-sig") as f:
            content = f.read()
            if not content.strip():
                print(f"File content empty after stripping: {fpath}")
                return
            print(f"DEBUG: {fpath} (size: {size} bytes) first 100 chars: {repr(content[:100])}")
            data = json.loads(content)
    except Exception as e:
        print(f"Error reading {fpath}: {e}")
        return

    logs = data.get("log", [])
    if not logs:
        return
    # 念のため logs の長さをチェック
    if len(logs) != total_rounds:
        print(f"Warning: {fpath} logs count changed? expected {total_rounds}, got {len(logs)}")

    discards_insert_query = """
    INSERT INTO discards (
      riichi_id, discard_order, tile, riichi_tile, created_at
    ) VALUES (%s, %s, %s, %s, %s)
    """
    waits_insert_query = """
    INSERT INTO wait_patterns (
      riichi_id, waits, created_at
    ) VALUES (%s, %s, %s)
    """

    discards_buffer = []
    waits_buffer = []

    for i in range(start_index, total_rounds):
        round_info = logs[i]
        if not round_info:
            continue

        qipai = round_info[0].get("qipai") if round_info[0] else None
        if not qipai:
            continue

        init_hands_strs = qipai.get("shoupai", [])
        if len(init_hands_strs) != 4:
            continue

        # 手牌を構築
        player_hands = []
        for j in range(4):
            tiles = []
            suit = ""
            for ch in init_hands_strs[j]:
                if ch in "mpsz":
                    suit = ch
                else:
                    t = convert_red_five(suit + ch)
                    tiles.append(t)
            player_hands.append(tiles)

        already_riichi = [False]*4
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
                    GLOBAL_RIICHI_ID += 1
                    current_riichi_id = GLOBAL_RIICHI_ID
                    already_riichi[l] = True

                    sorted_hand13 = sorted(player_hands[l])
                    waits = find_waiting_tiles(sorted_hand13)

                    discard_order = 0
                    for i_buf, discard_tile in enumerate(player_discard_buffer[l]):
                        discards_buffer.append((
                            current_riichi_id,
                            discard_order,
                            discard_tile.rstrip("*"),
                            "TRUE" if (i_buf == len(player_discard_buffer[l]) - 1) else "FALSE",
                            datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        ))
                        discard_order += 1

                    for w in waits:
                        waits_buffer.append((
                            current_riichi_id,
                            w,
                            datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        ))

                    player_discard_buffer[l].clear()

        # チャンク単位でコミット
        if (i+1) % CHUNK_SIZE == 0:
            if discards_buffer:
                cursor.executemany(discards_insert_query, discards_buffer)
                discards_buffer.clear()
            if waits_buffer:
                cursor.executemany(waits_insert_query, waits_buffer)
                waits_buffer.clear()
            cnx.commit()

            # progress更新
            progress_dict[fpath]["round_index"] = i+1
            progress_dict[fpath]["GLOBAL_RIICHI_ID"] = GLOBAL_RIICHI_ID
            save_progress(progress_dict)
            print(f"Saved progress at round {i+1} for {fpath}.")

    # 残りをINSERT
    if discards_buffer:
        cursor.executemany(discards_insert_query, discards_buffer)
    if waits_buffer:
        cursor.executemany(waits_insert_query, waits_buffer)
    cnx.commit()

    # ファイル完了時に progress を更新
    progress_dict[fpath]["round_index"] = total_rounds
    progress_dict[fpath]["GLOBAL_RIICHI_ID"] = GLOBAL_RIICHI_ID
    save_progress(progress_dict)
    print(f"Completed {fpath} (total rounds={total_rounds}).")

def main():
    global GLOBAL_RIICHI_ID

    progress_dict = load_progress()

    # DB接続
    db_config = {
        'user': 'admin',
        'password': 'Fight913',
        'host': 'machi-database-2-public.ch0kwscomlmk.us-east-1.rds.amazonaws.com',
        'database': 'mahjong'
    }
    cnx = mysql.connector.connect(**db_config)
    cursor = cnx.cursor()

    # ファイル一覧
    input_files = glob(os.path.join(INPUT_DIR, "*.json"))
    for fpath in sorted(input_files):
        info = progress_dict.get(fpath, {})
        done_rounds = info.get("round_index", 0)
        total_rounds = info.get("total_rounds", None)
        GLOBAL_RIICHI_ID = info.get("GLOBAL_RIICHI_ID", GLOBAL_RIICHI_ID)

        # total_rounds が既に分かっていて、かつ done_rounds >= total_rounds => 完了済み => スキップ
        if total_rounds is not None and done_rounds >= total_rounds:
            print(f"Skipping {fpath}, already processed {done_rounds}/{total_rounds} rounds.")
            continue

        # total_rounds がまだわからない場合、1度だけファイルを開いて取得
        if total_rounds is None:
            print(f"Calculating total_rounds for {fpath} ...")
            try:
                with codecs.open(fpath, "r", "utf-8-sig") as f:
                    data = json.load(f)
                logs = data.get("log", [])
                total_rounds = len(logs)
                # progress.json に保存
                progress_dict[fpath] = {
                    "round_index": done_rounds,
                    "total_rounds": total_rounds,
                    "GLOBAL_RIICHI_ID": GLOBAL_RIICHI_ID
                }
                save_progress(progress_dict)
                print(f"{fpath}: total_rounds={total_rounds}")
            except Exception as e:
                print(f"Error reading {fpath} to get total_rounds: {e}")
                continue

            # もし done_rounds >= total_rounds ならスキップ
            if done_rounds >= total_rounds:
                print(f"Skipping {fpath}, progress says done={done_rounds}, total={total_rounds}.")
                continue

        # ここで round_index < total_rounds => 処理を実行
        process_logfile(
            fpath,
            start_index=done_rounds,
            total_rounds=total_rounds,
            progress_dict=progress_dict,
            cnx=cnx,
            cursor=cursor
        )

    cursor.close()
    cnx.close()
    print("All files processed. Exiting.")

if __name__ == "__main__":
    main()
