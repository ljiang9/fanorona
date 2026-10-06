#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fanorona.py — Fanorona（马达加斯加棋）极简引擎。

纯 Python 标准库。规则要点（标准 Fanorona 的简化实现）：
- 9x5 棋盘，共 45 个交叉点；斜线只存在于 (行+列) 为偶数的"强点"之间。
- 双方各 22 子，开局摆满除中心点外所有交叉点，白方先走。
- 走子：沿线走一格到空点。
- 吃子二选一：
  - approach（迎击）：走向敌子，吃掉落点前方同一直线上所有连续敌子；
  - withdrawal（撤击）：远离相邻敌子，吃掉起点后方同一直线上所有连续敌子。
- 有吃必吃；多条吃子路线时必须选"全程（含连吃）吃子最多"的一条。
- 连吃：同一子可继续吃子，但一回合内不能落到已走过的点，
  也不能沿与上一次吃子相同的方向继续吃。
- 胜负：吃光对方棋子者胜；轮到走棋但无合法走法者负。
- 限制：三次重复局面判和；400 半回合上限判和（防无限对局）。

本实现为简化版 AI 演示，AI 只是"必吃最长 + 平局随机"的贪心策略。
"""

import argparse
import random
import sys

ROWS, COLS = 5, 9
EMPTY, WHITE, BLACK = 0, 1, 2
GLYPH = {EMPTY: "·", WHITE: "○", BLACK: "●"}
ZH = {WHITE: "白", BLACK: "黑"}

DIRS = [(-1, -1), (-1, 0), (-1, 1),
        (0, -1),           (0, 1),
        (1, -1),  (1, 0),  (1, 1)]

MAX_PLIES = 400          # 半回合上限，撞上限判和
REP_DRAW = 3             # 同一局面出现 3 次判和


def in_bounds(r, c):
    return 0 <= r < ROWS and 0 <= c < COLS


def strong(r, c):
    """强点：(r+c) 为偶数，斜线只经过强点。"""
    return (r + c) % 2 == 0


def foe(player):
    return BLACK if player == WHITE else WHITE


def steps_from(r, c):
    """从 (r,c) 出发所有合法单步：(dr, dc, nr, nc)。"""
    for dr, dc in DIRS:
        nr, nc = r + dr, c + dc
        if not in_bounds(nr, nc):
            continue
        if dr != 0 and dc != 0 and not strong(r, c):
            continue  # 弱点之间没有斜线
        yield dr, dc, nr, nc


def new_board():
    b = [[EMPTY] * COLS for _ in range(ROWS)]
    for c in range(COLS):
        b[0][c] = BLACK
        b[1][c] = BLACK
        b[3][c] = WHITE
        b[4][c] = WHITE
    for c in range(4):
        b[2][c] = BLACK
    for c in range(5, COLS):
        b[2][c] = WHITE
    return b  # b[2][4] 为空（中心点）


def count_line(board, r, c, dr, dc, player):
    """从 (r,c) 起沿 (dr,dc) 方向连续敌子数量。"""
    n = 0
    nr, nc = r + dr, c + dc
    while in_bounds(nr, nc) and board[nr][nc] == foe(player):
        n += 1
        nr += dr
        nc += dc
    return n


def remove_line(board, r, c, dr, dc, player):
    """移除从 (r,c) 起沿 (dr,dc) 的连续敌子，返回移除数。"""
    n = 0
    nr, nc = r + dr, c + dc
    while in_bounds(nr, nc) and board[nr][nc] == foe(player):
        board[nr][nc] = EMPTY
        n += 1
        nr += dr
        nc += dc
    return n


def do_move(board, player, mv):
    """执行走法 mv=(fr,fc,tr,tc,dr,dc,kind,...)，返回 (新棋盘, 本次吃子数)。"""
    fr, fc, tr, tc, dr, dc, kind = mv[:7]
    b = [row[:] for row in board]
    b[fr][fc] = EMPTY
    b[tr][tc] = player
    taken = 0
    if kind == "approach":
        taken = remove_line(b, tr, tc, dr, dc, player)
    elif kind == "withdrawal":
        taken = remove_line(b, fr, fc, -dr, -dc, player)
    return b, taken


def chain_options(board, player, r, c, visited, prev_dir):
    """同子连吃的可选后续走法（不含 total）。"""
    opts = []
    for dr, dc, nr, nc in steps_from(r, c):
        if board[nr][nc] != EMPTY or (nr, nc) in visited:
            continue
        if prev_dir is not None and (dr, dc) == prev_dir:
            continue  # 一回合内不许沿同一方向连吃
        for kind in ("approach", "withdrawal"):
            if kind == "approach":
                n = count_line(board, nr, nc, dr, dc, player)
            else:
                n = count_line(board, r, c, -dr, -dc, player)
            if n:
                opts.append((r, c, nr, nc, dr, dc, kind, n))
    return opts


def max_chain(board, player, r, c, visited, prev_dir):
    """从 (r,c) 出发同子连吃能取得的最大后续吃子总数。"""
    best = 0
    for mv in chain_options(board, player, r, c, visited, prev_dir):
        fr, fc, tr, tc, dr, dc, kind, n = mv
        b2, _ = do_move(board, player, mv)
        rest = max_chain(b2, player, tr, tc, visited | {(tr, tc)}, (dr, dc))
        if n + rest > best:
            best = n + rest
    return best


def gen_moves(board, player):
    """返回 player 的合法走法列表。

    走法元组：(fr,fc,tr,tc,dr,dc,kind,first_n,total)，
    kind ∈ {"approach","withdrawal","paika"}。
    有吃必吃；多条吃法只保留全程吃子总数最多的。
    """
    caps, paikas = [], []
    for r in range(ROWS):
        for c in range(COLS):
            if board[r][c] != player:
                continue
            for dr, dc, nr, nc in steps_from(r, c):
                if board[nr][nc] != EMPTY:
                    continue
                found = False
                for kind in ("approach", "withdrawal"):
                    if kind == "approach":
                        n = count_line(board, nr, nc, dr, dc, player)
                    else:
                        n = count_line(board, r, c, -dr, -dc, player)
                    if n == 0:
                        continue
                    found = True
                    mv = (r, c, nr, nc, dr, dc, kind, n)
                    b2, _ = do_move(board, player, mv)
                    total = n + max_chain(b2, player, nr, nc,
                                          {(r, c), (nr, nc)}, (dr, dc))
                    caps.append(mv + (total,))
                if not found:
                    paikas.append((r, c, nr, nc, dr, dc, "paika", 0, 0))
    if caps:
        m = max(x[8] for x in caps)
        return [x for x in caps if x[8] == m]
    return paikas


def count_pieces(board, player):
    return sum(row.count(player) for row in board)


def board_key(board, player):
    return (tuple(tuple(row) for row in board), player)


def render(board):
    files = " ".join("abcdefghi"[:COLS])
    lines = ["    " + files]
    for r in range(ROWS):
        rank = ROWS - r
        lines.append(f"  {rank} " + " ".join(GLYPH[board[r][c]] for c in range(COLS)))
    return "\n".join(lines)


def parse_coord(s):
    s = s.strip().lower()
    if len(s) != 2 or s[0] not in "abcdefghi" or s[1] not in "12345":
        raise ValueError(f"坐标格式应为 a1..i5：{s!r}")
    c = "abcdefghi".index(s[0])
    r = ROWS - int(s[1])
    return r, c


def fmt_coord(r, c):
    return f"{'abcdefghi'[c]}{ROWS - r}"


class Game:
    def __init__(self, seed=None):
        self.board = new_board()
        self.turn = WHITE  # 白方先走
        self.rng = random.Random(seed)
        self.plies = 0
        self.seen = {}
        self.winner = None   # WHITE / BLACK / "draw" / None
        self.reason = ""

    def _note_position(self):
        key = board_key(self.board, self.turn)
        self.seen[key] = self.seen.get(key, 0) + 1
        return self.seen[key] >= REP_DRAW

    def status(self):
        """返回本局状态：None=继续，WHITE/BLACK=某方胜，"draw"=和棋。"""
        if count_pieces(self.board, WHITE) == 0:
            return BLACK
        if count_pieces(self.board, BLACK) == 0:
            return WHITE
        if not gen_moves(self.board, self.turn):
            return foe(self.turn)  # 无合法走法判负
        if self.plies >= MAX_PLIES:
            return "draw"
        return None

    def ai_choose(self, moves):
        return self.rng.choice(moves)

    def play_move(self, mv, verbose=False):
        """执行一步（含 AI 自动连吃），更新状态。返回本手吃子数。"""
        player = self.turn
        total_taken = 0
        board, taken = do_move(self.board, player, mv)
        total_taken += taken
        self.board = board
        fr, fc, tr, tc, dr, dc, kind = mv[:7]
        if verbose:
            k = {"approach": "迎击", "withdrawal": "撤击", "paika": "走子"}[kind]
            print(f"  {ZH[player]} {fmt_coord(fr, fc)}→{fmt_coord(tr, tc)} {k}，吃 {taken} 子")
        visited = {(fr, fc), (tr, tc)}
        prev_dir = (dr, dc) if kind != "paika" else None
        cr, cc = tr, tc
        # 连吃：AI 自动选后续吃子总数最多的路线
        while kind != "paika":
            opts = chain_options(self.board, player, cr, cc, visited, prev_dir)
            if not opts:
                break
            scored = []
            for om in opts:
                b2, _ = do_move(self.board, player, om)
                rest = max_chain(b2, player, om[2], om[3],
                                 visited | {(om[2], om[3])}, (om[4], om[5]))
                scored.append((om[7] + rest, om))
            scored.sort(key=lambda x: -x[0])
            best_total = scored[0][0]
            best = [om for t, om in scored if t == best_total]
            nxt = self.rng.choice(best)
            board, taken = do_move(self.board, player, nxt)
            total_taken += taken
            self.board = board
            if verbose:
                k = {"approach": "迎击", "withdrawal": "撤击"}[nxt[6]]
                print(f"  {ZH[player]} 连吃 {fmt_coord(nxt[0], nxt[1])}→"
                      f"{fmt_coord(nxt[2], nxt[3])} {k}，吃 {taken} 子")
            visited.add((nxt[2], nxt[3]))
            prev_dir = (nxt[4], nxt[5])
            cr, cc = nxt[2], nxt[3]
            kind = nxt[6]
        self.plies += 1
        self.turn = foe(player)
        return total_taken

    def auto_game(self, verbose=False):
        self._note_position()
        while True:
            st = self.status()
            if st is not None:
                self.winner = st
                if st == "draw":
                    self.reason = "和棋"
                else:
                    loser = foe(st)
                    if count_pieces(self.board, loser) == 0:
                        self.reason = f"{ZH[st]}胜（吃光对方）"
                    else:
                        self.reason = f"{ZH[st]}胜（对方无棋可走）"
                return st
            moves = gen_moves(self.board, self.turn)
            mv = self.ai_choose(moves)
            self.play_move(mv, verbose=verbose)
            if self._note_position():
                self.winner = "draw"
                self.reason = "三次重复局面"
                return "draw"


def fmt_result(w):
    return {"white": "白胜", "black": "黑胜", "draw": "和棋"}[w]


def play_interactive(seed=None):
    g = Game(seed=seed)
    print("Fanorona（马达加斯加棋）：你执白 ○，AI 执黑 ●")
    print("走法输入如：e2 e3 ；同一步有迎击/撤击两种吃法时加后缀 a/w，如 e2 e3 a")
    print("连吃时输入落点继续，或输入 stop 结束本回合。q 退出。")
    g._note_position()
    while True:
        print()
        print(render(g.board))
        st = g.status()
        if st is not None:
            key = {WHITE: "white", BLACK: "black", "draw": "draw"}[st]
            print("对局结束：", fmt_result(key))
            break
        if g.turn == BLACK:
            mv = g.ai_choose(gen_moves(g.board, BLACK))
            g.play_move(mv, verbose=True)
            if g._note_position():
                print("对局结束：和棋（三次重复局面）")
                break
            continue
        moves = gen_moves(g.board, WHITE)
        caps = [m for m in moves if m[6] != "paika"]
        if caps:
            print(f"必须吃子（{len(caps)} 种最长吃法，选其一）：")
            for i, m in enumerate(caps):
                k = {"approach": "迎击", "withdrawal": "撤击"}[m[6]]
                print(f"  {i}: {fmt_coord(m[0], m[1])}→{fmt_coord(m[2], m[3])} {k}（首吃{m[7]}，全程{m[8]}）")
        try:
            s = input(f"[白] 走法序号或坐标 (q 退出)：").strip().lower()
        except EOFError:
            print("\n非终端输入，请用 --auto 看自动演示。")
            return 2
        if s == "q":
            print("已退出。")
            return 0
        mv = None
        if s.isdigit() and int(s) < len(moves):
            mv = moves[int(s)]
        else:
            parts = s.split()
            if len(parts) not in (2, 3):
                print("格式不对，示例：e2 e3 或 e2 e3 a")
                continue
            try:
                fr, fc = parse_coord(parts[0])
                tr, tc = parse_coord(parts[1])
            except ValueError as e:
                print(e)
                continue
            want = parts[2] if len(parts) == 3 else None
            cands = [m for m in moves
                     if (m[0], m[1], m[2], m[3]) == (fr, fc, tr, tc)]
            if want:
                kind = {"a": "approach", "w": "withdrawal"}.get(want)
                cands = [m for m in cands if m[6] == kind]
            if not cands:
                print("非法走法（注意：有吃必吃，且必须选全程吃子最多的路线）。")
                continue
            mv = cands[0]
        # 人类连吃：手动选择
        player = WHITE
        board, taken = do_move(g.board, player, mv)
        g.board = board
        fr, fc, tr, tc, dr, dc, kind = mv[:7]
        k = {"approach": "迎击", "withdrawal": "撤击", "paika": "走子"}[kind]
        print(f"  白 {fmt_coord(fr, fc)}→{fmt_coord(tr, tc)} {k}，吃 {taken} 子")
        visited = {(fr, fc), (tr, tc)}
        prev_dir = (dr, dc) if kind != "paika" else None
        cr, cc = tr, tc
        while kind != "paika":
            opts = chain_options(g.board, player, cr, cc, visited, prev_dir)
            if not opts:
                break
            print("  可连吃：", " ".join(
                f"{fmt_coord(o[2], o[3])}({'迎' if o[6]=='approach' else '撤'}{o[7]})"
                for o in opts), "；输入落点继续或 stop 停")
            try:
                s2 = input("  连吃落点/stop：").strip().lower()
            except EOFError:
                print("\n非终端输入，结束本回合。")
                break
            if s2 == "stop":
                break
            try:
                nr, nc = parse_coord(s2)
            except ValueError as e:
                print(" ", e)
                continue
            cands = [o for o in opts if (o[2], o[3]) == (nr, nc)]
            if not cands:
                print("  该落点不能连吃。")
                continue
            nxt = cands[0]
            board, taken = do_move(g.board, player, nxt)
            g.board = board
            k = {"approach": "迎击", "withdrawal": "撤击"}[nxt[6]]
            print(f"  白连吃 {fmt_coord(nxt[0], nxt[1])}→{fmt_coord(nxt[2], nxt[3])} {k}，吃 {taken} 子")
            visited.add((nxt[2], nxt[3]))
            prev_dir = (nxt[4], nxt[5])
            cr, cc = nxt[2], nxt[3]
            kind = nxt[6]
        g.plies += 1
        g.turn = BLACK
        if g._note_position():
            print("对局结束：和棋（三次重复局面）")
            break
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Fanorona（马达加斯加棋）：迎击/撤击吃子，必吃最长。")
    ap.add_argument("--auto", action="store_true", help="AI 对 AI 自动演示")
    ap.add_argument("--games", type=int, default=10, help="自动演示局数（默认 10）")
    ap.add_argument("--seed", type=int, default=None, help="随机种子")
    ap.add_argument("--verbose", action="store_true", help="自动演示打印每步")
    args = ap.parse_args(argv)

    if not args.auto:
        if not sys.stdin.isatty():
            print("交互模式需要终端；无头演示请用 --auto。", file=sys.stderr)
            return 2
        return play_interactive(seed=args.seed)

    wins = {"white": 0, "black": 0, "draw": 0}
    for i in range(args.games):
        g = Game(seed=None if args.seed is None else args.seed + i)
        w = g.auto_game(verbose=args.verbose)
        key = {WHITE: "white", BLACK: "black", "draw": "draw"}[w]
        wins[key] += 1
        print(f"第 {i + 1}/{args.games} 局：{fmt_result(key)}"
              f"（{g.plies} 半回合，白剩 {count_pieces(g.board, WHITE)}，"
              f"黑剩 {count_pieces(g.board, BLACK)}）")
    print(f"总计：白胜 {wins['white']}，黑胜 {wins['black']}，和棋 {wins['draw']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
