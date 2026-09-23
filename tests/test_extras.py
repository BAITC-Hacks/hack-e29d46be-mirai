"""Run with python -m unittest discover -s tests -p test_extras.py -v."""

import unittest
from unittest.mock import patch
import json

import networkx as nx
import pandas as pd
from pandas.testing import assert_frame_equal

from pipeline.extras import compute_extras, _bounded_cycles


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


class NetworkTests(unittest.TestCase):
    def test_directed_cycles_canonical_closed_and_membership(self):
        transfers = [(1, 2, "2026-07-01", 10), (2, 3, "2026-07-01", 10),
                     (3, 1, "2026-07-01", 10), (2, 1, "2026-07-01", 10),
                     (3, 4, "2026-07-01", 10)]
        out, global_ = compute_extras(*fixture(transfers, gids=[1, 2, 3, 4, 5]))
        self.assertEqual(global_["cycles"], [["1", "2", "1"], ["1", "2", "3", "1"]])
        self.assertEqual(out.loc[out.in_cycle, "gid"].tolist(), [1, 2, 3])
        self.assertTrue(global_["cycles_complete"])

    def test_cycle_length_limit(self):
        for length in (1, 2, 5, 6):
            transfers = [(v, (v + 1) % length, "2026-07-01", 10) for v in range(length)]
            out, global_ = compute_extras(*fixture(transfers))
            self.assertEqual(len(global_["cycles"]), int(length <= 5))
            self.assertEqual(int(out.in_cycle.sum()), length if length <= 5 else 0)

    def test_cycles_agree_with_networkx_on_small_graphs(self):
        for seed in range(5):
            graph = nx.gnp_random_graph(8, .3, seed=seed, directed=True)
            actual, complete, _ = _bounded_cycles(graph)
            def canonical(cycle):
                i = cycle.index(min(cycle))
                return tuple(cycle[i:] + cycle[:i])
            expected = {canonical(c) for c in nx.simple_cycles(graph, length_bound=5)}
            self.assertTrue(complete)
            self.assertEqual({tuple(c[:-1]) for c in actual}, expected)

    def test_search_budgets_report_incomplete(self):
        frames = fixture([(1, 2, "2026-07-01", 10), (2, 1, "2026-07-02", 10)])
        with patch("pipeline.extras.MAX_CYCLE_STEPS", 0), self.assertLogs("pipeline.extras"):
            out, global_ = compute_extras(*frames)
        self.assertEqual(len(out), 2)
        self.assertFalse(global_["cycles_complete"])
        self.assertEqual(global_["cycles"], [])

    def test_repeated_route_requires_two_chronological_occurrences(self):
        transfers = [(1, 2, "2026-07-01", 10), (2, 3, "2026-07-02", 8),
                     (1, 2, "2026-07-05", 10), (2, 3, "2026-07-07", 8)]
        out, global_ = compute_extras(*fixture(transfers))
        self.assertEqual(global_["repeated_routes"], [
            {"gids": ["1", "2", "3"], "occurrences": 2, "window_days": 2}])
        self.assertEqual(out.repeated_route_count.tolist(), [1, 1, 1])
        self.assertTrue(global_["repeated_routes_complete"])

    def test_repeated_aggregate_edges_do_not_prove_repeated_route(self):
        for outgoing_dates in [("2026-07-01", "2026-07-01"),
                                ("2026-07-02", "2026-07-08"),
                                ("2026-07-10", "2026-07-11")]:
            transfers = [(1, 2, "2026-07-01", 10), (1, 2, "2026-07-05", 10)]
            transfers += [(2, 3, d, 10) for d in outgoing_dates]
            _, global_ = compute_extras(*fixture(transfers))
            self.assertEqual(global_["repeated_routes"], [])

    def test_route_search_budget(self):
        transfers = [(1, 2, "2026-07-01", 10)] * 2 + [(2, 3, "2026-07-02", 10)] * 2
        with patch("pipeline.extras.MAX_ROUTE_CANDIDATES", 0), self.assertLogs("pipeline.extras"):
            out, global_ = compute_extras(*fixture(transfers))
        self.assertEqual(len(out), 3)
        self.assertFalse(global_["repeated_routes_complete"])

    def test_resilience_priority_and_denominators(self):
        # Removing the centre and 4 leaves leaves 6 disconnected nodes.
        n, e, t = fixture([(0, i, "2026-07-01", 10) for i in range(1, 11)], gids=range(11))
        n["priority_score"] = [1] + [.5] * 10
        _, global_ = compute_extras(n, e, t)
        baseline, top5, top10, top20 = global_["resilience"]
        self.assertEqual(baseline["largest_component_share"], 1)
        self.assertEqual(top5["removed_gids"], ["0", "1", "2", "3", "4"])
        self.assertEqual(top5["ranking_metric"], "priority_score")
        self.assertEqual(top5["n_components"], 6)
        self.assertAlmostEqual(top5["largest_component_share"], 1/6)
        self.assertAlmostEqual(top5["largest_component_original_share"], 1/11)
        self.assertEqual(top5["observed_flow_removed_share"], 1)
        self.assertEqual(top10["remaining_nodes"], 1)
        self.assertEqual(top20["actual_removed_n"], 11)
        self.assertEqual(top20["largest_component_share"], 0)

    def test_isolates_included_and_empty_resilience(self):
        for gids in ([], [1, 2, 3]):
            _, global_ = compute_extras(*fixture(gids=gids))
            baseline = global_["resilience"][0]
            self.assertEqual(baseline["n_components"], len(gids))
            self.assertEqual(baseline["remaining_nodes"], len(gids))

    def test_missing_priority_uses_betweenness_deterministically(self):
        n, e, t = fixture([(1, 2, "2026-07-01", 10), (2, 3, "2026-07-02", 10)])
        n["priority_score"] = [1, float("nan"), .5]
        _, global_ = compute_extras(n, e, t)
        row = global_["resilience"][1]
        self.assertEqual(row["ranking_metric"], "betweenness_exact")
        self.assertEqual(row["removed_gids"][0], "2")
        n["betweenness"] = [1, 0, 0]
        _, global_ = compute_extras(n, e, t)
        self.assertEqual(global_["resilience"][1]["ranking_metric"], "betweenness")
        self.assertEqual(global_["resilience"][1]["removed_gids"][0], "1")

    def test_large_ids_are_exact_in_dataframe_and_strings_in_json(self):
        a, b = 100000004015047101, 100000003684369103
        out, global_ = compute_extras(*fixture([(a, b, "2026-07-01", 10),
                                               (b, a, "2026-07-02", 10)]))
        self.assertEqual(set(out.gid), {a, b})
        self.assertEqual(global_["cycles"], [[str(b), str(a), str(b)]])
        parsed = json.loads(json.dumps(global_, allow_nan=False))
        self.assertEqual(set(parsed["resilience"][1]["removed_gids"]), {str(a), str(b)})

    def test_reordered_input_gives_identical_global_results(self):
        frames = fixture([(1, 2, "2026-07-01", 10), (2, 1, "2026-07-02", 10),
                          (1, 2, "2026-07-03", 10), (2, 3, "2026-07-04", 10)])
        _, first = compute_extras(*frames)
        _, second = compute_extras(*(f.iloc[::-1] for f in frames))
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
