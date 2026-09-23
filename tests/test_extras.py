"""Run with python -m unittest discover -s tests -p test_extras.py -v."""

import unittest

import pandas as pd
from pandas.testing import assert_frame_equal

from pipeline.extras import compute_extras


def fixture(transfers=(), depths=None, seeds=(), gids=None):
    gids = list(gids) if gids is not None else sorted({x for row in transfers for x in row[:2]})
    depths = depths or {}
    nodes = pd.DataFrame({"gid": pd.Series(gids, dtype="int64"),
                          "depth": [depths.get(g, 1) for g in gids],
                          "is_seed": [g in seeds for g in gids]})
    tx = pd.DataFrame(transfers, columns=["src", "dst", "date", "sum_kzt"])
    edges = tx.groupby(["src", "dst"]).agg(sum_kzt=("sum_kzt", "sum"),
                                           n_tx=("sum_kzt", "size")).reset_index()
    return nodes, edges, tx


class TemporalTests(unittest.TestCase):
    def test_next_day_and_second_day_capacity(self):
        n, e, t = fixture([(1, 2, "2026-07-01", 100), (1, 2, "2026-07-02", 100),
                           (2, 3, "2026-07-03", 160)])
        out, _ = compute_extras(n, e, t)
        middle = out.set_index("gid").loc[2]
        self.assertAlmostEqual(middle.fast_transit_share, .8)
        self.assertTrue(middle.fast_transit)
        self.assertAlmostEqual(middle.transit_observation_complete_share, .5)

    def test_incoming_and_outgoing_not_reused(self):
        for transfers, expected in [
            ([(1, 2, "2026-07-01", 100), (4, 2, "2026-07-01", 100),
              (2, 3, "2026-07-02", 100)], .5),
            ([(1, 2, "2026-07-01", 100), (2, 3, "2026-07-02", 100),
              (2, 4, "2026-07-02", 100)], 1.0),
        ]:
            with self.subTest(transfers=transfers):
                out, _ = compute_extras(*fixture(transfers))
                self.assertAlmostEqual(out.set_index("gid").loc[2].fast_transit_share, expected)

    def test_same_day_order_unknown_and_expired_money(self):
        for outgoing_date, strict, upper in [("2026-07-01", 0, 0),
                                              ("2026-07-02", 0, 1),
                                              ("2026-07-05", 0, 0)]:
            out, _ = compute_extras(*fixture([(1, 2, "2026-07-02", 100),
                                              (2, 3, outgoing_date, 100)]))
            row = out.set_index("gid").loc[2]
            self.assertEqual(row.fast_transit_share, strict)
            self.assertEqual(row.same_day_transit_share_upper_bound, upper)

    def test_fifo_keeps_newer_unexpired_incoming(self):
        out, _ = compute_extras(*fixture([(1, 2, "2026-07-01", 100),
                                          (1, 2, "2026-07-03", 200),
                                          (2, 3, "2026-07-04", 200)]))
        self.assertAlmostEqual(out.set_index("gid").loc[2].fast_transit_share, 2/3)

    def test_terminal_excludes_boundary_seeds_and_isolates(self):
        n, e, t = fixture([(1, 2, "2026-07-01", 100), (1, 3, "2026-07-01", 100),
                           (1, 4, "2026-07-01", 100)], depths={3: 4, 4: 0},
                          seeds=[4, 5], gids=[1, 2, 3, 4, 5, 6])
        out, _ = compute_extras(n, e, t)
        rows = out.set_index("gid")
        self.assertEqual(out.loc[out.likely_true_terminal, "gid"].tolist(), [2])
        self.assertTrue(rows.loc[3].truncated_by_depth)
        self.assertTrue(rows.loc[3].terminal_unknown)
        self.assertTrue(rows.loc[4].terminal_unknown)
        self.assertFalse(rows.loc[6].likely_true_terminal)

    def test_seed_transit_is_not_flagged(self):
        out, _ = compute_extras(*fixture([(1, 2, "2026-07-01", 100),
                                          (2, 3, "2026-07-02", 100)], seeds=[2]))
        row = out.set_index("gid").loc[2]
        self.assertEqual(row.fast_transit_share, 1)
        self.assertFalse(row.fast_transit)
        self.assertTrue(row.transit_seed_caveat)

    def test_sync_counts_distinct_payers_per_calendar_day(self):
        transfers = [(1, 5, "2026-07-01", 10)] * 3
        transfers += [(2, 5, "2026-07-01", 10), (3, 5, "2026-07-01", 10),
                      (1, 5, "2026-07-02", 10), (2, 5, "2026-07-02", 10)]
        out, _ = compute_extras(*fixture(transfers))
        row = out.set_index("gid").loc[5]
        self.assertEqual(row.sync_in_days, 1)
        self.assertEqual(row.sync_max_payers, 3)

    def test_self_transfers_not_counted_as_transit(self):
        out, _ = compute_extras(*fixture([(1, 1, "2026-07-01", 100),
                                          (1, 1, "2026-07-02", 100)]))
        self.assertEqual(out.fast_transit_share.tolist(), [0])

    def test_no_mutation_and_arbitrary_index(self):
        frames = fixture([(1, 2, "2026-07-01", 100)])
        frames[0].index = [20, 10]
        copies = [f.copy(deep=True) for f in frames]
        out, _ = compute_extras(*frames)
        self.assertEqual(out.gid.tolist(), [1, 2])
        for actual, expected in zip(frames, copies):
            assert_frame_equal(actual, expected)

    def test_empty_graph_and_isolates(self):
        for gids in [[], [1, 2]]:
            out, global_ = compute_extras(*fixture(gids=gids))
            self.assertEqual(out.gid.tolist(), gids)
            self.assertIn("cycles", global_)

    def test_bad_input_returns_typed_empty_result_and_warning(self):
        for kind in ["column", "date", "amount", "unknown", "duplicate", "null"]:
            n, e, t = fixture([(1, 2, "2026-07-01", 100)])
            if kind == "column":
                n = n.drop(columns="gid")
            elif kind == "date":
                t.loc[0, "date"] = "not-a-date"
            elif kind == "amount":
                t.loc[0, "sum_kzt"] = -1
            elif kind == "unknown":
                t.loc[0, "dst"] = 99
            elif kind == "duplicate":
                n = pd.concat([n, n])
            else:
                t.loc[0, "date"] = None
            with self.subTest(kind=kind), self.assertLogs("pipeline.extras", level="WARNING"):
                out, global_ = compute_extras(n, e, t)
            self.assertTrue(out.empty)
            self.assertEqual(global_, {})
            self.assertEqual(str(out.gid.dtype), "int64")


if __name__ == "__main__":
    unittest.main()
